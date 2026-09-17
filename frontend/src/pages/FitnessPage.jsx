import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Dumbbell, Plus, Trash2, Pencil, ChevronUp, ChevronDown, Lock, Users as UsersIcon, AlertTriangle, Sparkles, ListChecks } from "lucide-react";
import { toast } from "sonner";

const DISCIPLINES = [
  { value: "danza", label: "Danza" },
  { value: "pilates", label: "Pilates" },
  { value: "altro", label: "Altro" },
];
const LEVELS = [
  { value: "base", label: "Base" },
  { value: "intermedio", label: "Intermedio" },
  { value: "avanzato", label: "Avanzato" },
];

export default function FitnessPage() {
  const [tab, setTab] = useState("esercizi");

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-2xl bg-[#403A3C] text-white flex items-center justify-center"><Dumbbell size={18} /></div>
        <div>
          <div className="kicker">· fitness</div>
          <h2 className="text-2xl font-bold tracking-tight">Danza & Pilates</h2>
        </div>
      </div>

      <div className="inline-flex items-center gap-1 p-1 rounded-full bg-white/10 mb-6" data-testid="fitness-tabs">
        <TabBtn active={tab === "esercizi"} onClick={() => setTab("esercizi")} label="Esercizi" testid="tab-esercizi" />
        <TabBtn active={tab === "lezioni"} onClick={() => setTab("lezioni")} label="Lezioni" testid="tab-lezioni" />
        <TabBtn active={tab === "clienti"} onClick={() => setTab("clienti")} label="Clienti" testid="tab-clienti" />
      </div>

      {tab === "esercizi" && <ExercisesTab />}
      {tab === "lezioni" && <LessonsTab />}
      {tab === "clienti" && <ClientsTab />}
    </div>
  );
}

function TabBtn({ active, onClick, label, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={`px-4 py-1.5 rounded-full text-xs font-medium transition-all ${active ? "bg-white/10 shadow-sm text-white" : "text-white/60 hover:text-white"}`}
    >
      {label}
    </button>
  );
}

function VisibilityToggle({ hasOrg, visibility, onChange }) {
  if (!hasOrg) return null;
  return (
    <div className="flex gap-2">
      <button type="button" onClick={() => onChange("private")} className={`flex-1 py-2 rounded-xl text-sm flex items-center justify-center gap-1.5 ${visibility === "private" ? "bg-[#CECAD0] text-[#403A3C]" : "bg-white/10 text-white/60"}`}>
        <Lock size={13} /> Privata
      </button>
      <button type="button" onClick={() => onChange("org")} className={`flex-1 py-2 rounded-xl text-sm flex items-center justify-center gap-1.5 ${visibility === "org" ? "bg-[#CECAD0] text-[#403A3C]" : "bg-white/10 text-white/60"}`}>
        <UsersIcon size={13} /> Condivisa col team
      </button>
    </div>
  );
}

/* ============ ESERCIZI ============ */
function ExercisesTab() {
  const { user } = useAuth();
  const [exercises, setExercises] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try {
      const r = await api.get("/exercises");
      setExercises(r.data);
    } catch { toast.error("Errore nel caricamento degli esercizi"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const del = (ex) => {
    toast(`Eliminare "${ex.name}"?`, {
      action: {
        label: "Elimina",
        onClick: async () => {
          try { await api.delete(`/exercises/${ex.id}`); await load(); toast.success("Esercizio eliminato"); }
          catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-white/60">Il database esercizi condiviso, da usare per costruire le lezioni.</div>
        <button data-testid="new-exercise" onClick={() => setEditing({})} className="pill-btn text-sm"><Plus size={14} /> Nuovo esercizio</button>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && exercises.length === 0 && <div className="text-center text-white/40 py-24 kicker">nessun esercizio ancora</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {exercises.map((ex) => (
          <div key={ex.id} className="card-soft p-4 rounded-2xl relative group">
            <div className="flex items-start justify-between gap-2 mb-1.5">
              <div className="font-semibold">{ex.name}</div>
              {ex.visibility === "org" ? <UsersIcon size={13} className="text-white/40 shrink-0" title="Condiviso col team" /> : <Lock size={13} className="text-white/25 shrink-0" title="Privato" />}
            </div>
            <div className="flex flex-wrap gap-1.5 text-[11px]">
              <span className="px-2 py-0.5 rounded-full bg-white/10 text-white/70 capitalize">{ex.discipline}</span>
              {ex.level && <span className="px-2 py-0.5 rounded-full bg-white/10 text-white/70 capitalize">{ex.level}</span>}
              {ex.duration_minutes ? <span className="px-2 py-0.5 rounded-full bg-white/10 text-white/70">{ex.duration_minutes} min</span> : null}
            </div>
            {ex.equipment && <div className="text-[11px] text-white/45 mt-2">Attrezzatura: {ex.equipment}</div>}
            {ex.notes && <div className="text-sm text-white/70 mt-2 line-clamp-3">{ex.notes}</div>}
            <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={() => setEditing(ex)} className="p-1.5 rounded-full text-white/50 hover:bg-white/10"><Pencil size={13} /></button>
              <button onClick={() => del(ex)} className="p-1.5 rounded-full text-white/50 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={13} /></button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <ExerciseDialog
          hasOrg={!!user?.org_id}
          exercise={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load(); }}
        />
      )}
    </div>
  );
}

function ExerciseDialog({ hasOrg, exercise, onClose, onSaved }) {
  const isNew = !exercise.id;
  const [name, setName] = useState(exercise.name || "");
  const [discipline, setDiscipline] = useState(exercise.discipline || "danza");
  const [category, setCategory] = useState(exercise.category || "");
  const [level, setLevel] = useState(exercise.level || "");
  const [equipment, setEquipment] = useState(exercise.equipment || "");
  const [duration, setDuration] = useState(exercise.duration_minutes || "");
  const [notes, setNotes] = useState(exercise.notes || "");
  const [visibility, setVisibility] = useState(exercise.visibility || "private");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim()) { toast.error("Dai un nome all'esercizio"); return; }
    setSaving(true);
    const payload = {
      name: name.trim(),
      discipline,
      category: category.trim(),
      level: level || null,
      equipment: equipment.trim(),
      duration_minutes: duration ? Number(duration) : null,
      notes: notes.trim(),
      visibility,
    };
    try {
      if (isNew) await api.post("/exercises", payload);
      else await api.patch(`/exercises/${exercise.id}`, payload);
      toast.success("Esercizio salvato");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="exercise-dialog">
        <DialogHeader><DialogTitle>{isNew ? "Nuovo esercizio" : "Modifica esercizio"}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <div className="kicker mb-1">nome</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Plié in prima posizione" className="h-11 rounded-xl bg-white/10" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="kicker mb-1">disciplina</div>
              <select value={discipline} onChange={(e) => setDiscipline(e.target.value)} className="w-full h-11 rounded-xl bg-white/10 px-3 text-white">
                {DISCIPLINES.map((d) => <option key={d.value} value={d.value} className="text-black">{d.label}</option>)}
              </select>
            </div>
            <div>
              <div className="kicker mb-1">livello</div>
              <select value={level} onChange={(e) => setLevel(e.target.value)} className="w-full h-11 rounded-xl bg-white/10 px-3 text-white">
                <option value="" className="text-black">—</option>
                {LEVELS.map((l) => <option key={l.value} value={l.value} className="text-black">{l.label}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="kicker mb-1">categoria</div>
              <Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="es. riscaldamento, core…" className="h-11 rounded-xl bg-white/10" />
            </div>
            <div>
              <div className="kicker mb-1">durata (min)</div>
              <Input type="number" value={duration} onChange={(e) => setDuration(e.target.value)} className="h-11 rounded-xl bg-white/10" />
            </div>
          </div>
          <div>
            <div className="kicker mb-1">attrezzatura</div>
            <Input value={equipment} onChange={(e) => setEquipment(e.target.value)} placeholder="es. tappetino, elastico…" className="h-11 rounded-xl bg-white/10" />
          </div>
          <div>
            <div className="kicker mb-1">note per l'insegnante</div>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="bg-white/10 rounded-xl min-h-[70px]" />
          </div>
          <VisibilityToggle hasOrg={hasOrg} visibility={visibility} onChange={setVisibility} />
        </div>
        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Salva"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ============ LEZIONI ============ */
function LessonsTab() {
  const { user } = useAuth();
  const [lessons, setLessons] = useState([]);
  const [exercises, setExercises] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [showGenerate, setShowGenerate] = useState(false);
  const [showGuidelines, setShowGuidelines] = useState(false);

  const load = async () => {
    try {
      const [l, ex] = await Promise.all([api.get("/lesson-templates"), api.get("/exercises")]);
      setLessons(l.data);
      setExercises(ex.data);
    } catch { toast.error("Errore nel caricamento delle lezioni"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const del = (ls) => {
    toast(`Eliminare la lezione "${ls.name}"?`, {
      action: {
        label: "Elimina",
        onClick: async () => {
          try { await api.delete(`/lesson-templates/${ls.id}`); await load(); toast.success("Lezione eliminata"); }
          catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const exerciseName = (id) => exercises.find((e) => e.id === id)?.name || "(esercizio rimosso)";

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="text-sm text-white/60">Componi lezioni riutilizzabili a partire dal database esercizi.</div>
        <div className="flex items-center gap-2">
          <button data-testid="lesson-guidelines-btn" onClick={() => setShowGuidelines(true)} className="p-2 rounded-full bg-white/10 hover:bg-white/15 text-white/70" title="Linee guida per la generazione AI">
            <ListChecks size={15} />
          </button>
          <button data-testid="generate-lesson-btn" onClick={() => setShowGenerate(true)} className="pill-btn text-sm bg-white/10 text-white">
            <Sparkles size={14} /> Genera con AI
          </button>
          <button
            data-testid="new-lesson"
            onClick={() => exercises.length === 0 ? toast.error("Aggiungi prima qualche esercizio") : setEditing({})}
            className="pill-btn text-sm"
          >
            <Plus size={14} /> Nuova lezione
          </button>
        </div>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && lessons.length === 0 && <div className="text-center text-white/40 py-24 kicker">nessuna lezione ancora</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {lessons.map((ls) => (
          <div key={ls.id} className="card-soft p-4 rounded-2xl relative group">
            <div className="flex items-start justify-between gap-2 mb-1.5">
              <div className="font-semibold">{ls.name}</div>
              {ls.visibility === "org" ? <UsersIcon size={13} className="text-white/40 shrink-0" title="Condivisa col team" /> : <Lock size={13} className="text-white/25 shrink-0" title="Privata" />}
            </div>
            <div className="flex flex-wrap gap-1.5 text-[11px] mb-2">
              <span className="px-2 py-0.5 rounded-full bg-white/10 text-white/70 capitalize">{ls.discipline}</span>
              {ls.level && <span className="px-2 py-0.5 rounded-full bg-white/10 text-white/70 capitalize">{ls.level}</span>}
              <span className="px-2 py-0.5 rounded-full bg-white/10 text-white/70">{(ls.exercises || []).length} esercizi</span>
            </div>
            <ol className="text-sm text-white/70 space-y-0.5 list-decimal list-inside">
              {(ls.exercises || []).slice(0, 4).map((it, i) => <li key={i} className="truncate">{exerciseName(it.exercise_id)}</li>)}
              {(ls.exercises || []).length > 4 && <li className="text-white/40 list-none">+{(ls.exercises || []).length - 4} altri…</li>}
            </ol>
            <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={() => setEditing(ls)} className="p-1.5 rounded-full text-white/50 hover:bg-white/10"><Pencil size={13} /></button>
              <button onClick={() => del(ls)} className="p-1.5 rounded-full text-white/50 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={13} /></button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <LessonDialog
          hasOrg={!!user?.org_id}
          lesson={editing}
          allExercises={exercises}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load(); }}
        />
      )}

      {showGenerate && (
        <GenerateLessonDialog
          onClose={() => setShowGenerate(false)}
          onGenerated={async () => { setShowGenerate(false); await load(); }}
        />
      )}

      {showGuidelines && <GuidelinesDialog onClose={() => setShowGuidelines(false)} />}
    </div>
  );
}

function GenerateLessonDialog({ onClose, onGenerated }) {
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);

  const generate = async () => {
    if (!prompt.trim()) { toast.error("Descrivi la lezione che vuoi creare"); return; }
    setGenerating(true);
    try {
      const r = await api.post("/fitness/generate-lesson", { prompt: prompt.trim() });
      const n = r.data?.new_exercises_created || 0;
      toast.success(
        n > 0
          ? `Lezione "${r.data.lesson.name}" creata · ${n} nuov${n !== 1 ? "i" : "o"} esercizi${n !== 1 ? "" : "o"} aggiunt${n !== 1 ? "i" : "o"} al database`
          : `Lezione "${r.data.lesson.name}" creata`
      );
      onGenerated();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore nella generazione"); }
    finally { setGenerating(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)]" data-testid="generate-lesson-dialog">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><Sparkles size={16} /> Genera lezione con AI</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="text-sm text-white/60">
            Descrivi la lezione che vuoi: disciplina, numero di persone, durata, livello, obiettivo. L'AI componitrice
            userà gli esercizi già nel database e ne proporrà di nuovi solo se necessario, seguendo le linee guida
            dello studio.
          </div>
          <Textarea
            data-testid="generate-lesson-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder='es. "Fai una lezione di funzionale per 10 persone da 40 minuti livello medio, focus gambe"'
            className="bg-white/10 rounded-xl min-h-[100px]"
          />
        </div>
        <div className="flex justify-end mt-4">
          <button data-testid="generate-lesson-submit" onClick={generate} disabled={generating} className="pill-btn">
            {generating ? "Genero…" : "Genera"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const DEFAULT_GUIDELINES = "Metti sempre 5 minuti di stretching all'inizio e alla fine di ogni lezione.";

function GuidelinesDialog({ onClose }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/fitness/guidelines")
      .then((r) => setText(r.data?.text || DEFAULT_GUIDELINES))
      .catch(() => setText(DEFAULT_GUIDELINES))
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/fitness/guidelines", { text });
      toast.success("Linee guida salvate");
      onClose();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)]" data-testid="guidelines-dialog">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><ListChecks size={16} /> Linee guida per le lezioni</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="text-sm text-white/60">
            Regole che l'AI deve rispettare sempre quando genera una lezione (una per riga). Valgono per tutto il team.
          </div>
          {loading ? (
            <div className="text-sm text-white/40">caricamento…</div>
          ) : (
            <Textarea
              data-testid="guidelines-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="bg-white/10 rounded-xl min-h-[140px]"
            />
          )}
        </div>
        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving || loading} className="pill-btn">{saving ? "…" : "Salva"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function LessonDialog({ hasOrg, lesson, allExercises, onClose, onSaved }) {
  const isNew = !lesson.id;
  const [name, setName] = useState(lesson.name || "");
  const [discipline, setDiscipline] = useState(lesson.discipline || "danza");
  const [level, setLevel] = useState(lesson.level || "");
  const [notes, setNotes] = useState(lesson.notes || "");
  const [visibility, setVisibility] = useState(lesson.visibility || "private");
  const [items, setItems] = useState(lesson.exercises || []); // [{exercise_id, notes}]
  const [pickerId, setPickerId] = useState("");
  const [saving, setSaving] = useState(false);

  const exerciseById = (id) => allExercises.find((e) => e.id === id);

  const addExercise = () => {
    if (!pickerId) return;
    setItems((its) => [...its, { exercise_id: pickerId, notes: "" }]);
    setPickerId("");
  };
  const removeItem = (i) => setItems((its) => its.filter((_, idx) => idx !== i));
  const moveItem = (i, dir) => setItems((its) => {
    const next = [...its];
    const j = i + dir;
    if (j < 0 || j >= next.length) return its;
    [next[i], next[j]] = [next[j], next[i]];
    return next;
  });
  const setItemNote = (i, note) => setItems((its) => its.map((it, idx) => idx === i ? { ...it, notes: note } : it));

  const save = async () => {
    if (!name.trim()) { toast.error("Dai un nome alla lezione"); return; }
    setSaving(true);
    const payload = { name: name.trim(), discipline, level: level || null, notes: notes.trim(), visibility, exercises: items };
    try {
      if (isNew) await api.post("/lesson-templates", payload);
      else await api.patch(`/lesson-templates/${lesson.id}`, payload);
      toast.success("Lezione salvata");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-xl bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="lesson-dialog">
        <DialogHeader><DialogTitle>{isNew ? "Nuova lezione" : "Modifica lezione"}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <div className="kicker mb-1">nome</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Pilates Intermedio" className="h-11 rounded-xl bg-white/10" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="kicker mb-1">disciplina</div>
              <select value={discipline} onChange={(e) => setDiscipline(e.target.value)} className="w-full h-11 rounded-xl bg-white/10 px-3 text-white">
                {DISCIPLINES.map((d) => <option key={d.value} value={d.value} className="text-black">{d.label}</option>)}
              </select>
            </div>
            <div>
              <div className="kicker mb-1">livello</div>
              <select value={level} onChange={(e) => setLevel(e.target.value)} className="w-full h-11 rounded-xl bg-white/10 px-3 text-white">
                <option value="" className="text-black">—</option>
                {LEVELS.map((l) => <option key={l.value} value={l.value} className="text-black">{l.label}</option>)}
              </select>
            </div>
          </div>

          <div>
            <div className="kicker mb-2">sequenza esercizi ({items.length})</div>
            <div className="space-y-2">
              {items.map((it, i) => {
                const ex = exerciseById(it.exercise_id);
                return (
                  <div key={i} className="bg-white/5 rounded-xl p-2.5">
                    <div className="flex items-center gap-2">
                      <div className="flex flex-col">
                        <button type="button" onClick={() => moveItem(i, -1)} disabled={i === 0} className="text-white/40 hover:text-white disabled:opacity-20"><ChevronUp size={13} /></button>
                        <button type="button" onClick={() => moveItem(i, 1)} disabled={i === items.length - 1} className="text-white/40 hover:text-white disabled:opacity-20"><ChevronDown size={13} /></button>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{i + 1}. {ex?.name || "(esercizio rimosso)"}</div>
                        {ex && <div className="text-[10px] text-white/40 capitalize">{ex.discipline}{ex.level ? ` · ${ex.level}` : ""}</div>}
                      </div>
                      <button type="button" onClick={() => removeItem(i)} className="p-1 rounded-full text-white/40 hover:bg-red-500/10 hover:text-red-400 shrink-0"><Trash2 size={13} /></button>
                    </div>
                    <Input
                      value={it.notes}
                      onChange={(e) => setItemNote(i, e.target.value)}
                      placeholder="Nota per questo esercizio in questa lezione (opzionale)"
                      className="h-8 rounded-lg bg-white/10 text-xs mt-2"
                    />
                  </div>
                );
              })}
              {items.length === 0 && <div className="text-xs text-white/40">Nessun esercizio ancora nella sequenza</div>}
            </div>
            <div className="flex gap-2 mt-2">
              <select value={pickerId} onChange={(e) => setPickerId(e.target.value)} className="flex-1 h-9 rounded-lg bg-white/10 text-sm px-2 text-white">
                <option value="" className="text-black">aggiungi esercizio…</option>
                {allExercises.map((ex) => <option key={ex.id} value={ex.id} className="text-black">{ex.name}</option>)}
              </select>
              <button type="button" onClick={addExercise} className="p-2 rounded-lg bg-white/10 hover:bg-white/15 text-white/80"><Plus size={14} /></button>
            </div>
          </div>

          <div>
            <div className="kicker mb-1">note generali</div>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="bg-white/10 rounded-xl min-h-[60px]" />
          </div>
          <VisibilityToggle hasOrg={hasOrg} visibility={visibility} onChange={setVisibility} />
        </div>
        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Salva lezione"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ============ CLIENTI ============ */
const CERT_WARNING_DAYS = 30;

function certStatus(dateStr) {
  if (!dateStr) return null;
  const days = Math.floor((new Date(dateStr).getTime() - Date.now()) / (24 * 3600 * 1000));
  if (days < 0) return "expired";
  if (days <= CERT_WARNING_DAYS) return "soon";
  return "ok";
}

function ClientsTab() {
  const { user } = useAuth();
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try {
      const r = await api.get("/clients");
      setClients(r.data);
    } catch { toast.error("Errore nel caricamento dei clienti"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const del = (c) => {
    toast(`Eliminare "${c.name}"?`, {
      action: {
        label: "Elimina",
        onClick: async () => {
          try { await api.delete(`/clients/${c.id}`); await load(); toast.success("Cliente eliminato"); }
          catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const expiringCount = clients.filter((c) => ["expired", "soon"].includes(certStatus(c.medical_certificate_expiry))).length;

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="text-sm text-white/60">
          Anagrafica iscritti.
          {expiringCount > 0 && (
            <span className="ml-2 text-amber-400 inline-flex items-center gap-1">
              <AlertTriangle size={12} /> {expiringCount} certificat{expiringCount !== 1 ? "i" : "o"} medic{expiringCount !== 1 ? "i" : "o"} scadut{expiringCount !== 1 ? "i" : "o"} o in scadenza
            </span>
          )}
        </div>
        <button data-testid="new-client" onClick={() => setEditing({})} className="pill-btn text-sm"><Plus size={14} /> Nuovo cliente</button>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && clients.length === 0 && <div className="text-center text-white/40 py-24 kicker">nessun cliente ancora</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {clients.map((c) => {
          const status = certStatus(c.medical_certificate_expiry);
          return (
            <div key={c.id} className="card-soft p-4 rounded-2xl relative group">
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <div className="font-semibold">{c.name}</div>
                {c.visibility === "org" ? <UsersIcon size={13} className="text-white/40 shrink-0" title="Condiviso col team" /> : <Lock size={13} className="text-white/25 shrink-0" title="Privato" />}
              </div>
              {c.subscription_type && <div className="text-[11px] text-white/50">{c.subscription_type}</div>}
              {c.phone && <div className="text-[11px] text-white/45 mt-1">{c.phone}</div>}
              {c.medical_certificate_expiry && (
                <div
                  className={`inline-flex items-center gap-1 text-[11px] mt-2 px-2 py-0.5 rounded-full ${
                    status === "expired" ? "bg-red-500/20 text-red-400" : status === "soon" ? "bg-amber-500/20 text-amber-400" : "bg-white/10 text-white/60"
                  }`}
                >
                  {status !== "ok" && <AlertTriangle size={11} />}
                  Certificato: {new Date(c.medical_certificate_expiry).toLocaleDateString("it-IT")}
                </div>
              )}
              {c.notes && <div className="text-sm text-white/70 mt-2 line-clamp-2">{c.notes}</div>}
              <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => setEditing(c)} className="p-1.5 rounded-full text-white/50 hover:bg-white/10"><Pencil size={13} /></button>
                <button onClick={() => del(c)} className="p-1.5 rounded-full text-white/50 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={13} /></button>
              </div>
            </div>
          );
        })}
      </div>

      {editing && (
        <ClientDialog
          hasOrg={!!user?.org_id}
          client={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load(); }}
        />
      )}
    </div>
  );
}

function ClientDialog({ hasOrg, client, onClose, onSaved }) {
  const isNew = !client.id;
  const [name, setName] = useState(client.name || "");
  const [phone, setPhone] = useState(client.phone || "");
  const [email, setEmail] = useState(client.email || "");
  const [enrollmentDate, setEnrollmentDate] = useState(client.enrollment_date || "");
  const [subscriptionType, setSubscriptionType] = useState(client.subscription_type || "");
  const [certExpiry, setCertExpiry] = useState(client.medical_certificate_expiry || "");
  const [notes, setNotes] = useState(client.notes || "");
  const [visibility, setVisibility] = useState(client.visibility || "private");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim()) { toast.error("Dai un nome al cliente"); return; }
    setSaving(true);
    const payload = {
      name: name.trim(),
      phone: phone.trim(),
      email: email.trim(),
      enrollment_date: enrollmentDate || null,
      subscription_type: subscriptionType.trim(),
      medical_certificate_expiry: certExpiry || null,
      notes: notes.trim(),
      visibility,
    };
    try {
      if (isNew) await api.post("/clients", payload);
      else await api.patch(`/clients/${client.id}`, payload);
      toast.success("Cliente salvato");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="client-dialog">
        <DialogHeader><DialogTitle>{isNew ? "Nuovo cliente" : "Modifica cliente"}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <div className="kicker mb-1">nome</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} className="h-11 rounded-xl bg-white/10" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="kicker mb-1">telefono</div>
              <Input value={phone} onChange={(e) => setPhone(e.target.value)} className="h-11 rounded-xl bg-white/10" />
            </div>
            <div>
              <div className="kicker mb-1">email</div>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="h-11 rounded-xl bg-white/10" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="kicker mb-1">data iscrizione</div>
              <Input type="date" value={enrollmentDate} onChange={(e) => setEnrollmentDate(e.target.value)} className="h-11 rounded-xl bg-white/10" />
            </div>
            <div>
              <div className="kicker mb-1">abbonamento</div>
              <Input value={subscriptionType} onChange={(e) => setSubscriptionType(e.target.value)} placeholder="es. mensile, 10 lezioni…" className="h-11 rounded-xl bg-white/10" />
            </div>
          </div>
          <div>
            <div className="kicker mb-1">scadenza certificato medico</div>
            <Input type="date" value={certExpiry} onChange={(e) => setCertExpiry(e.target.value)} className="h-11 rounded-xl bg-white/10" />
          </div>
          <div>
            <div className="kicker mb-1">note (infortuni, limitazioni…)</div>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="bg-white/10 rounded-xl min-h-[70px]" />
          </div>
          <VisibilityToggle hasOrg={hasOrg} visibility={visibility} onChange={setVisibility} />
        </div>
        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Salva"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
