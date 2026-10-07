"""The Help guide (help/mAIPAL-help.md) must keep up with the app: every section of the menu
and every chat agent needs its page, or Help would not know about it. A new section or agent
makes this fail until the guide is updated."""
import re
from pathlib import Path

import pytest

import help_guide as hg

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages"
# chat agent (ChatPage ALL_ACTIONS id) -> the guide's section about it
AGENT_SECTIONS = {
    "info_request": "agente-cerca", "info_upload": "agente-salva", "task_todo": "agente-task",
    "journal": "diario", "job_log": "diario-commessa", "vet_report": "referto",
    "work_report": "report-lavoro", "scheduled_action": "azioni",
}
VERTICALS = [None, "artigiano", "veterinario", "fitness"]


def test_guide_parses():
    secs = hg.all_sections()
    ids = [s.id for s in secs]
    assert len(ids) == len(set(ids)), "duplicate section ids"
    assert hg.OVERVIEW_ID in ids and "help" in ids
    for s in secs:
        assert s.title and s.body, s.id
        assert any(v in ("tutti", "nessuno") or v.lstrip("!") in ("artigiano", "veterinario", "fitness") for v in s.verticals), s.id


@pytest.mark.skipif(not FRONTEND.exists(), reason="frontend sources not here")
def test_every_menu_section_has_its_page():
    nav = (FRONTEND / "DashboardLayout.jsx").read_text(encoding="utf-8")
    items = [(m.group(1), (re.search(r'vertical: "(\w+)"', m.group(0)) or [None, None])[1])
             for m in re.finditer(r'\{ to: "(/dashboard/[\w-]+)"[^}]*\}', nav)]
    assert len(items) >= 9
    for path, vertical in items:
        for v in ([vertical] if vertical else VERTICALS):
            assert hg.for_path(path, v), f"no guide page for {path} (vertical {v})"


@pytest.mark.skipif(not FRONTEND.exists(), reason="frontend sources not here")
def test_every_chat_agent_is_documented():
    chat = (FRONTEND / "ChatPage.jsx").read_text(encoding="utf-8")
    block = chat.split("const ALL_ACTIONS = [", 1)[1].split("\n];", 1)[0]
    agents = re.findall(r'id: "(\w+)", key:', block)
    assert len(agents) >= 8
    ids = {s.id for s in hg.all_sections()}
    for a in agents:
        assert a in AGENT_SECTIONS, f"chat agent {a} has no page in the Help guide"
        assert AGENT_SECTIONS[a] in ids, AGENT_SECTIONS[a]


def test_vertical_filter():
    assert {s.id for s in hg.for_path("/dashboard/journal", "artigiano")} == {"diario-commessa"}
    assert {s.id for s in hg.for_path("/dashboard/journal", None)} == {"diario"}
    assert {s.id for s in hg.for_path("/dashboard/liste", "fitness")} == {"liste"}
    assert hg.for_path("/dashboard/fitness", "artigiano") == []
