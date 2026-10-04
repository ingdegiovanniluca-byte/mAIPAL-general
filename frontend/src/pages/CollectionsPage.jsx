import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { List, Plus, Trash2, Pencil, ArrowLeft, Users, Lock, X, ChevronRight, Settings2, Share2, Check, UserRound, Repeat } from "lucide-react";
import { toast } from "sonner";

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
  (label || "").toLowerCase().trim().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "campo";

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
      <div className="flex items-center justify-end mb-5">
        <RoundBtn icon={Plus} label="Nuova lista" testid="new-collection" onClick={() => setShowCreate(true)} big />
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}

      {!loading && collections.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">
          nessuna lista ancora — crea la tua prima lista (clienti, esercizi, commesse…)
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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
            {/* name, then on the right the lock/people icon and the bin side by side (never on top of each other) */}
            <div className="flex items-start gap-2 mb-2">
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
            <div className="text-sm text-white/70">{c.item_count || 0} campi</div>
            {sharingLabel(c) && <div className="text-[11px] text-white/85 mt-1 flex items-center gap-1" data-testid={`collection-sharing-${c.id}`}><Users size={11} className="shrink-0" />{sharingLabel(c)}</div>}
            <div className="text-[11px] text-white/60 mt-2">{(c.fields || []).map((f) => f.label).join(" · ")}</div>
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
function RoundBtn({ icon: Icon, label, onClick, testid, big = false }) {
  return (
    <button type="button" data-testid={testid} onClick={onClick} title={label} aria-label={label}
      className={`lg-glass shrink-0 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform ${big ? "h-12 w-12" : "h-11 w-11"}`}>
      <Icon size={big ? 24 : 19} strokeWidth={1.7} />
    </button>
  );
}

// One cell of the info under a list's name: a small label and its value below.
function InfoCell({ label, value, sub, icon: Icon, testid, grow = false }) {
  return (
    <div className={`min-w-0 ${grow ? "flex-1" : "shrink-0"}`} data-testid={testid}>
      <div className="text-[10.5px] uppercase tracking-[0.14em] text-white/60 flex items-center gap-1">{Icon && <Icon size={11} />}{label}</div>
      <div className="text-[14px] font-medium text-white mt-0.5 truncate">{value}</div>
      {sub && <div className="text-[11px] text-white/65 truncate">{sub}</div>}
    </div>
  );
}

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
    const next = { ...fl, ...patch };
    if (patch.label !== undefined && !fl.key) next.key = slugify(patch.label);
    return next;
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
  return fields.filter((f) => f.label.trim()).map((f) => ({
    key: f.key || slugify(f.label),
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

      <div className="font-semibold text-2xl">{coll.name}</div>
      {/* the list at a glance: how many campi, who it's shared with, the actions working on it */}
      <div className="mt-3 mb-5 flex items-start gap-6" data-testid="collection-info">
        <InfoCell label="Campi" value={loading ? "…" : items.length} testid="info-items" />
        <InfoCell label={shareInfo.label} value={shareInfo.value} icon={shareInfo.label === "Condivisa" ? Users : Lock} testid="collection-sharing" />
        {related.length > 0 && (
          <InfoCell label={related.length === 1 ? "Azione" : `Azioni · ${related.length}`} icon={Repeat} grow testid="info-actions"
            value={related[0].title} sub={related[0].schedule_label} />
        )}
      </div>

      {/* +, Gestisci attributi, Condividi: round glass buttons on one row, like the rest of the app */}
      <div className="flex items-center gap-2.5 mb-5" data-testid="collection-actions">
        <RoundBtn icon={Plus} label="Nuovo campo" testid="new-item" onClick={() => setEditing({})} />
        <RoundBtn icon={Settings2} label="Gestisci attributi" testid="manage-fields" onClick={() => setManagingFields(true)} />
        {canShare && <RoundBtn icon={Share2} label="Condividi" testid="share-collection" onClick={() => setSharing(true)} />}
        {selected.size > 0 && (
          <div className="ml-auto flex items-center gap-2">
            <button data-testid="clear-selection" onClick={() => setSelected(new Set())} className="h-11 px-3 rounded-full text-sm text-white/80">Annulla</button>
            <button data-testid="delete-selected" onClick={delSelected}
              className="lg-glass h-11 px-4 rounded-full flex items-center gap-2 text-sm text-white whitespace-nowrap">
              <Trash2 size={16} /> Elimina {selected.size}
            </button>
          </div>
        )}
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && items.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">nessun campo ancora</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((item) => (
          <div
            key={item.id}
            draggable
            onDragStart={(e) => { setDraggedId(item.id); e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => { e.preventDefault(); if (dragOverId !== item.id) setDragOverId(item.id); }}
            onDragLeave={() => setDragOverId((v) => (v === item.id ? null : v))}
            onDrop={(e) => { e.preventDefault(); reorderItems(draggedId, item.id); setDraggedId(null); setDragOverId(null); }}
            onDragEnd={() => { setDraggedId(null); setDragOverId(null); }}
            data-testid={`item-card-${item.id}`}
className={`lg-card p-4 pr-12 rounded-[22px] relative group cursor-grab active:cursor-grabbing transition-transform duration-150 ${dragOverId === item.id && draggedId !== item.id ? "ring-2 ring-white/40 scale-[1.02]" : ""} ${draggedId === item.id ? "opacity-50" : ""}`}
            // tap: while ticking campi it ticks this one too; otherwise opens it (its elementi) or edits it
            onClick={() => (selected.size ? toggleSelected(item.id) : hasSubLevel ? onOpenItem(item) : setEditing(item))}
          >
            {(coll.fields || []).slice(0, 5).map((f) => (
              item.data?.[f.key] ? (
                <div key={f.key} className="mb-1.5">
                  <div className="text-[10px] uppercase tracking-widest text-white/60">{f.label}</div>
                  <div className="text-sm">{String(item.data[f.key])}</div>
                </div>
              ) : null
            ))}
            {hasSubLevel && (
              <div className="flex items-center gap-1 text-[11px] text-white/70 mt-2">
                <ChevronRight size={12} /> {item.sub_item_count || 0} elementi
              </div>
            )}
            {/* round tick to select it (several at once, then "Elimina"); the pencil where a tap opens the elementi */}
            <div className="absolute top-3 right-3 flex flex-col items-center gap-1.5">
              <button type="button" data-testid={`select-item-${item.id}`} aria-pressed={selected.has(item.id)}
                aria-label={selected.has(item.id) ? "Deseleziona" : "Seleziona"}
                onClick={(e) => { e.stopPropagation(); toggleSelected(item.id); }}
                className={`h-6 w-6 rounded-full flex items-center justify-center transition-colors ${selected.has(item.id) ? "bg-white text-[#8E2F6B]" : "shadow-[inset_0_0_0_1.5px_rgba(255,255,255,0.75)]"}`}>
                {selected.has(item.id) && <Check size={14} strokeWidth={3} />}
              </button>
              {hasSubLevel && (
                <button type="button" onClick={(e) => { e.stopPropagation(); setEditing(item); }} aria-label="Modifica"
                  className="p-1 rounded-full text-white/70 hover:bg-white/10"><Pencil size={13} /></button>
              )}
            </div>
          </div>
        ))}
      </div>

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
  const [coll, setColl] = useState(collection);
  const [subItems, setSubItems] = useState([]);
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
    toast("Eliminare questo elemento?", {
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

      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <div className="kicker">· elementi di</div>
          <div className="font-semibold text-xl">{itemLabel}</div>
        </div>
        <button data-testid="new-sub-item" onClick={() => setEditing({})} className="pill-btn text-sm">
          <Plus size={14} /> Nuovo elemento
        </button>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && subItems.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">nessun elemento ancora</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {subItems.map((sub) => (
          <div key={sub.id} className="lg-card p-4 rounded-[22px] relative group">
            {(coll.sub_item_fields || []).slice(0, 5).map((f) => (
              sub.data?.[f.key] ? (
                <div key={f.key} className="mb-1.5">
                  <div className="text-[10px] uppercase tracking-widest text-white/60">{f.label}</div>
                  <div className="text-sm">{String(sub.data[f.key])}</div>
                </div>
              ) : null
            ))}
            <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={() => setEditing(sub)} className="p-1.5 rounded-full text-white/50 hover:bg-white/10"><Pencil size={13} /></button>
              <button onClick={() => delSub(sub)} className="p-1.5 rounded-full text-white/50 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={13} /></button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <ItemFormDialog
          title={editing.id ? "Modifica elemento" : "Nuovo elemento"}
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
