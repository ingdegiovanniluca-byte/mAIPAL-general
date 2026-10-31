from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header, UploadFile, File, Form
from fastapi.responses import StreamingResponse, RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
import os
import json
import logging
import re
import uuid
import secrets
import tempfile
import asyncio
import httpx
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Literal, Any
from datetime import date, datetime, timezone, timedelta
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
import microsoft_integration as ms
import telegram_bot as tg
import embeddings as emb
import retrieval
import news_service
import vet_reports
import work_reports
import job_logs as jl
import list_updates as lu
import scheduled_actions as sa
import recurrence as rec
import conversation_retention as cr
import mentions as mn
import usage_tracking as ut
import agent_guard
import help_guide
import verticals as vx
import push_notify as push
import site_presence as sp
import client_updates as cu
import access as orgaccess
import milestone_templates as mtpl
import fitness as fx

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
    role: Optional[str] = "user"              # in their organization: "admin" or "user"
    tenant_id: Optional[str] = None           # the organization (the subscription) the account belongs to
    org_id: Optional[str] = None              # the active team (lists, commesse, tasks shared with it)
    org_ids: Optional[List[str]] = None       # every team the account is in
    org_role: Optional[Literal["owner", "member"]] = None
    news_time: Optional[str] = "08:00"
    summary_time: Optional[str] = "07:00"
    presence_late_at: Optional[str] = None
    client_update_day: Optional[int] = None
    client_update_at: Optional[str] = None
    can_collaborators: Optional[bool] = None   # (computed by /auth/me: may link collaborators)
    tenant: Optional[dict] = None              # (computed by /auth/me: the organization's name, plan and rules)
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
    # artigiano: from this hour whoever is still "in cantiere" is asked if they really are
    presence_late_at: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    # artigiano: when the clients get the weekly progress of their works (0 = monday)
    client_update_day: Optional[int] = Field(default=None, ge=0, le=6)
    client_update_at: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ChatRequest(BaseModel):
    action: Literal["info_upload", "info_request", "task_todo", "journal", "help"]
    content: str
    filters: Optional[dict] = None
    # Help mode: the page the user opened it from ("Chiedi a Help" under a section's "i")
    page: Optional[str] = None
    conv_id: Optional[str] = None
    # Photos attached while writing a diary entry (action == "journal" only) - each a
    # "data:image/...;base64,..." URI, already size-checked client-side. Stored on the
    # journal entry so the Diario page can show them without depending on Google Drive.
    images: Optional[List[str]] = None
    # Non-image files attached to a diary entry (action == "journal" only) - already
    # uploaded to Drive client-side, each {"name": ..., "url": ...}.
    documents: Optional[List[dict]] = None
    # What the chat shows for this message when `content` also carries notes meant only
    # for the model (attachments indexed, Drive outcome): stored as the visible text, while
    # `content` is kept (as llm_content) so follow-up turns still give the model the full context.
    display_content: Optional[str] = None
    # KB documents (doc_id from /kb/upload) attached to this message: the model gets their
    # extracted text, and the message is linked to them so they are found by it later.
    attachment_doc_ids: Optional[List[str]] = None


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
    shared_with: List[str] = []  # user_id dei compagni di team con cui è condivisa
    share_perms: Dict[str, Literal["edit", "read"]] = {}  # per persona: modifica (default) o sola lettura
    org_perm: Literal["edit", "read"] = "edit"  # con "tutto il team": modifica o sola lettura
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


class CollectionSharingPayload(BaseModel):
    visibility: Literal["private", "org"] = "private"  # "org" = tutto il team
    user_ids: List[str] = []  # singole persone del team
    perms: Dict[str, Literal["edit", "read"]] = {}  # per persona: modifica (default) o sola lettura
    org_perm: Literal["edit", "read"] = "edit"  # con tutto il team


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
    # Files attached to this very message (already in the KB): their text is what the request
    # is about - "aggiungi questi prodotti alla lista della spesa" + a photo of a receipt.
    attachment_doc_ids: Optional[List[str]] = None
    # The chat conversation this request belongs to: the files sent earlier in it are the
    # context of "aggiungili alla lista della spesa" sent right after a photo.
    conv_id: Optional[str] = None


class NewsFeedbackPayload(BaseModel):
    value: Optional[Literal["like", "dislike"]] = None


# ---- Verticale fitness (scuole di danza/pilates): esercizi, lezioni, clienti ----
class ExerciseUpsert(BaseModel):
    name: str
    activity: Optional[str] = "funzionale"     # funzionale, pilates, danza...
    type: Optional[str] = ""                   # tipologia (Squat, Affondi...)
    role: Optional[str] = "esercizio"          # riscaldamento | esercizio | stretching
    body_part: Optional[str] = ""
    level: Optional[str] = None                # basso | medio | alto
    equipment: Optional[str] = ""              # "" = corpo libero
    equipment_per_person: Optional[int] = 0
    timed: Optional[dict] = None               # {allowed, min_sec, max_sec, min_sets, max_sets}
    reps: Optional[dict] = None                # {allowed, sec_per_set, min_reps, max_reps, min_sets, max_sets}
    description: Optional[str] = ""
    notes: Optional[str] = ""
    link: Optional[str] = ""
    # older fields (danza / pilates)
    discipline: Optional[str] = None
    category: Optional[str] = ""
    duration_minutes: Optional[int] = None
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


# ---- Verticale veterinario: report visita ----
class GenerateWorkReportPayload(BaseModel):
    text: str
    report_type: str = "sopralluogo"   # chiave built-in o id di un template personalizzato
    client_item_id: Optional[str] = None   # forza un cliente (risoluzione ambiguità nome)
    new_client: bool = False               # "è un cliente nuovo" anche se il nome somiglia a uno esistente
    # report di commessa: the chips, used for what the message doesn't say
    include: List[str] = []
    period: str = "all"
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class CommessaReportPayload(BaseModel):
    text: str = ""                         # which commessa, and what to bring out ("evidenzia i ritardi")
    commessa_id: Optional[str] = None      # chosen from the buttons when the text names none
    include: List[str] = []                # work_reports.COMMESSA_PARTS keys; none -> named in the text, else the default ones
    period: str = "all"                    # all (a period said in the text, else the whole job) | last7 | last30 | prev_month | custom
    date_from: Optional[str] = None        # custom: YYYY-MM-DD
    date_to: Optional[str] = None


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
    if user_doc.get("revoked_at"):   # suspended or removed by their organization's administrator
        raise HTTPException(status_code=401, detail="Accesso sospeso")
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


def _my_orgs(current: User) -> list:
    """Every team of the account (the active one first)."""
    ids = list(current.org_ids or [])
    if current.org_id and current.org_id not in ids:
        ids.insert(0, current.org_id)
    return ids


def _lists_query(current: User) -> dict:
    """Lists (collections) a user can see: their own, their teams' (visibility "org") and the
    ones a team-mate shared with them by name (shared_with) - in any of their teams. Sharing
    only holds within a team: whoever leaves it stops seeing the list."""
    orgs = _my_orgs(current)
    if orgs:
        return {"$or": [{"user_id": current.user_id}, {"org_id": {"$in": orgs}, "visibility": "org"},
                        {"org_id": {"$in": orgs}, "shared_with": current.user_id}]}
    return {"user_id": current.user_id}


def _list_perm(coll: dict, current: User) -> Optional[str]:
    """What the user can do on a list: "owner", "edit", "read" (shared read-only) or None.
    Shared with a team-mate by name, their own permission counts; with the whole team, the
    team's (both "edit" when never set: the lists shared before had no read-only)."""
    if coll.get("user_id") == current.user_id:
        return "owner"
    if not coll.get("org_id") or coll.get("org_id") not in _my_orgs(current):
        return None
    if current.user_id in (coll.get("shared_with") or []):
        return (coll.get("share_perms") or {}).get(current.user_id) or "edit"
    if coll.get("visibility") == "org":
        return coll.get("org_perm") or "edit"
    return None


READ_ONLY_LIST = "Questa lista è condivisa con te in sola lettura: puoi vederla ma non modificarla."


def _require_list_edit(coll: dict, current: User) -> None:
    if _list_perm(coll, current) not in ("owner", "edit"):
        raise HTTPException(status_code=403, detail=READ_ONLY_LIST)


def _clean_perms(user_ids: list, perms: dict) -> dict:
    """Only the read-only ones are kept (edit is the default)."""
    return {u: "read" for u in user_ids if (perms or {}).get(u) == "read"}


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


# ============ ORGANIZATIONS (tenants) ============
# Every account belongs to one organization - the unit that will subscribe. Who "subscribed"
# (for now: listed in the local file, see access.py) comes in as the administrator of their own
# organization; everyone else only when an administrator added them (an invitation by e-mail),
# within the plan's limits (users, collaborators, administrators). Nothing of an organization -
# its users, teams, collaborators - is ever shown to another one.

NOT_ALLOWED_MSG = ("Il tuo account non è abilitato a mAIPAL: chiedi all'amministratore della tua organizzazione "
                   "di aggiungerti agli utenti, con questa email.")


async def _access_gate(email: str) -> Optional[tuple]:
    """How an e-mail may come in: ("member", None) already in an organization, ("admin", entry)
    listed as an organization's administrator, ("invite", invitation) added by one; None: not."""
    email = (email or "").strip().lower()
    u = await db.users.find_one({"email": email}, {"_id": 0})
    if u and u.get("revoked_at"):
        return None
    if u and u.get("tenant_id"):
        return ("member", None)
    e = orgaccess.entry(email, ADMIN_EMAIL)
    if e:
        return ("admin", e)
    inv = await db.tenant_invites.find_one({"email": email}, {"_id": 0})
    return ("invite", inv) if inv else None


async def _new_tenant(owner: dict, name: str = "", plan: Optional[dict] = None) -> dict:
    t = {"id": f"ten_{uuid.uuid4().hex[:12]}", "name": name or f"Organizzazione di {_first_name(owner.get('name')) or owner.get('email')}",
         "owner_user_id": owner["user_id"], "owner_email": owner.get("email"), "plan": plan or dict(orgaccess.DEFAULT_PLAN),
         "sharing": {"users_share": True, "collab_contacts": False}, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.tenants.insert_one(t)
    t.pop("_id", None)
    return t


async def _apply_gate(user_doc: dict, gate: tuple) -> dict:
    """After the account is there: its organization (a new one for an administrator listed, the
    inviting one for an invitation). -> the user doc, updated."""
    kind, data = gate
    upd = {}
    if kind == "admin" and not user_doc.get("tenant_id"):
        t = await _new_tenant(user_doc, data.get("org") or "", data.get("plan"))
        upd = {"tenant_id": t["id"], "role": "admin"}
    elif kind == "invite" and not user_doc.get("tenant_id"):
        upd = {"tenant_id": data["tenant_id"], "role": "admin" if data.get("role") == "admin" else "user"}
        await db.tenant_invites.delete_many({"email": user_doc["email"]})
    if upd:
        await db.users.update_one({"user_id": user_doc["user_id"]}, {"$set": upd})
        user_doc = {**user_doc, **upd}
    return user_doc


async def _sharing_allowed(current: User) -> bool:
    """The organization's rule: may its users (not only its administrators) share lists, commesse,
    tasks and saved information with the others?"""
    if current.role == "admin" or not current.tenant_id:
        return True
    t = await db.tenants.find_one({"id": current.tenant_id}, {"_id": 0, "sharing": 1}) or {}
    return (t.get("sharing") or {}).get("users_share", True) is not False


SHARE_NOT_ALLOWED = "Nella tua organizzazione le condivisioni le decide l'amministratore."


async def _require_share_allowed(current: User) -> None:
    if not await _sharing_allowed(current):
        raise HTTPException(status_code=403, detail=SHARE_NOT_ALLOWED)


async def _tenant_of(current: User) -> Optional[dict]:
    return await db.tenants.find_one({"id": current.tenant_id}, {"_id": 0}) if current.tenant_id else None


def _plan(tenant: Optional[dict]) -> dict:
    """The plan's limits: the subscription's (for now the local file's, read live) or the stored ones."""
    if not tenant:
        return dict(orgaccess.DEFAULT_PLAN)
    e = orgaccess.entry(tenant.get("owner_email") or "", ADMIN_EMAIL)
    return {**orgaccess.DEFAULT_PLAN, **(tenant.get("plan") or {}), **((e or {}).get("plan") or {})}


async def _migrate_tenants() -> None:
    """Once the organizations exist: every account already in gets one (idempotent, at start).
    The administrators listed get their own; everyone else had been let in by the installation's
    administrator, so they are users of that organization, with its teams and collaborators."""
    admins = orgaccess.admins(ADMIN_EMAIL)
    users = await db.users.find({}, {"_id": 0}).to_list(10000)
    for u in users:
        if not u.get("tenant_id") and (u.get("email") or "").lower() in admins:
            await _apply_gate(u, ("admin", admins[u["email"].lower()]))
    users = await db.users.find({}, {"_id": 0}).to_list(10000)
    main_owner = next((u for u in users if (u.get("email") or "").lower() == ADMIN_EMAIL and u.get("tenant_id")), None) \
        or next((u for u in users if u.get("tenant_id") and (u.get("email") or "").lower() in admins), None)
    main = main_owner.get("tenant_id") if main_owner else None
    if not main:
        return
    for u in users:
        if not u.get("tenant_id"):
            await db.users.update_one({"user_id": u["user_id"]}, {"$set": {"tenant_id": main, "role": "user"}})
    known = {(u.get("email") or "").lower() for u in users}
    for a in await db.allowed_emails.find({}, {"_id": 0}).to_list(5000):
        em = (a.get("email") or "").lower()
        if em and em not in known and em not in admins and not await db.tenant_invites.find_one({"email": em}, {"_id": 1}):
            await db.tenant_invites.insert_one({"tenant_id": main, "email": em, "role": "user", "invited_by": "migrazione",
                                                "invited_at": datetime.now(timezone.utc).isoformat()})
    tenant_by_user = {u["user_id"]: u.get("tenant_id") for u in await db.users.find({}, {"_id": 0, "user_id": 1, "tenant_id": 1}).to_list(10000)}
    for o in await db.organizations.find({}, {"_id": 0}).to_list(5000):
        if not o.get("tenant_id"):
            await db.organizations.update_one({"id": o["id"]}, {"$set": {"tenant_id": tenant_by_user.get(o.get("created_by")) or main}})
    for c in await db.collaborators.find({}, {"_id": 0, "id": 1, "owner_user_id": 1, "tenant_id": 1}).to_list(10000):
        if not c.get("tenant_id"):
            await db.collaborators.update_one({"id": c["id"]}, {"$set": {"tenant_id": tenant_by_user.get(c.get("owner_user_id")) or main}})


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

    if await db.users.find_one({"email": email}, {"_id": 0}):
        raise HTTPException(status_code=409, detail="Un account con questa email esiste già. Prova ad accedere.")
    gate = await _access_gate(email)
    if not gate:
        raise HTTPException(status_code=403, detail=NOT_ALLOWED_MSG)

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user_doc = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "picture": None,
        "password_hash": _hash_password(payload.password),
        "role": "user",
        "onboarded": False,
        "profession": None,
        "sector": None,
        "verticals": [],
        "interests": [],
        "tone": "informale",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user_doc)
    user_doc.pop("_id", None)
    user_doc = await _apply_gate(user_doc, gate)

    session_token = await _create_session(user_id)
    _set_session_cookie(response, session_token)
    return {"user": User(**user_doc).model_dump()}


@api_router.post("/auth/login")
async def login(payload: LoginRequest, response: Response):
    email = (payload.email or "").strip().lower()
    user_doc = await db.users.find_one({"email": email}, {"_id": 0})
    if not user_doc or not user_doc.get("password_hash") or not _verify_password(payload.password, user_doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Email o password errati")
    gate = await _access_gate(email)
    if not gate:
        raise HTTPException(status_code=403, detail=NOT_ALLOWED_MSG)
    user_doc = await _apply_gate(user_doc, gate)

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

    gate = await _access_gate(email)
    if not gate:
        return RedirectResponse(f"{base}/?auth_error=not_whitelisted")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": info.get("name"), "picture": info.get("picture")}},
        )
        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": info.get("name", ""),
            "picture": info.get("picture"),
            "role": "user",
            "onboarded": False,
            "profession": None,
            "sector": None,
            "verticals": [],
            "interests": [],
            "tone": "informale",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(user_doc)
        user_doc.pop("_id", None)
    user_doc = await _apply_gate(user_doc, gate)

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
            if creds and user_doc.get("role") == "admin":   # (the users' files go to the administrator's archive)
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
    return current.model_copy(update={"can_collaborators": await _can_manage_collaborators(current),
                                      "tenant": await _tenant_view(current)})


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


async def require_admin(current: User = Depends(get_current_user)) -> User:
    """An administrator of their organization (only theirs is ever touched)."""
    if (current.role or "user") != "admin" or not current.tenant_id:
        raise HTTPException(status_code=403, detail="Solo l'amministratore della tua organizzazione")
    return current


# ============ THE ORGANIZATION (its administrator) ============
# Its users (invited by e-mail, within the plan), their role (another administrator, if the
# plan allows), suspended or removed; the plan's limits and what is used; the sharing rules.

class TenantUserInvite(BaseModel):
    email: str
    role: Literal["user", "admin"] = "user"


class TenantUserPatch(BaseModel):
    role: Optional[Literal["user", "admin"]] = None
    suspended: Optional[bool] = None


class TenantPatch(BaseModel):
    name: Optional[str] = None
    users_share: Optional[bool] = None        # the users (not only the administrators) share lists, commesse, tasks
    collab_contacts: Optional[bool] = None    # new collaborators see the clients' phone and e-mail


async def _tenant_usage(tenant: dict) -> dict:
    members = await db.users.find({"tenant_id": tenant["id"]}, {"_id": 0, "user_id": 1, "role": 1, "revoked_at": 1}).to_list(5000)
    invites = await db.tenant_invites.count_documents({"tenant_id": tenant["id"]})
    collabs = await db.collaborators.count_documents({"tenant_id": tenant["id"]})
    others = [m for m in members if m["user_id"] != tenant.get("owner_user_id")]
    return {"users": len(others) + invites, "admins": sum(1 for m in members if m.get("role") == "admin"), "collaborators": collabs}


async def _require_seat(tenant: dict, role: str = "user") -> None:
    plan, used = _plan(tenant), await _tenant_usage(tenant)
    if used["users"] >= plan["max_users"]:
        raise HTTPException(status_code=403, detail=f"Hai già {plan['max_users']} utenti, il massimo del tuo abbonamento.")
    if role == "admin" and used["admins"] >= plan["max_admins"]:
        raise HTTPException(status_code=403, detail="Il tuo abbonamento non prevede altri amministratori.")


async def _tenant_view(current: User) -> Optional[dict]:
    t = await _tenant_of(current)
    if not t:
        return None
    out = {"id": t["id"], "name": t.get("name"), "is_owner": t.get("owner_user_id") == current.user_id,
           "sharing": {"users_share": True, "collab_contacts": False, **(t.get("sharing") or {})}}
    if current.role == "admin":
        out.update(plan=_plan(t), usage=await _tenant_usage(t))
    return out


@api_router.get("/tenant")
async def get_tenant(current: User = Depends(get_current_user)):
    """The organization: for its administrators also its users, invitations, plan and usage."""
    view = await _tenant_view(current)
    if not view:
        raise HTTPException(status_code=404, detail="Nessuna organizzazione")
    if current.role == "admin":
        t = await _tenant_of(current)
        members = await db.users.find({"tenant_id": t["id"]}, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1, "picture": 1,
                                                               "revoked_at": 1, "created_at": 1}).to_list(5000)
        view["members"] = [{**m, "suspended": bool(m.pop("revoked_at", None)), "owner": m["user_id"] == t.get("owner_user_id")}
                           for m in sorted(members, key=lambda m: (m["user_id"] != t.get("owner_user_id"), (m.get("name") or "").lower()))]
        view["invites"] = await db.tenant_invites.find({"tenant_id": t["id"]}, {"_id": 0}).sort("invited_at", -1).to_list(500)
    return view


@api_router.patch("/tenant")
async def patch_tenant(payload: TenantPatch, current: User = Depends(require_admin)):
    t = await _tenant_of(current)
    upd = {}
    if payload.name is not None and payload.name.strip():
        upd["name"] = payload.name.strip()[:120]
    sharing = {"users_share": True, "collab_contacts": False, **(t.get("sharing") or {})}
    for k in ("users_share", "collab_contacts"):
        if getattr(payload, k) is not None:
            sharing[k] = getattr(payload, k)
    upd["sharing"] = sharing
    await db.tenants.update_one({"id": t["id"]}, {"$set": upd})
    return await get_tenant(current)


@api_router.post("/tenant/users")
async def invite_tenant_user(payload: TenantUserInvite, current: User = Depends(require_admin)):
    """A user of the organization: they come in with this e-mail (password or Google), as a user
    or - if the plan allows - as another administrator."""
    t = await _tenant_of(current)
    email = (payload.email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Email non valida")
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing and existing.get("tenant_id") == t["id"]:
        raise HTTPException(status_code=400, detail="Questa persona fa già parte della tua organizzazione")
    if existing and existing.get("tenant_id"):
        raise HTTPException(status_code=409, detail="Questa email usa già mAIPAL con un'altra organizzazione")
    if await db.tenant_invites.find_one({"email": email}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Questa email è già stata invitata")
    if orgaccess.entry(email, ADMIN_EMAIL):
        raise HTTPException(status_code=409, detail="Questa email ha una sua organizzazione")
    await _require_seat(t, payload.role)
    inv = {"tenant_id": t["id"], "email": email, "role": payload.role, "invited_by": current.email,
           "invited_at": datetime.now(timezone.utc).isoformat()}
    await db.tenant_invites.insert_one(inv)
    inv.pop("_id", None)
    if existing:   # an account already there (without an organization, maybe removed from one): in at once
        await db.users.update_one({"user_id": existing["user_id"]}, {"$unset": {"revoked_at": "", "revoked_by": ""}})
        await _apply_gate(existing, ("invite", inv))
    return await get_tenant(current)


@api_router.delete("/tenant/invites/{email}")
async def remove_tenant_invite(email: str, current: User = Depends(require_admin)):
    await db.tenant_invites.delete_one({"tenant_id": current.tenant_id, "email": (email or "").strip().lower()})
    return await get_tenant(current)


async def _tenant_member_or_404(current: User, user_id: str) -> tuple:
    t = await _tenant_of(current)
    u = await db.users.find_one({"user_id": user_id, "tenant_id": t["id"]}, {"_id": 0}) if t else None
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato nella tua organizzazione")
    if u["user_id"] == t.get("owner_user_id"):
        raise HTTPException(status_code=400, detail="Chi ha sottoscritto l'organizzazione resta sempre amministratore")
    return t, u


@api_router.patch("/tenant/users/{user_id}")
async def patch_tenant_user(user_id: str, payload: TenantUserPatch, current: User = Depends(require_admin)):
    """Another administrator (if the plan allows) or back to user; suspended (no access, data
    kept) or active again."""
    t, u = await _tenant_member_or_404(current, user_id)
    upd = {}
    if payload.role and payload.role != u.get("role"):
        if payload.role == "admin":
            plan, used = _plan(t), await _tenant_usage(t)
            if used["admins"] >= plan["max_admins"]:
                raise HTTPException(status_code=403, detail="Il tuo abbonamento non prevede altri amministratori.")
        upd["role"] = payload.role
    if payload.suspended is True and not u.get("revoked_at"):
        upd.update(revoked_at=datetime.now(timezone.utc).isoformat(), revoked_by=current.email)
        await db.user_sessions.delete_many({"user_id": user_id})
    if payload.suspended is False and u.get("revoked_at"):
        await db.users.update_one({"user_id": user_id}, {"$unset": {"revoked_at": "", "revoked_by": ""}})
    if upd:
        await db.users.update_one({"user_id": user_id}, {"$set": upd})
    return await get_tenant(current)


@api_router.delete("/tenant/users/{user_id}")
async def remove_tenant_user(user_id: str, current: User = Depends(require_admin)):
    """Out of the organization: no access any more, out of its teams; what they wrote in shared
    lists and commesse stays there."""
    t, u = await _tenant_member_or_404(current, user_id)
    for oid in _memberships(u):
        await _drop_membership(user_id, oid)
    await db.users.update_one({"user_id": user_id}, {"$set": {"tenant_id": None, "role": "user", "org_id": None, "org_ids": [],
                                                               "revoked_at": datetime.now(timezone.utc).isoformat(), "revoked_by": current.email}})
    await db.user_sessions.delete_many({"user_id": user_id})
    return await get_tenant(current)


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
    if updates.get("business_vertical"):
        await _apply_vertical(User(**user_doc), updates["business_vertical"])
        user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    out = User(**user_doc)
    return out.model_copy(update={"can_collaborators": await _can_manage_collaborators(out), "tenant": await _tenant_view(out)})


# ============ PACCHETTI VERTICALI (see verticals.py) ============
async def _apply_vertical(current: User, key: str) -> None:
    """Idempotent: what turning a vertical on needs - its team, its system lists. Never
    deletes or rewrites anything the user already has."""
    if key == "veterinario":
        await _ensure_vet_patients_list(current)
        return
    if key == "fitness":
        await _ensure_fitness_base(current)
        return
    if key != "artigiano":
        return
    if not current.org_id:   # the titolare's own team: collaborators will join it
        org_doc = {
            "id": f"org_{uuid.uuid4().hex[:12]}",
            "name": f"Impresa di {(current.name or 'te').split(' ')[0]}",
            "join_code": _gen_org_code(),
            "created_by": current.user_id,
            "tenant_id": current.tenant_id,
            "vertical": "artigiano",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.organizations.insert_one(org_doc)
        await _add_membership(current.user_id, org_doc["id"], "owner")
        current = current.model_copy(update={"org_id": org_doc["id"], "org_role": "owner"})
    await _ensure_clienti_list(current)
    await _ensure_weekly_jobs_action(current.model_copy(update={"business_vertical": "artigiano"}))


async def _ensure_clienti_list(current: User) -> dict:
    """The artigiano's "Clienti" list, with a "Commessa" under each client. A list already
    called Clienti is adopted (its attributes and data stay, the missing base ones are added)."""
    existing = await _clienti_list(current)
    if existing:
        return existing
    named = next((c for c in await db.collections.find({"user_id": current.user_id}, {"_id": 0}).to_list(500)
                  if (c.get("name") or "").strip().lower() == vx.CLIENTI_NAME.lower()), None)
    if named:
        fields, fmap = vx.merge_system_fields(named.get("fields"), vx.CLIENTI_FIELDS)
        subs, smap = vx.merge_system_fields(named.get("sub_item_fields"), vx.COMMESSA_FIELDS)
        upd = {"fields": _unique_field_keys(fields), "sub_item_fields": _unique_field_keys(subs),
               "system_key": vx.CLIENTI_KEY, "system_map": fmap, "system_sub_map": smap}
        if current.org_id:
            upd.update({"visibility": "org", "org_id": current.org_id})
        await db.collections.update_one({"id": named["id"]}, {"$set": upd})
        return {**named, **upd}
    fields, fmap = vx.merge_system_fields([], vx.CLIENTI_FIELDS)
    subs, smap = vx.merge_system_fields([], vx.COMMESSA_FIELDS)
    others = await db.collections.find(_lists_query(current), {"_id": 0, "sort_order": 1}).to_list(500)
    doc = {
        "id": f"coll_{uuid.uuid4().hex[:12]}",
        "name": vx.CLIENTI_NAME,
        "icon": None,
        "fields": fields,
        "sub_item_fields": subs,
        "system_key": vx.CLIENTI_KEY,
        "system_map": fmap,
        "system_sub_map": smap,
        "visibility": "org" if current.org_id else "private",
        "sort_order": min([o.get("sort_order", 0) for o in others], default=0) - 1,   # first in the page
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.collections.insert_one(doc)
    doc.pop("_id", None)
    return doc


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
# An account can be in several teams (org_ids); one is the active one (org_id): the lists,
# commesse and tasks shared "with the team" are the active team's, and it is changed from
# Impostazioni > Team. Whoever creates a team is in it; an invitation (by e-mail) is seen by the
# invited account there, to accept or decline - also when it is already in another team.

def _gen_org_code() -> str:
    return secrets.token_hex(3).upper()  # es. "A1B2C3"


def _team_q(org_id: Optional[str]) -> dict:
    """The users of a team (also the ones that only have it as their single, older org_id)."""
    return {"$or": [{"org_ids": org_id}, {"org_id": org_id}]}


def _memberships(udoc: dict) -> list:
    ids = list(udoc.get("org_ids") or [])
    if udoc.get("org_id") and udoc["org_id"] not in ids:
        ids.insert(0, udoc["org_id"])
    return ids


async def _add_membership(user_id: str, org_id: str, role: str = "member", activate: bool = False) -> None:
    """In the team (and active there when they had none, or when asked)."""
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    ids = _memberships(u)
    if org_id not in ids:
        ids.append(org_id)
    upd = {"org_ids": ids}
    if activate or not u.get("org_id"):
        upd.update({"org_id": org_id, "org_role": role})
    await db.users.update_one({"user_id": user_id}, {"$set": upd})


async def _drop_membership(user_id: str, org_id: str) -> bool:
    """Out of the team; if it was the active one, another of theirs becomes active (or none)."""
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not u or org_id not in _memberships(u):
        return False
    ids = [x for x in _memberships(u) if x != org_id]
    upd = {"org_ids": ids}
    if u.get("org_id") == org_id:
        upd.update({"org_id": ids[0] if ids else None, "org_role": "member" if ids else None})
    await db.users.update_one({"user_id": user_id}, {"$set": upd})
    return True


class TeamInviteCreate(BaseModel):
    email: str


class OrgSwitchPayload(BaseModel):
    org_id: str


class OrgLeavePayload(BaseModel):
    org_id: Optional[str] = None


async def _team_members(org_id: str) -> list:
    return await db.users.find(_team_q(org_id), {"_id": 0, "user_id": 1, "name": 1, "email": 1, "picture": 1, "org_role": 1,
                                                  "telegram_chat_id": 1}).to_list(300)


@api_router.get("/org")
async def get_org(current: User = Depends(get_current_user)):
    """The active team with its members, every team of the account (teams) and the invitations
    waiting for its e-mail (invites). Without any team and invitation: only those two, empty."""
    udoc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0}) or {}
    ids = _memberships(udoc)
    orgs = {o["id"]: o for o in await db.organizations.find({"id": {"$in": ids}}, {"_id": 0}).to_list(100)} if ids else {}
    teams = []
    for oid in ids:
        if oid in orgs:
            teams.append({"id": oid, "name": orgs[oid].get("name"), "active": oid == current.org_id,
                          "members_count": len(await _team_members(oid))})
    invites = []
    for inv in await db.team_invites.find({"email": (current.email or "").lower()}, {"_id": 0}).to_list(50):
        if inv["org_id"] in ids:
            continue
        o = await db.organizations.find_one({"id": inv["org_id"], "tenant_id": current.tenant_id}, {"_id": 0, "name": 1})
        if o:
            invites.append({"org_id": inv["org_id"], "name": o.get("name"), "invited_by": inv.get("invited_by"), "invited_at": inv.get("invited_at")})
    org = orgs.get(current.org_id)
    if not org:
        return {"teams": teams, "invites": invites, "members": []} if (teams or invites) else None
    members = await _team_members(org["id"])
    for m in members:
        m["has_telegram"] = bool(m.pop("telegram_chat_id", None))
    return {**org, "members": members, "teams": teams, "invites": invites}


@api_router.post("/org/join")
async def join_org(payload: OrgJoinPayload, current: User = Depends(get_current_user)):
    """With the team's code (the account's e-mail must be invited): in the team, also when it is
    already in others."""
    code = (payload.code or "").strip().upper()
    org = await db.organizations.find_one({"join_code": code, "tenant_id": current.tenant_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Codice non valido")
    return await _accept_invite(current, org)


async def _accept_invite(current: User, org: dict) -> dict:
    udoc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0}) or {}
    if org["id"] in _memberships(udoc):
        raise HTTPException(status_code=400, detail="Fai già parte di questo team")
    invite = await db.team_invites.find_one({"org_id": org["id"], "email": (current.email or "").lower()}, {"_id": 0})
    if not invite:
        raise HTTPException(status_code=403, detail="Il tuo indirizzo email non è stato invitato a questo team. Contatta l'amministratore.")
    await _add_membership(current.user_id, org["id"])
    await db.team_invites.delete_one({"org_id": org["id"], "email": (current.email or "").lower()})
    return org


@api_router.post("/org/invites/{org_id}/accept")
async def accept_team_invite(org_id: str, current: User = Depends(get_current_user)):
    """The invitation seen in Impostazioni > Team: in the team (the e-mail is the proof, no code)."""
    org = await db.organizations.find_one({"id": org_id, "tenant_id": current.tenant_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Team non trovato")
    return await _accept_invite(current, org)


@api_router.post("/org/invites/{org_id}/decline")
async def decline_team_invite(org_id: str, current: User = Depends(get_current_user)):
    await db.team_invites.delete_one({"org_id": org_id, "email": (current.email or "").lower()})
    return {"ok": True}


@api_router.post("/org/switch")
async def switch_org(payload: OrgSwitchPayload, current: User = Depends(get_current_user)):
    """The active team: the one whose shared lists, commesse and tasks the account works with."""
    udoc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0}) or {}
    if payload.org_id not in _memberships(udoc):
        raise HTTPException(status_code=404, detail="Non fai parte di questo team")
    org = await db.organizations.find_one({"id": payload.org_id, "tenant_id": current.tenant_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Team non trovato")
    role = "owner" if org.get("created_by") == current.user_id else "member"
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"org_id": payload.org_id, "org_role": role, "org_ids": _memberships(udoc)}})
    return {"ok": True, "org_id": payload.org_id}


@api_router.post("/org/leave")
async def leave_org(payload: Optional[OrgLeavePayload] = None, current: User = Depends(get_current_user)):
    org_id = (payload.org_id if payload else None) or current.org_id
    if not org_id or not await _drop_membership(current.user_id, org_id):
        raise HTTPException(status_code=400, detail="Non fai parte di questo team")
    return {"ok": True}


# ---- Gestione team (solo amministratore): crea più team (e ne fa parte), invita per email,
# fornisce il codice d'invito, rimuove membri. Un utente entra solo in un team a cui è stato
# invitato: accetta l'invito da Impostazioni > Team (o con il codice).
async def _team_with_details(org: dict) -> dict:
    members = await db.users.find(_team_q(org["id"]), {"_id": 0, "user_id": 1, "name": 1, "email": 1, "picture": 1}).to_list(300)
    invites = await db.team_invites.find({"org_id": org["id"]}, {"_id": 0}).sort("invited_at", -1).to_list(200)
    return {**org, "members": members, "invites": invites}


async def _team_or_404(current: User, team_id: str) -> dict:
    """A team of the administrator's own organization (no other one is ever touched)."""
    org = await db.organizations.find_one({"id": team_id, "tenant_id": current.tenant_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Team non trovato")
    return org


@api_router.get("/admin/teams")
async def admin_list_teams(current: User = Depends(require_admin)):
    orgs = await db.organizations.find({"tenant_id": current.tenant_id}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return [await _team_with_details(o) for o in orgs]


@api_router.post("/admin/teams")
async def admin_create_team(payload: OrgCreatePayload, current: User = Depends(require_admin)):
    """A new team, with whoever creates it already in (active only when they had none)."""
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obbligatorio")
    org_doc = {
        "id": f"org_{uuid.uuid4().hex[:12]}",
        "name": name,
        "join_code": _gen_org_code(),
        "created_by": current.user_id,
        "tenant_id": current.tenant_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.organizations.insert_one(org_doc)
    org_doc.pop("_id", None)
    await _add_membership(current.user_id, org_doc["id"], "owner")
    return await _team_with_details(org_doc)


@api_router.patch("/admin/teams/{team_id}")
async def admin_rename_team(team_id: str, payload: OrgRenamePayload, current: User = Depends(require_admin)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome obbligatorio")
    await _team_or_404(current, team_id)
    await db.organizations.update_one({"id": team_id}, {"$set": {"name": name}})
    org = await db.organizations.find_one({"id": team_id}, {"_id": 0})
    return await _team_with_details(org)


@api_router.post("/admin/teams/{team_id}/regenerate-code")
async def admin_regenerate_team_code(team_id: str, current: User = Depends(require_admin)):
    await _team_or_404(current, team_id)
    new_code = _gen_org_code()
    await db.organizations.update_one({"id": team_id}, {"$set": {"join_code": new_code}})
    return {"join_code": new_code}


@api_router.delete("/admin/teams/{team_id}")
async def admin_delete_team(team_id: str, current: User = Depends(require_admin)):
    await _team_or_404(current, team_id)
    for m in await db.users.find(_team_q(team_id), {"_id": 0, "user_id": 1}).to_list(500):
        await _drop_membership(m["user_id"], team_id)
    await db.team_invites.delete_many({"org_id": team_id})
    await db.organizations.delete_one({"id": team_id})
    return {"ok": True}


@api_router.post("/admin/teams/{team_id}/invites")
async def admin_invite_to_team(team_id: str, payload: TeamInviteCreate, current: User = Depends(require_admin)):
    """An invitation by e-mail: the account sees it in Impostazioni > Team (and is told, if it
    already has the app), also when it is already in another team."""
    org = await _team_or_404(current, team_id)
    email = (payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email non valida")
    invited = await db.users.find_one({"email": email, "tenant_id": current.tenant_id}, {"_id": 0})
    if not invited:   # only people of the organization: add them first among its users
        raise HTTPException(status_code=400, detail="Questa email non è tra gli utenti della tua organizzazione: aggiungila prima "
                                                    "in Impostazioni → Organizzazione.")
    if invited and team_id in _memberships(invited):
        raise HTTPException(status_code=400, detail="Questa persona fa già parte del team")
    if invited and invited["user_id"] == current.user_id:   # yourself: simply in
        await _add_membership(current.user_id, team_id)
        return {"org_id": team_id, "email": email, "joined": True}
    await db.team_invites.update_one(
        {"org_id": team_id, "email": email},
        {
            "$set": {"org_id": team_id, "email": email},
            "$setOnInsert": {"id": f"inv_{uuid.uuid4().hex[:12]}", "invited_by": current.email, "invited_at": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )
    if invited:
        text = (f"👥 {current.name or 'L'+chr(39)+'amministratore'} ti ha invitato nel team «{org['name']}»: "
                "lo accetti in mAIPAL → Impostazioni → Team.")
        push.fire_and_forget(db, invited["user_id"], "👥 Invito in un team", text, "/dashboard/settings?s=team", f"team-{team_id}")
        if invited.get("telegram_chat_id"):
            try:
                await _send_telegram_text(invited["telegram_chat_id"], text)
            except Exception:
                logger.exception("team invite notice failed")
    return await db.team_invites.find_one({"org_id": team_id, "email": email}, {"_id": 0})


@api_router.delete("/admin/teams/{team_id}/invites/{email}")
async def admin_remove_team_invite(team_id: str, email: str, current: User = Depends(require_admin)):
    await _team_or_404(current, team_id)
    await db.team_invites.delete_one({"org_id": team_id, "email": (email or "").strip().lower()})
    return {"ok": True}


@api_router.delete("/admin/teams/{team_id}/members/{member_user_id}")
async def admin_remove_team_member(team_id: str, member_user_id: str, current: User = Depends(require_admin)):
    await _team_or_404(current, team_id)
    if not await _drop_membership(member_user_id, team_id):
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
            "Tu salvi SOLO informazioni e note: non puoi aggiungere, togliere o modificare elementi delle Liste "
            "(lista della spesa, clienti...). Non dire MAI di averlo fatto; se l'utente lo chiedeva, digli che hai "
            "salvato l'informazione come nota e che può chiedere di nuovo la modifica alla lista. "
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
            "Leggi TUTTO il contesto prima di rispondere: le voci possono essere note, documenti, task, diario o liste. "
            "DATE: ogni nota riporta tra parentesi quadre il giorno in cui è stata salvata (es. '[Nota salvata sabato 12 settembre 2026]'). "
            "Se il testo di una nota usa un riferimento relativo ('oggi', 'ieri', 'stamattina', 'venerdì scorso', 'il 19'), "
            "calcola la data reale a partire dal giorno di salvataggio di QUELLA nota, non da oggi: 'oggi Martina ha fatto pilates' "
            "salvata il 12 settembre significa il 12 settembre. "
            "Se la domanda chiede QUANDO o QUANTE VOLTE è successo qualcosa, elenca tutte le occorrenze che trovi nel contesto "
            "(ogni data, in ordine cronologico), non solo la prima. "
            "Considera equivalenti parole vicine per significato (es. 'lezione' e 'pilates', 'corso' e 'lezione', singolare e plurale). "
            "Rispondi 'non ho trovato' SOLO se nessuna voce del contesto riguarda davvero la domanda. "
            "Tu NON salvi nulla: se l'utente ti chiede di registrare, salvare o annotare qualcosa, o ti racconta un fatto "
            "da ricordare (es. 'oggi ho speso 50 euro di benzina'), NON dire mai di averlo registrato o salvato: digli "
            "chiaramente che NON è stato salvato e che per salvarlo deve usare l'agente Salva. "
            "Se il contesto è vuoto o non pertinente, indica gentilmente che non hai fonti dalla KB personale e rispondi con le tue conoscenze generali. "
            "Al termine, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"argomento in 3-6 parole\", \"summary\": \"riassunto naturale in 1 riga, max 140 caratteri, che descriva cosa hai risposto\"}<<<END>>>"
        )
    elif action == "task_todo":
        base += (
            " L'utente vuole salvare un task o un to-do. Se è presente un CONTESTO dalla knowledge base personale "
            "(es. un documento o un'immagine caricati prima, o proprio in questo messaggio, con un programma/orario/"
            "elenco di eventi), usalo per capire di quali eventi l'utente sta parlando. "
            "REGOLA CRITICA: se il messaggio dell'utente non sta chiaramente descrivendo uno o più task/to-do da "
            "creare o modificare (es. sta facendo una domanda, un commento generico, o parlando d'altro), NON "
            "includere il blocco META qui sotto - rispondi in modo naturale e basta, senza fingere di aver salvato "
            "nulla. "
            "CREAZIONE MULTIPLA: se l'utente chiede di creare un task per OGNUNO di più eventi (es. 'crea un task per "
            "ogni lezione di pilates della settimana', quando il CONTESTO contiene un programma con più orari/date), "
            "e il CONTESTO fornisce dati sufficienti per identificarli tutti con certezza, crea un task PER CIASCUNO: "
            "usa il blocco META in forma elenco, "
            "<<<META>>>{\"tasks\": [{\"title\": \"...\", \"due_date\": \"YYYY-MM-DD\", \"due_time\": \"HH:MM o null\", "
            "\"duration_minutes\": \"numero o null\", \"priority\": \"alta|media|bassa\", \"tags\": [\"...\"], \"notes\": \"\", "
            "\"recurrence\": {...} solo se va ripetuto, vedi RICORRENZA}, "
            "...]}<<<END>>>, un oggetto per evento, con le stesse regole su date/ore/durata descritte sotto. Nella "
            "risposta visibile elenca brevemente cosa hai creato (es. 'Ho creato 5 task, uno per ogni lezione di "
            "pilates della settimana: lunedì, mercoledì...'). Se il CONTESTO non è chiaro o sufficiente per "
            "identificare con certezza tutti gli eventi, NON inventare: chiedi all'utente di chiarire o ricaricare il "
            "documento, senza includere il blocco META. "
            "CREAZIONE SINGOLA: altrimenti, per un solo task/to-do, scrivi UNA risposta di conferma naturale (1-2 "
            "frasi, es. 'Perfetto, ho preso nota: ti ricorderò di chiamare Marco domani alle 15:30.'). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"breve titolo del task/todo\", \"summary\": \"riassunto in 1 riga max 140 caratteri\", \"description\": \"\", "
            "\"due_date\": \"YYYY-MM-DD o null\", \"due_time\": \"HH:MM o null\", \"duration_minutes\": \"numero di minuti o null\", "
            "\"reminder_minutes_before\": \"numero di minuti o null\", "
            "\"priority\": \"alta|media|bassa\", \"tags\": [\"...\"], \"notes\": \"\", "
            "\"recurrence\": {...} solo se va ripetuto, vedi RICORRENZA}<<<END>>>. "
            "RICORRENZA: se l'utente chiede che il task si RIPETA (es. 'ogni lunedì alle 9', 'tutti i giorni', 'ogni 2 "
            "settimane', 'il primo di ogni mese', 'ogni anno il 3 ottobre', 'per tutto il 2026', 'fino a dicembre', "
            "'per 10 volte'), aggiungi \"recurrence\": {\"freq\": \"daily|weekly|monthly|yearly\", \"interval\": 1, "
            "\"weekdays\": [numeri 0-6, 0=lunedì, solo per weekly], \"day_of_month\": 1-31 oppure -1 per l'ultimo giorno "
            "(solo per monthly), \"until\": \"YYYY-MM-DD o null\", \"count\": \"numero di ripetizioni o null\"} e metti in "
            "due_date la PRIMA occorrenza da oggi in poi (es. 'ogni lunedì' -> il prossimo lunedì, oggi compreso). "
            "'Per tutto il 2026' -> until 2026-12-31. Se l'utente non chiede ripetizioni ometti del tutto recurrence. "
            "Nella risposta visibile conferma anche la cadenza (es. 'ogni lunedì alle 9'). "
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
            "REGOLA SULLA DATA (IMPORTANTE, controlla SEMPRE): la voce va salvata sul giorno a cui il racconto si "
            "riferisce, non sempre oggi. Prima di rispondere, controlla se il testo contiene un riferimento temporale "
            "diverso da oggi, anche implicito (es. 'ieri', 'l'altro ieri', 'stamattina presto' se ora è sera inoltrata, "
            "'domenica scorsa', 'il 19 settembre', 'tre giorni fa', un giorno della settimana passato senza 'prossimo'). "
            "Se lo trovi, calcola la data esatta (usando SEMPRE oggi come riferimento, come indicato all'inizio di "
            "questo messaggio) e mettila nei metadati come \"date\": \"YYYY-MM-DD\" - esempio: se oggi è martedì 23 "
            "settembre 2026 e l'utente scrive 'ieri sono andato al mare', il campo deve essere \"date\": \"2026-09-22\". "
            "Questo passaggio non è facoltativo: se c'è un riferimento temporale e lo ometti, la voce finisce sul "
            "giorno sbagliato. Se invece il testo NON specifica alcun riferimento temporale (racconta senza dire "
            "quando è successo), ometti del tutto la chiave \"date\" - il sistema userà oggi automaticamente. "
            "Rispondi con il diario riscritto in modo naturale (senza intestazioni tipo 'Diario:' e senza menzionare la data, "
            "che è già evidente da dove viene salvata la voce). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"titolo breve della giornata (max 6 parole)\", "
            "\"summary\": \"riassunto in 1 riga max 140 caratteri\", "
            "\"date\": \"YYYY-MM-DD - includi questa chiave SOLO se hai individuato un riferimento temporale diverso da "
            "oggi come spiegato sopra, altrimenti ometti del tutto la chiave\", "
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
    (see retrieval.py) so it isn't recomputed on every search. If this
    update touches one of the fields that embedding was computed from, drop the stale
    cache so the next search recomputes it from the new text."""
    if any(f in payload for f in text_fields):
        payload["embedding"] = None




async def retrieve_kb(user_id: str, query: str, limit: int = 8, scope: str = "kb", org_id: Optional[str] = None) -> List[dict]:
    """Search the user's saved knowledge - see retrieval.py (kept separate so it can be
    tested without the web server). Used by the web chat and the Telegram bot alike."""
    return await retrieval.retrieve(db, user_id, query, limit=limit, scope=scope, org_id=org_id)


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
    "help": "help",
}


class AgentCheckPayload(BaseModel):
    action: str
    text: str


@api_router.post("/agents/check")
async def agents_check(payload: AgentCheckPayload, current: User = Depends(get_current_user)):
    """Before a NEW chat goes to the chosen agent: is it surely the wrong one? Then the chat
    suggests the right agent instead of answering (see agent_guard.py)."""
    return {"suggestion": await agent_guard.check(payload.text, payload.action, user_id=current.user_id)}


@api_router.get("/help/sections")
async def help_sections(path: Optional[str] = None, current: User = Depends(get_current_user)):
    """What the "i" next to a section's title shows: that page's part of the guide (for the
    user's vertical), plus the titles of all the others."""
    v = current.business_vertical
    page = help_guide.for_path(path, v) if path else []
    return {
        "sections": [{"id": s.id, "title": s.title, "body": s.body} for s in page],
        "index": [{"id": s.id, "title": s.title} for s in help_guide.sections_for(v)],
    }


@api_router.get("/help/sections/{section_id}")
async def help_section(section_id: str, current: User = Depends(get_current_user)):
    sec = next((s for s in help_guide.sections_for(current.business_vertical) if s.id == section_id), None)
    if not sec:
        raise HTTPException(status_code=404, detail="Sezione della guida non trovata")
    return {"id": sec.id, "title": sec.title, "body": sec.body}


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
            "user_message": payload.display_content or payload.content,   # legacy: first message for cronologia preview
            "filters": payload.filters or {},
            "pipeline": {"claude": "ok", "n8n": "skip", "mongodb": "ok"},
            "messages": [],
        })

    # @agenti: the part before the first tag is this action's message; the tagged pieces
    # are run by their agents after it (see _run_sub_agent). The chat shows the message as
    # typed, tags included.
    shown_user_text = payload.display_content or payload.content
    typed = _strip_attachment_lines(payload.display_content) if payload.display_content else payload.content.split("\n\nAllegati caricati", 1)[0]
    # @persone / @team: who the saved information is ALSO shared with (see _share_kb_docs)
    share_recipients, share_slugs, typed_clean = [], [], typed
    if current.org_id and "@" in typed and await _sharing_allowed(current):
        members = await db.users.find(_team_q(current.org_id), {"_id": 0, "user_id": 1, "name": 1, "email": 1, "telegram_chat_id": 1}).to_list(300)
        directory = mn.people_directory(members)
        typed_clean, share_slugs = mn.extract_people(typed, directory)
        for slug in share_slugs:
            share_recipients += [m for m in members if m["user_id"] != current.user_id] if slug in mn.GROUP_TAGS else [directory[slug]]
        share_recipients = list({m["user_id"]: m for m in share_recipients if m["user_id"] != current.user_id}.values())
    main_text, mention_parts = mn.split_mentions(typed_clean)
    run_primary = True
    if mention_parts or share_slugs:
        run_primary = bool(main_text)
        payload.content = payload.content.replace(typed, main_text, 1) if typed and typed in payload.content else main_text
        if payload.display_content:
            payload.display_content = payload.display_content.replace(typed, main_text, 1)
    linkage: dict = {}

    # RAG context: run on EVERY info_request turn (not just first) so follow-up questions
    # can pull fresh chunks based on the new question. Also runs for task_todo so a request
    # like "crea un task per ogni lezione di pilates" can see a schedule the user uploaded
    # earlier (or just now, in this same turn - see the attachment handling above) without
    # having to paste its content into the chat - scope is forced to "kb" (personal
    # documents only, not other tasks/todos/journal entries, which would just be noise here).
    # Help: the chat in Help mode, or a question to Cerca that is clearly about mAIPAL itself
    # ("come creo una lista?") - answered from the guide, not from the user's data
    help_turn = action == "help"
    if not help_turn and action == "info_request" and run_primary and not payload.attachment_doc_ids:
        help_turn = await help_guide.is_about_app(main_text, user_id=current.user_id)

    kb_context = []
    if action == "info_request" and not help_turn:
        if payload.conv_id:
            scope = (conv.get("filters", {}) or {}).get("scope", "all")
        else:
            scope = (payload.filters or {}).get("scope", "all")
        kb_context = await retrieve_kb(current.user_id, payload.content, scope=scope, org_id=current.org_id)
        logger.info(f"[RAG] user={current.user_id[:8]} scope={scope} q={payload.content[:60]!r} chunks={len(kb_context)}")
    elif action == "task_todo":
        kb_context = await retrieve_kb(current.user_id, payload.content, scope="kb", org_id=current.org_id)
        logger.info(f"[RAG] user={current.user_id[:8]} scope=kb (task_todo) q={payload.content[:60]!r} chunks={len(kb_context)}")

    system = build_system_prompt(current, action)
    user_text = payload.content
    if help_turn:
        system = help_guide.system_prompt(current.name, current.business_vertical, _today_it_string())
        user_text = help_guide.user_message(payload.content, current.business_vertical, payload.page)
    attached_ids = [d for d in (payload.attachment_doc_ids or []) if isinstance(d, str)][:10]
    conv_doc_ids = await _conv_attachment_ids(current.user_id, conv, prior_messages) if payload.conv_id else []
    if attached_ids:
        await db.conversations.update_one({"conv_id": conv_id}, {"$addToSet": {"attachment_doc_ids": {"$each": attached_ids}}})
    # a follow-up about a file sent earlier in this chat ("le canzoni del file", "crea i task
    # di quello che c'è da fare") - the model only kept what the user typed, not the file's text
    if not attached_ids and conv_doc_ids and action in ("task_todo", "info_request") and run_primary and not help_turn:
        att_text = await _attachments_text_for_model(current.user_id, conv_doc_ids, limit=8000)
        if att_text:
            user_text = (f"{user_text}\n\nDOCUMENTI ALLEGATI IN QUESTA CONVERSAZIONE (testo completo - usalo quando "
                         f"la richiesta si riferisce al file o al documento):\n{att_text}")
    if attached_ids and action in ("info_upload", "task_todo"):
        att_text = await _attachments_text_for_model(current.user_id, attached_ids)
        if att_text:
            user_text = (f"{user_text}\n\nCONTENUTO LETTO DAGLI ALLEGATI (già salvato nella knowledge base, collegato a "
                         f"questo messaggio - nella risposta conferma in breve cosa contiene, es. esercente, data e "
                         f"totale di uno scontrino):\n{att_text}")
    if kb_context:
        def _fmt(c):
            # Non-KB sources (task/todo/journal) use a compact display line.
            # KB chunks are already chunked to ~1400 chars during upload — send them in full.
            if c.get("display"):
                return c["display"]
            return c.get("text", "")
        ctx = "\n\n".join([f"- {_fmt(c)}" for c in kb_context])
        label = "RICHIESTA" if action == "task_todo" else "DOMANDA"
        period = retrieval.period_hint(payload.content) if action == "info_request" else ""
        user_text = f"CONTESTO KB PERSONALE:\n{ctx}\n\n{period + chr(10) + chr(10) if period else ''}{label}:\n{user_text}"

    initial = [{"role": "system", "content": system}]
    for m in prior_messages:
        initial.append({"role": m["role"], "content": m.get("llm_content") or m["content"]})

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=conv_id,
        system_message=system,
        initial_messages=initial,
        user_id=current.user_id, feature="help" if help_turn else _ACTION_TO_FEATURE.get(action, "altro"),
        channel="web", trigger="utente", org_id=current.org_id,
    ).with_model("openai", "gpt-4o")

    # Save the user turn to the messages array immediately
    await db.conversations.update_one(
        {"conv_id": conv_id},
        {"$push": {"messages": {"role": "user", "content": shown_user_text, "ts": now,
                                **({"llm_content": payload.content} if payload.content != shown_user_text else {})}}},
    )

    import json as _json
    MARKER = "<<<META>>>"
    async def primary_events():
        full = []
        pending = ""     # buffer with tail that could still be a partial marker prefix
        stopped = False  # true once MARKER encountered
        if help_turn:   # the chat marks this answer as Help's
            yield _json.dumps({"type": "help"}) + "\n"
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
        if not prior_messages:
            asyncio.create_task(_ensure_conv_topics(current.user_id, [conv_id]))
        if not prior_messages and meta:
            if meta.get("title"): conv_set["title"] = meta["title"]
            if meta.get("summary"): conv_set["summary"] = meta["summary"]
        await db.conversations.update_one(
            {"conv_id": conv_id},
            {
                "$push": {"messages": {"role": "assistant", "content": visible_answer, "ts": completed_at, **({"help": True} if help_turn else {})}},
                "$set": conv_set,
            },
        )

        # One feature_events row per chat turn, regardless of how many (if any) LLM calls
        # it triggered - lets the usage dashboard count feature USES, not just LLM calls.
        ut.fire_and_forget_feature_event(
            user_id=current.user_id, feature="help" if help_turn else _ACTION_TO_FEATURE.get(action, "altro"),
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
        if action == "info_upload" and attached_ids:
            typed = _strip_attachment_lines(payload.display_content or payload.content.split("\n\nAllegati caricati", 1)[0])
            try:
                await _link_user_context_to_docs(current.user_id, attached_ids, typed)
            except Exception:
                logger.exception("linking message to attachments failed")
        if action == "info_upload":
            # the note is what the user wrote (+ attached file names), not the notes for the model
            note_text = payload.display_content or payload.content
            try:
                e = await emb.embed_texts([note_text])
                embedding = e[0] if e else None
            except Exception:
                embedding = None
            doc_id = f"doc_{uuid.uuid4().hex[:12]}"
            linkage["source"] = {"type": "note", "doc_id": doc_id, "conv_id": conv_id, "preview": note_text[:200],
                                 "created_at": datetime.now(timezone.utc).isoformat()}
            await db.kb_chunks.insert_one({
                "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
                "user_id": current.user_id,
                "text": note_text,
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
                classification = await _classify_document(note_text, user_id=current.user_id, channel="web")
            except Exception:
                classification = {"category": "altro", "keywords": []}
            await db.kb_documents.insert_one({
                "doc_id": doc_id,
                "user_id": current.user_id,
                "name": (meta or {}).get("title") if meta else (note_text[:60] + ("…" if len(note_text) > 60 else "")),
                "ext": "chat",
                "source_type": "chat",
                "category": classification["category"],
                "keywords": list({*(classification["keywords"] or []), *(((meta or {}).get("tags") or []))})[:8],
                "chunks_count": 1,
                "chars": len(note_text),
                "size_bytes": len(note_text.encode("utf-8")),
                "preview": (((meta or {}).get("summary")) or note_text)[:280],
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

        # task_todo: creates on the FIRST turn of the thread that actually describes
        # something to save (per the system prompt, an earlier turn may have omitted META
        # entirely, e.g. a clarifying question) - not necessarily message #1. A later turn
        # with more META in the SAME thread updates what was already created there instead
        # of creating a duplicate, or - the bug this fixes - being silently dropped just
        # because it wasn't the very first message.
        if action == "task_todo":
            logger.info(f"[task_todo] meta={meta!r}")
            # mobile chat icons: put the new tasks on the calendar / turn their reminder on
            task_opts = {"default_reminder_enabled": bool((payload.filters or {}).get("reminder")),
                         "sync_calendar": bool((payload.filters or {}).get("calendar"))}
            try:
                saved = await _apply_task_todo_turn(current.user_id, main_text or typed, meta, conv_id, visible_answer, **task_opts)
            except Exception:
                logger.exception("task_todo save failed")
                saved = "⚠️ Non sono riuscito a salvarlo: riprova."
            if saved:
                # the line saying what was really saved (and where), in the chat and in the history
                yield _json.dumps({"type": "delta", "content": ("\n\n" if visible_answer else "") + saved}) + "\n"
                conv_doc = await db.conversations.find_one({"conv_id": conv_id}, {"_id": 0, "messages": 1}) or {}
                msgs = conv_doc.get("messages") or []
                if msgs and msgs[-1].get("role") == "assistant":
                    msgs[-1]["content"] = (msgs[-1].get("content") or "") + ("\n\n" if visible_answer else "") + saved
                    await db.conversations.update_one({"conv_id": conv_id}, {"$set": {"messages": msgs, "agent_response": msgs[-1]["content"]}})
        # journal: side-effect only on first exchange - a follow-up turn is normally a
        # refinement of the SAME entry, not a brand new one.
        elif not prior_messages and action == "journal":
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

            target_date = _resolve_journal_date(meta)
            jr = await _save_journal_entry(
                current.user_id, target_date, payload.content, visible_answer, meta, conv_id,
                images=valid_images, documents=valid_documents,
            )

            # Best-effort backup copy on Drive (Diario subfolder) when connected - the
            # app itself always displays the images straight from `jr["images"]` above,
            # this is purely for the user's own organization/backup on Drive.
            if valid_images and await _storage_targets(current.user_id):
                try:
                    import base64 as _b64
                    for idx, img in enumerate(valid_images):
                        header, b64_part = img.split(",", 1)
                        content_type = header.split(":", 1)[1].split(";", 1)[0] or "image/jpeg"
                        ext = content_type.split("/", 1)[-1] or "jpg"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                            tmp.write(_b64.b64decode(b64_part))
                            tmp_path = tmp.name
                        try:
                            await _storage_save(current.user_id, "Diario", tmp_path, f"diario_{jr['date']}_{idx + 1}.{ext}", content_type)
                        finally:
                            try: os.unlink(tmp_path)
                            except Exception: pass
                except Exception:
                    logger.exception("Drive/OneDrive backup of journal images failed")


    async def event_gen():
        if run_primary:
            async for chunk in primary_events():
                yield chunk
        # shared with @persone / @team: a copy of the saved note (and its attachments) in their knowledge base
        if share_slugs:
            if action == "info_upload" and linkage.get("source", {}).get("doc_id"):
                if share_recipients:
                    res = await _share_kb_docs(current, share_recipients, [linkage["source"]["doc_id"]] + attached_ids)
                else:
                    res = {"agent": "share", "label": "Condivisione", "status": "error", "message": "⚠️ Nel team non c'è nessun altro con cui condividere."}
            else:
                res = {"agent": "share", "label": "Condivisione", "status": "error",
                       "message": "ℹ️ Per condividere con persone o col team usa \"Salva informazioni\"."}
            await db.conversations.update_one({"conv_id": conv_id}, {"$push": {"messages": {
                "role": "assistant", "content": res["message"], "agent": "share", "ts": datetime.now(timezone.utc).isoformat()}}})
            yield _json.dumps({"type": "agent", **res}) + "\n"
        # then every @agent piece, each with the whole message as context
        source = linkage.get("source") or {"type": "conversation", "conv_id": conv_id, "created_at": now}
        docs_text = ""
        if mention_parts:
            doc_ids = list(dict.fromkeys(attached_ids + conv_doc_ids))
            if doc_ids:
                docs_text = await _attachments_text_for_model(current.user_id, doc_ids, limit=8000)
        for part in mention_parts[:6]:
            res = await _run_sub_agent(current, part["agent"], part["text"], typed, source, conv_id, docs=docs_text)
            await db.conversations.update_one({"conv_id": conv_id}, {"$push": {"messages": {
                "role": "assistant", "content": res.get("message") or "", "agent": part["agent"],
                "ts": datetime.now(timezone.utc).isoformat()}}})
            yield _json.dumps({"type": "agent", **res}) + "\n"
        if not run_primary and not prior_messages:
            await db.conversations.update_one({"conv_id": conv_id}, {"$set": {"completed_at": datetime.now(timezone.utc).isoformat()}})
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


async def _create_task_or_todo(user_id: str, parsed: dict, conv_id: str, default_reminder_enabled: bool = False,
                               sync_calendar: bool = False):
    now = datetime.now(timezone.utc).isoformat()
    # RULE: if due_date is present → TASK, otherwise → TODO (regardless of any 'type' field the LLM returned)
    due_date = parsed.get("due_date")
    recurrence_raw = parsed.get("recurrence") if isinstance(parsed.get("recurrence"), dict) else None
    if recurrence_raw and not due_date:
        # "ogni lunedì" without an explicit date: the first occurrence from today on
        due_date = rec.first_occurrence(recurrence_raw, datetime.now(LOCAL_TZ).date())
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
        if recurrence_raw:
            try:
                await _set_task_recurrence(doc, recurrence_raw, user_id)
            except Exception:
                logger.exception(f"recurrence setup failed for {recurrence_raw!r}")
        if sync_calendar:  # calendar icon on in the chat: straight onto the chosen calendars
            try:
                owner = await db.users.find_one({"user_id": user_id}, {"_id": 0})
                doc = await update_task(doc["id"], {"calendar_synced": True}, User(**owner))
            except Exception:
                logger.exception("calendar sync of a chat-created task failed")
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
    doc.pop("_id", None)
    return doc


def _resolve_journal_date(meta: Optional[dict]) -> str:
    """The calendar date a journal entry belongs to: the date the model identified in META
    (validated YYYY-MM-DD, computed from the same "Oggi è ..." reference date it was given -
    see build_system_prompt's journal instructions), or today if none was given / it was
    invalid. The entry is saved on the day the user is actually talking about (e.g. "ieri",
    "il 19 settembre"), not always on today's page.

    The raw value is matched for a YYYY-MM-DD substring rather than requiring the whole
    string to be exactly that (instead of a strict strptime on the full value) - the model
    occasionally wraps the date in a few extra words or a time suffix despite the prompt
    asking for a bare date, and a strict full-string match silently discarded those and fell
    back to today instead of the day the user actually meant."""
    import re as _re
    raw = (meta or {}).get("date")
    if raw:
        m = _re.search(r"\d{4}-\d{2}-\d{2}", str(raw))
        if m:
            try:
                datetime.strptime(m.group(0), "%Y-%m-%d")
                return m.group(0)
            except ValueError:
                pass
    return datetime.now(timezone.utc).date().isoformat()


def _downscale_image_bytes(contents: bytes, max_dim: int = 2000, max_bytes: int = 4 * 1024 * 1024) -> bytes:
    """Re-encodes raw image bytes as JPEG, downscaled/compressed if needed (also normalizes
    HEIC/HEIF/WebP to a format every vision model accepts). A phone camera photo can be many
    MB at full resolution with no client-side compression on some upload paths (e.g. a plain
    file attachment, unlike the diary's own upload flow which already downsizes in the
    browser) - sending that straight to an OCR/vision call can make the call fail outright
    instead of just being slow, which is indistinguishable from a generic "upload error" to
    the user."""
    from PIL import Image
    from io import BytesIO
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    img = Image.open(BytesIO(contents))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > max_dim:
        scale = max_dim / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    quality = 88
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    while len(buf.getvalue()) > max_bytes and quality > 40:
        quality -= 10
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _image_bytes_to_journal_data_uri(contents: bytes, max_dim: int = 1600, max_bytes: int = 2 * 1024 * 1024) -> str:
    """Downscales/re-encodes raw image bytes into a "data:image/jpeg;base64,..." URI sized
    like the web app's own client-side compression for diary photos (fileToJournalImageDataUri
    in ChatPage.jsx: max ~1600px, JPEG, under ~2MB) - used for photos attached to a diary
    entry from Telegram, which arrive as full-resolution originals with no client-side
    compression of their own."""
    import base64 as _b64
    jpeg_bytes = _downscale_image_bytes(contents, max_dim=max_dim, max_bytes=max_bytes)
    return "data:image/jpeg;base64," + _b64.b64encode(jpeg_bytes).decode("ascii")


def _strip_attachment_lines(text: str) -> str:
    return "\n".join(l for l in (text or "").splitlines() if not l.strip().startswith("📎")).strip()


async def _link_user_context_to_docs(user_id: str, doc_ids: List[str], context: str):
    """What the user wrote together with a file ("salva le spese come spese gatto") is
    written INTO that file's knowledge-base text, so the receipt's amounts and the user's own
    words for it are found together - saved apart, "spese del gatto" matched only a note
    with no amounts and the receipt had no "gatto" in it."""
    context = " ".join((context or "").split())[:500]
    if not context or not doc_ids:
        return
    chunks = await db.kb_chunks.find({"user_id": user_id, "doc_id": {"$in": list(doc_ids)}}, {"_id": 0, "embedding": 0}).to_list(500)
    if not chunks:
        return
    texts = []
    for c in chunks:
        raw = c.get("raw_text") or c.get("text") or ""
        texts.append(f"Nota dell'utente: {context}\n\n{raw}")
    try:
        embeddings = await emb.embed_texts(texts)
    except Exception:
        logger.exception("re-embedding of linked attachment failed")
        embeddings = [None] * len(texts)
    for c, t, e in zip(chunks, texts, embeddings):
        await db.kb_chunks.update_one({"chunk_id": c["chunk_id"]}, {"$set": {
            "text": t, "raw_text": c.get("raw_text") or c.get("text") or "", "user_context": context, "embedding": e,
        }})
    await db.kb_documents.update_many({"user_id": user_id, "doc_id": {"$in": list(doc_ids)}}, {"$set": {"user_context": context}})


async def _conv_attachment_ids(user_id: str, conv: Optional[dict], prior_messages: List[dict]) -> List[str]:
    """The knowledge-base documents attached earlier in this conversation, so a follow-up
    ("@task aggiungi per domani le cose da fare nel file") can read them. Conversations
    saved before attachment_doc_ids was stored: the files named on the "📎 nome" lines."""
    ids = [d for d in ((conv or {}).get("attachment_doc_ids") or []) if isinstance(d, str)]
    if ids:
        return ids[-10:]
    import re as _re
    names = []
    for m in prior_messages or []:
        if m.get("role") != "user":
            continue
        for line in (m.get("content") or "").splitlines():
            line = line.strip()
            if line.startswith("📎"):
                name = _re.sub(r"\s*\(https?://[^)]*\)$", "", line.lstrip("📎").split(" · ")[0]).strip()
                if name:
                    names.append(name)
    if not names:
        return []
    docs = await db.kb_documents.find({"user_id": user_id, "name": {"$in": list(dict.fromkeys(names))}},
                                      {"_id": 0, "doc_id": 1, "name": 1, "created_at": 1}).to_list(50)
    docs.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    pick: dict = {}
    for d in docs:
        pick.setdefault(d["name"], d["doc_id"])
    return list(pick.values())[:10]


async def _attachments_text_for_model(user_id: str, doc_ids: List[str], limit: int = 6000) -> str:
    chunks = await db.kb_chunks.find({"user_id": user_id, "doc_id": {"$in": list(doc_ids)}}, {"_id": 0, "embedding": 0}).to_list(200)
    chunks.sort(key=lambda c: (c.get("doc_id") or "", c.get("chunk_index") or 0))
    out, total = [], 0
    for c in chunks:
        piece = f"[{c.get('source_name') or c.get('title') or 'allegato'}]\n{c.get('raw_text') or c.get('text') or ''}"
        if total + len(piece) > limit:
            break
        out.append(piece)
        total += len(piece)
    return "\n\n".join(out)


async def _ocr_and_save_image_to_kb(
    user_id: str, filename: str, contents: bytes, channel: str = "web", org_id: Optional[str] = None,
    user_context: Optional[str] = None,
) -> dict:
    """Runs OCR on an image and persists the extracted text into the personal KB (kb_chunks +
    kb_documents) - the image-handling half of /kb/upload, factored out so a photo sent on
    Telegram while "salva informazioni" or "task/to-do" is the active action can be saved the
    same way instead of always going to Google Drive (its only previous destination on
    Telegram, regardless of the active action or whether Drive is even connected).
    Raises ValueError if no text could be extracted (mirrors /kb/upload's 422 case)."""
    ext = filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else "jpg"
    try:
        send_bytes = _downscale_image_bytes(contents)
    except Exception:
        logger.exception("image downscale/transcode failed; using original bytes")
        send_bytes = contents
    text = (await _ocr_image_bytes(send_bytes, filename, user_id=user_id, channel=channel) or "").strip()
    if not text:
        raise ValueError("Nessun testo estraibile dall'immagine")

    chunks = _chunk_text(text)
    try:
        embeddings = await emb.embed_texts(chunks)
    except Exception:
        logger.exception("kb image embedding failed")
        embeddings = [None] * len(chunks)
    classification = await _classify_document(text, user_id=user_id, channel=channel)

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for i, (chunk, e) in enumerate(zip(chunks, embeddings)):
        docs.append({
            "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "text": chunk,
            "title": filename,
            "tags": [ext, "ocr", classification["category"]],
            "summary": chunks[0][:140] if i == 0 else None,
            "embedding": e,
            "doc_id": doc_id,
            "source_type": "image_ocr",
            "source_name": filename,
            "chunk_index": i,
            "created_at": now,
        })
    if docs:
        await db.kb_chunks.insert_many(docs)

    await db.kb_documents.insert_one({
        "doc_id": doc_id,
        "user_id": user_id,
        "name": filename,
        "ext": ext,
        "source_type": "image_ocr",
        "category": classification["category"],
        "keywords": classification["keywords"],
        "chunks_count": len(docs),
        "chars": len(text),
        "size_bytes": len(contents),
        "preview": text[:280],
        "drive_link": None,
        "created_at": now,
    })

    if user_context:
        await _link_user_context_to_docs(user_id, [doc_id], user_context)
    ut.fire_and_forget_feature_event(user_id=user_id, feature="caricamento_informazioni", channel=channel, trigger="utente", org_id=org_id)
    return {
        "doc_id": doc_id, "name": filename, "size": len(contents), "chunks": len(docs), "chars": len(text),
        "preview": text[:280], "source_type": "image_ocr", "category": classification["category"],
        "keywords": classification["keywords"],
    }


async def _save_journal_entry(
    user_id: str, target_date: str, raw_text: str, cleaned_text: str, meta: Optional[dict], conv_id: str,
    images: Optional[List[str]] = None, documents: Optional[List[dict]] = None,
) -> dict:
    """Creates a new entry for `target_date`, or appends to the one already there. The user
    may write about a specific day (e.g. "ieri") across more than one message/conversation,
    and each should land on that SAME day's page rather than creating a second one for it -
    "aggiunto il testo o creata se non esiste la pagina di quella giornata"."""
    existing = await db.journal_entries.find_one({"user_id": user_id, "date": target_date}, {"_id": 0})
    if existing:
        fields = {
            "raw_text": f"{existing.get('raw_text', '')}\n\n{raw_text}".strip(),
            "cleaned_text": f"{existing.get('cleaned_text', '')}\n\n{cleaned_text}".strip(),
            "tags": list(dict.fromkeys((existing.get("tags") or []) + ((meta or {}).get("tags") or []))),
            "highlights": ((existing.get("highlights") or []) + ((meta or {}).get("highlights") or []))[:6],
            "images": ((existing.get("images") or []) + (images or []))[:5],
            "documents": (existing.get("documents") or []) + (documents or []),
        }
        await db.journal_entries.update_one({"id": existing["id"]}, {"$set": fields})
        existing.update(fields)
        return existing
    jr = {
        "id": f"jr_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "date": target_date,
        "raw_text": raw_text,
        "cleaned_text": cleaned_text,
        "title": (meta or {}).get("title", ""),
        "mood": (meta or {}).get("mood", ""),
        "tags": (meta or {}).get("tags", []),
        "highlights": (meta or {}).get("highlights", []),
        "images": (images or [])[:5],
        "documents": documents or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_conv": conv_id,
    }
    await db.journal_entries.insert_one(jr)
    return jr


# ---- what a task_todo chat turn really saved ----
# The answer is written by the model BEFORE anything is saved, so it used to say "fatto" also
# when nothing was saved (no META), when the to-do became a TASK (the model put a date: it
# went to the Task section), or when "ricrealo" just updated the one already there. Now the
# app decides from what the user asked, saves, and appends a line saying what and where.
_TODO_WORD = re.compile(r"\bto[\s-]?do\b|\bcos[ae] da fare\b", re.I)
_TASK_WORD = re.compile(r"\btask\b|\bpromemoria\b|\bappuntament", re.I)
_CREATE_ASK = re.compile(r"\b(crea\w*|ricrea\w*|aggiung\w*|rifa\w*|mett\w*|segna\w*|inserisc\w*|salva\w*|ricordami)\b", re.I)
_SAME_ONE = re.compile(r"\b(ricrea\w*|rifallo|rifalla|di nuovo|crealo|creala|non (lo|la) vedo|non c'[eè]|dov'[eè])\b", re.I)
_CLAIM = re.compile(r"\b(ho (creato|aggiunto|salvato|ricreato|inserito|registrato|preso nota|segnato)|(è|e') stat[oa] (creat|aggiunt|salvat)\w*|fatto|creato)\b", re.I)


# "aggiungi le seguenti note: 1) ... 2) ...", "aggiungi quest'altra nota: 3) ...": the text goes
# INTO the to-do/task's notes, added to the ones already there (it used to be only "said")
_NOTE_VERB = r"(aggiungi|aggiungici|aggiungimi|scrivi|scrivici|metti|mettici|inserisci|annota|annotati|segna|segnati)"
_NOTE_ASK = re.compile(r"^\s*(per favore,?\s*)?" + _NOTE_VERB + r"\b[^\n:]{0,60}\bnot[ae]\b|\bnot[ae]\s*:", re.I)
_NOTE_LEAD = re.compile(
    r"^\s*(per favore,?\s*)?" + _NOTE_VERB + r"\s+(anche\s+)?"
    r"((le|la|questa|queste|quest['’]altra|queste altre|un['’]altra|una|delle|alcune|altre|nelle|nella|alle|alla|tra le|fra le)\s+)?"
    r"(seguent[ei]\s+)?not[ae]\b(?:\s*:|[^:\n]*:)?\s*(che\s+)?",
    re.I)


def _note_text(typed: str) -> tuple:
    """(what names the target - the words before the note -, the note itself)."""
    t = (typed or "").strip()
    m = _NOTE_LEAD.match(t)
    if m:
        return t[:m.end()], t[m.end():].strip()
    if ":" in t[:120]:
        head, body = t.split(":", 1)
        return head, body.strip()
    return "", t


def _merge_notes(old: str, new: str) -> str:
    old, new = (old or "").strip(), (new or "").strip()
    if not new or new in old:
        return old
    return f"{old}\n{new}" if old else new


def _wanted_kind(text: str) -> Optional[str]:
    todo, task = bool(_TODO_WORD.search(text or "")), bool(_TASK_WORD.search(text or ""))
    return "todo" if todo and not task else "task" if task and not todo else None


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9àèéìòù]+", " ", (t or "").lower()).strip()


async def _extract_task_meta(text: str, user_id: str, channel: str = "web") -> Optional[dict]:
    """The model answered without saying what to save: read it straight from the request."""
    system = (
        f"Oggi è {_today_it_string()}. Estrai dal messaggio il task o to-do da salvare. Rispondi SOLO con JSON: "
        '{"title": "titolo breve, es. le parole tra virgolette se ci sono", "due_date": "YYYY-MM-DD o null", '
        '"due_time": "HH:MM o null", "priority": "alta|media|bassa"}. Se il messaggio non chiede di salvare nulla: {"title": null}.'
    )
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"taskx_{uuid.uuid4().hex[:8]}", system_message=system,
                       user_id=user_id, feature="creazione_task", channel=channel, trigger="utente").with_model("openai", "gpt-4o-mini")
        raw = (await chat.send_message(UserMessage(text=text))).strip()
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        logger.exception("task meta extraction failed")
        return None
    if not str(data.get("title") or "").strip():
        return None
    return {k: v for k, v in data.items() if v not in (None, "", "null")}


def _saved_line(doc: dict, verb: str = "Salvato") -> str:
    if doc["id"].startswith("task_"):
        when = _short_it_date(doc.get("due_date"), doc.get("due_time"))
        return f"📌 {verb} nei Task: «{doc.get('title')}»" + (f" · {when}" if when else "") + " (sezione Task)."
    return f"✅ {verb} nei To-Do: «{doc.get('title')}» (sezione To-Do)."


async def _apply_task_todo_turn(user_id: str, typed: str, meta: Optional[dict], conv_id: str, visible: str,
                                channel: str = "web", **opts) -> str:
    """Saves what this task_todo turn asks for and returns the line saying what was saved
    and where (or that nothing was)."""
    wanted = _wanted_kind(typed)

    def shaped(m: dict) -> dict:
        m = dict(m)
        if wanted == "todo":   # "crea un to-do ...": a to-do even if the model put a date on it
            for k in ("due_date", "due_time", "recurrence", "duration_minutes", "reminder_minutes_before"):
                m.pop(k, None)
        return m

    if _NOTE_ASK.search(typed or ""):
        head, note = _note_text(typed)
        target = None
        existing = await _find_created_in_conv(conv_id)
        if existing:
            target = existing
        else:   # in another chat: the to-do/task the request names ("aggiungi alla nota del to-do modifiche maipal: ...")
            todos = await db.todos.find({"user_id": user_id, "status": {"$ne": "fatto"}}, {"_id": 0, "id": 1, "title": 1, "notes": 1}).to_list(300)
            tasks = await db.tasks.find({"user_id": user_id, "completed": {"$ne": True}}, {"_id": 0, "id": 1, "title": 1, "notes": 1, "due_date": 1, "due_time": 1}).to_list(300)
            ids = lu.match_candidates(head, [(d["id"], d.get("title") or "") for d in todos + tasks]) if head.strip() else []
            if len(ids) == 1:
                d = next(x for x in todos + tasks if x["id"] == ids[0])
                target = ("task" if d["id"].startswith("task_") else "todo", d)
            elif not ids:
                return "⚠️ A quale to-do o task aggiungo la nota? Scrivimi il titolo, es. «aggiungi al to-do modifiche maipal la nota: ...»."
            else:
                return "⚠️ Più to-do o task corrispondono: scrivimi il titolo esatto a cui aggiungere la nota."
        if not note:
            return "⚠️ Non ho trovato il testo della nota: scrivilo dopo i due punti, es. «aggiungi la nota: ...»."
        kind, doc = target
        coll = db.tasks if kind == "task" else db.todos
        fresh = await coll.find_one({"id": doc["id"]}, {"_id": 0}) or doc
        merged = _merge_notes(fresh.get("notes"), note)
        await coll.update_one({"id": doc["id"]}, {"$set": {"notes": merged, "embedding": None}})
        where = "To-Do" if kind == "todo" else "Task"
        return f"📝 Nota aggiunta a «{fresh.get('title')}» (sezione {where}). Ora le note sono:\n{merged}"

    bulk = meta.get("tasks") if meta and isinstance(meta.get("tasks"), list) else None
    if bulk:
        made = []
        for item in bulk:
            if isinstance(item, dict) and item.get("title"):
                try:
                    made.append(await _create_task_or_todo(user_id, shaped(item), conv_id, **opts))
                except Exception:
                    logger.exception(f"bulk task creation failed for item={item!r}")
        if not made:
            return "⚠️ Non sono riuscito a salvare nulla: riprova."
        return "\n".join(_saved_line(d) for d in made[:12]) + (f"\n… e altri {len(made) - 12}." if len(made) > 12 else "")

    if not meta and (_SAME_ONE.search(typed or "") or _CLAIM.search(visible or "")):
        # "non lo vedo", "ricrealo": the one saved in this chat is there - say where
        existing = await _find_created_in_conv(conv_id)
        if existing:
            kind, old = existing
            if wanted and wanted != kind:
                await (db.tasks if kind == "task" else db.todos).delete_one({"id": old["id"], "user_id": user_id})
                return _saved_line(await _create_task_or_todo(user_id, shaped({"title": old.get("title"), "notes": old.get("notes", "")}), conv_id, **opts), "Spostato")
            return _saved_line(old, "È salvato")
    if not meta and _CREATE_ASK.search(typed or "") and (wanted or _CLAIM.search(visible or "")):
        meta = await _extract_task_meta(typed, user_id, channel)
    if not meta or not (meta.get("title") or "").strip():
        if _CLAIM.search(visible or "") and _CREATE_ASK.search(typed or ""):
            return "⚠️ In realtà non ho salvato niente: riscrivimi cosa salvare, es. «crea il to-do modifiche progetto»."
        return ""
    meta = shaped(meta)
    if wanted == "task" and not meta.get("due_date"):
        pass   # no date: it can only be a to-do - the line below says so

    existing = await _find_created_in_conv(conv_id)
    if existing:
        kind, old = existing
        same = (not meta.get("title")) or _norm_title(meta["title"]) == _norm_title(old.get("title")) or bool(_SAME_ONE.search(typed or ""))
        if not same and _CREATE_ASK.search(typed or ""):
            doc = await _create_task_or_todo(user_id, meta, conv_id, **opts)   # another one, in the same chat
            return _saved_line(doc)
        if wanted and wanted != kind:   # it was saved as the other kind: move it
            await (db.tasks if kind == "task" else db.todos).delete_one({"id": old["id"], "user_id": user_id})
            doc = await _create_task_or_todo(user_id, {**{"title": old.get("title")}, **meta}, conv_id, **opts)
            return _saved_line(doc, "Spostato")
        await _update_task_or_todo_from_meta(kind, old["id"], meta)
        doc = await (db.tasks if kind == "task" else db.todos).find_one({"id": old["id"]}, {"_id": 0}) or old
        return _saved_line(doc, "È salvato" if _SAME_ONE.search(typed or "") else "Aggiornato")
    doc = await _create_task_or_todo(user_id, meta, conv_id, **opts)
    line = _saved_line(doc)
    if wanted == "task" and doc["id"].startswith("todo_"):
        line += " Senza una data non può essere un task: se vuoi, dimmi per quando."
    return line


async def _find_created_in_conv(conv_id: str) -> Optional[tuple]:
    """Whatever task/todo has already been created within this chat thread, if any - so a
    follow-up "task_todo" turn updates it in place instead of creating a duplicate, or
    (the bug this fixes) instead of being silently dropped just because it isn't the first
    message of the thread."""
    t = await db.tasks.find_one({"source_conv": conv_id}, {"_id": 0})
    if t:
        return ("task", t)
    td = await db.todos.find_one({"source_conv": conv_id}, {"_id": 0})
    if td:
        return ("todo", td)
    return None


async def _update_task_or_todo_from_meta(kind: str, doc_id: str, meta: dict):
    """Applies a follow-up task_todo turn's META as an update to the task/todo already
    created in this thread - same field set _create_task_or_todo uses, minus the fields
    that only make sense at creation time (calendar_synced, reminder_sent, etc.)."""
    fields: dict = {}
    if meta.get("title"): fields["title"] = meta["title"]
    if meta.get("description"): fields["description"] = meta["description"]
    if meta.get("notes"):
        coll = db.tasks if kind == "task" else db.todos
        old = (await coll.find_one({"id": doc_id}, {"_id": 0, "notes": 1}) or {}).get("notes")
        fields["notes"] = _merge_notes(old, meta["notes"])   # added to the notes already there, never swapped
    if meta.get("priority"): fields["priority"] = meta["priority"]
    if meta.get("tags"): fields["tags"] = meta["tags"]
    if kind == "task":
        if meta.get("due_date"): fields["due_date"] = meta["due_date"]
        if meta.get("due_time"): fields["due_time"] = meta["due_time"]
        try:
            if meta.get("duration_minutes"): fields["duration_minutes"] = int(meta["duration_minutes"])
        except (TypeError, ValueError):
            pass
        try:
            if meta.get("reminder_minutes_before"):
                fields["reminder_offset_minutes"] = int(meta["reminder_minutes_before"])
                fields["reminder_enabled"] = True
        except (TypeError, ValueError):
            pass
    if fields:
        _clear_cached_embedding(fields, {"title", "description", "notes"})
        coll = db.tasks if kind == "task" else db.todos
        await coll.update_one({"id": doc_id}, {"$set": fields})
    if kind == "task" and isinstance(meta.get("recurrence"), dict):
        task = await db.tasks.find_one({"id": doc_id}, {"_id": 0})
        if task and task.get("due_date"):
            try:
                await _set_task_recurrence(task, meta["recurrence"], task["user_id"])
            except Exception:
                logger.exception("recurrence update from follow-up failed")


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
    convs = await cursor.to_list(200)
    # Conversations saved before topics existed get theirs in the background (visible on the
    # next load) - never slowing this listing down.
    missing = [c["conv_id"] for c in convs if not c.get("topic")][:40]
    if missing:
        asyncio.create_task(_ensure_conv_topics(current.user_id, missing))
    return convs


def _first_user_text(conv: dict) -> str:
    for m in conv.get("messages") or []:
        if m.get("role") == "user" and m.get("content"):
            return m["content"]
    return conv.get("user_message") or ""


_topics_running: set = set()


async def _ensure_conv_topics(user_id: str, conv_ids: List[str]):
    """One word per conversation ("Pilates", "Vacanza", "Fatture"...) for the history cards -
    one cheap batched call for all the conversations still without it."""
    if user_id in _topics_running:
        return
    _topics_running.add(user_id)
    try:
        convs = await db.conversations.find({"user_id": user_id, "conv_id": {"$in": conv_ids}, "topic": {"$exists": False}},
                                            {"_id": 0, "conv_id": 1, "title": 1, "messages": 1, "user_message": 1}).to_list(len(conv_ids))
        if not convs:
            return
        items = [{"id": c["conv_id"], "titolo": c.get("title") or "", "messaggio": _first_user_text(c)[:300]} for c in convs]
        system = (
            "Per ogni conversazione scegli UNA sola parola italiana (al massimo due se indispensabile, es. 'Codici casa') "
            "che dica di cosa parla, come un'etichetta: es. Vacanza, Pilates, Fatture, Sport, Design, Lavoro, Salute, "
            "Famiglia, Spesa, Wifi. Iniziale maiuscola, niente punteggiatura. "
            "Rispondi SOLO con JSON: {\"topics\": {\"<id>\": \"Parola\", ...}}"
        )
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"topics_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=user_id, feature="altro", channel="sistema", trigger="automatico",
        ).with_model("openai", "gpt-4o-mini")
        import json as _json, re as _re
        raw = await chat.send_message(UserMessage(text=_json.dumps(items, ensure_ascii=False)))
        m = _re.search(r"\{.*\}", raw or "", _re.DOTALL)
        topics = (_json.loads(m.group(0)).get("topics") or {}) if m else {}
        for c in convs:
            word = str(topics.get(c["conv_id"]) or "").strip().strip(".,;:!\"'")[:24]
            if word:
                await db.conversations.update_one({"conv_id": c["conv_id"]}, {"$set": {"topic": word[:1].upper() + word[1:]}})
    except Exception:
        logger.exception("conversation topics generation failed")
    finally:
        _topics_running.discard(user_id)


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


# ============ CLOUD: FILE (Google Drive / OneDrive) E CALENDARIO (Google / Outlook) ============
# Each user picks where files are saved (Google Drive, OneDrive or both) and which calendar
# tasks are synced to (Google, Outlook or both) - users.storage_targets / calendar_targets.
# Not set = every connected service. Saving goes to all chosen targets; one failing doesn't
# stop the others.
STORAGE_LABELS = {"google": "Google Drive", "onedrive": "OneDrive"}
CALENDAR_LABELS = {"google": "Google Calendar", "outlook": "Calendario di Outlook"}


async def _connected_providers(user_id: str) -> set:
    docs = await db.integrations.find({"user_id": user_id, "provider": {"$in": ["google", "microsoft"]}}, {"_id": 0, "provider": 1}).to_list(5)
    return {d["provider"] for d in docs}


async def _storage_user(user_id: str) -> str:
    """Whose archive (Drive / OneDrive) a user's files go to: an organization's users don't
    connect their own - their files go to its administrator's, under the client, the commessa or
    the folder they belong to (the subscriber's first, else another administrator with one)."""
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "role": 1, "tenant_id": 1}) or {}
    if u.get("role") == "admin" or not u.get("tenant_id"):
        return user_id
    t = await db.tenants.find_one({"id": u["tenant_id"]}, {"_id": 0, "owner_user_id": 1}) or {}
    admins = [a["user_id"] for a in await db.users.find({"tenant_id": u["tenant_id"], "role": "admin"}, {"_id": 0, "user_id": 1}).to_list(50)]
    admins.sort(key=lambda a: a != t.get("owner_user_id"))
    for a in admins:
        if await _connected_providers(a):
            return a
    return admins[0] if admins else user_id


async def _storage_owner_view(current: User) -> Optional[dict]:
    """For a user of an organization: whose archive their files go to (None for an administrator)."""
    uid = await _storage_user(current.user_id)
    if uid == current.user_id:
        return None
    u = await db.users.find_one({"user_id": uid}, {"_id": 0, "name": 1}) or {}
    return {"name": u.get("name") or "l'amministratore", "targets": await _storage_targets(current.user_id)}


async def _storage_targets(user_id: str) -> List[str]:
    user_id = await _storage_user(user_id)
    conn = await _connected_providers(user_id)
    available = [t for t, p in (("google", "google"), ("onedrive", "microsoft")) if p in conn]
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "storage_targets": 1}) or {}
    chosen = u.get("storage_targets")
    return available if chosen is None else [t for t in available if t in chosen]


async def _calendar_targets(user_id: str) -> List[str]:
    conn = await _connected_providers(user_id)
    available = [t for t, p in (("google", "google"), ("outlook", "microsoft")) if p in conn]
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "calendar_targets": 1}) or {}
    chosen = u.get("calendar_targets")
    return available if chosen is None else [t for t in available if t in chosen]


NO_STORAGE_MSG = "Nessun archivio collegato: collega Google Drive o OneDrive in Impostazioni."
NO_CALENDAR_MSG = "Nessun calendario collegato: collega Google Calendar o il Calendario di Outlook in Impostazioni."


async def _storage_folder_names(user_id: str) -> List[str]:
    user_id = await _storage_user(user_id)
    names = []
    for t in await _storage_targets(user_id):
        try:
            if t == "google":
                creds = await gi.get_credentials(db, user_id)
                names += [f["name"] for f in await gi.list_subfolders(db, user_id, creds)] if creds else []
            else:
                token = await ms.get_token(db, user_id)
                names += [f["name"] for f in await ms.list_folders(db, user_id, token)] if token else []
        except Exception:
            logger.exception(f"listing {t} folders failed")
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def _drive_safe(name: str) -> str:
    """A folder name both Drive and OneDrive accept (OneDrive refuses \\ / : * ? " < > |)."""
    return " ".join(re.sub(r'[\\/:*?"<>|]+', " ", str(name or "")).split()).strip(" .")[:120] or "Senza nome"


async def _storage_save(user_id: str, folder_name: Optional[str], tmp_path: str, filename: str, content_type: Optional[str],
                        only: Optional[List[str]] = None, subfolders: Optional[List[str]] = None) -> dict:
    """Saves a file into <mAIPAL>/<folder_name> (or the mAIPAL folder itself) on every chosen
    storage - or only on `only` (the cloud icons picked for this message in the mobile chat),
    always limited to the connected ones. `subfolders` nests further inside folder_name
    (e.g. Clienti / Rossi Mario / Bagno), each level found or created.
    -> {"saved": [...], "links": {target: url}, "web_view_link": first url, "errors": {...}}"""
    user_id = await _storage_user(user_id)   # (a user's: the organization administrator's archive)
    targets = await _storage_targets(user_id)
    if only is not None:
        conn = await _connected_providers(user_id)
        targets = [t for t, p in (("google", "google"), ("onedrive", "microsoft")) if p in conn and t in only]
    if not targets:
        raise HTTPException(status_code=400, detail=NO_STORAGE_MSG)
    out = {"saved": [], "links": {}, "errors": {}, "web_view_link": None, "file_id": None, "name": filename}
    for t in targets:
        try:
            if t == "google":
                creds = await gi.get_credentials(db, user_id)
                folder_id = (await gi.find_or_create_subfolder(db, user_id, creds, folder_name)) if folder_name else await gi.ensure_maipal_folder(db, user_id, creds)
                for sub in subfolders or []:
                    folder_id = await asyncio.to_thread(gi.find_or_create_subfolder_sync, creds, folder_id, _drive_safe(sub))
                res = gi.upload_file_to_folder(creds, folder_id, tmp_path, filename, content_type)
            else:
                token = await ms.get_token(db, user_id)
                folder_id = await ms.find_or_create_folder(db, user_id, token, folder_name)
                for sub in subfolders or []:
                    folder_id = await ms.find_or_create_child_folder(token, folder_id, _drive_safe(sub))
                res = await ms.upload_file(token, folder_id, tmp_path, filename, content_type)
            out["saved"].append(t)
            out["links"][t] = res.get("web_view_link")
            out["web_view_link"] = out["web_view_link"] or res.get("web_view_link")
            out["file_id"] = out["file_id"] or res.get("file_id")
        except Exception as e:
            logger.exception(f"saving to {t} failed")
            out["errors"][t] = str(e)[:200]
    if not out["saved"]:
        raise HTTPException(status_code=500, detail="Salvataggio non riuscito: " + "; ".join(f"{STORAGE_LABELS[k]}: {v}" for k, v in out["errors"].items()))
    return out


def _saved_where(res: dict) -> str:
    return " e ".join(STORAGE_LABELS[t] for t in res.get("saved", []))


def _events_of(doc: dict) -> dict:
    """{"google": id, "outlook": id} - older tasks only have calendar_event_id (Google)."""
    ev = dict(doc.get("calendar_events") or {})
    if doc.get("calendar_event_id") and "google" not in ev:
        ev["google"] = doc["calendar_event_id"]
    return {k: v for k, v in ev.items() if v}


async def _calendar_create(user_id: str, title: str, description: str, due_date: Optional[str], due_time: Optional[str],
                           duration_minutes: Optional[int], rule: Optional[dict] = None) -> dict:
    """One event (recurring when `rule` is given) on every chosen calendar -> {target: event id}."""
    targets = await _calendar_targets(user_id)
    if not targets:
        raise HTTPException(status_code=400, detail=NO_CALENDAR_MSG)
    from datetime import date as _date
    start = _date.fromisoformat(due_date) if (rule and due_date) else None
    events, errors = {}, {}
    for t in targets:
        try:
            if t == "google":
                creds = await gi.get_credentials(db, user_id)
                events[t] = await gi.create_calendar_event(creds, title=title, description=description, due_date=due_date,
                                                          due_time=due_time, duration_minutes=duration_minutes,
                                                          recurrence=rec.to_rrule(rule, start) if rule else None)
            else:
                token = await ms.get_token(db, user_id)
                events[t] = await ms.create_event(token, title=title, description=description, due_date=due_date,
                                                  due_time=due_time, duration_minutes=duration_minutes,
                                                  recurrence=rec.to_graph_recurrence(rule, start) if rule else None)
        except Exception as e:
            logger.exception(f"calendar event on {t} failed")
            errors[t] = str(e)[:200]
    if not events:
        raise HTTPException(status_code=500, detail="Sync calendar fallita: " + "; ".join(f"{CALENDAR_LABELS[k]}: {v}" for k, v in errors.items()))
    return events


async def _calendar_delete(user_id: str, events: dict):
    for t, eid in (events or {}).items():
        try:
            if t == "google":
                creds = await gi.get_credentials(db, user_id)
                if creds:
                    await gi.delete_calendar_event(creds, eid)
            elif t == "outlook":
                token = await ms.get_token(db, user_id)
                if token:
                    await ms.delete_event(token, eid)
        except Exception:
            logger.exception(f"calendar delete on {t} failed")


class CloudPreferencesPayload(BaseModel):
    storage_targets: Optional[List[Literal["google", "onedrive"]]] = None
    calendar_targets: Optional[List[Literal["google", "outlook"]]] = None


@api_router.put("/integrations/preferences")
async def set_cloud_preferences(payload: CloudPreferencesPayload, current: User = Depends(get_current_user)):
    upd = {}
    if payload.storage_targets is not None:
        upd["storage_targets"] = list(dict.fromkeys(payload.storage_targets))
    if payload.calendar_targets is not None:
        upd["calendar_targets"] = list(dict.fromkeys(payload.calendar_targets))
    if upd:
        await db.users.update_one({"user_id": current.user_id}, {"$set": upd})
    return {"storage_targets": await _storage_targets(current.user_id), "calendar_targets": await _calendar_targets(current.user_id)}


@api_router.get("/integrations/microsoft/authorize")
async def microsoft_authorize(current: User = Depends(get_current_user)):
    if not ms.is_configured():
        raise HTTPException(status_code=400, detail="Microsoft non è ancora configurato sul server (MS_CLIENT_ID / MS_CLIENT_SECRET nel file .env).")
    state = secrets.token_urlsafe(24)
    await db.ms_oauth_states.insert_one({"state": state, "user_id": current.user_id, "created_at": datetime.now(timezone.utc).isoformat()})
    return {"url": ms.authorization_url(state)}


@api_router.get("/integrations/microsoft/callback")
async def microsoft_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    base = os.environ["APP_BASE_URL"]
    st = await db.ms_oauth_states.find_one({"state": state}, {"_id": 0}) if state else None
    if not st or error or not code:
        return RedirectResponse(f"{base}/dashboard/settings?microsoft=error")
    await db.ms_oauth_states.delete_one({"state": state})
    try:
        tok = await ms.exchange_code(code)
        email = await ms.get_account_email(tok["access_token"])
    except Exception:
        logger.exception("microsoft oauth exchange failed")
        return RedirectResponse(f"{base}/dashboard/settings?microsoft=error")
    await db.integrations.update_one(
        {"user_id": st["user_id"], "provider": "microsoft"},
        {"$set": {**tok, "provider": "microsoft", "user_id": st["user_id"], "email": email,
                  "connected_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return RedirectResponse(f"{base}/dashboard/settings?microsoft=ok")


@api_router.post("/integrations/microsoft/disconnect")
async def microsoft_disconnect(current: User = Depends(get_current_user)):
    await db.integrations.delete_one({"user_id": current.user_id, "provider": "microsoft"})
    return {"ok": True}


async def _cleanup_old_conversations() -> int:
    """Deletes non-favorite conversations whose last message is older than
    cr.RETENTION_DAYS (see conversation_retention.py). Only the chat goes: whatever it
    created (notes, tasks, diary, lists) is stored elsewhere and stays."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=cr.RETENTION_DAYS)).isoformat()
    candidates = await db.conversations.find(
        {"favorite": {"$ne": True}, "created_at": {"$lt": cutoff}},
        {"_id": 0, "conv_id": 1, "favorite": 1, "created_at": 1, "completed_at": 1, "messages.ts": 1},
    ).to_list(5000)
    expired = [c["conv_id"] for c in candidates if cr.is_expired(c, now)]
    if expired:
        await db.conversations.delete_many({"conv_id": {"$in": expired}, "favorite": {"$ne": True}})
        logger.info(f"[cleanup] deleted {len(expired)} old non-favorite conversations")
    return len(expired)


async def _conversation_cleanup_loop():
    """Every 6 hours (and shortly after start-up, so a PC that was off catches up)."""
    await asyncio.sleep(60)
    while True:
        try:
            await _cleanup_old_conversations()
        except Exception:
            logger.exception("conversation cleanup failed")
        await asyncio.sleep(6 * 3600)


# ============ TASKS ============
@api_router.get("/tasks")
async def list_tasks(current: User = Depends(get_current_user)):
    cursor = db.tasks.find(_visible_query(current), {"_id": 0, "embedding": 0}).sort("created_at", -1)   # the search's vectors stay on the server
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
            await _require_share_allowed(current)
            payload["org_id"] = current.org_id
        else:
            payload["visibility"] = "private"
            payload["org_id"] = None
    existing = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    apply_to = payload.pop("apply_to", None)

    # Occurrence of a recurring task: Calendar holds the whole series as ONE recurring event
    series = await db.task_series.find_one({"id": existing["series_id"]}, {"_id": 0}) if existing.get("series_id") else None
    if series and "calendar_synced" in payload:
        want = bool(payload.pop("calendar_synced"))
        if want != bool(series.get("calendar_synced")):
            try:
                await _sync_series_calendar(series, want)
            except HTTPException:
                raise
            except Exception as e:
                logger.exception("series calendar sync failed")
                raise HTTPException(status_code=500, detail=f"Sync calendar fallita: {e}")

    # Handle calendar_synced toggle
    if "calendar_synced" in payload and payload["calendar_synced"] != existing.get("calendar_synced"):
        try:
            if payload["calendar_synced"]:
                events = await _calendar_create(
                    current.user_id, title=existing.get("title", "Task mAIPAL"), description=existing.get("description", "") or "",
                    due_date=existing.get("due_date"), due_time=existing.get("due_time"),
                    duration_minutes=existing.get("duration_minutes"),
                )
                payload["calendar_events"] = events
                payload["calendar_event_id"] = events.get("google")
            else:
                await _calendar_delete(current.user_id, _events_of(existing))
                payload["calendar_events"] = {}
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
    if payload:
        await db.tasks.update_one({"id": task_id, **_editable_query(current)}, {"$set": payload})
    if apply_to == "series" and series:
        await _apply_template_to_series(series["id"], payload)
    doc = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    return doc


@api_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, scope: str = "one", current: User = Depends(get_current_user)):
    """scope="following" on an occurrence of a recurring task: removes it and every
    not-yet-done occurrence after it, and stops the series there."""
    existing = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    if scope == "following" and existing.get("series_id"):
        await _stop_task_recurrence(existing, include_this=True)
        await db.tasks.delete_one({"id": task_id, **_editable_query(current)})
        return {"ok": True}
    if _events_of(existing):
        await _calendar_delete(current.user_id, _events_of(existing))
    await db.tasks.delete_one({"id": task_id, **_editable_query(current)})
    return {"ok": True}


# ============ TASK RICORRENTI ============
# A recurring task is a series (task_series) + ordinary task occurrences carrying series_id,
# generated rec.WINDOW_DAYS ahead (and topped up by _task_series_loop). Each occurrence can be
# completed, moved or deleted on its own; changing the rule from an occurrence re-anchors the
# series there ("da questo in poi"), past occurrences stay as they are. On Google Calendar a
# series is ONE recurring event (RRULE), not one event per occurrence.
_SERIES_TEMPLATE_FIELDS = ("title", "description", "priority", "tags", "due_time", "duration_minutes",
                           "reminder_enabled", "reminder_offset_minutes", "assigned_to")


class RecurrencePayload(BaseModel):
    rule: Optional[dict] = None  # None = stop repeating from this occurrence on


def _local_today():
    return datetime.now(LOCAL_TZ).date()


def _occurrence_doc(series: dict, d) -> dict:
    return {
        "id": f"task_{uuid.uuid4().hex[:12]}",
        "user_id": series["user_id"],
        "org_id": series.get("org_id"),
        "visibility": series.get("visibility") or "private",
        **{k: series.get(k) for k in _SERIES_TEMPLATE_FIELDS},
        "title": series.get("title") or "Task",
        "tags": series.get("tags") or [],
        "priority": series.get("priority") or "media",
        "notes": "",
        "due_date": d.isoformat(),
        "calendar_synced": bool(series.get("calendar_synced")),
        # the generic "domani hai in scadenza" digest would fire for every occurrence of a
        # routine; the per-task reminder (reminder_enabled) still works as for any task
        "reminder_sent": True,
        "reminder_enabled": bool(series.get("reminder_enabled")),
        "reminder_msg_sent": False,
        "series_id": series["id"],
        "recurrence_label": series.get("label"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_conv": series.get("source_conv"),
    }


async def _extend_series(series: dict, today=None) -> int:
    """Creates the missing occurrences up to today + WINDOW_DAYS."""
    if not series.get("active", True):
        return 0
    from datetime import date as _date
    today = today or _local_today()
    start = _date.fromisoformat(series["start_date"])
    horizon = today + timedelta(days=rec.WINDOW_DAYS)
    gen_until = _date.fromisoformat(series["generated_until"]) if series.get("generated_until") else start - timedelta(days=1)
    upd = {}
    created = 0
    if gen_until < horizon:
        dates = rec.occurrences(series["rule"], start, gen_until + timedelta(days=1), horizon)
        docs = [_occurrence_doc(series, d) for d in dates]
        if docs:
            await db.tasks.insert_many(docs)
            created = len(docs)
        upd["generated_until"] = horizon.isoformat()
        if rec.is_finished(series["rule"], start, horizon):
            upd["active"] = False
    if upd:
        await db.task_series.update_one({"id": series["id"]}, {"$set": upd})
        series.update(upd)
    return created


async def _sync_series_calendar(series: dict, on: bool, creds=None):
    """(Re)creates or removes the single recurring event of a series on every chosen
    calendar (Google and/or Outlook) and flags its occurrences accordingly."""
    owner = series["user_id"]
    if on and not await _calendar_targets(owner):
        raise HTTPException(status_code=400, detail=NO_CALENDAR_MSG)
    await _calendar_delete(owner, _events_of(series))
    # occurrences synced one by one before becoming a series: drop those single events
    async for t in db.tasks.find({"series_id": series["id"], "$or": [{"calendar_event_id": {"$nin": [None, ""]}},
                                                                      {"calendar_events": {"$nin": [None, {}]}}]}, {"_id": 0}):
        await _calendar_delete(owner, _events_of(t))
        await db.tasks.update_one({"id": t["id"]}, {"$set": {"calendar_event_id": None, "calendar_events": {}}})
    events = {}
    if on:
        events = await _calendar_create(
            owner, title=series.get("title") or "Task mAIPAL", description=series.get("description") or "",
            due_date=series["start_date"], due_time=series.get("due_time"),
            duration_minutes=series.get("duration_minutes"), rule=series["rule"],
        )
    upd = {"calendar_synced": on, "calendar_events": events, "calendar_event_id": events.get("google")}
    await db.task_series.update_one({"id": series["id"]}, {"$set": upd})
    series.update(upd)
    await db.tasks.update_many({"series_id": series["id"]}, {"$set": {"calendar_synced": on}})


async def _resync_series_calendar_if_needed(series: dict):
    if series.get("calendar_synced"):
        try:
            await _sync_series_calendar(series, True)
        except Exception:
            logger.exception("series calendar resync failed")


async def _set_task_recurrence(task: dict, raw_rule: dict, user_id: str) -> dict:
    """Makes `task` (and what follows it) repeat by `raw_rule`: a new series anchored on the
    task, or - for an occurrence of an existing series - the series re-anchored there with
    the new rule, replacing the not-yet-done occurrences after it."""
    from datetime import date as _date
    if not task.get("due_date"):
        raise HTTPException(status_code=400, detail="Per farlo ripetere, il task deve avere una data")
    start = _date.fromisoformat(task["due_date"])
    rule = rec.normalize_rule(raw_rule, start)
    if not rule:
        raise HTTPException(status_code=400, detail="Cadenza di ripetizione non valida")
    label = rec.rule_label(rule, start)
    series = await db.task_series.find_one({"id": task.get("series_id")}, {"_id": 0}) if task.get("series_id") else None
    template = {k: task.get(k) for k in _SERIES_TEMPLATE_FIELDS}
    if series:
        await db.tasks.delete_many({"series_id": series["id"], "id": {"$ne": task["id"]},
                                    "due_date": {"$gt": task["due_date"]}, "completed": {"$ne": True}})
        upd = {**template, "rule": rule, "label": label, "start_date": task["due_date"],
               "generated_until": task["due_date"], "active": True}
        await db.task_series.update_one({"id": series["id"]}, {"$set": upd})
        series.update(upd)
    else:
        series = {
            "id": f"series_{uuid.uuid4().hex[:12]}",
            "user_id": task.get("user_id") or user_id,
            "org_id": task.get("org_id"),
            "visibility": task.get("visibility") or "private",
            **template,
            "rule": rule, "label": label,
            "start_date": task["due_date"], "generated_until": task["due_date"],
            "active": True, "calendar_synced": bool(task.get("calendar_synced")), "calendar_event_id": None,
            "source_conv": task.get("source_conv"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.task_series.insert_one(dict(series))
        series.pop("_id", None)
    await db.tasks.update_one({"id": task["id"]}, {"$set": {"series_id": series["id"], "reminder_sent": True}})
    await _extend_series(series)
    await db.tasks.update_many({"series_id": series["id"]}, {"$set": {"recurrence_label": label}})
    await _resync_series_calendar_if_needed(series)
    return series


async def _stop_task_recurrence(task: dict, include_this: bool = False):
    """Stops a series at this occurrence: the not-yet-done occurrences after it (and this
    one too with include_this) are removed; what is left becomes plain tasks."""
    from datetime import date as _date
    series = await db.task_series.find_one({"id": task.get("series_id")}, {"_id": 0}) if task.get("series_id") else None
    if not series:
        return
    cmp = "$gte" if include_this else "$gt"
    await db.tasks.delete_many({"series_id": series["id"], "due_date": {cmp: task["due_date"]}, "completed": {"$ne": True}})
    last = _date.fromisoformat(task["due_date"]) - (timedelta(days=1) if include_this else timedelta(0))
    rule = {**series["rule"], "until": last.isoformat()}
    rule.pop("count", None)
    await db.task_series.update_one({"id": series["id"]}, {"$set": {"active": False, "rule": rule}})
    series.update({"active": False, "rule": rule})
    await db.tasks.update_many({"series_id": series["id"]}, {"$set": {"recurrence_label": None}})
    if series.get("calendar_synced"):
        try:
            remaining = await db.tasks.count_documents({"series_id": series["id"]})
            if remaining and last >= _date.fromisoformat(series["start_date"]):
                await _sync_series_calendar(series, True)
            else:
                await _sync_series_calendar(series, False)
        except Exception:
            logger.exception("series calendar update on stop failed")


async def _apply_template_to_series(series_id: str, fields: dict):
    """A change meant for the whole series: template + every not-yet-done occurrence from today."""
    tmpl = {k: v for k, v in fields.items() if k in _SERIES_TEMPLATE_FIELDS}
    if not tmpl:
        return
    await db.task_series.update_one({"id": series_id}, {"$set": tmpl})
    await db.tasks.update_many({"series_id": series_id, "completed": {"$ne": True}, "due_date": {"$gte": _local_today().isoformat()}},
                               {"$set": tmpl})
    series = await db.task_series.find_one({"id": series_id}, {"_id": 0})
    if series and ({"title", "description", "due_time", "duration_minutes"} & set(tmpl)):
        await _resync_series_calendar_if_needed(series)


@api_router.put("/tasks/{task_id}/recurrence")
async def set_task_recurrence(task_id: str, payload: RecurrencePayload, current: User = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if payload.rule is None:
        await _stop_task_recurrence(task)
    else:
        await _set_task_recurrence(task, payload.rule, current.user_id)
    return await db.tasks.find_one({"id": task_id}, {"_id": 0})


@api_router.get("/tasks/{task_id}/recurrence")
async def get_task_recurrence(task_id: str, current: User = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    series = await db.task_series.find_one({"id": task.get("series_id")}, {"_id": 0}) if task.get("series_id") else None
    if not series or not task.get("recurrence_label"):
        return {"series": None}
    return {"series": {k: series.get(k) for k in ("id", "rule", "label", "start_date", "active", "calendar_synced")}}


async def _task_series_loop():
    """Every 6 hours: tops up every active series to today + WINDOW_DAYS."""
    await asyncio.sleep(30)
    while True:
        try:
            async for s in db.task_series.find({"active": True}, {"_id": 0}):
                try:
                    await _extend_series(s)
                except Exception:
                    logger.exception(f"extending series {s.get('id')} failed")
        except Exception:
            logger.exception("task series loop iteration failed")
        await asyncio.sleep(6 * 3600)


# ============ TODOS ============
@api_router.get("/todos")
async def list_todos(current: User = Depends(get_current_user)):
    cursor = db.todos.find({"user_id": current.user_id}, {"_id": 0, "embedding": 0}).sort("created_at", -1)
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
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()   # the To-Do folders say when they last changed
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
    await _require_share_allowed(current)
    task = await db.tasks.find_one({"id": task_id, **_editable_query(current)}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update = {"assigned_to": payload.assigned_to}
    assignee = None
    if payload.assigned_to:
        assignee = await db.users.find_one({"user_id": payload.assigned_to, **_team_q(current.org_id)}, {"_id": 0})
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
    if current.business_vertical == "artigiano" and not await db.collections.find_one(
            {**_lists_query(current), "system_key": vx.CLIENTI_KEY}, {"_id": 1}):
        await _apply_vertical(current, "artigiano")
        current = User(**(await db.users.find_one({"user_id": current.user_id}, {"_id": 0})))
    cursor = db.collections.find(_lists_query(current), {"_id": 0}).sort("created_at", 1)
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
    # Each user keeps their own order (users.list_order, set by drag-and-drop): a team-mate
    # reordering a shared list never moves it in the owner's page. Lists not in it yet
    # (new or just shared) go at the bottom, in their owner's order.
    me = await db.users.find_one({"user_id": current.user_id}, {"_id": 0, "list_order": 1}) or {}
    pos = {cid: i for i, cid in enumerate(me.get("list_order") or [])}
    collections.sort(key=lambda c: (pos.get(c["id"], len(pos)), c["sort_order"]))
    await _add_sharing_info(collections, current)
    storage_uid = await _storage_user(current.user_id)
    for c in collections:
        await _repair_field_keys(c)
        _public_list_folder(c, storage_uid)
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
    """Persists the drag-and-drop order from the Liste page, for this user only
    (users.list_order); the lists they own also keep it as their sort_order. Silently
    ignores any id the caller can't see or that doesn't exist."""
    visible = await db.collections.find(_lists_query(current), {"_id": 0, "id": 1, "user_id": 1}).to_list(500)
    owner_of = {c["id"]: c.get("user_id") for c in visible}
    ids = [i for i in payload.ordered_ids if i in owner_of]
    if not ids:
        raise HTTPException(status_code=400, detail="Nessuna lista valida da riordinare")
    await db.users.update_one({"user_id": current.user_id}, {"$set": {"list_order": ids}})
    from pymongo import UpdateOne
    ops = [UpdateOne({"id": cid}, {"$set": {"sort_order": idx}}) for idx, cid in enumerate(ids) if owner_of[cid] == current.user_id]
    if ops:
        await db.collections.bulk_write(ops)
    return {"ok": True}


async def _add_sharing_info(colls: list, current: User):
    """Adds to each list: is_owner, owner {user_id, name} and shared_with_users [{user_id, name}]
    (the list's user_id is always whoever created it - sharing never changes the owner)."""
    uids = {c.get("user_id") for c in colls} | {u for c in colls for u in (c.get("shared_with") or [])}
    users = await db.users.find({"user_id": {"$in": [u for u in uids if u]}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(500)
    names = {u["user_id"]: u.get("name") or (u.get("email") or "").split("@")[0] for u in users}
    for c in colls:
        c["is_owner"] = c.get("user_id") == current.user_id
        c["owner"] = {"user_id": c.get("user_id"), "name": names.get(c.get("user_id"), "")}
        c["shared_with_users"] = [{"user_id": u, "name": names.get(u, ""), "perm": (c.get("share_perms") or {}).get(u) or "edit"}
                                  for u in (c.get("shared_with") or []) if u in names]
        c["my_perm"] = _list_perm(c, current)
        c["org_perm"] = c.get("org_perm") or "edit"
    return colls


async def _team_mate_ids(current: User, user_ids: list) -> list:
    """The given ids that are members of the caller's team (the caller excluded), deduplicated."""
    if not current.org_id or not user_ids:
        return []
    mates = await db.users.find({**_team_q(current.org_id), "user_id": {"$in": list(user_ids)}}, {"_id": 0, "user_id": 1}).to_list(300)
    ok = {m["user_id"] for m in mates} - {current.user_id}
    return [u for u in dict.fromkeys(user_ids) if u in ok]


async def _notify_list_shared(current: User, coll: dict, user_ids: list):
    if not user_ids:
        return
    rec = await db.users.find({"user_id": {"$in": user_ids}, "telegram_chat_id": {"$ne": None}}, {"_id": 0, "user_id": 1, "telegram_chat_id": 1}).to_list(300)
    for r in rec:
        read = ((coll.get("share_perms") or {}).get(r["user_id"]) if r["user_id"] in (coll.get("shared_with") or [])
                else coll.get("org_perm")) == "read"
        try:
            await _send_telegram_text(r["telegram_chat_id"], f"📋 {current.name} ti ha condiviso la lista «{coll['name']}»: "
                                      + ("puoi vederla (sola lettura)" if read else "puoi vederla e modificarla") + " in mAIPAL → Liste.")
        except Exception:
            logger.exception("list share telegram notice failed")


@api_router.put("/collections/{collection_id}/sharing")
async def set_collection_sharing(collection_id: str, payload: CollectionSharingPayload, current: User = Depends(get_current_user)):
    """Only the owner decides who the list is shared with: the whole team (visibility "org")
    and/or single team-mates (shared_with), each one (and the team) able to edit it or only to read it."""
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    if coll.get("user_id") != current.user_id:
        raise HTTPException(status_code=403, detail="Solo chi ha creato la lista può cambiare con chi è condivisa.")
    if (payload.visibility == "org" or payload.user_ids) and not current.org_id:
        raise HTTPException(status_code=400, detail="Per condividere una lista devi far parte di un team.")
    if payload.visibility == "org" or payload.user_ids:
        await _require_share_allowed(current)
    shared = await _team_mate_ids(current, payload.user_ids)
    updates = {"visibility": payload.visibility if current.org_id else "private", "shared_with": shared,
               "org_id": current.org_id, "share_perms": _clean_perms(shared, payload.perms), "org_perm": payload.org_perm}
    await db.collections.update_one({"id": collection_id}, {"$set": updates})
    before = coll.get("shared_with") or []
    new_people = [u for u in shared if u not in before]
    if payload.visibility == "org" and coll.get("visibility") != "org":
        mates = await db.users.find({**_team_q(current.org_id), "user_id": {"$ne": current.user_id}}, {"_id": 0, "user_id": 1}).to_list(300)
        new_people = list(dict.fromkeys(new_people + [m["user_id"] for m in mates if m["user_id"] not in before]))
    await _notify_list_shared(current, {**coll, **updates}, new_people)
    out = await db.collections.find_one({"id": collection_id}, {"_id": 0})
    return (await _add_sharing_info([out], current))[0]


@api_router.post("/collections")
async def create_collection(payload: CollectionCreatePayload, current: User = Depends(get_current_user)):
    if not payload.fields:
        raise HTTPException(status_code=400, detail="Definisci almeno un campo per la lista")
    if payload.max_items is not None and payload.max_items < 1:
        raise HTTPException(status_code=400, detail="Il limite di Campi deve essere almeno 1")
    if payload.max_sub_items_per_item is not None and payload.max_sub_items_per_item < 1:
        raise HTTPException(status_code=400, detail="Il limite di Elementi per Campo deve essere almeno 1")
    name = payload.name.strip() or "Nuova lista"
    if payload.visibility == "org" or payload.shared_with:
        await _require_share_allowed(current)
    existing = await db.collections.find(_lists_query(current), {"_id": 0, "name": 1, "sort_order": 1}).to_list(500)
    if any((e.get("name") or "").strip().lower() == name.lower() for e in existing):
        raise HTTPException(status_code=400, detail=f"Esiste già una lista chiamata \"{name}\".")
    next_order = max([e.get("sort_order", -1) for e in existing], default=-1) + 1
    doc = {
        "id": f"coll_{uuid.uuid4().hex[:12]}",
        "name": name,
        "icon": payload.icon,
        "fields": _unique_field_keys([f.model_dump() for f in payload.fields]),
        "sub_item_fields": _unique_field_keys([f.model_dump() for f in payload.sub_item_fields]),
        "visibility": payload.visibility,
        "shared_with": await _team_mate_ids(current, payload.shared_with),
        "org_perm": payload.org_perm,
        "max_items": payload.max_items,
        "max_sub_items_per_item": payload.max_sub_items_per_item,
        "sort_order": next_order,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    doc["share_perms"] = _clean_perms(doc["shared_with"], payload.share_perms)
    _stamp_owner_fields(doc, current)
    await db.collections.insert_one(doc)
    doc.pop("_id", None)
    if doc["shared_with"] or doc["visibility"] == "org":
        people = doc["shared_with"]
        if doc["visibility"] == "org":
            mates = await db.users.find({**_team_q(current.org_id), "user_id": {"$ne": current.user_id}}, {"_id": 0, "user_id": 1}).to_list(300)
            people = list(dict.fromkeys(people + [m["user_id"] for m in mates]))
        await _notify_list_shared(current, doc, people)
    return (await _add_sharing_info([doc], current))[0]


@api_router.get("/collections/{collection_id}")
async def get_collection(collection_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    await _repair_field_keys(coll)
    return _public_list_folder((await _add_sharing_info([coll], current))[0], await _storage_user(current.user_id))


@api_router.patch("/collections/{collection_id}")
async def update_collection(collection_id: str, payload: CollectionUpdatePayload, current: User = Depends(get_current_user)):
    existing = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(existing, current)
    updates = {}
    if payload.name is not None:
        new_name = payload.name.strip() or existing["name"]
        if new_name.lower() != (existing.get("name") or "").strip().lower():
            others = await db.collections.find({**_lists_query(current), "id": {"$ne": collection_id}}, {"_id": 0, "name": 1}).to_list(500)
            if any((o.get("name") or "").strip().lower() == new_name.lower() for o in others):
                raise HTTPException(status_code=400, detail=f"Esiste già una lista chiamata \"{new_name}\".")
        updates["name"] = new_name[:80]
    if payload.icon is not None:
        updates["icon"] = payload.icon
    if payload.fields is not None:
        updates["fields"] = _unique_field_keys([f.model_dump() for f in payload.fields])
    if payload.sub_item_fields is not None:
        updates["sub_item_fields"] = _unique_field_keys([f.model_dump() for f in payload.sub_item_fields])
    if existing.get("system_key") and ("fields" in updates or "sub_item_fields" in updates):
        gone = vx.missing_system_fields({**existing, **updates})
        if gone:
            raise HTTPException(status_code=400, detail="Questi attributi sono quelli di base del tuo settore e non si possono togliere: " + ", ".join(gone) + ". Puoi aggiungerne altri.")
    if payload.visibility is not None and payload.visibility != existing.get("visibility", "private"):
        if existing.get("user_id") != current.user_id:
            raise HTTPException(status_code=403, detail="Solo chi ha creato la lista può cambiare con chi è condivisa.")
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
    out = await db.collections.find_one({"id": collection_id}, {"_id": 0})
    return (await _add_sharing_info([out], current))[0]


@api_router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str, current: User = Depends(get_current_user)):
    existing = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    if existing.get("user_id") != current.user_id:
        raise HTTPException(status_code=403, detail="Solo chi ha creato la lista può eliminarla.")
    if existing.get("system_key"):
        raise HTTPException(status_code=400, detail=f"«{existing['name']}» è la lista di base del tuo settore: non si può eliminare.")
    await db.collections.delete_one({"id": collection_id})
    await db.collection_items.delete_many({"collection_id": collection_id})
    await db.collection_sub_items.delete_many({"collection_id": collection_id})
    return {"ok": True}


@api_router.get("/collections/{collection_id}/items")
async def list_collection_items(collection_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    # without the search's cached vectors (384 numbers per element): the phone downloaded
    # hundreds of KB for a shopping list
    cursor = db.collection_items.find({"collection_id": collection_id}, {"_id": 0, "embedding": 0}).sort("created_at", -1)
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
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
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
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
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
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
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
async def delete_collection_item(collection_id: str, item_id: str, code: Optional[str] = None, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
    if coll.get("system_key") == vx.CLIENTI_KEY:   # the client's commesse take their diary with them
        await _check_delete_code(current, collection_id, item_id, None, code)
        subs = await db.collection_sub_items.find({"collection_id": collection_id, "item_id": item_id}, {"_id": 0, "id": 1}).to_list(5000)
        await _delete_job_diaries([sb["id"] for sb in subs])
        await db.client_links.delete_many({"item_id": item_id})   # no more weekly progress to them
    await db.collection_items.delete_one({"id": item_id, "collection_id": collection_id})
    await db.collection_sub_items.delete_many({"collection_id": collection_id, "item_id": item_id})
    return {"ok": True}


# ---- Deleting a client or a commessa (and its diary) of the Clienti list: confirmed with a
# 6-digit code sent on Telegram - valid 10 minutes, once, for that one thing, 5 tries ----
DELETE_CODE_MINUTES = 10
DELETE_CODE_TRIES = 5
TELEGRAM_NEEDED_FOR_DELETE = ("Per eliminare clienti e commesse ti mando un codice di conferma su Telegram, che però non è "
                              "collegato: collegalo in Impostazioni → Collegamenti → Telegram.")


class DeleteCodePayload(BaseModel):
    collection_id: str
    item_id: str
    sub_id: Optional[str] = None


def _code_hash(user_id: str, code: str) -> str:
    import hashlib
    return hashlib.sha256(f"{user_id}:{(code or '').strip()}".encode()).hexdigest()


@api_router.post("/clienti/delete-code")
async def request_delete_code(payload: DeleteCodePayload, current: User = Depends(get_current_user)):
    """Elimina on a client or a commessa: the code goes to the user's Telegram with what will be
    deleted. Without Telegram linked -> 409 (the app asks to link it)."""
    coll = await db.collections.find_one({"id": payload.collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll or coll.get("system_key") != vx.CLIENTI_KEY:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
    if not current.telegram_chat_id or not tg.bot_token():
        raise HTTPException(status_code=409, detail=TELEGRAM_NEEDED_FOR_DELETE)
    client = await db.collection_items.find_one({"id": payload.item_id, "collection_id": coll["id"]}, {"_id": 0, "embedding": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    fmap, smap = coll.get("system_map") or {}, coll.get("system_sub_map") or {}
    client_name = _sysval(client.get("data"), fmap, "nome") or "il cliente"
    if payload.sub_id:
        sub = await db.collection_sub_items.find_one({"id": payload.sub_id, "collection_id": coll["id"], "item_id": client["id"]}, {"_id": 0})
        if not sub:
            raise HTTPException(status_code=404, detail="Commessa non trovata")
        ids = [sub["id"]]
        what = f"la commessa «{_sysval(sub.get('data'), smap, 'titolo') or 'senza titolo'}» di {client_name}"
    else:
        ids = [x["id"] for x in await db.collection_sub_items.find({"collection_id": coll["id"], "item_id": client["id"]}, {"_id": 0, "id": 1}).to_list(5000)]
        what = f"il cliente «{client_name}»" + (f" con {'la sua commessa' if len(ids) == 1 else f'le sue {len(ids)} commesse'}" if ids else "")
    entries = await db.job_logs.count_documents({"commessa_id": {"$in": ids}, "kind": None}) if ids else 0
    photos = await db.job_photos.count_documents({"commessa_id": {"$in": ids}}) if ids else 0
    parts = [f"{entries} {'voce' if entries == 1 else 'voci'}"] + ([f"{photos} foto"] if photos else [])
    code = f"{secrets.randbelow(10 ** 6):06d}"
    sent = await _send_telegram_text(current.telegram_chat_id,
        f"🗑 Codice per eliminare {what}: *{code}*\n"
        f"Verranno cancellati anche il diario ({', '.join(parts)}), le attività e i costi. I file su Drive/OneDrive restano.\n"
        f"Vale {DELETE_CODE_MINUTES} minuti. Se non sei stato tu, ignora questo messaggio.")
    if not sent:
        raise HTTPException(status_code=502, detail="Non sono riuscito a mandarti il codice su Telegram: riprova tra poco.")
    await db.delete_codes.delete_many({"user_id": current.user_id})   # one at a time: a new one replaces the old
    await db.delete_codes.insert_one({
        "user_id": current.user_id, "collection_id": coll["id"], "item_id": client["id"], "sub_id": payload.sub_id or None,
        "code_hash": _code_hash(current.user_id, code), "tries": 0,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=DELETE_CODE_MINUTES)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()})
    return {"sent": True, "minutes": DELETE_CODE_MINUTES, "what": what, "entries": entries, "photos": photos}


async def _check_delete_code(current: User, collection_id: str, item_id: str, sub_id: Optional[str], code: Optional[str]) -> None:
    """The code asked for exactly this deletion, not expired, not over the tries: then it is used up."""
    import hmac
    if not current.telegram_chat_id:
        raise HTTPException(status_code=409, detail=TELEGRAM_NEEDED_FOR_DELETE)
    rec_ = await db.delete_codes.find_one({"user_id": current.user_id, "collection_id": collection_id, "item_id": item_id,
                                           "sub_id": sub_id or None}, {"_id": 0})
    if not code or not rec_:
        raise HTTPException(status_code=403, detail="Serve il codice di conferma: tocca Elimina per riceverlo su Telegram.")
    if rec_["expires_at"] < datetime.now(timezone.utc).isoformat():
        await db.delete_codes.delete_many({"user_id": current.user_id})
        raise HTTPException(status_code=403, detail="Il codice è scaduto: chiedine uno nuovo.")
    if not hmac.compare_digest(rec_["code_hash"], _code_hash(current.user_id, re.sub(r"\D", "", code))):
        tries = int(rec_.get("tries") or 0) + 1
        if tries >= DELETE_CODE_TRIES:
            await db.delete_codes.delete_many({"user_id": current.user_id})
            raise HTTPException(status_code=403, detail="Codice errato troppe volte: chiedine uno nuovo.")
        await db.delete_codes.update_one({"user_id": current.user_id}, {"$set": {"tries": tries}})
        left = DELETE_CODE_TRIES - tries
        raise HTTPException(status_code=403, detail=f"Codice errato: {'resta 1 tentativo' if left == 1 else f'restano {left} tentativi'}.")
    await db.delete_codes.delete_many({"user_id": current.user_id})


# ---- The app's notifications on the device (Web Push), also with the app closed: only what
# external collaborators write in a commessa's diary and the tasks' reminders ----
class PushSubscribePayload(BaseModel):
    subscription: dict


class PushEndpointPayload(BaseModel):
    endpoint: str


@api_router.get("/push/key")
async def push_public_key(current: User = Depends(get_current_user)):
    return {"public_key": (await push.vapid_keys(db))["public"]}


@api_router.post("/push/subscribe")
async def push_subscribe(payload: PushSubscribePayload, request: Request, current: User = Depends(get_current_user)):
    try:
        await push.subscribe(db, current.user_id, payload.subscription, request.headers.get("user-agent", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "devices": await db.push_subscriptions.count_documents({"user_id": current.user_id})}


@api_router.post("/push/unsubscribe")
async def push_unsubscribe(payload: PushEndpointPayload, current: User = Depends(get_current_user)):
    await push.unsubscribe(db, current.user_id, payload.endpoint)
    return {"ok": True}


@api_router.post("/push/status")
async def push_status(payload: PushEndpointPayload, current: User = Depends(get_current_user)):
    """Is this device (its endpoint) receiving this user's notifications?"""
    on = bool(payload.endpoint) and bool(await db.push_subscriptions.find_one({"user_id": current.user_id, "endpoint": payload.endpoint}, {"_id": 1}))
    return {"subscribed": on, "devices": await db.push_subscriptions.count_documents({"user_id": current.user_id}),
            "last": await push.last_sending(db, current.user_id)}


@api_router.post("/push/test")
async def push_test(current: User = Depends(get_current_user)):
    n = await push.send_to_user(db, current.user_id, "🔔 mAIPAL", "Le notifiche funzionano: qui arriveranno i promemoria dei task e le voci dei collaboratori.", "/dashboard/settings?s=notifications", "test")
    if not n:
        errs = ((await push.last_sending(db, current.user_id)) or {}).get("errors") or []
        raise HTTPException(status_code=400, detail="Nessun dispositivo ha ricevuto la prova"
                            + (f" ({errs[0]})." if errs else ": riattiva le notifiche su questo dispositivo."))
    return {"sent": n}


def _push_collab_entry(owner: User, log: dict, author: dict) -> None:
    """A collaborator wrote in a commessa's diary: the owner's devices hear it."""
    who = author.get("name") or author.get("first_name") or "Un collaboratore"
    bits = [jl.hours_line(log["hours"])] if log.get("hours") else []
    if log.get("hours_pending"):
        bits.append(f"🕒 {jl.hours_line(log['hours_pending'])} da approvare")
    if log.get("problems"):
        bits.append("⚠️ " + "; ".join(log["problems"]))
    body = (log.get("text") or "") + (f" · {' · '.join(bits)}" if bits else "")
    if log.get("photos") and (log.get("raw_text") == PHOTO_ONLY_TEXT):
        body = f"📷 {len(log['photos'])} foto"
    push.fire_and_forget(db, owner.user_id, f"📒 {who} · {log.get('commessa_title') or 'Diario'}", body,
                         f"/dashboard/journal?commessa={log['commessa_id']}", f"jlog-{log['id']}")


async def _delete_job_diaries(commessa_ids: list) -> None:
    if commessa_ids:
        await db.job_logs.delete_many({"commessa_id": {"$in": commessa_ids}})
        await db.job_photos.delete_many({"commessa_id": {"$in": commessa_ids}})
        await db.job_todos.delete_many({"commessa_id": {"$in": commessa_ids}})
        await db.job_milestones.delete_many({"commessa_id": {"$in": commessa_ids}})
        await db.job_contacts.delete_many({"commessa_id": {"$in": commessa_ids}})
        await db.work_sessions.delete_many({"commessa_id": {"$in": commessa_ids}})
        await db.job_economics.delete_many({"commessa_id": {"$in": commessa_ids}})
        await db.collaborators.update_many({"commesse": {"$in": commessa_ids}}, {"$pull": {"commesse": {"$in": commessa_ids}}})


# ---- Elementi (livello 3): annidati dentro un campo/item specifico ----
@api_router.get("/collections/{collection_id}/items/{item_id}/sub-items")
async def list_sub_items(collection_id: str, item_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    cursor = db.collection_sub_items.find({"collection_id": collection_id, "item_id": item_id}, {"_id": 0, "embedding": 0}).sort("created_at", -1)
    subs = await cursor.to_list(1000)
    uid = await _storage_user(current.user_id)
    for sb in subs:   # the folder on the archive used (their own, or the organization administrator's)
        sb["drive_folder"] = (sb.pop("drive_folders", None) or {}).get(uid)
    return subs


@api_router.post("/collections/{collection_id}/items/{item_id}/sub-items")
async def create_sub_item(collection_id: str, item_id: str, payload: CollectionSubItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
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
    data = dict(payload.data or {})
    if coll.get("system_key") == vx.CLIENTI_KEY:   # a new commessa: in corso from today, unless said otherwise
        smap = coll.get("system_sub_map") or {}
        data.setdefault(smap.get("stato", "stato"), "in corso")
        if not data.get(smap.get("stato", "stato")):
            data[smap.get("stato", "stato")] = "in corso"
        data.setdefault(smap.get("data_inizio", "data_inizio"), jl.today_local().isoformat())
    doc = {
        "id": f"sub_{uuid.uuid4().hex[:12]}",
        "collection_id": collection_id,
        "item_id": item_id,
        "data": data,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.collection_sub_items.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/collections/{collection_id}/items/{item_id}/sub-items/{sub_id}")
async def update_sub_item(collection_id: str, item_id: str, sub_id: str, payload: CollectionSubItemPayload, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
    before = await db.collection_sub_items.find_one({"id": sub_id, "collection_id": collection_id, "item_id": item_id}, {"_id": 0})
    r = await db.collection_sub_items.update_one(
        {"id": sub_id, "collection_id": collection_id, "item_id": item_id}, {"$set": {"data": payload.data, "embedding": None}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Elemento non trovato")
    after = await db.collection_sub_items.find_one({"id": sub_id, "collection_id": collection_id}, {"_id": 0})
    if coll.get("system_key") == vx.CLIENTI_KEY and before:   # a commessa's state change goes in its diary
        smap = coll.get("system_sub_map") or {}
        old, new = _sysval(before.get("data"), smap, "stato"), _sysval(after.get("data"), smap, "stato")
        if old != new:
            client = await db.collection_items.find_one({"id": item_id, "collection_id": collection_id}, {"_id": 0, "embedding": 0})
            await _log_stato_change(current, coll, after, client, old, new)
    return after


@api_router.delete("/collections/{collection_id}/items/{item_id}/sub-items/{sub_id}")
async def delete_sub_item(collection_id: str, item_id: str, sub_id: str, code: Optional[str] = None, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
    if coll.get("system_key") == vx.CLIENTI_KEY:   # a commessa and its diary: only with the code from Telegram
        if not await db.collection_sub_items.find_one({"id": sub_id, "collection_id": collection_id, "item_id": item_id}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Elemento non trovato")
        await _check_delete_code(current, collection_id, item_id, sub_id, code)
    r = await db.collection_sub_items.delete_one({"id": sub_id, "collection_id": collection_id, "item_id": item_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Elemento non trovato")
    if coll.get("system_key") == vx.CLIENTI_KEY:
        await _delete_job_diaries([sub_id])
    return {"ok": True}


# ---- Rilevamento automatico "salva nota" vs "modifica lista" (un solo tasto in chat) ----
@api_router.post("/classify-save-intent")
async def classify_save_intent(payload: ClassifySaveIntentPayload, current: User = Depends(get_current_user)):
    colls = await db.collections.find(_lists_query(current), {"_id": 0, "name": 1}).to_list(200)
    kind = await lu.classify_save_intent(payload.text, [c["name"] for c in colls], user_id=current.user_id, channel="web")
    return {"kind": kind}


# ---- Creazione di una Lista da testo libero ("crea una lista della spesa con latte e pane") ----
def _unique_field_keys(fields: list) -> list:
    """Every attribute of a list needs its own key: "Descrizione", "Data inizio" and "Data
    fine" all ended up as "d" (the key was taken from the first letter typed), so editing
    one changed them all. A repeated or missing key gets a new one from the label; the
    first attribute keeps the key (and the values already saved under it)."""
    taken: set = set()
    out = []
    for f in fields or []:
        f = dict(f)
        key = (f.get("key") or "").strip()
        if not key or key in taken:
            key = _field_key(f.get("label") or "campo", taken)
        else:
            taken.add(key)
        f["key"] = key
        out.append(f)
    return out


async def _repair_field_keys(coll: dict) -> dict:
    """Lists saved with the old bug: fix their keys once, on the next read."""
    upd = {}
    for name in ("fields", "sub_item_fields"):
        keys = [f.get("key") for f in coll.get(name) or []]
        if len(set(keys)) != len(keys) or any(not k for k in keys):
            upd[name] = _unique_field_keys(coll.get(name) or [])
    if upd:
        await db.collections.update_one({"id": coll["id"]}, {"$set": upd})
        coll.update(upd)
    return coll


def _field_key(label: str, taken: set) -> str:
    import re as _re, unicodedata
    base = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    base = _re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "campo"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    taken.add(key)
    return key


# ---- a list's own folder on Drive / OneDrive ----
# "crea la lista Clienti e la relativa cartella su drive", or the folder button of a list: a
# folder named like the list inside the mAIPAL folder of every chosen storage - the same
# folders smart-upload saves into, so "salva questo file nella cartella Clienti" lands there.
_FOLDER_ASK = re.compile(r"\b(crea|creami|crei|creare|fai|fammi|apri|aggiungi|anche|con)\b.{0,60}\bcartell[ae]\b"
                         r"|\bcartell[ae]\b.{0,40}\b(drive|onedrive|cloud)\b", re.I | re.S)
_FOLDER_CLAUSE = re.compile(r"[,;]?\s*(?:e\s+)?(?:(?:crea|creami|fai|fammi)\s+)?(?:anche\s+)?(?:con\s+)?(?:la\s+|una\s+)?"
                            r"(?:relativa\s+|sua\s+)?cartell[ae]\b[^.;\n]*", re.I)


_WHOLE_LIST_DELETE = re.compile(r"^\W*(elimina|eliminami|cancella|rimuovi|butta)\s+(via\s+)?(tutta\s+)?(la|questa|quella)\s+lista\b", re.I)
_LIST_CONTENT_WORDS = re.compile(r"\b(element\w*|camp[oi]|voc[ei]|righe|riga|iscritt\w*|tutti|tutte|dalla|dalle|dai|dal)\b", re.I)


def _wants_list_folder(text: str) -> bool:
    return bool(_FOLDER_ASK.search(text or ""))


def _public_list_folder(coll: dict, user_id: str) -> dict:
    """The list as the API returns it: only the caller's own folder (each person's is on their Drive)."""
    folders = coll.pop("drive_folders", None) or {}
    coll["drive_folder"] = folders.get(user_id)
    return coll


LIST_FOLDER_TIMEOUT = 40


async def _ensure_list_folder(current: User, coll: dict) -> dict:
    """The list's folder on every chosen storage (made once, then reused)."""
    uid = await _storage_user(current.user_id)
    existing = (coll.get("drive_folders") or {}).get(uid)
    if existing and existing.get("ids"):
        return existing
    targets = await _storage_targets(uid)
    if not targets:
        raise HTTPException(status_code=400, detail=NO_STORAGE_MSG)
    name = re.sub(r"[\\/:*?\"<>|]+", " ", coll.get("name") or "Lista").strip()[:100] or "Lista"
    ids, links, errors = {}, {}, {}
    for t in targets:
        try:
            # Drive's client blocks: in a thread, and never longer than LIST_FOLDER_TIMEOUT - a
            # stuck call used to leave the chat waiting forever on "crea la cartella su drive"
            if t == "google":
                creds = await gi.get_credentials(db, uid)
                if not creds:
                    raise RuntimeError("Google Drive non collegato")
                parent = await asyncio.wait_for(gi.ensure_maipal_folder(db, uid, creds), LIST_FOLDER_TIMEOUT)
                fid = await asyncio.wait_for(asyncio.to_thread(gi.find_or_create_subfolder_sync, creds, parent, name), LIST_FOLDER_TIMEOUT)
                ids[t], links[t] = fid, f"https://drive.google.com/drive/folders/{fid}"
            else:
                token = await ms.get_token(db, uid)
                fid = await asyncio.wait_for(ms.find_or_create_folder(db, uid, token, name), LIST_FOLDER_TIMEOUT)
                ids[t] = fid
                try:
                    links[t] = await ms.item_web_url(token, fid)
                except Exception:
                    links[t] = None
        except asyncio.TimeoutError:
            logger.error(f"list folder on {t}: no answer in {LIST_FOLDER_TIMEOUT}s")
            errors[t] = "non ha risposto in tempo, riprova tra poco"
        except Exception as e:
            logger.exception(f"list folder on {t} failed")
            errors[t] = str(e)[:200]
    if not ids:
        raise HTTPException(status_code=500, detail="Cartella non creata: " + "; ".join(f"{STORAGE_LABELS[k]}: {v}" for k, v in errors.items()))
    info = {"name": name, "ids": ids, "links": links, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.collections.update_one({"id": coll["id"]}, {"$set": {"drive_folders": {**(coll.get("drive_folders") or {}), uid: info}}})
    coll.setdefault("drive_folders", {})[uid] = info
    return info


def _folder_where(info: dict) -> str:
    return " e ".join(STORAGE_LABELS[t] for t in (info.get("ids") or {}))


async def _ensure_storage_path(current: User, folder: str, subs: List[str]) -> dict:
    """mAIPAL/<folder>/<subs...> on every chosen storage, each level found or made (blocking
    Drive calls in a thread, each bounded by LIST_FOLDER_TIMEOUT). -> {"name", "ids", "links"}"""
    uid = await _storage_user(current.user_id)
    targets = await _storage_targets(uid)
    if not targets:
        raise HTTPException(status_code=400, detail=NO_STORAGE_MSG)
    path = [_drive_safe(folder)] + [_drive_safe(x) for x in subs if x]
    ids, links, errors = {}, {}, {}
    for t in targets:
        try:
            if t == "google":
                creds = await gi.get_credentials(db, uid)
                if not creds:
                    raise RuntimeError("Google Drive non collegato")
                fid = await asyncio.wait_for(gi.ensure_maipal_folder(db, uid, creds), LIST_FOLDER_TIMEOUT)
                for name in path:
                    fid = await asyncio.wait_for(asyncio.to_thread(gi.find_or_create_subfolder_sync, creds, fid, name), LIST_FOLDER_TIMEOUT)
                ids[t], links[t] = fid, f"https://drive.google.com/drive/folders/{fid}"
            else:
                token = await ms.get_token(db, uid)
                fid = await asyncio.wait_for(ms.find_or_create_folder(db, uid, token, path[0]), LIST_FOLDER_TIMEOUT)
                for name in path[1:]:
                    fid = await asyncio.wait_for(ms.find_or_create_child_folder(token, fid, name), LIST_FOLDER_TIMEOUT)
                ids[t] = fid
                try:
                    links[t] = await ms.item_web_url(token, fid)
                except Exception:
                    links[t] = None
        except asyncio.TimeoutError:
            logger.error(f"folder {path} on {t}: no answer in {LIST_FOLDER_TIMEOUT}s")
            errors[t] = "non ha risposto in tempo, riprova tra poco"
        except Exception as e:
            logger.exception(f"folder {path} on {t} failed")
            errors[t] = str(e)[:200]
    if not ids:
        raise HTTPException(status_code=500, detail="Cartella non creata: " + "; ".join(f"{STORAGE_LABELS[k]}: {v}" for k, v in errors.items()))
    return {"name": " / ".join(path), "ids": ids, "links": links, "created_at": datetime.now(timezone.utc).isoformat()}


@api_router.post("/jobs/commesse/{commessa_id}/folder")
async def create_commessa_folder(commessa_id: str, current: User = Depends(get_current_user)):
    """The commessa's folder, under its client's: mAIPAL/Clienti/<cliente>/<commessa> - the same
    place where its reports and diary photos are saved. Made once per person, then reused."""
    clienti, sub, client = await _commessa_or_404(current, commessa_id)
    uid = await _storage_user(current.user_id)
    existing = (sub.get("drive_folders") or {}).get(uid)
    if existing and existing.get("ids"):
        return {"drive_folder": existing, "message": f"Cartella «{existing['name']}» già pronta."}
    view = _commessa_view(sub, client, clienti)
    info = await _ensure_storage_path(current, clienti.get("name") or vx.CLIENTI_NAME, [view["client_name"], view["title"]])
    await db.collection_sub_items.update_one({"id": commessa_id}, {"$set": {"drive_folders": {**(sub.get("drive_folders") or {}), uid: info}}})
    return {"drive_folder": info, "message": f"Cartella «{info['name']}» pronta su {_folder_where(info)}."}


@api_router.post("/collections/{collection_id}/folder")
async def create_list_folder(collection_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    _require_list_edit(coll, current)
    info = await _ensure_list_folder(current, coll)
    return {"drive_folder": info, "message": f"Cartella «{info['name']}» pronta su {_folder_where(info)}."}


async def _create_list_from_text(current: User, text: str, channel: str = "web", attachment_doc_ids: Optional[List[str]] = None) -> dict:
    """Creates a new list (and its first items) from a sentence. Until now chat could only
    EDIT existing lists: "crea una lista ..." was either saved as a plain note or sent to
    the list editor, which found no such list - and nothing was created."""
    clienti = await _clienti_list(current)
    if clienti and lu.about_jobs(text, [clienti.get("name") or "", "clienti"]):
        # "crea una commessa per i Rossi": it goes under the client in the Clienti list, never a new list
        res = await _execute_list_update(current, text, collection_id=None, channel=channel)
        if res.get("status") in ("ok", "error"):
            return res
        return {"status": "error", "message": res.get("message") or "Per quale cliente? Scrivimi il nome esatto (es. «crea la commessa Bagno per Mario Rossi»)."}
    try:
        doc_ids = [d for d in (attachment_doc_ids or []) if isinstance(d, str)][:10]
        if doc_ids:
            ctx = await _attachments_text_for_model(current.user_id, doc_ids, limit=6000)
        else:
            hits = await retrieve_kb(current.user_id, text, scope="kb", org_id=current.org_id, limit=6)
            ctx = "\n\n".join(f"- {h.get('display') or h.get('text', '')}" for h in hits)[:6000]
    except Exception:
        ctx = ""
    want_folder = _wants_list_folder(text)
    list_text = (_FOLDER_CLAUSE.sub("", text).strip() or text) if want_folder else text
    spec = await lu.interpret_list_creation(list_text, ctx, user_id=current.user_id, channel=channel)
    taken: set = set()
    fields = [CollectionFieldDef(key=_field_key(f["label"], taken), label=f["label"], type=f["type"]) for f in spec["fields"]]
    try:
        coll = await create_collection(CollectionCreatePayload(name=spec["name"], fields=fields), current)
    except HTTPException as he:
        if want_folder:   # "crea la cartella della lista Spesa" read as a new list: the list is there, make its folder
            same = next((c for c in await db.collections.find(_lists_query(current), {"_id": 0}).to_list(200)
                         if (c.get("name") or "").strip().lower() == (spec["name"] or "").strip().lower()), None)
            if same:
                return await _list_folder_reply(current, same, already=True)
        return {"status": "error", "message": str(he.detail)}
    by_label = {f.label.strip().lower(): f.key for f in fields}
    now = datetime.now(timezone.utc).isoformat()
    docs, seen = [], set()
    for raw in spec["items"]:
        data = {}
        for k, v in raw.items():
            key = by_label.get(str(k).strip().lower()) or (fields[0].key if len(raw) == 1 else None)
            if key and v not in (None, ""):
                data[key] = v if isinstance(v, (int, float)) else str(v).strip()
        name = str(data.get(fields[0].key) or "").strip().lower()
        if not data or not name or name in seen:
            continue
        seen.add(name)
        doc = {"id": f"item_{uuid.uuid4().hex[:12]}", "collection_id": coll["id"], "data": data,
               "visibility": coll.get("visibility", "private"), "sort_order": len(docs), "created_at": now}
        _stamp_owner_fields(doc, current)
        docs.append(doc)
    if docs:
        await db.collection_items.insert_many(docs)
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="gestione_liste", channel=channel, trigger="utente", org_id=current.org_id)
    cols = ", ".join(f.label for f in fields)
    what = (f" e {len(docs)} element{'o' if len(docs) == 1 else 'i'}" if docs else "")
    message = f"Ho creato la lista «{coll['name']}» (colonne: {cols}){what}. La trovi nella sezione Liste."
    if want_folder:
        try:
            info = await _ensure_list_folder(current, coll)
            message += f" Ho creato anche la cartella «{info['name']}» su {_folder_where(info)}: la apri dall'icona cartella della lista."
        except HTTPException as he:
            message += f" La cartella non l'ho creata: {he.detail}"
        except Exception:
            logger.exception("list folder after list creation failed")
            message += " La cartella non sono riuscito a crearla: riprova dall'icona cartella della lista."
    return {"status": "ok", "collection_id": coll["id"], "name": coll["name"], "items": len(docs), "message": message}


async def _list_folder_reply(current: User, coll: dict, already: bool = False) -> dict:
    had = bool(((coll.get("drive_folders") or {}).get(await _storage_user(current.user_id)) or {}).get("ids"))
    try:
        info = await _ensure_list_folder(current, coll)
    except HTTPException as he:
        return {"status": "error", "message": f"Non ho creato la cartella della lista «{coll['name']}»: {he.detail}"}
    head = f"La lista «{coll['name']}» c'era già. " if already else ""
    did = (f"La cartella «{info['name']}» su {_folder_where(info)} c'era già" if had
           else f"Ho creato la cartella «{info['name']}» su {_folder_where(info)}")
    return {"status": "ok", "collection_id": coll["id"], "name": coll["name"], "folder_only": True,
            "message": f"{head}{did} per la lista «{coll['name']}». "
                       f"La apri dall'icona cartella della lista; i file che salvi \"nella cartella {info['name']}\" finiscono lì."}


class ListCreatePayload(BaseModel):
    text: str
    attachment_doc_ids: Optional[List[str]] = None
    conv_id: Optional[str] = None


@api_router.post("/lists/create-from-text")
async def create_list_from_text(payload: ListCreatePayload, current: User = Depends(get_current_user)):
    doc_ids = payload.attachment_doc_ids
    if not doc_ids and payload.conv_id:
        conv = await db.conversations.find_one({"conv_id": payload.conv_id, "user_id": current.user_id}, {"_id": 0})
        if conv:
            doc_ids = await _conv_attachment_ids(current.user_id, conv, conv.get("messages") or [])
    return await _create_list_from_text(current, payload.text, attachment_doc_ids=doc_ids)


# ---- Modifica delle Liste da testo libero (chat web + Telegram) ----
@api_router.post("/lists/update")
async def update_list_via_text(payload: ListUpdatePayload, current: User = Depends(get_current_user)):
    return await _execute_list_update(
        current, payload.text, op=payload.op, collection_id=payload.collection_id,
        item_id=payload.item_id, sub_item_id=payload.sub_item_id, fields=payload.fields,
        item_query=payload.item_query, sub_item_query=payload.sub_item_query, confirm=payload.confirm,
        new_sub_items=payload.sub_items, new_items=payload.items, attachment_doc_ids=payload.attachment_doc_ids,
        conv_id=payload.conv_id,
    )


async def _execute_list_update(
    current: User, text: str, op: Optional[str] = None, collection_id: Optional[str] = None,
    item_id: Optional[str] = None, sub_item_id: Optional[str] = None, fields: Optional[dict] = None,
    item_query: Optional[str] = None, sub_item_query: Optional[str] = None, confirm: bool = False,
    new_sub_items: Optional[List[dict]] = None, new_items: Optional[List[dict]] = None, channel: str = "web",
    attachment_doc_ids: Optional[List[str]] = None, conv_id: Optional[str] = None,
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

    visible = await db.collections.find(_lists_query(current), {"_id": 0}).to_list(200)
    colls = [c for c in visible if _list_perm(c, current) in ("owner", "edit")]   # the read-only ones are not changed
    if not colls:
        raise HTTPException(status_code=400, detail=READ_ONLY_LIST if visible else
                            "Non hai ancora nessuna lista. Creane una nella sezione Liste prima di poter usare questa funzione.")
    coll_by_id = {c["id"]: c for c in colls}
    if not op and _WHOLE_LIST_DELETE.search(text) and not _LIST_CONTENT_WORDS.search(text):
        # deleting a WHOLE list goes through Azioni, which always asks for a yes first
        return {"status": "error", "message": "Per eliminare un'intera lista usa l'agente Azioni: scrivi «elimina la lista …» e ti chiederò conferma prima di farlo."}
    if not op and _wants_list_folder(text):
        named = lu.match_candidates(text, [(c["id"], c.get("name") or "") for c in colls if (c.get("name") or "").strip()])
        if len(named) == 1:
            res = await _list_folder_reply(current, coll_by_id[named[0]])
            if res["status"] == "ok":
                ut.fire_and_forget_feature_event(user_id=current.user_id, feature="gestione_liste", channel=channel, trigger="utente", org_id=current.org_id)
            return res

    if not op or not collection_id:
        pool = colls
        if not collection_id:   # a commessa / cantiere: only the Clienti list (under its client)
            clienti_c = [c for c in colls if c.get("system_key") == vx.CLIENTI_KEY]
            if clienti_c and lu.about_jobs(text, ["clienti"]):
                pool = clienti_c
        catalog = [{"id": c["id"], "name": c["name"], "fields": c.get("fields", []), "sub_item_fields": c.get("sub_item_fields", [])} for c in pool]
        # Give the interpreter a shot at the user's own uploaded documents too - e.g. "crea
        # un campo per ogni orario delle lezioni di pilates" only makes sense if it can see
        # the schedule that was OCR'd/extracted into the KB in an earlier message.
        kb_context = ""
        try:
            doc_ids = [d for d in (attachment_doc_ids or []) if isinstance(d, str)][:10]
            if not doc_ids and conv_id:   # files sent earlier in the same chat
                conv = await db.conversations.find_one({"conv_id": conv_id, "user_id": current.user_id}, {"_id": 0})
                if conv:
                    doc_ids = await _conv_attachment_ids(current.user_id, conv, conv.get("messages") or [])
            if doc_ids:   # the files sent with this message ARE the subject: use them, not a search
                kb_context = (await _attachments_text_for_model(current.user_id, doc_ids, limit=6000))
            else:
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
    if coll.get("system_key") == vx.CLIENTI_KEY and op in ("delete_item", "clear_items", "delete_sub_item", "clear_sub_items", "clear_all_sub_items"):
        raise HTTPException(status_code=400, detail="Clienti e commesse non si eliminano dalla chat: apri la lista Clienti e tocca Elimina, "
                                                    "ti mando un codice di conferma su Telegram.")
    items = await db.collection_items.find({"collection_id": collection_id}, {"_id": 0}).to_list(2000)

    item = None
    if op not in ("add_item", "clear_items", "clear_all_sub_items", "bulk_add_items"):
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
    if op == "clear_all_sub_items":
        all_subs_count = await db.collection_sub_items.count_documents({"collection_id": collection_id, "item_id": {"$in": [i["id"] for i in items]}})
        if not all_subs_count:
            ut.fire_and_forget_feature_event(user_id=current.user_id, feature="gestione_liste", channel=channel, trigger="utente", org_id=current.org_id)
            return {"status": "ok", "message": f"I campi di \"{coll['name']}\" sono già tutti vuoti, nulla da eliminare.", "collection_id": collection_id, "collection_name": coll["name"]}
        if not confirm:
            return {
                "status": "confirm_clear", "op": op, "collection_id": collection_id, "fields": {},
                "item_query": item_query, "sub_item_query": sub_item_query, "text": text, "count": all_subs_count,
                "candidates": [{"confirm": True, "label": f"Conferma: elimina tutti e {all_subs_count} gli elementi dai {len(items)} campi di \"{coll['name']}\""}],
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
        await delete_collection_item(collection_id, item["id"], current=current)
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
        await delete_sub_item(collection_id, item["id"], sub_item["id"], current=current)
        summary = f"Ho rimosso \"{lu.item_display(sub_item)}\" da \"{lu.item_display(item)}\" ({coll['name']})."
    elif op == "clear_sub_items":
        await db.collection_sub_items.delete_many({"collection_id": collection_id, "item_id": item["id"]})
        summary = f"Ho eliminato tutti e {len(sub_items)} gli elementi di \"{lu.item_display(item)}\" ({coll['name']})."
    elif op == "clear_all_sub_items":
        await db.collection_sub_items.delete_many({"collection_id": collection_id, "item_id": {"$in": [i["id"] for i in items]}})
        summary = f"Ho eliminato tutti e {all_subs_count} gli elementi dai {len(items)} campi di \"{coll['name']}\" (i campi restano)."
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
def _int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _clean_exercise(d: dict) -> dict:
    """The exercise as stored: words in lower case where they are filters, levels and roles
    from their lists, numbers as numbers (only the keys given are touched)."""
    out = dict(d)
    if "name" in out:
        out["name"] = " ".join(str(out["name"] or "").split())[:120]
        if not out["name"]:
            raise HTTPException(status_code=400, detail="Scrivi il nome dell'esercizio")
    for k in ("activity", "body_part", "equipment"):
        if k in out:
            out[k] = " ".join(str(out[k] or "").lower().split())[:60]
    if out.get("equipment") in ("nessuno", "corpo libero"):
        out["equipment"] = ""
    if "type" in out:
        out["type"] = " ".join(str(out["type"] or "").split())[:60]
    if "level" in out:
        out["level"] = fx.norm_level(out["level"])
    if "role" in out:
        out["role"] = out["role"] if out["role"] in fx.ROLES else "esercizio"
    if "equipment_per_person" in out:
        out["equipment_per_person"] = max(0, _int_or_none(out["equipment_per_person"]) or 0)
    for k, keys in (("timed", ("min_sec", "max_sec", "min_sets", "max_sets")),
                    ("reps", ("sec_per_set", "min_reps", "max_reps", "min_sets", "max_sets"))):
        if out.get(k) is not None:
            src = out[k] or {}
            out[k] = {"allowed": bool(src.get("allowed", True)), **{x: _int_or_none(src.get(x)) for x in keys}}
    return out


async def _ensure_fitness_base(current: User) -> None:
    """The fitness vertical's starting set, once per studio (the team, or the user alone): the
    base exercises, the equipment of the example and the base lesson type. Never added again,
    even if the studio deletes them."""
    owner = _fitness_owner_key(current)
    if await db.fitness_setup.find_one({"owner_key": owner, "base": 1}, {"_id": 1}):
        return
    await db.fitness_setup.update_one({"owner_key": owner}, {"$set": {"owner_key": owner, "base": 1,
                                       "at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    base = fx.base_catalog()
    now = datetime.now(timezone.utc).isoformat()
    vis = "org" if current.org_id else "private"
    docs = []
    for e in base["exercises"]:
        d = {"id": f"ex_{uuid.uuid4().hex[:12]}", **_clean_exercise(e), "base_id": e.get("base_id"), "builtin": True,
             "visibility": vis, "created_at": now}
        _stamp_owner_fields(d, current)
        docs.append(d)
    for d in docs:
        await db.exercises.insert_one(d)
    for e in base["equipment"]:
        await db.fitness_equipment.insert_one({"id": f"eq_{uuid.uuid4().hex[:12]}", "owner_key": owner, "name": e["name"],
                                               "quantity": int(e["quantity"]), "notes": "", "created_at": now})
    for t in fx.BASE_LESSON_TYPES:
        await db.lesson_types.insert_one({"id": f"ltype_{uuid.uuid4().hex[:12]}", "owner_key": owner, **t, "builtin": True, "created_at": now})


@api_router.get("/exercises")
async def list_exercises(current: User = Depends(get_current_user)):
    if current.business_vertical == "fitness":
        await _ensure_fitness_base(current)
    cursor = db.exercises.find(_visible_query(current), {"_id": 0}).sort("name", 1)
    return await cursor.to_list(2000)


@api_router.post("/exercises")
async def create_exercise(payload: ExerciseUpsert, current: User = Depends(get_current_user)):
    doc = {
        "id": f"ex_{uuid.uuid4().hex[:12]}",
        **_clean_exercise(payload.model_dump()),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.exercises.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/exercises/{exercise_id}")
async def update_exercise(exercise_id: str, payload: dict, current: User = Depends(get_current_user)):
    for k in ("id", "user_id", "_id", "org_id", "builtin", "base_id", "created_at"):
        payload.pop(k, None)
    payload = _clean_exercise(payload)
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


# ---- the studio's equipment: what there is and how many (the lessons are built on it) ----
class EquipmentPayload(BaseModel):
    name: Optional[str] = None
    quantity: Optional[int] = None
    delta: Optional[int] = None               # +1 / -1 from the list
    notes: Optional[str] = None


@api_router.get("/fitness/equipment")
async def list_equipment(current: User = Depends(get_current_user)):
    await _ensure_fitness_base(current)
    items = await db.fitness_equipment.find({"owner_key": _fitness_owner_key(current)}, {"_id": 0}).to_list(500)
    return sorted(items, key=lambda e: e["name"].lower())


@api_router.post("/fitness/equipment")
async def add_equipment(payload: EquipmentPayload, current: User = Depends(get_current_user)):
    owner = _fitness_owner_key(current)
    name = " ".join((payload.name or "").lower().split())[:60]
    if not name:
        raise HTTPException(status_code=400, detail="Scrivi il nome dell'attrezzo")
    qty = max(0, payload.quantity or 0)
    existing = await db.fitness_equipment.find_one({"owner_key": owner, "name": name}, {"_id": 0})
    if existing:   # the same piece again: its quantity goes up
        await db.fitness_equipment.update_one({"id": existing["id"]}, {"$set": {"quantity": existing["quantity"] + qty}})
        return {**existing, "quantity": existing["quantity"] + qty}
    doc = {"id": f"eq_{uuid.uuid4().hex[:12]}", "owner_key": owner, "name": name, "quantity": qty,
           "notes": (payload.notes or "").strip()[:200], "created_at": datetime.now(timezone.utc).isoformat()}
    await db.fitness_equipment.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/fitness/equipment/{eq_id}")
async def update_equipment(eq_id: str, payload: EquipmentPayload, current: User = Depends(get_current_user)):
    eq = await db.fitness_equipment.find_one({"id": eq_id, "owner_key": _fitness_owner_key(current)}, {"_id": 0})
    if not eq:
        raise HTTPException(status_code=404, detail="Attrezzo non trovato")
    upd = {}
    if payload.name is not None:
        name = " ".join(payload.name.lower().split())[:60]
        if not name:
            raise HTTPException(status_code=400, detail="Scrivi il nome dell'attrezzo")
        upd["name"] = name
    if payload.quantity is not None:
        upd["quantity"] = max(0, payload.quantity)
    if payload.delta:
        upd["quantity"] = max(0, upd.get("quantity", eq["quantity"]) + payload.delta)
    if payload.notes is not None:
        upd["notes"] = payload.notes.strip()[:200]
    if upd:
        await db.fitness_equipment.update_one({"id": eq_id}, {"$set": upd})
        if upd.get("name") and upd["name"] != eq["name"]:   # the exercises follow the new name
            await db.exercises.update_many({**_visible_query(current), "equipment": eq["name"]}, {"$set": {"equipment": upd["name"]}})
    return {**eq, **upd}


@api_router.delete("/fitness/equipment/{eq_id}")
async def delete_equipment(eq_id: str, current: User = Depends(get_current_user)):
    r = await db.fitness_equipment.delete_one({"id": eq_id, "owner_key": _fitness_owner_key(current)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Attrezzo non trovato")
    return {"ok": True}


# ---- the lesson types and their rules (duration, stretching at start and end, rest...) ----
class LessonTypePayload(BaseModel):
    name: Optional[str] = None
    activity: Optional[str] = None
    duration_min: Optional[int] = None
    start_min: Optional[int] = None
    start_kind: Optional[str] = None
    end_min: Optional[int] = None
    end_kind: Optional[str] = None
    rest_sec: Optional[int] = None
    default_level: Optional[str] = None
    default_participants: Optional[int] = None
    mode: Optional[str] = None
    rules_text: Optional[str] = None


def _clean_lesson_type(p: dict) -> dict:
    out = {}
    if p.get("name") is not None:
        out["name"] = " ".join(p["name"].split())[:60]
        if not out["name"]:
            raise HTTPException(status_code=400, detail="Scrivi il nome del tipo di lezione")
    if p.get("activity") is not None:
        out["activity"] = " ".join(p["activity"].lower().split())[:40]
    for k, lo, hi in (("duration_min", 5, 240), ("start_min", 0, 60), ("end_min", 0, 60), ("rest_sec", 0, 300), ("default_participants", 1, 200)):
        if p.get(k) is not None:
            out[k] = max(lo, min(hi, int(p[k])))
    for k in ("start_kind", "end_kind"):
        if p.get(k) is not None:
            out[k] = p[k] if p[k] in fx.PHASE_KINDS else "stretching"
    if p.get("default_level") is not None:
        out["default_level"] = fx.norm_level(p["default_level"])
    if p.get("mode") is not None:
        out["mode"] = p["mode"] if p["mode"] in ("misto", "tempo", "ripetizioni") else "misto"
    if p.get("rules_text") is not None:
        out["rules_text"] = p["rules_text"].strip()[:2000]
    if "duration_min" in out and (out.get("start_min", 0) + out.get("end_min", 0)) >= out["duration_min"]:
        raise HTTPException(status_code=400, detail="Inizio e fine non possono occupare tutta la lezione")
    return out


@api_router.get("/fitness/lesson-types")
async def list_lesson_types(current: User = Depends(get_current_user)):
    await _ensure_fitness_base(current)
    return await db.lesson_types.find({"owner_key": _fitness_owner_key(current)}, {"_id": 0}).sort("created_at", 1).to_list(100)


@api_router.post("/fitness/lesson-types")
async def create_lesson_type(payload: LessonTypePayload, current: User = Depends(get_current_user)):
    data = {**fx.BASE_LESSON_TYPES[0], "name": "", **_clean_lesson_type(payload.model_dump())}
    if not data["name"]:
        raise HTTPException(status_code=400, detail="Scrivi il nome del tipo di lezione")
    doc = {"id": f"ltype_{uuid.uuid4().hex[:12]}", "owner_key": _fitness_owner_key(current), **data, "builtin": False,
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db.lesson_types.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/fitness/lesson-types/{type_id}")
async def update_lesson_type(type_id: str, payload: LessonTypePayload, current: User = Depends(get_current_user)):
    t = await db.lesson_types.find_one({"id": type_id, "owner_key": _fitness_owner_key(current)}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Tipo di lezione non trovato")
    upd = _clean_lesson_type(payload.model_dump())
    merged = {**t, **upd}
    if merged["start_min"] + merged["end_min"] >= merged["duration_min"]:
        raise HTTPException(status_code=400, detail="Inizio e fine non possono occupare tutta la lezione")
    if upd:
        await db.lesson_types.update_one({"id": type_id}, {"$set": upd})
    return merged


@api_router.delete("/fitness/lesson-types/{type_id}")
async def delete_lesson_type(type_id: str, current: User = Depends(get_current_user)):
    r = await db.lesson_types.delete_one({"id": type_id, "owner_key": _fitness_owner_key(current)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tipo di lezione non trovato")
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
    if isinstance(payload.get("blocks"), list):   # a generated lesson changed by hand: checked like the model's
        payload = {**payload, **(await _relesson_blocks(current, lesson_id, payload["blocks"]))}
    await db.lesson_templates.update_one({"id": lesson_id, **_editable_query(current)}, {"$set": payload})
    doc = await db.lesson_templates.find_one({"id": lesson_id, **_editable_query(current)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Lezione non trovata")
    return doc


async def _relesson_blocks(current: User, lesson_id: str, blocks: list) -> dict:
    """Blocks edited in the app: known exercises only, within their limits, totals recomputed."""
    doc = await db.lesson_templates.find_one({"id": lesson_id, **_editable_query(current)}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Lezione non trovata")
    ids = [b.get("exercise_id") for b in blocks if isinstance(b, dict)]
    by_id = {e["id"]: e for e in await db.exercises.find({**_visible_query(current), "id": {"$in": ids}}, {"_id": 0}).to_list(500)}
    order = {"inizio": 0, "centrale": 1, "fine": 2}
    seq = []
    for b in blocks:
        if not isinstance(b, dict) or b.get("exercise_id") not in by_id:
            continue
        x = fx.fix_block(b, by_id[b["exercise_id"]], "misto")
        x["phase"] = b.get("phase") if b.get("phase") in order else "centrale"
        seq.append(x)
    seq.sort(key=lambda x: order[x["phase"]])   # stable: the order inside a phase is kept
    rest = int(doc.get("rest_sec") or fx.DEFAULT_REST_SEC)
    participants = int(doc.get("participants") or 1)
    return {"blocks": seq, "total_sec": sum(fx.block_seconds(x, rest) for x in seq),
            "equipment_needed": fx.equipment_summary(seq, participants),
            "exercises": [{"exercise_id": x["exercise_id"], "notes": x.get("notes", "")} for x in seq]}


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


class GenerateLessonV2Payload(BaseModel):
    prompt: str
    type_id: Optional[str] = None
    replace_id: Optional[str] = None     # a change to this lesson ("fallo per 15 persone"): rebuilt in its place


async def _lesson_llm(system: str, prompt: str, current: User, model: str, feature: str = "creazione_lezioni") -> str:
    """One model call of the lesson builder (kept apart: the tests replace it)."""
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"lesson_{uuid.uuid4().hex[:8]}", system_message=system,
                   user_id=current.user_id, feature=feature, channel="web", trigger="utente", org_id=current.org_id
                   ).with_model("openai", model)
    return await chat.send_message(UserMessage(text=prompt))


def _json_in(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise ValueError("no JSON")
    return json.loads(m.group(0))


async def _read_lesson_request(current: User, prompt: str, type_names: list) -> dict:
    """The request's parameters: the model reads them (types, level words, body parts said in
    other words); the numbers it gives are checked against the ones in the text."""
    found = {}
    for line in prompt.split("\n"):   # a change asked later ("Modifiche richieste: ...") wins over the request
        found.update(fx.parse_request_fallback(line))
    system = (
        "Leggi la richiesta di un istruttore di fitness che vuole creare una lezione ed estrai i parametri. "
        f"Tipi di lezione disponibili: {', '.join(type_names) or 'nessuno'}.\n"
        "Rispondi SOLO con JSON: {\"type\": \"uno dei tipi o vuoto\", \"participants\": numero o null, "
        "\"duration_min\": numero o null, \"level\": \"basso|medio|alto\" o null, "
        "\"body_parts\": [\"gambe\", \"braccia\", \"glutei\", ...] (vuoto se tutto il corpo), "
        "\"mode\": \"tempo|ripetizioni|misto\" o null}. Solo ciò che è detto, mai inventare."
    )
    try:
        got = _json_in(await _lesson_llm(system, prompt, current, "gpt-4o-mini"))
    except Exception:
        logger.exception("lesson request reading failed, using the plain reading")
        got = {}
    out = {"type": str(got.get("type") or "").strip()}
    for k in ("participants", "duration_min"):
        v = _int_or_none(got.get(k))
        out[k] = found.get(k) if found.get(k) else v
    out["level"] = fx.norm_level(got.get("level")) or found.get("level")
    parts = [str(x).strip().lower() for x in (got.get("body_parts") or []) if str(x).strip()]
    out["body_parts"] = parts or found.get("body_parts") or []
    out["mode"] = got.get("mode") if got.get("mode") in ("tempo", "ripetizioni", "misto") else found.get("mode")
    return out


def _exercise_line(e: dict, participants: int) -> str:
    t, r = e.get("timed") or {}, e.get("reps") or {}
    eq = f"{e['equipment']} x{e.get('equipment_per_person')} a persona" if e.get("equipment") else "corpo libero"
    bits = [f"id={e['id']}", e["name"], f"parte={e.get('body_part') or '-'}", f"livello={e.get('level') or '-'}", eq]
    if t.get("allowed", True):
        bits.append(f"a tempo: serie {t.get('min_sets')}-{t.get('max_sets')}, {t.get('min_sec')}-{t.get('max_sec')} s")
    if r.get("allowed", True):
        bits.append(f"a ripetizioni: serie {r.get('min_sets')}-{r.get('max_sets')}, ripetizioni {r.get('min_reps')}-{r.get('max_reps')}")
    if e.get("notes"):
        bits.append(f"nota: {e['notes']}")
    return " | ".join(str(b) for b in bits)


@api_router.post("/fitness/generate-lesson")
async def generate_lesson(payload: GenerateLessonV2Payload, current: User = Depends(get_current_user)):
    return await _generate_lesson(current, payload.prompt, payload.type_id, payload.replace_id)


async def _generate_lesson(current: User, prompt: str, type_id: Optional[str] = None, replace_id: Optional[str] = None) -> dict:
    """The lesson from the request + the rules of its type + the exercises and the equipment
    the studio has (see fitness.py for what is decided here and what the model chooses).
    With replace_id the request is a change to that lesson: its request + the change, rebuilt
    in its place (same id, still a favorite if it was)."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Descrivi la lezione che vuoi creare")
    old = None
    if replace_id:
        old = await db.lesson_templates.find_one({"id": replace_id, **_editable_query(current)}, {"_id": 0})
        if not old:
            raise HTTPException(status_code=404, detail="Lezione non trovata")
        prompt = f"{(old.get('request') or old.get('name') or '').strip()}\nModifiche richieste: {prompt}"[:3000]
        type_id = type_id or old.get("type_id")
    await _ensure_fitness_base(current)
    owner = _fitness_owner_key(current)
    types = await db.lesson_types.find({"owner_key": owner}, {"_id": 0}).sort("created_at", 1).to_list(100)
    if not types:
        raise HTTPException(status_code=400, detail="Crea prima un tipo di lezione (es. Funzionale) con le sue regole")
    exercises = await db.exercises.find(_visible_query(current), {"_id": 0}).to_list(3000)
    inventory = fx.inventory_map(await db.fitness_equipment.find({"owner_key": owner}, {"_id": 0}).to_list(500))
    guidelines = ((await db.lesson_guidelines.find_one({"owner_key": owner}, {"_id": 0})) or {}).get("text", "").strip()

    req = await _read_lesson_request(current, prompt, [t["name"] for t in types])
    ltype = next((t for t in types if t["id"] == type_id), None) \
        or next((t for t in types if req["type"] and t["name"].lower() == req["type"].lower()), None) \
        or next((t for t in types if t["name"].lower() in prompt.lower()), None) or types[0]
    participants = req["participants"] or ltype.get("default_participants") or 10
    level = req["level"] or fx.norm_level(ltype.get("default_level"))
    duration = req["duration_min"] or ltype.get("duration_min") or 40
    parts = req["body_parts"]
    mode = req["mode"] or ltype.get("mode") or "misto"
    rest = int(ltype.get("rest_sec") if ltype.get("rest_sec") is not None else fx.DEFAULT_REST_SEC)
    start_min, end_min = int(ltype.get("start_min") or 0), int(ltype.get("end_min") or 0)
    budgets = {"inizio": start_min * 60, "fine": end_min * 60, "centrale": max(60, duration * 60 - (start_min + end_min) * 60)}

    cand = fx.candidates(exercises, ltype.get("activity") or "", level, parts, participants, inventory)
    pools = {"inizio": cand[ltype.get("start_kind") or "stretching"] if start_min else [],
             "centrale": cand["esercizio"],
             "fine": cand[ltype.get("end_kind") or "stretching"] if end_min else []}
    if not pools["centrale"]:
        raise HTTPException(status_code=400, detail="Non trovo esercizi adatti" + (f" per {', '.join(parts)}" if parts else "")
                            + (f" al livello {level}" if level else "") + f" con gli attrezzi disponibili per {participants} persone.")

    listing = "\n".join(f"[{ph}] " + _exercise_line(e, participants) for ph, pool in pools.items() for e in pool)
    system = (
        "Sei un istruttore di fitness esperto. Componi una lezione SCEGLIENDO SOLO tra gli esercizi elencati (usa i loro id), "
        "rispettando le regole. Fasi e tempo a disposizione:\n"
        + "".join(f"- {ph}: {budgets[ph] // 60} minuti\n" for ph in ("inizio", "centrale", "fine") if budgets[ph])
        + f"Partecipanti: {participants}. Livello: {level or 'misto'}. Parti del corpo: {', '.join(parts) or 'tutto il corpo'}. "
        f"Modalità delle serie: {mode} (tempo = secondi, ripetizioni = numero di ripetizioni). Pausa tra le serie: {rest} secondi.\n"
        f"Tipo di lezione: {ltype['name']}." + (f" Regole del tipo: {ltype['rules_text']}" if ltype.get("rules_text") else "") + "\n"
        + (f"Regole generali dello studio: {guidelines}\n" if guidelines else "")
        + "Alterna le parti del corpo e varia gli esercizi; per ogni esercizio resta dentro i limiti di serie, secondi e "
        "ripetizioni indicati. Gli esercizi con [inizio] vanno all'inizio, [fine] alla fine, [centrale] nel corpo della lezione.\n"
        "Se la richiesta contiene \"Modifiche richieste\", quelle valgono sopra la richiesta iniziale.\n"
        f"Esercizi disponibili:\n{listing}\n\n"
        "Rispondi SOLO con JSON: {\"title\": \"nome breve della lezione\", \"notes\": \"indicazioni per l'istruttore (breve)\", "
        "\"blocks\": [{\"phase\": \"inizio|centrale|fine\", \"exercise_id\": \"...\", \"mode\": \"tempo|ripetizioni\", "
        "\"sets\": n, \"seconds\": n, \"reps\": n, \"notes\": \"\"}]}"
    )
    try:
        plan = _json_in(await _lesson_llm(system, prompt, current, "gpt-4o"))
    except Exception:
        logger.exception("lesson composition failed, building it from the rules alone")
        plan = {}
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="creazione_lezioni", channel="web", trigger="utente", org_id=current.org_id)

    # the model's answer, checked: only the candidates of each phase, within their limits, fitted to the time
    by_id = {e["id"]: e for pool in pools.values() for e in pool}
    pool_ids = {ph: {e["id"] for e in pool} for ph, pool in pools.items()}
    blocks = {ph: [] for ph in pools}
    for b in plan.get("blocks") or []:
        ph = b.get("phase") if b.get("phase") in pools else None
        if not ph or b.get("exercise_id") not in pool_ids[ph] or any(x["exercise_id"] == b["exercise_id"] for x in blocks[ph]):
            continue
        blocks[ph].append(fx.fix_block({**b, "phase": ph}, by_id[b["exercise_id"]], mode))
    for ph in pools:
        if budgets[ph] and pools[ph]:
            blocks[ph] = fx.fit_phase(blocks[ph], budgets[ph], rest, by_id, pools[ph], mode)
            for x in blocks[ph]:
                x["phase"] = ph
    seq = blocks["inizio"] + blocks["centrale"] + blocks["fine"]
    total = sum(fx.block_seconds(x, rest) for x in seq)
    notes = (plan.get("notes") or "").strip()[:600]
    lesson = {
        "id": f"lsn_{uuid.uuid4().hex[:12]}", "kind": "v2",
        "name": (plan.get("title") or f"{ltype['name']} {', '.join(parts) or 'total body'}").strip()[:120],
        "type_id": ltype["id"], "type_name": ltype["name"], "activity": ltype.get("activity") or "",
        "participants": participants, "level": level, "body_parts": parts, "duration_min": duration, "mode": mode,
        "rest_sec": rest, "blocks": seq, "total_sec": total,
        "equipment_needed": fx.equipment_summary(seq, participants), "excluded_equipment": cand["excluded_equipment"][:20],
        "request": prompt, "notes": notes,
        # older fields, for the lists that still read them
        "discipline": "altro", "exercises": [{"exercise_id": x["exercise_id"], "notes": x.get("notes", "")} for x in seq],
        "visibility": "org" if current.org_id else "private", "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(lesson, current)
    if old:   # the same lesson, changed: its id, date, sharing and star are kept
        lesson.update({k: old[k] for k in ("id", "created_at", "visibility", "org_id", "favorite") if k in old})
        lesson["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.lesson_templates.delete_one({"id": old["id"]})
    await db.lesson_templates.insert_one(lesson)
    lesson.pop("_id", None)
    return {"lesson": lesson, "new_exercises_created": 0, "replaced": bool(old), "message": fx.lesson_message(lesson, changed=bool(old))}


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
        if await _storage_targets(current.user_id):
            folder_name = patient_name if patient_name else "Report generici"
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(docx_bytes)
                tmp_path = tmp.name
            try:
                result = await _storage_save(
                    current.user_id, folder_name, tmp_path, fname,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                drive_link = result.get("web_view_link")
                drive_folder_name = folder_name
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass
    except Exception:
        logger.exception("vet report drive/onedrive save failed")

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


# ============ ARTIGIANO: REPORT (primo sopralluogo, ...) ============
def _sysval(data: dict, mapping: dict, base_key: str) -> str:
    return str((data or {}).get((mapping or {}).get(base_key, base_key)) or "").strip()


def _norm_title(t: str) -> str:
    return " ".join(re.findall(r"[\wàèéìòù]+", (t or "").lower()))


async def _find_or_create_commessa(clienti: dict, client: dict, job_title: str, address: str, text: str,
                                   description: str) -> tuple[Optional[dict], bool]:
    """The commessa (sub-item of the client) this report is about: one whose title is named in
    the text or equals the job title; otherwise a new one in stato "preventivo"."""
    smap = clienti.get("system_sub_map") or {}
    tkey = smap.get("titolo", "titolo")
    subs = await db.collection_sub_items.find({"collection_id": clienti["id"], "item_id": client["id"]}, {"_id": 0}).to_list(500)
    low, jt = _norm_title(text), _norm_title(job_title)
    for sub in subs:
        title = _norm_title((sub.get("data") or {}).get(tkey))
        if title and (title == jt or re.search(rf"\b{re.escape(title)}\b", low)):
            return sub, False
    if not job_title:
        return None, False
    data = {tkey: job_title, smap.get("stato", "stato"): "preventivo"}
    if address:
        data[smap.get("indirizzo_cantiere", "indirizzo_cantiere")] = address
    if description:
        data[smap.get("descrizione", "descrizione")] = description
    doc = {"id": f"sub_{uuid.uuid4().hex[:12]}", "collection_id": clienti["id"], "item_id": client["id"],
           "data": data, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.collection_sub_items.insert_one(doc)
    doc.pop("_id", None)
    return doc, True


@api_router.get("/work/templates")
async def list_work_templates(current: User = Depends(get_current_user)):
    custom = await db.work_templates.find(_visible_query(current), {"_id": 0}).sort("created_at", -1).to_list(200)
    builtin = [{"key": k, "name": v["name"], "hint": v.get("hint", "")} for k, v in work_reports.BUILTIN_TEMPLATES.items()]
    cr = work_reports.COMMESSA_REPORT   # not dictated: made from the diary, with its own options
    builtin.append({"key": cr["key"], "name": cr["name"], "hint": cr["hint"], "commessa": True,
                    "parts": [{"key": k, "name": n} for k, n in work_reports.COMMESSA_PARTS], "default_parts": work_reports.COMMESSA_DEFAULT})
    return {"builtin": builtin, "custom": custom}


@api_router.post("/work/templates")
async def upload_work_template(file: UploadFile = File(...), name: str = Form(...), current: User = Depends(get_current_user)):
    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        sections = vet_reports.extract_template_structure(tmp_path)
    except Exception as e:
        logger.exception("work template parse failed")
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il template: {e}")
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass
    doc = {
        "id": f"wtpl_{uuid.uuid4().hex[:12]}",
        "name": name.strip() or (file.filename or "Template"),
        "sections": sections,
        "source_filename": file.filename,
        "visibility": "org" if current.org_id else "private",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _stamp_owner_fields(doc, current)
    await db.work_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.delete("/work/templates/{template_id}")
async def delete_work_template(template_id: str, current: User = Depends(get_current_user)):
    r = await db.work_templates.delete_one({"id": template_id, **_editable_query(current)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template non trovato")
    return {"ok": True}


@api_router.post("/work/generate-report")
async def generate_work_report(payload: GenerateWorkReportPayload, current: User = Depends(get_current_user)):
    opts = {"include": payload.include, "period": payload.period, "date_from": payload.date_from, "date_to": payload.date_to}
    return await _generate_work_report(current, payload.text, payload.report_type, payload.client_item_id, payload.new_client,
                                       commessa_opts=opts)


async def _generate_work_report(current: User, text: str, report_type: str = "sopralluogo", client_item_id: Optional[str] = None,
                                new_client: bool = False, channel: str = "web", commessa_opts: Optional[dict] = None) -> dict:
    """The artigiano's report from a dictation. The client is recognized deterministically in the
    Clienti list (several clients with that name -> {"status": "ambiguous_client", "candidates"}
    and the caller re-calls with client_item_id, or new_client); a client or a commessa that
    isn't there yet is added (commessa in stato "preventivo"). The .docx goes to the report
    archive, to Drive/OneDrive in mAIPAL/Clienti/<cliente>/<commessa> and to Telegram."""
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Descrivi il sopralluogo o l'intervento")
    # the message says which report it is ("SAL del bagno", "fammi il report della commessa ..."):
    # that wins over the type selected in the chat, which only counts when the message doesn't say
    custom = await db.work_templates.find(_visible_query(current), {"_id": 0, "id": 1, "name": 1}).to_list(200)
    said_type = work_reports.detect_report_type(text, custom)
    from_text = bool(said_type) and said_type != report_type
    report_type = said_type or report_type
    if report_type == work_reports.COMMESSA_REPORT["key"]:   # from the diary, never dictated
        rep = await _generate_commessa_report(current, CommessaReportPayload(text=text, **(commessa_opts or {})), channel)
        return {**rep, "type_from_text": from_text}
    if report_type in work_reports.BUILTIN_TEMPLATES:
        template_name = work_reports.BUILTIN_TEMPLATES[report_type]["name"]
        skeleton = work_reports.BUILTIN_TEMPLATES[report_type]["sections"]
    else:
        tmpl = await db.work_templates.find_one({"id": report_type, **_visible_query(current)}, {"_id": 0})
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template non trovato")
        template_name, skeleton = tmpl["name"], tmpl["sections"]

    clienti = await _ensure_clienti_list(current)
    fmap = clienti.get("system_map") or {}
    name_key = fmap.get("nome", "nome")
    clients = await db.collection_items.find({"collection_id": clienti["id"]}, {"_id": 0, "embedding": 0}).to_list(2000)
    client = None
    if client_item_id:
        client = next((c for c in clients if c["id"] == client_item_id), None)
        if not client:
            raise HTTPException(status_code=404, detail="Cliente non trovato")
    elif not new_client:
        matches = work_reports.find_matching_clients(text, clients, name_key)
        if len(matches) > 1:
            return {"status": "ambiguous_client", "text": text, "report_type": report_type, "candidates": [
                {"item_id": c["id"], "name": _sysval(c.get("data"), fmap, "nome"),
                 "address": _sysval(c.get("data"), fmap, "indirizzo"), "phone": _sysval(c.get("data"), fmap, "telefono")}
                for c in matches]}
        client = matches[0] if matches else None

    try:
        interpreted = await work_reports.interpret(text, skeleton, user_name=current.name or "", user_id=current.user_id, channel=channel,
                                                   report_name=template_name)
    except Exception as e:
        logger.exception("work report interpretation failed")
        raise HTTPException(status_code=500, detail=f"Generazione fallita: {e}")
    sections, said = interpreted["sections"], interpreted["client"]
    said = _really_said(said, text)
    if not said.get("name") and not client:
        work_reports.clear_field(sections, "Cliente")   # a name the model made up stays out of the report too
    for label, key in (("Telefono", "phone"), ("Email", "email")):
        if not said.get(key):
            work_reports.clear_field(sections, label)

    client_created = False
    if not client and said.get("name"):
        # the model may have caught a client the name match missed (e.g. "dalla signora Bianchi")
        again = work_reports.find_matching_clients(said["name"], clients, name_key) if not new_client else []
        exact = [c for c in again if _norm_title(_sysval(c.get("data"), fmap, "nome")) == _norm_title(said["name"])]
        if len(exact) == 1:
            client = exact[0]
        else:
            data = {name_key: said["name"]}
            for base, val in (("telefono", said.get("phone")), ("email", said.get("email")), ("indirizzo", said.get("address"))):
                if val:
                    data[fmap.get(base, base)] = val
            orders = [c.get("sort_order") for c in clients if c.get("sort_order") is not None]
            client = {"id": f"item_{uuid.uuid4().hex[:12]}", "collection_id": clienti["id"], "data": data,
                      "visibility": clienti.get("visibility", "private"), "sort_order": max(orders, default=-1) + 1,
                      "created_at": datetime.now(timezone.utc).isoformat()}
            _stamp_owner_fields(client, current)
            await db.collection_items.insert_one(client)
            client.pop("_id", None)
            client_created = True
    elif client:
        # complete the client's card with what was said, never overwriting what's there
        data = dict(client.get("data") or {})
        for base, val in (("telefono", said.get("phone")), ("email", said.get("email")), ("indirizzo", said.get("address"))):
            if val and not _sysval(data, fmap, base):
                data[fmap.get(base, base)] = val
        if data != (client.get("data") or {}):
            await db.collection_items.update_one({"id": client["id"]}, {"$set": {"data": data, "embedding": None}})
            client["data"] = data

    client_name = _sysval(client.get("data"), fmap, "nome") if client else ""
    commessa, commessa_created = None, False
    if client:
        oggetto = next((s["fields"].get("Oggetto dell'intervento") for s in sections if "Oggetto dell'intervento" in s["fields"]), "")
        site = said.get("address") or _sysval(client.get("data"), fmap, "indirizzo")
        commessa, commessa_created = await _find_or_create_commessa(clienti, client, interpreted["job_title"], site, text, oggetto or "")
    smap = clienti.get("system_sub_map") or {}
    commessa_title = _sysval(commessa.get("data"), smap, "titolo") if commessa else ""

    # what the app knows wins over what the model heard
    if client:
        work_reports.set_field(sections, "Cliente", client_name)
        work_reports.set_field(sections, "Telefono", _sysval(client.get("data"), fmap, "telefono"))
        work_reports.set_field(sections, "Email", _sysval(client.get("data"), fmap, "email"))
    if commessa:
        work_reports.set_field(sections, "Indirizzo del cantiere", _sysval(commessa.get("data"), smap, "indirizzo_cantiere"), overwrite=False)
    if client:
        work_reports.set_field(sections, "Indirizzo del cantiere", _sysval(client.get("data"), fmap, "indirizzo"), overwrite=False)
    work_reports.set_field(sections, "Eseguito da", current.name or "", overwrite=False)
    work_reports.set_field(sections, "Data", datetime.now(work_reports.LOCAL_TZ).strftime("%d/%m/%Y"), overwrite=False)
    if commessa and not commessa_created and report_type in ("sal", "fine_lavori"):
        await _fill_report_from_diary(sections, report_type, commessa["id"], _sysval(commessa.get("data"), smap, "data_inizio"))

    company = ""
    if current.org_id:
        org = await db.organizations.find_one({"id": current.org_id}, {"_id": 0, "name": 1})
        company = (org or {}).get("name") or ""
    docx_bytes = work_reports.build_docx(template_name, client_name or None, commessa_title or None, sections, company=company)
    stamp = datetime.now(work_reports.LOCAL_TZ).strftime("%Y%m%d_%H%M")
    fname = f"{template_name} - {client_name or 'senza cliente'} - {stamp}.docx".replace("/", "-")

    if client:
        folder, subs = (clienti.get("name") or vx.CLIENTI_NAME), [client_name] + ([commessa_title] if commessa_title else [])
    else:
        folder, subs = "Report", []
    drive_link, drive_folder, telegram_sent = await _deliver_work_report(
        current, docx_bytes, fname, folder, subs, f"📄 {template_name}" + (f" — {client_name}" if client_name else ""))

    import base64 as _b64
    report_doc = {
        "id": f"wrep_{uuid.uuid4().hex[:12]}",
        "status": "ok",
        "user_id": current.user_id,
        "org_id": current.org_id,
        "report_type": report_type,
        "type_from_text": from_text,   # the message named another type than the selected one
        "template_name": template_name,
        "collection_id": clienti["id"],
        "client_item_id": client["id"] if client else None,
        "client_name": client_name or None,
        "client_created": client_created,
        "commessa_id": commessa["id"] if commessa else None,
        "commessa_title": commessa_title or None,
        "commessa_created": commessa_created,
        "transcript": text,
        "sections": sections,
        "summary": interpreted.get("summary") or work_reports.summary_of(sections),
        "company": company,
        "drive_path": [folder] + subs,
        "version": 1,
        "docx_b64": _b64.b64encode(docx_bytes).decode("ascii"),
        "docx_filename": fname,
        "drive_link": drive_link,
        "drive_folder": drive_folder,
        "telegram_sent": telegram_sent,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.work_reports.insert_one(report_doc)
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="creazione_report", channel=channel, trigger="utente", org_id=current.org_id)
    report_doc.pop("_id", None)
    report_doc.pop("docx_b64", None)
    if commessa:
        head = f"Report «{template_name}» generato da {_first_name(current.name)}" + (" (commessa aperta da questo report)" if commessa_created else "") + "."
        await _log_report_event(current, report_doc, head + (f"\n{report_doc['summary']}" if report_doc["summary"] else ""), channel)
    return report_doc


async def _log_report_event(current: User, rep: dict, text: str, channel: str = "web") -> None:
    """A report made (or changed) for a commessa, as a line of its diary: which report, a summary,
    who and when. Not an entry of work (no hours): the diary shows it like a change of state."""
    try:
        log = {"id": f"jlog_{uuid.uuid4().hex[:12]}", "kind": "report", "report_id": rep["id"],
               "report_type": rep.get("report_type"), "template_name": rep.get("template_name"), "report_version": rep.get("version") or 1,
               "user_id": current.user_id, "org_id": current.org_id, "author_name": _first_name(current.name),
               "collection_id": rep.get("collection_id"), "collection_name": None,
               "client_item_id": rep.get("client_item_id"), "client_name": rep.get("client_name"),
               "commessa_id": rep["commessa_id"], "commessa_title": rep.get("commessa_title"), "date": jl.today_local().isoformat(),
               "raw_text": text, "text": text, "hours": [], "materials": [], "problems": [], "photos": [],
               "channel": channel, "created_at": datetime.now(timezone.utc).isoformat(), "embedding": None}
        await db.job_logs.insert_one(log)
    except Exception:
        logger.exception("report diary line failed")   # the report itself is made: never lose it for this


async def _fill_report_from_diary(sections: list, report_type: str, cid: str, data_inizio: str = "") -> None:
    """SAL and fine lavori: what the diary already knows goes in the fields the dictation left
    empty - for a SAL the period since the last SAL (or the whole job): hours, materials,
    problems, milestones; for the end of works the dates and the total hours."""
    fmt = lambda iso: datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    since = None
    if report_type == "sal":
        prev = await db.work_reports.find({"commessa_id": cid, "report_type": "sal"}, {"_id": 0, "created_at": 1}).to_list(200)
        if prev:
            since = (datetime.fromisoformat(max(p["created_at"] for p in prev)).astimezone(LOCAL_TZ).date() + timedelta(days=1)).isoformat()
    q = {"commessa_id": cid, "kind": None}
    if since:
        q["date"] = {"$gte": since}
    logs = await db.job_logs.find(q, {"_id": 0, "date": 1, "hours": 1, "materials": 1, "problems": 1}).to_list(20000)
    tot = jl.totals(logs)
    days = sorted(lg["date"] for lg in logs if lg.get("date"))
    hours = f"{jl._fmt_num(tot['hours_total'])} h" if tot["hours_total"] else ""
    if report_type == "sal":
        start = since or (days[0] if days else None)
        if start:
            work_reports.set_field(sections, "Periodo di riferimento",
                                   f"dal {fmt(start)} al {datetime.now(LOCAL_TZ).strftime('%d/%m/%Y')}", overwrite=False)
        work_reports.set_field(sections, "Ore impiegate", hours, overwrite=False)
        work_reports.set_field(sections, "Materiali impiegati", "\n".join(f"- {m}" for m in jl.materials_line(tot["materials"]).split(", ") if m), overwrite=False)
        work_reports.set_field(sections, "Problemi riscontrati", "\n".join(f"- {p['text']}" for p in tot["problems"][:15]), overwrite=False)
        ms = await _commessa_milestones(cid)
        work_reports.set_field(sections, "Milestone", "\n".join(_ms_report_line(v) for v in ms[:15]), overwrite=False)
    else:
        start = (data_inizio or "")[:10] or (days[0] if days else None)
        if start:
            work_reports.set_field(sections, "Data inizio lavori", fmt(start[:10]), overwrite=False)
        work_reports.set_field(sections, "Data fine lavori", datetime.now(LOCAL_TZ).strftime("%d/%m/%Y"), overwrite=False)
        work_reports.set_field(sections, "Ore complessive", hours, overwrite=False)


def _ms_report_line(v: dict) -> str:
    fmt = lambda iso: datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    return (f"- {v['title']}: " + (f"completata il {fmt(v['done_date'])}" if v["status"] == "done" else
            f"in ritardo (prevista il {fmt(v['due_date'])})" if v["status"] == "late" else f"prevista entro il {fmt(v['due_date'])}"))


def _report_period(payload: "CommessaReportPayload", today: date) -> Optional[tuple]:
    """(from, to) of a report di commessa, or None for the whole job: the period said in the
    message first, then the one chosen with the chips."""
    said = work_reports.parse_period(payload.text, today)
    if said:
        return said
    p = payload.period or "all"
    if p == "last7":
        return today - timedelta(days=6), today
    if p == "last30":
        return today - timedelta(days=29), today
    if p == "prev_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if p == "custom":
        try:
            a = date.fromisoformat((payload.date_from or "")[:10]) if payload.date_from else None
            b = date.fromisoformat((payload.date_to or "")[:10]) if payload.date_to else today
        except ValueError:
            raise HTTPException(status_code=400, detail="Date del periodo non valide")
        if a and a > b:
            a, b = b, a
        return (a, b) if (a or payload.date_to) else None   # only "up to": from the job's first day
    return None


@api_router.post("/work/commessa-report")
async def generate_commessa_report(payload: CommessaReportPayload, current: User = Depends(get_current_user)):
    return await _generate_commessa_report(current, payload)


async def _generate_commessa_report(current: User, payload: CommessaReportPayload, channel: str = "web") -> dict:
    """A report of a commessa for a period, with the parts the user picked (state summary, work
    done, hours, problems, materials, milestones, costs) - all from its diary: nothing dictated,
    nothing created (no client, no commessa). Several commesse fit the text -> {"status":
    "pick_commessa", "candidates"} and the caller re-calls with commessa_id."""
    text = (payload.text or "").strip()
    clienti = await _clienti_list(current)
    if not clienti:
        raise HTTPException(status_code=400, detail="Non hai ancora commesse: il report di commessa si fa dal loro diario")
    if payload.commessa_id:   # (also one shared with them, even read-only: a report only reads it)
        clienti, sub, client = await _commessa_or_404(current, payload.commessa_id, write=False)
        view = _commessa_view(sub, client, clienti)
    else:
        res = await _resolve_commessa(clienti, text, "", "", None)
        view = res.get("commessa")
        if not view:
            rows = res.get("pick") or []
            if res.get("reason") == "clients":   # several clients with that name: all their commesse
                ids = {c["item_id"] for c in res.get("clients") or []}
                theirs = [c for c in (await _all_commesse(clienti))[0] if c["client_item_id"] in ids]
                rows = _pick_rows(theirs, await _last_activity([c["id"] for c in theirs]))
            if res.get("create_for"):
                name = _sysval(res["create_for"].get("data"), clienti.get("system_map") or {}, "nome")
                raise HTTPException(status_code=400, detail=f"{name} non ha ancora commesse: non c'è un diario da cui fare il report")
            if not rows:
                raise HTTPException(status_code=400, detail="Non hai ancora commesse: il report di commessa si fa dal loro diario")
            return {"status": "pick_commessa", "message": "Di quale commessa faccio il report?", "candidates": rows, "text": text}
    cid = view["id"]

    today = jl.today_local()
    period = _report_period(payload, today)
    valid = {k for k, _ in work_reports.COMMESSA_PARTS}
    wants = work_reports.parts_from_text(text) or [k for k in payload.include if k in valid] or list(work_reports.COMMESSA_DEFAULT)
    q = {"commessa_id": cid}
    if period:
        q["date"] = {"$lte": period[1].isoformat(), **({"$gte": period[0].isoformat()} if period[0] else {})}
    logs = await db.job_logs.find(q, {"_id": 0, "embedding": 0}).to_list(20000)
    logs.sort(key=lambda lg: (lg.get("date") or "", lg.get("created_at") or ""))
    work = [lg for lg in logs if not lg.get("kind")]
    tot = jl.totals(work)
    start, end = period or (None, today)
    if not start:   # the whole job: from its start date, or its first entry
        firsts = [x for x in ((view.get("data_inizio") or "")[:10], tot["first_day"]) if x and re.fullmatch(r"\d{4}-\d{2}-\d{2}", x)]
        start = min(date.fromisoformat(min(firsts)), end) if firsts else end
    plabel = work_reports.period_label(start, end)
    fmt = lambda iso: datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    none = "Nessun dato registrato nel periodo"

    milestones = await _commessa_milestones(cid) if ("milestone" in wants or "stato" in wants) else []
    hours = f"{jl._fmt_num(tot['hours_total'])} h" if tot["hours_total"] else ""
    problems = "\n".join(f"- {fmt(p['date'])}: {p['text']}" if p.get("date") else f"- {p['text']}" for p in tot["problems"][:40])
    materials = "\n".join(f"- {m}" for m in jl.materials_line(tot["materials"]).split(", ") if m)

    written = {}
    if "stato" in wants or "attivita" in wants:
        facts = "; ".join(x for x in (
            hours and f"ore lavorate {hours}",
            tot["hours_pending_total"] and f"ore da approvare (non conteggiate) {jl._fmt_num(tot['hours_pending_total'])} h", tot["problems"] and f"{len(tot['problems'])} problemi registrati",
            milestones and "milestone: " + milestones_line(milestones)) if x)
        diary = "\n".join(jl._ctx_line(lg) for lg in logs)[-14000:]
        try:
            written = await work_reports.commessa_summary(view, plabel, diary, facts, wants, request=text,
                                                          user_id=current.user_id, channel=channel)
        except Exception:
            logger.exception("commessa report summary failed")
            written = {}
        if "attivita" in wants and not written.get("attivita"):   # the model failed: the diary's own lines
            written["attivita"] = "\n".join(f"- {fmt(lg['date'])} · {lg.get('author_name') or ''}: {lg.get('text') or ''}"
                                             for lg in work[:60] if lg.get("date"))

    sections = [{"title": "Dati della commessa", "fields": {
        "Cliente": view["client_name"], "Commessa": view["title"], "Indirizzo del cantiere": view["address"],
        "Stato": view["stato"], "Periodo di riferimento": plabel, "Data": today.strftime("%d/%m/%Y"),
        "Redatto da": current.name or ""}}]
    titles = dict(work_reports.COMMESSA_PARTS)
    for key in [k for k, _ in work_reports.COMMESSA_PARTS if k in wants]:
        if key == "stato":
            fields = {"Riassunto": written.get("stato") or none}
        elif key == "attivita":
            fields = {"Lavori del periodo": written.get("attivita") or none}
        elif key == "ore":
            people = "\n".join(f"- {who}: {jl._fmt_num(h)} h" for who, h in sorted(tot["by_person"].items(), key=lambda x: -x[1]))
            days = len({lg["date"] for lg in work if lg.get("date") and lg.get("hours")})
            fields = {"Ore totali": hours or "0 h", "Ore per persona": people or none,
                      "Giorni con ore registrate": str(days) if days else "0"}
            if tot["pending"]:   # written by collaborators, not approved yet: apart, not in the totals
                fields["Ore da approvare (non conteggiate)"] = "\n".join(
                    f"- {fmt(p['date'])} · {p['who']}: {jl._fmt_num(p['hours'])} h" for p in tot["pending"])
        elif key == "problemi":
            fields = {"Problemi riscontrati": problems or "Nessun problema registrato nel periodo"}
        elif key == "materiali":
            fields = {"Materiali impiegati": materials or none}
        elif key == "milestone":
            fields = {"Milestone": "\n".join(_ms_report_line(v) for v in milestones[:20]) or "Nessuna milestone sulla commessa"}
        else:   # costi: the period's hours and materials at the list's rates, the other costs of those days
            econ = await db.job_economics.find_one({"commessa_id": cid}, {"_id": 0}) or {}
            extras = [x for x in econ.get("extras") or [] if not period or start.isoformat() <= (x.get("date") or "")[:10] <= end.isoformat()]
            costs = clienti.get("costs") or {}
            e = jl.economics(work, costs.get("rates"), costs.get("default_rate"), costs.get("prices"), extras,
                             econ.get("budget") if not period else None)
            fields = {"Manodopera": jl._eur(e["labor_total"]), "Materiali": jl._eur(e["materials_total"]),
                      "Altre spese": jl._eur(e["extras_total"]), "Totale costi": jl._eur(e["cost_total"])}
            if e.get("budget"):
                fields["Preventivo"] = jl._eur(e["budget"])
                fields["Margine"] = f"{jl._eur(e['margin'])} ({e['used_pct']:.0f}% del preventivo speso)"
            if not e["complete"]:
                miss = ([f"{jl._fmt_num(e['unpriced_hours'])} h senza tariffa"] if e["unpriced_hours"] else []) + \
                       ([f"{len(e['unpriced_materials'])} materiali senza prezzo"] if e["unpriced_materials"] else [])
                fields["Non conteggiati"] = ", ".join(miss)
        sections.append({"title": titles[key], "fields": fields})

    template_name = work_reports.COMMESSA_REPORT["name"]
    company = ""
    if current.org_id:
        org = await db.organizations.find_one({"id": current.org_id}, {"_id": 0, "name": 1})
        company = (org or {}).get("name") or ""
    docx_bytes = work_reports.build_docx(template_name, view["client_name"] or None, view["title"] or None, sections, company=company)
    stamp = datetime.now(work_reports.LOCAL_TZ).strftime("%Y%m%d_%H%M")
    fname = f"{template_name} - {view['client_name'] or view['title']} - {stamp}.docx".replace("/", "-")
    folder = clienti.get("name") or vx.CLIENTI_NAME
    subs = [x for x in (view["client_name"], view["title"]) if x]
    drive_link, drive_folder, telegram_sent = await _deliver_work_report(
        current, docx_bytes, fname, folder, subs, f"📄 {template_name} — {view['title']}" + (f" ({view['client_name']})" if view["client_name"] else ""))

    import base64 as _b64
    summary = (written.get("stato") or "")[:400] or f"Periodo {plabel}" + (f", {hours}" if hours else "") + \
        (f", {len(tot['problems'])} problemi" if tot["problems"] else "") + "."
    report_doc = {
        "id": f"wrep_{uuid.uuid4().hex[:12]}", "status": "ok", "user_id": current.user_id, "org_id": current.org_id,
        "report_type": "commessa", "template_name": template_name, "collection_id": clienti["id"],
        "client_item_id": view["client_item_id"], "client_name": view["client_name"] or None, "client_created": False,
        "commessa_id": cid, "commessa_title": view["title"], "commessa_created": False,
        "period_from": start.isoformat(), "period_to": end.isoformat(), "period_label": plabel, "include": wants,
        "transcript": text, "sections": sections, "summary": summary, "company": company,
        "drive_path": [folder] + subs, "version": 1,
        "docx_b64": _b64.b64encode(docx_bytes).decode("ascii"), "docx_filename": fname,
        "drive_link": drive_link, "drive_folder": drive_folder, "telegram_sent": telegram_sent,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.work_reports.insert_one(report_doc)
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="creazione_report", channel=channel, trigger="utente", org_id=current.org_id)
    report_doc.pop("_id", None)
    report_doc.pop("docx_b64", None)
    await _log_report_event(current, report_doc, f"Report «{template_name}» ({plabel}) generato da {_first_name(current.name)}.", channel)
    return report_doc


def _really_said(said: dict, text: str) -> dict:
    """Client data the model read, kept only if it is in the dictation: a name, phone or
    e-mail it made up ("Mario Rossi", "333 1234567" as an example) never reaches the list."""
    out = dict(said or {})
    if out.get("name") and not work_reports.said_in(out["name"], text):
        out["name"] = ""
    digits = re.sub(r"\D", "", text or "")
    if out.get("phone") and (len(re.sub(r"\D", "", out["phone"])) < 6 or re.sub(r"\D", "", out["phone"]) not in digits):
        out["phone"] = ""
    if out.get("email") and out["email"].lower() not in (text or "").lower():
        out["email"] = ""
    return out


async def _deliver_work_report(current: User, docx_bytes: bytes, fname: str, folder: str, subs: list, caption: str) -> tuple:
    """Drive/OneDrive (mAIPAL/<folder>/<subs...>) and Telegram. -> (link, folder shown, sent on telegram)"""
    drive_link, drive_folder = None, None
    try:
        if await _storage_targets(current.user_id):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(docx_bytes)
                tmp_path = tmp.name
            try:
                res = await _storage_save(current.user_id, _drive_safe(folder), tmp_path, fname,
                                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document", subfolders=subs)
                drive_link = res.get("web_view_link")
                drive_folder = " / ".join([_drive_safe(folder)] + [_drive_safe(x) for x in subs])
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass
    except Exception:
        logger.exception("work report drive/onedrive save failed")
    telegram_sent = False
    if current.telegram_chat_id:
        try:
            from telegram import Bot
            import io as _io
            await Bot(token=tg.bot_token()).send_document(chat_id=current.telegram_chat_id, document=_io.BytesIO(docx_bytes),
                                                          filename=fname, caption=caption)
            telegram_sent = True
        except Exception:
            logger.exception("work report telegram send failed")
    return drive_link, drive_folder, telegram_sent


class ReviseWorkReportPayload(BaseModel):
    text: str


@api_router.post("/work/reports/{report_id}/revise")
async def revise_work_report(report_id: str, payload: ReviseWorkReportPayload, current: User = Depends(get_current_user)):
    return await _revise_work_report(current, report_id, payload.text)


async def _revise_work_report(current: User, report_id: str, instruction: str, channel: str = "web") -> dict:
    """A change to a report already made, asked in the same chat: the same report, only what was
    asked changes (never a new report, never a new client). The new .docx is "versione N" in
    the same folder; the client's card changes only for data the request states."""
    instruction = (instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Scrivi cosa cambiare nel report")
    rep = await db.work_reports.find_one({"id": report_id, "user_id": current.user_id}, {"_id": 0})
    if not rep:
        raise HTTPException(status_code=404, detail="Report non trovato")
    old = rep.get("sections") or []
    if not old:
        raise HTTPException(status_code=400, detail="Questo report è di una versione precedente dell'app: non posso modificarlo, generane uno nuovo")
    try:
        res = await work_reports.revise(old, instruction, user_id=current.user_id, channel=channel)
    except Exception as e:
        logger.exception("work report revision failed")
        raise HTTPException(status_code=500, detail=f"Modifica fallita: {e}")
    sections, said = res["sections"], _really_said(res["client"], instruction)
    changed = work_reports.changed_fields(old, sections)
    if not changed:
        return {**{k: v for k, v in rep.items() if k != "docx_b64"}, "revised": True, "changed": [],
                "message": "Non ho trovato cosa cambiare: dimmi il campo e il nuovo valore (es. «nei tempi indicativi metti 3 giorni»)."}

    # the client's card: only data the request states; a new name only for a client this report created
    client_name, note = rep.get("client_name") or "", ""
    clienti = await _clienti_list(current)
    client = None
    if clienti and rep.get("client_item_id"):
        client = await db.collection_items.find_one({"id": rep["client_item_id"], "collection_id": clienti["id"]}, {"_id": 0, "embedding": 0})
    if client:
        fmap = clienti.get("system_map") or {}
        data = dict(client.get("data") or {})
        for base, key in (("telefono", "phone"), ("email", "email")):
            if said.get(key):
                data[fmap.get(base, base)] = said[key]
        if said.get("name") and _norm_title(said["name"]) != _norm_title(client_name):
            if rep.get("client_created"):
                data[fmap.get("nome", "nome")] = said["name"]
                client_name = said["name"]
            else:
                note = f"Nella lista Clienti «{client_name}» non l'ho rinominato: se il cliente era sbagliato, generane uno nuovo."
                client_name = said["name"]
        if data != (client.get("data") or {}):
            await db.collection_items.update_one({"id": client["id"]}, {"$set": {"data": data, "embedding": None}})
    elif said.get("name"):
        client_name = said["name"]

    version = int(rep.get("version") or 1) + 1
    docx_bytes = work_reports.build_docx(rep["template_name"], client_name or None, rep.get("commessa_title") or None, sections,
                                         company=rep.get("company") or "")
    base_name = re.sub(r"( - v\d+)?\.docx$", "", rep.get("docx_filename") or rep["template_name"])
    fname = f"{base_name} - v{version}.docx"
    path = rep.get("drive_path") or ([vx.CLIENTI_NAME, rep["client_name"]] + ([rep["commessa_title"]] if rep.get("commessa_title") else [])
                                     if rep.get("client_name") else ["Report"])
    drive_link, drive_folder, telegram_sent = await _deliver_work_report(
        current, docx_bytes, fname, path[0], path[1:], f"📄 {rep['template_name']} (versione {version})" + (f" — {client_name}" if client_name else ""))

    import base64 as _b64
    upd = {"sections": sections, "client_name": client_name or None, "version": version, "docx_filename": fname,
           "docx_b64": _b64.b64encode(docx_bytes).decode("ascii"), "drive_link": drive_link or rep.get("drive_link"),
           "drive_folder": drive_folder or rep.get("drive_folder"), "telegram_sent": telegram_sent,
           "updated_at": datetime.now(timezone.utc).isoformat(), "embedding": None,
           "revisions": (rep.get("revisions") or []) + [{"text": instruction, "changed": changed, "at": datetime.now(timezone.utc).isoformat()}]}
    await db.work_reports.update_one({"id": report_id}, {"$set": upd})
    out = {**{k: v for k, v in rep.items() if k != "docx_b64"}, **{k: v for k, v in upd.items() if k not in ("docx_b64", "embedding")}}
    shown = ", ".join(c.split(" › ")[1] for c in changed[:8]) + ("…" if len(changed) > 8 else "")
    if rep.get("commessa_id"):
        await _log_report_event(current, out, f"Report «{rep['template_name']}» aggiornato alla versione {version} da "
                                f"{_first_name(current.name)}: modificato {shown}.", channel)
    out.update({"revised": True, "changed": changed,
                "message": f"✏️ Report aggiornato (versione {version}): modificato {shown}." + (f"\n{note}" if note else "")})
    return out


@api_router.get("/work/reports")
async def list_work_reports(current: User = Depends(get_current_user)):
    return await db.work_reports.find({"user_id": current.user_id}, {"_id": 0, "docx_b64": 0}).sort("created_at", -1).to_list(200)


@api_router.get("/work/reports/{report_id}/download")
async def download_work_report(report_id: str, current: User = Depends(get_current_user)):
    doc = await db.work_reports.find_one({"id": report_id, "user_id": current.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Report non trovato")
    import base64 as _b64
    from urllib.parse import quote as _q
    filename = doc.get("docx_filename") or "report.docx"
    return Response(
        content=_b64.b64decode(doc["docx_b64"]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"report.docx\"; filename*=UTF-8''{_q(filename)}"},
    )


# ============ ARTIGIANO: DIARIO DI COMMESSA ============
# What was done on each job, day by day, by the owner and (Fase 3) the collaborators: text,
# hours per person, materials, problems, photos. The Clienti list's commesse are the jobs.
JOB_PHOTO_MAX_DIM = 1600
JOB_PHOTO_MAX_BYTES = 900 * 1024
JOB_PICK_MAX = 12
# titles that are ordinary words in any entry ("finiti i lavori"): never matched in the text
JOB_GENERIC_TITLES = {"lavori", "lavoro", "commessa", "cantiere", "intervento", "interventi", "manutenzione", "manutenzioni"}


class JobLogPayload(BaseModel):
    text: str
    images: List[str] = []                    # data URI JPEG, compressed in the browser
    commessa_id: Optional[str] = None         # chosen (commessa page, or answer to "quale commessa?")
    hint_commessa_id: Optional[str] = None    # the one the conversation is about: used if the text names none
    new_client_name: Optional[str] = None     # "è un cliente nuovo": client + commessa created
    client_item_id: Optional[str] = None      # chosen among namesakes: its open commessa, or a new one
    conv_id: Optional[str] = None
    material_choice: Optional[str] = None     # answer to "usati o da prendere?": usato | da_prendere


class JobTodoPayload(BaseModel):
    text: str
    who: Optional[str] = ""                   # who takes care of it
    due_date: Optional[str] = None            # by when (YYYY-MM-DD), optional
    collaborator_id: Optional[str] = None     # assigned to an external collaborator: told on Telegram


class JobTodoPatch(BaseModel):
    text: Optional[str] = None
    who: Optional[str] = None
    due_date: Optional[str] = None            # "" clears it
    done: Optional[bool] = None
    collaborator_id: Optional[str] = None     # "" = no longer a collaborator's


class JobLogPatch(BaseModel):
    text: Optional[str] = None
    date: Optional[str] = None
    hours: Optional[List[dict]] = None
    materials: Optional[List[dict]] = None
    problems: Optional[List[str]] = None


class JobPhotosPayload(BaseModel):
    images: List[str]


class CommessaStatoPayload(BaseModel):
    stato: str


def _first_name(name: Optional[str]) -> str:
    return (name or "").strip().split(" ")[0] or "Io"


async def _clienti_list(current: User) -> Optional[dict]:
    """The Clienti list the user works with: their own, else the active team's, else another team's."""
    found = await db.collections.find({**_lists_query(current), "system_key": vx.CLIENTI_KEY}, {"_id": 0}).to_list(50)
    return min(found, key=lambda c: (c.get("user_id") != current.user_id, c.get("org_id") != current.org_id,
                                     c.get("created_at") or ""), default=None)


def _commessa_view(sub: dict, client: Optional[dict], clienti: dict) -> dict:
    smap, fmap = clienti.get("system_sub_map") or {}, clienti.get("system_map") or {}
    d, cd = sub.get("data") or {}, (client or {}).get("data") or {}
    return {
        "id": sub["id"], "client_item_id": sub.get("item_id"), "collection_id": clienti["id"],
        "title": _sysval(d, smap, "titolo") or "Commessa senza titolo",
        "stato": _sysval(d, smap, "stato") or "",
        "address": _sysval(d, smap, "indirizzo_cantiere") or _sysval(cd, fmap, "indirizzo"),
        "data_inizio": _sysval(d, smap, "data_inizio"), "data_fine": _sysval(d, smap, "data_fine"),
        "descrizione": _sysval(d, smap, "descrizione"),
        "client_name": _sysval(cd, fmap, "nome"), "client_phone": _sysval(cd, fmap, "telefono"),
        "client_email": _sysval(cd, fmap, "email"),
    }


async def _all_commesse(clienti: dict) -> tuple[list, dict]:
    """-> ([commessa view, ...], {client id: client item})"""
    clients = {c["id"]: c for c in await db.collection_items.find({"collection_id": clienti["id"]}, {"_id": 0, "embedding": 0}).to_list(3000)}
    subs = await db.collection_sub_items.find({"collection_id": clienti["id"]}, {"_id": 0, "embedding": 0}).to_list(5000)
    return [_commessa_view(sb, clients.get(sb.get("item_id")), clienti) for sb in subs if sb.get("item_id") in clients], clients


READ_ONLY_COMMESSA = "Questa commessa è condivisa con te in sola lettura: puoi vederla ma non modificarla."


async def _commessa_access(current: User, commessa_id: str) -> Optional[dict]:
    """How the user reaches a commessa: from their Clienti list (as its owner, or as the team's
    list shared with them) or because a team-mate shared that one commessa with them.
    -> {"clienti", "sub", "client", "perm": "owner"|"edit"|"read", "shared_by": name|None} or None"""
    clienti = await _clienti_list(current)
    sub = await db.collection_sub_items.find_one({"id": commessa_id, "collection_id": clienti["id"]}, {"_id": 0}) if clienti else None
    shared_by = None
    if sub:
        perm = _list_perm(clienti, current) or "read"
    else:   # one commessa shared by a team-mate (only while they are in a team together)
        sub = await db.collection_sub_items.find_one({"id": commessa_id, "shared_with": {"$in": [current.user_id]}}, {"_id": 0})
        clienti = await db.collections.find_one({"id": sub.get("collection_id")}, {"_id": 0}) if sub else None
        owner = await db.users.find_one({"user_id": clienti.get("user_id")}, {"_id": 0}) if clienti else None
        me_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0}) or current.model_dump()
        if not owner or not set(_memberships(owner)) & set(_memberships(me_doc)):
            return None
        perm = (sub.get("share_perms") or {}).get(current.user_id) or "edit"
        shared_by = owner.get("name") or ""
    client = await db.collection_items.find_one({"id": sub.get("item_id"), "collection_id": clienti["id"]}, {"_id": 0, "embedding": 0})
    return {"clienti": clienti, "sub": sub, "client": client, "perm": perm, "shared_by": shared_by}


async def _commessa_or_404(current: User, commessa_id: str, write: bool = True) -> tuple[dict, dict, Optional[dict]]:
    """(clienti list, commessa sub-item, client item) of a commessa the user can see - and, when
    `write`, change (a commessa or a list shared read-only: 403)."""
    acc = await _commessa_access(current, commessa_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    if write and acc["perm"] == "read":
        raise HTTPException(status_code=403, detail=READ_ONLY_COMMESSA)
    return acc["clienti"], acc["sub"], acc["client"]


async def _last_activity(commessa_ids: list) -> dict:
    out = {}
    for lg in await db.job_logs.find({"commessa_id": {"$in": commessa_ids}}, {"_id": 0, "commessa_id": 1, "date": 1, "hours": 1, "kind": 1}).to_list(20000):
        cur = out.setdefault(lg["commessa_id"], {"last_day": None, "entries": 0, "hours": 0.0})
        cur["entries"] += 0 if lg.get("kind") else 1
        cur["hours"] = round(cur["hours"] + sum(float(h.get("hours") or 0) for h in lg.get("hours") or []), 2)
        if lg.get("date") and (not cur["last_day"] or lg["date"] > cur["last_day"]):
            cur["last_day"] = lg["date"]
    return out


def _pick_rows(commesse: list, activity: dict) -> list:
    rows = sorted(commesse, key=lambda c: ((activity.get(c["id"]) or {}).get("last_day") or "", c["title"]), reverse=True)
    return [{"commessa_id": c["id"], "title": c["title"], "client_name": c["client_name"], "stato": c["stato"]} for c in rows[:JOB_PICK_MAX]]


async def _resolve_commessa(clienti: dict, text: str, said_client: str, said_commessa: str,
                            hint_id: Optional[str]) -> dict:
    """Which commessa a diary entry is about. Names in the text win; then the conversation's
    commessa; else the user is asked. -> {"commessa": view} | {"create_for": client item,
    "title": ...} | {"pick": [rows], "reason": ...}"""
    commesse, clients = await _all_commesse(clienti)
    fmap = clienti.get("system_map") or {}
    name_key = fmap.get("nome", "nome")
    open_ = [c for c in commesse if c["stato"] != "chiusa"]
    probe = " ".join(x for x in (text, said_client, said_commessa) if x)
    low = _norm_title(probe)

    named_clients = work_reports.find_matching_clients(text, list(clients.values()), name_key)
    if not named_clients and said_client:
        named_clients = work_reports.find_matching_clients(said_client, list(clients.values()), name_key)
    named_ids = {c["id"] for c in named_clients}

    def _title_hit(c):
        t = _norm_title(c["title"])
        return len(t) >= 4 and t not in JOB_GENERIC_TITLES and (re.search(rf"\b{re.escape(t)}\b", low) is not None
                                or (said_commessa and _norm_title(said_commessa) == t))
    by_title = [c for c in commesse if _title_hit(c)]
    if named_ids:
        by_title = [c for c in by_title if c["client_item_id"] in named_ids]
    if by_title:
        opened = [c for c in by_title if c["stato"] != "chiusa"] or by_title
        if len(opened) == 1:
            return {"commessa": opened[0]}
        hinted = next((c for c in opened if c["id"] == hint_id), None)
        if hinted:
            return {"commessa": hinted}
        return {"pick": _pick_rows(opened, await _last_activity([c["id"] for c in opened])), "reason": "several"}

    if named_ids:
        theirs = [c for c in open_ if c["client_item_id"] in named_ids]
        if len(theirs) == 1:
            return {"commessa": theirs[0]}
        if len(theirs) > 1:
            hinted = next((c for c in theirs if c["id"] == hint_id), None)
            if hinted:
                return {"commessa": hinted}
            return {"pick": _pick_rows(theirs, await _last_activity([c["id"] for c in theirs])), "reason": "several"}
        if len(named_ids) == 1:
            closed = [c for c in commesse if c["client_item_id"] in named_ids]
            if not closed:   # the client has no commessa at all: the first one is opened
                return {"create_for": named_clients[0], "title": said_commessa}
            # only closed ones: one of them (work after closing) or a new one - the user says
            return {"pick": _pick_rows(closed, await _last_activity([c["id"] for c in closed])), "reason": "closed",
                    "new_commessa_for": [{"item_id": named_clients[0]["id"], "name": _sysval(named_clients[0].get("data"), fmap, "nome")}]}
        return {"pick": [], "reason": "clients", "clients": [
            {"item_id": c["id"], "name": _sysval(c.get("data"), fmap, "nome")} for c in named_clients]}

    if hint_id:
        hinted = next((c for c in commesse if c["id"] == hint_id), None)
        if hinted:
            return {"commessa": hinted}
    if said_client:   # a client not in the list: the user confirms it's new (no silent duplicates)
        return {"pick": _pick_rows(open_, await _last_activity([c["id"] for c in open_])), "reason": "unknown_client",
                "client_said": said_client}
    if len(open_) == 1:
        return {"commessa": open_[0]}
    return {"pick": _pick_rows(open_, await _last_activity([c["id"] for c in open_])), "reason": "none"}


async def _new_commessa(clienti: dict, client: dict, title: str, stato: str = "in corso") -> dict:
    smap = clienti.get("system_sub_map") or {}
    data = {smap.get("titolo", "titolo"): (title or "Lavori").strip()[:80], smap.get("stato", "stato"): stato,
            smap.get("data_inizio", "data_inizio"): jl.today_local().isoformat()}
    doc = {"id": f"sub_{uuid.uuid4().hex[:12]}", "collection_id": clienti["id"], "item_id": client["id"],
           "data": data, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.collection_sub_items.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _new_client(current: User, clienti: dict, name: str) -> dict:
    fmap = clienti.get("system_map") or {}
    orders = [c.get("sort_order") for c in await db.collection_items.find({"collection_id": clienti["id"]}, {"_id": 0, "sort_order": 1}).to_list(3000)
              if c.get("sort_order") is not None]
    doc = {"id": f"item_{uuid.uuid4().hex[:12]}", "collection_id": clienti["id"], "data": {fmap.get("nome", "nome"): name.strip()[:120]},
           "visibility": clienti.get("visibility", "private"), "sort_order": max(orders, default=-1) + 1,
           "created_at": datetime.now(timezone.utc).isoformat()}
    _stamp_owner_fields(doc, current)
    await db.collection_items.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _data_uri_bytes(uri: str) -> Optional[bytes]:
    import base64 as _b64
    m = re.match(r"data:image/[\w.+-]+;base64,(.+)$", (uri or "").strip(), re.S)
    if not m:
        return None
    try:
        return _b64.b64decode(m.group(1))
    except Exception:
        return None


async def _store_job_photos(current: User, log: dict, images: List[str]) -> list:
    """Every photo is kept in mAIPAL (compressed), so the diary shows it even without a cloud;
    with Drive/OneDrive connected a copy also goes to Clienti/<cliente>/<commessa>."""
    import base64 as _b64
    added = []
    for uri in (images or [])[:10]:
        raw = _data_uri_bytes(uri)
        if not raw:
            continue
        try:
            jpeg = _downscale_image_bytes(raw, max_dim=JOB_PHOTO_MAX_DIM, max_bytes=JOB_PHOTO_MAX_BYTES)
        except Exception:
            logger.exception("job photo compress failed")
            continue
        ph = {"id": f"jph_{uuid.uuid4().hex[:12]}", "log_id": log["id"], "commessa_id": log["commessa_id"],
              "user_id": current.user_id, "org_id": current.org_id, "mime": "image/jpeg",
              "data_b64": _b64.b64encode(jpeg).decode("ascii"), "drive_link": None,
              "created_at": datetime.now(timezone.utc).isoformat()}
        await db.job_photos.insert_one(ph)
        added.append({"id": ph["id"], "drive_link": None})
    if added:
        await db.job_logs.update_one({"id": log["id"]}, {"$set": {"photos": (log.get("photos") or []) + added}})
        log["photos"] = (log.get("photos") or []) + added
        asyncio.create_task(_job_photos_to_cloud(current.user_id, log, [a["id"] for a in added]))
    return added


async def _job_photos_to_cloud(user_id: str, log: dict, photo_ids: list) -> None:
    import base64 as _b64
    try:
        if not await _storage_targets(user_id):
            return
        folder = _drive_safe(log.get("collection_name") or vx.CLIENTI_NAME)
        subs = [x for x in (log.get("client_name"), log.get("commessa_title")) if x]
        for n, pid in enumerate(photo_ids, 1):
            ph = await db.job_photos.find_one({"id": pid}, {"_id": 0})
            if not ph:
                continue
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(_b64.b64decode(ph["data_b64"]))
                tmp_path = tmp.name
            try:
                res = await asyncio.wait_for(_storage_save(user_id, folder, tmp_path, f"{log.get('date')} diario {n}.jpg",
                                                           "image/jpeg", subfolders=subs), timeout=LIST_FOLDER_TIMEOUT)
                link = res.get("web_view_link")
                await db.job_photos.update_one({"id": pid}, {"$set": {"drive_link": link}})
                cur = await db.job_logs.find_one({"id": log["id"]}, {"_id": 0, "photos": 1})
                if cur:
                    await db.job_logs.update_one({"id": log["id"]}, {"$set": {"photos": [
                        {**p, "drive_link": link} if p.get("id") == pid else p for p in cur.get("photos") or []]}})
            finally:
                try: os.unlink(tmp_path)
                except Exception: pass
    except Exception:
        logger.exception("job photos cloud copy failed")


def _job_log_message(log: dict, created: dict) -> str:
    when = _short_it_date(log.get("date"))
    head = f"📒 Diario di «{log.get('commessa_title')}»" + (f" — {log['client_name']}" if log.get("client_name") else "") + f" · {when}"
    lines = [head]
    if created.get("client"):
        lines.append(f"👤 Cliente nuovo aggiunto alla lista Clienti: {log.get('client_name')}")
    if created.get("commessa"):
        lines.append("🧱 Commessa nuova, stato «in corso»")
    if log.get("hours_pending"):
        lines.append(f"⏳ Ore da approvare: {jl.hours_line(log['hours_pending'])}{_review_detail(log)}. "
                     "Contano quando il titolare le approva.")
    elif log.get("hours"):
        lines.append(f"⏱ Ore: {jl.hours_line(log['hours'])}" + (_review_detail(log) if (log.get("hours_review") or {}).get("start") else ""))
    else:
        lines.append("⏱ Ore: non indicate")
    if log.get("materials"):
        lines.append(f"🧰 Materiali: {jl.materials_line(log['materials'])}")
    if log.get("problems"):
        lines.append("⚠️ Problemi: " + "; ".join(log["problems"]))
    if log.get("photos"):
        n = len(log["photos"])
        lines.append(f"📷 {n} foto" if n > 1 else "📷 1 foto")
    return "\n".join(lines)


# ---- HOURS TO APPROVE: a collaborator's hours are counted by themselves only from 📍 arrival
# and end (with the position). Hours written in a note - "oggi 8 ore", "ho finito alle 17.10",
# "ho sbagliato l'orario di fine, era 17.10" - go in the diary as hours to approve: the owner
# approves them (then they count; a correction takes the place of the 📍 hours of that day) or
# not. The app's users (the owner, the team) write theirs as before: counted at once.

HOURS_LOOKBACK_DAYS = 3   # "correggi l'ultimo fine cantiere": the presence of the last days


def _hhmm_at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=LOCAL_TZ)


async def _hours_claim(current: User, author: Optional[dict], speaker: str, target: dict, parsed: dict, times: dict) -> dict:
    """What a note says about the writer's hours: the times of arrival / end ("ho finito alle
    17.10" - the other one from their 📍 of that day, or from a start never ended) or the hours.
    -> {"hours": counted now, "pending": to approve, "review": dict|None, "replaces": the 📍 entry
    they take the place of, "session": a start never ended that they close, "date", "missing":
    "start"|"end" when a time alone can't make hours, "error"}"""
    now = datetime.now(timezone.utc).isoformat()
    out = {"hours": parsed["hours"], "pending": [], "review": None, "replaces": None, "session": None,
           "date": parsed["date"], "missing": None, "error": None}
    has_times = bool(times.get("start") or times.get("end"))
    if not has_times and not (author and parsed["hours"]):
        return out
    today = jl.today_local()
    day = date.fromisoformat(parsed["date"])
    # a time with no day said ("correggi l'ultimo fine cantiere") may be about the last days
    since = (today - timedelta(days=HOURS_LOOKBACK_DAYS) if has_times and day == today else day).isoformat()
    who_q = {"collaborator_id": author["id"]} if author else {"user_id": current.user_id, "collaborator_id": None}
    pres = [lg for lg in await db.job_logs.find({"commessa_id": target["id"], **who_q, "date": {"$gte": since, "$lte": day.isoformat()}},
                                                {"_id": 0, "embedding": 0}).to_list(100)
            if lg.get("presence") and not lg.get("hours_replaced_by")]
    pres_one = max(pres, key=lambda lg: lg["presence"]["end_at"], default=None)
    sess = None
    if has_times and not pres_one:   # a start never ended (open, or closed as forgotten)
        worker = author["id"] if author else f"{USER_WORKER}{current.user_id}"
        cands = [x for x in await db.work_sessions.find({"collaborator_id": worker, "commessa_id": target["id"]}, {"_id": 0}).to_list(500)
                 if not x.get("log_id") and (x.get("end_at") is None or x.get("forgotten"))
                 and since <= _local(x["start_at"]).date().isoformat() <= day.isoformat()]
        sess = max(cands, key=lambda x: x["start_at"], default=None)
    base = date.fromisoformat(pres_one["date"]) if pres_one else _local(sess["start_at"]).date() if sess else day
    start = times.get("start") or (sp.hhmm(_local(pres_one["presence"]["start_at"])) if pres_one
                                   else sp.hhmm(_local(sess["start_at"])) if sess else None)
    end = times.get("end") or (sp.hhmm(_local(pres_one["presence"]["end_at"])) if pres_one else None)
    hours, replaces = list(parsed["hours"]), None
    if has_times and start and end:
        minutes = int((_hhmm_at(base, end) - _hhmm_at(base, start)).total_seconds() // 60)
        if minutes <= 0:
            out["error"] = f"L'orario di fine ({end}) è prima dell'inizio ({start}): scrivimi gli orari giusti, es. «dalle 8 alle 17.10»."
            return out
        pause = ((pres_one or {}).get("presence") or {}).get("pause_min") or 0
        hours = [{"who": speaker, "hours": sp.round_hours(max(0, minutes - pause))}] + [h for h in hours if h["who"].lower() != speaker.lower()]
        replaces = pres_one
        out["session"] = sess
    elif has_times:
        out["missing"] = "start" if not start else "end"
    elif author and any(h["who"].lower() == speaker.lower() for h in hours):
        replaces = pres_one   # "oggi 8 ore" on a day with their 📍: in its place
    out.update(date=base.isoformat(), replaces=replaces)
    if not hours:
        out["hours"] = []
        return out
    review = {"kind": "correzione" if replaces else "dichiarate", "start": start if has_times else None, "end": end if has_times else None,
              "replaces_log_id": replaces["id"] if replaces else None, "replaced_hours": replaces["hours"] if replaces else [],
              "requested_by": speaker, "requested_at": now}
    if author:
        out.update(hours=[], pending=hours, review={**review, "status": "pending"})
    elif has_times:
        out.update(hours=hours, review={**review, "status": "approved", "decided_by": speaker, "decided_at": now})
    return out


async def _hours_claim_done(current: User, claim: dict, log: dict, author: Optional[dict], view: dict) -> None:
    """After the entry is saved: the start never ended is closed with it, a correction by the
    owner/team takes the 📍 hours' place at once, a collaborator's hours go to the owner."""
    rv = claim["review"] or {}
    if claim["session"] and (log.get("hours") or log.get("hours_pending")):
        end = _hhmm_at(date.fromisoformat(log["date"]), rv["end"]) if rv.get("end") else datetime.now(timezone.utc)
        await db.work_sessions.update_one({"id": claim["session"]["id"]}, {"$set": {
            "end_at": end.astimezone(timezone.utc).isoformat(), "log_id": log["id"], "declared": True}})
    if rv.get("status") == "approved" and rv.get("replaces_log_id"):
        await _replace_presence_hours(rv["replaces_log_id"], log["id"])
    if rv.get("status") == "pending" and author:
        await _hours_to_approve_notice(current, log, author, view)


def _review_detail(log: dict) -> str:
    """"(dalle 07:58 alle 17:10, al posto delle 10,5 h segnate con 📍)" """
    rv = log.get("hours_review") or {}
    bits = [f"dalle {rv['start']} alle {rv['end']}"] if rv.get("start") and rv.get("end") else []
    if rv.get("replaces_log_id"):
        old = sum(h["hours"] for h in rv.get("replaced_hours") or [])
        bits.append(f"al posto delle {jl._fmt_num(old)} h segnate con 📍" if old else "al posto della presenza segnata con 📍")
    return f" ({', '.join(bits)})" if bits else ""


async def _replace_presence_hours(pres_id: str, log_id: str) -> None:
    pres = await db.job_logs.find_one({"id": pres_id}, {"_id": 0, "hours": 1, "hours_replaced_by": 1})
    if pres and not pres.get("hours_replaced_by"):
        await db.job_logs.update_one({"id": pres_id}, {"$set": {"hours": [], "hours_replaced": pres.get("hours") or [],
                                                                 "hours_replaced_by": log_id, "embedding": None}})


async def _hours_to_approve_notice(owner: User, log: dict, author: dict, view: dict) -> None:
    who = (author.get("name") or author.get("first_name") or "") + (f" ({author['company']})" if author.get("company") else "")
    what = f"{_short_it_date(log['date'])}: {jl.hours_line(log['hours_pending'])}{_review_detail(log)}"
    try:
        await _notify_owner(owner, f"🕒 Ore da approvare: {who} su «{view['title']}» — {view['client_name']}, {what}.\n"
                                   "Le approvi nel diario della commessa, sezione Ore.")
    except Exception:
        logger.exception("hours to approve notice failed")
    # (on the phone: the entry's own notification says "da approvare")


MAT_EVE_AT, MAT_MORNING_AT = "19:30", "07:00"   # materials to take: the evening before and that morning


def _mat_reminder_times(due: str) -> tuple:
    d = date.fromisoformat(due)
    eve = datetime.combine(d - timedelta(days=1), datetime.strptime(MAT_EVE_AT, "%H:%M").time(), tzinfo=LOCAL_TZ)
    morning = datetime.combine(d, datetime.strptime(MAT_MORNING_AT, "%H:%M").time(), tzinfo=LOCAL_TZ)
    return eve, morning


async def _plan_people(current: User, commessa_id: str) -> list:
    """Who a material to take can be for: the collaborators enabled on the commessa and the team."""
    people = [{"kind": "collab", "id": c["id"], "name": c["name"], "first": c["first_name"]}
              for c in await _assignable_collaborators(commessa_id)]
    team = await db.users.find(_team_q(current.org_id), {"_id": 0, "user_id": 1, "name": 1}).to_list(200) if current.org_id else []
    if not any(u["user_id"] == current.user_id for u in team):
        team.append({"user_id": current.user_id, "name": current.name})
    people += [{"kind": "user", "id": u["user_id"], "name": u.get("name") or "", "first": _first_name(u.get("name"))} for u in team]
    return [p for p in people if p["first"]]


def _plan_person(m: dict, raw: str, people: list) -> Optional[dict]:
    """Who has to take it: the name the model read ("ricorda a Mario…"), else one of the people
    named in the message - only when it is one person and not ambiguous."""
    def by_name(name: str) -> Optional[dict]:
        n = " ".join(name.lower().split())
        full = [p for p in people if p["name"].lower() == n]
        first = [p for p in people if p["first"].lower() == n.split(" ")[0]] if n else []
        return full[0] if len(full) == 1 else first[0] if len(first) == 1 else None
    if m.get("who"):
        hit = by_name(m["who"])
        if hit:
            return hit
    low = jl._norm(raw)
    def given_to(first: str) -> bool:   # "a Mario", "per Gino", "Gino porta / deve prendere"
        f = re.escape(jl._norm(first))
        return bool(re.search(rf"\b(?:a|ad|per)\s+{f}\b|\b{f}\s+(?:deve|dovrebbe|porta|prende|passa|compra|ordina|recupera)\b", low))
    named = {p["id"]: p for p in people if given_to(p["first"])}
    return next(iter(named.values())) if len(named) == 1 else None


async def _plan_materials(current: User, target: dict, clienti: dict, planned: list, author: Optional[dict],
                          from_log_id: Optional[str] = None, raw: str = "") -> list:
    """Materials to take -> one To Do "Da prendere" per day needed and person: the one named
    ("ricorda a Mario…", a collaborator of the commessa or a team mate), else who wrote it.
    Reminded the evening before and that morning; a collaborator named by someone else hears it
    at once on Telegram (one without Telegram: the writer is reminded instead). A collaborator's
    own one is also for the colleagues of their company on that commessa (on Telegram, with ✅
    Fatto for all), unless they said "solo per me"."""
    people = await _plan_people(current, target["id"])
    mates = await _company_mates(author, target["id"]) if author and not jl.only_for_me(raw) else []
    groups: dict = {}
    for m in planned:
        due = m.get("for_date") or (jl.today_local() + timedelta(days=1)).isoformat()
        person = _plan_person(m, raw, people)
        groups.setdefault((due, (person or {}).get("kind"), (person or {}).get("id")), {"person": person, "ms": []})["ms"].append(m)
    now = datetime.now(timezone.utc)
    out = []
    for (due, _k, _i), g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][2] or "")):
        ms, person = g["ms"], g["person"]
        eve, morning = _mat_reminder_times(due)
        if person and person["kind"] == "collab":
            collab_doc = await db.collaborators.find_one({"id": person["id"]}, {"_id": 0}) or {}
            on_tg = bool(collab_doc.get("telegram_chat_id")) and collab_doc.get("status") == "active"
            who, collab_id = person["name"], person["id"]
            assignee = None if on_tg or author else current.user_id   # not on Telegram: the writer is reminded
        elif person:
            who, collab_id, assignee = person["first"], None, person["id"]
        else:
            who, collab_id = (author or {}).get("name") or _first_name(current.name), (author or {}).get("id")
            assignee = None if author else current.user_id
        doc = {"id": f"jtodo_{uuid.uuid4().hex[:12]}", "commessa_id": target["id"], "collection_id": clienti["id"],
               "user_id": current.user_id, "org_id": current.org_id, "author_name": (author or {}).get("first_name") or _first_name(current.name),
               "kind": "materiale", "text": "Da prendere: " + ", ".join(jl.mat_label(m) for m in ms),
               "materials": [{k: m.get(k) for k in ("name", "qty", "unit")} for m in ms],
               "who": who, "collaborator_id": collab_id,
               "assignee_user_id": assignee, "due_date": due, "done": False, "done_at": None,
               "from_log_id": from_log_id, "created_at": now.isoformat(),
               # a time already gone when it is written is not reminded (it was just said)
               "reminded": {**({"eve": due} if now >= eve else {}), **({"morning": due} if now >= morning else {})}}
        mine = person is None or (person["kind"] == "collab" and person["id"] == (author or {}).get("id")) \
            or (person["kind"] == "user" and not author and person["id"] == current.user_id)
        shared = mates if mine else []   # (mates: only for a collaborator's own)
        if shared:
            doc["shared_with"] = [c["id"] for c in shared]
        await db.job_todos.insert_one(doc)
        doc.pop("_id", None)
        view_doc = {k: v for k, v in doc.items() if k != "reminded"}
        if shared:
            view_doc["shared_names"] = [c.get("first_name") or _collab_name(c) for c in shared]
        view_doc["for_other"] = not mine   # (for the answer: whose it is, when not the writer's)
        # given to a collaborator by someone else: told now (the writer was just answered)
        if collab_id and collab_id != (author or {}).get("id"):
            view_doc["notified"] = await _notify_assignee("todo", view_doc, target)
        for c in shared:   # the colleagues of the same company: told now, like the writer was
            try:
                await _tell_collaborator(c, _shared_material_text(view_doc, target, author), f"cldone:t:{doc['id']}")
            except Exception:
                logger.exception("shared material notice failed")
        _day_pin_touch(collab_id, *[c["id"] for c in shared])
        out.append(view_doc)
    return out


async def _company_mates(author: dict, commessa_id: str) -> list:
    """The other collaborators of the author's company enabled on the commessa, on Telegram."""
    company = " ".join((author.get("company") or "").split()).lower()
    if not company or not author.get("id"):
        return []
    me = await db.collaborators.find_one({"id": author["id"]}, {"_id": 0, "owner_user_id": 1})
    if not me:
        return []
    docs = await db.collaborators.find({"owner_user_id": me["owner_user_id"], "commesse": {"$in": [commessa_id]}}, {"_id": 0}).to_list(200)
    return [c for c in docs if c["id"] != author["id"] and c.get("status") == "active" and c.get("telegram_chat_id")
            and " ".join((c.get("company") or "").split()).lower() == company]


def _and_join(names: list) -> str:
    return ", ".join(names[:-1]) + " e " + names[-1] if len(names) > 1 else "".join(names)


def _mat_items(todo: dict) -> list:
    """The materials of a To Do "Da prendere", one label each ("10 pz scatole 503")."""
    return [jl.mat_label(m) for m in todo.get("materials") or [] if m.get("name")] \
        or [x.strip() for x in (todo.get("text") or "").removeprefix("Da prendere: ").split(", ") if x.strip()]


def _mat_bullets(todo: dict, mark: str = "•") -> str:
    """The materials as a bulleted list, one per line (the Telegram messages)."""
    return "\n".join(f"{mark} {x}" for x in _mat_items(todo))


def _shared_material_text(todo: dict, target: dict, author: dict) -> str:
    today = jl.today_local()
    due = todo["due_date"]
    when = "domani" if due == (today + timedelta(days=1)).isoformat() else "oggi" if due == today.isoformat() else _short_it_date(due)
    return (f"📌 {author.get('first_name') or author.get('name')} ha segnato da prendere {when} per «{target.get('title')}»"
            + (f" — {target['client_name']}" if target.get("client_name") else "")
            + f":\n{_mat_bullets(todo)}\nVale per tutta la ditta: quando qualcuno l'ha preso tocca ✅ Fatto.")


def _plan_message(target: dict, todos: list, short: bool = False) -> str:
    today = jl.today_local()
    def when(due):
        d = date.fromisoformat(due)
        return "domani" if d == today + timedelta(days=1) else "oggi" if d == today else _short_it_date(due)
    lines = [f"📌 Da prendere {when(t['due_date'])}" + (f" ({t['who']})" if t.get("for_other") else "") + f":\n{_mat_bullets(t)}"
             + (f"\nLo vedono anche {_and_join(t['shared_names'])} (scrivi «solo per me» se è solo tuo)." if t.get("shared_names") else "")
             for t in todos]
    if short:
        return "\n".join(lines)
    head = f"📌 Promemoria per «{target.get('title')}»" + (f" — {target['client_name']}" if target.get("client_name") else "")
    now = datetime.now(timezone.utc)
    times = []
    eve, morning = _mat_reminder_times(todos[0]["due_date"])
    say = lambda hm: hm.lstrip("0").replace(":00", "").replace(":", ".")   # "07:00" -> "7", "19:30" -> "19.30"
    if now < eve:
        times.append(f"la sera prima alle {say(MAT_EVE_AT)}")
    if now < morning:
        times.append(f"la mattina alle {say(MAT_MORNING_AT)}")
    told = [t["who"] for t in todos if t.get("notified")]
    remind = ("Lo ricordo " + " e ".join(times) + "." if times else "")
    return "\n".join([head, *[ln.replace("📌 ", "") for ln in lines],
                      (f"Mandato su Telegram a {', '.join(told)}. " if told else "") + remind + " Non l'ho messo tra i materiali usati."]).strip()


async def _material_reminders(now_utc: Optional[datetime] = None) -> int:
    """To Do "Da prendere": the evening before (19:30) and that morning (7:00), once each - on
    Telegram to the collaborator (with ✅ Fatto), or to the user (app notification + Telegram)."""
    now = now_utc or datetime.now(timezone.utc)
    today = now.astimezone(LOCAL_TZ).date()
    days = [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    sent = 0
    for t in await db.job_todos.find({"kind": "materiale", "done": False, "due_date": {"$in": days}}, {"_id": 0}).to_list(2000):
        eve, morning = _mat_reminder_times(t["due_date"])
        kind = "morning" if now >= morning else "eve" if now >= eve else None
        if not kind or (t.get("reminded") or {}).get(kind) == t["due_date"]:
            continue
        await db.job_todos.update_one({"id": t["id"]}, {"$set": {"reminded": {**(t.get("reminded") or {}), kind: t["due_date"]}}})
        sub = await db.collection_sub_items.find_one({"id": t["commessa_id"]}, {"_id": 0})
        if not sub:
            continue
        client = await db.collection_items.find_one({"id": sub.get("item_id")}, {"_id": 0, "embedding": 0})
        coll = await db.collections.find_one({"id": sub.get("collection_id")}, {"_id": 0})
        view = _commessa_view(sub, client, coll or {})
        what = ", ".join(_mat_items(t))   # (the phone's notification: one line)
        head = "🧰 Domani da prendere" if kind == "eve" else "🧰 Oggi da prendere"
        text = f"{head} per «{view['title']}» — {view['client_name']}:\n{_mat_bullets(t)}"
        try:
            # the collaborator, and the colleagues of their company it is shared with
            for cid in [x for x in [t.get("collaborator_id"), *(t.get("shared_with") or [])] if x]:
                c = await db.collaborators.find_one({"id": cid}, {"_id": 0})
                pinned_today = kind == "morning" and ((c or {}).get("day_pin") or {}).get("date") == t["due_date"] \
                    and (c or {}).get("day_pin", {}).get("message_id")
                by = f" (segnato da {t.get('author_name')})" if cid != t.get("collaborator_id") and t.get("author_name") else ""
                if c and not pinned_today and t["commessa_id"] in (c.get("commesse") or []) \
                        and await _tell_collaborator(c, text + by + "\nQuando l'hai preso tocca ✅ Fatto.", f"cldone:t:{t['id']}"):
                    sent += 1
            if t.get("assignee_user_id"):
                u = await db.users.find_one({"user_id": t["assignee_user_id"]}, {"_id": 0, "telegram_chat_id": 1})
                push.fire_and_forget(db, t["assignee_user_id"], head + f" · {view['title']}", what,
                                     f"/dashboard/journal?commessa={view['id']}", f"mat-{t['id']}-{kind}")
                if u and u.get("telegram_chat_id"):
                    await _send_telegram_text(u["telegram_chat_id"], text)
                sent += 1
        except Exception:
            logger.exception("materials reminder failed")
    return sent


def _public_log(log: dict) -> dict:
    return {k: v for k, v in log.items() if k not in ("embedding", "_id")}


PHOTO_ONLY_TEXT = "Foto dal cantiere"
PHOTO_DESCRIBE_MINUTES = 20   # a description sent within this time completes the photo sent just before


async def _photo_awaiting_text(current: User, author: Optional[dict], commessa_id: Optional[str]) -> Optional[dict]:
    """The last entry of this author that is only photos ("Foto dal cantiere"), sent in the last
    minutes - on that commessa when it is known. The message that follows describes it."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=PHOTO_DESCRIBE_MINUTES)).isoformat()
    q = {"user_id": current.user_id, "raw_text": PHOTO_ONLY_TEXT, "created_at": {"$gte": since},
         "collaborator_id": author.get("id") if author else None}
    if commessa_id:
        q["commessa_id"] = commessa_id
    cands = await db.job_logs.find(q, {"_id": 0, "embedding": 0}).to_list(50)
    cands = [c for c in cands if c.get("photos") and not c.get("kind")]
    return max(cands, key=lambda c: c.get("created_at") or "", default=None)


JOB_LOG_QUESTION_MSG = ("Il Diario serve solo a scrivere note sulle commesse, quindi non ho salvato niente. "
                        "Per cercare informazioni usa l'agente Cerca, oppure apri la commessa nella sezione Diario "
                        "e chiedi con il tasto della chat.")


async def _save_job_log(current: User, text: str, images: Optional[List[str]] = None, commessa_id: Optional[str] = None,
                        hint_commessa_id: Optional[str] = None, new_client_name: Optional[str] = None,
                        conv_id: Optional[str] = None, channel: str = "web", client_item_id: Optional[str] = None,
                        author: Optional[dict] = None, material_choice: Optional[str] = None) -> dict:
    """Shared by the chat agent, the commessa page, @diario and Telegram. `author`: a
    collaborator writing on Telegram ({"id", "first_name", "name", "company"}) - the entry is
    theirs, in the account (`current`) that enabled them on that commessa.
    -> {"status": "ok", "log", "message", ...} | {"status": "pick_commessa", "candidates", "message", "text"}
       | {"status": "question" | "unclear" | "invalid", "message"} - nothing saved (invalid: times that don't add up)
       | {"status": "planned", "todos", "message"} - only materials to take: a reminder, no entry
       | {"status": "material_doubt", "materials", "commessa_id", "message", "text"} - asked: used or to take?"""
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Racconta cosa è stato fatto in cantiere")
    clienti = await _ensure_clienti_list(current)
    team = []
    if current.org_id:
        team = [_first_name(m.get("name")) for m in await db.users.find(_team_q(current.org_id), {"_id": 0, "name": 1}).to_list(200)]
    speaker = _first_name(current.name)
    if author:
        speaker = author.get("first_name") or speaker
        team = [*team, _first_name(current.name)]

    # text after a photo sent alone: it is the photo's description (same commessa, few minutes)
    photo_entry = None if images else await _photo_awaiting_text(current, author, commessa_id or hint_commessa_id)
    if photo_entry and not commessa_id and not hint_commessa_id:
        hint_commessa_id = photo_entry["commessa_id"]
    known, target, created = None, None, {}
    if commessa_id:   # (a commessa shared by a team-mate is in their Clienti list)
        clienti, sub, client = await _commessa_or_404(current, commessa_id)
        target = _commessa_view(sub, client, clienti)
        known = {"title": target["title"], "client": target["client_name"]}
    try:
        parsed = await jl.interpret(text, speaker, team, known=known, user_id=current.user_id, channel=channel,
                                    **({"photos": len(photo_entry["photos"])} if photo_entry else {}))
    except Exception:
        logger.exception("job log interpretation failed, saving the text as is")
        parsed = {"kind": "nota", "date": jl.today_local().isoformat(), "text": text, "hours": [], "materials": [], "problems": [],
                  "client": "", "commessa": ""}

    # the agent Diario only writes entries, with only what the user said: a question or an entry
    # it can't understand saves nothing (and creates no client or commessa)
    photo_only = bool(images) and text == PHOTO_ONLY_TEXT
    if not photo_only and (parsed.get("kind") == "domanda" or jl.is_plain_question(text)):
        return {"status": "question", "message": JOB_LOG_QUESTION_MSG}
    times = jl.clock_times(parsed.get("times"), text)   # "ho finito alle 17.10": an entry even with nothing else
    has_times = bool(times["start"] or times["end"])
    if has_times and parsed.get("kind") == "non_chiara":
        parsed["kind"] = "nota"
    if has_times and not commessa_id and not hint_commessa_id:   # on the commessa of their last 📍
        since = (jl.today_local() - timedelta(days=HOURS_LOOKBACK_DAYS)).isoformat()
        q = {"collaborator_id": author["id"]} if author else {"user_id": current.user_id, "collaborator_id": None}
        last = [lg for lg in await db.job_logs.find({**q, "date": {"$gte": since}}, {"_id": 0, "commessa_id": 1, "presence": 1}).to_list(100)
                if lg.get("presence")]
        if last:
            hint_commessa_id = max(last, key=lambda lg: lg["presence"]["end_at"])["commessa_id"]
    if not photo_only and parsed.get("kind") == "non_chiara":
        return {"status": "unclear", "message": "Non ho salvato niente: la nota non è chiara. "
                + (parsed.get("doubt") or "Mi dici cosa avete fatto e per quale cliente o commessa?")}
    parsed = jl.ground(parsed, text)

    if not target and client_item_id:
        client = await db.collection_items.find_one({"id": client_item_id, "collection_id": clienti["id"]}, {"_id": 0, "embedding": 0})
        if not client:
            raise HTTPException(status_code=404, detail="Cliente non trovato")
        commesse, _ = await _all_commesse(clienti)
        theirs = [c for c in commesse if c["client_item_id"] == client_item_id and c["stato"] != "chiusa"]
        if len(theirs) == 1:
            target = theirs[0]
        elif len(theirs) > 1:
            return {"status": "pick_commessa", "message": "Di quale commessa si tratta?", "clients": [], "new_commessa_for": [], "new_client_name": "",
                    "candidates": _pick_rows(theirs, await _last_activity([c["id"] for c in theirs])), "text": text}
        else:
            sub = await _new_commessa(clienti, client, parsed.get("commessa") or "Lavori")
            target, created = _commessa_view(sub, client, clienti), {"commessa": True}
    if not target and new_client_name:
        client = await _new_client(current, clienti, new_client_name)
        sub = await _new_commessa(clienti, client, parsed.get("commessa") or "Lavori")
        target, created = _commessa_view(sub, client, clienti), {"client": True, "commessa": True}
    if not target:
        res = await _resolve_commessa(clienti, text, parsed.get("client") or "", parsed.get("commessa") or "", hint_commessa_id)
        if res.get("commessa"):
            target = res["commessa"]
        elif res.get("create_for"):
            sub = await _new_commessa(clienti, res["create_for"], res.get("title") or parsed.get("commessa") or "Lavori")
            target, created = _commessa_view(sub, res["create_for"], clienti), {"commessa": True}
        else:
            reason = res.get("reason")
            nc = res.get("new_commessa_for") or []
            msg = ("Di quale commessa si tratta?" if reason == "several" else
                   f"{nc[0]['name']} non ha commesse aperte: la voce va su una commessa chiusa o ne apro una nuova?"
                   if reason == "closed" else
                   f"Non trovo «{res.get('client_said')}» nella lista Clienti: è un cliente nuovo o una di queste commesse?"
                   if reason == "unknown_client" else
                   "Ho più clienti con questo nome: quale intendi?" if reason == "clients" else
                   "A quale commessa va questa voce?" if res.get("pick") else
                   "Non hai ancora commesse aperte: dimmi per quale cliente è (es. «dai Rossi…»).")
            return {"status": "pick_commessa", "message": msg, "candidates": res.get("pick") or [],
                    "clients": res.get("clients") or [], "new_commessa_for": nc,
                    "new_client_name": res.get("client_said") or "", "text": text}

    if not commessa_id:   # found in their Clienti list: not if the team's is read-only for them
        await _commessa_or_404(current, target["id"])

    # materials used vs to take ("domani porto 10 scatole 503"): the ones to take become a reminder
    # (To Do "Da prendere"), never material used; when it can't be told, asked
    mats = parsed.get("materials") or []
    if material_choice in ("usato", "da_prendere"):
        for m in mats:
            if m.get("status") == "dubbio":
                m["status"] = material_choice
                m["for_date"] = jl.plan_date(m, text, jl.today_local()) if material_choice == "da_prendere" else None
    doubtful = [m for m in mats if m.get("status") == "dubbio"]
    if doubtful:
        names = [jl.mat_label(m) for m in doubtful]
        return {"status": "material_doubt", "materials": names, "commessa_id": target["id"], "commessa": target, "text": text,
                "message": f"🧰 {', '.join(names)}: li avete usati oggi o sono da prendere?"}
    planned = [m for m in mats if m.get("status") == "da_prendere"]
    parsed["materials"] = [{k: m.get(k) for k in ("name", "qty", "unit")} for m in mats if m.get("status") != "da_prendere"]
    if planned:   # the entry's text keeps only what was done
        parsed["text"] = jl.without_plans(parsed["text"], planned)
    if planned and not parsed["hours"] and not parsed["materials"] and not parsed["problems"] and not images \
            and not parsed["text"]:
        todos = await _plan_materials(current, target, clienti, planned, author, raw=text)
        ut.fire_and_forget_feature_event(user_id=current.user_id, feature="diario", channel=channel, trigger="utente", org_id=current.org_id)
        return {"status": "planned", "todos": todos, "commessa": target, "client_created": bool(created.get("client")),
                "commessa_created": bool(created.get("commessa")), "message": _plan_message(target, todos)}

    claim = await _hours_claim(current, author, speaker, target, parsed, times)
    if claim["error"]:
        return {"status": "invalid", "message": "Non ho salvato niente: " + claim["error"][0].lower() + claim["error"][1:]}
    parsed["hours"], parsed["date"] = claim["hours"], claim["date"]
    review_fields = {"hours_pending": claim["pending"], "hours_review": claim["review"]} if claim["review"] else {}

    now = datetime.now(timezone.utc).isoformat()
    if photo_entry and photo_entry["commessa_id"] == target["id"]:
        # the description goes into the photo's entry (what it was is kept, to undo it)
        upd = {"raw_text": text, "text": parsed["text"], "date": parsed["date"], "hours": parsed["hours"],
               "materials": parsed["materials"], "problems": parsed["problems"], "described_at": now, "embedding": None, **review_fields,
               "before_description": {k: photo_entry.get(k) for k in ("raw_text", "text", "date", "hours", "materials", "problems")}}
        await db.job_logs.update_one({"id": photo_entry["id"]}, {"$set": upd})
        log = {**photo_entry, **upd}
        ut.fire_and_forget_feature_event(user_id=current.user_id, feature="diario", channel=channel, trigger="utente", org_id=current.org_id)
        if log["hours"] or log["materials"]:
            asyncio.create_task(_check_budget_alert(clienti, target["id"]))
        await _hours_claim_done(current, claim, log, author, target)
        n = len(photo_entry.get("photos") or [])
        msg = _job_log_message(log, {}).replace("📒 Diario", f"📷 Descrizione aggiunta {'alla foto' if n == 1 else f'alle {n} foto'} nel diario", 1)
        todos = await _plan_materials(current, target, clienti, planned, author, from_log_id=log["id"], raw=text) if planned else []
        if todos:
            msg += "\n" + _plan_message(target, todos, short=True)
        if author:
            _push_collab_entry(current, log, author)
        return {"status": "ok", "log": _public_log({k: v for k, v in log.items() if k != "before_description"}), "commessa": target,
                "client_created": False, "commessa_created": False, "described_photo": True, "message": msg, "todos": todos}
    log = {
        "id": f"jlog_{uuid.uuid4().hex[:12]}",
        "user_id": current.user_id, "org_id": current.org_id, "author_name": speaker,
        **({"collaborator_id": author.get("id"), "author_company": author.get("company") or ""} if author else {}),
        "collection_id": clienti["id"], "collection_name": clienti.get("name"),
        "client_item_id": target["client_item_id"], "client_name": target["client_name"],
        "commessa_id": target["id"], "commessa_title": target["title"],
        "date": parsed["date"], "raw_text": text, "text": parsed["text"],
        "hours": parsed["hours"], "materials": parsed["materials"], "problems": parsed["problems"], **review_fields,
        "photos": [], "channel": channel, "conv_id": conv_id, "created_at": now, "embedding": None,
    }
    await db.job_logs.insert_one(log)
    log.pop("_id", None)
    await _hours_claim_done(current, claim, log, author, target)
    if images:
        await _store_job_photos(current, log, images)
    if author:
        _push_collab_entry(current, {**log, "photos": log.get("photos") or images or []}, author)
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="diario", channel=channel, trigger="utente", org_id=current.org_id)
    if log["hours"] or log["materials"]:
        asyncio.create_task(_check_budget_alert(clienti, target["id"]))
    msg = _job_log_message(log, created)
    if claim["missing"]:
        msg += ("\nNon so a che ora sei arrivato" if claim["missing"] == "start" else "\nNon so a che ora hai finito") \
            + ": per le ore scrivimi l'orario di arrivo e di fine, es. «ieri dalle 8 alle 17.10»."
    todos = await _plan_materials(current, target, clienti, planned, author, from_log_id=log["id"], raw=text) if planned else []
    if todos:
        msg += "\n" + _plan_message(target, todos, short=True)
    return {"status": "ok", "log": _public_log(log), "commessa": target, "client_created": bool(created.get("client")),
            "commessa_created": bool(created.get("commessa")), "message": msg, "todos": todos}


@api_router.post("/jobs/logs")
async def create_job_log(payload: JobLogPayload, current: User = Depends(get_current_user)):
    return await _save_job_log(current, payload.text, payload.images, payload.commessa_id, payload.hint_commessa_id,
                               payload.new_client_name, payload.conv_id, client_item_id=payload.client_item_id,
                               material_choice=payload.material_choice)


async def _shared_commesse(current: User, skip: set) -> list:
    """The commesse a team-mate shared with the user (while they are in a team together)."""
    out = []
    for sub in await db.collection_sub_items.find({"shared_with": {"$in": [current.user_id]}}, {"_id": 0, "embedding": 0}).to_list(500):
        if sub["id"] in skip:
            continue
        acc = await _commessa_access(current, sub["id"])
        if acc and acc["shared_by"] is not None:
            out.append({**_commessa_view(acc["sub"], acc["client"], acc["clienti"]), "shared": True, "shared_by": acc["shared_by"],
                        "perm": acc["perm"]})
    return out


@api_router.get("/jobs/commesse")
async def list_job_commesse(current: User = Depends(get_current_user)):
    """The commesse of the user's Clienti list and the ones team-mates shared with them
    ("shared": true, with who shared it and the permission)."""
    clienti = await _clienti_list(current)
    commesse = []
    if clienti:
        commesse, _ = await _all_commesse(clienti)
        perm = _list_perm(clienti, current) or "read"
        for c in commesse:
            c.update({"perm": perm, "shared": False})
    commesse += await _shared_commesse(current, {c["id"] for c in commesse})
    if not commesse:
        return []
    act = await _last_activity([c["id"] for c in commesse])
    for c in commesse:
        a = act.get(c["id"]) or {}
        c.update({"last_day": a.get("last_day"), "entries": a.get("entries", 0), "hours_total": a.get("hours", 0)})
    # in corso first, chiuse last; within a state the most recently worked on first
    order = {s: i for i, s in enumerate(["in corso", "preventivo", "sospesa", "", "chiusa"])}
    commesse.sort(key=lambda c: c["last_day"] or "", reverse=True)
    commesse.sort(key=lambda c: order.get(c["stato"], 3))
    return commesse


@api_router.get("/jobs/commesse/{commessa_id}")
async def get_job_commessa(commessa_id: str, date_from: Optional[str] = None, date_to: Optional[str] = None,
                           current: User = Depends(get_current_user)):
    """The commessa, its whole-job totals (the four figures on top) and the entries of the
    period asked (date_from/date_to, YYYY-MM-DD; none = the whole commessa), newest first.
    The totals need only the figures, so the texts are loaded for the period alone."""
    acc = await _commessa_access(current, commessa_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    clienti, sub, client = acc["clienti"], acc["sub"], acc["client"]
    light = await db.job_logs.find({"commessa_id": commessa_id},
                                   {"_id": 0, "id": 1, "date": 1, "kind": 1, "hours": 1, "materials": 1, "problems": 1, "photos": 1,
                                    "hours_pending": 1, "hours_review": 1, "author_name": 1}).to_list(20000)
    q: dict = {"commessa_id": commessa_id}
    rng = {}
    if date_from:
        rng["$gte"] = date_from[:10]
    if date_to:
        rng["$lte"] = date_to[:10]
    if rng:
        q["date"] = rng
    logs = await db.job_logs.find(q, {"_id": 0, "embedding": 0}).to_list(5000)
    logs.sort(key=lambda lg: (lg.get("date") or "", lg.get("created_at") or ""), reverse=True)
    reports = await db.work_reports.count_documents({"commessa_id": commessa_id})
    photos = sum(len(lg.get("photos") or []) for lg in light)
    todos = _sort_job_todos(await db.job_todos.find({"commessa_id": commessa_id}, {"_id": 0}).to_list(1000))
    econ = await _commessa_economics(clienti, commessa_id, light)
    milestones = await _commessa_milestones(commessa_id)
    waiting = [lg["id"] for lg in light if lg.get("hours_pending")]   # a collaborator's hours, to approve
    to_approve = await db.job_logs.find({"id": {"$in": waiting}}, {"_id": 0, "embedding": 0}).to_list(500) if waiting else []
    return {"commessa": _commessa_view(sub, client, clienti), "logs": logs, "totals": jl.totals(light),
            "hours_to_approve": sorted(to_approve, key=lambda lg: (lg.get("date") or "", lg.get("created_at") or "")),
            "todos": todos, "team": await _team_first_names(current),
            "collaborators": await _assignable_collaborators(commessa_id),
            "on_site": await _on_site(commessa_id), "geo": sub.get("geo"),
            "milestones": milestones, "milestones_summary": _milestones_summary(milestones),
            "contacts": await _commessa_contacts(commessa_id),
            "economics": {k: econ[k] for k in ("cost_total", "budget", "margin", "used_pct", "complete")},
            "period_totals": jl.totals(logs), "docs": {"photos": photos, "reports": reports, "total": photos + reports},
            "first_day": min((lg.get("date") for lg in light if lg.get("date")), default=None),
            "stati": vx.COMMESSA_STATI,
            # what the user can do: "owner" (also shares it), "edit", "read"; shared_by: a team-mate's commessa
            "access": {"perm": acc["perm"], "shared_by": acc["shared_by"], "is_owner": clienti.get("user_id") == current.user_id},
            "shared_count": len(sub.get("shared_with") or []) if clienti.get("user_id") == current.user_id else 0}


class CommessaSharingPayload(BaseModel):
    user_ids: List[str] = []                              # team-mates
    perms: Dict[str, Literal["edit", "read"]] = {}        # each one: modifica (default) or sola lettura


async def _commessa_sharing_view(current: User, sub: dict) -> dict:
    mates = await db.users.find({**_team_q(current.org_id), "user_id": {"$ne": current.user_id}},
                                {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(300) if current.org_id else []
    shared, perms = sub.get("shared_with") or [], sub.get("share_perms") or {}
    return {"in_team": bool(current.org_id),
            "members": [{"user_id": m["user_id"], "name": m.get("name") or (m.get("email") or "").split("@")[0],
                         "shared": m["user_id"] in shared, "perm": perms.get(m["user_id"]) or "edit"} for m in mates]}


@api_router.get("/jobs/commesse/{commessa_id}/sharing")
async def get_commessa_sharing(commessa_id: str, current: User = Depends(get_current_user)):
    clienti, sub, _client = await _commessa_or_404(current, commessa_id, write=False)
    if clienti.get("user_id") != current.user_id:
        raise HTTPException(status_code=403, detail="Solo chi ha la commessa nella sua lista Clienti può condividerla")
    return await _commessa_sharing_view(current, sub)


@api_router.put("/jobs/commesse/{commessa_id}/sharing")
async def set_commessa_sharing(commessa_id: str, payload: CommessaSharingPayload, current: User = Depends(get_current_user)):
    """One commessa (its diary, costs included) shared with team-mates, each able to write in it
    or only to read it. Only who has it in their own Clienti list decides."""
    clienti, sub, client = await _commessa_or_404(current, commessa_id, write=False)
    if clienti.get("user_id") != current.user_id:
        raise HTTPException(status_code=403, detail="Solo chi ha la commessa nella sua lista Clienti può condividerla")
    if payload.user_ids and not current.org_id:
        raise HTTPException(status_code=400, detail="Per condividere una commessa devi far parte di un team.")
    if payload.user_ids:
        await _require_share_allowed(current)
    shared = await _team_mate_ids(current, payload.user_ids)
    perms = _clean_perms(shared, payload.perms)
    before = sub.get("shared_with") or []
    await db.collection_sub_items.update_one({"id": commessa_id}, {"$set": {"shared_with": shared, "share_perms": perms}})
    sub = {**sub, "shared_with": shared, "share_perms": perms}
    view = _commessa_view(sub, client, clienti)
    for u in await db.users.find({"user_id": {"$in": [x for x in shared if x not in before]}}, {"_id": 0}).to_list(300):
        how = "puoi vederlo (sola lettura)" if perms.get(u["user_id"]) == "read" else "puoi vederlo e scriverci"
        text = f"📒 {current.name} ti ha condiviso il diario di «{view['title']}» — {view['client_name']}: {how} in mAIPAL → Diario."
        push.fire_and_forget(db, u["user_id"], f"📒 Commessa condivisa · {view['title']}", text, f"/dashboard/journal?commessa={commessa_id}",
                             f"share-{commessa_id}")
        if u.get("telegram_chat_id"):
            try:
                await _send_telegram_text(u["telegram_chat_id"], text)
            except Exception:
                logger.exception("commessa share notice failed")
    return await _commessa_sharing_view(current, sub)


# ---- the commessa's To Do: the next activities, who takes care of them and by when ----
# Kept inside the commessa (job_todos): the To-Do section is personal (one owner, no
# assignee, no date), while these belong to the job and to whoever sees it in the team.

def _sort_job_todos(todos: list) -> list:
    """Open ones first - with a date, soonest first, then without - the done ones last."""
    return sorted(todos, key=lambda x: (bool(x.get("done")), x.get("due_date") is None, x.get("due_date") or "",
                                        x.get("created_at") or ""))


async def _team_first_names(current: User) -> list:
    me = _first_name(current.name)
    if not current.org_id:
        return [me]
    names = [_first_name(m.get("name")) for m in await db.users.find(_team_q(current.org_id), {"_id": 0, "name": 1}).to_list(200)]
    return [me] + sorted({n for n in names if n and n != me})


def _valid_due(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="Data non valida")


# ---- To Do and milestones given to an external COLLABORATOR (one enabled on the commessa): they
# hear it on Telegram - when it is given to them, when its date moves, the day before, the day
# itself and when late - with a "✅ Fatto" button. Marked done from there: the diary says it and
# the owner hears it (app notification and Telegram).

async def _assignable_collaborators(commessa_id: str) -> list:
    docs = await db.collaborators.find({"commesse": {"$in": [commessa_id]}}, {"_id": 0}).to_list(200)
    return [{"id": c["id"], "name": _collab_name(c), "first_name": c.get("first_name") or "", "company": c.get("company") or "",
             "telegram": bool(c.get("telegram_chat_id")) and c.get("status") == "active"}
            for c in docs if c.get("status") in ("active", "invited")]


async def _resolve_assignee(current: User, commessa_id: str, who: Optional[str], collaborator_id: Optional[str],
                            keep: Optional[str] = None) -> tuple:
    """-> (who, collaborator_id): the collaborator chosen (their name becomes the who), none
    ("" given), or - when only a name is given - the collaborator with that name, if one only."""
    collabs = await _assignable_collaborators(commessa_id)
    if collaborator_id:
        c = next((x for x in collabs if x["id"] == collaborator_id), None)
        if not c:
            raise HTTPException(status_code=400, detail="Il collaboratore non è abilitato su questa commessa")
        return c["name"], c["id"]
    if collaborator_id == "" or who is None:
        return who, (None if collaborator_id == "" else keep)
    name = who.strip().lower()
    full = [c for c in collabs if c["name"].lower() == name]
    first = [c for c in collabs if c["first_name"].lower() == name] if name != _first_name(current.name).lower() else []
    hit = full if len(full) == 1 else first if len(first) == 1 else []
    return (hit[0]["name"] if hit else who), (hit[0]["id"] if hit else None)


async def _tell_collaborator(collab: dict, text: str, done_data: Optional[str] = None) -> bool:
    """A message to a collaborator's Telegram, with the "✅ Fatto" button when given."""
    if not collab.get("telegram_chat_id") or collab.get("status") != "active" or not tg.bot_token():
        return False
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Fatto", callback_data=done_data)]]) if done_data else None
    bot = Bot(token=tg.bot_token())
    for mode in ("Markdown", None):
        try:
            await bot.send_message(chat_id=collab["telegram_chat_id"], text=text, reply_markup=kb, **({"parse_mode": mode} if mode else {}))
            return True
        except Exception:
            if mode is None:
                logger.exception(f"message to collaborator {collab.get('id')} failed")
    return False


def _assignment_text(kind: str, item: dict, view: dict, change: str, old_due: Optional[str] = None) -> str:
    what = item.get("text") if kind == "todo" else item.get("title")
    where = f"«{view.get('title')}» — {view.get('client_name')}"
    due = item.get("due_date")
    if change == "date":
        head = f"📅 Nuova scadenza per {'l’attività' if kind == 'todo' else 'la milestone'} *{what}*"
        return f"{head}\n{where} · {'entro ' + _short_it_date(due) if due else 'senza data'}" + (f" (era {_short_it_date(old_due)})" if old_due else "")
    if kind == "todo" and item.get("kind") == "materiale":   # materials to take: one per line
        return (f"📌 Da prendere per te{' entro ' + _short_it_date(due) if due else ''}:\n{_mat_bullets(item)}\n{where}"
                "\nQuando l'hai preso tocca ✅ Fatto.")
    head = f"📌 Nuova attività per te: *{what}*" if kind == "todo" else f"🚩 Milestone affidata a te: *{what}*"
    return (f"{head}\n{where}" + (f" · {'entro' if kind == 'todo' else 'scadenza'} {_short_it_date(due)}" if due else "")
            + "\nQuando è fatta tocca ✅ Fatto.")


async def _notify_assignee(kind: str, item: dict, view: dict, change: str = "new", old_due: Optional[str] = None) -> bool:
    if not item.get("collaborator_id") or item.get("done"):
        return False
    c = await db.collaborators.find_one({"id": item["collaborator_id"]}, {"_id": 0})
    if not c or item["commessa_id"] not in (c.get("commesse") or []):
        return False
    return await _tell_collaborator(c, _assignment_text(kind, item, view, change, old_due), f"cldone:{kind[0]}:{item['id']}")


COLLAB_NOT_YOURS = "Questa attività non è più tra le tue."


async def _collab_mark_done(collab: dict, kind: str, item_id: str) -> str:
    """The "✅ Fatto" of a collaborator: the To Do / milestone done, a line in the diary, the
    owner told. -> the answer for the collaborator."""
    coll = db.job_todos if kind == "t" else db.job_milestones
    item = await coll.find_one({"id": item_id}, {"_id": 0})
    if not item or item["commessa_id"] not in (collab.get("commesse") or []) \
            or (item.get("collaborator_id") and item["collaborator_id"] != collab["id"] and collab["id"] not in (item.get("shared_with") or [])):
        return COLLAB_NOT_YOURS
    what = item.get("text") if kind == "t" else item.get("title")
    if item.get("done"):
        return f"«{what}» era già segnata come fatta 👍"
    today = jl.today_local().isoformat()
    if kind == "t":
        await coll.update_one({"id": item_id}, {"$set": {"done": True, "done_at": datetime.now(timezone.utc).isoformat(), "done_by": _collab_name(collab)}})
    else:
        await coll.update_one({"id": item_id}, {"$set": {"done": True, "done_date": today, "done_by": _collab_name(collab)}})
    owner_doc = await db.users.find_one({"user_id": collab["owner_user_id"]}, {"_id": 0})
    sub = await db.collection_sub_items.find_one({"id": item["commessa_id"]}, {"_id": 0})
    clienti = await db.collections.find_one({"id": sub.get("collection_id")}, {"_id": 0}) if sub else None
    if not owner_doc or not sub or not clienti:
        return f"✅ «{what}» segnata come fatta."
    owner = User(**owner_doc)
    client = await db.collection_items.find_one({"id": sub.get("item_id")}, {"_id": 0, "embedding": 0})
    view = _commessa_view(sub, client, clienti)
    who = _collab_name(collab) + (f" ({collab['company']})" if collab.get("company") else "")
    if kind == "t":
        line = f"Attività «{what}» fatta (segnata da {who} su Telegram)."
    else:
        m = _milestone_view({**item, "done": True, "done_date": today}, today)
        late = f", {m['delay_days']} {'giorno' if m['delay_days'] == 1 else 'giorni'} di ritardo" if m["delay_days"] else ", in tempo"
        line = f"Milestone «{what}» completata il {_short_it_date(today)}{late} (segnata da {who} su Telegram)."
    await _log_commessa_event(owner, view, "todo" if kind == "t" else "milestone", line,
                              {"todo_id" if kind == "t" else "milestone_id": item_id}, author_name=collab.get("first_name") or _collab_name(collab))
    _day_pin_touch(collab["id"], item.get("collaborator_id"), *(item.get("shared_with") or []))
    push.fire_and_forget(db, owner.user_id, f"✅ {_collab_name(collab)} · {view.get('title')}", f"Fatta: «{what}»",
                         f"/dashboard/journal?commessa={view['id']}", f"done-{item_id}")
    try:
        await _notify_owner(owner, f"✅ {who} ha segnato come fatta {'l’attività' if kind == 't' else 'la milestone'} «{what}» su «{view['title']}» — {view['client_name']}.")
    except Exception:
        logger.exception("owner notice failed")
    return f"✅ Fatto! «{what}» è segnata come fatta, {owner.name.split(' ')[0] if owner.name else 'il titolare'} lo vede nel diario."


async def _todo_reminders(now_utc: Optional[datetime] = None) -> int:
    """To Do given to a collaborator, with a date: from 8:00 the day before, the day itself and
    the first day late, once each (like the milestones). -> how many sent."""
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    if now_local.strftime("%H:%M") < "08:00":
        return 0
    today = now_local.date().isoformat()
    tomorrow = (now_local.date() + timedelta(days=1)).isoformat()
    sent = 0
    for t in await db.job_todos.find({"done": False, "due_date": {"$lte": tomorrow}}, {"_id": 0}).to_list(5000):
        if not t.get("collaborator_id") or not t.get("due_date") or t.get("kind") == "materiale":
            continue
        kind = "before" if t["due_date"] == tomorrow else "due" if t["due_date"] == today else "late"
        if (t.get("reminded") or {}).get(kind) == t["due_date"]:
            continue
        await db.job_todos.update_one({"id": t["id"]}, {"$set": {"reminded": {**(t.get("reminded") or {}), kind: t["due_date"]}}})
        c = await db.collaborators.find_one({"id": t["collaborator_id"]}, {"_id": 0})
        sub = await db.collection_sub_items.find_one({"id": t["commessa_id"]}, {"_id": 0})
        if not c or not sub or t["commessa_id"] not in (c.get("commesse") or []):
            continue
        client = await db.collection_items.find_one({"id": sub.get("item_id")}, {"_id": 0, "embedding": 0})
        coll = await db.collections.find_one({"id": sub.get("collection_id")}, {"_id": 0})
        view = _commessa_view(sub, client, coll or {})
        head = ("⏰ Domani va fatta" if kind == "before" else "⏰ Oggi va fatta" if kind == "due"
                else f"🔴 In ritardo di {_days(today, t['due_date'])} giorni")
        text = f"{head}: *{t['text']}*\n«{view['title']}» — {view['client_name']} · entro {_short_it_date(t['due_date'])}\nQuando è fatta tocca ✅ Fatto."
        try:
            if await _tell_collaborator(c, text, f"cldone:t:{t['id']}"):
                sent += 1
        except Exception:
            logger.exception("to do reminder failed")
    return sent


async def _job_todo_or_404(current: User, todo_id: str) -> dict:
    todo = await db.job_todos.find_one({"id": todo_id}, {"_id": 0})
    if not todo:
        raise HTTPException(status_code=404, detail="Attività non trovata")
    await _commessa_or_404(current, todo["commessa_id"])   # only who sees the commessa
    return todo


@api_router.post("/jobs/commesse/{commessa_id}/todos")
async def create_job_todo(commessa_id: str, payload: JobTodoPayload, current: User = Depends(get_current_user)):
    clienti, sub, client = await _commessa_or_404(current, commessa_id)
    text = " ".join((payload.text or "").split())
    if not text:
        raise HTTPException(status_code=400, detail="Scrivi l'attività da fare")
    who, collab_id = await _resolve_assignee(current, commessa_id, (payload.who or "").strip()[:60], payload.collaborator_id)
    doc = {
        "id": f"jtodo_{uuid.uuid4().hex[:12]}", "commessa_id": commessa_id, "collection_id": clienti["id"],
        "user_id": current.user_id, "org_id": current.org_id, "author_name": _first_name(current.name),
        "text": text[:500], "who": who or _first_name(current.name), "collaborator_id": collab_id,
        "due_date": _valid_due(payload.due_date), "done": False, "done_at": None, "reminded": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.job_todos.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("reminded", None)
    doc["notified"] = await _notify_assignee("todo", doc, _commessa_view(sub, client, clienti))
    _day_pin_touch(collab_id)
    return doc


@api_router.patch("/jobs/todos/{todo_id}")
async def update_job_todo(todo_id: str, payload: JobTodoPatch, current: User = Depends(get_current_user)):
    todo = await _job_todo_or_404(current, todo_id)
    upd: dict = {}
    if payload.text is not None:
        text = " ".join(payload.text.split())
        if not text:
            raise HTTPException(status_code=400, detail="Scrivi l'attività da fare")
        upd["text"] = text[:500]
    if payload.who is not None or payload.collaborator_id is not None:
        who, collab_id = await _resolve_assignee(current, todo["commessa_id"], payload.who.strip()[:60] if payload.who is not None else None,
                                                 payload.collaborator_id, keep=todo.get("collaborator_id"))
        if who is not None:
            upd["who"] = who or todo.get("who") or _first_name(current.name)
        upd["collaborator_id"] = collab_id
    if payload.due_date is not None:
        upd["due_date"] = _valid_due(payload.due_date)
        if upd["due_date"] != todo.get("due_date"):
            upd["reminded"] = {}
    if payload.done is not None:
        upd["done"] = payload.done
        upd["done_at"] = datetime.now(timezone.utc).isoformat() if payload.done else None
    if upd:
        await db.job_todos.update_one({"id": todo_id}, {"$set": upd})
    out = {k: v for k, v in {**todo, **upd}.items() if k != "reminded"}
    _day_pin_touch(todo.get("collaborator_id"), out.get("collaborator_id"), *(todo.get("shared_with") or []))
    new_collab = upd.get("collaborator_id") and upd["collaborator_id"] != todo.get("collaborator_id")
    moved = "reminded" in upd and out.get("collaborator_id") and not new_collab
    if new_collab or moved:
        clienti, sub, client = await _commessa_or_404(current, todo["commessa_id"])
        out["notified"] = await _notify_assignee("todo", out, _commessa_view(sub, client, clienti),
                                                 "new" if new_collab else "date", todo.get("due_date"))
    return out


@api_router.delete("/jobs/todos/{todo_id}")
async def delete_job_todo(todo_id: str, current: User = Depends(get_current_user)):
    todo = await _job_todo_or_404(current, todo_id)
    await db.job_todos.delete_one({"id": todo_id})
    _day_pin_touch(todo.get("collaborator_id"), *(todo.get("shared_with") or []))
    return {"ok": True}


# ---- the commessa's MILESTONES: the project's steps, who does them and by when. Done ones keep
# their execution date; the first planned date stays, so delays are measured; a late one gets
# corrective actions (with a new date). Reminders on Telegram: the day before, the day itself
# and when late - to whoever created it and to who has to do it (a team mate or a collaborator).

class MilestonePayload(BaseModel):
    title: str
    who: Optional[str] = ""
    due_date: str                             # scadenza, YYYY-MM-DD
    collaborator_id: Optional[str] = None


class MilestonePatch(BaseModel):
    title: Optional[str] = None
    who: Optional[str] = None
    due_date: Optional[str] = None
    done: Optional[bool] = None
    done_date: Optional[str] = None           # the day it was done (default today)
    collaborator_id: Optional[str] = None     # "" = no longer a collaborator's


class MilestoneActionPayload(BaseModel):
    text: str
    new_due_date: Optional[str] = None


def _days(a: str, b: str) -> int:
    return (datetime.strptime(a, "%Y-%m-%d").date() - datetime.strptime(b, "%Y-%m-%d").date()).days


def _milestone_view(m: dict, today: Optional[str] = None) -> dict:
    """The milestone with its state: done (and how late against the first plan), late (days past
    the current date), soon (within 3 days), planned; slip = how far the date was moved."""
    today = today or jl.today_local().isoformat()
    due, orig = m["due_date"], m.get("original_due_date") or m["due_date"]
    out = {**m, "slip_days": _days(due, orig)}
    if m.get("done"):
        done = m.get("done_date") or today
        out.update({"status": "done", "delay_days": max(0, _days(done, orig)), "late_days": 0})
    elif due < today:
        out.update({"status": "late", "late_days": _days(today, due), "delay_days": _days(today, orig)})
    else:
        out.update({"status": "soon" if _days(due, today) <= 3 else "planned", "late_days": 0, "delay_days": max(0, _days(due, orig))})
    return out


def _milestones_summary(views: list) -> dict:
    done = [v for v in views if v["status"] == "done"]
    late = [v for v in views if v["status"] == "late"]
    return {"total": len(views), "done": len(done), "late": len(late),
            "on_time": sum(1 for v in done if not v["delay_days"]),
            "avg_delay": round(sum(v["delay_days"] for v in done) / len(done), 1) if done else 0,
            "next": next((v for v in views if v["status"] != "done"), None)}


async def _commessa_milestones(commessa_id: str) -> list:
    ms = await db.job_milestones.find({"commessa_id": commessa_id}, {"_id": 0, "reminded": 0}).to_list(500)
    today = jl.today_local().isoformat()
    return [_milestone_view(m, today) for m in sorted(ms, key=lambda x: (x["due_date"], x.get("created_at") or ""))]


def milestones_line(views: list) -> str:
    """For the commessa's chat: every milestone with its state."""
    if not views:
        return ""
    def one(v):
        st = (f"fatta il {v.get('done_date')}" + (f", {v['delay_days']} giorni di ritardo" if v["delay_days"] else ", in tempo")
              if v["status"] == "done" else f"in ritardo di {v['late_days']} giorni" if v["status"] == "late" else "da fare")
        acts = "; ".join(a["text"] for a in v.get("corrective_actions") or [])
        return f"«{v['title']}» ({v.get('who') or '-'}) scadenza {v['due_date']}: {st}" + (f" [azioni correttive: {acts}]" if acts else "")
    return " | ".join(one(v) for v in views)


async def _milestone_or_404(current: User, ms_id: str) -> tuple:
    m = await db.job_milestones.find_one({"id": ms_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Milestone non trovata")
    clienti, sub, client = await _commessa_or_404(current, m["commessa_id"])
    return m, _commessa_view(sub, client, clienti)


async def _log_commessa_event(current: User, view: dict, kind: str, text: str, extra: Optional[dict] = None,
                              author_name: Optional[str] = None) -> None:
    """A line of the commessa's diary that is not work done (a milestone reached, an action)."""
    log = {"id": f"jlog_{uuid.uuid4().hex[:12]}", "kind": kind, **(extra or {}),
           "user_id": current.user_id, "org_id": current.org_id, "author_name": author_name or _first_name(current.name),
           "collection_id": view.get("collection_id"), "client_item_id": view.get("client_item_id"), "client_name": view.get("client_name"),
           "commessa_id": view["id"], "commessa_title": view.get("title"), "date": jl.today_local().isoformat(),
           "raw_text": text, "text": text, "hours": [], "materials": [], "problems": [], "photos": [],
           "channel": "web", "created_at": datetime.now(timezone.utc).isoformat(), "embedding": None}
    await db.job_logs.insert_one(log)


@api_router.get("/jobs/commesse/{commessa_id}/milestones")
async def list_milestones(commessa_id: str, current: User = Depends(get_current_user)):
    await _commessa_or_404(current, commessa_id, write=False)
    views = await _commessa_milestones(commessa_id)
    return {"milestones": views, "summary": _milestones_summary(views)}


@api_router.post("/jobs/commesse/{commessa_id}/milestones")
async def create_milestone(commessa_id: str, payload: MilestonePayload, current: User = Depends(get_current_user)):
    clienti, sub, client = await _commessa_or_404(current, commessa_id)
    title = " ".join((payload.title or "").split())
    if not title:
        raise HTTPException(status_code=400, detail="Scrivi la milestone")
    due = _valid_due(payload.due_date)
    if not due:
        raise HTTPException(status_code=400, detail="Indica la scadenza")
    who, collab_id = await _resolve_assignee(current, commessa_id, (payload.who or "").strip()[:60], payload.collaborator_id)
    doc = {"id": f"jms_{uuid.uuid4().hex[:12]}", "commessa_id": commessa_id, "collection_id": clienti["id"],
           "user_id": current.user_id, "org_id": current.org_id, "author_name": _first_name(current.name),
           "title": title[:200], "who": who or _first_name(current.name), "collaborator_id": collab_id,
           "due_date": due, "original_due_date": due, "done": False, "done_date": None, "corrective_actions": [],
           "reminded": {}, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.job_milestones.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("reminded", None)
    notified = await _notify_assignee("milestone", doc, _commessa_view(sub, client, clienti))
    _day_pin_touch(await _ms_collab_id(doc))
    return {**_milestone_view(doc), "notified": notified}


@api_router.patch("/jobs/milestones/{ms_id}")
async def update_milestone(ms_id: str, payload: MilestonePatch, current: User = Depends(get_current_user)):
    m, view = await _milestone_or_404(current, ms_id)
    today = jl.today_local().isoformat()
    upd: dict = {}
    if payload.title is not None:
        title = " ".join(payload.title.split())
        if not title:
            raise HTTPException(status_code=400, detail="Scrivi la milestone")
        upd["title"] = title[:200]
    if payload.who is not None or payload.collaborator_id is not None:
        who, collab_id = await _resolve_assignee(current, m["commessa_id"], payload.who.strip()[:60] if payload.who is not None else None,
                                                 payload.collaborator_id, keep=m.get("collaborator_id"))
        if who is not None:
            upd["who"] = who or m.get("who")
        upd["collaborator_id"] = collab_id
    if payload.due_date is not None:
        due = _valid_due(payload.due_date)
        if not due:
            raise HTTPException(status_code=400, detail="Indica la scadenza")
        upd["due_date"] = due
        # a new plan before anything slipped is not a delay: the first date moves too
        if not m.get("done") and not m.get("corrective_actions") and m["due_date"] >= today:
            upd["original_due_date"] = due
        upd["reminded"] = {}
    if payload.done is not None and payload.done != bool(m.get("done")):
        upd["done"] = payload.done
        upd["done_date"] = (_valid_due(payload.done_date) or today) if payload.done else None
    elif payload.done_date is not None and m.get("done"):
        upd["done_date"] = _valid_due(payload.done_date) or today
    if upd:
        await db.job_milestones.update_one({"id": ms_id}, {"$set": upd})
    out = _milestone_view({k: v for k, v in {**m, **upd}.items() if k != "reminded"}, today)
    _day_pin_touch(await _ms_collab_id(m), await _ms_collab_id(out))
    new_collab = upd.get("collaborator_id") and upd["collaborator_id"] != m.get("collaborator_id")
    moved = upd.get("due_date") and upd["due_date"] != m["due_date"] and out.get("collaborator_id") and not new_collab
    if new_collab or moved:
        out["notified"] = await _notify_assignee("milestone", out, view, "new" if new_collab else "date", m["due_date"])
    if upd.get("done"):
        late = f", {out['delay_days']} {'giorno' if out['delay_days'] == 1 else 'giorni'} di ritardo" if out["delay_days"] else ", in tempo"
        await _log_commessa_event(current, view, "milestone", f"Milestone «{out['title']}» completata il {_short_it_date(out['done_date'])}{late}.",
                                  {"milestone_id": ms_id})
    return out


@api_router.post("/jobs/milestones/{ms_id}/actions")
async def add_milestone_action(ms_id: str, payload: MilestoneActionPayload, current: User = Depends(get_current_user)):
    """A corrective action on a late (or at risk) milestone; with a new date the deadline moves,
    the first one stays to measure the delay."""
    m, view = await _milestone_or_404(current, ms_id)
    text = " ".join((payload.text or "").split())
    if not text:
        raise HTTPException(status_code=400, detail="Scrivi l'azione correttiva")
    new_due = _valid_due(payload.new_due_date)
    act = {"id": f"act_{uuid.uuid4().hex[:8]}", "text": text[:500], "new_due_date": new_due, "old_due_date": m["due_date"],
           "by": _first_name(current.name), "at": datetime.now(timezone.utc).isoformat()}
    upd = {"corrective_actions": (m.get("corrective_actions") or []) + [act]}
    if new_due:
        upd.update({"due_date": new_due, "reminded": {}})
    await db.job_milestones.update_one({"id": ms_id}, {"$set": upd})
    if new_due and new_due != m["due_date"]:
        await _notify_assignee("milestone", {**m, **upd}, view, "date", m["due_date"])
        _day_pin_touch(await _ms_collab_id(m))
    await _log_commessa_event(current, view, "milestone",
                              f"Milestone «{m['title']}»: azione correttiva — {text}"
                              + (f" Nuova scadenza {_short_it_date(new_due)} (era {_short_it_date(m['due_date'])})." if new_due else ""),
                              {"milestone_id": ms_id})
    return _milestone_view({k: v for k, v in {**m, **upd}.items() if k != "reminded"})


@api_router.delete("/jobs/milestones/{ms_id}")
async def delete_milestone(ms_id: str, current: User = Depends(get_current_user)):
    m, _view = await _milestone_or_404(current, ms_id)
    await db.job_milestones.delete_one({"id": ms_id})
    _day_pin_touch(await _ms_collab_id(m))
    return {"ok": True}


# ---- MILESTONE TEMPLATES (see milestone_templates.py): the ready-made ones and the ones saved
# from a commessa (shared by the team); applied to a commessa from a start date.

class MilestoneTemplatePayload(BaseModel):
    name: Optional[str] = None
    steps: Optional[list] = None              # [{"title", "day"}] - day: working days from the start


class SaveMilestoneTemplatePayload(BaseModel):
    name: str


class ApplyMilestoneTemplatePayload(BaseModel):
    template_id: str
    start_date: Optional[str] = None          # default: today


def _tpl_owner(current: User) -> str:
    return current.org_id or current.user_id


async def _milestone_template_or_404(current: User, tpl_id: str) -> dict:
    t = await db.milestone_templates.find_one({"id": tpl_id, "owner_key": _tpl_owner(current)}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Modello non trovato")
    return t


async def _new_milestone_template(current: User, name: str, steps: list, source: Optional[str] = None) -> dict:
    name = " ".join((name or "").split())[:80]
    steps = mtpl.clean_steps(steps)
    if not name:
        raise HTTPException(status_code=400, detail="Scrivi il nome del modello")
    if not steps:
        raise HTTPException(status_code=400, detail="Il modello non ha milestone")
    doc = {"id": f"mtpl_{uuid.uuid4().hex[:12]}", "owner_key": _tpl_owner(current), "name": name, "steps": steps,
           "source": source, "created_by": current.user_id, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.milestone_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.get("/jobs/milestone-templates")
async def list_milestone_templates(current: User = Depends(get_current_user)):
    custom = await db.milestone_templates.find({"owner_key": _tpl_owner(current)}, {"_id": 0}).sort("name", 1).to_list(200)
    return {"builtin": mtpl.builtin_list(), "custom": custom}


@api_router.post("/jobs/milestone-templates")
async def create_milestone_template(payload: MilestoneTemplatePayload, current: User = Depends(get_current_user)):
    """A template of their own (e.g. a ready-made one copied, to change it)."""
    return await _new_milestone_template(current, payload.name or "", payload.steps or [])


@api_router.post("/jobs/commesse/{commessa_id}/milestone-templates")
async def save_milestone_template(commessa_id: str, payload: SaveMilestoneTemplatePayload, current: User = Depends(get_current_user)):
    """The commessa's milestones as a template: each first planned date as working days from
    the start (the commessa's start date, or its first milestone)."""
    clienti, sub, client = await _commessa_or_404(current, commessa_id, write=False)
    ms = await db.job_milestones.find({"commessa_id": commessa_id}, {"_id": 0}).to_list(500)
    if not ms:
        raise HTTPException(status_code=400, detail="La commessa non ha milestone da salvare")
    first = min(date.fromisoformat((m.get("original_due_date") or m["due_date"])[:10]) for m in ms)
    begin = _commessa_view(sub, client, clienti).get("data_inizio")
    try:
        start = min(first, date.fromisoformat(str(begin)[:10])) if begin else first
    except ValueError:
        start = first
    return await _new_milestone_template(current, payload.name, mtpl.from_milestones(ms, start), source=commessa_id)


@api_router.patch("/jobs/milestone-templates/{tpl_id}")
async def update_milestone_template(tpl_id: str, payload: MilestoneTemplatePayload, current: User = Depends(get_current_user)):
    t = await _milestone_template_or_404(current, tpl_id)
    upd = {}
    if payload.name is not None:
        upd["name"] = " ".join(payload.name.split())[:80]
        if not upd["name"]:
            raise HTTPException(status_code=400, detail="Scrivi il nome del modello")
    if payload.steps is not None:
        upd["steps"] = mtpl.clean_steps(payload.steps)
        if not upd["steps"]:
            raise HTTPException(status_code=400, detail="Il modello non ha milestone")
    if upd:
        await db.milestone_templates.update_one({"id": tpl_id}, {"$set": upd})
    return {**t, **upd}


@api_router.delete("/jobs/milestone-templates/{tpl_id}")
async def delete_milestone_template(tpl_id: str, current: User = Depends(get_current_user)):
    await _milestone_template_or_404(current, tpl_id)
    await db.milestone_templates.delete_one({"id": tpl_id})
    return {"ok": True}


@api_router.post("/jobs/commesse/{commessa_id}/milestones/from-template")
async def apply_milestone_template(commessa_id: str, payload: ApplyMilestoneTemplatePayload, current: User = Depends(get_current_user)):
    """The template's milestones on the commessa, from the start date (working days); the ones
    the commessa already has (same title) are left as they are."""
    await _commessa_or_404(current, commessa_id)
    t = mtpl.builtin(payload.template_id) if payload.template_id.startswith("builtin:") \
        else await _milestone_template_or_404(current, payload.template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Modello non trovato")
    start = date.fromisoformat(_valid_due(payload.start_date) or jl.today_local().isoformat())
    have = {" ".join((m.get("title") or "").lower().split())
            for m in await db.job_milestones.find({"commessa_id": commessa_id}, {"_id": 0, "title": 1}).to_list(500)}
    created, skipped = [], []
    for st in t["steps"]:
        if " ".join(st["title"].lower().split()) in have:
            skipped.append(st["title"])
            continue
        due = mtpl.add_workdays(start, st["day"]).isoformat()
        created.append(await create_milestone(commessa_id, MilestonePayload(title=st["title"], due_date=due), current))
    return {"created": len(created), "skipped": skipped, "milestones": created, "template": t["name"]}


async def _milestone_recipients(m: dict) -> list:
    """Telegram chats to remind: who created it, and who has to do it - a team mate or a
    collaborator enabled on that commessa, recognized by name."""
    chats = []
    owner = await db.users.find_one({"user_id": m["user_id"]}, {"_id": 0, "telegram_chat_id": 1, "org_id": 1})
    if owner and owner.get("telegram_chat_id"):
        chats.append(owner["telegram_chat_id"])
    who = (m.get("who") or "").strip().lower()
    if who:
        if m.get("org_id"):
            for u in await db.users.find(_team_q(m["org_id"]), {"_id": 0, "name": 1, "telegram_chat_id": 1}).to_list(200):
                if u.get("telegram_chat_id") and who in {(u.get("name") or "").strip().lower(), _first_name(u.get("name")).lower()}:
                    chats.append(u["telegram_chat_id"])
    return list(dict.fromkeys(chats))


async def _ms_collab_id(m: dict) -> Optional[str]:
    return (await _milestone_collaborator(m) or {}).get("id")


async def _milestone_collaborator(m: dict) -> Optional[dict]:
    """The collaborator who has to do it: the one it was given to, or (older ones) by name."""
    if m.get("collaborator_id"):
        c = await db.collaborators.find_one({"id": m["collaborator_id"]}, {"_id": 0})
        return c if c and m["commessa_id"] in (c.get("commesse") or []) else None
    who = (m.get("who") or "").strip().lower()
    if not who:
        return None
    for c in await db.collaborators.find({"commesse": {"$in": [m["commessa_id"]]}, "status": "active"}, {"_id": 0}).to_list(200):
        if who in {(c.get("first_name") or "").lower(), _collab_name(c).lower()}:
            return c
    return None


async def _milestone_reminders(now_utc: Optional[datetime] = None) -> int:
    """From 8:00, once per kind and per deadline: the day before, the day itself, and the first
    day it is late (asking to mark it done or to write a corrective action). -> how many sent."""
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    if now_local.strftime("%H:%M") < "08:00":
        return 0
    today = now_local.date().isoformat()
    tomorrow = (now_local.date() + timedelta(days=1)).isoformat()
    sent = 0
    for m in await db.job_milestones.find({"done": False, "due_date": {"$lte": tomorrow}}, {"_id": 0}).to_list(5000):
        kind = "before" if m["due_date"] == tomorrow else "due" if m["due_date"] == today else "late"
        if (m.get("reminded") or {}).get(kind) == m["due_date"]:
            continue
        await db.job_milestones.update_one({"id": m["id"]}, {"$set": {"reminded": {**(m.get("reminded") or {}), kind: m["due_date"]}}})
        sub = await db.collection_sub_items.find_one({"id": m["commessa_id"]}, {"_id": 0})
        coll = await db.collections.find_one({"id": m.get("collection_id")}, {"_id": 0}) if sub else None
        if not sub or not coll:
            continue
        client = await db.collection_items.find_one({"id": sub.get("item_id")}, {"_id": 0, "embedding": 0})
        view = _commessa_view(sub, client, coll)
        where = f"«{view['title']}» — {view['client_name']}"
        head = (f"🚩 Domani scade la milestone *{m['title']}*" if kind == "before" else
                f"🚩 Oggi scade la milestone *{m['title']}*" if kind == "due" else
                f"🔴 Milestone in ritardo di {_days(today, m['due_date'])} giorni: *{m['title']}*")
        text = (f"{head}\n{where} · {m.get('who') or ''} · scadenza {_short_it_date(m['due_date'])}"
                + ("\nSe è fatta segnala come fatta; se no scrivi un'azione correttiva con la nuova data "
                   "(diario della commessa → Milestone)." if kind == "late" else ""))
        for chat in await _milestone_recipients(m):
            try:
                if await _send_telegram_text(chat, text):
                    sent += 1
            except Exception:
                logger.exception("milestone reminder failed")
        c = await _milestone_collaborator(m)
        if c:
            try:
                ctext = text.replace("\nSe è fatta segnala come fatta; se no scrivi un'azione correttiva con la nuova data "
                                     "(diario della commessa → Milestone).", "") + "\nQuando è fatta tocca ✅ Fatto."
                if await _tell_collaborator(c, ctext, f"cldone:m:{m['id']}"):
                    sent += 1
            except Exception:
                logger.exception("milestone reminder to collaborator failed")
    return sent


# ---- the commessa's USEFUL CONTACTS: the other trades and people of the job (plumber,
# electrician, site manager, supplier...), with role, phone, e-mail. A contact used on other
# commesse is suggested again (the directory), so it is written once.

JOB_CONTACT_ROLES = ["Idraulico", "Elettricista", "Muratore", "Imbianchino", "Serramentista", "Piastrellista",
                     "Direttore lavori", "Geometra", "Fornitore", "Amministratore di condominio", "Referente del cliente"]


class JobContactPayload(BaseModel):
    role: Optional[str] = ""
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    note: Optional[str] = ""


def _clean_contact(payload: JobContactPayload) -> dict:
    name = " ".join((payload.name or "").split())[:80]
    if not name:
        raise HTTPException(status_code=400, detail="Scrivi il nome del contatto")
    email = (payload.email or "").strip()[:120]
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Email non valida")
    return {"role": " ".join((payload.role or "").split())[:60], "name": name,
            "phone": " ".join((payload.phone or "").split())[:40], "email": email, "note": (payload.note or "").strip()[:300]}


async def _commessa_contacts(commessa_id: str) -> list:
    out = await db.job_contacts.find({"commessa_id": commessa_id}, {"_id": 0}).to_list(200)
    return sorted(out, key=lambda c: ((c.get("role") or "~").lower(), c["name"].lower()))


def contacts_line(contacts: list) -> str:
    """For the commessa's chat."""
    return " | ".join(", ".join(x for x in (c.get("role"), c["name"], c.get("phone"), c.get("email"), c.get("note")) if x) for c in contacts)


async def _job_contact_or_404(current: User, contact_id: str) -> dict:
    c = await db.job_contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Contatto non trovato")
    await _commessa_or_404(current, c["commessa_id"])
    return c


@api_router.get("/jobs/commesse/{commessa_id}/contacts")
async def list_job_contacts(commessa_id: str, current: User = Depends(get_current_user)):
    await _commessa_or_404(current, commessa_id, write=False)
    return await _commessa_contacts(commessa_id)


@api_router.post("/jobs/commesse/{commessa_id}/contacts")
async def create_job_contact(commessa_id: str, payload: JobContactPayload, current: User = Depends(get_current_user)):
    clienti, _, _ = await _commessa_or_404(current, commessa_id)
    doc = {"id": f"jct_{uuid.uuid4().hex[:12]}", "commessa_id": commessa_id, "collection_id": clienti["id"],
           "user_id": current.user_id, "org_id": current.org_id, **_clean_contact(payload),
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db.job_contacts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/jobs/contacts/{contact_id}")
async def update_job_contact(contact_id: str, payload: JobContactPayload, current: User = Depends(get_current_user)):
    c = await _job_contact_or_404(current, contact_id)
    upd = _clean_contact(payload)
    await db.job_contacts.update_one({"id": contact_id}, {"$set": upd})
    return {**c, **upd}


@api_router.delete("/jobs/contacts/{contact_id}")
async def delete_job_contact(contact_id: str, current: User = Depends(get_current_user)):
    await _job_contact_or_404(current, contact_id)
    await db.job_contacts.delete_one({"id": contact_id})
    return {"ok": True}


@api_router.get("/jobs/contacts/directory")
async def job_contacts_directory(current: User = Depends(get_current_user)):
    """The contacts already used on the commesse the user sees (one per name and phone, the most
    recent), and the usual roles: to fill a new contact with a tap."""
    clienti = await _clienti_list(current)
    seen, out = set(), []
    if clienti:
        rows = await db.job_contacts.find({"collection_id": clienti["id"]}, {"_id": 0}).to_list(5000)
        for c in sorted(rows, key=lambda x: x.get("created_at") or "", reverse=True):
            key = (c["name"].lower(), re.sub(r"\D", "", c.get("phone") or ""))
            if key not in seen:
                seen.add(key)
                out.append({k: c.get(k, "") for k in ("role", "name", "phone", "email", "note")})
    roles = list(dict.fromkeys(JOB_CONTACT_ROLES + [c["role"] for c in out if c.get("role")]))
    return {"contacts": out[:500], "roles": roles}


# ============ COSTI E MARGINI della commessa ============
# Hourly costs per person (and a default one) and the materials' unit prices are on the
# Clienti list - the same for every commessa; the quote (preventivo) and the other costs on
# the commessa (job_economics). The admin gets a Telegram note at 80% and 100% of the quote.

BUDGET_ALERTS = (80, 100)


class EconomicsPatch(BaseModel):
    budget: Optional[float] = None
    clear_budget: bool = False


class ExtraCostPayload(BaseModel):
    label: str
    amount: float
    date: Optional[str] = None


class CostsPatch(BaseModel):
    default_rate: Optional[float] = None
    clear_default_rate: bool = False
    rates: Optional[dict] = None       # {person: €/h, or null to remove}
    prices: Optional[List[dict]] = None   # [{name, unit, price (null to remove)}]


def _num_or_none(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if f >= 0 else None


async def _commessa_economics(clienti: dict, commessa_id: str, logs: Optional[list] = None) -> dict:
    costs = clienti.get("costs") or {}
    econ = await db.job_economics.find_one({"commessa_id": commessa_id}, {"_id": 0}) or {}
    if logs is None:
        logs = await db.job_logs.find({"commessa_id": commessa_id}, {"_id": 0, "hours": 1, "materials": 1, "problems": 1, "kind": 1, "date": 1}).to_list(20000)
    return jl.economics(logs, costs.get("rates"), costs.get("default_rate"), costs.get("prices"), econ.get("extras"), econ.get("budget"))


async def _check_budget_alert(clienti: dict, commessa_id: str) -> None:
    """Once per threshold (80%, 100% of the quote): a note to the list's owner on Telegram.
    Lowered again (quote raised, costs removed), the thresholds re-arm."""
    try:
        econ_doc = await db.job_economics.find_one({"commessa_id": commessa_id}, {"_id": 0}) or {}
        if not econ_doc.get("budget"):
            return
        e = await _commessa_economics(clienti, commessa_id)
        pct = e["used_pct"] or 0
        sent = set(econ_doc.get("alerts") or [])
        keep = {t for t in sent if pct >= t}
        new = [t for t in BUDGET_ALERTS if pct >= t and t not in sent]
        if keep != sent or new:
            await db.job_economics.update_one({"commessa_id": commessa_id}, {"$set": {"alerts": sorted(keep | set(new))}})
        if not new:
            return
        owner_doc = await db.users.find_one({"user_id": clienti.get("user_id")}, {"_id": 0})
        sub = await db.collection_sub_items.find_one({"id": commessa_id}, {"_id": 0})
        client = await db.collection_items.find_one({"id": (sub or {}).get("item_id")}, {"_id": 0, "embedding": 0}) if sub else None
        if not owner_doc or not sub:
            return
        v = _commessa_view(sub, client, clienti)
        t = max(new)
        head = "🔴 Preventivo superato" if t >= 100 else "🟠 Attenzione al preventivo"
        await _notify_owner(User(**owner_doc), f"{head} su «{v['title']}» — {v['client_name']}: speso {jl._eur(e['cost_total'])} "
                                               f"di {jl._eur(e['budget'])} ({pct:.0f}%), margine {jl._eur(e['margin'])}.")
    except Exception:
        logger.exception("budget alert failed")


def _econ_people(e: dict, team: list, collabs: list) -> list:
    """Whose hourly cost can be set: who has hours here, the team, the collaborators."""
    names = [x["who"] for x in e["labor"]] + team + collabs
    return list(dict.fromkeys(n for n in names if n))


@api_router.get("/jobs/commesse/{commessa_id}/economics")
async def get_commessa_economics(commessa_id: str, current: User = Depends(get_current_user)):
    clienti, _, _ = await _commessa_or_404(current, commessa_id, write=False)
    e = await _commessa_economics(clienti, commessa_id)
    costs = clienti.get("costs") or {}
    team = await _team_first_names(current)
    collabs = [c.get("first_name") for c in await db.collaborators.find({"owner_user_id": clienti.get("user_id")}, {"_id": 0, "first_name": 1}).to_list(500)]
    rates = costs.get("rates") or {}
    return {**e, "default_rate": costs.get("default_rate"),
            "people": [{"who": n, "rate": _rate_of(rates, n)} for n in _econ_people(e, team, collabs)]}


@api_router.patch("/jobs/commesse/{commessa_id}/economics")
async def patch_commessa_economics(commessa_id: str, payload: EconomicsPatch, current: User = Depends(get_current_user)):
    """The quote (what the client pays) of a commessa."""
    clienti, _, _ = await _commessa_or_404(current, commessa_id)
    budget = None if payload.clear_budget else _num_or_none(payload.budget)
    await db.job_economics.update_one({"commessa_id": commessa_id}, {"$set": {"commessa_id": commessa_id, "budget": budget}}, upsert=True)
    await _check_budget_alert(clienti, commessa_id)
    return await get_commessa_economics(commessa_id, current)


@api_router.post("/jobs/commesse/{commessa_id}/extras")
async def add_commessa_extra(commessa_id: str, payload: ExtraCostPayload, current: User = Depends(get_current_user)):
    """Another cost of the commessa: scaffolding hire, disposal, a subcontract..."""
    clienti, _, _ = await _commessa_or_404(current, commessa_id)
    label = " ".join((payload.label or "").split())[:120]
    amount = _num_or_none(payload.amount)
    if not label or amount is None:
        raise HTTPException(status_code=400, detail="Scrivi la voce e l'importo")
    extra = {"id": f"xc_{uuid.uuid4().hex[:10]}", "label": label, "amount": amount,
             "date": (payload.date or jl.today_local().isoformat())[:10], "by": _first_name(current.name)}
    econ = await db.job_economics.find_one({"commessa_id": commessa_id}, {"_id": 0})
    if econ:
        await db.job_economics.update_one({"commessa_id": commessa_id}, {"$push": {"extras": extra}})
    else:
        await db.job_economics.insert_one({"commessa_id": commessa_id, "budget": None, "extras": [extra], "alerts": []})
    await _check_budget_alert(clienti, commessa_id)
    return await get_commessa_economics(commessa_id, current)


@api_router.delete("/jobs/commesse/{commessa_id}/extras/{extra_id}")
async def delete_commessa_extra(commessa_id: str, extra_id: str, current: User = Depends(get_current_user)):
    clienti, _, _ = await _commessa_or_404(current, commessa_id)
    econ = await db.job_economics.find_one({"commessa_id": commessa_id}, {"_id": 0}) or {}
    extras = [x for x in econ.get("extras") or [] if x.get("id") != extra_id]
    await db.job_economics.update_one({"commessa_id": commessa_id}, {"$set": {"extras": extras}})
    await _check_budget_alert(clienti, commessa_id)
    return await get_commessa_economics(commessa_id, current)


@api_router.patch("/jobs/costs")
async def patch_job_costs(payload: CostsPatch, commessa_id: Optional[str] = None, current: User = Depends(get_current_user)):
    """Hourly costs and material prices, the same for every commessa (kept on the Clienti list -
    for a commessa shared by a team-mate, theirs)."""
    if commessa_id:
        clienti, _sub, _client = await _commessa_or_404(current, commessa_id)
    else:
        clienti = await _clienti_list(current)
        if clienti:
            _require_list_edit(clienti, current)
    if not clienti:
        raise HTTPException(status_code=404, detail="Lista Clienti non trovata")
    costs = dict(clienti.get("costs") or {})
    if payload.clear_default_rate:
        costs["default_rate"] = None
    elif payload.default_rate is not None:
        costs["default_rate"] = _num_or_none(payload.default_rate)
    if payload.rates is not None:
        rates = dict(costs.get("rates") or {})
        for who, v in payload.rates.items():
            who = " ".join(str(who).split())[:60]
            val = _num_or_none(v) if v is not None else None
            if not who:
                continue
            if val is None:
                rates.pop(who, None)
            else:
                rates[who] = val
        costs["rates"] = rates
    if payload.prices is not None:
        prices = dict(costs.get("prices") or {})
        for p in payload.prices:
            name = " ".join(str(p.get("name") or "").split())[:120]
            if not name:
                continue
            key = jl.price_key(name, p.get("unit") or "")
            val = _num_or_none(p.get("price")) if p.get("price") is not None else None
            if val is None:
                prices.pop(key, None)
            else:
                prices[key] = {"name": name, "unit": (p.get("unit") or "")[:20], "price": val}
        costs["prices"] = prices
    await db.collections.update_one({"id": clienti["id"]}, {"$set": {"costs": costs}})
    clienti["costs"] = costs
    if commessa_id:
        await _check_budget_alert(clienti, commessa_id)
        return await get_commessa_economics(commessa_id, current)
    return {"ok": True, "costs": costs}


# ============ COLLABORATORI: solo Telegram, solo le commesse abilitate ============
# People outside the app (subcontractors, workers) who write in the diario di commessa and ask
# about a commessa from Telegram, nothing else: no account, no access to the app. For now the
# platform Admin manages them (later: the subscription's holder). See collab_telegram.py.

COLLAB_CODE_DAYS = 7
COLLAB_DAILY_LIMIT = 80          # messages per collaborator per day (the AI cost is the account's)
COLLAB_UNDO_MINUTES = 10         # "Annulla" under a saved entry
COLLAB_REMIND_AT = "18:00"       # end-of-day reminder, Monday-Friday, if nothing was written today


class CollaboratorPayload(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = ""                 # optional: the invitation goes by WhatsApp to the phone
    phone: Optional[str] = ""
    role: Optional[str] = ""
    company: Optional[str] = ""
    commesse: List[str] = []
    show_client_contacts: Optional[bool] = None   # (none: the organization's rule)
    hourly_rate: Optional[float] = None       # €/h: their default cost on the commesse (Costi can change it)


class CollaboratorPatch(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    company: Optional[str] = None
    commesse: Optional[List[str]] = None
    show_client_contacts: Optional[bool] = None
    status: Optional[Literal["active", "suspended"]] = None
    hourly_rate: Optional[float] = None
    clear_hourly_rate: bool = False


async def _can_manage_collaborators(current: User) -> bool:
    """The organization's administrators link its collaborators (Telegram only), within the plan."""
    return current.role == "admin" and bool(current.tenant_id)


async def _require_collab_manager(current: User) -> None:
    if not await _can_manage_collaborators(current):
        raise HTTPException(status_code=403, detail="I collaboratori li gestisce l'amministratore della tua organizzazione")


def _collab_code() -> str:
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))


def _phone_digits(phone: Optional[str]) -> str:
    """'+39 333 123 4567' / '0039…' / '333 1234567' -> '393331234567' (WhatsApp and the check
    of the Telegram contact compare these)."""
    d = re.sub(r"\D", "", phone or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 10 and d.startswith("3"):
        d = "39" + d
    return d


def _collab_name(c: dict) -> str:
    return f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()


async def _collab_views(current: User) -> dict:
    """{commessa id: view} of the admin's commesse (the ones a collaborator can be enabled on)."""
    clienti = await _clienti_list(current)
    if not clienti:
        return {}
    commesse, _ = await _all_commesse(clienti)
    return {c["id"]: c for c in commesse}


def _rate_of(rates: Optional[dict], name: Optional[str]) -> Optional[float]:
    """The hourly cost of a person on the Clienti list (by first name, as the diary counts the hours)."""
    low = (name or "").strip().lower()
    return next((v for k, v in (rates or {}).items() if k.lower() == low and v is not None), None) if low else None


async def _list_rates(current: User) -> dict:
    clienti = await _clienti_list(current)
    return ((clienti or {}).get("costs") or {}).get("rates") or {}


async def _set_person_rate(current: User, name: str, rate: Optional[float]) -> None:
    """A collaborator's hourly cost, kept with the others on the Clienti list: the one the Costi
    of every commessa use (and change)."""
    clienti = await _clienti_list(current)
    name = " ".join((name or "").split())[:60]
    if not clienti or not name:
        return
    costs = dict(clienti.get("costs") or {})
    rates = {k: v for k, v in (costs.get("rates") or {}).items() if k.lower() != name.lower()}
    if rate is not None:
        rates[name] = rate
    costs["rates"] = rates
    await db.collections.update_one({"id": clienti["id"]}, {"$set": {"costs": costs}})


def _collab_public(c: dict, views: dict, rates: Optional[dict] = None) -> dict:
    out = {k: c.get(k) for k in ("id", "first_name", "last_name", "email", "phone", "role", "company", "status",
                                  "show_client_contacts", "linked_at", "last_message_at", "created_at", "code_expires_at")}
    out["name"] = _collab_name(c)
    out["hourly_rate"] = _rate_of(rates, c.get("first_name"))
    out["linked"] = bool(c.get("telegram_chat_id"))
    out["commesse"] = [{"id": cid, "title": views[cid]["title"], "client_name": views[cid]["client_name"], "stato": views[cid]["stato"]}
                       for cid in c.get("commesse") or [] if cid in views]
    expired = not c.get("code_expires_at") or c["code_expires_at"] < datetime.now(timezone.utc).isoformat()
    out["code"] = c.get("code") if c.get("code") and not expired else None
    return out


async def _collab_invite(current: User, c: dict, views: dict) -> dict:
    """The message to send the collaborator (on WhatsApp, or copied): link + code."""
    username = await tg.bot_username()
    link = f"https://t.me/{username}?start={c['code']}" if username else None
    jobs = ", ".join(f"{views[cid]['title']} ({views[cid]['client_name']})" for cid in c.get("commesse") or [] if cid in views)
    msg = (f"Ciao {c['first_name']}, {current.name or 'il tuo referente'} ti ha invitato a collaborare con mAIPAL"
           + (f" sulle commesse: {jobs}" if jobs else "") + ".\n"
           "Da Telegram potrai scrivere (anche a voce o con le foto) cosa fate in cantiere e chiedere informazioni sulle commesse.\n\n"
           + (f"1. Apri questo link: {link}\n2. Premi «Avvia».\n" if link else "1. Apri Telegram e cerca il bot di mAIPAL.\n")
           + f"Se ti chiede un codice, scrivi: /start {c['code']}\n"
           f"Il codice vale {COLLAB_CODE_DAYS} giorni.")
    from urllib.parse import quote
    phone = _phone_digits(c.get("phone"))
    return {"code": c["code"], "link": link, "message": msg, "expires_at": c.get("code_expires_at"),
            "whatsapp_url": f"https://wa.me/{phone}?text={quote(msg)}" if phone else f"https://wa.me/?text={quote(msg)}"}


def _org_collabs_q(current: User) -> dict:
    """The organization's collaborators (any of its administrators manages them)."""
    return {"$or": [{"tenant_id": current.tenant_id}, {"owner_user_id": current.user_id}]} if current.tenant_id \
        else {"owner_user_id": current.user_id}


async def _collab_or_404(current: User, collab_id: str) -> dict:
    c = await db.collaborators.find_one({"id": collab_id, **_org_collabs_q(current)}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Collaboratore non trovato")
    return c


def _clean_collab_fields(d: dict) -> dict:
    """Trimmed fields; the e-mail, if given, must look like one; the phone, if given, must have
    8-15 digits once normalized (an Italian mobile without +39 gets it)."""
    out = {}
    for k in ("first_name", "last_name", "email", "phone", "role", "company"):
        if d.get(k) is not None:
            out[k] = " ".join(str(d[k]).split())[:120]
    if out.get("email"):
        out["email"] = out["email"].lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", out["email"]):
            raise HTTPException(status_code=400, detail="Email non valida")
    if out.get("phone") and not 8 <= len(_phone_digits(out["phone"])) <= 15:
        raise HTTPException(status_code=400, detail="Numero di telefono non valido")
    return out


@api_router.get("/collaborators")
async def list_collaborators(current: User = Depends(get_current_user)):
    await _require_collab_manager(current)
    views = await _collab_views(current)
    docs = await db.collaborators.find(_org_collabs_q(current), {"_id": 0}).sort("created_at", -1).to_list(500)
    rates = await _list_rates(current)
    return [_collab_public(c, views, rates) for c in docs]


@api_router.post("/collaborators")
async def create_collaborator(payload: CollaboratorPayload, current: User = Depends(get_current_user)):
    await _require_collab_manager(current)
    fields = _clean_collab_fields(payload.model_dump())
    if not fields.get("first_name") or not fields.get("last_name"):
        raise HTTPException(status_code=400, detail="Nome e cognome sono obbligatori")
    tenant = await _tenant_of(current)
    limit = _plan(tenant)["max_collaborators"]
    if await db.collaborators.count_documents({"tenant_id": current.tenant_id}) >= limit:
        raise HTTPException(status_code=403, detail=f"Hai già {limit} collaboratori, il massimo del tuo abbonamento.")
    contacts = payload.show_client_contacts
    if contacts is None:
        contacts = bool(((tenant or {}).get("sharing") or {}).get("collab_contacts"))
    views = await _collab_views(current)
    now = datetime.now(timezone.utc)
    c = {
        "id": f"collab_{uuid.uuid4().hex[:12]}", "owner_user_id": current.user_id, "org_id": current.org_id, "tenant_id": current.tenant_id,
        **fields, "commesse": [x for x in dict.fromkeys(payload.commesse) if x in views],
        "show_client_contacts": contacts, "status": "invited",
        "code": _collab_code(), "code_expires_at": (now + timedelta(days=COLLAB_CODE_DAYS)).isoformat(),
        "telegram_chat_id": None, "linked_at": None, "last_message_at": None, "created_at": now.isoformat(),
    }
    await db.collaborators.insert_one(c)
    c.pop("_id", None)
    rate = _num_or_none(payload.hourly_rate)
    if rate is not None:
        await _set_person_rate(current, c["first_name"], rate)
    return {"collaborator": _collab_public(c, views, await _list_rates(current)), "invite": await _collab_invite(current, c, views)}


@api_router.patch("/collaborators/{collab_id}")
async def update_collaborator(collab_id: str, payload: CollaboratorPatch, current: User = Depends(get_current_user)):
    await _require_collab_manager(current)
    c = await _collab_or_404(current, collab_id)
    views = await _collab_views(current)
    upd = _clean_collab_fields(payload.model_dump(exclude_none=True))
    if payload.commesse is not None:
        upd["commesse"] = [x for x in dict.fromkeys(payload.commesse) if x in views]
    if payload.show_client_contacts is not None:
        upd["show_client_contacts"] = payload.show_client_contacts
    if payload.status is not None:
        if c.get("status") == "invited" and payload.status == "active":
            raise HTTPException(status_code=400, detail="Il collaboratore non si è ancora collegato a Telegram")
        upd["status"] = payload.status
    old_first = c.get("first_name")
    if upd:
        await db.collaborators.update_one({"id": collab_id}, {"$set": upd})
        c.update(upd)
    rates = await _list_rates(current)
    rate = None if payload.clear_hourly_rate else _num_or_none(payload.hourly_rate)
    if payload.clear_hourly_rate or rate is not None:
        await _set_person_rate(current, c["first_name"], rate)
    elif c["first_name"].lower() != (old_first or "").lower() and _rate_of(rates, old_first) is not None \
            and _rate_of(rates, c["first_name"]) is None:   # renamed: their cost follows them
        await _set_person_rate(current, c["first_name"], _rate_of(rates, old_first))
    return _collab_public(c, views, await _list_rates(current))


@api_router.post("/collaborators/{collab_id}/invite")
async def reinvite_collaborator(collab_id: str, current: User = Depends(get_current_user)):
    """A new code (the old one stops working): to send again, or to link a new phone."""
    await _require_collab_manager(current)
    c = await _collab_or_404(current, collab_id)
    views = await _collab_views(current)
    upd = {"code": _collab_code(), "code_expires_at": (datetime.now(timezone.utc) + timedelta(days=COLLAB_CODE_DAYS)).isoformat()}
    await db.collaborators.update_one({"id": collab_id}, {"$set": upd})
    c.update(upd)
    return {"collaborator": _collab_public(c, views, await _list_rates(current)), "invite": await _collab_invite(current, c, views)}


@api_router.delete("/collaborators/{collab_id}")
async def delete_collaborator(collab_id: str, current: User = Depends(get_current_user)):
    """Removed: they can't write any more; what they already wrote stays in the diary."""
    await _require_collab_manager(current)
    await _collab_or_404(current, collab_id)
    await db.collaborators.delete_one({"id": collab_id})
    return {"ok": True}


@api_router.get("/jobs/commesse/{commessa_id}/collaborators")
async def commessa_collaborators(commessa_id: str, current: User = Depends(get_current_user)):
    """From the commessa's diary: every collaborator, and whether they are enabled on it."""
    await _require_collab_manager(current)
    await _commessa_or_404(current, commessa_id, write=False)
    docs = await db.collaborators.find(_org_collabs_q(current), {"_id": 0}).sort("first_name", 1).to_list(500)
    return [{"id": c["id"], "name": _collab_name(c), "company": c.get("company") or "", "role": c.get("role") or "",
             "status": c.get("status"), "enabled": commessa_id in (c.get("commesse") or [])} for c in docs]


class CommessaGeoPayload(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None               # none: found again from the address


@api_router.put("/jobs/commesse/{commessa_id}/geo")
async def set_commessa_geo(commessa_id: str, payload: CommessaGeoPayload, current: User = Depends(get_current_user)):
    """The site's position for the presences: set here (e.g. from the phone, on site) or from the address."""
    clienti, sub, client = await _commessa_or_404(current, commessa_id)
    if payload.lat is not None and payload.lon is not None:
        if not (-90 <= payload.lat <= 90 and -180 <= payload.lon <= 180):
            raise HTTPException(status_code=400, detail="Posizione non valida")
        geo = {"lat": payload.lat, "lon": payload.lon, "source": "manual", "address": None}
        await db.collection_sub_items.update_one({"id": commessa_id}, {"$set": {"geo": geo}})
        return geo
    await db.collection_sub_items.update_one({"id": commessa_id}, {"$set": {"geo": None}})
    found = await _commessa_geo(commessa_id, _commessa_view(sub, client, clienti))
    if not found:
        raise HTTPException(status_code=400, detail="Non trovo l'indirizzo del cantiere sulla mappa: controlla l'indirizzo o imposta la posizione quando sei sul posto.")
    return found


class CollabEnablePayload(BaseModel):
    enabled: bool


@api_router.put("/jobs/commesse/{commessa_id}/collaborators/{collab_id}")
async def set_commessa_collaborator(commessa_id: str, collab_id: str, payload: CollabEnablePayload, current: User = Depends(get_current_user)):
    """From the commessa's diary: enable or disable one collaborator on it."""
    await _require_collab_manager(current)
    acc = await _commessa_access(current, commessa_id)
    if not acc or acc["shared_by"] is not None:   # (a team-mate's commessa: their collaborators)
        raise HTTPException(status_code=404, detail="Commessa non trovata")
    await _commessa_or_404(current, commessa_id)
    await _collab_or_404(current, collab_id)
    op = {"$addToSet": {"commesse": commessa_id}} if payload.enabled else {"$pull": {"commesse": commessa_id}}
    await db.collaborators.update_one({"id": collab_id}, op)
    return {"ok": True, "enabled": payload.enabled}


async def _collab_targets(collab: dict) -> list:
    """What a collaborator can work on right now: [(owner User, clienti list, commessa view)] for
    the commesse enabled and not closed (a closed commessa closes their access by itself)."""
    if collab.get("status") != "active":
        return []
    owner_doc = await db.users.find_one({"user_id": collab["owner_user_id"]}, {"_id": 0})
    if not owner_doc:
        return []
    owner = User(**owner_doc)
    clienti = await _clienti_list(owner)
    if not clienti:
        return []
    commesse, _ = await _all_commesse(clienti)
    enabled = set(collab.get("commesse") or [])
    return [(owner, clienti, v) for v in commesse if v["id"] in enabled and v["stato"] != "chiusa"]


async def _collab_answer(collab: dict, owner: User, view: dict, question: str, history: list) -> str:
    """A collaborator's question on ONE of their commesse: only that commessa's data, the client's
    phone and e-mail left out unless the admin allowed them."""
    if not collab.get("show_client_contacts"):
        view = {k: v for k, v in view.items() if k not in ("client_phone", "client_email")}
    # the reports' lines in the diary carry their summary: the reports below, filtered, say enough
    logs = await db.job_logs.find({"commessa_id": view["id"], "kind": {"$ne": "report"}}, {"_id": 0, "embedding": 0}).to_list(5000)
    logs.sort(key=lambda lg: (lg.get("date") or "", lg.get("created_at") or ""))
    reports = await db.work_reports.find({"commessa_id": view["id"]}, {"_id": 0, "docx_b64": 0, "embedding": 0, "summary": 0}).to_list(50)
    hidden = r"stima economica|prezz|cost|import|preventiv"   # money never reaches a collaborator
    if not collab.get("show_client_contacts"):
        hidden += r"|telefon|cellulare|email|e-mail|mail|contatt"
    hide = re.compile(hidden, re.I)
    for r in reports:
        for sec in r.get("sections") or []:
            sec["fields"] = {f: v for f, v in (sec.get("fields") or {}).items() if not hide.search(f)}
    open_todos = [t for t in await db.job_todos.find({"commessa_id": view["id"], "done": False}, {"_id": 0}).to_list(300)]
    view = {**view, "milestones_line": milestones_line(await _commessa_milestones(view["id"])),
            "todos_line": " | ".join(f"«{t['text']}» ({t.get('who') or '-'})" + (f" entro {t['due_date']}" if t.get("due_date") else "")
                                     for t in _sort_job_todos(open_todos)),
            "contacts_line": contacts_line(await _commessa_contacts(view["id"]))}   # the job's trades: useful to them too
    out = await jl.answer(view, logs, reports, question, history[-8:], user_id=owner.user_id, channel="telegram")
    return out["answer"]


async def _collab_remind_due(now_utc: Optional[datetime] = None) -> int:
    """End of the working day (Mon-Fri, from COLLAB_REMIND_AT): every linked collaborator who
    wrote nothing today gets "Cosa hai fatto oggi?" with a button per commessa. Once a day.
    -> how many were reminded."""
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    if now_local.weekday() >= 5 or now_local.strftime("%H:%M") < COLLAB_REMIND_AT:
        return 0
    today = now_local.date().isoformat()
    sent = 0
    for c in await db.collaborators.find({"status": "active", "telegram_chat_id": {"$ne": None}, "reminded_on": {"$ne": today}}, {"_id": 0}).to_list(2000):
        await db.collaborators.update_one({"id": c["id"]}, {"$set": {"reminded_on": today}})
        open_ = await _open_presence(c["id"])
        if open_:
            if await _tell_collaborator(c, f"⏱️ Hai ancora il tempo aperto su «{open_['commessa_title']}» dalle "
                                           f"{sp.hhmm(_local(open_['start_at']))}: quando hai finito tocca 📍 Ho finito "
                                           "(o scrivi «ho finito alle 17:30»)."):
                sent += 1
            continue
        if await db.job_logs.find_one({"collaborator_id": c["id"], "date": today}, {"_id": 1}):
            continue
        targets = await _collab_targets(c)
        if not targets:
            continue
        try:
            from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{v['title']} · {v['client_name']}"[:60], callback_data=f"clc:{v['id']}")]
                                       for _o, _cl, v in targets[:8]])
            await Bot(token=tg.bot_token()).send_message(
                chat_id=c["telegram_chat_id"], reply_markup=kb,
                text=f"Ciao {c.get('first_name', '')}, cosa avete fatto oggi? Scegli la commessa e raccontamelo, anche a voce.")
            sent += 1
        except Exception:
            logger.exception(f"collaborator reminder to {c['id']} failed")
    return sent


# ---- PRESENCE ON SITE (see site_presence.py): "sono arrivato" / "ho finito" on Telegram, with
# the position sent by the button; the time in between is the collaborator's hours in the diary.

async def _commessa_geo(commessa_id: str, view: dict) -> Optional[dict]:
    """The site's position: the one set by the owner, or found from the commessa's address
    (looked up once per address, kept on the commessa)."""
    sub = await db.collection_sub_items.find_one({"id": commessa_id}, {"_id": 0, "geo": 1})
    geo = (sub or {}).get("geo") or {}
    if geo.get("source") == "manual" and geo.get("lat") is not None:
        return geo
    addr = (view.get("address") or "").strip()
    if not addr:
        return None
    if geo.get("address") != addr:
        found = await sp.geocode(addr)
        geo = {"address": addr, "source": "address", "lat": (found or {}).get("lat"), "lon": (found or {}).get("lon")}
        await db.collection_sub_items.update_one({"id": commessa_id}, {"$set": {"geo": geo}})
    return geo if geo.get("lat") is not None else None


async def _open_presence(collab_id: str) -> Optional[dict]:
    return await db.work_sessions.find_one({"collaborator_id": collab_id, "end_at": None}, {"_id": 0})


# Not only the collaborators: the app's users (the owner, the colleagues of the team) say they
# are on site too - from the app or the bot. Their presence is the same thing, kept under the id
# "usr_<user_id>" in work_sessions.collaborator_id ("who is working"); their diary entry is theirs.
USER_WORKER = "usr_"


def _user_worker(udoc: dict, owner_user_id: Optional[str] = None) -> dict:
    """An app user as "who is on site". owner_user_id: whose Clienti list the commesse are."""
    first = _first_name(udoc.get("name")) or "Io"
    rest = " ".join((udoc.get("name") or "").split()[1:])
    return {"id": f"{USER_WORKER}{udoc['user_id']}", "user_id": udoc["user_id"], "owner_user_id": owner_user_id or udoc["user_id"],
            "first_name": first, "last_name": rest, "company": "", "status": "active",
            "telegram_chat_id": udoc.get("telegram_chat_id"), "is_user": True}


async def _worker_of(worker_id: Optional[str]) -> Optional[dict]:
    """Who a work session belongs to: a collaborator, or an app user."""
    if not worker_id:
        return None
    if worker_id.startswith(USER_WORKER):
        u = await db.users.find_one({"user_id": worker_id[len(USER_WORKER):]}, {"_id": 0})
        return _user_worker(u) if u else None
    return await db.collaborators.find_one({"id": worker_id}, {"_id": 0})


async def _tg_send(chat_id, text: str, kb=None) -> bool:
    """A Telegram message (Markdown, plain text if that fails)."""
    if not chat_id or not tg.bot_token():
        return False
    from telegram import Bot
    bot = Bot(token=tg.bot_token())
    for mode in ("Markdown", None):
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, **({"parse_mode": mode} if mode else {}))
            return True
        except Exception:
            if mode is None:
                logger.exception("telegram message failed")
    return False


async def _tell_worker(w: dict, text: str, kb=None) -> bool:
    """To whoever is on site, on Telegram: a collaborator (if active) or an app user (if linked)."""
    if not w or w.get("status", "active") != "active":
        return False
    if not w.get("is_user") and kb is None:   # a plain message to a collaborator: the usual way
        return await _tell_collaborator(w, text)
    return await _tg_send(w.get("telegram_chat_id"), text, kb)


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(LOCAL_TZ)


async def _presence_start(collab: dict, owner: Optional[User], view: Optional[dict], at: datetime, loc: Optional[dict]) -> str:
    """The start of the work on a commessa (an open one is only recalled). -> the answer for the collaborator."""
    open_ = await _open_presence(collab["id"])
    if open_:
        return (f"Hai già il tempo aperto su «{open_['commessa_title']}» dalle {sp.hhmm(_local(open_['start_at']))}: "
                "quando hai finito tocca 📍 Ho finito (o scrivi «ho finito»).")
    geo = await _commessa_geo(view["id"], view) if loc else None
    d = sp.distance_m(loc, geo)
    doc = {"id": f"ws_{uuid.uuid4().hex[:12]}", "collaborator_id": collab["id"], "user_id": collab.get("user_id"),
           "owner_user_id": collab["owner_user_id"], "org_id": owner.org_id if owner else None, "commessa_id": view["id"], "commessa_title": view.get("title"), "client_name": view.get("client_name"),
           "start_at": at.astimezone(timezone.utc).isoformat(), "start_loc": loc, "start_m": d, "site_known": geo is not None,
           "end_at": None, "end_loc": None, "end_m": None, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.work_sessions.insert_one(doc)
    # the conversation is about this commessa now: what they write next goes there
    await db.collaborators.update_one({"id": collab["id"]}, {"$set": {"tg_state": {"target": view["id"], "at": datetime.now(timezone.utc).isoformat()}}})
    where = f"«{view.get('title')}» — {view.get('client_name')}"
    msg = f"🟢 Inizio alle {sp.hhmm(at.astimezone(LOCAL_TZ))} su {where}"
    msg += f" ({sp.distance_text(d)})." if d is not None else "." if loc else " (senza posizione)."
    if sp.far(d):
        msg += f"\n⚠️ Risulti {sp.distance_text(d)}: se sei nel posto giusto va bene così, la distanza resta segnata."
    if sp.far(d) and owner and owner.user_id != collab.get("user_id"):
        push.fire_and_forget(db, owner.user_id, f"⚠️ {_collab_name(collab)} · {view.get('title')}",
                             f"Inizio lavoro {sp.distance_text(d)}", f"/dashboard/journal?commessa={view['id']}", f"ws-{doc['id']}")
    if loc and geo is None:
        msg += "\n(La posizione del cantiere non è nota: la tua resta salvata.)"
    return msg + "\nQuando hai finito tocca 📍 Ho finito (o scrivi «ho finito»)." + ("" if loc else "\nCon il pulsante 📍 si registra anche la posizione.")


async def _presence_stop(collab: dict, at: datetime, loc: Optional[dict], channel: str = "telegram") -> tuple:
    """The end: the hours in the diary of that commessa. -> (answer, diary entry id or None)."""
    s_ = await _open_presence(collab["id"])
    if not s_:
        return ("Non hai un inizio aperto: quando arrivi in cantiere tocca 📍 Sono arrivato (o scrivi «sono arrivato»). "
                "Se hai dimenticato di segnarlo scrivimi gli orari, es. «oggi dalle 8 alle 17»"
                + (": li metto nel diario." if collab.get("is_user") else ": vanno nel diario come ore da approvare dal titolare."), None)
    start = datetime.fromisoformat(s_["start_at"])
    minutes = int((at - start).total_seconds() // 60)
    if minutes <= 0:
        return (f"L'orario di fine è prima dell'inizio ({sp.hhmm(_local(s_['start_at']))}): scrivimi l'ora giusta, es. «ho finito alle 17:30».", None)
    if minutes > sp.FORGOTTEN_HOURS * 60:
        return (f"Dall'inizio ({_short_it_date(_local(s_['start_at']).date().isoformat())} alle {sp.hhmm(_local(s_['start_at']))}) sono passate "
                f"più di {sp.FORGOTTEN_HOURS} ore: scrivimi a che ora hai finito, es. «ho finito alle 17:30».", None)
    sub = await db.collection_sub_items.find_one({"id": s_["commessa_id"]}, {"_id": 0})
    clienti = await db.collections.find_one({"id": (sub or {}).get("collection_id")}, {"_id": 0}) if sub else None
    owner_doc = await db.users.find_one({"user_id": collab["owner_user_id"]}, {"_id": 0})
    if not sub or not clienti or not owner_doc:
        await db.work_sessions.update_one({"id": s_["id"]}, {"$set": {"end_at": at.astimezone(timezone.utc).isoformat(), "orphan": True}})
        return ("La commessa non c'è più: non ho potuto registrare le ore.", None)
    owner = User(**owner_doc)
    client = await db.collection_items.find_one({"id": sub.get("item_id")}, {"_id": 0, "embedding": 0})
    view = _commessa_view(sub, client, clienti)
    geo = await _commessa_geo(view["id"], view) if loc else None
    d_end = sp.distance_m(loc, geo)
    hours = sp.round_hours(minutes)
    log = _presence_log(collab, owner, view, s_, at, minutes, 0, loc, d_end, channel)
    await db.job_logs.insert_one(log)
    log.pop("_id", None)
    await db.work_sessions.update_one({"id": s_["id"]}, {"$set": {"end_at": at.astimezone(timezone.utc).isoformat(), "end_loc": loc,
                                                                  "end_m": d_end, "minutes": minutes, "log_id": log["id"]}})
    if s_.get("late_asked_at") and not s_.get("late_answer_at"):   # the evening's question answered by closing
        await _presence_answered(s_, collab, left_at=at)
    await db.collaborators.update_one({"id": collab["id"]}, {"$set": {"tg_state": {"target": view["id"], "at": datetime.now(timezone.utc).isoformat()}}})
    if not collab.get("is_user"):
        author = {"id": collab["id"], "first_name": collab.get("first_name") or "", "name": _collab_name(collab), "company": collab.get("company") or ""}
        _push_collab_entry(owner, log, author)
    if hours:
        asyncio.create_task(_check_budget_alert(clienti, view["id"]))
    msg = (f"🔴 Fine alle {sp.hhmm(at.astimezone(LOCAL_TZ))}: {sp.fmt_duration(minutes)} su «{view['title']}» → "
           f"{jl._fmt_num(hours)} h nel diario" + (f" ({sp.distance_text(d_end)})." if d_end is not None else "."))
    if sp.far(d_end):
        msg += f"\n⚠️ Risulti {sp.distance_text(d_end)}: la distanza resta segnata."
    return msg + "\nSe hai fatto pause toglile con i pulsanti; poi, se vuoi, scrivimi cosa avete fatto oggi.", log["id"]


def _presence_log(collab: dict, owner: User, view: dict, s_: dict, end: datetime, minutes: int, pause: int,
                  end_loc: Optional[dict], end_m: Optional[int], channel: str = "telegram") -> dict:
    """The diary entry of a presence: the times, the hours (pauses out) and how far from the site."""
    start_l, end_l = _local(s_["start_at"]), end.astimezone(LOCAL_TZ)
    worked = max(0, minutes - pause)
    warn = [f"inizio {sp.distance_text(s_.get('start_m'))}"] if sp.far(s_.get("start_m")) else []
    if sp.far(end_m):
        warn.append(f"fine {sp.distance_text(end_m)}")
    text = (f"In cantiere dalle {sp.hhmm(start_l)} alle {sp.hhmm(end_l)} ({sp.fmt_duration(worked)}"
            + (f", pausa {sp.fmt_duration(pause)} esclusa" if pause else "") + ")" + (f" · ⚠️ {', '.join(warn)}" if warn else ""))
    return {
        "id": f"jlog_{uuid.uuid4().hex[:12]}", "user_id": collab.get("user_id") or owner.user_id, "org_id": owner.org_id,
        "author_name": collab.get("first_name") or _collab_name(collab), "collaborator_id": None if collab.get("is_user") else collab["id"],
        "author_company": collab.get("company") or "",
        "collection_id": view["collection_id"], "client_item_id": view["client_item_id"], "client_name": view["client_name"],
        "commessa_id": view["id"], "commessa_title": view["title"], "date": start_l.date().isoformat(),
        "raw_text": text, "text": text, "hours": [{"who": collab.get("first_name") or _collab_name(collab), "hours": sp.round_hours(worked)}],
        "materials": [], "problems": [], "photos": [], "channel": channel, "conv_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(), "embedding": None,
        "presence": {"session_id": s_["id"], "start_at": s_["start_at"], "end_at": end.astimezone(timezone.utc).isoformat(),
                     "minutes": minutes, "pause_min": pause, "start_m": s_.get("start_m"), "end_m": end_m,
                     "start_loc": s_.get("start_loc"), "end_loc": end_loc, "site_known": s_.get("site_known")},
    }


PRESENCE_GONE = "Non trovo più quella voce."


async def _presence_pause(collab: dict, log_id: str, pause: int) -> str:
    """A pause taken out of a presence's hours (the last choice counts; 0 = none)."""
    log = await db.job_logs.find_one({"id": log_id}, {"_id": 0})
    mine = log and ((collab.get("is_user") and log.get("user_id") == collab.get("user_id") and not log.get("collaborator_id"))
                    or (not collab.get("is_user") and log.get("collaborator_id") == collab["id"]))
    if not mine or not log.get("presence"):
        return PRESENCE_GONE
    pr = log["presence"]
    pause = max(0, min(int(pause), pr["minutes"] - 1))
    session = await db.work_sessions.find_one({"id": pr["session_id"]}, {"_id": 0}) or {}
    owner_doc = await db.users.find_one({"user_id": session.get("owner_user_id") or collab["owner_user_id"]}, {"_id": 0})
    if not owner_doc:
        return PRESENCE_GONE
    owner = User(**owner_doc)
    view = {"id": log["commessa_id"], "title": log["commessa_title"], "client_name": log["client_name"],
            "collection_id": log["collection_id"], "client_item_id": log["client_item_id"]}
    s_ = {"id": pr["session_id"], "start_at": pr["start_at"], "start_m": pr.get("start_m"), "start_loc": pr.get("start_loc"),
          "site_known": pr.get("site_known")}
    new = _presence_log(collab, owner, view, s_, datetime.fromisoformat(pr["end_at"]), pr["minutes"], pause, pr.get("end_loc"), pr.get("end_m"),
                        log.get("channel") or "telegram")
    upd = {k: new[k] for k in ("text", "raw_text", "hours", "presence")}
    await db.job_logs.update_one({"id": log_id}, {"$set": {**upd, "embedding": None}})
    if not pause:
        return f"👍 Nessuna pausa: {jl._fmt_num(upd['hours'][0]['hours'])} h nel diario."
    return f"⏸️ Pausa di {sp.fmt_duration(pause)} tolta: {jl._fmt_num(upd['hours'][0]['hours'])} h nel diario."


async def _presence_forgotten(now_utc: Optional[datetime] = None) -> int:
    """A start never ended, after FORGOTTEN_HOURS: closed without hours; the collaborator and the
    owner told (the hours can still be written in the diary). -> how many closed."""
    now = now_utc or datetime.now(timezone.utc)
    limit = (now - timedelta(hours=sp.FORGOTTEN_HOURS)).isoformat()
    n = 0
    for s_ in await db.work_sessions.find({"end_at": None, "start_at": {"$lt": limit}}, {"_id": 0}).to_list(500):
        await db.work_sessions.update_one({"id": s_["id"]}, {"$set": {"end_at": s_["start_at"], "forgotten": True}})
        n += 1
        c = await _worker_of(s_["collaborator_id"])
        when = f"{_short_it_date(_local(s_['start_at']).date().isoformat())} alle {sp.hhmm(_local(s_['start_at']))}"
        if c:
            text = (f"⏱️ Non hai segnato la fine del lavoro su «{s_['commessa_title']}» (iniziato {when}): "
                    "non ho contato le ore. Scrivimi a che ora hai finito, es. «ho finito alle 17.30»"
                    + ("." if c.get("is_user") else ": vanno nel diario come ore da approvare dal titolare."))
            try:
                await _tell_worker(c, text)
            except Exception:
                logger.exception("forgotten presence notice failed")
            if c.get("is_user"):
                push.fire_and_forget(db, c["user_id"], "⏱️ Fine non segnata", text, f"/dashboard/journal?commessa={s_['commessa_id']}", f"ws-{s_['id']}")
        owner_doc = await db.users.find_one({"user_id": s_["owner_user_id"]}, {"_id": 0})
        if owner_doc and c and owner_doc["user_id"] != c.get("user_id"):
            await _notify_owner(User(**owner_doc), f"⏱️ {_collab_name(c)} ha iniziato su «{s_['commessa_title']}» {when} "
                                                   "ma non ha segnato la fine: quelle ore non sono state contate.")
    return n


# ---- the app's users on site, from the app: "📍 Sono in cantiere" / "Ho finito" in the commessa's
# diary (the phone's position if allowed), the pauses, "are you still there?" answered.

class PresencePayload(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    at: Optional[str] = None          # "HH:MM" today, when said later ("ho finito alle 17:30")


class PresencePausePayload(BaseModel):
    log_id: str
    minutes: int = 0


async def _me_worker(current: User) -> dict:
    clienti = await _clienti_list(current)
    udoc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0}) or {"user_id": current.user_id, "name": current.name}
    return _user_worker(udoc, (clienti or {}).get("user_id") or current.user_id)


def _at_today(hhmm: Optional[str], now: datetime, day: Optional[date] = None) -> datetime:
    """"17:30" on that day (today by default), as UTC; now when not given. Never in the future."""
    if not hhmm:
        return now
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", hhmm.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise HTTPException(status_code=400, detail="Orario non valido")
    d = day or now.astimezone(LOCAL_TZ).date()
    at = datetime.combine(d, datetime.min.time().replace(hour=int(m.group(1)), minute=int(m.group(2))), tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    if at > now + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail=f"Le {hhmm} non sono ancora arrivate")
    return at


def _session_view(s_: Optional[dict]) -> Optional[dict]:
    if not s_:
        return None
    return {"id": s_["id"], "commessa_id": s_["commessa_id"], "commessa_title": s_.get("commessa_title"), "client_name": s_.get("client_name"),
            "start_at": s_["start_at"], "start_m": s_.get("start_m"), "far": sp.far(s_.get("start_m")),
            # asked in the evening whether they are still there, not answered yet
            "late_asked": bool(s_.get("late_asked_at")) and not s_.get("late_answer_at")}


@api_router.get("/jobs/presence/me")
async def my_presence(current: User = Depends(get_current_user)):
    """Am I on site now (and where, since when)?"""
    return {"open": _session_view(await _open_presence(f"{USER_WORKER}{current.user_id}"))}


@api_router.post("/jobs/commesse/{commessa_id}/presence/start")
async def presence_start_app(commessa_id: str, payload: PresencePayload, current: User = Depends(get_current_user)):
    clienti, sub, client = await _commessa_or_404(current, commessa_id)
    view = _commessa_view(sub, client, clienti)
    if view["stato"] == "chiusa":
        raise HTTPException(status_code=400, detail="La commessa è chiusa")
    worker = await _me_worker(current)
    open_ = await _open_presence(worker["id"])
    if open_:
        raise HTTPException(status_code=409, detail=f"Sei già in cantiere su «{open_['commessa_title']}» dalle {sp.hhmm(_local(open_['start_at']))}")
    owner_doc = await db.users.find_one({"user_id": clienti.get("user_id")}, {"_id": 0})
    now = datetime.now(timezone.utc)
    loc = {"lat": payload.lat, "lon": payload.lon} if payload.lat is not None and payload.lon is not None else None
    await _presence_start({**worker, "owner_user_id": clienti.get("user_id") or current.user_id},
                          User(**owner_doc) if owner_doc else current, view, _at_today(payload.at, now), loc)
    return {"open": _session_view(await _open_presence(worker["id"]))}


@api_router.post("/jobs/presence/stop")
async def presence_stop_app(payload: PresencePayload, current: User = Depends(get_current_user)):
    worker = await _me_worker(current)
    s_ = await _open_presence(worker["id"])
    if not s_:
        raise HTTPException(status_code=400, detail="Non risulti in cantiere")
    worker["owner_user_id"] = s_.get("owner_user_id") or worker["owner_user_id"]
    now = datetime.now(timezone.utc)
    at = _at_today(payload.at, now, _local(s_["start_at"]).date())
    loc = {"lat": payload.lat, "lon": payload.lon} if payload.lat is not None and payload.lon is not None else None
    answer, log_id = await _presence_stop(worker, at, loc, channel="web")
    if not log_id:
        raise HTTPException(status_code=400, detail=answer)
    log = await db.job_logs.find_one({"id": log_id}, {"_id": 0, "presence": 1, "hours": 1, "commessa_id": 1, "commessa_title": 1})
    return {"message": answer, "log_id": log_id, "minutes": log["presence"]["minutes"], "hours": log["hours"][0]["hours"],
            "commessa_id": log["commessa_id"], "commessa_title": log["commessa_title"]}


@api_router.post("/jobs/presence/pause")
async def presence_pause_app(payload: PresencePausePayload, current: User = Depends(get_current_user)):
    answer = await _presence_pause(await _me_worker(current), payload.log_id, payload.minutes)
    if answer == PRESENCE_GONE:
        raise HTTPException(status_code=404, detail=answer)
    return {"message": answer}


@api_router.post("/jobs/presence/still")
async def presence_still_app(current: User = Depends(get_current_user)):
    """The evening's question answered in the app: yes, still on site."""
    worker = await _me_worker(current)
    s_ = await _open_presence(worker["id"])
    if not s_:
        raise HTTPException(status_code=400, detail="Non risulti in cantiere")
    return {"message": await _presence_late_answer(worker, s_["id"], True)}


# ---- THE EVENING CHECK: past the owner's hour (19:00 unless changed in Impostazioni) whoever is
# still "in cantiere" is asked if they really are (✅ Sì / 🚪 No), the owner is told. "No": at what
# time they left (buttons, or "ho finito alle 17:40") and the time is closed there; "Sì": asked
# again two hours later. A start made late is asked two hours after it.

PRESENCE_LATE_AT = "19:00"
PRESENCE_ASK_AGAIN = timedelta(hours=2)


def _late_threshold(s_: dict, late_at: str) -> datetime:
    start = _local(s_["start_at"])
    h, m = (int(x) for x in (late_at or PRESENCE_LATE_AT).split(":"))
    at = datetime.combine(start.date(), datetime.min.time().replace(hour=h, minute=m), tzinfo=LOCAL_TZ)
    return max(at, start + PRESENCE_ASK_AGAIN).astimezone(timezone.utc)


def _left_options(s_: dict, now: datetime) -> list:
    """Half hours from half an hour after the start to now (the last six): the buttons of "when did you leave?"."""
    start = _local(s_["start_at"]) + timedelta(minutes=30)
    t = start.replace(minute=0 if start.minute == 0 else 30 if start.minute <= 30 else 0, second=0, microsecond=0)
    if t < start:
        t += timedelta(minutes=30)
    out, end = [], now.astimezone(LOCAL_TZ)
    while t <= end:
        out.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return out[-6:]


def _late_kb(sid: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Sì, sono ancora qui", callback_data=f"pls:y:{sid}"),
                                  InlineKeyboardButton("🚪 No, sono andato via", callback_data=f"pls:n:{sid}")]])


def _left_kb(sid: str, options: list):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton(o, callback_data=f"ple:{sid}:{o.replace(':', '')}") for o in options[i:i + 3]] for i in range(0, len(options), 3)]
    return InlineKeyboardMarkup(rows) if rows else None


async def _presence_late_check(now_utc: Optional[datetime] = None) -> int:
    """Asks whoever is still on site past the hour (see above). -> how many asked."""
    now = now_utc or datetime.now(timezone.utc)
    asked = 0
    late_at = {}
    for s_ in await db.work_sessions.find({"end_at": None}, {"_id": 0}).to_list(1000):
        own = s_.get("owner_user_id")
        if own not in late_at:
            od = await db.users.find_one({"user_id": own}, {"_id": 0, "presence_late_at": 1}) or {}
            late_at[own] = od.get("presence_late_at") or PRESENCE_LATE_AT
        due = _late_threshold(s_, late_at[own])
        if s_.get("late_asked_at"):
            nxt = s_.get("late_next_at")
            if not nxt or s_.get("late_answer_at") is None or datetime.fromisoformat(nxt) > now:
                continue
        elif now < due:
            continue
        await db.work_sessions.update_one({"id": s_["id"]}, {"$set": {"late_asked_at": now.isoformat(), "late_answer_at": None, "late_next_at": None}})
        w = await _worker_of(s_["collaborator_id"])
        if not w:
            continue
        since = sp.hhmm(_local(s_["start_at"]))
        text = (f"🕖 Sei ancora in cantiere su «{s_['commessa_title']}»? Risulti lì dalle {since}.\n"
                "Se sei andato via dimmi a che ora, così chiudo il tempo giusto.")
        await _tell_worker(w, text, _late_kb(s_["id"]))
        if w.get("is_user"):
            push.fire_and_forget(db, w["user_id"], "🕖 Sei ancora in cantiere?", f"«{s_['commessa_title']}», dalle {since}: rispondi nel diario.",
                                 f"/dashboard/journal?commessa={s_['commessa_id']}", f"late-{s_['id']}")
        asked += 1
        if own and own != w.get("user_id") and not s_.get("late_told_owner"):
            owner_doc = await db.users.find_one({"user_id": own}, {"_id": 0})
            if owner_doc:
                note = (f"🕖 Alle {sp.hhmm(now.astimezone(LOCAL_TZ))} risulta ancora in cantiere *{_collab_name(w)}* su «{s_['commessa_title']}» "
                        f"(dalle {since}). Gli ho chiesto se è ancora lì: ti dico cosa risponde.")
                await _notify_owner(User(**owner_doc), note)
                push.fire_and_forget(db, own, "🕖 Ancora in cantiere", f"{_collab_name(w)} su «{s_['commessa_title']}» dalle {since}",
                                     f"/dashboard/journal?commessa={s_['commessa_id']}", f"late-o-{s_['id']}")
                await db.work_sessions.update_one({"id": s_["id"]}, {"$set": {"late_told_owner": True}})
    return asked


async def _presence_answered(s_: dict, w: dict, still: bool = False, left_at: Optional[datetime] = None) -> None:
    """The evening's answer: noted on the session and, when it is someone else's, told to the owner."""
    now = datetime.now(timezone.utc)
    upd = {"late_answer_at": now.isoformat(), "late_answer": "si" if still else "no"}
    if still:
        upd["late_next_at"] = (now + PRESENCE_ASK_AGAIN).isoformat()
    await db.work_sessions.update_one({"id": s_["id"]}, {"$set": upd})
    own = s_.get("owner_user_id")
    if not s_.get("late_asked_at") or not own or own == w.get("user_id"):
        return
    owner_doc = await db.users.find_one({"user_id": own}, {"_id": 0})
    if not owner_doc:
        return
    text = (f"✅ {_collab_name(w)} conferma di essere ancora in cantiere su «{s_['commessa_title']}»." if still else
            f"🚪 {_collab_name(w)} era andato via da «{s_['commessa_title']}» alle {sp.hhmm(left_at.astimezone(LOCAL_TZ))}: ore registrate fino a lì.")
    await _notify_owner(User(**owner_doc), text)


async def _presence_late_answer(w: dict, sid: str, still: bool) -> str:
    """✅ Sì (still there) or 🚪 No (asked when they left: the buttons go with _presence_left_kb)."""
    s_ = await db.work_sessions.find_one({"id": sid, "collaborator_id": w["id"]}, {"_id": 0})
    if not s_ or s_.get("end_at"):
        return "Il tempo in cantiere è già chiuso."
    if still:
        await _presence_answered(s_, w, still=True)
        return "👍 Ok, buon lavoro! Quando hai finito tocca 📍 Ho finito (o scrivi «ho finito»)."
    return "🚪 A che ora sei andato via? Tocca l'orario, oppure scrivimelo (es. «ho finito alle 17:40»)."


async def _presence_left_buttons(sid: str):
    s_ = await db.work_sessions.find_one({"id": sid}, {"_id": 0})
    return _left_kb(sid, _left_options(s_, datetime.now(timezone.utc))) if s_ and not s_.get("end_at") else None


async def _presence_left_at(w: dict, sid: str, hhmm: str, channel: str = "telegram") -> tuple:
    """The time they left (a button of the evening's question): the time closed there. -> (answer, log id)."""
    s_ = await db.work_sessions.find_one({"id": sid, "collaborator_id": w["id"]}, {"_id": 0})
    if not s_ or s_.get("end_at"):
        return "Il tempo in cantiere è già chiuso.", None
    hhmm = f"{hhmm[:2]}:{hhmm[2:]}" if re.fullmatch(r"\d{4}", hhmm or "") else hhmm
    try:
        at = _at_today(hhmm, datetime.now(timezone.utc), _local(s_["start_at"]).date())
    except HTTPException as e:
        return e.detail, None
    w = {**w, "owner_user_id": s_.get("owner_user_id") or w.get("owner_user_id")}
    return await _presence_stop(w, at, None, channel)


# ---- "HOW DID IT GO?": a while after someone ends their time on a commessa, if they wrote
# nothing in its diary that day (the hours alone), they are asked - their answer goes there.

PRESENCE_NOTE_AFTER = timedelta(minutes=20)


async def _presence_day_note(now_utc: Optional[datetime] = None) -> int:
    now = now_utc or datetime.now(timezone.utc)
    asked = 0
    q = {"end_at": {"$lte": (now - PRESENCE_NOTE_AFTER).isoformat(), "$gte": (now - timedelta(hours=12)).isoformat()}}
    for s_ in await db.work_sessions.find(q, {"_id": 0}).to_list(1000):
        if s_.get("note_asked") or s_.get("forgotten") or s_.get("orphan") or not s_.get("log_id"):
            continue
        await db.work_sessions.update_one({"id": s_["id"]}, {"$set": {"note_asked": True}})
        w = await _worker_of(s_["collaborator_id"])
        if not w:
            continue
        day = _local(s_["start_at"]).date().isoformat()
        wrote = False
        for lg in await db.job_logs.find({"commessa_id": s_["commessa_id"], "date": day}, {"_id": 0, "presence": 1, "kind": 1,
                                                                                            "collaborator_id": 1, "user_id": 1}).to_list(500):
            if lg.get("presence") or lg.get("kind"):
                continue
            if (w.get("is_user") and lg.get("user_id") == w["user_id"] and not lg.get("collaborator_id")) or lg.get("collaborator_id") == w["id"]:
                wrote = True
                break
        if wrote:
            continue
        text = (f"📝 Com'è andata oggi su «{s_['commessa_title']}»? Scrivimi (anche a voce) cosa avete fatto, "
                "eventuali problemi o materiali: lo metto nel diario della commessa.")
        if w.get("is_user"):
            if w.get("telegram_chat_id"):
                await tg._set_state(db, w["telegram_chat_id"], w["user_id"],
                                    pending_presence_note={"commessa_id": s_["commessa_id"], "at": now.isoformat()})
            push.fire_and_forget(db, w["user_id"], "📝 Com'è andata oggi?", f"«{s_['commessa_title']}»: scrivilo nel diario.",
                                 f"/dashboard/journal?commessa={s_['commessa_id']}", f"note-{s_['id']}")
        else:   # what they write next goes to that commessa
            await db.collaborators.update_one({"id": w["id"]}, {"$set": {"tg_state": {"target": s_["commessa_id"], "at": now.isoformat()}}})
        if await _tell_worker(w, text) or w.get("is_user"):
            asked += 1
    return asked


async def _on_site(commessa_id: str) -> list:
    """Who is working on the commessa now (a start not ended yet)."""
    out = []
    for s_ in await db.work_sessions.find({"commessa_id": commessa_id, "end_at": None}, {"_id": 0}).to_list(50):
        c = await _worker_of(s_["collaborator_id"])
        out.append({"name": _collab_name(c) if c else "?", "is_user": bool(c and c.get("is_user")), "since": s_["start_at"], "start_m": s_.get("start_m"),
                    "far": sp.far(s_.get("start_m")), "role": (c or {}).get("role") or "", "company": (c or {}).get("company") or ""})
    return sorted(out, key=lambda p: p["since"] or "")


# ---- THE DAY'S PINNED MESSAGE (collaborators, Telegram): at 6:00 one message "📋 Oggi" with,
# commessa by commessa (address + map link), the To Do, milestones and materials to bring due
# that day for them, with a ✅ button each - pinned on top of the chat. It is edited when
# something changes (done, added) and replaced the next day; a day with nothing gets none.

DAY_PIN_AT = "06:00"


async def _day_pin_send(chat_id, text: str, kb) -> Optional[int]:
    from telegram import Bot
    bot = Bot(token=tg.bot_token())
    msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
    return msg.message_id


async def _day_pin_edit(chat_id, message_id: int, text: str, kb) -> None:
    from telegram import Bot
    await Bot(token=tg.bot_token()).edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML",
                                                      reply_markup=kb, disable_web_page_preview=True)


async def _day_pin_unpin(chat_id, message_id: int) -> None:
    from telegram import Bot
    await Bot(token=tg.bot_token()).unpin_chat_message(chat_id=chat_id, message_id=message_id)


async def _collab_day_items(collab: dict, day: str) -> list:
    """[(commessa view, [(kind "t"|"m", id, label, done)]), ...] - what is theirs for that day."""
    out = []
    for _owner, _cl, view in await _collab_targets(collab):
        rows = []
        for t in await db.job_todos.find({"commessa_id": view["id"], "due_date": day,
                                          "$or": [{"collaborator_id": collab["id"]}, {"shared_with": {"$in": [collab["id"]]}}]}, {"_id": 0}).to_list(100):
            label = ("🧰 Da portare:\n" + _mat_bullets(t, "   ◦")) if t.get("kind") == "materiale" else t["text"]
            rows.append((0 if t.get("kind") != "materiale" else 2, "t", t["id"], label, bool(t.get("done"))))
        for m in await db.job_milestones.find({"commessa_id": view["id"], "due_date": day}, {"_id": 0}).to_list(100):
            c = await _milestone_collaborator(m)
            if c and c["id"] == collab["id"]:
                rows.append((1, "m", m["id"], f"🚩 {m['title']} (milestone)", bool(m.get("done"))))
        if rows:
            out.append((view, [r[1:] for r in sorted(rows, key=lambda r: r[0])]))
    return out


def _day_pin_body(day: str, items: list) -> tuple:
    """-> (HTML text, inline keyboard with a ✅ per open item)"""
    import html
    from urllib.parse import quote
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    lines = [f"📋 <b>Oggi, {jl.IT_WEEKDAYS[date.fromisoformat(day).weekday()]} {html.escape(_short_it_date(day))}</b>"]
    buttons = []
    for view, rows in items:
        lines += ["", f"🏗️ <b>{html.escape(view.get('title') or '')}</b> — {html.escape(view.get('client_name') or '')}"]
        if view.get("address"):
            url = html.escape(f"https://www.google.com/maps/search/?api=1&query={quote(view['address'])}", quote=True)
            lines.append(f"📍 <a href=\"{url}\">{html.escape(view['address'])}</a>")
        for kind, item_id, label, done in rows:
            lines.append(f"✅ <s>{html.escape(label)}</s>" if done else f"• {html.escape(label)}")
            if not done:
                short = re.sub(r"\s*\n\s*◦\s*", ", ", label).replace(":, ", ": ")   # a button: one line
                buttons.append([InlineKeyboardButton(f"✅ {short}"[:60], callback_data=f"cldone:{kind}:{item_id}")])
    open_n = sum(1 for _v, rows in items for r in rows if not r[3])
    lines += ["", "Quando una cosa è fatta tocca il suo ✅." if open_n else "🎉 Tutto fatto per oggi!"]
    return "\n".join(lines), (InlineKeyboardMarkup(buttons) if buttons else None)


async def _day_pin_refresh(collab_id: str, now_utc: Optional[datetime] = None) -> str:
    """Brings the collaborator's pinned message up to date: sent and pinned (the 6:00 one, or the
    first thing of the day added later), edited, or - a new day - the old one unpinned.
    -> "sent" | "edited" | "same" | "none" | "skip" """
    c = await db.collaborators.find_one({"id": collab_id}, {"_id": 0})
    if not c or c.get("status") != "active" or not c.get("telegram_chat_id") or not tg.bot_token():
        return "skip"
    now_l = (now_utc or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    if now_l.strftime("%H:%M") < DAY_PIN_AT:
        return "skip"
    day = now_l.date().isoformat()
    pin = c.get("day_pin") or {}
    if pin.get("date") != day:
        if pin.get("message_id"):
            try:
                await _day_pin_unpin(c["telegram_chat_id"], pin["message_id"])
            except Exception:
                logger.warning("unpin of yesterday's message failed for %s", collab_id)
        pin = {"date": day, "message_id": None}
        await db.collaborators.update_one({"id": collab_id}, {"$set": {"day_pin": pin}})
    items = await _collab_day_items(c, day)
    if not items and not pin.get("message_id"):
        return "none"
    text, kb = _day_pin_body(day, items)
    if pin.get("message_id"):
        if pin.get("text") == text:
            return "same"
        try:
            await _day_pin_edit(c["telegram_chat_id"], pin["message_id"], text, kb)
            await db.collaborators.update_one({"id": collab_id}, {"$set": {"day_pin": {**pin, "text": text}}})
            return "edited"
        except Exception:
            logger.warning("edit of the pinned message failed for %s: a new one is sent", collab_id)
    try:
        mid = await _day_pin_send(c["telegram_chat_id"], text, kb)
    except Exception:
        logger.exception(f"day message to {collab_id} failed")
        return "skip"
    await db.collaborators.update_one({"id": collab_id}, {"$set": {"day_pin": {"date": day, "message_id": mid, "text": text}}})
    return "sent"


async def _collab_day_briefs(now_utc: Optional[datetime] = None) -> int:
    """From 6:00, once a day: every linked collaborator's message of the day (or yesterday's
    unpinned when today has nothing). -> how many sent."""
    now_l = (now_utc or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    if now_l.strftime("%H:%M") < DAY_PIN_AT:
        return 0
    day = now_l.date().isoformat()
    n = 0
    for c in await db.collaborators.find({"status": "active", "telegram_chat_id": {"$ne": None}}, {"_id": 0}).to_list(2000):
        if (c.get("day_pin") or {}).get("date") == day:
            continue
        try:
            if await _day_pin_refresh(c["id"], now_utc) == "sent":
                n += 1
        except Exception:
            logger.exception(f"day brief for {c['id']} failed")
    return n


def _day_pin_touch(*collab_ids) -> None:
    """Something of theirs changed: their pinned message follows (in the background)."""
    for cid in {x for x in collab_ids if x}:
        async def run(cid=cid):
            try:
                await _day_pin_refresh(cid)
            except Exception:
                logger.exception("day message refresh failed")
        try:
            task = asyncio.get_running_loop().create_task(run())
            _DAY_PIN_TASKS.add(task)
            task.add_done_callback(_DAY_PIN_TASKS.discard)
        except RuntimeError:
            pass


_DAY_PIN_TASKS: set = set()


async def _collab_reminder_loop():
    while True:
        try:
            if tg.bot_token():
                await _collab_remind_due()
                await _milestone_reminders()
                await _collab_day_briefs()
                await _todo_reminders()
                await _material_reminders()
                await _presence_forgotten()
                await _presence_late_check()
                await _presence_day_note()
                await _client_weekly_updates()
        except Exception:
            logger.exception("collaborator reminder loop iteration failed")
        await asyncio.sleep(300)


# ---- THE CLIENT'S WEEKLY PROGRESS (Telegram): the client links once, from the invitation the
# owner sends on WhatsApp (link + code, like a collaborator's); then every week, on the owner's
# day and hour, each open commessa of theirs with work done in the week gets a short message:
# the works done (written for them from the diary's notes - never hours, costs, names or
# problems), the milestones reached, the next works. The owner gets a copy; from the
# commessa's diary they turn it off, see it beforehand or send it at once.

class ClientInvitePayload(BaseModel):
    phone: Optional[str] = None


class ClientUpdatesPatch(BaseModel):
    enabled: bool


def _require_owner(current: User, clienti: dict) -> None:
    if current.role != "admin" and clienti.get("user_id") != current.user_id:
        raise HTTPException(status_code=403, detail="Lo gestisce il titolare")


def _client_schedule(owner_doc: dict) -> tuple:
    day = owner_doc.get("client_update_day")
    return (cu.DEFAULT_DAY if day is None else int(day)), (owner_doc.get("client_update_at") or cu.DEFAULT_AT)


def _client_updates_on(sub: dict) -> bool:
    return (sub.get("client_updates") or {}).get("enabled", True)


async def _client_updates_state(clienti: dict, sub: dict, client: dict) -> dict:
    view = _commessa_view(sub, client, clienti)
    link = await db.client_links.find_one({"item_id": sub.get("item_id")}, {"_id": 0}) or {}
    owner_doc = await db.users.find_one({"user_id": clienti.get("user_id")}, {"_id": 0}) or {}
    day, at = _client_schedule(owner_doc)
    expired = not link.get("code_expires_at") or link["code_expires_at"] < datetime.now(timezone.utc).isoformat()
    cup = sub.get("client_updates") or {}
    return {"client_name": view["client_name"], "phone": link.get("phone") or view.get("client_phone") or "",
            "status": "active" if link.get("telegram_chat_id") and link.get("status") == "active" else
                      "stopped" if link.get("telegram_chat_id") else "invited" if link.get("code") and not expired else "none",
            "linked_at": link.get("linked_at"), "code_expires_at": None if expired else link.get("code_expires_at"),
            "enabled": _client_updates_on(sub), "day": day, "day_label": cu.WEEKDAYS[day], "at": at,
            "last_sent_at": cup.get("last_sent_at"), "last_text": cup.get("last_text")}


async def _client_update_text(clienti: dict, sub: dict, client: dict, owner_name: str, day: Optional[date] = None) -> tuple:
    """-> (message or "" when the week has no work to tell, the first day of the week)"""
    view = _commessa_view(sub, client, clienti)
    day = day or jl.today_local()
    start = cu.week_start(day, (sub.get("client_updates") or {}).get("last_sent_at"))
    logs = await db.job_logs.find({"commessa_id": sub["id"], "date": {"$gte": start.isoformat(), "$lte": day.isoformat()}},
                                  {"_id": 0, "embedding": 0}).to_list(2000)
    logs.sort(key=lambda lg: (lg.get("date") or "", lg.get("created_at") or ""))
    # only the notes of work: no state changes, reports, presences ("in cantiere dalle…"), photos alone
    notes = [lg["text"] for lg in logs if not lg.get("kind") and not lg.get("presence") and lg.get("text")
             and lg.get("raw_text") != PHOTO_ONLY_TEXT]
    done = await cu.summarize(view["title"], notes, user_id=clienti.get("user_id")) if notes else []
    ms = await _commessa_milestones(sub["id"])
    reached = [m["title"] for m in ms if m["status"] == "done" and start.isoformat() <= (m.get("done_date") or "") <= day.isoformat()]
    upcoming = [m["title"] for m in ms if m["status"] != "done"][:3]
    if not done and not reached:
        return "", start
    return cu.message(view["title"], start, day, done, reached, upcoming, owner_name), start


async def _send_client_update(clienti: dict, sub: dict, client: dict, link: dict, owner: User, day: Optional[date] = None) -> Optional[str]:
    """The week's message to the client (and a copy to the owner). -> the text, None if nothing to tell."""
    day = day or jl.today_local()
    text, _start = await _client_update_text(clienti, sub, client, owner.name or "", day)
    now = datetime.now(timezone.utc).isoformat()
    if not text:
        await db.collection_sub_items.update_one({"id": sub["id"]}, {"$set": {"client_updates": {
            **(sub.get("client_updates") or {}), "last_checked": day.isoformat()}}})
        return None
    if not await _send_telegram_text(link["telegram_chat_id"], text):
        raise RuntimeError("telegram send failed")
    await db.collection_sub_items.update_one({"id": sub["id"]}, {"$set": {"client_updates": {
        **(sub.get("client_updates") or {}), "last_sent_at": now, "last_text": text, "last_checked": day.isoformat()}}})
    await _notify_owner(owner, f"📤 Avanzamento settimanale inviato a {link.get('name') or 'il cliente'}:\n\n{text}")
    return text


async def _client_weekly_updates(now_utc: Optional[datetime] = None) -> int:
    """On each owner's day, from their hour: the week's message for every open commessa of the
    clients linked (once a day at most per commessa). -> how many sent."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    today = now.date().isoformat()
    sent = 0
    for link in await db.client_links.find({"status": "active"}, {"_id": 0}).to_list(5000):
        if not link.get("telegram_chat_id"):
            continue
        owner_doc = await db.users.find_one({"user_id": link["owner_user_id"]}, {"_id": 0})
        if not owner_doc:
            continue
        day, at = _client_schedule(owner_doc)
        if now.weekday() != day or now.strftime("%H:%M") < at:
            continue
        clienti = await db.collections.find_one({"id": link["collection_id"]}, {"_id": 0})
        client = await db.collection_items.find_one({"id": link["item_id"]}, {"_id": 0, "embedding": 0})
        if not clienti or not client:
            continue
        for sub in await db.collection_sub_items.find({"item_id": link["item_id"]}, {"_id": 0, "embedding": 0}).to_list(200):
            cup = sub.get("client_updates") or {}
            if not _client_updates_on(sub) or _commessa_view(sub, client, clienti)["stato"] == "chiusa" \
                    or cup.get("last_checked") == today:
                continue
            try:
                if await _send_client_update(clienti, sub, client, link, User(**owner_doc), now.date()):
                    sent += 1
            except Exception:
                logger.exception("client weekly update failed")
    return sent


async def _client_commessa(current: User, commessa_id: str) -> tuple:
    clienti, sub, client = await _commessa_or_404(current, commessa_id)
    _require_owner(current, clienti)
    return clienti, sub, client


@api_router.get("/jobs/commesse/{commessa_id}/client-updates")
async def get_client_updates(commessa_id: str, current: User = Depends(get_current_user)):
    return await _client_updates_state(*(await _client_commessa(current, commessa_id)))


@api_router.post("/jobs/commesse/{commessa_id}/client-updates/invite")
async def invite_client_updates(commessa_id: str, payload: ClientInvitePayload, current: User = Depends(get_current_user)):
    """The invitation for the client: a link to the bot with a code (7 days), to send on WhatsApp."""
    clienti, sub, client = await _client_commessa(current, commessa_id)
    view = _commessa_view(sub, client, clienti)
    phone = " ".join((payload.phone or view.get("client_phone") or "").split())[:40]
    if phone and not 8 <= len(_phone_digits(phone)) <= 15:
        raise HTTPException(status_code=400, detail="Numero di telefono non valido")
    now = datetime.now(timezone.utc)
    link = await db.client_links.find_one({"item_id": sub["item_id"]}, {"_id": 0})
    upd = {"code": _collab_code(), "code_expires_at": (now + timedelta(days=COLLAB_CODE_DAYS)).isoformat(), "phone": phone,
           "name": view["client_name"]}
    if link:
        await db.client_links.update_one({"id": link["id"]}, {"$set": upd})
    else:
        link = {"id": f"cl_{uuid.uuid4().hex[:12]}", "owner_user_id": clienti.get("user_id"), "collection_id": clienti["id"],
                "item_id": sub["item_id"], "telegram_chat_id": None, "linked_at": None, "status": "invited", "created_at": now.isoformat()}
        await db.client_links.insert_one({**link, **upd})
    username = await tg.bot_username()
    url = f"https://t.me/{username}?start={upd['code']}" if username else None
    msg = (f"Buongiorno {view['client_name']}, sono {current.name or 'la vostra impresa'}: ogni settimana le manderò su Telegram un breve "
           f"aggiornamento su come avanzano i lavori «{view['title']}».\n\n"
           + (f"Per riceverlo apra questo link e prema «Avvia»: {url}\n" if url else "Apra Telegram e cerchi il bot di mAIPAL.\n")
           + f"Se le chiede un codice, scriva: /start {upd['code']}")
    from urllib.parse import quote
    digits = _phone_digits(phone)
    state = await _client_updates_state(clienti, await db.collection_sub_items.find_one({"id": commessa_id}, {"_id": 0}), client)
    return {**state, "invite": {"code": upd["code"], "link": url, "message": msg, "expires_at": upd["code_expires_at"],
                                "whatsapp_url": f"https://wa.me/{digits}?text={quote(msg)}" if digits else f"https://wa.me/?text={quote(msg)}"}}


@api_router.patch("/jobs/commesse/{commessa_id}/client-updates")
async def patch_client_updates(commessa_id: str, payload: ClientUpdatesPatch, current: User = Depends(get_current_user)):
    clienti, sub, client = await _client_commessa(current, commessa_id)
    cup = {**(sub.get("client_updates") or {}), "enabled": payload.enabled}
    await db.collection_sub_items.update_one({"id": commessa_id}, {"$set": {"client_updates": cup}})
    return await _client_updates_state(clienti, {**sub, "client_updates": cup}, client)


@api_router.post("/jobs/commesse/{commessa_id}/client-updates/preview")
async def preview_client_update(commessa_id: str, current: User = Depends(get_current_user)):
    """What the client would get now (nothing is sent)."""
    clienti, sub, client = await _client_commessa(current, commessa_id)
    text, start = await _client_update_text(clienti, sub, client, current.name or "")
    return {"text": text, "since": start.isoformat()}


@api_router.post("/jobs/commesse/{commessa_id}/client-updates/send")
async def send_client_update_now(commessa_id: str, current: User = Depends(get_current_user)):
    clienti, sub, client = await _client_commessa(current, commessa_id)
    link = await db.client_links.find_one({"item_id": sub["item_id"]}, {"_id": 0}) or {}
    if not link.get("telegram_chat_id") or link.get("status") != "active":
        raise HTTPException(status_code=400, detail="Il cliente non è collegato a Telegram")
    owner_doc = await db.users.find_one({"user_id": clienti.get("user_id")}, {"_id": 0})
    try:
        text = await _send_client_update(clienti, sub, client, link, User(**owner_doc) if owner_doc else current)
    except Exception:
        logger.exception("client update send failed")
        raise HTTPException(status_code=502, detail="Invio non riuscito, riprova tra poco")
    if not text:
        raise HTTPException(status_code=400, detail="Questa settimana non ci sono lavori nel diario da raccontare")
    return {"sent": True, "text": text}


@api_router.delete("/jobs/commesse/{commessa_id}/client-updates/link")
async def unlink_client_updates(commessa_id: str, current: User = Depends(get_current_user)):
    """The client no longer gets anything (their Telegram is unlinked)."""
    clienti, sub, client = await _client_commessa(current, commessa_id)
    link = await db.client_links.find_one({"item_id": sub["item_id"]}, {"_id": 0})
    if link and link.get("telegram_chat_id"):
        try:
            await _send_telegram_text(link["telegram_chat_id"], "Non riceverai più qui gli aggiornamenti sui lavori.")
        except Exception:
            logger.exception("client unlink notice failed")
    await db.client_links.delete_many({"item_id": sub["item_id"]})
    return await _client_updates_state(clienti, sub, client)


async def _notify_owner(owner: User, text: str) -> None:
    """A note to the admin on Telegram (if linked): a collaborator linked, a problem reported."""
    if owner.telegram_chat_id:
        try:
            await _send_telegram_text(owner.telegram_chat_id, text)
        except Exception:
            logger.exception("collaborator notice to owner failed")


@api_router.patch("/jobs/commesse/{commessa_id}/stato")
async def set_job_commessa_stato(commessa_id: str, payload: CommessaStatoPayload, current: User = Depends(get_current_user)):
    if payload.stato not in vx.COMMESSA_STATI:
        raise HTTPException(status_code=400, detail="Stato non valido")
    clienti, sub, client = await _commessa_or_404(current, commessa_id)
    smap = clienti.get("system_sub_map") or {}
    data = {**(sub.get("data") or {}), smap.get("stato", "stato"): payload.stato}
    if payload.stato == "chiusa" and not _sysval(data, smap, "data_fine"):
        data[smap.get("data_fine", "data_fine")] = jl.today_local().isoformat()
    await db.collection_sub_items.update_one({"id": commessa_id}, {"$set": {"data": data, "embedding": None}})
    old = _sysval(sub.get("data"), smap, "stato")
    if old != payload.stato:
        await _log_stato_change(current, clienti, {**sub, "data": data}, client, old, payload.stato)
    return _commessa_view({**sub, "data": data}, client, clienti)


async def _log_stato_change(current: User, clienti: dict, sub: dict, client: Optional[dict], old: str, new: str) -> dict:
    """A state change, as a line of the commessa's diary: who, when, from what to what."""
    view = _commessa_view(sub, client, clienti)
    text = (f"Stato cambiato da «{old}» a «{new}»" if old else f"Stato impostato a «{new}»") + f" da {_first_name(current.name)}."
    log = {"id": f"jlog_{uuid.uuid4().hex[:12]}", "kind": "stato", "stato_from": old or None, "stato_to": new,
           "user_id": current.user_id, "org_id": current.org_id, "author_name": _first_name(current.name),
           "collection_id": clienti["id"], "collection_name": clienti.get("name"),
           "client_item_id": view["client_item_id"], "client_name": view["client_name"],
           "commessa_id": view["id"], "commessa_title": view["title"], "date": jl.today_local().isoformat(),
           "raw_text": text, "text": text, "hours": [], "materials": [], "problems": [], "photos": [],
           "channel": "web", "created_at": datetime.now(timezone.utc).isoformat(), "embedding": None}
    await db.job_logs.insert_one(log)
    log.pop("_id", None)
    return log


class CommessaAskPayload(BaseModel):
    question: str
    history: List[dict] = []   # [{"role": "user"|"assistant", "content": ...}] of this chat


@api_router.post("/jobs/commesse/{commessa_id}/ask")
async def ask_job_commessa(commessa_id: str, payload: CommessaAskPayload, current: User = Depends(get_current_user)):
    """The chat of a commessa: questions answered from its card, its diary and its reports."""
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Scrivi una domanda")
    clienti, sub, client = await _commessa_or_404(current, commessa_id, write=False)
    view = _commessa_view(sub, client, clienti)
    logs = await db.job_logs.find({"commessa_id": commessa_id}, {"_id": 0, "embedding": 0}).to_list(5000)
    logs.sort(key=lambda lg: (lg.get("date") or "", lg.get("created_at") or ""))
    reports = await db.work_reports.find({"commessa_id": commessa_id}, {"_id": 0, "docx_b64": 0, "embedding": 0}).to_list(50)
    view["economics_line"] = jl.economics_line(await _commessa_economics(clienti, commessa_id, logs))   # never for collaborators
    view["milestones_line"] = milestones_line(await _commessa_milestones(commessa_id))
    view["contacts_line"] = contacts_line(await _commessa_contacts(commessa_id))
    try:
        out = await jl.answer(view, logs, reports, question, payload.history[-8:], user_id=current.user_id)
    except Exception as e:
        logger.exception("commessa chat failed")
        raise HTTPException(status_code=500, detail=f"Non sono riuscito a rispondere: {e}")
    return out


async def _job_log_or_404(current: User, log_id: str) -> dict:
    log = await db.job_logs.find_one({"id": log_id}, {"_id": 0, "embedding": 0})
    if not log:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    await _commessa_or_404(current, log["commessa_id"])   # the user can see that commessa
    return log


class HoursReviewPayload(BaseModel):
    approve: bool


@api_router.post("/jobs/logs/{log_id}/hours-review")
async def review_job_log_hours(log_id: str, payload: HoursReviewPayload, current: User = Depends(get_current_user)):
    """The hours a collaborator wrote: approved (they count; a correction takes the place of the
    📍 hours of that day) or not. Told to the collaborator on Telegram."""
    log = await _job_log_or_404(current, log_id)
    clienti, sub, client = await _commessa_or_404(current, log["commessa_id"])
    if current.role != "admin" and clienti.get("user_id") != current.user_id:
        raise HTTPException(status_code=403, detail="Le ore le approva il titolare")
    rv = dict(log.get("hours_review") or {})
    if rv.get("status") != "pending" or not log.get("hours_pending"):
        raise HTTPException(status_code=400, detail="Queste ore non sono da approvare")
    now = datetime.now(timezone.utc).isoformat()
    rv.update(status="approved" if payload.approve else "rejected", decided_by=_first_name(current.name), decided_at=now)
    if payload.approve:
        upd = {"hours": log["hours_pending"], "hours_pending": [], "hours_review": rv, "embedding": None}
        if rv.get("replaces_log_id"):
            await _replace_presence_hours(rv["replaces_log_id"], log_id)
    else:
        upd = {"hours_pending": [], "hours_review": {**rv, "rejected_hours": log["hours_pending"]}, "embedding": None}
    await db.job_logs.update_one({"id": log_id}, {"$set": upd})
    log.update(upd)
    if payload.approve:
        asyncio.create_task(_check_budget_alert(clienti, log["commessa_id"]))
    c = await db.collaborators.find_one({"id": log.get("collaborator_id")}, {"_id": 0}) if log.get("collaborator_id") else None
    if c:
        view = _commessa_view(sub, client, clienti)
        hrs = jl.hours_line(upd.get("hours") or upd["hours_review"].get("rejected_hours") or [])
        text = (f"✅ Approvate le ore del {_short_it_date(log['date'])} su «{view['title']}»: {hrs}." if payload.approve else
                f"❌ Le ore del {_short_it_date(log['date'])} su «{view['title']}» ({hrs}) non sono state approvate"
                + (": restano quelle segnate con 📍." if rv.get("replaces_log_id") else "."))
        try:
            await _tell_collaborator(c, text)
        except Exception:
            logger.exception("hours review notice failed")
    return {"log": _public_log(log)}


class PlanMaterialPayload(BaseModel):
    index: int                                # which material of the entry
    due_date: Optional[str] = None            # when it is needed (default tomorrow)


@api_router.post("/jobs/logs/{log_id}/plan-material")
async def plan_material_from_log(log_id: str, payload: PlanMaterialPayload, current: User = Depends(get_current_user)):
    """A material written as used that was only to take: out of the entry, into a reminder
    "Da prendere" for who wrote it (the collaborator, or the user)."""
    log = await _job_log_or_404(current, log_id)
    mats = list(log.get("materials") or [])
    if log.get("kind") or not 0 <= payload.index < len(mats):
        raise HTTPException(status_code=400, detail="Materiale non trovato")
    m = mats.pop(payload.index)
    clienti, sub, client = await _commessa_or_404(current, log["commessa_id"])
    author = None
    if log.get("collaborator_id"):
        c = await db.collaborators.find_one({"id": log["collaborator_id"]}, {"_id": 0})
        if c:
            author = {"id": c["id"], "first_name": c.get("first_name") or "", "name": _collab_name(c), "company": c.get("company") or ""}
    due = _valid_due(payload.due_date) or (jl.today_local() + timedelta(days=1)).isoformat()
    todos = await _plan_materials(current, _commessa_view(sub, client, clienti), clienti, [{**m, "for_date": due}], author)
    await db.job_logs.update_one({"id": log_id}, {"$set": {"materials": mats, "embedding": None}})
    return {"log": _public_log({**log, "materials": mats}), "todo": todos[0]}


@api_router.patch("/jobs/logs/{log_id}")
async def update_job_log(log_id: str, payload: JobLogPatch, current: User = Depends(get_current_user)):
    log = await _job_log_or_404(current, log_id)
    if log.get("kind"):
        raise HTTPException(status_code=400, detail=("Un cambio di stato non si modifica: puoi solo eliminarlo" if log["kind"] == "stato"
                                                     else "Questa riga del diario non si modifica: puoi solo eliminarla"))
    upd: dict = {}
    if payload.text is not None and payload.text.strip():
        upd["text"] = payload.text.strip()
    if payload.date is not None:
        upd["date"] = jl.valid_day(payload.date, jl.today_local())
    if payload.hours is not None:
        upd["hours"] = jl.clean_hours(payload.hours, log.get("author_name") or "Io")
    if payload.materials is not None:
        upd["materials"] = jl.clean_materials(payload.materials)
    if payload.problems is not None:
        upd["problems"] = jl.clean_problems(payload.problems)
    if upd:
        upd["embedding"] = None
        await db.job_logs.update_one({"id": log_id}, {"$set": upd})
        if "hours" in upd or "materials" in upd:
            clienti = await _clienti_list(current)
            if clienti:
                asyncio.create_task(_check_budget_alert(clienti, log["commessa_id"]))
    return _public_log({**log, **upd})


@api_router.delete("/jobs/logs/{log_id}")
async def delete_job_log(log_id: str, current: User = Depends(get_current_user)):
    await _job_log_or_404(current, log_id)
    await db.job_logs.delete_one({"id": log_id})
    await db.job_photos.delete_many({"log_id": log_id})
    return {"ok": True}


@api_router.post("/jobs/logs/{log_id}/photos")
async def add_job_photos(log_id: str, payload: JobPhotosPayload, current: User = Depends(get_current_user)):
    log = await _job_log_or_404(current, log_id)
    added = await _store_job_photos(current, log, payload.images)
    if not added:
        raise HTTPException(status_code=400, detail="Nessuna immagine valida")
    return _public_log(log)


@api_router.delete("/jobs/logs/{log_id}/photos/{photo_id}")
async def delete_job_photo(log_id: str, photo_id: str, current: User = Depends(get_current_user)):
    log = await _job_log_or_404(current, log_id)
    photos = [p for p in log.get("photos") or [] if p.get("id") != photo_id]
    await db.job_logs.update_one({"id": log_id}, {"$set": {"photos": photos}})
    await db.job_photos.delete_one({"id": photo_id, "log_id": log_id})
    return {**_public_log(log), "photos": photos}


@api_router.get("/jobs/photos/{photo_id}")
async def get_job_photo(photo_id: str, current: User = Depends(get_current_user)):
    ph = await db.job_photos.find_one({"id": photo_id}, {"_id": 0})
    if not ph:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    await _commessa_or_404(current, ph["commessa_id"], write=False)
    import base64 as _b64
    return Response(content=_b64.b64decode(ph["data_b64"]), media_type=ph.get("mime") or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


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
    cursor = db.journal_entries.find(query, {"_id": 0, "embedding": 0}).sort("date", -1).limit(limit)
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
        "due_time (formato ESATTO HH:MM, oppure null), priority ('alta'|'media'|'bassa'), tags, notes, "
        "recurrence (per farlo RIPETERE: {\"freq\": \"daily|weekly|monthly|yearly\", \"interval\": 1, \"weekdays\": [0-6, "
        "0=lunedì, solo weekly], \"day_of_month\": 1-31 o -1 (solo monthly), \"until\": \"YYYY-MM-DD o null\", \"count\": null}; "
        "null per SMETTERE di ripeterlo), apply_to_series (true SOLO se il task fa parte di una serie ricorrente e "
        "l'utente chiede che la modifica valga per tutte le prossime ripetizioni, es. 'sempre', 'tutte le volte', "
        "'tutta la serie'; altrimenti la modifica vale solo per questa occorrenza). "
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
        has_rec = "recurrence" in meta
        rec_raw = meta.pop("recurrence", None)
        to_series = bool(meta.pop("apply_to_series", False))
        meta = {k: v for k, v in meta.items() if k in ("title", "description", "due_date", "due_time", "priority", "tags", "notes")}
        if meta:
            _clear_cached_embedding(meta, {"title", "description", "notes"})
            await db.tasks.update_one(q, {"$set": meta})
            if to_series and task.get("series_id"):
                await _apply_template_to_series(task["series_id"], meta)
        if has_rec:
            fresh = await db.tasks.find_one(q, {"_id": 0})
            try:
                if rec_raw is None:
                    await _stop_task_recurrence(fresh)
                else:
                    await _set_task_recurrence(fresh, rec_raw, current.user_id)
            except HTTPException as he:
                visible += f"\n⚠️ {he.detail}"
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
    if not await _storage_targets(current.user_id):
        raise HTTPException(status_code=400, detail=NO_STORAGE_MSG)

    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file.filename.rsplit('.',1)[-1] if '.' in (file.filename or '') else 'bin'}") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        res = await _storage_save(current.user_id, None, tmp_path, file.filename or "file", file.content_type)
        return {"file_id": res.get("file_id"), "web_view_link": res.get("web_view_link"), "name": res.get("name"),
                "saved": res["saved"], "links": res["links"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("drive upload failed")
        raise HTTPException(status_code=500, detail=f"Upload Drive fallito: {e}")
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass


# Words that can follow the folder name in a request ("...nella cartella Schermate su drive
# per favore") and are never part of it.
_FOLDER_STOP_WORDS = {
    "su", "in", "nel", "nella", "sul", "sulla", "di", "del", "della", "da", "per", "e", "ed", "che", "con",
    "drive", "google", "grazie", "per favore", "perfavore", "please", "mi", "ti", "li", "le", "lo", "la",
    "subito", "ora", "adesso", "tutti", "tutte", "anche", "poi", "dentro", "mentre",
}
# Verbs a reply like "salvali nella cartella X" is made of - such a reply is a sentence,
# never a bare folder name, even when it's short.
_FOLDER_COMMAND_WORDS = ("salva", "salvali", "salvale", "salvalo", "salvala", "salvarl", "metti", "mettil", "mettel",
                         "carica", "caricali", "caricale", "sposta", "spostali", "archivia", "cartella", "drive")


def _regex_drive_folder_hint(text: str) -> Optional[str]:
    """Deterministic extraction of '...(nella) cartella NomeCartella...' - tried BEFORE the
    model, since this is by far the most common phrasing and needs no guessing. A quoted
    name is taken as is; otherwise the name is the words after "cartella" up to the first
    word that can't be part of it ("su drive", "per favore", punctuation...)."""
    import re as _re
    t = text or ""
    q = _re.search(r"cartella\s+(?:chiamata\s+|denominata\s+|di\s+nome\s+|nominata\s+)?[\"'«“]([^\"'»”]{1,60})[\"'»”]", t, _re.IGNORECASE)
    if q:
        return q.group(1).strip() or None
    m = _re.search(r"cartella\s+(?:chiamata\s+|denominata\s+|di\s+nome\s+|nominata\s+)?(.+)", t, _re.IGNORECASE)
    if not m:
        return None
    words = []
    for w in _re.split(r"\s+", m.group(1).strip()):
        clean = w.strip(".,;:!?()")
        if not clean or clean.lower() in _FOLDER_STOP_WORDS:
            break
        words.append(clean)
        if w[-1:] in ".,;:!?" or len(words) == 4:
            break
    return " ".join(words) or None


def _canonical_folder(name: Optional[str], existing: List[str]) -> Optional[str]:
    """Reuses an existing folder when the name only differs by case/spacing ("schermate"
    -> "Schermate"), instead of creating a near-duplicate."""
    if not name:
        return None
    key = " ".join(name.split()).lower()
    for e in existing:
        if " ".join((e or "").split()).lower() == key:
            return e
    return " ".join(name.split())


async def _resolve_drive_folder_hint(text: str, existing_folders: List[str], user_id: Optional[str] = None, channel: str = "web") -> Optional[str]:
    """Which Drive folder the user's message names (existing or new), or None. The literal
    "cartella X" phrasing is read deterministically; the model only handles the rest
    (e.g. "mettila con le altre fatture")."""
    text = (text or "").strip()
    if not text:
        return None
    literal = _regex_drive_folder_hint(text)
    if literal:
        return _canonical_folder(literal, existing_folders)
    folders_list = ", ".join(existing_folders) if existing_folders else "(nessuna)"
    system = (
        "L'utente sta caricando un file su Google Drive, dentro la cartella mAIPAL. "
        f"Cartelle già esistenti dentro mAIPAL: {folders_list}. "
        "Analizza il messaggio dell'utente (può contenere errori di battitura): se indica in quale cartella salvare il "
        "file (sia una cartella esistente sia una nuova da creare), rispondi SOLO con il nome di quella cartella - solo "
        "il nome, senza verbi, articoli, virgolette né altro testo (es. 'salvali nelle fatture' -> Fatture se esiste "
        "una cartella simile). Se non lo specifica, rispondi SOLO con la parola: NESSUNA."
    )
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"drivehint_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=user_id, feature="caricamento_informazioni", channel=channel, trigger="utente",
        ).with_model("openai", "gpt-4o-mini")  # single-word folder-name extraction
        raw = (await chat.send_message(UserMessage(text=text))).strip().strip('"').strip()
        if not raw or raw.upper() == "NESSUNA" or len(raw) > 60:
            return None
        return _canonical_folder(raw, existing_folders)
    except Exception:
        logger.exception("drive folder hint resolution via LLM failed")
        return None


async def _drive_smart_upload_core(current: User, contents: bytes, filename: str, content_type: str, text: str, silent: bool = False, channel: str = "web",
                                   only: Optional[List[str]] = None, ask_folder: bool = True) -> dict:
    """Shared by the web endpoint and the Telegram bot (same process, no HTTP round-trip).
    Uploads a file into the mAIPAL Drive tree, picking the subfolder from the user's
    message when possible. If no folder can be determined, stashes the file and returns
    suggestions so the conversation can ask the user (see _drive_resolve_pending_core) -
    UNLESS `silent` is set, in which case it just reports {"status": "skipped"} instead:
    used when a file was primarily attached for the knowledge base and the caller wants
    to *also* save it to Drive automatically only if the message clearly names a folder,
    without ever prompting the user for one. With `ask_folder` False (mobile chat, folder icon
    off) a file whose message names no folder goes straight into the mAIPAL folder itself."""
    if not await _storage_targets(current.user_id) and not only:
        if silent:
            return {"status": "skipped"}
        raise HTTPException(status_code=400, detail=NO_STORAGE_MSG)

    existing_names = await _storage_folder_names(current.user_id)
    folder_name = await _resolve_drive_folder_hint(text, existing_names, user_id=current.user_id, channel=channel)

    if folder_name or (not ask_folder and not silent):
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{filename.rsplit('.',1)[-1] if '.' in (filename or '') else 'bin'}") as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        try:
            result = await _storage_save(current.user_id, folder_name or None, tmp_path, filename, content_type, only=only)
            folder_name = folder_name or "mAIPAL"
            ut.fire_and_forget_feature_event(user_id=current.user_id, feature="caricamento_informazioni", channel=channel, trigger="utente", org_id=current.org_id)
            return {"status": "saved", "folder": folder_name, "where": _saved_where(result), **result}
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
        "only": only,
        "created_at": datetime.now(timezone.utc),
    })
    return {"status": "needs_folder", "pending_id": pending_id, "suggestions": existing_names}


@api_router.post("/drive/smart-upload")
async def drive_smart_upload(file: UploadFile = File(...), text: str = Form(""), silent: bool = Form(False),
                             targets: Optional[str] = Form(None), ask_folder: bool = Form(True),
                             current: User = Depends(get_current_user)):
    """`targets` (comma-separated "google,onedrive") and `ask_folder` come from the mobile chat's
    icons; without them the user's saved preferences apply and a missing folder is asked."""
    contents = await file.read()
    only = [t.strip() for t in targets.split(",") if t.strip()] if targets is not None else None
    return await _drive_smart_upload_core(current, contents, file.filename, file.content_type, text, silent=silent,
                                          only=only, ask_folder=ask_folder)


async def _drive_resolve_pending_core(current: User, pending_id: str, text: str, channel: str = "web") -> dict:
    """Shared by the web endpoint and the Telegram bot. Second turn of the smart-upload
    flow: the user's follow-up message may now name the folder. Resolves it once and
    uploads EVERY file of that same batch still waiting for a folder (several images sent
    together each got their own pending upload - answering the question once saves them
    all, not just the last one)."""
    doc = await db.pending_drive_uploads.find_one({"pending_id": pending_id, "user_id": current.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Nessun upload in attesa trovato")

    if not await _storage_targets(current.user_id):
        raise HTTPException(status_code=400, detail=NO_STORAGE_MSG)
    existing_names = await _storage_folder_names(current.user_id)

    # A direct reply to "in quale cartella la salvo?": "cartella X" in it is read literally;
    # otherwise a short answer with no command verb in it ("Scontrini", "le ricevute") IS the
    # folder name. A short SENTENCE like "salvali nella cartella schermate" never is - taking
    # it verbatim once created a folder literally named after the whole sentence.
    _NON_ANSWERS = {"non lo so", "boh", "nessuna", "non saprei", "niente", "annulla", "no", "non importa"}
    stripped = text.strip()
    folder_name = _regex_drive_folder_hint(stripped)
    lowered = stripped.lower()
    if not folder_name and stripped and len(stripped) <= 40 and len(stripped.split()) <= 4 and not stripped.endswith("?") \
            and lowered not in _NON_ANSWERS and not any(w in lowered for w in _FOLDER_COMMAND_WORDS):
        folder_name = stripped.rstrip(".,;:!")
    if folder_name:
        folder_name = _canonical_folder(folder_name, existing_names)
    else:
        folder_name = await _resolve_drive_folder_hint(text, existing_names, user_id=current.user_id, channel=channel)
    if not folder_name:
        return {"status": "needs_folder", "pending_id": pending_id, "suggestions": existing_names}

    # the same batch: this user's uploads left waiting within 15 minutes of this one
    created = doc.get("created_at")
    batch_q = {"user_id": current.user_id}
    if isinstance(created, datetime):
        created_utc = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        batch_q["created_at"] = {"$gte": created_utc - timedelta(minutes=15)}
    batch = await db.pending_drive_uploads.find(batch_q, {"_id": 0}).to_list(50)
    if not any(b["pending_id"] == pending_id for b in batch):
        batch.append(doc)

    import base64 as _b64
    saved, failed, last = [], [], {}
    for item in batch:
        ext = item["filename"].rsplit(".", 1)[-1] if "." in (item.get("filename") or "") else "bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(_b64.b64decode(item["data_b64"]))
            tmp_path = tmp.name
        try:
            last = await _storage_save(current.user_id, folder_name, tmp_path, item["filename"], item["content_type"], only=item.get("only"))
            await db.pending_drive_uploads.delete_one({"pending_id": item["pending_id"]})
            saved.append(item["filename"])
        except Exception:
            logger.exception(f"drive upload of pending {item['pending_id']} failed")
            failed.append(item["filename"])
        finally:
            try: os.unlink(tmp_path)
            except Exception: pass
    # uploads nobody ever answered for stay at most a day
    await db.pending_drive_uploads.delete_many({"user_id": current.user_id, "created_at": {"$lt": datetime.now(timezone.utc) - timedelta(days=1)}})
    if not saved:
        raise HTTPException(status_code=500, detail="Caricamento su Drive non riuscito")
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="caricamento_informazioni", channel=channel, trigger="utente", org_id=current.org_id)
    where = _saved_where(last)
    last = {k: v for k, v in last.items() if k not in ("saved",)}
    return {"status": "saved", "folder": folder_name, "where": where, **last, "saved": saved, "failed": failed}


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


def _docx_text(path: str) -> str:
    """Text of a .docx in reading order: paragraphs AND tables (one row per line, cells joined
    by " | ", nested tables included), content controls, text boxes, headers and footers.
    doc.paragraphs alone skips every table - a list of songs or of things to do laid out
    in a table never reached the knowledge base."""
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(path)
    P, TBL, SDT, TR, TC = qn("w:p"), qn("w:tbl"), qn("w:sdt"), qn("w:tr"), qn("w:tc")
    T, TAB, BR = qn("w:t"), qn("w:tab"), qn("w:br")

    def para(el) -> str:
        out = []
        for node in el.iter(T, TAB, BR):
            out.append((node.text or "") if node.tag == T else (" " if node.tag == TAB else "\n"))
        return "".join(out).strip()

    def blocks(parent, out: list):
        for el in parent.iterchildren():
            if el.tag == P:
                t = para(el)
                if t:
                    out.append(t)
            elif el.tag == TBL:
                for tr in el.iterchildren(TR):
                    cells = []
                    for tc in tr.iterchildren(TC):
                        inner: list = []
                        blocks(tc, inner)
                        cell = "; ".join(x.replace("\n", "; ") for x in inner).strip()
                        if cell:
                            cells.append(cell)
                    if cells:
                        out.append(" | ".join(cells))
            elif el.tag == SDT:
                content = el.find(qn("w:sdtContent"))
                if content is not None:
                    blocks(content, out)

    lines: list = []
    seen_hf = set()
    for sec in doc.sections:
        for hf in (sec.header, sec.first_page_header):
            try:
                if hf.is_linked_to_previous:
                    continue
                part: list = []
                blocks(hf._element, part)
                for t in part:
                    if t not in seen_hf:
                        seen_hf.add(t)
                        lines.append(t)
            except Exception:
                pass
    blocks(doc.element.body, lines)
    for sec in doc.sections:
        try:
            if sec.footer.is_linked_to_previous:
                continue
            part = []
            blocks(sec.footer._element, part)
            for t in part:
                if t not in seen_hf:
                    seen_hf.add(t)
                    lines.append(t)
        except Exception:
            pass
    return "\n".join(lines)


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
        return _docx_text(path)
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
        if ext in IMAGE_EXTS:
            # Images are handled entirely by the shared helper (downscale + OCR + chunk +
            # embed + persist) - same helper Telegram photos use, so both channels behave
            # identically instead of Telegram only ever going to Drive.
            try:
                return await _ocr_and_save_image_to_kb(current.user_id, file.filename, contents, channel="web", org_id=current.org_id)
            except ValueError as ve:
                raise HTTPException(status_code=422, detail=str(ve))

        source_type = "file"
        try:
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
                "tags": [ext, classification["category"]],
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
    # theirs, and the organization's knowledge (shared by an administrator: read-only for the others)
    query: dict = {"$or": [{"user_id": current.user_id}, {"tenant_kb": current.tenant_id}]} if current.tenant_id \
        else {"user_id": current.user_id}
    if category and category != "all":
        query["category"] = category
    if q:
        safe = _re.escape(q.strip())
        query = {"$and": [query, {"$or": [
            {"name": {"$regex": safe, "$options": "i"}},
            {"keywords": {"$regex": safe, "$options": "i"}},
            {"preview": {"$regex": safe, "$options": "i"}},
        ]}]}
    cursor = db.kb_documents.find(query, {"_id": 0}).sort("created_at", -1).limit(500)
    docs = await cursor.to_list(500)
    for d in docs:
        d["org_kb"] = bool(d.get("tenant_kb"))
        d["mine"] = d.get("user_id") == current.user_id

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


class OrgKbPayload(BaseModel):
    shared: bool


@api_router.put("/kb/documents/{doc_id}/org")
async def set_kb_document_org(doc_id: str, payload: OrgKbPayload, current: User = Depends(require_admin)):
    """An administrator's document in the organization's knowledge: every user of the organization
    finds it (Documenti, the agents' answers), read-only; off again: theirs alone."""
    doc = await db.kb_documents.find_one({"doc_id": doc_id, "user_id": current.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato tra i tuoi")
    val = current.tenant_id if payload.shared else None
    await db.kb_documents.update_one({"doc_id": doc_id}, {"$set": {"tenant_kb": val}})
    await db.kb_chunks.update_many({"doc_id": doc_id, "user_id": current.user_id}, {"$set": {"tenant_kb": val}})
    return {"doc_id": doc_id, "org_kb": bool(val)}


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
    ms_doc = await db.integrations.find_one({"user_id": current.user_id, "provider": "microsoft"}, {"_id": 0, "email": 1})
    user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    return {
        "google": {
            "configured": gi.is_configured(),
            "connected": bool(google_doc),
            "email": google_doc.get("email") if google_doc else None,
            "drive_folder_id": google_doc.get("drive_folder_id") if google_doc else None,
        },
        "microsoft": {
            "configured": ms.is_configured(),
            "connected": bool(ms_doc),
            "email": ms_doc.get("email") if ms_doc else None,
        },
        "storage_targets": await _storage_targets(current.user_id),
        "calendar_targets": await _calendar_targets(current.user_id),
        # a user's files go to the organization administrator's archive (they don't connect their own)
        "storage_owner": await _storage_owner_view(current),
        "storage_choice": (user_doc or {}).get("storage_targets"),
        "calendar_choice": (user_doc or {}).get("calendar_targets"),
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


# ============ OROLOGIO (Galaxy Watch / Wear OS) ============
# The watch has no keyboard to log in with: it asks for a 6-digit code (shown on its
# screen), the user types it in the app (Impostazioni › Collegamenti › Orologio) and the
# watch, which keeps polling, receives its own long-lived session token. It then calls the
# /watch/* endpoints below (and /voice/transcribe) with "Authorization: Bearer <token>".
WATCH_PAIR_TTL_MIN = 10
WATCH_SESSION_DAYS = 365
WATCH_MAX_FAILED_CODES = 5      # wrong codes per user every WATCH_PAIR_TTL_MIN minutes


class WatchPairConfirmPayload(BaseModel):
    code: str


class WatchAskPayload(BaseModel):
    agent: Literal["info_request", "info_upload", "task_todo", "journal", "scheduled_action"]
    text: str
    conv_id: Optional[str] = None


@api_router.post("/watch/pair/start")
async def watch_pair_start():
    now = datetime.now(timezone.utc)
    await db.watch_pairings.delete_many({"expires_at": {"$lt": now}})
    for _ in range(20):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if not await db.watch_pairings.find_one({"code": code}, {"_id": 1}):
            break
    else:
        raise HTTPException(status_code=503, detail="Riprova tra poco")
    pair_id = secrets.token_urlsafe(24)
    await db.watch_pairings.insert_one({
        "pair_id": pair_id, "code": code, "user_id": None, "session_token": None,
        "created_at": now, "expires_at": now + timedelta(minutes=WATCH_PAIR_TTL_MIN),
    })
    return {"pair_id": pair_id, "code": code, "expires_in": WATCH_PAIR_TTL_MIN * 60}


@api_router.get("/watch/pair/status")
async def watch_pair_status(pair_id: str):
    p = await db.watch_pairings.find_one({"pair_id": pair_id}, {"_id": 0})
    if not p:
        return {"status": "expired"}
    exp = p.get("expires_at")
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if not p.get("session_token"):
        if exp and exp < datetime.now(timezone.utc):
            await db.watch_pairings.delete_one({"pair_id": pair_id})
            return {"status": "expired"}
        return {"status": "pending"}
    # handed over once, then forgotten: the token only lives in the session and on the watch
    await db.watch_pairings.delete_one({"pair_id": pair_id})
    return {"status": "linked", "token": p["session_token"], "name": p.get("user_name") or ""}


@api_router.post("/watch/pair/confirm")
async def watch_pair_confirm(payload: WatchPairConfirmPayload, current: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=WATCH_PAIR_TTL_MIN)
    failed = await db.watch_pair_failures.count_documents({"user_id": current.user_id, "at": {"$gt": since}})
    if failed >= WATCH_MAX_FAILED_CODES:
        raise HTTPException(status_code=429, detail="Troppi codici sbagliati: riprova tra qualche minuto")
    code = "".join(ch for ch in payload.code if ch.isdigit())
    p = await db.watch_pairings.find_one({"code": code, "session_token": None, "expires_at": {"$gt": now}}, {"_id": 0})
    if not p:
        await db.watch_pair_failures.insert_one({"user_id": current.user_id, "at": now})
        raise HTTPException(status_code=404, detail="Codice non valido o scaduto: controlla quello mostrato sull'orologio")
    token = secrets.token_urlsafe(32)
    device_id = f"watch_{uuid.uuid4().hex[:12]}"
    await db.user_sessions.insert_one({
        "user_id": current.user_id, "session_token": token, "device": "watch", "device_id": device_id,
        "expires_at": now + timedelta(days=WATCH_SESSION_DAYS), "created_at": now,
    })
    await db.watch_devices.insert_one({
        "device_id": device_id, "user_id": current.user_id, "name": "Galaxy Watch",
        "created_at": now.isoformat(), "last_seen": None,
    })
    await db.watch_pairings.update_one({"pair_id": p["pair_id"]}, {"$set": {
        "user_id": current.user_id, "session_token": token, "user_name": current.name,
    }})
    return {"ok": True, "device_id": device_id}


@api_router.get("/watch/devices")
async def watch_devices(current: User = Depends(get_current_user)):
    return await db.watch_devices.find({"user_id": current.user_id}, {"_id": 0}).sort("created_at", -1).to_list(20)


@api_router.delete("/watch/devices/{device_id}")
async def watch_device_delete(device_id: str, current: User = Depends(get_current_user)):
    await db.watch_devices.delete_one({"device_id": device_id, "user_id": current.user_id})
    await db.user_sessions.delete_many({"device_id": device_id, "user_id": current.user_id})
    return {"ok": True}


async def _watch_seen(request: Request, current: User):
    token = request.headers.get("authorization", "")[7:]
    s = await db.user_sessions.find_one({"session_token": token, "device": "watch"}, {"_id": 0, "device_id": 1})
    if s:
        await db.watch_devices.update_one({"device_id": s["device_id"]}, {"$set": {"last_seen": datetime.now(timezone.utc).isoformat()}})


@api_router.get("/watch/me")
async def watch_me(request: Request, current: User = Depends(get_current_user)):
    await _watch_seen(request, current)
    return {"name": current.name, "email": current.email}


def _day_of(value) -> str:
    return str(value or "")[:10]


@api_router.get("/watch/tasks")
async def watch_tasks(current: User = Depends(get_current_user)):
    """Today's tasks, the overdue ones and the next week's, light enough for the watch."""
    today = datetime.now(LOCAL_TZ).date()
    horizon = (today + timedelta(days=7)).isoformat()
    t = today.isoformat()
    docs = await db.tasks.find(_visible_query(current), {"_id": 0, "id": 1, "title": 1, "due_date": 1, "due_time": 1,
                                                        "completed": 1, "completed_at": 1}).to_list(1000)
    out = []
    for d in docs:
        day = _day_of(d.get("due_date"))
        if not day:
            continue
        done = bool(d.get("completed"))
        if done:
            if day != t:
                continue
            status = "done"
        elif day < t:
            status = "late"
        elif day == t:
            status = "today"
        elif day <= horizon:
            status = "upcoming"
        else:
            continue
        time = d.get("due_time") or (str(d.get("due_date"))[11:16] if len(str(d.get("due_date") or "")) > 10 else "")
        out.append({"id": d["id"], "title": d.get("title") or "", "date": day, "time": time or "", "status": status})
    out.sort(key=lambda x: (x["date"], x["time"] or "99:99"))
    return {"today": t, "tasks": out}


@api_router.post("/watch/tasks/{task_id}/done")
async def watch_task_done(task_id: str, current: User = Depends(get_current_user)):
    q = {"id": task_id, **_editable_query(current)}
    res = await db.tasks.update_one(q, {"$set": {"completed": True, "completed_at": datetime.now(timezone.utc).isoformat()}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Task non trovato")
    return {"ok": True}


@api_router.get("/watch/todos")
async def watch_todos(current: User = Depends(get_current_user)):
    docs = await db.todos.find({"user_id": current.user_id, "status": {"$ne": "fatto"}},
                               {"_id": 0, "id": 1, "title": 1, "status": 1, "completion_percent": 1}).sort("created_at", -1).to_list(200)
    return [{"id": d["id"], "title": d.get("title") or "", "status": d.get("status") or "da_fare",
             "percent": d.get("completion_percent") or 0} for d in docs]


@api_router.post("/watch/todos/{todo_id}/done")
async def watch_todo_done(todo_id: str, current: User = Depends(get_current_user)):
    res = await db.todos.update_one({"id": todo_id, "user_id": current.user_id},
                                    {"$set": {"status": "fatto", "completion_percent": 100}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="To-do non trovato")
    return {"ok": True}


@api_router.get("/watch/lists")
async def watch_lists(current: User = Depends(get_current_user)):
    colls = await list_collections(current)
    return [{"id": c["id"], "name": c.get("name") or "", "count": c.get("item_count", 0)} for c in colls]


@api_router.get("/watch/lists/{collection_id}")
async def watch_list_items(collection_id: str, current: User = Depends(get_current_user)):
    coll = await db.collections.find_one({"id": collection_id, **_lists_query(current)}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Lista non trovata")
    items = await list_collection_items(collection_id, current)
    keys = [f["key"] for f in (coll.get("fields") or []) if f.get("key")]
    out = []
    for it in items[:300]:
        data = it.get("data") or {}
        vals = [str(data.get(k)).strip() for k in keys if data.get(k) not in (None, "", [], False)]
        if not keys:
            vals = [str(v).strip() for v in data.values() if v not in (None, "", [], False)]
        out.append({"id": it["id"], "label": vals[0] if vals else "—", "detail": " · ".join(vals[1:3])})
    return {"id": coll["id"], "name": coll.get("name") or "", "items": out}


@api_router.post("/watch/ask")
async def watch_ask(payload: WatchAskPayload, request: Request, current: User = Depends(get_current_user)):
    """One message from the watch to an agent; the answer comes back whole (no streaming),
    after the same routing the phone does: lists for "Salva", complete/delete for "Task"."""
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Messaggio vuoto")
    await _watch_seen(request, current)
    agent = payload.agent

    if agent == "scheduled_action":
        res = await _build_scheduled_draft(current, text, channel="watch")
        if res.get("status") != "confirm":
            return {"kind": "message", "reply": res.get("message") or "Non ho capito l'azione"}
        return {"kind": "confirm_action", "reply": res["preview"], "draft": res["draft"]}

    if agent == "task_todo":
        res = await _execute_task_command(current.user_id, text, channel="watch")
        if res is not None:
            if res["status"] == "ok":
                return {"kind": "message", "reply": res.get("message") or "Fatto"}
            if res["status"] == "ambiguous":
                titles = ", ".join(c["title"] for c in res["candidates"][:4])
                return {"kind": "message", "reply": f"Ho trovato più corrispondenze ({titles}): ripeti con il nome preciso."}
            return {"kind": "message", "reply": f"Non ho trovato nessun task o to-do che corrisponda a \"{res.get('query') or text}\"."}

    if agent == "info_upload":
        colls = await db.collections.find(_lists_query(current), {"_id": 0, "name": 1}).to_list(200)
        names = [c["name"] for c in colls]
        kind = await lu.classify_save_intent(text, names, user_id=current.user_id, channel="watch")
        if kind == "list_create":
            res = await _create_list_from_text(current, text, channel="watch")
            return {"kind": "message", "reply": res.get("message") or ""}
        if kind == "list_update" and not lu.looks_like_note(text):
            res = await _execute_list_update(current, text, channel="watch")
            status = res.get("status")
            if status in ("ambiguous_list", "ambiguous_item", "ambiguous_sub_item"):
                labels = ", ".join((c.get("name") or c.get("label") or "") for c in res.get("candidates", [])[:4])
                return {"kind": "message", "reply": f"Non so quale intendi ({labels}): ripeti con il nome preciso."}
            if status in ("confirm_clear", "confirm_bulk_add"):
                return {"kind": "message", "reply": "È una modifica grande: confermala dall'app sul telefono."}
            return {"kind": "message", "reply": res.get("message") or "Fatto"}

    conv_id = payload.conv_id
    if conv_id and not await db.conversations.find_one({"conv_id": conv_id, "user_id": current.user_id, "action": agent}, {"_id": 1}):
        conv_id = None
    user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    reply, conv_id = await tg._process_action(db, user_doc, agent, text, conv_id, channel="watch")
    return {"kind": "answer", "reply": reply, "conv_id": conv_id}


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


# ============ AZIONI PROGRAMMATE ============
# Comandi ricorrenti scritti a parole ("ogni venerdì all'una di notte svuota la lista lezioni
# di pilates"): interpretati una volta sola alla creazione (scheduled_actions.py), mostrati
# all'utente per conferma con la cadenza esatta, poi eseguiti da _scheduled_actions_loop
# finché l'utente non li disattiva o cancella dalla sezione Azioni.
class ScheduledInterpretPayload(BaseModel):
    text: str
    previous_text: Optional[str] = None


class ScheduledCreatePayload(BaseModel):
    draft: dict


class ScheduledPatchPayload(BaseModel):
    enabled: Optional[bool] = None
    title: Optional[str] = None


def _dt_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat() if dt else None


def _fmt_local_dt(iso: Optional[str]) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso).astimezone(LOCAL_TZ)
    return f"{sa.IT_WEEKDAYS[d.weekday()]} {d.day} {sa.IT_MONTHS[d.month - 1]} alle {d.strftime('%H:%M')}"


def _fields_text(fields: Optional[dict]) -> str:
    return " · ".join(str(v) for v in (fields or {}).values() if str(v or "").strip())


async def _describe_list_op(lo: dict, coll: dict) -> str:
    """What a scheduled list edit will do, in words, with today's counts - shown before the
    user confirms, so e.g. "svuota" can't silently mean the wrong level of the list."""
    name = coll["name"]
    op = lo["op"]
    items = await db.collection_items.find({"collection_id": coll["id"]}, {"_id": 0, "id": 1}).to_list(2000)
    item_ids = [i["id"] for i in items]
    if op == "clear_items":
        return f"eliminerò TUTTI i campi della lista \"{name}\" (oggi sono {len(items)}), con i loro elementi"
    if op == "clear_all_sub_items":
        n = await db.collection_sub_items.count_documents({"collection_id": coll["id"], "item_id": {"$in": item_ids}})
        return f"eliminerò tutti gli elementi dentro tutti i campi di \"{name}\", lasciando i campi (oggi {n} elementi in {len(items)} campi)"
    target = lo.get("item_query") or ""
    if op == "clear_sub_items":
        return f"eliminerò tutti gli elementi del campo \"{target}\" di \"{name}\""
    if op == "add_item":
        return f"aggiungerò a \"{name}\" il campo \"{_fields_text(lo.get('fields'))}\""
    if op == "bulk_add_items":
        return f"aggiungerò {len(lo.get('items') or [])} campi a \"{name}\""
    if op == "delete_item":
        return f"eliminerò da \"{name}\" il campo \"{target}\""
    if op == "update_item":
        return f"aggiornerò in \"{name}\" il campo \"{target}\" con: {_fields_text(lo.get('fields'))}"
    if op == "add_sub_item":
        who = [_fields_text(s) for s in (lo.get("sub_items") or [])] or [_fields_text(lo.get("fields"))]
        return f"aggiungerò {', '.join(w for w in who if w)} al campo \"{target}\" di \"{name}\""
    if op == "delete_sub_item":
        return f"eliminerò \"{lo.get('sub_item_query')}\" dal campo \"{target}\" di \"{name}\""
    if op == "update_sub_item":
        return f"aggiornerò \"{lo.get('sub_item_query')}\" nel campo \"{target}\" di \"{name}\" con: {_fields_text(lo.get('fields'))}"
    return f"modificherò la lista \"{name}\""


def _list_named(colls: list, name: str, text: str) -> Optional[dict]:
    """The list a command names: exact name first, then the best unique match."""
    for q in (name, text):
        q = (q or "").strip()
        if not q:
            continue
        exact = [c for c in colls if (c.get("name") or "").strip().lower() == q.lower()]
        if len(exact) == 1:
            return exact[0]
        ids = lu.match_candidates(q, [(c["id"], c.get("name") or "") for c in colls if (c.get("name") or "").strip()])
        if len(ids) == 1:
            return next(c for c in colls if c["id"] == ids[0])
    return None


def _news_rule(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    try:
        days = int(raw.get("older_than_days")) if raw.get("older_than_days") not in (None, "", "null") else None
    except (TypeError, ValueError):
        days = None
    if days is not None:
        days = max(0, min(days, 3650))
    return {"older_than_days": days, "keep_liked": raw.get("keep_liked") is not False, "only_disliked": raw.get("only_disliked") is True}


def _news_rule_label(nw: dict) -> str:
    what = "le news col pollice in giù" if nw.get("only_disliked") else "le news"
    if nw.get("older_than_days") is not None:
        what += f" più vecchie di {nw['older_than_days']} giorn{'o' if nw['older_than_days'] == 1 else 'i'}"
    if nw.get("keep_liked") and not nw.get("only_disliked"):
        what += " (tranne quelle col pollice in su)"
    return what


async def _build_scheduled_draft(current: User, text: str, channel: str = "web") -> dict:
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Scrivi cosa vuoi che faccia e quando")
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(LOCAL_TZ)
    colls = await db.collections.find(_lists_query(current), {"_id": 0}).to_list(200)
    linked = bool(current.telegram_chat_id)
    try:
        parsed = await sa.interpret_command(
            text, [{"name": c["name"], "has_sub_items": bool(c.get("sub_item_fields"))} for c in colls],
            now_local, linked, user_id=current.user_id, channel=channel,
        )
    except Exception as e:
        logger.exception("scheduled action interpretation failed")
        raise HTTPException(status_code=500, detail=f"Non sono riuscito a interpretare il comando: {e}")

    kind = parsed.get("kind")
    if parsed.get("supported") is False or kind not in sa.KINDS:
        return {"status": "unsupported", "message": parsed.get("reason") or "Non riesco a trasformare questa richiesta in un'azione programmata."}
    schedule = sa.normalize_schedule(parsed.get("schedule"))
    if not schedule and kind in ("list_delete", "news_delete"):
        schedule = {"freq": "now"}
    if not schedule:
        return {"status": "unsupported", "message": "Non ho capito quando eseguire l'azione: indicami il giorno (o la cadenza) e l'orario."}
    now_run = schedule["freq"] == "now"
    next_run = sa.next_run_after(schedule, now_utc)
    if not next_run:
        return {"status": "unsupported", "message": "La data indicata è già passata: indicami un momento futuro."}

    draft = {
        "text": text,
        "title": (str(parsed.get("title") or "").strip() or text)[:80],
        "description": str(parsed.get("description") or "").strip()[:600],
        "kind": kind,
        "schedule": schedule,
        "delivery": "telegram" if parsed.get("delivery") == "telegram" else "app",
        "notify": bool(parsed.get("notify")),
    }
    warnings = []
    if kind == "list_update":
        if not colls:
            return {"status": "unsupported", "message": "Non hai ancora nessuna lista: creane una nella sezione Liste prima di programmare modifiche."}
        request = (str(parsed.get("list_request") or "").strip() or text)
        catalog = [{"id": c["id"], "name": c["name"], "fields": c.get("fields", []), "sub_item_fields": c.get("sub_item_fields", [])} for c in colls]
        try:
            li = await lu.interpret_list_request(request, catalog, user_id=current.user_id, channel=channel)
        except Exception as e:
            logger.exception("scheduled list interpretation failed")
            raise HTTPException(status_code=500, detail=f"Non sono riuscito a capire la modifica alla lista: {e}")
        coll = next((c for c in colls if c["id"] == li.get("collection_id")), None)
        if li.get("op") not in lu.VALID_OPS or not coll:
            return {"status": "unsupported", "message": "Non ho capito quale lista modificare o come: scrivi il nome della lista e cosa fare (es. \"svuota tutti gli iscritti della lista Lezioni Pilates\")."}
        draft["list_op"] = {
            "text": request, "op": li["op"], "collection_id": coll["id"], "collection_name": coll["name"],
            "item_query": li.get("item_query") or "", "sub_item_query": li.get("sub_item_query") or "",
            "fields": li.get("fields") or {}, "sub_items": li.get("sub_items") or [], "items": li.get("items") or [],
        }
        what = await _describe_list_op(draft["list_op"], coll)
    elif kind == "report":
        instruction = str(parsed.get("report_instruction") or "").strip() or text
        period = parsed.get("period") if parsed.get("period") in sa.PERIODS else "none"
        draft.update({"report_instruction": instruction, "period": period})
        what = f"{instruction[0].lower() + instruction[1:]}" + (f", usando i dati del periodo: {sa.PERIOD_PREVIEW[period]}" if period != "none" else "")
        rl = _report_list_for(colls, str(parsed.get("report_list") or ""), instruction)
        if rl:
            draft["report_list_id"] = rl["id"]
            what += f", controllando uno per uno gli elementi della lista «{rl['name']}» nelle informazioni salvate"
    elif kind == "list_delete":
        coll = _list_named(colls, str(parsed.get("list_name") or ""), text)
        if not coll:
            names = ", ".join(f"«{c['name']}»" for c in colls[:12]) or "nessuna"
            return {"status": "unsupported", "message": f"Non ho capito quale lista eliminare. Le tue liste: {names}."}
        if coll.get("user_id") != current.user_id:
            return {"status": "unsupported", "message": f"La lista «{coll['name']}» te l'ha condivisa un collega: solo chi l'ha creata può eliminarla."}
        if coll.get("system_key"):
            return {"status": "unsupported", "message": f"«{coll['name']}» è la lista di base del tuo settore: non si può eliminare."}
        n = await db.collection_items.count_documents({"collection_id": coll["id"]})
        draft["list_delete"] = {"collection_id": coll["id"], "collection_name": coll["name"]}
        draft["title"] = f"Elimina la lista «{coll['name']}»"[:80]
        what = (f"eliminerò la lista «{coll['name']}» con {'il suo campo' if n == 1 else f'i suoi {n} campi'} e tutti i loro "
                f"elementi. Non si può annullare")
    elif kind == "news_delete":
        nw = _news_rule(parsed.get("news"))
        draft["news"] = nw
        what = "eliminerò " + _news_rule_label(nw)
    elif kind == "message":
        msg = str(parsed.get("message_text") or "").strip()
        if not msg:
            return {"status": "unsupported", "message": "Non ho capito il testo del promemoria da inviarti."}
        draft["message_text"] = msg
        what = f"ti manderò il promemoria: \"{msg}\""
    else:
        task = parsed.get("task") if isinstance(parsed.get("task"), dict) else {}
        title = str(task.get("title") or "").strip()
        if not title:
            return {"status": "unsupported", "message": "Non ho capito che task creare."}
        draft["task"] = {
            "title": title[:200],
            "priority": task.get("priority") if task.get("priority") in ("alta", "media", "bassa") else "media",
            "due_time": sa._norm_time(task.get("due_time")),
        }
        what = f"creerò il task \"{title}\" con scadenza il giorno stesso"

    if draft["delivery"] == "telegram" and not linked:
        draft["delivery"] = "app"
        warnings.append("Telegram non è collegato: finché non lo colleghi (Impostazioni → Telegram) il risultato lo trovi nella sezione Azioni.")
    if now_run:
        draft["schedule_label"] = sa.schedule_label(schedule)
        preview = f"Adesso, una volta sola (l'azione non resta salvata): {what}."
        if warnings:
            preview += "\n⚠️ " + " ".join(warnings)
        return {"status": "confirm", "draft": draft, "preview": preview}
    if kind in ("report", "message"):
        where = "su Telegram" if draft["delivery"] == "telegram" else "nella sezione Azioni"
        what += f"; il risultato arriverà {where}"
    elif draft["notify"] and linked:
        what += "; ti avviserò su Telegram a ogni esecuzione"

    draft["schedule_label"] = sa.schedule_label(schedule)
    preview = f"{draft['schedule_label']} {what}.\nPrima esecuzione: {_fmt_local_dt(_dt_iso(next_run))}."
    if warnings:
        preview += "\n⚠️ " + " ".join(warnings)
    return {"status": "confirm", "draft": draft, "preview": preview}


def _public_action(a: dict) -> dict:
    a = {k: v for k, v in a.items() if k != "_id"}
    a["next_run_label"] = _fmt_local_dt(a.get("next_run_at")) if a.get("enabled") else ""
    a["last_run_label"] = _fmt_local_dt(a.get("last_run_at"))
    try:
        a["schedule_label"] = sa.schedule_label(a.get("schedule") or {})
    except Exception:
        a["schedule_label"] = ""
    return a


@api_router.post("/scheduled-actions/interpret")
async def interpret_scheduled_action(payload: ScheduledInterpretPayload, current: User = Depends(get_current_user)):
    text = payload.text.strip()
    if payload.previous_text and payload.previous_text.strip():
        text = f"{payload.previous_text.strip()}\nPrecisazione successiva dell'utente (ha la precedenza): {text}"
    return await _build_scheduled_draft(current, text)


async def _create_scheduled_action(current: User, draft: dict) -> dict:
    kind = draft.get("kind")
    schedule = sa.normalize_schedule(draft.get("schedule"))
    if kind not in sa.KINDS or not schedule:
        raise HTTPException(status_code=400, detail="Azione non valida, riprova a descriverla")
    now_run = schedule["freq"] == "now"
    active = 0 if now_run else await db.scheduled_actions.count_documents({"user_id": current.user_id, "enabled": True})
    if active >= sa.MAX_ACTIVE_PER_USER:
        raise HTTPException(status_code=400, detail=f"Hai già {active} azioni attive (massimo {sa.MAX_ACTIVE_PER_USER}): disattivane o cancellane qualcuna.")
    next_run = sa.next_run_after(schedule, datetime.now(timezone.utc))
    if not next_run:
        raise HTTPException(status_code=400, detail="La data indicata è già passata")
    doc = {
        "id": f"{'once' if now_run else 'sched'}_{uuid.uuid4().hex[:12]}",
        "user_id": current.user_id,
        "org_id": current.org_id,
        "text": str(draft.get("text") or "")[:2000],
        "title": str(draft.get("title") or "Azione programmata")[:80],
        "description": str(draft.get("description") or "")[:600],
        "kind": kind,
        "schedule": schedule,
        "schedule_label": sa.schedule_label(schedule),
        "delivery": "telegram" if draft.get("delivery") == "telegram" else "app",
        "notify": bool(draft.get("notify")),
        "enabled": True,
        "next_run_at": _dt_iso(next_run),
        "last_run_at": None,
        "last_status": None,
        "last_result": None,
        "run_count": 0,
        "runs": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if kind == "list_update":
        lo = draft.get("list_op") or {}
        target_list = await db.collections.find_one({"id": lo.get("collection_id"), **_lists_query(current)}, {"_id": 0})
        if lo.get("op") not in lu.VALID_OPS or not target_list:
            raise HTTPException(status_code=400, detail="Lista non trovata")
        _require_list_edit(target_list, current)
        doc["list_op"] = {k: lo.get(k) for k in ("text", "op", "collection_id", "collection_name", "item_query", "sub_item_query", "fields", "sub_items", "items")}
    elif kind == "report":
        doc["report_instruction"] = str(draft.get("report_instruction") or doc["text"])[:1000]
        doc["period"] = draft.get("period") if draft.get("period") in sa.PERIODS else "none"
        if draft.get("report_list_id"):
            doc["report_list_id"] = str(draft["report_list_id"])
    elif kind == "list_delete":
        ld = draft.get("list_delete") or {}
        coll = await db.collections.find_one({"id": ld.get("collection_id"), **_lists_query(current)}, {"_id": 0})
        if not coll:
            raise HTTPException(status_code=400, detail="Lista non trovata (forse è già stata eliminata)")
        _require_list_edit(coll, current)
        if coll.get("user_id") != current.user_id:
            raise HTTPException(status_code=403, detail="Solo chi ha creato la lista può eliminarla.")
        doc["list_delete"] = {"collection_id": coll["id"], "collection_name": coll["name"]}
    elif kind == "news_delete":
        doc["news"] = _news_rule(draft.get("news"))
    elif kind == "message":
        doc["message_text"] = str(draft.get("message_text") or "")[:1000]
    else:
        t = draft.get("task") or {}
        doc["task"] = {"title": str(t.get("title") or doc["title"])[:200],
                       "priority": t.get("priority") if t.get("priority") in ("alta", "media", "bassa") else "media",
                       "due_time": sa._norm_time(t.get("due_time"))}
    if now_run:   # una tantum: done right now, nothing saved
        run = await _execute_scheduled_action(doc, manual=True)
        return {"ran": True, "title": doc["title"], "status": run.get("status"), "result": run.get("result") or ""}
    await db.scheduled_actions.insert_one(doc)
    ut.fire_and_forget_feature_event(user_id=current.user_id, feature="azioni_programmate", channel="web", trigger="utente", org_id=current.org_id)
    return _public_action(doc)


@api_router.post("/scheduled-actions")
async def create_scheduled_action(payload: ScheduledCreatePayload, current: User = Depends(get_current_user)):
    return await _create_scheduled_action(current, payload.draft)


@api_router.get("/scheduled-actions")
async def list_scheduled_actions(current: User = Depends(get_current_user)):
    await _ensure_weekly_jobs_action(current)   # artigiani who chose the vertical before it existed
    docs = await db.scheduled_actions.find({"user_id": current.user_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # actions saved before short labels and descriptions existed get them once (then stored)
    for d in docs:
        if d.get("description"):
            continue
        try:
            got = await sa.describe_action(d.get("text") or d.get("title") or "", sa.schedule_label(d.get("schedule") or {}), user_id=current.user_id)
        except Exception:
            logger.exception(f"describing action {d.get('id')} failed")
            continue
        upd = {k: v for k, v in got.items() if v}
        if upd:
            await db.scheduled_actions.update_one({"id": d["id"]}, {"$set": upd})
            d.update(upd)
    return [_public_action(d) for d in docs]


@api_router.patch("/scheduled-actions/{action_id}")
async def update_scheduled_action(action_id: str, payload: ScheduledPatchPayload, current: User = Depends(get_current_user)):
    a = await db.scheduled_actions.find_one({"id": action_id, "user_id": current.user_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Azione non trovata")
    upd = {}
    if payload.title is not None and payload.title.strip():
        upd["title"] = payload.title.strip()[:80]
    if payload.enabled is not None:
        if payload.enabled and not a.get("enabled"):
            active = await db.scheduled_actions.count_documents({"user_id": current.user_id, "enabled": True})
            if active >= sa.MAX_ACTIVE_PER_USER:
                raise HTTPException(status_code=400, detail=f"Hai già {active} azioni attive (massimo {sa.MAX_ACTIVE_PER_USER})")
            # Re-activation starts from now: runs missed while paused are skipped, not replayed.
            nxt = sa.next_run_after(a["schedule"], datetime.now(timezone.utc))
            if not nxt:
                raise HTTPException(status_code=400, detail="Questa azione era da eseguire una volta sola e la data è passata")
            upd.update({"enabled": True, "next_run_at": _dt_iso(nxt)})
        elif not payload.enabled:
            upd.update({"enabled": False, "next_run_at": None})
    if upd:
        await db.scheduled_actions.update_one({"id": action_id}, {"$set": upd})
        a.update(upd)
    return _public_action(a)


@api_router.delete("/scheduled-actions/{action_id}")
async def delete_scheduled_action(action_id: str, current: User = Depends(get_current_user)):
    res = await db.scheduled_actions.delete_one({"id": action_id, "user_id": current.user_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Azione non trovata")
    return {"ok": True}


@api_router.post("/scheduled-actions/{action_id}/run")
async def run_scheduled_action_now(action_id: str, current: User = Depends(get_current_user)):
    """"Esegui ora": same execution as the scheduled one (handy to check what it does),
    without moving the next scheduled run."""
    a = await db.scheduled_actions.find_one({"id": action_id, "user_id": current.user_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Azione non trovata")
    await _execute_scheduled_action(a, manual=True)
    a = await db.scheduled_actions.find_one({"id": action_id}, {"_id": 0})
    return _public_action(a)


async def _send_telegram_text(chat_id, text: str) -> bool:
    """Plain text to a linked chat, Markdown first then plain as fallback - model-written
    text can contain characters Telegram's Markdown parser rejects."""
    if not chat_id or not tg.bot_token() or not text:
        return False
    from telegram import Bot
    bot = Bot(token=tg.bot_token())
    ok = True
    for i in range(0, len(text), 3900):
        chunk = text[i:i + 3900]
        try:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
        except Exception:
            try:
                await bot.send_message(chat_id=chat_id, text=chunk)
            except Exception:
                logger.exception("scheduled action telegram send failed")
                ok = False
    return ok


def _report_list_for(colls: list, name: str, instruction: str) -> Optional[dict]:
    """The list a report goes through element by element: the one the interpreter named, or
    one the instruction clearly names."""
    name = (name or "").strip().lower()
    if name:
        exact = [c for c in colls if (c.get("name") or "").strip().lower() == name]
        if exact:
            return exact[0]
        ids = lu.match_candidates(name, [(c["id"], c.get("name") or "") for c in colls])
        if len(ids) == 1:
            return next(c for c in colls if c["id"] == ids[0])
        return None
    score, ids = retrieval._match_scored(instruction, [(c["id"], c.get("name") or "") for c in colls if (c.get("name") or "").strip()])
    if len(ids) == 1 and score >= 1000:   # the list's whole name is in the instruction
        return next(c for c in colls if c["id"] == ids[0])
    return None


async def _list_items_with_kb(user: User, coll: dict, today) -> List[str]:
    """For every element of a list: what is saved about it in the knowledge base (notes,
    documents, diary, tasks) and when the latest piece was saved - computed here, so "i
    clienti senza informazioni da più di un mese" is a matter of reading a number."""
    uid = user.user_id
    items = await db.collection_items.find({"collection_id": coll["id"]}, {"_id": 0, "embedding": 0}).to_list(2000)
    key = ((coll.get("fields") or [{}])[0] or {}).get("key")
    records = []   # (day, kind, text)
    for c in await db.kb_chunks.find({"user_id": uid}, {"_id": 0, "text": 1, "created_at": 1, "source_name": 1}).to_list(20000):
        records.append((retrieval._local_day(c.get("created_at")), "nota" if not c.get("source_name") else f"documento «{c['source_name']}»", c.get("text") or ""))
    for j in await db.journal_entries.find({"user_id": uid}, {"_id": 0, "date": 1, "cleaned_text": 1, "raw_text": 1}).to_list(5000):
        records.append((retrieval._local_day(j.get("date")), "diario", j.get("cleaned_text") or j.get("raw_text") or ""))
    for t in await db.tasks.find(_visible_query(user), {"_id": 0, "title": 1, "notes": 1, "description": 1, "created_at": 1}).to_list(3000):
        records.append((retrieval._local_day(t.get("created_at")), "task", " ".join(x for x in (t.get("title"), t.get("description"), t.get("notes")) if x)))
    prepared = [(d, k, txt, txt.lower(), retrieval._tokens(txt)) for d, k, txt in records if txt]
    out = [f"--- Elementi della lista «{coll['name']}» ({len(items)}) con le informazioni salvate su ciascuno nella knowledge base "
           f"(oggi è {retrieval.format_it_date(today.isoformat())}) ---"]
    for it in items[:400]:
        name = str(((it.get("data") or {}).get(key) if key else "") or "").strip()
        display = lu.item_display(it)
        if not name:
            continue
        low = name.lower()
        words = [w for w in retrieval._tokens(low) if len(w) >= 3]
        hits = [(d, k, txt) for d, k, txt, tl, toks in prepared
                if low in tl or (len(words) >= 2 and all(w in toks for w in words))]
        if not hits:
            out.append(f"• {display} — nessuna informazione salvata")
            continue
        dated = [h for h in hits if h[0]]
        last = max(dated, key=lambda h: h[0]) if dated else hits[0]
        ago = f", {(today - last[0]).days} giorni fa" if last[0] else ""
        when = retrieval.format_it_date(last[0].isoformat()) if last[0] else "data sconosciuta"
        n = f"1 informazione salvata" if len(hits) == 1 else f"{len(hits)} informazioni salvate"
        out.append(f"• {display} — {n}; l'ultima il {when}{ago} ({last[1]}: «{last[2][:120]}»)")
    return out


async def _gather_report_data(user: User, instruction: str, rng, list_id: Optional[str] = None) -> str:
    """Everything the report may need: all records dated inside the period (notes, diary,
    tasks, to-dos, list entries) plus the best search hits for the instruction itself (e.g.
    a "Spese" list whose rows carry no date)."""
    lines, seen = [], set()

    def add(line: str):
        key = line.strip()[:400]
        if key and key not in seen:
            seen.add(key)
            lines.append(line.strip())

    uid = user.user_id
    colls = await db.collections.find(_lists_query(user), {"_id": 0}).to_list(200)
    coll_by_id = {c["id"]: c for c in colls}
    per_item = coll_by_id.get(list_id) if list_id else _report_list_for(colls, "", instruction)
    if per_item:
        for line in await _list_items_with_kb(user, per_item, datetime.now(LOCAL_TZ).date()):
            add(line)
    if rng:
        s, e, _ = rng
        start_iso = datetime(s.year, s.month, s.day, tzinfo=LOCAL_TZ).astimezone(timezone.utc).isoformat()
        e1 = e + timedelta(days=1)
        end_iso = datetime(e1.year, e1.month, e1.day, tzinfo=LOCAL_TZ).astimezone(timezone.utc).isoformat()
        in_range = {"$gte": start_iso, "$lt": end_iso}
        for c in await db.kb_chunks.find({"user_id": uid, "created_at": in_range}, {"_id": 0, "embedding": 0}).sort("created_at", 1).to_list(400):
            add(retrieval._kb_display(c))
        for j in await db.journal_entries.find({"user_id": uid, "date": {"$gte": s.isoformat(), "$lte": e.isoformat()}}, {"_id": 0}).sort("date", 1).to_list(60):
            add(f"[Diario {retrieval.format_it_date(j.get('date'))}] {(j.get('cleaned_text') or j.get('raw_text') or '')[:1500]}")
        task_q = {"$and": [_visible_query(user), {"$or": [
            {"due_date": {"$gte": s.isoformat(), "$lte": e.isoformat()}}, {"completed_at": in_range}]}]}
        for t in await db.tasks.find(task_q, {"_id": 0}).to_list(300):
            state = "completato" if t.get("completed") else "aperto"
            add(f"[Task] {t.get('title', '')} · scadenza {t.get('due_date') or '-'} · {state}")
        for t in await db.todos.find({"user_id": uid, "created_at": in_range}, {"_id": 0}).to_list(200):
            add(f"[To-Do creato {retrieval.format_it_date(t.get('created_at'))}] {t.get('title', '')} · {t.get('status', '')}")
        if coll_by_id:
            items = await db.collection_items.find({"collection_id": {"$in": list(coll_by_id)}, "created_at": in_range}, {"_id": 0}).to_list(1000)
            for it in items:
                add(f"[Lista \"{coll_by_id[it['collection_id']]['name']}\" · aggiunto {retrieval.format_it_date(it.get('created_at'))}] {lu.item_display(it)}")
            subs = await db.collection_sub_items.find({"collection_id": {"$in": list(coll_by_id)}, "created_at": in_range}, {"_id": 0}).to_list(1000)
            parents = {}
            if subs:
                for p in await db.collection_items.find({"id": {"$in": list({x['item_id'] for x in subs})}}, {"_id": 0}).to_list(1000):
                    parents[p["id"]] = p
            for sub in subs:
                parent = parents.get(sub["item_id"])
                where = f"{coll_by_id[sub['collection_id']]['name']} › {lu.item_display(parent)}" if parent else coll_by_id[sub["collection_id"]]["name"]
                add(f"[Lista \"{where}\" · aggiunto {retrieval.format_it_date(sub.get('created_at'))}] {lu.item_display(sub)}")
    try:
        hits = await retrieval.retrieve(db, uid, instruction, limit=12, scope="all", org_id=user.org_id)
    except Exception:
        logger.exception("report retrieval failed")
        hits = []
    if hits:
        add("--- Altri dati pertinenti trovati con la ricerca (possono essere fuori dal periodo) ---")
        for h in hits:
            add(h.get("display") or retrieval._kb_display(h))
    out, total = [], 0
    cap = 60000 if per_item else 30000   # one line per element of the list comes first
    for line in lines:
        if total + len(line) > cap:
            break
        out.append(line)
        total += len(line) + 1
    return "\n".join(out)


async def _execute_scheduled_action(a: dict, manual: bool = False, scheduled_for: Optional[str] = None) -> dict:
    """Runs one action and records the outcome on it (last_* fields + last 10 runs)."""
    started = datetime.now(timezone.utc)
    status, result, delivered = "ok", "", False
    user_doc = await db.users.find_one({"user_id": a["user_id"]}, {"_id": 0})
    if not user_doc:
        await db.scheduled_actions.update_one({"id": a["id"]}, {"$set": {"enabled": False, "next_run_at": None}})
        return {"status": "error", "result": "utente non trovato"}
    user = User(**user_doc)
    chat_id = user_doc.get("telegram_chat_id")
    kind = a.get("kind")
    try:
        if kind == "list_update":
            lo = a.get("list_op") or {}
            try:
                res = await _execute_list_update(
                    user, lo.get("text") or a.get("text", ""), op=lo.get("op"), collection_id=lo.get("collection_id"),
                    item_query=lo.get("item_query"), sub_item_query=lo.get("sub_item_query"), fields=lo.get("fields"),
                    confirm=True, new_sub_items=lo.get("sub_items"), new_items=lo.get("items"), channel="sistema",
                )
            except HTTPException as he:
                res = {"status": "error", "message": str(he.detail)}
            if res.get("status") == "ok":
                result = res.get("message") or "Fatto."
            elif str(res.get("status", "")).startswith("ambiguous"):
                status = "error"
                result = "Più elementi corrispondono alla descrizione, non ho modificato nulla per non sbagliare. Rendi il comando più preciso."
            else:
                status = "error"
                result = res.get("message") or "Modifica non riuscita."
            if a.get("notify") and chat_id:
                delivered = await _send_telegram_text(chat_id, f"🔁 *{a['title']}*\n{'✅' if status == 'ok' else '⚠️'} {result}")
        elif kind == "report":
            now_local = started.astimezone(LOCAL_TZ)
            rng = sa.period_range(a.get("period") or "none", now_local)
            data_block = await _gather_report_data(user, a.get("report_instruction") or a.get("text", ""), rng, a.get("report_list_id"))
            result = await sa.write_report(a.get("report_instruction") or a.get("text", ""), data_block, now_local,
                                           rng[2] if rng else None, user_name=user.name, user_id=user.user_id)
            if not result:
                status, result = "error", "Il riepilogo è risultato vuoto."
            elif a.get("delivery") == "telegram" and chat_id:
                delivered = await _send_telegram_text(chat_id, f"🔁 *{a['title']}*\n\n{result}")
        elif kind == "list_delete":
            ld = a.get("list_delete") or {}
            coll = await db.collections.find_one({"id": ld.get("collection_id"), "user_id": user.user_id}, {"_id": 0})
            if not coll:
                status, result = "error", f"La lista «{ld.get('collection_name') or ''}» non c'è più (forse è già stata eliminata)."
            else:
                n = await db.collection_items.count_documents({"collection_id": coll["id"]})
                await delete_collection(coll["id"], user)
                result = f"Eliminata la lista «{coll['name']}» ({n} camp{'o' if n == 1 else 'i'})."
            if a.get("notify") and chat_id:
                delivered = await _send_telegram_text(chat_id, f"🔁 *{a['title']}*\n{'✅' if status == 'ok' else '⚠️'} {result}")
        elif kind == "news_delete":
            nw = _news_rule(a.get("news"))
            q = {"user_id": user.user_id}
            if nw["older_than_days"] is not None:
                q["created_at"] = {"$lt": (started - timedelta(days=nw["older_than_days"])).isoformat()}
            if nw["only_disliked"]:
                q["feedback"] = "dislike"
            elif nw["keep_liked"]:
                q["feedback"] = {"$ne": "like"}
            await _remember_disliked_sources(q)
            res = await db.news_items.delete_many(q)
            n = res.deleted_count
            result = (f"Eliminate {n} news" if n != 1 else "Eliminata 1 news") + f": {_news_rule_label(nw)}." if n else f"Nessuna news da eliminare ({_news_rule_label(nw)})."
            if a.get("notify") and chat_id:
                delivered = await _send_telegram_text(chat_id, f"🔁 *{a['title']}*\n✅ {result}")
        elif kind == "job_weekly":
            result = await _job_weekly_summary(user, started.astimezone(LOCAL_TZ))
            if chat_id:
                delivered = await _send_telegram_text(chat_id, result)
        elif kind == "message":
            result = a.get("message_text") or a.get("title")
            if a.get("delivery") == "telegram" and chat_id:
                delivered = await _send_telegram_text(chat_id, f"⏰ {result}")
        elif kind == "create_task":
            t = a.get("task") or {}
            due = started.astimezone(LOCAL_TZ).date().isoformat()
            await _create_task_or_todo(user.user_id, {
                "title": t.get("title") or a["title"], "priority": t.get("priority") or "media",
                "due_date": due, "due_time": t.get("due_time"),
                "description": f"Creato dall'azione programmata \"{a['title']}\"",
            }, f"sched_{a['id']}")
            result = f"Creato il task \"{t.get('title') or a['title']}\" con scadenza {due}."
            if a.get("notify") and chat_id:
                delivered = await _send_telegram_text(chat_id, f"🔁 *{a['title']}*\n✅ {result}")
        else:
            status, result = "error", "Tipo di azione sconosciuto."
    except Exception as e:
        logger.exception(f"scheduled action {a.get('id')} failed")
        status, result = "error", f"Errore durante l'esecuzione: {e}"

    run = {"at": _dt_iso(started), "status": status, "result": (result or "")[:4000], "delivered": delivered, "manual": manual}
    if scheduled_for and not manual:
        late = (started - datetime.fromisoformat(scheduled_for)).total_seconds() / 60
        if late > 10:
            run["late_minutes"] = int(late)
    await db.scheduled_actions.update_one({"id": a["id"]}, {
        "$set": {"last_run_at": run["at"], "last_status": status, "last_result": run["result"], "last_delivered": delivered},
        "$inc": {"run_count": 1},
        "$push": {"runs": {"$each": [run], "$slice": -10}},
    })
    ut.fire_and_forget_feature_event(user_id=user.user_id, feature="azioni_programmate", channel="web" if manual else "sistema",
                                     trigger="utente" if manual else "automatico", org_id=user.org_id)
    logger.info(f"[scheduled] {a['id']} kind={kind} status={status} manual={manual}")
    return run


# ---- the artigiano's preconfigured action: Monday's summary of the job sites ----
WEEKLY_JOBS_KEY = "artigiano_weekly"


async def _job_weekly_summary(user: User, now_local: datetime) -> str:
    """Last week (Mon-Sun) on the job sites, from the data, no AI: hours per site and person,
    materials, problems, quote vs costs, the sites standing still, the activities due."""
    clienti = await _clienti_list(user)
    if not clienti:
        return "Non c'è ancora la lista Clienti con le commesse."
    lo, hi, label = sa.period_range("last_week", now_local)
    commesse, _ = await _all_commesse(clienti)
    open_c = [c for c in commesse if c["stato"] != "chiusa"]
    ids = [c["id"] for c in commesse]
    logs = await db.job_logs.find({"commessa_id": {"$in": ids}}, {"_id": 0, "embedding": 0}).to_list(50000) if ids else []
    by: dict = {}
    for lg in logs:
        by.setdefault(lg["commessa_id"], []).append(lg)
    week = lambda lgs: [x for x in lgs if not x.get("kind") and lo.isoformat() <= (x.get("date") or "") <= hi.isoformat()]
    lines = [f"🗓 *Cantieri — {label}*"]
    worked = sorted([c for c in commesse if week(by.get(c["id"], []))],
                    key=lambda c: -jl.totals(week(by[c["id"]]))["hours_total"])
    all_week = [x for c in worked for x in week(by[c["id"]])]
    if not worked:
        lines.append("Nessuna voce di diario nella settimana.")
    else:
        tot = jl.totals(all_week)
        per = ", ".join(f"{k} {jl._fmt_num(v)} h" for k, v in sorted(tot["by_person"].items(), key=lambda x: -x[1]))
        lines.append(f"Ore totali: *{jl._fmt_num(tot['hours_total'])} h*" + (f" ({per})" if per else ""))
    econs = {}
    for c in worked:
        t = jl.totals(week(by[c["id"]]))
        per = ", ".join(f"{k} {jl._fmt_num(v)} h" for k, v in t["by_person"].items())
        lines.append(f"\n*{c['title']}* — {c['client_name']}: {jl._fmt_num(t['hours_total'])} h" + (f" ({per})" if per else ""))
        if t["materials"]:
            lines.append(f"🧰 {jl.materials_line(t['materials'])}")
        for p in t["problems"]:
            lines.append(f"⚠️ {p['text']}")
        econs[c["id"]] = e = await _commessa_economics(clienti, c["id"], by[c["id"]])
        if e.get("budget"):
            flag = "🔴 " if e["used_pct"] >= 100 else "🟠 " if e["used_pct"] >= 80 else ""
            lines.append(f"{flag}💶 speso {jl._eur(e['cost_total'])} di {jl._eur(e['budget'])} ({e['used_pct']:.0f}%), margine {jl._eur(e['margin'])}")
    # quotes at risk on the sites not worked last week
    risky = []
    for c in open_c:
        if c["id"] in econs:
            continue
        e = await _commessa_economics(clienti, c["id"], by.get(c["id"], []))
        if e.get("budget") and e["used_pct"] >= 80:
            risky.append(f"«{c['title']}» {e['used_pct']:.0f}%")
    if risky:
        lines.append("\n🟠 Preventivi oltre l'80%: " + ", ".join(risky))
    # sites "in corso" standing still for more than a week
    still = []
    for c in open_c:
        if c["stato"] != "in corso":
            continue
        days = [x.get("date") for x in by.get(c["id"], []) if not x.get("kind") and x.get("date")]
        last = max(days) if days else None
        if not last or last < (hi - timedelta(days=6)).isoformat():
            still.append(f"«{c['title']}» ({'mai' if not last else 'ultima ' + _short_it_date(last)})")
    if still:
        lines.append("\n⏸ In corso ma senza voci da più di 7 giorni: " + ", ".join(still))
    # the commesse's To Do due this week
    today = now_local.date()
    due = await db.job_todos.find({"commessa_id": {"$in": [c["id"] for c in open_c]}, "done": False}, {"_id": 0}).to_list(2000) if open_c else []
    titles = {c["id"]: c["title"] for c in commesse}
    week_due = sorted([t for t in due if t.get("due_date") and t["due_date"] <= (today + timedelta(days=6)).isoformat()],
                      key=lambda t: t["due_date"])
    # the milestones: late ones, and the ones due this week
    ms = await db.job_milestones.find({"commessa_id": {"$in": [c["id"] for c in open_c]}, "done": False}, {"_id": 0}).to_list(2000) if open_c else []
    ms_late = sorted([m for m in ms if m["due_date"] < today.isoformat()], key=lambda m: m["due_date"])
    ms_week = sorted([m for m in ms if today.isoformat() <= m["due_date"] <= (today + timedelta(days=6)).isoformat()], key=lambda m: m["due_date"])
    if ms_late:
        lines.append("\n🔴 Milestone in ritardo:")
        lines += [f"• {m['title']} — {m.get('who') or ''}, scadenza {_short_it_date(m['due_date'])} "
                  f"({_days(today.isoformat(), m['due_date'])} g) · «{titles.get(m['commessa_id'], '')}»" for m in ms_late[:15]]
    if ms_week:
        lines.append("\n🚩 Milestone di questa settimana:")
        lines += [f"• {m['title']} — {m.get('who') or ''} entro {_short_it_date(m['due_date'])} · «{titles.get(m['commessa_id'], '')}»"
                  for m in ms_week[:15]]
    if week_due:
        lines.append("\n📌 Da fare entro questa settimana:")
        lines += [f"• {t['text']} — {t.get('who') or ''} entro {_short_it_date(t['due_date'])}"
                  + (" (scaduta)" if t["due_date"] < today.isoformat() else "") + f" · «{titles.get(t['commessa_id'], '')}»"
                  for t in week_due[:15]]
    return "\n".join(lines)


async def _ensure_weekly_jobs_action(user: User) -> None:
    """The artigiano gets the Monday summary of the job sites as an action, once: paused or
    deleted, it is never created again."""
    if user.business_vertical != "artigiano":
        return
    udoc = await db.users.find_one({"user_id": user.user_id}, {"_id": 0, "system_actions": 1}) or {}
    if WEEKLY_JOBS_KEY in (udoc.get("system_actions") or []):
        return
    await db.users.update_one({"user_id": user.user_id}, {"$addToSet": {"system_actions": WEEKLY_JOBS_KEY}})
    schedule = sa.normalize_schedule({"freq": "weekly", "weekdays": [0], "time": "08:00"})
    now = datetime.now(timezone.utc)
    await db.scheduled_actions.insert_one({
        "id": f"sched_{uuid.uuid4().hex[:12]}", "user_id": user.user_id, "org_id": user.org_id, "system_key": WEEKLY_JOBS_KEY,
        "text": "Ogni lunedì alle 8 mandami il riepilogo della settimana passata dei cantieri",
        "title": "Riepilogo cantieri",
        "description": ("Ogni lunedì alle 8:00 ti invia il riepilogo della settimana appena conclusa: ore per cantiere e per "
                        "persona, materiali, problemi segnalati, costi rispetto al preventivo, cantieri fermi da più di una "
                        "settimana e attività in scadenza. Arriva su Telegram, se collegato, e resta qui."),
        "kind": "job_weekly", "schedule": schedule, "schedule_label": sa.schedule_label(schedule),
        "delivery": "telegram", "notify": False, "enabled": True,
        "next_run_at": _dt_iso(sa.next_run_after(schedule, now)), "last_run_at": None, "last_status": None,
        "last_result": None, "run_count": 0, "runs": [], "created_at": now.isoformat(),
    })


async def _scheduled_actions_loop():
    """Every 30s: runs every enabled action whose next_run_at has come. The next run is
    moved forward BEFORE executing (a compare-and-set on next_run_at, so a run is never
    picked up twice), always computed from now: if the server was off at the scheduled
    moment, a missed action runs once on restart instead of once per missed occurrence."""
    await asyncio.sleep(20)
    while True:
        try:
            now = datetime.now(timezone.utc)
            due = await db.scheduled_actions.find(
                {"enabled": True, "next_run_at": {"$ne": None, "$lte": _dt_iso(now)}}, {"_id": 0},
            ).to_list(200)
            for a in due:
                nxt = sa.next_run_after(a["schedule"], now)
                upd = {"next_run_at": _dt_iso(nxt)}
                if nxt is None:
                    upd["enabled"] = False  # one-off action: done
                claimed = await db.scheduled_actions.update_one({"id": a["id"], "next_run_at": a["next_run_at"]}, {"$set": upd})
                if claimed.modified_count:
                    await _execute_scheduled_action(a, scheduled_for=a["next_run_at"])
        except Exception:
            logger.exception("scheduled actions loop iteration failed")
        await asyncio.sleep(30)


# ============ SUGGERIMENTI "PER TE" (striscia sopra la chat, mobile) ============
_insights_running: set = set()


async def _generate_ai_insights(user: User, today_iso: str):
    """Once a day per user: up to 3 short suggestions linking what the user saved (notes,
    documents) with what's coming up (tasks, to-dos) or today's news. Cached in
    suggestions_ai; an empty result is cached too, so it runs at most once a day."""
    if user.user_id in _insights_running:
        return
    _insights_running.add(user.user_id)
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        notes = await db.kb_chunks.find({"user_id": user.user_id, "created_at": {"$gte": since}},
                                        {"_id": 0, "embedding": 0}).sort("created_at", -1).to_list(30)
        horizon = (datetime.now(LOCAL_TZ).date() + timedelta(days=14)).isoformat()
        tasks = await db.tasks.find({"$and": [_visible_query(user), {"due_date": {"$gte": today_iso, "$lte": horizon}},
                                              {"completed": {"$ne": True}}]}, {"_id": 0}).sort("due_date", 1).to_list(25)
        todos = await db.todos.find({"user_id": user.user_id, "status": {"$in": ["da_fare", "in_corso"]}}, {"_id": 0}).to_list(10)
        news = await db.news_items.find({"user_id": user.user_id, "date": today_iso}, {"_id": 0}).to_list(5)
        if not notes and not tasks:
            await db.suggestions_ai.update_one({"user_id": user.user_id}, {"$set": {"date": today_iso, "items": []}}, upsert=True)
            return
        lines = [f"OGGI: {_today_it_string()}", "NOTE E DOCUMENTI SALVATI (ultimi 30 giorni):"]
        lines += [f"- {retrieval._kb_display(n)[:300]}" for n in notes] or ["- nessuna"]
        lines.append("TASK IN ARRIVO (14 giorni):")
        lines += [f"- [id={t['id']}] {t.get('title')} · {t.get('due_date')} {t.get('due_time') or ''}" for t in tasks] or ["- nessuno"]
        lines.append("TO-DO APERTI:")
        lines += [f"- {t.get('title')}" for t in todos] or ["- nessuno"]
        if news:
            lines.append("NEWS DI OGGI:")
            lines += [f"- {n.get('title')}" for n in news]
        system = (
            "Sei mAIPAL, assistente personale. Guarda i dati dell'utente e proponi AL MASSIMO 3 suggerimenti brevi e "
            "concreti (max 110 caratteri ciascuno, in italiano, seconda persona) che COLLEGANO informazioni diverse e gli "
            "sono utili adesso: es. un task in arrivo e una nota che lo riguarda ('Domani chiami Marco: nell'ultima nota "
            "aspettava il preventivo'), una scadenza o un'informazione salvata da non dimenticare, una news collegata a "
            "un suo argomento. Usa SOLO i dati forniti, non inventare nulla; niente consigli generici o banali; se non c'è "
            "niente di davvero utile restituisci una lista vuota. Per ciascuno indica cosa succede al tocco: "
            "{\"type\": \"task\", \"id\": \"<id del task>\"} se riguarda un task elencato, altrimenti "
            "{\"type\": \"chat\", \"action\": \"info_request\", \"text\": \"<domanda breve da fare a mAIPAL per approfondire>\"}. "
            "Rispondi SOLO con JSON: {\"items\": [{\"text\": \"...\", \"target\": {...}}]}"
        )
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY, session_id=f"insights_{uuid.uuid4().hex[:8]}", system_message=system,
            user_id=user.user_id, feature="altro", channel="sistema", trigger="automatico", org_id=user.org_id,
        ).with_model("openai", "gpt-4o-mini")
        import json as _json, re as _re
        raw = await chat.send_message(UserMessage(text="\n".join(lines)[:12000]))
        m = _re.search(r"\{.*\}", raw or "", _re.DOTALL)
        parsed = _json.loads(m.group(0)) if m else {}
        task_ids = {t["id"] for t in tasks}
        items = []
        for i, it in enumerate((parsed.get("items") or [])[:3]):
            text = str((it or {}).get("text") or "").strip()
            tgt = (it or {}).get("target") or {}
            if not text:
                continue
            if tgt.get("type") == "task" and tgt.get("id") in task_ids:
                target = {"type": "task", "id": tgt["id"]}
            else:
                target = {"type": "chat", "action": "info_request", "text": str(tgt.get("text") or "")[:200]}
            items.append({"id": f"ai{i}", "kind": "insight", "text": text[:140], "target": target, "priority": 70 - i})
        await db.suggestions_ai.update_one({"user_id": user.user_id}, {"$set": {"date": today_iso, "items": items}}, upsert=True)
    except Exception:
        logger.exception("AI insights generation failed")
    finally:
        _insights_running.discard(user.user_id)


@api_router.get("/suggestions")
async def get_suggestions(current: User = Depends(get_current_user)):
    import suggestions as sg
    now_local = datetime.now(LOCAL_TZ)
    today = now_local.date()
    today_iso = today.isoformat()
    tasks = await db.tasks.find({"$and": [_visible_query(current), {"completed": {"$ne": True}}, {"due_date": {"$lte": (today + timedelta(days=1)).isoformat()}}]},
                                {"_id": 0, "id": 1, "title": 1, "due_date": 1, "due_time": 1, "completed": 1}).to_list(500)
    todos = await db.todos.find({"user_id": current.user_id, "status": {"$in": ["da_fare", "in_corso"]}},
                                {"_id": 0, "id": 1, "title": 1, "status": 1, "created_at": 1}).to_list(200)
    news = await db.news_items.find({"user_id": current.user_id, "date": today_iso}, {"_id": 0, "title": 1, "url": 1, "date": 1, "feedback": 1}).to_list(20)
    past_dates = []
    for y in (1, 2, 3):
        try:
            past_dates.append(today.replace(year=today.year - y).isoformat())
        except ValueError:
            pass
    journal_past = await db.journal_entries.find({"user_id": current.user_id, "date": {"$in": past_dates}},
                                                 {"_id": 0, "date": 1, "title": 1, "cleaned_text": 1}).to_list(5)
    actions = await db.scheduled_actions.find({"user_id": current.user_id, "enabled": True}, {"_id": 0, "title": 1, "enabled": 1, "next_run_at": 1}).to_list(50)
    items = sg.build_rule_suggestions(today, now_local, tasks, todos, news, journal_past, actions)

    cached = await db.suggestions_ai.find_one({"user_id": current.user_id}, {"_id": 0})
    if cached and cached.get("date") == today_iso:
        items += cached.get("items") or []
    else:
        asyncio.create_task(_generate_ai_insights(current, today_iso))  # ready on a later load
    items.sort(key=lambda s: -s.get("priority", 0))
    return {"items": sg.with_tips(items[:8], today)}


# ============ @AGENTI IN CHAT ============
# "...informazioni sul paziente... @task richiamare la padrona giovedì": the part before the
# first tag goes to the action selected in the chat, each tagged piece to that agent (see
# mentions.py), with the whole message as context. Results come back one per agent; list
# edits and scheduled actions that need a confirmation return it (never applied blindly).

AGENT_LABELS = {"task_todo": "Task", "info_upload": "Nota", "info_request": "Cerca", "journal": "Diario",
                "list_update": "Lista", "scheduled_action": "Azione"}


def _short_it_date(iso: Optional[str], time_s: Optional[str] = None) -> str:
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    s = f"{d.day} {sa.IT_MONTHS[d.month - 1][:3]}"
    return f"{s} {time_s}" if time_s else s


def _source_label(source: Optional[dict]) -> str:
    if not source:
        return ""
    when = _short_it_date((source.get("created_at") or "")[:10])
    return {"note": f"Nota del {when}", "journal": f"Diario del {_short_it_date(source.get('date'))}",
            "vet_report": f"Referto del {when}", "work_report": f"Report del {when}",
            "job_log": f"Diario commessa del {_short_it_date(source.get('date')) or when}"}.get(source.get("type"), f"Chat del {when}")


async def _agent_llm(user: User, action: str, text: str, feature: str, channel: str) -> tuple[str, Optional[dict]]:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY, session_id=f"agent_{action}_{uuid.uuid4().hex[:8]}",
        system_message=build_system_prompt(user, action),
        user_id=user.user_id, feature=feature, channel=channel, trigger="utente", org_id=user.org_id,
    ).with_model("openai", "gpt-4o")
    raw = await chat.send_message(UserMessage(text=text))
    visible, meta = _extract_meta(raw or "")
    return visible.replace("```json", "").replace("```", "").strip(), meta


async def _run_sub_agent(user: User, agent: str, piece: str, context: str, source: Optional[dict],
                         conv_id: str, channel: str = "web", docs: str = "") -> dict:
    """Runs one tagged piece; never raises - a failing agent reports its error and the
    others still run. `docs`: the text of the files attached in the conversation, so a
    piece like "aggiungi per domani le cose da fare nel file" can act on them."""
    base = {"agent": agent, "label": AGENT_LABELS.get(agent, agent)}
    ctx_block = (f"CONTESTO - il messaggio completo dell'utente, di cui questa richiesta fa parte:\n{context}\n\n"
                 if context and context.strip() != piece.strip() else "")
    docs_block = (f"DOCUMENTI ALLEGATI IN QUESTA CONVERSAZIONE (testo completo):\n{docs}\n\n" if docs else "")
    try:
        if agent == "task_todo":
            kb_block = ""
            if not docs:
                # "le cose da fare nel file" in a new chat: look the file up in the knowledge base
                hits = await retrieve_kb(user.user_id, f"{piece}\n{context or ''}"[:1000], scope="kb", org_id=user.org_id)
                if hits:
                    kb_block = "CONTESTO KB PERSONALE:\n" + "\n\n".join(f"- {h.get('display') or h.get('text', '')}" for h in hits) + "\n\n"
            prompt = (docs_block + kb_block + ctx_block + "Usa il contesto per rendere il task completo e specifico: nel titolo i nomi giusti "
                      "(persona, paziente, cliente...), in 'notes' i dettagli utili per svolgerlo presi dal contesto "
                      "(senza inventare nulla). Se la richiesta si riferisce a un file o documento (\"le cose da fare "
                      "nel file\", \"gli impegni del documento\"), leggi il documento e crea un task SEPARATO per ogni "
                      "voce pertinente (lista \"tasks\" nel META), con la data e l'ora indicate nella richiesta; non "
                      "dire mai che non hai accesso ai documenti quando il loro testo è qui sopra."
                      "\n\nRICHIESTA PER IL TASK:\n" + piece)
            visible, meta = await _agent_llm(user, "task_todo", prompt, "creazione_task", channel)
            items = meta.get("tasks") if meta and isinstance(meta.get("tasks"), list) else ([meta] if meta else [])
            created = []
            for it in items:
                if isinstance(it, dict) and it.get("title"):
                    doc = await _create_task_or_todo(user.user_id, it, conv_id, default_reminder_enabled=(channel == "telegram"))
                    if doc:
                        created.append(doc)
            if not created:
                return {**base, "status": "error", "message": visible or "Non ho capito che task creare."}
            if source:
                src = {**source, "label": _source_label(source)}
                for d in created:
                    coll = db.tasks if d["id"].startswith("task_") else db.todos
                    await coll.update_one({"id": d["id"]}, {"$set": {"source": src}})
                if source.get("type") == "note" and source.get("doc_id"):
                    await db.kb_documents.update_one({"doc_id": source["doc_id"]}, {"$push": {"linked": {"$each": [
                        {"type": "task" if d["id"].startswith("task_") else "todo", "id": d["id"], "title": d.get("title")} for d in created]}}})
            lines = []
            for d in created:
                if d["id"].startswith("task_"):
                    when = _short_it_date(d.get("due_date"), d.get("due_time"))
                    lines.append(f"📌 Task creato: «{d.get('title')}»" + (f" · {when}" if when else ""))
                else:
                    lines.append(f"✅ To-Do creato: «{d.get('title')}»")
                if d.get("notes"):
                    lines.append(f"   Note: {d['notes'][:200]}")
            return {**base, "status": "ok", "message": "\n".join(lines),
                    "task_id": created[0]["id"] if created[0]["id"].startswith("task_") else None}

        if agent == "journal" and user.business_vertical == "artigiano":
            # the artigiano's diary is the diario di commessa; the commessa of what was just
            # done (a report, an entry) is the one meant when the piece names none
            hint = None
            if source and source.get("type") == "work_report" and source.get("id"):
                rep_doc = await db.work_reports.find_one({"id": source["id"]}, {"_id": 0, "commessa_id": 1})
                hint = (rep_doc or {}).get("commessa_id")
            elif source and source.get("type") == "job_log":
                hint = source.get("commessa_id")
            res = await _save_job_log(user, piece, hint_commessa_id=hint, conv_id=conv_id, channel=channel)
            if res["status"] == "ok":
                return {**base, "label": "Diario commessa", "status": "ok", "message": res["message"],
                        "commessa_id": res["log"]["commessa_id"]}
            if res["status"] == "planned":
                return {**base, "label": "Diario commessa", "status": "ok", "message": res["message"], "commessa_id": res["commessa"]["id"]}
            if res["status"] == "material_doubt":
                return {**base, "label": "Diario commessa", "status": "error",
                        "message": f"Non l'ho salvato: {res['message']} Riscrivilo dicendo «usati» o «da prendere»."}
            if res["status"] in ("question", "unclear", "invalid"):
                return {**base, "label": "Diario commessa", "status": "error", "message": res["message"]}
            opts = "; ".join(f"«{c['title']}» ({c['client_name']})" for c in res.get("candidates") or [])
            return {**base, "label": "Diario commessa", "status": "error",
                    "message": f"Non l'ho salvato: {res['message']}" + (f" Commesse aperte: {opts}." if opts else "")
                               + " Riscrivilo nominando il cliente o la commessa."}

        if agent == "journal":
            visible, meta = await _agent_llm(user, "journal", piece, "diario", channel)
            jr = await _save_journal_entry(user.user_id, _resolve_journal_date(meta), piece, visible or piece, meta, conv_id)
            return {**base, "status": "ok", "message": f"📔 Aggiunto al diario del {_short_it_date(jr.get('date'))}."}

        if agent == "info_upload":
            # "@salva elimina il latte" right after reading the shopping list is a list edit,
            # not a note to save (it used to be saved as a note, with "fatto" as the answer)
            names = [c["name"] for c in await db.collections.find(_lists_query(user), {"_id": 0, "name": 1}).to_list(200)]
            conv_ctx = ""
            if names and conv_id:
                conv = await db.conversations.find_one({"conv_id": conv_id, "user_id": user.user_id}, {"_id": 0, "messages": 1})
                conv_ctx = "\n".join(f"{'Utente' if m.get('role') == 'user' else 'Assistente'}: {(m.get('content') or '')[:600]}"
                                      for m in ((conv or {}).get("messages") or [])[-4:])
            kind = await lu.classify_save_intent(piece, names, user_id=user.user_id, channel=channel, context=conv_ctx) if names else "info_upload"
            if kind == "list_create" or (kind == "list_update" and not lu.looks_like_note(piece)):
                agent = "list_update"
                base = {**base, "agent": "list_update", "label": AGENT_LABELS.get("list_update", "Lista")}
                if conv_ctx:
                    context = f"{context}\n\nConversazione precedente:\n{conv_ctx}" if context else f"Conversazione precedente:\n{conv_ctx}"
        if agent == "info_upload":
            try:
                e = await emb.embed_texts([piece])
                embedding = e[0] if e else None
            except Exception:
                embedding = None
            doc_id = f"doc_{uuid.uuid4().hex[:12]}"
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.kb_chunks.insert_one({
                "chunk_id": f"kb_{uuid.uuid4().hex[:12]}", "user_id": user.user_id, "text": piece, "title": piece[:60],
                "tags": [], "summary": piece[:140], "embedding": embedding, "doc_id": doc_id, "source_type": "chat",
                "chunk_index": 0, "conv_id": conv_id, "created_at": now_iso,
            })
            await db.kb_documents.insert_one({
                "doc_id": doc_id, "user_id": user.user_id, "name": piece[:60] + ("…" if len(piece) > 60 else ""),
                "ext": "chat", "source_type": "chat", "category": "note", "keywords": [], "chunks_count": 1,
                "chars": len(piece), "size_bytes": len(piece.encode("utf-8")), "preview": piece[:280], "drive_link": None,
                "created_at": now_iso, "conv_id": conv_id,
            })
            ut.fire_and_forget_feature_event(user_id=user.user_id, feature="caricamento_informazioni", channel=channel, trigger="utente", org_id=user.org_id)
            return {**base, "status": "ok", "message": "💾 Informazione salvata."}

        if agent == "info_request":
            hits = await retrieve_kb(user.user_id, piece, scope="all", org_id=user.org_id)
            ctx = "\n\n".join(f"- {h.get('display') or h.get('text', '')}" for h in hits)
            text = docs_block + ((f"CONTESTO KB PERSONALE:\n{ctx}\n\nDOMANDA:\n{piece}") if ctx else piece)
            visible, _ = await _agent_llm(user, "info_request", text, "ricerca_informazioni", channel)
            return {**base, "status": "ok", "message": f"🔍 {visible}"}

        if agent == "list_update":
            import re as _re
            if _re.search(r"\b(crea|creami|crei|fai|fammi|nuova|apri)\b", piece, _re.I):
                names = [c["name"] for c in await db.collections.find(_lists_query(user), {"_id": 0, "name": 1}).to_list(200)]
                if await lu.classify_save_intent(piece, names, user_id=user.user_id, channel=channel) == "list_create":
                    res = await _create_list_from_text(user, piece + (f"\n\n{docs[:4000]}" if docs else ""), channel=channel)
                    return {**base, "status": res["status"], "message": ("📋 " if res["status"] == "ok" else "⚠️ ") + res["message"]}
            text = piece + (f"\n\n(Contesto del messaggio, per capire a chi o cosa si riferisce: {context[:2400]})"
                            if context and context.strip() != piece.strip() else "")
            if docs:
                text += f"\n\n(Testo dei file allegati nella conversazione, se la richiesta vi si riferisce: {docs[:4000]})"
            try:
                res = await _execute_list_update(user, text, channel=channel)
            except HTTPException as he:
                return {**base, "status": "error", "message": f"⚠️ {he.detail}"}
            if res.get("status") == "ok":
                return {**base, "status": "ok", "message": f"📋 {res.get('message')}"}
            # ambiguity or a confirmation (e.g. "svuota") - shown with its buttons, applied only on a tap
            prompt = {"ambiguous_list": "In quale lista?", "ambiguous_item": "Ho trovato più corrispondenze, quale intendi?",
                      "ambiguous_sub_item": "Ho trovato più corrispondenze, quale intendi?"}.get(res.get("status"))
            msg = prompt or (f"⚠️ {res.get('message')}" if res.get("message") else "⚠️ Prima di modificare la lista serve una tua conferma:")
            return {**base, "status": "pending", "message": msg, "list_result": res}

        if agent == "scheduled_action":
            res = await _build_scheduled_draft(user, piece, channel=channel)
            if res.get("status") != "confirm":
                return {**base, "status": "error", "message": f"⚠️ {res.get('message')}"}
            ask = "Confermi?" if (res["draft"].get("schedule") or {}).get("freq") == "now" else "La attivo?"
            return {**base, "status": "pending", "message": f"🔁 Ho capito così:\n\n{res['preview']}\n\n{ask}", "draft": res["draft"]}
    except Exception as e:
        logger.exception(f"sub-agent {agent} failed")
        return {**base, "status": "error", "message": f"⚠️ {getattr(e, 'detail', None) or 'non sono riuscito a completare questa parte'}"}
    return {**base, "status": "error", "message": "Agente sconosciuto."}


async def _share_kb_docs(sender: User, recipients: List[dict], doc_ids: List[str]) -> dict:
    """Copies the sender's saved note/documents into each recipient's knowledge base, marked
    "condivisa da <sender>" (search shows it that way), and lets them know on Telegram."""
    doc_ids = [d for d in dict.fromkeys(doc_ids) if d]
    chunks = await db.kb_chunks.find({"user_id": sender.user_id, "doc_id": {"$in": doc_ids}}, {"_id": 0}).to_list(500)
    docs = await db.kb_documents.find({"user_id": sender.user_id, "doc_id": {"$in": doc_ids}}, {"_id": 0}).to_list(50)
    if not chunks:
        return {"agent": "share", "label": "Condivisione", "status": "error", "message": "⚠️ Non ho trovato l'informazione da condividere."}
    by = {"user_id": sender.user_id, "name": sender.name}
    now_iso = datetime.now(timezone.utc).isoformat()
    preview = next((c.get("raw_text") or c.get("text") or "" for c in chunks if c.get("doc_id") == doc_ids[0]), "")[:400]
    for r in recipients:
        idmap = {d: f"doc_{uuid.uuid4().hex[:12]}" for d in doc_ids}
        await db.kb_chunks.insert_many([{
            **{k: v for k, v in c.items() if k not in ("conv_id",)},
            "chunk_id": f"kb_{uuid.uuid4().hex[:12]}", "user_id": r["user_id"], "doc_id": idmap[c["doc_id"]],
            "shared_by": by, "shared_from": {"user_id": sender.user_id, "doc_id": c["doc_id"]}, "created_at": now_iso,
        } for c in chunks])
        if docs:
            await db.kb_documents.insert_many([{
                **{k: v for k, v in d.items() if k not in ("conv_id", "linked", "shared_with")},
                "doc_id": idmap[d["doc_id"]], "user_id": r["user_id"], "shared_by": by, "created_at": now_iso,
            } for d in docs])
        if r.get("telegram_chat_id"):
            try:
                await _send_telegram_text(r["telegram_chat_id"], f"📥 {sender.name} ti ha condiviso un'informazione su mAIPAL:\n\n{preview}")
            except Exception:
                logger.exception("share telegram notice failed")
    await db.kb_documents.update_many({"user_id": sender.user_id, "doc_id": {"$in": doc_ids}},
                                      {"$addToSet": {"shared_with": {"$each": [{"user_id": r["user_id"], "name": r.get("name")} for r in recipients]}}})
    names = [r.get("name") or "un membro del team" for r in recipients]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]
    return {"agent": "share", "label": "Condivisione", "status": "ok",
            "message": f"👥 Condivisa con {who}: la trovano anche nella loro base di conoscenza, con il tuo nome."}


class AgentDispatchPayload(BaseModel):
    text: str                          # the whole typed message, tags included
    source: Optional[dict] = None      # what the main action produced, e.g. {"type": "vet_report", "id": ...}


@api_router.post("/agents/dispatch")
async def dispatch_agents(payload: AgentDispatchPayload, current: User = Depends(get_current_user)):
    """The tagged pieces of a message whose main action does not go through /chat/stream
    (report visita, azioni programmate, modifica lista): run after the main one."""
    main, parts = mn.split_mentions(payload.text)
    source = payload.source if isinstance(payload.source, dict) else None
    if source is not None:
        source = {k: v for k, v in source.items() if k in ("type", "id", "doc_id", "conv_id", "date", "created_at", "preview")}
        source.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    results = []
    for p in parts[:6]:
        results.append(await _run_sub_agent(current, p["agent"], p["text"], payload.text, source, conv_id=f"agents_{uuid.uuid4().hex[:8]}"))
    return {"main": main, "results": results}


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
    # ===== Organizations: every account already in gets one (see _migrate_tenants) =====
    try:
        await _migrate_tenants()
    except Exception:
        logger.exception("organizations migration failed")
    try:   # the diario di commessa is read by commessa and day (page, chat, totals)
        await db.job_logs.create_index([("commessa_id", 1), ("date", -1)])
        await db.job_logs.create_index([("user_id", 1), ("date", -1)])
        await db.job_logs.create_index([("org_id", 1), ("date", -1)])
        await db.job_photos.create_index([("log_id", 1)])
        await db.job_photos.create_index([("commessa_id", 1)])
        await db.job_todos.create_index([("commessa_id", 1)])
        await db.job_milestones.create_index([("commessa_id", 1)])
        await db.job_contacts.create_index([("commessa_id", 1)])
        await db.job_contacts.create_index([("collection_id", 1)])
        await db.job_milestones.create_index([("done", 1), ("due_date", 1)])
        await db.job_economics.create_index([("commessa_id", 1)], unique=True)
        await db.delete_codes.create_index([("user_id", 1)])
        await db.push_subscriptions.create_index([("user_id", 1)])
        await db.push_subscriptions.create_index([("endpoint", 1)])
        await db.collaborators.create_index([("telegram_chat_id", 1)])
        await db.work_sessions.create_index([("collaborator_id", 1), ("end_at", 1)])
        await db.work_sessions.create_index([("commessa_id", 1), ("end_at", 1)])
        await db.collaborators.create_index([("code", 1)])
        await db.collaborators.create_index([("owner_user_id", 1)])
        await db.work_reports.create_index([("commessa_id", 1)])
    except Exception:
        logger.exception("job diary indexes failed")
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
        asyncio.create_task(_collab_reminder_loop())
    except Exception:
        logger.exception("failed to start collaborator reminder loop")
    try:
        asyncio.create_task(_daily_news_loop())
    except Exception:
        logger.exception("failed to start daily news loop")
    try:
        asyncio.create_task(_news_cleanup_loop())
    except Exception:
        logger.exception("failed to start news cleanup loop")
    try:
        asyncio.create_task(_usage_aggregation_loop())
    except Exception:
        logger.exception("failed to start usage aggregation loop")
    try:
        asyncio.create_task(_scheduled_actions_loop())
    except Exception:
        logger.exception("failed to start scheduled actions loop")
    try:
        asyncio.create_task(_task_series_loop())
    except Exception:
        logger.exception("failed to start task series loop")
    try:
        asyncio.create_task(_conversation_cleanup_loop())
    except Exception:
        logger.exception("failed to start conversation cleanup loop")


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


async def _exact_reminders_tick(now: Optional[datetime] = None) -> None:
    """Every minute: for tasks with reminder_enabled=True and reminder_msg_sent!=True,
    fire a Telegram message at (due_date + due_time - reminder_offset_minutes); offset
    defaults to 15 minutes when the user hasn't specified one. due_date/due_time are the
    wall-clock values the user typed, in Europe/Rome local time - converted to UTC here
    before comparing to now(), otherwise the reminder fires 1-2h later than intended."""
    now = now or datetime.now(timezone.utc)
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
        minutes_left = max(0, round((due_dt - now).total_seconds() / 60))
        # the app's notification on the user's devices, also with the app closed - once for this
        # time (a Telegram retry next minute doesn't repeat it; a snoozed/moved task does)
        if t.get("reminder_push_for") != fire_at.isoformat():
            await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_push_for": fire_at.isoformat()}})
            try:
                await push.send_to_user(db, t["user_id"], f"🔔 {t.get('title') or 'Promemoria'}",
                                        (f"Tra {minutes_left} minuti" if minutes_left else "Adesso") + f" ({due_time})"
                                        + (f" · {t['notes']}" if t.get("notes") else ""), "/dashboard/tasks", f"task-{t['id']}")
            except Exception:
                logger.exception("task reminder push failed")
        if not user or not user.get("telegram_chat_id"):
            await db.tasks.update_one({"id": t["id"]}, {"$set": {"reminder_msg_sent": True, "reminder_msg_sent_at": datetime.now(timezone.utc).isoformat()}})
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


async def _exact_reminders_loop():
    while True:
        try:
            await _exact_reminders_tick()
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
    future searches can be steered toward (or away from) them. Disliked news are deleted
    after NEWS_KEEP_DAYS (see _cleanup_old_news): their votes live on in news_source_feedback."""
    scores = {}
    async for row in db.news_source_feedback.find({"user_id": user_id}, {"_id": 0}):
        scores[row["source"]] = scores.get(row["source"], 0) - (row.get("dislikes") or 0)
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


NEWS_KEEP_DAYS = 5


async def _remember_disliked_sources(q: dict):
    """Before deleting news: their thumbs-down are kept per source (news_source_feedback),
    so the next searches still avoid those sources."""
    disliked = await db.news_items.find({**q, "feedback": "dislike", "source": {"$nin": [None, ""]}},
                                        {"_id": 0, "user_id": 1, "source": 1}).to_list(100000)
    counts: dict = {}
    for d in disliked:
        key = (d["user_id"], d["source"])
        counts[key] = counts.get(key, 0) + 1
    for (user_id, source), n in counts.items():
        await db.news_source_feedback.update_one({"user_id": user_id, "source": source},
                                                 {"$inc": {"dislikes": n}}, upsert=True)


async def _cleanup_old_news() -> int:
    """News the user didn't give a thumbs up to go away NEWS_KEEP_DAYS days after they
    arrived; the liked ones stay. A thumbs down is still remembered (per source) so the
    next searches keep avoiding that source."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=NEWS_KEEP_DAYS)).isoformat()
    q = {"created_at": {"$lt": cutoff}, "feedback": {"$ne": "like"}}
    await _remember_disliked_sources(q)
    res = await db.news_items.delete_many(q)
    if res.deleted_count:
        logger.info(f"news cleanup: {res.deleted_count} news older than {NEWS_KEEP_DAYS} days without a like deleted")
    return res.deleted_count


async def _news_cleanup_loop():
    """Every 6 hours (and shortly after start-up)."""
    await asyncio.sleep(90)
    while True:
        try:
            await _cleanup_old_news()
        except Exception:
            logger.exception("news cleanup failed")
        await asyncio.sleep(6 * 3600)


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
