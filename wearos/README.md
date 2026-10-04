# mAIPAL per Galaxy Watch (Wear OS)

App per orologi Wear OS 3+ (Galaxy Watch4 e successivi). Funziona da sola: parla con il
server mAIPAL via Wi-Fi/LTE dell'orologio o attraverso il telefono a cui è associato.

- **Home**: microfono al centro. Nel semicerchio sopra le sezioni (Chat, Task, To-Do,
  Liste), in quello sotto gli agenti (Cerca, Salva, Task, Diario, Azioni). Anche la
  ghiera o la corona cambiano agente.
- **Microfono**: il primo tocco registra, il secondo invia. Il vocale viene trascritto
  dal server e mandato all'agente scelto. Dalla risposta puoi continuare a parlare nella
  stessa conversazione. Le conversazioni compaiono anche nella cronologia dell'app.
- **Task / To-Do / Liste**: elenchi a scorrimento. Tocca il cerchio per segnare un task o
  un to-do come fatto.

## Collegare l'orologio

1. Apri mAIPAL sull'orologio: mostra un codice di 6 cifre (vale 10 minuti).
2. Sul telefono o sul PC apri mAIPAL › Impostazioni › Collegamenti › **Orologio**.
3. Scrivi il codice e premi **Collega**: l'orologio entra da solo nella home.

Dalla stessa schermata puoi scollegarlo. L'orologio torna alla schermata del codice.

## Installare l'APK sull'orologio

Serve `adb`, che fa parte degli Android SDK Platform-Tools:
https://developer.android.com/tools/releases/platform-tools

1. Sull'orologio: Impostazioni › Info sull'orologio › Info sul software. Tocca 7 volte
   **Versione software**: si attivano le Opzioni sviluppatore.
2. Impostazioni › Opzioni sviluppatore: attiva **Debug ADB** e **Debug wireless**.
   L'orologio e il PC devono essere sulla stessa rete Wi-Fi.
3. In Debug wireless tocca **Associa nuovo dispositivo**. Compaiono un indirizzo
   `IP:PORTA` e un codice. Dal PC:
   ```
   adb pair IP:PORTA        # inserisci il codice mostrato sull'orologio
   adb connect IP:PORTA2    # l'indirizzo mostrato nella schermata Debug wireless
   adb install -r maipal-watch.apk
   ```
4. Sull'orologio trovi **mAIPAL** tra le app. Al primo vocale chiede il permesso del
   microfono.

Se `adb install` risponde `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, l'APK è stato firmato
su un'altra macchina. Prima disinstalla la vecchia versione:
`adb uninstall it.maipal.watch`.

## Compilare

- **GitHub**: ogni push che tocca `wearos/` avvia l'azione **Wear OS APK**. L'APK si
  scarica dagli artifact del run. Da "Run workflow" puoi anche indicare un altro server.
- **Android Studio**: apri la cartella `wearos/` e premi Run con l'orologio collegato
  via adb.
- **Riga di comando** (JDK 17+ e Android SDK):
  ```
  cd wearos
  ./gradlew assembleDebug                               # server: https://maipal.it/general
  ./gradlew assembleDebug -PmaipalUrl=http://192.168.1.10:8000   # un server di prova
  ```
  L'APK è in `app/build/outputs/apk/debug/app-debug.apk`.

L'indirizzo del server si imposta in `gradle.properties` (`maipalUrl`), senza `/api`.
