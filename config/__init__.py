"""Config loaders. Everything collectors/pipeline need comes from here — no magic values inline."""
import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

CONFIG_DIR = Path(__file__).parent
REPO_ROOT = CONFIG_DIR.parent

load_dotenv(REPO_ROOT / ".env")


def _load_yaml(name):
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_competitors():
    return _load_yaml("competitors.yaml")["competitors"]


def get_rubric():
    return _load_yaml("rubric.yaml")


def get_settings():
    return _load_yaml("settings.yaml")


def get_app_store_ids():
    return _load_yaml("app_store_ids.yaml")["ios_app_ids"]


def get_sec_user_agent():
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError(
            "SEC_USER_AGENT is not set — add it to .env (see .env.example). "
            "SEC EDGAR returns 403 without a declared User-Agent."
        )
    return ua


def get_anthropic_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — add it to .env (see .env.example).")
    return key


def db_path():
    return REPO_ROOT / get_settings()["db"]["path"]


def competitors_as_json_row(competitor):
    """Serialize a competitors.yaml entry's list fields to JSON text for the `competitor` table."""
    row = dict(competitor)
    row["tickers"] = json.dumps(row["tickers"]) if row.get("tickers") else None
    row["pillars"] = json.dumps(row["pillars"])
    return row
