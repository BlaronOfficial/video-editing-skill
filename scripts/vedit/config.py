"""User configuration in personal/config.json, merged over shipped defaults.

The defaults live in code so `git pull` can add new settings without touching the user's file;
`migrate()` upgrades older personal files in place when the schema changes.
"""

from __future__ import annotations

import copy
import os
from typing import Any

from .paths import personal_dir
from .util import read_json, write_json

SCHEMA_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "transcription": {
        "engine": "ask",                     # ask | whisper | scribe
        "whisper_model": "large-v3-turbo",   # fast default for English
        "whisper_model_bangla": "large-v3",  # turbo is weaker on Bangla / code-switching
        "whisper_compute_type": "int8",
        "scribe_model": "scribe_v2",
    },
    "capcut": {
        "drafts_root": None,                 # None = OS default
        "app_path": None,
        "seed": None,                        # filled by `vedit capcut calibrate`
        "app_version": None,
        "pro": "ask",                        # ask | yes | no  (per project override in edit.json)
        "alpha_overlays": "unknown",         # unknown | prores | webm | chroma (probed once)
    },
    "render": {
        "encoder": "auto",                   # auto | libx264 | h264_qsv | h264_nvenc | h264_videotoolbox
        "crf": 18,
        "preset": "medium",
        "audio_bitrate": "192k",
        "target_lufs": -14.0,
    },
    "higgsfield": {"spend_policy": "ask_with_estimate"},
    "pinterest": {"default_mode": "moodboard"},   # moodboard | use
    "defaults": {"brand": None, "style": None, "captions": "karaoke_pop"},
    "screen_control": {"preferred": "auto"},      # auto | computer-use | windows-mcp | none
}

SECRET_ENV = {
    "elevenlabs": "ELEVENLABS_API_KEY",
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def config_path():
    return personal_dir() / "config.json"


def load() -> dict[str, Any]:
    user = read_json(config_path(), default={}) or {}
    user = migrate(user)
    return _deep_merge(DEFAULTS, user)


def save_user_values(updates: dict[str, Any]) -> dict[str, Any]:
    """Persist only what the user set (not the defaults), so future default changes still apply."""
    user = read_json(config_path(), default={}) or {}
    user = _deep_merge(user, updates)
    user["schema_version"] = SCHEMA_VERSION
    write_json(config_path(), user)
    return load()


def set_value(dotted_key: str, value: Any) -> dict[str, Any]:
    node: dict[str, Any] = {}
    cursor = node
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value
    return save_user_values(node)


def migrate(user: dict[str, Any]) -> dict[str, Any]:
    """Upgrade an older personal config. Add a branch here whenever SCHEMA_VERSION increases."""
    version = user.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        return user  # written by a newer skill version; leave untouched
    return user


def secret(name: str) -> str | None:
    """API keys: environment variable first, then personal/secrets.json (never committed)."""
    env_name = SECRET_ENV.get(name, name.upper())
    if os.environ.get(env_name):
        return os.environ[env_name]
    secrets = read_json(personal_dir() / "secrets.json", default={}) or {}
    return secrets.get(name)


def set_secret(name: str, value: str) -> None:
    path = personal_dir() / "secrets.json"
    secrets = read_json(path, default={}) or {}
    secrets[name] = value
    write_json(path, secrets)
