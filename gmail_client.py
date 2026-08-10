"""Gmail OAuth, inbox reading, draft creation, and sent-message retrieval."""

from __future__ import annotations

import base64
import logging
import os
import re
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.utils import parseaddr
from functools import lru_cache
from html.parser import HTMLParser
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    GMAIL_SCOPES,
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_TOKEN_PATH,
)

logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError):
        return value


def _decode_body(data: str) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")


def _payload_text(payload: dict[str, Any]) -> str:
    """Prefer plain text, then convert HTML, traversing nested MIME parts."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")
    if mime_type == "text/plain" and body_data:
        return _decode_body(body_data)

    plain_candidates: list[str] = []
    html_candidates: list[str] = []
    for part in payload.get("parts", []):
        text = _payload_text(part)
        if not text:
            continue
        if part.get("mimeType") == "text/html":
            html_candidates.append(text)
        else:
            plain_candidates.append(text)

    if plain_candidates:
        return "\n".join(plain_candidates)
    if html_candidates:
        return "\n".join(html_candidates)
    if mime_type == "text/html" and body_data:
        parser = _HTMLTextExtractor()
        parser.feed(_decode_body(body_data))
        return parser.text()
    if body_data and not payload.get("filename"):
        return _decode_body(body_data)
    return ""


def _clean_reply_history(body: str) -> str:
    """Remove common quoted-thread markers from a message body."""
    markers = [
        r"(?im)^\s*On .+wrote:\s*$",
        r"(?im)^\s*-{2,}\s*Original Message\s*-{2,}\s*$",
        r"(?im)^\s*From:\s+.+$",
        r"(?im)^\s*_{5,}\s*$",
    ]
    cut_at = len(body)
    for marker in markers:
        match = re.search(marker, body)
        if match:
            cut_at = min(cut_at, match.start())
    cleaned_lines = [
        line for line in body[:cut_at].splitlines() if not line.lstrip().startswith(">")
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        header["name"].lower(): _decode_header(header.get("value", ""))
        for header in payload.get("headers", [])
    }


def _parse_message(message: dict[str, Any]) -> dict[str, Any]:
    payload = message.get("payload", {})
    headers = _headers(payload)
    body = _clean_reply_history(_payload_text(payload))
    from_header = headers.get("from", "")
    reply_address = parseaddr(headers.get("reply-to", from_header))[1]
    return {
        "id": message["id"],
        "thread_id": message["threadId"],
        "from": from_header,
        "from_email": reply_address,
        "subject": headers.get("subject", "(No subject)"),
        "snippet": message.get("snippet", ""),
        "body": body or message.get("snippet", ""),
        "rfc_message_id": headers.get("message-id", ""),
        "internal_date": int(message.get("internalDate", "0")),
    }


@lru_cache(maxsize=1)
def get_gmail_service():
    """Authenticate locally and return a cached Gmail API service."""
    credentials: Credentials | None = None
    if GOOGLE_TOKEN_PATH.exists():
        try:
            credentials = Credentials.from_authorized_user_file(
                str(GOOGLE_TOKEN_PATH), GMAIL_SCOPES
            )
        except (ValueError, OSError) as exc:
            logger.warning("Could not load saved Google token: %s", exc)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid or not credentials.has_scopes(GMAIL_SCOPES):
        if not GOOGLE_CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"Google OAuth credentials not found at {GOOGLE_CREDENTIALS_PATH}. "
                "Download an OAuth desktop client file and save it as credentials.json."
            )
        if os.getenv("HEADLESS", "").lower() in {"1", "true", "yes"}:
            raise RuntimeError(
                "Gmail is not authenticated on this server. Run the app once on a "
                "local machine to create token.json, then copy credentials.json and "
                "token.json onto the host (or unset HEADLESS to auth interactively)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(GOOGLE_CREDENTIALS_PATH), GMAIL_SCOPES
        )
        credentials = flow.run_local_server(port=0)

    GOOGLE_TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def get_unread_emails(max_results: int = 25) -> list[dict[str, Any]]:
    """Return parsed unread inbox messages, excluding Promotions and Social."""
    service = get_gmail_service()
    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            q="is:unread in:inbox -category:promotions -category:social -category:updates",
            maxResults=max_results,
        )
        .execute()
    )
    emails: list[dict[str, Any]] = []
    for item in response.get("messages", []):
        message = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="full")
            .execute()
        )
        emails.append(_parse_message(message))
    return emails


def create_draft(
    thread_id: str,
    to_email: str,
    subject: str,
    body_text: str,
    reply_to_message_id: str = "",
) -> str:
    """Create a plain-text reply draft in an existing Gmail thread."""
    if not to_email:
        raise ValueError("The sender has no valid reply-to email address.")
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    mime_message = MIMEText(body_text, "plain", "utf-8")
    mime_message["To"] = to_email
    mime_message["Subject"] = reply_subject
    if reply_to_message_id:
        mime_message["In-Reply-To"] = reply_to_message_id
        mime_message["References"] = reply_to_message_id

    raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("ascii")
    result = (
        get_gmail_service()
        .users()
        .drafts()
        .create(
            userId="me",
            body={"message": {"raw": raw, "threadId": thread_id}},
        )
        .execute()
    )
    return result["id"]
