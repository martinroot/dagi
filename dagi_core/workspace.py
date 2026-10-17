"""Resolve persisted session workspaces safely below the configured root."""

from pathlib import Path, PurePosixPath


def resolve_session_workspace(configured_root: Path, stored_workspace: str) -> Path:
    """Return the absolute owning workspace for an empty legacy or relative path.

    The persisted value is untrusted state: validate both its lexical form and
    its resolved path so symlinks cannot redirect a session outside the root.
    The function deliberately does not create directories.
    """
    if not isinstance(stored_workspace, str) or "\x00" in stored_workspace or "\\" in stored_workspace:
        raise ValueError("session workspace must be a safe relative path")

    root = Path(configured_root).expanduser().resolve()
    if stored_workspace == "":
        return root

    relative = PurePosixPath(stored_workspace)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("session workspace must stay inside the configured root")

    try:
        candidate = (root / Path(*relative.parts)).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("session workspace cannot be resolved safely") from exc
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError("session workspace resolves outside the configured root")
    return candidate
