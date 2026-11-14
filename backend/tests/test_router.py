"""The chat router (router.py), offline: no model is called.

- The context and the rules must NEVER be wrong on the golden set (tests/router/router_golden.jsonl):
  when they decide, the agent is one of the expected ones (or, for an ambiguous message, they ask).
- The model level is checked with a fake client: its answer, a broken answer, a timeout.
- The thresholds: go / go_show / ask, and what changes data is asked unless sure.
The real model is measured by scripts/router_eval.py (needs the API key).
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import router  # noqa: E402

GOLDEN = [json.loads(x) for x in (Path(__file__).parent / "router" / "router_golden.jsonl").read_text().splitlines() if x.strip()]


def _offline(case):
    ctx = case.get("ctx") or {}
    return (router.by_context(case["text"], ctx, case["v"], bool(case.get("images")))
            or router.by_rules(case["text"], case["v"], case.get("lists") or []))


def test_golden_is_sane():
    assert len(GOLDEN) >= 100
    for c in GOLDEN:
        allowed = router.intents_for(c["v"])
        assert all(e in allowed for e in c["expect"]), c


def test_context_and_rules_are_never_wrong():
    wrong, decided = [], 0
    for c in GOLDEN:
        d = _offline(c)
        if d is None:
            continue
        decided += 1
        ok = d["intent"] in c["expect"] or (c["amb"] and d["mode"] == "ask")
        if not ok:
            wrong.append((c["text"], d["intent"], d["reason"], c["expect"]))
    assert not wrong, "\n".join(map(str, wrong))
    # most clear messages are decided without the model (fast, free, predictable)
    clear = [c for c in GOLDEN if not c["amb"]]
    clear_decided = sum(1 for c in clear if _offline(c) is not None)
    assert clear_decided / len(clear) >= 0.6, (clear_decided, len(clear))
    print(f"\ndecided offline: {decided}/{len(GOLDEN)} (clear ones: {clear_decided}/{len(clear)})")


def test_thresholds_and_risky():
    d = router._decision("task_todo", 0.95, "model")
    assert d["mode"] == "go" and d["options"] == ["task_todo"]
    assert router._decision("task_todo", 0.7, "model")["mode"] == "go_show"
    d = router._decision("task_todo", 0.4, "model", second="job_log", vertical="artigiano")
    assert d["mode"] == "ask" and d["options"] == ["task_todo", "job_log"]
    assert len(router._decision("info_upload", 0.3, "model")["options"]) == 2      # always two buttons to ask
    # what changes data by itself, later: asked unless very sure
    assert router._decision("scheduled_action", 0.85, "rules")["mode"] == "ask"
    assert router._decision("scheduled_action", 0.95, "model")["mode"] == "go"


def test_intents_per_trade():
    assert "job_log" in router.intents_for("artigiano") and "journal" not in router.intents_for("artigiano")
    assert "work_report" in router.intents_for("artigiano") and "vet_report" not in router.intents_for("artigiano")
    assert "journal" in router.intents_for(None) and "vet_report" in router.intents_for(None)
    assert "lesson" in router.intents_for("fitness")


class _FakeClient:
    def __init__(self, answer=None, delay=0.0, boom=False):
        self.answer, self.delay, self.boom, self.calls = answer, delay, boom, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.calls.append(kw)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.boom:
            raise RuntimeError("down")
        msg = SimpleNamespace(content=self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None, model="fake")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_model_level_and_fallbacks():
    os.environ.setdefault("OPENAI_API_KEY", "x")
    text = "Rossi ha pagato 500 euro"   # not decided by the rules
    assert router.by_rules(text, "artigiano", []) is None
    # the model's answer, with the context and the trade in its instructions
    fc = _FakeClient('{"intent": "info_upload", "confidence": 0.72, "second": "job_log", "reason": "un pagamento"}')
    d = _run(router.route(text, vertical="artigiano", context={"current_action": "job_log", "history": [{"role": "user", "content": "x"}]},
                          lists=["fornitori"], commesse=["Bagno Rossi"], client=fc))
    assert (d["intent"], d["mode"], d["level"]) == ("info_upload", "go_show", "model"), d
    sysmsg = fc.calls[0]["messages"][0]["content"]
    assert "ARTIGIANO" in sysmsg and "job_log" in sysmsg and "Bagno Rossi" in sysmsg and "fornitori" in sysmsg and "journal (" not in sysmsg
    # an agent the trade doesn't have, or garbage: not used -> fallback (the conversation's agent)
    for bad in ['{"intent": "vet_report", "confidence": 0.99}', "boh", '{"intent": "task_todo", "confidence": "molto"}']:
        d = _run(router.route(text, vertical="artigiano", context={"current_action": "job_log"}, client=_FakeClient(bad)))
        assert d["level"] in ("fallback", "model"), d
        if d["level"] == "fallback":
            assert d["intent"] == "job_log" and d["mode"] == "go_show"
    # down or too slow: never stuck, a decision anyway
    d = _run(router.route(text, vertical="artigiano", client=_FakeClient(boom=True)))
    assert d["level"] == "fallback" and d["mode"] == "ask" and len(d["options"]) == 2   # no model, no conversation: asked
    old = router.TIMEOUT_S
    router.TIMEOUT_S = 0.05
    try:
        d = _run(router.route(text, vertical="artigiano", client=_FakeClient('{"intent": "job_log", "confidence": 0.9}', delay=0.3)))
        assert d["level"] == "fallback" and d["ms"] < 1000
    finally:
        router.TIMEOUT_S = old
    # the rules don't call the model at all
    fc = _FakeClient('{"intent": "info_upload", "confidence": 0.99}')
    d = _run(router.route("Ricordami di chiamare il fornitore martedì", vertical="artigiano", client=fc))
    assert d["intent"] == "task_todo" and d["level"] == "rules" and not fc.calls
