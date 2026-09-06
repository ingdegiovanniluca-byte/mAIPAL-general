"""Iteration 7: verify /api/conversations returns pipeline + optional meta field."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://smart-chat-executor.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "test_session_demo_12345"


@pytest.fixture
def client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    return s


def test_auth_me(client):
    r = client.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200, r.text
    assert r.json().get("user_id") == "test-user-demo"


def test_list_conversations_has_pipeline(client):
    r = client.get(f"{BASE_URL}/api/conversations")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if not data:
        pytest.skip("no conversations seeded")
    c = data[0]
    assert "conv_id" in c
    assert "action" in c
    assert "pipeline" in c
    # meta is optional but if present must be dict
    if "meta" in c and c["meta"] is not None:
        assert isinstance(c["meta"], dict)


def test_favorite_toggle(client):
    r = client.get(f"{BASE_URL}/api/conversations")
    convs = r.json()
    if not convs:
        pytest.skip("no conv")
    cid = convs[0]["conv_id"]
    prev = bool(convs[0].get("favorite"))
    r2 = client.post(f"{BASE_URL}/api/conversations/{cid}/favorite")
    assert r2.status_code == 200
    after = client.get(f"{BASE_URL}/api/conversations").json()
    now = next((c for c in after if c["conv_id"] == cid), None)
    assert now is not None
    assert bool(now.get("favorite")) != prev
    # restore
    client.post(f"{BASE_URL}/api/conversations/{cid}/favorite")


def test_conversation_detail(client):
    convs = client.get(f"{BASE_URL}/api/conversations").json()
    if not convs:
        pytest.skip("no conv")
    cid = convs[0]["conv_id"]
    r = client.get(f"{BASE_URL}/api/conversations/{cid}")
    assert r.status_code == 200
    d = r.json()
    assert d["conv_id"] == cid
    assert "action" in d
