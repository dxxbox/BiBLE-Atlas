import pytest

from bible.common.errors import (
    ErrorCode,
    InvalidArgumentError,
    http_status_for_error,
    is_retryable_error,
)
from bible.common.schemas import ErrorInfo, MetaInfo, BibleResponse, ResponseStatus


def test_response_envelope_success_contract():
    envelope = BibleResponse.success(result={"ok": True}, meta=MetaInfo(request_id="req_1", cost_ms=5))

    assert envelope.status == ResponseStatus.OK
    assert envelope.result == {"ok": True}
    assert envelope.error is None
    assert envelope.meta is not None
    assert envelope.meta.request_id == "req_1"


def test_response_envelope_error_contract():
    error = ErrorInfo(code=ErrorCode.INVALID_ARGUMENT.value, message="invalid input", retryable=False)
    envelope = BibleResponse.failure(error=error)

    assert envelope.status == ResponseStatus.ERROR
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.INVALID_ARGUMENT.value
    assert envelope.result is None


def test_response_envelope_error_requires_error_payload():
    with pytest.raises(ValueError, match="error is required"):
        BibleResponse(status=ResponseStatus.ERROR, result=None, error=None)


def test_error_code_http_mapping_and_retryable():
    assert http_status_for_error(ErrorCode.RESOURCE_EXHAUSTED) == 429
    assert is_retryable_error(ErrorCode.RESOURCE_EXHAUSTED) is True
    assert http_status_for_error("SOME_UNKNOWN_CODE") == 500
    assert is_retryable_error("SOME_UNKNOWN_CODE") is False


def test_domain_error_to_error_info():
    err = InvalidArgumentError("bad page size", details={"field": "page_size"})

    assert err.http_status_code == 400
    payload = err.to_error_info()
    assert payload.code == ErrorCode.INVALID_ARGUMENT.value
    assert payload.retryable is False
    assert payload.details == {"field": "page_size"}
