"""The app's own notifications (Web Push): they arrive on the phone or the computer also with
mAIPAL closed, once the user turned them on for that device (Impostazioni > Notifiche).

Only two kinds, by design: what an external collaborator writes in a commessa's diary, and the
tasks' reminders. Each device is a subscription ({endpoint, keys}) of one user; a device that
is gone (404/410 from the push service) is forgotten. The VAPID keys come from the environment
(VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY) or, the first time, are made and kept in the database.
"""
import asyncio
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_keys: Optional[dict] = None


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


async def vapid_keys(db) -> dict:
    """{"public": applicationServerKey (base64url), "private_pem": str}"""
    global _keys
    if _keys:
        return _keys
    pub, priv = os.environ.get("VAPID_PUBLIC_KEY"), os.environ.get("VAPID_PRIVATE_KEY")
    if pub and priv:
        _keys = {"public": pub.strip(), "private_pem": priv.replace("\\n", "\n").strip()}
        return _keys
    doc = await db.app_settings.find_one({"key": "vapid"}, {"_id": 0})
    if not doc:
        from py_vapid import Vapid01
        from cryptography.hazmat.primitives import serialization
        v = Vapid01()
        v.generate_keys()
        doc = {"key": "vapid", "created_at": datetime.now(timezone.utc).isoformat(),
               "public": _b64url(v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
               "private_pem": v.private_pem().decode()}
        await db.app_settings.insert_one(dict(doc))
        doc.pop("_id", None)
    _keys = {"public": doc["public"], "private_pem": doc["private_pem"]}
    return _keys


async def subscribe(db, user_id: str, sub: dict, user_agent: str = "") -> dict:
    endpoint = (sub or {}).get("endpoint")
    keys = (sub or {}).get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Iscrizione alle notifiche non valida")
    now = datetime.now(timezone.utc).isoformat()
    # one device = one endpoint: signing in with another account on it moves it there
    await db.push_subscriptions.delete_many({"endpoint": endpoint})
    doc = {"id": f"push_{uuid.uuid4().hex[:12]}", "user_id": user_id, "endpoint": endpoint,
           "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}, "user_agent": (user_agent or "")[:200], "created_at": now}
    await db.push_subscriptions.insert_one(dict(doc))
    return doc


async def unsubscribe(db, user_id: str, endpoint: str) -> None:
    await db.push_subscriptions.delete_many({"user_id": user_id, "endpoint": endpoint})


def _send_one(sub: dict, payload: str, private_pem: str, claims_sub: str):
    from pywebpush import webpush
    from py_vapid import Vapid02   # RFC 8292 ("vapid t=..., k=..."), what Apple and the others expect
    return webpush(subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]}, data=payload,
                   vapid_private_key=Vapid02.from_pem(private_pem.encode()), vapid_claims={"sub": claims_sub}, ttl=6 * 3600)


async def send_to_user(db, user_id: str, title: str, body: str, url: str = "/dashboard", tag: Optional[str] = None) -> int:
    """To every device of the user that turned notifications on. -> how many got it."""
    subs = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(20)
    if not subs:
        return 0
    keys = await vapid_keys(db)
    claims_sub = "mailto:" + (os.environ.get("ADMIN_EMAIL") or "ingdegiovanniluca@gmail.com")
    payload = json.dumps({"title": title, "body": body[:240], "url": url, "tag": tag}, ensure_ascii=False)
    sent = 0
    for sub in subs:
        try:
            await asyncio.to_thread(_send_one, sub, payload, keys["private_pem"], claims_sub)
            sent += 1
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):   # the device unsubscribed or the browser data was cleared
                await db.push_subscriptions.delete_many({"endpoint": sub["endpoint"]})
            else:
                logger.warning("web push failed (%s): %s", status, str(e)[:200])
    return sent


def fire_and_forget(db, user_id: str, title: str, body: str, url: str = "/dashboard", tag: Optional[str] = None) -> None:
    async def run():
        try:
            await send_to_user(db, user_id, title, body, url, tag)
        except Exception:
            logger.exception("web push failed")
    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        pass
