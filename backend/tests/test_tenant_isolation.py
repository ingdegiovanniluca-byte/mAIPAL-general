"""Organizations must never see or change each other's data.

1) Static guard (always runs): every endpoint that looks up an id coming from the request WITHOUT a filter on the user /
   organization in the same query must be in REVIEWED - checked by hand and by the probe: they verify the access before
   (e.g. _commessa_or_404). A new endpoint like that fails here until it is reviewed (and the probe run).
2) Probe (runs when ISOLATION_MONGO_URL points to a throwaway MongoDB): the administrator of organization B calls every
   endpoint with organization A's ids; any A data in a response, or A data changed, is a failure (scripts/isolation_probe.py)."""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import isolation_scan  # noqa: E402

# reviewed on 2026-11-24 with the probe: each verifies the user's access before the flagged query
REVIEWED = {
    "scan_public_qr",   # public QR: only visibility "public" + active, and only the text the administrator wrote for it
    "add_milestone_action", "admin_delete_team", "admin_regenerate_team_code", "admin_rename_team", "create_commessa_folder",
    "decide_client_draft", "delete_activity_item", "delete_collaborator", "delete_collection", "delete_commessa_link",
    "delete_equipment", "delete_job_contact", "delete_job_log", "delete_job_photo", "delete_job_todo", "delete_lesson_type",
    "delete_milestone", "delete_milestone_template", "discard_quote", "get_job_photo", "invite_client_updates", "new_client_draft",
    "patch_activity", "patch_client_updates", "patch_job_problem", "plan_material_from_log", "reinvite_collaborator",
    "report_chat", "report_chat_set", "review_job_log_hours", "run_scheduled_action_now", "set_collection_sharing",
    "set_commessa_collaborator", "set_commessa_description", "set_commessa_geo", "set_commessa_sharing", "set_kb_document_org",
    "set_material_done", "set_task_recurrence", "share_commessa_link", "update_collaborator", "update_collection",
    "update_equipment", "update_job_contact", "update_job_log", "update_job_todo", "update_lesson_type", "update_milestone",
    "update_milestone_template", "update_scheduled_action",
}


def test_every_unscoped_lookup_is_reviewed():
    found = isolation_scan.scan(os.path.join(HERE, "server.py"))
    new = sorted({f"{m} {p} ({fn}: db.{coll}.{op})" for m, p, fn, coll, op, *_ in found if fn not in REVIEWED})
    assert not new, ("Endpoint che cercano un id della richiesta senza filtro su utente/organizzazione: verifica che "
                     "controllino l'accesso (es. _commessa_or_404), esegui scripts/isolation_probe.py e aggiungili a REVIEWED:\n"
                     + "\n".join(new))


@pytest.mark.skipif(not os.environ.get("ISOLATION_MONGO_URL"), reason="needs a throwaway MongoDB (ISOLATION_MONGO_URL)")
def test_probe_finds_no_leak():
    env = {**os.environ, "MONGO_URL": os.environ["ISOLATION_MONGO_URL"], "DB_NAME": "isolation_probe", "OPENAI_API_KEY": "x"}
    r = subprocess.run([sys.executable, os.path.join(HERE, "scripts", "isolation_probe.py")], cwd=HERE, env=env,
                       capture_output=True, text=True, timeout=3600)
    report = "\n".join(l for l in r.stdout.splitlines() if l.startswith(("ROUTES", "LEAK", "      ")))
    assert r.returncode == 0, report or r.stderr[-3000:]
