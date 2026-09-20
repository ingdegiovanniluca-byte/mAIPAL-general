import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { List, Plus, Trash2, Pencil, ArrowLeft, Users, Lock, X, ChevronRight, Settings2 } from "lucide-react";
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
  const { user } = useAuth();
  const [collections, setCollections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState({ level: 1 }); // {level:1} | {level:2, collection} | {level:3, collection, item}
  const [showCreate, setShowCreate] = useState(false);

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
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <List size={20} className="text-white/70" />
          <div className="kicker">le tue liste</div>
        </div>
        <button data-testid="new-collection" onClick={() => setShowCreate(true)} className="pill-btn text-sm">
          <Plus size={14} /> Nuova lista
        </button>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}

      {!loading && collections.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">
          nessuna lista ancora — crea la tua prima lista (clienti, esercizi, commesse…)
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {collections.map((c) => (
          <div key={c.id} className="card-soft card-hover p-5 rounded-2xl cursor-pointer relative group" onClick={() => setView({ level: 2, collection: c })}>
            <div className="flex items-start justify-between mb-2">
              <div className="font-semibold text-lg">{c.name}</div>
              {c.visibility === "org" ? <Users size={14} className="text-white/40 mt-1" title="Condivisa col team" /> : <Lock size={14} className="text-white/30 mt-1" title="Privata" />}
            </div>
            <div className="text-sm text-white/50">{c.item_count || 0} campi</div>
            <div className="text-[11px] text-white/35 mt-2">{(c.fields || []).map((f) => f.label).join(" · ")}</div>
            <button
              onClick={(e) => { e.stopPropagation(); del(c); }}
              className="absolute top-3 right-3 p-1.5 rounded-full text-white/0 group-hover:text-white/40 hover:!text-red-400 hover:bg-red-500/10 transition-colors"
              title="Elimina lista"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      {showCreate && (
        <CreateCollectionDialog
          hasOrg={!!user?.org_id}
          existingCollections={collections}
          onClose={() => setShowCreate(false)}
          onCreated={async (c) => { setShowCreate(false); await load(); setView({ level: 2, collection: c }); }}
        />
      )}
    </div>
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
        <Users size={13} /> Condivisa col team
      </button>
    </div>
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

function CreateCollectionDialog({ hasOrg, existingCollections, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState("private");
  const [fields, setFields] = useState([{ key: "nome", label: "Nome", type: "text" }]);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim()) { toast.error("Dai un nome alla lista"); return; }
    const cleanFields = toApiFields(fields);
    if (cleanFields.length === 0) { toast.error("Aggiungi almeno un attributo"); return; }
    setSaving(true);
    try {
      const r = await api.post("/collections", { name: name.trim(), visibility, fields: cleanFields });
      toast.success("Lista creata");
      onCreated(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="create-collection-dialog">
        <DialogHeader><DialogTitle>Nuova lista</DialogTitle></DialogHeader>

        <div className="space-y-4">
          <div>
            <div className="kicker mb-1">nome lista</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Clienti, Esercizi, Commesse…" className="h-11 rounded-xl bg-white/10" />
          </div>

          <VisibilityToggle hasOrg={hasOrg} visibility={visibility} onChange={setVisibility} />

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

  const delItem = (item) => {
    toast("Eliminare questo campo?", {
      action: {
        label: "Elimina",
        onClick: async () => {
          try {
            await api.delete(`/collections/${coll.id}/items/${item.id}`);
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
        <ArrowLeft size={14} /> Liste
      </button>

      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="font-semibold text-xl">{coll.name}</div>
        <div className="flex items-center gap-2">
          <button data-testid="manage-fields" onClick={() => setManagingFields(true)} className="pill-btn text-sm bg-white/10 text-white">
            <Settings2 size={14} /> Gestisci attributi
          </button>
          <button data-testid="new-item" onClick={() => setEditing({})} className="pill-btn text-sm">
            <Plus size={14} /> Nuovo campo
          </button>
        </div>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && items.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">nessun campo ancora</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((item) => (
          <div
            key={item.id}
            className={`card-soft p-4 rounded-2xl relative group ${hasSubLevel ? "cursor-pointer card-hover" : ""}`}
            onClick={hasSubLevel ? () => onOpenItem(item) : undefined}
          >
            {(coll.fields || []).slice(0, 5).map((f) => (
              item.data?.[f.key] ? (
                <div key={f.key} className="mb-1.5">
                  <div className="text-[10px] uppercase tracking-widest text-white/40">{f.label}</div>
                  <div className="text-sm">{String(item.data[f.key])}</div>
                </div>
              ) : null
            ))}
            {hasSubLevel && (
              <div className="flex items-center gap-1 text-[11px] text-white/50 mt-2">
                <ChevronRight size={12} /> {item.sub_item_count || 0} elementi
              </div>
            )}
            <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={(e) => { e.stopPropagation(); setEditing(item); }} className="p-1.5 rounded-full text-white/50 hover:bg-white/10"><Pencil size={13} /></button>
              <button onClick={(e) => { e.stopPropagation(); delItem(item); }} className="p-1.5 rounded-full text-white/50 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={13} /></button>
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
          <div key={sub.id} className="card-soft p-4 rounded-2xl relative group">
            {(coll.sub_item_fields || []).slice(0, 5).map((f) => (
              sub.data?.[f.key] ? (
                <div key={f.key} className="mb-1.5">
                  <div className="text-[10px] uppercase tracking-widest text-white/40">{f.label}</div>
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
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="manage-fields-dialog">
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
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="item-dialog">
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>

        <div className="space-y-3">
          {(fields || []).map((f) => (
            <div key={f.key}>
              <div className="kicker mb-1">{f.label}</div>
              {f.type === "textarea" && (
                <Textarea value={data[f.key] || ""} onChange={(e) => setField(f.key, e.target.value)} className="bg-white/10 rounded-xl min-h-[70px]" />
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
              {["text", "number", "date", "phone", "email"].includes(f.type) && (
                <Input
                  type={f.type === "number" ? "number" : f.type === "date" ? "date" : f.type === "email" ? "email" : "text"}
                  value={data[f.key] || ""}
                  onChange={(e) => setField(f.key, e.target.value)}
                  className="h-11 rounded-xl bg-white/10"
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
