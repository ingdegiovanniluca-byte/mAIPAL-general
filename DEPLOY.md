# Deploy di mAIPAL su maipal.it/general (Docker locale + Cloudflare)

Questa guida presume: app in Docker sul tuo PC, dominio `maipal.it` già gestito su
Cloudflare con un altro sito attivo sulla root. L'obiettivo è esporre mAIPAL sotto
`https://maipal.it/general` senza toccare il sito esistente.

## 1. Google OAuth (login + Drive/Calendar)

1. Vai su https://console.cloud.google.com/apis/credentials
2. Crea (o riusa) un progetto, poi "Crea credenziali" → "ID client OAuth" → tipo
   "Applicazione web"
3. In "URI di reindirizzamento autorizzati" aggiungi ENTRAMBI:
   - `https://maipal.it/general/api/auth/google/callback`
   - `https://maipal.it/general/api/integrations/google/callback`
4. Copia Client ID e Client Secret in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
5. Se il progetto è in modalità "Test", aggiungi la tua email tra gli utenti di test
   (o pubblica l'app per consentire l'accesso a chiunque sia in whitelist)

## 1b. Microsoft: OneDrive + calendario Outlook (facoltativo)

Serve solo se vuoi salvare i file su OneDrive e/o mettere i task nel calendario di Outlook
(in alternativa o insieme a Google: ogni utente sceglie in Impostazioni → "Dove salvo file ed eventi").

1. Vai su https://entra.microsoft.com → "Identità" → "Applicazioni" → "Registrazioni app" →
   "Nuova registrazione" (va bene anche un account Microsoft personale: è gratis)
2. Nome: `mAIPAL`. Tipi di account supportati: **"Account in qualsiasi directory organizzativa
   e account Microsoft personali"** (così funzionano sia hotmail/outlook.com sia Microsoft 365)
3. URI di reindirizzamento: piattaforma **Web**,
   `https://maipal.it/general/api/integrations/microsoft/callback` → "Registra"
4. Dalla pagina "Panoramica" copia **ID applicazione (client)** in `.env` come `MS_CLIENT_ID`
5. "Certificati e segreti" → "Nuovo segreto client" (scadenza 24 mesi) → copia subito il
   **Valore** (non l'ID) in `.env` come `MS_CLIENT_SECRET`. Segnati la scadenza: quando
   scade va rigenerato e aggiornato nel `.env`
6. "Autorizzazioni API" → "Aggiungi un'autorizzazione" → Microsoft Graph → Autorizzazioni
   delegate: `offline_access`, `openid`, `email`, `User.Read`, `Files.ReadWrite.AppFolder`,
   `Calendars.ReadWrite` (non serve il consenso amministratore)
7. Lascia `MS_TENANT=common`, ricrea il backend e collega l'account da Impostazioni →
   "Microsoft · OneDrive e Outlook"

I file finiscono solo nella cartella dell'app su OneDrive (`App/mAIPAL`): mAIPAL non vede il
resto del tuo OneDrive.

## 2. Chiavi LLM

- `OPENAI_API_KEY`: da https://platform.openai.com/api-keys — usata per tutte le
  funzioni AI (chat, task, diario, news, OCR, trascrizione vocale). Verifica che
  l'account abbia credito disponibile.
- `ANTHROPIC_API_KEY`: non più necessaria, può restare vuota/assente.

## 3. Configura l'ambiente

```bash
cp .env.example .env
# apri .env e compila tutti i valori (APP_BASE_URL=https://maipal.it/general già corretto)
```

## 4. Avvia i container

```bash
docker compose up -d --build
```

Verifica che tutto giri:

```bash
docker compose ps
curl -I http://localhost:8080/general/
```

A questo punto l'app è raggiungibile SOLO in locale su `http://localhost:8080/general/`.
I passi successivi la espongono su internet sotto `maipal.it/general`.

## 5. Cloudflare Tunnel (esporre il PC locale senza aprire porte)

Il tunnel crea un hostname pubblico che punta al tuo Docker locale.

1. Installa `cloudflared` sul PC (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
2. Login e crea il tunnel:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create maipal-general
   ```
3. Crea un sottodominio DEDICATO al tunnel (NON la root, per non toccare il sito
   esistente), es. `general-origin.maipal.it`:
   ```bash
   cloudflared tunnel route dns maipal-general general-origin.maipal.it
   ```
4. Config del tunnel (`~/.cloudflared/config.yml`):
   ```yaml
   tunnel: maipal-general
   credentials-file: /home/<tuo-utente>/.cloudflared/<TUNNEL_ID>.json

   ingress:
     - hostname: general-origin.maipal.it
       service: http://localhost:8080
     - service: http_status:404
   ```
5. Avvia il tunnel:
   ```bash
   cloudflared tunnel run maipal-general
   ```
   (per farlo partire automaticamente col PC: `cloudflared service install`)

A questo punto `https://general-origin.maipal.it/general/` è già raggiungibile da
internet — ma è un sottodominio dedicato, non ancora `maipal.it/general`.

## 6. Cloudflare Worker: instrada maipal.it/general* verso il tunnel

Questo è il passaggio che fa convivere il sito esistente (su `maipal.it`) con mAIPAL
sotto `/general`, senza modificare nulla della configurazione attuale del sito.

1. Dashboard Cloudflare → il tuo dominio `maipal.it` → **Workers Routes** (o
   **Workers & Pages** → crea un nuovo Worker)
2. Codice del Worker (`worker.js`):
   ```js
   export default {
     async fetch(request) {
       const url = new URL(request.url);
       const origin = new URL(request.url);
       origin.hostname = "general-origin.maipal.it";
       const originReq = new Request(origin.toString(), request);
       return fetch(originReq);
     },
   };
   ```
3. Deploy del Worker, poi in **Workers Routes** aggiungi la route:
   - Route: `maipal.it/general*`
   - Worker: quello appena creato

Tutto il traffico verso `maipal.it/*` che NON matcha `/general*` continua ad andare
al sito esistente, invariato. Solo `/general*` viene deviato verso il tuo Docker
locale attraverso il tunnel.

## 7. Verifica finale

- `https://maipal.it/general/` → deve mostrare la pagina di login mAIPAL
- Click "Accedi con Google" → consenso Google → redirect a
  `https://maipal.it/general/dashboard` con sessione attiva
- `https://maipal.it/` (root) → deve continuare a mostrare il sito esistente,
  invariato

## Note operative

- Il PC deve restare acceso e con `cloudflared` + Docker attivi perché l'app resti
  raggiungibile (non è un hosting always-on gestito).
- Per aggiornare l'app dopo modifiche al codice: `docker compose up -d --build`.
- I log: `docker compose logs -f backend` / `frontend` / `mongodb`.
- Backup dati: il volume Docker `mongo_data` contiene tutto (utenti, task, diario,
  knowledge base) — fai backup periodici con `docker run --rm -v maipal-general_mongo_data:/data -v $(pwd):/backup mongo:7 mongodump --out /backup/dump_$(date +%F)`.

## 8. Più organizzazioni: API, worker e controlli di isolamento

Il backend ha due ruoli, scelti con la variabile `ROLE` (vedi `backend/jobs.py`):

- **`api`** (servizio `backend` nel `docker-compose.yml`): risponde alle richieste dell'app. Non esegue lavori
  periodici né il bot Telegram, quindi se ne possono avviare più copie: `docker compose up -d --scale backend=3`.
  Ogni copia usa `WEB_CONCURRENCY` processi (predefinito 2; uno per core disponibile è un buon valore).
- **`worker`** (servizio `worker`): esegue i lavori periodici (promemoria, presenze, riepiloghi, news,
  azioni programmate…) e il bot Telegram. Ogni lavoro gira per conto suo; il turno viene preso nel database
  (collezione `job_leases`), quindi una seconda copia del worker fa da riserva senza mandare doppi messaggi.
  Il bot Telegram è attivo su una sola copia alla volta e passa a un'altra se quella si ferma.
- **`all`** (predefinito se `ROLE` manca): tutto in un processo, come prima.

All'avvio vengono creati gli indici del database (`backend/db_indexes.py`); le sessioni scadute vengono cancellate da
MongoDB stesso. Variabili utili: `DAILY_PARALLEL` (utenti serviti insieme dai riepiloghi del mattino e della sera,
predefinito 8), `NEWS_PARALLEL` (news preparate insieme, predefinito 4), `TELEGRAM_SEND_RATE` (messaggi al secondo
di tutto il server, predefinito 25: Telegram ne accetta circa 30).

Per molte organizzazioni il PC di casa non basta: serve un server in cloud (UE) con MongoDB in replica set e
backup automatici. I passi sono descritti nel documento di analisi.

**Isolamento tra organizzazioni** (un'organizzazione non deve mai vedere i dati di un'altra):

- `backend/tests/test_tenant_isolation.py` gira con gli altri test e fallisce se un endpoint nuovo cerca un id
  ricevuto dalla richiesta senza filtrare per utente o organizzazione, finché non viene controllato.
- La prova completa: l'amministratore di un'organizzazione chiama ogni endpoint con gli id dei dati di un'altra.
  Serve un MongoDB **di prova** (il database viene svuotato a ogni passo):
  ```bash
  docker run -d --name mongo-prova -p 27018:27017 mongo:7
  cd backend
  ISOLATION_MONGO_URL=mongodb://localhost:27018 python -m pytest tests/test_tenant_isolation.py
  ```

## 9. Indice di ricerca (Cerca su tutto lo storico)

Le domande a Cerca leggono i record più recenti da MongoDB e, per tutto il resto dello storico, chiedono a un
**indice di ricerca** (Qdrant, servizio `qdrant` nel `docker-compose.yml`, vedi `backend/search_index.py`).
Senza indice resta il comportamento di prima: vengono letti al massimo 5.000 pezzi di note/documenti e 3.000 voci
di diario per domanda, e quelli più vecchi non vengono cercati (ora il log lo segnala).

- **Avvio**: `docker compose up -d` avvia anche `qdrant`. Il worker crea l'indice e ci copia tutti i record
  già salvati, un po' ogni minuto; finché non ha finito Cerca funziona come prima. Poi ogni nota, voce di diario,
  task, to-do, report o elemento di lista nuovo o modificato entra nell'indice entro un minuto (una cancellazione
  lo toglie). Lo stato: `docker compose exec worker python scripts/search_reindex.py`.
- **Sicurezza**: l'indice non ha porte aperte verso l'esterno. Dice solo *quali* record guardare: ogni record viene
  poi riletto da MongoDB con gli stessi filtri per utente e organizzazione di sempre, quindi un dato di un'altra
  organizzazione non può arrivare in una risposta neppure se l'indice sbagliasse. Facoltativo: una chiave
  (`QDRANT__SERVICE__API_KEY` sul servizio `qdrant` e lo stesso valore in `SEARCH_INDEX_API_KEY` nel `.env`).
- **Spazio**: circa 1,5 KB per record (il significato è compresso); 1 milione di record ≈ 1,5–2 GB.
- **Backup**: non serve. MongoDB contiene tutto, l'indice è una copia che si ricostruisce:
  `docker compose exec worker python scripts/search_reindex.py --rebuild` (anche se il volume `qdrant_data` va perso:
  il worker se ne accorge e lo ricostruisce da solo).
- **Passare a un altro indice** (un altro server, o MongoDB Atlas Vector Search in cloud): si imposta
  `SEARCH_INDEX_URL` sul nuovo indice e si fa `--rebuild`; per Atlas serve una classe con gli stessi metodi di
  `QdrantIndex` in `backend/search_index.py`. Il resto dell'app non cambia.
- **Disattivarlo**: `SEARCH_INDEX_URL=` (vuoto) nel `.env`. Se lo riattivi, il worker se ne accorge e lo riempie di nuovo.
- Variabili: `SEARCH_RECENT_KB`, `SEARCH_RECENT_LOGS` e `SEARCH_RECENT_DOCS` (record più recenti letti da MongoDB
  per domanda quando l'indice è completo, predefiniti 800, 500 e 400).
- **Significato calcolato al salvataggio**: il worker calcola il significato (embedding) di ogni record nuovo o
  modificato entro un minuto, anche **senza** indice, così una domanda non lo aspetta più. La prima volta lo fa per
  tutti i record che non l'hanno ancora: con molti dati il worker resta impegnato per un po' (in background).
- **Documenti di commessa**: il testo completo (fino a circa 150 pagine) è salvato a pezzi in `job_doc_chunks` e cercato
  da Cerca, con la stessa visibilità della voce di diario. I documenti caricati prima di questa versione vengono resi
  ricercabili all'avvio del worker, dal testo che era già salvato (i primi 20.000 caratteri).
- Prova con MongoDB e Qdrant veri: `backend/tests/integration/live_search_index.py` (istruzioni in testa al file).
