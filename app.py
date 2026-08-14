"""Streamlit dashboard for manual drafting and template management."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

import config
import db
from config import (
    GOOGLE_CREDENTIALS_PATH,
    WRITING_STYLE_PATH,
    apply_runtime_secrets,
    ensure_app_files,
)
from gmail_client import get_unread_emails
from template_store import (
    export_excel,
    load_category_settings,
    load_templates,
    save_templates,
)
from worker import draft_email, draft_emails_batch

logger = logging.getLogger(__name__)

st.set_page_config(page_title="AI Email Assistant", page_icon="✉️", layout="wide")
ensure_app_files()
apply_runtime_secrets()
db.initialize_db()


def _require_login() -> bool:
    """Gate remote access when APP_PASSWORD is set. Return True if unlocked."""
    if not config.APP_PASSWORD:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("AI Email Assistant")
    st.caption("Enter the shared access password to continue.")
    password = st.text_input("Password", type="password")
    if st.button("Unlock", type="primary"):
        if password == config.APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Incorrect password.")
    return False


if not _require_login():
    st.stop()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_unread_emails() -> list[dict[str, Any]]:
    return get_unread_emails()


st.title("AI Email Assistant")
st.caption(
    "Draft one email, or Draft All Unread in one Gemini request. "
    "Manage templates in Settings."
)

inbox_tab, style_tab, template_tab = st.tabs(
    ["📥 Inbox & Manual Draft", "✍️ Writing Style", "⚙️ Template Settings"]
)

with inbox_tab:
    st.subheader("Unread inbox")
    st.caption("Promotional, Social, and Updates emails are hidden from this list.")
    if not GOOGLE_CREDENTIALS_PATH.exists():
        st.info(
            f"Add your Google OAuth desktop credentials at "
            f"`{GOOGLE_CREDENTIALS_PATH.name}` to connect Gmail."
        )
    elif not config.GEMINI_API_KEY:
        st.info(
            "Set the `GEMINI_API_KEY` environment variable before drafting responses."
        )

    refresh_col, draft_all_col, _ = st.columns([1, 1, 4])
    if refresh_col.button("↻ Refresh inbox"):
        _cached_unread_emails.clear()

    if GOOGLE_CREDENTIALS_PATH.exists():
        try:
            with st.spinner("Loading unread emails…"):
                unread_emails = _cached_unread_emails()
            if not unread_emails:
                st.success("No unread inbox messages.")

            undrafted = [
                email
                for email in unread_emails
                if not db.draft_exists(email["id"])
            ]
            draft_all_disabled = not undrafted or not bool(config.GEMINI_API_KEY)
            if draft_all_col.button(
                "⚡ Draft All Unread",
                type="primary",
                disabled=draft_all_disabled,
                help=(
                    "Generates replies for all undrafted unread emails in one "
                    "Gemini request (template library sent once), then saves "
                    "each Gmail draft."
                ),
            ):
                try:
                    with st.spinner(
                        f"Drafting {len(undrafted)} email(s) in one Gemini request…"
                    ):
                        summary = draft_emails_batch(undrafted)
                    _cached_unread_emails.clear()
                    drafted_count = len(summary["drafted"])
                    skipped_count = len(summary["skipped"])
                    failed_count = len(summary["failed"])
                    st.success(
                        f"Draft All finished: {drafted_count} drafted, "
                        f"{skipped_count} skipped, {failed_count} failed."
                    )
                    if summary["failed"]:
                        with st.expander("Failed drafts"):
                            for item in summary["failed"]:
                                st.write(
                                    f"- {item.get('subject') or item['id']}: "
                                    f"{item.get('reason', 'Unknown error')}"
                                )
                    st.rerun()
                except Exception as exc:
                    logger.exception("Draft All failed")
                    st.error(f"Could not draft all emails: {exc}")

            for email in unread_emails:
                already_drafted = db.draft_exists(email["id"])
                with st.container(border=True):
                    st.markdown(f"**{email['subject']}**")
                    st.caption(f"From: {email['from']}")
                    st.write(email["snippet"] or email["body"][:240])
                    if already_drafted:
                        st.caption("✓ A draft is already tracked for this message.")
                    if st.button(
                        "⚡ Draft Email Now",
                        key=f"draft_{email['id']}",
                        type="primary",
                        disabled=already_drafted or not bool(config.GEMINI_API_KEY),
                    ):
                        try:
                            with st.spinner("Generating and saving your draft…"):
                                draft_email(email)
                            st.success("Draft successfully saved to Gmail!")
                        except Exception as exc:
                            logger.exception("Manual draft failed")
                            st.error(f"Could not create the draft: {exc}")
        except Exception as exc:
            logger.exception("Inbox loading failed")
            st.error(f"Could not load Gmail inbox: {exc}")

with style_tab:
    st.subheader("Writing style rules")
    st.caption(
        "These rules are always included in Gemini's context for every draft "
        "(greeting, sign-off, kisses 'x', and tone)."
    )
    try:
        current_style = WRITING_STYLE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        current_style = config.DEFAULT_WRITING_STYLE + "\n"
        WRITING_STYLE_PATH.write_text(current_style, encoding="utf-8")

    edited_style = st.text_area(
        "Always-on writing style prompt",
        value=current_style,
        height=360,
        help="Changes apply to the next Draft Email Now / Draft All Unread run.",
    )
    if st.button("💾 Save writing style", type="primary"):
        if not edited_style.strip():
            st.error("Writing style cannot be empty.")
        else:
            WRITING_STYLE_PATH.write_text(edited_style.rstrip() + "\n", encoding="utf-8")
            st.success("Writing style saved. Future drafts will use it immediately.")

with template_tab:
    st.subheader("Response template library")
    templates = load_templates()
    categories, active_categories = load_category_settings(templates)
    if not categories:
        categories = ["General"]
        active_categories = ["General"]
    st.caption(
        f"{len(templates)} templates across {len(categories)} categories · "
        f"{len(active_categories)} categories available to Gemini"
    )
    create_category_option = "➕ Create a new category…"

    if "gemini_categories" not in st.session_state:
        st.session_state["gemini_categories"] = list(active_categories)
    else:
        st.session_state["gemini_categories"] = [
            category
            for category in st.session_state["gemini_categories"]
            if category in categories
        ]

    select_all_col, clear_all_col, _ = st.columns([1, 1, 4])
    if select_all_col.button("Select all categories"):
        st.session_state["gemini_categories"] = list(categories)
    if clear_all_col.button("Clear all"):
        st.session_state["gemini_categories"] = []

    selected_active_categories = st.multiselect(
        "Categories available to Gemini",
        options=categories,
        key="gemini_categories",
        help=(
            "Gemini receives every response template inside the selected categories. "
            "Templates in other categories stay saved but are excluded."
        ),
    )
    if st.button("Save category selection"):
        save_templates(templates, categories, selected_active_categories)
        st.success("Gemini context categories updated.")
        st.rerun()

    st.divider()
    if not templates:
        st.info("No response templates exist yet. Add the first one below.")
    else:
        template_ids = [str(template["id"]) for template in templates]

        def _template_label(template_id: str) -> str:
            template = next(
                item for item in templates if str(item["id"]) == template_id
            )
            return f"{template.get('category', 'General')} — {template['name']}"

        selected_id = st.selectbox(
            "Select a template to edit",
            options=template_ids,
            format_func=_template_label,
        )
        selected_index = next(
            index
            for index, template in enumerate(templates)
            if str(template["id"]) == selected_id
        )
        selected = templates[selected_index]
        edited_name = st.text_input(
            "Template name / customer question",
            value=selected.get("name", ""),
            key=f"template_name_{selected_id}",
        )
        selected_category = selected.get("category", "General")
        edited_category = st.selectbox(
            "Category",
            options=categories,
            index=categories.index(selected_category),
            key=f"template_category_{selected_id}",
        )
        edited_content = st.text_area(
            "Approved response",
            value=selected.get("content", ""),
            height=320,
            key=f"template_content_{selected_id}",
        )
        save_col, delete_col, _ = st.columns([1, 1, 4])
        if save_col.button("💾 Save", type="primary", key=f"save_template_{selected_id}"):
            if not edited_name.strip() or not edited_content.strip():
                st.error("Template name and response are required.")
            else:
                selected["name"] = edited_name
                selected["category"] = edited_category
                selected["content"] = edited_content
                save_templates(templates, categories, active_categories)
                st.success("Template updated.")
                st.rerun()
        if delete_col.button("Delete", key=f"delete_template_{selected_id}"):
            del templates[selected_index]
            save_templates(templates, categories, active_categories)
            st.rerun()

    st.divider()
    with st.expander("Add a new template"):
        new_name = st.text_input("Template name / customer question", key="new_name")
        new_category_choice = st.selectbox(
            "Category",
            options=[*categories, create_category_option],
            key="new_template_category",
        )
        inline_category = ""
        if new_category_choice == create_category_option:
            inline_category = st.text_input(
                "New category name", key="inline_category_name"
            )
        new_content = st.text_area("Approved response", key="new_content", height=220)
        if st.button("Add template", type="primary"):
            category_to_use = (
                inline_category.strip()
                if new_category_choice == create_category_option
                else new_category_choice
            )
            category_exists = category_to_use.casefold() in {
                category.casefold() for category in categories
            }
            if not new_name.strip() or not new_content.strip():
                st.error("Template name and response are required.")
            elif not category_to_use:
                st.error("Enter a name for the new category.")
            elif new_category_choice == create_category_option and category_exists:
                st.error("That category already exists. Select it from the dropdown.")
            else:
                if not category_exists:
                    categories.append(category_to_use)
                    active_categories.append(category_to_use)
                    st.session_state["gemini_categories"] = list(active_categories)
                templates.append(
                    {
                        "id": "",
                        "name": new_name,
                        "category": category_to_use,
                        "content": new_content,
                        "active": True,
                    }
                )
                save_templates(templates, categories, active_categories)
                st.rerun()

    if templates:
        st.download_button(
            "⬇️ Export templates as Excel",
            data=export_excel(templates),
            file_name="email_response_templates.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )
