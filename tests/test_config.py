import os
import stat

from hermes.config import DEFAULT_BASE_URL, DEFAULT_MODEL, load_config


def test_config_uses_dagi_environment_and_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_API_KEY", "test-key-not-a-real-credential")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.delenv("DAGI_MODEL", raising=False)
    monkeypatch.delenv("DAGI_BASE_URL", raising=False)
    monkeypatch.delenv("DAGI_ENABLE_SHELL", raising=False)

    config = load_config()

    assert config.api_key == "test-key-not-a-real-credential"
    assert config.model == DEFAULT_MODEL
    assert config.base_url == DEFAULT_BASE_URL
    assert config.workspace == (tmp_path / "workspace").resolve()
    assert config.enable_shell is False
    assert config.memory_db_path == tmp_path / "home" / "memory.sqlite3"
    if os.name == "posix":
        assert stat.S_IMODE(config.home.stat().st_mode) == 0o700
        assert stat.S_IMODE(config.skills_dir.stat().st_mode) == 0o700


def test_config_allows_explicit_compatible_endpoint_and_shell_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_API_KEY", "test-key")
    monkeypatch.setenv("DAGI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAGI_BASE_URL", "https://openrouter.ai/api/v1/")
    monkeypatch.setenv("DAGI_MODEL", "vendor/model")
    monkeypatch.setenv("DAGI_ENABLE_SHELL", "1")

    config = load_config()

    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.model == "vendor/model"
    assert config.enable_shell is True


def test_config_refuses_to_start_without_api_key(monkeypatch):
    monkeypatch.delenv("DAGI_API_KEY", raising=False)
    try:
        load_config()
    except ValueError as exc:
        assert "DAGI_API_KEY" in str(exc)
    else:
        raise AssertionError("load_config accepted missing API key")
