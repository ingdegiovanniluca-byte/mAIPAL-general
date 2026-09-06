from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import httpx
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any
from datetime import datetime, timezone, timedelta

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')

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
    created_at: Optional[str] = None


class OnboardingPayload(BaseModel):
    profession: Optional[str] = ""
    sector: Optional[str] = ""
    verticals: List[str] = []
    interests: List[str] = []
    tone: Optional[str] = "informale"


class ChatRequest(BaseModel):
    action: Literal["info_upload", "info_request", "task_todo"]
    content: str
    filters: Optional[dict] = None


class Task(BaseModel):
    id: str
    user_id: str
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


# ============ AUTH ROUTES ============
@api_router.post("/auth/session")
async def process_session(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    async with httpx.AsyncClient() as hc:
        r = await hc.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": session_id},
            timeout=15.0,
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Auth failed")
    data = r.json()

    email = data["email"]
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": data.get("name"), "picture": data.get("picture")}},
        )
        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": data.get("name", ""),
            "picture": data.get("picture"),
            "onboarded": False,
            "profession": None,
            "sector": None,
            "verticals": [],
            "interests": [],
            "tone": "informale",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(user_doc)

    session_token = data["session_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc),
    })

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7 * 24 * 60 * 60,
    )
    return {"user": User(**user_doc).model_dump()}


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
            "onboarded": True,
        }},
    )
    user_doc = await db.users.find_one({"user_id": current.user_id}, {"_id": 0})
    return User(**user_doc)


# ============ LLM / CHAT ============
def build_system_prompt(user: User, action: str) -> str:
    verticals = ", ".join(user.verticals) if user.verticals else "generico"
    interests = ", ".join(user.interests) if user.interests else "n/d"
    user_name = user.name or "l'utente"
    base = (
        f"Sei mAIPAL, un assistente personale AI (segretario digitale) per {user_name}. "
        f"Profilo: professione '{user.profession or 'n/d'}', settore '{user.sector or 'n/d'}', "
        f"verticali d'uso: {verticals}, interessi: {interests}. "
        f"Tono di comunicazione: {user.tone or 'informale'}. "
        "Rispondi sempre in italiano, in modo chiaro e conciso."
    )
    if action == "info_upload":
        base += (
            " L'utente sta caricando un'informazione da salvare nella sua knowledge base personale. "
            "Rispondi confermando cosa hai memorizzato, estrai un titolo breve, tag (2-4 parole chiave) e una sintesi. "
            "Termina con un JSON in un blocco ```json``` con chiavi: title, summary, tags (array)."
        )
    elif action == "info_request":
        base += (
            " L'utente ti sta ponendo una domanda. "
            "Se ti viene fornito un CONTESTO dalla knowledge base, usalo come fonte principale e cita testualmente "
            "gli spunti rilevanti. Se il contesto è vuoto o non pertinente, indicalo esplicitamente e rispondi "
            "con le tue conoscenze generali dichiarando che è una risposta senza fonti dalla KB personale."
        )
    elif action == "task_todo":
        base += (
            " L'utente vuole salvare un task o un to-do. Estrai i seguenti campi e restituisci SOLO un blocco ```json``` "
            "con: type ('task' se c'è una data di scadenza esplicita o implicita, altrimenti 'todo'), title (breve), "
            "description, due_date (ISO YYYY-MM-DD o null), priority ('alta'|'media'|'bassa'), tags (array), notes. "
            "Prima del JSON, scrivi una breve conferma in linguaggio naturale (1-2 frasi)."
        )
    return base


async def retrieve_kb(user_id: str, query: str, limit: int = 4) -> List[dict]:
    # simple keyword-based retrieval on knowledge chunks
    terms = [t for t in query.lower().split() if len(t) > 2][:6]
    if not terms:
        return []
    regex = "|".join([t for t in terms])
    cursor = db.kb_chunks.find(
        {"user_id": user_id, "text": {"$regex": regex, "$options": "i"}},
        {"_id": 0},
    ).limit(limit)
    return await cursor.to_list(limit)


@api_router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, current: User = Depends(get_current_user)):
    conv_id = f"conv_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    kb_context = []
    if payload.action == "info_request":
        kb_context = await retrieve_kb(current.user_id, payload.content)

    user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    await db.conversations.insert_one({
        "conv_id": conv_id,
        "user_id": current.user_id,
        "action": payload.action,
        "created_at": now,
        "user_message": payload.content,
        "user_message_id": user_msg_id,
        "filters": payload.filters or {},
        "pipeline": {
            "claude": "ok",
            "n8n": "skip",
            "mongodb": "ok",
        },
    })

    system = build_system_prompt(current, payload.action)
    user_text = payload.content
    if kb_context:
        ctx = "\n\n".join([f"- {c.get('text','')[:400]}" for c in kb_context])
        user_text = f"CONTESTO KB PERSONALE:\n{ctx}\n\nDOMANDA:\n{payload.content}"

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=conv_id,
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-5")

    import json as _json
    async def event_gen():
        full = []
        try:
            async for ev in chat.stream_message(UserMessage(text=user_text)):
                if isinstance(ev, TextDelta):
                    full.append(ev.content)
                    yield _json.dumps({"type": "delta", "content": ev.content}) + "\n"
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            logger.exception("LLM stream error")
            yield _json.dumps({"type": "error", "content": str(e)}) + "\n"

        answer = "".join(full)
        # persist answer
        await db.conversations.update_one(
            {"conv_id": conv_id},
            {"$set": {"agent_response": answer, "completed_at": datetime.now(timezone.utc).isoformat()}},
        )

        # side-effects based on action
        if payload.action == "info_upload":
            chunk = {
                "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
                "user_id": current.user_id,
                "text": payload.content,
                "summary": answer,
                "conv_id": conv_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.kb_chunks.insert_one(chunk)
        elif payload.action == "task_todo":
            parsed = _parse_task_json(answer)
            if parsed:
                await _create_task_or_todo(current.user_id, parsed, conv_id)

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
    t_type = parsed.get("type", "todo")
    if t_type == "task" and parsed.get("due_date"):
        doc = {
            "id": f"task_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": parsed.get("title", "Nuovo task"),
            "description": parsed.get("description", ""),
            "due_date": parsed.get("due_date"),
            "priority": parsed.get("priority", "media"),
            "tags": parsed.get("tags", []),
            "notes": parsed.get("notes", ""),
            "calendar_synced": False,
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
async def list_conversations(current: User = Depends(get_current_user), action: Optional[str] = None):
    q = {"user_id": current.user_id}
    if action and action != "all":
        q["action"] = action
    cursor = db.conversations.find(q, {"_id": 0}).sort("created_at", -1).limit(100)
    return await cursor.to_list(100)


# ============ TASKS ============
@api_router.get("/tasks")
async def list_tasks(current: User = Depends(get_current_user)):
    cursor = db.tasks.find({"user_id": current.user_id}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(500)


@api_router.post("/tasks")
async def create_task(payload: TaskUpsert, current: User = Depends(get_current_user)):
    doc = {
        "id": f"task_{uuid.uuid4().hex[:12]}",
        "user_id": current.user_id,
        **payload.model_dump(),
        "calendar_synced": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.tasks.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/tasks/{task_id}")
async def update_task(task_id: str, payload: dict, current: User = Depends(get_current_user)):
    payload.pop("id", None); payload.pop("user_id", None); payload.pop("_id", None)
    await db.tasks.update_one({"id": task_id, "user_id": current.user_id}, {"$set": payload})
    doc = await db.tasks.find_one({"id": task_id, "user_id": current.user_id}, {"_id": 0})
    return doc


@api_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current: User = Depends(get_current_user)):
    await db.tasks.delete_one({"id": task_id, "user_id": current.user_id})
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


# ============ CONTEXTUAL CHAT (per task/todo) ============
class ContextChatRequest(BaseModel):
    message: str


@api_router.post("/tasks/{task_id}/chat")
async def task_chat(task_id: str, payload: ContextChatRequest, current: User = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id, "user_id": current.user_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    system = (
        f"Sei mAIPAL. L'utente sta modificando il task: {task}. "
        "Aggiorna il task in base alla richiesta e restituisci un breve messaggio di conferma, "
        "seguito da un blocco ```json``` con le SOLE chiavi da aggiornare tra: title, description, due_date, priority, tags, notes."
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"task_{task_id}", system_message=system).with_model("anthropic", "claude-sonnet-5")
    answer = await chat.send_message(UserMessage(text=payload.message))
    updates = _parse_task_json(answer) or {}
    if updates:
        await db.tasks.update_one({"id": task_id, "user_id": current.user_id}, {"$set": updates})
    updated = await db.tasks.find_one({"id": task_id, "user_id": current.user_id}, {"_id": 0})
    return {"answer": answer, "task": updated}


@api_router.post("/todos/{todo_id}/chat")
async def todo_chat(todo_id: str, payload: ContextChatRequest, current: User = Depends(get_current_user)):
    todo = await db.todos.find_one({"id": todo_id, "user_id": current.user_id}, {"_id": 0})
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    system = (
        f"Sei mAIPAL. L'utente sta modificando il to-do: {todo}. "
        "Aggiorna il to-do e restituisci un breve messaggio di conferma seguito da un blocco ```json``` con "
        "le SOLE chiavi da aggiornare tra: title, description, status ('da_fare'|'in_corso'|'fatto'), completion_percent, priority, tags, notes."
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"todo_{todo_id}", system_message=system).with_model("anthropic", "claude-sonnet-5")
    answer = await chat.send_message(UserMessage(text=payload.message))
    updates = _parse_task_json(answer) or {}
    if updates:
        await db.todos.update_one({"id": todo_id, "user_id": current.user_id}, {"$set": updates})
    updated = await db.todos.find_one({"id": todo_id, "user_id": current.user_id}, {"_id": 0})
    return {"answer": answer, "todo": updated}


@api_router.get("/")
async def root():
    return {"message": "mAIPAL API"}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
