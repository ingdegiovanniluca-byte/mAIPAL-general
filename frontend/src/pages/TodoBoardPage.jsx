import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tag, Star, Trash2 } from "lucide-react";
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

  // Todo ordering: favorites first, then by created_at desc
  const sortTodos = (arr) => [...arr].sort((a, b) => {
    if (!!b.favorite !== !!a.favorite) return b.favorite ? 1 : -1;
    return (b.created_at || "").localeCompare(a.created_at || "");
  });

  const grouped = COLS.map((c) => ({ ...c, items: sortTodos(todos.filter((t) => t.status === c.key)) }));

  const toggleFav = async (id, cur) => {
    setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: !cur } : t)));
    try { await api.post(`/todos/${id}/favorite`); }
    catch { toast.error("Errore preferito"); setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, favorite: cur } : t))); }
  };

  const del = async (id) => {
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

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
        {grouped.map((c) => (
          <div key={c.key} className="rounded-2xl p-5 bg-white/5 " data-testid={`col-${c.key}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                <div className="kicker">{c.label}</div>
              </div>
              <div className="kicker">{c.items.length}</div>
            </div>
            <div className="mt-5 space-y-3 min-h-[240px]">
              {c.items.length === 0 && <div className="text-center text-white/40 py-16 kicker">vuoto</div>}
              {c.items.map((t) => (
                <TodoCard key={t.id} todo={t} onClick={() => setSelected(t)} onToggleFav={() => toggleFav(t.id, !!t.favorite)} onDelete={() => del(t.id)} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && <TodoDialog todo={selected} onClose={() => setSelected(null)} onUpdated={load} />}
    </div>
  );
}

function TodoCard({ todo, onClick, onToggleFav, onDelete }) {
  const priorityStripe = todo.priority === "alta" ? "priority-high" : todo.priority === "media" ? "priority-med" : todo.priority === "bassa" ? "priority-low" : "";
  const stop = (fn) => (e) => { e.stopPropagation(); e.preventDefault(); fn(); };
  const isFav = !!todo.favorite;
  return (
    <div
      data-testid={`todo-${todo.id}`}
      className={`relative w-full text-left card-soft ${priorityStripe} p-4 card-hover`}
    >
      <div className="absolute top-2 right-2 flex items-center gap-1">
        <button data-testid="todo-fav" onClick={stop(onToggleFav)} className={`p-1.5 rounded-full ${isFav ? "text-amber-500 hover:bg-amber-50" : "text-white/40 hover:bg-white/10 hover:text-amber-500"}`} title={isFav ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti"}>
          <Star size={14} className={isFav ? "fill-current" : ""} />
        </button>
        <button data-testid="todo-delete" onClick={stop(onDelete)} className="p-1.5 rounded-full text-white/40 hover:bg-red-50 hover:text-red-600" title="Elimina"><Trash2 size={14} /></button>
      </div>
      <button onClick={onClick} className="w-full text-left pr-14">
        <div className="font-semibold">{todo.title}</div>
        {todo.description && <div className="text-sm text-white/60 mt-1 line-clamp-2">{todo.description}</div>}
        {todo.status === "in_corso" && (
          <div className="mt-3">
            <Progress value={todo.completion_percent || 0} className="h-1.5" />
            <div className="kicker mt-1">{todo.completion_percent || 0}%</div>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {(todo.tags || []).map((tag, i) => (
            <span key={i} className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-white/10  text-white/60">
              <Tag size={10} /> {tag}
            </span>
          ))}
          {todo.notes && (
            <span className="inline-flex items-center gap-1 text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-amber-50 border border-amber-200 text-amber-700">
              📝 note
            </span>
          )}
        </div>
        <div className="mt-3 kicker">{todo.created_at ? new Date(todo.created_at).toLocaleDateString("it-IT") : ""}</div>
      </button>
    </div>
  );
}

function TodoDialog({ todo, onClose, onUpdated }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState([]);
  const [pct, setPct] = useState(todo.completion_percent || 0);
  const [status, setStatus] = useState(todo.status);
  const [notes, setNotes] = useState(todo.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);

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

  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      await api.patch(`/todos/${todo.id}`, { notes });
      onUpdated();
      toast.success("Note salvate");
    } catch { toast.error("Errore"); }
    finally { setSavingNotes(false); }
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
    toast("Eliminare questo to-do?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          await api.delete(`/todos/${todo.id}`);
          onUpdated(); onClose();
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="todo-dialog">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">{todo.title}</DialogTitle>
        </DialogHeader>
        <div className="text-white/70 text-sm">{todo.description}</div>

        <div className="flex flex-wrap gap-2">
          {["da_fare", "in_corso", "fatto"].map((s) => (
            <button key={s} data-testid={`status-${s}`} onClick={() => persistStatus(s)}
                    style={status === s ? { backgroundColor: "#CECAD0", color: "#fff", border: "none" } : {}}
                    className={`px-3 py-1.5 rounded-full text-xs ${status === s ? "" : "bg-white/10 border"}`}>
              {s.replace("_", " ")}
            </button>
          ))}
          <button data-testid="delete-todo" onClick={del} className="px-3 py-1.5 rounded-full text-xs bg-white/10 border text-red-600">Elimina</button>
        </div>

        {status === "in_corso" && (
          <div className="pt-2">
            <div className="kicker mb-2">completamento · {pct}%</div>
            <input data-testid="todo-progress" type="range" min="0" max="100" value={pct} onChange={(e) => persistPct(parseInt(e.target.value))} className="w-full" />
          </div>
        )}

        {/* NOTES */}
        <div className="pt-2">
          <div className="kicker mb-2">· note</div>
          <Textarea
            data-testid="todo-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Aggiungi note libere sul to-do…"
            className="bg-white/10 rounded-2xl min-h-[80px]"
          />
          <div className="flex justify-end mt-2">
            <button data-testid="todo-notes-save" onClick={saveNotes} disabled={savingNotes || notes === (todo.notes || "")} className="px-4 py-1.5 rounded-full text-xs bg-black text-white disabled:opacity-40">
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
          <Textarea data-testid="todo-chat-input" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Aggiorna stato, avanzamento, tag, note…" className="bg-white/10 rounded-2xl min-h-[80px]" />
          <div className="flex justify-end mt-2">
            <button data-testid="todo-chat-send" onClick={send} disabled={busy} className="pill-btn">{busy ? "…" : "Invia a mAIPAL"}</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
