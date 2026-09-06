# mAIPAL - Product Requirements Document

## Original Problem Statement
Build **mAIPAL** — un assistente personale AI (segretario digitale) con knowledge base personalizzata, multi-canale (Web + Telegram) e integrazioni con Google Workspace/Microsoft 365, Supabase e n8n. I messaggi degli utenti sono analizzati e interpretati da un modello LLM (Claude Sonnet 5) per compiere l'azione richiesta o rispondere all'utente. UX ispirata ad Apple / music apps, come nei mockup forniti.

## User Personas
- **Professionista organizzato**: usa mAIPAL come segretario per task/promemoria di lavoro
- **Utente ibrido lavoro/personale**: gestisce anche tempo libero, palestra, viaggi
- **Knowledge worker**: archivia note/documenti e li interroga tramite RAG personale

## Architecture (implemented)
- Frontend: React 19 + Tailwind + shadcn/ui, React Router v7
- Backend: FastAPI + Motor (MongoDB async)
- LLM: Claude Sonnet 5 via `emergentintegrations` (streaming NDJSON)
- Auth: Emergent Google Auth (session token in httpOnly cookie)
- Storage: MongoDB (users, user_sessions, conversations, tasks, todos, kb_chunks)

## Implemented (2026-02-06)
- **Auth flow**: Login page → Emergent Google Auth → `AuthCallback` (hash session_id) → `/api/auth/session` → dashboard
- **Onboarding**: 4-step wizard (professione/settore, verticali, interessi, tono) → personalizza system prompt LLM
- **Dashboard shell**: headline "Cosa vuoi fare, {name}?" con parola gradient, tab pills (Chat / Task Board / To-Do)
- **Chat**:
  - 3 action cards (Caricamento info / Richiesta info / Task-ToDo) con SELEZIONA/ATTIVO
  - Contextual input area (paperclip, mic placeholders, model badge "CLAUDE SONNET 5", pill "Invia", shortcut ⌘/Ctrl+⏎)
  - Streaming risposta via NDJSON
  - Cronologia con search, filtri (Tutti/Upload/Query/ToDo), date picker, badge pipeline (Claude / n8n · skip / MongoDB)
- **Task Board**: kanban 3 colonne priorità (Alta/Media/Bassa) con tint colonna, left-border colored, highlight della scadenza più imminente, tag chips, dialog contestuale con chat LLM per modifiche + toggle Calendar (mock) + delete
- **To-Do Board**: kanban 3 stati (Da fare/In corso/Fatti), progress bar per In corso, priorità opzionale, dialog contestuale con chat LLM + status buttons + progress slider
- **LLM interpretation**:
  - `info_upload` → estrae titolo/tag/sintesi, salva chunk in `kb_chunks`
  - `info_request` → RAG semplificato (Mongo regex sui chunk personali) + risposta contestuale
  - `task_todo` → LLM restituisce ```json``` block, backend crea task (se due_date) o todo
- **Multi-user isolation** via `user_id` filter in ogni query (verificato)

## Deferred (P1/P2)
- **P1** Google Drive/Calendar OAuth + auto-creazione cartella "mAIPAL"
- **P1** Microsoft OneDrive/Outlook OAuth (alternativa)
- **P1** Telegram bot linked account
- **P1** n8n webhook triggers per automazioni
- **P2** Voice STT (registrazione microfono → trascrizione)
- **P2** Image/file upload con OCR + salvataggio Supabase Storage / Emergent Object Storage
- **P2** pgvector-style embeddings (attualmente Mongo text/regex search)
- **P2** Knowledge base organizzazione (multi-tenant)
- **P2** Web search fallback come 3° step della cascata RAG
- **P2** Dark mode

## Testing Notes
- Test session cookie seed: `test_session_demo_12345` for `test-user-demo` (Marco Rossi)
- See `/app/auth_testing.md` and `/app/memory/test_credentials.md`
- Full backend + frontend E2E passed in `/app/test_reports/iteration_1.json`

## Known Polish (LOW priority)
- PATCH /api/tasks|todos/{id} returns 200 null instead of 404 when cross-user or missing (data safe)
- User.created_at as Optional[str] is strict; admin seed scripts must use ISO strings
