# Gap analysis – Verticale Artigiani: creazione e gestione delle commesse

> Specifica: «SPEC_gestione_commesse» (da «Specifica funzionale v0.2 del 02/11/2026»).
> Codice analizzato: branch `claude/analyze-main-branch-175dis`, 02/11/2026.
> Stato: **fase 2 completata – in attesa delle decisioni sui punti in contrasto (§ C) prima dell'implementazione.**

## A. Riepilogo

| Stato | Quanti |
|---|---|
| ✅ Implementato | 5 |
| 🟡 Parziale | 35 |
| ❌ Mancante | 11 |
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
| PERM-MATRIX | Permessi | Matrice 2.4 | | 🟡 | `require_admin`, `_can_manage_collaborators`, `_can_describe`, `_require_owner` | Fatto: whitelist, collaboratori, eliminazione (titolare, con codice). Mancano: User che non crea clienti/commesse né pianifica né registra l'esito; flag costi agli User; riepiloghi solo all'Admin. |
| COLLAB-LEVEL | Permessi | Livello `WRITE`/`READ_WRITE` per commessa | P | ❌ | `collaborators.commesse` (lista di id) | Oggi tutti i collaboratori possono anche chiedere (= `READ_WRITE`). Serve un livello per commessa; default proposto `READ_WRITE` per non cambiare il comportamento attuale. |
| DATA-CLIENTE | Dati | Entità Cliente 3.1 | | 🟡 | lista di sistema Clienti (`verticals.py`, `collection_items`) | Ci sono nome, indirizzo, telefono, email, note. Mancano tipo, CF/P.IVA, referente, cartella Drive del cliente come campo. |
| DATA-COMMESSA | Dati | Entità Commessa 3.2 + storico | | 🟡 | sotto-elementi della lista Clienti, `_commessa_view`, `job_economics.budget` | Ci sono titolo, indirizzo, date, descrizione, valore (preventivo in Costi), stato, collaboratori. Mancano codice, orari standard, utenti assegnati come campo (oggi condivisione), esito preventivo, motivo perdita e **storico delle modifiche** (solo i cambi di stato sono nel diario). |
| DATA-STATI | Dati | Stati e transizioni 3.3 | P | 🟡 | `verticals.COMMESSA_STATI`, `PATCH /jobs/commesse/{id}/stato` | 4 stati diversi da quelli della specifica; nessuna transizione automatica. Vedi § C.1. |
| DATA-DIARIO | Dati | Diario con sezioni e metadati | | 🟡 | `job_logs`, sezioni di `JobDiaryPage.jsx` (Diario, Ore, Problemi, Materiali, Costi, Milestone, To Do, Descrizione) | Voci con data, autore, canale (`web`/`telegram`), testo originale (`raw_text`), foto. Mancano le sezioni Sintesi, Sopralluogo, Preventivo, Pianificazione, Attività svolte, Spese (oggi dentro Costi), Reminder, Report. |
| DATA-ATTIVITA | Dati | Attività pianificata + conferme | P | ❌ | (vicino: `job_todos`, `job_milestones`) | Da creare l'entità: orari, più assegnatari, materiale per categoria, stati, conferma per assegnatario. |
| DATA-PRESENZA | Dati | Registrazione presenza 3.6 | | 🟡 | `work_sessions` / `site_presence.py`, `_presence_start/_stop` | Check-in/out, ore calcolate e arrotondate, pausa. Manca l'origine `TEMPO_REALE`/`DICHIARATA` esplicita (oggi «ore da approvare» per quelle scritte). |
| DATA-REMINDER | Dati | Reminder 3.7 | | 🟡 | `job_todos` (kind `materiale`), promemoria task | Promemoria materiali e To Do con data; mancano reminder con ora, destinatari multipli espliciti e stato `ATTIVO/INVIATO/ANNULLATO`. |
| RF-CAN-01 | Canali | Parità Liste / Chat / Telegram | | 🟡 | `_save_job_log` condiviso da chat, app e Telegram | Note, ore, materiali, presenze: sì. Creazione commessa, preventivo, pianificazione: solo in parte o solo app. |
| RF-CAN-02 | Canali | Input multimodali | | 🟡 | foto e OCR (`_ocr_image_bytes`), `_extract_text_from_file` | Foto e testo su tutti i canali; PDF/Office solo nell'app (Documenti, Descrizione). **Telegram non gestisce i documenti** (PDF). PDF scansionati senza testo non letti. |
| AUT-GEN-01 | Agente | Individuazione della commessa | | 🟡 | `_resolve_commessa`, `collab_telegram._choose`, `_open_presence` | 1 (citata), 2 (check-in aperto) e 4 (pulsanti) ci sono; manca il criterio 3 per **fase** (foto di sopralluogo → commesse nuove). |
| AUT-GEN-02 | Agente | Estrazione + OCR manoscritti | | 🟡 | `_ocr_image_bytes` (KB), `read_document` | OCR presente per Salva e Descrizione; non nel diario per gli appunti manoscritti. |
| AUT-GEN-03 | Agente | Conferma prima di salvare dati sensibili | P | 🟡 | `pick_commessa` («è un cliente nuovo?»), `DescriptionDocSheet` | Conferma per cliente nuovo e per il valore dal preventivo; manca un riepilogo uniforme per creazione commessa e spese. |
| AUT-GEN-04 | Agente | Chiede i dati mancanti | | ✅ | `jl.ground`, stato `non_chiara`, `amount_in_text` | Note non chiare non salvate, importi solo se scritti nel documento. |
| AUT-GEN-05 | Agente | Ricevuta con sezione e link | | 🟡 | messaggi di `_save_job_log` | Indica commessa e cosa è stato salvato; il link al file su Drive non sempre. |
| AUT-GEN-06 | Drive | Struttura cartelle | P | 🟡 | `_storage_save(subfolders=…)`, `create_commessa_folder` | `mAIPAL/Clienti/<cliente>/<commessa>`: mancano codice nel nome e sottocartelle per fase. |
| AUT-GEN-07 | Drive | Nomenclatura file | parz. | ❌ | `_job_photos_to_cloud` («AAAA-MM-GG diario N.jpg») | Da sostituire con `<fase>_AAAAMMGG_<desc>` e suffisso `_02`. |
| AUT-GEN-08 | Drive | Coda e retry | P | ❌ | salvataggio «best effort» | Da aggiungere coda con tentativi e avviso all'Admin dopo 24 h. |
| RF-CRE-01..05 | Creazione | Cliente/commessa, assegnazioni, modifiche | 03 | 🟡 | Liste (app), `_new_client`, `_new_commessa`, `set_commessa_sharing`, `set_commessa_collaborator` | Creazione da Liste e implicita da una nota; manca «nuova commessa per …» con parametri da Chat/Telegram; manca lo storico delle modifiche. |
| AUT-CRE-01 | Creazione | Duplicati cliente | P | 🟡 | `_resolve_commessa` («Ho più clienti con questo nome») | Somiglianza solo per nome normalizzato; manca il confronto «simile». |
| AUT-CRE-02 | Creazione | Codice, diario, cartella, conferma | | 🟡 | `create_commessa_folder` (su richiesta) | Il diario esiste implicitamente; mancano il codice e la cartella automatica alla creazione. |
| AUT-CRE-03 | Creazione | Avviso di abilitazione | P | 🟡 | avvisi su condivisione e abilitazione collaboratore | Collaboratori avvisati al collegamento; avviso per ogni nuova commessa abilitata da completare. |
| RF-SOP-01..02 | Sopralluogo | Note/file e aggregazione | | 🟡 | diario (foto + testo), report «Primo sopralluogo» (`work_reports`) | Le note vanno nel diario generico, non in una sezione Sopralluogo. |
| AUT-SOP-01..04 | Sopralluogo | Estrazione, struttura, file, stato | 02 | ❌ | — | Sezione strutturata, OCR degli appunti, nomi file e passaggio di stato da fare. |
| RF-PRE-01..03 | Preventivo | Caricamento, versioni, esito | 02 | 🟡 | `POST /jobs/commesse/{id}/description/read` | Caricamento solo dall'app (Descrizione); mancano versioni ed esito. |
| AUT-PRE-01..03 | Preventivo | Estrazione, salvataggio, stato e valore | 02 | 🟡 | `jl.read_document`, `set_commessa_description` | Estrae descrizione e importo (imponibile) con conferma; mancano voci, scadenze, cartella `Preventivi/`, stato. Se il valore è diverso oggi propone di sostituirlo (con spunta), non chiede «quale tenere». |
| AUT-PRE-04 | Preventivo | Solleciti sull'esito | P | ❌ | — | |
| AUT-PRE-05..06 | Preventivo | Accettato → pianificazione; Perso → motivo | 06 | ❌ | — | |
| AUT-PRE-07 | Preventivo | Storico delle perdite | | ❌ | — | |
| RF-SVO-01 | Lavori | Pianificazione attività | P | 🟡 | To Do e Milestone (con collaboratore e scadenza) | Manca l'attività con orari, più assegnatari, materiale per categoria. |
| RF-SVO-02..04 | Lavori | Note, check-in/out, reminder | 03 | ✅ | `_save_job_log`, presenze (📍, «sono arrivato», «ho finito alle 17:30»), promemoria materiali | Spese dai messaggi escluse (vedi AUT-SVO-01). |
| AUT-SVO-01..03 | Lavori | Categorizzazione, file, reminder | | 🟡 | `jl.interpret` (ore, materiali, problemi) | Mancano: **spese** dai messaggi, attività svolta collegata, chiusura delle problematiche («risolto»), file in `Lavori/`/`Spese/`. |
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
| CONFIG | Config | Parametri cap. 7 configurabili | | ❌ | costanti in `server.py` (`DAY_PIN_AT`, `PRESENCE_LATE_AT`, `COLLAB_REMIND_AT`…) | Da spostare in impostazioni di organizzazione. |
| RNF-01 | NFR | Tracciabilità | | 🟡 | `job_logs` (`raw_text`, `channel`, `author_*`, `created_at`) | Manca `updated_by` e lo storico delle modifiche ai parametri. |
| RNF-02 | NFR | Italiano, Europe/Rome, formati | | ✅ | `LOCAL_TZ`, `_eur`, date in italiano | |
| RNF-03 | NFR | Nessun duplicato; accorpamento | | ✅ | campi `reminded`, `reminded_on`, un promemoria per persona | |
| RNF-04 | NFR | Ricevuta entro 10 s; asincrono | P | 🟡 | salvataggi su cloud in background | Le chiamate al modello sono sincrone (ricevuta di solito in pochi secondi). |
| RNF-05 | NFR | Economici mai a collaboratori/cliente | | ✅ | `_collab_answer` (filtra costi/prezzi), `client_updates` (niente costi) | |
| RNF-06 | NFR | Presenze: niente GPS di default | | 🟡 | pulsante 📍 con posizione | Vedi § C.4: oggi la posizione si manda al tocco del 📍 (mai tracciamento continuo). |

**Già conformi oltre alla checklist**: collaboratori di più imprese su un solo Telegram; messaggio del giorno fissato con modifica e rimozione; ore scritte come «da approvare»; avanzamento al cliente senza costi né nomi.

## C. Punti da decidere prima di implementare (codice esistente in contrasto con la specifica)

| # | Tema | Oggi | Specifica | Proposta meno distruttiva |
|---|---|---|---|---|
| C.1 | Stati della commessa | preventivo, in corso, sospesa, chiusa | NUOVA, SOPRALLUOGO, PREVENTIVO_INVIATO, IN_LAVORAZIONE, PERSA, COMPLETATA, ARCHIVIATA | Adottare i 7 stati con migrazione: preventivo → PREVENTIVO_INVIATO, in corso → IN_LAVORAZIONE, chiusa → COMPLETATA; tenere SOSPESA come stato in più. |
| C.2 | Report settimanale al cliente | automatico su Telegram (scelta del titolare) | bozza approvata dall'Admin, poi email | Bozza con approvazione + invio su Telegram (già collegato al cliente) o copia; email quando ci sarà l'integrazione mail. |
| C.3 | Costi agli User | visibili su commessa condivisa | flag di organizzazione, default No | Flag nelle regole di condivisione, default **No** come da specifica. |
| C.4 | Vocali e posizione | vocali trascritti; 📍 manda la posizione | vocali esclusi; niente GPS | Tenere vocali e 📍 (già in uso), con un'opzione di organizzazione per spegnere la posizione. |
