# -*- coding: utf-8 -*-
"""Load and store the coordination rules (settings.json).

Defaults live in the extension (config/default_settings.json).
The user's own copy lives in %APPDATA%/Coordination/settings.json and wins
over the defaults key by key, so new default keys appear automatically.
"""
import io
import json
import os
import shutil

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
EXTENSION_DIR = os.path.dirname(os.path.dirname(_LIB_DIR))
DEFAULTS_PATH = os.path.join(EXTENSION_DIR, "config", "default_settings.json")

USER_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Coordination")
USER_PATH = os.path.join(USER_DIR, "settings.json")


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _merge(base, override):
    """Recursively merge override into a copy of base."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def ensure_user_file():
    """Create the user's settings file from defaults if it does not exist."""
    if not os.path.isdir(USER_DIR):
        os.makedirs(USER_DIR)
    if not os.path.isfile(USER_PATH):
        shutil.copyfile(DEFAULTS_PATH, USER_PATH)
    return USER_PATH


def load():
    """Return the effective settings (defaults + user overrides)."""
    settings = _read_json(DEFAULTS_PATH)
    if os.path.isfile(USER_PATH):
        settings = _merge(settings, _read_json(USER_PATH))
    return settings
