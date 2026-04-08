"""Workspace path safety: canonicalization and traversal prevention.

Ports the Elixir PathSafety module to ensure workspace paths are safe
and cannot escape the configured workspace root via symlinks or traversal.
"""

from __future__ import annotations

import re
from pathlib import Path


def sanitize_workspace_key(identifier: str) -> str:
    """Derive a safe directory name from an issue identifier.

    Replaces any character not in [A-Za-z0-9._-] with underscore.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", identifier)


def canonicalize(path: str | Path) -> str:
    """Canonicalize a path, resolving symlinks for existing segments.

    For segments that exist on disk, symlinks are resolved.
    For segments that don't exist yet, they are appended as-is.

    Returns the canonical absolute path string.
    Raises ValueError if a path segment cannot be resolved.
    """
    path = Path(path).expanduser().resolve()
    parts = path.parts

    if not parts:
        raise ValueError(f"Cannot canonicalize empty path: {path}")

    # Start with the root
    resolved = Path(parts[0])

    for segment in parts[1:]:
        candidate = resolved / segment

        if candidate.is_symlink():
            # Resolve the symlink target
            target = candidate.resolve()
            resolved = target
        elif candidate.exists():
            resolved = candidate
        else:
            # Path doesn't exist yet — append remaining segments as-is
            resolved = candidate

    return str(resolved)


def validate_workspace_path(workspace_path: str | Path, workspace_root: str | Path) -> str:
    """Validate that a workspace path is safely under the workspace root.

    Returns the canonical workspace path.
    Raises ValueError if the path escapes the root.
    """
    canonical_workspace = canonicalize(workspace_path)
    canonical_root = canonicalize(workspace_root)

    if not canonical_workspace.startswith(canonical_root + "/") and canonical_workspace != canonical_root:
        raise ValueError(
            f"Workspace path {canonical_workspace} escapes root {canonical_root}"
        )

    return canonical_workspace


def workspace_path_for_issue(workspace_root: str, identifier: str) -> str:
    """Compute the workspace directory path for an issue.

    Args:
        workspace_root: The configured workspace root directory.
        identifier: The issue identifier (e.g., "ABC-123").

    Returns:
        The full workspace path.
    """
    key = sanitize_workspace_key(identifier)
    return str(Path(workspace_root) / key)
