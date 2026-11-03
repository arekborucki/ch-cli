import pytest

from ch_cli.config import ConfigError, resolve_profile

CONFIG = {
    "default": "a",
    "profiles": {
        "a": {"url": "http://a:8123/", "user": "ua", "password_env": "A_PW"},
        "b": {"url": "http://b:8123", "password_cmd": "printf 'secret\\n'"},
        "bad": {"url": "http://c:8123", "password": "inline"},
        "pipe": {"url": "http://d:8123", "password_cmd": "sh -c 'echo nope >&2; exit 3' | cat"},
        "empty": {"url": "http://e:8123", "password_cmd": "true"},
    },
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("CH_PROFILE", "CH_URL", "CH_USER", "CH_PASSWORD", "CH_DATABASE", "A_PW"):
        monkeypatch.delenv(var, raising=False)


def test_default_profile_and_password_env(monkeypatch):
    monkeypatch.setenv("A_PW", "pw")
    p = resolve_profile(CONFIG)
    assert (p.name, p.url, p.user, p.password) == ("a", "http://a:8123", "ua", "pw")


def test_password_cmd():
    p = resolve_profile(CONFIG, "b")
    assert (p.user, p.password) == ("default", "secret")


def test_missing_password_env_is_an_error():
    with pytest.raises(ConfigError, match="A_PW"):
        resolve_profile(CONFIG, "a")


def test_inline_password_is_refused():
    with pytest.raises(ConfigError, match="password_env or password_cmd"):
        resolve_profile(CONFIG, "bad")


def test_unknown_profile():
    with pytest.raises(ConfigError, match="unknown profile 'x'"):
        resolve_profile(CONFIG, "x")


def test_env_and_flags_override(monkeypatch):
    monkeypatch.setenv("CH_PASSWORD", "envpw")
    monkeypatch.setenv("CH_URL", "http://env:8123")
    p = resolve_profile(CONFIG, "a", user="flaguser")
    assert (p.url, p.user, p.password) == ("http://env:8123", "flaguser", "envpw")


def test_no_config_defaults_to_localhost():
    p = resolve_profile({})
    assert (p.url, p.user, p.password) == ("http://localhost:8123", "default", "")


def test_password_cmd_failure_inside_a_pipe():
    with pytest.raises(ConfigError, match="password_cmd failed: nope"):
        resolve_profile(CONFIG, "pipe")


def test_password_cmd_empty_output():
    with pytest.raises(ConfigError, match="password_cmd failed: empty output"):
        resolve_profile(CONFIG, "empty")
