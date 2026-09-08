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

LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


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


def build_authorization_url(state: str) -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return url


def exchange_code(code: str) -> dict:
    flow = Flow.from_client_config(_client_config(), scopes=None, redirect_uri=redirect_uri())
    flow.fetch_token(code=code)
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


def build_login_authorization_url(state: str) -> str:
    flow = Flow.from_client_config(_login_client_config(), scopes=LOGIN_SCOPES, redirect_uri=login_redirect_uri())
    url, _ = flow.authorization_url(
        access_type="online",
        include_granted_scopes="true",
        prompt="select_account",
        state=state,
    )
    return url


def exchange_login_code(code: str) -> dict:
    """Exchange a login-flow auth code for the user's email/name/picture."""
    flow = Flow.from_client_config(_login_client_config(), scopes=LOGIN_SCOPES, redirect_uri=login_redirect_uri())
    flow.fetch_token(code=code)
    r = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {flow.credentials.token}"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return {"email": data.get("email"), "name": data.get("name"), "picture": data.get("picture")}


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
