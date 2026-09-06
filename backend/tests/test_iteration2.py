"""Iteration 2 backend tests: integrations (Google/Telegram) + voice STT + task 404s."""
import os
import io
import wave
import math
import struct
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://smart-chat-executor.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "test_session_demo_12345"
AUTH_HEADERS = {"Authorization": f"Bearer {SESSION_TOKEN}"}


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update(AUTH_HEADERS)
    return s


# ---------- Integrations Status ----------
def test_integrations_status_shape(client):
    r = client.get(f"{BASE_URL}/api/integrations/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "google" in data and "telegram" in data
    g = data["google"]
    for k in ("configured", "connected", "email", "drive_folder_id"):
        assert k in g
    assert g["configured"] is False  # env intentionally empty
    t = data["telegram"]
    assert t["configured"] is True
    assert t.get("bot_username") == "mAIPAL_bot"


def test_integrations_status_unauth():
    r = requests.get(f"{BASE_URL}/api/integrations/status")
    assert r.status_code == 401


# ---------- Google Authorize (not configured) ----------
def test_google_authorize_not_configured(client):
    r = client.get(f"{BASE_URL}/api/integrations/google/authorize")
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert "GOOGLE_CLIENT_ID" in detail or "non configurato" in detail.lower()


# ---------- Telegram link-code ----------
def test_telegram_link_code_and_invalidation(client):
    r1 = client.post(f"{BASE_URL}/api/integrations/telegram/link-code")
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1.get("code") and isinstance(d1["code"], str)
    assert d1.get("bot_username") == "mAIPAL_bot"
    assert d1.get("deep_link", "").startswith("https://t.me/mAIPAL_bot?start=")

    # Subsequent call must invalidate previous
    r2 = client.post(f"{BASE_URL}/api/integrations/telegram/link-code")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["code"] != d1["code"]


def test_telegram_disconnect(client):
    r = client.post(f"{BASE_URL}/api/integrations/telegram/disconnect")
    assert r.status_code == 200
    assert r.json().get("ok") is True


# ---------- Voice STT ----------
def _make_wav_bytes(seconds=1, freq=440, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for i in range(int(rate * seconds)):
            val = int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / rate))
            w.writeframesraw(struct.pack("<h", val))
    return buf.getvalue()


def test_voice_transcribe(client):
    wav_bytes = _make_wav_bytes()
    files = {"file": ("test.wav", wav_bytes, "audio/wav")}
    r = client.post(f"{BASE_URL}/api/voice/transcribe", files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "text" in data
    assert isinstance(data["text"], str)


# ---------- Tasks calendar sync when Google not connected ----------
def test_task_calendar_sync_without_google(client):
    # Create a task first
    payload = {"title": "TEST_iteration2 calendar sync", "due_date": "2026-12-31", "priority": "media"}
    cr = client.post(f"{BASE_URL}/api/tasks", json=payload)
    assert cr.status_code == 200
    task_id = cr.json()["id"]
    try:
        r = client.patch(f"{BASE_URL}/api/tasks/{task_id}", json={"calendar_synced": True})
        assert r.status_code == 400
        assert "Google" in r.json().get("detail", "")
    finally:
        client.delete(f"{BASE_URL}/api/tasks/{task_id}")


# ---------- 404 tests ----------
def test_patch_missing_task_returns_404(client):
    r = client.patch(f"{BASE_URL}/api/tasks/task_does_not_exist_xyz", json={"title": "x"})
    assert r.status_code == 404


def test_delete_missing_task_returns_404(client):
    r = client.delete(f"{BASE_URL}/api/tasks/task_does_not_exist_xyz")
    assert r.status_code == 404
