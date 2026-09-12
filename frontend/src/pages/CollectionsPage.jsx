import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { List, Plus, Trash2, Pencil, ArrowLeft, Users, Lock, X } from "lucide-react";
import { toast } from "sonner";

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
  const [selected, setSelected] = useState(null);
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

  const del = async (coll) => {
    toast(`Eliminare "${coll.name}" e tutti i suoi elementi?`, {
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

  if (selected) {
    return <CollectionDetail collection={selected} onBack={() => { setSelected(null); load(); }} />;
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
          <div key={c.id} className="card-soft card-hover p-5 rounded-2xl cursor-pointer relative group" onClick={() => setSelected(c)}>
            <div className="flex items-start justify-between mb-2">
              <div className="font-semibold text-lg">{c.name}</div>
              {c.visibility === "org" ? <Users size={14} className="text-white/40 mt-1" title="Condivisa col team" /> : <Lock size={14} className="text-white/30 mt-1" title="Privata" />}
            </div>
            <div className="text-sm text-white/50">{c.item_count || 0} elementi</div>
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
          onCreated={async () => { setShowCreate(false); await load(); }}
        />
      )}
    </div>
  );
}

function CreateCollectionDialog({ hasOrg, existingCollections, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState("private");
  const [fields, setFields] = useState([{ key: "nome", label: "Nome", type: "text" }]);
  const [saving, setSaving] = useState(false);

  const addField = () => setFields((f) => [...f, { key: "", label: "", type: "text" }]);
  const removeField = (i) => setFields((f) => f.filter((_, idx) => idx !== i));
  const updateField = (i, patch) => setFields((f) => f.map((fl, idx) => {
    if (idx !== i) return fl;
    const next = { ...fl, ...patch };
    if (patch.label !== undefined) next.key = slugify(patch.label);
    return next;
  }));

  const save = async () => {
    if (!name.trim()) { toast.error("Dai un nome alla lista"); return; }
    const cleanFields = fields.filter((f) => f.label.trim());
    if (cleanFields.length === 0) { toast.error("Aggiungi almeno un campo"); return; }
    setSaving(true);
    try {
      await api.post("/collections", {
        name: name.trim(),
        visibility,
        fields: cleanFields.map((f) => ({
          key: f.key || slugify(f.label),
          label: f.label.trim(),
          type: f.type,
          options: f.type === "select" ? (f.optionsText || "").split(",").map((s) => s.trim()).filter(Boolean) : null,
          ref_collection_id: f.type === "reference" ? (f.ref_collection_id || null) : null,
        })),
      });
      toast.success("Lista creata");
      onCreated();
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

          {hasOrg && (
            <div className="flex gap-2">
              <button onClick={() => setVisibility("private")} className={`flex-1 py-2 rounded-xl text-sm flex items-center justify-center gap-1.5 ${visibility === "private" ? "bg-[#CECAD0] text-[#403A3C]" : "bg-white/10 text-white/60"}`}>
                <Lock size={13} /> Privata
              </button>
              <button onClick={() => setVisibility("org")} className={`flex-1 py-2 rounded-xl text-sm flex items-center justify-center gap-1.5 ${visibility === "org" ? "bg-[#CECAD0] text-[#403A3C]" : "bg-white/10 text-white/60"}`}>
                <Users size={13} /> Condivisa col team
              </button>
            </div>
          )}

          <div>
            <div className="kicker mb-2">campi</div>
            <div className="space-y-2">
              {fields.map((f, i) => (
                <div key={i} className="flex gap-2 items-start bg-white/5 rounded-xl p-2.5">
                  <div className="flex-1 space-y-2">
                    <Input value={f.label} onChange={(e) => updateField(i, { label: e.target.value })} placeholder="Nome campo (es. Telefono)" className="h-9 rounded-lg bg-white/10 text-sm" />
                    <div className="flex gap-2">
                      <select
                        value={f.type}
                        onChange={(e) => updateField(i, { type: e.target.value })}
                        className="h-9 rounded-lg bg-white/10 text-sm px-2 flex-1 text-white"
                      >
                        {FIELD_TYPES.map((t) => <option key={t.value} value={t.value} className="text-black">{t.label}</option>)}
                      </select>
                    </div>
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
            <button onClick={addField} className="mt-2 text-sm text-white/60 hover:text-white flex items-center gap-1"><Plus size={13} /> Aggiungi campo</button>
          </div>
        </div>

        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Crea lista"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CollectionDetail({ collection, onBack }) {
  const [coll, setColl] = useState(collection);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // item being edited, or {} for new

  const load = async () => {
    try {
      const [c, it] = await Promise.all([
        api.get(`/collections/${coll.id}`),
        api.get(`/collections/${coll.id}/items`),
      ]);
      setColl(c.data);
      setItems(it.data);
    } catch {
      toast.error("Errore nel caricamento della lista");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const delItem = async (item) => {
    toast("Eliminare questo elemento?", {
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
        <button data-testid="new-item" onClick={() => setEditing({})} className="pill-btn text-sm">
          <Plus size={14} /> Nuovo elemento
        </button>
      </div>

      {loading && <div className="text-center text-white/40 py-16 kicker">caricamento…</div>}
      {!loading && items.length === 0 && (
        <div className="text-center text-white/40 py-24 kicker">nessun elemento ancora</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((item) => (
          <div key={item.id} className="card-soft p-4 rounded-2xl relative group">
            {(coll.fields || []).slice(0, 5).map((f) => (
              item.data?.[f.key] ? (
                <div key={f.key} className="mb-1.5">
                  <div className="text-[10px] uppercase tracking-widest text-white/40">{f.label}</div>
                  <div className="text-sm">{String(item.data[f.key])}</div>
                </div>
              ) : null
            ))}
            <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={() => setEditing(item)} className="p-1.5 rounded-full text-white/50 hover:bg-white/10"><Pencil size={13} /></button>
              <button onClick={() => delItem(item)} className="p-1.5 rounded-full text-white/50 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={13} /></button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <ItemDialog
          collection={coll}
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load(); }}
        />
      )}
    </div>
  );
}

function ItemDialog({ collection, item, onClose, onSaved }) {
  const isNew = !item.id;
  const [data, setData] = useState(item.data || {});
  const [saving, setSaving] = useState(false);
  const [refItems, setRefItems] = useState({}); // ref_collection_id -> items[]

  useEffect(() => {
    const refFields = (collection.fields || []).filter((f) => f.type === "reference" && f.ref_collection_id);
    refFields.forEach(async (f) => {
      try {
        const r = await api.get(`/collections/${f.ref_collection_id}/items`);
        setRefItems((prev) => ({ ...prev, [f.ref_collection_id]: r.data }));
      } catch { /* ignore */ }
    });
  }, [collection]);

  const setField = (key, value) => setData((d) => ({ ...d, [key]: value }));

  const save = async () => {
    setSaving(true);
    try {
      if (isNew) {
        await api.post(`/collections/${collection.id}/items`, { data });
      } else {
        await api.patch(`/collections/${collection.id}/items/${item.id}`, { data });
      }
      toast.success("Salvato");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="item-dialog">
        <DialogHeader><DialogTitle>{isNew ? "Nuovo elemento" : "Modifica elemento"}</DialogTitle></DialogHeader>

        <div className="space-y-3">
          {(collection.fields || []).map((f) => (
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
        </div>

        <div className="flex justify-end mt-4">
          <button onClick={save} disabled={saving} className="pill-btn">{saving ? "…" : "Salva"}</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
