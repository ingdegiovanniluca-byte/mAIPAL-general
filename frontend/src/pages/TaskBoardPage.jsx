import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  Calendar, CalendarCheck, Star, Trash2, CircleCheck, Bell, BellRing, Send, StickyNote, Wand2, Share2,
  Repeat, Link2, Plus, Check, ChevronDown, ChevronLeft, ChevronRight, MoreHorizontal, Clock, Flag, Type,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { useIsMobile } from "@/hooks/use-is-mobile";
import TodoDetail from "@/components/TodoDetail";
import { NewTodoSheet } from "@/components/TodoFolders";
import GlassBottomSheet from "@/components/GlassBottomSheet";
import GlassMenu, { GlassMenuItem } from "@/components/GlassMenu";
import { Field, Input, Select, PRIMARY } from "@/components/FormFields";

/* Task e To-Do, one section in the style of the diario di commessa: the big words on top choose the view
   (To-Do · Giornate · Calendario, a swipe or a tap on a side one changes it).
   GIORNATE: today always first, its tasks by the hour they start (an "Adesso" line where the time is now,
   the ones without an hour "In giornata"), then the late ones in their own box, then the next days under
   their month, each day with its number on the left; the round button on a row completes it, a tap on the
   row opens the task (the same card as before, with all its functions).
   TO-DO: the three states (Da fare, In corso, Fatto) as the diary's months, each with its "+"; a tap opens
   the to do's own full page, unchanged; "…" moves it, marks it done or deletes it.
   CALENDARIO: the month, and under it the tasks of the day chosen.
   On the computer, with room enough, Giornate (or Calendario) and To-Do side by side. */

const PRIORITY_RANK = { alta: 0, media: 1, bassa: 2 };
const PRIORITY_META = {
  alta: { label: "Alta", color: "#E8663F" },
  media: { label: "Media", color: "#F2B640" },
  bassa: { label: "Bassa", color: "#8FB3C9" },
};

const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const IT_MONTHS_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const IT_WD_LONG = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
const IT_WD_SHORT = ["DOM", "LUN", "MAR", "MER", "GIO", "VEN", "SAB"];

const formatDayMonth = (iso, time) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const day = d.getDate();
  const month = IT_MONTHS_LONG[d.getMonth()];
  return time ? `${time}, ${day} ${month}` : `${day} ${month}`;
};

const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const todayIso = () => isoOf(new Date());
const dateOf = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (iso, n) => { const d = dateOf(iso); d.setDate(d.getDate() + n); return isoOf(d); };
const hhmm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const shortDay = (iso, withYear) => {
  const d = dateOf(iso);
  return `${d.getDate()} ${IT_MONTHS_SHORT[d.getMonth()]}${withYear ? ` ${d.getFullYear()}` : ""}`;
};
// "Ieri", "24 nov", "3 ott 25": the day of a late task, short enough for the hour's column
const lateDay = (iso, today) => {
  if (iso === addDays(today, -1)) return "Ieri";
  const d = dateOf(iso);
  return d.getFullYear() !== dateOf(today).getFullYear() ? `${d.getDate()}/${d.getMonth() + 1}/${String(d.getFullYear()).slice(2)}` : shortDay(iso);
};

const isTaskOverdue = (t, today = todayIso()) => !!t.due_date && !t.completed && t.due_date < today;

// a day's tasks: those with an hour by the hour, then the ones "in giornata"; same hour, the higher priority first
const byHour = (a, b) => {
  const ta = a.due_time || "99:99", tb = b.due_time || "99:99";
  if (ta !== tb) return ta.localeCompare(tb);
  const pa = PRIORITY_RANK[a.priority] ?? 3, pb = PRIORITY_RANK[b.priority] ?? 3;
  if (pa !== pb) return pa - pb;
  return (a.created_at || "").localeCompare(b.created_at || "");
};

const VIEWS = [
  { key: "todo", label: "To-Do" },
  { key: "giornate", label: "Giornate" },
  { key: "calendario", label: "Calendario" },
];
const TODO_GROUPS = [
  { key: "da_fare", label: "Da fare", dot: "rgba(255,255,255,0.75)" },
  { key: "in_corso", label: "In corso", dot: "#36C5E0" },
  { key: "fatto", label: "Fatto", dot: "#FFAC33" },
];
const NEW_TODO_FOLDER = { da_fare: { key: "da_fare", label: "Da fare" }, in_corso: { key: "in_corso", label: "In corso" }, fatto: { key: "fatto", label: "Fatti" } };

// the width of the section (the chat column on the left takes part of the window on the computer)
function useWidth() {
  const ref = useRef(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    setW(el.offsetWidth);
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

// the time now, again every minute (the "Adesso" line moves on its own)
function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function TaskBoardPage() {
  const { user } = useAuth();
  const isMobile = useIsMobile();
  const [rootRef, width] = useWidth();
  const split = !isMobile && width >= 860;
  const now = useNow();
  const today = isoOf(now);
  const [tasks, setTasks] = useState([]);
  const [todos, setTodos] = useState([]);
  const [selected, setSelected] = useState(null);
  const [openTodo, setOpenTodo] = useState(null);
  const [orgMembers, setOrgMembers] = useState([]);
  const [status, setStatus] = useState("attivi");
  const [prio, setPrio] = useState("");
  const [tag, setTag] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [newTask, setNewTask] = useState(false);
  const [newTodo, setNewTodo] = useState(null);       // the state it goes in
  const [calDay, setCalDay] = useState(null);

  const [params, setParams] = useSearchParams();
  const view = VIEWS.some((v) => v.key === params.get("v")) ? params.get("v") : "giornate";
  const setView = (v) => setParams((p) => {
    const n = new URLSearchParams(p);
    if (v === "giornate") n.delete("v"); else n.set("v", v);
    return n;
  }, { replace: true });
  // on the computer the To-Do are always on the right: on the left Giornate or Calendario
  const leftView = split && view === "todo" ? "giornate" : view;

  const load = async () => {
    const r = await api.get("/tasks");
    setTasks(r.data);
  };
  const loadTodos = async () => {
    const r = await api.get("/todos");
    setTodos(r.data);
  };
  useEffect(() => { load(); loadTodos(); }, []);
  // Opened from a suggestion ("Oggi: «Palestra» alle 18:00") or from the chat: that task right away.
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const wanted = location.state?.openTask;
    if (wanted && tasks.some((t) => t.id === wanted)) {
      setSelected(wanted);
      navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks]);
  useEffect(() => {
    if (user?.org_id) api.get("/org").then((r) => setOrgMembers(r.data?.members || [])).catch(() => {});
    else setOrgMembers([]);
  }, [user?.org_id]);

  // ===== the task's quick actions (the rest is in its card) =====
  const toggleDone = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, completed: !cur, completed_at: cur ? null : new Date().toISOString() } : t)));
    try {
      await api.post(`/tasks/${id}/complete`);
      toast.success(cur ? "Riaperto" : "Task completato ✓");
      load();
    } catch { toast.error("Errore"); setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, completed: cur } : t))); }
  };

  // ===== the to dos' actions =====
  const sortTodos = (arr) => [...arr].sort((a, b) => {
    if (!!b.favorite !== !!a.favorite) return b.favorite ? 1 : -1;
    return (b.created_at || "").localeCompare(a.created_at || "");
  });
  const todoFav = async (id, cur) => {
    setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: !cur } : t)));
    try { await api.post(`/todos/${id}/favorite`); }
    catch { toast.error("Errore preferito"); setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: cur } : t))); }
  };
  const todoMove = async (todo, next) => {
    const prev = todos;
    setTodos((ts) => ts.map((t) => (t.id === todo.id ? { ...t, status: next } : t)));
    try {
      await api.patch(`/todos/${todo.id}`, { status: next });
      toast.success(`Spostato in ${TODO_GROUPS.find((g) => g.key === next).label}`);
    } catch { toast.error("Non sono riuscito a spostarlo"); setTodos(prev); }
  };
  const todoDelete = (id) => {
    toast("Eliminare questo to-do?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = todos;
          setTodos((ts) => ts.filter((t) => t.id !== id));
          try { await api.delete(`/todos/${id}`); toast.success("To-do eliminato"); }
          catch { toast.error("Errore eliminazione"); setTodos(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  // ===== the filters: priority, tag and favourites for both; Attivi / Completati for the tasks =====
  const allTags = Array.from(new Set([...tasks, ...todos].flatMap((t) => t.tags || []))).sort((a, b) => a.localeCompare(b));
  const keep = (t) => (!prio || t.priority === prio) && (!tag || (t.tags || []).includes(tag)) && (!favOnly || !!t.favorite);
  const shown = tasks.filter(keep);
  const shownTodos = todos.filter(keep);

  const selectedTask = tasks.find((t) => t.id === selected) || null;
  // one compact row: the small filters on the left, the "+" on the right
  const filters = (withStatus, add) => (
    <div className="flex items-center gap-1.5" data-testid="task-filters">
      <div className="flex items-center gap-1.5 min-w-0 flex-1 overflow-hidden">
        {withStatus && (
          <PillSelect label="Attivi o completati" value={status === "attivi" ? "" : status} onChange={(v) => setStatus(v || "attivi")} testid="filter-status"
            options={[["", "Attivi"], ["completati", "Fatti"]]} />
        )}
        <PillSelect label="Priorità" value={prio} onChange={setPrio} testid="filter-priority"
          options={[["", "Priorità"], ["alta", "Alta"], ["media", "Media"], ["bassa", "Bassa"]]} />
        {allTags.length > 0 && (
          <PillSelect label="Tag" value={tag} onChange={setTag} testid="filter-tag"
            options={[["", "#"], ...allTags.map((x) => [x, `#${x}`])]} />
        )}
        <button type="button" data-testid="filter-fav" aria-pressed={favOnly} aria-label="Solo preferiti" title="Solo preferiti"
          onClick={() => setFavOnly((v) => !v)}
          className={`h-7 w-7 shrink-0 rounded-full border flex items-center justify-center ${favOnly ? "bg-white/85 border-white/50 text-[#7A2A5C]" : "bg-white/10 border-white/15 text-white/75"}`}>
          <Star size={13} strokeWidth={1.8} className={favOnly ? "fill-current" : ""} />
        </button>
      </div>
      {add}
    </div>
  );
  const addBtn = (label, onClick, testid) => (
    <button type="button" onClick={onClick} data-testid={testid} aria-label={label} title={label}
      className="h-7 shrink-0 pl-2 pr-3 rounded-full bg-white/85 text-[#7A2A5C] text-[12px] font-semibold inline-flex items-center gap-1">
      <Plus size={14} strokeWidth={2.4} /> {label.replace("Nuovo ", "")}
    </button>
  );

  const giornate = (
    <Giornate tasks={shown} status={status} now={now} today={today} onOpen={setSelected} onToggleDone={toggleDone} />
  );
  const calendario = (
    <MonthView tasks={shown} today={today} day={calDay || today} onDay={setCalDay} onOpen={setSelected} onToggleDone={toggleDone} />
  );
  const todoView = (
    <TodoGroups todos={shownTodos} sortTodos={sortTodos} onOpen={setOpenTodo} onAdd={(s) => setNewTodo(NEW_TODO_FOLDER[s])}
      onMove={todoMove} onDelete={todoDelete} onToggleFav={todoFav} />
  );
  const sheets = (
    <>
      {selectedTask && (
        <TaskDialog task={selectedTask} orgMembers={orgMembers} onClose={() => setSelected(null)} onUpdated={async () => { await load(); }} />
      )}
      {openTodo && <TodoDetail todo={openTodo} onClose={() => setOpenTodo(null)} onUpdated={loadTodos} />}
      {newTask && <NewTaskSheet today={today} onClose={() => setNewTask(false)} onCreated={load} />}
      {newTodo && <NewTodoSheet folder={newTodo} onClose={() => setNewTodo(null)} onCreated={loadTodos} />}
    </>
  );

  // one box around both layouts, so the width is always measured on the same element
  return (
    <div ref={rootRef} className="w-full pb-10" data-testid="task-page">
      {split ? (
        <>
          <div className="max-w-[520px]">{filters(true, null)}</div>
          <div className="mt-6 grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-10 items-start">
            <div className="min-w-0">
              <div className="flex items-baseline gap-6 mb-4" data-testid="view-tabs">
                {VIEWS.filter((v) => v.key !== "todo").map((v) => (
                  <button key={v.key} type="button" onClick={() => setView(v.key)} data-testid={`view-${v.key}`} aria-current={leftView === v.key ? "page" : undefined}
                    className={leftView === v.key ? "text-[30px] font-semibold tracking-tight text-white/[0.68]" : "text-[16px] font-medium text-white/50 hover:text-white/75"}>
                    {v.label}
                  </button>
                ))}
                <span className="ml-auto self-center">{addBtn("Nuovo task", () => setNewTask(true), "new-task-btn")}</span>
              </div>
              {leftView === "calendario" ? calendario : giornate}
            </div>
            <div className="min-w-0">
              <div className="mb-4 flex items-center justify-between">
                <span className="text-[30px] font-semibold tracking-tight text-white/[0.68]" data-testid="todo-pane-title">To-Do</span>
                {addBtn("Nuovo to-do", () => setNewTodo(NEW_TODO_FOLDER.da_fare), "new-todo-btn")}
              </div>
              {todoView}
            </div>
          </div>
        </>
      ) : (
        <>
          <ViewCarousel view={view} onView={setView} />
          <div className="mt-3">
            {filters(view !== "todo", view === "todo"
              ? addBtn("Nuovo to-do", () => setNewTodo(NEW_TODO_FOLDER.da_fare), "new-todo-btn")
              : addBtn("Nuovo task", () => setNewTask(true), "new-task-btn"))}
          </div>
          <div className="mt-5">
            {view === "todo" ? todoView : view === "calendario" ? calendario : giornate}
          </div>
        </>
      )}
      {sheets}
    </div>
  );
}

// the views, like the diary's sections: the chosen one in the middle, big; a swipe or a tap on a side one changes it
function ViewCarousel({ view, onView }) {
  const x0 = useRef(null);
  const i = VIEWS.findIndex((v) => v.key === view);
  const at = (k) => VIEWS[(k + VIEWS.length) % VIEWS.length];
  return (
    <div className="mt-1 -mx-4 h-[46px] flex items-center justify-center gap-[22px] overflow-hidden select-none" data-testid="view-tabs"
      onTouchStart={(e) => { x0.current = e.touches?.[0]?.clientX ?? null; }}
      onTouchEnd={(e) => {
        if (x0.current == null) return;
        const dx = (e.changedTouches?.[0]?.clientX ?? x0.current) - x0.current;
        x0.current = null;
        if (Math.abs(dx) > 40) onView(at(i + (dx < 0 ? 1 : -1)).key);
      }}
      style={{ WebkitMaskImage: "linear-gradient(to right, transparent 0, #000 18%, #000 82%, transparent 100%)", maskImage: "linear-gradient(to right, transparent 0, #000 18%, #000 82%, transparent 100%)" }}>
      <button type="button" onClick={() => onView(at(i - 1).key)} data-testid={`view-${at(i - 1).key}`}
        className="flex-1 basis-0 text-right text-[15px] font-medium text-white/30">{at(i - 1).label}</button>
      <h2 className="shrink-0 m-0 text-[30px] font-semibold tracking-tight text-white/[0.68]" data-testid="view-current"
        style={{ textShadow: "0 2px 16px rgba(60,10,60,0.18)" }}>{at(i).label}</h2>
      <button type="button" onClick={() => onView(at(i + 1).key)} data-testid={`view-${at(i + 1).key}`}
        className="flex-1 basis-0 text-left text-[15px] font-medium text-white/30">{at(i + 1).label}</button>
    </div>
  );
}

// a small dropdown in the filters row: a little pill with what is chosen; the phone's own picker opens on it
// (the native list stays invisible on top, at its own size, so the iPhone never zooms in)
function PillSelect({ label, value, onChange, options, testid }) {
  const cur = options.find(([k]) => k === value) || options[0];
  return (
    <label className={`relative h-7 shrink-0 max-w-[112px] rounded-full border pl-2.5 pr-6 flex items-center text-[12px] cursor-pointer ${value ? "bg-white/25 border-white/40 text-white" : "bg-white/10 border-white/15 text-white/80"}`}>
      <span className="truncate">{cur[1]}</span>
      <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-white/60 pointer-events-none" />
      <select aria-label={label} value={value} data-testid={testid} onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer">
        {options.map(([k, l]) => <option key={k} value={k} className="text-black">{l}</option>)}
      </select>
    </label>
  );
}

/* The type, as in the diario di commessa: the day's number 14px (two digits) in a 34px column, the month's line 11px
   in capitals spaced out, the days split by a thin line, the meta line 11.5px, the text 14px medium, the round tick
   of 20px (green when done, as the activities of the diary). */
const DAY_ROW = "grid grid-cols-[34px_minmax(0,1fr)] gap-x-3 py-3 border-t border-white/[0.16]";
const LINE_ROW = "py-3 border-t border-white/[0.16]";

// the day on the left of its tasks: the number (as in the diary) and, under it, the weekday
function DayNum({ iso }) {
  const d = dateOf(iso);
  return (
    <div className="flex flex-col">
      <span className="text-[14px] font-medium leading-[1.45] text-white/90 tabular-nums">{String(d.getDate()).padStart(2, "0")}</span>
      <span className="text-[10.5px] leading-tight text-white/45">{IT_WD_SHORT[d.getDay()].toLowerCase()}</span>
    </div>
  );
}

// the line on top of a block (Oggi, a month, Da fare...), as the diary's month: the words and, on the right, how many
function BlockHead({ children, right, testid, className = "text-white/60" }) {
  return (
    <div className="flex items-center justify-between gap-3 pt-4 pb-1.5" data-testid={testid}>
      <span className={`flex items-center gap-2 min-w-0 text-[11px] font-medium tracking-[0.18em] uppercase whitespace-nowrap ${className}`}>{children}</span>
      {right != null && <span className="shrink-0 text-[11px] text-white/50">{right}</span>}
    </div>
  );
}

// one task, as an entry of the diary: the hour and the priority on the small line, the title under it; the round
// tick on the right completes it
function TaskRow({ task, onOpen, onToggleDone, when, whenClass = "text-white/50", line = false }) {
  const prio = PRIORITY_META[task.priority];
  const done = !!task.completed;
  return (
    <div className={`flex items-start gap-3 ${line ? LINE_ROW : ""}`} data-testid={`task-${task.id}`}>
      <button type="button" onClick={onOpen} className="flex-1 min-w-0 text-left" data-testid="task-open">
        <span className={`flex items-center gap-[5px] text-[11.5px] font-medium tabular-nums ${whenClass}`}>
          {prio && <span className="inline-block w-[6px] h-[6px] rounded-full" style={{ background: prio.color }} title={`Priorità ${prio.label.toLowerCase()}`} />}
          {when ?? (task.due_time || "in giornata")}
        </span>
        <span className={`block mt-[3px] text-[14px] font-medium leading-snug break-words ${done ? "line-through text-white/45" : "text-white"}`}>{task.title}</span>
      </button>
      <button type="button" data-testid="task-complete" onClick={onToggleDone} aria-label={done ? "Fatto: tocca per riaprirlo" : "Segna come fatto"}
        title={done ? "Riapri" : "Segna come fatto"}
        className={`mt-[3px] h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${done ? "bg-[#8ED973] text-[#1F4D17]" : "bg-white/20"}`}>
        {done && <Check size={12} strokeWidth={2.8} />}
      </button>
    </div>
  );
}

// tasks grouped by month and day (the next days; the completed ones, newest first)
function MonthsAndDays({ tasks, dayOf, desc, rowProps, today }) {
  const days = [];
  [...tasks].sort((a, b) => {
    const da = dayOf(a), db_ = dayOf(b);
    if (da !== db_) return desc ? db_.localeCompare(da) : da.localeCompare(db_);
    return byHour(a, b);
  }).forEach((t) => {
    const d = dayOf(t);
    const g = days[days.length - 1];
    if (g && g.day === d) g.items.push(t); else days.push({ day: d, items: [t] });
  });
  const months = [];
  days.forEach((g) => {
    const key = g.day.slice(0, 7);
    const m = months[months.length - 1];
    if (m && m.key === key) m.days.push(g); else months.push({ key, days: [g] });
  });
  const year = dateOf(today).getFullYear();
  return months.map((m) => {
    const [y, mo] = m.key.split("-").map(Number);
    return (
      <section key={m.key} className="flex flex-col" data-testid={`month-${m.key}`}>
        <BlockHead>{IT_MONTHS_LONG[mo - 1]}{y !== year ? ` ${y}` : ""}</BlockHead>
        {m.days.map((g) => (
          <div key={g.day} className={DAY_ROW} data-testid={`day-${g.day}`}>
            <DayNum iso={g.day} />
            <div className="flex flex-col gap-3">
              {g.items.map((t) => <TaskRow key={t.id} task={t} {...rowProps(t)} />)}
            </div>
          </div>
        ))}
      </section>
    );
  });
}

function Giornate({ tasks, status, now, today, onOpen, onToggleDone }) {
  const [allLate, setAllLate] = useState(false);
  const rowProps = (t) => ({ onOpen: () => onOpen(t.id), onToggleDone: () => onToggleDone(t.id, !!t.completed) });

  if (status === "completati") {
    const done = tasks.filter((t) => t.completed);
    const dayOf = (t) => (t.completed_at ? isoOf(new Date(t.completed_at)) : t.due_date || today);
    return (
      <div className="flex flex-col gap-5" data-testid="giornate">
        {done.length === 0 && <div className="text-center text-white/60 text-[14px] py-10">Nessun task completato.</div>}
        <MonthsAndDays tasks={done} dayOf={dayOf} desc today={today} rowProps={rowProps} />
      </div>
    );
  }

  const nowHm = hhmm(now);
  const todays = tasks.filter((t) => t.due_date === today).sort(byHour);
  const late = tasks.filter((t) => isTaskOverdue(t, today)).sort((a, b) => b.due_date.localeCompare(a.due_date) || byHour(a, b));
  const next = tasks.filter((t) => !t.completed && t.due_date && t.due_date > today);
  const undated = tasks.filter((t) => !t.completed && !t.due_date).sort((a, b) => (PRIORITY_RANK[a.priority] ?? 3) - (PRIORITY_RANK[b.priority] ?? 3) || (b.created_at || "").localeCompare(a.created_at || ""));
  // where the "Adesso" line goes: before the first task with an hour still to come (after the last one with an hour, if none)
  const timed = todays.filter((t) => t.due_time);
  let nowAt = timed.findIndex((t) => t.due_time > nowHm);
  if (nowAt < 0) nowAt = timed.length;
  const nowLine = (
    <div key="now" className="flex items-center gap-2 text-[10.5px] font-medium tracking-[0.14em] uppercase tt-now" data-testid="now-line">
      <span className="w-[7px] h-[7px] rounded-full tt-now-bg" />
      <span className="flex-1 h-px tt-now-bg opacity-70" />
      Adesso {nowHm}
    </div>
  );
  const todayRows = [];
  todays.forEach((t, k) => {
    if (k === nowAt && t.due_time) todayRows.push(nowLine);
    todayRows.push(<TaskRow key={t.id} task={t} {...rowProps(t)} />);
    if (k === timed.length - 1 && nowAt === timed.length) todayRows.push(nowLine);
  });
  if (!timed.length && todays.length) todayRows.unshift(nowLine);
  const d = dateOf(today);
  const lateShown = allLate ? late : late.slice(0, 3);

  return (
    <div className="flex flex-col gap-2" data-testid="giornate">
      {/* TODAY: always first, by the hour they start */}
      <section className="flex flex-col" data-testid="giornate-oggi">
        <BlockHead className="text-white/85">
          <span className="w-[6px] h-[6px] rounded-full tt-now-bg shrink-0" />Oggi
        </BlockHead>
        <div className={DAY_ROW}>
          <DayNum iso={today} />
          <div className="flex flex-col gap-3">
            {todayRows}
            {todays.length === 0 && <div className="text-[14px] leading-[1.45] text-white/60" data-testid="today-empty">Niente in programma per oggi.</div>}
          </div>
        </div>
      </section>

      {/* LATE: right after today */}
      {late.length > 0 && (
        <section className="tt-late-box rounded-[20px] px-4 py-3.5" data-testid="giornate-scaduti">
          <div className="text-[11px] font-medium tracking-[0.18em] uppercase tt-late">Scaduti · {late.length}</div>
          <div className="mt-3 flex flex-col gap-3">
            {lateShown.map((t) => (
              <TaskRow key={t.id} task={t} {...rowProps(t)} whenClass="tt-late" when={`${lateDay(t.due_date, today)}${t.due_time ? ` · ${t.due_time}` : ""}`} />
            ))}
          </div>
          {late.length > 3 && (
            <button type="button" onClick={() => setAllLate((v) => !v)} data-testid="late-more" className="mt-3 text-[12px] font-medium tt-late">
              {allLate ? "Mostra meno" : `Mostra tutti (${late.length})`}
            </button>
          )}
        </section>
      )}

      {/* the next days, by month, as in the diario di commessa */}
      <MonthsAndDays tasks={next} dayOf={(t) => t.due_date} today={today} rowProps={rowProps} />

      {undated.length > 0 && (
        <section className="flex flex-col" data-testid="giornate-senza-data">
          <BlockHead>Senza data</BlockHead>
          <div className="flex flex-col">
            {undated.map((t) => <TaskRow key={t.id} task={t} {...rowProps(t)} when="senza data" line />)}
          </div>
        </section>
      )}

    </div>
  );
}

// the month as a grid (week numbers on the left, the priority of the day's open tasks as dots); under it the chosen day
function MonthView({ tasks, today, day, onDay, onOpen, onToggleDone }) {
  const [month, setMonth] = useState(() => day.slice(0, 7));
  useEffect(() => { setMonth(day.slice(0, 7)); }, [day]);
  const [y, m] = month.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(y, m - 1, 1 - lead);
  const weeks = [];
  for (let w = 0; w < 6; w++) {
    const row = [];
    for (let k = 0; k < 7; k++) {
      const dd = new Date(start);
      dd.setDate(start.getDate() + w * 7 + k);
      row.push(isoOf(dd));
    }
    if (w > 3 && row[0].slice(0, 7) !== month) break;
    weeks.push(row);
  }
  const byDay = {};
  tasks.forEach((t) => { if (t.due_date) (byDay[t.due_date] = byDay[t.due_date] || []).push(t); });
  const shift = (n) => { const dt = new Date(y, m - 1 + n, 1); setMonth(isoOf(dt).slice(0, 7)); };
  const dayTasks = (byDay[day] || []).slice().sort(byHour);
  const dd = dateOf(day);
  return (
    <div className="flex flex-col gap-5" data-testid="calendario">
      <div className="card-soft p-4">
        <div className="flex items-center justify-between">
          <button type="button" onClick={() => shift(-1)} aria-label="Mese prima" data-testid="cal-prev" className="h-9 w-9 rounded-full bg-white/10 flex items-center justify-center text-white"><ChevronLeft size={18} /></button>
          <div className="text-[15px] font-semibold text-white capitalize" data-testid="cal-month">{IT_MONTHS_LONG[m - 1]} {y}</div>
          <button type="button" onClick={() => shift(1)} aria-label="Mese dopo" data-testid="cal-next" className="h-9 w-9 rounded-full bg-white/10 flex items-center justify-center text-white"><ChevronRight size={18} /></button>
        </div>
        <div className="mt-3 grid grid-cols-7 gap-y-1 text-center">
          {["L", "M", "M", "G", "V", "S", "D"].map((w, k) => <span key={k} className="text-[11px] text-white/55 py-1">{w}</span>)}
          {weeks.map((row) => (
            <React.Fragment key={row[0]}>
              {row.map((iso) => {
                const inMonth = iso.slice(0, 7) === month;
                const open = (byDay[iso] || []).filter((t) => !t.completed);
                const dots = Array.from(new Set(open.map((t) => t.priority))).sort((a, b) => (PRIORITY_RANK[a] ?? 3) - (PRIORITY_RANK[b] ?? 3)).slice(0, 3);
                const isToday = iso === today, isSel = iso === day;
                return (
                  <button key={iso} type="button" onClick={() => onDay(iso)} data-testid={`cal-day-${iso}`} aria-pressed={isSel}
                    className={`mx-auto h-11 w-10 rounded-xl flex flex-col items-center justify-center gap-1 ${inMonth ? "" : "opacity-35"} ${isSel && !isToday ? "ring-2 ring-white/70" : ""} ${isToday ? "bg-white/85" : ""}`}>
                    <span className={`text-[14px] leading-none tabular-nums ${isToday ? "text-[#7A2A5C] font-semibold" : "text-white"}`}>{dateOf(iso).getDate()}</span>
                    <span className="flex gap-0.5 h-[5px]">
                      {dots.map((p) => <span key={p} className="w-[5px] h-[5px] rounded-full" style={{ background: PRIORITY_META[p]?.color || "rgba(255,255,255,.6)" }} />)}
                    </span>
                  </button>
                );
              })}
            </React.Fragment>
          ))}
        </div>
      </div>
      <section className="flex flex-col" data-testid="cal-day-list">
        <BlockHead className="text-white/85">
          {day === today ? "Oggi · " : ""}{IT_WD_LONG[dd.getDay()]} {dd.getDate()} {IT_MONTHS_LONG[dd.getMonth()]}
        </BlockHead>
        <div className="flex flex-col">
          {dayTasks.map((t) => (
            <TaskRow key={t.id} task={t} line onOpen={() => onOpen(t.id)} onToggleDone={() => onToggleDone(t.id, !!t.completed)} />
          ))}
          {dayTasks.length === 0 && <div className={`${LINE_ROW} text-[14px] leading-[1.45] text-white/60`}>Nessun task in questo giorno.</div>}
        </div>
      </section>
    </div>
  );
}

// the to dos' three states, like the diary's months: the title with how many and its "+", then the rows
function TodoGroups({ todos, sortTodos, onOpen, onAdd, onMove, onDelete, onToggleFav }) {
  const [allDone, setAllDone] = useState(false);
  return (
    <div className="flex flex-col gap-2" data-testid="todo-groups">
      {TODO_GROUPS.map((g) => {
        const items = sortTodos(todos.filter((t) => t.status === g.key));
        const list = g.key === "fatto" && !allDone ? items.slice(0, 5) : items;
        return (
          <section key={g.key} className="flex flex-col" data-testid={`todo-group-${g.key}`}>
            <div className="flex items-center justify-between gap-3 pt-4 pb-1.5">
              <span className="flex items-center gap-2 text-[11px] font-medium tracking-[0.18em] uppercase text-white/60 whitespace-nowrap">
                <span className="w-[6px] h-[6px] rounded-full" style={{ background: g.dot }} />{g.label} <span className="text-white/45" data-testid={`todo-count-${g.key}`}>{items.length}</span>
              </span>
              <button type="button" onClick={() => onAdd(g.key)} data-testid={`todo-add-${g.key}`} aria-label={`Nuovo to-do in ${g.label}`} title={`Nuovo to-do in ${g.label}`}
                className="h-7 w-7 rounded-full bg-white/15 text-white flex items-center justify-center">
                <Plus size={14} />
              </button>
            </div>
            {list.map((t) => (
              <TodoRow key={t.id} todo={t} onOpen={() => onOpen(t)} onMove={(s) => onMove(t, s)} onDelete={() => onDelete(t.id)} onToggleFav={() => onToggleFav(t.id, !!t.favorite)} />
            ))}
            {items.length === 0 && <div className={`${LINE_ROW} text-[14px] leading-[1.45] text-white/50`}>Nessuno</div>}
            {g.key === "fatto" && items.length > 5 && (
              <button type="button" onClick={() => setAllDone((v) => !v)} data-testid="todo-done-more" className="mt-1 self-start text-[12px] font-medium text-white/70">
                {allDone ? "Mostra meno" : `Mostra tutti (${items.length})`}
              </button>
            )}
          </section>
        );
      })}
    </div>
  );
}

function TodoRow({ todo, onOpen, onMove, onDelete, onToggleFav }) {
  const btn = useRef(null);
  const panel = useRef(null);
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    if (!menu) return undefined;
    const close = (e) => { if (!panel.current?.contains(e.target) && !btn.current?.contains(e.target)) setMenu(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menu]);
  const prio = PRIORITY_META[todo.priority];
  const steps = todo.steps || [];
  const stepsDone = steps.filter((x) => x.done).length;
  const pct = steps.length ? Math.round((stepsDone / steps.length) * 100) : todo.completion_percent || 0;
  const done = todo.status === "fatto";
  const pick = (fn) => () => { setMenu(false); fn(); };
  // one line: the priority as a dot, the title, how many steps are done; in corso a thin bar under it
  return (
    <div className={`flex items-start gap-2 ${LINE_ROW}`} data-testid={`todo-${todo.id}`}>
      <button type="button" onClick={onOpen} className="flex-1 min-w-0 text-left flex flex-col gap-1.5" data-testid="todo-open">
        <span className="flex items-baseline gap-2 min-w-0">
          <span className={`min-w-0 flex-1 text-[14px] font-medium leading-snug break-words ${done ? "line-through text-white/45" : "text-white"}`}>
            {prio && <span className="inline-block w-[6px] h-[6px] rounded-full mr-2 align-middle -mt-0.5" style={{ background: prio.color }} title={`Priorità ${prio.label.toLowerCase()}`} />}
            {todo.title}
            {todo.favorite && <Star size={12} className="inline ml-1.5 -mt-0.5 fill-current text-white/60" aria-label="Preferito" />}
          </span>
          {steps.length > 0 && <span className="shrink-0 text-[11.5px] font-medium text-white/50 tabular-nums" title="Passi fatti" data-testid="todo-steps">{stepsDone}/{steps.length}</span>}
        </span>
        {todo.status === "in_corso" && pct > 0 && (
          <span className="block h-[3px] rounded-full bg-white/20 overflow-hidden" title={`${pct}%`}>
            <span className="block h-full rounded-full bg-white/85" style={{ width: `${pct}%` }} />
          </span>
        )}
      </button>
      <button ref={btn} type="button" onClick={() => setMenu((v) => !v)} data-testid="todo-menu" aria-label="Sposta, segna fatto o elimina" aria-expanded={menu}
        className="-mt-1 h-7 w-7 shrink-0 rounded-full text-white/60 hover:bg-white/10 flex items-center justify-center">
        <MoreHorizontal size={16} />
      </button>
      {menu && (
        <GlassMenu anchorRef={btn} panelRef={panel} testid="todo-move-menu" width={236}>
          <div className="px-5 pt-2.5 pb-1 text-[11px] tracking-[0.16em] uppercase text-white/55">Sposta in</div>
          {TODO_GROUPS.filter((g) => g.key !== todo.status).map((g) => (
            <GlassMenuItem key={g.key} icon={g.key === "fatto" ? CircleCheck : g.key === "in_corso" ? Clock : Flag} label={g.label}
              testid={`move-to-${g.key}`} onClick={pick(() => onMove(g.key))} />
          ))}
          <GlassMenuItem icon={Star} label={todo.favorite ? "Togli dai preferiti" : "Aggiungi ai preferiti"} testid="todo-fav" onClick={pick(onToggleFav)} />
          <GlassMenuItem icon={Trash2} label="Elimina" danger testid="todo-delete" onClick={pick(onDelete)} />
        </GlassMenu>
      )}
    </div>
  );
}

// a new task written by hand: what, the day and the hour, the priority (the rest in its card, once it exists)
function NewTaskSheet({ today, onClose, onCreated }) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(today);
  const [time, setTime] = useState("");
  const [priority, setPriority] = useState("media");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const r = await api.post("/tasks", { title: title.trim(), due_date: date || null, priority });
      if (date && time) await api.patch(`/tasks/${r.data.id}`, { due_time: time });
      toast.success("Task aggiunto");
      await onCreated();
      onClose();
    } catch (e) { toast.error(e.response?.data?.detail || "Non sono riuscito a salvare il task"); }
    finally { setBusy(false); }
  };
  return (
    <GlassBottomSheet onClose={onClose} testid="task-new-sheet" className="max-h-[88vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-xl font-semibold text-white mb-4">Nuovo task</div>
      <div className="flex flex-col gap-4">
        <Field label="Cosa">
          <Input icon={Type} autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") save(); }}
            placeholder="Es. Chiamare il commercialista" data-testid="task-new-title" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quando">
            <Input icon={Calendar} type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="task-new-date" />
          </Field>
          <Field label="Alle">
            <Input icon={Clock} type="time" value={time} disabled={!date} onChange={(e) => setTime(e.target.value)} data-testid="task-new-time" />
          </Field>
        </div>
        <Field label="Priorità">
          <Select icon={Flag} value={priority} onChange={setPriority} testid="task-new-priority"
            options={[["alta", "Alta"], ["media", "Media"], ["bassa", "Bassa"]]} />
        </Field>
        <button type="button" onClick={save} disabled={busy || !title.trim()} data-testid="task-new-save" className={`${PRIMARY} w-full`}>
          {busy ? "…" : "Aggiungi il task"}
        </button>
        <div className="text-[12px] text-white/55 text-center">Ripetizione, promemoria, calendario e condivisione si impostano aprendo il task.</div>
      </div>
    </GlassBottomSheet>
  );
}

const TAG_BG = "rgba(131, 108, 96, 0.3)";

// Deleting an occurrence of a recurring task asks what to delete: just this one, or this and
// every following one (which also stops the repetition).
const askDeleteTask = (task, doDelete) => {
  if (!task.recurrence_label) {
    toast("Eliminare questo task?", {
      action: { label: "Elimina", onClick: () => doDelete("one") },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
    return;
  }
  toast.custom((id) => (
    <div data-testid="recurring-delete-toast" className="rounded-2xl bg-[#2A2429] text-white p-4 shadow-xl w-[356px] max-w-[calc(100vw-2rem)]" style={{ fontFamily: "'Poppins', sans-serif" }}>
      <div className="text-sm font-medium">Eliminare questo task ricorrente?</div>
      <div className="text-xs text-white/60 mt-1 flex items-center gap-1.5"><Repeat size={11} />{task.recurrence_label}</div>
      <div className="flex flex-wrap gap-2 mt-3">
        <button data-testid="delete-one" onClick={() => { toast.dismiss(id); doDelete("one"); }} className="text-xs px-3 py-1.5 rounded-full bg-white/10 hover:bg-white/20">Solo questo</button>
        <button data-testid="delete-following" onClick={() => { toast.dismiss(id); doDelete("following"); }} className="text-xs px-3 py-1.5 rounded-full bg-red-500/25 hover:bg-red-500/35 text-red-100">Questo e i successivi</button>
        <button onClick={() => toast.dismiss(id)} className="text-xs px-3 py-1.5 rounded-full text-white/60 hover:text-white">Annulla</button>
      </div>
    </div>
  ), { duration: 10000 });
};

// "Da: Nota del 29 set" - where a task created by a tagged agent (@task) came from.
function SourceRow({ source }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  if (!source) return null;
  const label = source.label || "Chat";
  const canOpenChat = !!source.conv_id && !String(source.conv_id).startsWith("agents_") && !String(source.conv_id).startsWith("tg_");
  return (
    <div className="mt-1.5 text-sm" style={{ color: "#D9D9D9" }} data-testid="task-source">
      <button
        onClick={() => (source.preview ? setOpen((v) => !v) : canOpenChat && navigate("/dashboard/chat", { state: { openConv: source.conv_id } }))}
        className="flex items-center gap-1.5 hover:underline decoration-dotted underline-offset-2"
        title="Da dove è nato questo task"
      >
        <Link2 size={14} /> Da: {label}
      </button>
      {open && (
        <div className="mt-2 rounded-xl px-3 py-2 text-xs text-white/85 whitespace-pre-wrap" style={{ background: TAG_BG }}>
          {source.preview}
          {canOpenChat && (
            <button onClick={() => navigate("/dashboard/chat", { state: { openConv: source.conv_id } })} className="block mt-2 text-[11px] underline text-white/70">
              Apri la chat
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const RECUR_FREQS = [
  { key: "none", label: "Mai" },
  { key: "daily", label: "Giorno", unit: ["giorno", "giorni"] },
  { key: "weekly", label: "Settimana", unit: ["settimana", "settimane"] },
  { key: "monthly", label: "Mese", unit: ["mese", "mesi"] },
  { key: "yearly", label: "Anno", unit: ["anno", "anni"] },
];
const WEEKDAY_INITIALS = ["L", "M", "M", "G", "V", "S", "D"];
const WEEKDAY_NAMES = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"];

// "Ripeti" row of the task detail: shows the current repetition and edits it inline.
function RecurrenceRow({ task, onUpdated }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const start = task.due_date ? new Date(`${task.due_date}T12:00:00`) : null;
  const startWeekday = start ? (start.getDay() + 6) % 7 : 0;
  const [freq, setFreq] = useState("none");
  const [interval, setIntervalN] = useState(1);
  const [weekdays, setWeekdays] = useState([startWeekday]);
  const [lastDay, setLastDay] = useState(false);
  const [endMode, setEndMode] = useState("never");
  const [until, setUntil] = useState("");
  const [count, setCount] = useState(10);

  const openEditor = async () => {
    setFreq("none"); setIntervalN(1); setWeekdays([startWeekday]); setLastDay(false); setEndMode("never"); setUntil(""); setCount(10);
    if (task.recurrence_label) {
      try {
        const r = await api.get(`/tasks/${task.id}/recurrence`);
        const rule = r.data?.series?.rule;
        if (rule) {
          setFreq(rule.freq);
          setIntervalN(rule.interval || 1);
          if (rule.weekdays) setWeekdays(rule.weekdays);
          setLastDay(rule.day_of_month === -1);
          if (rule.until) { setEndMode("until"); setUntil(rule.until); }
          else if (rule.count) { setEndMode("count"); setCount(rule.count); }
        }
      } catch { /* editor opens with defaults */ }
    }
    setOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      let rule = null;
      if (freq !== "none") {
        rule = { freq, interval: Math.max(1, Math.min(99, Number(interval) || 1)) };
        if (freq === "weekly") rule.weekdays = weekdays.length ? weekdays : [startWeekday];
        if (freq === "monthly") rule.day_of_month = lastDay ? -1 : start.getDate();
        if (endMode === "until" && until) rule.until = until;
        if (endMode === "count") rule.count = Math.max(1, Number(count) || 1);
      }
      if (!rule && !task.recurrence_label) { setOpen(false); return; }
      await api.put(`/tasks/${task.id}/recurrence`, { rule });
      await onUpdated();
      toast.success(rule ? "Ripetizione salvata" : "Il task non si ripete più");
      setOpen(false);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  const chip = (active) => `text-xs px-2.5 py-1 rounded-full transition-colors ${active ? "bg-[#00B0F0]/25 text-[#00B0F0]" : "bg-white/10 text-white/80 hover:bg-white/15"}`;
  const unit = RECUR_FREQS.find((f) => f.key === freq)?.unit;

  if (!open) {
    return (
      <button
        onClick={task.due_date ? openEditor : undefined}
        data-testid="task-recurrence-display"
        className={`flex items-center gap-1.5 mt-1.5 text-sm ${task.due_date ? "hover:underline decoration-dotted underline-offset-2" : "cursor-default opacity-60"}`}
        style={{ color: "#D9D9D9" }}
        title={task.due_date ? "Imposta la ripetizione" : "Aggiungi prima una data per poterlo ripetere"}
      >
        <Repeat size={14} />
        {task.recurrence_label || (task.due_date ? "Non si ripete" : "Non si ripete · serve una data")}
      </button>
    );
  }

  return (
    <div className="mt-2 rounded-2xl p-3 space-y-3" style={{ background: TAG_BG }} data-testid="task-recurrence-editor">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-white/60"><Repeat size={12} /> Ripeti</div>
      <div className="flex flex-wrap gap-1.5">
        {RECUR_FREQS.map((f) => (
          <button key={f.key} data-testid={`recur-${f.key}`} onClick={() => setFreq(f.key)} className={chip(freq === f.key)}>{f.label}</button>
        ))}
      </div>
      {freq !== "none" && (
        <>
          <div className="flex items-center gap-2 text-xs text-white/80">
            Ogni
            <input
              type="number" min={1} max={99} value={interval}
              onChange={(e) => setIntervalN(e.target.value)}
              data-testid="recur-interval"
              className="w-14 bg-white/10 rounded-lg px-2 py-1 text-white text-xs border-0 outline-none"
            />
            {Number(interval) === 1 ? unit?.[0] : unit?.[1]}
          </div>
          {freq === "weekly" && (
            <div className="flex gap-1.5">
              {WEEKDAY_INITIALS.map((w, i) => {
                const on = weekdays.includes(i);
                return (
                  <button
                    key={i}
                    data-testid={`recur-wd-${i}`}
                    title={WEEKDAY_NAMES[i]}
                    onClick={() => setWeekdays((ws) => (on ? ws.filter((x) => x !== i) : [...ws, i].sort()))}
                    className={`h-8 w-8 rounded-full text-xs font-semibold ${on ? "bg-[#00B0F0] text-white" : "bg-white/10 text-white/70"}`}
                  >
                    {w}
                  </button>
                );
              })}
            </div>
          )}
          {freq === "monthly" && start && (
            <div className="flex flex-wrap gap-1.5">
              <button onClick={() => setLastDay(false)} className={chip(!lastDay)}>Il giorno {start.getDate()}</button>
              <button onClick={() => setLastDay(true)} className={chip(lastDay)}>L'ultimo giorno del mese</button>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-white/60 mr-1">Termina</span>
            <button onClick={() => setEndMode("never")} className={chip(endMode === "never")}>Mai</button>
            <button onClick={() => setEndMode("until")} className={chip(endMode === "until")}>Il giorno…</button>
            <button onClick={() => setEndMode("count")} className={chip(endMode === "count")}>Dopo…</button>
            {endMode === "until" && (
              <input type="date" value={until} min={task.due_date} onChange={(e) => setUntil(e.target.value)} data-testid="recur-until"
                className="bg-white/10 rounded-lg px-1.5 py-0.5 text-white text-xs border-0 outline-none" />
            )}
            {endMode === "count" && (
              <span className="flex items-center gap-1.5 text-xs text-white/80">
                <input type="number" min={1} max={1000} value={count} onChange={(e) => setCount(e.target.value)}
                  className="w-14 bg-white/10 rounded-lg px-2 py-1 text-white text-xs border-0 outline-none" />
                volte
              </span>
            )}
          </div>
        </>
      )}
      {task.recurrence_label && (
        <div className="text-[11px] text-white/50">La modifica vale da questa occorrenza in poi; quelle passate restano come sono.</div>
      )}
      <div className="flex items-center gap-2">
        <button data-testid="recur-save" onClick={save} disabled={saving} className="text-xs px-3 py-1.5 rounded-full bg-white/15 hover:bg-white/25 text-white disabled:opacity-50">
          {saving ? "…" : "Salva"}
        </button>
        <button onClick={() => setOpen(false)} className="text-xs px-2 py-1.5 rounded-full text-white/50 hover:text-white/80">Annulla</button>
      </div>
    </div>
  );
}

// "Priorità alta" in the task's card: a tap changes it (on the computer it was the drag between the columns)
function PriorityRow({ task, onUpdated }) {
  const p = PRIORITY_META[task.priority];
  const change = async (v) => {
    try {
      await api.patch(`/tasks/${task.id}`, { priority: v });
      await onUpdated();
      toast.success("Priorità aggiornata");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  return (
    <label className="relative flex items-center gap-1.5 mt-1.5 text-sm w-fit cursor-pointer hover:underline decoration-dotted underline-offset-2"
      style={{ color: "#D9D9D9" }} title="Cambia la priorità" data-testid="task-priority">
      <Flag size={14} />
      {p && <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />}
      Priorità {p ? p.label.toLowerCase() : "media"}
      <select data-testid="task-priority-select" aria-label="Priorità" value={task.priority || "media"} onChange={(e) => change(e.target.value)}
        className="absolute inset-0 opacity-0 cursor-pointer">
        <option value="alta">Alta</option>
        <option value="media">Media</option>
        <option value="bassa">Bassa</option>
      </select>
    </label>
  );
}

const formatCreatedAt = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${IT_MONTHS_LONG[d.getMonth()]}, ${hh}:${mm}`;
};

function TaskDialog({ task, orgMembers, onClose, onUpdated }) {
  const { user } = useAuth();
  const isMobile = useIsMobile();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const [notes, setNotes] = useState(task.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [editingDate, setEditingDate] = useState(false);
  const [dateDraft, setDateDraft] = useState("");
  const [timeDraft, setTimeDraft] = useState("");
  const [savingDate, setSavingDate] = useState(false);

  const openDateEdit = () => {
    setDateDraft(task.due_date || "");
    setTimeDraft(task.due_time || "");
    setEditingDate(true);
  };

  const saveDueDate = async () => {
    setSavingDate(true);
    try {
      await api.patch(`/tasks/${task.id}`, { due_date: dateDraft || null, due_time: timeDraft || null });
      onUpdated();
      toast.success("Data aggiornata");
      setEditingDate(false);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore aggiornamento data"); }
    finally { setSavingDate(false); }
  };

  const send = async () => {
    if (!msg.trim()) return;
    setBusy(true);
    try {
      const r = await api.post(`/tasks/${task.id}/chat`, { message: msg });
      setThread((t) => [...t, { user: msg, agent: r.data.answer }]);
      setMsg("");
      onUpdated();
      toast.success("Task aggiornato");
    } catch (e) { toast.error("Errore aggiornamento"); }
    finally { setBusy(false); }
  };

  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      await api.patch(`/tasks/${task.id}`, { notes });
      onUpdated();
      toast.success("Note salvate");
    } catch (e) { toast.error("Errore salvataggio note"); }
    finally { setSavingNotes(false); }
  };

  const toggleFav = async () => {
    try {
      await api.post(`/tasks/${task.id}/favorite`);
      onUpdated();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleDone = async () => {
    try {
      await api.post(`/tasks/${task.id}/complete`);
      onUpdated();
      toast.success(task.completed ? "Riaperto" : "Task completato ✓");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleCal = async () => {
    try {
      await api.patch(`/tasks/${task.id}`, { calendar_synced: !task.calendar_synced });
      onUpdated();
      toast.success(task.calendar_synced ? "Rimosso da Calendar" : "Aggiunto a Calendar");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleReminder = async () => {
    try {
      await api.patch(`/tasks/${task.id}`, { reminder_enabled: !task.reminder_enabled });
      onUpdated();
      toast.success(task.reminder_enabled ? "Promemoria disattivato" : "Promemoria attivato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const toggleVisibility = async () => {
    const next = task.visibility === "org" ? "private" : "org";
    try {
      await api.patch(`/tasks/${task.id}`, { visibility: next });
      onUpdated();
      toast.success(next === "org" ? "Condiviso con il team" : "Reso privato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const assignTo = async (memberId) => {
    setAssigning(true);
    try {
      const r = await api.post(`/tasks/${task.id}/assign`, { assigned_to: memberId || null });
      onUpdated();
      if (memberId) {
        const member = orgMembers.find((m) => m.user_id === memberId);
        toast.success(
          member?.has_telegram
            ? `Assegnato a ${member?.name || "membro"} · notifica inviata su Telegram`
            : `Assegnato a ${member?.name || "membro"}`
        );
      } else {
        toast.success("Assegnazione rimossa");
      }
      return r.data;
    } catch (e) { toast.error(e.response?.data?.detail || "Errore assegnazione"); }
    finally { setAssigning(false); }
  };

  const del = async () => {
    askDeleteTask(task, async (scope) => {
      try {
        await api.delete(`/tasks/${task.id}`, { params: { scope } });
        onUpdated();
        onClose();
      } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    });
  };

  const isFav = !!task.favorite;
  const isDone = !!task.completed;
  const isCal = !!task.calendar_synced;
  const isReminder = !!task.reminder_enabled;

  const owner = task.user_id === user?.user_id
    ? (user?.name || "Tu")
    : (orgMembers.find((m) => m.user_id === task.user_id)?.name || "Team");
  const assignee = task.assigned_to ? orgMembers.find((m) => m.user_id === task.assigned_to) : null;
  const sharedWith = assignee
    ? `Assegnato a ${assignee.name}${assignee.user_id === user?.user_id ? " (io)" : ""}`
    : task.visibility === "org" ? "Organizzazione" : "Solo io";

  const dateBlock = editingDate ? (
    <div className="flex items-center gap-1.5 mt-1.5 text-sm flex-wrap" style={{ color: "#D9D9D9" }}>
      <Calendar size={14} />
      <input
        type="date"
        data-testid="task-due-date-input"
        value={dateDraft}
        onChange={(e) => setDateDraft(e.target.value)}
        className="bg-white/10 rounded-lg px-1.5 py-0.5 text-white text-xs border-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
      />
      <input
        type="time"
        data-testid="task-due-time-input"
        value={timeDraft}
        onChange={(e) => setTimeDraft(e.target.value)}
        disabled={!dateDraft}
        className="bg-white/10 rounded-lg px-1.5 py-0.5 text-white text-xs border-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30 disabled:opacity-40"
      />
      <button data-testid="task-due-date-save" onClick={saveDueDate} disabled={savingDate} className="text-xs px-2 py-0.5 rounded-full bg-white/15 hover:bg-white/25 text-white disabled:opacity-50">
        {savingDate ? "…" : "Salva"}
      </button>
      <button onClick={() => setEditingDate(false)} className="text-xs px-1.5 py-0.5 rounded-full text-white/50 hover:text-white/80">
        Annulla
      </button>
    </div>
  ) : (
    <button
      onClick={openDateEdit}
      data-testid="task-due-date-display"
      className="flex items-center gap-1.5 mt-1.5 text-sm hover:underline decoration-dotted underline-offset-2"
      style={{ color: "#D9D9D9" }}
      title="Modifica la data"
    >
      <Calendar size={14} />
      {task.due_date ? formatDayMonth(task.due_date, task.due_time) : "Aggiungi data"}
    </button>
  );

  const actionButtons = (
    <>
      <button data-testid="task-fav" onClick={toggleFav} className={`p-1.5 rounded-full ${isFav ? "text-amber-400" : "text-white/40 hover:text-white/70"}`} title={isFav ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}>
        <Star size={16} className={isFav ? "fill-current" : ""} />
      </button>
      <button data-testid="task-reminder" onClick={toggleReminder} className={`p-1.5 rounded-full ${isReminder ? "text-purple-300" : "text-white/40 hover:text-white/70"}`} title={isReminder ? "Disattiva promemoria" : "Attiva promemoria"}>
        {isReminder ? <BellRing size={16} /> : <Bell size={16} />}
      </button>
      <button data-testid="toggle-calendar" onClick={toggleCal} className={`p-1.5 rounded-full ${isCal ? "text-[#4E95D9]" : "text-white/40 hover:text-white/70"}`} title={isCal ? "Rimuovi da Calendar" : "Aggiungi a Calendar"}>
        <CalendarCheck size={16} className={isCal ? "fill-current" : ""} />
      </button>
      <button data-testid="task-complete" onClick={toggleDone} className={`p-1.5 rounded-full ${isDone ? "text-[#92D050]" : "text-white/40 hover:text-white/70"}`} title={isDone ? "Riapri" : "Segna come fatto"}>
        <CircleCheck size={16} className={isDone ? "fill-current" : ""} />
      </button>
      <button data-testid="delete-task" onClick={del} className="p-1.5 rounded-full text-white/40 hover:text-red-400" title="Elimina">
        <Trash2 size={16} />
      </button>
    </>
  );

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent
        className="max-w-2xl max-h-[90vh] overflow-hidden border-0 rounded-2xl liquid-glass-panel wobble-glass text-white"
        data-testid="task-dialog"
      >
        <div className="max-h-full overflow-y-auto pr-1">
        {isMobile ? (
          // Spec v2 §2.7: su smartphone le icone stanno nella prima riga in alto, allineate
          // a sinistra (-ml-1.5 compensa il p-1.5 del primo pulsante, così il glifo parte
          // esattamente dal bordo del testo sotto), e il titolo va a capo invece di essere
          // troncato. La "x" di chiusura resta quella del Dialog, in alto a destra.
          <div>
            <div className="flex items-center gap-1 -ml-1.5 pr-8" data-testid="task-dialog-actions">
              {actionButtons}
            </div>
            <div className="mt-2 min-w-0">
              <DialogHeader>
                <DialogTitle className="text-xl font-bold text-white break-words text-left leading-snug">{task.title}</DialogTitle>
              </DialogHeader>
              {dateBlock}
              <PriorityRow task={task} onUpdated={onUpdated} />
              <RecurrenceRow task={task} onUpdated={onUpdated} />
              <SourceRow source={task.source} />
            </div>
          </div>
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogHeader>
                <DialogTitle className="text-xl font-bold text-white truncate">{task.title}</DialogTitle>
              </DialogHeader>
              {dateBlock}
              <PriorityRow task={task} onUpdated={onUpdated} />
              <RecurrenceRow task={task} onUpdated={onUpdated} />
              <SourceRow source={task.source} />
            </div>
            <div className="flex items-center gap-1 shrink-0 pt-1">
              {actionButtons}
            </div>
          </div>
        )}

        {(task.tags || []).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4">
            {task.tags.map((t, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-md text-white/90" style={{ background: TAG_BG }}>#{t}</span>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
          <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: "#ACA6A3" }}>Data Creazione</div>
            <div className="text-sm text-white mt-1">{formatCreatedAt(task.created_at)}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide" style={{ color: "#ACA6A3" }}>Owner</div>
            <div className="text-sm text-white mt-1">{owner}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide flex items-center gap-1" style={{ color: "#ACA6A3" }}>
              Shared With
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    data-testid="share-assign-btn"
                    className="p-0.5 rounded-full text-white/50 hover:text-white hover:bg-white/10 transition-colors"
                    title="Condividi o assegna questo task"
                  >
                    <Share2 size={12} />
                  </button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-72 bg-[#2A2429] border-white/10 text-white rounded-2xl shadow-xl">
                  {user?.org_id ? (
                    <div className="space-y-4">
                      <div>
                        <div className="text-[11px] uppercase tracking-widest text-white/50 mb-2">Condividi</div>
                        <button
                          data-testid="toggle-visibility"
                          onClick={toggleVisibility}
                          className={`w-full text-left text-sm px-3 py-2 rounded-xl transition-colors ${task.visibility === "org" ? "bg-[#00B0F0]/20 text-[#00B0F0]" : "bg-white/10 text-white hover:bg-white/15"}`}
                        >
                          {task.visibility === "org" ? "✓ Condiviso con il team" : "Condividi con il team"}
                        </button>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-widest text-white/50 mb-2">Assegna a</div>
                        <select
                          data-testid="task-assign-select"
                          value={task.assigned_to || ""}
                          disabled={assigning}
                          onChange={(e) => assignTo(e.target.value)}
                          className="w-full text-sm text-white bg-white/10 rounded-xl px-3 py-2 outline-none disabled:opacity-50 cursor-pointer"
                          style={{ colorScheme: "dark" }}
                        >
                          <option value="" className="text-black">Nessuno</option>
                          {orgMembers.map((m) => (
                            <option key={m.user_id} value={m.user_id} className="text-black">
                              {m.name}{m.user_id === user?.user_id ? " (io)" : ""}{m.has_telegram ? "" : " · no Telegram"}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-white/60">
                      Non fai ancora parte di un team: vai in <span className="text-white font-medium">Impostazioni → Team</span> per unirti, poi qui potrai condividere o assegnare questo task.
                    </div>
                  )}
                </PopoverContent>
              </Popover>
            </div>
            <div className="text-sm text-white mt-1">{sharedWith}</div>
          </div>
        </div>

        {/* NOTES */}
        <div className="mt-7">
          <div
            className="flex items-center gap-1.5 mb-1.5 text-[11px] uppercase tracking-widest text-white/50"
            title="Appunti liberi su questo task: non vengono interpretati da mAIPAL, restano solo un promemoria per te"
          >
            <StickyNote size={13} /> Note
          </div>
          <div className="relative">
            <Textarea
              data-testid="task-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Note"
              className="border-0 rounded-2xl min-h-[80px] pr-12 text-white placeholder:text-white/50"
              style={{ background: TAG_BG }}
            />
            <button
              data-testid="task-notes-save"
              onClick={saveNotes}
              disabled={savingNotes || notes === (task.notes || "")}
              className="absolute bottom-2.5 right-2.5 p-2 rounded-full bg-white/15 text-white hover:bg-white/25 disabled:opacity-30"
              title="Salva note"
            >
              <Send size={14} />
            </button>
          </div>
        </div>

        <div className="mt-2 space-y-3 max-h-60 overflow-y-auto">
          {thread.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="rounded-xl p-3 text-sm text-white" style={{ background: TAG_BG }}>{t.user}</div>
              <div className="prose-answer text-sm whitespace-pre-wrap">{t.agent}</div>
            </div>
          ))}
        </div>

        <div className="mt-3">
          <div
            className="flex items-center gap-1.5 mb-1.5 text-[11px] uppercase tracking-widest text-white/50"
            title="Scrivi in linguaggio naturale per far modificare il task a mAIPAL: data, priorità, titolo e altro"
          >
            <Wand2 size={13} /> Modifica con mAIPAL
          </div>
          <div className="relative">
            <Textarea
              data-testid="task-chat-input"
              value={msg}
              onChange={(e) => setMsg(e.target.value)}
              placeholder="Modifica il task scrivendo in linguaggio naturale"
              className="border-0 rounded-2xl min-h-[80px] pr-12 text-white placeholder:text-white/50"
              style={{ background: TAG_BG }}
            />
            <button
              data-testid="task-chat-send"
              onClick={send}
              disabled={busy}
              className="absolute bottom-2.5 right-2.5 p-2 rounded-full bg-white/15 text-white hover:bg-white/25 disabled:opacity-30"
              title="Invia a mAIPAL"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
