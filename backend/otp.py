"""Shared 6-digit email-code machinery (sign-up, password reset, email change).
Codes are stored only as HMAC digests: 10-min expiry, 60s resend cooldown, 5 wrong tries, 6 sends/hour."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from typing import List, Optional

from fastapi import HTTPException
from pymongo import ReturnDocument

from emailer import send_email, EMAIL_FROM_NAME

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = 60          # seconds
MAX_ATTEMPTS = 5              # wrong tries per code
MAX_SENDS_PER_HOUR = 6
PURGE_AFTER = timedelta(hours=24)  # abandoned codes are removed by a TTL index on purge_at
PEPPER = os.environ.get("JWT_SECRET", "dev-secret")

EXPIRED = "This code has expired. Tap “Resend code” to get a new one."
LOCKED = "Too many wrong tries. Tap “Resend code” to get a new code."


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def digest(dkey: str, code: str) -> str:
    return hmac.new(PEPPER.encode(), f"{dkey}:{code}".encode(), hashlib.sha256).hexdigest()


def wait(doc: dict) -> int:
    return max(0, RESEND_COOLDOWN - int((now() - aware(doc["last_sent_at"])).total_seconds()))


def fresh(doc: Optional[dict]) -> bool:
    """A code was sent less than a minute ago and is still valid -> don't send another."""
    return bool(doc) and wait(doc) > 0 and aware(doc["expires_at"]) > now()


def status(doc: dict, email: str) -> dict:
    return {"email": email, "resend_in": wait(doc),
            "expires_in": max(0, int((aware(doc["expires_at"]) - now()).total_seconds())),
            "attempts_left": MAX_ATTEMPTS - doc.get("attempts", 0)}


def _shell(rows: str) -> str:
    brand = escape(EMAIL_FROM_NAME)
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6FA;padding:24px 0">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:480px;background:#FFFFFF;border-radius:12px;font-family:Arial,Helvetica,sans-serif;color:#0F172A">'
        f'<tr><td style="padding:28px 28px 8px 28px;font-size:20px;font-weight:bold">{brand}</td></tr>'
        f'{rows}'
        f'<tr><td style="padding:16px 28px 28px 28px;font-size:11px;color:#94A3B8">Sent by {brand}. '
        'We never ask for your password or payment details by email.</td></tr>'
        '</table></td></tr></table>'
    )


def code_email_html(code: str, name: str, intro: str) -> str:
    return _shell(
        f'<tr><td style="padding:8px 28px;font-size:15px;line-height:22px">Hi {escape(name)}, {escape(intro)}</td></tr>'
        f'<tr><td align="center" style="padding:20px 28px"><div style="display:inline-block;background:#EEF2FF;border-radius:10px;'
        f'padding:14px 24px;font-size:32px;letter-spacing:8px;font-weight:bold;color:#1E3A8A">{escape(code)}</div></td></tr>'
        '<tr><td style="padding:0 28px 8px 28px;font-size:13px;line-height:20px;color:#475569">'
        'The code expires in 10 minutes. If you did not request it, you can safely ignore this email.</td></tr>'
    )


def notice_email_html(name: str, lines: List[str]) -> str:
    body = "".join(f'<tr><td style="padding:6px 28px;font-size:15px;line-height:22px">{escape(t)}</td></tr>' for t in lines)
    return _shell(f'<tr><td style="padding:8px 28px;font-size:15px;line-height:22px">Hi {escape(name)},</td></tr>{body}')


async def send_code(coll, base: dict, prev: Optional[dict], *, to: str, name: str, what: str, intro: str, dkey: str, logger) -> dict:
    """Create/replace the code document (`base` must contain `_id`) and email a fresh code to `to`."""
    t = now()
    in_window = bool(prev) and t - aware(prev.get("window_start", t)) < timedelta(hours=1)
    sends = prev.get("sends", 0) if in_window else 0
    if sends >= MAX_SENDS_PER_HOUR:
        raise HTTPException(429, "Too many codes requested. Please try again in an hour.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    doc = {**base, "code_digest": digest(dkey, code), "expires_at": t + CODE_TTL, "last_sent_at": t, "attempts": 0,
           "sends": sends + 1, "window_start": aware(prev["window_start"]) if in_window else t, "purge_at": t + PURGE_AFTER}
    await coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    try:
        await send_email(to=to, subject=f"{code} is your {EMAIL_FROM_NAME} {what} code", html=code_email_html(code, name, intro))
    except HTTPException:
        # not delivered -> let the user retry right away
        await coll.update_one({"_id": doc["_id"]}, {"$set": {"last_sent_at": t - timedelta(seconds=RESEND_COOLDOWN)}})
        raise
    doc["last_sent_at"] = now()  # cooldown starts once the email is actually out
    await coll.update_one({"_id": doc["_id"]}, {"$set": {"last_sent_at": doc["last_sent_at"]}})
    logger.info(f"{what} code sent to {to}")
    return doc


async def check_code(coll, doc: dict, dkey: str, code: str) -> None:
    """Raise a friendly 400 unless `code` matches; on success the code is consumed (single use)."""
    if aware(doc["expires_at"]) <= now():
        raise HTTPException(400, EXPIRED)
    if doc.get("attempts", 0) >= MAX_ATTEMPTS:
        raise HTTPException(400, LOCKED)
    if not hmac.compare_digest(doc["code_digest"], digest(dkey, code)):
        upd = await coll.find_one_and_update({"_id": doc["_id"], "attempts": {"$lt": MAX_ATTEMPTS}},
                                             {"$inc": {"attempts": 1}}, return_document=ReturnDocument.AFTER)
        left = MAX_ATTEMPTS - upd["attempts"] if upd else 0
        if left <= 0:
            raise HTTPException(400, LOCKED)
        raise HTTPException(400, f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.")
    gone = await coll.delete_one({"_id": doc["_id"], "code_digest": doc["code_digest"]})
    if gone.deleted_count != 1:
        raise HTTPException(400, "This code was already used.")


async def notify(to: str, name: str, subject: str, lines: List[str], logger) -> None:
    """Best-effort security notice; never blocks the user's action."""
    try:
        await send_email(to=to, subject=subject, html=notice_email_html(name, lines))
    except HTTPException as ex:
        logger.warning(f"notice to {to} not sent: {ex.detail}")
