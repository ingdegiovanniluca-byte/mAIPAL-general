"""The database's indexes: every lookup the app makes often - by id on each request (the session, the user),
by commessa, by list, by user - and every filter of the periodic jobs (open presences, due reminders, open
activities...). Without them each of these reads the whole collection, which grows with every organization:
with hundreds of organizations the pages slow down and the 5-minute jobs no longer fit in 5 minutes.

Created at startup (idempotent: an index already there is left as it is); a failing one is logged, never stops
the app. Kept here in one list so a new query's index is added in one place."""
import logging
from typing import Iterable, Tuple

logger = logging.getLogger(__name__)

A, D = 1, -1

# (collection, keys, options)
INDEXES: Tuple[Tuple[str, list, dict], ...] = (
    # every request: the session cookie, then its user
    ("user_sessions", [("session_token", A)], {}),
    ("user_sessions", [("user_id", A)], {}),
    ("user_sessions", [("expires_at", A)], {"expireAfterSeconds": 0}),   # expired sessions removed by MongoDB itself
    ("watch_pair_failures", [("at", A)], {"expireAfterSeconds": 86400}),
    ("users", [("user_id", A)], {}),
    ("users", [("email", A)], {}),
    ("users", [("telegram_chat_id", A)], {"sparse": True}),
    ("users", [("tenant_id", A)], {}),
    ("users", [("org_id", A)], {}),
    ("users", [("org_ids", A)], {}),
    ("organizations", [("id", A)], {}),
    ("organizations", [("tenant_id", A)], {}),
    ("tenants", [("id", A)], {}),
    ("tenant_invites", [("email", A)], {}),
    ("tenant_invites", [("tenant_id", A)], {}),
    ("team_invites", [("org_id", A)], {}),
    ("integrations", [("user_id", A), ("provider", A)], {}),
    ("telegram_links", [("code", A)], {}),
    # lists, clients and commesse
    ("collections", [("id", A)], {}),
    ("collections", [("user_id", A)], {}),
    ("collections", [("org_id", A), ("visibility", A)], {}),
    ("collections", [("system_key", A)], {}),
    ("collection_items", [("id", A)], {}),
    ("collection_items", [("collection_id", A)], {}),
    ("collection_sub_items", [("id", A)], {}),
    ("collection_sub_items", [("collection_id", A), ("item_id", A)], {}),
    ("collection_sub_items", [("item_id", A)], {}),
    ("collection_sub_items", [("shared_with", A)], {"sparse": True}),
    ("client_links", [("item_id", A), ("status", A)], {}),
    ("client_links", [("id", A)], {}),
    ("commessa_counters", [("scope", A), ("year", A)], {}),
    # the commessa's diary and what hangs on it
    ("job_logs", [("id", A)], {}),
    ("job_logs", [("commessa_id", A), ("date", D)], {}),
    ("job_logs", [("collaborator_id", A), ("date", D)], {"sparse": True}),
    ("job_logs", [("user_id", A), ("date", D)], {}),
    ("job_logs", [("org_id", A), ("date", D)], {}),
    ("job_photos", [("id", A)], {}),
    ("job_activities", [("id", A)], {}),
    ("job_activities", [("commessa_id", A), ("date", A)], {}),
    ("job_activities", [("date", A), ("status", A)], {}),
    ("job_activities", [("status", A), ("date", A)], {}),
    ("job_activities", [("assignees.id", A), ("date", A)], {}),
    ("job_todos", [("id", A)], {}),
    ("job_todos", [("done", A), ("due_date", A)], {}),
    ("job_todos", [("kind", A), ("done", A), ("due_date", A)], {}),
    ("job_milestones", [("id", A)], {}),
    ("job_quotes", [("id", A)], {}),
    ("job_quotes", [("commessa_id", A), ("status", A), ("version", D)], {}),
    ("job_quotes", [("status", A), ("outcome", A)], {}),
    ("job_waits", [("id", A)], {}),
    ("job_waits", [("status", A)], {}),
    ("job_waits", [("commessa_id", A)], {}),
    ("job_extra_works", [("commessa_id", A), ("status", A)], {}),
    ("job_extra_works", [("id", A)], {}),
    ("work_reports", [("id", A)], {}),
    ("work_reports", [("user_id", A), ("created_at", D)], {}),
    ("work_reports", [("client_item_id", A)], {"sparse": True}),
    ("report_drafts", [("id", A)], {}),
    ("report_photos", [("id", A)], {}),
    ("report_photos", [("draft_id", A)], {}),
    ("archive_files", [("id", A)], {}),
    ("archive_files", [("status", A), ("user_id", A)], {}),
    # presences: the open ones are read every 5 minutes
    ("work_sessions", [("id", A)], {}),
    ("work_sessions", [("end_at", A), ("start_at", A)], {}),
    ("work_sessions", [("commessa_id", A), ("start_at", A)], {}),
    ("work_sessions", [("owner_user_id", A), ("start_at", D)], {}),
    # collaborators
    ("collaborators", [("id", A)], {}),
    ("collaborators", [("status", A), ("telegram_chat_id", A)], {}),
    ("collaborators", [("commesse", A)], {}),
    ("collaborators", [("tenant_id", A)], {}),
    # tasks, to-dos, reminders, scheduled actions
    ("tasks", [("id", A)], {}),
    ("tasks", [("user_id", A), ("due_date", A)], {}),
    ("tasks", [("due_date", A), ("reminder_sent", A)], {}),
    ("tasks", [("due_date", A), ("reminder_enabled", A)], {}),
    ("tasks", [("org_id", A), ("visibility", A)], {}),
    ("tasks", [("series_id", A)], {"sparse": True}),
    ("task_series", [("id", A)], {}),
    ("task_series", [("active", A)], {}),
    ("todos", [("id", A)], {}),
    ("todos", [("user_id", A), ("status", A)], {}),
    ("todos", [("steps.due_date", A)], {"sparse": True}),
    ("todos", [("due_date", A)], {"sparse": True}),
    ("todo_covers", [("todo_id", A)], {}),
    ("scheduled_actions", [("id", A)], {}),
    ("scheduled_actions", [("user_id", A)], {}),
    ("scheduled_actions", [("enabled", A), ("next_run_at", A)], {}),
    # knowledge base, chat, news
    ("kb_chunks", [("user_id", A), ("created_at", D)], {}),
    ("kb_chunks", [("tenant_kb", A)], {"sparse": True}),
    ("kb_chunks", [("tenant_kb", A), ("created_at", D)], {"sparse": True}),
    # the search index (search_index.py): the records still to index, the deleted ones to remove
    *((c, [("ix_h", A)], {}) for c in ("kb_chunks", "tasks", "todos", "journal_entries", "vet_reports", "work_reports",
                                         "job_logs", "collection_items", "job_doc_chunks")),
    ("search_index_gone", [("at", A)], {"expireAfterSeconds": 30 * 86400}),
    # the pieces of the documents sent on a commessa (searchable by Cerca)
    ("job_doc_chunks", [("id", A)], {}),
    ("job_doc_chunks", [("log_id", A)], {}),
    ("job_doc_chunks", [("commessa_id", A)], {}),
    ("job_doc_chunks", [("user_id", A), ("created_at", D)], {}),
    ("job_doc_chunks", [("org_id", A), ("created_at", D)], {}),
    ("job_logs", [("doc_name", A)], {"sparse": True}),
    # QR of the organizations
    ("qr_codes", [("code", A)], {"unique": True}),
    ("qr_codes", [("id", A)], {}),
    ("qr_codes", [("tenant_id", A), ("updated_at", D)], {}),
    ("qr_code_versions", [("qr_id", A), ("edited_at", D)], {}),
    ("qr_scans", [("qr_id", A), ("at", D)], {}),
    ("kb_chunks", [("doc_id", A)], {}),
    ("kb_chunks", [("chunk_id", A)], {}),
    ("kb_documents", [("doc_id", A)], {}),
    ("kb_documents", [("user_id", A)], {}),
    ("journal_entries", [("id", A)], {}),
    ("journal_entries", [("user_id", A), ("date", D)], {}),
    ("conversations", [("conv_id", A)], {}),
    ("conversations", [("user_id", A), ("created_at", D)], {}),
    ("news_items", [("id", A)], {}),
    ("news_items", [("user_id", A), ("created_at", D)], {}),
    ("suggestions_ai", [("user_id", A)], {}),
    ("lesson_templates", [("id", A)], {}),
    ("work_templates", [("id", A)], {}),
    ("watch_pairings", [("pair_id", A)], {}),
    ("watch_pairings", [("code", A)], {}),
    ("watch_devices", [("device_id", A)], {}),
    # the periodic jobs' own leases (see jobs.py)
    ("job_leases", [("name", A)], {"unique": True}),
)


async def ensure_indexes(db, indexes: Iterable = INDEXES) -> int:
    """Creates the missing ones. -> how many could not be created (logged)."""
    failed = 0
    for coll, keys, opts in indexes:
        try:
            await db[coll].create_index(keys, **opts)
        except Exception:
            failed += 1
            logger.exception("index %s %s not created", coll, keys)
    return failed
