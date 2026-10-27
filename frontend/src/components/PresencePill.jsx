import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, MapPin, Square } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* "📍 Sono in cantiere" / "Ho finito" for the app's user (the owner, a colleague), in a commessa's
   diary: the same presence as the collaborators' on Telegram - the phone's position when allowed,
   the time in between becomes their hours in the diary. At the end: the pauses and "how did it
   go?" (an entry of the diary). In the evening, when asked whether they are still there: yes, or
   the time they left. */

const hhmm = (iso) => new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
const nowHHMM = () => new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
const where = (m) => (m == null ? "senza posizione" : m <= 300 ? "in cantiere" : m < 1000 ? `a ${m} m dal cantiere` : `a ${(m / 1000).toFixed(1).replace(".", ",")} km dal cantiere`);
const duration = (min) => (min >= 60 ? `${Math.floor(min / 60)} h${min % 60 ? ` ${String(min % 60).padStart(2, "0")} min` : ""}` : `${min} min`);
const hours = (h) => String(h).replace(".", ",");

// the phone's position, if the user allows it (never waits more than a few seconds)
const position = () => new Promise((resolve) => {
  if (!navigator.geolocation) { resolve(null); return; }
  navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
    () => resolve(null), { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 });
});

function EndSheet({ end, onClose, onSaved }) {
  const [pause, setPause] = useState(0);
  const [hoursNow, setHoursNow] = useState(end.hours);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const pick = async (m) => {
    setPause(m);
    try {
      await api.post("/jobs/presence/pause", { log_id: end.log_id, minutes: m });
      setHoursNow(Math.max(0, Math.round(((end.minutes - m) / 60) * 2) / 2));
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a togliere la pausa"); }
  };
  const save = async () => {
    if (!note.trim()) { onClose(); return; }
    setBusy(true);
    try {
      await api.post("/jobs/logs", { text: note.trim(), commessa_id: end.commessa_id });
      toast.success("Scritto nel diario");
      onSaved();
      onClose();
    } catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a salvarlo"); }
    finally { setBusy(false); }
  };
  return (
    <GlassBottomSheet onClose={onClose} testid="presence-end-sheet" className="max-h-[86vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· Fine in cantiere</div>
      <div className="text-2xl font-bold text-white mt-1">{hours(hoursNow)} h nel diario</div>
      <div className="text-[13px] text-white/70 mt-1">«{end.commessa_title}» · {duration(end.minutes)}</div>
      <div className="kicker mt-5 mb-2">Hai fatto pause?</div>
      <div className="flex gap-2 flex-wrap">
        {[[0, "Nessuna"], [30, "− 30 min"], [60, "− 1 h"]].map(([m, label]) => (
          <button key={m} type="button" onClick={() => pick(m)} data-testid={`presence-pause-${m}`}
            className={`px-3.5 py-1.5 rounded-full text-xs ${pause === m ? "bg-white text-[#403A3C] font-semibold" : "bg-white/10 text-white"}`}>{label}</button>
        ))}
      </div>
      <div className="kicker mt-5 mb-2">Com'è andata oggi?</div>
      <textarea data-testid="presence-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3}
        placeholder="Cosa avete fatto, problemi, materiali… (va nel diario)"
        className="w-full rounded-2xl bg-white/10 px-4 py-3 text-sm text-white placeholder:text-white/45 outline-none resize-none" />
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={onClose} className="flex-1 py-3 rounded-full lg-glass text-white text-sm">Più tardi</button>
        <button type="button" onClick={save} disabled={busy} data-testid="presence-note-save"
          className="flex-1 py-3 rounded-full bg-white text-[#403A3C] text-sm font-semibold disabled:opacity-40">{busy ? "…" : note.trim() ? "Scrivi nel diario" : "Fatto"}</button>
      </div>
    </GlassBottomSheet>
  );
}

export default function PresencePill({ commessa, onChanged }) {
  const [open, setOpen] = useState(undefined);   // my open time on site (null: none; undefined: loading)
  const [busy, setBusy] = useState(false);
  const [end, setEnd] = useState(null);          // the end just made: pauses and the note
  const [leaving, setLeaving] = useState(false); // "no, I left": at what time
  const [leftAt, setLeftAt] = useState(nowHHMM());
  const load = async () => {
    try { setOpen((await api.get("/jobs/presence/me")).data.open || null); } catch { setOpen(null); }
  };
  useEffect(() => { load(); }, [commessa.id]);

  const start = async () => {
    setBusy(true);
    try {
      const pos = await position();
      const r = await api.post(`/jobs/commesse/${commessa.id}/presence/start`, pos || {});
      setOpen(r.data.open);
      toast.success(`🟢 Inizio alle ${hhmm(r.data.open.start_at)} su «${commessa.title}» (${where(r.data.open.start_m)})`);
      onChanged();
    } catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a segnarlo"); load(); }
    finally { setBusy(false); }
  };
  const stop = async (at) => {
    setBusy(true);
    try {
      const pos = at ? null : await position();
      const r = await api.post("/jobs/presence/stop", { ...(pos || {}), ...(at ? { at } : {}) });
      setOpen(null);
      setLeaving(false);
      setEnd(r.data);
      onChanged();
    } catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a segnarlo"); load(); }
    finally { setBusy(false); }
  };
  const still = async () => {
    try { await api.post("/jobs/presence/still"); toast.success("👍 Buon lavoro!"); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  if (open === undefined) return null;
  const here = open && open.commessa_id === commessa.id;
  const sheet = end && <EndSheet end={end} onClose={() => setEnd(null)} onSaved={onChanged} />;
  if (!open && commessa.stato === "chiusa") return sheet || null;
  return (
    <>
      {open?.late_asked ? (
        // the evening's question, answered here (also asked on Telegram and with a notification)
        <div className="mt-3 rounded-2xl lg-glass px-4 py-3 text-white" data-testid="presence-late">
          <div className="text-[14px] font-semibold">🕖 Sei ancora in cantiere?</div>
          <div className="text-[12px] text-white/70 mt-0.5">«{open.commessa_title}», dalle {hhmm(open.start_at)}</div>
          {!leaving ? (
            <div className="mt-2.5 flex gap-2">
              <button type="button" onClick={still} data-testid="presence-still" className="flex-1 py-2 rounded-full bg-white text-[#403A3C] text-[13px] font-semibold">Sì, sono qui</button>
              <button type="button" onClick={() => { setLeftAt(nowHHMM()); setLeaving(true); }} data-testid="presence-left"
                className="flex-1 py-2 rounded-full bg-white/15 text-white text-[13px]">No, sono andato via</button>
            </div>
          ) : (
            <div className="mt-2.5 flex items-center gap-2">
              <span className="text-[13px] text-white/80">Sono andato via alle</span>
              <input type="time" value={leftAt} onChange={(e) => setLeftAt(e.target.value)} data-testid="presence-left-at"
                className="com-date h-9 rounded-full bg-white/10 px-3 text-white text-[13px]" />
              <button type="button" disabled={busy || !leftAt} onClick={() => stop(leftAt)} data-testid="presence-left-save"
                className="ml-auto px-4 py-2 rounded-full bg-white text-[#403A3C] text-[13px] font-semibold disabled:opacity-40">Chiudi</button>
            </div>
          )}
        </div>
      ) : (
        <div className="mt-3 flex justify-center">
          <button type="button" disabled={busy} onClick={open ? () => stop() : start} data-testid="presence-pill"
            className="flex items-center gap-2 px-4 py-2 rounded-full lg-glass text-[13px] text-white active:opacity-70 disabled:opacity-60 max-w-full">
            {busy ? <Loader2 size={15} className="animate-spin" /> : open ? <Square size={13} className="text-[#FF8A80]" fill="currentColor" /> : <MapPin size={15} />}
            <span className="truncate">
              {open
                ? (here ? `Ho finito · in cantiere dalle ${hhmm(open.start_at)}` : `Ho finito su «${open.commessa_title}» · dalle ${hhmm(open.start_at)}`)
                : "Sono in cantiere"}
            </span>
          </button>
        </div>
      )}
      {sheet}
    </>
  );
}
