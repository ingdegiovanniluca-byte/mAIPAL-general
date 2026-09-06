"""Backend tests for admin revoke / restore / delete user endpoints.

Covers the bug fix: "impossibile revocare/eliminare utenti in AdminPage".
"""
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_TOKEN = "admin_session_1788717776_v2"
ADMIN_USER_ID = "user_e6fb16f2cc33"
ADMIN_EMAIL = "ingdegiovanniluca@gmail.com"

# Load frontend .env to get REACT_APP_BACKEND_URL if not set
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                API = f"{BASE_URL}/api"
                break

# Direct DB access to seed test users and verify persistence
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
if not MONGO_URL or not DB_NAME:
    # load backend .env
    with open("/app/backend/.env") as f:
        for line in f:
            line = line.strip()
            if line.startswith("MONGO_URL="):
                MONGO_URL = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("DB_NAME="):
                DB_NAME = line.split("=", 1)[1].strip().strip('"')


def _admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture()
def test_user(mongo_db):
    """Create an ad-hoc test user + session + whitelist. Yield ids; teardown wipes everything."""
    ts = int(time.time())
    uid = f"test-user-admin-lifecycle-{ts}-{uuid.uuid4().hex[:6]}"
    email = f"test_admin_lc_{ts}_{uuid.uuid4().hex[:4]}@example.com"
    stoken = f"test_session_admin_lc_{ts}_{uuid.uuid4().hex[:4]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    exp = datetime.now(timezone.utc) + timedelta(days=7)

    mongo_db.users.insert_one({
        "user_id": uid, "email": email, "name": "Test LC",
        "role": "user", "onboarded": False, "created_at": now_iso,
    })
    mongo_db.user_sessions.insert_one({
        "user_id": uid, "session_token": stoken,
        "created_at": datetime.now(timezone.utc), "expires_at": exp,
    })
    mongo_db.allowed_emails.insert_one({
        "email": email, "notes": "TEST_lifecycle",
        "added_by": ADMIN_EMAIL, "added_at": now_iso,
    })
    mongo_db.tasks.insert_one({"task_id": f"t-{ts}", "user_id": uid, "title": "TEST_task", "created_at": now_iso})
    mongo_db.todos.insert_one({"todo_id": f"td-{ts}", "user_id": uid, "title": "TEST_todo", "created_at": now_iso})
    mongo_db.journal_entries.insert_one({"entry_id": f"j-{ts}", "user_id": uid, "text": "TEST_j", "created_at": now_iso})
    mongo_db.conversations.insert_one({"conv_id": f"c-{ts}", "user_id": uid, "title": "TEST_c", "created_at": now_iso})
    mongo_db.kb_documents.insert_one({"doc_id": f"d-{ts}", "user_id": uid, "name": "TEST_d", "created_at": now_iso})
    mongo_db.kb_chunks.insert_one({"chunk_id": f"ch-{ts}", "user_id": uid, "text": "TEST_ch"})

    yield {"user_id": uid, "email": email, "session_token": stoken}

    for coll in ["tasks","todos","journal_entries","conversations","kb_chunks","kb_documents","user_sessions"]:
        mongo_db[coll].delete_many({"user_id": uid})
    mongo_db.allowed_emails.delete_many({"email": email})
    mongo_db.users.delete_one({"user_id": uid})


def _run(x):
    """No-op wrapper: pymongo is synchronous."""
    return x


# ============ TESTS ============

class TestAdminAuth:
    def test_admin_endpoints_reject_non_admin(self):
        # regular user token from credentials file
        r = requests.get(f"{API}/admin/users", headers={"Authorization": "Bearer test_session_1788713374_v11"})
        assert r.status_code == 403, r.text

    def test_admin_endpoints_reject_missing_auth(self):
        r = requests.get(f"{API}/admin/users")
        assert r.status_code == 401

    def test_admin_list_users_ok(self):
        r = requests.get(f"{API}/admin/users", headers=_admin_headers())
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestRevoke:
    def test_revoke_marks_user_and_removes_sessions_and_whitelist(self, test_user, mongo_db):
        uid = test_user["user_id"]
        r = requests.post(f"{API}/admin/users/{uid}/revoke", headers=_admin_headers())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["email"] == test_user["email"]
        assert body["sessions_removed"] >= 1

        # verify DB state
        doc = _run(mongo_db.users.find_one({"user_id": uid}, {"_id": 0}))
        assert doc is not None
        assert "revoked_at" in doc and doc["revoked_at"]
        assert doc.get("revoked_by") == ADMIN_EMAIL
        # sessions gone
        sess = _run(mongo_db.user_sessions.count_documents({"user_id": uid}))
        assert sess == 0
        # whitelist removed
        wl = _run(mongo_db.allowed_emails.find_one({"email": test_user["email"]}))
        assert wl is None

    def test_revoke_admin_forbidden(self):
        r = requests.post(f"{API}/admin/users/{ADMIN_USER_ID}/revoke", headers=_admin_headers())
        assert r.status_code == 400
        assert "amministratore" in r.json().get("detail", "").lower()

    def test_revoke_unknown_user_404(self):
        r = requests.post(f"{API}/admin/users/nonexistent-xyz/revoke", headers=_admin_headers())
        assert r.status_code == 404


class TestRestore:
    def test_restore_reinstates_whitelist_and_clears_revoked(self, test_user, mongo_db):
        uid = test_user["user_id"]
        # revoke first
        r = requests.post(f"{API}/admin/users/{uid}/revoke", headers=_admin_headers())
        assert r.status_code == 200
        # restore
        r = requests.post(f"{API}/admin/users/{uid}/restore", headers=_admin_headers())
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert r.json()["email"] == test_user["email"]

        # DB assertions
        doc = _run(mongo_db.users.find_one({"user_id": uid}, {"_id": 0}))
        assert "revoked_at" not in doc
        assert "revoked_by" not in doc
        wl = _run(mongo_db.allowed_emails.find_one({"email": test_user["email"]}))
        assert wl is not None


class TestDelete:
    def test_delete_wipes_all_user_data(self, test_user, mongo_db):
        uid = test_user["user_id"]
        r = requests.delete(f"{API}/admin/users/{uid}", headers=_admin_headers())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["email"] == test_user["email"]
        deleted = body["deleted"]
        # each seeded collection had 1 doc
        for coll in ["tasks","todos","journal_entries","conversations","kb_documents","kb_chunks"]:
            assert deleted[coll] >= 1, f"{coll} not deleted: {deleted}"
        assert deleted["users"] == 1
        assert deleted["allowed_emails"] >= 1

        # verify DB
        assert _run(mongo_db.users.find_one({"user_id": uid})) is None
        for coll in ["tasks","todos","journal_entries","conversations","kb_documents","kb_chunks","user_sessions"]:
            n = _run(mongo_db[coll].count_documents({"user_id": uid}))
            assert n == 0, f"{coll} still has {n} docs"
        # user no longer in admin list
        r2 = requests.get(f"{API}/admin/users", headers=_admin_headers())
        assert not any(u.get("user_id") == uid for u in r2.json())

    def test_delete_admin_forbidden(self):
        r = requests.delete(f"{API}/admin/users/{ADMIN_USER_ID}", headers=_admin_headers())
        assert r.status_code == 400
        assert "amministratore" in r.json().get("detail", "").lower()

    def test_delete_unknown_404(self):
        r = requests.delete(f"{API}/admin/users/does-not-exist-xyz", headers=_admin_headers())
        assert r.status_code == 404


class TestFullLifecycle:
    def test_create_revoke_restore_revoke_delete(self, test_user, mongo_db):
        uid = test_user["user_id"]
        # revoke
        assert requests.post(f"{API}/admin/users/{uid}/revoke", headers=_admin_headers()).status_code == 200
        # restore
        assert requests.post(f"{API}/admin/users/{uid}/restore", headers=_admin_headers()).status_code == 200
        doc = _run(mongo_db.users.find_one({"user_id": uid}, {"_id": 0}))
        assert "revoked_at" not in doc
        # revoke again
        assert requests.post(f"{API}/admin/users/{uid}/revoke", headers=_admin_headers()).status_code == 200
        # delete
        r = requests.delete(f"{API}/admin/users/{uid}", headers=_admin_headers())
        assert r.status_code == 200
        assert _run(mongo_db.users.find_one({"user_id": uid})) is None
