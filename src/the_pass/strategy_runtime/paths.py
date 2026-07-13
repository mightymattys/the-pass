"""Workspace path containment for local strategy source files."""

from __future__ import annotations

from pathlib import Path
from typing import Union


PathLike = Union[str, Path]


def resolve_workspace_path(workspace_root: PathLike, relative_path: PathLike) -> Path:
    """Resolve an existing file without allowing traversal or symlink escape."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace root must be an existing directory")

    requested = Path(relative_path)
    if requested.is_absolute():
        raise ValueError("workspace path must be relative")
    if not requested.parts or any(part == ".." for part in requested.parts):
        raise ValueError("workspace path traversal is not allowed")

    resolved = (root / requested).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("workspace path escapes the workspace root") from exc
    if not resolved.is_file():
        raise ValueError("workspace path must resolve to a regular file")
    return resolved
