import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, API } from "@/lib/api";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { BookOpen, Trash2, Sparkles, Mic, MicOff, Search, X, TrendingUp, Star } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";

const MOODS = ["felice", "grato", "energico", "riflessivo", "neutro", "stanco", "stressato"];
const MOOD_EMOJI = {
  felice: "😊", neutro: "😐", stressato: "😣", riflessivo: "🤔",
  energico: "⚡", stanco: "😴", grato: "🙏",
};

const MOOD_LABEL_BY_SCORE = { 1: "😣", 2: "😴", 3: "😐", 4: "⚡", 5: "😊" };

export default function JournalPage() {
  const [entries, setEntries] = useState([]);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  // Search & filter
  const [q, setQ] = useState("");
  const [mood, setMood] = useState("all");
  const [favOnly, setFavOnly] = useState(false);

  // Voice recording
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const recStartRef = useRef(0);

  // Trend
  const [trend, setTrend] = useState([]);
  const [trendDays, setTrendDays] = useState(7);

  const load = async () => {
    const params = {};
    if (q.trim()) params.q = q.trim();
    if (mood && mood !== "all") params.mood = mood;
    if (favOnly) params.favorite = true;
    const r = await api.get("/journal", { params });
    setEntries(r.data);
  };
  const loadTrend = async () => {
    const r = await api.get("/journal/trend", { params: { days: trendDays } });
    setTrend(r.data.days || []);
  };
  useEffect(() => { load(); }, [q, mood, favOnly]);
  useEffect(() => { loadTrend(); }, [trendDays, entries.length]);

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
    if (!confirm("Eliminare questa voce di diario?")) return;
    const prev = entries;
    setEntries((es) => es.filter((e) => e.id !== id));
    try { await api.delete(`/journal/${id}`); toast.success("Voce eliminata"); }
    catch { toast.error("Errore"); setEntries(prev); }
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
        <div className="w-10 h-10 rounded-2xl bg-neutral-100 flex items-center justify-center"><BookOpen size={18} /></div>
        <div>
          <div className="kicker">· diario</div>
          <h2 className="text-2xl font-bold tracking-tight">Racconta la tua giornata</h2>
        </div>
      </div>

      {/* Composer */}
      <div className="rounded-2xl p-5 shadow-md" style={{ background: "#6EB7EC" }}>
        <div className="kicker text-white/85 mb-3">· oggi · {new Date().toLocaleDateString("it-IT", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</div>
        <Textarea
          data-testid="journal-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Come è andata oggi? Cosa hai fatto, com'era il tuo umore, cosa vuoi ricordare…"
          className="border-0 focus-visible:ring-0 bg-transparent text-base min-h-[160px] px-0 resize-none text-white placeholder:text-white/70"
        />
        <div className="flex items-center justify-between pt-2 border-t  gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 text-white/85">
            <button
              data-testid="journal-mic-btn"
              onClick={recording ? stopRec : startRec}
              disabled={transcribing}
              className={`p-2 rounded-full transition-colors duration-150 inline-flex items-center gap-1.5 ${recording ? "bg-white/30 text-white animate-pulse" : "hover:bg-white/15"}`}
              title={recording ? "Ferma registrazione" : "Registra vocale"}
            >
              {recording ? <MicOff size={16} /> : <Mic size={16} />}
              <span className="text-[10px] font-mono-tight uppercase tracking-widest">
                {recording ? "rec…" : transcribing ? "trascrivo…" : "vocale"}
              </span>
            </button>
          </div>
          <button data-testid="journal-save" onClick={save} disabled={saving || !text.trim() || transcribing}
                  className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-white text-[#0A6BBF] font-medium disabled:opacity-50 hover:bg-white/95 text-sm">
            <Sparkles size={14} /> {saving ? "mAIPAL sta scrivendo…" : "Salva nel diario"}
          </button>
        </div>
      </div>

      {/* Mood trend chart */}
      <div className="mt-8 p-5 rounded-2xl bg-white/70  backdrop-blur-xl shadow-sm" data-testid="mood-trend-card">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
          <div className="flex items-center gap-2">
            <TrendingUp size={16} className="text-neutral-500" />
            <div className="kicker">· trend umore</div>
          </div>
          <div className="flex items-center gap-1 bg-neutral-100 rounded-full p-0.5" data-testid="trend-range">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                data-testid={`trend-${d}`}
                onClick={() => setTrendDays(d)}
                className={`px-2.5 py-1 rounded-full text-[10px] font-mono-tight uppercase tracking-widest transition-all ${trendDays === d ? "bg-[#6EB7EC] text-white shadow-sm" : "text-neutral-500 hover:text-neutral-800"}`}
              >
                {d}g
              </button>
            ))}
          </div>
        </div>
        {hasAnyScore ? (
          <div className="w-full h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#eee" strokeDasharray="3 3" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                <YAxis domain={[1, 5]} ticks={[1, 2, 3, 4, 5]} tick={{ fontSize: 10 }} tickFormatter={(v) => MOOD_LABEL_BY_SCORE[v] || v} />
                <ReferenceLine y={3} stroke="#d1d5db" strokeDasharray="3 3" />
                <Tooltip
                  contentStyle={{ borderRadius: 12, borderColor: "#e5e7eb", fontSize: 12 }}
                  formatter={(val, _n, item) => [`${MOOD_EMOJI[item.payload.mood] || ""} ${item.payload.mood || "-"}`, "Umore"]}
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
        ) : (
          <div className="text-neutral-500 text-sm py-8 text-center">Nessun dato di umore ancora. Racconta qualche giornata per vedere il trend.</div>
        )}
      </div>

      {/* Search + mood filter */}
      <div className="mt-8 p-4 rounded-2xl bg-white/60  backdrop-blur-xl shadow-sm">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-neutral-400" />
            <Input
              data-testid="journal-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Cerca nel diario…"
              className="pl-10 pr-10 h-10 rounded-full bg-white/80"
            />
            {q && (
              <button
                data-testid="journal-search-clear"
                onClick={() => setQ("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-700"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1 flex-wrap">
            <button
              key="all"
              data-testid="fav-filter-off"
              onClick={() => setFavOnly(false)}
              style={!favOnly ? { backgroundColor: "#6EB7EC", color: "#fff", border: "none" } : {}}
              className={`px-3 py-1.5 rounded-full text-[10px] font-mono-tight uppercase tracking-widest ${!favOnly ? "" : "bg-white/70  text-neutral-500 hover:"}`}
            >tutti</button>
            <button
              data-testid="fav-filter-on"
              onClick={() => setFavOnly(true)}
              style={favOnly ? { backgroundColor: "#F59E0B", color: "#fff", border: "none" } : {}}
              className={`px-3 py-1.5 rounded-full text-[10px] font-mono-tight uppercase tracking-widest inline-flex items-center gap-1 ${favOnly ? "" : "bg-white/70  text-neutral-500 hover:"}`}
              title="Solo giornate memorabili"
            >
              <Star size={11} className={favOnly ? "fill-current" : ""} /> preferiti
            </button>
            <span className="w-px h-4 bg-neutral-300 mx-1" />
            <button
              key="mood-all"
              data-testid="mood-filter-all"
              onClick={() => setMood("all")}
              style={mood === "all" ? { backgroundColor: "#6EB7EC", color: "#fff", border: "none" } : {}}
              className={`px-3 py-1.5 rounded-full text-[10px] font-mono-tight uppercase tracking-widest ${mood === "all" ? "" : "bg-white/70  text-neutral-500 hover:"}`}
            >ogni umore</button>
            {MOODS.map((m) => (
              <button
                key={m}
                data-testid={`mood-filter-${m}`}
                onClick={() => setMood(m)}
                style={mood === m ? { backgroundColor: "#6EB7EC", color: "#fff", border: "none" } : {}}
                className={`px-3 py-1.5 rounded-full text-[10px] font-mono-tight uppercase tracking-widest inline-flex items-center gap-1 ${mood === m ? "" : "bg-white/70  text-neutral-500 hover:"}`}
                title={m}
              >
                <span>{MOOD_EMOJI[m]}</span> {m}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Entries */}
      <div className="mt-6 space-y-4">
        <div className="kicker">· voci precedenti · {entries.length}</div>
        {entries.length === 0 && <div className="text-neutral-500 text-sm">Nessuna voce trovata con questi filtri.</div>}
        {entries.map((e) => (
          <div key={e.id} className="p-5 rounded-2xl bg-white/70  backdrop-blur-xl shadow-sm" data-testid="journal-entry">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{MOOD_EMOJI[e.mood] || "📝"}</span>
                <div>
                  <div className="font-semibold text-lg">{e.title || "Diario"}</div>
                  <div className="kicker">
                    {new Date(e.date).toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "long", year: "numeric" })}
                    {e.mood ? ` · ${e.mood}` : ""}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  data-testid="journal-fav"
                  onClick={() => toggleFav(e.id, !!e.favorite)}
                  title={e.favorite ? "Rimuovi da giornate memorabili" : "Segna come giornata memorabile"}
                  className={`p-2 rounded-full transition-colors duration-150 ${e.favorite ? "text-amber-500 hover:bg-amber-50" : "text-neutral-400 hover:bg-neutral-100 hover:text-amber-500"}`}
                >
                  <Star size={16} className={e.favorite ? "fill-current" : ""} />
                </button>
                <button data-testid="journal-delete" onClick={() => del(e.id)} className="p-2 rounded-full text-neutral-400 hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
              </div>
            </div>

            <div className="mt-4 prose-answer whitespace-pre-wrap text-[15px] text-neutral-800">{e.cleaned_text}</div>

            {(e.highlights || []).length > 0 && (
              <div className="mt-4 pt-4 border-t ">
                <div className="kicker mb-2">· momenti chiave</div>
                <ul className="text-sm text-neutral-600 space-y-1">
                  {(e.highlights || []).map((h, i) => (<li key={i}>· {h}</li>))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
