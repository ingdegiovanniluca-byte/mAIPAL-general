import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import GlassBottomSheet from "@/components/GlassBottomSheet";
import { Dumbbell, Plus, Minus, Trash2, Pencil, Lock, Users as UsersIcon, AlertTriangle, Sparkles, ListChecks, Search, Clock, X, Loader2, ExternalLink, Star } from "lucide-react";
import { toast } from "sonner";

/* Fitness: the lessons built by the agent from the rules of their type + the request, the
   exercises' catalog (the vertical's base set + the studio's own), the studio's equipment
   (the lessons only use what is enough for everybody) and the clients. */
const LEVELS = [
  { value: "basso", label: "Basso" },
  { value: "medio", label: "Medio" },
  { value: "alto", label: "Alto" },
];
const ROLES = [
  { value: "riscaldamento", label: "Riscaldamento" },
  { value: "esercizio", label: "Esercizio" },
  { value: "stretching", label: "Stretching" },
];
const PHASE_KINDS = [
  { value: "stretching", label: "Stretching" },
  { value: "riscaldamento", label: "Riscaldamento" },
];
const MODES = [
  { value: "misto", label: "Misto" },
  { value: "tempo", label: "A tempo" },
  { value: "ripetizioni", label: "A ripetizioni" },
];
const PHASES = [
  { key: "inizio", label: "Inizio" },
  { key: "centrale", label: "Parte centrale" },
  { key: "fine", label: "Fine" },
];
const LEGACY_LEVEL = { base: "basso", intermedio: "medio", avanzato: "alto" };
const field = "h-10 w-full min-w-0 rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none";
const sheetCls = "max-h-[90vh] md:left-1/2 md:right-auto md:w-[560px] md:-translate-x-1/2 md:bottom-8";
const errMsg = (e, fallback = "Errore") => e?.response?.data?.detail || fallback;
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
const exLevel = (ex) => ex.level ? (LEGACY_LEVEL[ex.level] || ex.level) : "";
const exBody = (ex) => ex.body_part || ex.category || "";
const mins = (sec) => Math.round((sec || 0) / 60);

export default function FitnessPage() {
  const [tab, setTab] = useState("lezioni");

  return (
    <div>
      <div className="flex items-center gap-2.5 mb-6">
        <Dumbbell size={24} strokeWidth={1.8} className="text-white shrink-0" />
        <h2 className="text-2xl font-bold tracking-tight">Lezioni & allenamenti</h2>
      </div>

      <div className="flex items-center gap-1 p-1 rounded-full bg-white/10 mb-6 w-fit max-w-full overflow-x-auto" data-testid="fitness-tabs">
        <TabBtn active={tab === "lezioni"} onClick={() => setTab("lezioni")} label="Lezioni" testid="tab-lezioni" />
        <TabBtn active={tab === "esercizi"} onClick={() => setTab("esercizi")} label="Esercizi" testid="tab-esercizi" />
        <TabBtn active={tab === "attrezzi"} onClick={() => setTab("attrezzi")} label="Attrezzi" testid="tab-attrezzi" />
        <TabBtn active={tab === "clienti"} onClick={() => setTab("clienti")} label="Clienti" testid="tab-clienti" />
      </div>

      {tab === "lezioni" && <LessonsTab />}
      {tab === "esercizi" && <ExercisesTab />}
      {tab === "attrezzi" && <EquipmentTab />}
      {tab === "clienti" && <ClientsTab />}
    </div>
  );
}

function TabBtn({ active, onClick, label, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={`shrink-0 px-4 py-1.5 rounded-full text-xs font-medium transition-all ${active ? "bg-white/10 shadow-sm text-white" : "text-white/60 hover:text-white"}`}
    >
      {label}
    </button>
  );
}

function Chip({ on, onClick, children, testid }) {
  return (
    <button type="button" onClick={onClick} data-testid={testid}
      className={`shrink-0 whitespace-nowrap inline-flex items-center px-2.5 py-1 rounded-full text-xs transition-colors ${on ? "lg-bubble text-white font-medium" : "bg-white/10 text-white/75 hover:bg-white/15"}`}>
      {children}
    </button>
  );
}

function ChipRow({ options, value, onChange, testid }) {
  return (
    <div className="flex flex-wrap gap-1.5" data-testid={testid}>
      {options.map((o) => <Chip key={o.value} on={value === o.value} onClick={() => onChange(o.value)} testid={testid && `${testid}-${o.value}`}>{o.label}</Chip>)}
    </div>
  );
}

function RoundBtn({ icon: Icon, label, onClick, testid }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick} title={label} aria-label={label}
      className="lg-glass shrink-0 rounded-full h-11 w-11 flex items-center justify-center text-white active:scale-95 transition-transform">
      <Icon size={22} strokeWidth={1.7} />
    </button>
  );
}

function Label({ children }) {
  return <div className="text-[10px] uppercase tracking-widest text-white/50 mb-1.5">{children}</div>;
}

function Tag({ children }) {
  return <span className="px-2 py-0.5 rounded-full bg-white/10 text-white/70 text-[11px]">{children}</span>;
}

function NumField({ value, onChange, placeholder, testid, min = 0 }) {
  return (
    <input type="number" inputMode="numeric" min={min} value={value ?? ""} placeholder={placeholder} data-testid={testid}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} className={field} />
  );
}

function confirmToast(text, label, run) {
  toast(text, {
    action: { label, onClick: run },
    cancel: { label: "Annulla", onClick: () => {} },
    duration: 6000,
  });
}

/* ============ LEZIONI ============ */
function blockDose(b) {
  return b.mode === "ripetizioni" ? `${b.sets} × ${b.reps} rip.` : `${b.sets} × ${b.seconds}"`;
}

function LessonsTab() {
  const location = useLocation();
  const navigate = useNavigate();
  const [lessons, setLessons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [open, setOpen] = useState(null);
  const [onlyFav, setOnlyFav] = useState(false);

  const load = async () => {
    try {
      const list = (await api.get("/lesson-templates")).data;
      setLessons(list);
      return list;
    } catch { toast.error("Errore nel caricamento delle lezioni"); return []; }
    finally { setLoading(false); }
  };
  useEffect(() => {
    // from the chat's "Apri la lezione": that lesson opened
    const wanted = location.state?.lesson;
    load().then((list) => {
      const l = wanted && list.find((x) => x.id === wanted);
      if (l) { setOpen(l); navigate(location.pathname, { replace: true, state: {} }); }
    });
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // favourites first, then the newest
  const sorted = useMemo(() => [...lessons]
    .filter((l) => !onlyFav || l.favorite)
    .sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0) || (b.created_at || "").localeCompare(a.created_at || "")), [lessons, onlyFav]);
  const favCount = lessons.filter((l) => l.favorite).length;

  const toggleFav = async (ls) => {
    const favorite = !ls.favorite;
    setLessons((xs) => xs.map((x) => (x.id === ls.id ? { ...x, favorite } : x)));
    try { await api.patch(`/lesson-templates/${ls.id}`, { favorite }); }
    catch (e) { toast.error(errMsg(e)); load(); }
  };
  const del = (ls) => confirmToast(`Eliminare la lezione "${ls.name}"?`, "Elimina", async () => {
    try { await api.delete(`/lesson-templates/${ls.id}`); toast.success("Lezione eliminata"); load(); }
    catch (e) { toast.error(errMsg(e)); }
  });

  return (
    <div>
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <button data-testid="generate-lesson-btn" onClick={() => setCreating(true)} className="pill-btn text-sm">
          <Sparkles size={14} /> Crea lezione
        </button>
        <button data-testid="lesson-rules-btn" onClick={() => setShowRules(true)} className="pill-btn text-sm bg-white/10 text-white">
          <ListChecks size={14} /> Regole
        </button>
        {favCount > 0 && (
          <Chip on={onlyFav} onClick={() => setOnlyFav((v) => !v)} testid="lesson-only-fav">
            <Star size={12} className="mr-1" fill={onlyFav ? "currentColor" : "none"} /> Preferite
          </Chip>
        )}
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && lessons.length === 0 && <div className="text-center text-white/40 py-24 kicker">nessuna lezione ancora</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {sorted.map((ls) => (
          <div key={ls.id} role="button" tabIndex={0} onClick={() => setOpen(ls)} onKeyDown={(e) => e.key === "Enter" && setOpen(ls)}
            data-testid="lesson-card" className="card-soft p-4 rounded-2xl text-left min-w-0 cursor-pointer">
            <div className="flex items-start gap-1 mb-1.5">
              <div className="font-semibold break-words min-w-0 flex-1 pt-1">{ls.name}</div>
              <button type="button" onClick={(e) => { e.stopPropagation(); toggleFav(ls); }} data-testid="lesson-fav"
                aria-label={ls.favorite ? "Togli dalle preferite" : "Aggiungi alle preferite"} aria-pressed={!!ls.favorite}
                className={`p-1.5 rounded-full shrink-0 ${ls.favorite ? "text-amber-300" : "text-white/45 hover:text-white"}`}>
                <Star size={16} fill={ls.favorite ? "currentColor" : "none"} />
              </button>
              <button type="button" onClick={(e) => { e.stopPropagation(); del(ls); }} data-testid="lesson-trash" aria-label="Elimina la lezione"
                className="p-1.5 -mr-1.5 rounded-full shrink-0 text-white/45 hover:text-white">
                <Trash2 size={16} />
              </button>
            </div>
            {ls.kind === "v2" ? (
              <>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {ls.type_name && <Tag>{ls.type_name}</Tag>}
                  <Tag>{mins(ls.total_sec)} min</Tag>
                  {ls.level && <Tag>{cap(ls.level)}</Tag>}
                  <Tag>{ls.participants} pers.</Tag>
                  {(ls.body_parts || []).map((p) => <Tag key={p}>{cap(p)}</Tag>)}
                </div>
                <div className="text-sm text-white/65 line-clamp-2">{(ls.blocks || []).filter((b) => b.phase === "centrale").map((b) => b.name).join(" · ")}</div>
              </>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {ls.level && <Tag>{cap(LEGACY_LEVEL[ls.level] || ls.level)}</Tag>}
                <Tag>{(ls.exercises || []).length} esercizi</Tag>
              </div>
            )}
          </div>
        ))}
      </div>
      {!loading && onlyFav && sorted.length === 0 && <div className="text-center text-white/40 py-16 kicker">nessuna lezione preferita</div>}

      {creating && <CreateLessonSheet onClose={() => setCreating(false)} onCreated={async (l) => { setCreating(false); await load(); setOpen(l); }} />}
      {showRules && <RulesSheet onClose={() => setShowRules(false)} />}
      {open && <LessonSheet lesson={open} onClose={() => setOpen(null)} onChanged={load} />}
    </div>
  );
}

function CreateLessonSheet({ onClose, onCreated }) {
  const [types, setTypes] = useState(null);
  const [typeId, setTypeId] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get("/fitness/lesson-types").then((r) => { setTypes(r.data); setTypeId(r.data[0]?.id || null); }).catch(() => setTypes([]));
  }, []);
  const t = (types || []).find((x) => x.id === typeId);

  const generate = async () => {
    if (!prompt.trim()) { toast.error("Descrivi la lezione che vuoi creare"); return; }
    setBusy(true);
    try {
      const r = await api.post("/fitness/generate-lesson", { prompt, type_id: typeId });
      toast.success("Lezione creata");
      onCreated(r.data.lesson);
    } catch (e) { toast.error(errMsg(e, "Non sono riuscito a creare la lezione")); }
    finally { setBusy(false); }
  };

  return (
    <GlassBottomSheet onClose={onClose} testid="generate-lesson-sheet" className={sheetCls}>
      <div className="text-lg font-semibold text-white mb-4 flex items-center gap-2"><Sparkles size={16} /> Crea lezione</div>
      {types === null ? <div className="kicker">caricamento…</div> : (
        <div className="space-y-4">
          {types.length > 0 && (
            <div>
              <Label>tipo di lezione</Label>
              <ChipRow options={types.map((x) => ({ value: x.id, label: x.name }))} value={typeId} onChange={setTypeId} testid="lesson-type-pick" />
              {t && (
                <div className="text-xs text-white/55 mt-2" data-testid="lesson-type-summary">
                  {t.duration_min} min · inizio {t.start_min} min di {t.start_kind} · fine {t.end_min} min di {t.end_kind} · pausa {t.rest_sec}" · se non lo dici: {t.default_participants} persone, livello {t.default_level || "medio"}
                </div>
              )}
            </div>
          )}
          <div>
            <Label>la richiesta</Label>
            <Textarea data-testid="generate-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} autoFocus
              placeholder="Es. lezione per 10 persone, livello medio, allenamento gambe"
              className="bg-white/10 rounded-xl min-h-[110px] text-white" />
            <div className="text-xs text-white/45 mt-1.5">Puoi dire partecipanti, livello, parti del corpo, durata, “a tempo” o “a ripetizioni”: il resto lo prendono le regole del tipo.</div>
          </div>
        </div>
      )}
      <div className="flex justify-end gap-2 mt-5">
        <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
        <button onClick={generate} disabled={busy || types === null} data-testid="generate-submit" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50 inline-flex items-center gap-1.5">
          {busy ? <><Loader2 size={14} className="animate-spin" /> Creo…</> : "Crea"}
        </button>
      </div>
    </GlassBottomSheet>
  );
}

function LessonSheet({ lesson, onClose, onChanged }) {
  const [ls, setLs] = useState(lesson);
  const [name, setName] = useState(lesson.name || "");
  const [blocks, setBlocks] = useState(lesson.blocks || []);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exercises, setExercises] = useState([]);
  const [adding, setAdding] = useState(null);   // phase
  const v2 = ls.kind === "v2";
  useEffect(() => { api.get("/exercises").then((r) => setExercises(r.data)).catch(() => {}); }, []);
  const byId = useMemo(() => Object.fromEntries(exercises.map((e) => [e.id, e])), [exercises]);

  const change = (fn) => { setBlocks(fn); setDirty(true); };
  const setSets = (i, d) => change((bs) => bs.map((b, j) => (j === i ? { ...b, sets: Math.max(1, b.sets + d) } : b)));
  const remove = (i) => change((bs) => bs.filter((_, j) => j !== i));
  const add = (ex) => {
    const timed = ex.timed?.allowed !== false;
    const b = { exercise_id: ex.id, name: ex.name, phase: adding, mode: timed ? "tempo" : "ripetizioni", sets: ex.timed?.min_sets || ex.reps?.min_sets || 1,
      seconds: ex.timed?.max_sec || 40, reps: ex.reps?.min_reps || 10, equipment: ex.equipment || "" };
    change((bs) => {
      const at = bs.map((x) => x.phase).lastIndexOf(adding);
      const order = PHASES.findIndex((p) => p.key === adding);
      const pos = at >= 0 ? at + 1 : bs.filter((x) => PHASES.findIndex((p) => p.key === x.phase) < order).length;
      return [...bs.slice(0, pos), b, ...bs.slice(pos)];
    });
    setAdding(null);
  };

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.patch(`/lesson-templates/${ls.id}`, v2 ? { name, blocks } : { name });
      setLs(r.data); setBlocks(r.data.blocks || []); setDirty(false);
      toast.success("Lezione salvata");
      onChanged();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const del = () => confirmToast(`Eliminare la lezione "${ls.name}"?`, "Elimina", async () => {
    try { await api.delete(`/lesson-templates/${ls.id}`); toast.success("Lezione eliminata"); onChanged(); onClose(); }
    catch (e) { toast.error(errMsg(e)); }
  });

  const need = Object.entries(ls.equipment_needed || {});
  return (
    <GlassBottomSheet onClose={onClose} testid="lesson-sheet" className={sheetCls}>
      <input value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} data-testid="lesson-name"
        className="w-full bg-transparent text-lg font-semibold text-white outline-none mb-1" />
      {v2 ? (
        <>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {ls.type_name && <Tag>{ls.type_name}</Tag>}
            <Tag>{ls.participants} persone</Tag>
            {ls.level && <Tag>Livello {ls.level}</Tag>}
            {(ls.body_parts || []).map((p) => <Tag key={p}>{cap(p)}</Tag>)}
            <Tag>pausa {ls.rest_sec}"</Tag>
          </div>
          <div className="text-xs text-white/55 mb-3 flex items-center gap-1.5" data-testid="lesson-total">
            <Clock size={12} /> {dirty ? "salva per ricalcolare la durata" : `${mins(ls.total_sec)} min su ${ls.duration_min} previsti`}
          </div>
          {ls.request && <div className="text-xs text-white/50 italic mb-3 break-words">“{ls.request}”</div>}
          {PHASES.map((ph) => {
            const rows = blocks.map((b, i) => [b, i]).filter(([b]) => b.phase === ph.key);
            return (
              <div key={ph.key} className="mb-3" data-testid={`phase-${ph.key}`}>
                <div className="flex items-center gap-2">
                  <div className="text-[10px] uppercase tracking-widest text-white/50 flex-1">{ph.label}</div>
                  <button type="button" onClick={() => setAdding(ph.key)} data-testid={`phase-add-${ph.key}`} className="p-1 rounded-full text-white/55 hover:text-white" aria-label={`Aggiungi esercizio a ${ph.label}`}><Plus size={13} /></button>
                </div>
                {rows.length === 0 && <div className="text-xs text-white/40 py-1.5">nessun esercizio</div>}
                {rows.map(([b, i]) => (
                  <div key={`${b.exercise_id}-${i}`} className="py-2 border-b border-white/[0.08] last:border-b-0 flex items-center gap-2" data-testid="lesson-block">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-white break-words">{b.name}</div>
                      <div className="text-[11.5px] text-white/55">
                        {blockDose(b)}{b.equipment ? ` · ${b.equipment}${b.equipment_per_person > 1 ? ` ×${b.equipment_per_person}` : ""}` : ""}{b.notes ? ` · ${b.notes}` : ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5 shrink-0">
                      <button type="button" onClick={() => setSets(i, -1)} aria-label="Una serie in meno" className="p-1.5 rounded-full bg-white/10 text-white/80"><Minus size={12} /></button>
                      <button type="button" onClick={() => setSets(i, 1)} aria-label="Una serie in più" className="p-1.5 rounded-full bg-white/10 text-white/80"><Plus size={12} /></button>
                      <button type="button" onClick={() => remove(i)} aria-label="Togli" data-testid="block-remove" className="p-1.5 rounded-full text-white/50 hover:text-white"><X size={13} /></button>
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
          {need.length > 0 && (
            <div className="mb-3" data-testid="lesson-equipment">
              <Label>attrezzi da preparare</Label>
              <div className="flex flex-wrap gap-1.5">{need.map(([k, q]) => <Tag key={k}>{q} × {k}</Tag>)}</div>
            </div>
          )}
          {(ls.excluded_equipment || []).length > 0 && (
            <div className="text-xs text-white/50 mb-3 flex items-start gap-1.5" data-testid="lesson-excluded">
              <AlertTriangle size={12} className="shrink-0 mt-0.5" />
              <span>Esclusi perché gli attrezzi non bastano per tutti: {ls.excluded_equipment.join(", ")}</span>
            </div>
          )}
          {ls.notes && <div className="text-sm text-white/70 mb-2 break-words">{ls.notes}</div>}
        </>
      ) : (
        <ol className="text-sm text-white/75 space-y-1 list-decimal list-inside my-3">
          {(ls.exercises || []).map((it, i) => <li key={i} className="break-words">{byId[it.exercise_id]?.name || "(esercizio rimosso)"}{it.notes ? ` — ${it.notes}` : ""}</li>)}
        </ol>
      )}
      <div className="flex justify-end gap-2 mt-4">
        <button onClick={del} data-testid="lesson-delete" className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5"><Trash2 size={14} /> Elimina</button>
        <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Chiudi</button>
        {dirty && <button onClick={save} disabled={busy} data-testid="lesson-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">{busy ? "Salvo…" : "Salva"}</button>}
      </div>
      {adding && (
        <PickExerciseSheet phase={adding} exercises={exercises} onClose={() => setAdding(null)} onPick={add} />
      )}
    </GlassBottomSheet>
  );
}

function PickExerciseSheet({ phase, exercises, onClose, onPick }) {
  const [q, setQ] = useState("");
  const role = phase === "centrale" ? "esercizio" : null;
  const list = exercises
    .filter((e) => (role ? (e.role || "esercizio") === role : (e.role || "esercizio") !== "esercizio"))
    .filter((e) => !q.trim() || e.name.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <GlassBottomSheet onClose={onClose} testid="pick-exercise-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-3">Aggiungi esercizio</div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca" className={`${field} mb-2`} autoFocus />
      <div className="max-h-[50vh] overflow-y-auto">
        {list.map((e) => (
          <button key={e.id} type="button" onClick={() => onPick(e)} data-testid="pick-exercise" className="w-full text-left py-2 border-b border-white/[0.08] last:border-b-0">
            <div className="text-sm text-white">{e.name}</div>
            <div className="text-[11px] text-white/50">{[cap(exBody(e)), exLevel(e) && `livello ${exLevel(e)}`, e.equipment].filter(Boolean).join(" · ")}</div>
          </button>
        ))}
        {list.length === 0 && <div className="text-xs text-white/45 py-2">Nessun esercizio</div>}
      </div>
    </GlassBottomSheet>
  );
}

/* the rules: the lesson types (duration, start and end, rest, defaults, free rules) + the studio's general rules */
function RulesSheet({ onClose }) {
  const [types, setTypes] = useState(null);
  const [editing, setEditing] = useState(null);
  const [guide, setGuide] = useState("");
  const [guideDirty, setGuideDirty] = useState(false);
  const load = async () => {
    try { setTypes((await api.get("/fitness/lesson-types")).data); } catch { setTypes([]); }
  };
  useEffect(() => {
    load();
    api.get("/fitness/guidelines").then((r) => setGuide(r.data?.text || "")).catch(() => {});
  }, []);
  const saveGuide = async () => {
    try { await api.put("/fitness/guidelines", { text: guide }); setGuideDirty(false); toast.success("Regole dello studio salvate"); }
    catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <GlassBottomSheet onClose={onClose} testid="rules-sheet" className={sheetCls}>
      <div className="text-lg font-semibold text-white mb-1">Regole delle lezioni</div>
      <div className="text-xs text-white/55 mb-4">Ogni tipo di lezione ha le sue regole di base; nella richiesta puoi cambiarle per quella lezione.</div>
      <div className="flex items-center gap-2 mb-1">
        <div className="text-[10px] uppercase tracking-widest text-white/50 flex-1">tipi di lezione</div>
        <button type="button" onClick={() => setEditing({})} data-testid="lesson-type-add" className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15 text-xs text-white"><Plus size={11} /> Nuovo tipo</button>
      </div>
      {types === null ? <div className="kicker py-2">caricamento…</div> : types.map((t) => (
        <button key={t.id} type="button" onClick={() => setEditing(t)} data-testid="lesson-type-row" className="w-full text-left py-2.5 border-b border-white/[0.08] last:border-b-0 flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-sm text-white font-medium">{t.name}</div>
            <div className="text-[11.5px] text-white/55">{t.duration_min} min · inizio {t.start_min}' {t.start_kind} · fine {t.end_min}' {t.end_kind} · pausa {t.rest_sec}"</div>
            {t.rules_text && <div className="text-[11.5px] text-white/45 line-clamp-1">{t.rules_text}</div>}
          </div>
          <Pencil size={13} className="text-white/50 shrink-0" />
        </button>
      ))}
      <div className="mt-5">
        <Label>regole valide per tutte le lezioni dello studio</Label>
        <Textarea data-testid="guidelines-text" value={guide} onChange={(e) => { setGuide(e.target.value); setGuideDirty(true); }}
          placeholder="Es. mai due esercizi di salto di seguito; spiega sempre la respirazione"
          className="bg-white/10 rounded-xl min-h-[90px] text-white" />
        {guideDirty && <div className="flex justify-end mt-2"><button onClick={saveGuide} data-testid="guidelines-save" className="px-4 py-1.5 rounded-full text-sm bg-white text-[#403A3C] font-medium">Salva</button></div>}
      </div>
      {editing && <LessonTypeSheet type={editing} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); }} />}
    </GlassBottomSheet>
  );
}

function LessonTypeSheet({ type, onClose, onSaved }) {
  const isNew = !type.id;
  const [f, setF] = useState({
    name: type.name || "", activity: type.activity || "funzionale", duration_min: type.duration_min ?? 40,
    start_min: type.start_min ?? 5, start_kind: type.start_kind || "stretching", end_min: type.end_min ?? 5, end_kind: type.end_kind || "stretching",
    rest_sec: type.rest_sec ?? 15, default_level: type.default_level || "medio", default_participants: type.default_participants ?? 10,
    mode: type.mode || "misto", rules_text: type.rules_text || "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    if (!f.name.trim()) { toast.error("Scrivi il nome del tipo di lezione"); return; }
    setBusy(true);
    try {
      if (isNew) await api.post("/fitness/lesson-types", f);
      else await api.patch(`/fitness/lesson-types/${type.id}`, f);
      onSaved();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const del = () => confirmToast(`Eliminare il tipo "${type.name}"?`, "Elimina", async () => {
    try { await api.delete(`/fitness/lesson-types/${type.id}`); onSaved(); } catch (e) { toast.error(errMsg(e)); }
  });
  return (
    <GlassBottomSheet onClose={onClose} testid="lesson-type-sheet" className={sheetCls}>
      <div className="text-lg font-semibold text-white mb-4">{isNew ? "Nuovo tipo di lezione" : type.name}</div>
      <div className="space-y-3.5">
        <div className="grid grid-cols-2 gap-2.5">
          <div><Label>nome</Label><input value={f.name} onChange={(e) => set("name")(e.target.value)} placeholder="Es. Funzionale" data-testid="lt-name" className={field} /></div>
          <div><Label>attività degli esercizi</Label><input value={f.activity} onChange={(e) => set("activity")(e.target.value)} className={field} /></div>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <div><Label>durata (minuti)</Label><NumField value={f.duration_min} onChange={set("duration_min")} testid="lt-duration" /></div>
          <div><Label>pausa tra le serie (secondi)</Label><NumField value={f.rest_sec} onChange={set("rest_sec")} /></div>
        </div>
        <div>
          <Label>inizio</Label>
          <div className="flex items-center gap-2.5 flex-wrap">
            <div className="w-20"><NumField value={f.start_min} onChange={set("start_min")} testid="lt-start" /></div>
            <span className="text-xs text-white/55">min di</span>
            <ChipRow options={PHASE_KINDS} value={f.start_kind} onChange={set("start_kind")} testid="lt-start-kind" />
          </div>
        </div>
        <div>
          <Label>fine</Label>
          <div className="flex items-center gap-2.5 flex-wrap">
            <div className="w-20"><NumField value={f.end_min} onChange={set("end_min")} /></div>
            <span className="text-xs text-white/55">min di</span>
            <ChipRow options={PHASE_KINDS} value={f.end_kind} onChange={set("end_kind")} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <div><Label>partecipanti (se non detto)</Label><NumField value={f.default_participants} onChange={set("default_participants")} min={1} /></div>
          <div><Label>livello (se non detto)</Label><ChipRow options={LEVELS} value={f.default_level} onChange={set("default_level")} /></div>
        </div>
        <div><Label>esercizi</Label><ChipRow options={MODES} value={f.mode} onChange={set("mode")} /></div>
        <div>
          <Label>altre regole (testo libero)</Label>
          <Textarea value={f.rules_text} onChange={(e) => set("rules_text")(e.target.value)} data-testid="lt-rules"
            placeholder="Es. alterna parte alta e bassa; massimo 2 esercizi di fila con lo stesso attrezzo"
            className="bg-white/10 rounded-xl min-h-[80px] text-white" />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        {!isNew && <button onClick={del} className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5"><Trash2 size={14} /> Elimina</button>}
        <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
        <button onClick={save} disabled={busy} data-testid="lt-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">{busy ? "Salvo…" : "Salva"}</button>
      </div>
    </GlassBottomSheet>
  );
}

/* ============ ESERCIZI ============ */
function ExercisesTab() {
  const { user } = useAuth();
  const [exercises, setExercises] = useState([]);
  const [equipment, setEquipment] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [part, setPart] = useState("");
  const [level, setLevel] = useState("");
  const [tool, setTool] = useState("");

  const load = async () => {
    try {
      const [r, eq] = await Promise.all([api.get("/exercises"), api.get("/fitness/equipment").catch(() => ({ data: [] }))]);
      setExercises(r.data); setEquipment(eq.data);
    } catch { toast.error("Errore nel caricamento degli esercizi"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const parts = useMemo(() => [...new Set(exercises.map(exBody).filter(Boolean))].sort(), [exercises]);
  const tools = useMemo(() => [...new Set(exercises.map((e) => e.equipment).filter(Boolean))].sort(), [exercises]);
  const shown = exercises.filter((e) =>
    (!role || (e.role || "esercizio") === role) && (!part || exBody(e) === part) && (!level || exLevel(e) === level)
    && (!tool || (tool === "-" ? !e.equipment : e.equipment === tool)) && (!q.trim() || e.name.toLowerCase().includes(q.trim().toLowerCase())));

  const toggle = (setter, cur, v) => setter(cur === v ? "" : v);
  return (
    <div>
      <div className="flex items-center gap-2.5 mb-2.5">
        <RoundBtn icon={Plus} label="Nuovo esercizio" testid="new-exercise" onClick={() => setEditing({})} />
        <div className="relative flex-1 min-w-0">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/45" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca un esercizio" data-testid="exercise-search" className={`${field} pl-9`} />
        </div>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-1 mb-4 -mx-4 px-4 md:mx-0 md:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" data-testid="exercise-filters">
        {ROLES.map((r) => <Chip key={r.value} on={role === r.value} onClick={() => toggle(setRole, role, r.value)} testid={`f-role-${r.value}`}>{r.label}</Chip>)}
        {parts.length > 0 && <span className="w-px bg-white/15 mx-0.5 shrink-0" />}
        {parts.map((p) => <Chip key={p} on={part === p} onClick={() => toggle(setPart, part, p)} testid={`f-part-${p}`}>{cap(p)}</Chip>)}
        <span className="w-px bg-white/15 mx-0.5 shrink-0" />
        {LEVELS.map((l) => <Chip key={l.value} on={level === l.value} onClick={() => toggle(setLevel, level, l.value)}>{l.label}</Chip>)}
        <span className="w-px bg-white/15 mx-0.5 shrink-0" />
        <Chip on={tool === "-"} onClick={() => toggle(setTool, tool, "-")}>Senza attrezzi</Chip>
        {tools.map((t) => <Chip key={t} on={tool === t} onClick={() => toggle(setTool, tool, t)}>{cap(t)}</Chip>)}
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && exercises.length === 0 && <div className="text-center text-white/40 py-24 kicker">nessun esercizio ancora</div>}
      {!loading && exercises.length > 0 && <div className="kicker mb-2" data-testid="exercise-count">{shown.length} esercizi</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {shown.map((ex) => (
          <button key={ex.id} type="button" onClick={() => setEditing(ex)} data-testid="exercise-card" className="card-soft p-3.5 rounded-2xl text-left min-w-0">
            <div className="flex items-start justify-between gap-2 mb-1.5">
              <div className="font-semibold text-sm break-words min-w-0">{ex.name}</div>
              {ex.builtin ? <span className="text-[10px] uppercase tracking-wider text-white/40 shrink-0">base</span>
                : ex.visibility === "org" ? <UsersIcon size={13} className="text-white/40 shrink-0" /> : <Lock size={13} className="text-white/25 shrink-0" />}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {ex.role && ex.role !== "esercizio" && <Tag>{cap(ex.role)}</Tag>}
              {exBody(ex) && <Tag>{cap(exBody(ex))}</Tag>}
              {exLevel(ex) && <Tag>{cap(exLevel(ex))}</Tag>}
              {ex.equipment && <Tag>{ex.equipment}{ex.equipment_per_person > 1 ? ` ×${ex.equipment_per_person}` : ""}</Tag>}
              {ex.timed?.allowed && ex.timed.max_sec && <Tag>{ex.timed.min_sec || ex.timed.max_sec}–{ex.timed.max_sec}"</Tag>}
              {ex.reps?.allowed && ex.reps.max_reps && <Tag>{ex.reps.min_reps || ex.reps.max_reps}–{ex.reps.max_reps} rip.</Tag>}
              {!ex.timed && ex.duration_minutes ? <Tag>{ex.duration_minutes} min</Tag> : null}
            </div>
            {ex.description && <div className="text-[12.5px] text-white/60 mt-2 line-clamp-2">{ex.description}</div>}
          </button>
        ))}
      </div>

      {editing && (
        <ExerciseSheet hasOrg={!!user?.org_id} exercise={editing} equipment={equipment} parts={parts}
          onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); }} />
      )}
    </div>
  );
}

function RangeRow({ label, on, onToggle, children, testid }) {
  return (
    <div className="rounded-2xl bg-white/[0.06] p-3" data-testid={testid}>
      <label className="flex items-center gap-2 text-sm text-white cursor-pointer">
        <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} className="accent-white" /> {label}
      </label>
      {on && <div className="grid grid-cols-2 gap-2 mt-2.5">{children}</div>}
    </div>
  );
}

function ExerciseSheet({ hasOrg, exercise, equipment, parts, onClose, onSaved }) {
  const isNew = !exercise.id;
  const t0 = exercise.timed || {}, r0 = exercise.reps || {};
  const [f, setF] = useState({
    name: exercise.name || "", role: exercise.role || "esercizio", activity: exercise.activity || "funzionale",
    body_part: exBody(exercise), level: exLevel(exercise), equipment: exercise.equipment || "", equipment_per_person: exercise.equipment_per_person ?? (exercise.equipment ? 1 : 0),
    description: exercise.description || "", notes: exercise.notes || "", link: exercise.link || "", visibility: exercise.visibility || (hasOrg ? "org" : "private"),
  });
  const [timed, setTimed] = useState({ allowed: exercise.id ? !!t0.allowed : true, min_sec: t0.min_sec ?? 30, max_sec: t0.max_sec ?? 40, min_sets: t0.min_sets ?? 1, max_sets: t0.max_sets ?? 3 });
  const [reps, setReps] = useState({ allowed: !!r0.allowed, min_reps: r0.min_reps ?? 10, max_reps: r0.max_reps ?? 12, min_sets: r0.min_sets ?? 1, max_sets: r0.max_sets ?? 3, sec_per_set: r0.sec_per_set ?? 30 });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const setT = (k) => (v) => setTimed((x) => ({ ...x, [k]: v }));
  const setR = (k) => (v) => setReps((x) => ({ ...x, [k]: v }));

  const save = async () => {
    if (!f.name.trim()) { toast.error("Scrivi il nome dell'esercizio"); return; }
    if (f.role === "esercizio" && !timed.allowed && !reps.allowed) { toast.error("Scegli se si fa a tempo, a ripetizioni o in tutti e due i modi"); return; }
    setBusy(true);
    const body = { ...f, level: f.level || null, equipment_per_person: f.equipment ? (f.equipment_per_person || 1) : 0, timed, reps };
    try {
      if (isNew) await api.post("/exercises", body);
      else await api.patch(`/exercises/${exercise.id}`, body);
      toast.success(isNew ? "Esercizio aggiunto" : "Esercizio salvato");
      onSaved();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const del = () => confirmToast(`Eliminare "${exercise.name}"?`, "Elimina", async () => {
    try { await api.delete(`/exercises/${exercise.id}`); toast.success("Esercizio eliminato"); onSaved(); }
    catch (e) { toast.error(errMsg(e)); }
  });

  return (
    <GlassBottomSheet onClose={onClose} testid="exercise-sheet" className={sheetCls}>
      <div className="text-lg font-semibold text-white mb-4">{isNew ? "Nuovo esercizio" : "Esercizio"}</div>
      <div className="space-y-3.5">
        <input value={f.name} onChange={(e) => set("name")(e.target.value)} placeholder="Nome (es. Affondi alternati)" autoFocus={isNew} data-testid="exercise-name" className={field} />
        <div><Label>tipo</Label><ChipRow options={ROLES} value={f.role} onChange={set("role")} testid="exercise-role" /></div>
        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <Label>parte del corpo</Label>
            <input value={f.body_part} onChange={(e) => set("body_part")(e.target.value)} list="ex-parts" placeholder="Es. gambe" data-testid="exercise-body" className={field} />
            <datalist id="ex-parts">{[...new Set([...parts, "gambe", "braccia", "glutei", "addome", "schiena", "spalle"])].map((p) => <option key={p} value={p} />)}</datalist>
          </div>
          <div><Label>attività</Label><input value={f.activity} onChange={(e) => set("activity")(e.target.value)} placeholder="funzionale" className={field} /></div>
        </div>
        <div><Label>livello</Label><ChipRow options={[{ value: "", label: "Tutti" }, ...LEVELS]} value={f.level} onChange={set("level")} testid="exercise-level" /></div>
        <div className="grid grid-cols-[1fr_7rem] gap-2.5">
          <div>
            <Label>attrezzo</Label>
            <input value={f.equipment} onChange={(e) => set("equipment")(e.target.value)} list="ex-tools" placeholder="Nessuno" data-testid="exercise-equipment" className={field} />
            <datalist id="ex-tools">{equipment.map((e) => <option key={e.id} value={e.name} />)}</datalist>
          </div>
          <div><Label>per persona</Label><NumField value={f.equipment ? f.equipment_per_person : ""} onChange={set("equipment_per_person")} placeholder="—" testid="exercise-per-person" /></div>
        </div>
        <RangeRow label="A tempo" on={timed.allowed} onToggle={setT("allowed")} testid="exercise-timed">
          <div><Label>secondi min</Label><NumField value={timed.min_sec} onChange={setT("min_sec")} /></div>
          <div><Label>secondi max</Label><NumField value={timed.max_sec} onChange={setT("max_sec")} testid="timed-max-sec" /></div>
          <div><Label>serie min</Label><NumField value={timed.min_sets} onChange={setT("min_sets")} min={1} /></div>
          <div><Label>serie max</Label><NumField value={timed.max_sets} onChange={setT("max_sets")} min={1} /></div>
        </RangeRow>
        <RangeRow label="A ripetizioni" on={reps.allowed} onToggle={setR("allowed")} testid="exercise-reps">
          <div><Label>ripetizioni min</Label><NumField value={reps.min_reps} onChange={setR("min_reps")} /></div>
          <div><Label>ripetizioni max</Label><NumField value={reps.max_reps} onChange={setR("max_reps")} /></div>
          <div><Label>serie min</Label><NumField value={reps.min_sets} onChange={setR("min_sets")} min={1} /></div>
          <div><Label>serie max</Label><NumField value={reps.max_sets} onChange={setR("max_sets")} min={1} /></div>
          <div className="col-span-2"><Label>secondi stimati per serie</Label><NumField value={reps.sec_per_set} onChange={setR("sec_per_set")} /></div>
        </RangeRow>
        <Textarea value={f.description} onChange={(e) => set("description")(e.target.value)} placeholder="Descrizione / come si esegue" className="bg-white/10 rounded-xl min-h-[70px] text-white" />
        <input value={f.notes} onChange={(e) => set("notes")(e.target.value)} placeholder="Note (es. schiena dritta)" className={field} />
        <div className="relative">
          <input value={f.link} onChange={(e) => set("link")(e.target.value)} placeholder="Link a un video (facoltativo)" className={`${field} ${f.link ? "pr-10" : ""}`} />
          {/^https?:\/\//.test(f.link) && <a href={f.link} target="_blank" rel="noreferrer" className="absolute right-3 top-1/2 -translate-y-1/2 text-white/60" aria-label="Apri il link"><ExternalLink size={14} /></a>}
        </div>
        {!exercise.builtin && <VisibilityToggle hasOrg={hasOrg} visibility={f.visibility} onChange={set("visibility")} />}
      </div>
      <div className="flex justify-end gap-2 mt-5">
        {!isNew && <button onClick={del} data-testid="exercise-delete" className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5"><Trash2 size={14} /> Elimina</button>}
        <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
        <button onClick={save} disabled={busy} data-testid="exercise-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">{busy ? "Salvo…" : "Salva"}</button>
      </div>
    </GlassBottomSheet>
  );
}

/* ============ ATTREZZI ============ */
function EquipmentTab() {
  const [items, setItems] = useState(null);
  const [name, setName] = useState("");
  const [qty, setQty] = useState(1);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try { setItems((await api.get("/fitness/equipment")).data); } catch { setItems([]); toast.error("Errore nel caricamento degli attrezzi"); }
  };
  useEffect(() => { load(); }, []);

  const add = async () => {
    if (!name.trim()) { toast.error("Scrivi il nome dell'attrezzo"); return; }
    try { await api.post("/fitness/equipment", { name, quantity: qty || 1 }); setName(""); setQty(1); await load(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  const bump = async (it, delta) => {
    setItems((xs) => xs.map((x) => (x.id === it.id ? { ...x, quantity: Math.max(0, x.quantity + delta) } : x)));
    try { await api.patch(`/fitness/equipment/${it.id}`, { delta }); } catch (e) { toast.error(errMsg(e)); load(); }
  };

  return (
    <div>
      <div className="text-sm text-white/60 mb-4">Gli attrezzi dello studio e quanti pezzi hai: nelle lezioni entrano solo gli esercizi con attrezzi sufficienti per tutti i partecipanti.</div>
      <div className="flex gap-2 mb-4" data-testid="equipment-add-row">
        <input value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="Nuovo attrezzo" data-testid="equipment-name" className={`${field} flex-1`} />
        <div className="w-16 shrink-0"><NumField value={qty} onChange={setQty} min={1} testid="equipment-qty" /></div>
        <button onClick={add} data-testid="equipment-add" className="pill-btn text-sm shrink-0" onMouseDown={(e) => e.preventDefault()}><Plus size={14} /> Aggiungi</button>
      </div>
      {items === null && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {items && items.length === 0 && <div className="text-center text-white/40 py-20 kicker">nessun attrezzo: le lezioni useranno solo esercizi a corpo libero</div>}
      {items && items.length > 0 && (
        <div className="glass-panel rounded-2xl px-4" data-testid="equipment-list">
          {items.map((it) => (
            <div key={it.id} className="glass-row py-3 flex items-center gap-3" data-testid="equipment-row">
              <button type="button" onClick={() => setEditing(it)} className="min-w-0 flex-1 text-left">
                <div className="text-sm text-white font-medium break-words">{cap(it.name)}</div>
                {it.notes && <div className="text-[11.5px] text-white/50 break-words">{it.notes}</div>}
              </button>
              <button type="button" onClick={() => bump(it, -1)} disabled={it.quantity <= 0} aria-label={`Togli un ${it.name}`} data-testid="equipment-minus" className="p-2 rounded-full bg-white/10 text-white disabled:opacity-40"><Minus size={14} /></button>
              <div className="w-9 text-center text-base font-semibold text-white tabular-nums" data-testid="equipment-quantity">{it.quantity}</div>
              <button type="button" onClick={() => bump(it, 1)} aria-label={`Aggiungi un ${it.name}`} data-testid="equipment-plus" className="p-2 rounded-full bg-white/10 text-white"><Plus size={14} /></button>
            </div>
          ))}
        </div>
      )}
      {editing && <EquipmentSheet item={editing} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); }} />}
    </div>
  );
}

function EquipmentSheet({ item, onClose, onSaved }) {
  const [f, setF] = useState({ name: item.name, quantity: item.quantity, notes: item.notes || "" });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.patch(`/fitness/equipment/${item.id}`, f); onSaved(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const del = () => confirmToast(`Eliminare "${item.name}" dagli attrezzi?`, "Elimina", async () => {
    try { await api.delete(`/fitness/equipment/${item.id}`); onSaved(); } catch (e) { toast.error(errMsg(e)); }
  });
  return (
    <GlassBottomSheet onClose={onClose} testid="equipment-sheet" className="max-h-[80vh] md:left-1/2 md:right-auto md:w-[440px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-4">Attrezzo</div>
      <div className="space-y-2.5">
        <div className="grid grid-cols-[1fr_6rem] gap-2.5">
          <div><Label>nome</Label><input value={f.name} onChange={(e) => setF((x) => ({ ...x, name: e.target.value }))} data-testid="equipment-edit-name" className={field} /></div>
          <div><Label>quantità</Label><NumField value={f.quantity} onChange={(v) => setF((x) => ({ ...x, quantity: v ?? 0 }))} /></div>
        </div>
        <input value={f.notes} onChange={(e) => setF((x) => ({ ...x, notes: e.target.value }))} placeholder="Nota (es. 2 kg)" className={field} />
        <div className="text-xs text-white/45">Cambiando il nome, si aggiorna anche negli esercizi che lo usano.</div>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <button onClick={del} data-testid="equipment-delete" className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5"><Trash2 size={14} /> Elimina</button>
        <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
        <button onClick={save} disabled={busy} data-testid="equipment-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">{busy ? "Salvo…" : "Salva"}</button>
      </div>
    </GlassBottomSheet>
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
