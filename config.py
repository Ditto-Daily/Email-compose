"""Application configuration and filesystem locations."""

from __future__ import annotations

import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"

STANDARD_TEMPLATE_PATH = TEMPLATES_DIR / "standard.txt"
TEMPLATES_JSON_PATH = TEMPLATES_DIR / "templates.json"
WRITING_STYLE_PATH = TEMPLATES_DIR / "writing_style.txt"
DATABASE_PATH = BASE_DIR / "tracker.db"
GOOGLE_CREDENTIALS_PATH = Path(
    os.getenv("GOOGLE_CREDENTIALS_PATH", BASE_DIR / "credentials.json")
)
GOOGLE_TOKEN_PATH = Path(os.getenv("GOOGLE_TOKEN_PATH", BASE_DIR / "token.json"))

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.drafts.create",
    "https://www.googleapis.com/auth/gmail.readonly",
]

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


DEFAULT_WRITING_STYLE = """Always start the reply with:
Hello {customer_name},

Use the customer's first name from the email when it is clear. If the name is unclear, use:
Hello,

Always end the reply with one of these sign-offs (prefer "All the best" unless the tone is more formal):

All the best,
Anita

or

Best regards,
Anita

If the customer used "x" in their email as kisses (for example ending with "x" or "xx"), include a matching "x" after the sign-off.

Keep the tone warm, natural, and personal. Do not invent a customer name.
""".strip()


def ensure_app_files() -> None:
    """Create runtime directories and default style rules when absent."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if not WRITING_STYLE_PATH.exists():
        WRITING_STYLE_PATH.write_text(DEFAULT_WRITING_STYLE + "\n", encoding="utf-8")


def _secrets_mapping():
    try:
        import streamlit as st

        return st.secrets
    except Exception:
        return None


def apply_runtime_secrets() -> None:
    """Load Streamlit Cloud / local secrets into env paths used by the app."""
    global MODEL_NAME, GEMINI_API_KEY, APP_PASSWORD

    secrets = _secrets_mapping()
    if not secrets:
        return

    if secrets.get("GEMINI_API_KEY"):
        GEMINI_API_KEY = str(secrets["GEMINI_API_KEY"])
        os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY
    if secrets.get("GEMINI_MODEL"):
        MODEL_NAME = str(secrets["GEMINI_MODEL"])
        os.environ["GEMINI_MODEL"] = MODEL_NAME
    if secrets.get("APP_PASSWORD"):
        APP_PASSWORD = str(secrets["APP_PASSWORD"])
        os.environ["APP_PASSWORD"] = APP_PASSWORD

    credentials_json = secrets.get("google_credentials_json")
    if credentials_json:
        if hasattr(credentials_json, "to_dict"):
            payload = json.dumps(credentials_json.to_dict())
        elif isinstance(credentials_json, dict):
            payload = json.dumps(credentials_json)
        else:
            payload = str(credentials_json).strip()
        GOOGLE_CREDENTIALS_PATH.write_text(payload, encoding="utf-8")

    token_json = secrets.get("google_token_json")
    if token_json:
        if hasattr(token_json, "to_dict"):
            payload = json.dumps(token_json.to_dict())
        elif isinstance(token_json, dict):
            payload = json.dumps(token_json)
        else:
            payload = str(token_json).strip()
        GOOGLE_TOKEN_PATH.write_text(payload, encoding="utf-8")

    # Cloud/server hosts should not try interactive browser OAuth.
    os.environ.setdefault("HEADLESS", "true")
