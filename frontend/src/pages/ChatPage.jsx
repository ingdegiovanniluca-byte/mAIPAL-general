import React, { useEffect, useMemo, useRef, useState } from "react";
import { CloudUpload, Search, CheckSquare, Paperclip, Mic, MicOff, Send, Calendar, Check } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { api, streamChat, API } from "@/lib/api";
import { toast } from "sonner";

const ACTIONS = [
  {
    id: "info_upload",
    key: "upload",
    icon: <CloudUpload size={22} />,
    title: "Caricamento informazioni",
    subtitle: "Archivia documenti, note o dati nel sistema",
    placeholder: "Cosa vuoi salvare nella tua knowledge base?",
  },
  {
    id: "info_request",
    key: "query",
    icon: <Search size={22} />,
    title: "Richiesta informazioni",
    subtitle: "Interroga la base di conoscenza con Claude",
    placeholder: "Cosa vuoi sapere?",
  },
  {
    id: "task_todo",
    key: "todo",
    icon: <CheckSquare size={22} />,
    title: "Salvataggio task o to-do",
    subtitle: "Crea task e sincronizzali con n8n + Supabase",
    placeholder: "Es. Ricordami di chiamare il fornitore martedì alle 15",
  },
];

export default function ChatPage() {
  const [active, setActive] = useState("info_request");
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [liveAnswer, setLiveAnswer] = useState("");
  const [history, setHistory] = useState([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [date, setDate] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const scrollRef = useRef(null);

  const activeAction = useMemo(() => ACTIONS.find((a) => a.id === active), [active]);

  const load = async () => {
    try {
      const r = await api.get("/conversations");
      setHistory(r.data);
    } catch (e) { console.error(e); }
  };
  useEffect(() => { load(); }, []);

  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
      chunksRef.current = [];
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
          setText((prev) => (prev ? prev + " " : "") + (j.text || ""));
          toast.success("Trascrizione completata");
        } catch (e) {
          toast.error("Trascrizione fallita: " + e.message);
        } finally {
          setTranscribing(false);
        }
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setRecording(true);
    } catch (e) {
      toast.error("Microfono non disponibile: " + e.message);
    }
  };

  const stopRec = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      setRecording(false);
    }
  };

  const send = async () => {
    if (!text.trim() || streaming) return;
    setStreaming(true);
    setLiveAnswer("");
    const currentQuestion = text;
    setText("");
    await streamChat(
      { action: active, content: currentQuestion },
      (delta) => setLiveAnswer((s) => s + delta),
      async () => {
        setStreaming(false);
        setLiveAnswer("");
        await load();
        toast.success("Elaborato con Claude Sonnet 5");
      },
      (err) => {
        setStreaming(false);
        toast.error("Errore: " + err.message);
      }
    );
  };

  const filtered = history.filter((h) => {
    if (filter !== "all") {
      const map = { upload: "info_upload", query: "info_request", todo: "task_todo" };
      if (h.action !== map[filter]) return false;
    }
    if (search && !(h.user_message || "").toLowerCase().includes(search.toLowerCase())) return false;
    if (date && !(h.created_at || "").startsWith(date)) return false;
    return true;
  });

  return (
    <div className="max-w-6xl">
      {/* Action selector */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
        {ACTIONS.map((a) => {
          const selected = a.id === active;
          return (
            <button
              key={a.id}
              data-testid={`action-${a.key}`}
              onClick={() => setActive(a.id)}
              className={`text-left card-soft p-5 transition-all duration-200 ${selected ? "card-selected" : "hover:-translate-y-0.5 hover:shadow-md"}`}
            >
              <div className="flex items-start justify-between">
                <div className="w-10 h-10 rounded-xl bg-neutral-100 flex items-center justify-center">{a.icon}</div>
                <span className={`text-[10px] font-mono-tight tracking-widest px-2.5 py-1 rounded-full border ${selected ? "border-[color:var(--accent-blue)] text-[color:var(--accent-blue)]" : "border-neutral-300 text-neutral-500"}`}>
                  {selected ? "ATTIVO" : "SELEZIONA"}
                </span>
              </div>
              <div className="mt-4 text-lg font-semibold">{a.title}</div>
              <div className="text-sm text-neutral-500 mt-1">{a.subtitle}</div>
            </button>
          );
        })}
      </div>

      {/* Input area */}
      <div className="card-soft mt-6 p-5" data-testid="chat-input-card">
        <div className="flex items-center justify-between mb-3">
          <div className="kicker">· {activeAction.title.toLowerCase()}</div>
          <div className="kicker">⌘/Ctrl + ⏎ per inviare</div>
        </div>
        <Textarea
          data-testid="chat-textarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") send();
          }}
          placeholder={activeAction.placeholder}
          className="border-0 focus-visible:ring-0 bg-transparent text-lg min-h-[70px] px-0 resize-none"
        />
        <div className="flex items-center justify-between pt-2 border-t border-neutral-200">
          <div className="flex items-center gap-2 text-neutral-500">
            <button data-testid="attach-btn" className="p-2 rounded-full hover:bg-neutral-100"><Paperclip size={16} /></button>
            <button
              data-testid="mic-btn"
              onClick={recording ? stopRec : startRec}
              disabled={transcribing}
              className={`p-2 rounded-full transition-colors duration-150 ${recording ? "bg-red-100 text-red-600" : "hover:bg-neutral-100"}`}
              title={recording ? "Stop registrazione" : "Registra vocale"}
            >
              {recording ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
            {(recording || transcribing) && (
              <span className="kicker">{recording ? "· registrazione…" : "· trascrivo…"}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="kicker">claude sonnet 5</span>
            <button data-testid="send-btn" onClick={send} disabled={streaming || !text.trim()} className="pill-btn">
              <Send size={14} /> {streaming ? "Elaboro…" : "Invia"}
            </button>
          </div>
        </div>
      </div>

      {/* Streaming answer preview */}
      {(streaming || liveAnswer) && (
        <div className="card-soft mt-6 p-6" ref={scrollRef} data-testid="stream-card">
          <div className="kicker mb-3">in corso · claude</div>
          <div className="prose-answer whitespace-pre-wrap">{liveAnswer}<span className="animate-pulse">▊</span></div>
        </div>
      )}

      {/* History */}
      <div className="mt-10 flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[240px]">
          <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-neutral-400" />
          <Input data-testid="history-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cerca nella cronologia…" className="pl-10 h-11 rounded-full bg-white" />
        </div>
        {[
          ["all", "tutti"],
          ["upload", "upload"],
          ["query", "query"],
          ["todo", "todo"],
        ].map(([k, l]) => (
          <button
            key={k}
            data-testid={`filter-${k}`}
            onClick={() => setFilter(k)}
            className={`px-4 py-2 rounded-full text-xs font-mono-tight uppercase tracking-widest ${filter === k ? "bg-black text-white" : "bg-white border border-neutral-200 text-neutral-500 hover:border-neutral-400"}`}
          >{l}</button>
        ))}
        <div className="flex items-center gap-2">
          <Calendar size={14} className="text-neutral-400" />
          <input data-testid="history-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-11 rounded-full bg-white border border-neutral-200 px-4 text-sm" />
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between">
        <div className="kicker">· cronologia</div>
        <div className="kicker">{filtered.length} messaggi</div>
      </div>

      <div className="mt-4 space-y-4">
        {filtered.length === 0 && <div className="text-neutral-500 text-sm">Nessuna conversazione ancora.</div>}
        {filtered.map((c) => <HistoryCard key={c.conv_id} conv={c} />)}
      </div>
    </div>
  );
}

function HistoryCard({ conv }) {
  const [open, setOpen] = useState(false);
  const actionLabels = {
    info_upload: "Caricamento Informazioni",
    info_request: "Richiesta Informazioni",
    task_todo: "Task / To-Do",
  };
  const badge = (label, ok) => (
    <span className={`text-[10px] font-mono-tight tracking-widest uppercase px-2.5 py-1 rounded-md border ${ok ? "border-green-500/40 text-green-700 bg-green-50" : "border-neutral-300 text-neutral-500 bg-neutral-100"}`}>
      {ok ? <Check size={10} className="inline mr-1" /> : null}{label}
    </span>
  );
  const p = conv.pipeline || {};
  const d = conv.created_at ? new Date(conv.created_at) : null;

  return (
    <div className="card-soft p-5" data-testid="history-card">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-blue-500" />
          <div className="kicker">{actionLabels[conv.action] || conv.action}</div>
          <div className="kicker">· {d ? d.toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</div>
        </div>
        <div className="flex items-center gap-2">
          {badge(p.claude === "ok" ? "✓ claude" : "claude · skip", p.claude === "ok")}
          <span className="text-neutral-300">→</span>
          {badge(p.n8n === "ok" ? "✓ n8n" : "n8n · skip", p.n8n === "ok")}
          <span className="text-neutral-300">→</span>
          {badge(p.mongodb === "ok" ? "✓ mongodb" : "mongodb · skip", p.mongodb === "ok")}
        </div>
      </div>

      <div className="mt-4 bg-neutral-50 rounded-xl p-4 text-neutral-800">{conv.user_message}</div>
      {conv.agent_response && (
        <button onClick={() => setOpen((x) => !x)} className="mt-3 text-sm text-blue-600 hover:underline" data-testid="toggle-answer">
          {open ? "Nascondi risposta" : "Mostra risposta"}
        </button>
      )}
      {open && (
        <div className="mt-3 border-t border-neutral-200 pt-4 prose-answer whitespace-pre-wrap text-[15px]">{conv.agent_response}</div>
      )}
    </div>
  );
}
