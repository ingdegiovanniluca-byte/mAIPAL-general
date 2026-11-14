import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tag, Star, Trash2 } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { toast } from "sonner";
import { useIsMobile } from "@/hooks/use-is-mobile";
import TodoFolders from "@/components/TodoFolders";
import TodoDetail from "@/components/TodoDetail";

const COLS = [
  { key: "da_fare", label: "Da fare", dot: "bg-neutral-400" },
  { key: "in_corso", label: "In svolgimento", dot: "bg-blue-500" },
  { key: "fatto", label: "Fatti", dot: "bg-green-500" },
];

export default function TodoBoardPage() {
  const [todos, setTodos] = useState([]);
  const [selected, setSelected] = useState(null);
  const isMobile = useIsMobile();

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

  // the phone: the three states as folders (TodoFolders); the desktop keeps the three columns
  if (isMobile) {
    return (
      <>
        <TodoFolders todos={todos} setTodos={setTodos} sortTodos={sortTodos} reload={load}
          onOpenTodo={setSelected} onToggleFav={toggleFav} onDelete={del} />
        {selected && <TodoDetail todo={selected} onClose={() => setSelected(null)} onUpdated={load} />}
      </>
    );
  }

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

      {selected && <TodoDetail todo={selected} onClose={() => setSelected(null)} onUpdated={load} />}
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
