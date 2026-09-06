"""Iteration 5 backend tests: meta marker stripping, semantic KB, profile PATCH, attachments 400."""
import os
import json
import time
import uuid
import pytest
import requests
from datetime import datetime, timezone

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION_TOKEN = "test_session_demo_12345"
AUTH = {"Authorization": f"Bearer {SESSION_TOKEN}"}
USER_ID = "test-user-demo"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update(AUTH)
    return s


@pytest.fixture(scope="module")
def db():
    c = MongoClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


def _stream_chat(client, action, content, conv_id=None, timeout=120):
    """POST /api/chat/stream and collect visible text + conv_id."""
    payload = {"action": action, "content": content}
    if conv_id:
        payload["conv_id"] = conv_id
    visible = ""
    final_conv = None
    with client.post(f"{BASE_URL}/api/chat/stream", json=payload, stream=True, timeout=timeout) as r:
        assert r.status_code == 200, r.text
        for line in r.iter_lines():
            if not line:
                continue
            try:
                ev = json.loads(line.decode() if isinstance(line, bytes) else line)
            except Exception:
                continue
            if ev.get("type") == "delta":
                visible += ev.get("content", "")
            elif ev.get("type") == "done":
                final_conv = ev.get("conv_id")
    return visible, final_conv


# ---------- 1. info_upload: no meta leak, kb_chunk embedded ----------
def test_info_upload_clean_stream_and_embedding(client, db):
    text = f"La password del router di casa è 8j2K9pQrLm3z_TEST_{uuid.uuid4().hex[:6]} e la rete si chiama CasaMaipal_5G_TEST"
    visible, conv_id = _stream_chat(client, "info_upload", text)
    # No marker / JSON leak in visible stream
    assert "<<<META>>>" not in visible
    assert "<<<END>>>" not in visible
    assert "```json" not in visible
    assert "```" not in visible
    # It should be non-empty natural response
    assert len(visible.strip()) > 5

    # Wait for background write and check DB
    time.sleep(1.5)
    conv = db.conversations.find_one({"conv_id": conv_id})
    assert conv is not None
    ar = conv.get("agent_response", "")
    assert "<<<META>>>" not in ar
    assert "```json" not in ar

    # kb_chunk with 384-float embedding
    chunk = db.kb_chunks.find_one({"conv_id": conv_id})
    assert chunk is not None, "kb_chunk not created"
    emb = chunk.get("embedding")
    assert isinstance(emb, list), "embedding missing or not list"
    assert len(emb) == 384, f"embedding dim {len(emb)} != 384"
    assert all(isinstance(x, (int, float)) for x in emb[:5])

    # cleanup
    db.conversations.delete_one({"conv_id": conv_id})
    db.kb_chunks.delete_one({"chunk_id": chunk["chunk_id"]})


# ---------- 2. Semantic retrieval ----------
def test_semantic_retrieval_wifi(client, db):
    # First upload a fact
    marker = uuid.uuid4().hex[:6]
    wifi_name = f"CasaMaipal_5G_{marker}"
    wifi_pass = f"8j2K9pQrLm3z_{marker}"
    upload_text = f"La password del router di casa è {wifi_pass} e la rete si chiama {wifi_name}"
    _, upload_conv = _stream_chat(client, "info_upload", upload_text)
    time.sleep(2)

    try:
        query = "come si chiama il mio wifi e qual e la chiave?"
        visible, conv_id = _stream_chat(client, "info_request", query)
        assert "<<<META>>>" not in visible
        assert "```" not in visible
        # Semantic hit
        assert wifi_name in visible, f"Wifi SSID '{wifi_name}' not found in answer: {visible}"
        assert wifi_pass in visible, f"Wifi password '{wifi_pass}' not found in answer: {visible}"
        # cleanup
        db.conversations.delete_one({"conv_id": conv_id})
    finally:
        db.conversations.delete_one({"conv_id": upload_conv})
        db.kb_chunks.delete_many({"conv_id": upload_conv})


# ---------- 3. task_todo -> task created, natural response ----------
def test_task_todo_clean_and_task_created(client, db):
    content = f"Ricordami di comprare fiori TEST_{uuid.uuid4().hex[:6]} sabato alle 10, priorità media"
    visible, conv_id = _stream_chat(client, "task_todo", content)
    assert "<<<META>>>" not in visible
    assert "```json" not in visible
    assert "\"title\"" not in visible.lower() or "title:" not in visible.lower()

    time.sleep(1.5)
    conv = db.conversations.find_one({"conv_id": conv_id})
    assert conv is not None
    meta = conv.get("meta") or {}
    assert isinstance(meta, dict)
    # meta should contain due_time 10:00
    assert (meta.get("due_time") or "").startswith("10:"), f"meta due_time missing: {meta}"
    # Task should be created (due_date present)
    task = db.tasks.find_one({"source_conv": conv_id})
    todo = db.todos.find_one({"source_conv": conv_id})
    assert task or todo, f"Neither task nor todo created for conv={conv_id}, meta={meta}"
    if task:
        assert (task.get("due_time") or "").startswith("10:")
        db.tasks.delete_one({"id": task["id"]})
    if todo:
        db.todos.delete_one({"id": todo["id"]})
    db.conversations.delete_one({"conv_id": conv_id})


# ---------- 4. Contextual chat: task_chat returns clean answer ----------
def test_task_chat_meta_stripped(client, db):
    task_id = f"task_TEST_{uuid.uuid4().hex[:8]}"
    db.tasks.insert_one({
        "id": task_id, "user_id": USER_ID, "title": "Riunione clienti",
        "description": "Discutere piano Q1", "due_date": "2026-02-01", "due_time": "15:00",
        "priority": "media", "tags": [], "notes": "", "calendar_synced": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = client.post(f"{BASE_URL}/api/tasks/{task_id}/chat", json={"message": "Cambia priorità ad alta"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "answer" in data and "task" in data
        ans = data["answer"]
        assert "<<<META>>>" not in ans
        assert "```" not in ans
        assert isinstance(data["task"], dict)
    finally:
        db.tasks.delete_one({"id": task_id})


def test_todo_chat_meta_stripped(client, db):
    todo_id = f"todo_TEST_{uuid.uuid4().hex[:8]}"
    db.todos.insert_one({
        "id": todo_id, "user_id": USER_ID, "title": "Leggere libro",
        "description": "", "status": "da_fare", "completion_percent": 0,
        "priority": "media", "tags": [], "notes": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = client.post(f"{BASE_URL}/api/todos/{todo_id}/chat", json={"message": "Segna in corso al 50%"})
        assert r.status_code == 200, r.text
        data = r.json()
        ans = data["answer"]
        assert "<<<META>>>" not in ans
        assert "```" not in ans
        assert isinstance(data["todo"], dict)
    finally:
        db.todos.delete_one({"id": todo_id})


# ---------- 5. Profile PATCH ----------
def test_profile_patch_and_me(client, db):
    original = db.users.find_one({"user_id": USER_ID}, {"_id": 0})
    try:
        patch = {
            "profession": "Test Engineer",
            "sector": "QA",
            "verticals": ["Lavoro", "Studio"],
            "interests": ["testing", "ai"],
            "tone": "informale",
            "home_address": "Via Roma 1, Milano",
            "work_address": "Via Torino 5, Milano",
        }
        r = client.patch(f"{BASE_URL}/api/profile", json=patch)
        assert r.status_code == 200, r.text
        d = r.json()
        for k, v in patch.items():
            assert d.get(k) == v, f"field {k}: {d.get(k)} != {v}"

        # GET /auth/me reflects changes
        me = client.get(f"{BASE_URL}/api/auth/me")
        assert me.status_code == 200
        md = me.json()
        assert md.get("home_address") == "Via Roma 1, Milano"
        assert md.get("work_address") == "Via Torino 5, Milano"
        assert md.get("profession") == "Test Engineer"
    finally:
        # restore
        if original:
            restore = {k: original.get(k) for k in ["profession", "sector", "verticals", "interests", "tone", "home_address", "work_address"]}
            db.users.update_one({"user_id": USER_ID}, {"$set": restore})


# ---------- 6. Onboarding accepts addresses ----------
def test_onboarding_accepts_addresses(client, db):
    original = db.users.find_one({"user_id": USER_ID}, {"_id": 0})
    try:
        payload = {
            "profession": "P", "sector": "S",
            "verticals": ["Lavoro"], "interests": ["x"],
            "tone": "informale",
            "home_address": "H_TEST_ADDR",
            "work_address": "W_TEST_ADDR",
        }
        r = client.post(f"{BASE_URL}/api/onboarding", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("home_address") == "H_TEST_ADDR"
        assert d.get("work_address") == "W_TEST_ADDR"
        assert d.get("onboarded") is True
    finally:
        if original:
            restore = {k: original.get(k) for k in ["profession", "sector", "verticals", "interests", "tone", "home_address", "work_address", "onboarded"]}
            db.users.update_one({"user_id": USER_ID}, {"$set": restore})


# ---------- 7. Attachments upload returns 400 when Google not connected ----------
def test_attachments_upload_no_google_returns_400(client, db):
    # ensure not connected
    db.integrations.delete_many({"user_id": USER_ID, "provider": "google"})
    files = {"file": ("test.txt", b"hello world", "text/plain")}
    r = requests.post(f"{BASE_URL}/api/attachments/upload", headers=AUTH, files=files, timeout=30)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "Google Workspace non collegato" in detail
