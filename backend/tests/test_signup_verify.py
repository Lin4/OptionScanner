"""Email-verified sign-up backend tests (register / resend / verify)."""
import os
import hmac
import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"].strip('"')

API = f"{BASE_URL}/api"

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]


def _label() -> str:
    return f"uitest{uuid.uuid4().hex[:8]}"


def _mail(label: str) -> str:
    return f"delivered+{label}@resend.dev"


def _digest(email: str, code: str) -> str:
    return hmac.new(JWT_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _cleanup(email: str):
    db.email_verifications.delete_many({"email": email})
    db.users.delete_many({"email": email})
    uids = [u["user_id"] for u in db.users.find({"email": email}, {"user_id": 1})]
    if uids:
        db.user_sessions.delete_many({"user_id": {"$in": uids}})


@pytest.fixture
def ephemeral_email():
    email = _mail(_label())
    yield email
    _cleanup(email)


S = requests.Session()
S.headers["Content-Type"] = "application/json"


# ---------- /auth/register ----------
def test_register_returns_202_and_only_creates_pending(ephemeral_email):
    r = S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "Secret12!", "name": "QA Bot"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["verification_required"] is True
    assert body["email"] == ephemeral_email
    assert body["attempts_left"] == 5
    assert 0 <= body["resend_in"] <= 60
    assert 500 < body["expires_in"] <= 600
    assert db.users.find_one({"email": ephemeral_email}) is None
    assert db.email_verifications.find_one({"email": ephemeral_email}) is not None


def test_register_invalid_email_422():
    r = S.post(f"{API}/auth/register", json={"email": "not-an-email", "password": "Secret12!"})
    assert r.status_code == 422


def test_register_short_password_422(ephemeral_email):
    r = S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "abc"})
    assert r.status_code == 422


def test_register_existing_user_rejected():
    r = S.post(f"{API}/auth/register", json={"email": "trader@optiscreen.app", "password": "whatever123"})
    assert r.status_code == 400
    assert "already registered" in r.json().get("detail", "").lower()


def test_login_pending_email_returns_403(ephemeral_email):
    S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "Secret12!"})
    r = S.post(f"{API}/auth/login", json={"email": ephemeral_email, "password": "Secret12!"})
    assert r.status_code == 403
    assert "verif" in r.json().get("detail", "").lower()


# ---------- /auth/register (re-register within cooldown) ----------
def test_rere_register_keeps_same_code_and_updates_password(ephemeral_email):
    r1 = S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "FirstPass1!"})
    assert r1.status_code == 202
    doc1 = db.email_verifications.find_one({"email": ephemeral_email})
    digest_before = doc1["code_digest"]
    pw_before = doc1["password"]

    r2 = S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "SecondPass2!"})
    assert r2.status_code == 202
    doc2 = db.email_verifications.find_one({"email": ephemeral_email})
    # code untouched during cooldown
    assert doc2["code_digest"] == digest_before
    # password refreshed
    assert doc2["password"] != pw_before


# ---------- /auth/register/resend ----------
def test_resend_cooldown_then_success(ephemeral_email):
    assert S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "Secret12!"}).status_code == 202
    r = S.post(f"{API}/auth/register/resend", json={"email": ephemeral_email})
    assert r.status_code == 429, r.text
    assert "wait" in r.json().get("detail", "").lower()

    # move last_sent_at >60s back
    db.email_verifications.update_one(
        {"email": ephemeral_email},
        {"$set": {"last_sent_at": datetime.now(timezone.utc) - timedelta(seconds=61)},
         "$inc": {"attempts": 3}},
    )
    old_digest = db.email_verifications.find_one({"email": ephemeral_email})["code_digest"]
    r2 = S.post(f"{API}/auth/register/resend", json={"email": ephemeral_email})
    assert r2.status_code == 202, r2.text
    assert r2.json()["attempts_left"] == 5
    new_doc = db.email_verifications.find_one({"email": ephemeral_email})
    assert new_doc["code_digest"] != old_digest
    assert new_doc["attempts"] == 0

    # old code must no longer work
    stale = S.post(f"{API}/auth/register/verify",
                   json={"email": ephemeral_email, "code": "000000"})
    assert stale.status_code in (400,)


def test_resend_unknown_email_404():
    r = S.post(f"{API}/auth/register/resend", json={"email": _mail(_label())})
    assert r.status_code == 404


# ---------- /auth/register/verify ----------
def test_verify_wrong_code_countdown_then_lockout(ephemeral_email):
    assert S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "Secret12!"}).status_code == 202
    # overwrite digest to known code so last correct-code assertion can succeed on resend step
    known_code = "123456"
    db.email_verifications.update_one({"email": ephemeral_email},
                                      {"$set": {"code_digest": _digest(ephemeral_email, known_code)}})
    expected_left = [4, 3, 2, 1]
    for exp in expected_left:
        r = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": "000000"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert f"{exp}" in detail and "left" in detail.lower()
    # 5th wrong try -> lockout
    r5 = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": "000000"})
    assert r5.status_code == 400
    assert "too many" in r5.json()["detail"].lower()
    # Even correct code rejected now
    rc = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": known_code})
    assert rc.status_code == 400
    assert "too many" in rc.json()["detail"].lower()


def test_verify_non_6_digit_422(ephemeral_email):
    assert S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "Secret12!"}).status_code == 202
    r = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": "12a456"})
    assert r.status_code == 422
    r2 = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": "12345"})
    assert r2.status_code == 422


def test_verify_expired_returns_400(ephemeral_email):
    assert S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "Secret12!"}).status_code == 202
    db.email_verifications.update_one({"email": ephemeral_email},
                                      {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=5)}})
    r = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": "123456"})
    assert r.status_code == 400
    assert "expire" in r.json()["detail"].lower()


def test_verify_success_full_flow(ephemeral_email):
    assert S.post(f"{API}/auth/register", json={"email": ephemeral_email, "password": "SecretPass9!", "name": "UI Tester"}).status_code == 202
    known = "246813"
    db.email_verifications.update_one({"email": ephemeral_email},
                                      {"$set": {"code_digest": _digest(ephemeral_email, known), "attempts": 0}})
    r = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": known})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == ephemeral_email
    assert body["user"]["email_verified"] is True
    token = body["session_token"]
    assert token

    # pending doc deleted; user exists
    assert db.email_verifications.find_one({"email": ephemeral_email}) is None
    assert db.users.find_one({"email": ephemeral_email}) is not None

    # reuse -> 404
    r2 = S.post(f"{API}/auth/register/verify", json={"email": ephemeral_email, "code": known})
    assert r2.status_code == 404

    # /auth/me works with token
    me = S.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == ephemeral_email

    # subsequent password login works
    lg = S.post(f"{API}/auth/login", json={"email": ephemeral_email, "password": "SecretPass9!"})
    assert lg.status_code == 200
    assert lg.json()["user"]["email_verified"] is True


# ---------- existing accounts untouched ----------
@pytest.mark.parametrize("email,pw", [
    ("trader@optiscreen.app", "TestPass123!"),
    ("lingesa4@gmail.com", "Linges1@12"),
])
def test_legacy_login_still_works(email, pw):
    r = S.post(f"{API}/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == email
