import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Newspaper, ExternalLink, RefreshCw, ThumbsUp, ThumbsDown, BookmarkPlus, BookmarkCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";

const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

const formatDate = (dateStr) => {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return `${d.getDate()} ${IT_MONTHS_LONG[d.getMonth()]} ${d.getFullYear()}`;
};

export default function NewsPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const r = await api.get("/news");
      setItems(r.data);
    } catch {
      toast.error("Errore nel caricamento delle news");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await api.post("/news/refresh");
      await load();
      toast.success("News aggiornate");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nella ricerca delle news");
    } finally {
      setRefreshing(false);
    }
  };

  const setFeedback = async (item, value) => {
    const next = item.feedback === value ? null : value;
    setItems((its) => its.map((it) => (it.id === item.id ? { ...it, feedback: next } : it)));
    try {
      await api.post(`/news/${item.id}/feedback`, { value: next });
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
      setItems((its) => its.map((it) => (it.id === item.id ? { ...it, feedback: item.feedback } : it)));
    }
  };

  const saveToKb = async (item) => {
    try {
      const r = await api.post(`/news/${item.id}/save-to-kb`);
      setItems((its) => its.map((it) => (it.id === item.id ? { ...it, kb_doc_id: r.data.doc_id } : it)));
      toast.success(r.data.already_saved ? "Già salvata nella Knowledge Base" : "Salvata nella Knowledge Base");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nel salvataggio");
    }
  };

  const deleteItem = (item) => {
    toast("Eliminare questa news?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = items;
          setItems((its) => its.filter((it) => it.id !== item.id));
          try { await api.delete(`/news/${item.id}`); toast.success("News eliminata"); }
          catch (e) { toast.error(e.response?.data?.detail || "Errore"); setItems(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const groups = items.reduce((acc, it) => {
    const key = it.date || "";
    (acc[key] = acc[key] || []).push(it);
    return acc;
  }, {});
  const dates = Object.keys(groups).sort((a, b) => b.localeCompare(a));

  return (
    <div>
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Newspaper size={20} className="text-white/70" />
          <div className="kicker">news personalizzate</div>
        </div>
        <button
          data-testid="news-refresh"
          onClick={refresh}
          disabled={refreshing}
          className="pill-btn text-sm disabled:opacity-50"
        >
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          {refreshing ? "Ricerca in corso…" : "Aggiorna ora"}
        </button>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}

      {!loading && items.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">
          nessuna news ancora — premi "aggiorna ora" per la prima ricerca
        </div>
      )}

      <div className="space-y-8">
        {dates.map((date) => (
          <div key={date}>
            <div className="text-xs text-white/45 uppercase tracking-widest mb-3">{formatDate(date)}</div>
            <div className="space-y-3">
              {groups[date].map((it) => (
                <div key={it.id} data-testid={`news-item-${it.id}`} className="card-soft card-hover p-4 rounded-2xl">
                  <a href={it.url} target="_blank" rel="noreferrer" className="block">
                    <div className="flex items-start justify-between gap-3">
                      <div className="font-semibold">{it.title}</div>
                      <ExternalLink size={14} className="text-white/40 shrink-0 mt-1" />
                    </div>
                    {it.summary && <div className="text-sm text-white/65 mt-1.5">{it.summary}</div>}
                    {it.source && <div className="text-[10px] text-white/40 uppercase tracking-widest mt-2">{it.source}</div>}
                  </a>

                  <div className="flex items-center gap-1 mt-3 pt-2.5 border-t border-white/10">
                    <button
                      data-testid="news-like"
                      onClick={() => setFeedback(it, "like")}
                      title="Mi interessa"
                      className={`p-1.5 rounded-full ${it.feedback === "like" ? "text-emerald-400 bg-emerald-400/10" : "text-white/40 hover:text-white/70"}`}
                    >
                      <ThumbsUp size={14} className={it.feedback === "like" ? "fill-current" : ""} />
                    </button>
                    <button
                      data-testid="news-dislike"
                      onClick={() => setFeedback(it, "dislike")}
                      title="Non mi interessa"
                      className={`p-1.5 rounded-full ${it.feedback === "dislike" ? "text-red-400 bg-red-400/10" : "text-white/40 hover:text-white/70"}`}
                    >
                      <ThumbsDown size={14} className={it.feedback === "dislike" ? "fill-current" : ""} />
                    </button>
                    <button
                      data-testid="news-save-kb"
                      onClick={() => saveToKb(it)}
                      title={it.kb_doc_id ? "Salvata nella Knowledge Base" : "Salva nella Knowledge Base"}
                      className={`p-1.5 rounded-full ${it.kb_doc_id ? "text-blue-300" : "text-white/40 hover:text-white/70"}`}
                    >
                      {it.kb_doc_id ? <BookmarkCheck size={14} /> : <BookmarkPlus size={14} />}
                    </button>
                    <button
                      data-testid="news-delete"
                      onClick={() => deleteItem(it)}
                      title="Elimina"
                      className="p-1.5 rounded-full text-white/40 hover:text-red-400 ml-auto"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
