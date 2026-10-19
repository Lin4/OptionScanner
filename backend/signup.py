"""Email-verified sign-up: register -> 6-digit code by email -> verify -> account is created.
Pending sign-ups live in `email_verifications` (code stored as an HMAC digest, never in plain text)."""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument

from emailer import send_email, EMAIL_FROM_NAME

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = 60          # seconds
MAX_ATTEMPTS = 5              # wrong tries per code
MAX_SENDS_PER_HOUR = 6
PURGE_AFTER = timedelta(hours=24)  # abandoned sign-ups are removed by a TTL index
PEPPER = os.environ.get("JWT_SECRET", "dev-secret")
NOT_FOUND = "No sign-up is waiting for this email. Please create your account again."


class SignupReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: Optional[str] = Field(default=None, max_length=80)


class EmailReq(BaseModel):
    email: EmailStr


class VerifyReq(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _digest(email: str, code: str) -> str:
    return hmac.new(PEPPER.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _wait(doc: dict) -> int:
    return max(0, RESEND_COOLDOWN - int((_now() - _aware(doc["last_sent_at"])).total_seconds()))


def _status(doc: dict) -> dict:
    return {"verification_required": True, "email": doc["email"], "resend_in": _wait(doc),
            "expires_in": max(0, int((_aware(doc["expires_at"]) - _now()).total_seconds())),
            "attempts_left": MAX_ATTEMPTS - doc.get("attempts", 0)}


def _email_html(code: str, name: str) -> str:
    brand = escape(EMAIL_FROM_NAME)
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6FA;padding:24px 0">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:480px;background:#FFFFFF;border-radius:12px;font-family:Arial,Helvetica,sans-serif;color:#0F172A">'
        f'<tr><td style="padding:28px 28px 8px 28px;font-size:20px;font-weight:bold">{brand}</td></tr>'
        f'<tr><td style="padding:8px 28px;font-size:15px;line-height:22px">Hi {escape(name)}, welcome! '
        f'Use this code in the {brand} app to finish creating your account:</td></tr>'
        f'<tr><td align="center" style="padding:20px 28px"><div style="display:inline-block;background:#EEF2FF;border-radius:10px;'
        f'padding:14px 24px;font-size:32px;letter-spacing:8px;font-weight:bold;color:#1E3A8A">{escape(code)}</div></td></tr>'
        '<tr><td style="padding:0 28px 8px 28px;font-size:13px;line-height:20px;color:#475569">'
        'The code expires in 10 minutes. If you did not sign up, you can safely ignore this email.</td></tr>'
        f'<tr><td style="padding:16px 28px 28px 28px;font-size:11px;color:#94A3B8">Sent by {brand}. '
        'We never ask for your password or payment details by email.</td></tr>'
        '</table></td></tr></table>'
    )


async def ensure_indexes(db):
    await db.email_verifications.create_index("email", unique=True)
    await db.email_verifications.create_index("purge_at", expireAfterSeconds=0)


def register(router, *, db, hash_pw, start_session, logger):
    pending = db.email_verifications

    async def issue_code(base: dict, prev: Optional[dict]) -> dict:
        now = _now()
        in_window = bool(prev) and now - _aware(prev.get("window_start", now)) < timedelta(hours=1)
        sends = prev.get("sends", 0) if in_window else 0
        if sends >= MAX_SENDS_PER_HOUR:
            raise HTTPException(429, "Too many codes requested for this email. Please try again in an hour.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        doc = {**base, "code_digest": _digest(base["email"], code), "expires_at": now + CODE_TTL,
               "last_sent_at": now, "attempts": 0, "sends": sends + 1,
               "window_start": _aware(prev["window_start"]) if in_window else now, "purge_at": now + PURGE_AFTER}
        await pending.replace_one({"email": base["email"]}, doc, upsert=True)
        try:
            await send_email(to=base["email"], subject=f"{code} is your {EMAIL_FROM_NAME} verification code",
                             html=_email_html(code, base["name"]))
        except HTTPException:
            # not delivered -> let the user retry right away
            await pending.update_one({"email": base["email"]},
                                     {"$set": {"last_sent_at": now - timedelta(seconds=RESEND_COOLDOWN)}})
            raise
        doc["last_sent_at"] = _now()  # cooldown starts once the email is actually out
        await pending.update_one({"email": base["email"]}, {"$set": {"last_sent_at": doc["last_sent_at"]}})
        logger.info(f"signup code sent to {base['email']}")
        return _status(doc)

    @router.post("/auth/register", status_code=202)
    async def start_signup(req: SignupReq):
        email = req.email.lower()
        if await db.users.find_one({"email": email}, {"_id": 1}):
            raise HTTPException(400, "Email already registered — please sign in instead")
        base = {"email": email, "name": (req.name or "").strip() or email.split("@")[0], "password": hash_pw(req.password)}
        prev = await pending.find_one({"email": email})
        if prev and _wait(prev) > 0 and _aware(prev["expires_at"]) > _now():
            # code just sent: keep it valid, latest name/password win
            await pending.update_one({"email": email}, {"$set": base})
            return _status({**prev, **base})
        return await issue_code(base, prev)

    @router.post("/auth/register/resend", status_code=202)
    async def resend_code(req: EmailReq):
        email = req.email.lower()
        prev = await pending.find_one({"email": email})
        if not prev:
            raise HTTPException(404, NOT_FOUND)
        if _wait(prev) > 0:
            raise HTTPException(429, f"Please wait {_wait(prev)}s before requesting a new code.")
        return await issue_code({k: prev[k] for k in ("email", "name", "password")}, prev)

    @router.post("/auth/register/verify")
    async def verify_code(req: VerifyReq):
        email = req.email.lower()
        doc = await pending.find_one({"email": email})
        if not doc:
            raise HTTPException(404, NOT_FOUND)
        if _aware(doc["expires_at"]) <= _now():
            raise HTTPException(400, "This code has expired. Tap “Resend code” to get a new one.")
        if not hmac.compare_digest(doc["code_digest"], _digest(email, req.code)):
            upd = await pending.find_one_and_update({"_id": doc["_id"], "attempts": {"$lt": MAX_ATTEMPTS}},
                                                    {"$inc": {"attempts": 1}}, return_document=ReturnDocument.AFTER)
            left = MAX_ATTEMPTS - upd["attempts"] if upd else 0
            if left <= 0:
                raise HTTPException(400, "Too many wrong tries. Tap “Resend code” to get a new code.")
            raise HTTPException(400, f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.")
        if doc.get("attempts", 0) >= MAX_ATTEMPTS:
            raise HTTPException(400, "Too many wrong tries. Tap “Resend code” to get a new code.")
        gone = await pending.delete_one({"_id": doc["_id"], "code_digest": doc["code_digest"]})
        if gone.deleted_count != 1:
            raise HTTPException(400, "This code was already used.")
        if await db.users.find_one({"email": email}, {"_id": 1}):
            raise HTTPException(400, "Email already registered — please sign in instead")
        now = _now()
        user = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": email,
            "name": doc["name"],
            "password": doc["password"],
            "plan": None,
            "questionnaire_complete": False,
            "consent_signed": False,
            "picture": None,
            "email_verified": True,
            "email_verified_at": now,
            "created_at": now,
        }
        await db.users.insert_one(user)
        logger.info(f"signup verified: {email}")
        return await start_session(user)
