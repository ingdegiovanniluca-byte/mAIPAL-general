"""Microsoft account (personal outlook.com/hotmail or work/school Microsoft 365) via
Microsoft Graph: OneDrive for files and the Outlook calendar for tasks - the Microsoft
counterpart of google_integration.py.

Setup (once, free): register an app in Microsoft Entra ID (portal.azure.com -> App
registrations), "Accounts in any organizational directory and personal Microsoft accounts",
Web redirect URI = <APP_BASE_URL>/api/integrations/microsoft/callback, then put in .env:
MS_CLIENT_ID, MS_CLIENT_SECRET (and optionally MS_TENANT, default "common").

Least privilege: files go only into the app's own OneDrive folder (Files.ReadWrite.AppFolder
-> "Apps/mAIPAL" on personal accounts), and the calendar scope only manages events.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlencode

import httpx

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["offline_access", "openid", "email", "User.Read", "Files.ReadWrite.AppFolder", "Calendars.ReadWrite"]
EVENT_TIMEZONE = "W. Europe Standard Time"  # Europe/Rome in Windows time-zone naming (what Graph expects)
SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024
CHUNK = 320 * 1024 * 16  # upload-session chunks must be multiples of 320 KiB


def is_configured() -> bool:
    return bool(os.environ.get("MS_CLIENT_ID")) and bool(os.environ.get("MS_CLIENT_SECRET"))


def _tenant() -> str:
    return os.environ.get("MS_TENANT") or "common"


def redirect_uri() -> str:
    return f"{os.environ['APP_BASE_URL']}/api/integrations/microsoft/callback"


def authorization_url(state: str) -> str:
    q = urlencode({
        "client_id": os.environ["MS_CLIENT_ID"], "response_type": "code", "redirect_uri": redirect_uri(),
        "response_mode": "query", "scope": " ".join(SCOPES), "state": state, "prompt": "select_account",
    })
    return f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/authorize?{q}"


async def _token_request(data: dict) -> dict:
    data = {**data, "client_id": os.environ["MS_CLIENT_ID"], "client_secret": os.environ["MS_CLIENT_SECRET"],
            "scope": " ".join(SCOPES)}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/token", data=data)
    if r.status_code != 200:
        raise RuntimeError(f"Microsoft token error {r.status_code}: {r.text[:300]}")
    j = r.json()
    return {
        "access_token": j["access_token"],
        "refresh_token": j.get("refresh_token"),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(j.get("expires_in", 3600)))).isoformat(),
        "scopes": (j.get("scope") or "").split(),
    }


async def exchange_code(code: str) -> dict:
    return await _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})


async def get_token(db, user_id: str) -> Optional[str]:
    """A valid access token for the user's connected Microsoft account (refreshed when
    about to expire), or None when not connected."""
    doc = await db.integrations.find_one({"user_id": user_id, "provider": "microsoft"}, {"_id": 0})
    if not doc:
        return None
    try:
        exp = datetime.fromisoformat(doc.get("expires_at"))
    except (TypeError, ValueError):
        exp = datetime.now(timezone.utc)
    if exp > datetime.now(timezone.utc) + timedelta(seconds=90):
        return doc["access_token"]
    if not doc.get("refresh_token"):
        return None
    fresh = await _token_request({"grant_type": "refresh_token", "refresh_token": doc["refresh_token"]})
    upd = {"access_token": fresh["access_token"], "expires_at": fresh["expires_at"],
           "updated_at": datetime.now(timezone.utc).isoformat()}
    if fresh.get("refresh_token"):
        upd["refresh_token"] = fresh["refresh_token"]
    await db.integrations.update_one({"user_id": user_id, "provider": "microsoft"}, {"$set": upd})
    return fresh["access_token"]


async def _graph(token: str, method: str, path: str, **kw) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}", **kw.pop("headers", {})}
    async with httpx.AsyncClient(timeout=60) as c:
        return await c.request(method, path if path.startswith("http") else f"{GRAPH}{path}", headers=headers, **kw)


async def get_account_email(token: str) -> Optional[str]:
    r = await _graph(token, "GET", "/me")
    if r.status_code != 200:
        return None
    j = r.json()
    return j.get("mail") or j.get("userPrincipalName")


# ======================= OneDrive (app folder) =======================
async def _approot_id(db, user_id: str, token: str) -> str:
    doc = await db.integrations.find_one({"user_id": user_id, "provider": "microsoft"}, {"_id": 0, "approot_id": 1})
    if doc and doc.get("approot_id"):
        return doc["approot_id"]
    r = await _graph(token, "GET", "/me/drive/special/approot")
    r.raise_for_status()
    root_id = r.json()["id"]
    await db.integrations.update_one({"user_id": user_id, "provider": "microsoft"}, {"$set": {"approot_id": root_id}})
    return root_id


async def list_folders(db, user_id: str, token: str) -> list:
    root = await _approot_id(db, user_id, token)
    r = await _graph(token, "GET", f"/me/drive/items/{root}/children?$top=200&$select=id,name,folder")
    r.raise_for_status()
    return [{"id": i["id"], "name": i["name"]} for i in r.json().get("value", []) if "folder" in i]


async def find_or_create_folder(db, user_id: str, token: str, name: Optional[str]) -> str:
    """A first-level folder inside the app folder (the app folder itself when name is None)."""
    root = await _approot_id(db, user_id, token)
    if not name:
        return root
    for f in await list_folders(db, user_id, token):
        if f["name"].strip().lower() == name.strip().lower():
            return f["id"]
    r = await _graph(token, "POST", f"/me/drive/items/{root}/children",
                     json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"})
    r.raise_for_status()
    return r.json()["id"]


async def item_web_url(token: str, item_id: str) -> Optional[str]:
    """The OneDrive web address of a file or folder (to open it from the app)."""
    r = await _graph(token, "GET", f"/me/drive/items/{item_id}?$select=webUrl")
    r.raise_for_status()
    return r.json().get("webUrl")


async def upload_file(token: str, folder_id: str, tmp_path: str, filename: str, content_type: Optional[str]) -> dict:
    name = filename or "file"
    size = os.path.getsize(tmp_path)
    target = f"/me/drive/items/{folder_id}:/{quote(name)}:"
    if size <= SIMPLE_UPLOAD_MAX:
        with open(tmp_path, "rb") as fh:
            r = await _graph(token, "PUT", f"{target}/content?@microsoft.graph.conflictBehavior=rename",
                             content=fh.read(), headers={"Content-Type": content_type or "application/octet-stream"})
        r.raise_for_status()
        j = r.json()
    else:
        r = await _graph(token, "POST", f"{target}/createUploadSession",
                         json={"item": {"@microsoft.graph.conflictBehavior": "rename"}})
        r.raise_for_status()
        upload_url = r.json()["uploadUrl"]
        j = {}
        async with httpx.AsyncClient(timeout=120) as c:
            with open(tmp_path, "rb") as fh:
                start = 0
                while start < size:
                    chunk = fh.read(CHUNK)
                    end = start + len(chunk) - 1
                    rr = await c.put(upload_url, content=chunk, headers={
                        "Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{size}"})
                    if rr.status_code not in (200, 201, 202):
                        raise RuntimeError(f"OneDrive upload failed {rr.status_code}: {rr.text[:200]}")
                    if rr.status_code in (200, 201):
                        j = rr.json()
                    start = end + 1
    return {"file_id": j.get("id"), "web_view_link": j.get("webUrl"), "name": j.get("name") or name}


# ======================= Outlook calendar =======================
def event_body(title: str, description: str = "", due_date: Optional[str] = None, due_time: Optional[str] = None,
               duration_minutes: Optional[int] = None, recurrence: Optional[dict] = None) -> dict:
    """Graph event JSON for a task (timed, or all-day without a time), optionally recurring."""
    duration = duration_minutes or 30
    if due_date and due_time:
        start = datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M")
        end = start + timedelta(minutes=duration)
        ev = {"start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": EVENT_TIMEZONE},
              "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": EVENT_TIMEZONE}}
    elif due_date:
        d = datetime.strptime(due_date, "%Y-%m-%d")
        ev = {"isAllDay": True,
              "start": {"dateTime": d.strftime("%Y-%m-%dT00:00:00"), "timeZone": EVENT_TIMEZONE},
              "end": {"dateTime": (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"), "timeZone": EVENT_TIMEZONE}}
    else:
        now = datetime.now(timezone.utc)
        ev = {"start": {"dateTime": now.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
              "end": {"dateTime": (now + timedelta(minutes=duration)).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}}
    ev.update({"subject": title or "Task mAIPAL", "body": {"contentType": "text", "content": description or ""}})
    if recurrence and (due_date or due_time):
        ev["recurrence"] = recurrence
    return ev


async def create_event(token: str, **kw) -> str:
    r = await _graph(token, "POST", "/me/events", json=event_body(**kw))
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Outlook event error {r.status_code}: {r.text[:300]}")
    return r.json()["id"]


async def delete_event(token: str, event_id: str):
    r = await _graph(token, "DELETE", f"/me/events/{event_id}")
    if r.status_code not in (200, 204, 404):
        logger.warning(f"outlook delete event failed {r.status_code}: {r.text[:200]}")
