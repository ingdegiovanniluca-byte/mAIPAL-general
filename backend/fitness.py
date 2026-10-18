"""Fitness vertical: the exercises' catalog, the studio's equipment and the lesson rules, and
the pieces of the lesson builder that must not be left to the model.

A lesson is built in three steps:
1. the request ("10 persone, livello medio, gambe") is read into parameters and merged with the
   rules of the lesson type (duration, minutes of stretching at start and end, rest...);
2. the candidate exercises are chosen HERE: the right activity, role (riscaldamento /
   esercizio / stretching), body part and level, and only if the equipment is enough for
   everybody at once (participants x pieces per person <= pieces available);
3. the model picks and orders among those candidates; its answer is then checked here - unknown
   exercises dropped, sets / seconds / repetitions brought inside each exercise's limits - and
   fitted to the time of each phase.
Kept free of server imports so it can be tested on its own.
"""
import json
import os
import re
from typing import Optional

LEVELS = ["basso", "medio", "alto"]
_LEVEL_ALIASES = {"base": "basso", "principiante": "basso", "facile": "basso", "intermedio": "medio",
                  "avanzato": "alto", "difficile": "alto", "medio-alto": "alto"}
ROLES = ["riscaldamento", "esercizio", "stretching"]
PHASE_KINDS = ["stretching", "riscaldamento"]
DEFAULT_SEC_PER_REPS_SET = 30      # a set of repetitions, when the exercise doesn't say
DEFAULT_REST_SEC = 15

BASE_FILE = os.path.join(os.path.dirname(__file__), "data", "fitness_base.json")


def base_catalog() -> dict:
    """{"exercises": [...], "equipment": [{"name", "quantity"}]} - the vertical's starting set."""
    with open(BASE_FILE, encoding="utf-8") as f:
        return json.load(f)


# the vertical's base lesson type (editable by the studio)
BASE_LESSON_TYPES = [{
    "name": "Funzionale", "activity": "funzionale", "duration_min": 40,
    "start_min": 5, "start_kind": "stretching", "end_min": 5, "end_kind": "stretching",
    "rest_sec": DEFAULT_REST_SEC, "default_level": "medio", "default_participants": 10, "mode": "misto",
    "rules_text": "",
}]


def norm_level(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip().lower()
    v = _LEVEL_ALIASES.get(v, v)
    return v if v in LEVELS else None


def level_ok(ex_level: Optional[str], wanted: Optional[str]) -> bool:
    """A medium class does low and medium exercises; a high one everything."""
    ex_level, wanted = norm_level(ex_level), norm_level(wanted)
    if not ex_level or not wanted:
        return True
    return LEVELS.index(ex_level) <= LEVELS.index(wanted)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def inventory_map(equipment: list) -> dict:
    return {_norm(e.get("name")): int(e.get("quantity") or 0) for e in equipment or []}


def equipment_need(ex: dict, participants: int) -> int:
    per = int(ex.get("equipment_per_person") or 0)
    return per * max(1, participants) if ex.get("equipment") and per else 0


def equipment_ok(ex: dict, participants: int, inventory: dict) -> bool:
    need = equipment_need(ex, participants)
    return not need or inventory.get(_norm(ex.get("equipment")), 0) >= need


def body_ok(ex: dict, parts: list) -> bool:
    return not parts or _norm(ex.get("body_part")) in {_norm(p) for p in parts}


def candidates(exercises: list, activity: str, level: Optional[str], parts: list, participants: int,
               inventory: dict) -> dict:
    """{"riscaldamento": [...], "esercizio": [...], "stretching": [...], "excluded_equipment": [names]}
    - for warm-up and stretching the body parts are a preference (all of them when none fits)."""
    out = {r: [] for r in ROLES}
    excluded = []
    act = _norm(activity)
    for ex in exercises:
        if act and _norm(ex.get("activity")) not in ("", act):
            continue
        role = ex.get("role") if ex.get("role") in ROLES else "esercizio"
        if role == "esercizio" and not level_ok(ex.get("level"), level):
            continue
        if not equipment_ok(ex, participants, inventory):
            if role == "esercizio" and body_ok(ex, parts):
                excluded.append(ex["name"])
            continue
        out[role].append(ex)
    out["esercizio"] = [e for e in out["esercizio"] if body_ok(e, parts)]
    for r in ("riscaldamento", "stretching"):
        fit = [e for e in out[r] if body_ok(e, parts)]
        out[r] = fit or out[r]
    out["excluded_equipment"] = excluded
    return out


def _clamp(v, lo, hi, default):
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def fix_block(block: dict, ex: dict, mode_pref: str = "misto") -> dict:
    """The model's block inside the exercise's limits: a mode the exercise allows, sets and
    seconds / repetitions within their minimum and maximum."""
    t, r = ex.get("timed") or {}, ex.get("reps") or {}
    can_t, can_r = t.get("allowed", True), r.get("allowed", True)
    mode = block.get("mode") if block.get("mode") in ("tempo", "ripetizioni") else None
    if mode_pref in ("tempo", "ripetizioni"):
        mode = mode_pref
    if mode == "tempo" and not can_t:
        mode = "ripetizioni"
    if mode == "ripetizioni" and not can_r:
        mode = "tempo"
    mode = mode or ("tempo" if can_t else "ripetizioni")
    out = {"exercise_id": ex["id"], "name": ex["name"], "phase": block.get("phase"), "mode": mode,
           "body_part": ex.get("body_part") or "", "equipment": ex.get("equipment") or "",
           "equipment_per_person": int(ex.get("equipment_per_person") or 0),
           "notes": (block.get("notes") or "").strip()[:200], "exercise_notes": ex.get("notes") or ""}
    if mode == "tempo":
        out["sets"] = _clamp(block.get("sets"), t.get("min_sets") or 1, t.get("max_sets"), t.get("min_sets") or 1)
        out["seconds"] = _clamp(block.get("seconds"), t.get("min_sec"), t.get("max_sec"), t.get("max_sec") or 40)
    else:
        out["sets"] = _clamp(block.get("sets"), r.get("min_sets") or 1, r.get("max_sets"), r.get("min_sets") or 1)
        out["reps"] = _clamp(block.get("reps"), r.get("min_reps"), r.get("max_reps"), r.get("min_reps") or 10)
        out["seconds_per_set"] = int(r.get("sec_per_set") or DEFAULT_SEC_PER_REPS_SET)
    return out


def block_seconds(b: dict, rest_sec: int) -> int:
    """Working time plus the rests between its sets and after it."""
    work = b["seconds"] if b["mode"] == "tempo" else b.get("seconds_per_set") or DEFAULT_SEC_PER_REPS_SET
    return b["sets"] * work + b["sets"] * rest_sec


def fit_phase(blocks: list, budget_sec: int, rest_sec: int, by_id: dict, pool: list, mode_pref: str = "misto") -> list:
    """Brings a phase near its time: too long -> fewer sets, then fewer exercises; too short ->
    more sets (within each exercise's maximum), then more exercises from the pool."""
    blocks = list(blocks)
    total = lambda: sum(block_seconds(b, rest_sec) for b in blocks)
    def limit(b):
        ex = by_id[b["exercise_id"]]
        lim = (ex.get("timed") if b["mode"] == "tempo" else ex.get("reps")) or {}
        return lim.get("min_sets") or 1, lim.get("max_sets") or b["sets"]
    # too long
    while blocks and total() > budget_sec * 1.05:
        reducible = [b for b in blocks if b["sets"] > limit(b)[0]]
        if reducible:
            max(reducible, key=lambda b: b["sets"])["sets"] -= 1
        else:
            blocks.pop()
    # too short
    used = {b["exercise_id"] for b in blocks}
    while total() < budget_sec * 0.9:
        growable = [b for b in blocks if b["sets"] < limit(b)[1]]
        if growable:
            min(growable, key=lambda b: b["sets"])["sets"] += 1
            continue
        extra = next((e for e in pool if e["id"] not in used), None)
        if not extra:
            break
        used.add(extra["id"])
        phase = blocks[-1]["phase"] if blocks else None
        blocks.append(fix_block({"phase": phase}, extra, mode_pref))
    return blocks


def equipment_summary(blocks: list, participants: int) -> dict:
    """{equipment: the most needed at the same time}"""
    out: dict = {}
    for b in blocks:
        if b.get("equipment") and b.get("equipment_per_person"):
            out[b["equipment"]] = max(out.get(b["equipment"], 0), b["equipment_per_person"] * max(1, participants))
    return out


def parse_request_fallback(text: str) -> dict:
    """Numbers and words read without the model (also a safety net when it fails)."""
    low = (text or "").lower()
    p = {}
    m = re.search(r"(\d+)\s*(persone|partecipanti|allievi|clienti|iscritti)", low)
    if m:
        p["participants"] = int(m.group(1))
    m = re.search(r"(\d+)\s*(minuti|min\b|')", low)
    if m:
        p["duration_min"] = int(m.group(1))
    for word, lvl in (("basso", "basso"), ("principiant", "basso"), ("medio", "medio"), ("intermedio", "medio"),
                      ("alto", "alto"), ("avanzat", "alto")):
        if re.search(rf"\blivello\s+{word}|\b{word}", low):
            p["level"] = lvl
            break
    parts = [x for x in ("gambe", "braccia", "glutei", "addome", "schiena", "spalle", "petto") if x in low]
    if parts:
        p["body_parts"] = parts
    if "a tempo" in low:
        p["mode"] = "tempo"
    elif "ripetizion" in low:
        p["mode"] = "ripetizioni"
    return p
