# Streamlit Community Cloud deploy

Anita only needs the Streamlit URL + the app password.

## 1. Push this folder to GitHub

Do **not** commit `credentials.json`, `token.json`, or `.env`.

## 2. Create the Streamlit app

1. Go to https://share.streamlit.io
2. New app → pick your GitHub repo
3. Main file path: `app.py`
4. Deploy

## 3. Add secrets (Streamlit app → Settings → Secrets)

Paste this shape (replace the values):

```toml
GEMINI_API_KEY = "your-gemini-key"
# Tried in order. If one is busy or out of free quota, the next one is used.
GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
APP_PASSWORD = "shared-password-for-anita"

google_credentials_json = """
PASTE_FULL_credentials.json_HERE
"""

google_token_json = """
PASTE_FULL_token.json_HERE
"""
```

Use the existing local `credentials.json` and `token.json` from this machine for the first deploy.

## 4. Share with Anita

- App URL from Streamlit Cloud
- `APP_PASSWORD`

## Switching to company Gmail later

1. On a laptop, auth once with the company inbox to create a new `token.json`
2. Update Streamlit secrets:
   - `google_credentials_json`
   - `google_token_json`
3. Reboot the app

No code changes needed.
