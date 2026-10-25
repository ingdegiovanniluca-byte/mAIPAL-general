import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { ArrowLeft, ArrowRightLeft, CircleCheck, Plus, Rows3, Star, StickyNote, Trash2 } from "lucide-react";
import { toast } from "sonner";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* To-Do on the phone: the three states as folders of the app's glass, one under the other.
   The first to dos peek out of each folder as small cards; a finger (or the mouse) on them
   tilts the front forward and fans them out, the one under the finger rising most. Slid up,
   the cards stay up when the finger lifts: then a sideways slide scrolls through all the
   folder's to dos, a slide down puts them back, a tap on one opens it. A tap on the folder
   opens the list of all its to dos (cards like the task cards), its + a new one already in
   that state. */

export const FOLDERS = [
  { key: "da_fare", label: "Da fare", tone: "linear-gradient(160deg, rgba(142,47,107,.18), rgba(142,47,107,.04))" },
  { key: "in_corso", label: "In corso", tone: "linear-gradient(160deg, rgba(242,112,30,.22), rgba(242,112,30,.04))" },
  { key: "fatto", label: "Fatti", tone: "linear-gradient(160deg, rgba(203,223,228,.35), rgba(203,223,228,.08))" },
];
const PRIORITY = {
  alta: { label: "Alta", color: "#E8663F" },
  media: { label: "Media", color: "#F2B640" },
  bassa: { label: "Bassa", color: "#8FB3C9" },
};
const ACCENT = "#00B0F0";

// the folder's two layers, measured on a 318 x 255 box (the back with its tab on the right,
// the front with its tab on the left), drawn at any size through objectBoundingBox clip paths
const W = 318, H = 255;
const BACK = "M0 52 Q0 32 20 32 L132 32 C151 32 151 0 172 0 L298 0 Q318 0 318 20 L318 235 Q318 255 298 255 L20 255 Q0 255 0 235 Z";
const FRONT = "M0 89 Q0 69 20 69 L116 69 C138 69 139 98 162 98 L298 98 Q318 98 318 118 L318 235 Q318 255 298 255 L20 255 Q0 255 0 235 Z";
const unit = (d) => { let i = 0; return d.replace(/-?\d+(\.\d+)?/g, (n) => (+n / (i++ % 2 ? H : W)).toFixed(5)); };

function ClipDefs() {
  return (
    <svg width="0" height="0" className="absolute" aria-hidden="true">
      <defs>
        <clipPath id="todo-cp-back" clipPathUnits="objectBoundingBox"><path d={unit(BACK)} /></clipPath>
        <clipPath id="todo-cp-front" clipPathUnits="objectBoundingBox"><path d={unit(FRONT)} /></clipPath>
      </defs>
    </svg>
  );
}

const shortDate = (iso) => (iso ? new Date(iso).toLocaleDateString("it-IT", { day: "numeric", month: "short" }) : "");
const longDate = (iso) => (iso ? new Date(iso).toLocaleDateString("it-IT", { day: "numeric", month: "long" }) : "");

// "Alta · 60%" / "Media" / "12 ott": what the card under the title says
function meta(t) {
  const parts = [];
  if (PRIORITY[t.priority]) parts.push(PRIORITY[t.priority].label);
  if (t.status === "in_corso") parts.push(`${t.completion_percent || 0}%`);
  if (!parts.length && t.created_at) parts.push(shortDate(t.created_at));
  return parts.join(" · ");
}

// when the folder last changed: "aggiornato oggi / ieri / il 12 ottobre"
function lastChange(items) {
  const last = items.map((t) => t.updated_at || t.created_at).filter(Boolean).sort().pop();
  if (!last) return "vuota";
  const d = new Date(last), today = new Date();
  const days = Math.round((new Date(today.toDateString()) - new Date(d.toDateString())) / 86400000);
  return days <= 0 ? "aggiornato oggi" : days === 1 ? "aggiornato ieri" : `aggiornato il ${longDate(last)}`;
}

// the folders' size: three of them fit between the header and the bottom bar, with room above
// each for the cards to fan out (no scrolling, so a finger on the cards never fights the page)
function useFolderScale() {
  const calc = () => {
    if (typeof window === "undefined") return 0.66;
    const free = window.innerHeight - 56 - 100 - 3 * 70;
    return Math.max(0.42, Math.min(0.66, free / (3 * H)));
  };
  const [k, setK] = useState(calc);
  useEffect(() => {
    const on = () => setK(calc());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return k;
}

const PIN_SLIDE = 24;    // px up (or down, once up) that keep the cards up (or put them back)
const CARD_STEP = 64;    // px of sideways slide per card, with the cards up
const PINNED_MAX = 40;   // cards drawn with the cards up (a long folder is opened as a list)

// a card's place with the cards up, from its slot (0 = the one in front, on the left; fractions
// while sliding): the fan's three places, continued on both sides and fading out there; the
// one in front a little higher
function slotStyle(p) {
  const fade = p < 0 ? 1 + p : p > 2 ? 3 - p : 1;
  const lift = Math.max(0, 1 - Math.abs(p)) * 22;
  return { "--x": `${4 + 38 * p}px`, "--y": `${-74 + 21 * p - lift}px`, "--r": `${-5 + 4.5 * p}deg`, "--s": 1 + 0.04 * Math.max(0, 1 - Math.abs(p)),
           opacity: Math.max(0, Math.min(1, fade)), zIndex: 1 };
}

function Folder({ folder, items, k, fan, hot, pinned, onFan, onUnfan, onPin, onUnpin, onOpen, onOpenTodo, onAdd }) {
  const hit = useRef(null);
  const press = useRef(null);
  const [offset, setOffset] = useState(0);       // the first card's slot with the cards up (fractional while sliding)
  const [sliding, setSliding] = useState(false);
  const maxOffset = Math.max(0, Math.min(items.length, PINNED_MAX) - 1);   // up to the last one in front
  useEffect(() => { if (!pinned) setOffset(0); }, [pinned]);
  const sheets = pinned ? items.slice(0, PINNED_MAX) : items.slice(0, 3);
  const hotAt = (e) => {
    const r = hit.current.getBoundingClientRect();
    const n = Math.max(Math.min(items.length, 3), 1);
    return Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n)));
  };
  const down = (e) => {
    hit.current.setPointerCapture?.(e.pointerId);
    press.current = { x: e.clientX, y: e.clientY, t: Date.now(), mode: null, offset };
    if (!pinned) onFan(hotAt(e));
  };
  const move = (e) => {
    const p = press.current;
    if (!p) { if (e.pointerType === "mouse" && !pinned) onFan(hotAt(e)); return; }
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    // with the cards up a slant slide counts as sideways (a finger never moves quite straight)
    if (!p.mode && Math.hypot(dx, dy) > 8) p.mode = Math.abs(dx) >= Math.abs(dy) * (pinned ? 0.6 : 1) ? "side" : "updown";
    if (!pinned) { onFan(hotAt(e)); return; }
    if (p.mode === "side") {
      // a little give past the ends, like a list scrolled too far
      const raw = p.offset - dx / CARD_STEP;
      const o = raw < 0 ? raw / 3 : raw > maxOffset ? maxOffset + (raw - maxOffset) / 3 : raw;
      setSliding(true);
      setOffset(o);
    }
  };
  const up = (e) => {
    const p = press.current;
    press.current = null;
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    const tap = Math.abs(dx) < 8 && Math.abs(dy) < 8 && Date.now() - p.t < 350;
    if (pinned) {
      setSliding(false);
      if (tap) {   // the card under the finger opens
        // the topmost card there that can be seen (the faded ones at the sides don't count)
        const card = document.elementsFromPoint(e.clientX, e.clientY)
          .find((el) => el.dataset?.todoCard && parseFloat(getComputedStyle(el).opacity) > 0.5);
        const todo = card && items.find((t) => t.id === card.dataset.todoCard);
        if (todo) onOpenTodo(todo);
        return;
      }
      if (p.mode === "side") { setOffset(Math.max(0, Math.min(maxOffset, Math.round(offset)))); return; }
      if (p.mode === "updown" && dy > PIN_SLIDE) onUnpin();
      return;
    }
    // a quick tap on the cards opens the folder too; slid up the cards stay up; a slide only looks
    if (tap) { onUnfan(); onOpen(); return; }
    if (p.mode === "updown" && dy < -PIN_SLIDE) { onPin(); return; }
    if (e.pointerType !== "mouse") onUnfan();
  };
  return (
    <div
      className={`todo-folder ${fan || pinned ? "fan" : ""} ${pinned ? "pinned" : ""} ${sliding ? "sliding" : ""}`}
      style={{ "--k": k, "--tone": folder.tone }}
      data-testid={`folder-${folder.key}`}
      data-pinned={pinned ? "true" : undefined}
      onClick={(e) => { if (!e.target.closest(".tf-add, .tf-hit")) onOpen(); }}
    >
      <div className="tf-shade"><i /></div>
      <div className="tf-back" />
      {sheets.map((t, i) => (
        <div key={t.id} data-todo-card={t.id} className={`tf-sheet s${Math.min(i, 2)} ${fan && !pinned && hot === i ? "hot" : ""}`}
          style={pinned ? slotStyle(i - offset) : undefined}>
          <div className="tf-st">{t.title}</div>
          <div className="tf-sm">
            {PRIORITY[t.priority] && <i style={{ background: PRIORITY[t.priority].color }} />}
            {meta(t)}
          </div>
        </div>
      ))}
      <div className="tf-front" />
      <div className="tf-lbl tf-idle">
        <div className="tf-n">{folder.label}</div>
        <div className="tf-c"><Rows3 /> {items.length} to do</div>
      </div>
      <div className="tf-lbl tf-open">
        <div className="tf-n">{folder.label}</div>
        <div className="tf-c">{lastChange(items)}</div>
      </div>
      <button type="button" className="tf-add" data-testid={`folder-add-${folder.key}`} onClick={onAdd} aria-label={`Nuovo to do in ${folder.label}`}>
        <Plus />
      </button>
      {pinned && items.length > 1 && (
        <div className="tf-count" data-testid={`folder-count-${folder.key}`}>
          {Math.round(Math.max(0, Math.min(maxOffset, offset))) + 1} di {Math.min(items.length, PINNED_MAX)}
        </div>
      )}
      {sheets.length > 0 && (
        <div ref={hit} className="tf-hit" data-testid={`folder-cards-${folder.key}`} onPointerDown={down} onPointerMove={move} onPointerUp={up}
          onPointerCancel={() => { press.current = null; setSliding(false); if (!pinned) onUnfan(); }}
          onPointerLeave={(e) => { if (e.pointerType === "mouse" && !pinned) onUnfan(); }} />
      )}
    </div>
  );
}

function TodoCard({ todo, onOpen, onToggleFav, onDelete, onMove }) {
  const [moving, setMoving] = useState(false);
  const done = todo.status === "fatto";
  const prio = PRIORITY[todo.priority];
  const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
  return (
    <div data-testid={`todo-${todo.id}`} className={`w-full flex items-stretch rounded-2xl overflow-hidden card-soft ${done ? "opacity-70" : ""}`}>
      <button data-testid="todo-fav" onClick={stop(onToggleFav)}
        className={`shrink-0 w-12 flex items-center justify-center transition-colors ${todo.favorite ? "bg-amber-400" : "bg-white/10 hover:bg-white/15"}`}
        title={todo.favorite ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}>
        <Star size={18} className={todo.favorite ? "text-white fill-white" : "text-white/50"} />
      </button>
      <div className="flex-1 min-w-0 flex flex-col">
        <button onClick={onOpen} className="text-left px-4 pt-3 pb-1">
          <div className={`font-semibold text-sm break-words text-white ${done ? "line-through" : ""}`}>{todo.title}</div>
          {meta(todo) && (
            <div className="text-[11px] text-white/60 mt-1 flex items-center gap-1.5">
              {prio && <span className="w-2 h-2 rounded-full shrink-0" style={{ background: prio.color }} />}
              {meta(todo)}
            </div>
          )}
          {todo.status === "in_corso" && (
            <div className="mt-2 h-1 rounded-full bg-white/15 overflow-hidden">
              <div className="h-full rounded-full bg-white/80" style={{ width: `${todo.completion_percent || 0}%` }} />
            </div>
          )}
        </button>
        <div className="flex items-center gap-1 pl-2.5 pr-3 pb-2">
          <button onClick={onOpen} className={`p-1.5 rounded-full ${todo.notes ? "text-white/80" : "text-white/40 hover:text-white/70"}`} title="Note e dettagli"><StickyNote size={14} /></button>
          <button data-testid="todo-move" onClick={stop(() => setMoving((m) => !m))} className={`p-1.5 rounded-full ${moving ? "text-white" : "text-white/40 hover:text-white/70"}`} title="Sposta in un'altra cartella"><ArrowRightLeft size={14} /></button>
          <button data-testid="todo-done" onClick={stop(() => onMove(done ? "da_fare" : "fatto"))} className={`p-1.5 rounded-full ${done ? "text-[#92D050]" : "text-white/40 hover:text-white/70"}`} title={done ? "Riapri" : "Segna come fatto"}>
            <CircleCheck size={14} className={done ? "fill-current" : ""} />
          </button>
          <button data-testid="todo-delete" onClick={stop(onDelete)} className="p-1.5 rounded-full text-white/40 hover:text-red-400" title="Elimina"><Trash2 size={14} /></button>
        </div>
        {moving && (
          <div className="flex flex-wrap items-center gap-2 px-4 pb-3" data-testid="todo-move-menu">
            <span className="text-[11px] text-white/60">Sposta in</span>
            {FOLDERS.filter((f) => f.key !== todo.status).map((f) => (
              <button key={f.key} data-testid={`move-to-${f.key}`} onClick={stop(() => { setMoving(false); onMove(f.key); })}
                className="px-3 py-1 rounded-full text-xs lg-glass text-white">{f.label}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function NewTodoSheet({ folder, onClose, onCreated }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      await api.post("/todos", { title: title.trim(), description: description.trim(), status: folder.key, priority });
      toast.success(`Aggiunto a ${folder.label}`);
      onCreated();
      onClose();
    } catch { toast.error("Non sono riuscito a salvare il to do"); }
    finally { setBusy(false); }
  };
  return (
    <GlassBottomSheet onClose={onClose} testid="todo-new-sheet" className="max-h-[88vh]">
      <div className="kicker">· Nuovo to do</div>
      <div className="text-2xl font-bold text-white mt-1 mb-4">{folder.label}</div>
      <input data-testid="todo-new-title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") save(); }}
        placeholder="Cosa c'è da fare?" className="w-full rounded-2xl bg-white/10 px-4 py-3 text-sm text-white placeholder:text-white/45 outline-none" />
      <textarea data-testid="todo-new-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={3}
        placeholder="Note (facoltative)" className="w-full mt-3 rounded-2xl bg-white/10 px-4 py-3 text-sm text-white placeholder:text-white/45 outline-none resize-none" />
      <div className="kicker mt-4 mb-2">Priorità</div>
      <div className="flex gap-2">
        {Object.entries(PRIORITY).map(([key, p]) => (
          <button key={key} type="button" data-testid={`todo-new-prio-${key}`} onClick={() => setPriority(priority === key ? null : key)}
            className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs ${priority === key ? "bg-white text-[#403A3C] font-semibold" : "bg-white/10 text-white"}`}>
            <span className="w-2 h-2 rounded-full" style={{ background: p.color }} /> {p.label}
          </button>
        ))}
      </div>
      <button data-testid="todo-new-save" onClick={save} disabled={busy || !title.trim()}
        className="mt-5 w-full py-3 rounded-full bg-white text-[#403A3C] text-sm font-semibold disabled:opacity-40">
        {busy ? "…" : `Aggiungi a ${folder.label}`}
      </button>
    </GlassBottomSheet>
  );
}

export default function TodoFolders({ todos, sortTodos, reload, setTodos, onOpenTodo, onToggleFav, onDelete }) {
  const [params, setParams] = useSearchParams();
  const open = FOLDERS.find((f) => f.key === params.get("cartella")) || null;
  const [fan, setFan] = useState(null);           // {key, hot}
  const [pinned, setPinned] = useState(null);     // the folder whose cards stay up
  const [adding, setAdding] = useState(null);     // a folder
  const k = useFolderScale();
  const byFolder = Object.fromEntries(FOLDERS.map((f) => [f.key, sortTodos(todos.filter((t) => t.status === f.key))]));

  const openFolder = (f) => setParams((p) => { const n = new URLSearchParams(p); n.set("cartella", f.key); return n; });
  const closeFolder = () => setParams((p) => { const n = new URLSearchParams(p); n.delete("cartella"); return n; }, { replace: false });

  const moveTo = async (todo, status) => {
    const prev = todos;
    setTodos((ts) => ts.map((t) => (t.id === todo.id ? { ...t, status } : t)));
    try {
      await api.patch(`/todos/${todo.id}`, { status });
      toast.success(`Spostato in ${FOLDERS.find((f) => f.key === status).label}`);
    } catch { toast.error("Non sono riuscito a spostarlo"); setTodos(prev); }
  };

  const sheet = adding && <NewTodoSheet folder={adding} onClose={() => setAdding(null)} onCreated={reload} />;

  if (open) {
    const items = byFolder[open.key];
    return (
      <div data-testid={`folder-list-${open.key}`}>
        <button onClick={closeFolder} data-testid="folder-back" aria-label="Torna alle cartelle"
          className="lg-glass h-9 w-9 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
          <ArrowLeft size={17} />
        </button>
        <div className="flex items-end justify-between px-1 mt-5 mb-6">
          <div className="text-[44px] font-bold leading-none tracking-tight text-white">{open.label}<span style={{ color: ACCENT }}>.</span></div>
          <div className="text-[44px] font-light leading-none tabular-nums text-white/60">{items.length}</div>
        </div>
        <div className="flex items-center justify-between px-1 mb-4">
          <div className="kicker">{lastChange(items)}</div>
          <button onClick={() => setAdding(open)} data-testid="folder-list-add" aria-label={`Nuovo to do in ${open.label}`}
            className="lg-glass h-11 w-11 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
            <Plus size={20} />
          </button>
        </div>
        <div className="space-y-3">
          {items.length === 0 && <div className="text-center text-white/50 py-16 kicker">nessun to do</div>}
          {items.map((t) => (
            <TodoCard key={t.id} todo={t} onOpen={() => onOpenTodo(t)} onToggleFav={() => onToggleFav(t.id, !!t.favorite)}
              onDelete={() => onDelete(t.id)} onMove={(s) => moveTo(t, s)} />
          ))}
        </div>
        {sheet}
      </div>
    );
  }

  return (
    <div data-testid="todo-folders" className="todo-folders flex flex-col items-center justify-evenly"
      style={{ minHeight: "calc(100dvh - 3.5rem - 7rem - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px))" }}>
      <ClipDefs />
      {FOLDERS.map((f) => (
        <Folder key={f.key} folder={f} items={byFolder[f.key]} k={k}
          fan={fan?.key === f.key} hot={fan?.key === f.key ? fan.hot : -1} pinned={pinned === f.key}
          onFan={(hot) => { if (pinned && pinned !== f.key) setPinned(null); setFan((cur) => (cur?.key === f.key && cur.hot === hot ? cur : { key: f.key, hot })); }}
          onUnfan={() => setFan((cur) => (cur?.key === f.key ? null : cur))}
          onPin={() => { setFan(null); setPinned(f.key); }}
          onUnpin={() => setPinned((cur) => (cur === f.key ? null : cur))}
          onOpen={() => { setPinned(null); openFolder(f); }} onOpenTodo={onOpenTodo} onAdd={() => setAdding(f)} />
      ))}
      {sheet}
    </div>
  );
}
