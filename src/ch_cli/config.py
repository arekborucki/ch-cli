"""Connection profiles: ~/.config/ch-cli/config.toml, overridden by CH_* env vars and flags."""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    url: str
    user: str
    password: str
    database: str | None = None


def config_path() -> Path:
    if explicit := os.environ.get("CH_CLI_CONFIG"):
        return Path(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "ch-cli" / "config.toml"


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def profile_names(config: dict) -> list[str]:
    return sorted(config.get("profiles", {}))


def _password(name: str, section: dict) -> str:
    # Precedence: CH_PASSWORD, then the profile's password_env, then password_cmd.
    # A plain `password` key is refused so secrets never sit in the file.
    if "password" in section:
        raise ConfigError(f"profile {name!r}: use password_env or password_cmd, not password")
    if value := os.environ.get("CH_PASSWORD"):
        return value
    if env := section.get("password_env"):
        if value := os.environ.get(env):
            return value
        raise ConfigError(f"profile {name!r}: environment variable {env} is not set")
    if cmd := section.get("password_cmd"):
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ConfigError(f"profile {name!r}: password_cmd failed: {result.stderr.strip()}")
        return result.stdout.strip()
    return ""


def resolve_profile(
    config: dict,
    name: str | None = None,
    url: str | None = None,
    user: str | None = None,
) -> Profile:
    profiles = config.get("profiles", {})
    name = name or os.environ.get("CH_PROFILE") or config.get("default")
    if name and name not in profiles:
        known = ", ".join(profile_names(config)) or "none"
        raise ConfigError(f"unknown profile {name!r} (known: {known})")
    section = profiles.get(name, {}) if name else {}
    url = url or os.environ.get("CH_URL") or section.get("url") or "http://localhost:8123"
    user = user or os.environ.get("CH_USER") or section.get("user") or "default"
    return Profile(
        name=name or "-",
        url=url.rstrip("/"),
        user=user,
        password=_password(name or "-", section),
        database=os.environ.get("CH_DATABASE") or section.get("database"),
    )
