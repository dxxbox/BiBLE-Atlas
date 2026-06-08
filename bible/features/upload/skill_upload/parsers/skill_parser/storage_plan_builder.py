"""Storage plan builder — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations


def build_local_storage_plan(skill_package: dict, other_files: list[dict]) -> dict:
    """Build local_file_storage_plan covering ALL uploaded files.

    Returns {"files": [
        {"file_ref": ..., "filename": ..., "source_path": ...,
         "must_store_local": True, "storage_role": "skill_package" | "skill_attachment"}
    ]}
    """
    plan_files: list[dict] = []

    plan_files.append(
        {
            "file_ref": skill_package.get("file_ref", "file_0"),
            "filename": skill_package.get("filename", ""),
            "source_path": skill_package.get("abs_path", ""),
            "must_store_local": True,
            "storage_role": "skill_package",
        }
    )

    for f in other_files:
        plan_files.append(
            {
                "file_ref": f.get("file_ref", ""),
                "filename": f.get("filename", ""),
                "source_path": f.get("abs_path", ""),
                "must_store_local": True,
                "storage_role": "skill_attachment",
            }
        )

    return {"files": plan_files}
