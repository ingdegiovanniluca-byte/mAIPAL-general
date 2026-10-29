"""The clients on the shared Telegram bot: they link with the code of the owner's invitation
and from then only receive the weekly progress of their works. Whatever they write gets a
fixed answer (no assistant: they never read the diary); /stop and /start turn it off and on.
"""
import logging
from datetime import datetime, timezone

from telegram import Update

logger = logging.getLogger(__name__)

ONLY_UPDATES = ("Questo canale serve solo a ricevere gli aggiornamenti settimanali sui lavori: per qualsiasi domanda "
                "contatti direttamente {owner}. Scriva /stop per non ricevere più gli aggiornamenti.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _owner_name(db, link: dict) -> str:
    u = await db.users.find_one({"user_id": link.get("owner_user_id")}, {"_id": 0, "name": 1}) or {}
    return u.get("name") or "l'impresa"


async def try_link(update: Update, code: str) -> bool:
    """/start CODE with a client's code -> linked. False when the code is not a client's."""
    from server import db, _notify_owner, User
    link = await db.client_links.find_one({"code": (code or "").strip().upper()}, {"_id": 0})
    if not link:
        return False
    chat_id = update.effective_chat.id
    reply = update.message.reply_text
    if not link.get("code_expires_at") or link["code_expires_at"] < _now():
        await reply("⏳ Il link è scaduto: chiedi un nuovo invito a chi ti segue i lavori.")
        return True
    if await db.users.find_one({"telegram_chat_id": chat_id}, {"_id": 1}) \
            or await db.collaborators.find_one({"telegram_chat_id": chat_id}, {"_id": 1}):
        await reply("Questo account Telegram è già collegato a mAIPAL in un altro modo: per gli aggiornamenti sui lavori usa un altro account.")
        return True
    await db.client_links.update_one({"id": link["id"]}, {"$set": {"telegram_chat_id": chat_id, "status": "active", "linked_at": _now(),
                                                                   "code": None, "code_expires_at": None}})
    owner = await _owner_name(db, link)
    await reply(f"Buongiorno {link.get('name') or ''}! Da ora riceverà qui ogni settimana un breve aggiornamento su come "
                f"avanzano i suoi lavori, da {owner}. Per domande contatti direttamente {owner}. Scriva /stop se non vuole più riceverli.")
    owner_doc = await db.users.find_one({"user_id": link.get("owner_user_id")}, {"_id": 0})
    if owner_doc:
        await _notify_owner(User(**owner_doc), f"🔗 {link.get('name') or 'Il cliente'} si è collegato su Telegram: "
                                               "riceverà l'avanzamento settimanale dei suoi lavori.")
    return True


async def handle(update: Update) -> bool:
    """A message from a client's chat: /stop, /start or the fixed answer (-> True: it was a client's)."""
    from server import db
    link = await db.client_links.find_one({"telegram_chat_id": update.effective_chat.id}, {"_id": 0})
    if not link:
        return False
    text = ((update.message.text if update.message else "") or "").strip().lower()
    owner = await _owner_name(db, link)
    if text.startswith("/stop"):
        await db.client_links.update_one({"id": link["id"]}, {"$set": {"status": "stopped"}})
        await update.message.reply_text("Va bene, non riceverà più gli aggiornamenti. Se cambia idea scriva /start.")
    elif text.startswith("/start"):
        await db.client_links.update_one({"id": link["id"]}, {"$set": {"status": "active"}})
        await update.message.reply_text(f"👍 Riceverà di nuovo ogni settimana l'aggiornamento sui lavori da {owner}.")
    elif update.message:
        await update.message.reply_text(ONLY_UPDATES.format(owner=owner))
    return True
