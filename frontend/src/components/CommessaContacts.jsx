import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Phone, Mail, Plus, Trash2, Pencil } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* The useful contacts of a commessa (artigiano): the other trades and people of the job -
   plumber, electrician, site manager, supplier... - with role, phone, e-mail and a note.
   Shown in the commessa's card of the Clienti list and in its diary. A name already used on
   another commessa fills in the rest by itself. */
export default function CommessaContacts({ commessaId, onChanged, testid = "commessa-contacts" }) {
  const [list, setList] = useState(null);
  const [editing, setEditing] = useState(null);   // {} new | contact

  const load = async () => {
    try { setList((await api.get(`/jobs/commesse/${commessaId}/contacts`)).data || []); }
    catch { setList([]); }
  };
  useEffect(() => { load(); }, [commessaId]);   // eslint-disable-line react-hooks/exhaustive-deps
  const saved = async () => { setEditing(null); await load(); onChanged?.(); };

  return (
    <div data-testid={testid}>
      <div className="flex items-center gap-2">
        <div className="text-[10px] uppercase tracking-widest text-white/50 flex-1">contatti utili</div>
        <button type="button" onClick={() => setEditing({})} data-testid="contact-add"
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15 text-xs text-white">
          <Plus size={11} /> Aggiungi
        </button>
      </div>
      {list === null ? <div className="text-xs text-white/45 py-1.5">caricamento…</div> : list.length === 0 ? (
        <div className="text-xs text-white/50 py-1.5" data-testid="contacts-empty">Nessun contatto: idraulico, elettricista, direttore lavori, fornitori…</div>
      ) : (
        <div className="mt-1">
          {list.map((c) => (
            <div key={c.id} className="py-2 border-b border-white/[0.08] last:border-b-0 flex items-start gap-2" data-testid="contact-row">
              <div className="min-w-0 flex-1">
                {c.role && <div className="text-[10.5px] uppercase tracking-wider text-white/50">{c.role}</div>}
                <div className="text-sm text-white font-medium break-words">{c.name}</div>
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5 text-xs">
                  {c.phone && <a href={`tel:${c.phone}`} onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 text-white/85 underline-offset-2 hover:underline"><Phone size={11} /> {c.phone}</a>}
                  {c.email && <a href={`mailto:${c.email}`} onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 text-white/85 underline-offset-2 hover:underline min-w-0 break-all"><Mail size={11} /> {c.email}</a>}
                </div>
                {c.note && <div className="text-[11.5px] text-white/55 mt-0.5 break-words">{c.note}</div>}
              </div>
              <button type="button" onClick={() => setEditing(c)} aria-label={`Modifica ${c.name}`} data-testid="contact-edit"
                className="p-1.5 -mr-1.5 rounded-full text-white/55 hover:text-white shrink-0"><Pencil size={13} /></button>
            </div>
          ))}
        </div>
      )}
      {editing && <ContactSheet contact={editing} commessaId={commessaId} onClose={() => setEditing(null)} onSaved={saved} />}
    </div>
  );
}

function ContactSheet({ contact, commessaId, onClose, onSaved }) {
  const isNew = !contact.id;
  const [f, setF] = useState({ role: contact.role || "", name: contact.name || "", phone: contact.phone || "", email: contact.email || "", note: contact.note || "" });
  const [dir, setDir] = useState({ contacts: [], roles: [] });
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/jobs/contacts/directory").then((r) => setDir(r.data)).catch(() => {}); }, []);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  // a name already used elsewhere: its role, phone and e-mail come along (only into empty fields)
  const pickName = (e) => {
    const name = e.target.value;
    const known = dir.contacts.find((c) => c.name.toLowerCase() === name.trim().toLowerCase());
    setF((x) => (known ? { ...x, name, role: x.role || known.role, phone: x.phone || known.phone, email: x.email || known.email } : { ...x, name }));
  };
  const save = async () => {
    if (!f.name.trim()) { toast.error("Scrivi il nome del contatto"); return; }
    setBusy(true);
    try {
      if (isNew) await api.post(`/jobs/commesse/${commessaId}/contacts`, f);
      else await api.patch(`/jobs/contacts/${contact.id}`, f);
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore nel salvataggio"); } finally { setBusy(false); }
  };
  const del = async () => {
    try { await api.delete(`/jobs/contacts/${contact.id}`); onSaved(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const field = "h-10 w-full min-w-0 rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none";
  return (
    <GlassBottomSheet onClose={onClose} testid="contact-sheet" className="max-h-[88vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-4">{isNew ? "Nuovo contatto" : "Contatto"}</div>
      <div className="space-y-2.5">
        <input value={f.role} onChange={set("role")} list="contact-roles" placeholder="Ruolo (es. idraulico)" data-testid="contact-role" className={field} />
        <datalist id="contact-roles">{dir.roles.map((r) => <option key={r} value={r} />)}</datalist>
        <input value={f.name} onChange={pickName} list="contact-names" placeholder="Nome o ditta" autoFocus={isNew} data-testid="contact-name" className={field} />
        <datalist id="contact-names">{dir.contacts.map((c) => <option key={`${c.name}-${c.phone}`} value={c.name}>{c.role}</option>)}</datalist>
        <div className="grid grid-cols-2 gap-2.5">
          <input value={f.phone} onChange={set("phone")} placeholder="Telefono" inputMode="tel" data-testid="contact-phone" className={field} />
          <input value={f.email} onChange={set("email")} placeholder="Email" type="email" data-testid="contact-email" className={field} />
        </div>
        <input value={f.note} onChange={set("note")} placeholder="Nota (facoltativa)" data-testid="contact-note" className={field} />
      </div>
      <div className="flex justify-end gap-2 mt-5">
        {!isNew && (
          <button onClick={del} data-testid="contact-delete" className="mr-auto px-3 py-2 rounded-full text-sm text-white/75 hover:bg-white/10 inline-flex items-center gap-1.5">
            <Trash2 size={14} /> Elimina
          </button>
        )}
        <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
        <button onClick={save} disabled={busy} data-testid="contact-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">
          {busy ? "Salvo…" : "Salva"}
        </button>
      </div>
    </GlassBottomSheet>
  );
}
