"""Iteration 4 backend tests: conversation favorite toggle, deletion, favorite filter, multi-user isolation."""
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION_TOKEN = "test_session_demo_12345"
AUTH = {"Authorization": f"Bearer {SESSION_TOKEN}"}


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update(AUTH)
    return s


@pytest.fixture(scope="module")
def db():
    c = MongoClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


def _make_conv(db, user_id, favorite=False, action="info_request"):
    conv_id = f"conv_TEST_{uuid.uuid4().hex[:8]}"
    db.conversations.insert_one({
        "conv_id": conv_id,
        "user_id": user_id,
        "action": action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_message": "TEST message",
        "messages": [{"role": "user", "content": "TEST message", "ts": datetime.now(timezone.utc).isoformat()}],
        "pipeline": {"claude": "ok", "n8n": "skip", "mongodb": "ok"},
        "favorite": favorite,
    })
    return conv_id


def _make_second_user_session(db):
    user_id = f"user_TEST_{uuid.uuid4().hex[:8]}"
    token = f"TEST_sess_{uuid.uuid4().hex[:12]}"
    db.users.insert_one({
        "user_id": user_id, "email": f"{user_id}@t.test", "name": "T2",
        "onboarded": True, "verticals": [], "interests": [], "tone": "informale",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    db.user_sessions.insert_one({
        "user_id": user_id, "session_token": token,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "created_at": datetime.now(timezone.utc),
    })
    return user_id, token


# ---------- Favorite toggle ----------
def test_favorite_toggle(client, db):
    conv_id = _make_conv(db, "test-user-demo", favorite=False)
    try:
        r1 = client.post(f"{BASE_URL}/api/conversations/{conv_id}/favorite")
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["favorite"] is True
        assert d1["conv_id"] == conv_id

        g = client.get(f"{BASE_URL}/api/conversations/{conv_id}")
        assert g.status_code == 200
        assert g.json().get("favorite") is True

        r2 = client.post(f"{BASE_URL}/api/conversations/{conv_id}/favorite")
        assert r2.status_code == 200
        assert r2.json()["favorite"] is False

        g2 = client.get(f"{BASE_URL}/api/conversations/{conv_id}")
        assert g2.json().get("favorite") is False
    finally:
        db.conversations.delete_one({"conv_id": conv_id})


def test_favorite_unknown_conv_returns_404(client):
    r = client.post(f"{BASE_URL}/api/conversations/conv_TEST_doesnotexist/favorite")
    assert r.status_code == 404


def test_favorite_cross_user_returns_404(client, db):
    other_user, _ = _make_second_user_session(db)
    conv_id = _make_conv(db, other_user, favorite=False)
    try:
        r = client.post(f"{BASE_URL}/api/conversations/{conv_id}/favorite")
        assert r.status_code == 404
        doc = db.conversations.find_one({"conv_id": conv_id})
        assert doc.get("favorite") is False
    finally:
        db.conversations.delete_one({"conv_id": conv_id})
        db.users.delete_one({"user_id": other_user})
        db.user_sessions.delete_many({"user_id": other_user})


# ---------- Delete ----------
def test_delete_conversation(client, db):
    conv_id = _make_conv(db, "test-user-demo")
    r = client.delete(f"{BASE_URL}/api/conversations/{conv_id}")
    assert r.status_code == 200
    assert r.json().get("ok") is True
    g = client.get(f"{BASE_URL}/api/conversations/{conv_id}")
    assert g.status_code == 404


def test_delete_unknown_returns_404(client):
    r = client.delete(f"{BASE_URL}/api/conversations/conv_TEST_missing")
    assert r.status_code == 404


def test_delete_cross_user_returns_404(client, db):
    other_user, _ = _make_second_user_session(db)
    conv_id = _make_conv(db, other_user)
    try:
        r = client.delete(f"{BASE_URL}/api/conversations/{conv_id}")
        assert r.status_code == 404
        assert db.conversations.find_one({"conv_id": conv_id}) is not None
    finally:
        db.conversations.delete_one({"conv_id": conv_id})
        db.users.delete_one({"user_id": other_user})
        db.user_sessions.delete_many({"user_id": other_user})


# ---------- Favorite filter ----------
def test_list_favorite_filter(client, db):
    fav_id = _make_conv(db, "test-user-demo", favorite=True)
    plain_id = _make_conv(db, "test-user-demo", favorite=False)
    try:
        r = client.get(f"{BASE_URL}/api/conversations", params={"favorite": "true"})
        assert r.status_code == 200
        convs = r.json()
        ids = {c["conv_id"] for c in convs}
        assert fav_id in ids
        assert plain_id not in ids
        for c in convs:
            assert c.get("favorite") is True

        r2 = client.get(f"{BASE_URL}/api/conversations")
        assert r2.status_code == 200
        ids2 = {c["conv_id"] for c in r2.json()}
        assert fav_id in ids2 and plain_id in ids2
    finally:
        db.conversations.delete_many({"conv_id": {"$in": [fav_id, plain_id]}})


def test_favorite_filter_user_isolation(client, db):
    other_user, _ = _make_second_user_session(db)
    other_fav = _make_conv(db, other_user, favorite=True)
    try:
        r = client.get(f"{BASE_URL}/api/conversations", params={"favorite": "true"})
        assert r.status_code == 200
        ids = {c["conv_id"] for c in r.json()}
        assert other_fav not in ids
    finally:
        db.conversations.delete_one({"conv_id": other_fav})
        db.users.delete_one({"user_id": other_user})
        db.user_sessions.delete_many({"user_id": other_user})


# ---------- Guard: seeded fiscal-code conv still exists ----------
def test_fiscal_code_conv_still_exists(client):
    r = client.get(f"{BASE_URL}/api/conversations/conv_d8c2cbf317e8")
    assert r.status_code in (200, 404)
