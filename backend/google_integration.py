"""Google Drive + Calendar OAuth and helpers."""
import os
import logging
import requests
from datetime import datetime, timezone
from typing import Optional
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Google's token response can reorder/add scopes (e.g. implicit "openid") vs what
# we requested. oauthlib treats that as an error unless this is set — without it,
# Flow.fetch_token() raises "Scope has changed" on an otherwise successful exchange.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.events",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

# Login now requests the same scopes as the Drive/Calendar integration, so signing in
# with Google also connects Workspace and auto-creates the mAIPAL folder in one step.
LOGIN_SCOPES = SCOPES + ["https://www.googleapis.com/auth/userinfo.profile"]


def redirect_uri() -> str:
    return f"{os.environ['APP_BASE_URL']}/api/integrations/google/callback"


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID")) and bool(os.environ.get("GOOGLE_CLIENT_SECRET"))


def _client_config():
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri()],
        }
    }


def build_authorization_url(state: str) -> tuple[str, str]:
    """Returns (authorization_url, code_verifier) — see build_login_authorization_url
    for why the verifier must be persisted (keyed by state) and passed to exchange_code."""
    verifier, challenge = _generate_pkce_pair()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return url, verifier


def exchange_code(code: str, code_verifier: str) -> dict:
    flow = Flow.from_client_config(_client_config(), scopes=None, redirect_uri=redirect_uri())
    flow.fetch_token(code=code, code_verifier=code_verifier)
    c = flow.credentials
    return {
        "access_token": c.token,
        "refresh_token": c.refresh_token,
        "token_uri": c.token_uri,
        "client_id": c.client_id,
        "client_secret": c.client_secret,
        "scopes": list(c.scopes or []),
        "expiry": c.expiry.isoformat() if c.expiry else None,
    }


def _credentials_from_doc(doc: dict) -> Credentials:
    return Credentials(
        token=doc["access_token"],
        refresh_token=doc.get("refresh_token"),
        token_uri=doc["token_uri"],
        client_id=doc["client_id"],
        client_secret=doc["client_secret"],
        scopes=doc.get("scopes"),
    )


def login_redirect_uri() -> str:
    return f"{os.environ['APP_BASE_URL']}/api/auth/google/callback"


def _login_client_config():
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [login_redirect_uri()],
        }
    }


def _generate_pkce_pair() -> tuple[str, str]:
    import base64
    import hashlib
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_login_authorization_url(state: str) -> tuple[str, str]:
    """Returns (authorization_url, code_verifier). The verifier must be persisted
    (keyed by state) and passed back into exchange_login_code — Google's client
    requires PKCE, and the code_verifier can't be recovered from the callback alone."""
    verifier, challenge = _generate_pkce_pair()
    flow = Flow.from_client_config(_login_client_config(), scopes=LOGIN_SCOPES, redirect_uri=login_redirect_uri())
    url, _ = flow.authorization_url(
        # offline + consent so we reliably get a refresh_token to use Drive/Calendar
        # later, not just at the moment of login.
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account consent",
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return url, verifier


def exchange_login_code(code: str, code_verifier: str) -> dict:
    """Exchange a login-flow auth code for the user's profile info AND Drive/Calendar
    credentials (login requests the same scopes as the Workspace integration)."""
    flow = Flow.from_client_config(_login_client_config(), scopes=LOGIN_SCOPES, redirect_uri=login_redirect_uri())
    flow.fetch_token(code=code, code_verifier=code_verifier)
    c = flow.credentials
    r = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {c.token}"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return {
        "email": data.get("email"),
        "name": data.get("name"),
        "picture": data.get("picture"),
        "credentials": {
            "access_token": c.token,
            "refresh_token": c.refresh_token,
            "token_uri": c.token_uri,
            "client_id": c.client_id,
            "client_secret": c.client_secret,
            "scopes": list(c.scopes or []),
            "expiry": c.expiry.isoformat() if c.expiry else None,
        } if c.refresh_token else None,
    }


async def get_credentials(db, user_id: str) -> Optional[Credentials]:
    doc = await db.integrations.find_one({"user_id": user_id, "provider": "google"}, {"_id": 0})
    if not doc:
        return None
    creds = _credentials_from_doc(doc)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        await db.integrations.update_one(
            {"user_id": user_id, "provider": "google"},
            {"$set": {
                "access_token": creds.token,
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    return creds


async def ensure_maipal_folder(db, user_id: str, creds: Credentials) -> str:
    doc = await db.integrations.find_one({"user_id": user_id, "provider": "google"}, {"_id": 0})
    if doc and doc.get("drive_folder_id"):
        return doc["drive_folder_id"]
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    # search first
    q = "name='mAIPAL' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        folder_id = files[0]["id"]
    else:
        meta = {"name": "mAIPAL", "mimeType": "application/vnd.google-apps.folder"}
        folder = service.files().create(body=meta, fields="id").execute()
        folder_id = folder["id"]
    await db.integrations.update_one(
        {"user_id": user_id, "provider": "google"},
        {"$set": {"drive_folder_id": folder_id}},
    )
    return folder_id


async def list_subfolders(db, user_id: str, creds: Credentials) -> list:
    """First-level subfolders directly inside the user's mAIPAL folder."""
    parent_id = await ensure_maipal_folder(db, user_id, creds)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
    return res.get("files", [])


async def find_or_create_subfolder(db, user_id: str, creds: Credentials, name: str) -> str:
    """Find (or create) a subfolder by name directly inside mAIPAL. Returns its Drive file id."""
    parent_id = await ensure_maipal_folder(db, user_id, creds)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    safe_name = name.replace("'", "\\'")
    q = f"name='{safe_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def upload_file_to_folder(creds: Credentials, folder_id: str, tmp_path: str, filename: str, content_type: Optional[str]) -> dict:
    from googleapiclient.http import MediaFileUpload
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(tmp_path, mimetype=content_type or "application/octet-stream")
    meta = {"name": filename or "file", "parents": [folder_id]}
    created = service.files().create(body=meta, media_body=media, fields="id, webViewLink, name").execute()
    return {"file_id": created["id"], "web_view_link": created.get("webViewLink"), "name": created["name"]}


async def create_calendar_event(creds: Credentials, title: str, description: str = "", due_date: Optional[str] = None) -> str:
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    if due_date:
        # All-day event on due_date
        event = {
            "summary": title,
            "description": description or "",
            "start": {"date": due_date},
            "end": {"date": due_date},
        }
    else:
        now = datetime.now(timezone.utc).isoformat()
        event = {
            "summary": title,
            "description": description or "",
            "start": {"dateTime": now},
            "end": {"dateTime": now},
        }
    created = service.events().insert(calendarId="primary", body=event).execute()
    return created["id"]


async def delete_calendar_event(creds: Credentials, event_id: str):
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
    except Exception as e:
        logger.warning(f"delete event failed: {e}")
