import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, BellOff, Loader2, NotebookPen, AlarmClock } from "lucide-react";
import { api } from "@/lib/api";
import { pushSupported, currentPushSubscription, enablePush, disablePush, isIos, isStandalone } from "@/lib/pwa";

/* Impostazioni > Notifiche: the app's notifications on THIS device, also with mAIPAL closed.
   Only two kinds: what external collaborators write in a commessa's diary, and the tasks'
   reminders. Each device (phone, computer) is turned on by itself. */
export default function NotificationsPanel() {
  const [state, setState] = useState("checking");   // checking | unsupported | ios_home | denied | off | on
  const [busy, setBusy] = useState(false);

  const check = async () => {
    if (!pushSupported()) { setState(isIos() && !isStandalone() ? "ios_home" : "unsupported"); return; }
    if (Notification.permission === "denied") { setState("denied"); return; }
    const sub = await currentPushSubscription();
    if (!sub) { setState("off"); return; }
    try { setState((await api.post("/push/status", { endpoint: sub.endpoint })).data.subscribed ? "on" : "off"); }
    catch { setState("off"); }
  };
  useEffect(() => { check(); }, []);

  const turnOn = async () => {
    setBusy(true);
    try {
      const key = (await api.get("/push/key")).data.public_key;
      const sub = await enablePush(key);
      await api.post("/push/subscribe", { subscription: sub.toJSON() });
      setState("on");
      toast.success("Notifiche attive su questo dispositivo");
    } catch (e) {
      if (e.message === "denied") setState("denied");
      else if (e.message !== "dismissed") toast.error(e.response?.data?.detail || "Non sono riuscito ad attivare le notifiche");
    } finally { setBusy(false); }
  };
  const turnOff = async () => {
    setBusy(true);
    try {
      const endpoint = await disablePush();
      if (endpoint) await api.post("/push/unsubscribe", { endpoint });
      setState("off");
      toast.success("Notifiche spente su questo dispositivo");
    } catch { toast.error("Errore"); } finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true);
    try { await api.post("/push/test"); toast.success("Notifica di prova inviata"); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); } finally { setBusy(false); }
  };

  return (
    <div data-testid="notifications-panel">
      <div className="space-y-2.5 mb-4">
        <div className="flex items-start gap-3 text-sm text-white/85"><NotebookPen size={16} className="shrink-0 mt-0.5" /> Le voci scritte dai collaboratori nel diario delle commesse</div>
        <div className="flex items-start gap-3 text-sm text-white/85"><AlarmClock size={16} className="shrink-0 mt-0.5" /> I promemoria dei task</div>
      </div>
      {state === "checking" && <div className="kicker">controllo…</div>}
      {state === "ios_home" && (
        <p className="text-sm text-white/70" data-testid="push-ios-home">
          Su iPhone le notifiche arrivano solo dall'app sulla schermata Home: in Safari tocca Condividi → <b>Aggiungi alla schermata Home</b>, apri mAIPAL da lì e torna qui.
        </p>
      )}
      {state === "unsupported" && <p className="text-sm text-white/70">Questo browser non riceve notifiche dalle app web. Prova con Chrome, Edge o Firefox, oppure dall'app installata.</p>}
      {state === "denied" && (
        <p className="text-sm text-white/70" data-testid="push-denied">
          Le notifiche di mAIPAL sono bloccate su questo dispositivo: riattivale dalle impostazioni del browser (icona del lucchetto accanto all'indirizzo) o del telefono, poi torna qui.
        </p>
      )}
      {state === "off" && (
        <button onClick={turnOn} disabled={busy} data-testid="push-enable" className="pill-btn inline-flex items-center gap-2 disabled:opacity-60">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Bell size={15} />} Attiva su questo dispositivo
        </button>
      )}
      {state === "on" && (
        <div>
          <div className="text-sm text-white flex items-center gap-2 mb-3" data-testid="push-on"><Bell size={15} /> Attive su questo dispositivo</div>
          <div className="flex flex-wrap gap-2">
            <button onClick={test} disabled={busy} data-testid="push-test" className="px-4 py-2 rounded-full text-sm bg-white/15 text-white disabled:opacity-60">Manda una prova</button>
            <button onClick={turnOff} disabled={busy} data-testid="push-disable" className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10 inline-flex items-center gap-1.5 disabled:opacity-60">
              <BellOff size={14} /> Disattiva
            </button>
          </div>
        </div>
      )}
      <p className="text-xs text-white/50 mt-4">Ogni dispositivo si attiva per conto suo. Telegram, se collegato, continua a ricevere i suoi avvisi come prima.</p>
    </div>
  );
}
