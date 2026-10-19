"""Forgot-password reset and change-email, both confirmed with a 6-digit emailed code.
Codes live in `auth_codes` with _id f"{purpose}:{user_id}" and digest key f"{_id}:{target_email}"."""
import asyncio
from typing import Optional

from fastapi import Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

import otp
from emailer import EMAIL_FROM_NAME

BAD_CODE = "This code is invalid or has expired. Tap “Resend code” to get a new one."
GOOGLE_EMAIL = "Your email is managed by your Google account and can't be changed here."
IN_USE = "That email is already used by another account."


class EmailReq(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=6, max_length=128)


class EmailChangeReq(BaseModel):
    new_email: EmailStr
    current_password: str = Field(min_length=1, max_length=128)


class CodeReq(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def register(router, *, db, hash_pw, verify_pw, get_user, start_session, logger):
    codes = db.auth_codes

    def notify_later(to: str, name: str, subject: str, lines: list):
        asyncio.create_task(otp.notify(to, name, subject, lines, logger))

    async def issue(purpose: str, user: dict, target: str, prev: Optional[dict], what: str, intro: str) -> dict:
        k = f"{purpose}:{user['user_id']}"
        doc = await otp.send_code(codes, {"_id": k, "purpose": purpose, "user_id": user["user_id"], "target_email": target},
                                  prev, to=target, name=user["name"], what=what, intro=intro, dkey=f"{k}:{target}", logger=logger)
        return otp.status(doc, target)

    # ---------- forgot password ----------
    RESET_INTRO = f"use this code in the {EMAIL_FROM_NAME} app to set a new password:"

    @router.post("/auth/password-reset/request", status_code=202)
    async def reset_request(req: EmailReq):
        email = req.email.lower()
        user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1, "name": 1, "password": 1})
        if not user or not user.get("password"):
            # same answer whether or not the account exists (no account discovery)
            return {"email": email, "resend_in": otp.RESEND_COOLDOWN, "expires_in": int(otp.CODE_TTL.total_seconds()),
                    "attempts_left": otp.MAX_ATTEMPTS}
        prev = await codes.find_one({"_id": f"password_reset:{user['user_id']}"})
        if otp.fresh(prev):
            return otp.status(prev, email)
        return await issue("password_reset", user, email, prev, "password reset", RESET_INTRO)

    @router.post("/auth/password-reset/confirm")
    async def reset_confirm(req: ResetConfirm):
        email = req.email.lower()
        user = await db.users.find_one({"email": email}, {"_id": 0})
        doc = await codes.find_one({"_id": f"password_reset:{user['user_id']}"}) if user else None
        if not doc or doc.get("target_email") != email:
            raise HTTPException(400, BAD_CODE)
        await otp.check_code(codes, doc, f"{doc['_id']}:{email}", req.code)
        await db.users.update_one({"user_id": user["user_id"]},
                                  {"$set": {"password": hash_pw(req.new_password), "password_changed_at": otp.now()}})
        await db.user_sessions.delete_many({"user_id": user["user_id"]})  # sign out every device
        logger.info(f"password reset: {email}")
        notify_later(email, user["name"], f"Your {EMAIL_FROM_NAME} password was reset", [
            f"Your {EMAIL_FROM_NAME} password was just reset and every device was signed out.",
            "If this wasn't you, reset your password again right away from the sign-in screen.",
        ])
        return await start_session(user)

    # ---------- change email (signed in) ----------
    CHANGE_INTRO = f"use this code in the {EMAIL_FROM_NAME} app to confirm this as your new email address:"

    async def me(authorization: Optional[str]) -> dict:
        u = await get_user(authorization)
        raw = await db.users.find_one({"user_id": u["user_id"]}, {"_id": 0, "user_id": 1, "email": 1, "name": 1, "password": 1})
        if not raw.get("password"):
            raise HTTPException(400, GOOGLE_EMAIL)
        return raw

    async def email_taken(email: str) -> bool:
        return bool(await db.users.find_one({"email": email}, {"_id": 1})
                    or await db.email_verifications.find_one({"email": email}, {"_id": 1}))

    @router.post("/auth/email-change/request", status_code=202)
    async def email_change_request(req: EmailChangeReq, authorization: Optional[str] = Header(default=None)):
        user = await me(authorization)
        if not verify_pw(req.current_password, user["password"]):
            raise HTTPException(400, "Current password is incorrect.")
        new = req.new_email.lower()
        if new == user["email"]:
            raise HTTPException(400, "That's already your email address.")
        if await email_taken(new):
            raise HTTPException(409, IN_USE)
        prev = await codes.find_one({"_id": f"email_change:{user['user_id']}"})
        if otp.fresh(prev) and prev.get("target_email") == new:
            return otp.status(prev, new)
        return await issue("email_change", user, new, prev, "email change", CHANGE_INTRO)

    @router.post("/auth/email-change/resend", status_code=202)
    async def email_change_resend(authorization: Optional[str] = Header(default=None)):
        user = await me(authorization)
        prev = await codes.find_one({"_id": f"email_change:{user['user_id']}"})
        if not prev:
            raise HTTPException(404, "No email change in progress. Start again from your Profile.")
        if otp.wait(prev) > 0:
            raise HTTPException(429, f"Please wait {otp.wait(prev)}s before requesting a new code.")
        return await issue("email_change", user, prev["target_email"], prev, "email change", CHANGE_INTRO)

    @router.post("/auth/email-change/confirm")
    async def email_change_confirm(req: CodeReq, authorization: Optional[str] = Header(default=None)):
        user = await me(authorization)
        doc = await codes.find_one({"_id": f"email_change:{user['user_id']}"})
        if not doc:
            raise HTTPException(400, BAD_CODE)
        new = doc["target_email"]
        await otp.check_code(codes, doc, f"{doc['_id']}:{new}", req.code)
        if await email_taken(new):
            raise HTTPException(409, IN_USE)
        old = user["email"]
        try:
            await db.users.update_one({"user_id": user["user_id"]},
                                      {"$set": {"email": new, "email_verified": True, "email_changed_at": otp.now(),
                                                "previous_email": old}})
        except DuplicateKeyError:
            raise HTTPException(409, IN_USE)
        logger.info(f"email changed: {old} -> {new}")
        notify_later(old, user["name"], f"Your {EMAIL_FROM_NAME} email address was changed", [
            f"The email address on your {EMAIL_FROM_NAME} account was changed to {new}.",
            f"From now on, sign in with {new}. If you didn't make this change, contact the {EMAIL_FROM_NAME} team right away.",
        ])
        return {"email": new}
