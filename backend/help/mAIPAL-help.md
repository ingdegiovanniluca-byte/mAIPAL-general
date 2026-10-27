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

**Sul computer: chat a sinistra, sezione a destra**
- Con la finestra larga (da circa 1.100 pixel) la chat resta sempre nella colonna di sinistra, come sul telefono (nome dell'agente, casella, fila degli agenti, cronologia con il pulsante tondo), e a destra c'è la sezione scelta nell'header (Task, Diario, Liste...). Riquadri, colori ed effetti sono gli stessi del telefono. Cambiando sezione cambia solo la parte destra: la conversazione resta aperta.
- **Chat** nell'header apre (o chiude) la cronologia delle conversazioni nella colonna di sinistra; **Help** dal menu del profilo e "Chiedi a Help" aprono l'Help lì.
- Trascina il **bordo** tra le due colonne per allargare o stringere la chat (al massimo un terzo della finestra: la sezione a destra ha sempre almeno i due terzi e usa tutto lo spazio che ha); con **«** la nascondi (la sezione usa tutta la larghezza) e con **Chat** in alto a sinistra la riapri. Larghezza e scelta restano su quel computer.
- Con la finestra più stretta mAIPAL si mostra come sul telefono.

**Gli agenti**
- **Cerca**: risponde alle domande usando quello che hai salvato (note, documenti, task, diario, liste).
- **Salva**: memorizza note, codici, documenti e foto; capisce anche quando vuoi aggiungere, modificare o togliere un elemento da una lista.
- **Task**: crea task con data, to-do senza data, ricorrenze e promemoria.
- **Diario**: racconta la giornata e la salvo nel diario. Per gli artigiani diventa il **Diario di commessa**.
- **Referto** (veterinari) e **Report** (artigiani): generano un documento Word dalla tua dettatura.
- **Lezioni** (fitness): chiedi la lezione (es. "lezione funzionale per 10 persone, livello medio, gambe") e la compongo con le regole del tipo, i tuoi esercizi e i tuoi attrezzi; la trovi poi in Fitness → Lezioni. Nella stessa chat puoi chiedere modifiche ("fallo per 15 persone", "togli gli affondi"): cambio quella lezione. Per una lezione nuova scrivi "nuova lezione…" o "crea…".
- **Azioni**: comandi che mAIPAL esegue da solo con una cadenza (es. ogni venerdì).

Sul telefono gli agenti sono in fila sotto la casella di scrittura: toccane uno per sceglierlo, con **Altri** li vedi tutti. La **ⓘ accanto al nome dell'agente** spiega cosa fa, cosa significano le sue icone e propone esempi (toccandone uno lo scrive nella casella). A sinistra del nome c'è l'agente come una piccola **goccia animata**, con il suo colore e il suo carattere (Cerca ha gli occhiali, Report il caschetto, Azioni la mascherina): si guarda intorno quando aspetta, ti ascolta mentre scrivi o registri e si mette al lavoro quando invii.

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
- Cerca **legge** soltanto, non salva: le spese ("oggi ho speso 50 euro di benzina") e ogni altra informazione da ricordare si registrano con l'agente **Salva**. Se le scrivi a Cerca, ti propone di mandarle a Salva con un tocco.
- Per il totale di un periodo chiedi pure come ti viene: "spese di ottobre", "totale del mese", "quanto ho pagato questo mese": vengono considerate tutte le spese salvate in quel periodo.

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
- **Sul telefono** i tre stati sono tre **cartelle**, una sotto l'altra, con il numero dei to-do e il **+**. Dalla cartella spuntano i primi to-do: passandoci sopra il dito la cartella si apre in avanti e i to-do escono a ventaglio (quello sotto il dito sale di più).
- **Sfogliare i to-do di una cartella**: scorri in su con il dito sopra i to-do e lasciali: restano alzati. Ora scorrendo in orizzontale sfogli tutti i to-do della cartella (le caselle seguono il dito; dopo l'ultimo ricomincia dal primo, e all'indietro dall'ultimo) (il to do in primo piano si alza un po’ di più; in basso a sinistra vedi quale è, es. "3 di 7"), toccandone uno lo apri, e scorrendo in giù rientrano nella cartella.
- Tocca una cartella per l'**elenco** di tutti i suoi to-do: la stella li mette tra i preferiti (in cima), le frecce li **spostano** in un'altra cartella, il cerchio li segna come fatti (o li riapre), il cestino li elimina; toccando il titolo li apri. Con la freccia in alto (o il tasto indietro) torni alle cartelle.
- Il **+** su una cartella crea un to-do già in quello stato: scrivi cosa c'è da fare, le note e la priorità.
- Sul computer i tre stati restano tre colonne affiancate.
- Li crei anche dalla chat con l'agente Task (se non c'è una data diventa un to-do).

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
- **Materiali da prendere**: quello che va ancora preso, portato, comprato od ordinato ("domani porto 10 scatole 503 e il flessibile") **non** va tra i materiali usati: diventa un promemoria **Da prendere** (un To Do) per il giorno in cui serve (se non lo dice, il giorno dopo). È per chi l'ha scritto, oppure per chi nomini: "ricorda a Mario di prendere domani…", "Gino porta…" (un collaboratore abilitato sulla commessa o un collega del team). Un collaboratore lo riceve subito su Telegram; se non ha collegato Telegram, il promemoria arriva a te. Se il messaggio parla solo di quello, non nasce nessuna voce di diario. Il promemoria arriva **alle 19.30 della sera prima** e **alle 7 del mattino** del giorno stesso: su Telegram con ✅ Fatto per i collaboratori, con la notifica dell'app (e Telegram, se collegato) per te e il team.
- Se non si capisce se i materiali sono stati usati o sono da prendere (es. solo "10 scatole 503"), mAIPAL chiede con due pulsanti: **Usati oggi** / **Da prendere**.
- I materiali da prendere si vedono in cima alla sezione **Materiali** (blocco **Da prendere**) e tra i **To Do**, con l'icona della scatola. Se una voce già salvata ha un materiale che in realtà era da prendere, aprila e tocca l'icona del calendario accanto al materiale: esce dai materiali usati e diventa un promemoria per il giorno dopo.
- I collaboratori esterni possono anche segnare **arrivo e fine in cantiere** dal pulsante 📍 su Telegram: le ore vanno nel diario da sole, con la distanza dal cantiere (vedi "Collaboratori su Telegram"). In alto, **In cantiere ora** mostra chi sta lavorando; la posizione del cantiere la imposti dal pallino sulla mappa (o dalla voce **Cantiere**, se la mappa non c'è ancora).
- **Anche tu e il tuo team** segnate arrivo e fine in cantiere:
  - **dall'app**: nel diario della commessa, sotto il nome, tocca **📍 Sono in cantiere** (con la posizione del telefono, se la permetti) e poi **Ho finito**. Alla fine scegli se togliere una pausa e scrivi **com'è andata oggi**: va nel diario;
  - **da Telegram**: comando `/cantiere` per il pulsante 📍, oppure scrivi «sono arrivato (dai Rossi)» / «ho finito (alle 17:30)». Se le commesse aperte sono più di una, la sceglie la posizione, il nome scritto o i pulsanti.
  - Le ore vanno nel diario a nome tuo, come quelle dei collaboratori.
- **Controllo serale**: dalle **19:00** (l'orario lo cambi in Impostazioni → Collaboratori) chi risulta ancora in cantiere riceve la domanda **«Sei ancora in cantiere?»**, su Telegram con i pulsanti **Sì / No** e, per chi usa l'app, con una notifica e il riquadro nel diario. Tu ricevi un avviso con chi è ancora lì e poi la sua risposta.
  - **No**: chiede a che ora è andato via (pulsanti con le mezz'ore, oppure «ho finito alle 17:40») e chiude il tempo a quell'ora.
  - **Sì**: la domanda torna due ore dopo.
  - Chi ha iniziato tardi riceve la domanda due ore dopo l'inizio.
- **Com'è andata oggi?**: una ventina di minuti dopo la fine, se nel diario di quella commessa non ha scritto niente quel giorno (solo le ore), chi era in cantiere riceve la domanda. La risposta, anche a voce, va nel diario della commessa.
- L'agente Diario **scrive soltanto**: salva solo quello che hai detto tu, senza aggiungere nulla. Se la nota non è chiara non salva niente e ti chiede di precisare. Se invece fai una domanda ("com'è messa la commessa dei Rossi?") non salva niente: per cercare usa l'agente **Cerca** oppure la chat della commessa qui nel Diario.
- Puoi allegare le foto: vanno nella voce e nella cartella della commessa su Drive/OneDrive. Se mandi prima la foto e poi (entro 20 minuti) la sua descrizione, scritta o a voce, la descrizione completa la voce della foto invece di crearne una nuova.
- Da Telegram: comando `/journal` o scrivi liberamente; le foto mandate subito dopo vanno nella stessa voce.

**La sezione**
- In alto i clienti: ogni riquadro mostra nome, indirizzo e quante commesse ha (**totali** e **attive**, cioè tutte tranne le chiuse). Con la **freccia** lo apri e vedi le sue commesse con il loro stato; tocca una commessa per aprirne il diario. Cercando un cliente o una commessa, i riquadri trovati si aprono da soli.
- Nel diario della commessa:
  - una riga di informazioni da scorrere: **Stato** (toccalo per cambiarlo), Ore, Segnalazioni, Documenti, Date, Telefono, Email (il cantiere è sulla mappa qui sotto; la voce **Cantiere** compare solo finché la posizione non c'è);
  - la **mappa** del cantiere, a colori, sotto i dati in alto: il pallino è **verde** (col numero) se qualcuno è in cantiere ora, arancione se non c'è nessuno. Trascina la **barretta** sotto la mappa in su per nasconderla e in giù per riaprirla, oppure toccala; la scelta resta su quel dispositivo. Con un dito sposti la mappa, con due la ingrandisci. **Tocca il pallino** per sapere cosa indica: chi è in cantiere e da quando (o che non c'è nessuno), l'indirizzo e il pulsante per **navigare** fin lì. La posizione è quella dell'indirizzo o quella che imposti tu: tocca il pallino e poi l'icona della **posizione**. Senza una posizione la mappa non c'è, e al suo posto nella barra in alto c'è la voce **Cantiere** per impostarla;
  - le sezioni **Diario / Ore / Problemi / Materiali / Costi / Milestone / To Do**: scorri per passare dall'una all'altra;
  - **To Do**: le prossime attività della commessa. Con **Nuova attività** scrivi cosa c'è da fare, **chi se ne occupa** ed **entro quando** (facoltativo). Il pallino la segna come fatta; toccandola la modifichi o la elimini. Le attività restano dentro la commessa (non compaiono nella sezione To-Do generale);
  - il **periodo** (questa settimana da lunedì, ultimi 30 giorni, questo mese, tutto o date a scelta) con l'icona del calendario;
  - le voci giorno per giorno, con l'autore in grigio e le foto. Tocca una voce per modificarla o eliminarla.
- Ogni cambio di stato resta scritto nel diario.
- Anche ogni **report** generato con l'agente **Report** per una commessa resta scritto nel suo diario: il tipo di report, chi l'ha fatto e un breve riassunto, con il link **Scarica il report**. Se poi modifichi il report, nel diario compare anche la nuova versione con i campi cambiati. Toccando la riga puoi toglierla dal diario (il report resta tra i documenti).
- Il **tasto chat** tondo sul lato apre una chat per interrogare la commessa: "quante ore abbiamo fatto?", "cosa manca da comprare?".

**Contatti utili**
- Il riquadro **Contatti** in alto apre i contatti della commessa: gli altri artigiani e le persone del lavoro (idraulico, elettricista, direttore lavori, fornitori, amministratore…), con ruolo, telefono, email e una nota. Tocca il numero per chiamare, l'email per scrivere.
- **Aggiungi** un contatto: se il nome è già usato su un'altra commessa, ruolo, telefono ed email si compilano da soli.
- Gli stessi contatti li vedi (e li aggiungi) anche nella scheda della commessa della lista Clienti, aprendola con la freccia.
- La chat della commessa e l'agente Cerca li conoscono ("qual è il numero dell'idraulico dei Rossi?").

**Milestone**
- Nella sezione **Milestone** segni le tappe del lavoro: cosa va completato, **chi la esegue** e la **scadenza** (Nuova milestone).
- Il **pallino** la segna come fatta (con la data di oggi); toccandola puoi cambiare la data di esecuzione, la scadenza, chi la esegue, oppure eliminarla.
- **Ritardi**: la prima scadenza resta salvata. Vedi se una milestone è **in ritardo** (e di quanti giorni), se è stata fatta in tempo o con quanti giorni di ritardo, e di quanto è stata spostata. In alto: quante sono fatte, quante in ritardo, quante in tempo e il ritardo medio. Cambiare la scadenza prima che sia scaduta è una nuova pianificazione, non un ritardo.
- **Azioni correttive**: su una milestone in ritardo (o a rischio) scrivi cosa fai per recuperare e, se serve, la nuova scadenza. Restano nella milestone e nel diario.
- **Promemoria su Telegram**, dalle 8 del mattino: il giorno prima della scadenza, il giorno stesso e quando va in ritardo (ti chiede di segnarla fatta o di scrivere l'azione correttiva). Li ricevono chi l'ha creata e chi la esegue, se è un collega del team o un collaboratore abilitato sulla commessa con Telegram collegato.
- Le milestone completate e le azioni correttive restano scritte nel diario; il **riepilogo del lunedì** elenca quelle in ritardo e quelle della settimana; la chat della commessa risponde anche su di loro ("quali milestone sono in ritardo?").
- Il riquadro **Milestone** in alto mostra quante sono fatte e quante in ritardo.
- **Modelli di milestone**: con **Da modello** aggiungi in un colpo le milestone di un tipo di lavoro, a partire dal giorno di inizio che scegli (le scadenze sono in giorni lavorativi, lunedì-venerdì; vedi le date prima di confermare). Ci sono **modelli pronti**: impianto elettrico domestico, rifacimento bagno, rifacimento cucina (impianti), impianto idraulico, sostituzione caldaia, climatizzazione, tinteggiatura, ristrutturazione appartamento. Quelle che la commessa ha già (stesso nome) non vengono duplicate; dopo puoi cambiarle una per una.
- **Salva come modello**: le milestone di una commessa diventano un tuo modello (le scadenze diventano giorni lavorativi dall'inizio della commessa), da riusare nelle altre commesse; i modelli sono condivisi con il team. In **Da modello** apri un tuo modello per rinominarlo, cambiare milestone e giorni, o eliminarlo; un modello pronto lo puoi **copiare e modificare**.

**Attività e milestone ai collaboratori (Telegram)**
- In **chi se ne occupa** (To Do) e **chi la esegue** (Milestone) puoi scegliere un collega del team o un **collaboratore abilitato sulla commessa** (quelli con l'aeroplanino hanno collegato Telegram). Puoi anche scriverne il nome.
- Il collaboratore la riceve subito su Telegram, con il pulsante **✅ Fatto**; poi riceve i promemoria (il giorno prima, il giorno stesso e quando è in ritardo — per i To Do serve una data) e un avviso se la scadenza cambia.
- Quando tocca **✅ Fatto**, l'attività o la milestone risulta fatta, nel diario compare la riga "segnata da … su Telegram" e tu ricevi l'avviso (notifica dell'app e Telegram).
- Il collaboratore può anche chiedere al bot "cosa devo ancora fare?": risponde con le attività e le milestone aperte della commessa.
- Se il collaboratore non ha ancora collegato Telegram, l'attività è sua ma non riceve avvisi.

**Costi e margini**
- Nella sezione **Costi** della commessa:
  - **Preventivo**: l'importo concordato con il cliente;
  - **Manodopera**: una **tariffa standard** (€/ora) e, se serve, una tariffa per ogni persona. Le ore sono quelle scritte nel diario;
  - **Materiali**: il prezzo unitario di ogni materiale usato (per metro, pezzo, …);
  - **Altre spese**: noleggi, trasferte, smaltimenti, con importo e descrizione.
- Tariffe e prezzi valgono per **tutte le commesse** dei tuoi clienti: li scrivi una volta sola.
- In alto vedi costi, preventivo, **margine** e la barra di quanto preventivo hai già consumato (arancione dall'80%, rossa oltre il 100%). Ore o materiali senza prezzo non vengono stimati: sono indicati a parte come "non conteggiati".
- Il riquadro **Costi** nella riga di informazioni mostra il totale e la percentuale del preventivo.
- Quando una commessa arriva all'**80%** e quando **supera** il preventivo ricevi un avviso su Telegram, una sola volta per soglia.
- Puoi chiedere i numeri anche alla chat della commessa ("quanto margine mi resta?") o all'agente Cerca. I collaboratori su Telegram non vedono mai costi e margini.

**Riepilogo cantieri del lunedì**
- Con il verticale artigiano trovi già nelle **Azioni** il **Riepilogo cantieri**: ogni lunedì alle 8 ti arriva su Telegram la settimana passata (ore per persona e per commessa, materiali, problemi, situazione dei preventivi), le commesse in corso ferme da più di 7 giorni e le attività da fare in settimana.
- Puoi metterlo in pausa, eseguirlo subito o eliminarlo come ogni altra azione; se lo elimini non viene ricreato.

## Report di lavoro
<!-- id: report-lavoro · verticale: artigiano -->
L'agente **Report** genera report in Word, con lo spazio per le firme. **Che report fare lo capisce dal messaggio**: "SAL del bagno dei Rossi…", "fine lavori dai Bianchi…", "variante per i Verdi…", "intervento da…", "sopralluogo da…", "report della commessa…", o il nome di un tuo modello. Il tipo scelto con l'icona sotto il nome (accanto c'è scritto quale è) vale solo quando il messaggio non lo dice; se il messaggio chiede un altro tipo, la risposta lo segnala con "capito dal messaggio". I tipi sono:
- **Primo sopralluogo**: stato attuale, rilievi, lavori proposti, tempi e stima indicativa.
- **Rapporto di intervento**: un intervento (riparazione, manutenzione, installazione): orario, attività svolte, materiali, ore, esito.
- **Stato avanzamento lavori (SAL)**: percentuale di avanzamento, lavori del periodo, problemi, prossime attività e previsione di fine lavori. Ore, materiali, problemi e milestone del periodo (dall'ultimo SAL, o dall'inizio) li prende **dal diario della commessa** se non li detti.
- **Verbale di fine lavori**: lavori eseguiti, verifiche e collaudi, documentazione consegnata, garanzia; data di inizio e ore complessive dal diario.
- **Lavori extra / variante**: lavori aggiunti o cambiati, con tempi e costo indicativo, da far approvare al cliente.
- **Report di commessa**: non si detta, si costruisce **dal diario della commessa**. Sotto il nome scegli **cosa inserire** (riassunto stato commessa, lavori svolti, ore lavorate, problematiche, materiali, milestone, costi) e il **periodo** (tutta la commessa, ultimi 7 o 30 giorni, mese scorso, oppure dal… al… con le date). Poi scrivi di quale commessa si tratta, ad esempio "Report del bagno dei Rossi, metti in evidenza i ritardi".
  - Quello che scrivi nel messaggio (parti e periodo) vale più dei pulsanti: i pulsanti servono per quello che il messaggio non dice.
  - Basta anche scriverlo nel messaggio, qualunque tipo sia selezionato: "Fammi il report della commessa impianto elettrico di Luca D per la settimana corrente, con attività, materiali e ore per lavoratore". mAIPAL capisce che è un report di commessa e prende dal messaggio le parti e il periodo. Funziona anche da Telegram con `/report`.
  - Il periodo puoi anche scriverlo nel messaggio ("di ottobre", "dal 1 al 15/10", "ultime due settimane") quando hai scelto "Tutta la commessa".
  - Ore, problemi, materiali, milestone e costi sono copiati dal diario così come sono. Il riassunto e i lavori svolti li scrive mAIPAL solo da quello che c'è nel diario del periodo.
  - Se la commessa non è chiara mAIPAL ti chiede quale con i pulsanti. Non crea mai clienti o commesse nuovi.
  - Le parti che hai scelto restano nel report anche quando nel periodo non c'è niente: in quel caso è scritto.
  - Per un periodo i costi sono quelli di quei giorni; il preventivo e il margine compaiono solo per tutta la commessa.
- Oppure **carica un tuo modello** Word.
- Detta o scrivi com'è andato: l'esempio nella casella cambia con il tipo di report scelto.
- mAIPAL riconosce il cliente nella lista Clienti e la commessa; se non ci sono li crea. Se ci sono più clienti simili, te lo chiede.
- Il report si salva su Drive/OneDrive nella cartella del cliente e della commessa (mAIPAL/Clienti/cliente/commessa) e si scarica dalla chat.
- **Modificare il report**: nella stessa chat scrivi la correzione ("nei tempi metti 3 giorni"): mAIPAL crea la versione successiva cambiando solo quello che hai detto.
- **Nel diario della commessa** resta scritto ogni report generato (tipo, autore e un breve riassunto) e ogni sua nuova versione.
- Da Telegram: comando `/report`, poi scegli il tipo.

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
- La scheda commessa mostra Commessa, Via e Stato (preventivo, in corso, sospesa, chiusa); con la freccia vedi gli altri dati, i **contatti utili** della commessa (con **Aggiungi**) e i tasti Diario, Modifica, Elimina.
- Tocca la commessa per aprirne il **diario di commessa**.
- L'icona della **cartella** sulla commessa crea (o apre) su Drive/OneDrive la cartella mAIPAL/Clienti/cliente/commessa, dove finiscono anche report e foto del diario.
- Clienti e commesse si creano anche da soli quando detti un report o una voce di diario per un cliente nuovo.
- Puoi crearli anche dalla chat con l'agente **Salva**: "crea la commessa Bagno per Mario Rossi" la aggiunge sotto il cliente nella lista Clienti (stato «in corso», da oggi), non crea una lista nuova.
- **Eliminare** un cliente o una commessa cancella anche il diario (voci, foto), le attività e i costi, e non si può annullare. Per questo, toccando **Elimina**, ti arriva su **Telegram** un codice di 6 cifre da scrivere nell'app: vale 10 minuti, una volta sola, e dopo 5 tentativi sbagliati ne serve uno nuovo. Se Telegram non è collegato, l'app ti chiede di collegarlo (Impostazioni → Collegamenti → Telegram). I file su Drive/OneDrive restano.
- Dalla chat clienti e commesse non si eliminano: si usa il tasto Elimina nella lista.

## Documenti
<!-- id: documenti · path: /dashboard/documents · verticale: tutti -->
Documenti è la tua **base di conoscenza**: tutto quello che hai caricato con Salva (file, foto, scontrini) e che Cerca usa per rispondere.
- Vedi il totale, le categorie (lavoro, personale, finanza, salute…) e puoi filtrare per categoria.
- Cerca per nome, parola chiave o anteprima.
- Puoi rimuovere un documento.
- Per aggiungerne: Chat → Salva, con la graffetta (o condividendo un file dal telefono verso mAIPAL).
- **Sul telefono** i documenti sono in **cartelle**, una per argomento (Lavoro, Ricevute, Finanza…), due per riga: le più piene in alto, ognuna con il colore del suo argomento. Dentro ci sono i file e anche le **informazioni registrate** con Salva (segnate **Info**).
  - In alto, sempre visibili anche scorrendo: quanti **documenti** (e quante sono info), quanti **caratteri** e quante **categorie**.
  - Dalla cartella spuntano gli ultimi documenti, e i gesti sono quelli dei To-Do: col dito sopra escono a ventaglio; **scorri in su** sopra i documenti e restano alzati; allora scorrendo in orizzontale li sfogli tutti (dopo l'ultimo ricomincia dal primo), toccandone uno apri la sua scheda, e scorrendo in giù rientrano. La pagina scorre trascinando sulla parte bassa delle cartelle (nome e numero) o negli spazi tra una e l'altra.
  - **Tocca** la cartella per l'elenco dei suoi documenti, dal più recente; tocca un documento per la sua scheda (argomento, parole chiave, anteprima, **Apri su Drive**, **Elimina**). Con la freccia in alto (o il tasto indietro) torni alle cartelle.
  - Il **+** apre la chat con **Salva** per aggiungere un documento: l'argomento lo sceglie mAIPAL.

## Azioni
<!-- id: azioni · path: /dashboard/azioni · verticale: tutti -->
Le azioni programmate sono comandi che mAIPAL esegue da solo, con la cadenza che scegli, finché non le fermi.
- **Crearle**: dalla chat con l'agente **Azioni** ("Ogni lunedì alle 8 mandami su Telegram i task della settimana", "Ogni venerdì all'una di notte svuota gli iscritti della lista Lezioni Pilates"). Prima di attivarla, mAIPAL ti mostra cosa farà.
- **Nella sezione**: una casella per azione, con il titolo e sotto quando si ripete. Il **pallino** a sinistra la attiva o la mette in pausa. Toccando la casella si apre la sua scheda: cosa fa, la prossima esecuzione, l'ultimo risultato, **Esegui ora** (senza cambiare la programmazione) ed elimina.
- Da Telegram: `/azione <comando>` per crearne una, `/azioni` per l'elenco.
- Per gli artigiani è già pronta l'azione **Riepilogo cantieri** (ogni lunedì alle 8 su Telegram): vedi Diario di commessa.

## Fitness
<!-- id: fitness · path: /dashboard/fitness · verticale: fitness -->
La sezione Fitness (per istruttori e studi) ha quattro parti: Lezioni, Esercizi, Attrezzi e Clienti. Scegliendo il verticale Fitness trovi già pronti gli esercizi di base del funzionale, gli attrezzi di partenza e il tipo di lezione **Funzionale**.
- **Lezioni**: tocca **Crea lezione** (oppure chiedila in chat all'agente **Lezioni**), scegli il tipo e scrivi la richiesta, es. "lezione per 10 persone, livello medio, allenamento gambe". mAIPAL unisce la richiesta alle regole del tipo e compone la lezione in tre parti (inizio, parte centrale, fine), con serie, secondi o ripetizioni di ogni esercizio, la durata totale e gli attrezzi da preparare. Nella richiesta puoi dire partecipanti, livello, parti del corpo, durata, "a tempo" o "a ripetizioni"; quello che non dici lo prende dalle regole del tipo.
- **Come sceglie gli esercizi**: usa solo esercizi del tuo catalogo, del livello giusto (una lezione di livello medio usa esercizi di livello basso e medio) e delle parti del corpo chieste; rispetta i minimi e i massimi di ogni esercizio e i minuti di ogni parte. Un esercizio entra solo se gli attrezzi bastano per tutti insieme (partecipanti × pezzi a persona): quelli esclusi per questo sono elencati nella lezione.
- **Preferite ed eliminare**: la stella su una lezione la mette tra le **preferite** (in cima alla lista; con il filtro **Preferite** vedi solo quelle); il cestino la elimina.
- **Modificare una lezione**: toccala per aprirla; puoi rinominarla, cambiare le serie con − e +, togliere un esercizio (×) o aggiungerne uno a una parte (+), poi **Salva**: la durata viene ricalcolata.
- **Regole**: dal pulsante **Regole** gestisci i tipi di lezione. Per ognuno: durata (es. 40 minuti), minuti e tipo di inizio e fine (stretching o riscaldamento, es. 5 minuti di stretching all'inizio e alla fine), pausa tra le serie, partecipanti e livello se non detti, esercizi a tempo, a ripetizioni o misti, e altre regole a testo libero. Sotto ci sono le regole valide per tutte le lezioni dello studio.
- **Esercizi**: il catalogo, con la ricerca e i filtri su una riga che scorre (tipo, parte del corpo, livello, attrezzo). Con il **+** aggiungi i tuoi esercizi: parte del corpo, livello, attrezzo e pezzi per persona, se si fa a tempo (secondi e serie minimi e massimi) e/o a ripetizioni, descrizione, note e link a un video. Puoi modificare o eliminare anche quelli di base.
- **Attrezzi**: gli attrezzi dello studio con la quantità; cambiala con − e +, aggiungine di nuovi (se esiste già, la quantità si somma) o tocca il nome per rinominarlo o eliminarlo.
- **Clienti**: i tuoi clienti con abbonamento (es. mensile, 10 lezioni) e scadenza del certificato medico.

## Impostazioni
<!-- id: impostazioni · path: /dashboard/settings · verticale: tutti -->
Dalle Impostazioni (popup del profilo → Impostazioni, o dal menu) gestisci:
- **Profilo**: foto, professione, settore, ambito di utilizzo (lavoro, vita privata, tempo libero), interessi, tono delle risposte, indirizzi di casa e lavoro, orario delle news e del riepilogo del mattino. Ricorda di toccare **Salva profilo**.
- **Verticale**: il tuo settore (Veterinario, Fitness, Artigiano); quello scelto è evidenziato con la spunta. Cambia gli agenti e le sezioni dedicate.
- **Google Workspace**: collega Drive (cartella mAIPAL per file e allegati) e Calendar (eventi dai task).
- **Microsoft**: collega OneDrive e Outlook.
- **Dove salvo file ed eventi**: se hai collegato entrambi, scegli dove salvare i file e dove mettere gli eventi.
- **Telegram**: collega il bot (vedi "Telegram").
- **Orologio**: collega il Galaxy Watch (vedi "Orologio").
- **Notifiche**: gli avvisi di mAIPAL su questo dispositivo, anche con l'app chiusa (vedi "Notifiche").
- **Team**: unisciti a un team con il codice ricevuto dall'amministratore, per condividere task e liste.
- **Amministrazione** (solo amministratori): accessi e utenti. I team si creano e si gestiscono in **Team**.

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

## Notifiche
<!-- id: notifiche · verticale: tutti -->
mAIPAL può mandarti le notifiche direttamente sul telefono o sul computer, anche con l'app chiusa.
- **Cosa arriva**: i **promemoria dei task** e, per gli artigiani, le **voci scritte dai collaboratori** nel diario delle commesse (testo, ore, problemi o foto) e le attività o milestone che segnano come fatte. Toccando la notifica si apre la pagina giusta.
- **Attivarle**: Impostazioni → **Notifiche** → **Attiva su questo dispositivo**, poi consenti le notifiche quando il telefono lo chiede. Ogni dispositivo si attiva per conto suo; con **Manda una prova** controlli che arrivino, con **Disattiva** le spegni.
- **iPhone**: le notifiche arrivano solo dall'app aggiunta alla schermata Home (Safari → Condividi → Aggiungi alla schermata Home) e con iOS 16.4 o successivo.
- **Non arriva una notifica?** In Impostazioni → Notifiche, sotto **Ultima notifica**, vedi l'ultima mandata e com'è andata: a quanti dispositivi è arrivata, "nessun dispositivo con le notifiche attive" (attivale su quel dispositivo), un dispositivo non più iscritto (riattivale lì) o l'errore del servizio di notifiche. Se risulta arrivata ma non la vedi, controlla che le notifiche di mAIPAL (o del browser) siano permesse nelle impostazioni del telefono e che non sia attiva la modalità Non disturbare / Full immersion.
- Se le hai bloccate per errore, riattivale dalle impostazioni del browser o del telefono.
- Telegram, se collegato, continua a ricevere i suoi avvisi come prima.

## Team e condivisione
<!-- id: team · verticale: tutti -->
- Entri in un team con il codice che ti dà l'amministratore (Impostazioni → Team).
- In Impostazioni → **Team** vedi il tuo team: il nome, il numero di membri e chi ne fa parte.
- L'amministratore, sempre in **Team**, crea un nuovo team con il **+** nel cerchio e da ogni scheda cambia il nome, copia o rigenera il codice, invita o toglie le persone.
- Puoi **condividere o assegnare task** (dal dettaglio del task), **condividere liste** (icona di condivisione della lista) e **condividere informazioni** salvate scrivendo `@nome` o `@team` nel messaggio.
- Gli artigiani vedono i colleghi del team anche nelle ore del diario di commessa.

## App sul telefono
<!-- id: app-telefono · verticale: tutti -->
- **Installare l'app**: popup del profilo → **Installa l'app** (su iPhone: Condividi → Aggiungi a schermata Home). Si apre a schermo intero come un'app.
- **Scorciatoie**: tenendo premuta l'icona dell'app trovi Nuova nota, Nuovo task e Cerca.
- **Condividere verso mAIPAL**: da un'altra app (foto, file, link) scegli mAIPAL in "Condividi": si apre la chat con il contenuto pronto da salvare.
- **Tema**: chiaro o scuro dal popup del profilo (sole / luna).
- **Microfono**: nel popup del profilo, sotto il tema, scegli se il tasto dei vocali sta a sinistra o a destra della barra di scrittura. Vale su quel dispositivo.
- **Schede dal basso** (menu "+" della chat, guida Help, collaboratori…): per chiuderle trascina verso il basso la stanghetta in alto (o la scheda stessa quando sei in cima), oppure tocca la stanghetta o fuori dalla scheda.

## Collaboratori su Telegram
<!-- id: collaboratori · verticale: artigiano -->
I collaboratori sono persone esterne (operai, subappaltatori) che usano **solo Telegram**: scrivono nel diario delle commesse che abiliti e chiedono informazioni su quelle commesse. Non hanno accesso all'app.
- **Dove**: Impostazioni → **Collaboratori** (per ora solo per l'amministratore).
- **Nuovo collaboratore**: nome e cognome (obbligatori), cellulare, email (facoltativa), ruolo, azienda e le commesse da abilitare. Basta il cellulare per mandare l'invito: per i numeri italiani il +39 non serve, per un numero estero scrivi il prefisso (es. +41 …). Le commesse sono raggruppate per cliente: il pallino del cliente abilita (o toglie) tutte le sue commesse insieme, la freccia lo apre per sceglierle una per una (il trattino nel pallino indica che ne hai scelte solo alcune). Con **Invita** ottieni il codice e il messaggio di invito: **Invia su WhatsApp** apre WhatsApp con il messaggio già scritto (link e codice), oppure **Copia messaggio**. Il codice vale 7 giorni e si usa una volta sola.
- **Collegamento**: il collaboratore apre il link su Telegram e preme Avvia (oppure scrive `/start codice`). Se hai indicato il telefono, gli viene chiesto di condividere il suo numero, che deve corrispondere. Quando si collega ricevi un avviso su Telegram.
- **Cosa può fare**: scrivere cosa hanno fatto (anche a voce o con le foto) e fare domande, solo sulle sue commesse abilitate e non chiuse. Se ne ha più di una, nomina il cliente o i lavori oppure sceglie la commessa dai pulsanti. Sotto ogni voce salvata c'è **Annulla**, valido 10 minuti.
- **Dati del cliente**: telefono ed email del cliente non compaiono nelle risposte, a meno che tu non lo permetta nella scheda del collaboratore.
- **Nel diario** le sue voci hanno il suo nome e l'azienda. Se segnala un problema ti arriva un avviso su Telegram.
- **Promemoria**: dal lunedì al venerdì alle 18:00, se non ha scritto nulla, il bot gli chiede cosa hanno fatto oggi (se ha ancora il tempo aperto in cantiere, gli ricorda di chiuderlo).
- **Il messaggio del giorno, fissato**: ogni mattina alle 6, se quel giorno ha qualcosa in programma, il collaboratore riceve su Telegram il messaggio **📋 Oggi**, fissato in cima alla chat: commessa per commessa, con l'indirizzo del cantiere (toccandolo si apre la mappa), le **attività** e le **milestone** affidate a lui per oggi e i **materiali da portare** oggi, ciascuno con il suo pulsante ✅. Durante il giorno il messaggio si aggiorna da solo: le cose fatte appaiono barrate, quelle aggiunte per oggi compaiono. Il giorno dopo viene sostituito; un giorno senza niente in programma non arriva nessun messaggio. Contiene già i materiali, quindi il promemoria dei materiali delle 7 non viene ripetuto (quello delle 19.30 della sera prima sì).
- **Presenze in cantiere**: sotto la chat il collaboratore ha il pulsante **📍 Sono arrivato in cantiere**; quando lavora diventa **📍 Ho finito**. Il pulsante manda la posizione del telefono: all'arrivo avvia il conteggio (sulla commessa più vicina, oppure gli chiede quale), alla fine scrive nel diario la voce "In cantiere dalle 8:00 alle 12:30" con le sue ore, arrotondate alla mezz'ora: oltre l'ultima mezz'ora, più di 15 minuti arrotondano per eccesso, fino a 15 per difetto (1 h 10 → 1 h, 1 h 20 → 1,5 h, 1 h 50 → 2 h). Può anche scrivere "sono arrivato" / "ho finito", con l'orario se se n'è dimenticato ("ho finito alle 17:30"), ma così la posizione non viene registrata. Alla fine può togliere una pausa (30 minuti o 1 ora).
- **Posizione**: viene salvata solo nei due momenti in cui tocca 📍 (non viene seguito). Nel diario vedi a che distanza dal cantiere erano l'inizio e la fine (toccandola si apre la mappa); se supera i 300 m la distanza è evidenziata e ricevi una notifica. In alto nel diario, **In cantiere ora** mostra chi sta lavorando e da che ora.
- **Posizione del cantiere**: la trovo dall'indirizzo del cantiere; se è sbagliata, nel diario tocca il **pallino sulla mappa** e poi l'icona della **posizione** → **Sono in cantiere: usa questa posizione** (quando sei sul posto) oppure **Ritrova dall'indirizzo**. Se la posizione non c'è ancora (niente mappa), la imposti dalla voce **Cantiere** nella barra in alto.
- **Fine dimenticata**: dopo 14 ore senza fine il tempo si chiude senza contare le ore; il collaboratore e tu ricevete un avviso, e le ore si possono scrivere nel diario.
- **Dalla commessa**: nel diario della commessa la voce **Collaboratori** in alto mostra quanti sono abilitati; toccandola li abiliti o disabiliti con il pallino.
- **Gestione**: dalla scheda del collaboratore puoi modificarlo, mandare un nuovo codice (anche per collegare un altro telefono), sospenderlo o eliminarlo. Quello che ha già scritto resta nel diario. Quando una commessa viene chiusa, l'accesso dei collaboratori a quella commessa si chiude da solo.
