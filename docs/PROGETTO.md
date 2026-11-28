# mAIPAL: come è fatto il progetto

Questo documento descrive tutto il progetto: cosa fa, come è costruito e dove si usano i modelli di intelligenza artificiale.

Serve a uno scopo preciso: **cambiare il modello che interpreta i messaggi dell'utente** mantenendo interfaccia e funzionalità. L'obiettivo è che l'utente **scriva e basta**, senza dover scegliere l'agente (Cerca, Salva, Task, Diario, Report…) né dire che tipo di richiesta sta facendo.

- Le parti più importanti per questo scopo sono i capitoli **6** (come viaggia un messaggio), **7** (inventario dei modelli), **8** (scrivi e basta) e **9** (come cambiare modello).
- Il resto serve a orientarsi nel codice.

**L'app** (pagine, stile, comportamenti, schermate e l'elenco di tutte le chiamate al server) è descritta in **`docs/FRONTEND.md`**. Il frontend non parla mai con un modello: per cambiare modello l'interfaccia resta identica.

Aggiornato a: 27/11/2026, ramo `claude/analyze-main-branch-175dis`.

---

## Indice

1. [Cos'è mAIPAL](#1-cosè-maipal)
2. [Architettura](#2-architettura)
3. [Struttura delle cartelle](#3-struttura-delle-cartelle)
4. [Dati](#4-dati)
5. [Funzionalità, sezione per sezione](#5-funzionalità-sezione-per-sezione)
6. [Come viaggia un messaggio](#6-come-viaggia-un-messaggio)
7. [Inventario dei modelli](#7-inventario-dei-modelli)
8. [Obiettivo: «scrivi e basta»](#8-obiettivo-scrivi-e-basta)
9. [Come cambiare modello](#9-come-cambiare-modello)
10. [Configurazione (.env)](#10-configurazione-env)
11. [Avvio, aggiornamento e test](#11-avvio-aggiornamento-e-test)
12. [Backup e ripristino](#12-backup-e-ripristino)
13. [Regole del progetto](#13-regole-del-progetto)

---

## 1. Cos'è mAIPAL

mAIPAL è un **assistente con intelligenza artificiale** per piccole imprese, professionisti e privati.

- **Cosa fa l'utente**: scrive (o detta, o manda foto e documenti) e mAIPAL:
  - salva le informazioni;
  - risponde alle domande;
  - crea task e promemoria;
  - tiene il diario;
  - genera report e documenti.
- **Canali**:
  - **web app** installabile sul telefono (PWA, all'indirizzo `/general`);
  - **bot Telegram**;
  - **app per Galaxy Watch** (cartella `wearos/`).
- **Verticali** (il settore dell'utente, scelto in Impostazioni): cambiano agenti e sezioni.
  - **Artigiano**: clienti e commesse, diario di commessa, ore in cantiere, materiali, preventivi, report di sopralluogo e intervento, collaboratori esterni su Telegram, avanzamento al cliente, QR (con la lista Attrezzatura: chi ha preso un attrezzo).
  - **Veterinario**: pazienti e referti.
  - **Fitness**: lezioni ed esercizi.
  - **Nessuno**: assistente personale (diario personale, task, liste, documenti).
- **Organizzazioni**:
  - ogni account appartiene a un'organizzazione (l'impresa), con amministratori, utenti e collaboratori;
  - dentro l'organizzazione ci sono i team, con limiti di abbonamento e regole di condivisione;
  - nulla di un'organizzazione è visibile a un'altra.
- **Lingua**: tutto in **italiano**.
- **Regola fondamentale**: l'AI **non inventa mai dati**. Ore, misure, prezzi e date vengono solo da quello che l'utente ha scritto o dal database.

La guida completa per l'utente, una sezione per funzione, è in `backend/help/mAIPAL-help.md`. È anche la guida che l'app mostra (la «i» accanto ai titoli) e che l'agente Cerca usa per rispondere alle domande su come si usa l'app.

---

## 2. Architettura

```
                 Browser / PWA (React)                Telegram            Galaxy Watch
                         │ https://…/general              │                     │
                         ▼                                 │                     │
                ┌──────────────────┐                       │                     │
                │ frontend (nginx) │  file statici + /api ─┼─────────────────────┤
                └────────┬─────────┘                       │                     │
                         │ /general/api/*                  │                     │
                         ▼                                 ▼                     ▼
   ┌───────────────────────────────┐        ┌────────────────────────────────────────┐
   │ backend  (ROLE=api)           │        │ worker (ROLE=worker)                   │
   │ FastAPI, server.py            │        │ stesso codice: job periodici           │
   │ richieste dell'app            │        │ (promemoria, presenze, riepiloghi,     │
   │ (scalabile: --scale backend=N)│        │  news, indice di ricerca) + bot        │
   └──────┬───────────────┬────────┘        │ Telegram (solo il «leader»)            │
          │               │                 └──────┬──────────────┬──────────────────┘
          ▼               ▼                        ▼              ▼
   ┌────────────┐  ┌─────────────┐          (stessi MongoDB e Qdrant)
   │ MongoDB 7  │  │ Qdrant      │
   │ dati+GridFS│  │ indice      │     Servizi esterni: OpenAI (modelli, Whisper, ricerca web news),
   └────────────┘  │ di ricerca  │     Google (login, Drive, Calendar), Microsoft (OneDrive, Outlook),
                   └─────────────┘     Telegram Bot API, Open-Meteo (meteo), OpenStreetMap (indirizzi)
```

- **Frontend**: React 19 con CRA e craco, Tailwind e componenti shadcn/ui; è una PWA con service worker e funziona anche offline.
  - Pagine in `frontend/src/pages`, componenti in `frontend/src/components`.
  - Stile: font Poppins, vetro smerigliato su sfondo sfumato, tema scuro e chiaro.
  - Viene compilato con `PUBLIC_URL=/general` e servito da nginx (`frontend/Dockerfile`).
- **Backend**: Python 3.11, FastAPI e Motor (MongoDB asincrono).
  - Quasi tutte le API sono in `backend/server.py` (circa 20.000 righe); la logica di dominio sta nei moduli accanto (capitolo 3).
  - Tutte le API sono sotto `/api`; Cloudflare e nginx le espongono come `/general/api`.
- **Worker**: stessa immagine con `ROLE=worker`.
  - Esegue i job periodici (`backend/jobs.py`) con «lease» su MongoDB, così ogni job gira su una sola copia.
  - Esegue anche il bot Telegram (`telegram_bot.py`, `collab_telegram.py`, `client_telegram.py`).
- **Indice di ricerca**: Qdrant (`backend/search_index.py`).
  - Contiene una copia di ciò che è cercabile, ricostruibile da MongoDB.
  - La ricerca rilegge sempre i dati da MongoDB con i permessi dell'utente.
- **Embeddings**: calcolati **in locale** con fastembed (modello multilingue MiniLM, `backend/embeddings.py`). Nessun costo e nessun servizio esterno.
- **Deploy**: `docker-compose.yml` su un PC o server, esposto con Cloudflare Tunnel (vedi `DEPLOY.md`).

---

## 3. Struttura delle cartelle

```
.
├── docker-compose.yml        servizi: mongodb, backend, worker, qdrant, frontend
├── .env.example              tutte le variabili (copiare in .env)
├── DEPLOY.md                 installazione, Google/Microsoft, Cloudflare, più organizzazioni, indice
├── docs/
│   ├── PROGETTO.md           questo documento
│   └── gap-analysis-commesse.md
├── scripts/                  avvio/arresto (Windows) e backup dei dati
├── backend/
│   ├── server.py             TUTTE le API (FastAPI); i flussi della chat e degli agenti
│   ├── llm_integrations.py   LlmChat: chiamata a un modello (OpenAI o Anthropic), testo e immagini, streaming; Whisper
│   ├── router.py             il router: a quale agente va un messaggio (4 livelli) - vedi cap. 8
│   ├── router_golden.jsonl   122 esempi etichettati per misurare il router
│   ├── agent_guard.py        «hai scelto l'agente sbagliato?» (prima di una chat nuova)
│   ├── telegram_bot.py       il bot Telegram dell'utente (classifica i messaggi liberi)
│   ├── collab_telegram.py    i collaboratori esterni su Telegram (diario, ore, arrivo/fine)
│   ├── client_telegram.py    i clienti collegati su Telegram (avanzamento lavori)
│   ├── job_logs.py           diario di commessa: interpretazione note, foto materiali, preventivi, extra, domande
│   ├── work_reports.py       report di sopralluogo/intervento/commessa: interpretazione e documento Word
│   ├── vet_reports.py        referti veterinari: interpretazione e documento Word
│   ├── list_updates.py       modifica e creazione delle liste da linguaggio naturale
│   ├── scheduled_actions.py  azioni programmate («ogni venerdì svuota la lista…»)
│   ├── retrieval.py          ricerca (Cerca): KB, task, liste, commesse, con permessi
│   ├── search_index.py       indice Qdrant: sincronizzazione e richiamo
│   ├── embeddings.py         embeddings locali (fastembed)
│   ├── help_guide.py         la guida dell'app: sezioni, «la domanda è sull'app?»
│   ├── news_service.py       news quotidiane (ricerca web del modello)
│   ├── usage_tracking.py     consumi e costi di ogni chiamata ai modelli (collezione llm_calls)
│   ├── qr_tags.py, file_store.py   QR (stili, codici) e file (GridFS)
│   ├── site_presence.py, team_presence_tg.py, nearby.py, weather.py, recurrence.py, …
│   ├── help/mAIPAL-help.md   la guida per l'utente
│   ├── data/access/          chi può entrare come amministratore (org_admins.txt)
│   ├── scripts/              router_eval.py (misura del router), isolation_probe.py, …
│   └── tests/                test unitari + tests/integration/it_*.py (DB finto, modelli finti)
├── frontend/
│   ├── src/App.js            le pagine: /dashboard/{chat,tasks,todos,journal,oggi,news,liste,documents,fitness,azioni,qr,settings}, /q/:code
│   ├── src/pages/ChatPage.jsx       la chat e gli agenti (la parte da cambiare per «scrivi e basta»)
│   ├── src/pages/JobDiaryPage.jsx   diario di commessa (artigiano)
│   ├── src/pages/…           Task, To-Do, Liste, Documenti, News, Azioni, QR, Impostazioni, …
│   ├── src/components/       FormFields (campi del modulo), GlassMenu, IosSwitch, StatTiles, QrArViewer, …
│   └── src/lib/              api.js (axios), arPose.js (realtà aumentata), …
└── wearos/                   app Android per Galaxy Watch (Kotlin)
```

---

## 4. Dati

**MongoDB** (database `DB_NAME`). Le collezioni principali, per area:

| Area | Collezioni |
|---|---|
| Account e accesso | `users`, `user_sessions`, `tenants` (organizzazioni: piano, regole, logo), `organizations` (team), `tenant_invites`, `team_invites`, `allowed_emails`, `google_login_states`, `google_oauth_states`, `ms_oauth_states`, `integrations` (token Google/Microsoft) |
| Chat e agenti | `conversations` (una chat = una conversazione, con i messaggi), `router_shadow` (decisioni del router in ombra), `suggestions_ai`, `feature_events` |
| Informazioni (Salva/Cerca) | `kb_documents`, `kb_chunks` (testo a pezzi + embedding), `archive_files`, `pending_drive_uploads` |
| Task e to-do | `tasks`, `task_series` (ricorrenze), `todos`, `todo_covers`, `scheduled_actions` |
| Diario | `journal_entries` (personale) |
| Liste | `collections`, `collection_items`, `collection_sub_items` (anche Clienti → commesse) |
| Commesse (artigiano) | `job_logs` (le voci del diario), `job_economics`, `job_activities`, `job_milestones`, `milestone_templates`, `job_todos`, `job_quotes`, `job_extra_works`, `extra_not_works`, `job_photos`, `job_contacts`, `job_waits`, `job_doc_chunks`, `commessa_drafts`, `commessa_counters`, `commessa_history`, `work_sessions` (presenze), `collaborators`, `client_links` |
| Report | `work_reports`, `report_drafts`, `report_photos`, `work_templates`, `vet_reports`, `vet_templates` |
| Fitness | `exercises`, `fitness_equipment`, `fitness_setup`, `lesson_types`, `lesson_templates`, `lesson_guidelines` |
| QR | `qr_codes`, `qr_code_versions`, `qr_scans`, `qr_passes` |
| News | `news_items`, `news_source_feedback` |
| Telegram e Watch | `telegram_links`, `telegram_sessions`, `watch_devices`, `watch_pairings`, `watch_pair_failures` |
| Notifiche | `push_subscriptions`, `push_log` |
| Consumi | `llm_calls` (ogni chiamata a un modello: token, costo, funzione), `llm_pricing` (prezzi per modello), `usage_daily` |
| Sistema | `job_leases` (job periodici), `app_settings`, `delete_codes` |

- **File**: foto, PDF e modelli 3D dei QR, oltre al logo dell'organizzazione, sono in **GridFS** (bucket `files`) dentro MongoDB. Il resto dei file degli utenti va su Google Drive o OneDrive, se collegati.
- **Qdrant**: l'indice di ricerca. Si può perdere: il worker lo ricostruisce da MongoDB.
- **Isolamento**: ogni query filtra per utente, team o organizzazione. Lo script `backend/scripts/isolation_probe.py` e i test lo verificano.

---

## 5. Funzionalità, sezione per sezione

La guida utente (`backend/help/mAIPAL-help.md`) ha una sezione per ognuna. In sintesi:

| Sezione (app) | Cosa fa | Dove nel codice |
|---|---|---|
| **Chat** (`/dashboard/chat`) | Il cuore: si scrive, si detta o si allegano file; uno degli **agenti** risponde. Cronologia, @tag per mandare pezzi ad altri agenti | `ChatPage.jsx`; `server.py` `/chat/stream`, `/agents/dispatch`, `/agents/check` |
| Agente **Cerca** | Risponde a domande sui dati salvati, task, liste, commesse, presenze, clienti vicini, sul web e su come si usa l'app | `retrieval.py`, `search_index.py`, `help_guide.py`, `server.py` |
| Agente **Salva** | Salva informazioni (testo, foto con OCR, documenti), modifica o crea liste, legge preventivi nella chat | `server.py` (`_classify_document`, `_ocr_image_bytes`), `list_updates.py` |
| Agente **Task** | Crea, sposta e completa task e promemoria, anche ricorrenti | `server.py` (`_extract_task_meta`, `interpret_task_command`), `recurrence.py` |
| **Task e To-Do** | Una sezione: task per giornata (oggi per ora di avvio, scaduti, giorni successivi), calendario del mese, to-do in Da fare / In corso / Fatto con passi suggeriti | `TaskBoardPage.jsx`, `TodoDetail.jsx` |
| **Diario** | Personale (non artigiano) | `JournalPage.jsx`, `server.py` `create_journal` |
| **Dashboard Oggi** (artigiano) | La giornata: cantieri, chi c'è, attività, scadenze | `TodayPage.jsx` |
| **Diario di commessa** (artigiano) | Note di cantiere interpretate (ore, materiali, problemi, attività, arrivo/fine), foto, preventivi, tappe, costi, lavori extra, condivisione | `JobDiaryPage.jsx`, `job_logs.py`, `site_presence.py` |
| **Report** (artigiano) | Sopralluogo, intervento, SAL, report di commessa, varianti → Word con logo e firme | `work_reports.py` |
| **Referto** (veterinario) | Referto della visita → Word | `vet_reports.py` |
| **Liste** / **Clienti e commesse** | Liste personalizzate; Clienti con le commesse | `CollectionsPage.jsx`, `list_updates.py` |
| **Documenti** | Base di conoscenza (KB) con ricerca per significato | `DocumentsPage.jsx` |
| **News** | Notizie quotidiane per gli interessi dell'utente | `news_service.py` |
| **Azioni** | Comandi programmati ripetuti nel tempo | `scheduled_actions.py`, `ActionsPage.jsx` |
| **QR** | Etichette per attrezzi e cantieri: contenuto modificabile, pubblico o privato, solo in un luogo, foto e PDF; attrezzi con Prendi / Restituisci e lista Attrezzatura (la realtà aumentata è per ora tolta) | `QrPage.jsx`, `QrScanPage.jsx`, `qr_tags.py` |
| **Fitness** | Lezioni ed esercizi | `FitnessPage.jsx`, `fitness.py` |
| **Impostazioni** | Profilo, logo organizzazione, verticale, collegamenti (Google, Microsoft, Telegram, orologio), notifiche, team, collaboratori, organizzazione | `SettingsPage.jsx`, `TeamPanel.jsx`, `AdminPage.jsx` |
| **Telegram** | Tutto via chat: il bot classifica i messaggi liberi; collaboratori e clienti hanno flussi propri | `telegram_bot.py`, `collab_telegram.py`, `client_telegram.py` |
| **Notifiche** | Push nell'app e/o Telegram, per tipo | `push_notify.py`, `notify_prefs.py` |
| **Offline** | Diario e app aperta anche senza rete (coda di invio) | service worker, `OfflineStrip.jsx` |

---

## 6. Come viaggia un messaggio

### 6.1 Nell'app (oggi)

1. **L'utente sceglie l'agente**: nella chat c'è la fila di pulsanti Cerca / Salva / Task / Diario / Report / Referto / Lezioni / Azioni, a seconda del verticale.
   - L'agente scelto è `action` (`info_request`, `info_upload`, `task_todo`, `journal` / `job_log`, `work_report`, `vet_report`, `lesson`, `scheduled_action`).
2. **Controllo dell'agente** (solo per una chat nuova): `POST /agents/check` chiama `agent_guard.check`, un modello piccolo.
   - Se il messaggio va *sicuramente* a un altro agente, la chat lo suggerisce invece di rispondere.
3. **Router «in ombra»**: `POST /router/shadow` fa decidere in background al router (`router.py`) dove *avrebbe* mandato il messaggio.
   - Salva il confronto in `router_shadow`, così si misura il router sull'uso reale.
   - **Oggi non decide niente.**
4. **Risposta**: dipende dall'agente.
   - Cerca, Task e Diario personale passano da `POST /chat/stream`.
   - Salva prima chiama `POST /classify-save-intent`: nota, modifica di una lista, nuova lista o preventivo. Poi va al flusso giusto (`/lists/update`, …).
   - Diario di commessa, Report, Referto, Lezioni e Azioni hanno i loro endpoint e flussi a più passi, con domande e pulsanti di conferma.
5. **Più richieste in un messaggio**: l'utente può scrivere `@task …` o `@diario …` dentro il messaggio. La parte prima del primo @ va all'agente scelto, i pezzi taggati vanno ai loro agenti (`/agents/dispatch`, `_run_sub_agent`).
6. **Voce**: `POST /voice/transcribe` usa Whisper; il testo segue il percorso normale.
7. **Foto e file**: OCR con un modello che legge le immagini (`_ocr_image_bytes`), classificazione del documento, salvataggio nella KB.

### 6.2 Su Telegram (oggi)

- I comandi `/ask`, `/save`, `/task`, `/journal`, `/report`, `/lista`, `/azione` mandano il messaggio direttamente all'agente.
- I **messaggi liberi** sono già classificati automaticamente da `telegram_bot._classify_intent` (un modello piccolo), con il contesto dell'ultimo scambio e i nomi delle liste. Poi `_process_action` esegue l'agente.
- Anche qui il router gira in ombra.
- Vocali → Whisper; foto e documenti → OCR e KB, oppure diario di commessa.

### 6.3 Il formato delle risposte dei modelli

Quasi ogni chiamata chiede al modello **JSON** (`response_format={"type": "json_object"}`) con campi precisi. Il codice poi:
- **controlla** ogni campo (date, ore e materiali vengono rifiutati se non sono scritti nel messaggio: funzioni `said_in`, `clean_*` in `job_logs.py`);
- **non usa mai** un valore che il modello ha inventato.

Gli agenti che rispondono in chat (Cerca, Task) restituiscono testo libero con, in coda, un blocco di metadati JSON (`_extract_meta` in `server.py`).

---

## 7. Inventario dei modelli

Oggi tutto usa **OpenAI**:
- `gpt-4o` per capire e scrivere;
- `gpt-4o-mini` per classificare e per i compiti semplici;
- `whisper-1` per la voce;
- la ricerca web di OpenAI per le news.

Gli **embeddings** sono **locali** (fastembed) e non dipendono da un fornitore. `ANTHROPIC_API_KEY` è supportata da `LlmChat` ma oggi non è usata.

Le chiamate sono **circa 48**, in due forme:
- **(L)**: tramite `LlmChat` (`llm_integrations.py`): `LlmChat(...).with_model("openai", "<modello>")` e `send_message` / `stream_message`. Già oggi può usare Anthropic cambiando `with_model("anthropic", "<modello>")`.
- **(D)**: chiamata **diretta** `openai.AsyncOpenAI(...).chat.completions.create(...)`, quasi sempre con risposta JSON.

### 7.1 Interpretare il messaggio: a chi va e cosa chiede

| File · funzione | Modello | Cosa fa | Forma |
|---|---|---|---|
| `router.py` · `by_model` (livello 3 del router) | `ROUTER_MODEL` (gpt-4o-mini), timeout 2,5 s | A quale agente va il messaggio: intent, confidence, second, reason | D, JSON |
| `telegram_bot.py` · `_classify_intent` | gpt-4o-mini | Classifica i messaggi liberi su Telegram (oggi attivo) | L |
| `agent_guard.py` · `check` | gpt-4o-mini | «L'agente scelto è sicuramente sbagliato?» | D, JSON |
| `list_updates.py` · `classify_save_intent` | gpt-4o-mini | In Salva: nota / modifica lista / nuova lista | D, JSON |
| `help_guide.py` · `is_about_app` | gpt-4o-mini | La domanda è su come si usa l'app? | D |
| `server.py` · `_ensure_conv_topics` | gpt-4o-mini | Argomenti della conversazione (cronologia) | L |

### 7.2 Capire i dettagli e agire (gli agenti)

| File · funzione | Modello | Cosa fa | Forma |
|---|---|---|---|
| `server.py` · `_agent_llm`, `task_chat`, `todo_chat`, `_fmt` (risposta di Cerca e degli agenti in chat) | gpt-4o | Risposta in chat, con metadati JSON in coda | L (stream) |
| `telegram_bot.py` · `_process_action` / `_fmt` | gpt-4o | Lo stesso su Telegram | L |
| `server.py` · `_extract_task_meta`, `interpret_task_command` | gpt-4o-mini | Dati del task (titolo, data, ricorrenza), segna fatto/sposta/elimina | L, JSON |
| `server.py` · `suggest_todo_steps` | gpt-4o | Passi di un to-do | L |
| `server.py` · `create_journal` | gpt-4o | Diario personale | L |
| `job_logs.py` · `interpret` | gpt-4o | **Nota di cantiere** → ore, persone, materiali, problemi, attività, arrivo/fine | D, JSON |
| `job_logs.py` · `read_photo_materials` | gpt-4o (visione) | Materiali da una foto | D, JSON, immagini |
| `job_logs.py` · `read_new_commessa`, `read_activity`, `correct_note` | gpt-4o | Nuova commessa da testo, attività, correzione di una nota | D, JSON |
| `job_logs.py` · `read_document`, `read_quote` | gpt-4o (fino a 8000 token in uscita) | Documenti e **preventivi** (voci, importi) | D, JSON |
| `job_logs.py` · `survey_summary`, `find_extras`, `pick_similar`, `answer` | gpt-4o | Riassunto sopralluogo, lavori extra, commesse simili, risposte sulla commessa | D, JSON |
| `list_updates.py` · `interpret_list_request`, `interpret_list_creation` | gpt-4o | Modifica e creazione delle liste | D, JSON |
| `scheduled_actions.py` · `interpret_command`, `describe_action`, `write_report` | gpt-4o / gpt-4o-mini | Azioni programmate | D, JSON |
| `work_reports.py` · `interpret`, `revise`, `commessa_summary` | gpt-4o | Report: riempie le sezioni dal dettato, revisioni, riassunto di commessa | D, JSON |
| `vet_reports.py` · `interpret_visit` | gpt-4o | Referto veterinario | D, JSON |
| `client_updates.py` · `summarize` | gpt-4o | Avanzamento settimanale al cliente | D, JSON |
| `server.py` · `_lesson_llm` | variabile | Lezioni di fitness | L |
| `server.py` · `_resolve_drive_folder_hint` | gpt-4o-mini | Cartella Drive nominata in un messaggio | L |

### 7.3 Immagini, voce, web

| File · funzione | Modello | Cosa fa |
|---|---|---|
| `server.py` · `_ocr_image_bytes` | gpt-4o-mini (visione) | Testo da foto e scansioni (OCR) |
| `server.py` · `_classify_document` | gpt-4o-mini | Categoria e parole chiave di un documento |
| `server.py` · `voice_transcribe`; `telegram_bot.py` · `_msg_voice`; `collab_telegram.py` · `_transcribe` | whisper-1 | Voce → testo (italiano) |
| `news_service.py` · `generate_news_for_user` | `NEWS_MODEL` (gpt-4o-mini) + ricerca web (`responses.create`, `web_search_preview`) | News quotidiane |
| `server.py` · `_generate_ai_insights` | gpt-4o-mini | Suggerimenti |

### 7.4 Consumi

- Ogni chiamata registra token, costo e funzione in `llm_calls` (`usage_tracking.py`).
- I prezzi per modello sono in `llm_pricing`. Con un modello nuovo va aggiunta la sua riga, altrimenti il costo resta vuoto: non si rompe niente, ma il conteggio dei costi è incompleto.

---

## 8. Obiettivo: «scrivi e basta»

**Oggi nell'app l'utente deve scegliere l'agente.** L'obiettivo è togliere questa scelta: l'utente scrive (o detta, o allega) e mAIPAL capisce da solo:
- quale agente serve;
- se nello stesso messaggio ci sono più richieste;
- cosa chiede ciascuna.

### 8.1 Cosa c'è già

- **`backend/router.py`**: il router completo, pensato per questo («scrivi e basta») e già usato in ombra. Decide in quattro livelli, e il primo che decide vince.
  1. **Contesto, senza modello**:
     - mAIPAL ha fatto una domanda → stesso agente;
     - `@agente` scritto;
     - solo foto (artigiano) → diario di commessa.
  2. **Regole, senza modello**: frasi mai ambigue («ricordami di…», «salva che…», una domanda, «4 ore dai Rossi, posato…»). Sono scritte per essere **precise**: quando non sono sicure tacciono.
  3. **Modello** (`by_model`): un modello veloce con il contesto (agente della conversazione, ultimi messaggi, verticale, liste, commesse aperte). Restituisce intent, confidence, seconda scelta e motivo. Ha un timeout.
  4. **Ripiego**: l'agente della conversazione, altrimenti la regola più probabile, chiedendo all'utente.
  - Poi le **soglie** (`GO` = 0,80, `SHOW` = 0,55, `RISKY_GO` = 0,90):
    - sicuro → va;
    - abbastanza sicuro → va mostrando «→ Task · cambia»;
    - incerto → **chiede con due pulsanti**.
    - Ciò che cambia o cancella dati (azioni programmate) richiede più sicurezza.
  - `route()` **decide soltanto**, non esegue nulla. È pensato per servire sia l'app sia Telegram.
- **Misura**:
  - `router_golden.jsonl`: 122 esempi etichettati, anche ambigui;
  - `tests/test_router.py`: le regole non sbagliano mai sugli esempi;
  - `scripts/router_eval.py`:
    - `--golden`: precisione sugli esempi con il modello vero;
    - `--history`: confronto con le scelte reali degli utenti nelle conversazioni;
    - `--shadow`: quanto il router in ombra è d'accordo con l'agente usato;
    - `--replay`: rigioca i messaggi registrati con una nuova versione del router.
- **Telegram**: i messaggi liberi sono già classificati da un modello (`_classify_intent`), quindi lì «scrivi e basta» funziona già, con un classificatore separato.
- **Più richieste**: la gestione dei pezzi (`_run_sub_agent`, `/agents/dispatch`) esiste già per i @tag. Il router restituisce già una `second` (seconda richiesta) e un campo `parts`, previsto ma non ancora riempito.

### 8.2 Cosa manca

1. **Il modello del livello 3**: è il punto dove entra il nuovo modello.
   - Deve rispondere in pochi decimi di secondo, in italiano, con JSON affidabile.
   - Conviene che restituisca anche le **parti** quando il messaggio contiene più richieste: `{"parts": [{"intent", "text"}...]}`. Il codice per eseguirle c'è già.
   - Se si sceglie un modello più capace, può fare in una sola chiamata **routing + estrazione** (agente + dati), e alcuni passi successivi diventano più semplici. Conviene però farlo per gradi: prima il routing, poi il resto.
2. **Accendere il router nella chat dell'app** (`frontend/src/pages/ChatPage.jsx` + un endpoint, per esempio `POST /router/route`):
   - modalità predefinita **Automatico**: nessun agente scelto;
   - si chiama il router e si usa `mode`:
     - `go` → l'agente;
     - `go_show` → l'agente, con la pillola «→ Task · cambia»;
     - `ask` → due pulsanti;
   - la fila degli agenti resta, come scelta facoltativa per chi vuole forzare;
   - una conversazione resta di un agente finché il router non vede un cambio (lo fa già con il contesto).
3. **Un solo cervello per app e Telegram**: sostituire `telegram_bot._classify_intent` con `router.route`, così il comportamento è lo stesso ovunque e si misura in un posto solo.
4. **Togliere i controlli che diventano inutili**: `agent_guard` («hai scelto l'agente sbagliato») e il pre-classificatore di Salva (`classify_save_intent`) possono confluire nel router. Le intenzioni interne diventano più fini: nota, modifica lista, nuova lista, preventivo.
5. **Soglie e misura**:
   - prima di accendere, misurare con `router_eval.py --golden` e `--shadow` sul server, con il nuovo modello;
   - criteri suggeriti: **0 errori gravi** sugli esempi non ambigui (un messaggio mandato all'agente sbagliato con sicurezza); tempo mediano sotto 1 s; nei dati in ombra, accordo con le scelte degli utenti di almeno il 90%;
   - le disaccordanze vanno lette una per una: a volte sbagliava l'utente.

### 8.3 Piano suggerito

1. Rendere configurabile il modello del router (fornitore + modello in `.env`, capitolo 9) e misurare il nuovo modello con `router_eval.py --golden`.
2. Lasciarlo in ombra 1–2 settimane (`--shadow`) e correggere regole e prompt; `--replay` rigioca i messaggi già raccolti.
3. Accendere la modalità **Automatico** nell'app, con «· cambia» e la domanda a due pulsanti.
4. Unificare Telegram sul router.
5. Aggiungere le **parti** (più richieste in un messaggio) e, se il modello lo consente, l'estrazione dei dati nella stessa chiamata.
6. Togliere `agent_guard` e il pre-classificatore di Salva.

---

## 9. Come cambiare modello

### 9.1 Cosa deve saper fare il nuovo modello

| Capacità | Serve per | Note |
|---|---|---|
| Italiano scritto e parlato (anche gergo di cantiere) | tutto | |
| **JSON affidabile** (o function calling) | quasi tutte le chiamate | Oggi `response_format={"type":"json_object"}`; il codice estrae comunque il primo `{…}` dalla risposta in alcuni punti, ma non in tutti |
| **Velocità** (< 1 s) | router (timeout 2,5 s), classificazioni | Un modello «veloce» separato da quello «forte» è la soluzione tipica |
| Contesto lungo (decine di migliaia di token) | report, preventivi, domande sulla commessa | `read_quote` chiede fino a 8000 token di risposta |
| **Visione** (immagini) | OCR foto, materiali da foto, preventivi fotografati | Se il nuovo modello non legge immagini, queste chiamate restano su un altro |
| Voce → testo | Whisper | Può restare OpenAI o passare a un altro servizio (o Whisper locale) |
| Ricerca web | News | Solo le news; possono restare sull'attuale |

### 9.2 Tre strade

**A) Fornitore compatibile con l'API di OpenAI (la più rapida).**
- Molti fornitori espongono la stessa API (`/v1/chat/completions`): Mistral, Groq, Together, DeepSeek, OpenRouter, Azure OpenAI, e i server locali Ollama, vLLM e LM Studio.
- Basta dare al client OpenAI un altro indirizzo e un'altra chiave:
  - variabili `OPENAI_BASE_URL` (che l'SDK `openai` legge da solo) e `OPENAI_API_KEY`;
  - i **nomi dei modelli**, oggi scritti nel codice, vanno resi configurabili (vedi 9.3).
- Da verificare col fornitore: supporto di `response_format` JSON, `max_completion_tokens` (alcuni vogliono `max_tokens`), immagini e streaming.

**B) Anthropic (Claude).**
- `LlmChat` lo supporta già: `with_model("anthropic", "<modello>")`, con `ANTHROPIC_API_KEY`.
- Le chiamate **dirette (D)** invece sono scritte per OpenAI e vanno portate sul livello comune (9.3).
- Per il JSON: chiederlo nel prompt, o usare i *tool* per un output strutturato.

**C) Un livello comune (consigliata, ed è il lavoro vero).**
- Oggi i circa 48 punti chiamano il fornitore ognuno a modo suo.
- Conviene un unico modulo, per esempio `backend/llm.py`, con poche funzioni:
  - `chat_json(task, system, user, images=None, max_tokens=…)` → dict;
  - `chat_text(...)` / `stream_text(...)`;
  - `transcribe(audio)`.
- `task` è il **ruolo** (`"router"`, `"veloce"`, `"forte"`, `"visione"`, `"lungo"`) e nel `.env` si dice quale fornitore e quale modello usa ogni ruolo. Per esempio:

```
LLM_ROUTER=openai_compat:mistral-small-latest
LLM_VELOCE=openai_compat:mistral-small-latest
LLM_FORTE=anthropic:claude-sonnet-…
LLM_VISIONE=openai:gpt-4o-mini
LLM_STT=openai:whisper-1
```

- Il modulo traduce le differenze tra fornitori: formato dei messaggi e delle immagini, JSON, nomi dei parametri, streaming, conteggio dei token per `usage_tracking`.
- Poi si sostituiscono le chiamate, file per file. L'elenco esatto è nelle tabelle del capitolo 7; per trovarle:

```
grep -n "chat.completions.create\|LlmChat(\|\.transcribe(\|responses.create" backend/*.py
```

- Così il cambio di modello successivo è una riga nel `.env`.

### 9.3 Attenzioni

- **Router** (`router.py`):
  - `MODEL` si legge già da `ROUTER_MODEL`, ma il client è OpenAI;
  - va mantenuto il **timeout** (`ROUTER_TIMEOUT_S`): se il modello non risponde in tempo decide il livello 4;
  - il prompt è in `_system()`.
- **Prompt**: sono in italiano dentro le funzioni. Contengono regole del dominio («MAI inventare: ogni informazione deve essere scritta dall'utente») da mantenere identiche.
- **Controlli dopo il modello**: non toglierli (`said_in`, `clean_*`, verifiche delle ore e delle date in `job_logs.py`, `work_reports.py`). Proteggono dall'invenzione di dati con qualunque modello.
- **Immagini**: `llm_integrations._user_content_openai` e `_user_content_anthropic` mostrano i due formati. Le foto HEIC/WebP vengono convertite in JPEG prima (`_downscale_image_bytes`).
- **Costi**: aggiungere i prezzi del nuovo modello in `llm_pricing`.
- **Test**: i test di integrazione (`backend/tests/integration/it_*.py`) **sostituiscono** i modelli con risposte finte (per esempio `ag.openai.AsyncOpenAI = fake_client(...)`, `fake_interpret`). Col livello comune si sostituisce una funzione sola. I test non chiamano mai modelli veri.
- **Qualità**: per ogni funzione cambiata, confrontare le risposte del vecchio e del nuovo modello su messaggi reali (anonimizzati). Il router ha già lo strumento (`router_eval.py`); per gli altri conviene un piccolo set di esempi per funzione, come `router_golden.jsonl`.

---

## 10. Configurazione (.env)

Il file `.env` sta nella cartella principale; il modello è `.env.example`. **Non va mai messo nel repository.**

| Variabile | A cosa serve |
|---|---|
| `APP_BASE_URL` | Indirizzo pubblico (es. `https://maipal.it/general`): link, redirect OAuth, QR |
| `MONGO_URL`, `DB_NAME` | Database |
| `OPENAI_API_KEY` | Tutti i modelli di oggi (e Whisper, news) |
| `ANTHROPIC_API_KEY` | Facoltativa (Claude tramite `LlmChat`) |
| `ROUTER_MODEL`, `ROUTER_TIMEOUT_S`, `ROUTER_SHADOW` | Modello e timeout del router; `ROUTER_SHADOW=0` spegne il router in ombra |
| `NEWS_MODEL` | Modello delle news |
| `ADMIN_EMAIL` | Amministratore di riserva (vedi anche `backend/data/access/org_admins.txt`) |
| `CORS_ORIGINS` | Origini ammesse |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Login Google, Drive, Calendar |
| `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT` | OneDrive e Outlook |
| `TELEGRAM_BOT_TOKEN` | Bot Telegram |
| `SEARCH_INDEX_URL`, `SEARCH_INDEX_API_KEY` | Qdrant (predefinito il servizio del compose) |
| `WEB_CONCURRENCY` | Processi per copia del backend |

---

## 11. Avvio, aggiornamento e test

```bash
# avvio (Windows: .\scripts\start-maipal.ps1 avvia anche Docker Desktop e il tunnel Cloudflare)
docker compose up -d

# aggiornamento dopo un git pull
git pull origin claude/analyze-main-branch-175dis
docker compose build --no-cache backend frontend
docker compose up -d --force-recreate backend frontend worker

# test del backend (senza database né chiavi: DB e modelli finti)
cd backend && python -m pytest -q tests/test_integration_flows.py tests/test_router.py tests/test_help_guide.py

# test del frontend
cd frontend && CI=true npx craco test --watchAll=false

# misura del router sul server (usa il modello vero)
docker compose exec backend python scripts/router_eval.py --golden
docker compose exec backend python scripts/router_eval.py --shadow --days 14 --out /app/router_shadow.md
```

---

## 12. Backup e ripristino

Il backup è fatto di due parti.

**1. Il codice**: il repository GitHub, più un *bundle* git (un unico file con tutta la storia di tutti i rami).

```bash
git bundle create maipal-codice.bundle --all          # creare
git clone maipal-codice.bundle mAIPAL-general          # ripristinare
git bundle verify maipal-codice.bundle                 # controllare
```

**2. I dati del server**: database (con i file in GridFS), configurazione e indice di ricerca.
- `scripts/backup-maipal.ps1` (Windows) o `scripts/backup-maipal.sh` (Linux/macOS), lanciati nella cartella del progetto, creano `backup/maipal-AAAAMMGG-HHMM/` con:
  - `mongo.archive.gz`: tutto il database con `mongodump`, file compresi;
  - `env.txt`: copia del `.env` (**contiene le chiavi: tenerlo in un posto sicuro**);
  - `access/`: `backend/data/access` (chi può entrare come amministratore);
  - `qdrant/`: un'istantanea dell'indice (facoltativa: si ricostruisce da sola).
- Per ripristinare (dopo `docker compose up -d`):

```bash
docker compose exec -T mongodb mongorestore --archive --gzip --drop < backup/maipal-…/mongo.archive.gz
# poi: copia env.txt in .env e access/ in backend/data/access; l'indice si ricostruisce dal worker
```

---

## 13. Regole del progetto

- **L'AI non inventa dati**: ogni valore salvato deve essere scritto dall'utente o venire dal database. Quando manca qualcosa si chiede, con pulsanti quando possibile.
- **I file caricati non sono affidabili**: si controlla il contenuto, non il nome. Le foto vengono ricodificate senza metadati GPS; i PDF vengono verificati; i modelli GLB devono avere un'intestazione valida.
- **Isolamento**: ogni query filtra per utente, team o organizzazione; nessun dato passa tra organizzazioni.
- **Interfaccia**:
  - italiano, font Poppins, vetro e sfumature, tema scuro e chiaro;
  - nei moduli: etichetta sopra, icona nel campo, menu a tendina invece di file di pulsanti, pulsanti larghi (`frontend/src/components/FormFields.jsx`);
  - misure in pixel interi, poche icone;
  - per ogni nuova classe di colore bianco serve la regola del tema chiaro in `index.css`.
- **Guida**: ogni funzione visibile all'utente va descritta in `backend/help/mAIPAL-help.md`.
- **Test**: ogni flusso ha il suo `tests/integration/it_*.py`, con database e modelli finti.
