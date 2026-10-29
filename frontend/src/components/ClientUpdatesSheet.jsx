import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Copy, Loader2, MessageCircle, Send, Eye } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* The client's weekly progress on Telegram, from the commessa's diary: the invitation (link and
   code, sent on WhatsApp like a collaborator's), on / off for this commessa, what they would get
   now and "send it now". The message never has hours, costs, names or problems. */

const when = (iso) => (iso ? new Date(iso).toLocaleDateString("it-IT", { day: "numeric", month: "short" }) : "");

function Dot({ on }) {
  return (
    <span className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
      {on && <Check size={12} strokeWidth={2.8} />}
    </span>
  );
}

export default function ClientUpdatesSheet({ commessa, onClose, onChanged }) {
  const [st, setSt] = useState(null);
  const [phone, setPhone] = useState("");
  const [invite, setInvite] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const base = `/jobs/commesse/${commessa.id}/client-updates`;
  const load = async () => {
    try { const r = await api.get(base); setSt(r.data); setPhone(r.data.phone || ""); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); onClose(); }
  };
  useEffect(() => { load(); }, [commessa.id]);
  const run = async (key, fn) => {
    setBusy(key);
    try { await fn(); } catch (e) { toast.error(e.response?.data?.detail || "Errore"); } finally { setBusy(""); }
  };
  const doInvite = () => run("invite", async () => { const r = await api.post(`${base}/invite`, { phone }); setSt(r.data); setInvite(r.data.invite); });
  const toggle = () => run("toggle", async () => { const r = await api.patch(base, { enabled: !st.enabled }); setSt(r.data); onChanged?.(); });
  const doPreview = () => run("preview", async () => { const r = await api.post(`${base}/preview`); setPreview(r.data.text || ""); });
  const send = () => run("send", async () => { const r = await api.post(`${base}/send`); setPreview(r.data.text); toast.success("Avanzamento inviato al cliente"); load(); });
  const unlink = () => toast(`Scollegare ${st.client_name}? Non riceverà più gli aggiornamenti.`, {
    action: { label: "Scollega", onClick: () => run("unlink", async () => { const r = await api.delete(`${base}/link`); setSt(r.data); setInvite(null); }) },
    cancel: { label: "Annulla", onClick: () => {} }, duration: 7000,
  });
  const copy = async () => {
    try { await navigator.clipboard.writeText(invite.message); toast.success("Messaggio copiato"); }
    catch { toast.error("Copia non riuscita: seleziona il testo e copialo"); }
  };
  const linked = st?.status === "active" || st?.status === "stopped";
  const pill = "inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm disabled:opacity-50";
  return (
    <GlassBottomSheet onClose={onClose} testid="client-updates-sheet" className="max-h-[88vh] md:left-1/2 md:right-auto md:w-[500px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· Avanzamento al cliente</div>
      <div className="text-lg font-semibold text-white mt-1">{commessa.client_name} · {commessa.title}</div>
      {!st ? <div className="kicker mt-4">caricamento…</div> : (
        <div className="mt-3 space-y-4">
          <p className="text-[13px] text-white/70 leading-snug">
            Ogni {st.day_label} alle {st.at} il cliente riceve su Telegram un breve messaggio con i lavori fatti nella settimana, le milestone
            completate e i prossimi lavori. Mai ore, costi, nomi o problemi. Tu ne ricevi una copia.
          </p>
          <div className="flex items-center gap-2 text-[13px] text-white" data-testid="client-updates-status">
            <span className="h-2 w-2 rounded-full" style={{ background: st.status === "active" ? "#8ED973" : st.status === "invited" ? "#F2C14E" : "rgba(255,255,255,0.4)" }} />
            {st.status === "active" ? `Collegato su Telegram${st.linked_at ? ` dal ${when(st.linked_at)}` : ""}`
              : st.status === "stopped" ? "Il cliente ha chiesto di non ricevere più gli aggiornamenti"
              : st.status === "invited" ? `Invito mandato: il link vale fino al ${when(st.code_expires_at)}`
              : "Non ancora collegato"}
          </div>
          {!linked && (
            <div className="space-y-2.5">
              <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Cellulare del cliente" inputMode="tel" data-testid="client-updates-phone"
                className="h-10 w-full rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none" />
              {!invite ? (
                <button type="button" onClick={doInvite} disabled={!!busy} data-testid="client-updates-invite" className={`${pill} bg-white text-[#403A3C] font-medium`}>
                  {busy === "invite" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} {st.status === "invited" ? "Nuovo invito" : "Prepara l'invito"}
                </button>
              ) : (
                <div className="space-y-2.5" data-testid="client-updates-invite-box">
                  <div className="text-xs text-white/70 whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-xl bg-white/[0.07] p-3">{invite.message}</div>
                  <div className="flex flex-wrap gap-2">
                    <a href={invite.whatsapp_url} target="_blank" rel="noreferrer" data-testid="client-updates-whatsapp" className={`${pill} bg-white text-[#403A3C] font-medium`}>
                      <MessageCircle size={14} /> Invia su WhatsApp
                    </a>
                    <button type="button" onClick={copy} className={`${pill} bg-white/15 text-white`}><Copy size={14} /> Copia messaggio</button>
                  </div>
                </div>
              )}
            </div>
          )}
          <button type="button" onClick={toggle} disabled={!!busy} aria-pressed={st.enabled} data-testid="client-updates-toggle"
            className="w-full flex items-start gap-3 text-left text-sm text-white disabled:opacity-60">
            <Dot on={st.enabled} />
            <span>Avanzamento settimanale per questa commessa
              <span className="block text-xs text-white/55">{st.enabled ? "Acceso: parte da solo quando il cliente è collegato." : "Spento: per questa commessa non parte niente."}</span>
            </span>
          </button>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={doPreview} disabled={!!busy} data-testid="client-updates-preview" className={`${pill} bg-white/15 text-white`}>
              {busy === "preview" ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />} Anteprima
            </button>
            {st.status === "active" && (
              <button type="button" onClick={send} disabled={!!busy} data-testid="client-updates-send" className={`${pill} bg-white text-[#403A3C] font-medium`}>
                {busy === "send" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Invia ora
              </button>
            )}
            {linked && <button type="button" onClick={unlink} disabled={!!busy} data-testid="client-updates-unlink" className={`${pill} text-white/70`}>Scollega</button>}
          </div>
          {preview !== null && (
            <div className="rounded-xl bg-white/[0.07] p-3 text-[13px] text-white/85 whitespace-pre-wrap" data-testid="client-updates-preview-text">
              {preview || "Questa settimana nel diario non ci sono lavori da raccontare: non partirebbe nessun messaggio."}
            </div>
          )}
          {st.last_sent_at && preview === null && (
            <div className="text-[11.5px] text-white/50" data-testid="client-updates-last">Ultimo invio il {when(st.last_sent_at)}</div>
          )}
        </div>
      )}
    </GlassBottomSheet>
  );
}
