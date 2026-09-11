import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Calendar, CalendarCheck, Tag, MessageSquare, Star, Trash2, CircleCheck, Archive, AlertTriangle } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const COLS = [
  { key: "alta", label: "Alta priorità", tint: "column-tint-high", dot: "bg-[color:var(--high)]", side: "priority-high" },
  { key: "media", label: "Media priorità", tint: "column-tint-med", dot: "bg-[color:var(--med)]", side: "priority-med" },
  { key: "bassa", label: "Bassa priorità", tint: "column-tint-low", dot: "bg-[color:var(--low)]", side: "priority-low" },
];

const formatDDMMYYYY = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mm}/${d.getFullYear()}`;
};

export default function TaskBoardPage() {
  const [tasks, setTasks] = useState([]);
  const [selected, setSelected] = useState(null);
  const [showCompleted, setShowCompleted] = useState(false);
  const [dragOverCol, setDragOverCol] = useState(null);

  const load = async () => {
    const r = await api.get("/tasks");
    setTasks(r.data);
  };
  useEffect(() => { load(); }, []);

  const sortTasks = (arr) => [...arr].sort((a, b) => {
    const da = a.due_date || "9999-12-31";
    const db_ = b.due_date || "9999-12-31";
    if (da !== db_) return da.localeCompare(db_);
    return (b.created_at || "").localeCompare(a.created_at || "");
  });

  const visible = tasks.filter((t) => showCompleted ? !!t.completed : !t.completed);
  const grouped = COLS.map((c) => ({ ...c, items: sortTasks(visible.filter((t) => t.priority === c.key)) }));

  const toggleFav = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: !cur } : t)));
    try { await api.post(`/tasks/${id}/favorite`); }
    catch { toast.error("Errore"); setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: cur } : t))); }
  };

  const toggleDone = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, completed: !cur } : t)));
    try {
      await api.post(`/tasks/${id}/complete`);
      toast.success(cur ? "Riaperto" : "Task completato ✓");
    } catch { toast.error("Errore"); setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, completed: cur } : t))); }
  };

  const toggleCal = async (id, cur) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, calendar_synced: !cur } : t)));
    try {
      await api.patch(`/tasks/${id}`, { calendar_synced: !cur });
      toast.success(cur ? "Rimosso da Calendar" : "Aggiunto a Calendar");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
      setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, calendar_synced: cur } : t)));
    }
  };

  const del = async (id) => {
    toast("Eliminare questo task?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = tasks;
          setTasks((ts) => ts.filter((t) => t.id !== id));
          try { await api.delete(`/tasks/${id}`); toast.success("Task eliminato"); }
          catch { toast.error("Errore"); setTasks(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const changePriority = async (id, newPriority) => {
    const cur = tasks.find((t) => t.id === id);
    if (!cur || cur.priority === newPriority) return;
    const prevPriority = cur.priority;
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, priority: newPriority } : t)));
    try { await api.patch(`/tasks/${id}`, { priority: newPriority }); }
    catch {
      toast.error("Errore nello spostamento");
      setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, priority: prevPriority } : t)));
    }
  };

  const mostImminent = (items) => {
    const dated = items.filter((t) => t.due_date).sort((a, b) => a.due_date.localeCompare(b.due_date));
    return dated[0]?.id;
  };

  const activeCount = tasks.filter((t) => !t.completed).length;
  const completedCount = tasks.filter((t) => !!t.completed).length;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <button
          data-testid="filter-active"
          onClick={() => setShowCompleted(false)}
          title="Attivi"
          className={`rounded-full inline-flex items-center transition-all duration-200 ${!showCompleted ? "gap-1.5 px-4 py-2 bg-[#CECAD0] text-[#403A3C]" : "gap-1 px-2.5 py-2 bg-white/10 text-white/50 hover:text-white/80"}`}
        >
          {!showCompleted ? (
            <>
              <CircleCheck size={14} />
              <span className="text-xs font-mono-tight uppercase tracking-widest">attivi</span>
              <span className="ml-0.5 text-[10px] font-bold bg-black/10 rounded-full px-1.5 py-0.5">{activeCount}</span>
            </>
          ) : (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-current" />
              <CircleCheck size={13} />
            </>
          )}
        </button>
        <button
          data-testid="filter-completed"
          onClick={() => setShowCompleted(true)}
          title="Completati"
          className={`rounded-full inline-flex items-center transition-all duration-200 ${showCompleted ? "gap-1.5 px-4 py-2 bg-[#CECAD0] text-[#403A3C]" : "gap-1 px-2.5 py-2 bg-white/10 text-white/50 hover:text-white/80"}`}
        >
          {showCompleted ? (
            <>
              <Archive size={14} />
              <span className="text-xs font-mono-tight uppercase tracking-widest">completati</span>
              <span className="ml-0.5 text-[10px] font-bold bg-black/10 rounded-full px-1.5 py-0.5">{completedCount}</span>
            </>
          ) : (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-current" />
              <Archive size={13} />
            </>
          )}
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
        {grouped.map((c) => {
          const imm = mostImminent(c.items);
          return (
            <div
              key={c.key}
              className={`rounded-2xl p-5 ${c.tint} transition-shadow ${dragOverCol === c.key ? "ring-2 ring-white/50" : ""}`}
              data-testid={`col-${c.key}`}
              onDragOver={(e) => { e.preventDefault(); setDragOverCol(c.key); }}
              onDragLeave={() => setDragOverCol((v) => (v === c.key ? null : v))}
              onDrop={(e) => {
                e.preventDefault();
                setDragOverCol(null);
                const id = e.dataTransfer.getData("text/plain");
                if (id) changePriority(id, c.key);
              }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                  <div className="kicker">{c.label}</div>
                </div>
                <div className="h-7 w-7 rounded-full bg-white/15 flex items-center justify-center text-sm font-bold">{c.items.length}</div>
              </div>
              <div className="mt-5 space-y-3 min-h-[240px]">
                {c.items.length === 0 && <div className="text-center text-white/40 py-16 kicker">vuoto</div>}
                {c.items.map((t) => (
                  <TaskCard key={t.id} task={t} highlighted={t.id === imm} sideClass={c.side} onClick={() => setSelected(t)} onToggleFav={() => toggleFav(t.id, !!t.favorite)} onToggleDone={() => toggleDone(t.id, !!t.completed)} onToggleCal={() => toggleCal(t.id, !!t.calendar_synced)} onDelete={() => del(t.id)} />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {selected && (
        <TaskDialog task={selected} onClose={() => setSelected(null)} onUpdated={async () => { await load(); }} />
      )}
    </div>
  );
}

function TaskCard({ task, highlighted, sideClass, onClick, onToggleFav, onToggleDone, onToggleCal, onDelete }) {
  const stop = (fn) => (e) => { e.stopPropagation(); e.preventDefault(); fn(); };
  const isFav = !!task.favorite;
  const isDone = !!task.completed;
  const isCal = !!task.calendar_synced;
  const todayStr = new Date().toISOString().slice(0, 10);
  const isOverdue = !!task.due_date && !isDone && task.due_date < todayStr;
  return (
    <div
      data-testid={`task-${task.id}`}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", task.id)}
      className={`relative w-full text-left card-soft ${sideClass} p-4 card-hover cursor-grab active:cursor-grabbing ${highlighted ? "ring-2 ring-black/10 shadow-md" : ""} ${isDone ? "opacity-60" : ""} ${isOverdue ? "bg-red-500/10 ring-1 ring-red-500/30" : ""}`}
    >
      <div className="absolute top-2 right-2 flex items-center gap-1">
        <button data-testid="task-complete" onClick={stop(onToggleDone)} className={`p-1.5 rounded-full ${isDone ? "text-green-600 bg-green-50" : "text-white/40 hover:bg-green-50 hover:text-green-600"}`} title={isDone ? "Riapri" : "Segna come fatto"}>
          <CircleCheck size={14} className={isDone ? "fill-current" : ""} />
        </button>
        <button data-testid="task-fav" onClick={stop(onToggleFav)} className={`p-1.5 rounded-full ${isFav ? "text-amber-500 hover:bg-amber-50" : "text-white/40 hover:bg-white/10 hover:text-amber-500"}`} title={isFav ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}>
          <Star size={14} className={isFav ? "fill-current" : ""} />
        </button>
        <button data-testid="task-calendar" onClick={stop(onToggleCal)} className={`p-1.5 rounded-full ${isCal ? "text-blue-500 hover:bg-blue-50" : "text-white/40 hover:bg-white/10 hover:text-blue-500"}`} title={isCal ? "Rimuovi da Calendar" : "Aggiungi a Calendar"}>
          <CalendarCheck size={14} className={isCal ? "fill-current" : ""} />
        </button>
        <button data-testid="task-delete" onClick={stop(onDelete)} className="p-1.5 rounded-full text-white/40 hover:bg-red-50 hover:text-red-600" title="Elimina"><Trash2 size={14} /></button>
      </div>
      <button onClick={onClick} className="w-full text-left pr-28">
        <div className={`font-semibold ${isDone ? "line-through" : ""}`}>{task.title}</div>
        {task.created_at && (
          <div className="text-[9px] text-white/45 mt-0.5">data creazione: {formatDDMMYYYY(task.created_at)}</div>
        )}
        {task.description && <div className="text-sm text-white/60 mt-1">{task.description}</div>}
        <div className="mt-3 flex flex-wrap gap-2 items-center">
          {task.due_date && (
            <span className={`inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md ${isOverdue ? "bg-red-500/20 text-red-300 border border-red-500/40" : "bg-white/10"}`}>
              {isOverdue ? <AlertTriangle size={10} /> : <Calendar size={10} />} {new Date(task.due_date).toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric" })}{task.due_time ? ` · ${task.due_time}` : ""}{isOverdue ? " · scaduto" : ""}
            </span>
          )}
          {(task.tags || []).map((tag, i) => (
            <span key={i} className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-white/10  text-white/60">
              <Tag size={10} /> {tag}
            </span>
          ))}
          {task.notes && (
            <span className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-amber-50 border border-amber-200 text-amber-700">
              📝 note
            </span>
          )}
          {isDone && (
            <span className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-green-50 border border-green-200 text-green-700">
              ✓ fatto
            </span>
          )}
        </div>
      </button>
    </div>
  );
}

function TaskDialog({ task, onClose, onUpdated }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const [notes, setNotes] = useState(task.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);

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

  const toggleCal = async () => {
    try {
      await api.patch(`/tasks/${task.id}`, { calendar_synced: !task.calendar_synced });
      onUpdated();
      toast.success(task.calendar_synced ? "Rimosso da Calendar" : "Aggiunto a Calendar");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const del = async () => {
    toast("Eliminare questo task?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          await api.delete(`/tasks/${task.id}`);
          onUpdated();
          onClose();
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="task-dialog">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">{task.title}</DialogTitle>
        </DialogHeader>
        <div className="text-white/70 text-sm">{task.description}</div>
        <div className="flex flex-wrap gap-2">
          {task.due_date && <span className="text-xs px-2 py-1 rounded-md bg-white/10 border">📅 {task.due_date}{task.due_time ? ` · ${task.due_time}` : ""}</span>}
          <span className={`text-xs px-2 py-1 rounded-md border ${task.priority === "alta" ? "bg-red-50 text-red-700" : task.priority === "media" ? "bg-orange-50 text-orange-700" : "bg-white/10"}`}>priorità {task.priority}</span>
          {(task.tags || []).map((t, i) => <span key={i} className="text-xs px-2 py-1 rounded-md bg-white/10 border">#{t}</span>)}
          {task.calendar_synced && <span className="text-xs px-2 py-1 rounded-md bg-blue-50 text-blue-700 border border-blue-200">✓ Calendar</span>}
          {task.reminder_sent && <span className="text-xs px-2 py-1 rounded-md bg-purple-50 text-purple-700 border border-purple-200">⏰ promemoria inviato</span>}
        </div>

        <div className="flex gap-2 flex-wrap">
          <button data-testid="toggle-calendar" onClick={toggleCal} className="px-3 py-1.5 rounded-full text-xs bg-white/10 border">
            {task.calendar_synced ? "✓ In Calendar" : "+ Aggiungi a Calendar"}
          </button>
          <button data-testid="delete-task" onClick={del} className="px-3 py-1.5 rounded-full text-xs bg-white/10 border text-red-600">Elimina</button>
        </div>

        {/* NOTES */}
        <div className="pt-2">
          <div className="kicker mb-2">· note</div>
          <Textarea
            data-testid="task-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Aggiungi note libere sul task…"
            className="bg-white/10 rounded-2xl min-h-[80px]"
          />
          <div className="flex justify-end mt-2">
            <button data-testid="task-notes-save" onClick={saveNotes} disabled={savingNotes || notes === (task.notes || "")} className="px-4 py-1.5 rounded-full text-xs bg-black text-white disabled:opacity-40">
              {savingNotes ? "…" : "Salva note"}
            </button>
          </div>
        </div>

        <div className="mt-3 space-y-3 max-h-60 overflow-y-auto">
          {thread.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="bg-white/10 rounded-xl p-3 text-sm">{t.user}</div>
              <div className="prose-answer text-sm whitespace-pre-wrap">{t.agent}</div>
            </div>
          ))}
        </div>

        <div className="mt-3">
          <Textarea data-testid="task-chat-input" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Modifica titolo, scadenza, priorità, tag… (parla in linguaggio naturale)" className="bg-white/10 rounded-2xl min-h-[80px]" />
          <div className="flex justify-end mt-2">
            <button data-testid="task-chat-send" onClick={send} disabled={busy} className="pill-btn">{busy ? "…" : "Invia a mAIPAL"}</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
