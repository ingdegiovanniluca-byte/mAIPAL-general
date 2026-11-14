import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { pushSupported, currentPushSubscription, enablePush, disablePush, isIos, isStandalone, pushKeyMatches } from "@/lib/pwa";
import IosSwitch from "@/components/IosSwitch";

/* Impostazioni > Notifiche: first the app's notifications on THIS device (a switch: each device by
   itself), then the list of what mAIPAL can send - each kind with its switch and where it goes:
   in the app, on Telegram or both. */
const CHANNELS = [["app", "App"], ["telegram", "Telegram"], ["both", "Entrambi"]];

export default function NotificationsPanel() {
  const [state, setState] = useState("checking");   // checking | unsupported | ios_home | denied | off | on
  const [busy, setBusy] = useState(false);
  const keyRef = useRef(null);                       // the server's public key, read before the tap (iPhone: see enablePush)
  const [kinds, setKinds] = useState(null);
  const [tgLinked, setTgLinked] = useState(false);

  const check = async () => {
    if (!pushSupported()) { setState(isIos() && !isStandalone() ? "ios_home" : "unsupported"); return; }
    if (Notification.permission === "denied") { setState("denied"); return; }
    try { keyRef.current = (await api.get("/push/key")).data.public_key; } catch { /* read again on the tap */ }
    const sub = await currentPushSubscription();
    const old = !!(sub && keyRef.current && pushKeyMatches(sub, keyRef.current) === false);
    let on = false;
    try { on = !!(sub && (await api.post("/push/status", { endpoint: sub.endpoint })).data.subscribed); } catch { /* off */ }
    setState(on && !old ? "on" : "off");
  };
  const loadKinds = () => api.get("/notify/prefs").then((r) => { setKinds(r.data.kinds); setTgLinked(!!r.data.telegram_linked); }).catch(() => setKinds([]));
  useEffect(() => { check(); loadKinds(); }, []);

  const turnOn = async () => {
    setBusy(true);
    try {
      const key = keyRef.current || (await api.get("/push/key")).data.public_key;
      const sub = await enablePush(key);
      await api.post("/push/subscribe", { subscription: sub.toJSON() });
      setState("on");
    } catch (e) {
      if (e.message === "denied") setState("denied");
      else if (e.message === "dismissed") toast("Notifiche non attivate: riprova e scegli «Consenti».");
      else toast.error(e.response?.data?.detail || `Non sono riuscito ad attivare le notifiche${isIos() ? " (iPhone: serve iOS 16.4 o successivo, con mAIPAL aperta dalla schermata Home)" : ""}`);
    } finally { setBusy(false); }
  };
  const turnOff = async () => {
    setBusy(true);
    try {
      const endpoint = await disablePush();
      if (endpoint) await api.post("/push/unsubscribe", { endpoint });
      setState("off");
    } catch { toast.error("Errore"); } finally { setBusy(false); }
  };
  const test = async () => {
    try { await api.post("/push/test"); toast.success("Notifica di prova inviata"); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const setKind = async (key, body) => {
    const prev = kinds;
    setKinds((ks) => ks.map((k) => (k.key === key ? { ...k, ...body } : k)));
    try { await api.put(`/notify/prefs/${key}`, body); }
    catch { setKinds(prev); toast.error("Non sono riuscito a salvarlo"); }
  };

  const deviceNote = {
    ios_home: "Su iPhone le notifiche arrivano solo dall'app sulla schermata Home: in Safari tocca Condividi → Aggiungi alla schermata Home e apri mAIPAL da lì.",
    unsupported: "Questo browser non riceve notifiche: prova con Chrome, Edge o Firefox, oppure dall'app installata.",
    denied: "Le notifiche di mAIPAL sono bloccate su questo dispositivo: riattivale dalle impostazioni del telefono o del browser.",
  }[state];

  return (
    <div data-testid="notifications-panel">
      {/* this device */}
      <div className="flex items-center gap-3 py-1">
        <div className="flex-1 min-w-0">
          <div className="text-[15px] text-white">Notifiche su questo dispositivo</div>
          <div className="text-[12px] text-white/55">Anche con l'app chiusa. Ogni dispositivo si attiva da sé.</div>
        </div>
        {state === "checking" ? <span className="text-[12px] text-white/50">…</span> : (
          <IosSwitch checked={state === "on"} disabled={busy || !!deviceNote} onChange={(v) => (v ? turnOn() : turnOff())}
            label="Notifiche su questo dispositivo" testid="push-switch" />
        )}
      </div>
      {deviceNote && <p className="mt-1 text-[12px] text-white/65" data-testid={`push-${state}`}>{deviceNote}</p>}
      {state === "on" && (
        <button type="button" onClick={test} className="mt-1 text-[12px] text-white/70 underline underline-offset-2" data-testid="push-test">Manda una prova</button>
      )}

      {/* what mAIPAL can send, and where */}
      <div className="mt-6 text-[12px] font-semibold uppercase tracking-[0.12em] text-white/60">Cosa ti mando</div>
      {!kinds ? <div className="py-3 text-[12px] text-white/50">…</div> : (
        <div className="mt-1" data-testid="notify-kinds">
          {kinds.map((k) => (
            <div key={k.key} className="py-3 border-b border-white/[0.1] last:border-0" data-testid={`notify-${k.key}`}>
              <div className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-[15px] text-white">{k.label}</div>
                  <div className="text-[12px] leading-[16px] text-white/55">{k.help}</div>
                </div>
                <IosSwitch checked={k.on} onChange={(v) => setKind(k.key, { on: v })} label={k.label} testid={`notify-${k.key}-switch`} />
              </div>
              {k.on && (
                <div className="mt-2 inline-flex rounded-full bg-white/[0.12] p-[3px]" role="radiogroup" aria-label={`Dove: ${k.label}`}>
                  {CHANNELS.map(([c, label]) => {
                    const off = c !== "app" && !tgLinked;
                    return (
                      <button key={c} type="button" role="radio" aria-checked={k.channel === c} disabled={off}
                        title={off ? "Collega Telegram in Impostazioni per riceverle lì" : undefined}
                        onClick={() => setKind(k.key, { channel: c })} data-testid={`notify-${k.key}-${c}`}
                        className={`px-3 py-1 rounded-full text-[12px] transition-colors disabled:opacity-35 ${k.channel === c ? "bg-white text-[#403A3C] font-semibold" : "text-white/80"}`}>
                        {label}</button>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {kinds && !tgLinked && <p className="mt-2 text-[12px] text-white/55">Telegram non è collegato: per ora arrivano solo nell'app.</p>}
    </div>
  );
}
