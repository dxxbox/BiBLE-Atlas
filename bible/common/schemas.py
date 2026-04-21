from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

ResultT = TypeVar("ResultT")


class ResponseStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


class MetaInfo(BaseModel):
    request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cost_ms: int | None = None


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False


class BibleResponse(BaseModel, Generic[ResultT]):
    status: ResponseStatus
    result: ResultT | None = None
    error: ErrorInfo | None = None
    meta: MetaInfo | None = None

    @model_validator(mode="after")
    def validate_payload_shape(self) -> "BibleResponse[ResultT]":
        if self.status == ResponseStatus.OK and self.error is not None:
            raise ValueError("error must be null for successful responses")
        if self.status == ResponseStatus.ERROR and self.error is None:
            raise ValueError("error is required for failed responses")
        return self

    @classmethod
    def success(
        cls,
        result: ResultT,
        meta: MetaInfo | None = None,
    ) -> "BibleResponse[ResultT]":
        return cls(status=ResponseStatus.OK, result=result, error=None, meta=meta)

    @classmethod
    def failure(
        cls,
        error: ErrorInfo,
        *,
        meta: MetaInfo | None = None,
        result: Any = None,
    ) -> "BibleResponse[Any]":
        return cls(status=ResponseStatus.ERROR, result=result, error=error, meta=meta)
