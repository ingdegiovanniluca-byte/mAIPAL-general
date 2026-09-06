import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Calendar, Tag, MessageSquare } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const COLS = [
  { key: "alta", label: "Alta priorità", tint: "column-tint-high", dot: "bg-[color:var(--high)]", side: "priority-high" },
  { key: "media", label: "Media priorità", tint: "column-tint-med", dot: "bg-[color:var(--med)]", side: "priority-med" },
  { key: "bassa", label: "Bassa priorità", tint: "column-tint-low", dot: "bg-[color:var(--low)]", side: "priority-low" },
];

export default function TaskBoardPage() {
  const [tasks, setTasks] = useState([]);
  const [selected, setSelected] = useState(null);

  const load = async () => {
    const r = await api.get("/tasks");
    setTasks(r.data);
  };
  useEffect(() => { load(); }, []);

  const grouped = COLS.map((c) => ({ ...c, items: tasks.filter((t) => t.priority === c.key) }));

  const mostImminent = (items) => {
    const dated = items.filter((t) => t.due_date).sort((a, b) => a.due_date.localeCompare(b.due_date));
    return dated[0]?.id;
  };

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
        {grouped.map((c) => {
          const imm = mostImminent(c.items);
          return (
            <div key={c.key} className={`rounded-2xl p-5 ${c.tint} border border-neutral-200/60`} data-testid={`col-${c.key}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                  <div className="kicker">{c.label}</div>
                </div>
                <div className="kicker">{c.items.length}</div>
              </div>
              <div className="mt-5 space-y-3 min-h-[240px]">
                {c.items.length === 0 && <div className="text-center text-neutral-400 py-16 kicker">vuoto</div>}
                {c.items.map((t) => (
                  <TaskCard key={t.id} task={t} highlighted={t.id === imm} sideClass={c.side} onClick={() => setSelected(t)} />
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

function TaskCard({ task, highlighted, sideClass, onClick }) {
  return (
    <button
      onClick={onClick}
      data-testid={`task-${task.id}`}
      className={`w-full text-left card-soft ${sideClass} p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md ${highlighted ? "ring-2 ring-black/10 shadow-md" : ""}`}
    >
      <div className="font-semibold">{task.title}</div>
      {task.description && <div className="text-sm text-neutral-500 mt-1">{task.description}</div>}
      <div className="mt-3 flex flex-wrap gap-2 items-center">
        {task.due_date && (
          <span className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-neutral-100 border border-neutral-200">
            <Calendar size={10} /> {new Date(task.due_date).toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric" })}{task.due_time ? ` · ${task.due_time}` : ""}
          </span>
        )}
        {(task.tags || []).map((tag, i) => (
          <span key={i} className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-white border border-neutral-200 text-neutral-500">
            <Tag size={10} /> {tag}
          </span>
        ))}
        {task.notes && (
          <span className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-amber-50 border border-amber-200 text-amber-700">
            📝 note
          </span>
        )}
      </div>
      <div className="mt-3 kicker">
        {task.created_at ? new Date(task.created_at).toLocaleDateString("it-IT") : ""}
      </div>
    </button>
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
    if (!confirm("Eliminare questo task?")) return;
    await api.delete(`/tasks/${task.id}`);
    onUpdated();
    onClose();
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="task-dialog">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">{task.title}</DialogTitle>
        </DialogHeader>
        <div className="text-neutral-600 text-sm">{task.description}</div>
        <div className="flex flex-wrap gap-2">
          {task.due_date && <span className="text-xs px-2 py-1 rounded-md bg-white border">📅 {task.due_date}{task.due_time ? ` · ${task.due_time}` : ""}</span>}
          <span className={`text-xs px-2 py-1 rounded-md border ${task.priority === "alta" ? "bg-red-50 text-red-700" : task.priority === "media" ? "bg-orange-50 text-orange-700" : "bg-neutral-100"}`}>priorità {task.priority}</span>
          {(task.tags || []).map((t, i) => <span key={i} className="text-xs px-2 py-1 rounded-md bg-white border">#{t}</span>)}
          {task.calendar_synced && <span className="text-xs px-2 py-1 rounded-md bg-blue-50 text-blue-700 border border-blue-200">✓ Calendar</span>}
          {task.reminder_sent && <span className="text-xs px-2 py-1 rounded-md bg-purple-50 text-purple-700 border border-purple-200">⏰ promemoria inviato</span>}
        </div>

        <div className="flex gap-2 flex-wrap">
          <button data-testid="toggle-calendar" onClick={toggleCal} className="px-3 py-1.5 rounded-full text-xs bg-white border">
            {task.calendar_synced ? "✓ In Calendar" : "+ Aggiungi a Calendar"}
          </button>
          <button data-testid="delete-task" onClick={del} className="px-3 py-1.5 rounded-full text-xs bg-white border text-red-600">Elimina</button>
        </div>

        {/* NOTES */}
        <div className="pt-2">
          <div className="kicker mb-2">· note</div>
          <Textarea
            data-testid="task-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Aggiungi note libere sul task…"
            className="bg-white rounded-2xl min-h-[80px]"
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
              <div className="bg-neutral-100 rounded-xl p-3 text-sm">{t.user}</div>
              <div className="prose-answer text-sm whitespace-pre-wrap">{t.agent}</div>
            </div>
          ))}
        </div>

        <div className="mt-3">
          <Textarea data-testid="task-chat-input" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Modifica titolo, scadenza, priorità, tag… (parla in linguaggio naturale)" className="bg-white rounded-2xl min-h-[80px]" />
          <div className="flex justify-end mt-2">
            <button data-testid="task-chat-send" onClick={send} disabled={busy} className="pill-btn">{busy ? "…" : "Invia a mAIPAL"}</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
