import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { BookOpen, Trash2, Sparkles } from "lucide-react";

const MOOD_EMOJI = {
  felice: "😊", neutro: "😐", stressato: "😣", riflessivo: "🤔",
  energico: "⚡", stanco: "😴", grato: "🙏",
};

export default function JournalPage() {
  const [entries, setEntries] = useState([]);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const r = await api.get("/journal");
    setEntries(r.data);
  };
  useEffect(() => { load(); }, []);

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

  return (
    <div className="max-w-4xl">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-2xl bg-neutral-100 flex items-center justify-center"><BookOpen size={18} /></div>
        <div>
          <div className="kicker">· diario</div>
          <h2 className="text-2xl font-bold tracking-tight">Racconta la tua giornata</h2>
        </div>
      </div>

      <div className="rounded-2xl p-5 shadow-md" style={{ background: "#6EB7EC" }}>
        <div className="kicker text-white/85 mb-3">· oggi · {new Date().toLocaleDateString("it-IT", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</div>
        <Textarea
          data-testid="journal-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Come è andata oggi? Cosa hai fatto, com'era il tuo umore, cosa vuoi ricordare…"
          className="border-0 focus-visible:ring-0 bg-transparent text-base min-h-[160px] px-0 resize-none text-white placeholder:text-white/70"
        />
        <div className="flex justify-end pt-2 border-t border-white/25">
          <button data-testid="journal-save" onClick={save} disabled={saving || !text.trim()}
                  className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-white text-[#0A6BBF] font-medium disabled:opacity-50 hover:bg-white/95 text-sm">
            <Sparkles size={14} /> {saving ? "mAIPAL sta scrivendo…" : "Salva nel diario"}
          </button>
        </div>
      </div>

      <div className="mt-8 space-y-4">
        <div className="kicker">· voci precedenti · {entries.length}</div>
        {entries.length === 0 && <div className="text-neutral-500 text-sm">Nessuna voce ancora. Racconta com'è andata.</div>}
        {entries.map((e) => (
          <div key={e.id} className="p-5 rounded-2xl bg-white/70 border border-white/50 backdrop-blur-xl shadow-sm" data-testid="journal-entry">
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
              <button data-testid="journal-delete" onClick={() => del(e.id)} className="p-2 rounded-full text-neutral-400 hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
            </div>

            <div className="mt-4 prose-answer whitespace-pre-wrap text-[15px] text-neutral-800">{e.cleaned_text}</div>

            {(e.highlights || []).length > 0 && (
              <div className="mt-4 pt-4 border-t border-neutral-200">
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
