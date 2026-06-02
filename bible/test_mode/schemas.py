from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Domain = Literal["KNOWLEDGE_BASE", "SKILL", "MEMORY"]
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class ResponseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: int = 200
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = Field(default=None, alias="json")


class RouteFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    method: str
    path: str
    domain: Domain | None = None
    selector: dict[str, Any] = Field(default_factory=dict)
    response: ResponseFixture

    @model_validator(mode="after")
    def normalize_method(self) -> "RouteFixture":
        self.method = self.method.upper()
        return self


class TaskFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: str = "test_mode.task"
    domain: Domain
    tag: str | None = None
    status: TaskStatus = "queued"
    final_status: TaskStatus | None = None
    query_count: int = 0
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ArtifactFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    domain: Literal["SKILL", "MEMORY"]
    content_type: str
    file_name: str
    body_base64: str | None = None
    file_path: str | None = None
    sha256: str | None = None
    expired: bool = False

    @model_validator(mode="after")
    def exactly_one_body_source(self) -> "ArtifactFixture":
        if bool(self.body_base64) == bool(self.file_path):
            raise ValueError("artifact must define exactly one of body_base64 or file_path")
        return self


class FixtureDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    routes: list[RouteFixture] = Field(default_factory=list)
    tasks: list[TaskFixture] = Field(default_factory=list)
    artifacts: list[ArtifactFixture] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_version(self) -> "FixtureDocument":
        if self.version != 1:
            raise ValueError("fixture version must be 1")
        return self


class RequestContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: str
    path: str
    domain: Domain | None = None
    body: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    path_params: dict[str, Any] = Field(default_factory=dict)
    multipart: dict[str, Any] = Field(default_factory=dict)

