from __future__ import annotations

import json
from unittest.mock import patch

from bible_cli.exceptions import COMMAND_NOT_IMPLEMENTED_EXIT_CODE
from bible_cli.python_cli import build_parser, main


def test_parser_exposes_phase1_command_tree() -> None:
    parser = build_parser()
    help_text = parser.format_help()

    assert "health" in help_text
    assert "system" in help_text
    assert "knowledge" in help_text
    assert "memory" in help_text
    assert "skills" in help_text


def test_system_parser_exposes_info_action() -> None:
    parser = build_parser()
    system_action_choices: dict[str, object] = {}
    for action in parser._actions:  # noqa: SLF001
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and "system" in choices:
            system_parser = choices["system"]
            for system_action in system_parser._actions:  # noqa: SLF001
                sub_choices = getattr(system_action, "choices", None)
                if isinstance(sub_choices, dict):
                    system_action_choices = sub_choices
                    break
            break

    assert "status" in system_action_choices
    assert "info" in system_action_choices


def test_knowledge_parser_exposes_list_and_search_actions() -> None:
    parser = build_parser()
    knowledge_action_choices: dict[str, object] = {}
    for action in parser._actions:  # noqa: SLF001
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and "knowledge" in choices:
            knowledge_parser = choices["knowledge"]
            for knowledge_action in knowledge_parser._actions:  # noqa: SLF001
                sub_choices = getattr(knowledge_action, "choices", None)
                if isinstance(sub_choices, dict):
                    knowledge_action_choices = sub_choices
                    break
            break

    assert "list" in knowledge_action_choices
    assert "search" in knowledge_action_choices


def test_main_without_args_prints_help(capsys) -> None:
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage: bs" in captured.out


def test_system_status_command_calls_client(capsys) -> None:
    with patch("bible_cli.commands.handlers.SyncHTTPClient.status", return_value={"status": "ok"}):
        exit_code = main(["system", "status"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == {"status": "ok"}


def test_top_level_health_command_calls_client(capsys) -> None:
    with patch("bible_cli.commands.handlers.SyncHTTPClient.health", return_value={"status": "ok"}):
        exit_code = main(["health"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == {"status": "ok"}


def test_system_info_command_calls_client(capsys) -> None:
    payload = {"version": "0.0.1", "description": "BiBLE-Atlas: Agent-native context DB"}
    with patch("bible_cli.commands.handlers.SyncHTTPClient.info", return_value=payload):
        exit_code = main(["system", "info"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == payload


def test_knowledge_list_command_calls_client(capsys) -> None:
    payload = {"items": []}
    with patch("bible_cli.commands.handlers.SyncHTTPClient.knowledge_list", return_value=payload):
        exit_code = main(["knowledge", "list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == payload


def test_knowledge_search_command_calls_client(capsys) -> None:
    payload = {"items": [], "query": "faith"}
    with patch("bible_cli.commands.handlers.SyncHTTPClient.knowledge_search", return_value=payload):
        exit_code = main(["knowledge", "search", "faith"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == payload


def test_unimplemented_command_has_stable_exit_code(capsys) -> None:
    exit_code = main(["memory", "show"])
    captured = capsys.readouterr()

    assert exit_code == COMMAND_NOT_IMPLEMENTED_EXIT_CODE
    assert "CLI_NOT_IMPLEMENTED" in captured.err
    assert "memory show" in captured.err
