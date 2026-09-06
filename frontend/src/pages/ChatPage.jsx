import React, { useEffect, useMemo, useRef, useState } from "react";
import { CloudUpload, Search, CheckSquare, Paperclip, Mic, MicOff, Send, Calendar, Check, X, MessageSquarePlus, Star, Trash2 } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { api, streamChat, API } from "@/lib/api";
import { toast } from "sonner";

const ACTIONS = [
  {
    id: "info_upload", key: "upload", icon: <CloudUpload size={22} />,
    title: "Caricamento informazioni",
    subtitle: "Archivia documenti, note o dati nel sistema",
    placeholder: "Cosa vuoi salvare nella tua knowledge base?",
    color: "#FFAC33",
  },
  {
    id: "info_request", key: "query", icon: <Search size={22} />,
    title: "Richiesta informazioni",
    subtitle: "Interroga la base di conoscenza con Claude",
    placeholder: "Cosa vuoi sapere?",
    color: "#FF0061",
  },
  {
    id: "task_todo", key: "todo", icon: <CheckSquare size={22} />,
    title: "Salvataggio task o to-do",
    subtitle: "Crea task e sincronizzali con n8n + Supabase",
    placeholder: "Es. Ricordami di chiamare il fornitore martedì alle 15",
    color: "#007E9A",
  },
];

const ACTION_COLOR = { info_upload: "#FFAC33", info_request: "#FF0061", task_todo: "#007E9A" };

export default function ChatPage() {
  const [active, setActive] = useState("info_request");
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [history, setHistory] = useState([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [date, setDate] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [pendingVoice, setPendingVoice] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const recStartRef = useRef(0);
  const fileInputRef = useRef(null);

  const [thread, setThread] = useState(null);
  const threadEndRef = useRef(null);

  const activeAction = useMemo(() => ACTIONS.find((a) => a.id === active), [active]);

  const load = async () => {
    try {
      const r = await api.get("/conversations");
      setHistory(r.data);
    } catch (e) { console.error(e); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (threadEndRef.current) threadEndRef.current.scrollIntoView({ behavior: "smooth" });
  }, [thread?.messages?.length, thread?.liveAnswer]);

  const openThread = async (convId) => {
    const r = await api.get(`/conversations/${convId}`);
    const conv = r.data;
    let messages = conv.messages || [];
    if (messages.length === 0 && conv.user_message) {
      messages = [{ role: "user", content: conv.user_message }];
      if (conv.agent_response) messages.push({ role: "assistant", content: conv.agent_response });
    }
    setThread({ conv_id: conv.conv_id, action: conv.action, messages, liveAnswer: "" });
    setActive(conv.action);
  };
  const closeThread = () => setThread(null);

  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
      chunksRef.current = [];
      recStartRef.current = Date.now();
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        const seconds = Math.max(1, Math.round((Date.now() - recStartRef.current) / 1000));
        setPendingVoice({ blob, seconds });
        toast.success(`Vocale pronto (${seconds}s). Premi Invia.`);
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
  const discardVoice = () => { setPendingVoice(null); toast.success("Vocale scartato"); };
  const transcribeBlob = async (blob) => {
    const fd = new FormData();
    fd.append("file", blob, "voice.webm");
    const res = await fetch(`${API}/voice/transcribe`, { method: "POST", body: fd, credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const j = await res.json();
    return (j.text || "").trim();
  };

  const send = async () => {
    if (recording) { stopRec(); await new Promise((r) => setTimeout(r, 400)); }
    if (!text.trim() && attachments.length === 0 && !pendingVoice) return;
    if (streaming || transcribing) return;

    let voiceText = "";
    if (pendingVoice) {
      setTranscribing(true);
      try { voiceText = await transcribeBlob(pendingVoice.blob); }
      catch (e) { toast.error("Trascrizione fallita: " + e.message); setTranscribing(false); return; }
      setTranscribing(false);
      setPendingVoice(null);
      if (!voiceText && !text.trim() && attachments.length === 0) {
        toast.error("Vocale vuoto o non riconosciuto"); return;
      }
    }

    setStreaming(true);
    let currentQuestion = [text.trim(), voiceText].filter(Boolean).join(" ").trim();
    if (attachments.length > 0) {
      const filesLine = attachments.map((a) => `📎 ${a.name}${a.url ? ` (${a.url})` : ""}`).join("\n");
      currentQuestion = (currentQuestion ? currentQuestion + "\n\n" : "") + `Allegati caricati su Drive:\n${filesLine}`;
    }
    setText("");
    setAttachments([]);

    if (thread) {
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "user", content: currentQuestion }], liveAnswer: "" }));
    } else {
      setThread({ conv_id: null, action: active, messages: [{ role: "user", content: currentQuestion }], liveAnswer: "" });
    }

    const payload = { action: active, content: currentQuestion };
    if (thread?.conv_id) payload.conv_id = thread.conv_id;

    await streamChat(
      payload,
      (delta) => setThread((th) => (th ? { ...th, liveAnswer: (th.liveAnswer || "") + delta } : th)),
      async (convId) => {
        setStreaming(false);
        setThread((th) => {
          if (!th) return th;
          const finalized = th.liveAnswer || "";
          return { ...th, conv_id: convId, messages: [...th.messages, { role: "assistant", content: finalized }], liveAnswer: "" };
        });
        await load();
      },
      (err) => { setStreaming(false); toast.error("Errore: " + err.message); }
    );
  };

  const onAttachClick = () => fileInputRef.current?.click();
  const onFilesPicked = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    e.target.value = "";
    for (const f of files) {
      try {
        const fd = new FormData();
        fd.append("file", f, f.name);
        const res = await fetch(`${API}/attachments/upload`, { method: "POST", body: fd, credentials: "include" });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const j = await res.json();
        setAttachments((a) => [...a, { name: f.name, id: j.file_id, url: j.web_view_link }]);
        toast.success(`${f.name} → Drive`);
      } catch (err) { toast.error(`Upload ${f.name}: ${err.message}`); }
    }
  };
  const removeAttachment = (i) => setAttachments((a) => a.filter((_, idx) => idx !== i));

  const filtered = history.filter((h) => {
    if (filter === "fav") { if (!h.favorite) return false; }
    else if (filter !== "all") {
      const map = { upload: "info_upload", query: "info_request", todo: "task_todo" };
      if (h.action !== map[filter]) return false;
    }
    if (search && !(h.user_message || "").toLowerCase().includes(search.toLowerCase())) return false;
    if (date && !(h.created_at || "").startsWith(date)) return false;
    return true;
  });

  const toggleFavorite = async (convId, currentVal) => {
    setHistory((hs) => hs.map((h) => (h.conv_id === convId ? { ...h, favorite: !currentVal } : h)));
    try { await api.post(`/conversations/${convId}/favorite`); }
    catch { toast.error("Errore preferito"); setHistory((hs) => hs.map((h) => (h.conv_id === convId ? { ...h, favorite: currentVal } : h))); }
  };
  const deleteConv = async (convId) => {
    if (!confirm("Eliminare questa conversazione?")) return;
    const prev = history;
    setHistory((hs) => hs.filter((h) => h.conv_id !== convId));
    try {
      await api.delete(`/conversations/${convId}`);
      if (thread?.conv_id === convId) setThread(null);
      toast.success("Eliminata");
    } catch { toast.error("Errore"); setHistory(prev); }
  };

  return (
    <div className="relative w-full">
      {/* Ambient gradient blobs for frosted feel */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-40 -left-20 w-[520px] h-[520px] rounded-full opacity-40 blur-3xl" style={{ background: "radial-gradient(circle, #6EB7EC 0%, transparent 60%)" }} />
        <div className="absolute top-1/3 right-0 w-[480px] h-[480px] rounded-full opacity-30 blur-3xl" style={{ background: "radial-gradient(circle, #FF0061 0%, transparent 60%)" }} />
        <div className="absolute bottom-0 left-1/3 w-[520px] h-[520px] rounded-full opacity-25 blur-3xl" style={{ background: "radial-gradient(circle, #FFAC33 0%, transparent 60%)" }} />
        <div className="absolute bottom-10 right-1/4 w-[420px] h-[420px] rounded-full opacity-25 blur-3xl" style={{ background: "radial-gradient(circle, #007E9A 0%, transparent 60%)" }} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full">
        {/* LEFT 1/3 — sticky non-scrollable */}
        <aside className="lg:col-span-1 lg:sticky lg:top-6 self-start space-y-3">
          {ACTIONS.map((a) => {
            const selected = a.id === active;
            return (
              <button
                key={a.id}
                data-testid={`action-${a.key}`}
                onClick={() => { setActive(a.id); if (thread && thread.action !== a.id) setThread(null); }}
                style={{ backgroundColor: "#6EB7EC", opacity: selected ? 1 : 0.6, border: "none" }}
                className={`w-full flex items-center gap-3 text-left rounded-2xl py-3 px-4 text-white transition-all duration-200 ${selected ? "shadow-md" : "hover:opacity-80"} backdrop-blur-xl`}
              >
                <div className="w-9 h-9 shrink-0 rounded-xl bg-white flex items-center justify-center" style={{ color: a.color }}>
                  {React.cloneElement(a.icon, { size: 18 })}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold truncate">{a.title}</div>
                  <div className="text-xs text-white/90 truncate">{a.subtitle}</div>
                </div>
                <span className="text-[9px] font-mono-tight tracking-widest px-2 py-0.5 rounded-full shrink-0 bg-white/25 text-white">
                  {selected ? "ATTIVO" : "SEL"}
                </span>
              </button>
            );
          })}

          <div className="p-5 rounded-2xl border border-white/40 shadow-lg" style={{ background: "#6EB7EC" }} data-testid="chat-input-card">
            <div className="flex items-center justify-between mb-3">
              <div className="kicker text-white/85">· {thread ? "continua la conversazione" : activeAction.title.toLowerCase()}</div>
            </div>
            <Textarea
              data-testid="chat-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") send(); }}
              placeholder={thread ? "Rispondi o chiedi altro nel contesto…" : activeAction.placeholder}
              className="border-0 focus-visible:ring-0 bg-transparent text-base min-h-[110px] px-0 resize-none text-white placeholder:text-white/70"
            />
            <div className="flex items-center justify-between pt-2 border-t border-white/25">
              <div className="flex items-center gap-1.5 text-white/85 flex-wrap">
                <button data-testid="attach-btn" onClick={onAttachClick} className="p-2 rounded-full hover:bg-white/15"><Paperclip size={16} /></button>
                <button
                  data-testid="mic-btn"
                  onClick={recording ? stopRec : startRec}
                  disabled={transcribing}
                  className={`p-2 rounded-full transition-colors duration-150 ${recording ? "bg-white/30 text-white animate-pulse" : "hover:bg-white/15"}`}
                >{recording ? <MicOff size={16} /> : <Mic size={16} />}</button>
                {(recording || transcribing) && <span className="kicker text-white/80">{recording ? "· rec…" : "· trascrivo…"}</span>}
                {pendingVoice && !recording && !transcribing && (
                  <span data-testid="voice-chip" className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/25 text-white flex items-center gap-1">
                    🎙️ {pendingVoice.seconds}s
                    <button onClick={discardVoice} data-testid="voice-discard"><X size={10} /></button>
                  </span>
                )}
                {attachments.map((a, i) => (
                  <span key={i} className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/20 text-white flex items-center gap-1">
                    📎 {a.name.slice(0,12)}{a.name.length > 12 ? "…" : ""}
                    <button onClick={() => removeAttachment(i)}><X size={10} /></button>
                  </span>
                ))}
              </div>
              <button data-testid="send-btn" onClick={send}
                disabled={streaming || transcribing || (!text.trim() && attachments.length === 0 && !pendingVoice && !recording)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white text-[#0A6BBF] font-medium disabled:opacity-50 hover:bg-white/95 text-sm">
                <Send size={14} /> {streaming ? "Elaboro…" : transcribing ? "Trascrivo…" : recording ? "Ferma & invia" : "Invia"}
              </button>
            </div>
            <input ref={fileInputRef} type="file" multiple hidden onChange={onFilesPicked} data-testid="file-input" />
          </div>
        </aside>

        {/* RIGHT 2/3 — scrolls */}
        <section className="lg:col-span-2 space-y-4">
          {/* Filters */}
          <div className="flex items-center gap-3 flex-wrap p-4 rounded-2xl bg-white/60 border border-white/50 backdrop-blur-xl shadow-sm">
            <div className="relative flex-1 min-w-[220px]">
              <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-neutral-400" />
              <Input data-testid="history-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cerca nella cronologia…" className="pl-10 h-10 rounded-full bg-white/80" />
            </div>
            {[["all","tutti"],["fav","preferiti"],["upload","upload"],["query","query"],["todo","todo"]].map(([k, l]) => (
              <button key={k} data-testid={`filter-${k}`} onClick={() => setFilter(k)}
                style={filter === k ? { backgroundColor: "#6EB7EC", color: "#fff", border: "none" } : {}}
                className={`px-3 py-2 rounded-full text-[10px] font-mono-tight uppercase tracking-widest inline-flex items-center gap-1.5 ${filter === k ? "" : "bg-white/70 border border-neutral-200 text-neutral-500 hover:border-neutral-400"}`}
              >{k === "fav" && <Star size={11} className={filter === k ? "fill-current" : ""} />}{l}</button>
            ))}
            <input data-testid="history-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-10 rounded-full bg-white/80 border border-neutral-200 px-4 text-sm" />
          </div>

          {/* Thread view (replaces list when open) */}
          {thread ? (
            <div className="p-5 rounded-2xl bg-white/70 border border-white/50 backdrop-blur-xl shadow-sm" data-testid="thread-card">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ACTION_COLOR[thread.action] || "#6EB7EC" }} />
                  <div className="kicker">
                    {thread.action === "info_upload" ? "caricamento" : thread.action === "info_request" ? "richiesta" : "task / to-do"}
                    {" · thread "}{thread.conv_id ? thread.conv_id.slice(-6) : "nuovo"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button data-testid="new-thread-btn" onClick={() => setThread(null)} className="kicker px-3 py-1.5 rounded-full border border-neutral-200 bg-white hover:border-neutral-400 inline-flex items-center gap-1">
                    <MessageSquarePlus size={12} /> nuova
                  </button>
                  <button data-testid="close-thread-btn" onClick={closeThread} className="p-1.5 rounded-full hover:bg-neutral-100"><X size={14} /></button>
                </div>
              </div>
              <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-2">
                {thread.messages.map((m, i) => (
                  <div key={i}>
                    <div className="kicker mb-1">{m.role === "user" ? "· tu" : "· mAIPAL"}</div>
                    <div className={m.role === "user" ? "bg-neutral-100 rounded-2xl px-4 py-3 text-neutral-800" : "prose-answer whitespace-pre-wrap text-[15px] px-4 py-2"}>
                      {m.content}
                    </div>
                  </div>
                ))}
                {streaming && thread.liveAnswer !== undefined && (
                  <div>
                    <div className="kicker mb-1">· mAIPAL</div>
                    <div className="prose-answer whitespace-pre-wrap text-[15px] px-4 py-2">
                      {thread.liveAnswer}<span className="animate-pulse">▊</span>
                    </div>
                  </div>
                )}
                <div ref={threadEndRef} />
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between px-2">
                <div className="kicker">· cronologia</div>
                <div className="kicker">{filtered.length} messaggi</div>
              </div>
              <div className="space-y-3">
                {filtered.length === 0 && <div className="text-neutral-500 text-sm">Nessuna conversazione ancora.</div>}
                {filtered.map((c) => (
                  <HistoryCard
                    key={c.conv_id}
                    conv={c}
                    onOpen={() => openThread(c.conv_id)}
                    onToggleFav={() => toggleFavorite(c.conv_id, !!c.favorite)}
                    onDelete={() => deleteConv(c.conv_id)}
                  />
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function HistoryCard({ conv, onOpen, onToggleFav, onDelete }) {
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
  const preview = (conv.messages && conv.messages[0]?.content) || conv.user_message || "";
  const messageCount = (conv.messages?.length || 0) || (conv.user_message ? (conv.agent_response ? 2 : 1) : 0);
  const isFav = !!conv.favorite;
  // Short summary: prefer meta.summary; else last assistant reply first N chars
  const rawSummary = (conv.meta && conv.meta.summary) || conv.agent_response || (conv.messages && [...conv.messages].reverse().find((m) => m.role === "assistant")?.content) || "";
  const summary = rawSummary.replace(/\s+/g, " ").trim().slice(0, 180) + (rawSummary.length > 180 ? "…" : "");
  const stop = (fn) => (e) => { e.stopPropagation(); e.preventDefault(); fn(); };

  return (
    <div className="p-4 rounded-2xl bg-white/70 border border-white/50 backdrop-blur-xl shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md" data-testid="history-card">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: ACTION_COLOR[conv.action] || "#6EB7EC" }} />
          <div className="kicker">{actionLabels[conv.action] || conv.action}</div>
          <div className="kicker">· {d ? d.toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</div>
          {messageCount > 2 && <div className="kicker">· {messageCount} msg</div>}
        </div>
        <div className="flex items-center gap-1.5">
          <button data-testid="fav-btn" onClick={stop(onToggleFav)} title={isFav ? "Rimuovi preferito" : "Preferito"}
            className={`p-1.5 rounded-full transition-colors duration-150 ${isFav ? "text-amber-500 hover:bg-amber-50" : "text-neutral-400 hover:bg-neutral-100 hover:text-amber-500"}`}>
            <Star size={14} className={isFav ? "fill-current" : ""} />
          </button>
          <button data-testid="delete-conv-btn" onClick={stop(onDelete)} title="Elimina"
            className="p-1.5 rounded-full text-neutral-400 hover:bg-red-50 hover:text-red-600">
            <Trash2 size={14} />
          </button>
          <span className="w-px h-4 bg-neutral-200 mx-1" />
          {badge(p.claude === "ok" ? "✓ claude" : "claude · skip", p.claude === "ok")}
          {badge(p.mongodb === "ok" ? "✓ db" : "db · skip", p.mongodb === "ok")}
        </div>
      </div>

      <button onClick={onOpen} className="w-full text-left mt-3" data-testid="open-thread-btn">
        <div className="bg-neutral-50/70 rounded-xl p-3 text-neutral-800 line-clamp-2">{preview}</div>
        {summary && (
          <div className="mt-2 text-xs text-neutral-500 line-clamp-2 leading-relaxed" data-testid="conv-summary">
            {summary}
          </div>
        )}
        <div className="mt-2 kicker text-blue-600">apri thread →</div>
      </button>
    </div>
  );
}
