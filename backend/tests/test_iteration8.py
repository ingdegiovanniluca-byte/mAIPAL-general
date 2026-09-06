"""Iteration 8: Journal (chat action + endpoints), scope=all vs scope=kb, retrocompat.
Endpoints exercised: /api/chat/stream, /api/journal, /api/journal/trend, /api/voice/transcribe.
"""
import os
import json
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    # fallback for cases where env is not loaded
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")

TOKEN = "test_session_1788714113067_it8"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return s


def _stream_chat(sess, action, content, filters=None, timeout=60):
    payload = {"action": action, "content": content}
    if filters is not None:
        payload["filters"] = filters
    r = sess.post(f"{BASE}/api/chat/stream", json=payload, stream=True, timeout=timeout)
    assert r.status_code == 200, r.text
    conv_id = None
    full_visible = ""
    for line in r.iter_lines():
        if not line:
            continue
        try:
            ev = json.loads(line.decode())
        except Exception:
            continue
        if ev.get("type") == "delta":
            full_visible += ev.get("content", "")
        elif ev.get("type") == "done":
            conv_id = ev.get("conv_id")
            break
        elif ev.get("type") == "error":
            pytest.fail(f"stream error: {ev.get('content')}")
    return conv_id, full_visible


# ==== auth sanity ====
def test_auth_me(sess):
    r = sess.get(f"{BASE}/api/auth/me")
    assert r.status_code == 200, r.text
    assert r.json()["email"].startswith("it8.")


# ==== JOURNAL via chat action ====
def test_chat_action_journal_creates_entry(sess):
    content = (
        "Oggi ho fatto una lunga corsa al parco alle 7 del mattino, "
        "mi sono sentito davvero energico e grato per la giornata di sole. "
        "Poi ho pranzato con Marta e nel pomeriggio ho lavorato al progetto mAIPAL."
    )
    conv_id, visible = _stream_chat(sess, "journal", content, timeout=90)
    assert conv_id, "no conv_id"
    assert visible.strip(), "visible text empty"
    # Give mongo a moment
    time.sleep(0.5)
    r = sess.get(f"{BASE}/api/journal")
    assert r.status_code == 200
    entries = r.json()
    assert isinstance(entries, list) and len(entries) >= 1
    # Find our entry (source_conv match)
    matched = [e for e in entries if e.get("source_conv") == conv_id]
    assert matched, f"no journal entry linked to conv {conv_id}"
    e = matched[0]
    assert e.get("cleaned_text"), "cleaned_text empty"
    assert e.get("title"), "title empty"
    assert e.get("mood"), "mood empty"
    assert e["mood"] in {"felice", "neutro", "stressato", "riflessivo", "energico", "stanco", "grato"}
    assert isinstance(e.get("highlights"), list) and len(e["highlights"]) >= 1


# ==== JOURNAL filters ====
def test_journal_filter_by_mood(sess):
    r = sess.get(f"{BASE}/api/journal", params={"mood": "grato"})
    assert r.status_code == 200
    for e in r.json():
        assert e.get("mood") == "grato"


def test_journal_search_q(sess):
    r = sess.get(f"{BASE}/api/journal", params={"q": "corsa"})
    assert r.status_code == 200
    data = r.json()
    # If any entries match, they should contain 'corsa' somewhere (case-insensitive)
    for e in data:
        blob = " ".join([
            e.get("cleaned_text") or "", e.get("raw_text") or "",
            e.get("title") or "", " ".join(e.get("highlights") or []),
        ]).lower()
        assert "corsa" in blob, f"entry {e.get('id')} does not contain 'corsa'"


def test_journal_trend_7_days(sess):
    r = sess.get(f"{BASE}/api/journal/trend", params={"days": 7})
    assert r.status_code == 200
    data = r.json()
    assert "days" in data and "mood_score_map" in data
    assert len(data["days"]) == 7
    for d in data["days"]:
        assert set(d.keys()) >= {"date", "mood", "score"}
    m = data["mood_score_map"]
    assert m["felice"] == 5 and m["stressato"] == 1


# ==== scope=all vs scope=kb ====
def test_info_request_scope_all_sees_task_and_journal(sess):
    # Seed a task explicitly
    t = sess.post(f"{BASE}/api/tasks", json={
        "title": "Riunione con dentista Rossi",
        "description": "Controllo semestrale",
        "due_date": "2030-04-15",
        "priority": "media",
        "tags": ["salute"],
    })
    assert t.status_code == 200, t.text

    # Ensure there's a journal entry mentioning something unique
    _stream_chat(sess, "journal",
                 "Oggi 15 minuti di meditazione in giardino, tema focus e respirazione consapevole.",
                 timeout=90)
    time.sleep(1)

    # scope=all
    conv_id_all, visible_all = _stream_chat(sess, "info_request",
                                            "Quando ho la visita dal dentista Rossi?",
                                            filters={"scope": "all"}, timeout=60)
    assert conv_id_all
    # Retrieve conversation to inspect first assistant answer (some models may summarise date differently)
    r = sess.get(f"{BASE}/api/conversations/{conv_id_all}")
    assert r.status_code == 200
    # The visible response with scope=all should reference the dentist context; assert loosely.
    low = visible_all.lower()
    assert ("dentista" in low) or ("rossi" in low) or ("aprile" in low) or ("2030-04-15" in low), \
        f"scope=all response did not mention dentist context. Got: {visible_all[:300]}"


def test_info_request_default_scope_kb_no_task_hit(sess):
    # Ask for something that ONLY exists as a task (never uploaded to KB) → without scope=all
    conv_id, visible = _stream_chat(sess, "info_request",
                                    "Quando ho la visita dal dentista Rossi?",
                                    filters=None, timeout=60)
    # Cannot fully guarantee model won't guess; but must NOT reveal the exact stored date '2030-04-15'.
    assert "2030-04-15" not in visible, "scope=kb leaked task date"


# ==== retrocompat ====
def test_action_task_todo_still_works(sess):
    conv_id, visible = _stream_chat(sess, "task_todo",
                                    "Ricordami di chiamare Luca domani alle 15:30",
                                    timeout=60)
    assert conv_id and visible.strip()
    time.sleep(0.5)
    # Either task or todo should be created recently
    tr = sess.get(f"{BASE}/api/tasks").json()
    trr = sess.get(f"{BASE}/api/todos").json()
    combined = tr + trr
    assert any(("Luca" in (x.get("title") or "")) or ("luca" in (x.get("title") or "").lower())
               for x in combined), "task/todo not created for retro-compat"


def test_action_info_upload_still_works(sess):
    conv_id, visible = _stream_chat(sess, "info_upload",
                                    "Il mio codice cliente Amazon Business è AB-99-XYZ.",
                                    timeout=60)
    assert conv_id and visible.strip()


# ==== voice transcribe endpoint still there ====
def test_voice_transcribe_endpoint_present(sess):
    # Send a fake tiny webm blob — endpoint may return 500 from whisper, but should NOT be 404/401.
    r = sess.post(
        f"{BASE}/api/voice/transcribe",
        files={"file": ("t.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 100, "audio/webm")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code in (200, 500), f"unexpected status {r.status_code}: {r.text}"


def test_voice_transcribe_requires_auth():
    r = requests.post(
        f"{BASE}/api/voice/transcribe",
        files={"file": ("t.webm", b"\x00" * 10, "audio/webm")},
    )
    assert r.status_code == 401
