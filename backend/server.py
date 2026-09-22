from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header, UploadFile, File, Form
from fastapi.responses import StreamingResponse, RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
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
from zoneinfo import ZoneInfo
import bcrypt

LOCAL_TZ = ZoneInfo("Europe/Rome")


def _time_str_to_today_utc(time_str: Optional[str], local_date) -> datetime:
    """Resolves a user-configured 'HH:MM' (Europe/Rome local time) to a UTC datetime on
    the given local calendar date. Falls back to 08:00 on anything malformed."""
    try:
        hh, mm = map(int, (time_str or "08:00").split(":"))
    except (ValueError, AttributeError):
        hh, mm = 8, 0
    local_dt = datetime(local_date.year, local_date.month, local_date.day, hh, mm, tzinfo=LOCAL_TZ)
    return local_dt.astimezone(timezone.utc)

from llm_integrations import LlmChat, UserMessage, TextDelta, StreamDone, ImageContent, OpenAISpeechToText

import google_integration as gi
import telegram_bot as tg
import embeddings as emb
import news_service
import vet_reports
import list_updates as lu
import usage_tracking as ut

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
ut.init(db)

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
    news_time: Optional[str] = "08:00"
    summary_time: Optional[str] = "07:00"
    business_vertical: Optional[Literal["veterinario", "fitness", "artigiano"]] = None


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
    news_time: Optional[str] = None
    summary_time: Optional[str] = None
    business_vertical: Optional[Literal["veterinario", "fitness", "artigiano"]] = None


class ChatRequest(BaseModel):
    action: Literal["info_upload", "info_request", "task_todo", "journal"]
    content: str
    filters: Optional[dict] = None
    conv_id: Optional[str] = None
    # Photos attached while writing a diary entry (action == "journal" only) - each a
    # "data:image/...;base64,..." URI, already size-checked client-side. Stored on the
    # journal entry so the Diario page can show them without depending on Google Drive.
    images: Optional[List[str]] = None
    # Non-image files attached to a diary entry (action == "journal" only) - already
    # uploaded to Drive client-side, each {"name": ..., "url": ...}.
    documents: Optional[List[dict]] = None


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
    assigned_to: Optional[str] = None
    created_at: str


class TaskAssignPayload(BaseModel):
    assigned_to: Optional[str] = None
    notify: bool = True


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
    sub_item_fields: List[CollectionFieldDef] = []  # schema per gli "elementi" annidati in ogni campo
    visibility: Literal["private", "org"] = "private"
    max_items: Optional[int] = None  # limite massimo di Campi nella lista, nullo = illimitato
    max_sub_items_per_item: Optional[int] = None  # limite massimo di Elementi per Campo, nullo = illimitato


class CollectionUpdatePayload(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    fields: Optional[List[CollectionFieldDef]] = None
    sub_item_fields: Optional[List[CollectionFieldDef]] = None
    visibility: Optional[Literal["private", "org"]] = None
    max_items: Optional[int] = None
    max_sub_items_per_item: Optional[int] = None
    clear_max_items: bool = False  # esplicito: azzera il limite invece di lasciarlo invariato
    clear_max_sub_items_per_item: bool = False


class CollectionReorderPayload(BaseModel):
    ordered_ids: List[str]  # tutti gli id delle liste visibili all'utente, nel nuovo ordine


class CollectionItemPayload(BaseModel):
    data: dict
    visibility: Optional[Literal["private", "org"]] = None


class CollectionSubItemPayload(BaseModel):
    data: dict


class ClassifySaveIntentPayload(BaseModel):
    text: str


class ListUpdatePayload(BaseModel):
    text: str
    # Set on a follow-up call resolving an earlier ambiguous_list/ambiguous_item/
    # ambiguous_sub_item result - skips re-asking the LLM and forces the given target.
    op: Optional[str] = None
    collection_id: Optional[str] = None
    item_id: Optional[str] = None
    sub_item_id: Optional[str] = None
    fields: Optional[dict] = None
    item_query: Optional[str] = None
    sub_item_query: Optional[str] = None
    # Multiple new nested Elementi to create at once (add_item/add_sub_item), e.g. several
    # people enrolled in one lesson in a single request.
    sub_items: Optional[List[dict]] = None
    # Multiple new Campi to create at once (bulk_add_items), one dict of fields per Campo -
    # e.g. one per class time parsed out of an uploaded schedule document.
    items: Optional[List[dict]] = None
    # Set on the follow-up call confirming a clear_items/clear_sub_items/bulk_add_items bulk op.
    confirm: bool = False


class NewsFeedbackPayload(BaseModel):
    value: Optional[Literal["like", "dislike"]] = None


# ---- Verticale fitness (scuole di danza/pilates): esercizi, lezioni, clienti ----
class ExerciseUpsert(BaseModel):
    name: str
    discipline: Literal["danza", "pilates", "altro"] = "altro"
    category: Optional[str] = ""
    level: Optional[Literal["base", "intermedio", "avanzato"]] = None
    equipment: Optional[str] = ""
    duration_minutes: Optional[int] = None
    notes: Optional[str] = ""
    visibility: Literal["private", "org"] = "private"


class LessonExerciseItem(BaseModel):
    exercise_id: str
    notes: Optional[str] = ""


class LessonTemplateUpsert(BaseModel):
    name: str
    discipline: Literal["danza", "pilates", "altro"] = "altro"
    level: Optional[Literal["base", "intermedio", "avanzato"]] = None
    exercises: List[LessonExerciseItem] = []
    notes: Optional[str] = ""
    visibility: Literal["private", "org"] = "private"


class ClientUpsert(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    enrollment_date: Optional[str] = None
    subscription_type: Optional[str] = ""
    medical_certificate_expiry: Optional[str] = None
    notes: Optional[str] = ""
    visibility: Literal["private", "org"] = "private"


class LessonGuidelinesPayload(BaseModel):
    text: str


class GenerateLessonPayload(BaseModel):
    prompt: str


# ---- Verticale veterinario: report visita ----
class GenerateVetReportPayload(BaseModel):
    text: str
    visit_type: str  # "imaging" | "general" | id di un template personalizzato
    patient_item_id: Optional[str] = None  # forza un paziente specifico (risoluzione ambiguità nome)


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
    # Usage tracking (see usage_tracking.py) - never keeps metadata for a deleted account,
    # per the tracking spec's privacy requirement. llm_calls/feature_events rows are
    # anonymized (user_id -> null) rather than deleted outright: they still feed the
    # aggregate usage_daily numbers (system-wide cost/token totals must stay accurate),
    # they carry no prompt/response content to begin with, and the null user_id is the
    # same "no owning user" shape already used for background-job calls. usage_daily rows
    # for this user are removed outright since they're a derived per-user aggregate.
    r = await db.llm_calls.update_many({"user_id": user_id}, {"$set": {"user_id": None}})
    counts["llm_calls_anonymized"] = r.modified_count
    r = await db.feature_events.update_many({"user_id": user_id}, {"$set": {"user_id": None}})
    counts["feature_events_anonymized"] = r.modified_count
    r = await db.usage_daily.delete_many({"user_id": user_id})
    counts["usage_daily"] = r.deleted_count
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
    if updates.get("business_vertical") == "veterinario":
        await _ensure_vet_patients_list(current)
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


# ============ TEAM (org condivisa, gestita dall'amministratore) ============
def _gen_org_code() -> str:
    return secrets.token_hex(3).upper()  # es. "A1B2C3"


class TeamInviteCreate(BaseModel):
    email: str


@api_router.get("/org")
async def get_org(current: User = Depends(get_current_user)):
    """Vista di sola lettura del team a cui appartiene l'utente corrente."""
    if not current.org_id:
        return None
    org = await db.organizations.find_one({"id": current.org_id}, {"_id": 0})
    if not org:
        return None
    members = await db.users.find(
        {"org_id": current.org_id},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "picture": 1, "org_role": 1, "telegram_chat_id": 1},
    ).to_list(200)
    for m in members:
        m["has_telegram"] = bool(m.pop("telegram_chat_id", None))
    org["members"] = members
    return org


@api_router.post("/org/join")
async def join_org(payload: OrgJoinPayload, current: User = Depends(get_current_user)):
    if current.org_id:
        raise HTTPException(status_code=400, detail="Fai già parte di un team. Esci prima di unirti a un altro.")
    code = (payload.code or "").strip().upper()
    org = await db.organizations.find_one({"join_code": code}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Codice non valido")
    invite = await db.team_invites.find_one({"org_id": org["id"], "email": current.email.lower()}, {"_id": 0})
    if not invite:
        raise HTTPException(status_code=403, detail="Il tuo indirizzo email non è stato invitato a questo team. Contatta l'amministratore.")
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"org_id": org["id"], "org_role": "member"}})
    await db.team_invites.delete_one({"org_id": org["id"], "email": current.email.lower()})
    return org


@api_router.post("/org/leave")
async def leave_org(current: User = Depends(get_current_user)):
    if not current.org_id:
        raise HTTPException(status_code=400, detail="Non fai parte di un team")
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"org_id": None, "org_role": None}})
    return {"ok": True}


# ---- Gestione team (solo amministratore): crea più team, invita per email, fornisce
# il codice d'invito, rimuove membri. La creazione/appartenenza non è più self-service:
# un utente può unirsi solo a un team a cui è stato esplicitamente invitato.
async def _team_with_details(org: dict) -> dict:
    members = await db.users.find(
        {"org_id": org["id"]}, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "picture": 1}
    ).to_list(200)
    invites = await db.team_invites.find({"org_id": org["id"]}, {"_id": 0}).sort("invited_at", -1).to_list(200)
    return {**org, "members": members, "invites": invites}


@api_router.get("/admin/teams")
async def admin_list_teams(current: User = Depends(require_admin)):
    orgs = await db.organizations.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return [await _team_with_details(o) for o in orgs]


@api_router.post("/admin/teams")
async def admin_create_team(payload: OrgCreatePayload, current: User = Depends(require_admin)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obbligatorio")
    org_doc = {
        "id": f"org_{uuid.uuid4().hex[:12]}",
        "name": name,
        "join_code": _gen_org_code(),
        "created_by": current.user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.organizations.insert_one(org_doc)
    org_doc.pop("_id", None)
    return {**org_doc, "members": [], "invites": []}


@api_router.patch("/admin/teams/{team_id}")
async def admin_rename_team(team_id: str, payload: OrgRenamePayload, current: User = Depends(require_admin)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obbligatorio")
    r = await db.organizations.update_one({"id": team_id}, {"$set": {"name": name}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Team non trovato")
    org = await db.organizations.find_one({"id": team_id}, {"_id": 0})
    return await _team_with_details(org)


@api_router.post("/admin/teams/{team_id}/regenerate-code")
async def admin_regenerate_team_code(team_id: str, current: User = Depends(require_admin)):
    org = await db.organizations.find_one({"id": team_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Team non trovato")
    new_code = _gen_org_code()
    await db.organizations.update_one({"id": team_id}, {"$set": {"join_code": new_code}})
    return {"join_code": new_code}


@api_router.delete("/admin/teams/{team_id}")
async def admin_delete_team(team_id: str, current: User = Depends(require_admin)):
    org = await db.organizations.find_one({"id": team_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Team non trovato")
    await db.users.update_many({"org_id": team_id}, {"$set": {"org_id": None, "org_role": None}})
    await db.team_invites.delete_many({"org_id": team_id})
    await db.organizations.delete_one({"id": team_id})
    return {"ok": True}


@api_router.post("/admin/teams/{team_id}/invites")
async def admin_invite_to_team(team_id: str, payload: TeamInviteCreate, current: User = Depends(require_admin)):
    org = await db.organizations.find_one({"id": team_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Team non trovato")
    email = (payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email non valida")
    already_member = await db.users.find_one({"email": email, "org_id": team_id}, {"_id": 0})
    if already_member:
        raise HTTPException(status_code=400, detail="Questa persona fa già parte del team")
    await db.team_invites.update_one(
        {"org_id": team_id, "email": email},
        {
            "$set": {"org_id": team_id, "email": email},
            "$setOnInsert": {"id": f"inv_{uuid.uuid4().hex[:12]}", "invited_by": current.email, "invited_at": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )
    return await db.team_invites.find_one({"org_id": team_id, "email": email}, {"_id": 0})


@api_router.delete("/admin/teams/{team_id}/invites/{email}")
async def admin_remove_team_invite(team_id: str, email: str, current: User = Depends(require_admin)):
    await db.team_invites.delete_one({"org_id": team_id, "email": (email or "").strip().lower()})
    return {"ok": True}


@api_router.delete("/admin/teams/{team_id}/members/{member_user_id}")
async def admin_remove_team_member(team_id: str, member_user_id: str, current: User = Depends(require_admin)):
    r = await db.users.update_one({"user_id": member_user_id, "org_id": team_id}, {"$set": {"org_id": None, "org_role": None}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Membro non trovato in questo team")
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
            "REGOLA CRITICA SU GOOGLE DRIVE: il salvataggio del file su Google Drive (se richiesto) è un processo "
            "separato ed eseguito da un altro componente, di cui NON hai visibilità diretta in questo momento — "
            "NON dare mai per scontato che un file sia stato salvato su Drive o in una cartella specifica solo perché "
            "l'utente lo ha chiesto. Conferma il salvataggio su Drive SOLO se nel messaggio è presente una riga di "
            "stato automatica che lo conferma esplicitamente (es. 'File salvato su Drive in ...'); se è presente una "
            "riga che indica un errore o che la cartella non è stata determinata, comunicalo onestamente; se non è "
            "presente nessuna riga di stato su Drive, non menzionare affatto Drive nella tua risposta. "
            "Se nel testo è chiaramente presente ANCHE un impegno futuro da ricordare (una richiesta esplicita tipo "
            "'ricordami di...', o un'azione futura con una data/intervallo di tempo esplicito o facilmente calcolabile "
            "dalla data odierna, es. 'tra 10 giorni', 'lunedì prossimo'), crea ANCHE un task: aggiungi il campo 'task' "
            "nei metadati con la data calcolata. REGOLA CRITICA: aggiungi il campo 'task' SOLO se sei certo della data "
            "e dell'azione da ricordare — se la data è ambigua, implicita in modo incerto, o non c'è nessuna azione "
            "futura da ricordare, ometti del tutto il campo 'task' (non inventare o indovinare una data). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"...\", \"summary\": \"riassunto in 1 riga, max 140 caratteri\", \"tags\": [\"...\"], "
            "\"task\": {\"title\": \"breve titolo del task\", \"due_date\": \"YYYY-MM-DD\", \"due_time\": \"HH:MM o null\", "
            "\"priority\": \"alta|media|bassa\", \"notes\": \"\"} oppure ometti del tutto la chiave 'task' se non applicabile}"
            "<<<END>>>"
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
            "Il tuo compito è SOLO editoriale: (1) sistemare il testo (grammatica, punteggiatura, chiarezza) mantenendo "
            "la voce personale in prima persona, (2) organizzare in paragrafi coerenti. "
            "REGOLA CRITICA: non aggiungere MAI fatti, dettagli, emozioni o commenti sullo stato d'animo non esplicitamente "
            "scritti dall'utente (es. non scrivere 'sono molto felice' o 'è stata una giornata dura' se l'utente non lo ha "
            "detto lui stesso) - riscrivi solo ciò che c'è, non interpretarlo né arricchirlo. "
            "Rispondi con il diario riscritto in modo naturale (senza intestazioni tipo 'Diario:'). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"titolo breve della giornata (max 6 parole)\", "
            "\"summary\": \"riassunto in 1 riga max 140 caratteri\", "
            "\"mood\": \"parola singola dedotta dal testo, SOLO per uso interno (non va scritta nel diario): "
            "felice|neutro|stressato|riflessivo|energico|stanco|grato\", "
            "\"tags\": [\"1-3 parole chiave che riassumono gli argomenti della giornata, es. lavoro, famiglia, sport, salute\"], "
            "\"highlights\": [\"1-3 momenti chiave estratti letteralmente dal testo\"]}<<<END>>>"
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


def _clear_cached_embedding(payload: dict, text_fields: set):
    """retrieve_kb caches a lazily-computed semantic embedding on tasks/todos/list items
    (see _EMBED_SOURCE_COLLECTIONS below) so it isn't recomputed on every search. If this
    update touches one of the fields that embedding was computed from, drop the stale
    cache so the next search recomputes it from the new text."""
    if any(f in payload for f in text_fields):
        payload["embedding"] = None


# Maps a retrieve_kb candidate "source" to the Mongo collection its document lives in,
# used to persist a lazily-computed embedding back onto the document itself (see below).
_EMBED_SOURCE_COLLECTIONS = {
    "task": db.tasks,
    "todo": db.todos,
    "journal": db.journal_entries,
    "collection_item": db.collection_items,
    "collection_sub_item": db.collection_sub_items,
    "vet_report": db.vet_reports,
}


async def retrieve_kb(user_id: str, query: str, limit: int = 8, scope: str = "kb", org_id: Optional[str] = None) -> List[dict]:
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
    forced: set = set()  # id() of candidate dicts guaranteed into `top` regardless of score
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

    # Tasks and Liste can be shared with a team (visibility="org"), not just owned by
    # this user - miss that and a colleague's shared patient list is invisible to search.
    def _owned_or_shared(query_field: str = "user_id") -> dict:
        if org_id:
            return {"$or": [{query_field: user_id}, {"org_id": org_id, "visibility": "org"}]}
        return {query_field: user_id}

    if scope == "all":
        tasks = await db.tasks.find(_owned_or_shared(), {"_id": 0}).to_list(500)
        for t in tasks:
            txt_parts = [t.get("title", ""), t.get("description", ""), t.get("notes", "")]
            txt = " · ".join([p for p in txt_parts if p])
            if not txt: continue
            when = t.get("due_date", "") + (f" {t.get('due_time','')}" if t.get("due_time") else "")
            display = f"[Task] {t.get('title','')} — {when} · priorità {t.get('priority','media')}. {t.get('description','') or ''}".strip()
            candidates.append({"text": txt, "display": display, "source": "task", "meta": {"id": t.get("id")}, "embedding": t.get("embedding")})
        todos = await db.todos.find({"user_id": user_id}, {"_id": 0}).to_list(500)
        for td in todos:
            txt_parts = [td.get("title", ""), td.get("description", ""), td.get("notes", "")]
            txt = " · ".join([p for p in txt_parts if p])
            if not txt: continue
            display = f"[To-Do] {td.get('title','')} — stato {td.get('status','da_fare')} ({td.get('completion_percent',0)}%). {td.get('description','') or ''}".strip()
            candidates.append({"text": txt, "display": display, "source": "todo", "meta": {"id": td.get("id")}, "embedding": td.get("embedding")})
        journal_docs = await db.journal_entries.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(200)
        for j in journal_docs:
            txt = (j.get("cleaned_text") or j.get("raw_text") or "").strip()
            if not txt: continue
            display = f"[Diario · {j.get('date','')}] {j.get('title','')} · mood: {j.get('mood','')}. {txt[:400]}".strip()
            candidates.append({"text": txt, "display": display, "source": "journal", "meta": {"id": j.get("id"), "date": j.get("date")}, "embedding": j.get("embedding")})
        vet_report_docs = await db.vet_reports.find({"user_id": user_id}, {"_id": 0, "docx_b64": 0}).sort("created_at", -1).to_list(500)
        for vrp in vet_report_docs:
            txt = (vrp.get("transcript") or "").strip()
            if not txt: continue
            who = vrp.get("patient_name") or "paziente non identificato"
            visit_date = (vrp.get("created_at") or "")[:10]
            display = f"[Referto veterinario · {visit_date}] {who} — {vrp.get('template_name','')}. {txt[:400]}".strip()
            candidates.append({
                "text": f"{who} {txt}",
                "display": display,
                "source": "vet_report",
                "meta": {"id": vrp.get("id"), "patient_item_id": vrp.get("patient_item_id"), "date": visit_date},
                "embedding": vrp.get("embedding"),
            })

    # Liste (Collections): fetched and force-matchable regardless of scope - a query that
    # explicitly names a Lista or one of its Campi (e.g. "quante persone nella lezione di
    # pilates di lunedì mattina") should find it even under the default scope="kb", not
    # only when the user has opted into the broader "tutto" search. Only the REGULAR
    # (non-forced, normally-scored) per-item candidates stay scope="all"-only below.
    colls = await db.collections.find(_owned_or_shared(), {"_id": 0}).to_list(200)
    if colls:
        coll_map = {c["id"]: c for c in colls}
        coll_items = await db.collection_items.find({"collection_id": {"$in": list(coll_map.keys())}}, {"_id": 0}).to_list(2000)
        item_display_map: dict = {}  # item_id -> display text, used below to match a Campo by name
        item_candidates: List[dict] = []
        for it in coll_items:
            coll = coll_map.get(it.get("collection_id"))
            if not coll: continue
            field_labels = {f["key"]: f["label"] for f in (coll.get("fields") or [])}
            parts = [f"{field_labels.get(k, k)}: {v}" for k, v in (it.get("data") or {}).items() if v not in (None, "")]
            if not parts: continue
            txt = " · ".join(parts)
            display = f"[Lista: {coll.get('name', '')}] {txt}"
            cand = {"text": txt, "display": display, "source": "collection_item", "meta": {"id": it.get("id"), "collection_id": it.get("collection_id")}, "embedding": it.get("embedding")}
            item_candidates.append(cand)
            item_display_map[it["id"]] = txt
        if scope == "all":
            candidates.extend(item_candidates)

        # "Quali pazienti ho in lista?" style questions need the WHOLE list, not just
        # the fragments that happen to score well against a generic question - no
        # single item's text closely resembles "quali pazienti ho". If the query names
        # one of the user's lists, force-include ALL of its items regardless of semantic/
        # keyword score (and regardless of scope). Same fuzzy matcher as "Modifica liste"
        # (token-overlap, not a strict substring) so plural/singular or extra words in the
        # question (e.g. "lezione di pilates" vs a list named "Lezioni Pilates") don't
        # silently miss an otherwise obvious match - this deterministic name-matching,
        # not an LLM guess, is what decides whether a question gets this exhaustive,
        # guaranteed-complete answer path instead of the regular fuzzy-scored search.
        named_coll_ids = set(lu.match_candidates(query, [(c["id"], c["name"]) for c in colls if (c.get("name") or "").strip()]))
        if named_coll_ids:
            for cand in item_candidates:
                if cand["meta"].get("collection_id") in named_coll_ids:
                    if scope != "all":
                        candidates.append(cand)
                    forced.add(id(cand))

        # A Campo named in the question (e.g. "lezione di pilates di lunedì mattina") is
        # matched with the same fuzzy matcher "Modifica liste" uses - this catches it even
        # when the query doesn't repeat the Lista's own name verbatim (singular/plural,
        # extra words, etc. can all break the exact-substring named-list check above).
        # Force BOTH the Campo's own candidate (its answer may sit directly in its own
        # fields, e.g. a 2-level list) AND all of its nested Elementi (a 3-level list, e.g.
        # people enrolled in a lesson) - a partial sample of either would silently give a
        # wrong count for a question like "quante persone ci sono".
        if item_display_map:
            matched_item_ids = set(lu.match_candidates(query, list(item_display_map.items())))
            if matched_item_ids:
                item_by_id = {c["meta"]["id"]: c for c in item_candidates}
                for iid in matched_item_ids:
                    cand = item_by_id.get(iid)
                    if not cand: continue
                    if scope != "all":
                        candidates.append(cand)
                    forced.add(id(cand))

                sub_items_all = await db.collection_sub_items.find(
                    {"item_id": {"$in": list(matched_item_ids)}}, {"_id": 0}
                ).to_list(5000)
                item_coll_map = {it["id"]: it.get("collection_id") for it in coll_items}
                for s in sub_items_all:
                    if s.get("item_id") not in matched_item_ids:
                        continue
                    coll = coll_map.get(s.get("collection_id") or item_coll_map.get(s.get("item_id")))
                    if not coll: continue
                    sub_field_labels = {f["key"]: f["label"] for f in (coll.get("sub_item_fields") or [])}
                    sub_parts = [f"{sub_field_labels.get(k, k)}: {v}" for k, v in (s.get("data") or {}).items() if v not in (None, "")]
                    if not sub_parts: continue
                    sub_txt = " · ".join(sub_parts)
                    parent_txt = item_display_map.get(s.get("item_id"), "")
                    display = f"[Lista: {coll.get('name','')} > {parent_txt}] {sub_txt}"
                    cand = {
                        "text": sub_txt, "display": display, "source": "collection_sub_item",
                        "meta": {"id": s.get("id"), "item_id": s.get("item_id"), "collection_id": s.get("collection_id")},
                        "embedding": s.get("embedding"),
                    }
                    candidates.append(cand)
                    forced.add(id(cand))

    # A query naming a specific month+year (e.g. "luglio 2026") should surface any
    # candidate whose text literally contains that same month+year - one specific monthly
    # data point (e.g. one of twelve monthly bills) can score just below other same-topic
    # candidates and fall outside `limit`, the same structural gap the named-list force-
    # include above addresses. Runs unconditionally (not just scope=='all') since kb_chunks
    # - where a monthly document most likely lives - are always in the candidate pool.
    _IT_MONTHS_LOW = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                       "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    query_low_full = query.lower()
    date_month = next((m for m in _IT_MONTHS_LOW if m in query_low_full), None)
    date_year_m = _re.search(r"\b(19|20)\d{2}\b", query_low_full)
    if date_month and date_year_m:
        date_year = date_year_m.group(0)
        for c in candidates:
            ctext_low = c["text"].lower()
            if date_month in ctext_low and date_year in ctext_low:
                forced.add(id(c))

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
        # Tasks/todos/journal/list items/vet reports never had their embeddings persisted,
        # so "tutto" search recomputed one for EVERY such record on EVERY query - the
        # dominant cost that made search noticeably slower as a user's data grew. Cache
        # them on the source document itself (same pattern as kb_chunks above) so a
        # record's embedding is computed once and reused; the update endpoints below
        # clear the cached value whenever the text it was computed from changes.
        non_kb = [c for c in candidates if c["source"] != "kb" and not c.get("embedding")]
        if non_kb:
            try:
                nk_embs = await emb.embed_texts([c["text"] for c in non_kb])
                from pymongo import UpdateOne
                writes_by_source: dict = {}
                for c, e in zip(non_kb, nk_embs):
                    c["embedding"] = e
                    doc_id = (c.get("meta") or {}).get("id")
                    if doc_id and c["source"] in _EMBED_SOURCE_COLLECTIONS:
                        writes_by_source.setdefault(c["source"], []).append(UpdateOne({"id": doc_id}, {"$set": {"embedding": e}}))
                for source, ops in writes_by_source.items():
                    try:
                        await _EMBED_SOURCE_COLLECTIONS[source].bulk_write(ops, ordered=False)
                    except Exception:
                        logger.exception(f"embedding cache write failed for source={source}")
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

    # Keep chunks that have EITHER decent semantic score OR at least one keyword match,
    # OR are force-included (a named list's items, or a candidate matching a month+year
    # named in the query - see `forced` above).
    def _is_forced(s) -> bool:
        return id(s[3]) in forced

    scored = [s for s in scored if s[1] >= 0.20 or s[2] >= 1 or _is_forced(s)]
    forced_scored = [s for s in scored if _is_forced(s)]
    rest_scored = [s for s in scored if not _is_forced(s)]
    rest_scored.sort(key=lambda x: x[0], reverse=True)
    # Forced items (e.g. every patient in a list the question names) always make it in,
    # even past `limit` - otherwise a long list starves itself out of its own answer.
    top = [c for _s, _sem, _kh, c in forced_scored] + [c for _s, _sem, _kh, c in rest_scored[:max(0, limit - len(forced_scored))]]

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


# Usage tracking: the chat "action" field already tells us which catalog feature (§4 of
# the usage-tracking spec) a chat_stream/telegram _process_action call belongs to.
# task_todo can resolve to either a task or a to-do only after the LLM answers (see
# _create_task_or_todo's due_date rule) - tracked as creazione_task either way, since the
# feature can't be known yet at call time.
_ACTION_TO_FEATURE = {
    "info_request": "ricerca_informazioni",
    "info_upload": "caricamento_informazioni",
    "task_todo": "creazione_task",
    "journal": "diario",
}


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
            scope = (conv.get("filters", {}) or {}).get("scope", "all")
        else:
            scope = (payload.filters or {}).get("scope", "all")
        kb_context = await retrieve_kb(current.user_id, payload.content, scope=scope, org_id=current.org_id)
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
        user_id=current.user_id, feature=_ACTION_TO_FEATURE.get(action, "altro"),
        channel="web", trigger="utente", org_id=current.org_id,
    ).with_model("openai", "gpt-4o")

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

        # One feature_events row per chat turn, regardless of how many (if any) LLM calls
        # it triggered - lets the usage dashboard count feature USES, not just LLM calls.
        ut.fire_and_forget_feature_event(
            user_id=current.user_id, feature=_ACTION_TO_FEATURE.get(action, "altro"),
            channel="web", trigger="utente", org_id=current.org_id,
        )

        # info_upload always persists a new KB chunk on EVERY user turn - unlike
        # task_todo/journal below, a follow-up message in an ongoing "Salva informazioni"
        # conversation is virtually always a NEW distinct fact to remember (e.g. "oggi
        # Martina ha fatto lezione di Pilates" followed later by "venerdì scorso Martina ha
        # fatto lezione di Pilates" - two separate facts, both needed for "quando ha fatto
        # Pilates Martina?" to be answerable), not a duplicate of the first message. Gating
        # this on `not prior_messages` (first turn only) silently dropped every fact stated
        # in a follow-up turn - it never became retrievable, with no error to the user.
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
                classification = await _classify_document(payload.content, user_id=current.user_id, channel="web")
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
            # If a clearly-dated follow-up action was embedded in the uploaded info
            # (e.g. "ricordami di chiedere come sta tra 10 giorni"), the model attaches
            # a 'task' field to the meta - only when it's certain of the date.
            if meta and meta.get("task") and isinstance(meta["task"], dict) and meta["task"].get("due_date"):
                try:
                    await _create_task_or_todo(current.user_id, meta["task"], conv_id)
                except Exception:
                    logger.exception("auto task creation from info_upload failed")

        # side-effects only on first exchange of task/journal actions - a follow-up turn is
        # normally a refinement of the SAME task/entry, not a brand new one.
        if not prior_messages:
            if action == "task_todo":
                logger.info(f"[task_todo] meta={meta!r}")
                if meta:
                    await _create_task_or_todo(current.user_id, meta, conv_id)
            elif action == "journal":
                from datetime import date as _date
                # Each image is a "data:image/...;base64,..." URI, already size-checked
                # client-side - re-checked here (max 5, ~2MB decoded each) since the app
                # always renders straight from this field, independent of Google Drive.
                valid_images: List[str] = []
                for img in (payload.images or [])[:5]:
                    if not isinstance(img, str) or not img.startswith("data:image/") or "," not in img:
                        continue
                    try:
                        if len(img.split(",", 1)[1]) * 3 / 4 > 2 * 1024 * 1024:
                            continue
                    except Exception:
                        continue
                    valid_images.append(img)

                # Non-image documents (already uploaded to Drive client-side by the time
                # they get here) - just {"name", "url"} references, nothing to re-validate.
                valid_documents = [
                    {"name": str(d.get("name") or "documento"), "url": str(d["url"])}
                    for d in (payload.documents or [])
                    if isinstance(d, dict) and d.get("url")
                ]

                jr = {
                    "id": f"jr_{uuid.uuid4().hex[:12]}",
                    "user_id": current.user_id,
                    "date": _date.today().isoformat(),
                    "raw_text": payload.content,
                    "cleaned_text": visible_answer,
                    "title": (meta or {}).get("title", ""),
                    "mood": (meta or {}).get("mood", ""),
                    "tags": (meta or {}).get("tags", []),
                    "highlights": (meta or {}).get("highlights", []),
                    "images": valid_images,
                    "documents": valid_documents,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_conv": conv_id,
                }
                await db.journal_entries.insert_one(jr)

                # Best-effort backup copy on Drive (Diario subfolder) when connected - the
                # app itself always displays the images straight from `jr["images"]` above,
                # this is purely for the user's own organization/backup on Drive.
                if valid_images:
                    try:
                        creds = await gi.get_credentials(db, current.user_id)
                        if creds:
                            folder_id = await gi.find_or_create_subfolder(db, current.user_id, creds, "Diario")
                            import base64 as _b64
                            for idx, img in enumerate(valid_images):
                                header, b64_part = img.split(",", 1)
                                content_type = header.split(":", 1)[1].split(";", 1)[0] or "image/jpeg"
                                ext = content_type.split("/", 1)[-1] or "jpg"
                                raw = _b64.b64decode(b64_part)
                                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                                    tmp.write(raw)
                                    tmp_path = tmp.name
                                try:
                                    gi.upload_file_to_folder(creds, folder_id, tmp_path, f"diario_{jr['date']}_{idx + 1}.{ext}", content_type)
                                finally:
                                    try: os.unlink(tmp_path)
                                    except Exception: pass
                    except Exception:
                        logger.exception("Drive backup of journal images failed")

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


async def _create_task_or_todo(user_id: str, parsed: dict, conv_id: str, default_reminder_enabled: bool = False):
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
            # A web-created task defaults the reminder off (there's a one-click toggle on
            # the card to turn it on); a Telegram-created one has no such toggle, so the
            # caller passes default_reminder_enabled=True there instead.
            "reminder_enabled": reminder_offset_minutes is not None or default_reminder_enabled,
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


async def interpret_task_command(text: str, catalog: List[dict], user_id: Optional[str] = None, channel: str = "web") -> Optional[dict]:
    """Cheap LLM check: is this free text asking to DELETE or mark-COMPLETE an EXISTING
    task/to-do (as opposed to creating a new one, or an unrelated message)? Returns None
    when it isn't - the caller then falls through to normal task/to-do creation, exactly
    like classify_save_intent does for "Modifica liste" vs a generic note."""
    if not catalog:
        return None
    catalog_desc = ", ".join(f'"{c["title"]}"' for c in catalog[:50])
    system = (
        "Sei l'assistente che interpreta richieste su task/to-do ESISTENTI dell'utente. "
        f"Task/to-do attivi dell'utente: {catalog_desc}. "
        "Se il messaggio chiede di ELIMINARE/CANCELLARE/RIMUOVERE un task o to-do esistente, oppure di segnarlo "
        "come COMPLETATO/FATTO/FINITO, rispondi SOLO con un JSON: "
        '{"op": "delete", "query": "testo breve che identifica il task/to-do"} oppure '
        '{"op": "complete", "query": "..."}. '
        "Se il messaggio NON è un'istruzione di questo tipo (es. sta creando/descrivendo un NUOVO task/to-do, o è "
        'un messaggio generico), rispondi SOLO con: {"op": null}.'
    )
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"taskcmd_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=user_id, feature="creazione_task", channel=channel, trigger="utente",
        ).with_model("openai", "gpt-4o-mini")
        raw = (await chat.send_message(UserMessage(text=text))).strip()
        import re as _re, json as _json
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m:
            return None
        parsed = _json.loads(m.group(0))
        if parsed.get("op") not in ("delete", "complete"):
            return None
        return {"op": parsed["op"], "query": (parsed.get("query") or "").strip()}
    except Exception:
        logger.exception("interpret_task_command failed")
        return None


async def _apply_task_command(target_id: str, op: str, user_id: str) -> dict:
    """Actually deletes/completes a task or to-do, given a resolved id (from
    _execute_task_command, or from the caller re-invoking after an ambiguous choice).
    Always scoped to `user_id` so a crafted id from one user can never touch another's."""
    is_task = target_id.startswith("task_")
    coll = db.tasks if is_task else db.todos
    doc = await coll.find_one({"id": target_id, "user_id": user_id}, {"_id": 0})
    if not doc:
        return {"status": "not_found"}
    title = doc.get("title", "")
    label = "il task" if is_task else "il to-do"
    if op == "delete":
        await coll.delete_one({"id": target_id, "user_id": user_id})
        return {"status": "ok", "message": f"Ho eliminato {label} \"{title}\"."}
    if is_task:
        await coll.update_one({"id": target_id, "user_id": user_id}, {"$set": {"completed": True, "completed_at": datetime.now(timezone.utc).isoformat()}})
    else:
        await coll.update_one({"id": target_id, "user_id": user_id}, {"$set": {"status": "fatto", "completion_percent": 100}})
    return {"status": "ok", "message": f"Ho segnato come completato {label} \"{title}\"."}


async def _execute_task_command(user_id: str, text: str, channel: str = "web") -> Optional[dict]:
    """Returns None if `text` isn't a delete/complete instruction on an existing task/
    to-do (the caller should fall through to normal creation). Otherwise resolves the
    target deterministically (same fuzzy matcher as _execute_list_update, never an
    LLM-picked id) and performs the action. Returns {"status": "ok"|"ambiguous"|
    "not_found", ...}."""
    tasks = await db.tasks.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    todos = await db.todos.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    catalog = [{"id": t["id"], "title": t.get("title", "")} for t in tasks] + [{"id": t["id"], "title": t.get("title", "")} for t in todos]
    if not catalog:
        return None
    interpreted = await interpret_task_command(text, catalog, user_id=user_id, channel=channel)
    if not interpreted:
        return None
    ids = lu.match_candidates(interpreted["query"] or text, [(c["id"], c["title"]) for c in catalog])
    if not ids:
        return {"status": "not_found", "query": interpreted["query"]}
    if len(ids) > 1:
        by_id = {c["id"]: c for c in catalog}
        return {"status": "ambiguous", "op": interpreted["op"], "candidates": [{"id": i, "title": by_id[i]["title"]} for i in ids]}
    result = await _apply_task_command(ids[0], interpreted["op"], user_id)
    is_task = ids[0].startswith("task_")
    ut.fire_and_forget_feature_event(
        user_id=user_id, feature="creazione_task" if is_task else "creazione_todo", channel=channel, trigger="utente",
    )
    return result


class TaskCommandPayload(BaseModel):
    text: str


class TaskCommandApplyPayload(BaseModel):
    target_id: str
    op: str


@api_router.post("/tasks/command")
async def run_task_command(payload: TaskCommandPayload, current: User = Depends(get_current_user)):
    """Web chat's counterpart to the Telegram bot's task-command fast path: lets "Salva
    task/to-do" also handle 'elimina/segna come fatto il task X' instead of just creating
    new ones. Returns {"status": "not_applicable"} when the text isn't such an instruction,
    so the caller can fall through to normal task/to-do creation."""
    res = await _execute_task_command(current.user_id, payload.text, channel="web")
    return res or {"status": "not_applicable"}


@api_router.post("/tasks/command/apply")
async def apply_task_command(payload: TaskCommandApplyPayload, current: User = Depends(get_current_user)):
    """Follow-up call once the user picked one of an 'ambiguous' result's candidates."""
    if payload.op not in ("delete", "complete"):
        raise HTTPException(status_code=400, detail="Operazione non valida")
    result = await _apply_task_command(payload.target_id, payload.op, current.user_id)
    is_task = payload.target_id.startswith("task_")
    ut.fire_and_forget_feature_event(
        user_id=current.user_id, feature="creazione_task" if is_task else "creazione_todo", channel="web", trigger="utente",
    )
    return result


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

    _clear_cached_embedding(payload, {"title", "description", "notes"})
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
    _clear_cached_embedding(payload, {"title", "description", "notes"})
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


@api_router.post("/tasks/{task_id}/assign")
async def assign_task(task_id: str, payload: TaskAssignPayload, current: User = Depends(get_current_user)):
    if not current.org_id:
        raise HTTPException(status_code=400, detail="Serve un'organizzazione per assegnare i task")
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update = {"assigned_to": payload.assigned_to}
    assignee = None
    if payload.assigned_to:
        assignee = await db.users.find_one({"user_id": payload.assigned_to, "org_id": current.org_id}, {"_id": 0})
        if not assignee:
            raise HTTPException(status_code=404, detail="Membro non trovato nell'organizzazione")
        # assigning shares the task with the team, so the assignee can actually see it
        update["visibility"] = "org"
        update["org_id"] = current.org_id

    await db.tasks.update_one({"id": task_id, **_editable_query(current)}, {"$set": update})
    doc = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})

    if payload.assigned_to and payload.notify and assignee and assignee.get("telegram_chat_id") and assignee["user_id"] != current.user_id:
        try:
            from telegram import Bot
            bot = Bot(token=tg.bot_token())
            due_part = f"\n📅 Scadenza: {doc.get('due_date')}" if doc.get("due_date") else ""
            notes_line = f"\n📝 {doc['notes']}" if doc.get("notes") else ""
            text = (
                f"📋 {current.name} ti ha assegnato un task\n\n"
                f"📌 *{doc.get('title','(senza titolo)')}*"
                f"{due_part}"
                f"{notes_line}"
            )
            await bot.send_message(chat_id=assignee["telegram_chat_id"], text=text, parse_mode="Markdown")
        except Exception:
            logger.exception("failed to send assignment notification")

    return doc


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
    # Backfill sort_order (added for drag-to-reorder) for lists that predate it, keeping
    # the order they already had (by creation date) instead of jumping around on first load.
    missing = [c for c in collections if c.get("sort_order") is None]
    if missing:
        from pymongo import UpdateOne
        next_order = max([c.get("sort_order", -1) for c in collections if c.get("sort_order") is not None], default=-1) + 1
        ops = []
        for c in missing:
            c["sort_order"] = next_order
            ops.append(UpdateOne({"id": c["id"]}, {"$set": {"sort_order": next_order}}))
            next_order += 1
        await db.collections.bulk_write(ops)
    collections.sort(key=lambda c: c["sort_order"])
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


@api_router.patch("/collections/reorder")
async def reorder_collections(payload: CollectionReorderPayload, current: User = Depends(get_current_user)):
    """Persists the drag-and-drop order from the Liste page. Silently ignores any id the
    caller can't edit or that doesn't exist, rather than failing the whole reorder."""
    editable = await db.collections.find({**_editable_query(current)}, {"_id": 0, "id": 1}).to_list(500)
    editable_ids = {c["id"] for c in editable}
    ids = [i for i in payload.ordered_ids if i in editable_ids]
    if not ids:
        raise HTTPException(status_code=400, detail="Nessuna lista valida da riordinare")
    from pymongo import UpdateOne
    ops = [UpdateOne({"id": cid}, {"$set": {"sort_order": idx}}) for idx, cid in enumerate(ids)]
    await db.collections.bulk_write(ops)
    return {"ok": True}


@api_router.post("/collections")
async def create_collection(payload: CollectionCreatePayload, current: User = Depends(get_current_user)):
    if not payload.fields:
        raise HTTPException(status_code=400, detail="Definisci almeno un campo per la lista")
    if payload.max_items is not None and payload.max_items < 1:
        raise HTTPException(status_code=400, detail="Il limite di Campi deve essere almeno 1")
    if payload.max_sub_items_per_item is not None and payload.max_sub_items_per_item < 1:
        raise HTTPException(status_code=400, detail="Il limite di Elementi per Campo deve essere almeno 1")
    name = payload.name.strip() or "Nuova lista"
    existing = await db.collections.find(_visible_query(current), {"_id": 0, "name": 1, "sort_order": 1}).to_list(500)
    if any((e.get("name") or "").strip().lower() == name.lower() for e in existing):
        raise HTTPException(status_code=400, detail=f"Esiste già una lista chiamata \"{name}\".")
    next_order = max([e.get("sort_order", -1) for e in existing], default=-1) + 1
    doc = {
        "id": f"coll_{uuid.uuid4().hex[:12]}",
        "name": name,
        "icon": payload.icon,
        "fields": [f.model_dump() for f in payload.fields],
        "sub_item_fields": [f.model_dump() for f in payload.sub_item_fields],
        "visibility": payload.visibility,
        "max_items": payload.max_items,
        "max_sub_items_per_item": payload.max_sub_items_per_item,
        "sort_order": next_order,
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
    if payload.sub_item_fields is not None:
        updates["sub_item_fields"] = [f.model_dump() for f in payload.sub_item_fields]
    if payload.visibility is not None:
        if payload.visibility == "org" and current.org_id:
            updates["visibility"] = "org"
            updates["org_id"] = current.org_id
        else:
            updates["visibility"] = "private"
            updates["org_id"] = None
    if payload.clear_max_items:
        updates["max_items"] = None
    elif payload.max_items is not None:
        if payload.max_items < 1:
            raise HTTPException(status_code=400, detail="Il limite di Campi deve essere almeno 1")
        updates["max_items"] = payload.max_items
    if payload.clear_max_sub_items_per_item:
        updates["max_sub_items_per_item"] = None
    elif payload.max_sub_items_per_item is not None:
        if payload.max_sub_items_per_item < 1:
            raise HTTPException(status_code=400, detail="Il limite di Elementi per Campo deve essere almeno 1")
        updates["max_sub_items_per_item"] = payload.max_sub_items_per_item
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
    await db.collection_sub_items.delete_many({"collection_id": collection_id})
    return {"ok": True}


@api_router.get("/collections/{collection_id}/items")
async def list_collection_items(collection_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_visible_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    cursor = db.collection_items.find({"collection_id": collection_id}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(1000)
    # Backfill sort_order (added for drag-to-reorder) for Campi that predate it, keeping
    # the order they already had (by creation date) instead of jumping around on first load.
    missing = [it for it in items if it.get("sort_order") is None]
    if missing:
        from pymongo import UpdateOne
        next_order = max([it.get("sort_order", -1) for it in items if it.get("sort_order") is not None], default=-1) + 1
        ops = []
        for it in missing:
            it["sort_order"] = next_order
            ops.append(UpdateOne({"id": it["id"]}, {"$set": {"sort_order": next_order}}))
            next_order += 1
        await db.collection_items.bulk_write(ops)
    items.sort(key=lambda it: it["sort_order"])
    ids = [it["id"] for it in items]
    if ids:
        counts = await db.collection_sub_items.aggregate([
            {"$match": {"collection_id": collection_id, "item_id": {"$in": ids}}},
            {"$group": {"_id": "$item_id", "n": {"$sum": 1}}},
        ]).to_list(len(ids))
        count_map = {c["_id"]: c["n"] for c in counts}
        for it in items:
            it["sub_item_count"] = count_map.get(it["id"], 0)
    return items


@api_router.post("/collections/{collection_id}/items")
async def create_collection_item(collection_id: str, payload: CollectionItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_visible_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    max_items = coll.get("max_items")
    if max_items:
        current_count = await db.collection_items.count_documents({"collection_id": collection_id})
        if current_count >= max_items:
            raise HTTPException(status_code=400, detail=f"Hai raggiunto il limite di {max_items} elementi per la lista \"{coll['name']}\".")
    # The first field is the item's display "name" convention (used everywhere else, e.g.
    # itemLabel in CollectionsPage.jsx) - two items sharing it would be indistinguishable.
    name_field = (coll.get("fields") or [None])[0]
    if name_field:
        new_val = str(payload.data.get(name_field["key"]) or "").strip().lower()
        if new_val:
            existing = await db.collection_items.find({"collection_id": collection_id}, {"_id": 0, "data": 1}).to_list(2000)
            if any(str((e.get("data") or {}).get(name_field["key"]) or "").strip().lower() == new_val for e in existing):
                raise HTTPException(status_code=400, detail=f"Esiste già un elemento con {name_field['label']} \"{payload.data.get(name_field['key'])}\" in questa lista.")
    existing_orders = await db.collection_items.find({"collection_id": collection_id}, {"_id": 0, "sort_order": 1}).to_list(2000)
    next_order = max([o.get("sort_order") for o in existing_orders if o.get("sort_order") is not None], default=-1) + 1
    doc = {
        "id": f"item_{uuid.uuid4().hex[:12]}",
        "collection_id": collection_id,
        "data": payload.data,
        "visibility": payload.visibility or coll.get("visibility", "private"),
        "sort_order": next_order,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.collection_items.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/collections/{collection_id}/items/reorder")
async def reorder_collection_items(collection_id: str, payload: CollectionReorderPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    existing = await db.collection_items.find({"collection_id": collection_id}, {"_id": 0, "id": 1}).to_list(2000)
    existing_ids = {it["id"] for it in existing}
    ids = [i for i in payload.ordered_ids if i in existing_ids]
    if not ids:
        raise HTTPException(status_code=400, detail="Nessun campo valido da riordinare")
    from pymongo import UpdateOne
    ops = [UpdateOne({"id": iid, "collection_id": collection_id}, {"$set": {"sort_order": idx}}) for idx, iid in enumerate(ids)]
    await db.collection_items.bulk_write(ops)
    return {"ok": True}


@api_router.patch("/collections/{collection_id}/items/{item_id}")
async def update_collection_item(collection_id: str, item_id: str, payload: CollectionItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    updates = {"data": payload.data, "embedding": None}
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
    await db.collection_sub_items.delete_many({"collection_id": collection_id, "item_id": item_id})
    return {"ok": True}


# ---- Elementi (livello 3): annidati dentro un campo/item specifico ----
@api_router.get("/collections/{collection_id}/items/{item_id}/sub-items")
async def list_sub_items(collection_id: str, item_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_visible_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    cursor = db.collection_sub_items.find({"collection_id": collection_id, "item_id": item_id}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(1000)


@api_router.post("/collections/{collection_id}/items/{item_id}/sub-items")
async def create_sub_item(collection_id: str, item_id: str, payload: CollectionSubItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_visible_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    item = await db.collection_items.find_one({"id": item_id, "collection_id": collection_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Campo non trovato")
    max_sub_items = coll.get("max_sub_items_per_item")
    if max_sub_items:
        current_count = await db.collection_sub_items.count_documents({"collection_id": collection_id, "item_id": item_id})
        if current_count >= max_sub_items:
            raise HTTPException(status_code=400, detail=f"Hai raggiunto il limite di {max_sub_items} elementi per questo campo.")
    name_field = (coll.get("sub_item_fields") or [None])[0]
    if name_field:
        new_val = str(payload.data.get(name_field["key"]) or "").strip().lower()
        if new_val:
            existing = await db.collection_sub_items.find({"collection_id": collection_id, "item_id": item_id}, {"_id": 0, "data": 1}).to_list(500)
            if any(str((e.get("data") or {}).get(name_field["key"]) or "").strip().lower() == new_val for e in existing):
                raise HTTPException(status_code=400, detail=f"Esiste già un elemento con {name_field['label']} \"{payload.data.get(name_field['key'])}\" in questo campo.")
    doc = {
        "id": f"sub_{uuid.uuid4().hex[:12]}",
        "collection_id": collection_id,
        "item_id": item_id,
        "data": payload.data,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.collection_sub_items.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/collections/{collection_id}/items/{item_id}/sub-items/{sub_id}")
async def update_sub_item(collection_id: str, item_id: str, sub_id: str, payload: CollectionSubItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    r = await db.collection_sub_items.update_one(
        {"id": sub_id, "collection_id": collection_id, "item_id": item_id}, {"$set": {"data": payload.data, "embedding": None}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Elemento non trovato")
    return await db.collection_sub_items.find_one({"id": sub_id, "collection_id": collection_id}, {"_id": 0})


@api_router.delete("/collections/{collection_id}/items/{item_id}/sub-items/{sub_id}")
async def delete_sub_item(collection_id: str, item_id: str, sub_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_editable_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    r = await db.collection_sub_items.delete_one({"id": sub_id, "collection_id": collection_id, "item_id": item_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Elemento non trovato")
    return {"ok": True}


# ---- Rilevamento automatico "salva nota" vs "modifica lista" (un solo tasto in chat) ----
@api_router.post("/classify-save-intent")
async def classify_save_intent(payload: ClassifySaveIntentPayload, current: User = Depends(get_current_user)):
    colls = await db.collections.find(_visible_query(current), {"_id": 0, "name": 1}).to_list(200)
    kind = await lu.classify_save_intent(payload.text, [c["name"] for c in colls], user_id=current.user_id, channel="web")
    return {"kind": kind}


# ---- Modifica delle Liste da testo libero (chat web + Telegram) ----
@api_router.post("/lists/update")
async def update_list_via_text(payload: ListUpdatePayload, current: User = Depends(get_current_user)):
    return await _execute_list_update(
        current, payload.text, op=payload.op, collection_id=payload.collection_id,
        item_id=payload.item_id, sub_item_id=payload.sub_item_id, fields=payload.fields,
        item_query=payload.item_query, sub_item_query=payload.sub_item_query, confirm=payload.confirm,
        new_sub_items=payload.sub_items, new_items=payload.items,
    )


async def _execute_list_update(
    current: User, text: str, op: Optional[str] = None, collection_id: Optional[str] = None,
    item_id: Optional[str] = None, sub_item_id: Optional[str] = None, fields: Optional[dict] = None,
    item_query: Optional[str] = None, sub_item_query: Optional[str] = None, confirm: bool = False,
    new_sub_items: Optional[List[dict]] = None, new_items: Optional[List[dict]] = None, channel: str = "web",
) -> dict:
    """Shared by the web endpoint and the Telegram bot (same process, no HTTP round-trip).

    Two-phase flow, same shape as _generate_vet_report's ambiguous-patient handling:
    1. First call (only `text` given): the LLM extracts intent (op, target list, free-text
       description of the target item/sub-item, field values). Which list/item/sub-item is
       actually meant is then resolved deterministically (match_candidates) - if that's
       unambiguous the edit runs immediately; if not, an "ambiguous_*" result is returned
       with candidates for the caller to show as choices.
    2. Follow-up call (op/collection_id/fields carried over, plus a resolved item_id/
       sub_item_id): applies the edit directly, no LLM call.
    A bulk op (clear_items/clear_sub_items - "cancella tutti/tutte...") is never applied
    on the first call: it first returns a "confirm_clear" result with the count of records
    that would be deleted, and only deletes once the caller re-calls with confirm=True -
    a fuzzy-matched "delete everything" is exactly the kind of hard-to-reverse action that
    deserves an explicit yes, unlike a single delete_item/delete_sub_item match.
    """
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Scrivi cosa vuoi modificare nella lista")

    colls = await db.collections.find(_visible_query(current), {"_id": 0}).to_list(200)
    if not colls:
        raise HTTPException(status_code=400, detail="Non hai ancora nessuna lista. Creane una nella sezione Liste prima di poter usare questa funzione.")
    coll_by_id = {c["id"]: c for c in colls}

    if not op or not collection_id:
        catalog = [{"id": c["id"], "name": c["name"], "fields": c.get("fields", []), "sub_item_fields": c.get("sub_item_fields", [])} for c in colls]
        # Give the interpreter a shot at the user's own uploaded documents too - e.g. "crea
        # un campo per ogni orario delle lezioni di pilates" only makes sense if it can see
        # the schedule that was OCR'd/extracted into the KB in an earlier message.
        kb_context = ""
        try:
            kb_hits = await retrieve_kb(current.user_id, text, limit=4, scope="kb", org_id=current.org_id)
            kb_context = "\n---\n".join((h.get("text") or "").strip() for h in kb_hits if (h.get("text") or "").strip())[:6000]
        except Exception:
            logger.exception("KB context retrieval for list update failed")
        try:
            interpreted = await lu.interpret_list_request(text, catalog, kb_context=kb_context, user_id=current.user_id, channel=channel)
        except Exception as e:
            logger.exception("list update interpretation failed")
            raise HTTPException(status_code=500, detail=f"Non sono riuscito a interpretare la richiesta: {e}")
        op = interpreted["op"]
        collection_id = interpreted["collection_id"]
        item_query = interpreted["item_query"]
        sub_item_query = interpreted["sub_item_query"]
        fields = interpreted["fields"]
        new_sub_items = interpreted["sub_items"]
        new_items = interpreted["items"]

    if op not in lu.VALID_OPS:
        raise HTTPException(status_code=400, detail="Non ho capito che tipo di modifica vuoi fare a una lista.")

    if not collection_id or collection_id not in coll_by_id:
        return {
            "status": "ambiguous_list", "op": op, "fields": fields or {}, "item_query": item_query,
            "sub_item_query": sub_item_query, "text": text, "sub_items": new_sub_items or [],
            "candidates": [{"collection_id": c["id"], "name": c["name"]} for c in colls],
        }

    coll = coll_by_id[collection_id]
    items = await db.collection_items.find({"collection_id": collection_id}, {"_id": 0}).to_list(2000)

    item = None
    if op not in ("add_item", "clear_items", "bulk_add_items"):
        if item_id:
            item = next((i for i in items if i["id"] == item_id), None)
            if not item:
                raise HTTPException(status_code=404, detail="Elemento non trovato nella lista")
        else:
            ids = lu.match_candidates(item_query or text, [(i["id"], lu.item_display(i)) for i in items])
            if not ids:
                raise HTTPException(status_code=404, detail=f"Non ho trovato nulla in \"{coll['name']}\" che corrisponda a \"{item_query or text}\".")
            if len(ids) > 1:
                by_id = {i["id"]: i for i in items}
                return {
                    "status": "ambiguous_item", "collection_id": collection_id, "op": op, "fields": fields or {},
                    "item_query": item_query, "sub_item_query": sub_item_query, "text": text,
                    "sub_items": new_sub_items or [],
                    "candidates": [{"item_id": iid, "label": lu.item_display(by_id[iid])} for iid in ids],
                }
            item = next(i for i in items if i["id"] == ids[0])

    sub_item = None
    if op in ("add_sub_item", "delete_sub_item", "update_sub_item", "clear_sub_items"):
        sub_items = await db.collection_sub_items.find({"collection_id": collection_id, "item_id": item["id"]}, {"_id": 0}).to_list(500)
        if op not in ("add_sub_item", "clear_sub_items"):
            if sub_item_id:
                sub_item = next((s for s in sub_items if s["id"] == sub_item_id), None)
                if not sub_item:
                    raise HTTPException(status_code=404, detail="Elemento annidato non trovato")
            else:
                ids = lu.match_candidates(sub_item_query or text, [(s["id"], lu.item_display(s)) for s in sub_items])
                if not ids:
                    raise HTTPException(status_code=404, detail=f"Non ho trovato nulla che corrisponda a \"{sub_item_query or text}\" dentro \"{lu.item_display(item)}\".")
                if len(ids) > 1:
                    by_id = {s["id"]: s for s in sub_items}
                    return {
                        "status": "ambiguous_sub_item", "collection_id": collection_id, "item_id": item["id"], "op": op,
                        "fields": fields or {}, "item_query": item_query, "sub_item_query": sub_item_query, "text": text,
                        "sub_items": new_sub_items or [],
                        "candidates": [{"sub_item_id": sid, "label": lu.item_display(by_id[sid])} for sid in ids],
                    }
                sub_item = next(s for s in sub_items if s["id"] == ids[0])

    norm_new_items: List[dict] = []
    if op == "bulk_add_items" and new_items:
        for it in new_items:
            nf = lu.normalize_fields(it or {}, coll.get("fields", []))
            if nf:
                norm_new_items.append(nf)

    if op == "bulk_add_items" and not confirm:
        if not norm_new_items:
            raise HTTPException(status_code=400, detail="Non ho trovato dati sufficienti per creare i nuovi elementi (magari il documento caricato non contiene informazioni chiare a riguardo).")
        max_items = coll.get("max_items")
        current_count = len(items)
        if max_items and current_count + len(norm_new_items) > max_items:
            raise HTTPException(status_code=400, detail=f"Creare {len(norm_new_items)} nuovi elementi supererebbe il limite di {max_items} per \"{coll['name']}\" (attualmente {current_count}).")
        preview_lines = "\n".join(f"{i + 1}. {lu.item_display({'data': f})}" for i, f in enumerate(norm_new_items))
        return {
            "status": "confirm_bulk_add", "op": op, "collection_id": collection_id, "fields": {},
            "item_query": item_query, "sub_item_query": sub_item_query, "text": text, "count": len(norm_new_items),
            "items": norm_new_items,
            "message": f"Sto per creare {len(norm_new_items)} nuovi elementi in \"{coll['name']}\":\n{preview_lines}",
            "candidates": [{"confirm": True, "label": f"Conferma: crea {len(norm_new_items)} elementi in \"{coll['name']}\""}],
        }

    if op == "clear_items" and not confirm:
        if not items:
            ut.fire_and_forget_feature_event(user_id=current.user_id, feature="gestione_liste", channel=channel, trigger="utente", org_id=current.org_id)
            return {"status": "ok", "message": f"\"{coll['name']}\" è già vuota, nulla da eliminare.", "collection_id": collection_id, "collection_name": coll["name"]}
        return {
            "status": "confirm_clear", "op": op, "collection_id": collection_id, "fields": {},
            "item_query": item_query, "sub_item_query": sub_item_query, "text": text, "count": len(items),
            "candidates": [{"confirm": True, "label": f"Conferma: elimina tutti e {len(items)} gli elementi di \"{coll['name']}\""}],
        }
    if op == "clear_sub_items" and not confirm:
        if not sub_items:
            ut.fire_and_forget_feature_event(user_id=current.user_id, feature="gestione_liste", channel=channel, trigger="utente", org_id=current.org_id)
            return {"status": "ok", "message": f"\"{lu.item_display(item)}\" è già vuoto, nulla da eliminare.", "collection_id": collection_id, "collection_name": coll["name"]}
        return {
            "status": "confirm_clear", "op": op, "collection_id": collection_id, "item_id": item["id"], "fields": {},
            "item_query": item_query, "sub_item_query": sub_item_query, "text": text, "count": len(sub_items),
            "candidates": [{"confirm": True, "label": f"Conferma: elimina tutti e {len(sub_items)} gli elementi di \"{lu.item_display(item)}\""}],
        }

    if op in ("add_item", "update_item"):
        norm_fields = lu.normalize_fields(fields or {}, coll.get("fields", []))
    elif op in ("add_sub_item", "update_sub_item"):
        norm_fields = lu.normalize_fields(fields or {}, coll.get("sub_item_fields", []))
    else:
        norm_fields = {}

    # Several new Elementi at once (e.g. "aggiungi utente1, utente2 e utente3 alla lezione..."):
    # only relevant for add_item (populate the new Campo right away) and add_sub_item.
    norm_new_sub_items: List[dict] = []
    if op in ("add_item", "add_sub_item") and new_sub_items:
        for s in new_sub_items:
            nf = lu.normalize_fields(s or {}, coll.get("sub_item_fields", []))
            if nf:
                norm_new_sub_items.append(nf)

    if op == "add_item":
        if not norm_fields:
            raise HTTPException(status_code=400, detail="Non ho trovato nessun dato da salvare per il nuovo elemento.")
        created = await create_collection_item(collection_id, CollectionItemPayload(data=norm_fields), current)
        sub_created = [await create_sub_item(collection_id, created["id"], CollectionSubItemPayload(data=e), current) for e in norm_new_sub_items]
        if sub_created:
            names = ", ".join(f"\"{lu.item_display(c)}\"" for c in sub_created)
            summary = f"Ho aggiunto \"{lu.item_display(created)}\" a \"{coll['name']}\" con {len(sub_created)} elementi: {names}."
        else:
            summary = f"Ho aggiunto \"{lu.item_display(created)}\" a \"{coll['name']}\"."
    elif op == "delete_item":
        await delete_collection_item(collection_id, item["id"], current)
        summary = f"Ho rimosso \"{lu.item_display(item)}\" da \"{coll['name']}\"."
    elif op == "clear_items":
        item_ids = [i["id"] for i in items]
        await db.collection_items.delete_many({"collection_id": collection_id, "id": {"$in": item_ids}})
        await db.collection_sub_items.delete_many({"collection_id": collection_id, "item_id": {"$in": item_ids}})
        summary = f"Ho eliminato tutti e {len(item_ids)} gli elementi di \"{coll['name']}\"."
    elif op == "update_item":
        merged = {**item.get("data", {}), **norm_fields}
        updated = await update_collection_item(collection_id, item["id"], CollectionItemPayload(data=merged), current)
        summary = f"Ho aggiornato \"{lu.item_display(updated)}\" in \"{coll['name']}\"."
    elif op == "add_sub_item":
        entries = list(norm_new_sub_items)
        if norm_fields:
            entries.append(norm_fields)
        if not entries:
            raise HTTPException(status_code=400, detail="Non ho trovato nessun dato da salvare per il nuovo elemento.")
        created_list = [await create_sub_item(collection_id, item["id"], CollectionSubItemPayload(data=e), current) for e in entries]
        names = ", ".join(f"\"{lu.item_display(c)}\"" for c in created_list)
        summary = f"Ho aggiunto {names} a \"{lu.item_display(item)}\" ({coll['name']})."
    elif op == "delete_sub_item":
        await delete_sub_item(collection_id, item["id"], sub_item["id"], current)
        summary = f"Ho rimosso \"{lu.item_display(sub_item)}\" da \"{lu.item_display(item)}\" ({coll['name']})."
    elif op == "clear_sub_items":
        await db.collection_sub_items.delete_many({"collection_id": collection_id, "item_id": item["id"]})
        summary = f"Ho eliminato tutti e {len(sub_items)} gli elementi di \"{lu.item_display(item)}\" ({coll['name']})."
    elif op == "update_sub_item":
        merged = {**sub_item.get("data", {}), **norm_fields}
        updated = await update_sub_item(collection_id, item["id"], sub_item["id"], CollectionSubItemPayload(data=merged), current)
        summary = f"Ho aggiornato \"{lu.item_display(updated)}\" in \"{lu.item_display(item)}\" ({coll['name']})."
    elif op == "bulk_add_items":
        created_list = [await create_collection_item(collection_id, CollectionItemPayload(data=f), current) for f in norm_new_items]
        summary = f"Ho creato {len(created_list)} nuovi elementi in \"{coll['name']}\"."

    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="gestione_liste", channel=channel, trigger="utente", org_id=current.org_id)
    return {"status": "ok", "message": summary, "collection_id": collection_id, "collection_name": coll["name"]}


# ============ FITNESS: ESERCIZI / LEZIONI / CLIENTI ============
@api_router.get("/exercises")
async def list_exercises(current: User = Depends(get_current_user)):
    cursor = db.exercises.find(_visible_query(current), {"_id": 0}).sort("name", 1)
    return await cursor.to_list(500)


@api_router.post("/exercises")
async def create_exercise(payload: ExerciseUpsert, current: User = Depends(get_current_user)):
    doc = {
        "id": f"ex_{uuid.uuid4().hex[:12]}",
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.exercises.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/exercises/{exercise_id}")
async def update_exercise(exercise_id: str, payload: dict, current: User = Depends(get_current_user)):
    payload.pop("id", None); payload.pop("user_id", None); payload.pop("_id", None); payload.pop("org_id", None)
    if "visibility" in payload:
        if payload["visibility"] == "org" and current.org_id:
            payload["org_id"] = current.org_id
        else:
            payload["visibility"] = "private"
            payload["org_id"] = None
    await db.exercises.update_one({"id": exercise_id, **_editable_query(current)}, {"$set": payload})
    doc = await db.exercises.find_one({"id": exercise_id, **_editable_query(current)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Esercizio non trovato")
    return doc


@api_router.delete("/exercises/{exercise_id}")
async def delete_exercise(exercise_id: str, current: User = Depends(get_current_user)):
    r = await db.exercises.delete_one({"id": exercise_id, **_editable_query(current)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Esercizio non trovato")
    return {"ok": True}


@api_router.get("/lesson-templates")
async def list_lesson_templates(current: User = Depends(get_current_user)):
    cursor = db.lesson_templates.find(_visible_query(current), {"_id": 0}).sort("name", 1)
    return await cursor.to_list(500)


@api_router.post("/lesson-templates")
async def create_lesson_template(payload: LessonTemplateUpsert, current: User = Depends(get_current_user)):
    doc = {
        "id": f"lsn_{uuid.uuid4().hex[:12]}",
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.lesson_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/lesson-templates/{lesson_id}")
async def update_lesson_template(lesson_id: str, payload: dict, current: User = Depends(get_current_user)):
    payload.pop("id", None); payload.pop("user_id", None); payload.pop("_id", None); payload.pop("org_id", None)
    if "visibility" in payload:
        if payload["visibility"] == "org" and current.org_id:
            payload["org_id"] = current.org_id
        else:
            payload["visibility"] = "private"
            payload["org_id"] = None
    await db.lesson_templates.update_one({"id": lesson_id, **_editable_query(current)}, {"$set": payload})
    doc = await db.lesson_templates.find_one({"id": lesson_id, **_editable_query(current)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Lezione non trovata")
    return doc


@api_router.delete("/lesson-templates/{lesson_id}")
async def delete_lesson_template(lesson_id: str, current: User = Depends(get_current_user)):
    r = await db.lesson_templates.delete_one({"id": lesson_id, **_editable_query(current)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lezione non trovata")
    return {"ok": True}


@api_router.get("/clients")
async def list_clients(current: User = Depends(get_current_user)):
    cursor = db.clients.find(_visible_query(current), {"_id": 0}).sort("name", 1)
    return await cursor.to_list(1000)


@api_router.post("/clients")
async def create_client(payload: ClientUpsert, current: User = Depends(get_current_user)):
    doc = {
        "id": f"cli_{uuid.uuid4().hex[:12]}",
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.clients.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/clients/{client_id}")
async def update_client(client_id: str, payload: dict, current: User = Depends(get_current_user)):
    payload.pop("id", None); payload.pop("user_id", None); payload.pop("_id", None); payload.pop("org_id", None)
    if "visibility" in payload:
        if payload["visibility"] == "org" and current.org_id:
            payload["org_id"] = current.org_id
        else:
            payload["visibility"] = "private"
            payload["org_id"] = None
    await db.clients.update_one({"id": client_id, **_editable_query(current)}, {"$set": payload})
    doc = await db.clients.find_one({"id": client_id, **_editable_query(current)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    return doc


@api_router.delete("/clients/{client_id}")
async def delete_client(client_id: str, current: User = Depends(get_current_user)):
    r = await db.clients.delete_one({"id": client_id, **_editable_query(current)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    return {"ok": True}


def _fitness_owner_key(current: User) -> str:
    """Lesson guidelines belong to the whole studio, not a single member - shared by org
    if there is one, otherwise scoped to the solo user."""
    return current.org_id or current.user_id


@api_router.get("/fitness/guidelines")
async def get_lesson_guidelines(current: User = Depends(get_current_user)):
    doc = await db.lesson_guidelines.find_one({"owner_key": _fitness_owner_key(current)}, {"_id": 0})
    return {"text": (doc or {}).get("text", "")}


@api_router.put("/fitness/guidelines")
async def set_lesson_guidelines(payload: LessonGuidelinesPayload, current: User = Depends(get_current_user)):
    owner_key = _fitness_owner_key(current)
    await db.lesson_guidelines.update_one(
        {"owner_key": owner_key},
        {"$set": {
            "owner_key": owner_key,
            "text": payload.text,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": current.email,
        }},
        upsert=True,
    )
    return {"text": payload.text}


@api_router.post("/fitness/generate-lesson")
async def generate_lesson(payload: GenerateLessonPayload, current: User = Depends(get_current_user)):
    """Builds a lesson template from a free-text request (e.g. 'lezione funzionale per 10
    persone, 40 minuti, livello medio, focus gambe'), reusing existing exercises where
    possible and proposing new ones - which get added to the shared exercise database -
    when nothing suitable already exists. Always follows the studio's saved guidelines
    (e.g. 'sempre 5 minuti di stretching a inizio e fine')."""
    import re as _re, json as _json

    if not (payload.prompt or "").strip():
        raise HTTPException(status_code=400, detail="Descrivi la lezione che vuoi creare")

    exercises = await db.exercises.find(_visible_query(current), {"_id": 0}).to_list(500)
    guidelines_doc = await db.lesson_guidelines.find_one({"owner_key": _fitness_owner_key(current)}, {"_id": 0})
    guidelines_text = (guidelines_doc or {}).get("text", "").strip()

    exercises_listing = "\n".join(
        f"- id={e['id']} | {e['name']} | disciplina={e['discipline']} | categoria={e.get('category') or '—'} | "
        f"livello={e.get('level') or '—'} | durata={e.get('duration_minutes') or '—'}min | attrezzatura={e.get('equipment') or '—'}"
        for e in exercises
    ) or "(nessun esercizio nel database ancora: proponi tu gli esercizi necessari come nuovi)"

    guidelines_block = (
        f"\nLinee guida fisse dello studio, da rispettare SEMPRE nella costruzione della lezione:\n{guidelines_text}\n"
        if guidelines_text else ""
    )

    system = (
        "Sei l'assistente di segreteria di una scuola di danza/pilates. Componi il piano di una lezione a partire "
        "dalla richiesta in linguaggio naturale della titolare (numero di persone, durata, livello, focus/obiettivo). "
        "Riusa quando possibile gli esercizi già presenti nel database sotto. Se per soddisfare la richiesta "
        "servono esercizi che non esistono ancora, proponili come nuovi: verranno aggiunti automaticamente al "
        "database condiviso."
        f"{guidelines_block}\n"
        "Database esercizi disponibili:\n"
        f"{exercises_listing}\n\n"
        "Rispondi SOLO con un JSON valido (nessun testo prima o dopo, nessun markdown), in questo formato esatto:\n"
        '{"name": "nome breve della lezione", "discipline": "danza|pilates|altro", '
        '"level": "base|intermedio|avanzato", "notes": "note generali sulla lezione (n. persone, obiettivo, ecc.)", '
        '"sequence": [ '
        '{"exercise_id": "id di un esercizio esistente dalla lista sopra", "item_notes": "nota opzionale per questo esercizio in questa lezione"} '
        "OPPURE "
        '{"new_exercise": {"name": "...", "discipline": "danza|pilates|altro", "category": "...", '
        '"level": "base|intermedio|avanzato", "equipment": "...", "duration_minutes": 5, "notes": "..."}, "item_notes": "..."} '
        "] }\n"
        "La somma delle duration_minutes degli esercizi in sequence deve avvicinarsi alla durata totale richiesta."
    )

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"lesson_gen_{uuid.uuid4().hex[:8]}",
        system_message=system,
        user_id=current.user_id, feature="creazione_lezioni", channel="web", trigger="utente", org_id=current.org_id,
    ).with_model("openai", "gpt-4o")
    raw = await chat.send_message(UserMessage(text=payload.prompt))
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="creazione_lezioni", channel="web", trigger="utente", org_id=current.org_id)

    match = _re.search(r"\{.*\}", raw or "", _re.DOTALL)
    if not match:
        raise HTTPException(status_code=500, detail="Non sono riuscito a generare la lezione, riprova.")
    try:
        parsed = _json.loads(match.group(0))
    except _json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Risposta AI non valida, riprova.")

    exercises_by_id = {e["id"]: e for e in exercises}
    final_sequence = []
    new_exercise_count = 0

    for item in (parsed.get("sequence") or []):
        if not isinstance(item, dict):
            continue
        item_notes = (item.get("item_notes") or "").strip()

        ref_id = item.get("exercise_id")
        if ref_id and ref_id in exercises_by_id:
            final_sequence.append({"exercise_id": ref_id, "notes": item_notes})
            continue

        new_ex = item.get("new_exercise")
        if isinstance(new_ex, dict) and (new_ex.get("name") or "").strip():
            duration = new_ex.get("duration_minutes")
            try:
                duration = int(duration) if duration is not None else None
            except (TypeError, ValueError):
                duration = None
            ex_doc = {
                "id": f"ex_{uuid.uuid4().hex[:12]}",
                "name": new_ex["name"].strip()[:200],
                "discipline": new_ex.get("discipline") if new_ex.get("discipline") in ("danza", "pilates", "altro") else "altro",
                "category": (new_ex.get("category") or "").strip(),
                "level": new_ex.get("level") if new_ex.get("level") in ("base", "intermedio", "avanzato") else None,
                "equipment": (new_ex.get("equipment") or "").strip(),
                "duration_minutes": duration,
                "notes": (new_ex.get("notes") or "").strip(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _stamp_owner_fields(ex_doc, current)
            await db.exercises.insert_one(ex_doc)
            ex_doc.pop("_id", None)
            exercises_by_id[ex_doc["id"]] = ex_doc
            final_sequence.append({"exercise_id": ex_doc["id"], "notes": item_notes})
            new_exercise_count += 1

    lesson_doc = {
        "id": f"lsn_{uuid.uuid4().hex[:12]}",
        "name": (parsed.get("name") or "Lezione generata").strip()[:200],
        "discipline": parsed.get("discipline") if parsed.get("discipline") in ("danza", "pilates", "altro") else "altro",
        "level": parsed.get("level") if parsed.get("level") in ("base", "intermedio", "avanzato") else None,
        "notes": (parsed.get("notes") or "").strip(),
        "exercises": final_sequence,
        "visibility": "org" if current.org_id else "private",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(lesson_doc, current)
    await db.lesson_templates.insert_one(lesson_doc)
    lesson_doc.pop("_id", None)

    return {"lesson": lesson_doc, "new_exercises_created": new_exercise_count}


# ============ VETERINARIO: REPORT VISITA ============
async def _ensure_vet_patients_list(current: User):
    """Idempotent: creates the shared 'Pazienti' list (marked vet_patients=True so it
    can be found reliably even if renamed) the first time a user sets their vertical
    to veterinario. No-op if one already exists for them/their team."""
    existing = await db.collections.find_one({**_visible_query(current), "vet_patients": True}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": f"coll_{uuid.uuid4().hex[:12]}",
        "name": vet_reports.PATIENT_LIST_NAME,
        "icon": None,
        "fields": vet_reports.PATIENT_FIELDS,
        "sub_item_fields": [],
        "vet_patients": True,
        "visibility": "org" if current.org_id else "private",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.collections.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _find_vet_patients(current: User) -> tuple[Optional[dict], list]:
    coll = await db.collections.find_one({**_visible_query(current), "vet_patients": True}, {"_id": 0})
    if not coll:
        return None, []
    patients = await db.collection_items.find({"collection_id": coll["id"]}, {"_id": 0}).to_list(1000)
    return coll, patients


@api_router.get("/vet/templates")
async def list_vet_templates(current: User = Depends(get_current_user)):
    cursor = db.vet_templates.find(_visible_query(current), {"_id": 0}).sort("created_at", -1)
    custom = await cursor.to_list(200)
    builtin = [{"key": k, "name": v["name"]} for k, v in vet_reports.BUILTIN_TEMPLATES.items()]
    return {"builtin": builtin, "custom": custom}


@api_router.post("/vet/templates")
async def upload_vet_template(file: UploadFile = File(...), name: str = Form(...), current: User = Depends(get_current_user)):
    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        sections = vet_reports.extract_template_structure(tmp_path)
    except Exception as e:
        logger.exception("vet template parse failed")
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il template: {e}")
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass

    doc = {
        "id": f"vtpl_{uuid.uuid4().hex[:12]}",
        "name": name.strip() or (file.filename or "Template"),
        "sections": sections,
        "source_filename": file.filename,
        "visibility": "org" if current.org_id else "private",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.vet_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.delete("/vet/templates/{template_id}")
async def delete_vet_template(template_id: str, current: User = Depends(get_current_user)):
    r = await db.vet_templates.delete_one({"id": template_id, **_editable_query(current)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template non trovato")
    return {"ok": True}


@api_router.post("/vet/generate-report")
async def generate_vet_report(payload: GenerateVetReportPayload, current: User = Depends(get_current_user)):
    return await _generate_vet_report(current, payload.text, payload.visit_type, payload.patient_item_id)


async def _generate_vet_report(current: User, text: str, visit_type: str, patient_item_id: Optional[str] = None, channel: str = "web") -> dict:
    """Shared by the web endpoint and the Telegram /report flow (telegram_bot.py calls
    this directly - same process, no HTTP round-trip).

    Patient recognition is deterministic (whole-word name match against the Pazienti
    list), not left to the LLM: if the dictation names a patient but more than one
    distinct patient shares that name, generation stops and returns
    {"status": "ambiguous_patient", "candidates": [...], "text":..., "visit_type":...}
    so the caller can ask the user to pick one and re-call with patient_item_id set."""
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Descrivi la visita")

    if visit_type in vet_reports.BUILTIN_TEMPLATES:
        template_name = vet_reports.BUILTIN_TEMPLATES[visit_type]["name"]
        sections_skeleton = vet_reports.BUILTIN_TEMPLATES[visit_type]["sections"]
    else:
        tmpl = await db.vet_templates.find_one({"id": visit_type, **_visible_query(current)}, {"_id": 0})
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template non trovato")
        template_name = tmpl["name"]
        sections_skeleton = tmpl["sections"]

    _, patients = await _find_vet_patients(current)

    patient = None
    if patient_item_id:
        patient = next((p for p in patients if p["id"] == patient_item_id), None)
        if not patient:
            raise HTTPException(status_code=404, detail="Paziente non trovato")
    else:
        matches = vet_reports.find_matching_patients(text, patients)
        if len(matches) > 1:
            candidates = [
                {
                    "item_id": p["id"],
                    "name": p.get("data", {}).get("nome"),
                    "owner": p.get("data", {}).get("proprietario"),
                    "species": p.get("data", {}).get("tipo_animale"),
                }
                for p in matches
            ]
            return {"status": "ambiguous_patient", "candidates": candidates, "text": text, "visit_type": visit_type}
        if len(matches) == 1:
            patient = matches[0]

    sections_skeleton = vet_reports.filter_sections_for_patient(sections_skeleton, patient)

    try:
        interpreted = await vet_reports.interpret_visit(text, sections_skeleton, user_id=current.user_id, channel=channel)
    except Exception as e:
        logger.exception("vet report interpretation failed")
        raise HTTPException(status_code=500, detail=f"Generazione fallita: {e}")

    vet_reports.apply_patient_data(interpreted["sections"], patient)

    patient_name = (patient.get("data", {}).get("nome") if patient else None) or None
    docx_title = f"Referto - {template_name}"
    docx_bytes = vet_reports.build_docx(docx_title, patient_name, interpreted["sections"])
    fname = f"{docx_title} - {patient_name or 'generico'} - {datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.docx"

    drive_link = None
    drive_folder_name = None
    try:
        creds = await gi.get_credentials(db, current.user_id)
        if creds:
            folder_name = patient_name if patient_name else "Report generici"
            folder_id = await gi.find_or_create_subfolder(db, current.user_id, creds, folder_name)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(docx_bytes)
                tmp_path = tmp.name
            try:
                result = gi.upload_file_to_folder(
                    creds, folder_id, tmp_path, fname,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                drive_link = result.get("web_view_link")
                drive_folder_name = folder_name
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass
    except Exception:
        logger.exception("vet report drive save failed")

    if patient:
        await db.collection_items.update_one(
            {"id": patient["id"]},
            {"$set": {"data.data_ultima_visita": datetime.now(timezone.utc).date().isoformat()}},
        )

    telegram_sent = False
    if current.telegram_chat_id:
        try:
            from telegram import Bot
            import io as _io
            bot = Bot(token=tg.bot_token())
            await bot.send_document(
                chat_id=current.telegram_chat_id,
                document=_io.BytesIO(docx_bytes),
                filename=fname,
                caption=f"📄 {docx_title}" + (f" — {patient_name}" if patient_name else ""),
            )
            telegram_sent = True
        except Exception:
            logger.exception("vet report telegram send failed")

    import base64 as _b64
    report_doc = {
        "id": f"vrep_{uuid.uuid4().hex[:12]}",
        "status": "ok",
        "user_id": current.user_id,
        "org_id": current.org_id,
        "patient_item_id": patient["id"] if patient else None,
        "patient_name": patient_name,
        "template_name": template_name,
        "visit_type": visit_type,
        "transcript": text,
        "docx_b64": _b64.b64encode(docx_bytes).decode("ascii"),
        "docx_filename": fname,
        "drive_link": drive_link,
        "drive_folder": drive_folder_name,
        "telegram_sent": telegram_sent,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.vet_reports.insert_one(report_doc)
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="creazione_report", channel=channel, trigger="utente", org_id=current.org_id)
    report_doc.pop("_id", None)
    report_doc.pop("docx_b64", None)
    return report_doc


@api_router.get("/vet/reports")
async def list_vet_reports(current: User = Depends(get_current_user)):
    cursor = db.vet_reports.find({"user_id": current.user_id}, {"_id": 0, "docx_b64": 0}).sort("created_at", -1)
    return await cursor.to_list(200)


@api_router.get("/vet/reports/{report_id}/download")
async def download_vet_report(report_id: str, current: User = Depends(get_current_user)):
    doc = await db.vet_reports.find_one({"id": report_id, "user_id": current.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Report non trovato")
    import base64 as _b64
    data = _b64.b64decode(doc["docx_b64"])
    filename = doc.get("docx_filename") or "referto.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============ JOURNAL ============
class JournalCreate(BaseModel):
    content: str
    date: Optional[str] = None  # YYYY-MM-DD, defaults today


@api_router.get("/journal")
async def list_journal(
    current: User = Depends(get_current_user), q: Optional[str] = None, mood: Optional[str] = None,
    favorite: Optional[bool] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
):
    import re as _re
    query: dict = {"user_id": current.user_id}
    if mood and mood != "all":
        query["mood"] = mood
    if favorite is True:
        query["favorite"] = True
    if date_from or date_to:
        date_q = {}
        if date_from: date_q["$gte"] = date_from
        if date_to: date_q["$lte"] = date_to
        query["date"] = date_q
    if q:
        safe = _re.escape(q.strip())
        query["$or"] = [
            {"cleaned_text": {"$regex": safe, "$options": "i"}},
            {"raw_text": {"$regex": safe, "$options": "i"}},
            {"title": {"$regex": safe, "$options": "i"}},
            {"highlights": {"$regex": safe, "$options": "i"}},
            {"tags": {"$regex": safe, "$options": "i"}},
        ]
    limit = 2000 if (date_from or date_to) else 365
    cursor = db.journal_entries.find(query, {"_id": 0}).sort("date", -1).limit(limit)
    return await cursor.to_list(limit)


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
        "Il tuo compito è SOLO editoriale: (1) sistemare il testo (grammatica, punteggiatura, chiarezza) mantenendo "
        "la voce personale in prima persona, (2) organizzare in paragrafi coerenti. "
        "REGOLA CRITICA: non aggiungere MAI fatti, dettagli, emozioni o commenti sullo stato d'animo non esplicitamente "
        "scritti dall'utente (es. non scrivere 'sono molto felice' o 'è stata una giornata dura' se l'utente non lo ha "
        "detto lui stesso) - riscrivi solo ciò che c'è, non interpretarlo né arricchirlo. "
        "Restituisci una risposta con due parti: prima il diario riscritto in modo naturale (senza intestazioni tipo 'Diario:'), "
        "poi in coda solo per il sistema: "
        "<<<META>>>{\"title\": \"titolo breve della giornata (max 6 parole)\", \"mood\": \"parola singola dedotta dal testo, SOLO per uso interno "
        "(non va scritta nel diario): felice|neutro|stressato|riflessivo|energico|stanco|grato\", "
        "\"tags\": [\"1-3 parole chiave che riassumono gli argomenti della giornata, es. lavoro, famiglia, sport, salute\"], "
        "\"highlights\": [\"1-3 momenti chiave estratti letteralmente dal testo\"]}<<<END>>>"
    )
    # The journal must never be left unsaved because of a transient AI hiccup - if the
    # cleanup call fails for any reason, fall back to storing the raw text as-is rather
    # than losing the entry (this is the one journal entry-point without that safety net;
    # the chat-based "journal" action already degrades gracefully via its own error path).
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"journal_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=current.user_id, feature="diario", channel="web", trigger="utente", org_id=current.org_id,
        ).with_model("openai", "gpt-4o")
        raw = await chat.send_message(UserMessage(text=payload.content))
        cleaned, meta = _extract_meta(raw)
        cleaned = (cleaned.replace("```json", "").replace("```", "").strip()) or payload.content
    except Exception:
        logger.exception("journal cleanup failed, saving raw text")
        cleaned, meta = payload.content, None
    doc = {
        "id": f"jr_{uuid.uuid4().hex[:12]}",
        "user_id": current.user_id,
        "date": entry_date,
        "raw_text": payload.content,
        "cleaned_text": cleaned,
        "title": (meta or {}).get("title", ""),
        "mood": (meta or {}).get("mood", ""),
        "tags": (meta or {}).get("tags", []),
        "highlights": (meta or {}).get("highlights", []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.journal_entries.insert_one(doc)
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="diario", channel="web", trigger="utente", org_id=current.org_id)
    doc.pop("_id", None)
    return doc


@api_router.delete("/journal/{entry_id}")
async def delete_journal(entry_id: str, current: User = Depends(get_current_user)):
    res = await db.journal_entries.delete_one({"id": entry_id, "user_id": current.user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@api_router.delete("/journal/{entry_id}/images/{index}")
async def delete_journal_image(entry_id: str, index: int, current: User = Depends(get_current_user)):
    entry = await db.journal_entries.find_one({"id": entry_id, "user_id": current.user_id}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Voce di diario non trovata")
    images = list(entry.get("images") or [])
    if index < 0 or index >= len(images):
        raise HTTPException(status_code=404, detail="Immagine non trovata")
    images.pop(index)
    await db.journal_entries.update_one({"id": entry_id, "user_id": current.user_id}, {"$set": {"images": images}})
    return {"images": images}


# ============ CONTEXTUAL CHAT (per task/todo) ============
class ContextChatRequest(BaseModel):
    message: str


@api_router.post("/tasks/{task_id}/chat")
async def task_chat(task_id: str, payload: ContextChatRequest, current: User = Depends(get_current_user)):
    import re as _re_taskchat
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    system = (
        f"Sei mAIPAL. Oggi è {_today_it_string()}. Usa SEMPRE questa data come riferimento per calcolare "
        "qualunque data relativa menzionata dall'utente (es. 'domani', '20 settembre', 'lunedì prossimo'). "
        f"L'utente sta modificando il task: {task}. "
        "Rispondi in modo naturale (1-2 frasi) con la conferma della modifica. "
        "In coda includi SOLO per il sistema i campi da aggiornare tra i marcatori "
        "<<<META>>>{...}<<<END>>>, chiavi ammesse: title, description, due_date (formato ESATTO YYYY-MM-DD), "
        "due_time (formato ESATTO HH:MM, oppure null), priority ('alta'|'media'|'bassa'), tags, notes. "
        "Includi in META SOLO le chiavi che l'utente ha chiesto esplicitamente di cambiare - non toccare le altre."
    )
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY, session_id=f"task_{task_id}", system_message=system,
        user_id=current.user_id, feature="creazione_task", channel="web", trigger="utente", org_id=current.org_id,
    ).with_model("openai", "gpt-4o")
    raw = await chat.send_message(UserMessage(text=payload.message))
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="creazione_task", channel="web", trigger="utente", org_id=current.org_id)
    visible, meta = _extract_meta(raw)
    visible = visible.replace("```json", "").replace("```", "").strip()
    if meta:
        if "due_date" in meta and (not meta["due_date"] or not _re_taskchat.match(r"^\d{4}-\d{2}-\d{2}$", str(meta["due_date"]))):
            meta.pop("due_date")
        if "due_time" in meta and meta["due_time"] and not _re_taskchat.match(r"^\d{2}:\d{2}$", str(meta["due_time"])):
            meta.pop("due_time")
    q = {"id": task_id, **_editable_query(current)}
    if meta:
        _clear_cached_embedding(meta, {"title", "description", "notes"})
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
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY, session_id=f"todo_{todo_id}", system_message=system,
        user_id=current.user_id, feature="creazione_todo", channel="web", trigger="utente", org_id=current.org_id,
    ).with_model("openai", "gpt-4o")
    raw = await chat.send_message(UserMessage(text=payload.message))
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="creazione_todo", channel="web", trigger="utente", org_id=current.org_id)
    visible, meta = _extract_meta(raw)
    visible = visible.replace("```json", "").replace("```", "").strip()
    if meta:
        _clear_cached_embedding(meta, {"title", "description", "notes"})
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


_DRIVE_FOLDER_HINT_RE = None


def _regex_drive_folder_hint(text: str) -> Optional[str]:
    """Deterministic fallback used when the LLM-based folder-hint resolution fails
    outright (e.g. a transient error calling the model) - catches the common literal
    phrasing '...nella cartella NomeCartella...' without depending on any external call."""
    global _DRIVE_FOLDER_HINT_RE
    if _DRIVE_FOLDER_HINT_RE is None:
        import re as _re
        _DRIVE_FOLDER_HINT_RE = _re.compile(
            r"cartella\s+(?:chiamata\s+|denominata\s+|di\s+nome\s+)?[\"'«]?"
            r"([A-Za-zÀ-ÖØ-öø-ÿ0-9_\-]+(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ0-9_\-]+){0,3})[\"'»]?",
            _re.IGNORECASE,
        )
    m = _DRIVE_FOLDER_HINT_RE.search(text or "")
    if not m:
        return None
    name = m.group(1).strip().rstrip(".,;:!?")
    return name or None


async def _resolve_drive_folder_hint(text: str, existing_folders: List[str], user_id: Optional[str] = None, channel: str = "web") -> Optional[str]:
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
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"drivehint_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=user_id, feature="caricamento_informazioni", channel=channel, trigger="utente",
        ).with_model("openai", "gpt-4o-mini")  # single-word folder-name extraction
        raw = (await chat.send_message(UserMessage(text=text))).strip().strip('"').strip()
        if not raw or raw.upper() == "NESSUNA":
            return None
        return raw
    except Exception:
        # A failed LLM call (auth/config/network) must NOT be treated the same as "no
        # folder mentioned" - fall back to a deterministic regex match on the common
        # Italian phrasing so an explicit "salvalo nella cartella X" still works.
        logger.exception("drive folder hint resolution via LLM failed, trying regex fallback")
        return _regex_drive_folder_hint(text)


async def _drive_smart_upload_core(current: User, contents: bytes, filename: str, content_type: str, text: str, silent: bool = False, channel: str = "web") -> dict:
    """Shared by the web endpoint and the Telegram bot (same process, no HTTP round-trip).
    Uploads a file into the mAIPAL Drive tree, picking the subfolder from the user's
    message when possible. If no folder can be determined, stashes the file and returns
    suggestions so the conversation can ask the user (see _drive_resolve_pending_core) -
    UNLESS `silent` is set, in which case it just reports {"status": "skipped"} instead:
    used when a file was primarily attached for the knowledge base and the caller wants
    to *also* save it to Drive automatically only if the message clearly names a folder,
    without ever prompting the user for one."""
    creds = await gi.get_credentials(db, current.user_id)
    if not creds:
        if silent:
            return {"status": "skipped"}
        raise HTTPException(status_code=400, detail="Google Workspace non collegato. Vai in Impostazioni per collegarlo.")

    subfolders = await gi.list_subfolders(db, current.user_id, creds)
    folder_name = await _resolve_drive_folder_hint(text, [f["name"] for f in subfolders], user_id=current.user_id, channel=channel)

    if folder_name:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{filename.rsplit('.',1)[-1] if '.' in (filename or '') else 'bin'}") as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        try:
            folder_id = await gi.find_or_create_subfolder(db, current.user_id, creds, folder_name)
            result = gi.upload_file_to_folder(creds, folder_id, tmp_path, filename, content_type)
            ut.fire_and_forget_feature_event(user_id=current.user_id, feature="caricamento_informazioni", channel=channel, trigger="utente", org_id=current.org_id)
            return {"status": "saved", "folder": folder_name, **result}
        finally:
            try: os.unlink(tmp_path)
            except Exception: pass

    if silent:
        return {"status": "skipped"}

    import base64 as _b64
    pending_id = f"pdu_{uuid.uuid4().hex[:12]}"
    await db.pending_drive_uploads.insert_one({
        "pending_id": pending_id,
        "user_id": current.user_id,
        "filename": filename,
        "content_type": content_type,
        "data_b64": _b64.b64encode(contents).decode("ascii"),
        "created_at": datetime.now(timezone.utc),
    })
    return {"status": "needs_folder", "pending_id": pending_id, "suggestions": [f["name"] for f in subfolders]}


@api_router.post("/drive/smart-upload")
async def drive_smart_upload(file: UploadFile = File(...), text: str = Form(""), silent: bool = Form(False), current: User = Depends(get_current_user)):
    contents = await file.read()
    return await _drive_smart_upload_core(current, contents, file.filename, file.content_type, text, silent=silent)


async def _drive_resolve_pending_core(current: User, pending_id: str, text: str, channel: str = "web") -> dict:
    """Shared by the web endpoint and the Telegram bot. Second turn of the smart-upload
    flow: the user's follow-up message may now name the folder. Resolves it and finally
    uploads the stashed file."""
    doc = await db.pending_drive_uploads.find_one({"pending_id": pending_id, "user_id": current.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Nessun upload in attesa trovato")

    creds = await gi.get_credentials(db, current.user_id)
    if not creds:
        raise HTTPException(status_code=400, detail="Google Workspace non collegato. Vai in Impostazioni per collegarlo.")

    subfolders = await gi.list_subfolders(db, current.user_id, creds)
    folder_name = await _resolve_drive_folder_hint(text, [f["name"] for f in subfolders], user_id=current.user_id, channel=channel)
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
        ut.fire_and_forget_feature_event(user_id=current.user_id, feature="caricamento_informazioni", channel=channel, trigger="utente", org_id=current.org_id)
        return {"status": "saved", "folder": folder_name, **result}
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass


@api_router.post("/drive/resolve-pending")
async def drive_resolve_pending(payload: dict, current: User = Depends(get_current_user)):
    return await _drive_resolve_pending_core(current, payload.get("pending_id"), payload.get("text", ""))


# ============ KB DIRECT UPLOAD (no Google) ============
IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "heic", "heif")


async def _ocr_image_bytes(contents: bytes, filename: str, user_id: Optional[str] = None, channel: str = "web") -> str:
    """Run OCR on an image using the model's vision capability."""
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
        user_id=user_id, feature="caricamento_informazioni", channel=channel, trigger="utente",
    ).with_model("openai", "gpt-4o-mini")  # OCR transcription, not reasoning
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


async def _classify_document(text: str, user_id: Optional[str] = None, channel: str = "web") -> dict:
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
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"cls_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=user_id, feature="caricamento_informazioni", channel=channel, trigger="utente",
        ).with_model("openai", "gpt-4o-mini")  # simple category+keywords classification
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
                text = await _ocr_image_bytes(send_bytes, file.filename, user_id=current.user_id, channel="web")
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
        classification = await _classify_document(text, user_id=current.user_id, channel="web")

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

        ut.fire_and_forget_feature_event(user_id=current.user_id, feature="caricamento_informazioni", channel="web", trigger="utente", org_id=current.org_id)
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
async def voice_transcribe(file: UploadFile = File(...), action: str = Form(""), current: User = Depends(get_current_user)):
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
        # `action` is the caller's active tab/action hint (frontend already knows it) -
        # voice transcription has no feature of its own at call time, so it's attributed
        # to whichever chat feature triggered it, same mapping as chat_stream's.
        stt = OpenAISpeechToText(
            api_key=EMERGENT_LLM_KEY, user_id=current.user_id,
            feature=_ACTION_TO_FEATURE.get(action, "altro"), channel="web", trigger="utente", org_id=current.org_id,
        )
        with open(tmp_path, "rb") as f:
            result = await stt.transcribe(file=f, model="whisper-1", response_format="verbose_json", language="it")
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
    today = datetime.now(timezone.utc).astimezone(LOCAL_TZ).date().isoformat()
    try:
        await _run_daily_news_for_user(user, today)
    except Exception as e:
        logger.exception("manual news refresh failed")
        raise HTTPException(status_code=500, detail=f"Ricerca notizie fallita: {e}")
    items = await db.news_items.find({"user_id": current.user_id, "date": today}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return items


@api_router.post("/news/{item_id}/feedback")
async def set_news_feedback(item_id: str, payload: NewsFeedbackPayload, current: User = Depends(get_current_user)):
    existing = await db.news_items.find_one({"id": item_id, "user_id": current.user_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="News non trovata")
    await db.news_items.update_one({"id": item_id, "user_id": current.user_id}, {"$set": {"feedback": payload.value}})
    return {"id": item_id, "feedback": payload.value}


@api_router.delete("/news/{item_id}")
async def delete_news(item_id: str, current: User = Depends(get_current_user)):
    res = await db.news_items.delete_one({"id": item_id, "user_id": current.user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="News non trovata")
    return {"ok": True}


@api_router.post("/news/{item_id}/save-to-kb")
async def save_news_to_kb(item_id: str, current: User = Depends(get_current_user)):
    item = await db.news_items.find_one({"id": item_id, "user_id": current.user_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="News non trovata")
    if item.get("kb_doc_id"):
        return {"doc_id": item["kb_doc_id"], "already_saved": True}

    content = f"{item['title']}\n\n{item.get('summary','')}\n\nFonte: {item.get('source','')} — {item['url']}"
    try:
        e = await emb.embed_texts([content])
        embedding = e[0] if e else None
    except Exception:
        embedding = None

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    await db.kb_chunks.insert_one({
        "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
        "user_id": current.user_id,
        "text": content,
        "title": item["title"],
        "tags": ["news"],
        "summary": item.get("summary", ""),
        "embedding": embedding,
        "doc_id": doc_id,
        "source_type": "news",
        "chunk_index": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.kb_documents.insert_one({
        "doc_id": doc_id,
        "user_id": current.user_id,
        "name": item["title"],
        "ext": "news",
        "source_type": "news",
        "category": "note",
        "keywords": ["news", item.get("source", "")] if item.get("source") else ["news"],
        "chunks_count": 1,
        "chars": len(content),
        "size_bytes": len(content.encode("utf-8")),
        "preview": (item.get("summary") or item["title"])[:280],
        "drive_link": item["url"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.news_items.update_one({"id": item_id, "user_id": current.user_id}, {"$set": {"kb_doc_id": doc_id}})
    return {"doc_id": doc_id, "already_saved": False}


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
    try:
        asyncio.create_task(_usage_aggregation_loop())
    except Exception:
        logger.exception("failed to start usage aggregation loop")


def _snooze_keyboard(task_id: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔁 +15 min", callback_data=f"snooze:{task_id}:15"),
        InlineKeyboardButton("🔁 +1h", callback_data=f"snooze:{task_id}:60"),
        InlineKeyboardButton("🔁 Domani", callback_data=f"snooze:{task_id}:1440"),
    ]])


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
                    notes_line = f"\n📝 {t['notes']}" if t.get("notes") else ""
                    text = (
                        f"⏰ Promemoria mAIPAL\n\n"
                        f"Domani ({tomorrow}{time_part}) hai in scadenza:\n"
                        f"📌 *{t.get('title','(senza titolo)')}*\n"
                        f"{t.get('description','') or ''}"
                        f"{notes_line}\n\n"
                        f"Priorità: {t.get('priority','media')}"
                    )
                    await bot.send_message(chat_id=user["telegram_chat_id"], text=text, parse_mode="Markdown", reply_markup=_snooze_keyboard(t["id"]))
                    await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_sent": True, "reminder_sent_at": datetime.now(timezone.utc).isoformat()}})
                    logger.info(f"reminder sent for task {t['id']} to chat {user['telegram_chat_id']}")
                except Exception:
                    logger.exception("failed to send reminder")
        except Exception:
            logger.exception("reminders loop iteration failed")
        await asyncio.sleep(30 * 60)


async def _kb_reminder_enrichment(user_id: str, task: dict, org_id: Optional[str] = None) -> str:
    """Looks up the user's own Knowledge Base for information useful to carry out a task,
    and returns a short bullet-point block to append to its Telegram reminder - or "" when
    nothing relevant/confident enough was found (the reminder is then sent exactly as
    before, with no mention of the search ever having happened). Never raises - any
    failure here must never affect whether or when the reminder itself gets sent."""
    title = (task.get("title") or "").strip()
    notes = (task.get("notes") or "").strip()
    query = f"{title} {notes}".strip()
    if not query:
        return ""
    try:
        kb_hits = await retrieve_kb(user_id, query, limit=8, scope="all", org_id=org_id)
    except Exception:
        logger.exception("KB lookup for reminder enrichment failed")
        return ""
    if not kb_hits:
        return ""
    def _fmt(c):
        return c.get("display") or (c.get("text") or "")[:500]
    context = "\n\n".join(f"- {_fmt(c)}" for c in kb_hits)[:6000]
    system = (
        "Stai per generare la sezione 'Informazioni utili' di un promemoria Telegram per un task. "
        f"Task: \"{title}\". Note: \"{notes or 'nessuna'}\".\n\n"
        f"CONTESTO dalla knowledge base personale dell'utente (può contenere informazioni non pertinenti):\n{context}\n\n"
        "Analizza il task (titolo e note) per capire di chi/cosa si parla e che tipo di azione va svolta "
        "(chiamare, chiedere aggiornamenti, fare un follow-up, inviare un documento...), poi valuta se il "
        "CONTESTO sopra contiene informazioni davvero utili per svolgere QUESTA azione specifica.\n\n"
        "Regole tassative:\n"
        "- Usa SOLO informazioni presenti nel contesto sopra. Non inventare né dedurre dati non scritti "
        "esplicitamente (dati clinici, economici o personali non presenti).\n"
        "- Se il riferimento del task è ambiguo (es. il contesto riguarda più persone/cose con lo stesso nome) e "
        "le note del task non permettono di capire con sicurezza a chi/cosa si riferisce, non produrre nulla.\n"
        "- Se il contesto non contiene nulla di realmente utile per questo task specifico (es. task generico come "
        "'fare la spesa', o nessuna informazione pertinente), non produrre nulla.\n"
        "- Se produci qualcosa: 3-5 punti elenco sintetici (un fatto essenziale ciascuno), con la data quando "
        "disponibile nel contesto (es. 'Ultima visita: 15 settembre — ...'). Stesso tono asciutto e diretto di un "
        "promemoria, in italiano.\n\n"
        "Rispondi SOLO con i punti elenco (ogni riga inizia con '• '), oppure con la sola parola NESSUNA se non "
        "c'è nulla di utile o il riferimento è ambiguo. Nessun altro testo, nessuna spiegazione."
    )
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"remind_ctx_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=user_id, feature="creazione_task", channel="telegram", trigger="automatico", org_id=org_id,
        ).with_model("openai", "gpt-4o-mini")
        raw = (await asyncio.wait_for(chat.send_message(UserMessage(text="Genera la sezione, se applicabile.")), timeout=8)).strip()
    except Exception:
        logger.exception("reminder enrichment LLM call failed")
        return ""
    if not raw or raw.strip().upper().startswith("NESSUNA"):
        return ""
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    lines = [(l if l.startswith("•") else f"• {l}") for l in lines][:5]
    return "\n".join(lines)


async def _exact_reminders_loop():
    """Every minute: for tasks with reminder_enabled=True and reminder_msg_sent!=True,
    fire a Telegram message at (due_date + due_time - reminder_offset_minutes); offset
    defaults to 15 minutes when the user hasn't specified one. due_date/due_time are the
    wall-clock values the user typed, in Europe/Rome local time - converted to UTC here
    before comparing to now(), otherwise the reminder fires 1-2h later than intended."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            now_local = now.astimezone(LOCAL_TZ)
            today_iso = now_local.date().isoformat()
            tomorrow_iso = (now_local.date() + timedelta(days=1)).isoformat()
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
                    due_dt_local = datetime.strptime(f"{t.get('due_date')} {due_time}", "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
                except ValueError:
                    continue
                due_dt = due_dt_local.astimezone(timezone.utc)
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
                    notes_line = f"\n📝 {t['notes']}" if t.get("notes") else ""
                    text = (
                        f"🔔 Promemoria mAIPAL\n\n"
                        f"Tra {minutes_left} minuti ({due_time}) hai in programma:\n"
                        f"📌 *{t.get('title','(senza titolo)')}*\n"
                        f"{t.get('description','') or ''}"
                        f"{notes_line}"
                    )
                    # Best-effort: look up the user's own KB for info useful to carry out this
                    # task (e.g. a patient's last visit, a contact's last conversation) and
                    # append it. Never delays/blocks the reminder itself (bounded timeout,
                    # falls back to the plain text above on any failure or empty result) and
                    # never mentions the search when it finds nothing.
                    try:
                        enrichment = await asyncio.wait_for(
                            _kb_reminder_enrichment(t["user_id"], t, org_id=t.get("org_id")), timeout=12
                        )
                    except Exception:
                        enrichment = ""
                    if enrichment:
                        # Stay well under Telegram's 4096-char cap - if the enrichment doesn't
                        # fully fit, drop whole bullet lines from the end rather than cutting
                        # into title/scadenza/note, per spec.
                        header = "\n\n💡 Informazioni utili\n"
                        budget = 4000 - len(text) - len(header)
                        kept, used = [], 0
                        for line in enrichment.split("\n"):
                            if used + len(line) + 1 > budget:
                                break
                            kept.append(line)
                            used += len(line) + 1
                        if kept:
                            text = f"{text}{header}" + "\n".join(kept)
                    await bot.send_message(chat_id=user["telegram_chat_id"], text=text, parse_mode="Markdown", reply_markup=_snooze_keyboard(t["id"]))
                    await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_msg_sent": True, "reminder_msg_sent_at": datetime.now(timezone.utc).isoformat()}})
                    logger.info(f"exact reminder sent for task {t['id']} to chat {user['telegram_chat_id']}")
                except Exception:
                    logger.exception("failed to send exact reminder")
        except Exception:
            logger.exception("exact reminders loop iteration failed")
        await asyncio.sleep(60)


PRIORITY_ORDER = {"alta": 0, "media": 1, "bassa": 2, None: 3}
PRIORITY_EMOJI = {"alta": "🔴", "media": "🟠", "bassa": "⚪️", None: "⚪️"}


async def _open_todos_for(user_id: str) -> list[dict]:
    todos = await db.todos.find(
        {"user_id": user_id, "status": {"$in": ["da_fare", "in_corso"]}}, {"_id": 0}
    ).to_list(200)
    todos.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority"), 3))
    return todos


def _todo_lines(open_todos: list[dict]) -> list[str]:
    lines = [f"✅ *To-Do aperti* ({len(open_todos)})"]
    for t in open_todos[:10]:
        e = PRIORITY_EMOJI.get(t.get("priority"), "⚪️")
        pct = f" · {t.get('completion_percent', 0)}%" if t.get("status") == "in_corso" else ""
        lines.append(f"{e} {t.get('title', '(senza titolo)')}{pct}")
    return lines


async def _send_telegram(chat_id: str, lines: list[str], log_label: str):
    try:
        from telegram import Bot
        await Bot(token=tg.bot_token()).send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")
        logger.info(f"{log_label} sent to {chat_id}")
    except Exception:
        logger.exception(f"{log_label} send failed")


async def _send_daily_morning_recap(user: dict, today: str):
    """Today's due tasks (incl. overdue) + open to-dos."""
    tasks_today = await db.tasks.find(
        {"user_id": user["user_id"], "due_date": {"$lte": today}, "$or": [{"completed": {"$exists": False}}, {"completed": False}]},
        {"_id": 0},
    ).to_list(200)
    tasks_today.sort(key=lambda t: (PRIORITY_ORDER.get(t.get("priority"), 3), t.get("due_date", "")))
    open_todos = await _open_todos_for(user["user_id"])
    if not tasks_today and not open_todos:
        return
    lines = [f"☀️ *Buongiorno {user.get('name', '').split(' ')[0]}!* Riassunto di oggi:", ""]
    if tasks_today:
        lines.append(f"📌 *Task* ({len(tasks_today)})")
        for t in tasks_today[:10]:
            e = PRIORITY_EMOJI.get(t.get("priority"), "⚪️")
            when = t.get("due_date", "")
            if t.get("due_time"): when += f" · {t['due_time']}"
            lines.append(f"{e} {t.get('title', '(senza titolo)')} — _{when}_")
        lines.append("")
    if open_todos:
        lines.extend(_todo_lines(open_todos))
        lines.append("")
    lines.append("Buon lavoro! 🚀")
    await _send_telegram(user["telegram_chat_id"], lines, "daily morning recap")


async def _send_week_ahead_recap(user: dict, week_start: str, week_end: str):
    """Monday morning: everything due this week (Mon-Sun), instead of the daily recap."""
    week_tasks = await db.tasks.find(
        {
            "user_id": user["user_id"],
            "due_date": {"$gte": week_start, "$lte": week_end},
            "$or": [{"completed": {"$exists": False}}, {"completed": False}],
        },
        {"_id": 0},
    ).to_list(200)
    week_tasks.sort(key=lambda t: (t.get("due_date", ""), PRIORITY_ORDER.get(t.get("priority"), 3)))
    open_todos = await _open_todos_for(user["user_id"])
    if not week_tasks and not open_todos:
        return
    lines = [f"📅 *La tua settimana, {user.get('name', '').split(' ')[0]}!*", ""]
    if week_tasks:
        lines.append(f"📌 *Task in programma* ({len(week_tasks)})")
        for t in week_tasks[:15]:
            e = PRIORITY_EMOJI.get(t.get("priority"), "⚪️")
            when = t.get("due_date", "")
            if t.get("due_time"): when += f" · {t['due_time']}"
            lines.append(f"{e} {t.get('title', '(senza titolo)')} — _{when}_")
        lines.append("")
    if open_todos:
        lines.extend(_todo_lines(open_todos))
        lines.append("")
    lines.append("Buona settimana! 🌟")
    await _send_telegram(user["telegram_chat_id"], lines, "week-ahead recap")


async def _send_daily_evening_recap(user: dict, today: str, today_start_utc_iso: str):
    """Evening look-back: tasks completed today + tasks that were due today but not done."""
    completed_today = await db.tasks.find(
        {"user_id": user["user_id"], "completed": True, "completed_at": {"$gte": today_start_utc_iso}},
        {"_id": 0},
    ).to_list(200)
    missed_today = await db.tasks.find(
        {"user_id": user["user_id"], "due_date": today, "$or": [{"completed": {"$exists": False}}, {"completed": False}]},
        {"_id": 0},
    ).to_list(200)
    missed_today.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority"), 3))
    if not completed_today and not missed_today:
        return
    lines = [f"🌙 *Riepilogo serale — {user.get('name', '').split(' ')[0]}*", ""]
    lines.append(f"✅ *Completati oggi* ({len(completed_today)})")
    for t in completed_today[:10]:
        lines.append(f"  ✓ {t.get('title', '(senza titolo)')}")
    if not completed_today:
        lines.append("  _nessuno_")
    if missed_today:
        lines.append("")
        lines.append(f"⏳ *Rimasti aperti* ({len(missed_today)})")
        for t in missed_today[:10]:
            e = PRIORITY_EMOJI.get(t.get("priority"), "⚪️")
            lines.append(f"  {e} {t.get('title', '(senza titolo)')}")
    lines.append("")
    lines.append("A domani! 👋")
    await _send_telegram(user["telegram_chat_id"], lines, "daily evening recap")


async def _send_week_concluded_recap(user: dict, week_start_utc_iso: str):
    """Friday evening: what got done this week + what's still open."""
    done = await db.tasks.find(
        {"user_id": user["user_id"], "completed": True, "completed_at": {"$gte": week_start_utc_iso}},
        {"_id": 0},
    ).to_list(200)
    open_tasks = await db.tasks.find(
        {"user_id": user["user_id"], "$or": [{"completed": {"$exists": False}}, {"completed": False}]},
        {"_id": 0},
    ).to_list(200)
    open_tasks.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority"), 3))
    open_todos = await _open_todos_for(user["user_id"])
    lines = [f"📅 *Settimana conclusa — {user.get('name', '').split(' ')[0]}*", ""]
    lines.append(f"✅ *Completati questa settimana* ({len(done)})")
    for t in done[:10]:
        lines.append(f"  ✓ {t.get('title', '(senza titolo)')}")
    if not done:
        lines.append("  _nessuno_")
    lines.append("")
    lines.append(f"📌 *Task ancora aperti* ({len(open_tasks)})")
    for t in open_tasks[:10]:
        e = PRIORITY_EMOJI.get(t.get("priority"), "⚪️")
        lines.append(f"  {e} {t.get('title', '(senza titolo)')} · {t.get('due_date', '')}")
    lines.append("")
    lines.extend(_todo_lines(open_todos))
    lines.append("")
    lines.append("Buon weekend! 🌟")
    await _send_telegram(user["telegram_chat_id"], lines, "week-concluded recap")


async def _daily_summary_loop():
    """Every 5 min, per user with a linked Telegram chat:
    - Every morning at their configured summary_time (default 07:00, editable in
      Impostazioni): the daily recap (today's tasks + open to-dos) - except on Monday,
      when it's replaced by a week-ahead recap (everything due Mon-Sun this week).
    - Every evening at a fixed 21:00 Europe/Rome: an evening look-back recap (completed
      today + still open) - except on Friday, when it's replaced by a week-concluded
      recap (completed this week + still open)."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            now_local = now.astimezone(LOCAL_TZ)
            local_date = now_local.date()
            today = local_date.isoformat()
            monday = local_date - timedelta(days=local_date.weekday())
            sunday = monday + timedelta(days=6)
            week_start_utc_iso = _time_str_to_today_utc("00:00", monday).isoformat()
            today_start_utc_iso = _time_str_to_today_utc("00:00", local_date).isoformat()
            evening_target_utc = _time_str_to_today_utc("21:00", local_date)

            async for user in db.users.find({"telegram_chat_id": {"$exists": True}}, {"_id": 0}):
                # ---- Morning slot: daily recap, or Monday's week-ahead recap ----
                if user.get("daily_summary_date") != today:
                    target_utc = _time_str_to_today_utc(user.get("summary_time") or "07:00", local_date)
                    if now >= target_utc:
                        try:
                            if local_date.weekday() == 0:
                                await _send_week_ahead_recap(user, today, sunday.isoformat())
                            else:
                                await _send_daily_morning_recap(user, today)
                            await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"daily_summary_date": today}})
                        except Exception:
                            logger.exception("morning recap failed")

                # ---- Evening slot: daily recap, or Friday's week-concluded recap ----
                if user.get("evening_summary_date") != today and now >= evening_target_utc:
                    try:
                        if local_date.weekday() == 4:
                            await _send_week_concluded_recap(user, week_start_utc_iso)
                        else:
                            await _send_daily_evening_recap(user, today, today_start_utc_iso)
                        await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"evening_summary_date": today}})
                    except Exception:
                        logger.exception("evening recap failed")
        except Exception:
            logger.exception("daily/weekly loop iteration failed")
        await asyncio.sleep(5 * 60)


async def _news_source_preferences(user_id: str) -> dict:
    """Learns which news sources the user tends to like/dislike from past feedback, so
    future searches can be steered toward (or away from) them."""
    scores = {}
    cursor = db.news_items.aggregate([
        {"$match": {"user_id": user_id, "source": {"$nin": [None, ""]}, "feedback": {"$in": ["like", "dislike"]}}},
        {"$group": {"_id": {"source": "$source", "feedback": "$feedback"}, "n": {"$sum": 1}}},
    ])
    async for row in cursor:
        src = row["_id"]["source"]
        delta = row["n"] if row["_id"]["feedback"] == "like" else -row["n"]
        scores[src] = scores.get(src, 0) + delta
    liked = sorted([s for s, v in scores.items() if v > 0], key=lambda s: -scores[s])[:8]
    disliked = sorted([s for s, v in scores.items() if v < 0], key=lambda s: scores[s])[:8]
    return {"liked_sources": liked, "disliked_sources": disliked}


async def _news_current_context(user_id: str) -> dict:
    """Open tasks due this calendar week (today included) and open to-dos, so the news
    search can also surface content relevant to what the user is actively dealing with
    (e.g. a task about a tax deadline -> news about that deadline)."""
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    tasks = await db.tasks.find(
        {
            "user_id": user_id,
            "due_date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
            "$or": [{"completed": {"$exists": False}}, {"completed": False}],
        },
        {"_id": 0, "title": 1, "due_date": 1, "tags": 1},
    ).to_list(50)
    todos = await db.todos.find(
        {"user_id": user_id, "status": {"$in": ["da_fare", "in_corso"]}},
        {"_id": 0, "title": 1, "tags": 1},
    ).to_list(50)
    today_iso = today.isoformat()
    return {
        "tasks": [
            {"title": t.get("title", ""), "when": "oggi" if t.get("due_date") == today_iso else "questa settimana"}
            for t in tasks if t.get("title")
        ],
        "todos": [t.get("title", "") for t in todos if t.get("title")],
    }


async def _run_daily_news_for_user(user: dict, today: str):
    """Generates today's news digest for one user, stores it, and pushes it via Telegram
    if the user has a linked chat. Marks news_date=today regardless of result so the
    background loop doesn't retry a user with zero relevant news every 20 minutes."""
    prefs = await _news_source_preferences(user["user_id"])
    context = await _news_current_context(user["user_id"])
    items = await news_service.generate_news_for_user(user, prefs, context)
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"news_date": today}})
    ut.fire_and_forget_feature_event(
        user_id=user["user_id"], feature="invio_news", channel="sistema", trigger="automatico", org_id=user.get("org_id"),
    )
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


async def _compute_usage_daily(target_date: str):
    """(Re)computes usage_daily rows for one Europe/Rome calendar day from llm_calls +
    feature_events, upserting so re-running the same day never duplicates rows. This is the
    dashboard's fast-path aggregate table (day+user+feature+channel+model), per the
    usage-tracking spec's performance requirement - the dashboard itself stays read-only and
    never computes this on its own."""
    day_start_local = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
    day_end_local = day_start_local + timedelta(days=1)
    day_start_iso = day_start_local.astimezone(timezone.utc).isoformat()
    day_end_iso = day_end_local.astimezone(timezone.utc).isoformat()

    call_rows = await db.llm_calls.aggregate([
        {"$match": {"created_at": {"$gte": day_start_iso, "$lt": day_end_iso}}},
        {"$group": {
            "_id": {"user_id": "$user_id", "feature": "$feature", "channel": "$channel", "model": "$model"},
            "calls": {"$sum": 1},
            "calls_error": {"$sum": {"$cond": [{"$eq": ["$status", "errore"]}, 1, 0]}},
            "calls_no_price": {"$sum": {"$cond": [{"$eq": ["$cost_usd", None]}, 1, 0]}},
            "input_tokens": {"$sum": "$input_tokens"},
            "cached_input_tokens": {"$sum": "$cached_input_tokens"},
            "output_tokens": {"$sum": "$output_tokens"},
            "total_tokens": {"$sum": "$total_tokens"},
            "cost_usd": {"$sum": {"$ifNull": ["$cost_usd", 0]}},
        }},
    ]).to_list(20000)

    event_rows = await db.feature_events.aggregate([
        {"$match": {"created_at": {"$gte": day_start_iso, "$lt": day_end_iso}}},
        {"$group": {
            "_id": {"user_id": "$user_id", "feature": "$feature", "channel": "$channel"},
            "feature_events": {"$sum": 1},
            "feature_events_utente": {"$sum": {"$cond": [{"$eq": ["$trigger", "utente"]}, 1, 0]}},
        }},
    ]).to_list(20000)
    events_by_key = {(r["_id"]["user_id"], r["_id"]["feature"], r["_id"]["channel"]): r for r in event_rows}

    now_iso = datetime.now(timezone.utc).isoformat()
    keys_seen = set()
    ops = []
    for r in call_rows:
        k = r["_id"]
        ev = events_by_key.get((k["user_id"], k["feature"], k["channel"]), {})
        keys_seen.add((k["user_id"], k["feature"], k["channel"]))
        doc_key = {"date": target_date, "user_id": k["user_id"], "feature": k["feature"], "channel": k["channel"], "model": k["model"]}
        ops.append(UpdateOne(doc_key, {"$set": {
            **doc_key,
            "calls": r["calls"], "calls_error": r["calls_error"], "calls_no_price": r["calls_no_price"],
            "input_tokens": r["input_tokens"], "cached_input_tokens": r["cached_input_tokens"],
            "output_tokens": r["output_tokens"], "total_tokens": r["total_tokens"],
            "cost_usd": round(r["cost_usd"], 6),
            "feature_events": ev.get("feature_events", 0), "feature_events_utente": ev.get("feature_events_utente", 0),
            "updated_at": now_iso,
        }}, upsert=True))

    # A feature use that triggered zero LLM calls (or whose calls fell in a different
    # model bucket) still needs to be counted - never silently dropped, per the spec's "una
    # chiamata non deve mai andare persa" applied to feature use as well as LLM calls.
    for (user_id, feature, channel), ev in events_by_key.items():
        if (user_id, feature, channel) in keys_seen:
            continue
        doc_key = {"date": target_date, "user_id": user_id, "feature": feature, "channel": channel, "model": None}
        ops.append(UpdateOne(doc_key, {"$set": {
            **doc_key,
            "calls": 0, "calls_error": 0, "calls_no_price": 0,
            "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
            "feature_events": ev.get("feature_events", 0), "feature_events_utente": ev.get("feature_events_utente", 0),
            "updated_at": now_iso,
        }}, upsert=True))

    if ops:
        await db.usage_daily.bulk_write(ops, ordered=False)


async def _usage_aggregation_loop():
    """Every hour: recomputes usage_daily for yesterday and today (Europe/Rome). Today's
    row is necessarily partial and gets overwritten again on every run until the day rolls
    over; yesterday is recomputed once more after midnight to catch anything that landed
    between the loop's last pass and the day boundary."""
    while True:
        try:
            today_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ).date()
            await _compute_usage_daily((today_local - timedelta(days=1)).isoformat())
            await _compute_usage_daily(today_local.isoformat())
        except Exception:
            logger.exception("usage aggregation loop iteration failed")
        await asyncio.sleep(60 * 60)


async def _daily_news_loop():
    """Every 5 min: for each user, once local time reaches their configured news_time
    (default 08:00, editable in Impostazioni) and today's news haven't gone out yet,
    searches the web for news matching their profile and stores + sends them."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            local_date = now.astimezone(LOCAL_TZ).date()
            today = local_date.isoformat()
            async for user in db.users.find({}, {"_id": 0}):
                if user.get("news_date") == today:
                    continue
                target_utc = _time_str_to_today_utc(user.get("news_time"), local_date)
                if now < target_utc:
                    continue
                try:
                    await _run_daily_news_for_user(user, today)
                except Exception:
                    logger.exception(f"daily news generation failed for {user.get('user_id')}")
        except Exception:
            logger.exception("daily news loop iteration failed")
        await asyncio.sleep(5 * 60)


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        await tg.stop_polling()
    except Exception:
        pass
    client.close()
