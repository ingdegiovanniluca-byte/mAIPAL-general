import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Newspaper, ExternalLink, RefreshCw } from "lucide-react";
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
                <a
                  key={it.id}
                  href={it.url}
                  target="_blank"
                  rel="noreferrer"
                  data-testid={`news-item-${it.id}`}
                  className="block card-soft card-hover p-4 rounded-2xl"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="font-semibold">{it.title}</div>
                    <ExternalLink size={14} className="text-white/40 shrink-0 mt-1" />
                  </div>
                  {it.summary && <div className="text-sm text-white/65 mt-1.5">{it.summary}</div>}
                  {it.source && <div className="text-[10px] text-white/40 uppercase tracking-widest mt-2">{it.source}</div>}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
