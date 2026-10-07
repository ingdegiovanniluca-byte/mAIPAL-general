import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { List, Plus, Trash2, Pencil, ArrowLeft, Users, Lock, X, ChevronRight, Settings2, Share2, Check, UserRound, Repeat, Rows3, FolderOpen, FolderPlus, NotebookPen, ChevronDown, MapPin, Phone, Mail, Briefcase, Activity } from "lucide-react";
import { toast } from "sonner";

// a value as shown on a card: dates as dd/mm/yyyy, lists joined
const fmtVal = (f, v) => {
  if (Array.isArray(v)) return v.join(", ");
  const s = String(v);
  const m = f?.type === "date" && s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : s;
};
const filled = (v) => v !== undefined && v !== null && String(v).trim() !== "";
const STATO_COLOR = { "in corso": "#8ED973", preventivo: "#F2C14E", sospesa: "#E8A03F", chiusa: "rgba(255,255,255,0.35)" };

// Gerarchia a 3 livelli:
//   Livello 1 - Lista       (es. "Clienti", "Lezioni Pilates")
//   Livello 2 - Campo       (un elemento della lista, es. "Cliente 1", "Lezione lunedì mattina")
//   Livello 3 - Elemento    (annidato dentro un campo, es. le "commesse" di un cliente, le "persone" di una lezione)
// Lo schema dei campi è definito da coll.fields; lo schema degli elementi, se configurato, da coll.sub_item_fields.

const FIELD_TYPES = [
  { value: "text", label: "Testo breve" },
  { value: "textarea", label: "Testo lungo" },
  { value: "number", label: "Numero" },
  { value: "date", label: "Data" },
  { value: "select", label: "Scelta (elenco)" },
  { value: "phone", label: "Telefono" },
  { value: "email", label: "Email" },
  { value: "reference", label: "Collegamento ad un'altra lista" },
];

const slugify = (label) =>
  (label || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim()
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "campo";

export default function CollectionsPage() {
  const [collections, setCollections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState({ level: 1 }); // {level:1} | {level:2, collection} | {level:3, collection, item}
  const [showCreate, setShowCreate] = useState(false);
  const [draggedId, setDraggedId] = useState(null);
  const [dragOverId, setDragOverId] = useState(null);

  const load = async () => {
    try {
      const r = await api.get("/collections");
      setCollections(r.data);
    } catch {
      toast.error("Errore nel caricamento delle liste");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Drag-to-reorder the list cards - moves optimistically in local state, then persists
  // the new order server-side so it survives a reload.
  const reorder = (fromId, toId) => {
    if (!fromId || !toId || fromId === toId) return;
    setCollections((cur) => {
      const arr = [...cur];
      const fromIdx = arr.findIndex((c) => c.id === fromId);
      const toIdx = arr.findIndex((c) => c.id === toId);
      if (fromIdx === -1 || toIdx === -1) return cur;
      const [moved] = arr.splice(fromIdx, 1);
      arr.splice(toIdx, 0, moved);
      api.patch("/collections/reorder", { ordered_ids: arr.map((c) => c.id) }).catch(() => {
        toast.error("Errore nel salvare l'ordine delle liste");
      });
      return arr;
    });
  };

  const del = (coll) => {
    toast(`Eliminare "${coll.name}" e tutto il suo contenuto?`, {
      action: {
        label: "Elimina",
        onClick: async () => {
          try {
            await api.delete(`/collections/${coll.id}`);
            await load();
            toast.success("Lista eliminata");
          } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  if (view.level === 3) {
    return (
      <SubItemsView
        collection={view.collection}
        item={view.item}
        onBack={() => setView({ level: 2, collection: view.collection })}
        onCollectionChanged={(c) => setView({ level: 3, collection: c, item: view.item })}
      />
    );
  }

  if (view.level === 2) {
    return (
      <CollectionDetail
        collection={view.collection}
        onBack={() => { setView({ level: 1 }); load(); }}
        onOpenItem={(item) => setView({ level: 3, collection: view.collection, item })}
        onCollectionChanged={(c) => setView({ level: 2, collection: c })}
      />
    );
  }

  return (
    <div>
      <div className="flex items-center justify-start mb-5">
        <RoundBtn icon={Plus} label="Nuova lista" testid="new-collection" onClick={() => setShowCreate(true)} big />
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}

      {!loading && collections.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">
          nessuna lista ancora — crea la tua prima lista (clienti, esercizi, commesse…)
        </div>
      )}

      <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 ${collections.length > 12 ? "lg-many" : ""}`}>
        {collections.map((c) => (
          <div
            key={c.id}
            draggable
            onDragStart={(e) => { setDraggedId(c.id); e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => { e.preventDefault(); if (dragOverId !== c.id) setDragOverId(c.id); }}
            onDragLeave={() => setDragOverId((v) => (v === c.id ? null : v))}
            onDrop={(e) => { e.preventDefault(); reorder(draggedId, c.id); setDraggedId(null); setDragOverId(null); }}
            onDragEnd={() => { setDraggedId(null); setDragOverId(null); }}
            data-testid={`collection-card-${c.id}`}
            className={`lg-card p-5 rounded-[24px] cursor-grab active:cursor-grabbing relative group transition-transform duration-150 ${dragOverId === c.id && draggedId !== c.id ? "ring-2 ring-white/40 scale-[1.02]" : ""} ${draggedId === c.id ? "opacity-50" : ""}`}
            onClick={() => setView({ level: 2, collection: c })}
          >
            {/* only the essentials: the name and, when shared, who with - the attributes are inside the list.
                On the right the lock/people icon and the bin side by side (never on top of each other) */}
            <div className="flex items-start gap-2">
              <div className="font-semibold text-lg flex-1 min-w-0">{c.name}</div>
              <span className="shrink-0 h-7 flex items-center" title={isShared(c) ? "Condivisa" : "Privata"}>
                {isShared(c) ? <Users size={14} className="text-white/70" /> : <Lock size={14} className="text-white/50" />}
              </span>
              {c.is_owner !== false && (
                <button
                  onClick={(e) => { e.stopPropagation(); del(c); }}
                  data-testid={`collection-delete-${c.id}`}
                  className="shrink-0 -mr-1.5 h-7 w-7 flex items-center justify-center rounded-full text-white/30 md:text-white/0 md:group-hover:text-white/40 hover:!text-red-400 hover:bg-red-500/10 transition-colors"
                  title="Elimina lista"
                  aria-label="Elimina lista"
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
            {sharingLabel(c) && <div className="text-[11px] text-white/85 mt-1 flex items-center gap-1" data-testid={`collection-sharing-${c.id}`}><Users size={11} className="shrink-0" />{sharingLabel(c)}</div>}
          </div>
        ))}
      </div>

      {showCreate && (
        <CreateCollectionDialog
          existingCollections={collections}
          onClose={() => setShowCreate(false)}
          onCreated={async (c) => { setShowCreate(false); await load(); setView({ level: 2, collection: c }); }}
        />
      )}
    </div>
  );
}

// Round frosted-glass icon button, the same as the bottom menu's "+".
function RoundBtn({ icon: Icon, label, onClick, testid, big = false, active = false, disabled = false }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick} title={label} aria-label={label} aria-pressed={active} disabled={disabled}
      className={`lg-glass shrink-0 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform disabled:opacity-60 ${active ? "!bg-white/35" : ""} ${big ? "h-11 w-11" : "h-9 w-9"}`}>
      <Icon size={big ? 22 : 17} strokeWidth={1.7} />
    </button>
  );
}

// One cell of the info under a list's name: a small label and its value below.
// An icon on top (its meaning in the tooltip) and the value below, the same size for all.
function InfoCell({ label, value, icon: Icon, testid, grow = false }) {
  return (
    <div className={`min-w-0 ${grow ? "flex-1" : "shrink-0"}`} data-testid={testid} title={label}>
      <Icon size={17} strokeWidth={1.7} className="text-white/85" aria-label={label} />
      <div className="text-white text-[14px] leading-snug mt-1.5 line-clamp-2 break-words">{value}</div>
    </div>
  );
}

// the first link of a folder made on Drive and/or OneDrive
const folderLink = (f) => Object.values(f?.links || {}).find(Boolean);

const isShared = (c) => c.visibility === "org" || (c.shared_with || []).length > 0;

const joinNames = (names) => (names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} e ${names[names.length - 1]}`);

// "di Mario Rossi" on a list a team-mate shared with me; "condivisa con …" on my own shared lists.
function sharingLabel(c) {
  if (c.is_owner === false) return `di ${c.owner?.name || "un collega"} · condivisa con te`;
  if (c.visibility === "org") return "condivisa con tutto il team";
  const names = (c.shared_with_users || []).map((u) => u.name.split(" ")[0]);
  return names.length ? `condivisa con ${joinNames(names)}` : "";
}

// Team-mates (me excluded), loaded once per picker; [] when not in a team.
function useTeamMates() {
  return useOrg().mates;
}

// The team: { mates (me excluded; null while loading, [] without a team), name }.
function useOrg() {
  const { user } = useAuth();
  const [org, setOrg] = useState({ mates: null, name: "" });
  useEffect(() => {
    if (!user?.org_id) { setOrg({ mates: [], name: "" }); return; }
    api.get("/org")
      .then((r) => setOrg({ mates: (r.data?.members || []).filter((m) => m.user_id !== user.user_id), name: r.data?.name || "" }))
      .catch(() => setOrg({ mates: [], name: "" }));
  }, [user?.org_id, user?.user_id]);
  return org;
}

// Who the list is shared with: nobody, the whole team, or chosen team-mates. Whoever it is
// shared with can see and edit it; the creator stays the owner.
function SharePicker({ value, onChange }) {
  const mates = useTeamMates();
  if (!mates || mates.length === 0) return null;
  const { visibility, user_ids } = value;
  const toggle = (id) => onChange({ visibility: "private", user_ids: user_ids.includes(id) ? user_ids.filter((x) => x !== id) : [...user_ids, id] });
  const chip = (on) => `px-3 py-1.5 rounded-full text-xs inline-flex items-center gap-1.5 transition-colors ${on ? "bg-[#4E7FA8] text-white" : "bg-white/10 text-white/70"}`;
  return (
    <div data-testid="share-picker">
      <div className="kicker mb-2">condividi con</div>
      <div className="flex flex-wrap gap-2">
        <button type="button" data-testid="share-none" onClick={() => onChange({ visibility: "private", user_ids: [] })} className={chip(visibility !== "org" && user_ids.length === 0)}>
          <Lock size={12} /> Solo io
        </button>
        <button type="button" data-testid="share-team" onClick={() => onChange({ visibility: "org", user_ids: [] })} className={chip(visibility === "org")}>
          <Users size={12} /> Tutto il team
        </button>
        {mates.map((m) => {
          const on = visibility !== "org" && user_ids.includes(m.user_id);
          return (
            <button type="button" key={m.user_id} data-testid={`share-person-${m.user_id}`} onClick={() => toggle(m.user_id)} className={chip(on)}>
              {on ? <Check size={12} /> : <UserRound size={12} />} {m.name || m.email}
            </button>
          );
        })}
      </div>
      <div className="text-[11px] text-white/40 mt-2">Chi la riceve può vederla e modificarla; solo tu puoi eliminarla o cambiare con chi è condivisa.</div>
    </div>
  );
}

function ShareDialog({ collection, onClose, onSaved }) {
  const [value, setValue] = useState({ visibility: collection.visibility || "private", user_ids: collection.shared_with || [] });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put(`/collections/${collection.id}/sharing`, value);
      toast.success(isShared(r.data) ? sharingLabel(r.data).replace(/^c/, "C") : "Ora la lista è visibile solo a te");
      onSaved(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };
  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent overlayClassName="bg-black/25" className="glass-panel glass-sheet border-0 rounded-[28px] text-white w-[calc(100%-24px)] max-w-lg" data-testid="share-collection-dialog">
        <DialogHeader><DialogTitle>Condividi «{collection.name}»</DialogTitle></DialogHeader>
        <SharePicker value={value} onChange={setValue} />
        <div className="flex justify-end mt-4">
          <button data-testid="share-save" onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Salva"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Editor riutilizzabile per un elenco di CollectionFieldDef (usato per i campi della lista
// e, separatamente, per gli attributi degli elementi annidati).
function FieldsEditor({ fields, setFields, existingCollections, emptyHint }) {
  const addField = () => setFields((f) => [...f, { key: "", label: "", type: "text" }]);
  const removeField = (i) => setFields((f) => f.filter((_, idx) => idx !== i));
  const updateField = (i, patch) => setFields((f) => f.map((fl, idx) => {
    if (idx !== i) return fl;
    // a new attribute gets its key when saved, from its whole name (see toApiFields): taken
    // while typing it was the first letter only, the same for "Descrizione" and "Data inizio"
    return { ...fl, ...patch };
  }));

  return (
    <div>
      {fields.length === 0 && emptyHint && <div className="text-xs text-white/40 mb-2">{emptyHint}</div>}
      <div className="space-y-2">
        {fields.map((f, i) => (
          <div key={i} className="flex gap-2 items-start bg-white/5 rounded-xl p-2.5">
            <div className="flex-1 space-y-2">
              <Input value={f.label} onChange={(e) => updateField(i, { label: e.target.value })} placeholder="Nome attributo (es. Telefono)" className="h-9 rounded-lg bg-white/10 text-sm" />
              <select
                value={f.type}
                onChange={(e) => updateField(i, { type: e.target.value })}
                className="h-9 rounded-lg bg-white/10 text-sm px-2 w-full text-white"
              >
                {FIELD_TYPES.map((t) => <option key={t.value} value={t.value} className="text-black">{t.label}</option>)}
              </select>
              {f.type === "select" && (
                <Input value={f.optionsText || ""} onChange={(e) => updateField(i, { optionsText: e.target.value })} placeholder="opzioni separate da virgola" className="h-9 rounded-lg bg-white/10 text-sm" />
              )}
              {f.type === "reference" && (
                <select
                  value={f.ref_collection_id || ""}
                  onChange={(e) => updateField(i, { ref_collection_id: e.target.value })}
                  className="w-full h-9 rounded-lg bg-white/10 text-sm px-2 text-white"
                >
                  <option value="" className="text-black">scegli la lista collegata…</option>
                  {(existingCollections || []).map((c) => <option key={c.id} value={c.id} className="text-black">{c.name}</option>)}
                </select>
              )}
            </div>
            <button onClick={() => removeField(i)} className="p-1.5 rounded-full text-white/40 hover:bg-red-500/10 hover:text-red-400 shrink-0"><X size={14} /></button>
          </div>
        ))}
      </div>
      <button onClick={addField} className="mt-2 text-sm text-white/60 hover:text-white flex items-center gap-1"><Plus size={13} /> Aggiungi attributo</button>
    </div>
  );
}

function toApiFields(fields) {
  const kept = fields.filter((f) => f.label.trim());
  const taken = new Set();
  const uniqueKey = (f) => {
    if (f.key && !taken.has(f.key)) { taken.add(f.key); return f.key; }
    const base = slugify(f.label);
    let key = base, n = 2;
    while (taken.has(key) || kept.some((o) => o !== f && o.key === key)) key = `${base}_${n++}`;
    taken.add(key);
    return key;
  };
  return kept.map((f) => ({
    key: uniqueKey(f),
    label: f.label.trim(),
    type: f.type,
    options: f.type === "select" ? (f.optionsText || "").split(",").map((s) => s.trim()).filter(Boolean) : null,
    ref_collection_id: f.type === "reference" ? (f.ref_collection_id || null) : null,
  }));
}

function CreateCollectionDialog({ existingCollections, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [share, setShare] = useState({ visibility: "private", user_ids: [] });
  const [fields, setFields] = useState([{ key: "nome", label: "Nome", type: "text" }]);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim()) { toast.error("Dai un nome alla lista"); return; }
    const cleanFields = toApiFields(fields);
    if (cleanFields.length === 0) { toast.error("Aggiungi almeno un attributo"); return; }
    setSaving(true);
    try {
      const r = await api.post("/collections", { name: name.trim(), visibility: share.visibility, shared_with: share.user_ids, fields: cleanFields });
      toast.success("Lista creata");
      onCreated(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent overlayClassName="bg-black/25" className="glass-panel glass-sheet border-0 rounded-[28px] text-white w-[calc(100%-24px)] max-w-lg max-h-[90vh] overflow-y-auto" data-testid="create-collection-dialog">
        <DialogHeader><DialogTitle>Nuova lista</DialogTitle></DialogHeader>

        <div className="space-y-4">
          <div>
            <div className="kicker mb-1">nome lista</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Clienti, Esercizi, Commesse…" className="h-11 rounded-xl bg-white/10 border-0" />
          </div>

          <SharePicker value={share} onChange={setShare} />

          <div>
            <div className="kicker mb-2">attributi dei campi</div>
            <FieldsEditor fields={fields} setFields={setFields} existingCollections={existingCollections} />
            <div className="text-[11px] text-white/40 mt-2">
              Potrai aggiungere in seguito anche attributi per elementi annidati dentro ogni campo (es. le persone di una lezione, le commesse di un cliente) da "Gestisci attributi".
            </div>
          </div>
        </div>

        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Crea lista"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ============ LIVELLO 2 — CAMPI ============ */
const PAGE_ITEMS = 60;
function CollectionDetail({ collection, onBack, onOpenItem, onCollectionChanged }) {
  const [coll, setColl] = useState(collection);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // campo in modifica, o {} per nuovo
  const [managingFields, setManagingFields] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [draggedId, setDraggedId] = useState(null);
  const [dragOverId, setDragOverId] = useState(null);
  const [selected, setSelected] = useState(() => new Set());   // campi ticked for a bulk delete
  const [related, setRelated] = useState([]);                  // scheduled actions working on this list
  const [shown, setShown] = useState(PAGE_ITEMS);              // a long list is drawn a page at a time
  const [folderBusy, setFolderBusy] = useState(false);
  // the list's folder on Drive / OneDrive: made on the first tap, opened afterwards
  const openOrCreateFolder = async () => {
    if (coll.drive_folder && folderLink(coll.drive_folder)) {
      window.open(folderLink(coll.drive_folder), "_blank", "noopener");
      return;
    }
    setFolderBusy(true);
    try {
      const r = await api.post(`/collections/${coll.id}/folder`);
      const next = { ...coll, drive_folder: r.data.drive_folder };
      setColl(next);
      onCollectionChanged(next);
      const link = folderLink(r.data.drive_folder);
      toast.success(r.data.message || "Cartella creata", link ? { action: { label: "Apri", onClick: () => window.open(link, "_blank", "noopener") } } : undefined);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Non sono riuscito a creare la cartella");
    } finally {
      setFolderBusy(false);
    }
  };
  const [renaming, setRenaming] = useState(false);
  const rename = async (value) => {
    const name = (value || "").trim();
    setRenaming(false);
    if (!name || name === coll.name) return;
    try {
      const r = await api.patch(`/collections/${coll.id}`, { name });
      setColl((cur) => ({ ...cur, name: r.data?.name || name }));
      onCollectionChanged({ ...coll, name: r.data?.name || name });
      toast.success("Lista rinominata");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const { mates, name: orgName } = useOrg();
  const canShare = coll.is_owner !== false && (mates || []).length > 0;
  useEffect(() => {
    api.get("/scheduled-actions")
      .then((r) => setRelated((r.data || []).filter((a) => a.enabled && a.kind === "list_update" && a.list_op?.collection_id === collection.id)))
      .catch(() => {});
  }, [collection.id]);
  const toggleSelected = (id) => setSelected((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const delSelected = () => {
    const ids = [...selected];
    toast(`Eliminare ${ids.length === 1 ? "il campo selezionato" : `i ${ids.length} campi selezionati`}?`, {
      action: {
        label: "Elimina",
        onClick: async () => {
          const res = await Promise.allSettled(ids.map((id) => api.delete(`/collections/${coll.id}/items/${id}`)));
          const failed = res.filter((r) => r.status === "rejected").length;
          setSelected(new Set());
          await load();
          if (failed) toast.error(`${failed} non eliminat${failed === 1 ? "o" : "i"}`);
          else toast.success(ids.length === 1 ? "Eliminato" : `${ids.length} campi eliminati`);
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };
  // "Condivisa" / the team's name, or who it's shared with; "Privata" otherwise
  const shareInfo = coll.is_owner === false
    ? { label: "Condivisa", value: `di ${coll.owner?.name || "un collega"}` }
    : coll.visibility === "org"
      ? { label: "Condivisa", value: orgName || "tutto il team" }
      : (coll.shared_with_users || []).length
        ? { label: "Condivisa", value: joinNames((coll.shared_with_users || []).map((u) => u.name.split(" ")[0])) }
        : { label: "Privata", value: "solo tu" };

  const load = async () => {
    try {
      const [c, it] = await Promise.all([
        api.get(`/collections/${coll.id}`),
        api.get(`/collections/${coll.id}/items`),
      ]);
      setColl(c.data);
      setItems(it.data);
      onCollectionChanged(c.data);
    } catch {
      toast.error("Errore nel caricamento della lista");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const hasSubLevel = (coll.sub_item_fields || []).length > 0;
  // the artigiano's Clienti list: name and address on the card, phone and e-mail behind the arrow
  const isClienti = coll.system_key === "artigiano_clienti";
  const sysKey = (k) => (coll.system_map || {})[k] || k;
  const [expanded, setExpanded] = useState(() => new Set());
  const toggleExpanded = (id) => setExpanded((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const delClient = (item) => {
    const name = item.data?.[sysKey("nome")] || "questo cliente";
    const n = item.sub_item_count || 0;
    toast(`Eliminare ${name}${n ? ` con ${n === 1 ? "la sua commessa" : `le sue ${n} commesse`} e il loro diario` : ""}?`, {
      action: {
        label: "Elimina",
        onClick: async () => {
          try {
            await api.delete(`/collections/${coll.id}/items/${item.id}`);
            await load();
            toast.success("Cliente eliminato");
          } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 8000,
    });
  };

  // Drag-to-reorder the Campi cards - same approach as the Liste page's card reorder.
  const reorderItems = (fromId, toId) => {
    if (!fromId || !toId || fromId === toId) return;
    setItems((cur) => {
      const arr = [...cur];
      const fromIdx = arr.findIndex((it) => it.id === fromId);
      const toIdx = arr.findIndex((it) => it.id === toId);
      if (fromIdx === -1 || toIdx === -1) return cur;
      const [moved] = arr.splice(fromIdx, 1);
      arr.splice(toIdx, 0, moved);
      api.patch(`/collections/${coll.id}/items/reorder`, { ordered_ids: arr.map((it) => it.id) }).catch(() => {
        toast.error("Errore nel salvare l'ordine dei campi");
      });
      return arr;
    });
  };

  return (
    <div>
      <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-white/60 hover:text-white mb-4">
        <ArrowLeft size={14} /> Liste
      </button>

      {renaming ? (
        <input
          autoFocus
          data-testid="rename-input"
          defaultValue={coll.name}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setRenaming(false); }}
          onBlur={(e) => rename(e.currentTarget.value)}
          className="w-full bg-white/15 rounded-xl px-3 py-1.5 font-semibold text-2xl text-white outline-none border-0"
        />
      ) : (
        <button type="button" data-testid="rename-list" onClick={() => setRenaming(true)} title="Rinomina la lista"
          className="group flex items-center gap-2 text-left">
          <span className="font-semibold text-2xl">{coll.name}</span>
          <Pencil size={15} className="text-white/60 shrink-0" />
        </button>
      )}
      {/* the list at a glance: how many campi, who it's shared with, the actions working on it */}
      <div className="mt-3 mb-5 flex items-start gap-6" data-testid="collection-info">
        <InfoCell label={isClienti ? "Clienti" : "Campi"} icon={Rows3} testid="info-items"
          value={loading ? "…" : isClienti ? `${items.length} ${items.length === 1 ? "cliente" : "clienti"}` : `${items.length} ${items.length === 1 ? "campo" : "campi"}`} />
        <InfoCell label={shareInfo.label} value={shareInfo.value} icon={shareInfo.label === "Condivisa" ? Users : Lock} testid="collection-sharing" />
        {related.length > 0 && (
          <InfoCell label={related.length === 1 ? "Azione programmata" : `${related.length} azioni programmate`} icon={Repeat} grow testid="info-actions"
            value={`${related[0].title}${related[0].schedule_label ? ` · ${related[0].schedule_label.charAt(0).toLowerCase()}${related[0].schedule_label.slice(1)}` : ""}`} />
        )}
      </div>

      {/* +, Gestisci attributi, Condividi: round glass buttons on one row, like the rest of the app */}
      <div className="flex items-center gap-2.5 mb-5" data-testid="collection-actions">
        <RoundBtn icon={Plus} label="Nuovo campo" testid="new-item" onClick={() => setEditing({})} />
        <RoundBtn icon={Settings2} label="Gestisci attributi" testid="manage-fields" onClick={() => setManagingFields(true)} />
        {canShare && <RoundBtn icon={Share2} label="Condividi" testid="share-collection" onClick={() => setSharing(true)} />}
        <RoundBtn icon={coll.drive_folder ? FolderOpen : FolderPlus} testid="list-folder" active={!!coll.drive_folder} disabled={folderBusy}
          label={coll.drive_folder ? `Apri la cartella «${coll.drive_folder.name}» su Drive` : "Crea la cartella della lista su Drive"}
          onClick={openOrCreateFolder} />
        {selected.size > 0 && (
          // only a bin, with how many campi are ticked; untick them to cancel
          <button data-testid="delete-selected" onClick={delSelected} title="Elimina selezionati" aria-label={`Elimina ${selected.size} selezionati`}
            className="lg-glass ml-auto relative h-9 w-9 shrink-0 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
            <Trash2 size={17} strokeWidth={1.7} />
            <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-white text-[#8E2F6B] text-[11px] font-semibold flex items-center justify-center">{selected.size}</span>
          </button>
        )}
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && items.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">nessun campo ancora</div>
      )}

      <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 ${items.length > 12 ? "lg-many" : ""}`}>
        {items.slice(0, shown).map((item) => (
          <div
            key={item.id}
            draggable
            onDragStart={(e) => { setDraggedId(item.id); e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => { e.preventDefault(); if (dragOverId !== item.id) setDragOverId(item.id); }}
            onDragLeave={() => setDragOverId((v) => (v === item.id ? null : v))}
            onDrop={(e) => { e.preventDefault(); reorderItems(draggedId, item.id); setDraggedId(null); setDragOverId(null); }}
            onDragEnd={() => { setDraggedId(null); setDragOverId(null); }}
            data-testid={`item-card-${item.id}`}
className={`lg-card p-4 pr-10 rounded-[22px] relative group cursor-grab active:cursor-grabbing transition-transform duration-150 ${dragOverId === item.id && draggedId !== item.id ? "ring-2 ring-white/40 scale-[1.02]" : ""} ${draggedId === item.id ? "opacity-50" : ""}`}
            // tap: while ticking campi it ticks this one too; otherwise opens it (its elementi) or edits it
            onClick={() => (selected.size ? toggleSelected(item.id) : hasSubLevel ? onOpenItem(item) : setEditing(item))}
          >
            {isClienti ? (
              <div data-testid="client-card">
                <div className="font-semibold text-base leading-snug">{item.data?.[sysKey("nome")] || "Cliente senza nome"}</div>
                <div className="flex items-start gap-1.5 text-xs text-white/70 mt-1">
                  <MapPin size={12} className="shrink-0 mt-0.5" />
                  <span>{item.data?.[sysKey("indirizzo")] || "indirizzo non indicato"}</span>
                </div>
                {expanded.has(item.id) && (
                  <div className="mt-2.5 pt-2.5 border-t border-white/10 space-y-1.5 text-xs text-white/85" data-testid="client-details"
                    onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-1.5"><Phone size={12} className="text-white/60" />
                      {item.data?.[sysKey("telefono")]
                        ? <a href={`tel:${item.data[sysKey("telefono")]}`} className="underline-offset-2 hover:underline">{item.data[sysKey("telefono")]}</a>
                        : <span className="text-white/45">telefono non indicato</span>}
                    </div>
                    <div className="flex items-center gap-1.5"><Mail size={12} className="text-white/60" />
                      {item.data?.[sysKey("email")]
                        ? <a href={`mailto:${item.data[sysKey("email")]}`} className="underline-offset-2 hover:underline break-all">{item.data[sysKey("email")]}</a>
                        : <span className="text-white/45">email non indicata</span>}
                    </div>
                    {(coll.fields || []).filter((f) => ![sysKey("nome"), sysKey("indirizzo"), sysKey("telefono"), sysKey("email")].includes(f.key)
                      && filled(item.data?.[f.key])).map((f) => (
                      <div key={f.key} className="pt-0.5">
                        <div className="text-[10px] uppercase tracking-widest text-white/50">{f.label}</div>
                        <div className="text-xs text-white/85 break-words whitespace-pre-wrap">{fmtVal(f, item.data[f.key])}</div>
                      </div>
                    ))}
                    <div className="flex items-center gap-2 pt-1.5">
                      <button type="button" onClick={() => setEditing(item)} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15">
                        <Pencil size={11} /> Modifica
                      </button>
                      <button type="button" data-testid="delete-client" onClick={() => delClient(item)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-red-500/20 hover:text-red-200">
                        <Trash2 size={11} /> Elimina cliente
                      </button>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-1 text-[11px] text-white/70 mt-2">
                  <ChevronRight size={12} /> {item.sub_item_count || 0} {item.sub_item_count === 1 ? "commessa" : "commesse"}
                </div>
              </div>
            ) : (coll.fields || []).map((f) => (
              filled(item.data?.[f.key]) ? (
                <div key={f.key} className="mb-1.5">
                  <div className="text-[10px] uppercase tracking-widest text-white/60">{f.label}</div>
                  <div className="text-sm break-words">{fmtVal(f, item.data[f.key])}</div>
                </div>
              ) : null
            ))}
            {hasSubLevel && !isClienti && (
              <div className="flex items-center gap-1 text-[11px] text-white/70 mt-2">
                <ChevronRight size={12} /> {item.sub_item_count || 0} elementi
              </div>
            )}
            {/* round tick to select it (several at once, then "Elimina"); the pencil where a tap opens the elementi */}
            <div className="absolute top-3 right-3 flex flex-col items-center gap-1.5">
              <button type="button" data-testid={`select-item-${item.id}`} aria-pressed={selected.has(item.id)}
                aria-label={selected.has(item.id) ? "Deseleziona" : "Seleziona"}
                onClick={(e) => { e.stopPropagation(); toggleSelected(item.id); }}
                className={`h-5 w-5 rounded-full flex items-center justify-center backdrop-blur-md transition-colors ${selected.has(item.id) ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
                {selected.has(item.id) && <Check size={12} strokeWidth={2.8} />}
              </button>
              {isClienti ? (
                <button type="button" data-testid={`expand-client-${item.id}`} onClick={(e) => { e.stopPropagation(); toggleExpanded(item.id); }}
                  aria-label={expanded.has(item.id) ? "Nascondi telefono ed email" : "Mostra telefono ed email"} aria-expanded={expanded.has(item.id)}
                  className="p-1 rounded-full text-white/80 hover:bg-white/10">
                  <ChevronDown size={15} className={`transition-transform ${expanded.has(item.id) ? "rotate-180" : ""}`} />
                </button>
              ) : hasSubLevel && (
                <button type="button" onClick={(e) => { e.stopPropagation(); setEditing(item); }} aria-label="Modifica"
                  className="p-1 rounded-full text-white/70 hover:bg-white/10"><Pencil size={13} /></button>
              )}
            </div>
          </div>
        ))}
      </div>

      {items.length > shown && (
        <button data-testid="show-more-items" onClick={() => setShown((n) => n + PAGE_ITEMS)}
          className="mt-4 mb-28 md:mb-0 w-full py-2.5 rounded-full lg-glass text-sm text-white">
          Mostra altri {Math.min(PAGE_ITEMS, items.length - shown)} di {items.length - shown}
        </button>
      )}

      {editing && (
        <ItemFormDialog
          title={editing.id ? "Modifica campo" : "Nuovo campo"}
          fields={coll.fields || []}
          initialData={editing.data || {}}
          onClose={() => setEditing(null)}
          onSave={async (data) => {
            if (editing.id) await api.patch(`/collections/${coll.id}/items/${editing.id}`, { data });
            else await api.post(`/collections/${coll.id}/items`, { data });
            setEditing(null);
            await load();
            toast.success("Salvato");
          }}
        />
      )}

      {sharing && (
        <ShareDialog
          collection={coll}
          onClose={() => setSharing(false)}
          onSaved={(c) => { setSharing(false); setColl((cur) => ({ ...cur, ...c })); onCollectionChanged({ ...coll, ...c }); }}
        />
      )}

      {managingFields && (
        <ManageAttributesDialog
          collection={coll}
          onClose={() => setManagingFields(false)}
          onSaved={async () => { setManagingFields(false); await load(); }}
        />
      )}
    </div>
  );
}

/* ============ LIVELLO 3 — ELEMENTI ============ */
function SubItemsView({ collection, item, onBack, onCollectionChanged }) {
  const navigate = useNavigate();
  const [coll, setColl] = useState(collection);
  // the artigiano's Clienti list: each commessa has its diary
  const isCommesse = coll.system_key === "artigiano_clienti";
  // a commessa's card: Commessa, Via and Stato; everything else behind the arrow
  const subKey = (k) => (coll.system_sub_map || {})[k] || k;
  const mainSubKeys = [subKey("titolo"), subKey("indirizzo_cantiere"), subKey("stato")];
  const [openSubs, setOpenSubs] = useState(() => new Set());
  const toggleSub = (id) => setOpenSubs((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const openDiary = (sub) => navigate("/dashboard/journal", { state: { commessa: sub.id } });
  const [subItems, setSubItems] = useState([]);
  // the commessa's folder on Drive/OneDrive, inside its client's: mAIPAL/Clienti/<cliente>/<commessa>
  const [folderBusy, setFolderBusy] = useState(null);
  const commessaFolder = async (sub) => {
    if (sub.drive_folder && folderLink(sub.drive_folder)) {
      window.open(folderLink(sub.drive_folder), "_blank", "noopener");
      return;
    }
    setFolderBusy(sub.id);
    try {
      const r = await api.post(`/jobs/commesse/${sub.id}/folder`);
      setSubItems((cur) => cur.map((x) => (x.id === sub.id ? { ...x, drive_folder: r.data.drive_folder } : x)));
      const link = folderLink(r.data.drive_folder);
      toast.success(r.data.message || "Cartella creata", link ? { action: { label: "Apri", onClick: () => window.open(link, "_blank", "noopener") } } : undefined);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Non sono riuscito a creare la cartella");
    } finally {
      setFolderBusy(null);
    }
  };
  const activeCount = subItems.filter((sb) => String(sb.data?.[subKey("stato")] || "").toLowerCase() !== "chiusa").length;
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const itemLabel = (coll.fields && coll.fields[0]) ? (item.data?.[coll.fields[0].key] || "campo") : "campo";

  const load = async () => {
    try {
      const [c, sub] = await Promise.all([
        api.get(`/collections/${coll.id}`),
        api.get(`/collections/${coll.id}/items/${item.id}/sub-items`),
      ]);
      setColl(c.data);
      onCollectionChanged(c.data);
      setSubItems(sub.data);
    } catch {
      toast.error("Errore nel caricamento degli elementi");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const delSub = (sub) => {
    const name = isCommesse ? (sub.data?.[subKey("titolo")] || "questa commessa") : "";
    toast(isCommesse ? `Eliminare la commessa «${name}» e il suo diario?` : "Eliminare questo elemento?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          try {
            await api.delete(`/collections/${coll.id}/items/${item.id}/sub-items/${sub.id}`);
            await load();
            toast.success("Eliminato");
          } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  return (
    <div>
      <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-white/60 hover:text-white mb-4">
        <ArrowLeft size={14} /> {coll.name}
      </button>

      {isCommesse ? (
        // like the Clienti level: the client's name, its numbers on one row, then the "+"
        <>
          <div className="font-semibold text-2xl break-words" data-testid="commesse-client-name">{itemLabel}</div>
          <div className="mt-3 mb-5 flex items-start gap-6" data-testid="commesse-info">
            <InfoCell label="Commesse totali" icon={Briefcase} testid="info-commesse-total"
              value={loading ? "…" : `${subItems.length} ${subItems.length === 1 ? "commessa" : "commesse"}`} />
            <InfoCell label="Commesse attive (tutte tranne le chiuse)" icon={Activity} testid="info-commesse-active"
              value={loading ? "…" : `${activeCount} ${activeCount === 1 ? "attiva" : "attive"}`} />
          </div>
          <div className="flex items-center gap-2.5 mb-5">
            <RoundBtn icon={Plus} label="Nuova commessa" testid="new-sub-item" onClick={() => setEditing({})} />
          </div>
        </>
      ) : (
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <div className="kicker">· elementi di</div>
          <div className="font-semibold text-xl">{itemLabel}</div>
        </div>
        <button data-testid="new-sub-item" onClick={() => setEditing({})} className="pill-btn text-sm">
          <Plus size={14} /> Nuovo elemento
        </button>
      </div>
      )}

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && subItems.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">nessun elemento ancora</div>
      )}

      <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 ${subItems.length > 12 ? "lg-many" : ""}`}>
        {subItems.map((sub) => (
          isCommesse ? (
            <div key={sub.id} data-testid="commessa-card" onClick={() => openDiary(sub)}
              className="lg-card p-4 pr-11 rounded-[22px] relative cursor-pointer">
              <div className="text-[10px] uppercase tracking-widest text-white/60">Commessa</div>
              <div className="text-[15px] font-semibold leading-snug break-words">{filled(sub.data?.[subKey("titolo")]) ? sub.data[subKey("titolo")] : "Senza titolo"}</div>
              <div className="mt-2 text-[10px] uppercase tracking-widest text-white/60">Via</div>
              <div className="text-sm break-words">{filled(sub.data?.[subKey("indirizzo_cantiere")]) ? sub.data[subKey("indirizzo_cantiere")] : <span className="text-white/45">non indicata</span>}</div>
              <div className="mt-2 text-[10px] uppercase tracking-widest text-white/60">Stato</div>
              <div className="text-sm flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full shrink-0" style={{ background: STATO_COLOR[sub.data?.[subKey("stato")]] || "rgba(255,255,255,0.35)" }} />
                {filled(sub.data?.[subKey("stato")]) ? String(sub.data[subKey("stato")]).charAt(0).toUpperCase() + String(sub.data[subKey("stato")]).slice(1) : "senza stato"}
              </div>
              {openSubs.has(sub.id) && (
                <div className="mt-2.5 pt-2.5 border-t border-white/10 space-y-1.5" data-testid="commessa-details" onClick={(e) => e.stopPropagation()}>
                  {(coll.sub_item_fields || []).filter((f) => !mainSubKeys.includes(f.key) && filled(sub.data?.[f.key])).map((f) => (
                    <div key={f.key}>
                      <div className="text-[10px] uppercase tracking-widest text-white/50">{f.label}</div>
                      <div className="text-xs text-white/85 break-words whitespace-pre-wrap">{fmtVal(f, sub.data[f.key])}</div>
                    </div>
                  ))}
                  {!(coll.sub_item_fields || []).some((f) => !mainSubKeys.includes(f.key) && filled(sub.data?.[f.key])) && (
                    <div className="text-xs text-white/45">Nessun altro dato: aggiungili con Modifica.</div>
                  )}
                  {/* the commands' row also takes the space kept on the right for the arrow, which is at the top */}
                  <div className="flex flex-wrap items-center gap-2 pt-1.5 text-xs -mr-8">
                    <button type="button" data-testid="open-commessa-diary" onClick={() => openDiary(sub)} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15">
                      <NotebookPen size={11} /> Diario
                    </button>
                    <button type="button" onClick={() => setEditing(sub)} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15">
                      <Pencil size={11} /> Modifica
                    </button>
                    <button type="button" data-testid="delete-commessa" onClick={() => delSub(sub)} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-red-500/20 hover:text-red-200">
                      <Trash2 size={11} /> Elimina
                    </button>
                    {/* open card: the folder joins the commands, at the end of their row (bottom corner) */}
                    <button type="button" data-testid={`commessa-folder-${sub.id}`} disabled={folderBusy === sub.id}
                      onClick={(e) => { e.stopPropagation(); commessaFolder(sub); }}
                      title={sub.drive_folder ? `Apri la cartella «${sub.drive_folder.name}»` : "Crea la cartella della commessa su Drive, dentro quella del cliente"}
                      className="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15 disabled:opacity-50">
                      {sub.drive_folder ? <FolderOpen size={11} /> : <FolderPlus size={11} />} Cartella
                    </button>
                  </div>
                </div>
              )}
              <button type="button" data-testid={`expand-commessa-${sub.id}`} onClick={(e) => { e.stopPropagation(); toggleSub(sub.id); }}
                aria-label={openSubs.has(sub.id) ? "Nascondi gli altri dati" : "Mostra gli altri dati"} aria-expanded={openSubs.has(sub.id)}
                className="absolute top-3 right-3 p-1 rounded-full text-white/80 hover:bg-white/10">
                <ChevronDown size={15} className={`transition-transform ${openSubs.has(sub.id) ? "rotate-180" : ""}`} />
              </button>
              {/* closed card: the folder in the bottom corner, on the same side as the arrow but far from it */}
              {!openSubs.has(sub.id) && (
                <button type="button" data-testid={`commessa-folder-${sub.id}`} disabled={folderBusy === sub.id}
                  onClick={(e) => { e.stopPropagation(); commessaFolder(sub); }}
                  title={sub.drive_folder ? `Apri la cartella «${sub.drive_folder.name}»` : "Crea la cartella della commessa su Drive, dentro quella del cliente"}
                  aria-label={sub.drive_folder ? "Apri la cartella della commessa" : "Crea la cartella della commessa"}
                  className={`absolute bottom-3 right-3 p-1 rounded-full hover:bg-white/10 disabled:opacity-50 ${sub.drive_folder ? "text-white" : "text-white/80"}`}>
                  {sub.drive_folder ? <FolderOpen size={15} /> : <FolderPlus size={15} />}
                </button>
              )}
            </div>
          ) : (
          <div key={sub.id} className="lg-card p-4 rounded-[22px] relative group">
            {(coll.sub_item_fields || []).map((f) => (
              filled(sub.data?.[f.key]) ? (
                <div key={f.key} className="mb-1.5">
                  <div className="text-[10px] uppercase tracking-widest text-white/60">{f.label}</div>
                  <div className="text-sm break-words">{fmtVal(f, sub.data[f.key])}</div>
                </div>
              ) : null
            ))}
            <div className="absolute top-3 right-3 flex gap-1 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
              <button onClick={() => setEditing(sub)} className="p-1.5 rounded-full text-white/50 hover:bg-white/10"><Pencil size={13} /></button>
              <button onClick={() => delSub(sub)} className="p-1.5 rounded-full text-white/50 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={13} /></button>
            </div>
          </div>
          )
        ))}
      </div>

      {editing && (
        <ItemFormDialog
          title={editing.id ? (isCommesse ? "Modifica commessa" : "Modifica elemento") : (isCommesse ? "Nuova commessa" : "Nuovo elemento")}
          fields={coll.sub_item_fields || []}
          initialData={editing.data || {}}
          onClose={() => setEditing(null)}
          onSave={async (data) => {
            if (editing.id) await api.patch(`/collections/${coll.id}/items/${item.id}/sub-items/${editing.id}`, { data });
            else await api.post(`/collections/${coll.id}/items/${item.id}/sub-items`, { data });
            setEditing(null);
            await load();
            toast.success("Salvato");
          }}
        />
      )}
    </div>
  );
}

function ManageAttributesDialog({ collection, onClose, onSaved }) {
  const [fields, setFields] = useState(
    (collection.fields || []).map((f) => ({ ...f, optionsText: (f.options || []).join(", ") }))
  );
  const [subFields, setSubFields] = useState(
    (collection.sub_item_fields || []).map((f) => ({ ...f, optionsText: (f.options || []).join(", ") }))
  );
  const [maxItems, setMaxItems] = useState(collection.max_items != null ? String(collection.max_items) : "");
  const [maxSubItems, setMaxSubItems] = useState(collection.max_sub_items_per_item != null ? String(collection.max_sub_items_per_item) : "");
  const [allCollections, setAllCollections] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/collections").then((r) => setAllCollections(r.data)).catch(() => {});
  }, []);

  const save = async () => {
    const cleanFields = toApiFields(fields);
    if (cleanFields.length === 0) { toast.error("Serve almeno un attributo per i campi"); return; }
    setSaving(true);
    try {
      const payload = { fields: cleanFields, sub_item_fields: toApiFields(subFields) };
      if (maxItems.trim() === "") payload.clear_max_items = true;
      else payload.max_items = parseInt(maxItems, 10);
      if (maxSubItems.trim() === "") payload.clear_max_sub_items_per_item = true;
      else payload.max_sub_items_per_item = parseInt(maxSubItems, 10);
      await api.patch(`/collections/${collection.id}`, payload);
      toast.success("Attributi aggiornati");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent overlayClassName="bg-black/25" className="glass-panel glass-sheet border-0 rounded-[28px] text-white w-[calc(100%-24px)] max-w-lg max-h-[90vh] overflow-y-auto" data-testid="manage-fields-dialog">
        <DialogHeader><DialogTitle>Gestisci attributi — {collection.name}</DialogTitle></DialogHeader>

        <div className="space-y-5">
          <div>
            <div className="kicker mb-2">attributi dei campi (livello 2)</div>
            <FieldsEditor fields={fields} setFields={setFields} existingCollections={allCollections} />
          </div>
          <div className="pt-3 border-t">
            <div className="kicker mb-2">attributi degli elementi annidati (livello 3)</div>
            <FieldsEditor
              fields={subFields}
              setFields={setSubFields}
              existingCollections={allCollections}
              emptyHint='Non ancora configurati: nessun campo di questa lista mostrerà elementi annidati finché non ne aggiungi almeno uno (es. "persone" per una lezione, "commesse" per un cliente).'
            />
          </div>
          <div className="pt-3 border-t grid grid-cols-2 gap-3">
            <div>
              <div className="kicker mb-1">limite campi (livello 2)</div>
              <Input
                type="number" min="1" value={maxItems} onChange={(e) => setMaxItems(e.target.value)}
                placeholder="illimitato" data-testid="max-items-input" className="h-9 rounded-lg bg-white/10 text-sm"
              />
            </div>
            <div>
              <div className="kicker mb-1">limite elementi per campo</div>
              <Input
                type="number" min="1" value={maxSubItems} onChange={(e) => setMaxSubItems(e.target.value)}
                placeholder="illimitato" data-testid="max-sub-items-input" className="h-9 rounded-lg bg-white/10 text-sm"
              />
            </div>
            <div className="col-span-2 text-[11px] text-white/40">
              Lascia vuoto per nessun limite. Superato il limite, aggiungere un nuovo campo o elemento darà errore finché non ne elimini uno o alzi il limite.
            </div>
          </div>
        </div>

        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Salva attributi"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Form generico per creare/modificare un record (campo o elemento) secondo un elenco di
// CollectionFieldDef - usato sia a livello 2 sia a livello 3.
function ItemFormDialog({ title, fields, initialData, onClose, onSave }) {
  const [data, setData] = useState(initialData || {});
  const [saving, setSaving] = useState(false);
  const [refItems, setRefItems] = useState({}); // ref_collection_id -> items[]

  useEffect(() => {
    const refFields = (fields || []).filter((f) => f.type === "reference" && f.ref_collection_id);
    refFields.forEach(async (f) => {
      try {
        const r = await api.get(`/collections/${f.ref_collection_id}/items`);
        setRefItems((prev) => ({ ...prev, [f.ref_collection_id]: r.data }));
      } catch { /* ignore */ }
    });
  }, [fields]);

  const setField = (key, value) => setData((d) => ({ ...d, [key]: value }));

  const save = async () => {
    setSaving(true);
    try {
      await onSave(data);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent overlayClassName="bg-black/25" className="glass-panel glass-sheet border-0 rounded-[28px] text-white w-[calc(100%-24px)] max-w-lg max-h-[90vh] overflow-y-auto" data-testid="item-dialog">
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>

        <div className="space-y-3">
          {(fields || []).map((f) => (
            <div key={f.key}>
              <div className="kicker mb-1">{f.label}</div>
              {f.type === "textarea" && (
                <Textarea value={data[f.key] || ""} onChange={(e) => setField(f.key, e.target.value)} className="bg-white/10 border-0 rounded-xl min-h-[70px]" />
              )}
              {f.type === "select" && (
                <select value={data[f.key] || ""} onChange={(e) => setField(f.key, e.target.value)} className="w-full h-11 rounded-xl bg-white/10 px-3 text-white">
                  <option value="" className="text-black">—</option>
                  {(f.options || []).map((o) => <option key={o} value={o} className="text-black">{o}</option>)}
                </select>
              )}
              {f.type === "reference" && (
                <select value={data[f.key] || ""} onChange={(e) => setField(f.key, e.target.value)} className="w-full h-11 rounded-xl bg-white/10 px-3 text-white">
                  <option value="" className="text-black">—</option>
                  {(refItems[f.ref_collection_id] || []).map((it) => {
                    const firstVal = Object.values(it.data || {})[0] || it.id;
                    return <option key={it.id} value={it.id} className="text-black">{String(firstVal)}</option>;
                  })}
                </select>
              )}
              {(!f.type || ["text", "number", "date", "phone", "email"].includes(f.type)) && (
                <Input
                  type={f.type === "number" ? "number" : f.type === "date" ? "date" : f.type === "email" ? "email" : "text"}
                  value={data[f.key] || ""}
                  onChange={(e) => setField(f.key, e.target.value)}
                  className="h-11 rounded-xl bg-white/10 border-0"
                />
              )}
            </div>
          ))}
          {(fields || []).length === 0 && <div className="text-sm text-white/40">Nessun attributo definito.</div>}
        </div>

        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Salva"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
