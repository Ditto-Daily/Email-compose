"""Manual draft helpers used by the Streamlit dashboard buttons."""

from __future__ import annotations

import logging
from typing import Any

import db
from gmail_client import create_draft
from llm_engine import generate_email_draft, generate_email_drafts_batch

logger = logging.getLogger(__name__)

BATCH_SIZE = 20


def _prompt_input(email: dict[str, Any]) -> str:
    return (
        f"From: {email['from']}\n"
        f"Subject: {email['subject']}\n\n"
        f"{email['body']}"
    )


def draft_email(email: dict[str, Any]) -> str:
    """Generate, save, and track one Gmail draft. Return the Gmail draft ID."""
    if db.draft_exists(email["id"]):
        raise ValueError("This email already has a tracked draft.")

    ai_draft = generate_email_draft(_prompt_input(email))
    draft_id = create_draft(
        thread_id=email["thread_id"],
        to_email=email["from_email"],
        subject=email["subject"],
        body_text=ai_draft,
        reply_to_message_id=email.get("rfc_message_id", ""),
    )
    db.log_draft(
        incoming_message_id=email["id"],
        thread_id=email["thread_id"],
        draft_id=draft_id,
        incoming_body=email["body"],
        ai_draft=ai_draft,
    )
    logger.info("Created draft %s for message %s", draft_id, email["id"])
    return draft_id


def _save_generated_draft(email: dict[str, Any], ai_draft: str) -> str:
    draft_id = create_draft(
        thread_id=email["thread_id"],
        to_email=email["from_email"],
        subject=email["subject"],
        body_text=ai_draft,
        reply_to_message_id=email.get("rfc_message_id", ""),
    )
    db.log_draft(
        incoming_message_id=email["id"],
        thread_id=email["thread_id"],
        draft_id=draft_id,
        incoming_body=email["body"],
        ai_draft=ai_draft,
    )
    return draft_id


def draft_emails_batch(emails: list[dict[str, Any]]) -> dict[str, Any]:
    """Draft many unread emails with one Gemini call per chunk of BATCH_SIZE.

    Returns a summary with drafted, skipped, and failed lists.
    """
    summary: dict[str, Any] = {
        "drafted": [],
        "skipped": [],
        "failed": [],
    }

    pending: list[dict[str, Any]] = []
    for email in emails:
        if db.draft_exists(email["id"]):
            summary["skipped"].append(
                {
                    "id": email["id"],
                    "subject": email.get("subject", ""),
                    "reason": "Already has a tracked draft",
                }
            )
        else:
            pending.append(email)

    for start in range(0, len(pending), BATCH_SIZE):
        chunk = pending[start : start + BATCH_SIZE]
        try:
            drafts_by_id = generate_email_drafts_batch(chunk)
        except Exception as exc:
            logger.exception("Batch draft generation failed")
            for email in chunk:
                summary["failed"].append(
                    {
                        "id": email["id"],
                        "subject": email.get("subject", ""),
                        "reason": f"Gemini batch failed: {exc}",
                    }
                )
            continue

        for email in chunk:
            message_id = email["id"]
            ai_draft = drafts_by_id.get(message_id)
            if not ai_draft:
                summary["failed"].append(
                    {
                        "id": message_id,
                        "subject": email.get("subject", ""),
                        "reason": "Gemini omitted a reply for this message",
                    }
                )
                continue
            try:
                draft_id = _save_generated_draft(email, ai_draft)
                summary["drafted"].append(
                    {
                        "id": message_id,
                        "subject": email.get("subject", ""),
                        "draft_id": draft_id,
                    }
                )
                logger.info("Created draft %s for message %s", draft_id, message_id)
            except Exception as exc:
                logger.exception("Failed to save draft for message %s", message_id)
                summary["failed"].append(
                    {
                        "id": message_id,
                        "subject": email.get("subject", ""),
                        "reason": str(exc),
                    }
                )

    return summary
