import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { X, LifeBuoy, ChevronRight, ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";

/* What the "i" next to a section's title opens: that page's part of the Help guide
   (backend/help/mAIPAL-help.md, filtered by the user's vertical) in a frosted sheet, the other
   topics below it, and "Chiedi a Help", which opens the chat in Help mode knowing the page. */
export default function HelpSheet({ path, title, onClose }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);       // {sections, index}
  const [topic, setTopic] = useState(null);     // another topic opened from the list
  const [error, setError] = useState(false);

  useEffect(() => {
    api.get("/help/sections", { params: { path } }).then((r) => setData(r.data)).catch(() => setError(true));
  }, [path]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const openTopic = async (id) => {
    try { setTopic((await api.get(`/help/sections/${id}`)).data); } catch { setError(true); }
  };
  const askHelp = () => {
    onClose();
    navigate("/dashboard/chat", { state: { action: "help", page: path, nonce: Date.now() } });
  };

  const shown = topic ? [topic] : (data?.sections || []);
  const shownIds = new Set(shown.map((s) => s.id));
  const others = (data?.index || []).filter((s) => !shownIds.has(s.id));

  return createPortal(
    <div className="fixed inset-0 z-[70]" data-testid="help-sheet">
      <div className="absolute inset-0 bg-[#1A0820]/25 animate-in fade-in duration-200" onClick={onClose} />
      <div className="glass-panel glass-sheet absolute left-3 right-3 bottom-[calc(env(safe-area-inset-bottom,0px)+12px)] md:left-1/2 md:right-auto md:w-[560px] md:-translate-x-1/2 md:bottom-8 max-h-[84vh] overflow-y-auto no-scrollbar px-5 pt-3 pb-6 animate-in slide-in-from-bottom duration-300">
        <div className="w-10 h-1 rounded-full bg-white/35 mx-auto mb-4" />
        <button onClick={onClose} aria-label="Chiudi" data-testid="help-sheet-close" className="absolute top-4 right-4 p-1.5 rounded-full text-white/70 hover:bg-white/10"><X size={18} /></button>

        {topic && (
          <button type="button" onClick={() => setTopic(null)} data-testid="help-topic-back" className="flex items-center gap-1.5 text-xs text-white/60 mb-2">
            <ArrowLeft size={13} /> {title || "Indietro"}
          </button>
        )}
        {!data && !error && <div className="kicker text-white/50 py-8 text-center">caricamento…</div>}
        {error && <div className="text-sm text-white/70 py-6">La guida non è raggiungibile in questo momento. Riprova tra poco.</div>}
        {data && shown.length === 0 && !topic && (
          <div className="text-sm text-white/70 pr-8">Per questa pagina non c'è ancora una spiegazione: chiedi pure a Help.</div>
        )}
        {shown.map((s, i) => (
          <div key={s.id} className={i ? "mt-6 pt-5 border-t border-white/10" : ""} data-testid="help-section">
            <div className="text-lg font-semibold text-white pr-8">{s.title}</div>
            <div className="mt-2"><HelpText text={s.body} /></div>
          </div>
        ))}

        <button type="button" onClick={askHelp} data-testid="help-ask"
          className="mt-6 w-full flex items-center justify-center gap-2 py-3 rounded-full bg-white/[0.22] border border-white/30 text-white text-[15px] font-medium active:scale-[0.98]">
          <LifeBuoy size={17} /> Chiedi a Help
        </button>

        {data && others.length > 0 && (
          <div className="mt-6">
            <div className="text-[10.5px] tracking-[0.2em] uppercase text-white/55 mb-2">altri argomenti</div>
            <div>
              {others.map((s) => (
                <button key={s.id} type="button" onClick={() => openTopic(s.id)} data-testid={`help-topic-${s.id}`}
                  className="w-full flex items-center gap-2 py-2.5 text-left text-[14px] text-white/85 border-t border-white/[0.08] first:border-t-0">
                  <span className="flex-1">{s.title}</span>
                  <ChevronRight size={15} className="text-white/45" />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

// The guide's light markdown: paragraphs, "- " and "1. " lists, **bold** and `code`.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i} className="px-1 rounded bg-white/15 text-[0.92em]">{part.slice(1, -1)}</code>;
    return part;
  });
}

export function HelpText({ text }) {
  const blocks = [];
  let list = null;
  const flush = () => { if (list) { blocks.push(list); list = null; } };
  (text || "").split("\n").forEach((raw) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^(\s*)- (.*)$/);
    const num = line.match(/^(\s*)\d+\. (.*)$/);
    if (bullet || num) {
      const kind = bullet ? "ul" : "ol";
      const indent = (bullet || num)[1].length > 0;
      if (!list || list.kind !== kind) { flush(); list = { kind, items: [] }; }
      list.items.push({ text: (bullet || num)[2], indent });
    } else if (!line.trim()) {
      flush();
    } else {
      flush();
      blocks.push({ kind: "p", text: line });
    }
  });
  flush();
  return (
    <div className="space-y-2.5 text-[13.5px] leading-relaxed text-white/85 font-light">
      {blocks.map((b, i) => (b.kind === "p" ? <p key={i}>{inline(b.text)}</p> : (
        React.createElement(b.kind, { key: i, className: `space-y-1 pl-5 ${b.kind === "ul" ? "list-disc" : "list-decimal"} marker:text-white/45` },
          b.items.map((it, j) => <li key={j} className={it.indent ? "ml-4" : ""}>{inline(it.text)}</li>))
      )))}
    </div>
  );
}
