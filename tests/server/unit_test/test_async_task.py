"""
Tests for the async-task state machine and dispatch_task cancel guard.

Covers:
1. AsyncTaskRepository.create → always sets "queued"
2. Valid transitions: queued→running, queued→cancelled, running→completed, running→failed
3. Terminal-state protection: completed/failed/cancelled → any further write is silently ignored
4. Invalid non-terminal transition (e.g. queued→completed) is ignored with a warning
5. dispatch_task skips execution when task is already "cancelled"
6. AsyncTaskService.cancel only cancels queued tasks; running tasks receive a revoke signal
7. dispatch_task marks the task as "failed" when SoftTimeLimitExceeded is raised
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from bible.features.async_task.dispatcher import AsyncTaskDispatcher
from bible.features.async_task.repository import AsyncTaskRepository
from bible.features.async_task.service import AsyncTaskService
from bible.features.async_task.tasks.dispatch_task import configure_dispatch, dispatch_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo() -> AsyncTaskRepository:
    return AsyncTaskRepository()


def _create(repo: AsyncTaskRepository, task_id: str = "t1") -> None:
    repo.create(task_id=task_id, task_type="import.memory", payload={})


def _make_service(repo: AsyncTaskRepository | None = None) -> AsyncTaskService:
    return AsyncTaskService(repository=repo or _make_repo())


# ---------------------------------------------------------------------------
# 1. AsyncTaskRepository.create
# ---------------------------------------------------------------------------

class TestAsyncTaskRepositoryCreate:
    def test_create_sets_queued_status(self):
        repo = _make_repo()
        task = repo.create("t1", "import.memory", {})
        assert task.status == "queued"

    def test_create_stores_task_and_get_returns_it(self):
        repo = _make_repo()
        repo.create("t2", "import.memory", {"k": "v"})
        task = repo.get("t2")
        assert task is not None
        assert task.task_id == "t2"
        assert task.payload == {"k": "v"}

    def test_get_nonexistent_returns_none(self):
        repo = _make_repo()
        assert repo.get("nope") is None


# ---------------------------------------------------------------------------
# 2. Valid state transitions
# ---------------------------------------------------------------------------

class TestValidStateTransitions:
    def test_queued_to_running(self):
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "running")
        assert repo.get("t1").status == "running"

    def test_queued_to_cancelled(self):
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "cancelled")
        assert repo.get("t1").status == "cancelled"

    def test_running_to_completed(self):
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "running")
        repo.update_status("t1", "completed", result={"ok": True})
        task = repo.get("t1")
        assert task.status == "completed"
        assert task.result == {"ok": True}

    def test_running_to_failed(self):
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "running")
        repo.update_status("t1", "failed", error="boom")
        task = repo.get("t1")
        assert task.status == "failed"
        assert task.error == "boom"

    def test_update_status_raises_key_error_for_unknown_task(self):
        repo = _make_repo()
        with pytest.raises(KeyError):
            repo.update_status("ghost", "running")


# ---------------------------------------------------------------------------
# 3. Terminal-state protection
# ---------------------------------------------------------------------------

class TestTerminalStateProtection:
    @pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
    def test_terminal_state_cannot_transition_to_running(self, terminal):
        repo = _make_repo()
        _create(repo)
        if terminal != "cancelled":
            repo.update_status("t1", "running")
        repo.update_status("t1", terminal)
        # Try to overwrite with running — must be ignored
        repo.update_status("t1", "running")
        assert repo.get("t1").status == terminal

    def test_completed_cannot_be_overwritten_by_failed(self):
        """Race between task completion and a timeout — second write must be ignored."""
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "running")
        repo.update_status("t1", "completed", result={"ok": True})
        repo.update_status("t1", "failed", error="timeout")  # must be ignored
        task = repo.get("t1")
        assert task.status == "completed"
        assert task.error is None  # error not written

    def test_failed_cannot_be_overwritten_by_completed(self):
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "running")
        repo.update_status("t1", "failed", error="oops")
        repo.update_status("t1", "completed")  # ignored
        assert repo.get("t1").status == "failed"

    def test_cancelled_cannot_be_overwritten_by_running(self):
        """cancel() races with dispatch_task — running must not overwrite cancelled."""
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "cancelled")
        repo.update_status("t1", "running")  # must be ignored
        assert repo.get("t1").status == "cancelled"


# ---------------------------------------------------------------------------
# 4. Invalid non-terminal transitions
# ---------------------------------------------------------------------------

class TestInvalidNonTerminalTransitions:
    def test_queued_cannot_jump_to_completed(self):
        """queued → completed is not a valid edge; should be ignored."""
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "completed")  # skips "running" — invalid
        assert repo.get("t1").status == "queued"

    def test_queued_cannot_jump_to_failed(self):
        repo = _make_repo()
        _create(repo)
        repo.update_status("t1", "failed")
        assert repo.get("t1").status == "queued"


# ---------------------------------------------------------------------------
# 5. dispatch_task cancel guard
# ---------------------------------------------------------------------------

class TestDispatchTaskCancelGuard:
    def setup_method(self):
        """Fresh repository + dispatch for each test."""
        self._repo = _make_repo()
        self._dispatcher = AsyncTaskDispatcher()
        self._executor = MagicMock()
        self._executor.execute.return_value = {"ok": True}
        self._dispatcher.register("import.memory", self._executor)
        configure_dispatch(repository=self._repo, dispatcher=self._dispatcher)

    def teardown_method(self):
        import bible.features.async_task.tasks.dispatch_task as m
        m._repository = None
        m._dispatcher = None

    def test_cancelled_task_is_not_executed(self):
        """If task is cancelled before dispatch_task runs, executor must not be called."""
        self._repo.create("t1", "import.memory", {})
        self._repo.update_status("t1", "cancelled")

        dispatch_task("t1", "import.memory", {})

        self._executor.execute.assert_not_called()
        assert self._repo.get("t1").status == "cancelled"

    def test_queued_task_is_executed_and_completed(self):
        self._repo.create("t1", "import.memory", {})
        dispatch_task("t1", "import.memory", {})
        self._executor.execute.assert_called_once()
        assert self._repo.get("t1").status == "completed"

    def test_registered_task_type_from_another_domain_is_executed(self):
        skill_executor = MagicMock()
        skill_executor.execute.return_value = {"skill": "ok"}
        self._dispatcher.register("import.skill", skill_executor)
        self._repo.create("t1", "import.skill", {})

        dispatch_task("t1", "import.skill", {})

        skill_executor.execute.assert_called_once_with("t1", "import.skill", {})
        assert self._repo.get("t1").result == {"skill": "ok"}

    def test_task_set_to_running_before_execute(self):
        """dispatch_task must transition to 'running' before calling executor."""
        call_order: list[str] = []

        def record_status_then_execute(*args: Any, **kwargs: Any) -> dict[str, Any]:
            call_order.append(self._repo.get("t1").status)
            return {"ok": True}

        self._executor.execute.side_effect = record_status_then_execute
        self._repo.create("t1", "import.memory", {})
        dispatch_task("t1", "import.memory", {})

        assert call_order == ["running"]

    def test_executor_exception_sets_status_to_failed(self):
        from bible.common.errors import DomainError, ErrorCode
        self._executor.execute.side_effect = DomainError(ErrorCode.INTERNAL, "crash")
        self._repo.create("t1", "import.memory", {})
        dispatch_task("t1", "import.memory", {})
        assert self._repo.get("t1").status == "failed"

    def test_soft_time_limit_sets_status_to_failed_with_timeout_message(self):
        """SoftTimeLimitExceeded from Celery marks the task as failed with a timeout error."""
        self._executor.execute.side_effect = SoftTimeLimitExceeded()
        self._repo.create("t1", "import.memory", {})
        dispatch_task("t1", "import.memory", {})
        task = self._repo.get("t1")
        assert task.status == "failed"
        assert "timeout" in (task.error or "").lower()


# ---------------------------------------------------------------------------
# 6. AsyncTaskService.cancel
# ---------------------------------------------------------------------------

class TestAsyncTaskServiceCancel:
    def test_cancel_queued_task_sets_cancelled(self):
        repo = _make_repo()
        svc = _make_service(repo)
        with patch("bible.features.async_task.tasks.dispatch_task.dispatch_task.apply_async"):
            svc.submit("import.memory", {}, idempotency_key="t1")
        with patch("bible.features.async_task.service.celery_app") as mock_app:
            result = svc.cancel("t1")
        mock_app.control.revoke.assert_called_once_with("t1")
        assert result["status"] == "cancelled"

    def test_cancel_unknown_task_raises_key_error(self):
        svc = _make_service()
        with pytest.raises(KeyError):
            svc.cancel("nope")

    def test_cancel_running_task_sends_revoke_and_returns_running(self):
        """Running tasks receive a SIGTERM revoke; status stays 'running' until the worker updates it."""
        repo = _make_repo()
        svc = _make_service(repo)
        repo.create("t1", "import.memory", {})
        repo.update_status("t1", "running")

        with patch("bible.features.async_task.service.celery_app") as mock_app:
            result = svc.cancel("t1")

        mock_app.control.revoke.assert_called_once_with("t1", terminate=True, signal="SIGTERM")
        assert result["status"] == "running"

    def test_submit_enqueues_celery_task(self):
        """submit() must call apply_async rather than starting a thread."""
        repo = _make_repo()
        svc = _make_service(repo)
        with patch(
            "bible.features.async_task.tasks.dispatch_task.dispatch_task.apply_async"
        ) as mock_apply:
            result = svc.submit("import.memory", {"x": 1}, idempotency_key="t99")

        mock_apply.assert_called_once()
        call_kwargs = mock_apply.call_args
        assert call_kwargs.kwargs.get("task_id") == "t99" or "t99" in str(call_kwargs)
        assert result["status"] == "queued"

    def test_submit_sets_soft_time_limit_when_timeout_configured(self):
        repo = _make_repo()
        svc = AsyncTaskService(repository=repo, task_timeout_seconds=120)
        with patch(
            "bible.features.async_task.tasks.dispatch_task.dispatch_task.apply_async"
        ) as mock_apply:
            svc.submit("import.memory", {}, idempotency_key="t1")

        _, kwargs = mock_apply.call_args
        assert kwargs.get("soft_time_limit") == 120
