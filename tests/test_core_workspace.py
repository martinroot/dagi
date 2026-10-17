import pytest

from dagi_core.workspace import resolve_session_workspace


def test_legacy_empty_workspace_resolves_to_configured_root(tmp_path):
    root = tmp_path / "root"

    assert resolve_session_workspace(root, "") == root.resolve()


def test_child_workspace_resolves_beneath_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    resolved = resolve_session_workspace(root, ".dagi-children/12")

    assert resolved == (root / ".dagi-children" / "12").resolve()
    assert resolved.is_relative_to(root.resolve())


@pytest.mark.parametrize("stored", ["/tmp/outside", "../outside", "child/../../escape", "bad\\path", "bad\x00path"])
def test_session_workspace_rejects_unsafe_stored_path(tmp_path, stored):
    with pytest.raises(ValueError, match="workspace"):
        resolve_session_workspace(tmp_path / "root", stored)


def test_session_workspace_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="workspace"):
        resolve_session_workspace(root, "linked/child")


def test_session_workspace_rejects_symlink_target_outside_root(tmp_path):
    root = tmp_path / "root"
    outside_file = tmp_path / "secret.txt"
    root.mkdir()
    outside_file.write_text("secret", encoding="utf-8")
    (root / "secret.txt").symlink_to(outside_file)

    with pytest.raises(ValueError, match="workspace"):
        resolve_session_workspace(root, "secret.txt")
