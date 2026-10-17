import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Send, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* Deleting a client or a commessa of the Clienti list (and its diary): a 6-digit code arrives on
   Telegram and is typed here. Without Telegram linked, the sheet asks to link it.
   target: {collection_id, item_id, sub_id?}; url: the DELETE to call with the code. */
export default function DeleteWithCode({ title, target, url, onDone, onClose }) {
  const navigate = useNavigate();
  const [state, setState] = useState("asking");   // asking | sent | no_telegram | error
  const [info, setInfo] = useState(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    setState("asking"); setError(""); setCode("");
    try {
      setInfo((await api.post("/clienti/delete-code", target)).data);
      setState("sent");
    } catch (e) {
      setError(e.response?.data?.detail || "Non sono riuscito a mandare il codice");
      setState(e.response?.status === 409 ? "no_telegram" : "error");
    }
  };
  useEffect(() => { ask(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const confirm = async () => {
    const c = code.replace(/\D/g, "");
    if (c.length !== 6) { setError("Il codice ha 6 cifre"); return; }
    setBusy(true); setError("");
    try {
      await api.delete(url, { params: { code: c } });
      onDone();
    } catch (e) {
      setError(e.response?.data?.detail || "Eliminazione non riuscita");
      if (/scadut|troppe volte/i.test(e.response?.data?.detail || "")) setState("expired");
    } finally { setBusy(false); }
  };

  return (
    <GlassBottomSheet onClose={onClose} testid="delete-code-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[460px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-3">{title}</div>
      {state === "asking" && (
        <div className="flex items-center gap-2 text-sm text-white/70 py-3"><Loader2 size={15} className="animate-spin" /> Ti mando il codice su Telegram…</div>
      )}
      {state === "no_telegram" && (
        <div data-testid="delete-needs-telegram">
          <p className="text-sm text-white/80">{error}</p>
          <div className="flex justify-end gap-2 mt-5">
            <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
            <button onClick={() => { onClose(); navigate("/dashboard/settings?s=links"); }} data-testid="delete-link-telegram"
              className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium inline-flex items-center gap-1.5">
              <Send size={14} /> Collega Telegram
            </button>
          </div>
        </div>
      )}
      {state === "error" && (
        <div>
          <p className="text-sm text-white/80">{error}</p>
          <div className="flex justify-end gap-2 mt-5">
            <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
            <button onClick={ask} className="px-4 py-2 rounded-full text-sm bg-white/15 text-white">Riprova</button>
          </div>
        </div>
      )}
      {(state === "sent" || state === "expired") && info && (
        <div>
          <p className="text-sm text-white/80" data-testid="delete-code-what">
            Ti ho mandato su Telegram il codice per eliminare {info.what}. Insieme vengono cancellati il diario
            ({info.entries} {info.entries === 1 ? "voce" : "voci"}{info.photos ? `, ${info.photos} foto` : ""}), le attività e i costi:
            non si può annullare.
          </p>
          <input value={code} onChange={(e) => { setCode(e.target.value.replace(/\D/g, "").slice(0, 6)); setError(""); }}
            onKeyDown={(e) => e.key === "Enter" && confirm()} inputMode="numeric" autoComplete="one-time-code" placeholder="000000" autoFocus
            disabled={state === "expired"} data-testid="delete-code-input"
            className="mt-4 h-12 w-full rounded-xl bg-white/10 text-center font-mono-tight text-2xl tracking-[0.4em] text-white placeholder:text-white/25 outline-none disabled:opacity-50" />
          {error && <div className="mt-2 text-xs text-[#FFB4A8]" data-testid="delete-code-error">{error}</div>}
          <div className="flex items-center gap-2 mt-5">
            <button onClick={ask} data-testid="delete-code-resend" className="mr-auto px-3 py-2 rounded-full text-xs text-white/75 hover:bg-white/10">Mandami un nuovo codice</button>
            <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
            <button onClick={confirm} disabled={busy || state === "expired" || code.length !== 6} data-testid="delete-code-confirm"
              className="px-4 py-2 rounded-full text-sm bg-[#E8663F] text-white font-medium inline-flex items-center gap-1.5 disabled:opacity-50">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Elimina
            </button>
          </div>
        </div>
      )}
    </GlassBottomSheet>
  );
}
