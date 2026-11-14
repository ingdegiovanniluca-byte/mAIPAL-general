"""The app's own notifications (Web Push): they arrive on the phone or the computer also with
mAIPAL closed, once the user turned them on for that device (Impostazioni > Notifiche).

Which kinds arrive (and whether in the app, on Telegram or both) each user chooses in
Impostazioni > Notifiche (notify_prefs). Each device is a subscription ({endpoint, keys}) of one user; a device that
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
    same = await db.push_subscriptions.find_one({"endpoint": endpoint, "user_id": user_id}, {"_id": 0})
    if same:   # the app said it again (it does at every start): the keys and the device, the rest kept
        upd = {"keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}, "user_agent": (user_agent or same.get("user_agent") or "")[:200], "seen_at": now}
        await db.push_subscriptions.update_one({"endpoint": endpoint, "user_id": user_id}, {"$set": upd})
        return {**same, **upd}
    # one device = one endpoint: signing in with another account on it moves it there
    await db.push_subscriptions.delete_many({"endpoint": endpoint})
    doc = {"id": f"push_{uuid.uuid4().hex[:12]}", "user_id": user_id, "endpoint": endpoint,
           "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}, "user_agent": (user_agent or "")[:200], "created_at": now}
    await db.push_subscriptions.insert_one(dict(doc))
    return doc


async def unsubscribe(db, user_id: str, endpoint: str) -> None:
    await db.push_subscriptions.delete_many({"user_id": user_id, "endpoint": endpoint})


def vapid_subject() -> str:
    """Who sends (the VAPID "sub"): one clean mailto: or https: address. Apple's push service (iPhone,
    iPad, Safari) refuses the notifications when it isn't (a space, quotes, two addresses in
    ADMIN_EMAIL), while Google's accepts them - "on Android they arrive, on the iPhone not"."""
    import re
    raw = (os.environ.get("VAPID_SUBJECT") or os.environ.get("ADMIN_EMAIL") or "").strip().strip("'\"")
    first = re.split(r"[,;\s]+", raw)[0] if raw else ""
    if re.fullmatch(r"https://[^\s/]+(?:/\S*)?", first):
        return first
    first = first[len("mailto:"):] if first.lower().startswith("mailto:") else first
    if re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[a-zA-Z]{2,}", first):
        return "mailto:" + first.lower()
    base = (os.environ.get("APP_BASE_URL") or "").strip().strip("'\"")
    m = re.match(r"https://[^/\s]+", base)
    return m.group(0) if m else "mailto:ingdegiovanniluca@gmail.com"


def _send_one(sub: dict, payload: str, private_pem: str, claims_sub: str):
    from pywebpush import webpush
    from py_vapid import Vapid02   # RFC 8292 ("vapid t=..., k=..."), what Apple and the others expect
    return webpush(subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]}, data=payload,
                   vapid_private_key=Vapid02.from_pem(private_pem.encode()), vapid_claims={"sub": claims_sub}, ttl=6 * 3600,
                   headers={"Urgency": "high"})   # delivered at once, also with the phone saving battery


def device_label(user_agent: str, endpoint: str = "") -> dict:
    """Which device and which push service ("iPhone" / "Apple"): said in Impostazioni > Notifiche,
    so a notification that reaches the Android phone and not the iPhone shows why."""
    ua = (user_agent or "").lower()
    device = ("iPhone" if "iphone" in ua else "iPad" if "ipad" in ua else "Android" if "android" in ua
              else "Mac" if "macintosh" in ua or "mac os x" in ua else "Windows" if "windows" in ua else "Linux" if "linux" in ua else "Dispositivo")
    host = (endpoint or "").split("/")[2] if (endpoint or "").count("/") >= 2 else ""
    service = ("Apple" if "push.apple.com" in host else "Google" if "googleapis.com" in host else "Mozilla" if "mozilla" in host
               else "Microsoft" if "windows.com" in host else host or "?")
    return {"device": device, "service": service}


async def _record(db, user_id: str, title: str, devices: int, sent: int, errors: list, detail: Optional[list] = None) -> None:
    """The last sending of each user, shown in Impostazioni > Notifiche: when nothing arrives,
    the user (and whoever helps them) sees why - no device, a device gone, an error."""
    logger.info("web push to %s: %d/%d device(s) - %s%s", user_id, sent, devices, title[:60], f" - {errors}" if errors else "")
    try:
        await db.push_log.update_one({"user_id": user_id}, {"$set": {
            "user_id": user_id, "at": datetime.now(timezone.utc).isoformat(), "title": title[:120],
            "devices": devices, "sent": sent, "errors": errors[:5], "detail": (detail or [])[:10]}}, upsert=True)
    except Exception:
        logger.exception("web push log failed")


async def last_sending(db, user_id: str) -> Optional[dict]:
    return await db.push_log.find_one({"user_id": user_id}, {"_id": 0})


async def send_to_user(db, user_id: str, title: str, body: str, url: str = "/dashboard", tag: Optional[str] = None) -> int:
    """To every device of the user that turned notifications on. -> how many got it."""
    subs = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(20)
    if not subs:
        await _record(db, user_id, title, 0, 0, [])
        return 0
    keys = await vapid_keys(db)
    claims_sub = vapid_subject()
    payload = json.dumps({"title": title, "body": body[:240], "url": url, "tag": tag}, ensure_ascii=False)
    sent, errors, per_device = 0, [], []
    for sub in subs:
        who = device_label(sub.get("user_agent") or "", sub["endpoint"])
        try:
            await asyncio.to_thread(_send_one, sub, payload, keys["private_pem"], claims_sub)
            sent += 1
            per_device.append({**who, "ok": True})
        except Exception as e:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
            if status in (404, 410):   # the device unsubscribed or the browser data was cleared
                await db.push_subscriptions.delete_many({"endpoint": sub["endpoint"]})
                errors.append(f"{who['device']}: non è più iscritto ed è stato tolto, riattiva le notifiche su quel dispositivo")
                per_device.append({**who, "ok": False, "error": f"non più iscritto ({status}): riattivale lì"})
            else:
                detail = (getattr(resp, "text", "") or str(e) or type(e).__name__).strip().replace("\n", " ")
                logger.warning("web push to %s/%s failed (%s): %s", who["device"], who["service"], status, detail[:300])
                errors.append(f"{who['device']} ({who['service']}): errore {status or type(e).__name__}: {detail[:160]}")
                per_device.append({**who, "ok": False, "error": f"errore {status or type(e).__name__}: {detail[:160]}"})
    await _record(db, user_id, title, len(subs), sent, errors, per_device)
    return sent


_running: set = set()   # the tasks in flight: a task nobody refers to can be collected before it ends


def fire_and_forget(db, user_id: str, title: str, body: str, url: str = "/dashboard", tag: Optional[str] = None,
                    kind: Optional[str] = None) -> None:
    """Sent in the background; with a kind, only if the user wants that kind in the app (notify_prefs)."""
    async def run():
        try:
            import notify_prefs as nprefs
            if not await nprefs.wants(db, user_id, kind, "app"):
                return
            await send_to_user(db, user_id, title, body, url, tag)
        except Exception:
            logger.exception("web push failed")
    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        return
    _running.add(task)
    task.add_done_callback(_running.discard)
