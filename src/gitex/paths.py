"""Dosya yolları (config ve i18n'in döngüsel içe aktarma olmadan paylaştığı)."""

from __future__ import annotations

import os
from pathlib import Path

GITEX_DIR = ".gitex"
CONFIG_FILE = "config.toml"
INDEX_FILE = "index.db"


def user_config_path() -> Path:
    if env := os.environ.get("GITEX_CONFIG"):
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gitex" / CONFIG_FILE
