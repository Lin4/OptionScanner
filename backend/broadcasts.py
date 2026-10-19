"""Admin broadcasts: in-app announcements to all users or one plan tier (+ optional push)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, Literal, Optional

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

import billing

AUDIENCES = ("all", "trial", "simple", "advance", "expert", "expired")


class BroadcastReq(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    audience: Literal["all", "trial", "simple", "advance", "expert", "expired"] = "all"
    push: bool = False


def register(api_router, *, db, get_user: Callable, send_push: Callable, logger):

    async def require_admin(authorization: Optional[str]) -> Dict:
        user = await get_user(authorization)
        raw = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "is_admin": 1})
        if not (raw or {}).get("is_admin"):
            raise HTTPException(status_code=403, detail="Admin only")
        return user

    async def audience_ids(audience: str):
        users = await db.users.find({}, {"_id": 0, "user_id": 1, "plan": 1, "plan_expires_at": 1, "created_at": 1}).to_list(100000)
        return [u["user_id"] for u in users if audience == "all" or billing.compute_access(u)["tier"] == audience]

    def iso(d: Dict) -> Dict:
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    @api_router.post("/admin/broadcasts")
    async def create_broadcast(req: BroadcastReq, authorization: Optional[str] = Header(default=None)):
        admin = await require_admin(authorization)
        ids = await audience_ids(req.audience)
        doc = {"broadcast_id": f"bc_{uuid.uuid4().hex[:12]}", "title": req.title.strip(), "message": req.message.strip(),
               "audience": req.audience, "push": req.push, "active": True, "reach": len(ids),
               "created_by": admin["email"], "created_at": datetime.now(timezone.utc)}
        await db.broadcasts.insert_one(doc)
        doc.pop("_id", None)
        pushed = False
        if req.push and ids:
            try:
                await send_push(recipients=ids, data={"title": doc["title"], "message": doc["message"], "action_url": "/(tabs)"})
                pushed = True
            except Exception as ex:
                logger.info(f"broadcast push skipped: {ex}")
        return {**iso(doc), "pushed": pushed}

    @api_router.get("/admin/broadcasts")
    async def list_broadcasts(authorization: Optional[str] = Header(default=None)):
        await require_admin(authorization)
        rows = await db.broadcasts.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
        for r in rows:
            r["dismissed"] = await db.broadcast_reads.count_documents({"broadcast_id": r["broadcast_id"]})
            iso(r)
        return {"items": rows}

    @api_router.delete("/admin/broadcasts/{bid}")
    async def end_broadcast(bid: str, authorization: Optional[str] = Header(default=None)):
        await require_admin(authorization)
        r = await db.broadcasts.update_one({"broadcast_id": bid}, {"$set": {"active": False}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Broadcast not found")
        return {"ok": True}

    @api_router.get("/announcements")
    async def my_announcements(authorization: Optional[str] = Header(default=None)):
        user = await get_user(authorization)
        raw = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0}) or user
        tier = billing.compute_access(raw)["tier"]
        seen = {r["broadcast_id"] for r in await db.broadcast_reads.find({"user_id": user["user_id"]}, {"_id": 0, "broadcast_id": 1}).to_list(1000)}
        rows = await db.broadcasts.find({"active": True, "audience": {"$in": ["all", tier]}},
                                        {"_id": 0, "broadcast_id": 1, "title": 1, "message": 1, "created_at": 1}).sort("created_at", -1).to_list(20)
        return {"items": [iso(r) for r in rows if r["broadcast_id"] not in seen]}

    @api_router.post("/announcements/{bid}/dismiss")
    async def dismiss(bid: str, authorization: Optional[str] = Header(default=None)):
        user = await get_user(authorization)
        if not await db.broadcasts.find_one({"broadcast_id": bid}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Announcement not found")
        await db.broadcast_reads.update_one({"user_id": user["user_id"], "broadcast_id": bid},
                                            {"$setOnInsert": {"at": datetime.now(timezone.utc)}}, upsert=True)
        return {"ok": True}
