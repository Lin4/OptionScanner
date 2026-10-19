"""Email-verified sign-up: register -> 6-digit code by email -> verify -> account is created.
Pending sign-ups live in `email_verifications` (code stored as an HMAC digest of f"{email}:{code}")."""
import uuid
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field

import otp
from emailer import EMAIL_FROM_NAME

NOT_FOUND = "No sign-up is waiting for this email. Please create your account again."
INTRO = f"welcome! Use this code in the {EMAIL_FROM_NAME} app to finish creating your account:"


class SignupReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: Optional[str] = Field(default=None, max_length=80)


class EmailReq(BaseModel):
    email: EmailStr


class VerifyReq(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


async def ensure_indexes(db):
    await db.email_verifications.create_index("email", unique=True)
    await db.email_verifications.create_index("purge_at", expireAfterSeconds=0)
    await db.auth_codes.create_index("purge_at", expireAfterSeconds=0)


def register(router, *, db, hash_pw, start_session, logger):
    pending = db.email_verifications

    def _status(doc: dict) -> dict:
        return {"verification_required": True, **otp.status(doc, doc["email"])}

    async def issue(base: dict, prev: Optional[dict]) -> dict:
        doc = await otp.send_code(pending, {"_id": prev["_id"] if prev else uuid.uuid4().hex, **base}, prev,
                                  to=base["email"], name=base["name"], what="verification", intro=INTRO,
                                  dkey=base["email"], logger=logger)
        return _status(doc)

    @router.post("/auth/register", status_code=202)
    async def start_signup(req: SignupReq):
        email = req.email.lower()
        if await db.users.find_one({"email": email}, {"_id": 1}):
            raise HTTPException(400, "Email already registered — please sign in instead")
        base = {"email": email, "name": (req.name or "").strip() or email.split("@")[0], "password": hash_pw(req.password)}
        prev = await pending.find_one({"email": email})
        if otp.fresh(prev):
            # code just sent: keep it valid, latest name/password win
            await pending.update_one({"email": email}, {"$set": base})
            return _status({**prev, **base})
        return await issue(base, prev)

    @router.post("/auth/register/resend", status_code=202)
    async def resend_code(req: EmailReq):
        prev = await pending.find_one({"email": req.email.lower()})
        if not prev:
            raise HTTPException(404, NOT_FOUND)
        if otp.wait(prev) > 0:
            raise HTTPException(429, f"Please wait {otp.wait(prev)}s before requesting a new code.")
        return await issue({k: prev[k] for k in ("email", "name", "password")}, prev)

    @router.post("/auth/register/verify")
    async def verify_code(req: VerifyReq):
        email = req.email.lower()
        doc = await pending.find_one({"email": email})
        if not doc:
            raise HTTPException(404, NOT_FOUND)
        await otp.check_code(pending, doc, email, req.code)
        if await db.users.find_one({"email": email}, {"_id": 1}):
            raise HTTPException(400, "Email already registered — please sign in instead")
        t = otp.now()
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
            "email_verified_at": t,
            "created_at": t,
        }
        await db.users.insert_one(user)
        logger.info(f"signup verified: {email}")
        return await start_session(user)
