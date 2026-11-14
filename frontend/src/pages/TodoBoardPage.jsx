import React, { useEffect, useRef, useState } from "react";
import { Check, Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import TodoDetail from "@/components/TodoDetail";

/* To Do: one plain list, like a reminders app. A circle and the text, one per line; the circle marks it
   done (it fills and, a moment later, goes down among the done ones); the last line writes a new one
   (Enter, and the next one at once). The done ones are at the bottom with the filled tick: their circle
   opens them again. Touching the text opens the to do full screen (steps, notes, due date, delete). */

const ACCENT = "#FFAC33";     // the warm drop of the mAIPAL logo
const DONE_SHOWN = 15;

const byOpen = (a, b) => (!!b.favorite - !!a.favorite) || (a.created_at || "").localeCompare(b.created_at || "");
const byDone = (a, b) => (b.updated_at || b.created_at || "").localeCompare(a.updated_at || a.created_at || "");

function sub(t) {   // one short grey line under the text, only when there is something to say
  const steps = t.steps || [];
  const parts = [];
  if (steps.length) parts.push(`${steps.filter((s) => s.done).length}/${steps.length} passi`);
  else if (t.status === "in_corso") parts.push(t.completion_percent ? `in corso · ${t.completion_percent}%` : "in corso");
  if (t.due_date) parts.push(`entro il ${new Date(`${t.due_date}T12:00:00`).toLocaleDateString("it-IT", { day: "numeric", month: "short" })}`);
  return parts.join(" · ");
}

function Circle({ done, onClick, label }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} data-testid="todo-circle"
      className="h-[26px] w-[26px] shrink-0 rounded-full flex items-center justify-center transition-colors"
      style={done ? { background: ACCENT } : { border: "2px solid rgba(255,255,255,0.5)" }}>
      {done && <Check size={16} strokeWidth={3} className="text-[#3b2400]" />}
    </button>
  );
}

function Row({ t, done, last, onToggle, onOpen }) {
  const line = sub(t);
  return (
    <div className="flex items-start gap-3 pl-1" data-testid={done ? "todo-done-row" : "todo-row"} data-id={t.id}>
      <div className="pt-[11px]"><Circle done={done} onClick={onToggle} label={done ? "Riapri" : "Segna come fatto"} /></div>
      <button type="button" onClick={onOpen} className={`flex-1 min-w-0 text-left py-[12px] ${last ? "" : "border-b border-white/[0.12]"}`}>
        <span className={`block text-[16px] leading-[22px] ${done ? "text-white/60" : "text-white"} ${t.favorite && !done ? "font-semibold" : ""}`}>{t.title}</span>
        {line && !done && <span className="block mt-0.5 text-[12px] text-white/55">{line}</span>}
      </button>
    </div>
  );
}

export default function TodoBoardPage() {
  const [todos, setTodos] = useState(null);
  const [selected, setSelected] = useState(null);
  const [ticking, setTicking] = useState([]);     // just ticked: filled, still in their place for a moment
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [allDone, setAllDone] = useState(false);
  const input = useRef(null);

  const load = () => api.get("/todos").then((r) => setTodos(r.data)).catch(() => setTodos((x) => x || []));
  useEffect(() => { load(); }, []);

  const setStatus = async (t, status) => {
    const prev = t.status;
    setTodos((ts) => ts.map((x) => (x.id === t.id ? { ...x, status, updated_at: new Date().toISOString() } : x)));
    try { await api.patch(`/todos/${t.id}`, { status }); }
    catch { toast.error("Non sono riuscito a salvarlo"); setTodos((ts) => ts.map((x) => (x.id === t.id ? { ...x, status: prev } : x))); }
  };
  const tick = (t) => {
    setTicking((k) => [...k, t.id]);
    setTimeout(() => { setTicking((k) => k.filter((x) => x !== t.id)); setStatus(t, "fatto"); }, 650);
  };
  const add = async () => {
    const title = draft.trim();
    if (!title || busy) return;
    setBusy(true);
    try {
      const r = await api.post("/todos", { title, status: "da_fare" });
      setTodos((ts) => [...(ts || []), r.data]);
      setDraft("");
      input.current?.focus();
    } catch { toast.error("Non sono riuscito ad aggiungerlo"); }
    finally { setBusy(false); }
  };

  if (!todos) return <div className="kicker text-center py-10">caricamento…</div>;
  const open = todos.filter((t) => t.status !== "fatto").sort(byOpen);
  const done = todos.filter((t) => t.status === "fatto").sort(byDone);
  const shownDone = allDone ? done : done.slice(0, DONE_SHOWN);

  return (
    <div className="w-full max-w-[640px] mx-auto" data-testid="todo-list">
      <div className="rounded-[26px] lg-glass px-4 pt-2 pb-3">
        {open.map((t) => (
          <Row key={t.id} t={t} done={ticking.includes(t.id)} onToggle={() => !ticking.includes(t.id) && tick(t)} onOpen={() => setSelected(t)} />
        ))}
        {/* the line that writes a new one */}
        <div className="flex items-center gap-3 pl-1">
          <span className="h-[26px] w-[26px] shrink-0 rounded-full flex items-center justify-center border-2 border-dashed border-white/35 text-white/60"><Plus size={14} /></span>
          <input ref={input} value={draft} onChange={(e) => setDraft(e.target.value)} enterKeyHint="done"
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} onBlur={() => draft.trim() && add()}
            placeholder={open.length ? "Aggiungi una cosa da fare" : "Scrivi la prima cosa da fare"} data-testid="todo-add"
            className="flex-1 min-w-0 bg-transparent py-[13px] text-[16px] text-white placeholder:text-white/50 outline-none" />
        </div>
      </div>

      {done.length > 0 && (
        <div className="mt-5" data-testid="todo-done-list">
          <div className="px-5 pb-1 text-[13px] font-semibold text-white/80">Fatti · {done.length}</div>
          <div className="rounded-[26px] lg-glass px-4 pt-1 pb-2">
            {shownDone.map((t, i) => (
              <Row key={t.id} t={t} last={i === shownDone.length - 1 && done.length <= DONE_SHOWN} done onToggle={() => setStatus(t, "da_fare")} onOpen={() => setSelected(t)} />
            ))}
            {done.length > DONE_SHOWN && (
              <button type="button" onClick={() => setAllDone((v) => !v)} className="w-full py-3 text-[13px] text-white/70" data-testid="todo-done-more">
                {allDone ? "Mostra meno" : `Mostra tutti (${done.length})`}</button>
            )}
          </div>
        </div>
      )}

      {selected && <TodoDetail todo={selected} onClose={() => setSelected(null)} onUpdated={load} />}
    </div>
  );
}
