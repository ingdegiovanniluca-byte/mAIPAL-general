from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header, UploadFile, File, Form
from fastapi.responses import StreamingResponse, RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import secrets
import tempfile
import asyncio
import httpx
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any
from datetime import datetime, timezone, timedelta
import bcrypt

from llm_integrations import LlmChat, UserMessage, TextDelta, StreamDone, ImageContent, OpenAISpeechToText

import google_integration as gi
import telegram_bot as tg
import embeddings as emb
import news_service

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Passed as `api_key=` into LlmChat/OpenAISpeechToText for interface compatibility, but
# llm_integrations.py ignores it and reads ANTHROPIC_API_KEY / OPENAI_API_KEY directly.
EMERGENT_LLM_KEY = os.environ.get('ANTHROPIC_API_KEY')

# ============ ADMIN / WHITELIST ============
ADMIN_EMAIL = (os.environ.get('ADMIN_EMAIL') or 'ingdegiovanniluca@gmail.com').strip().lower()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============ MODELS ============
class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    onboarded: bool = False
    profession: Optional[str] = None
    sector: Optional[str] = None
    verticals: List[str] = []
    interests: List[str] = []
    tone: Optional[str] = "informale"
    home_address: Optional[str] = None
    work_address: Optional[str] = None
    created_at: Optional[str] = None
    telegram_chat_id: Optional[int] = None
    role: Optional[str] = "user"
    org_id: Optional[str] = None
    org_role: Optional[Literal["owner", "member"]] = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class OnboardingPayload(BaseModel):
    profession: Optional[str] = ""
    sector: Optional[str] = ""
    verticals: List[str] = []
    interests: List[str] = []
    tone: Optional[str] = "informale"
    home_address: Optional[str] = ""
    work_address: Optional[str] = ""


class ProfilePatch(BaseModel):
    profession: Optional[str] = None
    sector: Optional[str] = None
    verticals: Optional[List[str]] = None
    interests: Optional[List[str]] = None
    tone: Optional[str] = None
    home_address: Optional[str] = None
    work_address: Optional[str] = None


class ChatRequest(BaseModel):
    action: Literal["info_upload", "info_request", "task_todo", "journal"]
    content: str
    filters: Optional[dict] = None
    conv_id: Optional[str] = None


class Task(BaseModel):
    id: str
    user_id: str
    org_id: Optional[str] = None
    visibility: Literal["private", "org"] = "private"
    title: str
    description: Optional[str] = ""
    due_date: Optional[str] = None
    priority: Literal["alta", "media", "bassa"] = "media"
    tags: List[str] = []
    notes: Optional[str] = ""
    calendar_synced: bool = False
    created_at: str


class TaskUpsert(BaseModel):
    title: str
    description: Optional[str] = ""
    due_date: Optional[str] = None
    priority: Literal["alta", "media", "bassa"] = "media"
    tags: List[str] = []
    notes: Optional[str] = ""
    visibility: Literal["private", "org"] = "private"


class Todo(BaseModel):
    id: str
    user_id: str
    title: str
    description: Optional[str] = ""
    status: Literal["da_fare", "in_corso", "fatto"] = "da_fare"
    completion_percent: int = 0
    priority: Optional[Literal["alta", "media", "bassa"]] = None
    tags: List[str] = []
    notes: Optional[str] = ""
    created_at: str


class TodoUpsert(BaseModel):
    title: str
    description: Optional[str] = ""
    status: Literal["da_fare", "in_corso", "fatto"] = "da_fare"
    completion_percent: int = 0
    priority: Optional[Literal["alta", "media", "bassa"]] = None
    tags: List[str] = []
    notes: Optional[str] = ""


# ---- Organizzazione ----
class OrgCreatePayload(BaseModel):
    name: str


class OrgRenamePayload(BaseModel):
    name: str


class OrgJoinPayload(BaseModel):
    code: str


# ---- Collezioni (liste personalizzate: clienti, esercizi, commesse, ecc.) ----
class CollectionFieldDef(BaseModel):
    key: str
    label: str
    type: Literal["text", "textarea", "number", "date", "select", "phone", "email", "reference"] = "text"
    options: Optional[List[str]] = None
    ref_collection_id: Optional[str] = None


class CollectionCreatePayload(BaseModel):
    name: str
    icon: Optional[str] = None
    fields: List[CollectionFieldDef]
    visibility: Literal["private", "org"] = "private"


class CollectionUpdatePayload(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    fields: Optional[List[CollectionFieldDef]] = None
    visibility: Optional[Literal["private", "org"]] = None


class CollectionItemPayload(BaseModel):
    data: dict
    visibility: Optional[Literal["private", "org"]] = None


# ============ AUTH HELPERS ============
async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> User:
    token = request.cookies.get("session_token")
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    user_doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user_doc)


def _visible_query(current: User) -> dict:
    """Mongo filter matching a user's own documents plus anything shared with their
    organization. Used for tasks and collections (the two resource types with sharing)."""
    if current.org_id:
        return {"$or": [{"user_id": current.user_id}, {"org_id": current.org_id, "visibility": "org"}]}
    return {"user_id": current.user_id}


def _editable_query(current: User) -> dict:
    """Same as _visible_query but meant for mutating endpoints: any org-mate can edit/
    complete/delete a document shared with the org, not just its creator."""
    return _visible_query(current)


def _stamp_owner_fields(doc: dict, current: User):
    doc["user_id"] = current.user_id
    doc["org_id"] = current.org_id
    if doc.get("visibility") == "org" and not current.org_id:
        doc["visibility"] = "private"


# ============ AUTH ROUTES ============
LOGIN_STATE_TTL_MIN = 10


def _set_session_cookie(response: Response, session_token: str):
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=7 * 24 * 60 * 60,
    )


async def _create_session(user_id: str) -> str:
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc),
    })
    return session_token


async def _check_whitelist(email: str) -> tuple[bool, bool]:
    """Returns (is_admin_seed, is_allowed). Admins are always allowed."""
    is_admin_seed = email == ADMIN_EMAIL
    if is_admin_seed:
        return True, True
    allowed = await db.allowed_emails.find_one({"email": email})
    return False, bool(allowed)


@api_router.post("/auth/register")
async def register(payload: RegisterRequest, response: Response):
    email = (payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email non valida")
    if len(payload.password or "") < 8:
        raise HTTPException(status_code=400, detail="La password deve avere almeno 8 caratteri")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obbligatorio")

    is_admin_seed, allowed = await _check_whitelist(email)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "Il tuo account non è autorizzato ad accedere a mAIPAL. "
                f"Contatta l'amministratore ({ADMIN_EMAIL}) per essere aggiunto alla whitelist."
            ),
        )

    if await db.users.find_one({"email": email}, {"_id": 0}):
        raise HTTPException(status_code=409, detail="Un account con questa email esiste già. Prova ad accedere.")

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user_doc = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "picture": None,
        "password_hash": _hash_password(payload.password),
        "role": "admin" if is_admin_seed else "user",
        "onboarded": False,
        "profession": None,
        "sector": None,
        "verticals": [],
        "interests": [],
        "tone": "informale",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user_doc)

    session_token = await _create_session(user_id)
    _set_session_cookie(response, session_token)
    return {"user": User(**user_doc).model_dump()}


@api_router.post("/auth/login")
async def login(payload: LoginRequest, response: Response):
    email = (payload.email or "").strip().lower()
    user_doc = await db.users.find_one({"email": email}, {"_id": 0})
    if not user_doc or not user_doc.get("password_hash") or not _verify_password(payload.password, user_doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Email o password errati")

    session_token = await _create_session(user_doc["user_id"])
    _set_session_cookie(response, session_token)
    return {"user": User(**user_doc).model_dump()}


@api_router.get("/auth/google/login")
async def google_login():
    if not gi.is_configured():
        raise HTTPException(status_code=400, detail="Google OAuth non configurato (GOOGLE_CLIENT_ID/SECRET mancanti)")
    state = secrets.token_urlsafe(24)
    url, code_verifier = gi.build_login_authorization_url(state)
    await db.google_login_states.insert_one({
        "state": state,
        "code_verifier": code_verifier,
        "created_at": datetime.now(timezone.utc),
    })
    return RedirectResponse(url)


@api_router.get("/auth/google/callback")
async def google_login_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    base = os.environ["APP_BASE_URL"]
    if error or not code or not state:
        return RedirectResponse(f"{base}/?auth_error=denied")

    st = await db.google_login_states.find_one({"state": state}, {"_id": 0})
    if st:
        await db.google_login_states.delete_one({"state": state})
    created_at = st.get("created_at") if st else None
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if not st or not created_at or created_at < datetime.now(timezone.utc) - timedelta(minutes=LOGIN_STATE_TTL_MIN):
        return RedirectResponse(f"{base}/?auth_error=invalid_state")

    try:
        info = gi.exchange_login_code(code, st["code_verifier"])
    except Exception:
        logger.exception("Google login exchange failed")
        return RedirectResponse(f"{base}/?auth_error=oauth_failed")

    email = (info.get("email") or "").strip().lower()
    if not email:
        return RedirectResponse(f"{base}/?auth_error=no_email")

    is_admin_seed, allowed = await _check_whitelist(email)
    if not allowed:
        return RedirectResponse(f"{base}/?auth_error=not_whitelisted")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        # Ensure the admin role stays applied on every login for the admin email
        role_update = {"role": "admin"} if is_admin_seed else {}
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": info.get("name"), "picture": info.get("picture"), **role_update}},
        )
        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": info.get("name", ""),
            "picture": info.get("picture"),
            "role": "admin" if is_admin_seed else "user",
            "onboarded": False,
            "profession": None,
            "sector": None,
            "verticals": [],
            "interests": [],
            "tone": "informale",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(user_doc)

    # Best-effort: persist Drive/Calendar credentials and auto-create the mAIPAL folder.
    # Never blocks login — Workspace setup failing here just means the user connects
    # manually later from Impostazioni.
    creds_info = info.get("credentials")
    if creds_info and creds_info.get("refresh_token"):
        try:
            integration_doc = {
                **creds_info, "provider": "google", "user_id": user_id, "email": email,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.integrations.update_one(
                {"user_id": user_id, "provider": "google"},
                {"$set": integration_doc}, upsert=True,
            )
            creds = await gi.get_credentials(db, user_id)
            if creds:
                await gi.ensure_maipal_folder(db, user_id, creds)
        except Exception:
            logger.exception("Drive auto-setup at login failed")

    session_token = await _create_session(user_id)

    dest = f"{base}/dashboard" if user_doc.get("onboarded") else f"{base}/onboarding"
    response = RedirectResponse(dest)
    _set_session_cookie(response, session_token)
    return response


@api_router.get("/auth/me", response_model=User)
async def me(current: User = Depends(get_current_user)):
    return current


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


async def require_admin(current: User = Depends(get_current_user)) -> User:
    if (current.role or "user") != "admin":
        raise HTTPException(status_code=403, detail="Solo amministratori")
    return current


# ============ ADMIN: WHITELIST + USERS ============
class AllowlistItem(BaseModel):
    email: str
    notes: Optional[str] = ""


@api_router.get("/admin/allowlist")
async def admin_list_allowed(current: User = Depends(require_admin)):
    cursor = db.allowed_emails.find({}, {"_id": 0}).sort("added_at", -1)
    return await cursor.to_list(500)


@api_router.post("/admin/allowlist")
async def admin_add_allowed(item: AllowlistItem, current: User = Depends(require_admin)):
    email = (item.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email non valida")
    notes = (item.notes or "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.allowed_emails.update_one(
        {"email": email},
        {
            "$set": {"notes": notes, "email": email},
            "$setOnInsert": {"added_by": current.email, "added_at": now_iso},
        },
        upsert=True,
    )
    doc = await db.allowed_emails.find_one({"email": email}, {"_id": 0})
    return doc


@api_router.delete("/admin/allowlist/{email}")
async def admin_remove_allowed(email: str, current: User = Depends(require_admin)):
    email = (email or "").strip().lower()
    if email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Impossibile rimuovere l'amministratore")
    r = await db.allowed_emails.delete_one({"email": email})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Email non presente")
    return {"ok": True}


@api_router.get("/admin/users")
async def admin_list_users(current: User = Depends(require_admin)):
    users = await db.users.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Attach last session info
    out = []
    for u in users:
        last_sess = await db.user_sessions.find_one(
            {"user_id": u.get("user_id")},
            {"_id": 0, "created_at": 1, "expires_at": 1},
            sort=[("created_at", -1)],
        )
        out.append({**u, "last_session_at": last_sess.get("created_at").isoformat() if last_sess and hasattr(last_sess.get("created_at"), "isoformat") else (last_sess or {}).get("created_at")})
    return out


@api_router.post("/admin/users/{user_id}/revoke")
async def admin_revoke_user(user_id: str, current: User = Depends(require_admin)):
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if user.get("email") == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Impossibile revocare l'amministratore")
    # Remove from whitelist, drop all active sessions and mark the user as revoked
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.allowed_emails.delete_one({"email": user.get("email")})
    sessions = await db.user_sessions.delete_many({"user_id": user_id})
    await db.users.update_one({"user_id": user_id}, {"$set": {"revoked_at": now_iso, "revoked_by": current.email}})
    return {"ok": True, "email": user.get("email"), "sessions_removed": sessions.deleted_count}


@api_router.post("/admin/users/{user_id}/restore")
async def admin_restore_user(user_id: str, current: User = Depends(require_admin)):
    """Undo a revoke: put the email back in the whitelist and clear the revoked_at flag."""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    email = (user.get("email") or "").strip().lower()
    await db.allowed_emails.update_one(
        {"email": email},
        {"$set": {"email": email, "notes": "ripristinato dopo revoca"},
         "$setOnInsert": {"added_by": current.email, "added_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    await db.users.update_one({"user_id": user_id}, {"$unset": {"revoked_at": "", "revoked_by": ""}})
    return {"ok": True, "email": email}


@api_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, current: User = Depends(require_admin)):
    """Fully delete a user and every piece of data they own."""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if user.get("email") == ADMIN_EMAIL or user.get("role") == "admin":
        raise HTTPException(status_code=400, detail="Impossibile eliminare l'amministratore")

    counts = {}
    # per-user collections
    for coll in [
        "tasks", "todos", "journal_entries", "conversations",
        "kb_chunks", "kb_documents", "user_sessions",
    ]:
        r = await db[coll].delete_many({"user_id": user_id})
        counts[coll] = r.deleted_count
    # whitelist + user doc
    r = await db.allowed_emails.delete_one({"email": user.get("email")})
    counts["allowed_emails"] = r.deleted_count
    r = await db.users.delete_one({"user_id": user_id})
    counts["users"] = r.deleted_count
    return {"ok": True, "email": user.get("email"), "deleted": counts}


@api_router.post("/onboarding")
async def save_onboarding(payload: OnboardingPayload, current: User = Depends(get_current_user)):
    await db.users.update_one(
        {"user_id": current.user_id},
        {"$set": {
            "profession": payload.profession,
            "sector": payload.sector,
            "verticals": payload.verticals,
            "interests": payload.interests,
            "tone": payload.tone,
            "home_address": payload.home_address,
            "work_address": payload.work_address,
            "onboarded": True,
        }},
    )
    user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    return User(**user_doc)


@api_router.patch("/profile")
async def update_profile(payload: ProfilePatch, current: User = Depends(get_current_user)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        await db.users.update_one({"user_id": current.user_id}, {"$set": updates})
    user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    return User(**user_doc)


@api_router.post("/profile/avatar")
async def upload_avatar(file: UploadFile = File(...), current: User = Depends(get_current_user)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Il file deve essere un'immagine")
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Immagine troppo grande (max 2MB)")
    import base64 as _b64
    data_uri = f"data:{file.content_type};base64,{_b64.b64encode(contents).decode('ascii')}"
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"picture": data_uri}})
    user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    return User(**user_doc)


# ============ ORGANIZZAZIONE ============
def _gen_org_code() -> str:
    return secrets.token_hex(3).upper()  # es. "A1B2C3"


@api_router.post("/org")
async def create_org(payload: OrgCreatePayload, current: User = Depends(get_current_user)):
    if current.org_id:
        raise HTTPException(status_code=400, detail="Fai già parte di un'organizzazione. Esci prima di crearne una nuova.")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obbligatorio")
    org_id = f"org_{uuid.uuid4().hex[:12]}"
    org_doc = {
        "id": org_id,
        "name": name,
        "join_code": _gen_org_code(),
        "created_by": current.user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.organizations.insert_one(org_doc)
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"org_id": org_id, "org_role": "owner"}})
    org_doc.pop("_id", None)
    return org_doc


@api_router.get("/org")
async def get_org(current: User = Depends(get_current_user)):
    if not current.org_id:
        return None
    org = await db.organizations.find_one({"id": current.org_id}, {"_id": 0})
    if not org:
        return None
    members = await db.users.find(
        {"org_id": current.org_id}, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "picture": 1, "org_role": 1}
    ).to_list(200)
    org["members"] = members
    return org


@api_router.patch("/org")
async def rename_org(payload: OrgRenamePayload, current: User = Depends(get_current_user)):
    if not current.org_id or current.org_role != "owner":
        raise HTTPException(status_code=403, detail="Solo il proprietario dell'organizzazione può rinominarla")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obbligatorio")
    await db.organizations.update_one({"id": current.org_id}, {"$set": {"name": name}})
    return await db.organizations.find_one({"id": current.org_id}, {"_id": 0})


@api_router.post("/org/regenerate-code")
async def regenerate_org_code(current: User = Depends(get_current_user)):
    if not current.org_id or current.org_role != "owner":
        raise HTTPException(status_code=403, detail="Solo il proprietario può rigenerare il codice")
    new_code = _gen_org_code()
    await db.organizations.update_one({"id": current.org_id}, {"$set": {"join_code": new_code}})
    return {"join_code": new_code}


@api_router.post("/org/join")
async def join_org(payload: OrgJoinPayload, current: User = Depends(get_current_user)):
    if current.org_id:
        raise HTTPException(status_code=400, detail="Fai già parte di un'organizzazione. Esci prima di unirti a un'altra.")
    code = (payload.code or "").strip().upper()
    org = await db.organizations.find_one({"join_code": code}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Codice non valido")
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"org_id": org["id"], "org_role": "member"}})
    return org


@api_router.post("/org/leave")
async def leave_org(current: User = Depends(get_current_user)):
    if not current.org_id:
        raise HTTPException(status_code=400, detail="Non fai parte di un'organizzazione")
    if current.org_role == "owner":
        other_members = await db.users.count_documents({"org_id": current.org_id, "user_id": {"$ne": current.user_id}})
        if other_members > 0:
            raise HTTPException(
                status_code=400,
                detail="Non puoi uscire finché ci sono altri membri: rimuovili prima dalle impostazioni dell'organizzazione.",
            )
        await db.organizations.delete_one({"id": current.org_id})
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"org_id": None, "org_role": None}})
    return {"ok": True}


@api_router.delete("/org/members/{member_user_id}")
async def remove_org_member(member_user_id: str, current: User = Depends(get_current_user)):
    if not current.org_id or current.org_role != "owner":
        raise HTTPException(status_code=403, detail="Solo il proprietario può rimuovere membri")
    if member_user_id == current.user_id:
        raise HTTPException(status_code=400, detail="Non puoi rimuovere te stesso: usa 'esci dall'organizzazione'")
    await db.users.update_one({"user_id": member_user_id, "org_id": current.org_id}, {"$set": {"org_id": None, "org_role": None}})
    return {"ok": True}


# ============ LLM / CHAT ============
_IT_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
              "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _today_it_string() -> str:
    now = datetime.now(timezone.utc)
    return f"{_IT_WEEKDAYS[now.weekday()]} {now.day} {_IT_MONTHS[now.month - 1]} {now.year} (ISO: {now.date().isoformat()})"


def build_system_prompt(user: User, action: str) -> str:
    verticals = ", ".join(user.verticals) if user.verticals else "generico"
    interests = ", ".join(user.interests) if user.interests else "n/d"
    user_name = user.name or "l'utente"
    addr_parts = []
    if user.home_address: addr_parts.append(f"indirizzo casa: {user.home_address}")
    if user.work_address: addr_parts.append(f"indirizzo lavoro: {user.work_address}")
    addr = "; ".join(addr_parts)
    base = (
        f"Oggi è {_today_it_string()}. Usa SEMPRE questa data come riferimento per calcolare qualunque data "
        "relativa menzionata dall'utente (es. 'domani', 'dopodomani', 'lunedì prossimo', 'tra 3 giorni'). "
        f"Sei mAIPAL, un assistente personale AI (segretario digitale) per {user_name}. "
        f"Profilo: professione '{user.profession or 'n/d'}', settore '{user.sector or 'n/d'}', "
        f"verticali d'uso: {verticals}, interessi: {interests}. "
        + (addr + ". " if addr else "")
        + f"Tono di comunicazione: {user.tone or 'informale'}. "
        "Rispondi sempre in italiano, in modo chiaro, naturale e conciso. "
        "REGOLA CRITICA DI FORMATO: la parte visibile all'utente deve essere una conversazione naturale, "
        "SENZA mai includere JSON, blocchi di codice ```, tag XML, campi 'title/description/priority' o elenchi di metadati. "
        "Se devi produrre dati strutturati per il sistema, includili SOLO tra i marcatori speciali "
        "<<<META>>> e <<<END>>>: tutto ciò che è dentro NON verrà mostrato all'utente."
    )
    if action == "info_upload":
        base += (
            " L'utente sta caricando un'informazione. Conferma cosa hai memorizzato in modo naturale (1-3 frasi). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"...\", \"summary\": \"riassunto in 1 riga, max 140 caratteri\", \"tags\": [\"...\"]}<<<END>>>"
        )
    elif action == "info_request":
        base += (
            " L'utente ti sta ponendo una domanda. Se ti viene fornito un CONTESTO dalla knowledge base personale, "
            "usalo come fonte principale e rispondi in modo naturale (senza dire 'ecco il contesto', 'dal database'; parla come un assistente). "
            "Se il contesto è vuoto o non pertinente, indica gentilmente che non hai fonti dalla KB personale e rispondi con le tue conoscenze generali. "
            "Al termine, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"argomento in 3-6 parole\", \"summary\": \"riassunto naturale in 1 riga, max 140 caratteri, che descriva cosa hai risposto\"}<<<END>>>"
        )
    elif action == "task_todo":
        base += (
            " L'utente vuole salvare un task o un to-do. Scrivi UNA risposta di conferma naturale (1-2 frasi, es. "
            "'Perfetto, ho preso nota: ti ricorderò di chiamare Marco domani alle 15:30.'). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"breve titolo del task/todo\", \"summary\": \"riassunto in 1 riga max 140 caratteri\", \"description\": \"\", "
            "\"due_date\": \"YYYY-MM-DD o null\", \"due_time\": \"HH:MM o null\", \"duration_minutes\": \"numero di minuti o null\", "
            "\"reminder_minutes_before\": \"numero di minuti o null\", "
            "\"priority\": \"alta|media|bassa\", \"tags\": [\"...\"], \"notes\": \"\"}<<<END>>>. "
            "REGOLA: se rilevi una data (anche implicita: 'domani', 'lunedì', 'tra 3 giorni'), imposta due_date. "
            "Se rilevi un'ora, imposta due_time. Se rilevi anche una durata (es. 'per un'ora', 'di 45 minuti', "
            "'dalle 15 alle 16'), imposta duration_minutes; altrimenti lascialo null (il sistema userà 30 minuti di default "
            "quando l'evento viene sincronizzato su Calendar). Se l'utente chiede ESPLICITAMENTE un promemoria "
            "(es. 'avvisami un'ora prima', 'ricordamelo 10 minuti prima'), imposta reminder_minutes_before con i minuti "
            "richiesti; altrimenti lascialo null (il promemoria resta disattivato finché l'utente non lo attiva a mano; "
            "se poi lo attiva senza aver specificato nulla, il sistema userà 15 minuti prima come default). "
            "Il sistema salva come TASK se due_date è presente, altrimenti come TO-DO."
        )
    elif action == "journal":
        base += (
            " L'utente ti sta raccontando la sua giornata per il DIARIO. "
            "Il tuo compito: (1) sistemare il testo (grammatica, punteggiatura, chiarezza) mantenendo la voce personale in prima persona, "
            "(2) organizzare in paragrafi coerenti, (3) NON aggiungere fatti non presenti. "
            "Rispondi con il diario riscritto in modo naturale (senza intestazioni tipo 'Diario:'). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"titolo breve della giornata (max 6 parole)\", "
            "\"summary\": \"riassunto in 1 riga max 140 caratteri\", "
            "\"mood\": \"parola singola: felice|neutro|stressato|riflessivo|energico|stanco|grato\", "
            "\"highlights\": [\"1-3 momenti chiave estratti dal testo\"]}<<<END>>>"
        )
    return base


def _extract_meta(text: str) -> tuple[str, Optional[dict]]:
    """Return (visible_text, parsed_meta). Meta between <<<META>>>...<<<END>>> or legacy ```json``` fenced blocks."""
    import re, json as _json
    meta = None
    visible = text
    # Preferred: <<<META>>>...<<<END>>>
    m = re.search(r"<<<META>>>\s*(\{.*?\})\s*<<<END>>>", text, re.DOTALL)
    if m:
        try: meta = _json.loads(m.group(1))
        except Exception: meta = None
        visible = (text[:m.start()] + text[m.end():]).strip()
    else:
        # Legacy fallback: ```json {...} ```
        m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try: meta = _json.loads(m.group(1))
            except Exception: meta = None
            visible = (text[:m.start()] + text[m.end():]).strip()
    return visible, meta


async def retrieve_kb(user_id: str, query: str, limit: int = 8, scope: str = "kb") -> List[dict]:
    """Hybrid semantic + keyword retrieval over kb_chunks (and tasks/todos/journal if scope='all').
    - Semantic scoring via multilingual MiniLM cosine similarity.
    - Keyword boost for exact term matches (proper nouns, place names, etc.) to help generic queries
      like "informazioni su Rovigno" recover chunks that mention "Rovigno" but score low semantically.
    - Union of top-N semantic + top-M keyword hits, deduped by chunk id."""
    import re as _re
    try:
        q_emb = await emb.embed_query(query)
    except Exception:
        logger.exception("embed_query failed, falling back to keyword-only")
        q_emb = None

    # Extract meaningful query terms (drop very short + Italian stopwords)
    _STOP = {"per","con","del","dei","della","delle","degli","dal","dalla","dai","dagli","dallo",
             "sul","sulla","sui","sugli","sullo","nel","nella","nei","negli","nello","the","and",
             "che","chi","cosa","come","dove","quando","quale","quali","quanti","quanto",
             "sono","siamo","siete","essere","stato","stata","stati","state","molto","poco",
             "questa","questo","questi","queste","quello","quella","quelli","quelle","hai","hanno",
             "una","uno","gli","voi","noi","tuo","tua","tuoi","tue","mio","mia","miei","mie",
             "info","informazione","informazioni","dimmi","dammi","raccontami","parlami","cerca",
             "trova","voglio","sapere","cosa","tutto","tutti","tutte","tutta"}
    terms = [t for t in _re.findall(r"[\wàèéìòù']+", query.lower()) if len(t) >= 3 and t not in _STOP][:8]

    # Build candidate pool: kb_chunks always, plus extras when scope=='all'
    candidates: List[dict] = []
    kb_docs = await db.kb_chunks.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
    # Map: doc_id → list of sibling chunks (ordered by chunk_index) — used for doc expansion
    doc_siblings: dict = {}
    for c in kb_docs:
        item = {
            "text": c.get("text", ""),
            "source": "kb",
            "meta": {"chunk_id": c.get("chunk_id"), "title": c.get("title"), "doc_id": c.get("doc_id"), "chunk_index": c.get("chunk_index", 0)},
            "embedding": c.get("embedding"),
        }
        candidates.append(item)
        did = c.get("doc_id")
        if did:
            doc_siblings.setdefault(did, []).append(item)
    # Sort each doc's siblings by chunk_index for stable ordering
    for did in doc_siblings:
        doc_siblings[did].sort(key=lambda x: x["meta"].get("chunk_index", 0))

    if scope == "all":
        tasks = await db.tasks.find({"user_id": user_id}, {"_id": 0}).to_list(500)
        for t in tasks:
            txt_parts = [t.get("title", ""), t.get("description", ""), t.get("notes", "")]
            txt = " · ".join([p for p in txt_parts if p])
            if not txt: continue
            when = t.get("due_date", "") + (f" {t.get('due_time','')}" if t.get("due_time") else "")
            display = f"[Task] {t.get('title','')} — {when} · priorità {t.get('priority','media')}. {t.get('description','') or ''}".strip()
            candidates.append({"text": txt, "display": display, "source": "task", "meta": {"id": t.get("id")}, "embedding": None})
        todos = await db.todos.find({"user_id": user_id}, {"_id": 0}).to_list(500)
        for td in todos:
            txt_parts = [td.get("title", ""), td.get("description", ""), td.get("notes", "")]
            txt = " · ".join([p for p in txt_parts if p])
            if not txt: continue
            display = f"[To-Do] {td.get('title','')} — stato {td.get('status','da_fare')} ({td.get('completion_percent',0)}%). {td.get('description','') or ''}".strip()
            candidates.append({"text": txt, "display": display, "source": "todo", "meta": {"id": td.get("id")}, "embedding": None})
        journal_docs = await db.journal_entries.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(200)
        for j in journal_docs:
            txt = (j.get("cleaned_text") or j.get("raw_text") or "").strip()
            if not txt: continue
            display = f"[Diario · {j.get('date','')}] {j.get('title','')} · mood: {j.get('mood','')}. {txt[:400]}".strip()
            candidates.append({"text": txt, "display": display, "source": "journal", "meta": {"id": j.get("id"), "date": j.get("date")}, "embedding": None})

    # Compute embeddings for all candidates (semantic scoring)
    if q_emb is not None:
        missing_kb = [c for c in candidates if c["source"] == "kb" and not c.get("embedding")]
        if missing_kb:
            try:
                new_embs = await emb.embed_texts([c["text"] for c in missing_kb])
                for c, e in zip(missing_kb, new_embs):
                    c["embedding"] = e
                    await db.kb_chunks.update_one({"chunk_id": c["meta"]["chunk_id"]}, {"$set": {"embedding": e}})
            except Exception:
                logger.exception("backfill embeddings failed")
        non_kb = [c for c in candidates if c["source"] != "kb" and not c.get("embedding")]
        if non_kb:
            try:
                nk_embs = await emb.embed_texts([c["text"] for c in non_kb])
                for c, e in zip(non_kb, nk_embs):
                    c["embedding"] = e
            except Exception:
                logger.exception("non-kb embed failed")

    # Hybrid scoring: semantic cosine + keyword boost
    def _kw_hits(text: str) -> int:
        if not terms: return 0
        low = text.lower()
        return sum(1 for t in terms if t in low)

    scored = []
    for c in candidates:
        e = c.get("embedding")
        sem = emb.cosine(q_emb, e) if (q_emb is not None and e) else 0.0
        kh = _kw_hits(c["text"])
        # Each keyword hit adds 0.15; capped at +0.60. Ensures a chunk containing all terms wins.
        kw_boost = min(0.60, kh * 0.15)
        score = sem + kw_boost
        scored.append((score, sem, kh, c))

    # Keep chunks that have EITHER decent semantic score OR at least one keyword match
    scored = [s for s in scored if s[1] >= 0.20 or s[2] >= 1]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for _s, _sem, _kh, c in scored[:limit]]

    # DOCUMENT EXPANSION: for each KB chunk in the top, pull in ALL sibling chunks from the same doc.
    # This preserves the full document context (e.g., all Rovigno chunks together) so the LLM sees
    # the complete picture instead of scattered fragments diluted by other unrelated docs.
    seen_chunk_ids = set()
    expanded: List[dict] = []
    seen_doc_ids: set = set()
    for c in top:
        cid = (c.get("meta") or {}).get("chunk_id")
        did = (c.get("meta") or {}).get("doc_id")
        if c.get("source") == "kb" and did and did in doc_siblings and did not in seen_doc_ids:
            # Add all siblings of this doc (already sorted by chunk_index)
            for sib in doc_siblings[did]:
                scid = sib["meta"].get("chunk_id")
                if scid and scid not in seen_chunk_ids:
                    expanded.append(sib)
                    seen_chunk_ids.add(scid)
            seen_doc_ids.add(did)
        else:
            if cid and cid not in seen_chunk_ids:
                expanded.append(c)
                if cid: seen_chunk_ids.add(cid)
    top = expanded

    # Date-aware forcing: temporal questions about tasks ("oggi", "domani", "questa
    # settimana", "scaduti") get exact date-matched tasks injected regardless of semantic
    # score — a due_date carries no signal a text embedding model can pick up on, so
    # "dimmi i task di oggi" could otherwise score every task as equally (ir)relevant.
    if scope == "all":
        from datetime import date as _date, timedelta as _td
        low_q = query.lower()
        today = _date.today()
        lo = hi = None
        if "oggi" in low_q:
            lo = hi = today.isoformat()
        elif "domani" in low_q:
            lo = hi = (today + _td(days=1)).isoformat()
        elif "settiman" in low_q:
            lo, hi = today.isoformat(), (today + _td(days=7)).isoformat()
        elif "scad" in low_q or "ritardo" in low_q:
            hi = (today - _td(days=1)).isoformat()

        if lo or hi:
            date_q = {"user_id": user_id}
            if lo and hi: date_q["due_date"] = {"$gte": lo, "$lte": hi}
            elif hi: date_q["due_date"] = {"$lte": hi}
            elif lo: date_q["due_date"] = {"$gte": lo}
            date_tasks = await db.tasks.find(date_q, {"_id": 0}).sort("due_date", 1).to_list(200)
            existing_ids = {(c.get("meta") or {}).get("id") for c in top if c.get("source") == "task"}
            forced = []
            for t in date_tasks:
                if t.get("id") in existing_ids:
                    continue
                when = t.get("due_date", "") + (f" {t.get('due_time','')}" if t.get("due_time") else "")
                display = f"[Task] {t.get('title','')} — {when} · priorità {t.get('priority','media')}. {t.get('description','') or ''}".strip()
                forced.append({"text": t.get("title", ""), "display": display, "source": "task", "meta": {"id": t.get("id")}})
            top = forced + top

    # Fallback: if nothing passed filters but we have keyword terms, do a raw substring scan
    if not top and terms:
        for c in candidates:
            if any(t in c["text"].lower() for t in terms):
                top.append(c)
                if len(top) >= limit: break

    return top


@api_router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, current: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()

    # Load or create conversation
    if payload.conv_id:
        conv = await db.conversations.find_one({"conv_id": payload.conv_id, "user_id": current.user_id}, {"_id": 0})
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv_id = conv["conv_id"]
        action = conv["action"]
        prior_messages = conv.get("messages", [])
        # Legacy fallback: rebuild from old top-level fields if messages array missing
        if not prior_messages and conv.get("user_message"):
            prior_messages = [
                {"role": "user", "content": conv["user_message"], "ts": conv.get("created_at", now)},
            ]
            if conv.get("agent_response"):
                prior_messages.append({"role": "assistant", "content": conv["agent_response"], "ts": conv.get("completed_at", now)})
    else:
        conv_id = f"conv_{uuid.uuid4().hex[:12]}"
        action = payload.action
        prior_messages = []
        await db.conversations.insert_one({
            "conv_id": conv_id,
            "user_id": current.user_id,
            "action": action,
            "created_at": now,
            "user_message": payload.content,   # legacy: first message for cronologia preview
            "filters": payload.filters or {},
            "pipeline": {"claude": "ok", "n8n": "skip", "mongodb": "ok"},
            "messages": [],
        })

    # RAG context: run on EVERY info_request turn (not just first) so follow-up questions
    # can pull fresh chunks based on the new question.
    kb_context = []
    if action == "info_request":
        if payload.conv_id:
            scope = (conv.get("filters", {}) or {}).get("scope", "kb")
        else:
            scope = (payload.filters or {}).get("scope", "kb")
        kb_context = await retrieve_kb(current.user_id, payload.content, scope=scope)
        logger.info(f"[RAG] user={current.user_id[:8]} scope={scope} q={payload.content[:60]!r} chunks={len(kb_context)}")

    system = build_system_prompt(current, action)
    user_text = payload.content
    if kb_context:
        def _fmt(c):
            # Non-KB sources (task/todo/journal) use a compact display line.
            # KB chunks are already chunked to ~1400 chars during upload — send them in full.
            if c.get("display"):
                return c["display"]
            return c.get("text", "")
        ctx = "\n\n".join([f"- {_fmt(c)}" for c in kb_context])
        user_text = f"CONTESTO KB PERSONALE:\n{ctx}\n\nDOMANDA:\n{payload.content}"

    initial = [{"role": "system", "content": system}]
    for m in prior_messages:
        initial.append({"role": m["role"], "content": m["content"]})

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=conv_id,
        system_message=system,
        initial_messages=initial,
    ).with_model("anthropic", "claude-sonnet-5")

    # Save the user turn to the messages array immediately
    await db.conversations.update_one(
        {"conv_id": conv_id},
        {"$push": {"messages": {"role": "user", "content": payload.content, "ts": now}}},
    )

    import json as _json
    MARKER = "<<<META>>>"
    async def event_gen():
        full = []
        pending = ""     # buffer with tail that could still be a partial marker prefix
        stopped = False  # true once MARKER encountered
        try:
            async for ev in chat.stream_message(UserMessage(text=user_text)):
                if isinstance(ev, TextDelta):
                    full.append(ev.content)
                    if stopped:
                        continue
                    pending += ev.content
                    idx = pending.find(MARKER)
                    if idx >= 0:
                        pre = pending[:idx].rstrip()
                        if pre.endswith("```json"):
                            pre = pre[:-7].rstrip()
                        if pre:
                            yield _json.dumps({"type": "delta", "content": pre}) + "\n"
                        stopped = True
                        pending = ""
                        continue
                    # Hold back any tail matching a marker prefix
                    hold = 0
                    for k in range(min(len(MARKER) - 1, len(pending)), 0, -1):
                        if pending.endswith(MARKER[:k]):
                            hold = k
                            break
                    if len(pending) > hold:
                        out = pending[:len(pending) - hold]
                        pending = pending[len(pending) - hold:]
                        yield _json.dumps({"type": "delta", "content": out}) + "\n"
                elif isinstance(ev, StreamDone):
                    break
            if not stopped and pending:
                yield _json.dumps({"type": "delta", "content": pending}) + "\n"
        except Exception as e:
            logger.exception("LLM stream error")
            yield _json.dumps({"type": "error", "content": str(e)}) + "\n"

        raw_answer = "".join(full)
        visible_answer, meta = _extract_meta(raw_answer)
        visible_answer = visible_answer.replace("```json", "").replace("```", "").strip()
        completed_at = datetime.now(timezone.utc).isoformat()
        conv_set = {"agent_response": visible_answer, "meta": meta or {}, "completed_at": completed_at}
        # Persist a first-turn summary/title at conversation root so the history card can always display them
        if not prior_messages and meta:
            if meta.get("title"): conv_set["title"] = meta["title"]
            if meta.get("summary"): conv_set["summary"] = meta["summary"]
        await db.conversations.update_one(
            {"conv_id": conv_id},
            {
                "$push": {"messages": {"role": "assistant", "content": visible_answer, "ts": completed_at}},
                "$set": conv_set,
            },
        )

        # side-effects only on first exchange of upload/task actions
        if not prior_messages:
            if action == "info_upload":
                try:
                    e = await emb.embed_texts([payload.content])
                    embedding = e[0] if e else None
                except Exception:
                    embedding = None
                doc_id = f"doc_{uuid.uuid4().hex[:12]}"
                await db.kb_chunks.insert_one({
                    "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
                    "user_id": current.user_id,
                    "text": payload.content,
                    "title": (meta or {}).get("title") if meta else None,
                    "tags": (meta or {}).get("tags", []) if meta else [],
                    "summary": (meta or {}).get("summary") if meta else visible_answer,
                    "embedding": embedding,
                    "doc_id": doc_id,
                    "source_type": "chat",
                    "chunk_index": 0,
                    "conv_id": conv_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                # Classify + persist document-level record so it appears in the Documents page
                try:
                    classification = await _classify_document(payload.content)
                except Exception:
                    classification = {"category": "altro", "keywords": []}
                await db.kb_documents.insert_one({
                    "doc_id": doc_id,
                    "user_id": current.user_id,
                    "name": (meta or {}).get("title") if meta else (payload.content[:60] + ("…" if len(payload.content) > 60 else "")),
                    "ext": "chat",
                    "source_type": "chat",
                    "category": classification["category"],
                    "keywords": list({*(classification["keywords"] or []), *(((meta or {}).get("tags") or []))})[:8],
                    "chunks_count": 1,
                    "chars": len(payload.content),
                    "size_bytes": len(payload.content.encode("utf-8")),
                    "preview": ((meta or {}).get("summary") if meta else payload.content)[:280],
                    "drive_link": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "conv_id": conv_id,
                })
            elif action == "task_todo":
                logger.info(f"[task_todo] meta={meta!r}")
                if meta:
                    await _create_task_or_todo(current.user_id, meta, conv_id)
            elif action == "journal":
                from datetime import date as _date
                jr = {
                    "id": f"jr_{uuid.uuid4().hex[:12]}",
                    "user_id": current.user_id,
                    "date": _date.today().isoformat(),
                    "raw_text": payload.content,
                    "cleaned_text": visible_answer,
                    "title": (meta or {}).get("title", ""),
                    "mood": (meta or {}).get("mood", ""),
                    "highlights": (meta or {}).get("highlights", []),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_conv": conv_id,
                }
                await db.journal_entries.insert_one(jr)

        yield _json.dumps({"type": "done", "conv_id": conv_id}) + "\n"

    return StreamingResponse(
        event_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _parse_task_json(text: str) -> Optional[dict]:
    import re, json
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


async def _create_task_or_todo(user_id: str, parsed: dict, conv_id: str):
    now = datetime.now(timezone.utc).isoformat()
    # RULE: if due_date is present → TASK, otherwise → TODO (regardless of any 'type' field the LLM returned)
    due_date = parsed.get("due_date")
    due_time = parsed.get("due_time")
    try:
        duration_minutes = int(parsed.get("duration_minutes")) if parsed.get("duration_minutes") else None
    except (TypeError, ValueError):
        duration_minutes = None
    try:
        reminder_offset_minutes = int(parsed.get("reminder_minutes_before")) if parsed.get("reminder_minutes_before") else None
    except (TypeError, ValueError):
        reminder_offset_minutes = None
    if due_date:
        doc = {
            "id": f"task_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": parsed.get("title", "Nuovo task"),
            "description": parsed.get("description", ""),
            "due_date": due_date,
            "due_time": due_time,
            "duration_minutes": duration_minutes,
            "priority": parsed.get("priority", "media"),
            "tags": parsed.get("tags", []),
            "notes": parsed.get("notes", ""),
            "calendar_synced": False,
            "reminder_sent": False,
            "reminder_enabled": reminder_offset_minutes is not None,
            "reminder_offset_minutes": reminder_offset_minutes,
            "reminder_msg_sent": False,
            "created_at": now,
            "source_conv": conv_id,
        }
        await db.tasks.insert_one(doc)
    else:
        doc = {
            "id": f"todo_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": parsed.get("title", "Nuovo to-do"),
            "description": parsed.get("description", ""),
            "status": "da_fare",
            "completion_percent": 0,
            "priority": parsed.get("priority"),
            "tags": parsed.get("tags", []),
            "notes": parsed.get("notes", ""),
            "created_at": now,
            "source_conv": conv_id,
        }
        await db.todos.insert_one(doc)


# ============ CONVERSATIONS ============
@api_router.get("/conversations")
async def list_conversations(current: User = Depends(get_current_user), action: Optional[str] = None, favorite: Optional[bool] = None):
    q = {"user_id": current.user_id}
    if action and action != "all":
        q["action"] = action
    if favorite is True:
        q["favorite"] = True
    cursor = db.conversations.find(q, {"_id": 0}).sort("created_at", -1).limit(200)
    return await cursor.to_list(200)


@api_router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, current: User = Depends(get_current_user)):
    conv = await db.conversations.find_one({"conv_id": conv_id, "user_id": current.user_id}, {"_id": 0})
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    return conv


@api_router.post("/conversations/{conv_id}/favorite")
async def toggle_favorite(conv_id: str, current: User = Depends(get_current_user)):
    conv = await db.conversations.find_one({"conv_id": conv_id, "user_id": current.user_id}, {"_id": 0})
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    new_val = not conv.get("favorite", False)
    await db.conversations.update_one(
        {"conv_id": conv_id, "user_id": current.user_id},
        {"$set": {"favorite": new_val}},
    )
    return {"conv_id": conv_id, "favorite": new_val}


@api_router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, current: User = Depends(get_current_user)):
    res = await db.conversations.delete_one({"conv_id": conv_id, "user_id": current.user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ============ TASKS ============
@api_router.get("/tasks")
async def list_tasks(current: User = Depends(get_current_user)):
    cursor = db.tasks.find(_visible_query(current), {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(500)


@api_router.post("/tasks")
async def create_task(payload: TaskUpsert, current: User = Depends(get_current_user)):
    doc = {
        "id": f"task_{uuid.uuid4().hex[:12]}",
        **payload.model_dump(),
        "calendar_synced": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.tasks.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/tasks/{task_id}")
async def update_task(task_id: str, payload: dict, current: User = Depends(get_current_user)):
    payload.pop("id", None); payload.pop("user_id", None); payload.pop("_id", None); payload.pop("org_id", None)
    if "visibility" in payload:
        if payload["visibility"] == "org" and current.org_id:
            payload["org_id"] = current.org_id
        else:
            payload["visibility"] = "private"
            payload["org_id"] = None
    existing = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")

    # Handle calendar_synced toggle
    if "calendar_synced" in payload and payload["calendar_synced"] != existing.get("calendar_synced"):
        try:
            creds = await gi.get_credentials(db, current.user_id)
            if not creds:
                raise HTTPException(status_code=400, detail="Google Workspace non collegato. Vai in Impostazioni.")
            if payload["calendar_synced"]:
                event_id = await gi.create_calendar_event(
                    creds,
                    title=existing.get("title","Task mAIPAL"),
                    description=existing.get("description","") or "",
                    due_date=existing.get("due_date"),
                    due_time=existing.get("due_time"),
                    duration_minutes=existing.get("duration_minutes"),
                )
                payload["calendar_event_id"] = event_id
            else:
                if existing.get("calendar_event_id"):
                    await gi.delete_calendar_event(creds, existing["calendar_event_id"])
                payload["calendar_event_id"] = None
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("calendar sync failed")
            raise HTTPException(status_code=500, detail=f"Sync calendar fallita: {e}")

    # Re-enabling the reminder (or changing when it's due) should allow it to fire again.
    if payload.get("reminder_enabled") and not existing.get("reminder_enabled"):
        payload["reminder_msg_sent"] = False
    if ("due_date" in payload or "due_time" in payload) and (
        payload.get("due_date", existing.get("due_date")) != existing.get("due_date")
        or payload.get("due_time", existing.get("due_time")) != existing.get("due_time")
    ):
        payload["reminder_msg_sent"] = False

    await db.tasks.update_one({"id": task_id, **_editable_query(current)}, {"$set": payload})
    doc = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    return doc


@api_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current: User = Depends(get_current_user)):
    existing = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    if existing.get("calendar_event_id"):
        try:
            creds = await gi.get_credentials(db, current.user_id)
            if creds:
                await gi.delete_calendar_event(creds, existing["calendar_event_id"])
        except Exception:
            logger.exception("failed removing calendar event on delete")
    await db.tasks.delete_one({"id": task_id, **_editable_query(current)})
    return {"ok": True}


# ============ TODOS ============
@api_router.get("/todos")
async def list_todos(current: User = Depends(get_current_user)):
    cursor = db.todos.find({"user_id": current.user_id}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(500)


@api_router.post("/todos")
async def create_todo(payload: TodoUpsert, current: User = Depends(get_current_user)):
    doc = {
        "id": f"todo_{uuid.uuid4().hex[:12]}",
        "user_id": current.user_id,
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.todos.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/todos/{todo_id}")
async def update_todo(todo_id: str, payload: dict, current: User = Depends(get_current_user)):
    payload.pop("id", None); payload.pop("user_id", None); payload.pop("_id", None)
    await db.todos.update_one({"id": todo_id, "user_id": current.user_id}, {"$set": payload})
    doc = await db.todos.find_one({"id": todo_id, "user_id": current.user_id}, {"_id": 0})
    return doc


@api_router.delete("/todos/{todo_id}")
async def delete_todo(todo_id: str, current: User = Depends(get_current_user)):
    await db.todos.delete_one({"id": todo_id, "user_id": current.user_id})
    return {"ok": True}


@api_router.post("/tasks/{task_id}/complete")
async def toggle_task_complete(task_id: str, current: User = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    q = {"id": task_id, **_editable_query(current)}
    if task.get("completed"):
        await db.tasks.update_one(q, {"$set": {"completed": False, "completed_at": None}})
        return {"id": task_id, "completed": False}
    await db.tasks.update_one(q, {"$set": {"completed": True, "completed_at": datetime.now(timezone.utc).isoformat()}})
    return {"id": task_id, "completed": True}


@api_router.post("/tasks/{task_id}/favorite")
async def toggle_task_favorite(task_id: str, current: User = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    new_val = not task.get("favorite", False)
    await db.tasks.update_one({"id": task_id, **_editable_query(current)}, {"$set": {"favorite": new_val}})
    return {"id": task_id, "favorite": new_val}


@api_router.post("/todos/{todo_id}/favorite")
async def toggle_todo_favorite(todo_id: str, current: User = Depends(get_current_user)):
    todo = await db.todos.find_one({"id": todo_id, "user_id": current.user_id}, {"_id": 0})
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    new_val = not todo.get("favorite", False)
    await db.todos.update_one({"id": todo_id, "user_id": current.user_id}, {"$set": {"favorite": new_val}})
    return {"id": todo_id, "favorite": new_val}


# ============ COLLEZIONI (liste personalizzate: clienti, esercizi, commesse, ecc.) ============
@api_router.get("/collections")
async def list_collections(current: User = Depends(get_current_user)):
    cursor = db.collections.find(_visible_query(current), {"_id": 0}).sort("created_at", 1)
    collections = await cursor.to_list(200)
    ids = [c["id"] for c in collections]
    if ids:
        counts = await db.collection_items.aggregate([
            {"$match": {"collection_id": {"$in": ids}}},
            {"$group": {"_id": "$collection_id", "n": {"$sum": 1}}},
        ]).to_list(len(ids))
        count_map = {c["_id"]: c["n"] for c in counts}
        for c in collections:
            c["item_count"] = count_map.get(c["id"], 0)
    return collections


@api_router.post("/collections")
async def create_collection(payload: CollectionCreatePayload, current: User = Depends(get_current_user)):
    if not payload.fields:
        raise HTTPException(status_code=400, detail="Definisci almeno un campo per la lista")
    doc = {
        "id": f"coll_{uuid.uuid4().hex[:12]}",
        "name": payload.name.strip() or "Nuova lista",
        "icon": payload.icon,
        "fields": [f.model_dump() for f in payload.fields],
        "visibility": payload.visibility,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.collections.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.get("/collections/{collection_id}")
async def get_collection(collection_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_visible_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    return coll


@api_router.patch("/collections/{collection_id}")
async def update_collection(collection_id: str, payload: CollectionUpdatePayload, current: User = Depends(get_current_user)):
    existing = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    updates = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip() or existing["name"]
    if payload.icon is not None:
        updates["icon"] = payload.icon
    if payload.fields is not None:
        updates["fields"] = [f.model_dump() for f in payload.fields]
    if payload.visibility is not None:
        if payload.visibility == "org" and current.org_id:
            updates["visibility"] = "org"
            updates["org_id"] = current.org_id
        else:
            updates["visibility"] = "private"
            updates["org_id"] = None
    if updates:
        await db.collections.update_one({"id": collection_id}, {"$set": updates})
    return await db.collections.find_one({"id": collection_id}, {"_id": 0})


@api_router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str, current: User = Depends(get_current_user)):
    existing = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    await db.collections.delete_one({"id": collection_id})
    await db.collection_items.delete_many({"collection_id": collection_id})
    return {"ok": True}


@api_router.get("/collections/{collection_id}/items")
async def list_collection_items(collection_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_visible_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    cursor = db.collection_items.find({"collection_id": collection_id}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(1000)


@api_router.post("/collections/{collection_id}/items")
async def create_collection_item(collection_id: str, payload: CollectionItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_visible_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    doc = {
        "id": f"item_{uuid.uuid4().hex[:12]}",
        "collection_id": collection_id,
        "data": payload.data,
        "visibility": payload.visibility or coll.get("visibility", "private"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.collection_items.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/collections/{collection_id}/items/{item_id}")
async def update_collection_item(collection_id: str, item_id: str, payload: CollectionItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    updates = {"data": payload.data}
    if payload.visibility is not None:
        if payload.visibility == "org" and current.org_id:
            updates["visibility"] = "org"
            updates["org_id"] = current.org_id
        else:
            updates["visibility"] = "private"
            updates["org_id"] = None
    await db.collection_items.update_one({"id": item_id, "collection_id": collection_id}, {"$set": updates})
    return await db.collection_items.find_one({"id": item_id, "collection_id": collection_id}, {"_id": 0})


@api_router.delete("/collections/{collection_id}/items/{item_id}")
async def delete_collection_item(collection_id: str, item_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    await db.collection_items.delete_one({"id": item_id, "collection_id": collection_id})
    return {"ok": True}


# ============ JOURNAL ============
class JournalCreate(BaseModel):
    content: str
    date: Optional[str] = None  # YYYY-MM-DD, defaults today


@api_router.get("/journal")
async def list_journal(current: User = Depends(get_current_user), q: Optional[str] = None, mood: Optional[str] = None, favorite: Optional[bool] = None):
    import re as _re
    query: dict = {"user_id": current.user_id}
    if mood and mood != "all":
        query["mood"] = mood
    if favorite is True:
        query["favorite"] = True
    if q:
        safe = _re.escape(q.strip())
        query["$or"] = [
            {"cleaned_text": {"$regex": safe, "$options": "i"}},
            {"raw_text": {"$regex": safe, "$options": "i"}},
            {"title": {"$regex": safe, "$options": "i"}},
            {"highlights": {"$regex": safe, "$options": "i"}},
        ]
    cursor = db.journal_entries.find(query, {"_id": 0}).sort("date", -1).limit(365)
    return await cursor.to_list(365)


@api_router.post("/journal/{entry_id}/favorite")
async def toggle_journal_favorite(entry_id: str, current: User = Depends(get_current_user)):
    doc = await db.journal_entries.find_one({"id": entry_id, "user_id": current.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    new_val = not doc.get("favorite", False)
    await db.journal_entries.update_one(
        {"id": entry_id, "user_id": current.user_id},
        {"$set": {"favorite": new_val}},
    )
    return {"id": entry_id, "favorite": new_val}


@api_router.get("/journal/trend")
async def journal_trend(current: User = Depends(get_current_user), days: int = 30):
    """Return per-day mood score for the last `days` days.
    mood → score mapping favours a simple positive/neutral/negative axis for line chart."""
    from datetime import date as _date, timedelta as _td
    MOOD_SCORE = {
        "felice": 5, "grato": 5, "energico": 4,
        "riflessivo": 3, "neutro": 3,
        "stanco": 2, "stressato": 1,
    }
    since = (_date.today() - _td(days=max(1, min(days, 365)) - 1)).isoformat()
    cursor = db.journal_entries.find(
        {"user_id": current.user_id, "date": {"$gte": since}},
        {"_id": 0, "date": 1, "mood": 1, "title": 1},
    ).sort("date", 1)
    docs = await cursor.to_list(1000)
    # Group by date, take last mood of the day
    by_date: dict = {}
    for d in docs:
        by_date[d.get("date")] = d.get("mood") or "neutro"
    out = []
    today = _date.today()
    for i in range(max(1, min(days, 365))):
        day = (today - _td(days=(days - 1 - i))).isoformat()
        mood = by_date.get(day)
        out.append({
            "date": day,
            "mood": mood,
            "score": MOOD_SCORE.get(mood) if mood else None,
        })
    return {"days": out, "mood_score_map": MOOD_SCORE}

@api_router.get("/journal/stats")
async def journal_stats(current: User = Depends(get_current_user)):
    """Aggregated numbers for the journal summary card:
    - total entries
    - most frequent mood (with count)
    - streak of consecutive days ending today (or yesterday if today is missing)."""
    from datetime import date as _date, timedelta as _td
    docs = await db.journal_entries.find(
        {"user_id": current.user_id},
        {"_id": 0, "date": 1, "mood": 1},
    ).sort("date", -1).to_list(2000)

    total = len(docs)

    # most common mood
    mood_counts: dict = {}
    for d in docs:
        m = (d.get("mood") or "").strip()
        if not m: continue
        mood_counts[m] = mood_counts.get(m, 0) + 1
    top_mood = None
    if mood_counts:
        best = max(mood_counts.items(), key=lambda x: x[1])
        top_mood = {"mood": best[0], "count": best[1]}

    # streak: unique dates sorted desc, count consecutive from today (or yesterday)
    dates = sorted({d.get("date") for d in docs if d.get("date")}, reverse=True)
    streak = 0
    today = _date.today()
    if dates:
        first = _date.fromisoformat(dates[0])
        if first == today or first == today - _td(days=1):
            cur = first
            for ds in dates:
                if _date.fromisoformat(ds) == cur:
                    streak += 1
                    cur = cur - _td(days=1)
                elif _date.fromisoformat(ds) < cur:
                    break

    return {
        "total": total,
        "top_mood": top_mood,
        "streak_days": streak,
        "mood_breakdown": mood_counts,
    }





@api_router.post("/journal")
async def create_journal(payload: JournalCreate, current: User = Depends(get_current_user)):
    from datetime import date as _date
    entry_date = payload.date or _date.today().isoformat()
    system = (
        f"Sei mAIPAL, l'assistente di {current.name}. L'utente ti sta raccontando la sua giornata. "
        "Il tuo compito: (1) sistemare il testo (grammatica, punteggiatura, chiarezza) mantenendo la voce personale in prima persona, "
        "(2) organizzare in paragrafi coerenti, (3) NON aggiungere fatti non presenti. "
        "Restituisci una risposta con due parti: prima il diario riscritto in modo naturale (senza intestazioni tipo 'Diario:'), "
        "poi in coda solo per il sistema: "
        "<<<META>>>{\"title\": \"titolo breve della giornata (max 6 parole)\", \"mood\": \"parola singola: felice|neutro|stressato|riflessivo|energico|stanco|grato\", "
        "\"highlights\": [\"1-3 momenti chiave estratti dal testo\"]}<<<END>>>"
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"journal_{uuid.uuid4().hex[:8]}", system_message=system).with_model("anthropic", "claude-sonnet-5")
    raw = await chat.send_message(UserMessage(text=payload.content))
    cleaned, meta = _extract_meta(raw)
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    doc = {
        "id": f"jr_{uuid.uuid4().hex[:12]}",
        "user_id": current.user_id,
        "date": entry_date,
        "raw_text": payload.content,
        "cleaned_text": cleaned,
        "title": (meta or {}).get("title", ""),
        "mood": (meta or {}).get("mood", ""),
        "highlights": (meta or {}).get("highlights", []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.journal_entries.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.delete("/journal/{entry_id}")
async def delete_journal(entry_id: str, current: User = Depends(get_current_user)):
    res = await db.journal_entries.delete_one({"id": entry_id, "user_id": current.user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ============ CONTEXTUAL CHAT (per task/todo) ============
class ContextChatRequest(BaseModel):
    message: str


@api_router.post("/tasks/{task_id}/chat")
async def task_chat(task_id: str, payload: ContextChatRequest, current: User = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    system = (
        f"Sei mAIPAL. L'utente sta modificando il task: {task}. "
        "Rispondi in modo naturale (1-2 frasi) con la conferma della modifica. "
        "In coda includi SOLO per il sistema i campi da aggiornare tra i marcatori "
        "<<<META>>>{...}<<<END>>>, chiavi ammesse: title, description, due_date, due_time, priority, tags, notes."
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"task_{task_id}", system_message=system).with_model("anthropic", "claude-sonnet-5")
    raw = await chat.send_message(UserMessage(text=payload.message))
    visible, meta = _extract_meta(raw)
    visible = visible.replace("```json", "").replace("```", "").strip()
    q = {"id": task_id, **_editable_query(current)}
    if meta:
        await db.tasks.update_one(q, {"$set": meta})
    updated = await db.tasks.find_one(q, {"_id": 0})
    return {"answer": visible, "task": updated}


@api_router.post("/todos/{todo_id}/chat")
async def todo_chat(todo_id: str, payload: ContextChatRequest, current: User = Depends(get_current_user)):
    todo = await db.todos.find_one({"id": todo_id, "user_id": current.user_id}, {"_id": 0})
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    system = (
        f"Sei mAIPAL. L'utente sta modificando il to-do: {todo}. "
        "Rispondi in modo naturale (1-2 frasi) con la conferma. "
        "In coda includi SOLO per il sistema i campi da aggiornare tra i marcatori "
        "<<<META>>>{...}<<<END>>>, chiavi ammesse: title, description, status ('da_fare'|'in_corso'|'fatto'), completion_percent, priority, tags, notes."
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"todo_{todo_id}", system_message=system).with_model("anthropic", "claude-sonnet-5")
    raw = await chat.send_message(UserMessage(text=payload.message))
    visible, meta = _extract_meta(raw)
    visible = visible.replace("```json", "").replace("```", "").strip()
    if meta:
        await db.todos.update_one({"id": todo_id, "user_id": current.user_id}, {"$set": meta})
    updated = await db.todos.find_one({"id": todo_id, "user_id": current.user_id}, {"_id": 0})
    return {"answer": visible, "todo": updated}


@api_router.get("/")
async def root():
    return {"message": "mAIPAL API"}


# ============ FILE ATTACHMENTS -> DRIVE ============
@api_router.post("/attachments/upload")
async def upload_attachment(file: UploadFile = File(...), current: User = Depends(get_current_user)):
    creds = await gi.get_credentials(db, current.user_id)
    if not creds:
        raise HTTPException(status_code=400, detail="Google Workspace non collegato. Vai in Impostazioni per collegarlo.")

    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file.filename.rsplit('.',1)[-1] if '.' in (file.filename or '') else 'bin'}") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        folder_id = await gi.ensure_maipal_folder(db, current.user_id, creds)
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        media = MediaFileUpload(tmp_path, mimetype=file.content_type or "application/octet-stream")
        meta = {"name": file.filename or "file", "parents": [folder_id]}
        created = service.files().create(body=meta, media_body=media, fields="id, webViewLink, name").execute()
        return {"file_id": created["id"], "web_view_link": created.get("webViewLink"), "name": created["name"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("drive upload failed")
        raise HTTPException(status_code=500, detail=f"Upload Drive fallito: {e}")
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass


async def _resolve_drive_folder_hint(text: str, existing_folders: List[str]) -> Optional[str]:
    """Ask the LLM whether the user's message names a target Drive folder (existing or
    new). Returns the folder name, or None if the message doesn't specify one."""
    text = (text or "").strip()
    if not text:
        return None
    folders_list = ", ".join(existing_folders) if existing_folders else "(nessuna)"
    system = (
        "L'utente sta caricando un file su Google Drive, dentro la cartella mAIPAL. "
        f"Cartelle già esistenti dentro mAIPAL: {folders_list}. "
        "Analizza il messaggio dell'utente: se indica chiaramente in quale cartella salvare il file "
        "(sia una cartella esistente sia una nuova da creare), rispondi SOLO con il nome esatto di quella cartella, "
        "senza virgolette né altro testo. Se non lo specifica, rispondi SOLO con la parola: NESSUNA."
    )
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"drivehint_{uuid.uuid4().hex[:8]}", system_message=system).with_model("anthropic", "claude-sonnet-5")
        raw = (await chat.send_message(UserMessage(text=text))).strip().strip('"').strip()
        if not raw or raw.upper() == "NESSUNA":
            return None
        return raw
    except Exception:
        logger.exception("drive folder hint resolution failed")
        return None


@api_router.post("/drive/smart-upload")
async def drive_smart_upload(file: UploadFile = File(...), text: str = Form(""), current: User = Depends(get_current_user)):
    """Upload a file into the mAIPAL Drive tree, picking the subfolder from the user's
    message when possible. If no folder can be determined, stashes the file and returns
    suggestions so the conversation can ask the user (see /drive/resolve-pending)."""
    creds = await gi.get_credentials(db, current.user_id)
    if not creds:
        raise HTTPException(status_code=400, detail="Google Workspace non collegato. Vai in Impostazioni per collegarlo.")

    contents = await file.read()
    subfolders = await gi.list_subfolders(db, current.user_id, creds)
    folder_name = await _resolve_drive_folder_hint(text, [f["name"] for f in subfolders])

    if folder_name:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file.filename.rsplit('.',1)[-1] if '.' in (file.filename or '') else 'bin'}") as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        try:
            folder_id = await gi.find_or_create_subfolder(db, current.user_id, creds, folder_name)
            result = gi.upload_file_to_folder(creds, folder_id, tmp_path, file.filename, file.content_type)
            return {"status": "saved", "folder": folder_name, **result}
        finally:
            try: os.unlink(tmp_path)
            except Exception: pass

    import base64 as _b64
    pending_id = f"pdu_{uuid.uuid4().hex[:12]}"
    await db.pending_drive_uploads.insert_one({
        "pending_id": pending_id,
        "user_id": current.user_id,
        "filename": file.filename,
        "content_type": file.content_type,
        "data_b64": _b64.b64encode(contents).decode("ascii"),
        "created_at": datetime.now(timezone.utc),
    })
    return {"status": "needs_folder", "pending_id": pending_id, "suggestions": [f["name"] for f in subfolders]}


@api_router.post("/drive/resolve-pending")
async def drive_resolve_pending(payload: dict, current: User = Depends(get_current_user)):
    """Second turn of the smart-upload flow: the user's follow-up message may now name
    the folder. Resolves it and finally uploads the stashed file."""
    pending_id = payload.get("pending_id")
    text = payload.get("text", "")
    doc = await db.pending_drive_uploads.find_one({"pending_id": pending_id, "user_id": current.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Nessun upload in attesa trovato")

    creds = await gi.get_credentials(db, current.user_id)
    if not creds:
        raise HTTPException(status_code=400, detail="Google Workspace non collegato. Vai in Impostazioni per collegarlo.")

    subfolders = await gi.list_subfolders(db, current.user_id, creds)
    folder_name = await _resolve_drive_folder_hint(text, [f["name"] for f in subfolders])
    if not folder_name:
        return {"status": "needs_folder", "pending_id": pending_id, "suggestions": [f["name"] for f in subfolders]}

    import base64 as _b64
    contents = _b64.b64decode(doc["data_b64"])
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{doc['filename'].rsplit('.',1)[-1] if '.' in (doc['filename'] or '') else 'bin'}") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        folder_id = await gi.find_or_create_subfolder(db, current.user_id, creds, folder_name)
        result = gi.upload_file_to_folder(creds, folder_id, tmp_path, doc["filename"], doc["content_type"])
        await db.pending_drive_uploads.delete_one({"pending_id": pending_id})
        return {"status": "saved", "folder": folder_name, **result}
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass


# ============ KB DIRECT UPLOAD (no Google) ============
IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "heic", "heif")


async def _ocr_image_bytes(contents: bytes, filename: str) -> str:
    """Run OCR on an image using Claude Sonnet 5 vision."""
    import base64 as _b64
    b64 = _b64.b64encode(contents).decode("ascii")
    system = (
        "Sei un motore OCR. Estrai FEDELMENTE TUTTO il testo visibile nell'immagine. "
        "Regole: (1) rispetta l'ordine di lettura originale, (2) mantieni righe/paragrafi come nell'immagine, "
        "(3) se noti tabelle, ricostruiscile riga per riga separando le celle con ' | ', "
        "(4) NON aggiungere commenti né descrizioni, (5) se l'immagine non contiene testo leggibile, "
        "rispondi esattamente con: [NO_TEXT]."
    )
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ocr_{uuid.uuid4().hex[:8]}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-5")
    msg = UserMessage(text="Estrai tutto il testo dall'immagine.", file_contents=[ImageContent(image_base64=b64)])
    result = await chat.send_message(msg)
    text = (result or "").strip()
    if text == "[NO_TEXT]":
        return ""
    return text


def _extract_text_from_file(path: str, filename: str) -> str:
    """Extract plain text from common file formats. Raises ValueError on unsupported types."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext in ("txt", "md", "markdown", "csv", "json", "log", "yaml", "yml", "html", "htm", "xml"):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for p in reader.pages:
            try: pages.append(p.extract_text() or "")
            except Exception: pass
        return "\n\n".join(pages)
    if ext in ("docx",):
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    if ext in ("xlsx",):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        parts = []
        for sn in wb.sheetnames:
            ws = wb[sn]
            parts.append(f"# {sn}")
            for row in ws.iter_rows(values_only=True):
                line = " | ".join("" if v is None else str(v) for v in row)
                if line.strip(): parts.append(line)
        return "\n".join(parts)
    raise ValueError(f"Formato .{ext} non supportato (prova pdf, docx, xlsx, immagini, txt, md, csv, json, html)")


def _chunk_text(text: str, max_chars: int = 1400, overlap: int = 150) -> List[str]:
    text = (text or "").strip()
    if not text: return []
    if len(text) <= max_chars: return [text]
    chunks = []
    i = 0
    while i < len(text):
        end = min(len(text), i + max_chars)
        # try to break at a sentence/paragraph boundary
        window = text[i:end]
        if end < len(text):
            for sep in ["\n\n", "\n", ". ", "! ", "? "]:
                idx = window.rfind(sep)
                if idx >= int(max_chars * 0.6):
                    end = i + idx + len(sep)
                    window = text[i:end]
                    break
        chunks.append(window.strip())
        if end >= len(text): break
        i = max(end - overlap, i + 1)
    return [c for c in chunks if c]


async def _classify_document(text: str) -> dict:
    """Ask the LLM for a category + keywords for the uploaded document. Best-effort."""
    sample = (text or "")[:3500]
    if not sample.strip():
        return {"category": "altro", "keywords": []}
    system = (
        "Sei un classificatore di documenti personali. Ricevi il testo di un documento e restituisci SOLO un JSON: "
        "{\"category\": \"...\", \"keywords\": [\"...\"]}. "
        "Categorie ammesse: lavoro, personale, finanza, salute, viaggi, casa, ricevute, documenti_identità, istruzione, note, altro. "
        "Keywords: da 3 a 8 termini brevi (1-2 parole ciascuno), in italiano minuscolo, senza duplicati e senza stopwords. "
        "Rispondi con SOLO il JSON, senza commenti né markdown."
    )
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"cls_{uuid.uuid4().hex[:8]}", system_message=system).with_model("anthropic", "claude-sonnet-5")
        raw = await chat.send_message(UserMessage(text=sample))
        import json as _json, re as _re
        raw = (raw or "").strip()
        # strip fences if any
        m = _re.search(r"\{[\s\S]*\}", raw)
        data = _json.loads(m.group(0)) if m else {}
        cat = (data.get("category") or "altro").lower().strip()
        allowed = {"lavoro","personale","finanza","salute","viaggi","casa","ricevute","documenti_identità","istruzione","note","altro"}
        if cat not in allowed: cat = "altro"
        kws = data.get("keywords") or []
        kws = [str(k).lower().strip() for k in kws if str(k).strip()][:8]
        return {"category": cat, "keywords": kws}
    except Exception:
        logger.exception("classify failed")
        return {"category": "altro", "keywords": []}


@api_router.post("/kb/upload")
async def kb_upload(file: UploadFile = File(...), current: User = Depends(get_current_user)):
    """Upload a file, extract its text and store it (chunked, with embeddings) in the user's KB.
    No Google connection required."""
    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File troppo grande (max 20 MB)")
    if not (file.filename or "").strip():
        raise HTTPException(status_code=400, detail="File senza nome")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        source_type = "file"
        try:
            if ext in IMAGE_EXTS:
                # HEIC/HEIF or exotic image: transcode to JPEG for Claude compatibility
                send_bytes = contents
                if ext in ("heic", "heif", "webp"):
                    try:
                        from PIL import Image
                        try:
                            import pillow_heif  # noqa: F401 - registers heif
                            pillow_heif.register_heif_opener()
                        except Exception:
                            pass
                        from io import BytesIO
                        img = Image.open(BytesIO(contents))
                        if img.mode not in ("RGB", "L"): img = img.convert("RGB")
                        buf = BytesIO(); img.save(buf, format="JPEG", quality=88)
                        send_bytes = buf.getvalue()
                    except Exception:
                        logger.exception("image transcode failed; using original bytes")
                text = await _ocr_image_bytes(send_bytes, file.filename)
                source_type = "image_ocr"
            else:
                text = _extract_text_from_file(tmp_path, file.filename)
        except ValueError as ve:
            raise HTTPException(status_code=415, detail=str(ve))
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("text extraction failed")
            raise HTTPException(status_code=500, detail=f"Impossibile estrarre testo: {e}")

        text = (text or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="Nessun testo estraibile dal file")

        chunks = _chunk_text(text)
        # Embed all chunks in one batch (best-effort)
        try:
            embeddings = await emb.embed_texts(chunks)
        except Exception:
            logger.exception("kb upload embedding failed")
            embeddings = [None] * len(chunks)

        # Classify (category + keywords) — best effort, does not block upload on failure
        classification = await _classify_document(text)

        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        docs = []
        for i, (chunk, e) in enumerate(zip(chunks, embeddings)):
            docs.append({
                "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
                "user_id": current.user_id,
                "text": chunk,
                "title": file.filename,
                "tags": [ext] + (["ocr"] if source_type == "image_ocr" else []) + [classification["category"]],
                "summary": chunks[0][:140] if i == 0 else None,
                "embedding": e,
                "doc_id": doc_id,
                "source_type": source_type,
                "source_name": file.filename,
                "chunk_index": i,
                "created_at": now,
            })
        if docs:
            await db.kb_chunks.insert_many(docs)

        # Persist the document-level record
        await db.kb_documents.insert_one({
            "doc_id": doc_id,
            "user_id": current.user_id,
            "name": file.filename,
            "ext": ext,
            "source_type": source_type,
            "category": classification["category"],
            "keywords": classification["keywords"],
            "chunks_count": len(docs),
            "chars": len(text),
            "size_bytes": len(contents),
            "preview": text[:280],
            "drive_link": None,      # populated in the future when Drive is connected
            "created_at": now,
        })

        return {
            "doc_id": doc_id,
            "name": file.filename,
            "size": len(contents),
            "chunks": len(docs),
            "chars": len(text),
            "preview": text[:280],
            "source_type": source_type,
            "category": classification["category"],
            "keywords": classification["keywords"],
        }
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass


# ============ KB DOCUMENTS LIST ============
@api_router.get("/kb/documents")
async def list_kb_documents(current: User = Depends(get_current_user), q: Optional[str] = None, category: Optional[str] = None):
    import re as _re
    query: dict = {"user_id": current.user_id}
    if category and category != "all":
        query["category"] = category
    if q:
        safe = _re.escape(q.strip())
        query["$or"] = [
            {"name": {"$regex": safe, "$options": "i"}},
            {"keywords": {"$regex": safe, "$options": "i"}},
            {"preview": {"$regex": safe, "$options": "i"}},
        ]
    cursor = db.kb_documents.find(query, {"_id": 0}).sort("created_at", -1).limit(500)
    docs = await cursor.to_list(500)

    # Backfill: aggregate kb_chunks for doc_ids that don't have a kb_documents entry yet
    known_ids = {d["doc_id"] for d in docs}
    pipeline = [
        {"$match": {"user_id": current.user_id}},
        {"$group": {
            "_id": {"$ifNull": ["$doc_id", "$chunk_id"]},
            "name":         {"$first": "$title"},
            "chunk_id_ref": {"$first": "$chunk_id"},
            "source_type":  {"$first": "$source_type"},
            "summary":      {"$first": "$summary"},
            "text":         {"$first": "$text"},
            "tags":         {"$first": "$tags"},
            "created_at":   {"$first": "$created_at"},
            "chunks_count": {"$sum": 1},
            "chars":        {"$sum": {"$strLenCP": {"$ifNull": ["$text", ""]}}},
        }},
    ]
    async for r in db.kb_chunks.aggregate(pipeline):
        gid = r["_id"]
        if not gid or gid in known_ids:
            continue
        known_ids.add(gid)
        name = r.get("name") or (r.get("text") or "")[:40]
        docs.append({
            "doc_id": gid,
            "user_id": current.user_id,
            "name": name or "senza titolo",
            "ext": "chat" if (r.get("source_type") == "chat") else "txt",
            "source_type": r.get("source_type") or "chat",
            "category": "altro",
            "keywords": r.get("tags") or [],
            "chunks_count": r.get("chunks_count", 1),
            "chars": r.get("chars", 0),
            "size_bytes": r.get("chars", 0),
            "preview": (r.get("summary") or r.get("text") or "")[:280],
            "drive_link": None,
            "created_at": r.get("created_at", ""),
            "legacy": True,
        })

    # If filter narrowed to empty result but legacy exists, still applies via filter above
    if category and category != "all":
        docs = [d for d in docs if d.get("category") == category]
    if q:
        needle = q.lower().strip()
        docs = [d for d in docs if needle in (d.get("name","") + " " + " ".join(d.get("keywords", []) or []) + " " + d.get("preview","")).lower()]

    docs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return docs


@api_router.get("/kb/documents/categories")
async def kb_categories(current: User = Depends(get_current_user)):
    pipe = [
        {"$match": {"user_id": current.user_id}},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    out = []
    async for r in db.kb_documents.aggregate(pipe):
        cat = r.get("_id") or "altro"
        out.append({"category": cat, "count": r.get("count", 0)})
    return out


@api_router.delete("/kb/documents/{doc_id}")
async def delete_kb_document(doc_id: str, current: User = Depends(get_current_user)):
    doc = await db.kb_documents.find_one({"doc_id": doc_id, "user_id": current.user_id}, {"_id": 0})
    # Fallback: legacy record — try to delete a single chunk by chunk_id
    if not doc:
        legacy = await db.kb_chunks.find_one({"chunk_id": doc_id, "user_id": current.user_id}, {"_id": 0})
        if not legacy:
            raise HTTPException(status_code=404, detail="Not found")
        await db.kb_chunks.delete_one({"chunk_id": doc_id, "user_id": current.user_id})
        return {"ok": True, "deleted_chunks": 1}
    await db.kb_chunks.delete_many({"doc_id": doc_id, "user_id": current.user_id})
    await db.kb_documents.delete_one({"doc_id": doc_id, "user_id": current.user_id})
    return {"ok": True}


# ============ INTEGRATIONS STATUS ============
@api_router.get("/integrations/status")
async def integrations_status(current: User = Depends(get_current_user)):
    google_doc = await db.integrations.find_one({"user_id": current.user_id, "provider": "google"}, {"_id": 0})
    user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    return {
        "google": {
            "configured": gi.is_configured(),
            "connected": bool(google_doc),
            "email": google_doc.get("email") if google_doc else None,
            "drive_folder_id": google_doc.get("drive_folder_id") if google_doc else None,
        },
        "telegram": {
            "configured": bool(tg.bot_token()),
            "connected": bool(user_doc and user_doc.get("telegram_chat_id")),
            "bot_username": await tg.bot_username(),
        },
    }


# ============ GOOGLE OAUTH ============
@api_router.get("/integrations/google/authorize")
async def google_authorize(current: User = Depends(get_current_user)):
    if not gi.is_configured():
        raise HTTPException(status_code=400, detail="Google OAuth non configurato (GOOGLE_CLIENT_ID/SECRET mancanti)")
    state = f"{current.user_id}:{secrets.token_urlsafe(16)}"
    url, code_verifier = gi.build_authorization_url(state)
    await db.google_oauth_states.insert_one({
        "state": state,
        "user_id": current.user_id,
        "code_verifier": code_verifier,
        "created_at": datetime.now(timezone.utc),
    })
    return {"authorization_url": url}


@api_router.get("/integrations/google/callback")
async def google_callback(code: str, state: str):
    st = await db.google_oauth_states.find_one({"state": state}, {"_id": 0})
    if not st:
        raise HTTPException(status_code=400, detail="Invalid state")
    user_id = st["user_id"]
    await db.google_oauth_states.delete_one({"state": state})

    try:
        creds_dict = gi.exchange_code(code, st["code_verifier"])
    except Exception as e:
        logger.exception("Google exchange failed")
        return RedirectResponse(f"{os.environ['APP_BASE_URL']}/dashboard/settings?google=error")

    # Get user email
    try:
        async with httpx.AsyncClient() as hc:
            r = await hc.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds_dict['access_token']}"},
                timeout=10.0,
            )
        google_email = r.json().get("email") if r.status_code == 200 else None
    except Exception:
        google_email = None

    doc = {**creds_dict, "provider": "google", "user_id": user_id, "email": google_email,
           "connected_at": datetime.now(timezone.utc).isoformat()}
    await db.integrations.update_one(
        {"user_id": user_id, "provider": "google"},
        {"$set": doc}, upsert=True,
    )

    # Auto-create mAIPAL folder
    try:
        creds = await gi.get_credentials(db, user_id)
        if creds:
            await gi.ensure_maipal_folder(db, user_id, creds)
    except Exception as e:
        logger.exception("mAIPAL folder creation failed")

    return RedirectResponse(f"{os.environ['APP_BASE_URL']}/dashboard/settings?google=ok")


@api_router.post("/integrations/google/disconnect")
async def google_disconnect(current: User = Depends(get_current_user)):
    await db.integrations.delete_one({"user_id": current.user_id, "provider": "google"})
    return {"ok": True}


# ============ TELEGRAM LINKING ============
@api_router.post("/integrations/telegram/link-code")
async def telegram_link_code(current: User = Depends(get_current_user)):
    if not tg.bot_token():
        raise HTTPException(status_code=400, detail="Telegram non configurato")
    # Delete any previous unused code for this user
    await db.telegram_links.delete_many({"user_id": current.user_id})
    code = secrets.token_urlsafe(8)
    await db.telegram_links.insert_one({
        "code": code,
        "user_id": current.user_id,
        "created_at": datetime.now(timezone.utc),
    })
    username = await tg.bot_username()
    return {
        "code": code,
        "bot_username": username,
        "deep_link": f"https://t.me/{username}?start={code}" if username else None,
    }


@api_router.post("/integrations/telegram/disconnect")
async def telegram_disconnect(current: User = Depends(get_current_user)):
    await db.users.update_one({"user_id": current.user_id}, {"$unset": {"telegram_chat_id": ""}})
    return {"ok": True}


# ============ VOICE STT ============
@api_router.post("/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...), current: User = Depends(get_current_user)):
    # Save to temp file with proper extension
    ext = "webm"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"):
        ext = "webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        stt = OpenAISpeechToText(api_key=EMERGENT_LLM_KEY)
        with open(tmp_path, "rb") as f:
            result = await stt.transcribe(file=f, model="whisper-1", response_format="json", language="it")
        text = getattr(result, "text", None) or (result.get("text") if isinstance(result, dict) else str(result))
        return {"text": text}
    except Exception as e:
        logger.exception("stt failed")
        raise HTTPException(status_code=500, detail=f"Trascrizione fallita: {str(e)}")
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass


# ============ NEWS ============
@api_router.get("/news")
async def list_news(current: User = Depends(get_current_user)):
    items = await db.news_items.find({"user_id": current.user_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return items


@api_router.post("/news/refresh")
async def refresh_news(current: User = Depends(get_current_user)):
    user = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        await _run_daily_news_for_user(user, today)
    except Exception as e:
        logger.exception("manual news refresh failed")
        raise HTTPException(status_code=500, detail=f"Ricerca notizie fallita: {e}")
    items = await db.news_items.find({"user_id": current.user_id, "date": today}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return items


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def start_services():
    # ===== Seed admin + whitelist =====
    try:
        await db.allowed_emails.update_one(
            {"email": ADMIN_EMAIL},
            {"$setOnInsert": {
                "email": ADMIN_EMAIL,
                "notes": "amministratore",
                "added_by": "system",
                "added_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        # If an admin user already exists, ensure role=admin
        await db.users.update_many({"email": ADMIN_EMAIL}, {"$set": {"role": "admin"}})
        logger.info(f"admin whitelist seeded for {ADMIN_EMAIL}")
    except Exception:
        logger.exception("failed to seed admin whitelist")
    try:
        asyncio.create_task(tg.start_polling())
    except Exception:
        logger.exception("failed to start telegram polling")
    try:
        asyncio.create_task(_reminders_loop())
    except Exception:
        logger.exception("failed to start reminders loop")
    try:
        asyncio.create_task(_exact_reminders_loop())
    except Exception:
        logger.exception("failed to start exact reminders loop")
    try:
        asyncio.create_task(_daily_summary_loop())
    except Exception:
        logger.exception("failed to start daily summary loop")
    try:
        asyncio.create_task(_daily_news_loop())
    except Exception:
        logger.exception("failed to start daily news loop")


async def _reminders_loop():
    """Every 30 min: for each task with due_date == tomorrow (user local ≈ UTC ok for MVP) and reminder_sent!=True,
    send a Telegram message to the connected user (if any) and mark reminder_sent."""
    from datetime import date as _date
    while True:
        try:
            today = _date.today()
            tomorrow = (today + timedelta(days=1)).isoformat()
            # find candidates
            cursor = db.tasks.find(
                {"due_date": tomorrow, "$or": [{"reminder_sent": {"$exists": False}}, {"reminder_sent": False}]},
                {"_id": 0},
            )
            async for t in cursor:
                user = await db.users.find_one({"user_id": t["user_id"]}, {"_id": 0})
                if not user or not user.get("telegram_chat_id"):
                    await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_sent": True}})
                    continue
                try:
                    from telegram import Bot
                    bot = Bot(token=tg.bot_token())
                    time_part = f" alle {t.get('due_time')}" if t.get("due_time") else ""
                    text = (
                        f"⏰ Promemoria mAIPAL\n\n"
                        f"Domani ({tomorrow}{time_part}) hai in scadenza:\n"
                        f"📌 *{t.get('title','(senza titolo)')}*\n"
                        f"{t.get('description','') or ''}\n\n"
                        f"Priorità: {t.get('priority','media')}"
                    )
                    await bot.send_message(chat_id=user["telegram_chat_id"], text=text, parse_mode="Markdown")
                    await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_sent": True, "reminder_sent_at": datetime.now(timezone.utc).isoformat()}})
                    logger.info(f"reminder sent for task {t['id']} to chat {user['telegram_chat_id']}")
                except Exception:
                    logger.exception("failed to send reminder")
        except Exception:
            logger.exception("reminders loop iteration failed")
        await asyncio.sleep(30 * 60)


async def _exact_reminders_loop():
    """Every minute: for tasks with reminder_enabled=True and reminder_msg_sent!=True,
    fire a Telegram message at (due_date + due_time - reminder_offset_minutes); offset
    defaults to 15 minutes when the user hasn't specified one. Same UTC ≈ user-local
    MVP assumption as _reminders_loop."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            today_iso = now.date().isoformat()
            tomorrow_iso = (now.date() + timedelta(days=1)).isoformat()
            cursor = db.tasks.find(
                {
                    "reminder_enabled": True,
                    "$or": [{"reminder_msg_sent": {"$exists": False}}, {"reminder_msg_sent": False}],
                    "due_date": {"$in": [today_iso, tomorrow_iso]},
                },
                {"_id": 0},
            )
            async for t in cursor:
                due_time = t.get("due_time") or "09:00"
                try:
                    due_dt = datetime.strptime(f"{t.get('due_date')} {due_time}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                offset = t.get("reminder_offset_minutes") or 15
                fire_at = due_dt - timedelta(minutes=offset)
                if now < fire_at:
                    continue
                user = await db.users.find_one({"user_id": t["user_id"]}, {"_id": 0})
                if not user or not user.get("telegram_chat_id"):
                    await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_msg_sent": True}})
                    continue
                try:
                    from telegram import Bot
                    bot = Bot(token=tg.bot_token())
                    minutes_left = max(0, round((due_dt - now).total_seconds() / 60))
                    text = (
                        f"🔔 Promemoria mAIPAL\n\n"
                        f"Tra {minutes_left} minuti ({due_time}) hai in programma:\n"
                        f"📌 *{t.get('title','(senza titolo)')}*\n"
                        f"{t.get('description','') or ''}"
                    )
                    await bot.send_message(chat_id=user["telegram_chat_id"], text=text, parse_mode="Markdown")
                    await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_msg_sent": True, "reminder_msg_sent_at": datetime.now(timezone.utc).isoformat()}})
                    logger.info(f"exact reminder sent for task {t['id']} to chat {user['telegram_chat_id']}")
                except Exception:
                    logger.exception("failed to send exact reminder")
        except Exception:
            logger.exception("exact reminders loop iteration failed")
        await asyncio.sleep(60)


async def _daily_summary_loop():
    """Every 20 min: 07:00-07:59 UTC morning summary + Sunday 19:00-19:59 weekly recap."""
    from datetime import date as _date
    PRIORITY_ORDER = {"alta": 0, "media": 1, "bassa": 2, None: 3}
    while True:
        try:
            now = datetime.now(timezone.utc)
            today = _date.today().isoformat()
            is_sunday_evening = (now.weekday() == 6 and now.hour == 19)
            is_morning = (now.hour == 7)

            if is_morning or is_sunday_evening:
                async for user in db.users.find({"telegram_chat_id": {"$exists": True}}, {"_id": 0}):
                    if is_sunday_evening:
                        week_key = f"weekly_{now.strftime('%Y-W%V')}"
                        if user.get("weekly_recap_key") == week_key:
                            continue
                        # Weekly recap: completed tasks this week + open tasks/todos
                        seven_days_ago = (now - timedelta(days=7)).isoformat()
                        done = await db.tasks.find(
                            {"user_id": user["user_id"], "completed": True, "completed_at": {"$gte": seven_days_ago}},
                            {"_id": 0},
                        ).to_list(200)
                        open_tasks = await db.tasks.find(
                            {"user_id": user["user_id"], "$or": [{"completed": {"$exists": False}}, {"completed": False}]},
                            {"_id": 0},
                        ).to_list(200)
                        open_todos = await db.todos.find(
                            {"user_id": user["user_id"], "status": {"$in": ["da_fare", "in_corso"]}},
                            {"_id": 0},
                        ).to_list(200)
                        lines = [f"📅 *Weekly Recap mAIPAL* — {user.get('name','').split(' ')[0]}", ""]
                        lines.append(f"✅ *Completati questa settimana* ({len(done)})")
                        for t in done[:10]:
                            lines.append(f"  ✓ {t.get('title','(senza titolo)')}")
                        if not done: lines.append("  _nessuno_")
                        lines.append("")
                        lines.append(f"📌 *Task aperti* ({len(open_tasks)})")
                        for t in sorted(open_tasks, key=lambda x: PRIORITY_ORDER.get(x.get('priority'), 3))[:10]:
                            e = {"alta":"🔴","media":"🟠","bassa":"⚪️"}.get(t.get('priority','media'),"⚪️")
                            lines.append(f"  {e} {t.get('title','(senza titolo)')} · {t.get('due_date','')}")
                        lines.append("")
                        lines.append(f"📝 *To-Do aperti* ({len(open_todos)})")
                        for t in sorted(open_todos, key=lambda x: PRIORITY_ORDER.get(x.get('priority'), 3))[:10]:
                            lines.append(f"  • {t.get('title','(senza titolo)')}")
                        lines.append("")
                        lines.append("Buona settimana! 🌟")
                        try:
                            from telegram import Bot
                            await Bot(token=tg.bot_token()).send_message(
                                chat_id=user["telegram_chat_id"], text="\n".join(lines), parse_mode="Markdown"
                            )
                            await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"weekly_recap_key": week_key}})
                            logger.info(f"weekly recap sent to {user['telegram_chat_id']}")
                        except Exception:
                            logger.exception("weekly recap send failed")
                        continue

                    # Morning daily summary
                    if user.get("daily_summary_date") == today:
                        continue
                    tasks_today = await db.tasks.find(
                        {"user_id": user["user_id"], "due_date": {"$lte": today}, "$or": [{"completed": {"$exists": False}}, {"completed": False}]},
                        {"_id": 0},
                    ).to_list(200)
                    tasks_today.sort(key=lambda t: (PRIORITY_ORDER.get(t.get("priority"), 3), t.get("due_date", "")))
                    open_todos = await db.todos.find(
                        {"user_id": user["user_id"], "status": {"$in": ["da_fare", "in_corso"]}},
                        {"_id": 0},
                    ).to_list(200)
                    open_todos.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority"), 3))
                    if not tasks_today and not open_todos:
                        await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"daily_summary_date": today}})
                        continue
                    lines = [f"☀️ *Buongiorno {user.get('name','').split(' ')[0]}!* Riassunto di oggi:", ""]
                    if tasks_today:
                        lines.append(f"📌 *Task* ({len(tasks_today)})")
                        for t in tasks_today[:10]:
                            e = {"alta":"🔴","media":"🟠","bassa":"⚪️"}.get(t.get("priority","media"),"⚪️")
                            when = t.get("due_date", "")
                            if t.get("due_time"): when += f" · {t['due_time']}"
                            lines.append(f"{e} {t.get('title','(senza titolo)')} — _{when}_")
                        lines.append("")
                    if open_todos:
                        lines.append(f"✅ *To-Do aperti* ({len(open_todos)})")
                        for t in open_todos[:10]:
                            e = {"alta":"🔴","media":"🟠","bassa":"⚪️"}.get(t.get("priority"),"⚪️")
                            pct = f" · {t.get('completion_percent',0)}%" if t.get("status") == "in_corso" else ""
                            lines.append(f"{e} {t.get('title','(senza titolo)')}{pct}")
                        lines.append("")
                    lines.append("Buon lavoro! 🚀")
                    try:
                        from telegram import Bot
                        await Bot(token=tg.bot_token()).send_message(
                            chat_id=user["telegram_chat_id"], text="\n".join(lines), parse_mode="Markdown"
                        )
                        await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"daily_summary_date": today}})
                        logger.info(f"daily summary sent to {user['telegram_chat_id']}")
                    except Exception:
                        logger.exception("daily summary send failed")
        except Exception:
            logger.exception("daily/weekly loop iteration failed")
        await asyncio.sleep(20 * 60)


async def _run_daily_news_for_user(user: dict, today: str):
    """Generates today's news digest for one user, stores it, and pushes it via Telegram
    if the user has a linked chat. Marks news_date=today regardless of result so the
    background loop doesn't retry a user with zero relevant news every 20 minutes."""
    items = await news_service.generate_news_for_user(user)
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"news_date": today}})
    if not items:
        return []

    docs = []
    for it in items:
        docs.append({
            "id": str(uuid.uuid4()),
            "user_id": user["user_id"],
            "title": it["title"],
            "summary": it["summary"],
            "url": it["url"],
            "source": it.get("source") or "",
            "date": today,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    await db.news_items.insert_many(docs)

    if user.get("telegram_chat_id"):
        try:
            from telegram import Bot
            bot = Bot(token=tg.bot_token())
            lines = ["🗞️ *Le tue news di oggi*", ""]
            for it in docs[:6]:
                lines.append(f"• *{it['title']}*")
                if it["summary"]:
                    lines.append(it["summary"])
                lines.append(it["url"])
                lines.append("")
            await bot.send_message(chat_id=user["telegram_chat_id"], text="\n".join(lines), parse_mode="Markdown")
            logger.info(f"daily news sent to {user['telegram_chat_id']} ({len(docs)} items)")
        except Exception:
            logger.exception("failed to send daily news via telegram")

    return docs


async def _daily_news_loop():
    """Once a day (08:00-08:19 UTC window), searches the web for news matching each
    user's profile (profession/sector/interests) and stores + sends them."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            today = now.date().isoformat()
            if now.hour == 8:
                async for user in db.users.find({}, {"_id": 0}):
                    if user.get("news_date") == today:
                        continue
                    try:
                        await _run_daily_news_for_user(user, today)
                    except Exception:
                        logger.exception(f"daily news generation failed for {user.get('user_id')}")
        except Exception:
            logger.exception("daily news loop iteration failed")
        await asyncio.sleep(20 * 60)


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        await tg.stop_polling()
    except Exception:
        pass
    client.close()
