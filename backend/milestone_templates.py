"""Milestone templates (artigiano): the steps of a kind of job, reused as the starting point of
a new commessa's milestones - the ready-made ones below, or one saved from a commessa.

A step is {"title", "day"}: its deadline as working days (Monday-Friday) from the start, so a
template fits any start date. Kept free of server imports so it can be tested on its own.
"""
from datetime import date, timedelta

# the ready-made ones: typical steps and times of small jobs (editable once copied)
BUILTIN = [
    {"key": "elettrico_casa", "name": "Impianto elettrico domestico", "steps": [
        ("Sopralluogo e progetto dell'impianto", 0), ("Tracce a muro e a pavimento", 3), ("Posa corrugati e scatole", 5),
        ("Infilaggio cavi", 8), ("Quadro elettrico e collegamenti", 10), ("Frutti e placche", 12),
        ("Collaudo e misure", 13), ("Dichiarazione di conformità (DiCo)", 14)]},
    {"key": "bagno", "name": "Rifacimento bagno", "steps": [
        ("Smontaggio sanitari e demolizioni", 2), ("Nuovi scarichi e impianto idraulico", 4), ("Impianto elettrico del bagno", 5),
        ("Massetto e impermeabilizzazione", 7), ("Posa pavimento e rivestimento", 11), ("Montaggio sanitari e rubinetteria", 13),
        ("Box doccia e mobile bagno", 14), ("Pulizia finale e consegna", 15)]},
    {"key": "cucina", "name": "Rifacimento cucina (impianti)", "steps": [
        ("Smontaggio cucina e demolizioni", 1), ("Impianto idraulico e scarichi", 3), ("Impianto elettrico e prese elettrodomestici", 4),
        ("Impianto gas e prova di tenuta", 5), ("Rasatura e tinteggiatura", 7), ("Montaggio cucina", 9), ("Allacci e collaudo", 10)]},
    {"key": "idraulico_casa", "name": "Impianto idraulico appartamento", "steps": [
        ("Sopralluogo e progetto", 0), ("Tracce", 2), ("Posa tubazioni di carico e scarico", 5), ("Prova di tenuta", 6),
        ("Chiusura tracce", 7), ("Montaggio sanitari", 11), ("Collaudo e dichiarazione di conformità", 12)]},
    {"key": "caldaia", "name": "Sostituzione caldaia", "steps": [
        ("Sopralluogo e verifica canna fumaria", 0), ("Ordine della caldaia", 1), ("Smontaggio della vecchia caldaia", 5),
        ("Installazione e collegamenti", 5), ("Prima accensione e analisi fumi", 6), ("Libretto d'impianto e DiCo", 7)]},
    {"key": "clima", "name": "Climatizzazione (split)", "steps": [
        ("Sopralluogo e scelta delle macchine", 0), ("Fori e linee frigorifere", 4), ("Posa unità interne ed esterna", 5),
        ("Vuoto, carica e collaudo", 5), ("Registrazione F-gas e consegna", 6)]},
    {"key": "tinteggiatura", "name": "Tinteggiatura appartamento", "steps": [
        ("Protezione di pavimenti e arredi", 0), ("Stuccatura e rasatura", 2), ("Prima mano", 4), ("Seconda mano", 5),
        ("Pulizia e consegna", 6)]},
    {"key": "ristrutturazione", "name": "Ristrutturazione appartamento", "steps": [
        ("Demolizioni e sgomberi", 5), ("Impianti elettrico e idraulico", 15), ("Massetti", 20), ("Intonaci e rasature", 25),
        ("Pavimenti e rivestimenti", 33), ("Porte e serramenti", 37), ("Tinteggiatura", 40), ("Montaggi e finiture", 44),
        ("Pulizia e consegna", 45)]},
]


def builtin_list() -> list:
    return [{"id": f"builtin:{t['key']}", "name": t["name"], "builtin": True,
             "steps": [{"title": s, "day": d} for s, d in t["steps"]]} for t in BUILTIN]


def builtin(template_id: str):
    return next((t for t in builtin_list() if t["id"] == template_id), None)


def add_workdays(start: date, n: int) -> date:
    """start + n working days (a start on Saturday/Sunday counts from Monday)."""
    d = start
    while d.weekday() >= 5:
        d += timedelta(days=1)
    left = max(0, int(n))
    while left:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def workdays_between(start: date, end: date) -> int:
    """Working days from start to end (0 when end is not after start)."""
    d, n = start, 0
    while d.weekday() >= 5:
        d += timedelta(days=1)
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def clean_steps(rows) -> list:
    """[{title, day}] cleaned: titles kept, days 0-365, in order of day."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        title = " ".join(str(r.get("title") or "").split())[:200]
        try:
            day = max(0, min(365, int(r.get("day") or 0)))
        except (TypeError, ValueError):
            day = 0
        if title:
            out.append({"title": title, "day": day})
    return sorted(out, key=lambda x: x["day"])


def from_milestones(milestones: list, start: date) -> list:
    """A commessa's milestones as steps: each first planned date as working days from start."""
    steps = []
    for m in milestones:
        first = date.fromisoformat((m.get("original_due_date") or m["due_date"])[:10])
        steps.append({"title": m["title"], "day": workdays_between(start, first)})
    return clean_steps(steps)


if __name__ == "__main__":
    mon = date(2026, 10, 19)
    assert add_workdays(mon, 0) == mon and add_workdays(mon, 5) == date(2026, 10, 26)
    assert add_workdays(date(2026, 10, 24), 0) == date(2026, 10, 26)        # Saturday -> Monday
    assert workdays_between(mon, date(2026, 10, 26)) == 5
    for t in builtin_list():
        assert t["steps"] == clean_steps(t["steps"]), t["name"]
    print("ok")
