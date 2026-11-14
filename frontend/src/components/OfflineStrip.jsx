import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { flushOutbox, onOutboxChange, pendingCount } from "@/lib/outbox";

/* With no signal: a small strip on top ("Senza rete · 2 voci in attesa"), and the diary's entries kept on
   the phone are sent by themselves - when the network comes back, when the app is opened again or comes
   back to the front, and every half a minute while it is open. */
export default function OfflineStrip() {
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine !== false);
  const [waiting, setWaiting] = useState(0);

  useEffect(() => {
    const flush = () => {
      if (navigator.onLine === false) return;
      flushOutbox().then((n) => { if (n) toast.success(n === 1 ? "Inviata la voce del diario salvata senza rete" : `Inviate ${n} voci del diario salvate senza rete`); });
    };
    const up = () => { setOnline(true); flush(); };
    const down = () => setOnline(false);
    const back = () => { if (document.visibilityState === "visible") flush(); };
    const failed = (ev) => toast.error(`Una voce salvata senza rete non è stata accettata: «${(ev.detail?.label || "").slice(0, 40)}» — ${ev.detail?.error || "errore"}`);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    document.addEventListener("visibilitychange", back);
    window.addEventListener("maipal-outbox-failed", failed);
    const off = onOutboxChange(setWaiting);
    pendingCount().then(setWaiting).catch(() => {});
    flush();
    const t = setInterval(flush, 30000);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("maipal-outbox-failed", failed);
      off();
      clearInterval(t);
    };
  }, []);

  if (online && !waiting) return null;
  const what = waiting ? `${waiting} ${waiting === 1 ? "voce" : "voci"} in attesa` : "";
  return (
    <div className="fixed left-1/2 -translate-x-1/2 z-[60] px-3 py-1 rounded-full text-[12px] text-white whitespace-nowrap top-[calc(env(safe-area-inset-top,0px)+70px)] min-[1100px]:top-[92px]"
      style={{ background: "rgba(58,32,48,0.82)", backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)" }}
      role="status" data-testid="offline-strip">
      {online ? `Invio in corso · ${what}` : `Senza rete${what ? ` · ${what}` : ""}`}
    </div>
  );
}
