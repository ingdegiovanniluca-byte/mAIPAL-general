import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Reorder, motion, useDragControls, animate, useMotionValue, useTransform } from "framer-motion";
import { ArrowLeft, Star, MoreHorizontal, Check, Plus, ChevronDown, GripVertical, Trash2, CalendarDays, Bell, Sparkles,
  ArrowUp, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* A to do, full screen: its title, state, progress and its STEPS - added one after the other,
   ticked, marked as main (they stay on top, in bold), dragged by ⋮⋮ to reorder, slid left for
   date / delete, tapped to rewrite them with their due date, reminder and a line of note. The
   done ones go down in «Completati». ✨ Suggerisci proposes steps (only the ones picked are
   added); the bar at the bottom is the to do's chat with mAIPAL ("aggiungi …", "segna fatto …"). */

const STATI = [["da_fare", "Da fare"], ["in_corso", "In corso"], ["fatto", "Fatto"]];
const MON = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const DOW = ["dom", "lun", "mar", "mer", "gio", "ven", "sab"];
const todayIso = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const dayLabel = (iso, withDow = false) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return `${withDow ? `${DOW[dt.getDay()]} ` : ""}${d} ${MON[m - 1]}${y !== new Date().getFullYear() ? ` ${y}` : ""}`;
};
const ACTIONS_W = 148;   // the two buttons behind a step slid to the left

function StepRow({ step, open, onToggleOpen, onPatch, onDelete, onDragEnd, canDrag = true }) {
  const controls = useDragControls();
  const x = useMotionValue(0);
  const behind = useTransform(x, [-ACTIONS_W, -8, 0], [1, 1, 0]);   // the buttons behind show only when the row is slid
  const [text, setText] = useState(step.text);
  const [note, setNote] = useState(step.note || "");
  const dateRef = useRef(null);
  useEffect(() => { setText(step.text); setNote(step.note || ""); }, [step.text, step.note]);
  const close = () => animate(x, 0, { type: "spring", stiffness: 500, damping: 40 });
  const saveText = () => { if (text.trim() && text.trim() !== step.text) onPatch({ text: text.trim() }); else setText(step.text); };
  const pickDate = () => { try { dateRef.current?.showPicker?.(); } catch { /* old browsers */ } dateRef.current?.focus(); dateRef.current?.click(); };
  const late = step.due_date && !step.done && step.due_date < todayIso();
  const body = (
    <div className="relative overflow-hidden border-t border-white/[0.14]">
      {/* behind: the date and delete, shown by sliding the step left */}
      <motion.div className="absolute inset-y-0 right-0 flex" style={{ opacity: behind }}>
        <button type="button" onClick={() => { close(); pickDate(); }} className="w-[74px] bg-white/[0.18] text-white text-[11.5px] font-medium flex items-center justify-center gap-1">
          <CalendarDays size={12} /> Data</button>
        <button type="button" onClick={() => { close(); onDelete(); }} data-testid="step-delete-swipe"
          className="w-[74px] bg-[#E8663F] text-white text-[11.5px] font-medium flex items-center justify-center gap-1"><Trash2 size={12} /> Elimina</button>
      </motion.div>
      <motion.div drag={open ? false : "x"} dragDirectionLock dragConstraints={{ left: -ACTIONS_W, right: 0 }} dragElastic={0.05}
        onDragEnd={(_e, info) => animate(x, info.offset.x < -60 ? -ACTIONS_W : 0, { type: "spring", stiffness: 500, damping: 40 })}
        className="relative flex items-center gap-2.5 py-[11px]"
        style={{ x }}>
        {canDrag ? (
          <span onPointerDown={(e) => { e.preventDefault(); controls.start(e); }} data-testid="step-grip"
            className="touch-none cursor-grab active:cursor-grabbing text-white/35 -ml-1 pl-1 pr-0.5 py-1"><GripVertical size={15} /></span>
        ) : <span className="w-[15px]" />}
        <button type="button" onClick={() => onPatch({ done: !step.done })} aria-pressed={!!step.done} data-testid="step-check"
          aria-label={step.done ? "Segna da fare" : "Segna fatto"}
          className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center ${step.done ? "bg-white/55 text-[#7A2A5C]" : "border-[1.5px] border-white/55"}`}>
          {step.done && <Check size={12} strokeWidth={3} />}
        </button>
        <button type="button" onClick={onToggleOpen} className="flex-1 min-w-0 text-left" data-testid="step-text">
          <span className={`block text-[14.5px] leading-snug break-words ${step.done ? "line-through text-white/50" : step.main ? "font-semibold text-white" : "text-white/95"}`}>{step.text}</span>
          {(step.due_date || step.note) && !open && (
            <span className="block text-[11.5px] mt-0.5">
              {step.due_date && <span className={late ? "text-[#FF9A85]" : "text-[#F2C14E]"}>{late ? "scaduto " : "entro "}{dayLabel(step.due_date, true)}{step.reminder ? " · 🔔" : ""}</span>}
              {step.note && <span className="text-white/55">{step.due_date ? " · " : ""}{step.note}</span>}
            </span>
          )}
        </button>
        {!step.done && (
          <button type="button" onClick={() => onPatch({ main: !step.main })} aria-pressed={!!step.main} data-testid="step-main"
            aria-label={step.main ? "Non è principale" : "Segna come principale"} className={`p-1 ${step.main ? "text-[#F2C14E]" : "text-white/35"}`}>
            <Star size={16} className={step.main ? "fill-current" : ""} />
          </button>
        )}
      </motion.div>
      <input ref={dateRef} type="date" value={step.due_date || ""} onChange={(e) => onPatch({ due_date: e.target.value || "" })}
        className="absolute opacity-0 pointer-events-none w-0 h-0 bottom-0 left-1/2" tabIndex={-1} aria-hidden />
      {open && (
        <div className="mb-2.5 rounded-[18px] bg-white/[0.14] px-3.5 py-3" data-testid="step-edit">
          <input value={text} onChange={(e) => setText(e.target.value)} onBlur={saveText} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
            data-testid="step-edit-text" className="w-full bg-transparent text-[14.5px] text-white outline-none border-b-[1.5px] border-white/55 pb-1.5" />
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            <button type="button" onClick={() => onPatch({ main: !step.main })} data-testid="step-edit-main"
              className={`text-[12px] px-3 py-1 rounded-full ${step.main ? "bg-[#F2C14E] text-[#403A3C] font-semibold" : "bg-white/[0.12] text-white"}`}>★ Principale</button>
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
            className="mt-2.5 w-full bg-transparent text-[12.5px] text-white/85 placeholder:text-white/45 outline-none" />
        </div>
      )}
    </div>
  );
  if (!canDrag) return body;
  return (
    <Reorder.Item as="div" value={step} id={step.id} dragListener={false} dragControls={controls} onDragEnd={onDragEnd} data-testid="step-row"
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
  const [showDone, setShowDone] = useState(false);
  const [adding, setAdding] = useState("");
  const [menu, setMenu] = useState(false);
  const [askDone, setAskDone] = useState(false);
  const [suggest, setSuggest] = useState(null);       // {loading} | {steps, picked}
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState([]);           // steps deleted, waiting for their "Annulla"
  const addRef = useRef(null);
  const dueRef = useRef(null);

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
  const pct = total ? Math.round((done / total) * 100) : t.completion_percent || 0;
  const late = t.due_date && t.status !== "fatto" && t.due_date < todayIso();

  return createPortal(
    <div className="fixed inset-0 z-[65] overflow-y-auto overscroll-contain" data-testid="todo-detail" role="dialog" aria-label={t.title}
      style={{ background: "linear-gradient(165deg, #B9A3B3 0%, #A64A80 30%, #93306C 52%, #C85A33 76%, #BDB1BB 100%)" }}>
      <div className="mx-auto w-full max-w-[640px] px-5 pb-[130px]" style={{ paddingTop: "max(18px, env(safe-area-inset-top))" }}>
        {/* top */}
        <div className="flex items-center gap-2.5 pt-2">
          <button type="button" onClick={onClose} aria-label="Indietro" data-testid="todo-back"
            className="h-10 w-10 rounded-full lg-glass flex items-center justify-center text-white"><ArrowLeft size={18} /></button>
          <span className="flex-1" />
          <button type="button" onClick={toggleFav} aria-pressed={!!t.favorite} aria-label="Preferito" data-testid="todo-detail-fav"
            className={`h-10 w-10 rounded-full lg-glass flex items-center justify-center ${t.favorite ? "text-[#F2C14E]" : "text-white/80"}`}>
            <Star size={17} className={t.favorite ? "fill-current" : ""} /></button>
          <div className="relative">
            <button type="button" onClick={() => setMenu((m) => !m)} aria-label="Altro" data-testid="todo-detail-menu"
              className="h-10 w-10 rounded-full lg-glass flex items-center justify-center text-white"><MoreHorizontal size={18} /></button>
            {menu && (
              <div className="glass-panel absolute right-0 top-12 z-10 w-[220px] py-1" role="menu">
                <button type="button" onClick={() => { setMenu(false); try { dueRef.current?.showPicker?.(); } catch { /* */ } dueRef.current?.focus(); dueRef.current?.click(); }}
                  className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14.5px] text-white"><CalendarDays size={15} /> {t.due_date ? "Cambia la scadenza" : "Scadenza del to do"}</button>
                {t.due_date && (
                  <button type="button" onClick={() => { setMenu(false); patchTodo({ reminder: !t.reminder }); }}
                    className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14.5px] text-white"><Bell size={15} /> {t.reminder ? "Togli il promemoria" : "Promemoria su Telegram"}</button>
                )}
                {t.due_date && (
                  <button type="button" onClick={() => { setMenu(false); patchTodo({ due_date: null, reminder: false }); }}
                    className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14.5px] text-white"><X size={15} /> Togli la scadenza</button>
                )}
                <button type="button" onClick={del} data-testid="todo-detail-delete"
                  className="glass-row w-full flex items-center gap-3 px-5 py-3 text-left text-[14.5px] text-[#FF9A85]"><Trash2 size={15} /> Elimina il to do</button>
              </div>
            )}
          </div>
        </div>
        <input ref={dueRef} type="date" value={t.due_date || ""} onChange={(e) => e.target.value && patchTodo({ due_date: e.target.value })}
          className="absolute opacity-0 pointer-events-none w-0 h-0" tabIndex={-1} aria-hidden />

        {/* title, when, state, progress */}
        <textarea value={title} onChange={(e) => setTitle(e.target.value)} rows={1} data-testid="todo-detail-title"
          onBlur={() => { if (title.trim() && title.trim() !== t.title) patchTodo({ title: title.trim() }); else setTitle(t.title); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }}
          className="mt-4 w-full resize-none bg-transparent text-[30px] font-bold leading-tight text-white outline-none [field-sizing:content]" />
        <div className="mt-0.5 text-[12px] text-white/62 text-white/60" data-testid="todo-detail-meta">
          {t.created_at ? `creato il ${dayLabel(t.created_at.slice(0, 10))}` : ""}
          {t.due_date && <span className={late ? "text-[#FFB3A3]" : ""}> · {late ? "scaduto il" : "entro il"} {dayLabel(t.due_date)}{t.reminder ? " 🔔" : ""}</span>}
        </div>
        <div className="mt-3.5 inline-flex rounded-full bg-white/[0.12] p-[3px]" data-testid="todo-detail-status">
          {STATI.map(([k, label]) => (
            <button key={k} type="button" onClick={() => patchTodo({ status: k })} data-testid={`status-${k}`}
              className={`px-3.5 py-1.5 rounded-full text-[12.5px] transition-colors ${t.status === k ? "bg-white text-[#403A3C] font-semibold" : "text-white/80"}`}>{label}</button>
          ))}
        </div>
        {(total > 0 || t.status === "in_corso") && (
          <div className="mt-4">
            <div className="h-1.5 rounded-full bg-white/[0.18] overflow-hidden"><div className="h-full rounded-full bg-white/85 transition-all" style={{ width: `${pct}%` }} /></div>
            {total > 0 ? <div className="mt-1.5 text-[12px] text-white/72 text-white/70" data-testid="todo-detail-progress">{done} di {total} passi fatti</div> : (
              <input type="range" min="0" max="100" value={pct} onChange={(e) => setT((x) => ({ ...x, completion_percent: parseInt(e.target.value, 10) }))}
                onMouseUp={(e) => patchTodo({ completion_percent: parseInt(e.target.value, 10) })} onTouchEnd={(e) => patchTodo({ completion_percent: parseInt(e.target.value, 10) })}
                className="w-full mt-1" data-testid="todo-progress" aria-label="Completamento" />
            )}
          </div>
        )}
        {askDone && (
          <div className="mt-3 rounded-2xl bg-white/[0.14] px-3.5 py-2.5 flex items-center gap-2 text-[13px] text-white" data-testid="todo-ask-done">
            <span className="flex-1">Tutti i passi sono fatti: segno il to do come fatto?</span>
            <button type="button" onClick={() => { setAskDone(false); patchTodo({ status: "fatto" }); }} className="px-3 py-1 rounded-full bg-white text-[#403A3C] font-semibold text-[12.5px]">Sì</button>
            <button type="button" onClick={() => setAskDone(false)} className="px-3 py-1 rounded-full bg-white/[0.12] text-[12.5px]">No</button>
          </div>
        )}

        {/* the steps */}
        <div className="mt-6 flex items-center pb-1.5">
          <span className="kicker flex-1">passi</span>
          <button type="button" onClick={runSuggest} data-testid="todo-suggest"
            className="text-[12px] px-3 py-1 rounded-full bg-white/[0.14] text-white inline-flex items-center gap-1"><Sparkles size={12} /> Suggerisci</button>
        </div>
        <Reorder.Group axis="y" values={order} onReorder={setOrder} as="div" data-testid="todo-steps">
          {order.map((st) => (
            <StepRow key={st.id} step={st} open={openStep === st.id} onToggleOpen={() => setOpenStep((o) => (o === st.id ? null : st.id))}
              onPatch={(b) => patchStep(st.id, b)} onDelete={() => delStep(st)} onDragEnd={saveOrder} />
          ))}
        </Reorder.Group>
        <div className="flex items-center gap-2.5 py-[11px] border-t border-white/[0.14]">
          <span className="w-[15px]" />
          <button type="button" onClick={addStep} aria-label="Aggiungi il passo"
            className="h-5 w-5 shrink-0 rounded-full bg-white/[0.18] flex items-center justify-center text-white"><Plus size={13} /></button>
          <input ref={addRef} value={adding} onChange={(e) => setAdding(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addStep(); } }}
            placeholder="Aggiungi un passo" data-testid="todo-step-add" enterKeyHint="next"
            className="flex-1 min-w-0 bg-transparent text-[14.5px] text-white placeholder:text-white/55 outline-none" />
        </div>
        {doneSteps.length > 0 && (
          <>
            <button type="button" onClick={() => setShowDone((v) => !v)} aria-expanded={showDone} data-testid="todo-done-fold"
              className="w-full flex items-center gap-2 py-3 border-t border-white/[0.14] text-[12.5px] text-white/65">
              <span className="h-4 w-4 rounded-full bg-white/55 text-[#7A2A5C] flex items-center justify-center"><Check size={10} strokeWidth={3} /></span>
              <span className="flex-1 text-left">Completati · {doneSteps.length}</span>
              <ChevronDown size={15} className={`transition-transform ${showDone ? "rotate-180" : ""}`} />
            </button>
            {showDone && doneSteps.map((st) => (
              <StepRow key={st.id} step={st} canDrag={false} open={openStep === st.id} onToggleOpen={() => setOpenStep((o) => (o === st.id ? null : st.id))}
                onPatch={(b) => patchStep(st.id, b)} onDelete={() => delStep(st)} />
            ))}
          </>
        )}

        {/* notes */}
        <div className="kicker mt-6 mb-2">note</div>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (t.notes || "") && patchTodo({ notes })}
          placeholder="Aggiungi una nota…" rows={3} data-testid="todo-notes"
          className="w-full rounded-[18px] bg-white/10 px-3.5 py-3 text-[13.5px] leading-relaxed text-white/90 placeholder:text-white/45 outline-none resize-none [field-sizing:content] min-h-[76px]" />
        {t.description && <div className="mt-3 text-[12.5px] text-white/60 whitespace-pre-wrap">{t.description}</div>}
      </div>

      {/* the chat with mAIPAL */}
      <div className="fixed left-0 right-0 bottom-0 px-3.5" style={{ paddingBottom: "max(18px, env(safe-area-inset-bottom))" }}>
        <div className="mx-auto max-w-[640px] lg-glass rounded-[28px] pl-4 pr-1.5 py-1.5 flex items-center gap-2">
          <input value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") send(); }} data-testid="todo-chat-input"
            placeholder="Scrivi a mAIPAL: aggiungi, sposta, aggiorna…" className="flex-1 min-w-0 bg-transparent py-2 text-[13.5px] text-white placeholder:text-white/60 outline-none" />
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
              <div className="text-[11.5px] text-white/60 mt-1">Li aggiungo solo se li scegli; poi li cambi come vuoi.</div>
              <div className="mt-2">
                {suggest.steps.map((s, i) => (
                  <button key={i} type="button" onClick={() => setSuggest((x) => ({ ...x, picked: x.picked.map((p, j) => (j === i ? !p : p)) }))}
                    className="w-full flex items-center gap-2.5 py-[11px] border-t border-white/[0.14] text-left" data-testid="todo-suggest-item">
                    <span className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center ${suggest.picked[i] ? "bg-white/55 text-[#7A2A5C]" : "border-[1.5px] border-white/55"}`}>
                      {suggest.picked[i] && <Check size={12} strokeWidth={3} />}</span>
                    <span className="text-[14.5px] text-white">{s}</span>
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
    </div>,
    document.body,
  );
}
