"""Local garmin-ai configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".garmin-ai" / "config.json"


def load_config() -> dict[str, Any]:
    """Load local config, returning an empty dict when absent or invalid."""

    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict[str, Any]) -> Path:
    """Persist local config."""

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CONFIG_PATH


def get_config_value(key: str) -> Any:
    """Read one config value."""

    return load_config().get(key)


def set_config_value(key: str, value: Any) -> Path:
    """Set one config value."""

    data = load_config()
    data[key] = value
    return save_config(data)
