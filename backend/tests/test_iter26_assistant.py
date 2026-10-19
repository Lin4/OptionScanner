"""Ask AI (Claude) assistant endpoint tests — iteration 26.
Covers: streaming SSE chat, meta/delta/done events, follow-up ticker reuse, deep mode usage,
chat list/get/delete, cross-user isolation, plan gating (403), daily limit (429), validation.
"""
import hmac
import hashlib
import json
import os
import time
import uuid
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://optionscope.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "optiscreen_db")
JWT_SECRET = "optiscreen-dev-secret-change-in-prod"

TRADER_EMAIL = "trader@optiscreen.app"
TRADER_PASSWORD = "TestPass123!"


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def trader_token():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": TRADER_EMAIL, "password": TRADER_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def trader_headers(trader_token):
    return {"Authorization": f"Bearer {trader_token}"}


@pytest.fixture(scope="module")
def trial_user(db):
    """Register a brand-new trial user via sign-up+verify flow. Yields (email, token, user_id). Cleaned afterwards."""
    label = uuid.uuid4().hex[:8]
    email = f"delivered+aitest{label}@resend.dev"
    code = "123456"
    r = requests.post(f"{BASE}/api/auth/register",
                      json={"email": email, "password": "TrialPass123!", "name": "Trial AI Tester"}, timeout=15)
    assert r.status_code == 202, f"register: {r.status_code} {r.text}"
    digest = hmac.new(JWT_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()
    upd = db.email_verifications.update_one({"email": email}, {"$set": {"code_digest": digest, "attempts": 0}})
    assert upd.matched_count == 1, f"email_verifications row missing for {email}"
    r2 = requests.post(f"{BASE}/api/auth/register/verify", json={"email": email, "code": code}, timeout=15)
    assert r2.status_code == 200, f"verify: {r2.status_code} {r2.text}"
    data = r2.json()
    token = data["session_token"]
    user_id = data["user"]["user_id"]
    yield email, token, user_id
    # cleanup
    db.users.delete_many({"email": email})
    db.user_sessions.delete_many({"user_id": user_id})
    db.ai_chats.delete_many({"user_id": user_id})
    db.ai_messages.delete_many({"user_id": user_id})
    db.email_verifications.delete_many({"email": email})


# ---------- helpers ----------

def _stream_chat(headers, body, timeout=90):
    """POST /api/assistant/chat and return the list of parsed SSE event dicts."""
    r = requests.post(f"{BASE}/api/assistant/chat", json=body, headers=headers, stream=True, timeout=timeout)
    if r.status_code != 200:
        return r.status_code, None, r.text
    events = []
    buf = ""
    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            for line in block.splitlines():
                if line.startswith("data: "):
                    try:
                        events.append(json.loads(line[6:]))
                    except Exception:
                        pass
    return r.status_code, events, None


# ---------- validation / auth ----------

class TestValidation:
    def test_no_auth_401(self):
        r = requests.post(f"{BASE}/api/assistant/chat", json={"message": "hi", "mode": "quick"}, timeout=15)
        assert r.status_code == 401, r.text

    def test_empty_message_422(self, trader_headers):
        r = requests.post(f"{BASE}/api/assistant/chat", json={"message": "", "mode": "quick"}, headers=trader_headers, timeout=15)
        assert r.status_code == 422, r.text

    def test_message_too_long_422(self, trader_headers):
        long = "a" * 2001
        r = requests.post(f"{BASE}/api/assistant/chat", json={"message": long, "mode": "quick"}, headers=trader_headers, timeout=15)
        assert r.status_code == 422, r.text

    def test_bad_mode_422(self, trader_headers):
        r = requests.post(f"{BASE}/api/assistant/chat", json={"message": "hi", "mode": "x"}, headers=trader_headers, timeout=15)
        assert r.status_code == 422, r.text


# ---------- plan gating ----------

class TestPlanGating:
    def test_trial_user_blocked_403(self, trial_user):
        _, token, _ = trial_user
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{BASE}/api/assistant/chat",
                          json={"message": "Hi", "mode": "quick"}, headers=headers, timeout=20)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
        assert "Advance" in r.text and "Expert" in r.text

    def test_limit_exhaustion_429(self, db, trial_user):
        """Promote trial user to 'advance' in Mongo, insert 30 fake user ai_messages for today → expect 429."""
        email, token, user_id = trial_user
        db.users.update_one({"user_id": user_id}, {"$set": {"plan": "advance"}})
        now = datetime.now(timezone.utc)
        docs = [{"message_id": f"msg_fake_{user_id}_{i}", "chat_id": f"chat_fake_{user_id}", "user_id": user_id,
                 "role": "user", "content": f"q{i}", "mode": "quick", "tickers": [], "created_at": now}
                for i in range(30)]
        db.ai_messages.insert_many(docs)
        try:
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.post(f"{BASE}/api/assistant/chat",
                              json={"message": "test", "mode": "quick"}, headers=headers, timeout=20)
            assert r.status_code == 429, f"expected 429 at limit, got {r.status_code} {r.text}"
            assert "30" in r.text, r.text
        finally:
            db.ai_messages.delete_many({"user_id": user_id, "message_id": {"$regex": f"^msg_fake_{user_id}_"}})
            # revert plan so later tests see trial again if needed
            db.users.update_one({"user_id": user_id}, {"$set": {"plan": "free"}})


# ---------- Chat flow: send, follow-up, list, get, delete, cross-user ----------

class TestChatFlow:
    chat_id = None

    def test_01_quick_chat_aapl(self, trader_headers, db):
        status, events, err = _stream_chat(trader_headers, {
            "message": "Is $AAPL a good covered call right now? Keep it short.",
            "mode": "quick",
        }, timeout=90)
        assert status == 200, err
        assert events, "no SSE events"
        meta = next((e for e in events if e["type"] == "meta"), None)
        assert meta is not None, "no meta event"
        assert meta["model"] == "Claude Sonnet 5.5", meta
        assert any(t["ticker"] == "AAPL" for t in meta.get("tickers", [])), meta
        aapl_tick = next(t for t in meta["tickers"] if t["ticker"] == "AAPL")
        assert isinstance(aapl_tick.get("price"), (int, float)) and aapl_tick["price"] > 0, aapl_tick
        deltas = [e for e in events if e["type"] == "delta"]
        assert len(deltas) >= 1, "no delta events"
        done = next((e for e in events if e["type"] == "done"), None)
        assert done is not None, [e["type"] for e in events]
        assert "message_id" in done and done["message_id"].startswith("msg_")
        assert done["usage"]["limit"] == 30
        TestChatFlow.chat_id = meta["chat_id"]
        c = db.ai_chats.find_one({"chat_id": meta["chat_id"]})
        assert c is not None

    def test_02_followup_reuses_ticker(self, trader_headers):
        assert TestChatFlow.chat_id, "needs prior test"
        status, events, err = _stream_chat(trader_headers, {
            "message": "and what is the main risk?",
            "chat_id": TestChatFlow.chat_id,
            "mode": "quick",
        }, timeout=90)
        assert status == 200, err
        meta = next((e for e in events if e["type"] == "meta"), None)
        assert meta is not None
        tickers = [t["ticker"] for t in meta.get("tickers", [])]
        assert "AAPL" in tickers, f"follow-up should reuse AAPL, got {tickers}"

    def test_03_list_chats(self, trader_headers):
        r = requests.get(f"{BASE}/api/assistant/chats", headers=trader_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["chats"], list)
        assert body["models"] == {"quick": "Claude Sonnet 5.5", "deep": "Claude Opus 5.5"}
        assert "usage" in body
        # our chat should be present
        assert any(c["chat_id"] == TestChatFlow.chat_id for c in body["chats"])

    def test_04_get_chat_messages(self, trader_headers):
        assert TestChatFlow.chat_id
        r = requests.get(f"{BASE}/api/assistant/chats/{TestChatFlow.chat_id}", headers=trader_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        roles = [m["role"] for m in body["messages"]]
        assert "user" in roles and "assistant" in roles
        assert roles[0] == "user"
        for m in body["messages"]:
            assert isinstance(m.get("content", ""), str)

    def test_05_cross_user_404(self, trader_headers, trial_user):
        _, token, _ = trial_user
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{BASE}/api/assistant/chats/{TestChatFlow.chat_id}", headers=headers, timeout=15)
        assert r.status_code == 404, f"expected 404 (not found), got {r.status_code} {r.text}"

    def test_06_deep_mode_opus(self, trader_headers):
        r0 = requests.get(f"{BASE}/api/assistant/chats", headers=trader_headers, timeout=15)
        assert r0.status_code == 200
        before = r0.json()["usage"]["deep_used"]
        status, events, err = _stream_chat(trader_headers, {
            "message": "Deep look at AAPL: thesis, numbers, risks. Short.",
            "mode": "deep",
            "ticker": "AAPL",
        }, timeout=180)
        assert status == 200, err
        meta = next((e for e in events if e["type"] == "meta"), None)
        assert meta is not None
        assert meta["model"] == "Claude Opus 5.5", meta
        done = next((e for e in events if e["type"] == "done"), None)
        assert done is not None, [e["type"] for e in events]
        assert done["usage"]["deep_used"] == before + 1, (before, done["usage"])

    def test_07_delete_chat(self, trader_headers):
        status, events, _ = _stream_chat(trader_headers, {"message": "Hi, 2+2 only.", "mode": "quick"}, timeout=90)
        assert status == 200
        meta = next((e for e in events if e["type"] == "meta"), None)
        assert meta
        cid = meta["chat_id"]
        r = requests.delete(f"{BASE}/api/assistant/chats/{cid}", headers=trader_headers, timeout=15)
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{BASE}/api/assistant/chats/{cid}", headers=trader_headers, timeout=15)
        assert r2.status_code == 404, r2.text

        assert r.status_code == 200, r.text
        r2 = requests.get(f"{BASE}/api/assistant/chats/{cid}", headers=trader_headers, timeout=15)
        assert r2.status_code == 404, r2.text


# ---------- cleanup done in test_delete_chat + follow-up; TestQuickChat.chat_id cleaned manually post-run ----------
