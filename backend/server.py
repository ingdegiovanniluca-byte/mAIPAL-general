from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header, UploadFile, File
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

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
from emergentintegrations.llm.openai.speech_to_text import OpenAISpeechToText

import google_integration as gi
import telegram_bot as tg
import embeddings as emb

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
    home_address: Optional[str] = None
    work_address: Optional[str] = None
    created_at: Optional[str] = None
    telegram_chat_id: Optional[int] = None


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
    action: Literal["info_upload", "info_request", "task_todo"]
    content: str
    filters: Optional[dict] = None
    conv_id: Optional[str] = None


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


# ============ LLM / CHAT ============
def build_system_prompt(user: User, action: str) -> str:
    verticals = ", ".join(user.verticals) if user.verticals else "generico"
    interests = ", ".join(user.interests) if user.interests else "n/d"
    user_name = user.name or "l'utente"
    addr_parts = []
    if user.home_address: addr_parts.append(f"indirizzo casa: {user.home_address}")
    if user.work_address: addr_parts.append(f"indirizzo lavoro: {user.work_address}")
    addr = "; ".join(addr_parts)
    base = (
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
            "Poi in coda, ma solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"...\", \"summary\": \"...\", \"tags\": [\"...\"]}<<<END>>>"
        )
    elif action == "info_request":
        base += (
            " L'utente ti sta ponendo una domanda. Se ti viene fornito un CONTESTO dalla knowledge base personale, "
            "usalo come fonte principale e rispondi in modo naturale (senza dire 'ecco il contesto', 'dal database'; parla come un assistente). "
            "Se il contesto è vuoto o non pertinente, indica gentilmente che non hai fonti dalla KB personale e rispondi con le tue conoscenze generali."
        )
    elif action == "task_todo":
        base += (
            " L'utente vuole salvare un task o un to-do. Scrivi UNA risposta di conferma naturale (1-2 frasi, es. "
            "'Perfetto, ho preso nota: ti ricorderò di chiamare Marco domani alle 15:30.'). "
            "Poi in coda, solo per il sistema, aggiungi: "
            "<<<META>>>{\"title\": \"breve\", \"description\": \"\", "
            "\"due_date\": \"YYYY-MM-DD o null\", \"due_time\": \"HH:MM o null\", "
            "\"priority\": \"alta|media|bassa\", \"tags\": [\"...\"], \"notes\": \"\"}<<<END>>>. "
            "REGOLA: se rilevi una data (anche implicita: 'domani', 'lunedì', 'tra 3 giorni'), imposta due_date. "
            "Se rilevi un'ora, imposta due_time. Il sistema salva come TASK se due_date è presente, altrimenti come TO-DO."
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


async def retrieve_kb(user_id: str, query: str, limit: int = 4) -> List[dict]:
    """Semantic retrieval over kb_chunks using local multilingual embeddings + cosine similarity."""
    try:
        q_emb = await emb.embed_query(query)
    except Exception as e:
        logger.exception("embed_query failed, falling back to regex")
        q_emb = None

    # If we have an embedding, score all user's chunks; if no embedding is stored (legacy), score 0
    if q_emb is not None:
        cursor = db.kb_chunks.find({"user_id": user_id}, {"_id": 0})
        chunks = await cursor.to_list(1000)
        # Backfill missing embeddings lazily
        to_embed = [(i, c) for i, c in enumerate(chunks) if not c.get("embedding")]
        if to_embed:
            texts = [c["text"] for _, c in to_embed]
            try:
                new_embs = await emb.embed_texts(texts)
                for (i, c), e in zip(to_embed, new_embs):
                    chunks[i]["embedding"] = e
                    await db.kb_chunks.update_one({"chunk_id": c["chunk_id"]}, {"$set": {"embedding": e}})
            except Exception:
                logger.exception("backfill embeddings failed")
        scored = []
        for c in chunks:
            e = c.get("embedding")
            if not e: continue
            scored.append((emb.cosine(q_emb, e), c))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Only keep chunks with reasonable similarity
        top = [c for s, c in scored[:limit] if s >= 0.35]
        return top

    # Fallback keyword
    terms = [t for t in query.lower().split() if len(t) > 2][:6]
    if not terms:
        return []
    regex = "|".join(terms)
    cursor = db.kb_chunks.find({"user_id": user_id, "text": {"$regex": regex, "$options": "i"}}, {"_id": 0}).limit(limit)
    return await cursor.to_list(limit)


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

    # RAG context only on first turn of info_request
    kb_context = []
    if action == "info_request" and not prior_messages:
        kb_context = await retrieve_kb(current.user_id, payload.content)

    system = build_system_prompt(current, action)
    user_text = payload.content
    if kb_context:
        ctx = "\n\n".join([f"- {c.get('text','')[:400]}" for c in kb_context])
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
        await db.conversations.update_one(
            {"conv_id": conv_id},
            {
                "$push": {"messages": {"role": "assistant", "content": visible_answer, "ts": completed_at}},
                "$set": {"agent_response": visible_answer, "meta": meta or {}, "completed_at": completed_at},
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
                await db.kb_chunks.insert_one({
                    "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
                    "user_id": current.user_id,
                    "text": payload.content,
                    "title": (meta or {}).get("title") if meta else None,
                    "tags": (meta or {}).get("tags", []) if meta else [],
                    "summary": (meta or {}).get("summary") if meta else visible_answer,
                    "embedding": embedding,
                    "conv_id": conv_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            elif action == "task_todo":
                if meta:
                    await _create_task_or_todo(current.user_id, meta, conv_id)

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
    if due_date:
        doc = {
            "id": f"task_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": parsed.get("title", "Nuovo task"),
            "description": parsed.get("description", ""),
            "due_date": due_date,
            "due_time": due_time,
            "priority": parsed.get("priority", "media"),
            "tags": parsed.get("tags", []),
            "notes": parsed.get("notes", ""),
            "calendar_synced": False,
            "reminder_sent": False,
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
    existing = await db.tasks.find_one({"id": task_id, "user_id": current.user_id}, {"_id": 0})
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

    await db.tasks.update_one({"id": task_id, "user_id": current.user_id}, {"$set": payload})
    doc = await db.tasks.find_one({"id": task_id, "user_id": current.user_id}, {"_id": 0})
    return doc


@api_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current: User = Depends(get_current_user)):
    existing = await db.tasks.find_one({"id": task_id, "user_id": current.user_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    if existing.get("calendar_event_id"):
        try:
            creds = await gi.get_credentials(db, current.user_id)
            if creds:
                await gi.delete_calendar_event(creds, existing["calendar_event_id"])
        except Exception:
            logger.exception("failed removing calendar event on delete")
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
        "Rispondi in modo naturale (1-2 frasi) con la conferma della modifica. "
        "In coda includi SOLO per il sistema i campi da aggiornare tra i marcatori "
        "<<<META>>>{...}<<<END>>>, chiavi ammesse: title, description, due_date, due_time, priority, tags, notes."
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"task_{task_id}", system_message=system).with_model("anthropic", "claude-sonnet-5")
    raw = await chat.send_message(UserMessage(text=payload.message))
    visible, meta = _extract_meta(raw)
    visible = visible.replace("```json", "").replace("```", "").strip()
    if meta:
        await db.tasks.update_one({"id": task_id, "user_id": current.user_id}, {"$set": meta})
    updated = await db.tasks.find_one({"id": task_id, "user_id": current.user_id}, {"_id": 0})
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
    await db.google_oauth_states.insert_one({
        "state": state,
        "user_id": current.user_id,
        "created_at": datetime.now(timezone.utc),
    })
    url = gi.build_authorization_url(state)
    return {"authorization_url": url}


@api_router.get("/integrations/google/callback")
async def google_callback(code: str, state: str):
    st = await db.google_oauth_states.find_one({"state": state}, {"_id": 0})
    if not st:
        raise HTTPException(status_code=400, detail="Invalid state")
    user_id = st["user_id"]
    await db.google_oauth_states.delete_one({"state": state})

    try:
        creds_dict = gi.exchange_code(code)
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
    try:
        asyncio.create_task(tg.start_polling())
    except Exception:
        logger.exception("failed to start telegram polling")
    try:
        asyncio.create_task(_reminders_loop())
    except Exception:
        logger.exception("failed to start reminders loop")


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
                    # mark as processed anyway so we don't keep scanning
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
        await asyncio.sleep(30 * 60)  # every 30 minutes


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        await tg.stop_polling()
    except Exception:
        pass
    client.close()
