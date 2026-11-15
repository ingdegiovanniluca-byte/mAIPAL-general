"""Measures the chat router (router.py) - it changes NOTHING: it only reads.

Three measures:

  --golden   the labelled examples (router_golden.jsonl), through the whole router with the
             real model: how many go to the right agent, how many ask (right only for the ambiguous
             ones), how many go to a WRONG one (the number that must stay near zero), and the time.
  --history  the real conversations in the database (last --days days, at most --max messages): each
             user message with the agent the user chose then. How often the router agrees, and every
             disagreement, to read one by one (the user may have chosen wrong, or the router).
  --shadow   what the shadow mode collected on real use (router_shadow: app chat and Telegram, every
             message with the agent used and where the router would have sent it) - no model call.

Run on the server (needs OPENAI_API_KEY; --history also MONGO_URL / DB_NAME, as the backend):

    docker compose exec backend python scripts/router_eval.py --golden
    docker compose exec backend python scripts/router_eval.py --history --days 30 --max 300 --out /app/router_report.md
    docker compose cp backend:/app/router_report.md .
    docker compose exec backend python scripts/router_eval.py --shadow --days 14 --out /app/router_shadow.md

--no-model measures only the context and the rules (free, instant). The report has the users' messages:
it stays on the server; share only what you choose.
"""
import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import router  # noqa: E402

GOLDEN = HERE / "router_golden.jsonl"   # next to router.py (tests/ is not in the Docker image)


def _pct(a, b):
    return f"{(100 * a / b):.1f}%" if b else "-"


async def eval_golden(use_model: bool) -> list:
    cases = [json.loads(x) for x in GOLDEN.read_text().splitlines() if x.strip()]
    lines, times, by_level = [], [], Counter()
    right = asked_ok = asked_needless = wrong = 0
    wrongs, needless = [], []
    for c in cases:
        d = await router.route(c["text"], vertical=c["v"], context=c.get("ctx") or {}, lists=c.get("lists") or [],
                               has_images=bool(c.get("images")), use_model=use_model, channel="eval")
        times.append(d["ms"])
        by_level[d["level"]] += 1
        if d["mode"] == "ask":
            if c["amb"] or any(o in c["expect"] for o in d["options"]):
                asked_ok += 1
            if not c["amb"]:
                needless.append((c["text"], d["options"], c["expect"]))
        elif d["intent"] in c["expect"]:
            right += 1
        else:
            wrong += 1
            wrongs.append((c["text"], d["intent"], d["confidence"], d["level"], d["reason"], c["expect"]))
    n = len(cases)
    lines.append(f"# Router · golden set ({n} esempi, modello {'sì' if use_model else 'no'})\n")
    lines.append(f"- **Agente giusto**: {right} ({_pct(right, n)})")
    lines.append(f"- **Ha chiesto** (due pulsanti): {asked_ok} ({_pct(asked_ok, n)}), di cui senza bisogno: {len(needless)}")
    lines.append(f"- **Agente SBAGLIATO senza chiedere**: {wrong} ({_pct(wrong, n)})  ← deve restare vicino a zero")
    lines.append(f"- Deciso da: " + ", ".join(f"{k} {v}" for k, v in by_level.most_common()))
    if times:
        lines.append(f"- Tempo: mediana {statistics.median(times):.0f} ms, 95° percentile {sorted(times)[int(0.95 * (len(times) - 1))]} ms")
    if wrongs:
        lines.append("\n## Sbagliati\n")
        lines += [f"- «{t}» → **{i}** ({conf}, {lvl}: {why}) · atteso {exp}" for t, i, conf, lvl, why, exp in wrongs]
    if needless:
        lines.append("\n## Domande non necessarie\n")
        lines += [f"- «{t}» → chiede {opts} · atteso {exp}" for t, opts, exp in needless]
    return lines


async def eval_history(days: int, max_n: int, use_model: bool) -> list:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    verticals = {}
    rows = []
    async for conv in db.conversations.find({"created_at": {"$gte": since}}, {"_id": 0, "user_id": 1, "action": 1, "messages": 1,
                                                                               "user_message": 1}).sort("created_at", -1):
        action = conv.get("action")
        uid = conv.get("user_id")
        if uid not in verticals:
            u = await db.users.find_one({"user_id": uid}, {"_id": 0, "business_vertical": 1}) or {}
            verticals[uid] = u.get("business_vertical")
        v = verticals[uid]
        if action not in router.intents_for(v):
            continue
        msgs = conv.get("messages") or ([{"role": "user", "content": conv.get("user_message")}] if conv.get("user_message") else [])
        hist = []
        for i, m in enumerate(msgs):
            if m.get("role") == "user" and (m.get("content") or "").strip():
                text = m["content"].split("\n\nAllegati caricati", 1)[0].strip()
                ctx = {"current_action": action, "history": hist[-4:]} if hist else {}
                if hist and hist[-1].get("role") == "assistant" and (hist[-1].get("content") or "").rstrip().endswith("?"):
                    ctx["awaiting"] = True
                rows.append((uid, v, action, text, ctx, i == 0))
            hist.append({"role": m.get("role"), "content": (m.get("content") or "")[:300]})
        if len(rows) >= max_n:
            break
    rows = rows[:max_n]
    agree, per_action, dis, levels, asks = 0, defaultdict(lambda: [0, 0]), [], Counter(), 0
    for uid, v, action, text, ctx, first in rows:
        d = await router.route(text, vertical=v, context=ctx, use_model=use_model, user_id=uid, channel="eval")
        levels[d["level"]] += 1
        per_action[action][1] += 1
        if d["mode"] == "ask":
            asks += 1
            if action in d["options"]:
                agree += 1
                per_action[action][0] += 1
            else:
                dis.append((action, d, text, first))
        elif d["intent"] == action:
            agree += 1
            per_action[action][0] += 1
        else:
            dis.append((action, d, text, first))
    n = len(rows)
    lines = [f"# Router · conversazioni reali (ultimi {days} giorni, {n} messaggi, modello {'sì' if use_model else 'no'})\n",
             f"- **D'accordo con l'agente scelto dall'utente**: {agree} ({_pct(agree, n)})",
             f"- Avrebbe chiesto: {asks} ({_pct(asks, n)})",
             "- Deciso da: " + ", ".join(f"{k} {v}" for k, v in levels.most_common()),
             "\n| agente scelto | d'accordo | messaggi |", "|---|---|---|"]
    lines += [f"| {router.LABELS.get(a, a)} ({a}) | {_pct(ok, tot)} | {tot} |" for a, (ok, tot) in sorted(per_action.items(), key=lambda x: -x[1][1])]
    if dis:
        lines.append("\n## Disaccordi (da leggere: ha sbagliato l'utente o il router?)\n")
        for action, d, text, first in dis:
            lines.append(f"- scelto **{router.LABELS.get(action, action)}**, router **{d['label']}** ({d['confidence']}, {d['level']}, "
                         f"{'chiede' if d['mode'] == 'ask' else 'va'}{'' if first else ', seguito di conversazione'}): «{text[:200]}»")
    return lines


async def eval_shadow(days: int) -> list:
    """What the shadow mode collected (router_shadow): the router next to the agent actually used, on real use."""
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await db.router_shadow.find({"at": {"$gte": since}}, {"_id": 0}).sort("at", -1).to_list(20000)
    n = len(rows)
    lines = [f"# Router · modalità ombra (ultimi {days} giorni, {n} messaggi)\n"]
    if not n:
        return lines + ["Nessun messaggio raccolto: la modalità ombra è accesa (ROUTER_SHADOW) e qualcuno ha scritto in chat?"]
    agree = sum(1 for r in rows if r["agree"])
    asks = sum(1 for r in rows if r["mode"] == "ask")
    wrong_go = sum(1 for r in rows if not r["agree"] and r["mode"] != "ask")
    ms = sorted(r.get("ms") or 0 for r in rows)
    lines += [f"- **D'accordo con l'agente usato**: {agree} ({_pct(agree, n)})",
              f"- Avrebbe chiesto: {asks} ({_pct(asks, n)})",
              f"- **In disaccordo senza chiedere**: {wrong_go} ({_pct(wrong_go, n)})  ← da leggere uno per uno",
              "- Deciso da: " + ", ".join(f"{k} {v}" for k, v in Counter(r["level"] for r in rows).most_common()),
              f"- Tempo: mediana {statistics.median(ms):.0f} ms, 95° percentile {ms[int(0.95 * (n - 1))]} ms",
              "\n| canale | d'accordo | messaggi |", "|---|---|---|"]
    by_ch = defaultdict(lambda: [0, 0])
    by_ag = defaultdict(lambda: [0, 0])
    for r in rows:
        by_ch[r["channel"]][1] += 1; by_ch[r["channel"]][0] += 1 if r["agree"] else 0
        by_ag[r["chosen"]][1] += 1; by_ag[r["chosen"]][0] += 1 if r["agree"] else 0
    lines += [f"| {c} | {_pct(ok, t)} | {t} |" for c, (ok, t) in by_ch.items()]
    lines += ["\n| agente usato | d'accordo | messaggi |", "|---|---|---|"]
    lines += [f"| {router.LABELS.get(a, a)} ({a}) | {_pct(ok, t)} | {t} |" for a, (ok, t) in sorted(by_ag.items(), key=lambda x: -x[1][1])]
    dis = [r for r in rows if not r["agree"]]
    if dis:
        lines.append("\n## Disaccordi (i più recenti; ha sbagliato chi ha scelto o il router?)\n")
        for r in dis[:150]:
            lines.append(f"- {r['channel']}, usato **{router.LABELS.get(r['chosen'], r['chosen'])}**, router **{router.LABELS.get(r['intent'], r['intent'])}** "
                         f"({r['confidence']}, {r['level']}, {'chiede' if r['mode'] == 'ask' else 'va'}"
                         f"{', seguito' if r.get('follow_up') else ''}): «{r['text'][:200]}»")
    return lines


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", action="store_true")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--shadow", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not (a.golden or a.history or a.shadow):
        a.golden = True
    lines = []
    if a.golden:
        lines += await eval_golden(not a.no_model)
    if a.history:
        lines += [""] + await eval_history(a.days, a.max, not a.no_model)
    if a.shadow:
        lines += [""] + await eval_shadow(a.days)
    text = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text)
        print(f"Report scritto in {a.out}")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
