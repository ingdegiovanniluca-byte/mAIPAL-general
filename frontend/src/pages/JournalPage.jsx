import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, API } from "@/lib/api";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { BookOpen, Trash2, Sparkles, Mic, MicOff, Search, X, TrendingUp, Star, Flame, BarChart3, Notebook, Eye, EyeOff, CalendarDays, ChevronUp, ChevronDown, Tag, Smile } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";

const MOODS = ["felice", "grato", "energico", "riflessivo", "neutro", "stanco", "stressato"];
const MOOD_EMOJI = {
  felice: "😊", neutro: "😐", stressato: "😣", riflessivo: "🤔",
  energico: "⚡", stanco: "😴", grato: "🙏",
};

// Y axis is a plain 1-5 mood level (no emoji) - this legend above the chart spells out
// what each level means instead.
const MOOD_LEVEL_LABEL = { 1: "triste", 2: "stanco", 3: "neutro", 4: "energico", 5: "felice" };

const PERIODS = [
  { key: "all", label: "sempre" },
  { key: "today", label: "oggi" },
  { key: "week", label: "ultima settimana" },
  { key: "month", label: "ultimo mese" },
  { key: "custom", label: "personalizzato" },
];

// Icon-only filter category selector, styled like the chat page's action icon bar:
// each icon expands/collapses its own section below instead of carrying a label.
const FILTER_ICONS = [
  { key: "period", icon: <CalendarDays size={15} />, title: "Periodo", color: "#DD772F" },
  { key: "mood", icon: <Smile size={15} />, title: "Umore", color: "#6D6181" },
  { key: "search", icon: <Search size={15} />, title: "Cerca", color: "#7C6A7D" },
  { key: "topic", icon: <Tag size={15} />, title: "Argomento", color: "#8E2E11" },
];

const toISODate = (d) => d.toISOString().slice(0, 10);

const IT_WEEKDAYS_LONG = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
const IT_MONTHS_LONG = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
// Parses the "YYYY-MM-DD" date components directly (no Date(iso) UTC parsing) so the
// diary heading always shows the calendar date the entry was actually saved on.
const formatDiaryDate = (iso) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return "";
  const dt = new Date(y, m - 1, d);
  return `${cap(IT_WEEKDAYS_LONG[dt.getDay()])} ${d} ${cap(IT_MONTHS_LONG[m - 1])} ${y}`;
};

export default function JournalPage() {
  const [entries, setEntries] = useState([]);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  // Search & filter
  const [q, setQ] = useState("");
  const [moodFilters, setMoodFilters] = useState([]);
  const [topicFilters, setTopicFilters] = useState([]);
  const [favOnly, setFavOnly] = useState(false);
  const [period, setPeriod] = useState("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [composerOpen, setComposerOpen] = useState(true);
  // Periodo and umore stay open by default (the "main" filters); ricerca e argomento
  // are tucked behind their icon until clicked, like the chat page's action bar.
  const [expandedFilters, setExpandedFilters] = useState(() => new Set(["period", "mood"]));
  const toggleFilterSection = (key) => setExpandedFilters((cur) => {
    const next = new Set(cur);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  // Voice recording
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const recStartRef = useRef(0);

  // Trend
  const [trend, setTrend] = useState([]);
  const [trendDays, setTrendDays] = useState(7);
  const [showTrend, setShowTrend] = useState(true);

  // Stats
  const [stats, setStats] = useState(null);

  // Resolve the selected period into concrete date_from/date_to bounds for the API.
  const dateRange = useMemo(() => {
    const today = new Date();
    if (period === "today") { const s = toISODate(today); return { date_from: s, date_to: s }; }
    if (period === "week") { const from = new Date(today); from.setDate(from.getDate() - 6); return { date_from: toISODate(from), date_to: toISODate(today) }; }
    if (period === "month") { const from = new Date(today); from.setDate(from.getDate() - 29); return { date_from: toISODate(from), date_to: toISODate(today) }; }
    if (period === "custom") return { date_from: customFrom || undefined, date_to: customTo || undefined };
    return {};
  }, [period, customFrom, customTo]);

  const load = async () => {
    const params = {};
    if (q.trim()) params.q = q.trim();
    if (favOnly) params.favorite = true;
    if (dateRange.date_from) params.date_from = dateRange.date_from;
    if (dateRange.date_to) params.date_to = dateRange.date_to;
    const r = await api.get("/journal", { params });
    setEntries(r.data);
  };
  const loadTrend = async () => {
    const r = await api.get("/journal/trend", { params: { days: trendDays } });
    setTrend(r.data.days || []);
  };
  const loadStats = async () => {
    try {
      const r = await api.get("/journal/stats");
      setStats(r.data);
    } catch { /* silent */ }
  };
  useEffect(() => { load(); }, [q, favOnly, dateRange.date_from, dateRange.date_to]);
  useEffect(() => { loadTrend(); }, [trendDays, entries.length]);
  useEffect(() => { loadStats(); }, [entries.length]);

  // Mood and topic can each have several values selected at once (OR within a filter,
  // AND across filters) - applied client-side since the full period-filtered set is
  // already loaded, same approach as the tag filter on the Task board.
  const toggleMoodFilter = (m) => setMoodFilters((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));
  const toggleTopicFilter = (t) => setTopicFilters((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));
  const allTopics = useMemo(() => Array.from(new Set(entries.flatMap((e) => e.tags || []))).sort((a, b) => a.localeCompare(b)), [entries]);
  const filteredEntries = useMemo(() => entries.filter((e) => {
    if (moodFilters.length > 0 && !moodFilters.includes(e.mood)) return false;
    if (topicFilters.length > 0 && !(e.tags || []).some((t) => topicFilters.includes(t))) return false;
    return true;
  }), [entries, moodFilters, topicFilters]);

  const save = async () => {
    if (!text.trim() || saving) return;
    setSaving(true);
    try {
      await api.post("/journal", { content: text });
      setText("");
      await load();
      toast.success("Voce di diario salvata");
    } catch (e) {
      toast.error("Errore salvataggio");
    } finally { setSaving(false); }
  };

  const del = async (id) => {
    toast("Eliminare questa voce di diario?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = entries;
          setEntries((es) => es.filter((e) => e.id !== id));
          try { await api.delete(`/journal/${id}`); toast.success("Voce eliminata"); }
          catch { toast.error("Errore"); setEntries(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const toggleFav = async (id, currentVal) => {
    setEntries((es) => es.map((e) => (e.id === id ? { ...e, favorite: !currentVal } : e)));
    try { await api.post(`/journal/${id}/favorite`); }
    catch {
      toast.error("Errore preferito");
      setEntries((es) => es.map((e) => (e.id === id ? { ...e, favorite: currentVal } : e)));
    }
  };

  // ==== Voice ====
  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
      chunksRef.current = [];
      recStartRef.current = Date.now();
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        setTranscribing(true);
        try {
          const fd = new FormData();
          fd.append("file", blob, "voice.webm");
          const res = await fetch(`${API}/voice/transcribe`, { method: "POST", body: fd, credentials: "include" });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const j = await res.json();
          const t = (j.text || "").trim();
          if (!t) { toast.error("Vocale vuoto o non riconosciuto"); return; }
          setText((prev) => prev ? (prev + " " + t) : t);
          toast.success("Trascrizione inserita");
        } catch (e) {
          toast.error("Trascrizione fallita: " + e.message);
        } finally {
          setTranscribing(false);
        }
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setRecording(true);
    } catch (e) { toast.error("Microfono non disponibile: " + e.message); }
  };
  const stopRec = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      setRecording(false);
    }
  };

  // Prepare chart data (short labels)
  const chartData = useMemo(() => trend.map((d) => ({
    date: d.date,
    label: new Date(d.date).toLocaleDateString("it-IT", { day: "2-digit", month: "short" }),
    score: d.score,
    mood: d.mood,
  })), [trend]);

  const hasAnyScore = chartData.some((d) => d.score !== null && d.score !== undefined);

  return (
    <div className="max-w-4xl">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-2xl bg-white/10 flex items-center justify-center"><BookOpen size={18} /></div>
        <div>
          <div className="kicker">· diario</div>
          <h2 className="text-2xl font-bold tracking-tight">Racconta la tua giornata</h2>
        </div>
      </div>

      {/* Composer */}
      <div className={`chat-input-card p-5 rounded-2xl shadow-lg flex flex-col ${composerOpen ? "min-h-[340px]" : ""}`} data-testid="journal-input-card">
        <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
          <div className="kicker-p text-white/85">· oggi · {new Date().toLocaleDateString("it-IT", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</div>
          <button
            data-testid="composer-toggle"
            onClick={() => setComposerOpen((v) => !v)}
            title={composerOpen ? "Chiudi la sezione per scrivere" : "Apri la sezione per scrivere"}
            className="liquid-glass-btn p-1.5 rounded-full text-white/80 hover:text-white"
          >
            {composerOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
        {composerOpen && (
          <>
            <Textarea
              data-testid="journal-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Come è andata oggi? Cosa hai fatto, com'era il tuo umore, cosa vuoi ricordare…"
              className="diary-lines border-0 focus-visible:ring-0 bg-transparent text-base flex-1 min-h-[200px] px-0 resize-none text-white placeholder:text-white/60"
            />
            <div className="flex items-center justify-between pt-2 border-t  gap-2 flex-wrap">
              <div className="flex items-center gap-1.5 text-white/85">
                <button
                  data-testid="journal-mic-btn"
                  onClick={recording ? stopRec : startRec}
                  disabled={transcribing}
                  className={`liquid-glass-btn p-2 rounded-full transition-colors duration-150 inline-flex items-center gap-1.5 ${recording ? "text-white animate-pulse" : ""}`}
                  title={recording ? "Ferma registrazione" : "Registra vocale"}
                >
                  {recording ? <MicOff size={16} /> : <Mic size={16} />}
                  <span className="text-[10px] font-mono-tight uppercase tracking-widest">
                    {recording ? "rec…" : transcribing ? "trascrivo…" : "vocale"}
                  </span>
                </button>
              </div>
              <button data-testid="journal-save" onClick={save} disabled={saving || !text.trim() || transcribing}
                      className="liquid-glass-btn inline-flex items-center gap-2 px-5 py-2 rounded-full font-medium disabled:opacity-50 text-sm">
                <Sparkles size={14} /> {saving ? "mAIPAL sta scrivendo…" : "Salva nel diario"}
              </button>
            </div>
          </>
        )}
      </div>

      {/* Filters (periodo, ricerca, preferiti, umore, argomento) - sopra al riquadro di lettura.
          La riga di icone sceglie QUALE filtro mostrare (come la barra azioni della chat):
          periodo e umore restano aperti di default, gli altri si aprono al click. */}
      <div className="mt-8 p-4 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm space-y-3">
        <div className="flex items-center gap-1.5 md:gap-2 flex-wrap">
          {FILTER_ICONS.map((f) => {
            if (f.key === "topic" && allTopics.length === 0) return null;
            const on = expandedFilters.has(f.key);
            return (
              <button
                key={f.key}
                data-testid={`filter-toggle-${f.key}`}
                onClick={() => toggleFilterSection(f.key)}
                title={f.title}
                aria-label={f.title}
                style={{
                  backgroundColor: on ? f.color : undefined,
                  color: "#CECAD0",
                  opacity: on ? 1 : 0.5,
                  borderColor: on ? f.color : "rgba(206,202,208,0.25)",
                }}
                className="liquid-glass-btn h-8 w-8 md:h-9 md:w-9 rounded-full border shadow-sm flex items-center justify-center transition-all duration-200 hover:opacity-100"
              >
                {f.icon}
              </button>
            );
          })}
          <span className="w-px h-5 bg-white/15 mx-1" />
          <button
            data-testid="fav-filter-toggle"
            onClick={() => setFavOnly((v) => !v)}
            title="Solo giornate memorabili"
            aria-label="Solo giornate memorabili"
            style={{
              backgroundColor: favOnly ? "#F59E0B" : undefined,
              color: "#CECAD0",
              opacity: favOnly ? 1 : 0.5,
              borderColor: favOnly ? "#F59E0B" : "rgba(206,202,208,0.25)",
            }}
            className="liquid-glass-btn h-8 w-8 md:h-9 md:w-9 rounded-full border shadow-sm flex items-center justify-center transition-all duration-200 hover:opacity-100"
          >
            <Star size={15} className={favOnly ? "fill-current" : ""} />
          </button>
        </div>

        {expandedFilters.has("period") && (
          <div className="flex items-center gap-1 flex-wrap pt-3 border-t">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                data-testid={`period-${p.key}`}
                onClick={() => setPeriod(p.key)}
                style={{
                  backgroundColor: period === p.key ? "#DD772F" : undefined,
                  opacity: period === p.key ? 1 : 0.5,
                  borderColor: period === p.key ? "#DD772F" : "rgba(206,202,208,0.25)",
                }}
                className="liquid-glass-btn px-3 py-1.5 rounded-full border text-[10px] font-mono-tight uppercase tracking-widest text-white hover:opacity-100 transition-opacity"
              >
                {p.label}
              </button>
            ))}
            {period === "custom" && (
              <div className="flex items-center gap-2 flex-wrap ml-1">
                <input
                  type="date"
                  data-testid="period-custom-from"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                  style={{ fontFamily: "'Poppins', sans-serif" }}
                  className="bg-white/10 rounded-lg px-2 py-1 text-white text-xs border-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
                />
                <span className="text-white/40 text-xs">–</span>
                <input
                  type="date"
                  data-testid="period-custom-to"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  style={{ fontFamily: "'Poppins', sans-serif" }}
                  className="bg-white/10 rounded-lg px-2 py-1 text-white text-xs border-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
                />
              </div>
            )}
          </div>
        )}

        {expandedFilters.has("mood") && (
          <div className="flex items-center gap-1.5 flex-wrap pt-3 border-t">
            {MOODS.map((m) => {
              const on = moodFilters.includes(m);
              return (
                <button
                  key={m}
                  data-testid={`mood-filter-${m}`}
                  onClick={() => toggleMoodFilter(m)}
                  style={{
                    backgroundColor: on ? "#6D6181" : undefined,
                    opacity: on ? 1 : 0.5,
                    borderColor: on ? "#6D6181" : "rgba(206,202,208,0.25)",
                  }}
                  className="liquid-glass-btn px-3 py-1.5 rounded-full border text-[10px] font-mono-tight uppercase tracking-widest text-white inline-flex items-center gap-1 hover:opacity-100 transition-opacity"
                  title={m}
                >
                  <span>{MOOD_EMOJI[m]}</span> {m}
                </button>
              );
            })}
            {moodFilters.length > 0 && (
              <button onClick={() => setMoodFilters([])} className="text-[10px] text-white/40 hover:text-white/70 px-1.5">✕ azzera</button>
            )}
          </div>
        )}

        {expandedFilters.has("search") && (
          <div className="pt-3 border-t">
            <div className="relative max-w-sm">
              <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/40" />
              <Input
                data-testid="journal-search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Cerca nel diario…"
                className="pl-10 pr-10 h-10 rounded-full bg-white/10"
              />
              {q && (
                <button
                  data-testid="journal-search-clear"
                  onClick={() => setQ("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-white/40 hover:text-white/80"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          </div>
        )}

        {expandedFilters.has("topic") && allTopics.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap pt-3 border-t">
            {allTopics.map((t) => {
              const on = topicFilters.includes(t);
              return (
                <button
                  key={t}
                  data-testid={`topic-filter-${t}`}
                  onClick={() => toggleTopicFilter(t)}
                  style={{
                    backgroundColor: on ? "#8E2E11" : undefined,
                    opacity: on ? 1 : 0.5,
                    borderColor: on ? "#8E2E11" : "rgba(206,202,208,0.25)",
                  }}
                  className="liquid-glass-btn px-3 py-1.5 rounded-full border text-[10px] font-mono-tight uppercase tracking-widest text-white hover:opacity-100 transition-opacity"
                >
                  {t}
                </button>
              );
            })}
            {topicFilters.length > 0 && (
              <button onClick={() => setTopicFilters([])} className="text-[10px] text-white/40 hover:text-white/70 px-1.5">✕ azzera</button>
            )}
          </div>
        )}
      </div>

      {/* Entries: il riquadro per rileggere il diario, formattato come pagine di un diario */}
      <div className="mt-6 space-y-4">
        <div className="kicker">· voci precedenti · {filteredEntries.length}</div>
        {filteredEntries.length === 0 && <div className="text-white/60 text-sm">Nessuna voce trovata con questi filtri.</div>}
        {filteredEntries.map((e) => (
          <div key={e.id} className="p-6 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm" data-testid="journal-entry">
            <div className="flex items-start justify-between gap-3 flex-wrap pb-3 border-b border-white/15">
              <div>
                <div className="font-serif-italic text-lg text-white/90 inline-flex items-center gap-2">
                  <span>{MOOD_EMOJI[e.mood] || "📝"}</span> {formatDiaryDate(e.date)}
                </div>
                <div className="font-semibold text-base text-white mt-1">{e.title || "Diario"}</div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  data-testid="journal-fav"
                  onClick={() => toggleFav(e.id, !!e.favorite)}
                  title={e.favorite ? "Rimuovi da giornate memorabili" : "Segna come giornata memorabile"}
                  className={`liquid-glass-btn p-2 rounded-full transition-colors duration-150 ${e.favorite ? "text-amber-400" : "text-white/60"}`}
                >
                  <Star size={16} className={e.favorite ? "fill-current" : ""} />
                </button>
                <button data-testid="journal-delete" onClick={() => del(e.id)} className="liquid-glass-btn p-2 rounded-full text-white/60 hover:text-red-300"><Trash2 size={14} /></button>
              </div>
            </div>

            <div className="diary-page-lines diary-margin-line mt-3 pt-1 pb-1 prose-answer whitespace-pre-wrap text-[15px] text-white">{e.cleaned_text}</div>

            {(e.tags || []).length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {e.tags.map((t, i) => (
                  <span key={i} className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full bg-white/10 text-white/60">{t}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Stats summary */}
      {stats && (
        <div className="mt-10 grid grid-cols-2 sm:grid-cols-3 gap-3" data-testid="journal-stats">
          <StatCard
            icon={<Notebook size={18} />}
            label="Voci scritte"
            value={new Intl.NumberFormat("it-IT").format(stats.total || 0)}
            hint={stats.total === 1 ? "voce nel diario" : "voci nel diario"}
            color="#DD772F"
          />
          <StatCard
            icon={<BarChart3 size={18} />}
            label="Umore più frequente"
            value={stats.top_mood ? `${MOOD_EMOJI[stats.top_mood.mood] || ""} ${stats.top_mood.mood}` : "—"}
            hint={stats.top_mood ? `${stats.top_mood.count} volte` : "nessun mood ancora"}
            color="#6D6181"
          />
          <StatCard
            icon={<Flame size={18} />}
            label="Streak"
            value={`${stats.streak_days || 0} ${stats.streak_days === 1 ? "giorno" : "giorni"}`}
            hint={stats.streak_days >= 3 ? "continua così!" : "scrivi ogni giorno per crescere"}
            color="#8E2E11"
          />
        </div>
      )}

      {/* Mood trend chart */}
      <div className="mt-8 p-5 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm" data-testid="mood-trend-card">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
          <div className="flex items-center gap-2">
            <TrendingUp size={16} className="text-white/60" />
            <div className="kicker">· trend umore</div>
          </div>
          <div className="flex items-center gap-2">
            {showTrend && (
              <div className="flex items-center gap-1" data-testid="trend-range">
                {[7, 30, 90].map((d) => (
                  <button
                    key={d}
                    data-testid={`trend-${d}`}
                    onClick={() => setTrendDays(d)}
                    style={{
                      backgroundColor: trendDays === d ? "#DD772F" : undefined,
                      opacity: trendDays === d ? 1 : 0.5,
                      borderColor: trendDays === d ? "#DD772F" : "rgba(206,202,208,0.25)",
                    }}
                    className="liquid-glass-btn px-2.5 py-1 rounded-full border text-[10px] font-mono-tight uppercase tracking-widest text-white hover:opacity-100 transition-opacity"
                  >
                    {d}g
                  </button>
                ))}
              </div>
            )}
            <button
              data-testid="trend-toggle"
              onClick={() => setShowTrend((v) => !v)}
              title={showTrend ? "Nascondi trend" : "Mostra trend"}
              className="liquid-glass-btn p-1.5 rounded-full text-white/70 hover:text-white"
            >
              {showTrend ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
        {showTrend && (hasAnyScore ? (
          <>
            <div className="flex items-center flex-wrap gap-x-3 gap-y-1 mb-2 text-[10px] text-white/60" data-testid="mood-legend">
              {[1, 2, 3, 4, 5].map((lvl) => (
                <span key={lvl} className="inline-flex items-center gap-1">
                  <span className="font-mono-tight text-white/80">{lvl}</span> {MOOD_LEVEL_LABEL[lvl]}
                </span>
              ))}
            </div>
            <div className="w-full h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#eee" strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                  <YAxis domain={[1, 5]} ticks={[1, 2, 3, 4, 5]} tick={{ fontSize: 10 }} />
                  <ReferenceLine y={3} stroke="#d1d5db" strokeDasharray="3 3" />
                  <Tooltip
                    contentStyle={{ borderRadius: 12, borderColor: "#e5e7eb", fontSize: 12 }}
                    formatter={(val, _n, item) => [`${MOOD_LEVEL_LABEL[val] || ""} · ${item.payload.mood || "-"}`, "Umore"]}
                    labelFormatter={(l) => l}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#8B5CF6"
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: "#8B5CF6" }}
                    activeDot={{ r: 6 }}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        ) : (
          <div className="text-white/60 text-sm py-8 text-center">Nessun dato di umore ancora. Racconta qualche giornata per vedere il trend.</div>
        ))}
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, hint, color }) {
  return (
    <div className="p-4 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm card-hover flex items-start gap-3" data-testid="stat-card">
      <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0" style={{ backgroundColor: color + "22", color }}>
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-bold uppercase tracking-wider text-white/70">{label}</div>
        <div className="mt-1 text-lg font-semibold text-white truncate capitalize">{value}</div>
        {hint && <div className="text-[11px] text-white/50 mt-0.5">{hint}</div>}
      </div>
    </div>
  );
}
