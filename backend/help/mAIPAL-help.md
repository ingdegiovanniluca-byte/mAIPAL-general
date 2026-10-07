<!--
Guida di mAIPAL, letta da Help (backend/help_guide.py).

- Ogni sezione inizia con "## Titolo" seguito da una riga di metadati:
  <!- - id: liste · path: /dashboard/liste · verticale: tutti - ->   (senza gli spazi tra i trattini)
  id        nome univoco della sezione
  path      la pagina dell'app che la "i" accanto al titolo spiega (facoltativo; più sezioni
            possono avere la stessa pagina: la "i" le mostra tutte)
  verticale tutti | artigiano | veterinario | fitness | !artigiano (= tutti tranne artigiano);
            più valori separati da virgola
- Scritta per l'utente: cosa può fare e dove si trova, non come è fatta dentro.
- Va aggiornata insieme a ogni funzione nuova o cambiata (il test tests/test_help_guide.py
  controlla che ogni sezione del menu abbia la sua pagina).
-->

## Cos'è mAIPAL
<!-- id: panoramica · verticale: tutti -->
mAIPAL è il tuo assistente personale: scrivi o detti in italiano quello che ti serve e lui salva informazioni, crea task e promemoria, tiene il diario, aggiorna le liste e risponde alle tue domande usando quello che hai salvato.

**Come è organizzata l'app**
- **Chat**: il punto di partenza. Scegli un agente (Cerca, Salva, Task, Diario, …) e scrivi o detta.
- **Le sezioni** (Task, To-Do, Diario, News, Liste, Documenti, Azioni, Impostazioni) mostrano e permettono di modificare quello che hai salvato.
- **Menu in basso (telefono)**: Chat è sempre presente; con il tasto **+** apri l'elenco di tutte le sezioni. Con il pallino accanto a ciascuna scegli le 3 da tenere in primo piano nel menu.
- **Menu in alto (computer)**: tutte le sezioni sono in fila nella barra in alto.
- **Popup del profilo** (tocca la tua foto o la tua iniziale in alto a destra): Impostazioni, Installa l'app, Help, Esci; sotto, il tema chiaro/scuro e da che lato della chat sta il microfono.
- **La "i" accanto al titolo** della sezione, in alto, spiega quella sezione. Da lì puoi anche fare domande a Help.

**Dove puoi usare mAIPAL**
- Nel browser e come app installata sul telefono (vedi "App sul telefono").
- Su **Telegram**, dopo averlo collegato da Impostazioni.
- Sull'**orologio Galaxy Watch**, dopo averlo collegato da Impostazioni.

**Verticali**: se lavori in un settore specifico (Artigiano, Veterinario, Fitness), sceglilo in Impostazioni → Verticale. Compaiono gli agenti e le sezioni dedicati al tuo lavoro.

## Help
<!-- id: help · verticale: tutti -->
Help risponde alle domande su mAIPAL: cosa può fare, dove si trova una funzione, come si usa.
- **Dal profilo**: tocca la tua foto in alto a destra → **Help**. Si apre la chat in modalità Help: fai tutte le domande che vuoi. Per tornare agli altri agenti tocca la ✕ accanto a "Help" o scegli un altro agente.
- **Dalla "i"** accanto al titolo di ogni sezione: leggi la spiegazione di quella sezione e, se serve, tocca **Chiedi a Help**.
- **Dalla chat normale**: se con Cerca fai una domanda chiaramente su mAIPAL (es. "come creo una lista?", "cosa sai fare?"), ti risponde direttamente Help. Le domande sui tuoi dati ("cosa c'è nella lista della spesa?") restano a Cerca.

## Chat
<!-- id: chat · path: /dashboard/chat · verticale: tutti -->
La chat è il cuore di mAIPAL: scegli un **agente**, poi scrivi o detta il messaggio.

**Gli agenti**
- **Cerca**: risponde alle domande usando quello che hai salvato (note, documenti, task, diario, liste).
- **Salva**: memorizza note, codici, documenti e foto; capisce anche quando vuoi aggiungere, modificare o togliere un elemento da una lista.
- **Task**: crea task con data, to-do senza data, ricorrenze e promemoria.
- **Diario**: racconta la giornata e la salvo nel diario. Per gli artigiani diventa il **Diario di commessa**.
- **Referto** (veterinari) e **Report** (artigiani): generano un documento Word dalla tua dettatura.
- **Azioni**: comandi che mAIPAL esegue da solo con una cadenza (es. ogni venerdì).

Sul telefono gli agenti sono in fila sotto la casella di scrittura: toccane uno per sceglierlo, con **Altri** li vedi tutti. La **ⓘ accanto al nome dell'agente** spiega cosa fa, cosa significano le sue icone e propone esempi (toccandone uno lo scrive nella casella).

**Scrivere, dettare, allegare**
- **Microfono**: toccalo per dettare e di nuovo per fermare; la trascrizione va nella casella (con la ✕ annulli la registrazione). Il lato del microfono si sceglie dal popup del profilo.
- **Graffetta**: allega foto e documenti (Salva li legge e li mette nella tua base di conoscenza).
- **Icone sotto il nome dell'agente**: opzioni dell'agente, es. salvare anche su Drive/OneDrive, mettere i task nel calendario, attivare il promemoria.

**Più agenti in un messaggio: i tag @**
Scrivi `@task`, `@salva`, `@cerca`, `@diario`, `@lista` o `@azione` dentro il messaggio: il testo dopo il tag va a quell'agente. Es. "Visita di Fester, tutto bene @task richiamare la signora giovedì". Si può anche dettare "agente task …" o "chiocciola task …".

**Condividere con il team**: scrivi `@nome` di un collega o `@team` per condividere con lui o con tutti l'informazione che salvi.

**Agente sbagliato?** Se scrivi a un agente qualcosa che è chiaramente per un altro (es. "salva che…" a Cerca), mAIPAL te lo segnala e con un tocco lo rimanda all'agente giusto.

**Cronologia**
- Sul telefono il tasto tondo con l'orologio, sul lato destro, apre la cronologia delle chat; sparisce mentre scorri o scrivi.
- Tocca una chat della cronologia per riprenderla e continuare a scrivere nello stesso contesto.
- Le chat si cancellano da sole **10 giorni** dopo l'ultimo messaggio: segna con la **stella** quelle da tenere. Note, task e diario salvati restano comunque.

## Cerca
<!-- id: agente-cerca · verticale: tutti -->
Cerca risponde alle tue domande usando quello che hai salvato.
- Esempi: "Qual è il codice del wifi?", "Quanto ho speso per il gatto negli ultimi tre mesi?", "Cosa devo fare questa settimana?".
- Icone sotto il nome: **cerca ovunque** (note, documenti, task, diario e liste) oppure **solo nella base di conoscenza** (note e documenti).
- Capisce i periodi ("a settembre", "la settimana scorsa") e può rispondere anche sui file allegati in quella chat.
- Se la domanda è su come si usa mAIPAL, risponde Help.

## Salva
<!-- id: agente-salva · verticale: tutti -->
Salva memorizza informazioni nella tua base di conoscenza, così poi Cerca le ritrova.
- Note e fatti: "Il codice del wifi è XYZ-123", "Marco è allergico alle noci".
- Foto e documenti (con la graffetta): li legge (anche gli scontrini) e li salva; la lettura del contenuto si può spegnere dalle icone.
- **Drive / OneDrive**: con le icone sotto il nome scegli se salvare gli allegati anche lì. Con l'icona della cartella accesa, se non scrivi la cartella te la chiede; spenta, usa quella che scrivi o la cartella mAIPAL.
- **Liste**: "Aggiungi Mario Rossi alla lista Clienti", "Togli il latte dalla lista della spesa", "Crea una lista Fornitori con nome e telefono".
- Se nel testo c'è anche un impegno con una data chiara ("ricordami tra 10 giorni…"), crea anche il task.

## Agente Task
<!-- id: agente-task · verticale: tutti -->
L'agente Task trasforma quello che scrivi in **task** (con una data) o **to-do** (senza data).
- Esempi: "Ricordami di chiamare il fornitore martedì alle 15", "Palestra ogni lunedì e giovedì alle 18", "Devo comprare il regalo per Anna".
- **Ricorrenze**: "ogni lunedì", "il primo del mese", "l'ultimo giorno del mese".
- **Promemoria**: "avvisami un'ora prima"; oppure l'icona della campanella sotto il nome.
- **Calendario**: con l'icona del calendario accesa i nuovi task vanno anche su Google Calendar / Outlook (se collegati).
- **Comandi**: "Segna come fatto il task del commercialista", "Sposta la palestra a venerdì", "Elimina il task del dentista".
- Può creare task anche da un documento che hai caricato (es. "crea un task per ogni lezione del calendario che ti ho mandato").

## Task
<!-- id: task · path: /dashboard/tasks · verticale: tutti -->
La sezione Task mostra i tuoi impegni con una data.
- **Telefono**: in alto la striscia dei giorni del mese; tocca un giorno o una settimana per filtrare (un altro tocco toglie il filtro). Sotto, un'unica lista in ordine di scadenza; il colore indica la priorità.
- **Computer**: tre colonne per priorità (alta, media, bassa), con filtri per attivi/completati, scaduti/non scaduti, preferiti, archiviati e ricerca per #hashtag.
- **Aprendo un task** puoi:
  - modificarlo scrivendo in linguaggio naturale ("spostalo a giovedì alle 10, priorità alta");
  - cambiare la data, la ripetizione, il promemoria e il calendario;
  - aggiungere **note** libere (restano solo per te, mAIPAL non le interpreta);
  - **condividerlo o assegnarlo** a un collega del team;
  - vedere **da dove è nato** (es. "Da: Nota del 29 set" se creato con @task).
- **Task ricorrenti**: modificando o eliminando un'occorrenza scegli se vale solo per quella o anche per le successive; quelle passate restano come sono.
- I task scaduti sono in rosso scuro.

## To-Do
<!-- id: todo · path: /dashboard/todos · verticale: tutti -->
I to-do sono le cose da fare senza una data precisa.
- Tre stati: **Da fare**, **In corso** (con la barra di avanzamento), **Fatti**.
- Aprendo un to-do puoi aggiornarlo scrivendo ("a metà, manca solo la stampa"), cambiare stato, avanzamento e tag, aggiungere note, segnarlo come preferito o eliminarlo.
- Li crei dalla chat con l'agente Task (se non c'è una data diventa un to-do).

## Diario
<!-- id: diario · path: /dashboard/journal · verticale: !artigiano -->
Il diario raccoglie le tue giornate.
- Scrivi o detta dalla chat con l'agente **Diario**: mAIPAL riordina il testo e lo salva nel giorno giusto ("ieri", "sabato"). Puoi allegare fino a 5 foto.
- Nella sezione le giornate scorrono come schede; con il calendario cambi mese.
- Puoi segnare una giornata come **memorabile** (preferita), eliminare una voce o una foto.
- Cerca sa rispondere anche sul diario ("cosa ho fatto a Pasqua?").

## Diario di commessa
<!-- id: diario-commessa · path: /dashboard/journal · verticale: artigiano -->
Il diario di commessa raccoglie, cantiere per cantiere, il lavoro fatto: ore per persona, materiali usati, problemi e foto.

**Scrivere nel diario**
- Dalla chat con l'agente **Diario**, anche a voce: "Oggi io e Gino dai Rossi, 4 ore a testa: posati 20 metri di corrugato, manca una scatola 503".
- mAIPAL riconosce la commessa dal cliente o dai lavori che nomini; se non è sicuro te lo chiede con dei pulsanti (o ti propone di aprire una nuova commessa).
- Puoi allegare le foto: vanno nella voce e nella cartella della commessa su Drive/OneDrive.
- Da Telegram: comando `/journal` o scrivi liberamente; le foto mandate subito dopo vanno nella stessa voce.

**La sezione**
- In alto i clienti, ognuno con le sue commesse e il loro stato; tocca una commessa per aprirne il diario.
- Nel diario della commessa:
  - una riga di informazioni da scorrere: **Stato** (toccalo per cambiarlo), Ore, Segnalazioni, Documenti, Cantiere (apre la mappa), Date, Telefono, Email;
  - le sezioni **Diario / Ore / Problemi / Materiali**: scorri per passare dall'una all'altra;
  - il **periodo** (ultimi 30 giorni, questo mese, tutto o date a scelta) con l'icona del calendario;
  - le voci giorno per giorno, con l'autore in grigio e le foto. Tocca una voce per modificarla o eliminarla.
- Ogni cambio di stato resta scritto nel diario.
- Il **tasto chat** tondo sul lato apre una chat per interrogare la commessa: "quante ore abbiamo fatto?", "cosa manca da comprare?".

## Report di lavoro
<!-- id: report-lavoro · verticale: artigiano -->
L'agente **Report** genera il report di un sopralluogo in Word, con lo spazio per le firme.
- Detta o scrivi com'è andato: "Sopralluogo dal signor Mario Rossi in via Roma 5 a Torino: impianto della cucina da rifare…".
- mAIPAL riconosce il cliente nella lista Clienti e la commessa; se non ci sono li crea. Se ci sono più clienti simili, te lo chiede.
- Il report si salva su Drive/OneDrive nella cartella del cliente e della commessa (mAIPAL/Clienti/cliente/commessa) e si scarica dalla chat.
- **Modificare il report**: nella stessa chat scrivi la correzione ("nei tempi metti 3 giorni"): mAIPAL crea la versione successiva cambiando solo quello che hai detto.
- Con l'icona sotto il nome scegli il tipo di report o carichi un tuo modello.
- Da Telegram: comando `/report`.

## Referto veterinario
<!-- id: referto · verticale: veterinario, nessuno -->
L'agente **Referto** genera il referto strutturato (Word) della visita.
- Detta o scrivi il resoconto: "Ho visitato Fester, controllo ecografico di routine, tutto nella norma".
- Scegli il tipo di visita (es. imaging, visita generale) o carica un tuo modello di referto dall'icona sotto il nome.
- Il referto viene collegato al paziente e salvato su Drive/OneDrive se collegati.
- Da Telegram: comando `/report`.

## News
<!-- id: news · path: /dashboard/news · verticale: tutti -->
Ogni giorno mAIPAL prepara una selezione di notizie scelta in base alla tua professione, al settore e ai tuoi interessi (Impostazioni → Profilo).
- L'orario di invio si sceglie in Impostazioni → Profilo ("orario invio news").
- Con **Mi interessa / Non mi interessa** insegni a mAIPAL cosa preferisci; puoi eliminare una notizia.

## Liste
<!-- id: liste · path: /dashboard/liste · verticale: tutti -->
Le liste tengono in ordine elenchi strutturati: clienti, fornitori, esercizi, spesa…
- **Creare una lista**: tasto **Nuova lista**, oppure dalla chat con Salva ("crea una lista Fornitori con nome, telefono ed email").
- **Struttura**: ogni lista ha dei **campi** (le righe, es. un cliente) con i loro **attributi** (es. telefono, email). Una lista può avere anche un terzo livello di **elementi annidati** dentro ogni campo (es. le commesse di un cliente).
- **Gestisci attributi** (icona dell'ingranaggio): aggiungi, rinomina o togli attributi, ne scegli il tipo (testo breve o lungo, numero, data, scelta da elenco, telefono, email, collegamento a un'altra lista) e i limiti.
- **Aggiungere e modificare**: tasto **+**, oppure dalla chat ("aggiungi Mario Rossi alla lista clienti, telefono 333…"). Tocca una scheda per modificarla o aprirne gli elementi.
- **Riordinare**: trascina le schede. **Eliminare**: seleziona le schede e tocca il cestino.
- **Rinominare**: tocca il nome della lista.
- **Condividere**: icona di condivisione → scegli i colleghi o tutto il team. Chi la riceve può vederla e modificarla; solo tu puoi eliminarla o cambiare con chi è condivisa.
- **Cartella su Drive/OneDrive**: icona della cartella → crea (o apre) la cartella della lista dentro mAIPAL.
- Le **Azioni programmate** possono lavorare sulle liste (es. "ogni venerdì svuota gli iscritti della lista Pilates").

## Clienti e commesse
<!-- id: clienti-commesse · path: /dashboard/liste · verticale: artigiano -->
Per gli artigiani c'è la lista **Clienti**, già pronta, con le **commesse** di ogni cliente.
- La scheda del cliente mostra nome e indirizzo; con la **freccia** si espande e mostra telefono, email e gli altri dati, con **Modifica** ed **Elimina cliente** (elimina anche le sue commesse e il loro diario).
- Tocca il cliente per vedere le sue commesse: in alto il numero di commesse **totali** e **attive** (tutte tranne le chiuse), e il **+** per aggiungerne una.
- La scheda commessa mostra Commessa, Via e Stato (preventivo, in corso, sospesa, chiusa); con la freccia vedi gli altri dati e i tasti Diario, Modifica, Elimina.
- Tocca la commessa per aprirne il **diario di commessa**.
- L'icona della **cartella** sulla commessa crea (o apre) su Drive/OneDrive la cartella mAIPAL/Clienti/cliente/commessa, dove finiscono anche report e foto del diario.
- Clienti e commesse si creano anche da soli quando detti un report o una voce di diario per un cliente nuovo.

## Documenti
<!-- id: documenti · path: /dashboard/documents · verticale: tutti -->
Documenti è la tua **base di conoscenza**: tutto quello che hai caricato con Salva (file, foto, scontrini) e che Cerca usa per rispondere.
- Vedi il totale, le categorie (lavoro, personale, finanza, salute…) e puoi filtrare per categoria.
- Cerca per nome, parola chiave o anteprima.
- Puoi rimuovere un documento.
- Per aggiungerne: Chat → Salva, con la graffetta (o condividendo un file dal telefono verso mAIPAL).

## Azioni
<!-- id: azioni · path: /dashboard/azioni · verticale: tutti -->
Le azioni programmate sono comandi che mAIPAL esegue da solo, con la cadenza che scegli, finché non le fermi.
- **Crearle**: dalla chat con l'agente **Azioni** ("Ogni lunedì alle 8 mandami su Telegram i task della settimana", "Ogni venerdì all'una di notte svuota gli iscritti della lista Lezioni Pilates"). Prima di attivarla, mAIPAL ti mostra cosa farà.
- **Nella sezione**: l'elenco delle azioni con la prossima esecuzione; puoi **eseguirne una subito** (senza cambiare la programmazione) o eliminarla.
- Da Telegram: `/azione <comando>` per crearne una, `/azioni` per l'elenco.

## Fitness
<!-- id: fitness · path: /dashboard/fitness · verticale: fitness -->
La sezione Fitness (per istruttori, es. danza e pilates) ha tre parti:
- **Esercizi**: il database degli esercizi, con descrizione, categoria (es. riscaldamento, core) e attrezzi (es. tappetino, elastico); può essere condiviso con il team.
- **Lezioni**: componi lezioni riutilizzabili mettendo in sequenza gli esercizi, con una nota per ognuno; oppure descrivi la lezione e mAIPAL la propone. Le **linee guida** dicono a mAIPAL come generarle.
- **Clienti**: i tuoi clienti con abbonamento (es. mensile, 10 lezioni).

## Impostazioni
<!-- id: impostazioni · path: /dashboard/settings · verticale: tutti -->
Dalle Impostazioni (popup del profilo → Impostazioni, o dal menu) gestisci:
- **Profilo**: foto, professione, settore, verticali d'uso, interessi, tono delle risposte, indirizzi di casa e lavoro, orario delle news e del riepilogo del mattino. Ricorda di toccare **Salva profilo**.
- **Verticale**: il tuo settore (Veterinario, Fitness, Artigiano); quello scelto è evidenziato con la spunta. Cambia gli agenti e le sezioni dedicate.
- **Google Workspace**: collega Drive (cartella mAIPAL per file e allegati) e Calendar (eventi dai task).
- **Microsoft**: collega OneDrive e Outlook.
- **Dove salvo file ed eventi**: se hai collegato entrambi, scegli dove salvare i file e dove mettere gli eventi.
- **Telegram**: collega il bot (vedi "Telegram").
- **Orologio**: collega il Galaxy Watch (vedi "Orologio").
- **Team**: unisciti a un team con il codice ricevuto dall'amministratore, per condividere task e liste.
- **Amministrazione** (solo amministratori): accessi, utenti e team.

Tema chiaro/scuro e lato del microfono non sono qui: sono nel popup del profilo.

## Telegram
<!-- id: telegram · verticale: tutti -->
Con Telegram usi mAIPAL dal telefono come una chat.
- **Collegarlo**: Impostazioni → Telegram → Genera codice di collegamento → apri il bot, premi Avvia: il messaggio `/start codice` collega l'account. Il codice vale una volta sola.
- Scrivi liberamente: il bot capisce se stai salvando, cercando, creando un task o scrivendo il diario. Se il messaggio dopo continua lo stesso argomento, resta nel contesto.
- Mandagli foto (con o senza didascalia): le salva su Drive; se non capisce la cartella, te lo chiede.
- Comandi: `/ask` domanda, `/save` informazione, `/task` task, `/journal` diario, `/report` referto o report, `/lista` modifica una lista, `/azione` e `/azioni` azioni programmate, `/end` chiude la conversazione, `/help`.
- Ogni mattina (all'orario scelto in Profilo) ricevi il riepilogo della giornata; il lunedì quello della settimana. La sera alle 21 il resoconto della giornata, il venerdì quello della settimana.
- Help per ora risponde solo nell'app, non su Telegram.

## Orologio
<!-- id: orologio · verticale: tutti -->
Con l'app mAIPAL per **Galaxy Watch** parli con gli agenti e guardi task, to-do e liste dal polso.
- **Collegarlo**: apri mAIPAL sull'orologio, mostra un codice di 6 cifre; scrivilo in Impostazioni → Orologio e tocca Collega.
- In Impostazioni vedi gli orologi collegati e quando sono stati usati; con il cestino lo scolleghi.

## Team e condivisione
<!-- id: team · verticale: tutti -->
- Entri in un team con il codice che ti dà l'amministratore (Impostazioni → Team).
- Puoi **condividere o assegnare task** (dal dettaglio del task), **condividere liste** (icona di condivisione della lista) e **condividere informazioni** salvate scrivendo `@nome` o `@team` nel messaggio.
- Gli artigiani vedono i colleghi del team anche nelle ore del diario di commessa.

## App sul telefono
<!-- id: app-telefono · verticale: tutti -->
- **Installare l'app**: popup del profilo → **Installa l'app** (su iPhone: Condividi → Aggiungi a schermata Home). Si apre a schermo intero come un'app.
- **Scorciatoie**: tenendo premuta l'icona dell'app trovi Nuova nota, Nuovo task e Cerca.
- **Condividere verso mAIPAL**: da un'altra app (foto, file, link) scegli mAIPAL in "Condividi": si apre la chat con il contenuto pronto da salvare.
- **Tema**: chiaro o scuro dal popup del profilo (sole / luna).
- **Microfono**: nel popup del profilo, sotto il tema, scegli se il tasto dei vocali sta a sinistra o a destra della barra di scrittura. Vale su quel dispositivo.
