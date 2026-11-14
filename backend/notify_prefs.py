"""Which notifications a user wants, and where: in the app (the phone's / computer's notifications), on
Telegram, or both. One switch per kind (Impostazioni > Notifiche); all on, on both, until changed.

`wants(db, user_id, kind, channel)` is asked before each sending: a sending without a kind (the test,
a problem saving the archive) always goes.
"""
from typing import Optional

CHANNELS = ("app", "telegram", "both")

# (key, label, what it is) - in the order they are shown
KINDS = [
    ("task_reminder", "Promemoria dei task", "All'ora del task, e di nuovo se lo rimandi."),
    ("daily_summary", "Riepilogo della giornata", "La sera: cosa è successo oggi sulle commesse."),
    ("diary", "Diario dei collaboratori", "Quando un collaboratore scrive ore, lavori o foto in una commessa."),
    ("problems", "Problemi dai cantieri", "Un problema segnalato su una commessa."),
    ("done", "Attività fatte", "Un collaboratore segna come fatta un'attività o una milestone."),
    ("presence", "Presenze in cantiere", "Arrivi, fine non segnata, «sei ancora in cantiere?», «com'è andata oggi?»."),
    ("confirm", "Conferme delle attività", "Chi non può esserci o non ha ancora confermato un'attività."),
    ("hours", "Ore da approvare", "Le ore scritte da un collaboratore che aspettano il tuo ok."),
    ("extra", "Lavori extra e materiali non previsti", "Un lavoro o un materiale fuori dal preventivo."),
    ("materials", "Materiali da prendere", "I materiali da prendere che sono per te."),
    ("costs", "Costi e budget", "Spese oltre il previsto e commesse che rischiano di sforare."),
    ("client", "Aggiornamenti ai clienti", "Le bozze da approvare e gli aggiornamenti inviati ai clienti."),
    ("shares", "Condivisioni e inviti", "Task assegnati a te; commesse, liste e informazioni condivise con te; inviti in un team."),
    ("news", "News del mattino", "Le news del giorno, la mattina."),
    ("actions", "Azioni programmate", "I risultati delle azioni che hai programmato."),
]
KIND_KEYS = {k for k, _l, _h in KINDS}
DEFAULT = {"on": True, "channel": "both"}


def _pref(prefs: Optional[dict], kind: str) -> dict:
    p = (prefs or {}).get(kind) or {}
    on = p.get("on", DEFAULT["on"])
    channel = p.get("channel") if p.get("channel") in CHANNELS else DEFAULT["channel"]
    return {"on": bool(on), "channel": channel}


async def prefs_of(db, user_id: str) -> dict:
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "notify_prefs": 1}) or {}
    return u.get("notify_prefs") or {}


async def wants(db, user_id: Optional[str], kind: Optional[str], channel: str) -> bool:
    """Does the user want this kind of notification on this channel ("app" / "telegram")?"""
    if not kind or not user_id:
        return True
    p = _pref(await prefs_of(db, user_id), kind)
    return p["on"] and p["channel"] in ("both", channel)


async def listing(db, user_id: str) -> list:
    prefs = await prefs_of(db, user_id)
    return [{"key": k, "label": label, "help": hlp, **_pref(prefs, k)} for k, label, hlp in KINDS]


async def set_pref(db, user_id: str, kind: str, on: Optional[bool] = None, channel: Optional[str] = None) -> dict:
    if kind not in KIND_KEYS:
        raise ValueError("Tipo di notifica sconosciuto")
    if channel is not None and channel not in CHANNELS:
        raise ValueError("Canale non valido")
    prefs = dict(await prefs_of(db, user_id))
    cur = _pref(prefs, kind)
    if on is not None:
        cur["on"] = bool(on)
    if channel is not None:
        cur["channel"] = channel
    prefs[kind] = cur
    await db.users.update_one({"user_id": user_id}, {"$set": {"notify_prefs": prefs}})
    return cur
