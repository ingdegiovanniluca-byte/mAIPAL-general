import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tag } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { toast } from "sonner";

const COLS = [
  { key: "da_fare", label: "Da fare", dot: "bg-neutral-400" },
  { key: "in_corso", label: "In svolgimento", dot: "bg-blue-500" },
  { key: "fatto", label: "Fatti", dot: "bg-green-500" },
];

export default function TodoBoardPage() {
  const [todos, setTodos] = useState([]);
  const [selected, setSelected] = useState(null);

  const load = async () => {
    const r = await api.get("/todos");
    setTodos(r.data);
  };
  useEffect(() => { load(); }, []);

  const grouped = COLS.map((c) => ({ ...c, items: todos.filter((t) => t.status === c.key) }));

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
        {grouped.map((c) => (
          <div key={c.key} className="rounded-2xl p-5 bg-white/60 border border-neutral-200/60" data-testid={`col-${c.key}`}>
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
                <TodoCard key={t.id} todo={t} onClick={() => setSelected(t)} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && <TodoDialog todo={selected} onClose={() => setSelected(null)} onUpdated={load} />}
    </div>
  );
}

function TodoCard({ todo, onClick }) {
  const priorityStripe = todo.priority === "alta" ? "priority-high" : todo.priority === "media" ? "priority-med" : todo.priority === "bassa" ? "priority-low" : "";
  return (
    <button
      onClick={onClick}
      data-testid={`todo-${todo.id}`}
      className={`w-full text-left card-soft ${priorityStripe} p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md`}
    >
      <div className="font-semibold">{todo.title}</div>
      {todo.description && <div className="text-sm text-neutral-500 mt-1 line-clamp-2">{todo.description}</div>}
      {todo.status === "in_corso" && (
        <div className="mt-3">
          <Progress value={todo.completion_percent || 0} className="h-1.5" />
          <div className="kicker mt-1">{todo.completion_percent || 0}%</div>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {(todo.tags || []).map((tag, i) => (
          <span key={i} className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-white border border-neutral-200 text-neutral-500">
            <Tag size={10} /> {tag}
          </span>
        ))}
      </div>
      <div className="mt-3 kicker">{todo.created_at ? new Date(todo.created_at).toLocaleDateString("it-IT") : ""}</div>
    </button>
  );
}

function TodoDialog({ todo, onClose, onUpdated }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const [pct, setPct] = useState(todo.completion_percent || 0);
  const [status, setStatus] = useState(todo.status);

  const persistStatus = async (s) => {
    setStatus(s);
    await api.patch(`/todos/${todo.id}`, { status: s });
    onUpdated();
  };
  const persistPct = async (v) => {
    setPct(v);
    await api.patch(`/todos/${todo.id}`, { completion_percent: v });
    onUpdated();
  };

  const send = async () => {
    if (!msg.trim()) return;
    setBusy(true);
    try {
      const r = await api.post(`/todos/${todo.id}/chat`, { message: msg });
      setThread((t) => [...t, { user: msg, agent: r.data.answer }]);
      setMsg("");
      onUpdated();
      toast.success("To-do aggiornato");
    } catch { toast.error("Errore"); }
    finally { setBusy(false); }
  };

  const del = async () => {
    if (!confirm("Eliminare questo to-do?")) return;
    await api.delete(`/todos/${todo.id}`);
    onUpdated(); onClose();
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl bg-[color:var(--app-bg)]" data-testid="todo-dialog">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">{todo.title}</DialogTitle>
        </DialogHeader>
        <div className="text-neutral-600 text-sm">{todo.description}</div>

        <div className="flex flex-wrap gap-2">
          {["da_fare", "in_corso", "fatto"].map((s) => (
            <button key={s} data-testid={`status-${s}`} onClick={() => persistStatus(s)} className={`px-3 py-1.5 rounded-full text-xs border ${status === s ? "bg-black text-white border-black" : "bg-white"}`}>
              {s.replace("_", " ")}
            </button>
          ))}
          <button data-testid="delete-todo" onClick={del} className="px-3 py-1.5 rounded-full text-xs bg-white border text-red-600">Elimina</button>
        </div>

        {status === "in_corso" && (
          <div className="pt-2">
            <div className="kicker mb-2">completamento · {pct}%</div>
            <input data-testid="todo-progress" type="range" min="0" max="100" value={pct} onChange={(e) => persistPct(parseInt(e.target.value))} className="w-full" />
          </div>
        )}

        <div className="mt-3 space-y-3 max-h-60 overflow-y-auto">
          {thread.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="bg-neutral-100 rounded-xl p-3 text-sm">{t.user}</div>
              <div className="prose-answer text-sm whitespace-pre-wrap">{t.agent}</div>
            </div>
          ))}
        </div>

        <div className="mt-3">
          <Textarea data-testid="todo-chat-input" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Aggiorna stato, avanzamento, tag, note…" className="bg-white rounded-2xl min-h-[80px]" />
          <div className="flex justify-end mt-2">
            <button data-testid="todo-chat-send" onClick={send} disabled={busy} className="pill-btn">{busy ? "…" : "Invia a mAIPAL"}</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
