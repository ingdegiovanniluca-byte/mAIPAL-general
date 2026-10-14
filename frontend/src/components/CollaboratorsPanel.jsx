import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Send, Copy, Check, Pause, Play, RefreshCw, MessageCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/* Impostazioni > Collaboratori (Admin): people outside the app who only use Telegram - they
   write in the diario of the commesse enabled for them and ask about those commesse. Here the
   admin adds them, picks their commesse, sends the invitation (WhatsApp or copied) with the
   Telegram link and the code, suspends or removes them. */

const STATUS = {
  invited: { label: "Invitato", dot: "#F2C14E" },
  active: { label: "Collegato", dot: "#8ED973" },
  suspended: { label: "Sospeso", dot: "rgba(255,255,255,0.4)" },
};
const fmtDay = (iso) => (iso ? new Date(iso).toLocaleDateString("it-IT", { day: "numeric", month: "short" }) : "");

// The lists' selection dot.
function Dot({ on }) {
  return (
    <span className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
      {on && <Check size={12} strokeWidth={2.8} />}
    </span>
  );
}

function InviteBox({ invite }) {
  const copy = async () => {
    try { await navigator.clipboard.writeText(invite.message); toast.success("Messaggio copiato"); }
    catch { toast.error("Copia non riuscita: seleziona il testo e copialo"); }
  };
  return (
    <div className="space-y-3" data-testid="collab-invite">
      <div className="rounded-xl bg-white/10 p-3">
        <div className="kicker mb-1">codice · vale 7 giorni</div>
        <div className="font-mono-tight text-xl tracking-[0.25em] text-white" data-testid="collab-code">{invite.code}</div>
      </div>
      <div className="text-xs text-white/70 whitespace-pre-wrap rounded-xl bg-white/[0.07] p-3 max-h-48 overflow-y-auto" data-testid="collab-message">{invite.message}</div>
      <div className="flex flex-wrap gap-2">
        <a href={invite.whatsapp_url} target="_blank" rel="noreferrer" data-testid="collab-whatsapp"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium">
          <MessageCircle size={14} /> Invia su WhatsApp
        </a>
        <button type="button" onClick={copy} data-testid="collab-copy" className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm bg-white/15 text-white">
          <Copy size={14} /> Copia messaggio
        </button>
      </div>
    </div>
  );
}

function CollaboratorDialog({ initial, commesse, onClose, onSaved }) {
  const isNew = !initial?.id;
  const [f, setF] = useState(() => ({
    first_name: initial?.first_name || "", last_name: initial?.last_name || "", email: initial?.email || "",
    phone: initial?.phone || "", role: initial?.role || "", company: initial?.company || "",
    commesse: (initial?.commesse || []).map((c) => c.id), show_client_contacts: !!initial?.show_client_contacts,
  }));
  const [saving, setSaving] = useState(false);
  const [invite, setInvite] = useState(null);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const toggle = (id) => setF((x) => ({ ...x, commesse: x.commesse.includes(id) ? x.commesse.filter((c) => c !== id) : [...x.commesse, id] }));
  const groups = useMemo(() => {
    const by = new Map();
    commesse.filter((c) => c.stato !== "chiusa" || f.commesse.includes(c.id)).forEach((c) => {
      const g = by.get(c.client_name) || [];
      g.push(c);
      by.set(c.client_name, g);
    });
    return [...by.entries()].sort((a, b) => (a[0] || "").localeCompare(b[0] || ""));
  }, [commesse, f.commesse]);
  const save = async () => {
    if (!f.first_name.trim() || !f.last_name.trim()) { toast.error("Nome e cognome sono obbligatori"); return; }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) { toast.error("Email non valida"); return; }
    setSaving(true);
    try {
      if (isNew) {
        const r = await api.post("/collaborators", f);
        setInvite(r.data.invite);
        onSaved(false);
      } else {
        await api.patch(`/collaborators/${initial.id}`, f);
        onSaved(true);
      }
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };
  const field = "h-10 w-full rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none";
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg bg-[color:var(--app-bg)] max-h-[90vh] overflow-y-auto" data-testid="collab-dialog">
        <DialogHeader><DialogTitle>{invite ? "Invito pronto" : isNew ? "Nuovo collaboratore" : "Modifica collaboratore"}</DialogTitle></DialogHeader>
        {invite ? (
          <div className="space-y-4">
            <p className="text-sm text-white/75">Manda a {f.first_name} il link con il codice: aprendolo su Telegram si collega da solo.</p>
            <InviteBox invite={invite} />
            <div className="flex justify-end"><button onClick={onClose} className="px-4 py-2 rounded-full text-sm bg-white/15 text-white">Fatto</button></div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2.5">
              <input value={f.first_name} onChange={set("first_name")} placeholder="Nome" data-testid="collab-first" className={field} />
              <input value={f.last_name} onChange={set("last_name")} placeholder="Cognome" data-testid="collab-last" className={field} />
            </div>
            <input value={f.email} onChange={set("email")} placeholder="Email" type="email" data-testid="collab-email" className={field} />
            <input value={f.phone} onChange={set("phone")} placeholder="Telefono (facoltativo)" inputMode="tel" data-testid="collab-phone" className={field} />
            <div className="grid grid-cols-2 gap-2.5">
              <input value={f.role} onChange={set("role")} placeholder="Ruolo (es. idraulico)" data-testid="collab-role" className={field} />
              <input value={f.company} onChange={set("company")} placeholder="Azienda" data-testid="collab-company" className={field} />
            </div>
            <div>
              <div className="kicker mb-2">commesse abilitate</div>
              {groups.length === 0 ? (
                <div className="text-xs text-white/60">Nessuna commessa: le commesse stanno sotto ogni cliente nella lista Clienti.</div>
              ) : (
                <div className="space-y-3 max-h-64 overflow-y-auto pr-1" data-testid="collab-commesse">
                  {groups.map(([client, list]) => (
                    <div key={client}>
                      <div className="text-[11px] uppercase tracking-widest text-white/50 mb-1">{client || "Senza cliente"}</div>
                      {list.map((c) => (
                        <button key={c.id} type="button" onClick={() => toggle(c.id)} data-testid={`collab-commessa-${c.id}`}
                          className="w-full flex items-center gap-3 py-1.5 text-left text-sm text-white">
                          <Dot on={f.commesse.includes(c.id)} />
                          <span className="flex-1 min-w-0 truncate">{c.title}</span>
                          <span className="text-[11px] text-white/50">{c.stato}</span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <button type="button" onClick={() => setF((x) => ({ ...x, show_client_contacts: !x.show_client_contacts }))} data-testid="collab-contacts"
              className="w-full flex items-start gap-3 text-left text-sm text-white">
              <Dot on={f.show_client_contacts} />
              <span>Può vedere telefono ed email del cliente <span className="block text-xs text-white/55">Spento: nelle risposte su Telegram non compaiono mai.</span></span>
            </button>
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={onClose} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
              <button onClick={save} disabled={saving} data-testid="collab-save" className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">
                {saving ? "Salvo…" : isNew ? "Invita" : "Salva"}
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function CollaboratorsPanel() {
  const [list, setList] = useState(null);
  const [commesse, setCommesse] = useState([]);
  const [editing, setEditing] = useState(null);   // {} new | collaborator
  const [invite, setInvite] = useState(null);     // {name, invite}

  const load = async () => {
    try {
      const [a, b] = await Promise.all([api.get("/collaborators"), api.get("/jobs/commesse").catch(() => ({ data: [] }))]);
      setList(a.data || []);
      setCommesse(b.data || []);
    } catch { toast.error("Errore nel caricamento dei collaboratori"); setList([]); }
  };
  useEffect(() => { load(); }, []);

  const patch = async (c, body, ok) => {
    try { await api.patch(`/collaborators/${c.id}`, body); toast.success(ok); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const reinvite = async (c) => {
    try { const r = await api.post(`/collaborators/${c.id}/invite`); setInvite({ name: c.first_name, invite: r.data.invite }); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const del = (c) => toast(`Eliminare ${c.name}? Non potrà più scrivere; quello che ha scritto resta nel diario.`, {
    action: { label: "Elimina", onClick: async () => { try { await api.delete(`/collaborators/${c.id}`); toast.success("Collaboratore eliminato"); load(); } catch { toast.error("Errore"); } } },
    cancel: { label: "Annulla", onClick: () => {} }, duration: 7000,
  });

  return (
    <div data-testid="collaborators-panel">
      <p className="text-sm text-white/65 mb-4">
        Persone esterne (operai, subappaltatori) che usano solo Telegram: scrivono nel diario delle commesse che abiliti e
        chiedono informazioni su quelle. Non hanno accesso all'app.
      </p>
      <button type="button" onClick={() => setEditing({})} data-testid="collab-new"
        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm bg-white/15 text-white mb-4">
        <Plus size={14} /> Nuovo collaboratore
      </button>
      {list === null ? <div className="kicker">caricamento…</div> : list.length === 0 ? (
        <div className="text-sm text-white/55" data-testid="collab-empty">Nessun collaboratore ancora.</div>
      ) : (
        <div className="space-y-3">
          {list.map((c) => {
            const st = STATUS[c.status] || STATUS.invited;
            return (
              <div key={c.id} className="rounded-2xl bg-white/[0.08] border border-white/10 p-4" data-testid="collab-card">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-white leading-snug">{c.name}</div>
                    <div className="text-xs text-white/60">{[c.role, c.company].filter(Boolean).join(" · ") || c.email}</div>
                  </div>
                  <span className="inline-flex items-center gap-1.5 text-[11px] text-white/80 shrink-0" data-testid="collab-status">
                    <span className="h-2 w-2 rounded-full" style={{ background: st.dot }} />{st.label}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {c.commesse.length ? c.commesse.map((j) => (
                    <span key={j.id} className={`text-[11px] px-2 py-0.5 rounded-md bg-white/10 ${j.stato === "chiusa" ? "text-white/45 line-through" : "text-white/85"}`}>{j.title} · {j.client_name}</span>
                  )) : <span className="text-[11px] text-white/50">Nessuna commessa abilitata</span>}
                </div>
                <div className="mt-2 text-[11px] text-white/50">
                  {c.status === "invited" ? (c.code ? `Codice valido fino al ${fmtDay(c.code_expires_at)}` : "Codice scaduto: manda un nuovo invito")
                    : c.last_message_at ? `Ultimo messaggio ${fmtDay(c.last_message_at)}` : c.linked_at ? `Collegato il ${fmtDay(c.linked_at)}` : ""}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <button onClick={() => setEditing(c)} data-testid="collab-edit" className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15"><Pencil size={11} /> Modifica</button>
                  <button onClick={() => reinvite(c)} data-testid="collab-reinvite" className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15">
                    {c.status === "invited" ? <><Send size={11} /> Invito</> : <><RefreshCw size={11} /> Nuovo codice</>}
                  </button>
                  {c.status === "active" && <button onClick={() => patch(c, { status: "suspended" }, "Collaboratore sospeso")} data-testid="collab-suspend" className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15"><Pause size={11} /> Sospendi</button>}
                  {c.status === "suspended" && <button onClick={() => patch(c, { status: "active" }, "Collaboratore riattivato")} data-testid="collab-resume" className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15"><Play size={11} /> Riattiva</button>}
                  <button onClick={() => del(c)} data-testid="collab-delete" className="ml-auto p-1.5 text-white/55 hover:text-white" title="Elimina"><Trash2 size={14} /></button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {editing && <CollaboratorDialog initial={editing} commesse={commesse} onClose={() => { setEditing(null); load(); }}
        onSaved={(close) => { if (close) { setEditing(null); toast.success("Collaboratore aggiornato"); } load(); }} />}
      {invite && (
        <Dialog open onOpenChange={() => setInvite(null)}>
          <DialogContent className="max-w-lg bg-[color:var(--app-bg)]" data-testid="collab-reinvite-dialog">
            <DialogHeader><DialogTitle>Nuovo codice per {invite.name}</DialogTitle></DialogHeader>
            <p className="text-sm text-white/70">Il codice precedente non vale più.</p>
            <InviteBox invite={invite.invite} />
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
