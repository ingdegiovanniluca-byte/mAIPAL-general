import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { pushSupported, currentPushSubscription, enablePush, isIos, isStandalone, pushKeyMatches } from "@/lib/pwa";
import IosSwitch from "@/components/IosSwitch";

/* Impostazioni > Notifiche: the list of what mAIPAL can send - each kind with its switch and where it
   goes: in the app, on Telegram or both. No separate switch for the device: the first time a kind is
   turned on or sent to the app from here, this device is subscribed (the phone asks the permission
   right from that tap, as the iPhone wants); afterwards the app keeps it up to date by itself. */
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
      toast.success("Notifiche dell'app attive su questo dispositivo");
    } catch (e) {
      if (e.message === "denied") setState("denied");
      else if (e.message === "dismissed") toast("Notifiche non attivate: riprova e scegli «Consenti».");
      else toast.error(e.response?.data?.detail || `Non sono riuscito ad attivare le notifiche${isIos() ? " (iPhone: serve iOS 16.4 o successivo, con mAIPAL aperta dalla schermata Home)" : ""}`);
    } finally { setBusy(false); }
  };
  // a choice that needs the app's notifications: this device too, if it isn't yet (and can be)
  const ensureDevice = (k, body) => {
    const on = body.on ?? k.on, channel = body.channel ?? k.channel;
    if (on && channel !== "telegram" && state === "off" && !busy) turnOn();
  };
  const setKind = async (key, body) => {
    const k = kinds.find((x) => x.key === key);
    if (k) ensureDevice(k, body);
    const prev = kinds;
    setKinds((ks) => ks.map((k) => (k.key === key ? { ...k, ...body } : k)));
    try { await api.put(`/notify/prefs/${key}`, body); }
    catch { setKinds(prev); toast.error("Non sono riuscito a salvarlo"); }
  };

  const deviceNote = {
    ios_home: "Su iPhone le notifiche dell'app arrivano solo dall'app sulla schermata Home: in Safari tocca Condividi → Aggiungi alla schermata Home e apri mAIPAL da lì.",
    denied: "Le notifiche dell'app sono bloccate su questo dispositivo: riattivale dalle impostazioni del telefono o del browser.",
  }[state];

  return (
    <div data-testid="notifications-panel">
      {/* what mAIPAL can send, and where */}
      {!kinds ? <div className="py-3 text-[12px] text-white/50">…</div> : (
        <div data-testid="notify-kinds">
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
      {deviceNote && <p className="mt-2 text-[12px] text-white/55" data-testid={`push-${state}`}>{deviceNote}</p>}
    </div>
  );
}
