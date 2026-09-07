# DITTO AI Email Composer

Internal tool for DITTO’s CSM (Anita) to draft warm, on-brand replies to customer emails — powered by **Gmail**, **Gemini**, and an editable **template + writing-style library**.

Replies are saved as **Gmail drafts only**. Nothing is sent automatically. Anita reviews and sends from Gmail.

---

## Where it is deployed

| Item | Value |
| --- | --- |
| **Hosting** | [Streamlit Community Cloud](https://share.streamlit.io) |
| **Live app** | [https://email-compose.streamlit.app/](https://email-compose.streamlit.app/) |
| **GitHub** | [`Ditto-Daily/Email-compose`](https://github.com/Ditto-Daily/Email-compose) |
| **Branch / entrypoint** | `main` → `app.py` |
| **Inbox** | Company Gmail (`hello@dittodaily.com`) via OAuth |
| **Access** | App password gate (`APP_PASSWORD` in Streamlit secrets) |

CSM day-to-day needs: **[the live app](https://email-compose.streamlit.app/) + app password**. Everything else (templates, style, drafts) is in the dashboard / Gmail.

Detailed secrets setup: see [`DEPLOY.md`](./DEPLOY.md).

---

## What it does

1. Loads **unread Primary inbox** mail (excludes Promotions / Social / most Updates).
2. Always includes Shopify contact-form mail from **`mailer@shopify.com`** (even when Gmail tags it as Updates).
3. On **Draft** or **Draft All**, calls Gemini with:
   - active **template library** (by category)
   - **writing style** rules (greeting, sign-off, kisses `x`)
4. Creates a **Gmail draft** in the same thread.
5. Tracks drafted message IDs in SQLite so the same mail is not drafted twice.

Dashboard tabs:

- **Inbox** — refresh unread, draft one-by-one or Draft All  
- **Writing Style** — always-on tone / greeting / sign-off rules  
- **Template Settings** — categories, Q&A templates, which categories Gemini may use, Excel export  

---

## Architecture

```text
┌─────────────────┐     unread mail      ┌──────────────────┐
│  Gmail API      │ ───────────────────► │  Streamlit app   │
│  (hello@…)      │                      │  app.py          │
└────────▲────────┘                      └────────┬─────────┘
         │ draft create                           │
         │                                        ▼
         │                               ┌──────────────────┐
         │                               │  worker.py       │
         │                               │  single / batch  │
         │                               └────────┬─────────┘
         │                                        │
         │         draft body                     ▼
         │                               ┌──────────────────┐
         └───────────────────────────────│  llm_engine.py   │
                                         │  Gemini          │
                                         └────────┬─────────┘
                                                  │
                         ┌────────────────────────┼────────────────────────┐
                         ▼                        ▼                        ▼
              templates/templates.json   templates/writing_style.txt   tracker.db
              templates/standard.txt     (always in system prompt)     (draft log)
```

| Module | Role |
| --- | --- |
| `app.py` | Streamlit UI, password gate, Inbox / Style / Templates |
| `gmail_client.py` | OAuth, unread list, create draft |
| `llm_engine.py` | Single + batch Gemini drafting |
| `worker.py` | Orchestrates draft → Gmail → DB (`BATCH_SIZE = 20`) |
| `template_store.py` | Load/save templates, categories, Excel import/export |
| `config.py` | Paths, model name, Streamlit secrets → env/files |
| `db.py` | SQLite tracking of drafted messages |

---

## Batching & token optimisation

Templates are large. Sending the full library **once per email** wastes tokens and hits rate limits.

### Draft All (batch path)

1. Collect undrafted unread emails.
2. Split into chunks of **`BATCH_SIZE = 20`** (`worker.py`).
3. For each chunk, **one** Gemini call:
   - **System instruction** = writing style + full active template library (**once**)
   - **User message** = up to 20 email bodies with Gmail message IDs
   - **Response** = JSON map `{ message_id: reply_body }`
4. Create individual Gmail drafts from that map.

### Why this matters

| Approach | Template library in prompt | Gemini calls for 40 emails |
| --- | --- | --- |
| Naïve (1 call / email) | ×40 | 40 |
| **Batch (current)** | ×2 (once per chunk of 20) | **2** |

Single-email **Draft** still uses one call (needed for one-off replies). Use **Draft All** when clearing a busy inbox.

### Other cost / quality controls

- Only **active categories** are included in Gemini context.
- Temperature `0.3` for steadier, on-template replies.
- Promotions / Social / generic Updates stay out of the queue (less junk drafted).
- Shopify `mailer@shopify.com` is allow-listed so contact-form tickets still appear.

---

## Local development

```bash
cd ai-email-assistant
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# One-time Gmail OAuth (creates token.json) — not in HEADLESS mode
# Place OAuth desktop client as credentials.json

export GEMINI_API_KEY="…"
# optional: export APP_PASSWORD="…"
# optional: export GEMINI_MODEL="gemini-3.5-flash"

streamlit run app.py
```

**Never commit:** `credentials.json`, `token.json`, `.streamlit/secrets.toml`, `tracker.db`, `.env`.

Cloud deploy expects those Gmail files **pasted into Streamlit Secrets** as `google_credentials_json` / `google_token_json` (see `DEPLOY.md`).

---

## Template & style model

- **Templates** = approved Q&A / reply patterns, grouped by **category**.  
  Gemini only sees categories marked available in Template Settings.
- **Writing style** = separate always-on rules (e.g. `Hello {name}`, sign-off “All the best, Anita”, add `x` if the customer used kisses).
- Library is stored in `templates/templates.json` (+ generated `standard.txt` context).
- Bulk refresh historically came from Excel import; day-to-day edits are meant to happen **in the dashboard**.

---

## Security notes

- Repo is under the **`Ditto-Daily`** org. Prefer **private** visibility so source isn’t world-readable.
- Secrets live in **Streamlit Secrets**, not in git.
- Gmail scopes are limited: `gmail.readonly` + `gmail.drafts.create` (no send scope).
- App password protects the Streamlit UI; Gmail still requires Anita’s normal Gmail access to send.

---

## Future expansion ideas

Prioritise by CSM pain, not by “AI for AI’s sake.”

| Idea | Why |
| --- | --- |
| **Private GitHub + tighter Streamlit sharing** | Company IP + inbox tooling shouldn’t be public by default |
| **Dashboard Excel import with preview** | Safer bulk refresh without local scripts |
| **Parse Shopify contact-form Name / Email / Comment** | Draft To: real customer instead of `mailer@shopify.com` (Anita can still edit To today) |
| **Multi-CSM / multi-inbox** | Style + templates + OAuth per person |
| **Feedback loop on sent edits** | Learn which drafts Anita rewrites (V1 intentionally avoided auto-learning) |
| **Richer QA** | Spot-check drafts vs category templates before create |
| **Observability** | Log tokens / latency / failure rates per Draft All run |
| **Optional send + label workflow** | Only if product explicitly wants less Gmail friction |
| **Stronger medical / claims guardrails** | Extra system rules or blocked phrases for regulated topics |

---

## Repo layout

```text
ai-email-assistant/
├── app.py                 # Streamlit dashboard
├── worker.py              # Draft / Draft All orchestration
├── llm_engine.py          # Gemini single + batch
├── gmail_client.py        # Gmail read + draft
├── template_store.py      # Templates + categories + Excel
├── config.py              # Config + secrets bootstrap
├── db.py                  # Draft tracking
├── templates/             # Template JSON, style rules, standard context
├── requirements.txt
├── DEPLOY.md              # Streamlit Cloud secrets checklist
└── README.md              # You are here
```

---

## Ownership

Built for **Ditto Daily** CSM workflows. Questions about templates/tone → Anita / brand. Questions about deploy, Gemini, or Gmail OAuth → engineering / repo admins on `Ditto-Daily`.
