"""Iteration 3 backend tests: chat conv threading, task-with-due_date routing, notes persistence, reminders loop presence, telegram voice handler."""
import os
import json
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://smart-chat-executor.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "test_session_demo_12345"
AUTH = {"Authorization": f"Bearer {SESSION_TOKEN}"}


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update(AUTH)
    return s


def _stream_chat(client, action, content, conv_id=None, timeout=90):
    """POST /api/chat/stream and collect ndjson events. Returns (full_text, conv_id, events)."""
    payload = {"action": action, "content": content}
    if conv_id:
        payload["conv_id"] = conv_id
    r = client.post(f"{BASE_URL}/api/chat/stream", json=payload, stream=True, timeout=timeout)
    assert r.status_code == 200, r.text
    full = []
    got_conv = None
    events = []
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        events.append(ev)
        if ev.get("type") == "delta":
            full.append(ev.get("content", ""))
        elif ev.get("type") == "done":
            got_conv = ev.get("conv_id")
    return "".join(full), got_conv, events


# ---------- Task with due_date+time must be a Task (not Todo) ----------
def test_task_todo_with_datetime_goes_to_tasks(client):
    content = "Ricordami di chiamare Marco domani alle 15:30, priorità alta"
    tasks_before = client.get(f"{BASE_URL}/api/tasks").json()
    todos_before = client.get(f"{BASE_URL}/api/todos").json()
    n_tasks_before = len(tasks_before)
    n_todos_before = len(todos_before)

    text, conv_id, _ = _stream_chat(client, "task_todo", content)
    assert conv_id
    # small pause for insert visibility (already awaited server-side but be safe)
    time.sleep(1)

    tasks_after = client.get(f"{BASE_URL}/api/tasks").json()
    todos_after = client.get(f"{BASE_URL}/api/todos").json()
    assert len(tasks_after) == n_tasks_before + 1, f"expected +1 task, LLM answer: {text[:400]}"
    assert len(todos_after) == n_todos_before, "unexpected todo created"

    # newest task should have due_date and (usually) due_time
    newest = sorted(tasks_after, key=lambda t: t.get("created_at", ""), reverse=True)[0]
    assert newest.get("due_date"), f"newest task missing due_date: {newest}"
    # cleanup
    client.delete(f"{BASE_URL}/api/tasks/{newest['id']}")


# ---------- Conversation threading + context recall ----------
def test_conv_threading_context_recall(client):
    # Turn 1: upload info
    fiscal_code = "RSSMRA80A01H501Z"
    _, conv_id, _ = _stream_chat(client, "info_upload", f"Il mio codice fiscale è {fiscal_code}")
    assert conv_id, "conv_id not returned"

    # kb_chunk count for later side-effect check
    kb_chunks_1 = None  # not exposed via API; we'll rely on second turn not creating side-effects

    # Turn 2: same conv_id, ask about it
    answer, conv_id2, _ = _stream_chat(
        client, "info_request",
        "Qual era il codice fiscale che ti ho appena detto? Rispondi solo con il codice.",
        conv_id=conv_id,
    )
    assert conv_id2 == conv_id, "server should keep same conv_id"
    assert fiscal_code in answer, f"context not recalled. answer={answer[:400]}"


# ---------- GET /api/conversations/{conv_id} returns messages array ----------
def test_get_conversation_returns_messages(client):
    _, conv_id, _ = _stream_chat(client, "info_request", "Ciao, dimmi un fatto interessante in una frase.")
    assert conv_id
    r = client.get(f"{BASE_URL}/api/conversations/{conv_id}")
    assert r.status_code == 200, r.text
    conv = r.json()
    msgs = conv.get("messages", [])
    assert isinstance(msgs, list) and len(msgs) >= 2, f"messages malformed: {msgs}"
    roles = [m["role"] for m in msgs]
    assert "user" in roles and "assistant" in roles
    for m in msgs:
        assert set(m.keys()) >= {"role", "content", "ts"}


# ---------- Second turn on task_todo conv must not create duplicate task ----------
def test_second_turn_does_not_duplicate_task(client):
    content = "Ricordami di comprare il pane venerdì, priorità bassa"
    tasks_before = len(client.get(f"{BASE_URL}/api/tasks").json())
    _, conv_id, _ = _stream_chat(client, "task_todo", content)
    time.sleep(1)
    tasks_after1 = client.get(f"{BASE_URL}/api/tasks").json()
    assert len(tasks_after1) == tasks_before + 1

    # second turn - continue same conv - should NOT create another task
    _stream_chat(client, "task_todo", "Grazie, aggiungi 'con farro' nel titolo.", conv_id=conv_id)
    time.sleep(1)
    tasks_after2 = client.get(f"{BASE_URL}/api/tasks").json()
    assert len(tasks_after2) == len(tasks_after1), "duplicate task created on second turn"

    # cleanup newest
    newest = sorted(tasks_after2, key=lambda t: t.get("created_at", ""), reverse=True)[0]
    client.delete(f"{BASE_URL}/api/tasks/{newest['id']}")


# ---------- PATCH /tasks notes persistence ----------
def test_patch_task_notes_persists(client):
    cr = client.post(f"{BASE_URL}/api/tasks", json={"title": "TEST_notes task", "due_date": "2026-06-01", "priority": "media"})
    assert cr.status_code == 200
    tid = cr.json()["id"]
    try:
        pr = client.patch(f"{BASE_URL}/api/tasks/{tid}", json={"notes": "queste sono le note del task"})
        assert pr.status_code == 200
        assert pr.json().get("notes") == "queste sono le note del task"
        # GET all tasks and confirm
        lst = client.get(f"{BASE_URL}/api/tasks").json()
        got = next(t for t in lst if t["id"] == tid)
        assert got["notes"] == "queste sono le note del task"
    finally:
        client.delete(f"{BASE_URL}/api/tasks/{tid}")


# ---------- PATCH /todos notes persistence ----------
def test_patch_todo_notes_persists(client):
    cr = client.post(f"{BASE_URL}/api/todos", json={"title": "TEST_notes todo", "priority": "bassa"})
    assert cr.status_code == 200
    tid = cr.json()["id"]
    try:
        pr = client.patch(f"{BASE_URL}/api/todos/{tid}", json={"notes": "note del todo"})
        assert pr.status_code == 200
        assert pr.json().get("notes") == "note del todo"
        lst = client.get(f"{BASE_URL}/api/todos").json()
        got = next(t for t in lst if t["id"] == tid)
        assert got["notes"] == "note del todo"
    finally:
        client.delete(f"{BASE_URL}/api/todos/{tid}")


# ---------- Reminders loop function exists ----------
def test_reminders_loop_source_exists():
    src = open("/app/backend/server.py").read()
    assert "_reminders_loop" in src
    assert "asyncio.create_task(_reminders_loop())" in src
    assert "reminder_sent" in src


# ---------- Telegram voice handler registered ----------
def test_telegram_voice_handler_registered():
    src = open("/app/backend/telegram_bot.py").read()
    assert "_msg_voice" in src
    assert "filters.VOICE" in src
    assert "MessageHandler(filters.VOICE, _msg_voice)" in src
