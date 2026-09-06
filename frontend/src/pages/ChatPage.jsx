import React, { useEffect, useMemo, useRef, useState } from "react";
import { CloudUpload, Search, CheckSquare, Paperclip, Mic, MicOff, Send, Calendar, Check, X, MessageSquarePlus, Star, Trash2, Maximize2, Minimize2, BookOpen, Layers, Database } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { api, streamChat, API } from "@/lib/api";
import { toast } from "sonner";

const ACTIONS = [
  {
    id: "info_request", key: "query", icon: <Search size={22} />,
    title: "Richiesta informazioni",
    subtitle: "Interroga la base di conoscenza con Claude",
    placeholder: "Cosa vuoi sapere?",
    color: "#DD772F",
  },
  {
    id: "info_upload", key: "upload", icon: <CloudUpload size={22} />,
    title: "Caricamento informazioni",
    subtitle: "Archivia documenti, note o dati nel sistema",
    placeholder: "Cosa vuoi salvare nella tua knowledge base?",
    color: "#6D6181",
  },
  {
    id: "task_todo", key: "todo", icon: <CheckSquare size={22} />,
    title: "Salvataggio task o to-do",
    subtitle: "Crea task e sincronizzali con n8n + Supabase",
    placeholder: "Es. Ricordami di chiamare il fornitore martedì alle 15",
    color: "#7C6A7D",
  },
  {
    id: "journal", key: "journal", icon: <BookOpen size={22} />,
    title: "Diario",
    subtitle: "Racconta la giornata: la salvo nel diario",
    placeholder: "Com'è andata oggi? Cosa vuoi ricordare…",
    color: "#8E2E11",
  },
];

const ACTION_COLOR = { info_upload: "#6D6181", info_request: "#DD772F", task_todo: "#7C6A7D", journal: "#8E2E11" };

export default function ChatPage() {
  const [active, setActive] = useState("info_request");
  const [scope, setScope] = useState("kb"); // 'kb' | 'all' — solo per info_request
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
  const [focusMode, setFocusMode] = useState(false);
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
  const closeThread = () => { setThread(null); setFocusMode(false); };

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
      const kbLine = attachments.filter((a) => a.kb).map((a) => `📎 ${a.name} · ${a.chunks} chunk indicizzati (~${a.chars} caratteri)`).join("\n");
      const driveLine = attachments.filter((a) => !a.kb).map((a) => `📎 ${a.name}${a.url ? ` (${a.url})` : ""}`).join("\n");
      const parts = [];
      if (kbLine) parts.push(`Allegati caricati nella knowledge base personale:\n${kbLine}`);
      if (driveLine) parts.push(`Allegati caricati su Drive:\n${driveLine}`);
      currentQuestion = (currentQuestion ? currentQuestion + "\n\n" : "") + parts.join("\n\n");
    }
    setText("");
    setAttachments([]);

    if (thread) {
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "user", content: currentQuestion }], liveAnswer: "" }));
    } else {
      setThread({ conv_id: null, action: active, messages: [{ role: "user", content: currentQuestion }], liveAnswer: "" });
    }

    const payload = { action: active, content: currentQuestion };
    if (active === "info_request") payload.filters = { scope };
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
    // In info_upload: extract text and save into personal KB (no Google needed)
    // In other actions: keep the previous behaviour (upload to Drive as attachment)
    const useKb = active === "info_upload";
    for (const f of files) {
      try {
        const fd = new FormData();
        fd.append("file", f, f.name);
        const endpoint = useKb ? "/kb/upload" : "/attachments/upload";
        const res = await fetch(`${API}${endpoint}`, { method: "POST", body: fd, credentials: "include" });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const j = await res.json();
        if (useKb) {
          setAttachments((a) => [...a, { name: f.name, id: j.doc_id, kb: true, chunks: j.chunks, chars: j.chars, preview: j.preview, ocr: j.source_type === "image_ocr" }]);
          if (j.source_type === "image_ocr") {
            toast.success(`${f.name} → OCR + Knowledge Base (${j.chars} caratteri)`);
          } else {
            toast.success(`${f.name} → Knowledge Base (${j.chunks} chunk)`);
          }
        } else {
          setAttachments((a) => [...a, { name: f.name, id: j.file_id, url: j.web_view_link }]);
          toast.success(`${f.name} → Drive`);
        }
      } catch (err) { toast.error(`Upload ${f.name}: ${err.message}`); }
    }
  };
  const removeAttachment = (i) => setAttachments((a) => a.filter((_, idx) => idx !== i));

  const filtered = history.filter((h) => {
    if (filter === "fav") { if (!h.favorite) return false; }
    else if (filter !== "all") {
      const map = { upload: "info_upload", query: "info_request", todo: "task_todo", journal: "journal" };
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
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full h-[calc(100vh-15rem)]">
        {/* LEFT 1/3 — action icons + input area */}
        <aside className={`lg:col-span-1 flex flex-col overflow-y-auto pr-1 ${focusMode ? "hidden" : ""}`}>
          {/* Top block mirrors the right-side filter bar (same padding/height) so the input aligns with the first history card */}
          <div className="p-4 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm shrink-0">
            <div className="flex items-center gap-3 justify-start">
              {ACTIONS.map((a) => {
                const selected = a.id === active;
                return (
                  <button
                    key={a.id}
                    data-testid={`action-${a.key}`}
                    onClick={() => { setActive(a.id); if (thread && thread.action !== a.id) setThread(null); }}
                    title={a.title}
                    aria-label={a.title}
                    style={{
                      backgroundColor: selected ? a.color : "transparent",
                      color: "#CECAD0",
                      opacity: selected ? 1 : 0.5,
                      borderColor: selected ? a.color : "rgba(206,202,208,0.25)",
                    }}
                    className={`group relative w-10 h-10 rounded-xl border shadow-sm flex items-center justify-center transition-all duration-200 hover:opacity-100 hover:-translate-y-0.5 hover:shadow-md`}
                  >
                    {React.cloneElement(a.icon, { size: 18 })}
                    <span className="pointer-events-none absolute -bottom-9 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-lg bg-[#403A3C] text-white text-[11px] font-medium px-2.5 py-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150 shadow-lg z-30">
                      {a.title}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="flex items-center justify-between px-2 mt-4 shrink-0">
            <div className="kicker-p">· nuovo messaggio</div>
            <div className="kicker-p">{activeAction.title.toLowerCase()}</div>
          </div>
          <div className="p-5 rounded-2xl shadow-lg mt-2 min-h-[340px] flex flex-col" style={{ background: "linear-gradient(to right, #D97B48 0%, #8B636B 50%, #302F4A 100%)" }} data-testid="chat-input-card">
            <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
              <div className="kicker-p text-white/85">· {thread ? "continua la conversazione" : activeAction.title.toLowerCase()}</div>
              {active === "info_request" && !thread && (
                <div className="flex items-center gap-1 bg-white/10 rounded-full p-0.5" data-testid="scope-selector">
                  <button
                    data-testid="scope-all"
                    onClick={() => setScope("all")}
                    className={`px-2.5 py-1 rounded-full text-[10px] font-mono-tight uppercase tracking-widest inline-flex items-center gap-1 transition-all ${scope === "all" ? "bg-[#CECAD0] text-[#403A3C]" : "text-white/80 hover:bg-white/10"}`}
                    title="Cerca su Task, To-Do, Knowledge Base e Diario"
                  >
                    <Layers size={11} /> tutto
                  </button>
                  <button
                    data-testid="scope-kb"
                    onClick={() => setScope("kb")}
                    className={`px-2.5 py-1 rounded-full text-[10px] font-mono-tight uppercase tracking-widest inline-flex items-center gap-1 transition-all ${scope === "kb" ? "bg-[#CECAD0] text-[#403A3C]" : "text-white/80 hover:bg-white/10"}`}
                    title="Cerca solo nella Knowledge Base"
                  >
                    <Database size={11} /> solo kb
                  </button>
                </div>
              )}
            </div>
            <Textarea
              data-testid="chat-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") send(); }}
              placeholder={thread ? "Rispondi o chiedi altro nel contesto…" : activeAction.placeholder}
              className="border-0 focus-visible:ring-0 bg-transparent text-base flex-1 min-h-[200px] px-0 resize-none text-white placeholder:text-white/60"
            />
            <div className="flex items-center justify-between pt-2 border-t ">
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
                  <span key={i} className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/20 text-white flex items-center gap-1" title={a.preview || a.name}>
                    {a.ocr ? "🖼️" : "📎"} {a.name.slice(0,12)}{a.name.length > 12 ? "…" : ""}
                    {a.ocr && <span className="opacity-70">· ocr</span>}
                    <button onClick={() => removeAttachment(i)}><X size={10} /></button>
                  </span>
                ))}
              </div>
              <button data-testid="send-btn" onClick={send}
                disabled={streaming || transcribing || (!text.trim() && attachments.length === 0 && !pendingVoice && !recording)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-[#CECAD0] text-[#403A3C] font-medium disabled:opacity-50 hover:bg-white text-sm">
                <Send size={14} /> {streaming ? "Elaboro…" : transcribing ? "Trascrivo…" : recording ? "Ferma & invia" : "Invia"}
              </button>
            </div>
            <input ref={fileInputRef} type="file" multiple hidden onChange={onFilesPicked} accept={active === "info_upload" ? ".pdf,.docx,.xlsx,.txt,.md,.csv,.json,.html,.xml,.yaml,.yml,.log,.jpg,.jpeg,.png,.webp,.heic,.heif" : undefined} data-testid="file-input" />
          </div>
        </aside>

        {/* RIGHT 2/3 — scrolls */}
        <section className={`${focusMode ? "lg:col-span-3" : "lg:col-span-2"} flex flex-col h-full overflow-hidden`}>
          {/* Filters (hidden in focus mode when a thread is open) */}
          {!(focusMode && thread) && (
            <div className="flex items-center gap-3 flex-wrap p-4 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm shrink-0">
            <div className="relative flex-1 min-w-[220px]">
              <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/60" />
              <Input data-testid="history-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cerca nella cronologia…" className="pl-10 h-10 rounded-full bg-white/10  text-white placeholder:text-white/60" />
            </div>
            {[["all","tutti"],["fav","preferiti"],["upload","upload"],["query","query"],["todo","todo"],["journal","diario"]].map(([k, l]) => (
              <button key={k} data-testid={`filter-${k}`} onClick={() => setFilter(k)}
                style={filter === k ? { backgroundColor: "#CECAD0", color: "#403A3C", border: "none" } : {}}
                className={`px-3 py-2 rounded-full text-[10px] font-mono-tight uppercase tracking-widest inline-flex items-center gap-1.5 ${filter === k ? "" : "bg-white/10  text-white/70 hover: hover:text-white"}`}
              >{k === "fav" && <Star size={11} className={filter === k ? "fill-current" : ""} />}{l}</button>
            ))}
            <input data-testid="history-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-10 rounded-full bg-white/10  text-white px-4 text-sm" />
          </div>
          )}

          {/* Thread view (replaces list when open) */}
          {thread ? (
            <div className="p-5 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm flex-1 flex flex-col mt-4 overflow-hidden" data-testid="thread-card">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ACTION_COLOR[thread.action] || "#CECAD0" }} />
                  <div className="kicker">
                    {thread.action === "info_upload" ? "caricamento" : thread.action === "info_request" ? "richiesta" : thread.action === "journal" ? "diario" : "task / to-do"}
                    {" · thread "}{thread.conv_id ? thread.conv_id.slice(-6) : "nuovo"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button data-testid="focus-mode-btn" onClick={() => setFocusMode((v) => !v)} className="kicker px-3 py-1.5 rounded-full  bg-white/10 text-white hover: inline-flex items-center gap-1" title={focusMode ? "Esci focus" : "Modalità focus"}>
                    {focusMode ? <Minimize2 size={12} /> : <Maximize2 size={12} />} {focusMode ? "esci focus" : "focus"}
                  </button>
                  <button data-testid="new-thread-btn" onClick={() => { setThread(null); setFocusMode(false); }} className="kicker px-3 py-1.5 rounded-full  bg-white/10 text-white hover: inline-flex items-center gap-1">
                    <MessageSquarePlus size={12} /> nuova
                  </button>
                  <button data-testid="close-thread-btn" onClick={closeThread} className="p-1.5 rounded-full hover:bg-white/10 text-white"><X size={14} /></button>
                </div>
              </div>
              <div className="space-y-4 flex-1 overflow-y-auto pr-2">
                {thread.messages.map((m, i) => (
                  <div key={i}>
                    <div className="kicker mb-1">{m.role === "user" ? "· tu" : ""}</div>
                    <div className={m.role === "user" ? "bg-white/10 rounded-2xl px-4 py-3 text-white" : "prose-answer whitespace-pre-wrap text-[15px] px-4 py-2 text-white"}>
                      {m.content}
                    </div>
                  </div>
                ))}
                {streaming && thread.liveAnswer !== undefined && (
                  <div>
                    <div className="kicker mb-1"></div>
                    <div className="prose-answer whitespace-pre-wrap text-[15px] px-4 py-2 text-white">
                      {thread.liveAnswer}<span className="animate-pulse">▊</span>
                    </div>
                  </div>
                )}
                <div ref={threadEndRef} />
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between px-2 mt-4 shrink-0">
                <div className="kicker">· cronologia</div>
                <div className="kicker">{filtered.length} messaggi</div>
              </div>
              <div className="space-y-3 flex-1 overflow-y-auto pr-1 mt-2">
                {filtered.length === 0 && <div className="text-white/60 text-sm">Nessuna conversazione ancora.</div>}
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
    journal: "Diario",
  };
  const d = conv.created_at ? new Date(conv.created_at) : null;
  const preview = (conv.messages && conv.messages[0]?.content) || conv.user_message || "";
  const messageCount = (conv.messages?.length || 0) || (conv.user_message ? (conv.agent_response ? 2 : 1) : 0);
  const isFav = !!conv.favorite;
  const title = conv.title || (conv.meta && conv.meta.title) || "";
  const rawSummary = conv.summary || (conv.meta && conv.meta.summary) || conv.agent_response || (conv.messages && [...conv.messages].reverse().find((m) => m.role === "assistant")?.content) || "";
  const collapsed = rawSummary.replace(/\s+/g, " ").trim();
  const summary = collapsed.length > 180 ? collapsed.slice(0, 180) + "…" : collapsed;
  const stop = (fn) => (e) => { e.stopPropagation(); e.preventDefault(); fn(); };

  return (
    <div className="p-4 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md hover:bg-white/10" data-testid="history-card">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: ACTION_COLOR[conv.action] || "#CECAD0" }} />
          <div className="kicker-p">{actionLabels[conv.action] || conv.action}</div>
          <div className="kicker-p">· {d ? d.toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</div>
          {messageCount > 2 && <div className="kicker-p">· {messageCount} msg</div>}
        </div>
        <div className="flex items-center gap-1.5">
          <button data-testid="fav-btn" onClick={stop(onToggleFav)} title={isFav ? "Rimuovi preferito" : "Preferito"}
            className={`p-1.5 rounded-full transition-colors duration-150 ${isFav ? "text-amber-300 hover:bg-white/10" : "text-white/50 hover:bg-white/10 hover:text-amber-300"}`}>
            <Star size={14} className={isFav ? "fill-current" : ""} />
          </button>
          <button data-testid="delete-conv-btn" onClick={stop(onDelete)} title="Elimina"
            className="p-1.5 rounded-full text-white/50 hover:bg-red-500/20 hover:text-red-300">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <button onClick={onOpen} className="w-full text-left mt-3" data-testid="open-thread-btn">
        {title && <div className="text-sm font-semibold mb-1 text-[#403A3C]" data-testid="conv-title">{title}</div>}
        <div className="bg-white/5 rounded-xl p-3 text-sm text-white/90 line-clamp-2">{preview}</div>
        {summary && (
          <div className="mt-2 text-xs text-white/60 line-clamp-2 leading-relaxed" data-testid="conv-summary">
            {summary}
          </div>
        )}
        <div className="mt-2 kicker text-[#CECAD0]">apri thread →</div>
      </button>
    </div>
  );
}
