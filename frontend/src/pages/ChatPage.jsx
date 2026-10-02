import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CloudUpload, Search, CheckSquare, Paperclip, Mic, MicOff, Send, Calendar, Check, X, MessageSquarePlus, Star, Trash2, Maximize2, Minimize2, BookOpen, Layers, Database, HardDrive, Loader2, Stethoscope, Download, UploadCloud, Reply, History, Plus, Repeat, Cloud, Folder, Bell, ClipboardList, AtSign } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, streamChat, API } from "@/lib/api";
import { toast } from "sonner";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { takeSharedPayload } from "@/lib/pwa";
import SuggestionsTicker from "@/components/SuggestionsTicker";
import { MENTION_AGENTS, agentByKey, splitMentions, mentionQueryAt, buildPeopleDirectory, findPeople, tokenizeAll, PERSON_COLOR } from "@/lib/mentions";
import { useAuth } from "@/auth/AuthContext";
import { useNavigate, useLocation } from "react-router-dom";

const ACTION_LABELS_IT = { info_upload: "Caricamento", info_request: "Richiesta", task_todo: "Task/To-Do", journal: "Diario", vet_report: "Report", list_update: "Modifica lista", scheduled_action: "Azione" };
// Matches the backend's conversation_retention.RETENTION_DAYS.
const HISTORY_RETENTION_NOTE = "Le chat non preferite si cancellano da sole 10 giorni dopo l'ultimo messaggio: segna con la stella quelle da tenere. Note, task e diario salvati restano.";
const IT_MONTHS_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const formatReplyLabel = (conv) => {
  const d = conv.created_at ? new Date(conv.created_at) : null;
  const when = d ? `${d.getDate()} ${IT_MONTHS_SHORT[d.getMonth()]} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : "";
  return `${ACTION_LABELS_IT[conv.action] || conv.action}${when ? ` · ${when}` : ""}`;
};

const ACTIONS = [
  {
    id: "info_request", key: "query", short: "Cerca", icon: <Search size={22} />,
    title: "Richiesta informazioni",
    subtitle: "Interroga la base di conoscenza con Claude",
    placeholder: "Cosa vuoi sapere?",
    color: "#DD772F",
  },
  {
    id: "info_upload", key: "upload", short: "Salva", icon: <CloudUpload size={22} />,
    title: "Salva informazioni",
    subtitle: "Nota, documento o dato — oppure aggiungi/modifica/rimuovi un elemento da una lista",
    placeholder: 'Es. "Il codice del wifi è XYZ" oppure "Aggiungi Mario Rossi alla lista clienti"',
    color: "#6D6181",
  },
  {
    id: "task_todo", key: "todo", short: "Task", icon: <CheckSquare size={22} />,
    title: "Salvataggio task o to-do",
    subtitle: "Crea task e sincronizzali con n8n + Supabase",
    placeholder: "Es. Ricordami di chiamare il fornitore martedì alle 15",
    color: "#7C6A7D",
  },
  {
    id: "journal", key: "journal", short: "Diario", icon: <BookOpen size={22} />,
    title: "Diario",
    subtitle: "Racconta la giornata: la salvo nel diario",
    placeholder: "Com'è andata oggi? Cosa vuoi ricordare…",
    color: "#8E2E11",
  },
  {
    id: "vet_report", key: "report", short: "Referto", icon: <Stethoscope size={22} />,
    title: "Report visita",
    subtitle: "Detta o scrivi il resoconto: genero il referto strutturato",
    placeholder: 'Descrivi la visita, es. "Ho visitato Fester, controllo ecografico di routine…"',
    color: "#2E7D63",
  },
  {
    id: "scheduled_action", key: "scheduled", short: "Azioni", icon: <Repeat size={22} />,
    title: "Azioni programmate",
    subtitle: "Un comando che eseguo da solo con la cadenza che scegli, finché non lo fermi",
    placeholder: 'Es. "Ogni venerdì all\'una di notte svuota gli iscritti della lista Lezioni Pilates"',
    color: "#3E7C8C",
  },
];

// Mobile chat: what the ⓘ next to the agent's name explains - what it does, what the icons
// under the name mean, and examples (tapping one fills the box).
const AGENT_INFO = {
  info_request: {
    what: "Risponde alle tue domande usando quello che hai salvato: note, documenti, task, diario e liste.",
    options: [[Layers, "Cerca ovunque: note, documenti, task, diario e liste"], [Database, "Cerca solo nella base di conoscenza (note e documenti)"]],
    examples: ["Qual è il codice del wifi?", "Quanto ho speso per il gatto negli ultimi tre mesi?", "Cosa devo fare questa settimana?"],
  },
  info_upload: {
    what: "Salva note, codici, documenti e foto nella tua base di conoscenza, e se vuoi anche su Drive o OneDrive. Capisce anche quando vuoi aggiungere, modificare o togliere un elemento da una Lista.",
    options: [[HardDrive, "Salva gli allegati anche su Google Drive"], [Cloud, "Salva gli allegati anche su OneDrive"], [Folder, "Acceso: se non scrivi la cartella te la chiedo. Spento: la scelgo io (quella che scrivi, o la cartella mAIPAL)"]],
    examples: ["Il codice del wifi è XYZ-123", "Aggiungi Mario Rossi alla lista Clienti", "Salva lo scontrino nella cartella Spese gatto"],
  },
  task_todo: {
    what: "Crea task (con una data) e to-do (senza data) da quello che scrivi o detti. Capisce le ricorrenze (\"ogni lunedì\") e comandi come \"segna come fatto\".",
    options: [[Calendar, "Mette i nuovi task anche nel calendario collegato"], [Bell, "Attiva il promemoria prima della scadenza"]],
    examples: ["Ricordami di chiamare il fornitore martedì alle 15", "Palestra ogni lunedì e giovedì alle 18", "Segna come fatto il task del commercialista"],
  },
  journal: {
    what: "Racconta la giornata a parole tue: la riscrivo in ordine e la salvo nel Diario, nel giorno giusto (\"ieri\", \"sabato\"). Puoi allegare fino a 5 foto.",
    options: [],
    examples: ["Oggi giornata al mare con la famiglia", "Ieri cena da Marco, abbiamo parlato del viaggio in Grecia"],
  },
  vet_report: {
    what: "Detta o scrivi il resoconto della visita: genero il referto strutturato (Word) e lo collego al paziente.",
    options: [[ClipboardList, "Scegli il tipo di visita o carica un tuo modello di referto"]],
    examples: ["Ho visitato Fester, controllo ecografico di routine, tutto nella norma"],
  },
  scheduled_action: {
    what: "Un comando che eseguo da solo con la cadenza che scegli, finché non lo fermi. Prima di attivarlo ti mostro cosa farò.",
    options: [],
    examples: ["Ogni venerdì all'una di notte svuota gli iscritti della lista Lezioni Pilates", "Ogni lunedì alle 8 mandami su Telegram i task della settimana"],
  },
};
const CHAT_OPTS_KEY = "maipal.chatOptions";
const readChatOpts = () => { try { return JSON.parse(localStorage.getItem(CHAT_OPTS_KEY) || "{}"); } catch { return {}; } };

const ACTION_COLOR = { info_upload: "#6D6181", info_request: "#DD772F", task_todo: "#7C6A7D", journal: "#8E2E11", vet_report: "#2E7D63", list_update: "#2E5F7D", scheduled_action: "#3E7C8C" };
const TITLE_COLOR  = { info_upload: "#534357", info_request: "#DD772F", task_todo: "#372F42", journal: "#8E2E11", vet_report: "#2E7D63", list_update: "#2E5F7D", scheduled_action: "#3E7C8C" };

// Images over 1 MB for the knowledge base / Drive (typical PC screenshots or camera photos)
// are re-encoded client-side into a JPEG of at most 2560px before upload - whichever of the
// two is smaller is sent - so they stay well within the proxy's request size limits.
const prepareImageForUpload = (file) => new Promise((resolve) => {
  const isImg = (file.type || "").startsWith("image/") && !/heic|heif|gif|svg/i.test(file.type);
  if (!isImg || file.size <= 1024 * 1024) { resolve(file); return; }
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    try {
      const scale = Math.min(1, 2560 / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        URL.revokeObjectURL(url);
        if (!blob || blob.size >= file.size) { resolve(file); return; }
        resolve(new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" }));
      }, "image/jpeg", 0.9);
    } catch { URL.revokeObjectURL(url); resolve(file); }
  };
  img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
  img.src = url;
});

// A non-JSON error body means the request was stopped BEFORE reaching mAIPAL (proxy,
// Cloudflare, size limit) - say so instead of a bare "HTTP 403".
const uploadErrorMessage = async (res) => {
  const body = await res.text().catch(() => "");
  try { const j = JSON.parse(body); if (j.detail) return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* not JSON */ }
  if (res.status === 413) return "file troppo grande per il server (limite del proxy)";
  if (res.status === 403) return "caricamento bloccato prima di arrivare a mAIPAL (filtro di sicurezza di Cloudflare/proxy) - vedi Security → Events su Cloudflare";
  return `HTTP ${res.status}`;
};

// Diary photos are downscaled/compressed client-side (max ~1600px, JPEG) before being
// turned into a data URI, both to keep the request small and to stay under the backend's
// ~2MB-per-image cap without the user having to think about file size.
const fileToJournalImageDataUri = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onerror = () => reject(new Error("Lettura file fallita"));
  reader.onload = () => {
    const img = new Image();
    img.onerror = () => reject(new Error("Immagine non valida"));
    img.onload = () => {
      const maxDim = 1600;
      let { width, height } = img;
      if (width > maxDim || height > maxDim) {
        const scale = maxDim / Math.max(width, height);
        width = Math.round(width * scale);
        height = Math.round(height * scale);
      }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d").drawImage(img, 0, 0, width, height);
      let quality = 0.85;
      let dataUri = canvas.toDataURL("image/jpeg", quality);
      while (dataUri.length * 0.75 > 2 * 1024 * 1024 && quality > 0.4) {
        quality -= 0.1;
        dataUri = canvas.toDataURL("image/jpeg", quality);
      }
      resolve(dataUri);
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
});

export default function ChatPage() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const activeRef = useRef(null);
  const location = useLocation();
  // The Azioni section's "Nuova azione" opens the chat with that action already selected.
  // ...and the installed app's shortcuts (long-press on the icon) open it via ?action=
  const [active, setActive] = useState(() => {
    const wanted = location.state?.action || new URLSearchParams(location.search).get("action");
    return ACTIONS.some((a) => a.id === wanted) ? wanted : "info_request";
  });
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
  const textareaRef = useRef(null);

  const [thread, setThread] = useState(null);
  const [focusMode, setFocusMode] = useState(false);
  const threadEndRef = useRef(null);

  // Mobile only: tapping a history card binds the composer to that existing conversation
  // (pill "Rispondi a: ...") and shows it in full below; a follow-up message is appended to
  // it instead of starting a new one. Desktop keeps its existing "open the big thread" flow.
  const [mobileReplyTo, setMobileReplyTo] = useState(null); // { conv_id, action, label }
  // Mobile only (spec v2 §3.1/3.3): the chat opens on the composer alone; the history of old
  // conversations is a separate view reached from the clock button, not shown by default.
  const [mobileView, setMobileView] = useState("chat"); // "chat" | "history"
  // The header's clock button (DashboardLayout) opens/closes the history.
  useEffect(() => {
    const onHist = () => setMobileView((v) => (v === "history" ? "chat" : "history"));
    window.addEventListener("maipal:chat-history", onHist);
    return () => window.removeEventListener("maipal:chat-history", onHist);
  }, []);

  // Mobile: the per-agent icons under the agent's name (remembered on this device).
  const [integ, setInteg] = useState(null); // /integrations/status
  const [chatOpts, setChatOpts] = useState(readChatOpts); // {cloud: [...], askFolder, taskCal, taskBell}
  const [infoOpen, setInfoOpen] = useState(false);
  const [allAgentsOpen, setAllAgentsOpen] = useState(false);
  const [visitMenuOpen, setVisitMenuOpen] = useState(false);
  const [composerGrown, setComposerGrown] = useState(false);
  useEffect(() => {
    if (!isMobile) return;
    api.get("/integrations/status").then((r) => setInteg(r.data)).catch(() => setInteg({}));
  }, [isMobile]);
  const googleOn = !!integ?.google?.connected;
  const msOn = !!integ?.microsoft?.connected;
  const connectedClouds = [googleOn && "google", msOn && "onedrive"].filter(Boolean);
  // until the user touches the icons, the clouds chosen in Impostazioni
  const cloudTargets = (chatOpts.cloud || integ?.storage_targets || connectedClouds).filter((t) => connectedClouds.includes(t));
  const setChatOpt = (patch) => setChatOpts((o) => {
    const next = { ...o, ...patch };
    try { localStorage.setItem(CHAT_OPTS_KEY, JSON.stringify(next)); } catch { /* private mode */ }
    return next;
  });
  useEffect(() => { if (isMobile && integ) setSaveToDrive(cloudTargets.length > 0); }, [isMobile, integ, cloudTargets.length]);

  // Auto-growing composer textarea on mobile: grows with content up to ~50% of the viewport,
  // then scrolls internally. With no conversation on screen the box starts taller (~30% of
  // the viewport) so it is the centre of the page (spec v2 §3.1); once a conversation is shown
  // below it shrinks back to 1-2 lines to leave room for the messages. Desktop untouched.
  // (The textarea's flex-1 is desktop-only: in the mobile card, which has no fixed height,
  // flex-basis 0 overrode this inline height and pinned the box at its 60px minimum.)
  // Mobile: the box starts as a one-line bar (like a search bar) and opens up into a card as
  // soon as the text needs a second line; it goes back to a bar only once emptied.
  useEffect(() => {
    if (!isMobile) return;
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, window.innerHeight * 0.4) + "px";
    if (!text) setComposerGrown(false);
    else if (el.scrollHeight > 52) setComposerGrown(true);
  }, [text, isMobile]);

  const [visitType, setVisitType] = useState("imaging"); // 'imaging' | 'general' | id template personalizzato
  const [vetTemplates, setVetTemplates] = useState({ builtin: [], custom: [] });
  const [showTemplateUpload, setShowTemplateUpload] = useState(false);

  const loadVetTemplates = async () => {
    try {
      const r = await api.get("/vet/templates");
      setVetTemplates({ builtin: r.data?.builtin || [], custom: r.data?.custom || [] });
    } catch { /* silent: la sezione report resta usabile con i template built-in */ }
  };
  useEffect(() => { if (active === "vet_report") loadVetTemplates(); }, [active]);

  const activeAction = useMemo(() => ACTIONS.find((a) => a.id === active), [active]);
  activeRef.current = active;

  // ===== @agenti =====
  const [mentionQuery, setMentionQuery] = useState(null);
  // team members and "@team", taggable to share a saved information with them
  const { user: me } = useAuth();
  const [people, setPeople] = useState([]);
  useEffect(() => {
    if (!me?.org_id) { setPeople([]); return; }
    api.get("/org").then((r) => setPeople(buildPeopleDirectory(r.data?.members || [], me.user_id))).catch(() => setPeople([]));
  }, [me?.org_id, me?.user_id]);
  // caret to restore right after an inserted @tag is rendered (before the next key press)
  const pendingCaretRef = useRef(null);
  useLayoutEffect(() => {
    const pos = pendingCaretRef.current;
    const el = textareaRef.current;
    if (pos !== null && el) { el.focus(); el.setSelectionRange(pos, pos); pendingCaretRef.current = null; }
  });
  const agentResultMessage = (res) => ({
    role: "assistant",
    content: res.message || "",
    agent: res.agent,
    ...(res.status === "pending" && res.list_result ? { listAmbiguous: res.list_result } : {}),
    ...(res.status === "pending" && res.draft ? { schedDraft: res.draft } : {}),
    ...(res.task_id ? { taskLink: res.task_id } : {}),
  });
  // For the main actions that don't go through /chat/stream (report, azione programmata,
  // modifica lista): the tagged pieces run afterwards via /agents/dispatch.
  const dispatchTagged = async (fullText, source = null) => {
    if (!splitMentions(fullText).parts.length) return;
    try {
      const r = await api.post("/agents/dispatch", { text: fullText, source });
      setThread((th) => (th ? { ...th, messages: [...th.messages, ...(r.data.results || []).map(agentResultMessage)] } : th));
    } catch (e) { toast.error(e.response?.data?.detail || "Errore negli agenti taggati"); }
  };
  const onComposerChange = (e) => {
    setText(e.target.value);
    setMentionQuery(mentionQueryAt(e.target.value, e.target.selectionStart ?? e.target.value.length));
  };
  const insertMention = (agent) => {
    const el = textareaRef.current;
    const caret = el?.selectionStart ?? text.length;
    const before = text.slice(0, caret).replace(/@[\w.-]*$/, `@${agent.tag || agent.slug} `);
    const next = before + text.slice(caret);
    pendingCaretRef.current = before.length;
    setText(next);
    setMentionQuery(null);
  };
  const mentionMatches = mentionQuery === null ? [] : [
    ...MENTION_AGENTS.filter((a) => a.aliases.some((al) => al.startsWith(mentionQuery))),
    ...people.filter((p) => p.slug.startsWith(mentionQuery) || (p.name || "").toLowerCase().split(/\s+/).some((w) => w.startsWith(mentionQuery))),
  ];
  const typedTags = splitMentions(text).parts;
  const typedPeople = findPeople(text, people);
  const renderWithTags = (content) => tokenizeAll(content, people).map((tk, i) => (typeof tk === "string" ? tk : (
    <span key={i} className="inline-block rounded-md px-1.5 mx-0.5 text-[0.9em] font-medium text-white" style={{ background: tk.agent ? tk.agent.color : PERSON_COLOR }}>
      {tk.person ? `@${tk.person.name}` : tk.tag}
    </span>
  )));

  // Something shared to mAIPAL from another app (Android "Condividi" -> mAIPAL): it opens
  // here with the files attached and the shared text/link in the box, as "Salva
  // informazioni" - the user adds a word (e.g. which Drive folder) and sends.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const shared = await takeSharedPayload();
      if (cancelled || !shared) return;
      setActive("info_upload");
      setThread(null);
      const sharedText = [shared.title, shared.text, shared.url].filter((x, i, arr) => x && arr.indexOf(x) === i).join("\n");
      if (sharedText) setText(sharedText);
      if (shared.files.length) await ingestFiles(shared.files, "info_upload");
      toast.success("Contenuto condiviso pronto: aggiungi cosa farne e invia");
      if (location.search.includes("shared=1")) navigate(location.pathname, { replace: true });
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
  const closeThread = () => { setThread(null); setFocusMode(false); setPendingDriveUpload(null); setMobileReplyTo(null); };
  // "Nuova conversazione" on mobile (spec v2 §3.2): empties the view back to the bare
  // composer - whatever the user already typed stays in the box.
  const startNewMobileConversation = () => { closeThread(); setMobileView("chat"); };
  // Spec v2 §3.4: picking an old conversation from the history goes back to the chat view,
  // showing that conversation with the composer bound to it.
  // Opened from a task's "Da: ..." link: show that conversation.
  useEffect(() => {
    const cid = location.state?.openConv;
    if (!cid) return;
    openThread(cid).catch(() => toast.error("Conversazione non più disponibile"));
    navigate(location.pathname, { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resumeMobileConversation = (conv) => {
    setMobileReplyTo({ conv_id: conv.conv_id, action: conv.action, label: formatReplyLabel(conv) });
    openThread(conv.conv_id);
    setMobileView("chat");
  };

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
    fd.append("action", active);
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
        const n = (j.saved || []).length;
        toast.success(`${n > 1 ? `${n} file` : pendingDriveUpload.fileName} → ${j.where || "Drive"}/${j.folder}`);
        if ((j.failed || []).length) toast.error(`Non salvati: ${j.failed.join(", ")}`);
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
      rep.drive_link ? `📁 Salvato nella cartella "${rep.drive_folder}" (Drive/OneDrive)` : "⚠️ Non salvato nel cloud (collega Google Drive o OneDrive in Impostazioni)",
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
      const { main: visitText } = splitMentions(content);
      const r = await api.post("/vet/generate-report", { text: visitText || content, visit_type: visitType });
      appendVetReportResult(r.data);
      // "@task richiamo vaccino tra un anno": linked to this report (and its patient)
      await dispatchTagged(content, r.data?.id ? { type: "vet_report", id: r.data.id, preview: (visitText || "").slice(0, 200) } : null);
    } catch (e) {
      const errText = "⚠️ " + (e.response?.data?.detail || "Errore nella generazione del report");
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: errText }] }));
    } finally {
      setStreaming(false);
    }
  };

  // "Azioni programmate": the command is interpreted server-side into an exact schedule +
  // what will be done, shown back for an explicit "Attiva". Any further message in the same
  // thread before confirming is treated as a correction of that same command.
  const sendScheduledAction = async () => {
    if (recording) { stopRec(); await new Promise((r) => setTimeout(r, 400)); }
    let content = text.trim();
    if (pendingVoice) {
      setTranscribing(true);
      try { content = [content, await transcribeBlob(pendingVoice.blob)].filter(Boolean).join(" ").trim(); }
      catch (e) { toast.error("Trascrizione fallita: " + e.message); setTranscribing(false); return; }
      setTranscribing(false);
      setPendingVoice(null);
    }
    if (!content || streaming || transcribing) return;
    const pendingDraft = thread?.action === "scheduled_action"
      ? [...thread.messages].reverse().find((m) => m.schedDraft && !m.schedDone)
      : null;
    setStreaming(true);
    setText("");
    setThread((th) => (th && th.action === "scheduled_action")
      ? { ...th, messages: [...th.messages.map((m) => (m === pendingDraft ? { ...m, schedDone: "replaced" } : m)), { role: "user", content }] }
      : { conv_id: null, action: "scheduled_action", messages: [{ role: "user", content }], liveAnswer: "" });
    try {
      const { main: schedText, parts: schedTags } = splitMentions(content);
      const r = schedText
        ? await api.post("/scheduled-actions/interpret", { text: schedText, previous_text: pendingDraft?.schedDraft?.text || null })
        : { data: null };
      if (r.data) {
        const msg = r.data.status === "confirm"
          ? { role: "assistant", content: `Ho capito così:\n\n${r.data.preview}\n\nLa attivo? Se qualcosa non va, scrivimi cosa correggere.`, schedDraft: r.data.draft }
          : { role: "assistant", content: `⚠️ ${r.data.message}` };
        setThread((th) => ({ ...th, messages: [...th.messages, msg] }));
      }
      if (schedTags.length) await dispatchTagged(content);
    } catch (e) {
      const errText = "⚠️ " + (e.response?.data?.detail || "Non sono riuscito a interpretare il comando");
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: errText }] }));
    } finally {
      setStreaming(false);
    }
  };

  const resolveScheduledDraft = async (msgIndex, activate) => {
    const target = thread?.messages[msgIndex];
    if (!target?.schedDraft) return;
    const mark = (done) => (th) => ({ ...th, messages: th.messages.map((m, i) => (i === msgIndex ? { ...m, schedDone: done } : m)) });
    if (!activate) {
      setThread((th) => {
        const next = mark("cancelled")(th);
        return { ...next, messages: [...next.messages, { role: "assistant", content: "Ok, non ho attivato nulla." }] };
      });
      return;
    }
    setStreaming(true);
    try {
      const r = await api.post("/scheduled-actions", { draft: target.schedDraft });
      setThread((th) => {
        const next = mark("activated")(th);
        return { ...next, messages: [...next.messages, {
          role: "assistant",
          content: `✅ Azione attivata: "${r.data.title}".\nProssima esecuzione: ${r.data.next_run_label}.`,
          schedLink: true,
        }] };
      });
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nell'attivazione");
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
    if (res.status === "confirm_bulk_add") {
      setThread((th) => ({ ...th, messages: [...th.messages, {
        role: "assistant",
        content: `⚠️ ${res.message}`,
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
        sub_items: amb.sub_items, items: amb.items, collection_id: amb.collection_id, item_id: amb.item_id, ...override,
      });
      appendListUpdateResult(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nella modifica della lista");
    } finally {
      setStreaming(false);
    }
  };

  // "elimina/segna come fatto il task X" - checked before a plain "task_todo" message is
  // treated as a request to CREATE a new task, same false-confirmation trap already fixed
  // for Telegram: without this, the LLM would just chat back "fatto!" with no actual delete
  // tool available to it in the normal creation flow.
  const appendTaskCommandResult = (res) => {
    if (res.status === "ambiguous") {
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: "Ho trovato più corrispondenze. Quale intendi?", taskAmbiguous: res }] }));
      return;
    }
    if (res.status === "not_found") {
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: `⚠️ Non ho trovato nessun task/to-do che corrisponda a "${res.query || ""}".` }] }));
      return;
    }
    setThread((th) => ({ ...th, messages: [...th.messages, { role: "assistant", content: `✅ ${res.message}` }] }));
  };

  const resolveTaskCommand = async (targetId, op) => {
    setStreaming(true);
    try {
      const r = await api.post("/tasks/command/apply", { target_id: targetId, op });
      appendTaskCommandResult(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    } finally {
      setStreaming(false);
    }
  };

  // Mobile-only reply flow (spec 5.6, esteso): posta sulla conversazione toccata dall'utente
  // - la card in cronologia è sostituita dalla vista dell'intera conversazione (caricata via
  // openThread quando la card viene toccata), che questa funzione tiene aggiornata in diretta
  // con lo stesso pattern ottimistico/streaming usato da send() sul thread desktop.
  const sendMobileReply = async () => {
    if (recording) { stopRec(); await new Promise((r) => setTimeout(r, 400)); }
    let voiceText = "";
    if (pendingVoice) {
      setTranscribing(true);
      try { voiceText = await transcribeBlob(pendingVoice.blob); }
      catch (e) { toast.error("Trascrizione fallita: " + e.message); setTranscribing(false); return; }
      setTranscribing(false);
      setPendingVoice(null);
    }
    const content = [text.trim(), voiceText].filter(Boolean).join(" ").trim();
    if (!content) return;
    if (streaming || transcribing) return;
    setStreaming(true);
    setText("");
    const replyTarget = mobileReplyTo;
    setThread((th) => (th && th.conv_id === replyTarget.conv_id)
      ? { ...th, messages: [...th.messages, { role: "user", content }], liveAnswer: "" }
      : th);
    const replyAgentResults = [];
    await streamChat(
      { action: replyTarget.action, content, conv_id: replyTarget.conv_id },
      (delta) => setThread((th) => (th && th.conv_id === replyTarget.conv_id) ? { ...th, liveAnswer: (th.liveAnswer || "") + delta } : th),
      async () => {
        setStreaming(false);
        setThread((th) => {
          if (!th || th.conv_id !== replyTarget.conv_id) return th;
          const finalized = th.liveAnswer || "";
          return { ...th, messages: [...th.messages, ...(finalized ? [{ role: "assistant", content: finalized }] : []), ...replyAgentResults.map(agentResultMessage)], liveAnswer: "" };
        });
        await load();
      },
      (err) => { setStreaming(false); toast.error("Errore: " + err.message); },
      (evt) => { if (evt.type === "agent") replyAgentResults.push(evt); }
    );
  };

  const send = async () => {
    if (isMobile && mobileReplyTo) { await sendMobileReply(); return; }
    if (active === "vet_report") { await sendVetReport(); return; }
    if (active === "scheduled_action") { await sendScheduledAction(); return; }
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
    const { main: mainQuestion, parts: taggedParts } = splitMentions(currentQuestion);
    if (active === "info_upload" && attachments.length === 0 && mainQuestion) {
      if (thread?.action === "list_update") {
        setText("");
        await runListUpdateFor(mainQuestion);
        if (taggedParts.length) await dispatchTagged(currentQuestion);
        return;
      }
      // Re-classify on every new message, not just the first one in a thread: a user who
      // uploaded a file (starting an "info_upload" thread) may only ask to act on it - "crea
      // un campo per ogni orario..." - in a LATER message of that same thread, and that must
      // still be caught instead of being treated as a plain conversational follow-up.
      if (!thread || thread.action === "info_upload") {
        try {
          const cls = await api.post("/classify-save-intent", { text: mainQuestion });
          if (cls.data?.kind === "list_update") {
            setText("");
            await runListUpdateFor(mainQuestion);
            if (taggedParts.length) await dispatchTagged(currentQuestion);
            return;
          }
        } catch { /* classification failed: fall through to a normal save */ }
      }
    }

    // "Salvataggio task o to-do" doubles as "elimina/segna come fatto" - checked on every
    // fresh message before it's treated as a request to create a new one.
    if (active === "task_todo" && attachments.length === 0 && mainQuestion && !taggedParts.length && (!thread || thread.action === "task_todo")) {
      try {
        const cmd = await api.post("/tasks/command", { text: currentQuestion });
        if (cmd.data?.status && cmd.data.status !== "not_applicable") {
          setText("");
          if (thread) {
            setThread((th) => ({ ...th, messages: [...th.messages, { role: "user", content: currentQuestion }] }));
          } else {
            setThread({ conv_id: null, action: "task_todo", messages: [{ role: "user", content: currentQuestion }], liveAnswer: "" });
          }
          appendTaskCommandResult(cmd.data);
          setStreaming(false);
          return;
        }
      } catch { /* check failed: fall through to a normal task/to-do creation */ }
    }

    // What the chat SHOWS for this message: the user's own words + the attached file names.
    // The notes for the model (chunks indexed, Drive outcome...) go only in `content`.
    const displayQuestion = [currentQuestion, ...attachments.map((a) => `📎 ${a.name}`)].filter(Boolean).join("\n");
    const driveHintText = currentQuestion;
    const journalImgs = attachments.filter((a) => a.journalImage).map((a) => a.dataUri);
    const journalDocs = attachments.filter((a) => a.journalDocument).map((a) => ({ name: a.name, url: a.url }));
    if (attachments.length > 0) {
      const kbLine = attachments.filter((a) => a.kb).map((a) => `📎 ${a.name} · ${a.chunks} chunk indicizzati (~${a.chars} caratteri)`).join("\n");
      const driveLine = attachments.filter((a) => !a.kb && !a.journalImage && !a.journalDocument).map((a) => `📎 ${a.name}${a.url ? ` (${a.url})` : ""}`).join("\n");
      const parts = [];
      if (kbLine) parts.push(`Allegati caricati nella knowledge base personale:\n${kbLine}`);
      if (driveLine) parts.push(`Allegati caricati su Drive:\n${driveLine}`);
      currentQuestion = (currentQuestion ? currentQuestion + "\n\n" : "") + parts.join("\n\n");
    }
    // mobile: no cloud icon on -> the files stay in the knowledge base only
    const driveFiles = attachments.filter((a) => a.driveFile && !(isMobile && cloudTargets.length === 0));
    const kbDocIds = attachments.filter((a) => a.kb && a.id).map((a) => a.id);
    setText("");
    setAttachments([]);

    if (driveFiles.length > 0) {
      // Awaited (not fire-and-forget) so the AI's confirmation message below can be
      // told the real outcome instead of assuming the file landed on Drive - see the
      // matching "REGOLA CRITICA SU GOOGLE DRIVE" instruction in build_system_prompt.
      const driveResults = await Promise.all(
        driveFiles.map(async (a) => ({ name: a.name, ...(await (isMobile
          ? smartUploadToDrive(a.driveFile, driveHintText, false, { targets: cloudTargets, askFolder: !!chatOpts.askFolder })
          : smartUploadToDrive(a.driveFile, driveHintText, !a.driveExplicit))) }))
      );
      const statusLines = driveResults
        .filter((r) => r.status === "saved" || r.status === "error")
        .map((r) => (r.status === "saved"
          ? `File salvato su ${r.where || "Drive"} nella cartella "${r.folder}": ${r.name}.`
          : `Salvataggio su Drive di "${r.name}" non riuscito${r.error ? `: ${r.error}` : "."}`));
      const waiting = driveResults.filter((r) => r.status === "needs_folder").map((r) => `"${r.name}"`);
      if (waiting.length) {
        statusLines.push(`Non è stato possibile capire in quale cartella Drive salvare ${waiting.length > 1 ? `questi ${waiting.length} file` : "il file"} (${waiting.join(", ")}): NON sono ancora su Drive. Chiedi all'utente in quale cartella salvarli - basta una sola risposta per tutti.`);
      }
      if (statusLines.length > 0) {
        currentQuestion = (currentQuestion ? currentQuestion + "\n\n" : "") + statusLines.join("\n");
      }
    }

    if (thread) {
      setThread((th) => ({ ...th, messages: [...th.messages, { role: "user", content: displayQuestion }], liveAnswer: "" }));
    } else {
      setThread({ conv_id: null, action: active, messages: [{ role: "user", content: displayQuestion }], liveAnswer: "" });
    }

    const payload = { action: active, content: currentQuestion };
    if (displayQuestion !== currentQuestion) payload.display_content = displayQuestion;
    if (kbDocIds.length) payload.attachment_doc_ids = kbDocIds;
    if (active === "info_request") payload.filters = { scope };
    if (active === "task_todo" && isMobile) payload.filters = { calendar: !!chatOpts.taskCal && (googleOn || msOn), reminder: !!chatOpts.taskBell };
    if (active === "journal" && journalImgs.length > 0) payload.images = journalImgs;
    if (active === "journal" && journalDocs.length > 0) payload.documents = journalDocs;
    if (thread?.conv_id) payload.conv_id = thread.conv_id;

    // @agenti results arrive after the main answer; shown right below it
    const agentResults = [];
    await streamChat(
      payload,
      (delta) => setThread((th) => (th ? { ...th, liveAnswer: (th.liveAnswer || "") + delta } : th)),
      async (convId) => {
        setStreaming(false);
        setThread((th) => {
          if (!th) return th;
          const finalized = th.liveAnswer || "";
          return { ...th, conv_id: convId, messages: [...th.messages, ...(finalized ? [{ role: "assistant", content: finalized }] : []), ...agentResults.map(agentResultMessage)], liveAnswer: "" };
        });
        await load();
      },
      (err) => { setStreaming(false); toast.error("Errore: " + err.message); },
      (evt) => { if (evt.type === "agent") agentResults.push(evt); }
    );
  };

  const onAttachClick = () => fileInputRef.current?.click();
  const onFilesPicked = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    e.target.value = "";
    await ingestFiles(files);
  };
  // `forAction` lets the share-target flow attach files right after switching action,
  // before the `active` state update is visible here.
  const ingestFiles = async (files, forAction) => {
    const active = forAction || activeRef.current;

    // Diario: photos stay local (compressed into a data URI) instead of going through
    // KB/Drive - they're only sent to the backend once, embedded in the journal entry,
    // when the message is saved (see send()'s payload.images). Non-image files go to
    // Drive instead (payload.documents), same as a plain attachment elsewhere in the app.
    if (active === "journal") {
      const existingImgCount = attachments.filter((a) => a.journalImage).length;
      let remainingImgs = 5 - existingImgCount;
      for (const f of files) {
        if (!f.type.startsWith("image/")) {
          setUploadingFiles((u) => [...u, f.name]);
          try {
            const fd = new FormData();
            fd.append("file", f, f.name);
            const res = await fetch(`${API}/attachments/upload`, { method: "POST", body: fd, credentials: "include" });
            const j = await res.json();
            if (!res.ok) throw new Error(j.detail || `HTTP ${res.status}`);
            setAttachments((a) => [...a, { name: f.name, id: j.file_id, url: j.web_view_link, journalDocument: true }]);
            toast.success(`${f.name} → ${(j.saved || ["google"]).map((t) => (t === "onedrive" ? "OneDrive" : "Drive")).join(" + ")}`);
          } catch (err) {
            toast.error(`Errore con ${f.name}: ${err.message}`);
          } finally {
            setUploadingFiles((u) => u.filter((n) => n !== f.name));
          }
          continue;
        }
        if (remainingImgs <= 0) { toast.error("Massimo 5 foto per voce di diario"); continue; }
        setUploadingFiles((u) => [...u, f.name]);
        try {
          const dataUri = await fileToJournalImageDataUri(f);
          setAttachments((a) => [...a, { name: f.name, journalImage: true, dataUri }]);
          remainingImgs -= 1;
        } catch (err) {
          toast.error(`Errore con ${f.name}: ${err.message}`);
        } finally {
          setUploadingFiles((u) => u.filter((n) => n !== f.name));
        }
      }
      return;
    }

    // In info_upload and task_todo: extract text (OCR for images) and save into the
    // personal KB (no Google needed) - task_todo needs this so the AI can actually read an
    // attached schedule/program and create a task per event, instead of it going straight
    // to Drive unread. In other actions: keep the previous behaviour (upload to Drive as
    // attachment).
    const useKb = active === "info_upload" || active === "task_todo";
    for (const original of files) {
      setUploadingFiles((u) => [...u, original.name]);
      const f = await prepareImageForUpload(original);
      try {
        const fd = new FormData();
        fd.append("file", f, f.name);
        const endpoint = useKb ? "/kb/upload" : "/attachments/upload";
        const res = await fetch(`${API}${endpoint}`, { method: "POST", body: fd, credentials: "include" });
        if (!res.ok) throw new Error(await uploadErrorMessage(res));
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
          toast.success(`${f.name} → ${(j.saved || ["google"]).map((t) => (t === "onedrive" ? "OneDrive" : "Drive")).join(" + ")}`);
        }
      } catch (err) { toast.error(`Upload ${original.name}: ${err.message}`); }
      finally { setUploadingFiles((u) => u.filter((n) => n !== original.name)); }
    }
  };
  const removeAttachment = (i) => setAttachments((a) => a.filter((_, idx) => idx !== i));

  const smartUploadToDrive = async (file, hintText, silent = false, cloud = null) => {
    setUploadingFiles((u) => [...u, file.name]);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      fd.append("text", hintText || "");
      if (silent) fd.append("silent", "true");
      // mobile icons: which clouds, and whether to ask for a folder the message doesn't name
      if (cloud) { fd.append("targets", cloud.targets.join(",")); fd.append("ask_folder", cloud.askFolder ? "true" : "false"); }
      const res = await fetch(`${API}/drive/smart-upload`, { method: "POST", body: fd, credentials: "include" });
      if (!res.ok) throw new Error(await uploadErrorMessage(res));
      const j = await res.json();
      if (j.status === "saved") {
        toast.success(`${file.name} → ${j.where || "Drive"}/${j.folder}`);
        return { status: "saved", folder: j.folder, where: j.where };
      }
      if (j.status === "skipped") return { status: "skipped" };
      if (!silent) {
        // Several files sent together: one question for all of them (the backend saves the
        // whole batch into the folder given in the answer).
        setPendingDriveUpload((p) => ({ pendingId: j.pending_id, fileName: file.name, count: (p?.count || 0) + 1, suggestions: j.suggestions || [] }));
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


  // ===== pieces shared by the desktop card and the mobile composer =====
  const mentionMenu = (
    <>
      {mentionMatches.length > 0 && (
        <div className="mb-2 rounded-2xl bg-[#2A2429]/95 border border-white/10 shadow-lg overflow-hidden" data-testid="mention-menu">
          {mentionMatches.map((a) => (
            <button
              key={a.key || `p-${a.slug}`}
              type="button"
              data-testid={`mention-${a.tag || a.slug}`}
              onMouseDown={(e) => { e.preventDefault(); insertMention(a); }}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-white/10"
            >
              <span className="rounded-md px-1.5 text-xs font-medium text-white whitespace-nowrap" style={{ background: a.color || PERSON_COLOR }}>@{a.tag || a.slug}</span>
              <span className="text-sm text-white/90 whitespace-nowrap">{a.label || a.name}</span>
              <span className="text-xs text-white/45 truncate min-w-0">{a.hint || (a.kind === "group" ? "condividi con tutti i membri" : "condividi con questa persona")}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
  const shareChips = (
    <>
      {typedPeople.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap mb-2" data-testid="share-chips">
          <span className="text-[11px] text-white/55">Condivido con:</span>
          {typedPeople.map((p) => (
            <span key={p.slug} className="text-[11px] rounded-md px-1.5 py-0.5 text-white" style={{ background: PERSON_COLOR }}>{p.name}</span>
          ))}
          {active !== "info_upload" && <span className="text-[11px] text-amber-300">(funziona con Salva informazioni)</span>}
        </div>
      )}
    </>
  );
  const tagChips = (
    <>
      {typedTags.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap mb-2" data-testid="mention-chips">
          <span className="text-[11px] text-white/55">Invio anche a:</span>
          {typedTags.map((p, i) => (
            <span key={i} className="text-[11px] rounded-md px-1.5 py-0.5 text-white" style={{ background: agentByKey(p.agent)?.color }} title={p.text}>
              @{p.tag} · {p.text.length > 28 ? p.text.slice(0, 27) + "…" : p.text}
            </span>
          ))}
        </div>
      )}
    </>
  );
  const drivePendingChips = (
    <>
      {pendingDriveUpload && (
        <div className="flex items-center gap-1.5 flex-wrap mb-2" data-testid="drive-pending-suggestions">
          <span className="kicker text-white/70">cartella per {pendingDriveUpload.count > 1 ? `${pendingDriveUpload.count} file` : `"${pendingDriveUpload.fileName}"`}:</span>
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
    </>
  );
  const composerChips = (
    <>
      {(recording || transcribing) && <span className="kicker text-white/80">{recording ? "· rec…" : "· trascrivo…"}</span>}
      {pendingVoice && !recording && !transcribing && (
        <span data-testid="voice-chip" className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/25 text-white flex items-center gap-1">
          🎙️ {pendingVoice.seconds}s
          <button onClick={discardVoice} data-testid="voice-discard"><X size={10} /></button>
        </span>
      )}
      {attachments.map((a, i) => (
        <span key={i} className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/20 text-white flex items-center gap-1" title={a.preview || a.name}>
          {a.journalImage ? "📷" : a.ocr ? "🖼️" : "📎"} {a.name.slice(0,12)}{a.name.length > 12 ? "…" : ""}
          {a.ocr && <span className="opacity-70">· ocr</span>}
          <button onClick={() => removeAttachment(i)}><X size={10} /></button>
        </span>
      ))}
      {uploadingFiles.map((name, i) => (
        <span key={`up-${i}`} data-testid="file-uploading-chip" className="text-[10px] font-mono-tight uppercase tracking-widest px-2 py-1 rounded-md bg-white/10 text-white/70 flex items-center gap-1.5" title={`Carico ${name}…`}>
          <Loader2 size={11} className="animate-spin" /> {name.slice(0,12)}{name.length > 12 ? "…" : ""} · carico…
        </span>
      ))}
    </>
  );

  const mobileChatView = isMobile && mobileView === "chat";

  // What a tap on a "per te" suggestion does.
  const runSuggestion = (sug) => {
    const t = sug.target || {};
    if (t.type === "task") navigate("/dashboard/tasks", { state: { openTask: t.id } });
    else if (t.type === "page") navigate(t.to, { state: t.date ? { date: t.date } : undefined });
    else if (t.type === "url") window.open(t.url, "_blank", "noopener");
    else if (t.type === "chat") {
      if (ACTIONS.some((a) => a.id === t.action)) setActive(t.action);
      setThread(null);
      setMobileReplyTo(null);
      setText(t.text || "");
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  };
  const mobileHistoryView = isMobile && mobileView === "history";
  // ===== Mobile chat (like a browser's start page): agent name + ⓘ, its option icons, the
  // bar that opens up while you write, the row of agents (Cerca first, then the 3 most used,
  // then "Altri"). Desktop keeps its own card above.
  const selectAgent = (id) => {
    setActive(id);
    if (thread && thread.action !== id) setThread(null);
    setMobileReplyTo(null);
    setVisitMenuOpen(false);
  };
  const usage = useMemo(() => {
    const since = Date.now() - 30 * 864e5;
    const c = {};
    history.forEach((h) => {
      if (new Date(h.created_at).getTime() < since) return;
      const k = h.action === "list_update" ? "info_upload" : h.action;
      c[k] = (c[k] || 0) + 1;
    });
    return c;
  }, [history]);
  const rowAgents = useMemo(() => {
    const others = ACTIONS.filter((a) => a.id !== "info_request").sort((a, b) => (usage[b.id] || 0) - (usage[a.id] || 0));
    let row = [ACTIONS[0], ...others.slice(0, 3)];
    if (!row.some((a) => a.id === active)) row = [...row.slice(0, 3), ACTIONS.find((a) => a.id === active)];
    return row;
  }, [usage, active]);
  const optIcon = (key, Icon, on, onClick, title) => (
    <button
      key={key}
      type="button"
      data-testid={`opt-${key}`}
      onClick={onClick}
      title={title}
      aria-label={title}
      aria-pressed={on}
      className={`h-8 w-8 flex items-center justify-center transition-all duration-200 ${on ? "text-white drop-shadow-[0_0_6px_rgba(255,255,255,0.55)]" : "text-white/40"}`}
    >
      <Icon size={19} />
    </button>
  );
  const flash = (msg) => toast.message(msg, { duration: 1400 });
  const toggleCloud = (t, label) => {
    const on = cloudTargets.includes(t);
    setChatOpt({ cloud: on ? cloudTargets.filter((x) => x !== t) : [...cloudTargets, t] });
    flash(`${label}: ${on ? "spento" : "acceso"}`);
  };
  const agentOptions = [];
  if (active === "info_request") {
    agentOptions.push(
      optIcon("scope-all", Layers, scope === "all", () => { setScope("all"); flash("Cerco ovunque"); }, "Cerca ovunque"),
      optIcon("scope-kb", Database, scope === "kb", () => { setScope("kb"); flash("Cerco solo nella base di conoscenza"); }, "Solo base di conoscenza"),
    );
  } else if (active === "info_upload") {
    if (googleOn) agentOptions.push(optIcon("cloud-google", HardDrive, cloudTargets.includes("google"), () => toggleCloud("google", "Google Drive"), "Salva anche su Google Drive"));
    if (msOn) agentOptions.push(optIcon("cloud-onedrive", Cloud, cloudTargets.includes("onedrive"), () => toggleCloud("onedrive", "OneDrive"), "Salva anche su OneDrive"));
    if (cloudTargets.length) agentOptions.push(optIcon("ask-folder", Folder, !!chatOpts.askFolder, () => {
      setChatOpt({ askFolder: !chatOpts.askFolder });
      flash(chatOpts.askFolder ? "Cartella automatica" : "Ti chiedo la cartella se non la scrivi");
    }, "Chiedimi la cartella"));
  } else if (active === "task_todo") {
    if (googleOn || msOn) agentOptions.push(optIcon("task-calendar", Calendar, !!chatOpts.taskCal, () => {
      setChatOpt({ taskCal: !chatOpts.taskCal });
      flash(chatOpts.taskCal ? "Calendario: spento" : "I nuovi task vanno anche nel calendario");
    }, "Metti nel calendario"));
    agentOptions.push(optIcon("task-reminder", Bell, !!chatOpts.taskBell, () => {
      setChatOpt({ taskBell: !chatOpts.taskBell });
      flash(chatOpts.taskBell ? "Promemoria: spento" : "Promemoria acceso per i nuovi task");
    }, "Promemoria"));
  } else if (active === "vet_report") {
    agentOptions.push(optIcon("visit-type", ClipboardList, true, () => setVisitMenuOpen((v) => !v), "Tipo di visita"));
  }
  const visitTypes = [...(vetTemplates.builtin || []).map((t) => ({ id: t.key, name: t.name })), ...(vetTemplates.custom || []).map((t) => ({ id: t.id, name: t.name }))];

  const compactHero = !!(text.trim() || thread || mobileReplyTo || attachments.length || pendingVoice);
  const composerOpen = composerGrown || attachments.length > 0 || uploadingFiles.length > 0 || !!pendingVoice || recording || transcribing
    || mentionMatches.length > 0 || typedTags.length > 0 || typedPeople.length > 0 || !!pendingDriveUpload;
  const canSend = !(streaming || transcribing || uploadingFiles.length > 0 || (!text.trim() && attachments.length === 0 && !pendingVoice && !recording));
  const insertAt = () => {
    const el = textareaRef.current;
    const caret = el?.selectionStart ?? text.length;
    const before = text.slice(0, caret);
    const add = (before && !/\s$/.test(before) ? " " : "") + "@";
    pendingCaretRef.current = before.length + add.length;
    setText(before + add + text.slice(caret));
    setMentionQuery("");
  };
  const info = AGENT_INFO[active] || { what: "", options: [], examples: [] };

  const mobileChat = (
    <div data-testid="mobile-chat">
      {!compactHero && <SuggestionsTicker onSelect={runSuggestion} />}
      <div className={`flex flex-col items-center text-center ${compactHero ? "mt-1" : "mt-10"}`} data-testid="agent-hero">
        {!compactHero && <div className="text-[10px] tracking-[0.22em] uppercase text-white/60">agente</div>}
        <div className="flex items-center gap-2">
          <h1
            data-testid="agent-name"
            className={`font-semibold tracking-tight leading-tight bg-gradient-to-r from-white via-[#E9D5FF] to-[#BFDBFE] bg-clip-text text-transparent transition-all duration-200 ${compactHero ? "text-[30px]" : "text-[42px]"}`}
          >
            {activeAction.short}
          </h1>
          <button
            type="button"
            data-testid="agent-info-btn"
            onClick={() => setInfoOpen(true)}
            title={`Cosa fa ${activeAction.short}`}
            aria-label={`Cosa fa ${activeAction.short}`}
            className="h-[18px] w-[18px] rounded-full border border-white/70 bg-white/10 flex items-center justify-center text-[10px] leading-none italic font-semibold font-serif text-white"
          >
            i
          </button>
        </div>
        {agentOptions.length > 0 && <div className="flex items-center justify-center gap-3" data-testid="agent-options">{agentOptions}</div>}
        {visitMenuOpen && active === "vet_report" && (
          <div className="mt-2 flex flex-wrap justify-center gap-1.5" data-testid="visit-type-menu">
            {visitTypes.map((t) => (
              <button key={t.id} onClick={() => { setVisitType(t.id); setVisitMenuOpen(false); }}
                className={`text-xs px-3 py-1.5 rounded-full ${visitType === t.id ? "bg-white text-[#403A3C]" : "bg-white/10 text-white/85"}`}>{t.name}</button>
            ))}
            <button onClick={() => { setShowTemplateUpload(true); setVisitMenuOpen(false); }} className="text-xs px-3 py-1.5 rounded-full bg-white/10 text-white/85 inline-flex items-center gap-1">
              <UploadCloud size={12} /> carica modello
            </button>
          </div>
        )}
      </div>

      {mobileReplyTo && (
        <div data-testid="mobile-reply-pill" className="flex items-center gap-2 mt-3 px-3 py-2 rounded-xl bg-white/10 text-white/85 text-xs">
          <Reply size={13} className="shrink-0" />
          <span className="flex-1 min-w-0 truncate">Rispondi a: {mobileReplyTo.label}</span>
          <button data-testid="mobile-reply-clear" onClick={startNewMobileConversation} title="Torna a un nuovo messaggio" className="shrink-0 p-0.5 rounded-full hover:bg-white/10">
            <X size={13} />
          </button>
        </div>
      )}

      {/* One DOM for both shapes (bar / card), only the classes change: the textarea is never
          remounted, so the keyboard stays open when the bar opens up. */}
      <div
        data-testid="chat-input-card"
        className={`mt-5 flex flex-wrap items-center bg-white/15 border border-white/35 backdrop-blur-xl shadow-[inset_0_1px_1px_rgba(255,255,255,0.45),0_10px_30px_rgba(0,0,0,0.25)] transition-[border-radius] duration-200 ${composerOpen ? "rounded-3xl px-4 pt-3 pb-2 gap-y-1" : "rounded-full pl-3 pr-1.5 py-1.5"}`}
      >
        <button data-testid="attach-btn" onClick={onAttachClick} title="Allega" aria-label="Allega"
          className={`p-2 rounded-full text-white/85 hover:bg-white/15 ${composerOpen ? "order-3" : "order-1"}`}>
          <Paperclip size={19} />
        </button>
        <Textarea
          data-testid="chat-textarea"
          ref={textareaRef}
          value={text}
          onChange={onComposerChange}
          onClick={(e) => setMentionQuery(mentionQueryAt(text, e.target.selectionStart))}
          onKeyDown={(e) => {
            if (mentionMatches.length && (e.key === "Enter" || e.key === "Tab")) { e.preventDefault(); insertMention(mentionMatches[0]); return; }
            if (e.key === "Escape") setMentionQuery(null);
          }}
          placeholder={(thread || mobileReplyTo) ? "Rispondi o chiedi altro…" : activeAction.placeholder}
          rows={1}
          className={`border-0 focus-visible:ring-0 bg-transparent shadow-none min-h-0 text-[15px] leading-relaxed py-2 px-1 resize-none text-white placeholder:text-white/55 overflow-y-auto ${composerOpen ? "order-1 basis-full" : "order-2 flex-1 min-w-0 placeholder:truncate"}`}
        />
        {composerOpen && (
          <div className="order-2 basis-full">
            {mentionMenu}
            {shareChips}
            {tagChips}
            {drivePendingChips}
            <div className="flex items-center gap-1.5 flex-wrap empty:hidden mb-1">{composerChips}</div>
          </div>
        )}
        {composerOpen && (
          <button type="button" data-testid="at-btn" onClick={insertAt} title="Tagga un agente o una persona" aria-label="Tagga"
            className="order-3 p-2 rounded-full text-white/85 hover:bg-white/15">
            <AtSign size={19} />
          </button>
        )}
        {composerOpen && <div className="order-2 basis-full h-px bg-white/15" />}
        <div className={`order-3 flex items-center gap-1 ${composerOpen ? "ml-auto" : ""}`}>
          <button
            data-testid="mic-btn"
            onClick={recording ? stopRec : startRec}
            disabled={transcribing}
            title={recording ? "Ferma" : "Detta"}
            aria-label={recording ? "Ferma" : "Detta"}
            className={`p-2 rounded-full transition-colors duration-150 ${recording ? "bg-white/30 text-white animate-pulse" : "text-white/85 hover:bg-white/15"}`}
          >{recording ? <MicOff size={19} /> : <Mic size={19} />}</button>
          <button
            data-testid="send-btn"
            onClick={send}
            disabled={!canSend}
            title="Invia"
            aria-label="Invia"
            style={{ background: activeAction.color }}
            className="h-10 w-10 rounded-full flex items-center justify-center text-white shadow-md disabled:opacity-60"
          >
            {streaming || transcribing || uploadingFiles.length > 0 ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-5 mt-8" data-testid="agent-row">
        {rowAgents.map((a) => {
          const sel = a.id === active;
          return (
            <button key={a.id} data-testid={`action-${a.key}`} onClick={() => selectAgent(a.id)} aria-pressed={sel}
              className="flex flex-col items-center gap-1.5">
              <span className={`h-12 w-12 rounded-full flex items-center justify-center text-white transition-all duration-200 ${sel ? "shadow-[0_6px_18px_rgba(0,0,0,0.25)]" : ""}`}
                style={sel ? glowTileStyle(a.color) : undefined}>
                {React.cloneElement(a.icon, { size: 20 })}
              </span>
              <span className={`text-[11.5px] ${sel ? "font-semibold text-white" : "text-white/85"}`}>{a.short}</span>
            </button>
          );
        })}
        <button data-testid="agents-more" onClick={() => setAllAgentsOpen(true)} className="flex flex-col items-center gap-1.5">
          <span className="h-12 w-12 rounded-full flex items-center justify-center text-white"><Plus size={22} /></span>
          <span className="text-[11.5px] text-white/85">Altri</span>
        </button>
      </div>

      {infoOpen && (
        <BottomSheet onClose={() => setInfoOpen(false)} testid="agent-info-sheet">
          <div className="flex items-center gap-3">
            <span className="h-11 w-11 rounded-full flex items-center justify-center text-white shrink-0" style={glowTileStyle(activeAction.color)}>
              {React.cloneElement(activeAction.icon, { size: 19 })}
            </span>
            <div className="min-w-0">
              <div className="text-lg font-semibold text-white">{activeAction.title}</div>
              <div className="text-xs text-white/55">agente</div>
            </div>
          </div>
          <SheetSection title="cosa fa"><p className="text-[13.5px] leading-relaxed text-white/90 font-light">{info.what}</p></SheetSection>
          {info.options.length > 0 && (
            <SheetSection title="icone sotto il nome">
              <div className="space-y-2">
                {info.options.map(([Icon, label], i) => (
                  <div key={i} className="flex items-start gap-3 text-[13px] text-white/85 font-light">
                    <Icon size={17} className="text-white shrink-0 mt-0.5" /> <span>{label}</span>
                  </div>
                ))}
              </div>
            </SheetSection>
          )}
          <SheetSection title="esempi · tocca per provare">
            <div className="space-y-1.5">
              {info.examples.map((ex) => (
                <button key={ex} data-testid="agent-example" onClick={() => { setText(ex); setInfoOpen(false); setTimeout(() => textareaRef.current?.focus(), 60); }}
                  className="w-full flex items-center gap-3 text-left px-3 py-2.5 rounded-2xl bg-white/[0.07] border border-white/10 text-[13px] text-white/90 font-light">
                  <span className="flex-1">«{ex}»</span>
                  <span className="shrink-0 text-[11px] font-medium text-white bg-white/15 px-2.5 py-0.5 rounded-full">Prova</span>
                </button>
              ))}
            </div>
          </SheetSection>
          <SheetSection title="chiama altri agenti con @">
            <p className="text-[13px] leading-relaxed text-white/85 font-light mb-2">
              Nello stesso messaggio puoi far fare qualcosa anche a un altro agente{people.length ? ", o condividere con il team" : ""}: scrivi @ e scegli.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {MENTION_AGENTS.map((a) => (
                <span key={a.key} className="rounded-lg px-2 py-0.5 text-[13px] font-medium text-white" style={{ background: a.color }}>@{a.tag}</span>
              ))}
              {people.length > 0 && <span className="rounded-lg px-2 py-0.5 text-[13px] font-medium text-white" style={{ background: PERSON_COLOR }}>@nome · @team</span>}
            </div>
            <div className="mt-3 px-3 py-2.5 rounded-2xl bg-white/[0.07] border border-white/10 text-[12.5px] leading-relaxed text-white/90 font-light">
              «Visitato Fester, tutto ok <span className="rounded-md px-1.5 font-medium text-white" style={{ background: agentByKey("task_todo").color }}>@task</span> richiamare la padrona giovedì»
            </div>
          </SheetSection>
        </BottomSheet>
      )}

      {allAgentsOpen && (
        <BottomSheet onClose={() => setAllAgentsOpen(false)} testid="all-agents-sheet">
          <div className="text-lg font-semibold text-white">Tutti gli agenti</div>
          <p className="text-[12.5px] text-white/60 mt-1">Nella riga trovi Cerca e i 3 che usi di più: l'ordine si aggiorna da solo.</p>
          <div className="grid grid-cols-3 gap-y-5 mt-5">
            {ACTIONS.map((a) => {
              const sel = a.id === active;
              const n = usage[a.id] || 0;
              return (
                <button key={a.id} data-testid={`all-agents-${a.key}`} onClick={() => { selectAgent(a.id); setAllAgentsOpen(false); }} className="flex flex-col items-center gap-1">
                  <span className="h-14 w-14 rounded-full flex items-center justify-center text-white" style={sel ? glowTileStyle(a.color) : undefined}>
                    {React.cloneElement(a.icon, { size: 22 })}
                  </span>
                  <span className={`text-[13px] ${sel ? "font-semibold text-white" : "text-white/90"}`}>{a.short}</span>
                  <span className="text-[10.5px] text-white/50">{a.id === "info_request" ? "sempre prima" : n === 1 ? "1 chat recente" : n ? `${n} chat recenti` : "non usato di recente"}</span>
                </button>
              );
            })}
          </div>
          <SheetSection title="altro">
            <button onClick={() => { setAllAgentsOpen(false); setMobileView("history"); }}
              className="w-full flex items-center gap-3 text-left px-3 py-2.5 rounded-2xl bg-white/[0.07] border border-white/10 text-[13px] text-white/90">
              <History size={16} /> <span className="flex-1">Cronologia delle chat</span>
              <span className="text-[11px] font-medium text-white bg-white/15 px-2.5 py-0.5 rounded-full">Apri</span>
            </button>
          </SheetSection>
        </BottomSheet>
      )}
    </div>
  );


  return (
    <div className="relative w-full">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6 w-full lg:h-[calc(100vh-15rem)]">
        {/* LEFT 1/3 — action icons + input area */}
        <aside className={`lg:col-span-1 flex flex-col lg:overflow-y-auto pr-1 ${focusMode || (isMobile && mobileView === "history") ? "hidden" : ""}`}>
          {isMobile ? mobileChat : (
          <>
          {/* Top block mirrors the right-side filter bar (same padding/height) so the input aligns with the first history card */}
          <div className="flex items-center gap-1.5 md:gap-2 p-3 md:p-3.5 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm shrink-0 overflow-x-auto no-scrollbar">
              {ACTIONS.map((a) => {
                const selected = a.id === active;
                return (
                  <button
                    key={a.id}
                    data-testid={`action-${a.key}`}
                    onClick={() => { setActive(a.id); if (thread && thread.action !== a.id) setThread(null); setMobileReplyTo(null); }}
                    title={a.title}
                    aria-label={a.title}
                    style={{
                      backgroundColor: selected ? a.color : undefined,
                      color: "#CECAD0",
                      opacity: selected ? 1 : 0.5,
                      borderColor: selected ? a.color : "rgba(206,202,208,0.25)",
                    }}
                    className={`liquid-glass-btn ${selected ? "" : "liquid-still"} group relative h-8 w-8 md:h-9 md:w-9 rounded-full border shadow-sm flex items-center justify-center transition-all duration-200 hover:opacity-100 hover:shadow-md`}
                  >
                    {React.cloneElement(a.icon, { size: 15 })}
                    <span className="pointer-events-none absolute -bottom-9 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-lg bg-[#403A3C] text-white text-[11px] font-medium px-2.5 py-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150 shadow-lg z-30">
                      {a.title}
                    </span>
                  </button>
                );
              })}
              {/* Mobile (spec v2 §3.2/3.3): "nuova conversazione" (solo quando ce n'è una a
                  schermo) e l'accesso alla cronologia, nella stessa riga delle azioni. */}
              {isMobile && (
                <div className="ml-auto flex items-center gap-1.5 pl-2 border-l border-white/10 shrink-0">
                  {(thread || mobileReplyTo) && (
                    <button
                      data-testid="mobile-new-conversation"
                      onClick={startNewMobileConversation}
                      title="Nuova conversazione"
                      aria-label="Nuova conversazione"
                      className="liquid-glass-btn liquid-still h-8 w-8 rounded-full flex items-center justify-center text-white/85"
                    >
                      <MessageSquarePlus size={15} />
                    </button>
                  )}
                  <button
                    data-testid="mobile-history-toggle"
                    onClick={() => setMobileView("history")}
                    title="Messaggi precedenti"
                    aria-label="Messaggi precedenti"
                    className="liquid-glass-btn liquid-still h-8 w-8 rounded-full flex items-center justify-center text-white/85"
                  >
                    <History size={15} />
                  </button>
                </div>
              )}
          </div>
          {/* Nascosto su mobile: l'azione selezionata è già indicata dentro la card della
              chat (kicker "· ...") subito sotto, ripeterla qui sopra è ridondante. */}
          <div className="hidden md:flex items-center justify-between px-2 mt-4 shrink-0">
            <div className="text-xs font-bold uppercase tracking-wider text-white">nuovo messaggio</div>
            <div className="text-xs font-bold uppercase tracking-wider text-white/70">{activeAction.title.toLowerCase()}</div>
          </div>
          {isMobile && mobileReplyTo && (
            <div data-testid="mobile-reply-pill" className="flex items-center gap-2 mt-2 px-3 py-2 rounded-xl bg-white/10 text-white/85 text-xs">
              <Reply size={13} className="shrink-0" />
              <span className="flex-1 min-w-0 truncate">Rispondi a: {mobileReplyTo.label}</span>
              <button data-testid="mobile-reply-clear" onClick={startNewMobileConversation} title="Torna a un nuovo messaggio" className="shrink-0 p-0.5 rounded-full hover:bg-white/10">
                <X size={13} />
              </button>
            </div>
          )}
          <div className="chat-input-card p-4 md:p-5 rounded-2xl shadow-lg mt-2 md:min-h-[340px] flex flex-col" data-testid="chat-input-card">
            {/* The selected action is already shown by the highlighted icon above - no title in the box;
                this row only exists for the per-action selectors. */}
            {(active === "info_request" || active === "vet_report") && !thread && (
              <div className="flex items-center mb-3 gap-2 flex-wrap">
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
            )}
            <Textarea
              data-testid="chat-textarea"
              ref={textareaRef}
              value={text}
              onChange={onComposerChange}
              onClick={(e) => setMentionQuery(mentionQueryAt(text, e.target.selectionStart))}
              onKeyDown={(e) => {
                if (mentionMatches.length && (e.key === "Enter" || e.key === "Tab")) { e.preventDefault(); insertMention(mentionMatches[0]); return; }
                if (e.key === "Escape") setMentionQuery(null);
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") send();
              }}
              placeholder={(thread || mobileReplyTo) ? "Rispondi o chiedi altro nel contesto…" : activeAction.placeholder}
              rows={isMobile ? 1 : undefined}
              className="diary-lines border-0 focus-visible:ring-0 bg-transparent text-base md:flex-1 md:min-h-[200px] px-0 resize-none text-white placeholder:text-white/60 overflow-y-auto"
            />
            {mentionMenu}
            {shareChips}
            {tagChips}
            {drivePendingChips}
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
                {composerChips}
              </div>
              <button data-testid="send-btn" onClick={send}
                disabled={streaming || transcribing || uploadingFiles.length > 0 || (!text.trim() && attachments.length === 0 && !pendingVoice && !recording)}
                className="shrink-0 inline-flex items-center gap-2 p-2.5 md:px-4 md:py-2 rounded-full bg-[#CECAD0] text-[#403A3C] font-medium disabled:opacity-50 hover:bg-white text-sm">
                <Send size={14} />
                <span className="hidden md:inline">{streaming ? "Elaboro…" : transcribing ? "Trascrivo…" : uploadingFiles.length > 0 ? "Carico…" : recording ? "Ferma & invia" : "Invia"}</span>
              </button>
            </div>
          </div>
          </>
          )}
          <input ref={fileInputRef} type="file" multiple hidden onChange={onFilesPicked} accept={active === "info_upload" ? ".pdf,.docx,.xlsx,.txt,.md,.csv,.json,.html,.xml,.yaml,.yml,.log,.jpg,.jpeg,.png,.webp,.heic,.heif" : active === "journal" ? "image/*,.pdf,.docx,.xlsx,.txt,.md,.csv" : undefined} data-testid="file-input" />
        </aside>

        {/* RIGHT 2/3 — scrolls. On mobile (spec v2 §3) this area is either the conversation
            on screen (chat view - nothing at all before the first message is sent) or the
            history of old conversations (history view), never both. */}
        <section className={`${focusMode ? "lg:col-span-3" : "lg:col-span-2"} flex flex-col h-full overflow-hidden ${mobileChatView && !thread ? "hidden" : ""}`}>
          {/* Filters (hidden in focus mode when a thread is open; on mobile only in the history view) */}
          {(isMobile ? mobileHistoryView : !(focusMode && thread)) && (
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
          {thread && !mobileHistoryView ? (
            <div className="p-5 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm flex-1 flex flex-col mt-4 overflow-hidden" data-testid="thread-card">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ACTION_COLOR[thread.action] || "#CECAD0" }} />
                  <div className="kicker">
                    {thread.action === "info_upload" ? "caricamento" : thread.action === "info_request" ? "richiesta" : thread.action === "journal" ? "diario" : thread.action === "vet_report" ? "report" : thread.action === "list_update" ? "modifica lista" : thread.action === "scheduled_action" ? "azione programmata" : "task / to-do"}
                    {" · thread "}{thread.conv_id ? thread.conv_id.slice(-6) : "nuovo"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {/* No focus mode on mobile: it hides the composer, which must stay available (spec v2 §3.2). */}
                  {!isMobile && (
                    <button data-testid="focus-mode-btn" onClick={() => setFocusMode((v) => !v)} className="kicker px-3 py-1.5 rounded-full  bg-white/10 text-white hover: inline-flex items-center gap-1" title={focusMode ? "Esci focus" : "Modalità focus"}>
                      {focusMode ? <Minimize2 size={12} /> : <Maximize2 size={12} />} {focusMode ? "esci focus" : "focus"}
                    </button>
                  )}
                  <button data-testid="new-thread-btn" onClick={() => { setThread(null); setFocusMode(false); setPendingDriveUpload(null); setMobileReplyTo(null); }} className="kicker px-3 py-1.5 rounded-full  bg-white/10 text-white hover: inline-flex items-center gap-1">
                    <MessageSquarePlus size={12} /> nuova
                  </button>
                  <button data-testid="close-thread-btn" onClick={closeThread} className="p-1.5 rounded-full hover:bg-white/10 text-white"><X size={14} /></button>
                </div>
              </div>
              <div className="space-y-4 flex-1 overflow-y-auto pr-2">
                {thread.messages.map((m, i) => (
                  <div key={i}>
                    <div className="kicker mb-1">{m.role === "user" ? "· tu" : ""}</div>
                    {m.agent && agentByKey(m.agent) && (
                      <span className="ml-4 inline-block rounded-md px-1.5 text-[11px] font-medium text-white" style={{ background: agentByKey(m.agent).color }} data-testid="agent-result-tag">
                        @{agentByKey(m.agent).tag}
                      </span>
                    )}
                    <div className={m.role === "user" ? "bg-white/10 rounded-2xl px-4 py-3 text-white whitespace-pre-wrap" : "prose-answer whitespace-pre-wrap text-[15px] px-4 py-2 text-white"}>
                      {m.role === "user" ? renderWithTags(m.content) : m.content}
                    </div>
                    {m.taskLink && (
                      <button
                        data-testid="agent-open-task"
                        onClick={() => navigate("/dashboard/tasks", { state: { openTask: m.taskLink } })}
                        className="ml-4 mt-1 inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-white/10 hover:bg-white/15 text-white"
                      >
                        <CheckSquare size={12} /> Apri il task
                      </button>
                    )}
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
                    {m.schedDraft && !m.schedDone && (
                      <div className="flex flex-wrap gap-2 mt-2 ml-4" data-testid="scheduled-confirm">
                        <button
                          data-testid="scheduled-activate"
                          onClick={() => resolveScheduledDraft(i, true)}
                          disabled={streaming}
                          className="text-xs px-3 py-1.5 rounded-full disabled:opacity-50 bg-[#3E7C8C] hover:bg-[#4A8D9E] text-white"
                        >
                          Attiva
                        </button>
                        <button
                          data-testid="scheduled-cancel"
                          onClick={() => resolveScheduledDraft(i, false)}
                          disabled={streaming}
                          className="text-xs px-3 py-1.5 rounded-full disabled:opacity-50 bg-white/10 hover:bg-white/20 text-white"
                        >
                          Annulla
                        </button>
                      </div>
                    )}
                    {m.schedLink && (
                      <button
                        data-testid="scheduled-open-section"
                        onClick={() => navigate("/dashboard/azioni")}
                        className="ml-4 mt-2 inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-white/10 hover:bg-white/15 text-white"
                      >
                        <Repeat size={12} /> Vai alla sezione Azioni
                      </button>
                    )}
                    {m.taskAmbiguous && (
                      <div className="flex flex-wrap gap-2 mt-2 ml-4" data-testid="ambiguous-task-choices">
                        {m.taskAmbiguous.candidates.map((c) => (
                          <button
                            key={c.id}
                            onClick={() => resolveTaskCommand(c.id, m.taskAmbiguous.op)}
                            disabled={streaming}
                            className="text-xs px-3 py-1.5 rounded-full disabled:opacity-50 bg-white/10 hover:bg-white/20 text-white"
                          >
                            {c.title}
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
          ) : mobileHistoryView ? (
            // Mobile history (spec: note-style grid): search/filters stay on top, then two
            // columns of tiles - first the "+" tile back to a new chat, then one tile per
            // conversation colored by its action. Tapping a tile reopens that conversation
            // in the chat view, ready to be continued.
            // Two flex columns filled alternately (tile 0 left, 1 right, 2 left...) rather than
            // CSS columns, which fill the whole left column first: this way the conversations
            // read row by row, in the same order as the list, like a notes app.
            (() => {
              const tiles = [
                <button
                  key="__new"
                  data-testid="history-new-chat"
                  onClick={startNewMobileConversation}
                  title="Torna alla chat"
                  aria-label="Torna alla chat"
                  className="w-full h-36 rounded-3xl flex items-center justify-center bg-white/20 backdrop-blur-xl text-white shadow-md"
                >
                  <Plus size={44} strokeWidth={1.5} />
                </button>,
                ...filtered.map((c) => (
                  <MobileHistoryCard
                    key={c.conv_id}
                    conv={c}
                    isReplying={mobileReplyTo?.conv_id === c.conv_id}
                    onOpen={() => resumeMobileConversation(c)}
                    onToggleFav={() => toggleFavorite(c.conv_id, !!c.favorite)}
                    onDelete={() => deleteConv(c.conv_id)}
                  />
                )),
              ];
              return (
                <>
                  <div className="flex gap-3 mt-4 items-start" data-testid="mobile-history-grid">
                    {[0, 1].map((col) => (
                      <div key={col} className="flex-1 min-w-0 flex flex-col gap-3">
                        {tiles.filter((_, i) => i % 2 === col)}
                      </div>
                    ))}
                  </div>
                  <div className="mt-5 px-1 text-[11px] text-white/45" data-testid="history-retention-note">{HISTORY_RETENTION_NOTE}</div>
                </>
              );
            })()
          ) : (
            <>
              <div className="flex items-center justify-between px-2 mt-4 shrink-0">
                <div className="text-xs font-bold uppercase tracking-wider text-white">cronologia</div>
                <div className="text-xs font-bold uppercase tracking-wider text-white/70">{filtered.length} messaggi</div>
              </div>
              <div className="px-2 mt-1 text-[11px] text-white/45 shrink-0">{HISTORY_RETENTION_NOTE}</div>
              <div className="space-y-3 flex-1 overflow-y-auto pr-1 mt-2">
                {filtered.length === 0 && <div className="text-white/60 text-sm">Nessuna conversazione ancora.</div>}
                {filtered.map((c, idx) => (
                  <HistoryCard
                    key={c.conv_id}
                    conv={c}
                    index={idx}
                    isReplying={mobileReplyTo?.conv_id === c.conv_id}
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

const hexToRgba = (hex, alpha) => {
  const h = hex.replace("#", "");
  return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${alpha})`;
};

// Mixes a hex color toward white (t > 0) or black (t < 0), returning hex.
const shadeHex = (hex, t) => {
  const h = hex.replace("#", "");
  const target = t >= 0 ? 255 : 0;
  const k = Math.abs(t);
  return "#" + [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16);
    return Math.round(c + (target - c) * k).toString(16).padStart(2, "0");
  }).join("");
};

// Soft "glowing" tile in the action's color: deeper in the middle, lighter and luminous
// toward the edges, with an inner light rim and a colored halo underneath.
const glowTileStyle = (color) => ({
  background: `radial-gradient(ellipse 85% 80% at 50% 55%, ${hexToRgba(shadeHex(color, -0.12), 0.95)} 0%, ${hexToRgba(color, 0.92)} 45%, ${hexToRgba(shadeHex(color, 0.38), 0.9)} 100%)`,
  boxShadow: `inset 0 0 20px 3px ${hexToRgba(shadeHex(color, 0.6), 0.55)}, inset 0 1px 1px rgba(255, 255, 255, 0.35), 0 14px 32px -10px ${hexToRgba(color, 0.7)}`,
});

// Mobile history tile: one-word topic (white) with the star beside it, the first
// question in a lighter tint of the tile's own color (readable, but quieter than the
// topic), a blank line as tall as that text, then "25 set 15:00" with the trash can.
function MobileHistoryCard({ conv, isReplying = false, onOpen, onToggleFav, onDelete }) {
  const d = conv.created_at ? new Date(conv.created_at) : null;
  const pad = (n) => String(n).padStart(2, "0");
  const dateLabel = d ? `${d.getDate()} ${IT_MONTHS_SHORT[d.getMonth()]} ${pad(d.getHours())}:${pad(d.getMinutes())}` : "";
  const title = conv.title || (conv.meta && conv.meta.title) || "";
  const topic = conv.topic || (title ? title.split(/\s+/)[0] : "") || ACTION_LABELS_IT[conv.action] || "Chat";
  const question = (conv.messages && conv.messages.find((m) => m.role === "user")?.content) || conv.user_message || "";
  const isFav = !!conv.favorite;
  const color = ACTION_COLOR[conv.action] || "#6D6181";
  const questionColor = hexToRgba(shadeHex(color, 0.62), 0.95);
  const stop = (fn) => (e) => { e.stopPropagation(); e.preventDefault(); fn(); };
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}
      data-testid="history-card"
      className={`rounded-3xl p-4 text-white cursor-pointer ${isReplying ? "ring-2 ring-white/70" : ""}`}
      style={glowTileStyle(color)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-base font-normal leading-tight text-white break-words min-w-0" data-testid="conv-topic">{topic}</div>
        <button data-testid="fav-btn" onClick={stop(onToggleFav)} title={isFav ? "Rimuovi preferito" : "Preferito"}
          className={`-mt-1 -mr-1 p-1 shrink-0 ${isFav ? "text-amber-300" : "text-white/70"}`}>
          <Star size={16} className={isFav ? "fill-current" : ""} />
        </button>
      </div>
      {question && (
        <div className="mt-2 text-xs leading-snug line-clamp-5 break-words" style={{ color: questionColor }} data-testid="conv-question">{question}</div>
      )}
      <div className="h-3" aria-hidden="true" />
      <div className="flex items-center justify-between gap-2 text-xs text-white">
        <span className="truncate">{dateLabel}</span>
        <button data-testid="delete-conv-btn" onClick={stop(onDelete)} title="Elimina" className="p-1 -mr-1 shrink-0 text-white/70">
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}

function HistoryCard({ conv, index = 0, isReplying = false, onOpen, onToggleFav, onDelete }) {
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
      className={`p-4 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm card-hover card-enter ${isReplying ? "ring-2 ring-white/60" : ""}`}
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

// Mobile panel sliding up from the bottom (agent info, all agents). Portaled to <body>: the
// page's frosted (backdrop-filter) ancestors would otherwise trap a fixed element inside them.
function BottomSheet({ onClose, testid, children }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return createPortal(
    <div className="fixed inset-0 z-[70]" data-testid={testid}>
      <div className="absolute inset-0 bg-[#0A0819]/50 animate-in fade-in duration-200" onClick={onClose} />
      <div className="absolute left-0 right-0 bottom-0 max-h-[86vh] overflow-y-auto rounded-t-[28px] bg-[#28223A]/90 backdrop-blur-2xl border-t border-white/20 shadow-[0_-10px_40px_rgba(0,0,0,0.35)] px-5 pt-3 pb-[calc(env(safe-area-inset-bottom,0px)+24px)] animate-in slide-in-from-bottom duration-300">
        <div className="w-10 h-1 rounded-full bg-white/35 mx-auto mb-4" />
        <button onClick={onClose} aria-label="Chiudi" data-testid="sheet-close" className="absolute top-4 right-4 p-1.5 rounded-full text-white/70 hover:bg-white/10"><X size={18} /></button>
        {children}
      </div>
    </div>,
    document.body,
  );
}

function SheetSection({ title, children }) {
  return (
    <div className="mt-5">
      <div className="text-[10.5px] tracking-[0.2em] uppercase text-white/55 mb-2">{title}</div>
      {children}
    </div>
  );
}
