# Gap analysis – Verticale Artigiani: creazione e gestione delle commesse

> Specifica: «SPEC_gestione_commesse» (da «Specifica funzionale v0.2 del 02/11/2026»).
> Codice analizzato: branch `claude/analyze-main-branch-175dis`, 02/11/2026.
> Stato: **fase 3 in corso** – decisioni del titolare sui punti in contrasto registrate in § C (03/11/2026).

## A. Riepilogo

| Stato | Quanti |
|---|---|
| ✅ Implementato | 20 |
| 🟡 Parziale | 28 |
| ❌ Mancante | 3 |
| ⛔ Bloccato | 0 |
| **Totale** | **51** |

### Stack (fase 1, in breve)
- **Backend**: FastAPI + MongoDB (Motor), un solo modulo principale `backend/server.py` con moduli di dominio (`job_logs.py` interprete del diario, `collab_telegram.py` collaboratori, `site_presence.py` presenze, `client_updates.py` / `client_telegram.py` avanzamento al cliente, `work_reports.py` report, `access.py` amministratori, `verticals.py` liste di sistema). Nessun ORM e **nessuna migrazione**: le migrazioni sono funzioni idempotenti all'avvio (es. `_migrate_tenants`).
- **Agente AI**: chiamate OpenAI con JSON (`jl.interpret`, `jl.answer`, `jl.read_document`), classificazione degli agenti in `telegram_bot.py` / chat; regole deterministiche (regex) accanto al modello per non inventare (`jl.ground`, `amount_in_text`).
- **Telegram**: un bot condiviso (`telegram_bot.py`), gate dei collaboratori nel gruppo −1 (`collab_telegram.gate`), pulsanti inline con callback a prefisso.
- **Integrazioni**: Google Drive/Calendar (`google_integration.py`), OneDrive/Outlook Calendar (`microsoft_integration.py`); **nessuna integrazione mail** (Gmail/Outlook Mail).
- **Scheduler**: loop asincroni ogni 5 minuti (`_collab_reminder_loop`, `_daily_summary_loop`, `scheduled_actions`).
- **Permessi**: organizzazioni (`tenants`, ruolo `admin`/`user`), team (`organizations`), condivisione commessa per persona con `edit`/`read` (`_commessa_access`), collaboratori per commessa (`collaborators.commesse`).
- **Test**: flussi di integrazione con DB in memoria (`tests/integration/it_*.py`, eseguiti da `tests/test_integration_flows.py`) + test unitari.

### Principali discrepanze tra codice e specifica
1. **Stati della commessa**: nel codice sono 4 (`preventivo`, `in corso`, `sospesa`, `chiusa`, `verticals.COMMESSA_STATI`); la specifica ne vuole 7 con transizioni automatiche. `sospesa` non esiste nella specifica.
2. **Attività pianificate**: oggi ci sono **To Do** (testo, chi, scadenza, un collaboratore) e **Milestone**; manca l'entità con orari, più assegnatari, materiale per categoria, conferme e stati.
3. **Report al cliente**: oggi parte **in automatico su Telegram** (richiesta esplicita del titolare); la specifica vuole una **bozza approvata dall'Admin** e l'invio **via email**.
4. **Dati economici agli User**: oggi chi riceve una commessa condivisa vede anche i costi (scelta del titolare); la specifica vuole un flag di organizzazione con default **No**.
5. **Vocali e posizione**: la specifica esclude i vocali (PA-01) e la geolocalizzazione (PA-05, RNF-06); oggi i vocali sono trascritti e il pulsante 📍 manda la posizione (entrambi chiesti dal titolare).
6. **Orari**: oggi messaggio del giorno alle 06:00, promemoria materiali 19:30/07:00, «cosa avete fatto oggi?» alle 18:00, «ancora in cantiere?» alle 19:00, riepilogo cantieri il **lunedì alle 08:00**, resoconto serale generico alle 21:00; la specifica ha altri orari e li vuole **configurabili per organizzazione** (oggi sono costanti nel codice).
7. **Cartelle e nomi dei file su Drive**: oggi `mAIPAL/Clienti/<cliente>/<commessa>/` senza sottocartelle per fase, file come `2026-11-02 diario 1.jpg`.
8. **Creazione di clienti e commesse da parte degli User**: oggi uno User può aprire una commessa scrivendo una nota (es. «è un cliente nuovo?» → crea); la specifica (PA-09) lo vieta.

### Piano di implementazione (ordine del cap. 11)
1. **Fondamenta** – parametri di organizzazione (cap. 7) in `tenants.settings` con valori di default; stati nuovi + migrazione idempotente degli esistenti; codice commessa `AAAA-NNN`; storico modifiche; problematiche aperte/risolte; spese strutturate; permessi della matrice (User non crea/elimina/pianifica; flag costi agli User; livello collaboratore `WRITE`/`READ_WRITE`).
2. **Servizi trasversali** – cartelle per fase e nomenclatura dei file (`<fase>_AAAAMMGG_<desc>`), coda con retry per il Drive, conferma con riepilogo prima di creare clienti/commesse e salvare dati economici, ricevute con sezione e link.
3. **Creazione** – «nuova commessa per …» da Chat/Telegram con riepilogo e conferma, duplicati, cartella e avviso di abilitazione agli operatori.
4. **Sopralluogo e Preventivo** – sezione Sopralluogo strutturata (con OCR degli appunti), stato automatico; preventivo da Chat/Telegram (anche PDF su Telegram), versioni, esito con motivo di perdita, solleciti, storico delle perdite.
5. **Pianificazione** – entità Attività (orari, assegnatari, materiale per categoria, conferme), da app e chat; collegamento nota → attività svolta; spese dai messaggi.
6. **Notifiche** – G−1 alle 18:00 con meteo e Confermo/Non posso, messaggio del giorno alle 07:00 (o inizio −1 h), mancato arrivo / mancata uscita con orari attesi, note mancanti, riepilogo serale all'Admin per cantiere.
7. **Settimanali** – report del venerdì all'Admin con margine, programma della settimana agli operatori, bozza al cliente con approvazione (secondo la decisione su § C.2).
8. **Chiusura** – controlli, report finale, stop delle notifiche.
9. **Test end-to-end** dello scenario del cap. 8 e aggiornamento di questo file.

## B. Checklist

| ID | Area | Requisito sintetico | [P] | Stato | Riferimenti codice | Note |
|---|---|---|---|---|---|---|
| RNF-PERM-01 | Permessi | Permessi uguali su tutti i canali, nessuna rivelazione | | 🟡 | `_commessa_access`, `_commessa_or_404` (404 «Commessa non trovata»), `collab_telegram._targets_of` | App/chat/Telegram passano dagli stessi controlli e una commessa non accessibile risponde 404. Da verificare e uniformare: le risposte della chat che cercano per nome (retrieval) e i messaggi «non trovo» che citano il nome cercato. |
| PERM-MATRIX | Permessi | Matrice 2.4 | | 🟡 | `_is_org_admin`, `_require_org_admin`, `_sees_costs`, `require_admin`, `_can_manage_collaborators` | Fase 1: clienti e commesse (creazione, modifica, eliminazione, stato) solo Admin su Liste, Chat e Telegram; costi agli User con regola di organizzazione (default No). Restano: pianificazione ed esito preventivo (fasi 4-5), riepiloghi solo all'Admin (fasi 6-7). |
| COLLAB-LEVEL | Permessi | Livello `WRITE`/`READ_WRITE` per commessa | P | ✅ | `collaborators.levels`, `_collab_level`, `PUT /jobs/commesse/{id}/collaborators/{collab_id}` (level), `collab_telegram.process` | [P] Default `read_write` (comportamento precedente). Con `write` il collaboratore invia ma alle domande risponde che non può consultare. Scelta dal menu Collaboratori del diario. |
| DATA-CLIENTE | Dati | Entità Cliente 3.1 | | ✅ | `verticals.CLIENTI_FIELDS` (tipo, cf_piva, referente), `_migrate_commesse` | Campi aggiunti alle liste Clienti esistenti con la migrazione; la cartella del cliente sul Drive resta calcolata (fase 2). |
| DATA-COMMESSA | Dati | Entità Commessa 3.2 + storico | | 🟡 | `verticals.COMMESSA_FIELDS` (codice, ora_inizio, ora_fine), `_next_commessa_code`, `_track_commessa_changes`, `commessa_history`, `quote_outcome`, `lost_reason` | Fase 1: codice AAAA-NNN per organizzazione e anno (anche sulle esistenti), orari standard, storico delle modifiche (Liste, stato, valore, descrizione), esito e motivo di perdita. User assegnati = condivisione della commessa (esistente). Versioni del preventivo in fase 4. |
| DATA-STATI | Dati | Stati e transizioni 3.3 | P | ✅ | `verticals.COMMESSA_STATI`, `_set_commessa_stato`, `_survey_started`, `_confirm_quote`, `_quote_outcome` | [P] 7 stati + SOSPESA (C.1); transizioni automatiche: prima nota di sopralluogo → SOPRALLUOGO; preventivo confermato → PREVENTIVO_INVIATO; accettato → IN_LAVORAZIONE; perso (motivo obbligatorio) → PERSA. L'Admin può sempre forzare. |
| DATA-DIARIO | Dati | Diario con sezioni e metadati | | 🟡 | `job_logs` (section, kind, channel, raw_text), sezioni del diario: Diario, Ore, Problemi, Materiali, Costi, Milestone, To Do, Descrizione, Sopralluogo, Preventivo | Fase 4: sezioni Sopralluogo e Preventivo. Mancano Pianificazione/Attività svolte (fase 5), Reminder e Report come sezioni (fase 7). |
| DATA-ATTIVITA | Dati | Attività pianificata + conferme | P | ❌ | (vicino: `job_todos`, `job_milestones`) | Da creare l'entità: orari, più assegnatari, materiale per categoria, stati, conferma per assegnatario. |
| DATA-PRESENZA | Dati | Registrazione presenza 3.6 | | 🟡 | `work_sessions` / `site_presence.py`, `_presence_start/_stop` | Check-in/out, ore calcolate e arrotondate, pausa. Manca l'origine `TEMPO_REALE`/`DICHIARATA` esplicita (oggi «ore da approvare» per quelle scritte). |
| DATA-REMINDER | Dati | Reminder 3.7 | | 🟡 | `job_todos` (kind `materiale`), promemoria task | Promemoria materiali e To Do con data; mancano reminder con ora, destinatari multipli espliciti e stato `ATTIVO/INVIATO/ANNULLATO`. |
| RF-CAN-01 | Canali | Parità Liste / Chat / Telegram | | 🟡 | `_save_job_log` condiviso da chat, app e Telegram | Note, ore, materiali, presenze: sì. Creazione commessa, preventivo, pianificazione: solo in parte o solo app. |
| RF-CAN-02 | Canali | Input multimodali | | 🟡 | foto e OCR (`_ocr_image_bytes`), `_read_file_text`, `_ingest_commessa_document`, Telegram `_msg_document` | Fase 4: PDF/Office/foto anche su Telegram (documenti), appunti manoscritti letti. Vocali inclusi (decisione C.4, PA-01 superato). Restano i PDF scansionati senza testo (chiesta una foto). |
| AUT-GEN-01 | Agente | Individuazione della commessa | | 🟡 | `_resolve_commessa`, `collab_telegram._choose`, `_open_presence` | 1 (citata), 2 (check-in aperto) e 4 (pulsanti) ci sono; manca il criterio 3 per **fase** (foto di sopralluogo → commesse nuove). |
| AUT-GEN-02 | Agente | Estrazione + OCR manoscritti | | 🟡 | `_survey_after` (OCR delle foto di sopralluogo), `_read_file_text`, `jl.read_document`, `jl.read_quote` | Estrazione da testo, immagini e PDF con testo; OCR degli appunti; file originale conservato nell'archivio. PDF scansionati: non letti (si chiede la foto). |
| AUT-GEN-03 | Agente | Conferma prima di salvare dati sensibili | P | 🟡 | `_commessa_draft`, `_confirm_commessa_draft`, `POST /jobs/commesse/drafts/{id}`, Telegram `cmd:`, chat `commessaDraft`, `DescriptionDocSheet` | [P] Fase 3: riepilogo e conferma per creazione di cliente e commessa (chat, Telegram, Liste via chat) e per il valore dal preventivo. Le spese si salvano con ricevuta (e sono eliminabili in Costi), senza conferma: scelta coerente col criterio di accettazione di AUT-SVO-01; dati del preventivo in fase 4. |
| AUT-GEN-04 | Agente | Chiede i dati mancanti | | ✅ | `jl.ground`, stato `non_chiara`, `amount_in_text` | Note non chiare non salvate, importi solo se scritti nel documento. |
| AUT-GEN-05 | Agente | Ricevuta con sezione e link | | 🟡 | `_job_log_message`, `_confirm_commessa_draft`, `archive_files.path` | Ricevuta con commessa, sezioni (ore, materiali, problemi, risolti, spese) e cartella con link alla creazione. Il link al singolo file arriva sulla foto nel diario quando è salvato (il salvataggio è asincrono). |
| AUT-GEN-06 | Drive | Struttura cartelle | P | ✅ | `archive_names.py`, `_commessa_archive_place`, `_commessa_dir`, `_ensure_commessa_folders` | [P] `mAIPAL/Clienti/<cliente>/<codice> – <commessa>/{Sopralluogo, Preventivi, Lavori, Spese, Report}` per le commesse nuove; quelle create prima tengono la cartella col solo titolo (nessun file spostato). |
| AUT-GEN-07 | Drive | Nomenclatura file | parz. | ✅ | `archive_names.file_name/describe/unique`, `_archive_commessa_bytes`, `archive_files` | Nome `<fase>_AAAAMMGG_<descrizione>` (max 2 parole, data della nota o del caricamento), suffisso `_02` [P]; preventivi `preventivo_AAAAMMGG_vN`. |
| AUT-GEN-08 | Drive | Coda e retry | P | ✅ | `_archive_try`, `_archive_retry` (nel ciclo ogni 5 minuti), `archive_files` (status queued, data_b64) | [P] File in coda con tentativi a intervalli crescenti (fino a 1 h) e un solo avviso all'Admin dopo 24 h di errori. |
| RF-CRE-01..05 | Creazione | Cliente/commessa, assegnazioni, modifiche | 03 | 🟡 | Liste, `_commessa_draft`/`_confirm_commessa_draft` (Chat, Telegram), `set_commessa_sharing`, `set_commessa_collaborator`, `_track_commessa_changes` | Fase 3: creazione da Liste, Chat e Telegram con lo stesso risultato (record, codice, diario, cartelle); assegnazioni (condivisione User, collaboratori con livello); modifiche tracciate. |
| AUT-CRE-01 | Creazione | Duplicati cliente | P | ✅ | `_client_matches` (stesso nome, nomi simili) | [P] Somiglianza: rapporto ≥ 0,75 o parole contenute o una parola quasi uguale; l'Admin sceglie il cliente esistente o «Cliente nuovo». |
| AUT-CRE-02 | Creazione | Codice, diario, cartella, conferma | | ✅ | `_stamp_commessa`, `_after_new_commessa`, `_ensure_commessa_folders`, `_confirm_commessa_draft` | Codice, stato NUOVA, diario (implicito), cartella con sottocartelle creata entro 20 s (poi in background) e conferma all'Admin con il link. |
| AUT-CRE-03 | Creazione | Avviso di abilitazione | P | ✅ | `_tell_enabled` (in `set_commessa_collaborator` e `update_collaborator`) | [P] Il collaboratore collegato riceve su Telegram commessa, cliente e indirizzo. Gli User ricevono già l'avviso di condivisione. |
| RF-SOP-01..02 | Sopralluogo | Note/file e aggregazione | | ✅ | `_save_job_log` (section sopralluogo), `_ingest_commessa_document`, sezione Sopralluogo (`SurveyView`) | Admin e User da Chat, Telegram e app (non i collaboratori); più messaggi in momenti diversi sulla stessa commessa. |
| AUT-SOP-01..04 | Sopralluogo | Estrazione, struttura, file, stato | 02 | ✅ | `_survey_after`, `_survey_refresh`, `jl.survey_summary`, `_survey_started`, archivio `Sopralluogo/` | [P] OCR degli appunti; sezione riorganizzata (data e partecipanti, stato di fatto e misure, lavori richiesti, criticità, materiali, elenco file con link); file `sopralluogo_AAAAMMGG_<desc>`; NUOVA → SOPRALLUOGO. |
| RF-PRE-01..03 | Preventivo | Caricamento, versioni, esito | 02 | ✅ | `POST /jobs/commesse/{id}/documents`, Telegram documenti, `job_quotes` (versioni), `POST /jobs/commesse/{id}/quote/outcome`, `jl.quote_outcome_said` | [P] Caricamento da app e Telegram, versioni v1, v2… consultabili, esito dall'app, da messaggio o dai pulsanti dei solleciti (solo Admin). |
| AUT-PRE-01..03 | Preventivo | Estrazione, salvataggio, stato e valore | 02 | ✅ | `jl.read_quote`, `_quote_proposal`, `_confirm_quote`, `QuoteSheet`, Telegram `qc:/qx:/qv:` | Estrae totale/imponibile, voci, date, validità, pagamenti, attività, materiali (importi solo se scritti); conferma prima di salvare; file `preventivo_AAAAMMGG_vN` in Preventivi; stato e valore (vuoto → impostato, diverso → sceglie l'Admin). |
| AUT-PRE-04 | Preventivo | Solleciti sull'esito | P | ✅ | `_quote_followups` (nel ciclo), impostazioni `quote_followup_days/max` | [P] Dopo N giorni e poi ogni N, o alla scadenza di validità se prima, al massimo M solleciti, con pulsanti Accettato / Perso / In attesa. |
| AUT-PRE-05..06 | Preventivo | Accettato → pianificazione; Perso → motivo | 06 | 🟡 | `_quote_outcome`, `LostSheet`, Telegram `qo:/qr:` | Accettato → IN_LAVORAZIONE con l'elenco delle attività del preventivo da pianificare; Perso → motivo obbligatorio (categorie [P] + testo). La trasformazione in attività pianificate con date e assegnatari arriva con la Pianificazione (fase 5). |
| AUT-PRE-07 | Preventivo | Storico delle perdite | | ✅ | `_loss_feedback` | Al caricamento di un preventivo: se almeno 2 degli ultimi preventivi persi per lavori simili (parole in comune) hanno lo stesso motivo, l'Admin lo vede nel riepilogo. |
| RF-SVO-01 | Lavori | Pianificazione attività | P | 🟡 | To Do e Milestone (con collaboratore e scadenza) | Manca l'attività con orari, più assegnatari, materiale per categoria. |
| RF-SVO-02..04 | Lavori | Note, check-in/out, reminder | 03 | ✅ | `_save_job_log`, presenze (📍, «sono arrivato», «ho finito alle 17:30»), promemoria materiali | Spese dai messaggi escluse (vedi AUT-SVO-01). |
| AUT-SVO-01..03 | Lavori | Categorizzazione, file, reminder | | 🟡 | `jl.interpret` (ore, materiali, problemi, spese), `jl.clean_expenses`, `_save_log_expenses`, `jl.problems_resolved`, `_solve_problems`, `PATCH /jobs/logs/{id}/problems/{idx}` | Fase 1: spese dai messaggi (solo con importo scritto) nei Costi con fornitore e link alla nota; problematiche APERTA/RISOLTA (chiuse da un messaggio «risolto…» o a mano) con gravità. Restano attività svolte collegate (fase 5) e file in Lavori/Spese (fase 2). |
| RF-CHI-01, AUT-CHI-01..02 | Chiusura | Chiusura e report finale | P | 🟡 | stato `chiusa`, report «Verbale di fine lavori», chiusura dell'accesso ai collaboratori | Mancano controllo di problemi/attività aperti, report finale automatico, stop di tutte le notifiche. |
| AUT-G1-01..03 | Notifiche | G−1: reminder, conferma, aggiunte | 02 | 🟡 | `_material_reminders` (19:30), `_todo_reminders`, `_milestone_reminders` (dalle 08:00) | Mancano messaggio unico alle 18:00 con materiale per categoria, meteo, Confermo/Non posso, solleciti. |
| AUT-DAY-01 | Notifiche | Messaggio del giorno fissato | | 🟡 | `_day_pin_refresh` (pin, edit, unpin) | Fatto per i collaboratori alle 06:00; mancano orario 07:00/inizio −1 h, materiale per categoria e invio anche agli User. |
| AUT-DAY-02 | Notifiche | Mancato arrivo | | ❌ | — | Serve l'orario di inizio atteso (attività / standard / 09:00). |
| AUT-DAY-03 | Notifiche | Mancata uscita | | 🟡 | `_presence_late_check` (19:00), `_presence_forgotten` (14 h) | Da basare sull'orario di fine atteso + tolleranza, con avviso all'Admin e uscita `DICHIARATA`. |
| AUT-DAY-04 | Notifiche | Note mancanti | | 🟡 | `_presence_day_note` («com'è andata?»), `_collab_remind_due` (18:00) | Allineare all'orario configurabile (19:00) e alla condizione «presenza senza note». |
| AUT-DAY-05 | Notifiche | Riepilogo giornaliero all'Admin | | 🟡 | `_daily_summary_loop` (21:00, task e to-do) | Manca il riepilogo per cantiere (presenti, ore, attività, problemi, spese, anomalie). |
| AUT-WEEK-01 | Notifiche | Report settimanale con margine | | 🟡 | azione «Riepilogo cantieri» (lunedì 08:00) con ore, materiali, problemi, costi/preventivo | Spostare a venerdì 18:00 (configurabile) e aggiungere pianificate vs svolte e spese. |
| AUT-WEEK-02..03 | Notifiche | Bozza cliente + approvazione | 03 | 🟡 | `client_updates.py` (invio automatico su Telegram, copia al titolare, anteprima) | Vedi § C.2: manca l'approvazione; manca l'invio email (nessuna integrazione mail). |
| AUT-WEEK-04 | Notifiche | Programma settimanale agli operatori | | ❌ | — | |
| CONFIG | Config | Parametri cap. 7 configurabili | | 🟡 | `org_settings.py`, `GET/PATCH /tenant/settings`, Impostazioni → Organizzazione → «Commesse: orari e automatismi» | Fase 1: tutti i parametri del cap. 7 (+ tolleranza uscita, pausa pranzo PA-04, posizione C.4, approvazione report C.2) salvati per organizzazione e validati. Gli automatismi li leggono dalle fasi 4-7. |
| RNF-01 | NFR | Tracciabilità | | 🟡 | `job_logs` (`raw_text`, `channel`, autore), `commessa_history` | Storico delle modifiche dei parametri aggiunto; `updated_by` sulle voci di diario da completare. |
| RNF-02 | NFR | Italiano, Europe/Rome, formati | | ✅ | `LOCAL_TZ`, `_eur`, date in italiano | |
| RNF-03 | NFR | Nessun duplicato; accorpamento | | ✅ | campi `reminded`, `reminded_on`, un promemoria per persona | |
| RNF-04 | NFR | Ricevuta entro 10 s; asincrono | P | 🟡 | salvataggi su cloud in background | Le chiamate al modello sono sincrone (ricevuta di solito in pochi secondi). |
| RNF-05 | NFR | Economici mai a collaboratori/cliente | | ✅ | `_collab_answer`, `client_updates`, `_sees_costs` | Collaboratori e cliente mai; User secondo la regola di organizzazione (default No). |
| RNF-06 | NFR | Presenze: niente GPS di default | | 🟡 | pulsante 📍 con posizione | Vedi § C.4: oggi la posizione si manda al tocco del 📍 (mai tracciamento continuo). |

**Già conformi oltre alla checklist**: collaboratori di più imprese su un solo Telegram; messaggio del giorno fissato con modifica e rimozione; ore scritte come «da approvare»; avanzamento al cliente senza costi né nomi.

## C. Punti da decidere prima di implementare (codice esistente in contrasto con la specifica)

| # | Tema | Oggi | Specifica | Proposta meno distruttiva | Decisione (03/11/2026) |
|---|---|---|---|---|---|
| C.1 | Stati della commessa | preventivo, in corso, sospesa, chiusa | NUOVA, SOPRALLUOGO, PREVENTIVO_INVIATO, IN_LAVORAZIONE, PERSA, COMPLETATA, ARCHIVIATA | Adottare i 7 stati con migrazione: preventivo → PREVENTIVO_INVIATO, in corso → IN_LAVORAZIONE, chiusa → COMPLETATA; tenere SOSPESA come stato in più. | ✔ 7 stati della specifica + SOSPESA; migrazione degli esistenti. |
| C.2 | Report settimanale al cliente | automatico su Telegram (scelta del titolare) | bozza approvata dall'Admin, poi email | Bozza con approvazione + invio su Telegram (già collegato al cliente) o copia; email quando ci sarà l'integrazione mail. | ✔ Bozza da approvare dall'Admin; invio su Telegram al cliente (o copia), email quando ci sarà la posta. |
| C.3 | Costi agli User | visibili su commessa condivisa | flag di organizzazione, default No | Flag nelle regole di condivisione, default **No** come da specifica. | ✔ Opzione di organizzazione, default No. |
| C.4 | Vocali e posizione | vocali trascritti; 📍 manda la posizione | vocali esclusi; niente GPS | Tenere vocali e 📍 (già in uso), con un'opzione di organizzazione per spegnere la posizione. | ✔ Restano vocali e 📍; opzione di organizzazione per non salvare la posizione. |
