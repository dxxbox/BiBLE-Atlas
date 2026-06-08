"""Safe ZIP extractor — stdlib only (runs inside sandbox subprocess).

Prevents Zip Slip and enforces size/entry-count limits.
"""
from __future__ import annotations

import os
import zipfile

_MAX_ENTRIES = 2000
_MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024   # 512 MB
_MAX_SINGLE_ENTRY_BYTES = 64 * 1024 * 1024           # 64 MB


def safe_extract(zip_path: str, extract_dir: str) -> str:
    """Extract .skill zip to extract_dir safely.

    Checks:
    - ZIP can be opened (else SKILL_PACKAGE_INVALID_FORMAT)
    - Entry count <= _MAX_ENTRIES
    - No absolute paths or path components that escape extract_dir (Zip Slip)
    - No symlinks
    - Uncompressed size per entry <= _MAX_SINGLE_ENTRY_BYTES
    - Total uncompressed size <= _MAX_TOTAL_UNCOMPRESSED_BYTES

    Returns extract_dir.
    """
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(
            f"SKILL_PACKAGE_INVALID_FORMAT: Cannot open .skill package as ZIP: {exc}"
        )

    with zf:
        entries = zf.infolist()

        if len(entries) > _MAX_ENTRIES:
            raise ValueError(
                f"SKILL_PACKAGE_INVALID_FORMAT: ZIP contains {len(entries)} entries, "
                f"max allowed is {_MAX_ENTRIES}."
            )

        total_bytes = 0
        for entry in entries:
            # Reject symlinks
            if entry.external_attr >> 16 & 0o120000 == 0o120000:
                raise ValueError(
                    f"SKILL_PACKAGE_UNSAFE_PATH: ZIP entry '{entry.filename}' is a symlink, "
                    "which is not allowed."
                )

            # Reject absolute paths
            if os.path.isabs(entry.filename):
                raise ValueError(
                    f"SKILL_PACKAGE_UNSAFE_PATH: ZIP entry has absolute path: '{entry.filename}'."
                )

            # Zip Slip check — resolve and verify it stays within extract_dir
            target = os.path.realpath(os.path.join(extract_dir, entry.filename))
            realbase = os.path.realpath(extract_dir)
            if not target.startswith(realbase + os.sep) and target != realbase:
                raise ValueError(
                    f"SKILL_PACKAGE_UNSAFE_PATH: ZIP entry '{entry.filename}' would extract "
                    "outside the target directory."
                )

            # Per-entry size limit
            if entry.file_size > _MAX_SINGLE_ENTRY_BYTES:
                raise ValueError(
                    f"SKILL_PACKAGE_INVALID_FORMAT: ZIP entry '{entry.filename}' is "
                    f"{entry.file_size} bytes, exceeds max {_MAX_SINGLE_ENTRY_BYTES} bytes."
                )

            total_bytes += entry.file_size

        # Total size limit
        if total_bytes > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"SKILL_PACKAGE_INVALID_FORMAT: Total uncompressed size {total_bytes} bytes "
                f"exceeds max {_MAX_TOTAL_UNCOMPRESSED_BYTES} bytes."
            )

        os.makedirs(extract_dir, exist_ok=True)
        zf.extractall(extract_dir)

    return extract_dir
