import React, { useEffect, useMemo, useRef, useState } from "react";
import { CloudUpload, Search, CheckSquare, Paperclip, Mic, MicOff, Send, Calendar, Check, X, MessageSquarePlus, Star, Trash2, Maximize2, Minimize2, BookOpen, Layers, Database, HardDrive, Loader2, Stethoscope, Download, UploadCloud } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
    title: "Salva informazioni",
    subtitle: "Nota, documento o dato — oppure aggiungi/modifica/rimuovi un elemento da una lista",
    placeholder: 'Es. "Il codice del wifi è XYZ" oppure "Aggiungi Mario Rossi alla lista clienti"',
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
  {
    id: "vet_report", key: "report", icon: <Stethoscope size={22} />,
    title: "Report visita",
    subtitle: "Detta o scrivi il resoconto: genero il referto strutturato",
    placeholder: 'Descrivi la visita, es. "Ho visitato Fester, controllo ecografico di routine…"',
    color: "#2E7D63",
  },
];

const ACTION_COLOR = { info_upload: "#6D6181", info_request: "#DD772F", task_todo: "#7C6A7D", journal: "#8E2E11", vet_report: "#2E7D63", list_update: "#2E5F7D" };
const TITLE_COLOR  = { info_upload: "#534357", info_request: "#DD772F", task_todo: "#372F42", journal: "#8E2E11", vet_report: "#2E7D63", list_update: "#2E5F7D" };

export default function ChatPage() {
  const [active, setActive] = useState("info_request");
  const [scope, setScope] = useState("all"); // 'kb' | 'all' — solo per info_request
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
  const [uploadingFiles, setUploadingFiles] = useState([]); // filenames currently being caricati
  const [saveToDrive, setSaveToDrive] = useState(true);
  const [pendingDriveUpload, setPendingDriveUpload] = useState(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const recStartRef = useRef(0);
  const fileInputRef = useRef(null);

  const [thread, setThread] = useState(null);
  const [focusMode, setFocusMode] = useState(false);
  const threadEndRef = useRef(null);

  const [visitType, setVisitType] = useState("imaging"); // 'imaging' | 'general' | id template personalizzato
  const [vetTemplates, setVetTemplates] = useState({ builtin: [], custom: [] });
  const [showTemplateUpload, setShowTemplateUpload] = useState(false);

  const loadVetTemplates = async () => {
    try {
      const r = await api.get("/vet/templates");
      setVetTemplates(r.data);
    } catch { /* silent: la sezione report resta usabile con i template built-in */ }
  };
  useEffect(() => { if (active === "vet_report") loadVetTemplates(); }, [active]);

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
  const closeThread = () => { setThread(null); setFocusMode(false); setPendingDriveUpload(null); };

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

  const resolveDrivePending = async (folderText) => {
    try {
      const res = await api.post("/drive/resolve-pending", { pending_id: pendingDriveUpload.pendingId, text: folderText });
      const j = res.data;
      if (j.status === "saved") {
        toast.success(`${pendingDriveUpload.fileName} → Drive/${j.folder}`);
        setPendingDriveUpload(null);
        return true;
      }
      setPendingDriveUpload((p) => (p ? { ...p, suggestions: j.suggestions || [] } : p));
      toast.error('Non ho capito la cartella — scrivi un nome (es. "Viaggi") o scegline una qui sotto.');
      return false;
    } catch (err) {
      toast.error("Errore Drive: " + (err?.response?.data?.detail || err.message));
      return false;
    }
  };

  const appendVetReportResult = (rep) => {
    if (rep.status === "ambiguous_patient") {
      setThread((th) => ({ ...th, messages: [...th.messages, {
        role: "assistant",
        content: "🐾 Ho trovato più pazienti con questo nome. Quale intendi?",
        ambiguous: { candidates: rep.candidates, text: rep.text, visit_type: rep.visit_type },
      }] }));
      return;
    }
    const lines = [
      `✅ Report generato: ${rep.template_name}`,
      rep.patient_name
        ? `👤 Paziente: ${rep.patient_name} (data ultima visita aggiornata)`
        : `👤 Paziente non riconosciuto — salvato tra i "Report generici"`,
      rep.drive_link ? `📁 Salvato su Drive in "${rep.drive_folder}"` : "⚠️ Non salvato su Drive (collega Google Workspace in Impostazioni)",
      rep.telegram_sent ? "📨 Inviato anche su Telegram" : null,
    ].filter(Boolean).join("\n");
    setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: lines, reportId: rep.id }] }));
  };

  const sendVetReport = async () => {
    if (recording) { stopRec(); await new Promise((r) => setTimeout(r, 400)); }
    let content = text.trim();
    if (pendingVoice) {
      setTranscribing(true);
      try { content = (await transcribeBlob(pendingVoice.blob)) || content; }
      catch (e) { toast.error("Trascrizione fallita: " + e.message); setTranscribing(false); return; }
      setTranscribing(false);
      setPendingVoice(null);
    }
    if (!content) { toast.error("Descrivi la visita"); return; }
    if (streaming || transcribing) return;

    setStreaming(true);
    setThread((th) => th
      ? { ...th, messages: [...th.messages, { role: "user", content }] }
      : { conv_id: null, action: "vet_report", messages: [{ role: "user", content }], liveAnswer: "" });
    setText("");

    try {
      const r = await api.post("/vet/generate-report", { text: content, visit_type: visitType });
      appendVetReportResult(r.data);
    } catch (e) {
      const errText = "⚠️ " + (e.response?.data?.detail || "Errore nella generazione del report");
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: errText }] }));
    } finally {
      setStreaming(false);
    }
  };

  const resolveVetPatient = async (patientId, ambText, ambVisitType) => {
    setStreaming(true);
    try {
      const r = await api.post("/vet/generate-report", { text: ambText, visit_type: ambVisitType, patient_item_id: patientId });
      appendVetReportResult(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nella generazione del report");
    } finally {
      setStreaming(false);
    }
  };

  const appendListUpdateResult = (res) => {
    if (res.status === "ambiguous_list" || res.status === "ambiguous_item" || res.status === "ambiguous_sub_item") {
      const prompt = res.status === "ambiguous_list"
        ? "📋 A quale lista ti riferisci?"
        : "📋 Ho trovato più corrispondenze. Quale intendi?";
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: prompt, listAmbiguous: res }] }));
      return;
    }
    if (res.status === "confirm_clear") {
      setThread((th) => ({ ...th, messages: [...th.messages, {
        role: "assistant",
        content: `⚠️ Stai per eliminare ${res.count} element${res.count === 1 ? "o" : "i"} in un colpo solo. Confermi?`,
        listAmbiguous: res,
      }] }));
      return;
    }
    setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: `✅ ${res.message}` }] }));
  };

  // Shared by the auto-classifier below and by follow-up messages inside a thread that
  // already turned out to be a list edit - `content` is already fully resolved (voice
  // transcribed if needed) by the caller.
  const runListUpdateFor = async (content) => {
    setThread((th) => th
      ? { ...th, messages: [...th.messages, { role: "user", content }] }
      : { conv_id: null, action: "list_update", messages: [{ role: "user", content }], liveAnswer: "" });
    try {
      const r = await api.post("/lists/update", { text: content });
      appendListUpdateResult(r.data);
    } catch (e) {
      const errText = "⚠️ " + (e.response?.data?.detail || "Errore nella modifica della lista");
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: errText }] }));
    } finally {
      setStreaming(false);
    }
  };

  const resolveListUpdate = async (amb, override) => {
    setStreaming(true);
    try {
      const r = await api.post("/lists/update", {
        text: amb.text, op: amb.op, fields: amb.fields, item_query: amb.item_query, sub_item_query: amb.sub_item_query,
        sub_items: amb.sub_items, collection_id: amb.collection_id, item_id: amb.item_id, ...override,
      });
      appendListUpdateResult(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nella modifica della lista");
    } finally {
      setStreaming(false);
    }
  };

  const send = async () => {
    if (active === "vet_report") { await sendVetReport(); return; }
    if (recording) { stopRec(); await new Promise((r) => setTimeout(r, 400)); }
    if (pendingDriveUpload && text.trim() && attachments.length === 0 && !pendingVoice) {
      const resolved = await resolveDrivePending(text.trim());
      if (resolved) { setText(""); return; }
    }
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

    // "Salva informazioni" doubles as "modifica lista": a thread already recognized as a
    // list edit keeps going as one; a fresh message gets a cheap classification pass so
    // "aggiungi Mario alla lista clienti" is routed to the list editor instead of being
    // saved as a generic note - no separate button needed for the two.
    if (active === "info_upload" && attachments.length === 0 && currentQuestion) {
      if (thread?.action === "list_update") {
        setText("");
        await runListUpdateFor(currentQuestion);
        return;
      }
      if (!thread) {
        try {
          const cls = await api.post("/classify-save-intent", { text: currentQuestion });
          if (cls.data?.kind === "list_update") {
            setText("");
            await runListUpdateFor(currentQuestion);
            return;
          }
        } catch { /* classification failed: fall through to a normal save */ }
      }
    }

    if (attachments.length > 0) {
      const kbLine = attachments.filter((a) => a.kb).map((a) => `📎 ${a.name} · ${a.chunks} chunk indicizzati (~${a.chars} caratteri)`).join("\n");
      const driveLine = attachments.filter((a) => !a.kb).map((a) => `📎 ${a.name}${a.url ? ` (${a.url})` : ""}`).join("\n");
      const parts = [];
      if (kbLine) parts.push(`Allegati caricati nella knowledge base personale:\n${kbLine}`);
      if (driveLine) parts.push(`Allegati caricati su Drive:\n${driveLine}`);
      currentQuestion = (currentQuestion ? currentQuestion + "\n\n" : "") + parts.join("\n\n");
    }
    const driveFiles = attachments.filter((a) => a.driveFile);
    const driveHintText = text.trim();
    setText("");
    setAttachments([]);

    if (driveFiles.length > 0) {
      // Awaited (not fire-and-forget) so the AI's confirmation message below can be
      // told the real outcome instead of assuming the file landed on Drive - see the
      // matching "REGOLA CRITICA SU GOOGLE DRIVE" instruction in build_system_prompt.
      const driveResults = await Promise.all(
        driveFiles.map(async (a) => ({ name: a.name, ...(await smartUploadToDrive(a.driveFile, driveHintText, !a.driveExplicit)) }))
      );
      const statusLines = driveResults
        .filter((r) => r.status !== "skipped")
        .map((r) => {
          if (r.status === "saved") return `File salvato su Drive in "${r.folder}": ${r.name}.`;
          if (r.status === "needs_folder") return `Non è stato possibile determinare automaticamente la cartella Drive per "${r.name}": è stato chiesto all'utente in che cartella salvarlo, il file non è ancora stato salvato su Drive.`;
          return `Salvataggio su Drive di "${r.name}" non riuscito${r.error ? `: ${r.error}` : "."}`;
        });
      if (statusLines.length > 0) {
        currentQuestion = (currentQuestion ? currentQuestion + "\n\n" : "") + statusLines.join("\n");
      }
    }

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
      setUploadingFiles((u) => [...u, f.name]);
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
          // Always keep the raw file so it can ALSO be saved to Drive at send time - either
          // because the user pre-toggled "salva anche su Drive" (asks for a folder if the
          // message doesn't name one), or automatically/silently whenever the message text
          // turns out to name a folder on its own (e.g. "salva il file nella cartella X"),
          // with no toggle needed - see smartUploadToDrive's `silent` mode in send().
          setAttachments((a) => [...a, { name: f.name, id: j.doc_id, kb: true, chunks: j.chunks, chars: j.chars, preview: j.preview, ocr: j.source_type === "image_ocr", driveFile: f, driveExplicit: saveToDrive }]);
          if (j.source_type === "image_ocr") {
            toast.success(`${f.name} → OCR + Knowledge Base (${j.chars} caratteri)`);
          } else {
            toast.success(`${f.name} → Knowledge Base (${j.chunks} chunk)`);
          }
          if (saveToDrive) toast.message(`"${f.name}" verrà salvato anche su Drive quando invii il messaggio — scrivi la cartella se vuoi sceglierla tu.`);
        } else {
          setAttachments((a) => [...a, { name: f.name, id: j.file_id, url: j.web_view_link }]);
          toast.success(`${f.name} → Drive`);
        }
      } catch (err) { toast.error(`Upload ${f.name}: ${err.message}`); }
      finally { setUploadingFiles((u) => u.filter((n) => n !== f.name)); }
    }
  };
  const removeAttachment = (i) => setAttachments((a) => a.filter((_, idx) => idx !== i));

  const smartUploadToDrive = async (file, hintText, silent = false) => {
    setUploadingFiles((u) => [...u, file.name]);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      fd.append("text", hintText || "");
      if (silent) fd.append("silent", "true");
      const res = await fetch(`${API}/drive/smart-upload`, { method: "POST", body: fd, credentials: "include" });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || `HTTP ${res.status}`);
      if (j.status === "saved") {
        toast.success(`${file.name} → Drive/${j.folder}`);
        return { status: "saved", folder: j.folder };
      }
      if (j.status === "skipped") return { status: "skipped" };
      if (!silent) {
        setPendingDriveUpload({ pendingId: j.pending_id, fileName: file.name, suggestions: j.suggestions || [] });
        toast.message(`In quale cartella salvo "${file.name}"? Scrivilo nel messaggio o scegli qui sotto.`);
        return { status: "needs_folder" };
      }
      return { status: "skipped" };
    } catch (err) {
      if (!silent) toast.error(`Drive: ${err.message}`);
      else console.error("smartUploadToDrive (silent) failed:", err);
      return { status: "error", error: err.message };
    } finally {
      setUploadingFiles((u) => u.filter((n) => n !== file.name));
    }
  };

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
    toast("Eliminare questa conversazione?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = history;
          setHistory((hs) => hs.filter((h) => h.conv_id !== convId));
          try {
            await api.delete(`/conversations/${convId}`);
            if (thread?.conv_id === convId) setThread(null);
            toast.success("Eliminata");
          } catch { toast.error("Errore"); setHistory(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  return (
    <div className="relative w-full">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full h-[calc(100vh-15rem)]">
        {/* LEFT 1/3 — action icons + input area */}
        <aside className={`lg:col-span-1 flex flex-col overflow-y-auto pr-1 ${focusMode ? "hidden" : ""}`}>
          {/* Top block mirrors the right-side filter bar (same padding/height) so the input aligns with the first history card */}
          <div className="flex items-center gap-1.5 md:gap-2 p-3 md:p-3.5 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm shrink-0">
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
                      backgroundColor: selected ? a.color : undefined,
                      color: "#CECAD0",
                      opacity: selected ? 1 : 0.5,
                      borderColor: selected ? a.color : "rgba(206,202,208,0.25)",
                    }}
                    className="liquid-glass-btn group relative h-8 w-8 md:h-9 md:w-9 rounded-full border shadow-sm flex items-center justify-center transition-all duration-200 hover:opacity-100 hover:shadow-md"
                  >
                    {React.cloneElement(a.icon, { size: 15 })}
                    <span className="pointer-events-none absolute -bottom-9 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-lg bg-[#403A3C] text-white text-[11px] font-medium px-2.5 py-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150 shadow-lg z-30">
                      {a.title}
                    </span>
                  </button>
                );
              })}
          </div>
          <div className="flex items-center justify-between px-2 mt-4 shrink-0">
            <div className="text-xs font-bold uppercase tracking-wider text-white">nuovo messaggio</div>
            <div className="text-xs font-bold uppercase tracking-wider text-white/70">{activeAction.title.toLowerCase()}</div>
          </div>
          <div className="chat-input-card p-5 rounded-2xl shadow-lg mt-2 min-h-[340px] flex flex-col" data-testid="chat-input-card">
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
              {active === "vet_report" && !thread && (
                <div className="flex items-center gap-1 flex-wrap" data-testid="visit-type-selector">
                  <div className="flex items-center gap-1 bg-white/10 rounded-full p-0.5">
                    {vetTemplates.builtin.map((t) => (
                      <button
                        key={t.key}
                        data-testid={`visit-type-${t.key}`}
                        onClick={() => setVisitType(t.key)}
                        className={`px-2.5 py-1 rounded-full text-[10px] font-mono-tight uppercase tracking-widest transition-all ${visitType === t.key ? "bg-[#CECAD0] text-[#403A3C]" : "text-white/80 hover:bg-white/10"}`}
                      >
                        {t.name}
                      </button>
                    ))}
                    {vetTemplates.custom.map((t) => (
                      <button
                        key={t.id}
                        data-testid={`visit-type-${t.id}`}
                        onClick={() => setVisitType(t.id)}
                        className={`px-2.5 py-1 rounded-full text-[10px] font-mono-tight uppercase tracking-widest transition-all ${visitType === t.id ? "bg-[#CECAD0] text-[#403A3C]" : "text-white/80 hover:bg-white/10"}`}
                      >
                        {t.name}
                      </button>
                    ))}
                  </div>
                  <button
                    data-testid="upload-vet-template-btn"
                    onClick={() => setShowTemplateUpload(true)}
                    title="Carica un tuo template di report"
                    className="p-1.5 rounded-full bg-white/10 hover:bg-white/15 text-white/80"
                  >
                    <UploadCloud size={13} />
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
              className="diary-lines border-0 focus-visible:ring-0 bg-transparent text-base flex-1 min-h-[200px] px-0 resize-none text-white placeholder:text-white/60"
            />
            {pendingDriveUpload && (
              <div className="flex items-center gap-1.5 flex-wrap mb-2" data-testid="drive-pending-suggestions">
                <span className="kicker text-white/70">cartella per "{pendingDriveUpload.fileName}":</span>
                {pendingDriveUpload.suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => resolveDrivePending(s)}
                    className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/20 text-white hover:bg-white/30"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            <div className="flex items-center justify-between pt-2 border-t ">
              <div className="flex items-center gap-1.5 text-white/85 flex-wrap">
                <button data-testid="attach-btn" onClick={onAttachClick} className="p-2 rounded-full hover:bg-white/15"><Paperclip size={16} /></button>
                {active === "info_upload" && (
                  <button
                    data-testid="drive-save-toggle"
                    onClick={() => setSaveToDrive((v) => !v)}
                    title="Salva anche su Google Drive (cartella mAIPAL)"
                    className={`p-2 rounded-full transition-colors duration-150 ${saveToDrive ? "bg-white/30 text-white" : "hover:bg-white/15"}`}
                  >
                    <HardDrive size={16} />
                  </button>
                )}
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
                {uploadingFiles.map((name, i) => (
                  <span key={`up-${i}`} data-testid="file-uploading-chip" className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/10 text-white/70 flex items-center gap-1.5" title={`Carico ${name}…`}>
                    <Loader2 size={11} className="animate-spin" /> {name.slice(0,12)}{name.length > 12 ? "…" : ""} · carico…
                  </span>
                ))}
              </div>
              <button data-testid="send-btn" onClick={send}
                disabled={streaming || transcribing || uploadingFiles.length > 0 || (!text.trim() && attachments.length === 0 && !pendingVoice && !recording)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-[#CECAD0] text-[#403A3C] font-medium disabled:opacity-50 hover:bg-white text-sm">
                <Send size={14} /> {streaming ? "Elaboro…" : transcribing ? "Trascrivo…" : uploadingFiles.length > 0 ? "Carico…" : recording ? "Ferma & invia" : "Invia"}
              </button>
            </div>
            <input ref={fileInputRef} type="file" multiple hidden onChange={onFilesPicked} accept={active === "info_upload" ? ".pdf,.docx,.xlsx,.txt,.md,.csv,.json,.html,.xml,.yaml,.yml,.log,.jpg,.jpeg,.png,.webp,.heic,.heif" : undefined} data-testid="file-input" />
          </div>
        </aside>

        {/* RIGHT 2/3 — scrolls */}
        <section className={`${focusMode ? "lg:col-span-3" : "lg:col-span-2"} flex flex-col h-full overflow-hidden`}>
          {/* Filters (hidden in focus mode when a thread is open) */}
          {!(focusMode && thread) && (
            <div className="flex items-center gap-1.5 md:gap-2 flex-nowrap overflow-x-auto no-scrollbar p-3 md:p-3.5 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm shrink-0">
            <div className="relative shrink-0 w-32 md:w-40 lg:w-48">
              <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/60" />
              <Input data-testid="history-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cerca…" className="pl-8 h-8 md:h-9 text-xs md:text-sm rounded-full bg-white/10  text-white placeholder:text-white/60" />
            </div>
            {[
              { k: "all",     label: "tutti",     icon: <Layers size={15} />,       color: "#CECAD0" },
              { k: "fav",     label: "preferiti", icon: <Star size={15} className={filter === "fav" ? "fill-current" : ""} />, color: "#F5B942" },
              { k: "upload",  label: "upload",    icon: <CloudUpload size={15} />,  color: "#6D6181" },
              { k: "query",   label: "query",     icon: <Search size={15} />,       color: "#DD772F" },
              { k: "todo",    label: "todo",      icon: <CheckSquare size={15} />,  color: "#7C6A7D" },
              { k: "journal", label: "diario",    icon: <BookOpen size={15} />,     color: "#8E2E11" },
            ].map(({ k, label, icon, color }) => {
              const selected = filter === k;
              return (
                <button
                  key={k}
                  data-testid={`filter-${k}`}
                  onClick={() => setFilter(k)}
                  title={label}
                  aria-label={label}
                  style={{
                    backgroundColor: selected ? color : "transparent",
                    color: selected && k === "all" ? "#403A3C" : "#CECAD0",
                    opacity: selected ? 1 : 0.5,
                    borderColor: selected ? color : "rgba(206,202,208,0.25)",
                  }}
                  className="group relative shrink-0 h-8 w-8 md:h-9 md:w-9 rounded-full border shadow-sm flex items-center justify-center transition-all duration-200 hover:opacity-100 hover:shadow-md"
                >
                  {icon}
                  <span className="pointer-events-none absolute -bottom-9 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-lg bg-[#403A3C] text-white text-[11px] font-medium px-2.5 py-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150 shadow-lg z-30">
                    {label}
                  </span>
                </button>
              );
            })}
            <input data-testid="history-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="shrink-0 h-8 md:h-9 w-28 md:w-32 rounded-full bg-white/10  text-white px-2 text-[10px] md:text-[11px]" />
          </div>
          )}

          {/* Thread view (replaces list when open) */}
          {thread ? (
            <div className="p-5 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm flex-1 flex flex-col mt-4 overflow-hidden" data-testid="thread-card">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ACTION_COLOR[thread.action] || "#CECAD0" }} />
                  <div className="kicker">
                    {thread.action === "info_upload" ? "caricamento" : thread.action === "info_request" ? "richiesta" : thread.action === "journal" ? "diario" : thread.action === "vet_report" ? "report" : thread.action === "list_update" ? "modifica lista" : "task / to-do"}
                    {" · thread "}{thread.conv_id ? thread.conv_id.slice(-6) : "nuovo"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button data-testid="focus-mode-btn" onClick={() => setFocusMode((v) => !v)} className="kicker px-3 py-1.5 rounded-full  bg-white/10 text-white hover: inline-flex items-center gap-1" title={focusMode ? "Esci focus" : "Modalità focus"}>
                    {focusMode ? <Minimize2 size={12} /> : <Maximize2 size={12} />} {focusMode ? "esci focus" : "focus"}
                  </button>
                  <button data-testid="new-thread-btn" onClick={() => { setThread(null); setFocusMode(false); setPendingDriveUpload(null); }} className="kicker px-3 py-1.5 rounded-full  bg-white/10 text-white hover: inline-flex items-center gap-1">
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
                    {m.reportId && (
                      <a
                        href={`${API}/vet/reports/${m.reportId}/download`}
                        target="_blank"
                        rel="noreferrer"
                        data-testid="download-report-btn"
                        className="ml-4 mt-1 inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-white/10 hover:bg-white/15 text-white"
                      >
                        <Download size={12} /> Scarica il referto (.docx)
                      </a>
                    )}
                    {m.ambiguous && (
                      <div className="flex flex-wrap gap-2 mt-2 ml-4" data-testid="ambiguous-patient-choices">
                        {m.ambiguous.candidates.map((c) => (
                          <button
                            key={c.item_id}
                            onClick={() => resolveVetPatient(c.item_id, m.ambiguous.text, m.ambiguous.visit_type)}
                            disabled={streaming}
                            className="text-xs px-3 py-1.5 rounded-full bg-white/10 hover:bg-white/20 text-white disabled:opacity-50"
                          >
                            {c.name}{c.owner ? ` · ${c.owner}` : ""}{c.species ? ` (${c.species})` : ""}
                          </button>
                        ))}
                      </div>
                    )}
                    {m.listAmbiguous && (
                      <div className="flex flex-wrap gap-2 mt-2 ml-4" data-testid="ambiguous-list-choices">
                        {m.listAmbiguous.candidates.map((c) => (
                          <button
                            key={c.collection_id || c.item_id || c.sub_item_id || "confirm"}
                            onClick={() => resolveListUpdate(
                              m.listAmbiguous,
                              c.confirm ? { confirm: true }
                                : c.collection_id ? { collection_id: c.collection_id }
                                : c.item_id ? { item_id: c.item_id }
                                : { sub_item_id: c.sub_item_id }
                            )}
                            disabled={streaming}
                            className={`text-xs px-3 py-1.5 rounded-full disabled:opacity-50 ${c.confirm ? "bg-red-500/20 hover:bg-red-500/30 text-red-200" : "bg-white/10 hover:bg-white/20 text-white"}`}
                          >
                            {c.name || c.label}
                          </button>
                        ))}
                      </div>
                    )}
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
                <div className="text-xs font-bold uppercase tracking-wider text-white">cronologia</div>
                <div className="text-xs font-bold uppercase tracking-wider text-white/70">{filtered.length} messaggi</div>
              </div>
              <div className="space-y-3 flex-1 overflow-y-auto pr-1 mt-2">
                {filtered.length === 0 && <div className="text-white/60 text-sm">Nessuna conversazione ancora.</div>}
                {filtered.map((c, idx) => (
                  <HistoryCard
                    key={c.conv_id}
                    conv={c}
                    index={idx}
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

      {showTemplateUpload && (
        <VetTemplateUploadDialog
          onClose={() => setShowTemplateUpload(false)}
          onUploaded={async (tpl) => { setShowTemplateUpload(false); await loadVetTemplates(); setVisitType(tpl.id); }}
        />
      )}
    </div>
  );
}

function VetTemplateUploadDialog({ onClose, onUploaded }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!file) { toast.error("Scegli un file .docx"); return; }
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      fd.append("name", name.trim() || file.name);
      const res = await fetch(`${API}/vet/templates`, { method: "POST", body: fd, credentials: "include" });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const tpl = await res.json();
      toast.success(`Template "${tpl.name}" caricato`);
      onUploaded(tpl);
    } catch (e) { toast.error("Errore: " + e.message); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-md bg-[color:var(--app-bg)]" data-testid="vet-template-upload-dialog">
        <DialogHeader><DialogTitle>Carica un template di report</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="text-sm text-white/60">
            Carica un .docx: ne analizzo la struttura (sezioni e campi) per usarlo come riferimento nella generazione dei referti.
          </div>
          <div>
            <div className="kicker mb-1">nome template</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Visita dermatologica" className="h-11 rounded-xl bg-white/10" />
          </div>
          <div>
            <div className="kicker mb-1">file .docx</div>
            <input
              type="file"
              accept=".docx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="text-sm text-white/80 file:mr-3 file:py-2 file:px-3 file:rounded-full file:border-0 file:bg-white/10 file:text-white file:text-xs"
            />
          </div>
        </div>
        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Carica"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function HistoryCard({ conv, index = 0, onOpen, onToggleFav, onDelete }) {
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
    <div
      className="p-4 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm card-hover card-enter"
      style={{ ["--i"]: index }}
      data-testid="history-card"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: ACTION_COLOR[conv.action] || "#CECAD0" }} />
          <div className="kicker-p">{actionLabels[conv.action] || conv.action}</div>
          <div className="kicker-p">· {d ? d.toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</div>
          {messageCount > 2 && <div className="kicker-p">· {messageCount} msg</div>}
        </div>
        <div className="flex items-center gap-1.5">
          <button data-testid="open-thread-icon-btn" onClick={stop(onOpen)} title="Apri thread"
            className="p-1.5 rounded-full text-white/50 hover:bg-white/10 hover:text-white transition-colors duration-150">
            <Maximize2 size={14} />
          </button>
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
        {title && <div className="text-sm font-semibold mb-1 pl-3" style={{ color: TITLE_COLOR[conv.action] || "#482B94" }} data-testid="conv-title">{title}</div>}
        <div className="bg-white/5 rounded-xl p-3 text-sm text-white/90 line-clamp-2">{preview}</div>
        {summary && (
          <div className="mt-2 text-xs text-white/60 line-clamp-2 leading-relaxed pl-3" data-testid="conv-summary">
            {summary}
          </div>
        )}
      </button>
    </div>
  );
}
