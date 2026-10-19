"""Backend tests for forgot-password / change-email / logout revocation.

Uses `delivered+<label>@resend.dev` throwaway mailboxes, overrides `auth_codes.code_digest`
with a known-code HMAC to avoid sending many real emails.
"""
import os
import hmac
import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"].strip('"').strip("'")

API = f"{BASE_URL}/api"

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]
S = requests.Session()
S.headers["Content-Type"] = "application/json"


# ---------- helpers ----------
def _mail(label: str = "") -> str:
    return f"delivered+rc{label or uuid.uuid4().hex[:6]}@resend.dev"


def _signup_digest(email: str, code: str) -> str:
    return hmac.new(JWT_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _code_digest(doc_id: str, target_email: str, code: str) -> str:
    return hmac.new(JWT_SECRET.encode(), f"{doc_id}:{target_email}:{code}".encode(), hashlib.sha256).hexdigest()


def _cleanup(emails):
    for e in emails:
        for u in list(db.users.find({"email": e}, {"user_id": 1})):
            db.user_sessions.delete_many({"user_id": u["user_id"]})
            db.auth_codes.delete_many({"user_id": u["user_id"]})
        db.users.delete_many({"email": e})
        db.email_verifications.delete_many({"email": e})


def _create_verified_user(password: str = "StartPass9!", name: str = "QA"):
    """Create a verified user directly in Mongo (bypasses email sends)."""
    email = _mail()
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    t = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": user_id, "email": email, "name": name, "password": hashed,
        "plan": None, "questionnaire_complete": False, "consent_signed": False, "picture": None,
        "email_verified": True, "email_verified_at": t, "created_at": t,
    })
    # login to get a real session_token
    r = S.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return email, body["session_token"], body["user"]


# ================================================================
# FORGOT-PASSWORD
# ================================================================
class TestForgotPassword:
    @classmethod
    def setup_class(cls):
        cls.email, cls.token, cls.user = _create_verified_user(password="OrigPass9!")
        cls.user_id = cls.user["user_id"]

    @classmethod
    def teardown_class(cls):
        _cleanup([cls.email])

    def test_1_reset_request_known_email_202(self):
        r = S.post(f"{API}/auth/password-reset/request", json={"email": self.email})
        assert r.status_code == 202, r.text
        b = r.json()
        assert b["email"] == self.email
        assert b["attempts_left"] == 5
        assert 500 < b["expires_in"] <= 600
        # a code doc was created
        doc = db.auth_codes.find_one({"_id": f"password_reset:{self.user_id}"})
        assert doc is not None

    def test_2_reset_request_unknown_email_same_shape(self):
        unknown = _mail("unknown")
        r = S.post(f"{API}/auth/password-reset/request", json={"email": unknown})
        assert r.status_code == 202, r.text
        b = r.json()
        assert set(b.keys()) >= {"email", "resend_in", "expires_in", "attempts_left"}
        assert b["email"] == unknown
        # no user, no auth_codes created
        assert db.users.find_one({"email": unknown}) is None

    def test_3_second_request_within_60s_keeps_same_digest(self):
        before = db.auth_codes.find_one({"_id": f"password_reset:{self.user_id}"})
        assert before, "test ordering: expected code from test_1"
        r = S.post(f"{API}/auth/password-reset/request", json={"email": self.email})
        assert r.status_code == 202
        after = db.auth_codes.find_one({"_id": f"password_reset:{self.user_id}"})
        assert after["code_digest"] == before["code_digest"]
        assert after["sends"] == before["sends"]

    def test_4_wrong_code_countdown_then_lockout(self):
        # inject known code
        doc_id = f"password_reset:{self.user_id}"
        known = "246810"
        db.auth_codes.update_one({"_id": doc_id},
                                 {"$set": {"code_digest": _code_digest(doc_id, self.email, known), "attempts": 0}})
        for exp_left in (4, 3, 2, 1):
            r = S.post(f"{API}/auth/password-reset/confirm",
                       json={"email": self.email, "code": "000000", "new_password": "NewPass9!"})
            assert r.status_code == 400, r.text
            detail = r.json()["detail"]
            assert f"{exp_left}" in detail and "left" in detail.lower()
        # 5th wrong -> locked
        r5 = S.post(f"{API}/auth/password-reset/confirm",
                    json={"email": self.email, "code": "000000", "new_password": "NewPass9!"})
        assert r5.status_code == 400
        assert "too many" in r5.json()["detail"].lower()
        # even correct code rejected
        rc = S.post(f"{API}/auth/password-reset/confirm",
                    json={"email": self.email, "code": known, "new_password": "NewPass9!"})
        assert rc.status_code == 400
        assert "too many" in rc.json()["detail"].lower()

    def test_5_short_password_422(self):
        r = S.post(f"{API}/auth/password-reset/confirm",
                   json={"email": self.email, "code": "123456", "new_password": "abc"})
        assert r.status_code == 422

    def test_6_expired_code_returns_400(self):
        # reuse the code row from test_1 (don't call /request to avoid another email send)
        doc_id = f"password_reset:{self.user_id}"
        known = "778899"
        upd = db.auth_codes.update_one(
            {"_id": doc_id},
            {"$set": {"code_digest": _code_digest(doc_id, self.email, known),
                      "attempts": 0,
                      "expires_at": datetime.now(timezone.utc) - timedelta(seconds=5)}}
        )
        if upd.matched_count == 0:
            r = S.post(f"{API}/auth/password-reset/request", json={"email": self.email})
            assert r.status_code == 202
            db.auth_codes.update_one(
                {"_id": doc_id},
                {"$set": {"code_digest": _code_digest(doc_id, self.email, known), "attempts": 0,
                          "expires_at": datetime.now(timezone.utc) - timedelta(seconds=5)}}
            )
        r = S.post(f"{API}/auth/password-reset/confirm",
                   json={"email": self.email, "code": known, "new_password": "NewPass9!"})
        assert r.status_code == 400
        assert "expire" in r.json()["detail"].lower()

    def test_7_correct_code_signs_in_and_revokes_other_sessions(self):
        # Re-use the auth_codes row from test_6; just push expiry forward and inject known digest
        # to avoid another real email send (rate limited).
        doc_id = f"password_reset:{self.user_id}"
        known = "555666"
        upd = db.auth_codes.update_one(
            {"_id": doc_id},
            {"$set": {"code_digest": _code_digest(doc_id, self.email, known),
                      "attempts": 0,
                      "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)}}
        )
        # if somehow deleted, create fresh (may hit email rate limit)
        if upd.matched_count == 0:
            r = S.post(f"{API}/auth/password-reset/request", json={"email": self.email})
            assert r.status_code == 202, r.text
            db.auth_codes.update_one(
                {"_id": doc_id},
                {"$set": {"code_digest": _code_digest(doc_id, self.email, known), "attempts": 0}}
            )
        # ensure the old token still works right before reset
        me0 = S.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {self.__class__.token}"})
        assert me0.status_code == 200
        assert me0.json()["user"]["email"] == self.email
        # confirm
        new_pw = "NewPass123!"
        r = S.post(f"{API}/auth/password-reset/confirm",
                   json={"email": self.email, "code": known, "new_password": new_pw})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "session_token" in body and body["user"]["email"] == self.email
        new_token = body["session_token"]
        # old token revoked
        me1 = S.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {self.__class__.token}"})
        assert me1.status_code == 401
        # new token works
        me2 = S.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert me2.status_code == 200
        # old password no longer works
        lo = S.post(f"{API}/auth/login", json={"email": self.email, "password": "OrigPass9!"})
        assert lo.status_code == 401
        # new password works
        ln = S.post(f"{API}/auth/login", json={"email": self.email, "password": new_pw})
        assert ln.status_code == 200
        # code consumed, cannot be reused
        reuse = S.post(f"{API}/auth/password-reset/confirm",
                       json={"email": self.email, "code": known, "new_password": "AnotherPass9!"})
        assert reuse.status_code == 400


# ================================================================
# LOGOUT revocation (simple, user-isolated)
# ================================================================
class TestLogoutRevokes:
    """Uses the seeded trader account (login -> logout) to avoid new signup emails."""
    def test_logout_then_me_401(self):
        r = S.post(f"{API}/auth/login", json={"email": "trader@optiscreen.app", "password": "TestPass123!"})
        assert r.status_code == 200, r.text
        token = r.json()["session_token"]
        hdr = {"Authorization": f"Bearer {token}"}
        assert S.get(f"{API}/auth/me", headers=hdr).status_code == 200
        out = S.post(f"{API}/auth/logout", headers=hdr)
        assert out.status_code == 200
        me = S.get(f"{API}/auth/me", headers=hdr)
        assert me.status_code == 401, me.text


# ================================================================
# CHANGE-EMAIL
# ================================================================
class TestChangeEmail:
    @classmethod
    def setup_class(cls):
        cls.email, cls.token, cls.user = _create_verified_user(password="MyPass123!")
        cls.user_id = cls.user["user_id"]
        cls.new_email = _mail("new")
        cls.extra_emails_to_cleanup = [cls.new_email]

    @classmethod
    def teardown_class(cls):
        _cleanup([cls.email, cls.new_email] + cls.extra_emails_to_cleanup)

    def _hdr(self):
        return {"Authorization": f"Bearer {self.__class__.token}"}

    def test_1_request_wrong_password_400(self):
        r = S.post(f"{API}/auth/email-change/request",
                   json={"new_email": self.new_email, "current_password": "wrong"}, headers=self._hdr())
        assert r.status_code == 400
        assert "password" in r.json()["detail"].lower()

    def test_2_request_same_as_current_400(self):
        r = S.post(f"{API}/auth/email-change/request",
                   json={"new_email": self.email, "current_password": "MyPass123!"}, headers=self._hdr())
        assert r.status_code == 400

    def test_3_request_email_already_used_409(self):
        r = S.post(f"{API}/auth/email-change/request",
                   json={"new_email": "trader@optiscreen.app", "current_password": "MyPass123!"}, headers=self._hdr())
        assert r.status_code == 409

    def test_4_request_valid_returns_202(self):
        r = S.post(f"{API}/auth/email-change/request",
                   json={"new_email": self.new_email, "current_password": "MyPass123!"}, headers=self._hdr())
        assert r.status_code == 202, r.text
        b = r.json()
        assert b["email"] == self.new_email
        assert b["resend_in"] in range(55, 61)  # typically exactly 60
        doc = db.auth_codes.find_one({"_id": f"email_change:{self.user_id}"})
        assert doc and doc["target_email"] == self.new_email

    def test_5_resend_within_60s_returns_429(self):
        r = S.post(f"{API}/auth/email-change/resend", headers=self._hdr())
        assert r.status_code == 429
        assert "wait" in r.json()["detail"].lower()

    def test_6_confirm_wrong_code_400_tries_left(self):
        doc_id = f"email_change:{self.user_id}"
        known = "334455"
        db.auth_codes.update_one({"_id": doc_id},
                                 {"$set": {"code_digest": _code_digest(doc_id, self.new_email, known), "attempts": 0}})
        r = S.post(f"{API}/auth/email-change/confirm", json={"code": "000000"}, headers=self._hdr())
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "4" in detail and "left" in detail.lower()

    def test_7_confirm_correct_code_updates_email_and_sessions(self):
        doc_id = f"email_change:{self.user_id}"
        known = "334455"
        # keep same digest from previous test (attempt=1 now, still fine)
        r = S.post(f"{API}/auth/email-change/confirm", json={"code": known}, headers=self._hdr())
        assert r.status_code == 200, r.text
        assert r.json()["email"] == self.new_email
        # /auth/me shows new email (session for this user is still active - only password reset signs out)
        me = S.get(f"{API}/auth/me", headers=self._hdr())
        assert me.status_code == 200, me.text
        me_body = me.json()
        # /auth/me returns {user: {...}} or user object directly - handle both
        user_obj = me_body.get("user", me_body)
        assert user_obj.get("email") == self.new_email, f"got {me_body}"
        # login with new email works
        lg_new = S.post(f"{API}/auth/login", json={"email": self.new_email, "password": "MyPass123!"})
        assert lg_new.status_code == 200
        # login with old email fails
        lg_old = S.post(f"{API}/auth/login", json={"email": self.email, "password": "MyPass123!"})
        assert lg_old.status_code == 401

    def test_8_resend_no_pending_404(self):
        # code was consumed; resend should 404
        db.auth_codes.delete_many({"_id": f"email_change:{self.user_id}"})
        r = S.post(f"{API}/auth/email-change/resend", headers=self._hdr())
        assert r.status_code == 404


# ================================================================
# Regression: legacy seeded accounts still log in
# ================================================================
@pytest.mark.parametrize("email,pw", [
    ("trader@optiscreen.app", "TestPass123!"),
    ("lingesa4@gmail.com", "Linges1@12"),
])
def test_legacy_login_still_works(email, pw):
    r = S.post(f"{API}/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == email
