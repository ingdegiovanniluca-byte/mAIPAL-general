"""Previsioni di commessa (forecast.py): pure functions, fixed dates."""
from datetime import date

import forecast as fc

TODAY = date(2026, 10, 26)   # a Monday


def ms(title, orig, due=None, done=None):
    return {"title": title, "original_due_date": orig, "due_date": due or orig, "done": bool(done), "done_date": done}


def test_workdays():
    assert fc.workdays(date(2026, 10, 23), date(2026, 10, 26)) == 1        # Fri -> Mon
    assert fc.workdays(date(2026, 10, 19), date(2026, 10, 30)) == 9
    assert fc.workdays(date(2026, 10, 30), date(2026, 10, 19)) == 0
    assert fc.add_workdays(date(2026, 10, 23), 1) == date(2026, 10, 26)
    assert fc.add_workdays(date(2026, 10, 26), 10) == date(2026, 11, 9)


def test_progress_weighted_by_planned_days():
    start = date(2026, 10, 1)
    m = [ms("Demolizioni", "2026-10-05", done="2026-10-05"), ms("Impianti", "2026-10-19"), ms("Finiture", "2026-10-23")]
    p = fc.progress(m, start)
    # 2 + 10 + 4 working days planned: 2 done
    assert p == {"value": round(2 / 16, 3), "source": "milestone", "done": 1, "total": 3}
    assert fc.progress([], start, (0.6, "2026-10-20")) == {"value": 0.6, "source": "sal", "date": "2026-10-20"}
    assert fc.progress([], start) is None


def test_end_forecast_from_the_pace():
    start = date(2026, 10, 1)
    # planned 10 working days for the first two, they took 15: pace 1.5
    m = [ms("A", "2026-10-08", done="2026-10-12"), ms("B", "2026-10-15", done="2026-10-22"), ms("C", "2026-10-29"), ms("D", "2026-11-05")]
    e = fc.end_forecast(m, start, date(2026, 10, 22))
    assert e["pace"] == 1.5 and e["planned"] == "2026-11-05" and e["confidence"] == "media" and not e["finished"]
    # left: C 10 + D 5 planned working days, x 1.5 = 22 from the 22nd (the day the pace was measured)
    assert e["date"] == fc.add_workdays(date(2026, 10, 22), 22).isoformat() == "2026-11-23" and e["delay_days"] == 12
    # on time: in line
    m2 = [ms("A", "2026-10-08", done="2026-10-08"), ms("B", "2026-10-15")]
    e2 = fc.end_forecast(m2, start, date(2026, 10, 9))
    assert e2["delay_days"] == 0 and e2["date"] == "2026-10-15"
    # nothing done yet, already late on the first one
    e3 = fc.end_forecast([ms("A", "2026-10-08"), ms("B", "2026-10-15")], start, date(2026, 10, 15))
    assert e3["pace"] > 1 and e3["delay_days"] > 0 and e3["confidence"] == "bassa"
    # all done
    assert fc.end_forecast([ms("A", "2026-10-08", done="2026-10-09")], start, TODAY)["finished"]
    assert fc.end_forecast([], start, TODAY) is None


def test_cost_forecast():
    prog = {"value": 0.4, "source": "milestone"}
    c = fc.cost_forecast({"cost_total": 4000, "budget": 9000, "complete": True}, prog)
    assert c["final"] == 10000 and c["pct"] == 111.1 and c["over"] == 1000 and c["confidence"] == "media"
    assert fc.cost_forecast({"cost_total": 500, "budget": 9000}, {"value": 0.1, "source": "milestone"})["final"] is None
    assert fc.cost_forecast({"cost_total": 0, "budget": 9000}, prog) is None
    assert fc.cost_forecast({"cost_total": 3000, "budget": None, "complete": True}, {"value": 0.6, "source": "sal"})["confidence"] == "bassa"


def test_sal_percent_latest():
    reps = [{"report_type": "sal", "created_at": "2026-10-01T10:00", "sections": [{"fields": {"Percentuale di avanzamento": "30%"}}]},
            {"report_type": "sal", "created_at": "2026-10-20T10:00", "sections": [{"fields": {"Percentuale di avanzamento": "circa 60 %"}}]},
            {"report_type": "sopralluogo", "created_at": "2026-10-25T10:00", "sections": [{"fields": {"Percentuale di avanzamento": "90%"}}]}]
    assert fc.sal_percent(reps) == (0.6, "2026-10-20")


def test_stall():
    lg = lambda d, h=8: {"date": d, "hours": [{"who": "Luca", "hours": h}]}
    assert fc.stall([lg("2026-10-16")], TODAY, "in corso", [])["reason"].startswith("nessuna voce da 6")
    assert fc.stall([lg("2026-10-16")], TODAY, "sospesa", []) is None
    busy = [lg(f"2026-10-{d:02d}", 8) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16)] + [lg("2026-10-23", 4)]
    assert "contro le solite" in fc.stall(busy, TODAY, "in corso", [])["reason"]
    soon = [ms("Collaudo", "2026-10-28")]
    assert "Collaudo" in fc.stall([lg("2026-10-21")], TODAY, "in corso", soon)["reason"]
    assert fc.stall([lg("2026-10-23")], TODAY, "in corso", []) is None


def test_forecast_line_and_missing():
    f = fc.forecast({"data_inizio": "2026-10-01", "stato": "in corso"},
                    [ms("A", "2026-10-08", done="2026-10-12"), ms("B", "2026-10-15", done="2026-10-22"), ms("C", "2026-10-29")],
                    [{"date": "2026-10-23", "hours": [{"who": "Luca", "hours": 8}]}], {"cost_total": 4000, "budget": 6000, "complete": True},
                    [], date(2026, 10, 23))
    assert f["progress"]["source"] == "milestone" and "fine prevista" in f["line"] and "costo finale previsto" in f["line"]
    g = fc.forecast({"stato": "in corso"}, [], [{"date": "2026-10-23", "hours": []}], {"cost_total": 0}, [], date(2026, 10, 23))
    assert g["progress"] is None and g["line"].startswith("Per le previsioni servono le milestone")
