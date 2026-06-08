#!/usr/bin/env python3
"""Create a compact ZIP archive of the current folder.

The script prefers Git's ignore engine so nested .gitignore files, .git/info/exclude,
and global Git excludes are respected. It also skips hidden directories by default
to avoid packaging editor metadata, virtual environments, caches, and VCS data.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    ".cache",
    ".cursor",
    ".eggs",
    ".hypothesis",
    ".idea",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".nox",
    ".tox",
    "__pycache__",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Zip files under a folder while excluding hidden directories and files "
            "ignored by Git."
        )
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        type=Path,
        help="folder to package; defaults to the current folder",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output ZIP path; defaults to dist/<folder>-source-<timestamp>.zip",
    )
    parser.add_argument(
        "--include-hidden-dirs",
        action="store_true",
        help="include hidden directories that are not ignored by Git",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show files that would be packaged without creating a ZIP",
    )
    return parser.parse_args()


def default_output_path(root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"{root.name or 'package'}-source-{timestamp}.zip"
    return root / "dist" / archive_name


def git_list_files(root: Path) -> list[Path] | None:
    command = [
        "git",
        "-C",
        str(root),
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        ".",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    paths: list[Path] = []
    for raw_path in completed.stdout.split(b"\0"):
        if raw_path:
            paths.append(Path(raw_path.decode("utf-8", errors="surrogateescape")))
    return paths


def walk_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file():
            paths.append(path.relative_to(root))
    return paths


def is_hidden_dir(path_part: str) -> bool:
    return path_part.startswith(".")


def should_skip(
    relative_path: Path,
    *,
    output_path: Path,
    root: Path,
    include_hidden_dirs: bool,
) -> bool:
    full_path = root / relative_path
    if not full_path.is_file():
        return True

    try:
        if full_path.resolve() == output_path.resolve():
            return True
    except FileNotFoundError:
        pass

    directory_parts = relative_path.parts[:-1]
    if any(part in DEFAULT_EXCLUDED_DIRS for part in directory_parts):
        return True

    if not include_hidden_dirs and any(is_hidden_dir(part) for part in directory_parts):
        return True

    return False


def collect_files(root: Path, output_path: Path, include_hidden_dirs: bool) -> tuple[list[Path], bool]:
    git_files = git_list_files(root)
    used_git = git_files is not None
    candidates = git_files if git_files is not None else walk_files(root)

    files = [
        path
        for path in candidates
        if not should_skip(
            path,
            output_path=output_path,
            root=root,
            include_hidden_dirs=include_hidden_dirs,
        )
    ]
    return sorted(set(files)), used_git


def create_zip(root: Path, output_path: Path, files: list[Path]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in files:
            archive.write(root / relative_path, relative_path.as_posix())


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"error: root folder does not exist: {root}", file=sys.stderr)
        return 2

    output_path = (args.output or default_output_path(root)).resolve()
    files, used_git = collect_files(root, output_path, args.include_hidden_dirs)

    if not used_git:
        print(
            "warning: Git ignore rules were not available; "
            "falling back to a filesystem walk with built-in directory exclusions.",
            file=sys.stderr,
        )

    if args.dry_run:
        for relative_path in files:
            print(relative_path.as_posix())
        print(f"\n{len(files)} files would be packaged into {output_path}")
        return 0

    create_zip(root, output_path, files)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"created {output_path} with {len(files)} files ({size_mb:.2f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
