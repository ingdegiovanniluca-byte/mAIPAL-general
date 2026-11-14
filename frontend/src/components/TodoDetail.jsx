import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Reorder, motion, useDragControls, animate, useMotionValue, useTransform } from "framer-motion";
import { ArrowLeft, Star, MoreHorizontal, Check, Plus, Trash2, CalendarDays, Bell, Sparkles,
  ArrowUp, Loader2, X, ChevronDown, ImagePlus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* A to do, full screen: the title in the middle and one line under it (how many steps are done, the due
   date); a coloured box with what it is about and, if wanted, a photo (a trip, a room...); then the rows,
   what on the left and its content on the right: Avvio / Stato (the start date and the state), Note,
   Passi. The STEPS are like a reminders list - a circle and the text, one per line: the circle ticks it (filled,
   in the warm colour of the logo, the done ones at the bottom), the last open line writes the next
   one (Enter, and the next right away), a long press picks a step up to move it, sliding it left
   shows date / delete, touching it rewrites it with main, due date, reminder and a line of note.
   Everything else (suggest the steps, favourite, due date, done, remove the photo, delete) is in ⋯;
   the bar at the bottom is the to do's chat with mAIPAL. */

const MON = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const DOW = ["dom", "lun", "mar", "mer", "gio", "ven", "sab"];
const todayIso = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const dayLabel = (iso, withDow = false) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return `${withDow ? `${DOW[dt.getDay()]} ` : ""}${d} ${MON[m - 1]}${y !== new Date().getFullYear() ? ` ${y}` : ""}`;
};
const STATO = { da_fare: ["Da fare", "rgba(255,255,255,0.85)"], in_corso: ["In corso", "#36C5E0"], fatto: ["Fatto", "#FFAC33"] };

// a photo from the phone, made smaller before it is sent (a JPEG of at most 1600 px)
async function shrinkPhoto(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = url; });
    const k = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement("canvas");
    c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.82);
  } finally { URL.revokeObjectURL(url); }
}

const RowLabel = ({ title, sub }) => (
  <div className="min-w-0"><div className="text-[14px] leading-[20px] text-white">{title}</div>{sub && <div className="text-[12px] leading-[16px] text-white/55">{sub}</div>}</div>
);
const ACTIONS_W = 148;   // the two buttons behind a step slid to the left

const ACCENT = "#FFAC33";   // the warm drop of the mAIPAL logo: the done ones
const HOLD_MS = 380;        // a long press on a step picks it up, to move it

function Circle({ done, onClick, label, testid }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={!!done} aria-label={label} data-testid={testid}
      className="h-[18px] w-[18px] shrink-0 rounded-full flex items-center justify-center transition-colors"
      style={done ? { background: ACCENT } : { border: "1px solid rgba(255,255,255,0.75)" }}>
      {done && <Check size={11} strokeWidth={3} className="text-[#3b2400]" />}
    </button>
  );
}

function StepRow({ step, open, last, onToggleOpen, onPatch, onDelete, onDragEnd, canDrag = true }) {
  const controls = useDragControls();
  const x = useMotionValue(0);
  const behind = useTransform(x, [-ACTIONS_W, -8, 0], [1, 1, 0]);   // the buttons behind show only when the row is slid
  const [text, setText] = useState(step.text);
  const [note, setNote] = useState(step.note || "");
  const [lifted, setLifted] = useState(false);
  const dateRef = useRef(null);
  const hold = useRef(null);
  useEffect(() => { setText(step.text); setNote(step.note || ""); }, [step.text, step.note]);
  const close = () => animate(x, 0, { type: "spring", stiffness: 500, damping: 40 });
  const saveText = () => { if (text.trim() && text.trim() !== step.text) onPatch({ text: text.trim() }); else setText(step.text); };
  const pickDate = () => { try { dateRef.current?.showPicker?.(); } catch { /* old browsers */ } dateRef.current?.focus(); dateRef.current?.click(); };
  const late = step.due_date && !step.done && step.due_date < todayIso();
  // long press: the step lifts and follows the finger (no handle to look for); a move before it is a scroll or a swipe
  const cancelHold = () => { if (hold.current) { clearTimeout(hold.current.t); hold.current = null; } };
  const onPointerDown = (e) => {
    if (!canDrag || open) return;
    const ev = e.nativeEvent;
    cancelHold();
    hold.current = { x: e.clientX, y: e.clientY, t: setTimeout(() => { hold.current = null; setLifted(true); controls.start(ev); }, HOLD_MS) };
  };
  const onPointerMove = (e) => { if (hold.current && Math.hypot(e.clientX - hold.current.x, e.clientY - hold.current.y) > 8) cancelHold(); };
  const body = (
    <div className="relative overflow-hidden" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={cancelHold} onPointerCancel={cancelHold}
      onContextMenu={(e) => canDrag && e.preventDefault()} style={{ WebkitTouchCallout: "none" }}>
      {/* behind: the date and delete, shown by sliding the step left */}
      <motion.div className="absolute inset-y-0 right-0 flex" style={{ opacity: behind }}>
        <button type="button" onClick={() => { close(); pickDate(); }} className="w-[74px] bg-white/[0.18] text-white text-[12px] font-medium flex items-center justify-center gap-1">
          <CalendarDays size={12} /> Data</button>
        <button type="button" onClick={() => { close(); onDelete(); }} data-testid="step-delete-swipe"
          className="w-[74px] bg-[#E8663F] text-white text-[12px] font-medium flex items-center justify-center gap-1"><Trash2 size={12} /> Elimina</button>
      </motion.div>
      <motion.div drag={open || lifted ? false : "x"} dragDirectionLock dragConstraints={{ left: -ACTIONS_W, right: 0 }} dragElastic={0.05}
        onDragEnd={(_e, info) => animate(x, info.offset.x < -60 ? -ACTIONS_W : 0, { type: "spring", stiffness: 500, damping: 40 })}
        className="relative flex items-start gap-3 select-none" style={{ x }}>
        <div className="pt-[10px]">
          <Circle done={step.done} onClick={() => onPatch({ done: !step.done })} label={step.done ? "Segna da fare" : "Segna fatto"} testid="step-check" />
        </div>
        <button type="button" onClick={onToggleOpen} className="flex-1 min-w-0 text-left py-[9px]" data-testid="step-text">
          <span className={`block text-[14px] leading-[20px] break-words ${step.done ? "text-white/55" : step.main ? "font-semibold text-white" : "text-white"}`}>{step.text}</span>
          {(step.due_date || step.note) && !open && !step.done && (
            <span className="block text-[12px] mt-0.5">
              {step.due_date && <span className={late ? "text-[#FFB3A3]" : "text-white/55"}>{late ? "scaduto " : "entro "}{dayLabel(step.due_date, true)}{step.reminder ? " · 🔔" : ""}</span>}
              {step.note && <span className="text-white/55">{step.due_date ? " · " : ""}{step.note}</span>}
            </span>
          )}
        </button>
      </motion.div>
      <input ref={dateRef} type="date" value={step.due_date || ""} onChange={(e) => onPatch({ due_date: e.target.value || "" })}
        className="absolute opacity-0 pointer-events-none w-0 h-0 bottom-0 left-1/2" tabIndex={-1} aria-hidden />
      {open && (
        <div className="ml-[30px] mt-1 mb-3 rounded-[16px] bg-white/[0.12] px-3.5 py-3" data-testid="step-edit">
          <input value={text} onChange={(e) => setText(e.target.value)} onBlur={saveText} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
            data-testid="step-edit-text" className="w-full bg-transparent text-[16px] text-white outline-none border-b-[1px] border-white/55 pb-1.5" />
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            <button type="button" onClick={() => onPatch({ main: !step.main })} data-testid="step-edit-main"
              className={`text-[12px] px-3 py-1 rounded-full ${step.main ? "bg-[#FFAC33] text-[#3b2400] font-semibold" : "bg-white/[0.12] text-white"}`}>★ Principale</button>
            <label className="relative text-[12px] px-3 py-1 rounded-full bg-white/[0.12] text-white inline-flex items-center gap-1 cursor-pointer">
              <CalendarDays size={12} /> {step.due_date ? `Entro ${dayLabel(step.due_date, true)}` : "Scadenza"}
              <input type="date" value={step.due_date || ""} onChange={(e) => onPatch({ due_date: e.target.value || "" })} data-testid="step-edit-date"
                className="absolute inset-0 opacity-0 cursor-pointer" />
            </label>
            {step.due_date && (
              <button type="button" onClick={() => onPatch({ due_date: "" })} className="text-[12px] px-2 py-1 rounded-full bg-white/[0.06] text-white/70" aria-label="Togli la scadenza"><X size={12} /></button>
            )}
            <button type="button" disabled={!step.due_date} onClick={() => onPatch({ reminder: !step.reminder })} data-testid="step-edit-reminder"
              title={step.due_date ? "Ti scrivo su Telegram il giorno della scadenza" : "Prima metti una scadenza"}
              className={`text-[12px] px-3 py-1 rounded-full inline-flex items-center gap-1 disabled:opacity-40 ${step.reminder ? "bg-white text-[#403A3C] font-semibold" : "bg-white/[0.12] text-white"}`}>
              <Bell size={12} /> Promemoria</button>
            <button type="button" onClick={onDelete} className="text-[12px] px-3 py-1 rounded-full bg-white/[0.12] text-white" aria-label="Elimina il passo" data-testid="step-edit-delete"><Trash2 size={12} /></button>
          </div>
          <input value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== (step.note || "") && onPatch({ note })}
            placeholder="Una riga di nota (facoltativa)" data-testid="step-edit-note"
            className="mt-2.5 w-full bg-transparent text-[16px] text-white/85 placeholder:text-white/45 outline-none" />
        </div>
      )}
    </div>
  );
  if (!canDrag) return body;
  return (
    <Reorder.Item as="div" value={step} id={step.id} dragListener={false} dragControls={controls} data-testid="step-row"
      onDragEnd={() => { setLifted(false); onDragEnd(); }}
      whileDrag={{ scale: 1.02, boxShadow: "0 14px 28px rgba(0,0,0,0.28)", background: "rgba(255,255,255,0.22)", borderRadius: 16, zIndex: 5 }}
      style={{ position: "relative" }}>
      {body}
    </Reorder.Item>
  );
}

export default function TodoDetail({ todo: initial, onClose, onUpdated }) {
  const [t, setT] = useState(initial);
  const [title, setTitle] = useState(initial.title || "");
  const [notes, setNotes] = useState(initial.notes || "");
  const [openStep, setOpenStep] = useState(null);
  const [adding, setAdding] = useState("");
  const [menu, setMenu] = useState(false);
  const [askDone, setAskDone] = useState(false);
  const [suggest, setSuggest] = useState(null);       // {loading} | {steps, picked}
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState([]);           // steps deleted, waiting for their "Annulla"
  const addRef = useRef(null);
  const dueRef = useRef(null);
  const fileRef = useRef(null);
  const [desc, setDesc] = useState(initial.description || "");
  const [editDesc, setEditDesc] = useState(false);
  const [editNotes, setEditNotes] = useState(false);
  const [cover, setCover] = useState(null);           // the photo (a data: URL), loaded apart
  const [coverBusy, setCoverBusy] = useState(false);
  useEffect(() => { if (!editDesc) setDesc(t.description || ""); }, [t.description]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!t.has_cover) { setCover(null); return; }
    let alive = true;
    api.get(`/todos/${t.id}/cover`).then((r) => alive && setCover(r.data.image)).catch(() => alive && setCover(null));
    return () => { alive = false; };
  }, [t.id, t.has_cover, t.cover_v]);

  const steps = (t.steps || []).filter((x) => !hidden.includes(x.id));
  // the main ones on top (in their order), then the others
  const openSteps = useMemo(() => [...steps.filter((x) => !x.done && x.main), ...steps.filter((x) => !x.done && !x.main)], [t.steps, hidden]); // eslint-disable-line react-hooks/exhaustive-deps
  const doneSteps = steps.filter((x) => x.done);
  const [order, setOrder] = useState(openSteps);
  useEffect(() => { setOrder(openSteps); }, [openSteps]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !suggest) onClose(); };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onClose, suggest]);

  const apply = (doc) => {
    if (!doc) return;
    setT(doc);
    onUpdated?.();
    if (doc.ask_done) setAskDone(true);
  };
  const call = async (fn, okMsg) => {
    try { const r = await fn(); apply(r.data.todo || r.data); if (okMsg) toast.success(okMsg); return r.data; }
    catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a salvarlo"); return null; }
  };
  const patchTodo = (body) => call(() => api.patch(`/todos/${t.id}`, body));
  const patchStep = (id, body) => call(() => api.patch(`/todos/${t.id}/steps/${id}`, body));
  const addStep = async () => {
    const text = adding.trim();
    if (!text) return;
    setAdding("");
    await call(() => api.post(`/todos/${t.id}/steps`, { text }));
    addRef.current?.focus();      // Enter: the next one right away
  };
  const delStep = (st) => {
    setHidden((h) => [...h, st.id]);
    setOpenStep(null);
    let undone = false;
    toast(`Passo eliminato: «${st.text.slice(0, 40)}»`, {
      action: { label: "Annulla", onClick: () => { undone = true; setHidden((h) => h.filter((x) => x !== st.id)); } },
      duration: 4500,
      onAutoClose: () => { if (!undone) call(() => api.delete(`/todos/${t.id}/steps/${st.id}`)).then(() => setHidden((h) => h.filter((x) => x !== st.id))); },
      onDismiss: () => { if (!undone) call(() => api.delete(`/todos/${t.id}/steps/${st.id}`)).then(() => setHidden((h) => h.filter((x) => x !== st.id))); },
    });
  };
  const saveOrder = () => {
    const ids = [...order.map((x) => x.id), ...doneSteps.map((x) => x.id)];
    if (ids.join() === (t.steps || []).filter((x) => !hidden.includes(x.id)).map((x) => x.id).join()) return;
    call(() => api.put(`/todos/${t.id}/steps/order`, { ids }));
  };
  const toggleFav = async () => {
    setT((x) => ({ ...x, favorite: !x.favorite }));
    try { await api.post(`/todos/${t.id}/favorite`); onUpdated?.(); } catch { setT((x) => ({ ...x, favorite: !x.favorite })); toast.error("Errore"); }
  };
  const del = () => {
    setMenu(false);
    toast("Eliminare questo to do?", {
      action: { label: "Elimina", onClick: async () => { await api.delete(`/todos/${t.id}`); onUpdated?.(); onClose(); } },
      cancel: { label: "Annulla", onClick: () => {} }, duration: 6000,
    });
  };
  const runSuggest = async () => {
    setSuggest({ loading: true });
    try {
      const r = await api.post(`/todos/${t.id}/steps/suggest`);
      const list = r.data.steps || [];
      if (!list.length) { setSuggest(null); toast("Nessun passo da proporre: scrivili tu."); return; }
      setSuggest({ steps: list, picked: list.map(() => true) });
    } catch (e) { setSuggest(null); toast.error(e.response?.data?.detail || "Non riesco a proporre i passi ora"); }
  };
  const addSuggested = async () => {
    const texts = suggest.steps.filter((_, i) => suggest.picked[i]);
    setSuggest(null);
    if (texts.length) await call(() => api.post(`/todos/${t.id}/steps`, { texts }), `${texts.length} ${texts.length === 1 ? "passo aggiunto" : "passi aggiunti"}`);
  };
  const pickCover = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setCoverBusy(true);
    try {
      const image = await shrinkPhoto(file);
      await call(() => api.put(`/todos/${t.id}/cover`, { image }));
    } catch { toast.error("Non riesco a leggere questa foto"); }
    finally { setCoverBusy(false); }
  };
  const saveDesc = () => { setEditDesc(false); if (desc.trim() !== (t.description || "")) patchTodo({ description: desc.trim() }); };
  const send = async () => {
    if (!msg.trim()) return;
    setBusy(true);
    try {
      const r = await api.post(`/todos/${t.id}/chat`, { message: msg.trim() });
      setMsg("");
      if (r.data.todo) apply(r.data.todo);
      if (r.data.answer) toast.success(r.data.answer.slice(0, 160));
    } catch { toast.error("Errore"); }
    finally { setBusy(false); }
  };

  const total = steps.length;
  const done = doneSteps.length;
  const late = t.due_date && t.status !== "fatto" && t.due_date < todayIso();
  const start = t.start_date || (t.created_at || "").slice(0, 10) || todayIso();
  const sub = [total > 0 && <span key="p" data-testid="todo-detail-progress">{done} di {total} passi fatti</span>,
    t.due_date && <span key="d" className={late ? "text-[#FFB3A3]" : ""}>{late ? "scaduto il" : "entro il"} {dayLabel(t.due_date)}{t.reminder ? " 🔔" : ""}</span>].filter(Boolean);

  return createPortal(
    <motion.div layoutScroll className="fixed inset-0 z-[65] overflow-y-auto overscroll-contain" data-testid="todo-detail" role="dialog" aria-label={t.title}
      style={{ fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif", background: "linear-gradient(165deg, #B9A3B3 0%, #A64A80 30%, #93306C 52%, #C85A33 76%, #BDB1BB 100%)" }}>
      <div className="mx-auto w-full max-w-[640px] px-5 pb-[130px]" style={{ paddingTop: "max(18px, env(safe-area-inset-top))" }}>
        {/* top: back, and everything else in ⋯ */}
        <div className="flex items-center gap-2.5 pt-2">
          <button type="button" onClick={onClose} aria-label="Indietro" data-testid="todo-back"
            className="h-10 w-10 rounded-full lg-glass flex items-center justify-center text-white"><ArrowLeft size={18} /></button>
          <span className="flex-1" />
          <div className="relative">
            <button type="button" onClick={() => setMenu((m) => !m)} aria-label="Altro" data-testid="todo-detail-menu"
              className="h-10 w-10 rounded-full lg-glass flex items-center justify-center text-white"><MoreHorizontal size={18} /></button>
            {menu && (
              <div className="glass-panel absolute right-0 top-12 z-10 w-[240px] py-1" role="menu">
                <button type="button" onClick={() => { setMenu(false); runSuggest(); }} data-testid="todo-suggest"
                  className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-white"><Sparkles size={15} /> Suggerisci i passi</button>
                <button type="button" onClick={() => { setMenu(false); toggleFav(); }} data-testid="todo-detail-fav"
                  className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-white"><Star size={15} className={t.favorite ? "fill-current" : ""} /> {t.favorite ? "Togli dai preferiti" : "Aggiungi ai preferiti"}</button>
                <button type="button" onClick={() => { setMenu(false); try { dueRef.current?.showPicker?.(); } catch { /* */ } dueRef.current?.focus(); dueRef.current?.click(); }}
                  className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-white"><CalendarDays size={15} /> {t.due_date ? "Cambia la scadenza" : "Scadenza del to do"}</button>
                {t.due_date && (
                  <button type="button" onClick={() => { setMenu(false); patchTodo({ reminder: !t.reminder }); }}
                    className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-white"><Bell size={15} /> {t.reminder ? "Togli il promemoria" : "Promemoria su Telegram"}</button>
                )}
                {t.due_date && (
                  <button type="button" onClick={() => { setMenu(false); patchTodo({ due_date: null, reminder: false }); }}
                    className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-white"><X size={15} /> Togli la scadenza</button>
                )}
                <button type="button" onClick={() => { setMenu(false); patchTodo({ status: t.status === "fatto" ? "da_fare" : "fatto" }); }} data-testid="todo-detail-done"
                  className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-white"><Check size={15} /> {t.status === "fatto" ? "Riapri il to do" : "Segna il to do come fatto"}</button>
                {t.has_cover && (
                  <button type="button" onClick={() => { setMenu(false); call(() => api.delete(`/todos/${t.id}/cover`)); }} data-testid="todo-cover-remove"
                    className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-white"><ImagePlus size={15} /> Togli la foto</button>
                )}
                <button type="button" onClick={del} data-testid="todo-detail-delete"
                  className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14px] text-[#FF9A85]"><Trash2 size={15} /> Elimina il to do</button>
              </div>
            )}
          </div>
        </div>
        <input ref={dueRef} type="date" value={t.due_date || ""} onChange={(e) => e.target.value && patchTodo({ due_date: e.target.value })}
          className="absolute opacity-0 pointer-events-none w-0 h-0" tabIndex={-1} aria-hidden />

        {/* the title, in the middle, and one line under it */}
        <textarea value={title} onChange={(e) => setTitle(e.target.value)} rows={1} data-testid="todo-detail-title"
          onBlur={() => { if (title.trim() && title.trim() !== t.title) patchTodo({ title: title.trim() }); else setTitle(t.title); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }}
          className="mt-4 w-full resize-none bg-transparent text-center text-[30px] font-semibold tracking-[-0.02em] leading-tight text-white outline-none [field-sizing:content]" />
        {sub.length > 0 && (
          <div className="mt-0.5 text-center text-[15px] text-white/85" data-testid="todo-detail-meta">
            {sub.reduce((acc, x, k) => (k ? [...acc, " · ", x] : [x]), [])}
          </div>
        )}
        {askDone && (
          <div className="mt-3 rounded-2xl bg-white/[0.14] px-3.5 py-2.5 flex items-center gap-2 text-[13px] text-white" data-testid="todo-ask-done">
            <span className="flex-1">Tutti i passi sono fatti: segno il to do come fatto?</span>
            <button type="button" onClick={() => { setAskDone(false); patchTodo({ status: "fatto" }); }} className="px-3 py-1 rounded-full bg-white text-[#403A3C] font-semibold text-[12px]">Sì</button>
            <button type="button" onClick={() => setAskDone(false)} className="px-3 py-1 rounded-full bg-white/[0.12] text-[12px]">No</button>
          </div>
        )}

        {/* the only box: what it is about, and a photo if there is one (a trip, a room...) */}
        <div className="relative mt-6 rounded-[22px] overflow-hidden aspect-[16/9] shadow-[0_16px_36px_rgba(60,10,40,0.3)]" data-testid="todo-cover"
          style={cover ? { background: "#3a2030" } : { background: "linear-gradient(135deg, #FF7E00 0%, #FF0061 55%, #B9006C 100%)" }}>
          {cover && <img src={cover} alt="" className="absolute inset-0 h-full w-full object-cover" data-testid="todo-cover-img" />}
          {cover && <div className="absolute inset-0" style={{ background: "linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.12) 55%, rgba(0,0,0,0) 100%)" }} />}
          <div className="absolute top-3.5 left-4 right-4 flex items-center justify-between">
            <span className="text-[13px] text-white"><b className="font-bold">mAIPAL</b> To Do</span>
            <button type="button" onClick={() => fileRef.current?.click()} data-testid="todo-cover-pick"
              className="text-[13px] text-white inline-flex items-center gap-1"><ImagePlus size={13} /> {cover ? "Cambia foto" : "Foto"}</button>
          </div>
          {/* the description, from the top */}
          {editDesc ? (
            <textarea autoFocus value={desc} onChange={(e) => setDesc(e.target.value)} onBlur={saveDesc} data-testid="todo-desc-edit"
              placeholder="Di cosa si tratta?" className="absolute inset-x-4 top-11 bottom-4 bg-transparent p-0 text-[17px] leading-snug font-semibold text-white placeholder:text-white/70 outline-none resize-none" />
          ) : (
            <button type="button" onClick={() => setEditDesc(true)} className="absolute inset-x-4 top-11 bottom-4 text-left flex items-start" data-testid="todo-desc">
              <span className={`text-[17px] leading-snug font-semibold line-clamp-5 ${desc ? "text-white" : "text-white/75"}`}>{desc || "Tocca per scrivere di cosa si tratta"}</span>
            </button>
          )}
          {coverBusy && <div className="absolute inset-0 bg-black/30 flex items-center justify-center text-white"><Loader2 size={22} className="animate-spin" /></div>}
        </div>
        <input ref={fileRef} type="file" accept="image/*" hidden onChange={pickCover} data-testid="todo-cover-file" />

        {/* the rows, no boxes: what on the left, its content on the right */}
        <div className="mt-8 grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-7 items-start">
          <RowLabel title="Avvio" sub="Stato" />
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[14px] text-white pt-px" data-testid="todo-start">
            <label className="relative cursor-pointer">
              {dayLabel(start)}
              <input type="date" value={start} onChange={(e) => e.target.value && patchTodo({ start_date: e.target.value })} data-testid="todo-start-date"
                className="absolute inset-0 opacity-0 cursor-pointer" aria-label="Data di avvio" />
            </label>
            <span className="text-white/45">·</span>
            <label className="relative inline-flex items-center gap-1.5 cursor-pointer">
              <span className="h-2 w-2 rounded-full" style={{ background: STATO[t.status]?.[1] || STATO.da_fare[1] }} />
              {STATO[t.status]?.[0] || "Da fare"} <ChevronDown size={13} className="text-white/60" />
              <select value={t.status || "da_fare"} onChange={(e) => patchTodo({ status: e.target.value })} data-testid="todo-status"
                className="absolute inset-0 opacity-0 cursor-pointer" aria-label="Stato">
                {Object.entries(STATO).map(([k, [label]]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </label>
          </div>

          <RowLabel title="Note" />
          {editNotes ? (
            <textarea autoFocus value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="todo-notes"
              onBlur={() => { setEditNotes(false); if (notes !== (t.notes || "")) patchTodo({ notes }); }}
              placeholder="Scrivi una nota…" rows={2}
              className="w-full bg-transparent p-0 text-[14px] leading-[20px] text-white placeholder:text-white/45 outline-none resize-none [field-sizing:content]" />
          ) : (
            <button type="button" onClick={() => setEditNotes(true)} className="text-left pt-px" data-testid="todo-notes-view">
              <span className={`block text-[14px] leading-[20px] whitespace-pre-wrap break-words ${notes ? "text-white/90" : "text-white/45"}`}>{notes || "Scrivi una nota…"}</span>
            </button>
          )}

          <RowLabel title="Passi" sub={total ? `${done} di ${total} fatti` : "da fare"} />
          <div className="min-w-0 -mt-[7px]">
            <Reorder.Group axis="y" values={order} onReorder={setOrder} as="div" data-testid="todo-steps">
              {order.map((st) => (
                <StepRow key={st.id} step={st} open={openStep === st.id} onToggleOpen={() => setOpenStep((o) => (o === st.id ? null : st.id))}
                  onPatch={(b) => patchStep(st.id, b)} onDelete={() => delStep(st)} onDragEnd={saveOrder} />
              ))}
            </Reorder.Group>
            <div className="flex items-center gap-3">
              <button type="button" onClick={addStep} aria-label="Aggiungi il passo"
                className="h-[18px] w-[18px] shrink-0 rounded-full flex items-center justify-center border border-dashed border-white/60 text-white/60"><Plus size={10} /></button>
              <input ref={addRef} value={adding} onChange={(e) => setAdding(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addStep(); } }}
                placeholder={order.length || doneSteps.length ? "Aggiungi un passo" : "Scrivi il primo passo"} data-testid="todo-step-add" enterKeyHint="next"
                className="flex-1 min-w-0 bg-transparent py-[9px] text-[14px] text-white placeholder:text-white/45 outline-none" />
            </div>
            {doneSteps.map((st, k) => (
              <StepRow key={st.id} step={st} canDrag={false} last={k === doneSteps.length - 1} open={openStep === st.id} onToggleOpen={() => setOpenStep((o) => (o === st.id ? null : st.id))}
                onPatch={(b) => patchStep(st.id, b)} onDelete={() => delStep(st)} />
            ))}
          </div>
        </div>
      </div>

      {/* the chat with mAIPAL */}
      <div className="fixed left-0 right-0 bottom-0 px-3.5" style={{ paddingBottom: "max(18px, env(safe-area-inset-bottom))" }}>
        <div className="mx-auto max-w-[640px] lg-glass rounded-[28px] pl-4 pr-1.5 py-1.5 flex items-center gap-2">
          <input value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") send(); }} data-testid="todo-chat-input"
            placeholder="Scrivi a mAIPAL: aggiungi, sposta, aggiorna…" className="flex-1 min-w-0 bg-transparent py-2 text-[13px] text-white placeholder:text-white/60 outline-none" />
          <button type="button" onClick={send} disabled={busy || !msg.trim()} aria-label="Invia" data-testid="todo-chat-send"
            className="h-[34px] w-[34px] shrink-0 rounded-full bg-white text-[#7A2A5C] flex items-center justify-center disabled:opacity-50">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <ArrowUp size={16} />}</button>
        </div>
      </div>

      {suggest && (
        <GlassBottomSheet onClose={() => setSuggest(null)} testid="todo-suggest-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[520px] md:-translate-x-1/2 md:bottom-8">
          <div className="kicker inline-flex items-center gap-1.5"><Sparkles size={12} /> passi proposti per «{t.title}»</div>
          {suggest.loading ? (
            <div className="py-8 flex items-center justify-center text-white/75 text-[13px] gap-2"><Loader2 size={15} className="animate-spin" /> Penso ai passi…</div>
          ) : (
            <>
              <div className="text-[11px] text-white/60 mt-1">Li aggiungo solo se li scegli; poi li cambi come vuoi.</div>
              <div className="mt-2">
                {suggest.steps.map((s, i) => (
                  <button key={i} type="button" onClick={() => setSuggest((x) => ({ ...x, picked: x.picked.map((p, j) => (j === i ? !p : p)) }))}
                    className="w-full flex items-center gap-2.5 py-[11px] border-t border-white/[0.14] text-left" data-testid="todo-suggest-item">
                    <span className="h-[26px] w-[26px] shrink-0 rounded-full flex items-center justify-center"
                      style={suggest.picked[i] ? { background: ACCENT } : { border: "2px solid rgba(255,255,255,0.5)" }}>
                      {suggest.picked[i] && <Check size={16} strokeWidth={3} className="text-[#3b2400]" />}</span>
                    <span className="text-[16px] text-white">{s}</span>
                  </button>
                ))}
              </div>
              <div className="mt-4 flex gap-2">
                <button type="button" onClick={() => setSuggest(null)} className="flex-1 py-3 rounded-full bg-white/[0.14] text-white text-[14px]">Annulla</button>
                <button type="button" onClick={addSuggested} disabled={!suggest.picked.some(Boolean)} data-testid="todo-suggest-add"
                  className="flex-1 py-3 rounded-full bg-white text-[#403A3C] text-[14px] font-semibold disabled:opacity-40">
                  Aggiungi {suggest.picked.filter(Boolean).length} {suggest.picked.filter(Boolean).length === 1 ? "passo" : "passi"}</button>
              </div>
            </>
          )}
        </GlassBottomSheet>
      )}
    </motion.div>,
    document.body,
  );
}
