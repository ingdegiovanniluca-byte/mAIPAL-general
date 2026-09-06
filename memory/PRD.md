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

## Implemented (2026-02-06 - iteration 10)
- **Chat: nuova azione "Diario"**. Le 4 action card sono ora **icone-only** (`action-query`, `action-upload`, `action-todo`, `action-journal`) con tooltip on-hover. Ordine: Richiesta info (prima) → Upload → Task/To-Do → Diario. Quando "Diario" è attiva e l'utente invia un messaggio, viene salvata una voce in `journal_entries` con title/mood/highlights via LLM.
- **Chat: selettore scope per Richiesta info** (`scope-all` / `scope-kb`). Con `scope=all` la RAG cerca anche in `tasks`, `todos`, `journal_entries` oltre che in `kb_chunks`.
- **Journal: microfono** (`journal-mic-btn`) — MediaRecorder + Whisper, la trascrizione viene appesa al campo diario.
- **Journal: grafico trend umore** (Recharts LineChart) con selettore `trend-7 / trend-30 / trend-90`. Endpoint `/api/journal/trend?days=N` mappa mood→score (grato/felice=5, energico=4, neutro/riflessivo=3, stanco=2, stressato=1).
- **Journal: ricerca e filtri**. `journal-search` (case-insensitive, ReDoS-safe via `re.escape`) + `mood-filter-all / mood-filter-{felice,grato,energico,riflessivo,neutro,stanco,stressato}`. Il filtro per mood è server-side (`GET /api/journal?q=…&mood=…`).
- Verificato end-to-end da testing_agent (iteration_8.json): backend 11/11, frontend 100%.

## Implemented (2026-02-06 - iteration 9)
- **Diario (Journal)**: pagina `/dashboard/journal`, endpoint `POST/GET/DELETE /api/journal`, LLM riscrive testo + estrae mood + highlights
- **Task complete**: `POST /api/tasks/{id}/complete` (toggle) e chip "Segna come fatto" sulla card
- **Weekly recap Telegram**: la domenica alle 19:00 UTC, riepilogo settimanale con task completati + task/todo aperti
- **Font Poppins** globale (via `index.css` + `tailwind.config.js`)
- Action cards condensate in una singola riga a sinistra


- **Google Drive + Calendar OAuth** (playbook completo pronto, endpoint `/api/integrations/google/authorize`, `/callback`, `/disconnect`). Auto-crea cartella `mAIPAL` su Drive al primo collegamento. Toggle `calendar_synced` sui task crea/rimuove eventi sul Calendar primario. **Richiede** `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` (attualmente vuoti in .env - vedi UI Impostazioni per istruzioni).
- **Voice STT**: `/api/voice/transcribe` con OpenAI Whisper via Emergent LLM Key. Frontend: pulsante mic in Chat usa MediaRecorder (webm), invia al backend, inserisce trascrizione in textarea.
- **Telegram Bot** (`@mAIPAL_bot`): long polling attivo su avvio backend. Comandi `/start <codice>`, `/ask`, `/save`, `/task`, `/help`. Messaggi liberi: rilevamento azione automatico (info_request / info_upload / task_todo). Pagina Impostazioni con generatore codice + deep link.
- **Pagina Impostazioni** (`/dashboard/settings`) con tile Google e Telegram
- Fix 404 corretto su PATCH/DELETE /api/tasks|todos/{id}

## Implemented (2026-02-06 - iteration 1)
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
