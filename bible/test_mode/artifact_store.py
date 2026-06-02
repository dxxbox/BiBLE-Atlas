from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path

from bible.test_mode.schemas import ArtifactFixture


class ArtifactStoreError(ValueError):
    pass


class ArtifactStore:
    def __init__(self, artifacts: list[ArtifactFixture], *, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._artifacts = {artifact.artifact_id: artifact for artifact in artifacts}
        self._validate_artifacts()

    def get(self, artifact_id: str, domain: str) -> tuple[ArtifactFixture, bytes] | None:
        artifact = self._artifacts.get(artifact_id)
        if artifact is None or artifact.domain.lower() != domain.lower():
            return None
        return artifact, self._read_body(artifact)

    def is_expired(self, artifact_id: str) -> bool:
        artifact = self._artifacts.get(artifact_id)
        return bool(artifact and artifact.expired)

    def _read_body(self, artifact: ArtifactFixture) -> bytes:
        if artifact.body_base64 is not None:
            return self._decode_body_base64(artifact)
        if artifact.file_path is None:
            return b""
        return self._resolve_path(artifact.file_path).read_bytes()

    def _validate_artifacts(self) -> None:
        for artifact in self._artifacts.values():
            if artifact.body_base64 is not None:
                self._decode_body_base64(artifact)
            if artifact.file_path is not None:
                path = self._resolve_path(artifact.file_path)
                if not path.exists():
                    raise ArtifactStoreError(f"artifact file does not exist: {artifact.file_path}")
                if artifact.sha256:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    if digest != artifact.sha256:
                        raise ArtifactStoreError(f"artifact sha256 mismatch: {artifact.artifact_id}")

    def _decode_body_base64(self, artifact: ArtifactFixture) -> bytes:
        try:
            return base64.b64decode(artifact.body_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ArtifactStoreError(f"artifact body_base64 is invalid: {artifact.artifact_id}") from exc

    def _resolve_path(self, file_path: str) -> Path:
        path = Path(file_path)
        if path.is_absolute():
            return path
        return self.repo_root / path

