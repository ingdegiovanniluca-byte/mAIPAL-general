import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Send, Copy, Check, Pause, Play, RefreshCw, MessageCircle, Minus, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

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

// The lists' selection dot; "some" (a client with part of its commesse) shows a dash.
function Dot({ on, some = false }) {
  return (
    <span className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${on || some ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
      {on ? <Check size={12} strokeWidth={2.8} /> : some ? <Minus size={12} strokeWidth={2.8} /> : null}
    </span>
  );
}

// A client in "commesse abilitate": its dot picks (or drops) all its commesse at once, the
// arrow opens it on its commesse to pick them one by one.
function ClientGroup({ client, list, selected, onSet }) {
  const [open, setOpen] = useState(false);
  const n = list.filter((c) => selected.includes(c.id)).length;
  const all = n === list.length;
  return (
    <div className="border-t border-white/[0.16] first:border-t-0" data-testid="collab-client" data-open={open ? "1" : "0"}>
      <div className="flex items-center gap-3 py-2">
        <button type="button" onClick={() => onSet(list.map((c) => c.id), !all)} aria-pressed={all} data-testid="collab-client-toggle"
          className="flex-1 min-w-0 flex items-center gap-3 text-left">
          <Dot on={all} some={n > 0 && !all} />
          <span className="min-w-0">
            <span className="block text-sm font-medium text-white truncate">{client || "Senza cliente"}</span>
            <span className="block text-[11px] text-white/55" data-testid="collab-client-count">
              {n ? `${n} di ${list.length} ${list.length === 1 ? "commessa" : "commesse"}` : `${list.length} ${list.length === 1 ? "commessa" : "commesse"}`}
            </span>
          </span>
        </button>
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} data-testid="collab-client-expand"
          aria-label={open ? "Nascondi le commesse" : "Mostra le commesse"} className="p-1.5 -mr-1.5 rounded-full text-white/70 hover:bg-white/10">
          <ChevronDown size={17} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
      {open && (
        <div className="pl-8 pb-1.5">
          {list.map((c) => (
            <button key={c.id} type="button" onClick={() => onSet([c.id], !selected.includes(c.id))} data-testid={`collab-commessa-${c.id}`}
              className="w-full flex items-center gap-3 py-1.5 text-left text-sm text-white">
              <Dot on={selected.includes(c.id)} />
              <span className="flex-1 min-w-0 truncate">{c.title}</span>
              <span className="text-[11px] text-white/50 shrink-0">{c.stato}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// The same frosted glass as the "+" menu and the profile menu, as a sheet from the bottom:
// as wide as the screen (never wider - no sideways scrolling), long content scrolls up and down.
function GlassSheet({ title, onClose, testid, children }) {
  return (
    <GlassBottomSheet onClose={onClose} testid={testid} className="max-h-[88vh] md:left-1/2 md:right-auto md:w-[520px] md:-translate-x-1/2 md:bottom-8">
      <div className="text-lg font-semibold text-white mb-4">{title}</div>
      {children}
    </GlassBottomSheet>
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
      <div className="text-xs text-white/70 whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-xl bg-white/[0.07] p-3" data-testid="collab-message">{invite.message}</div>
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
    hourly_rate: initial?.hourly_rate != null ? String(initial.hourly_rate).replace(".", ",") : "",
  }));
  const [saving, setSaving] = useState(false);
  const [invite, setInvite] = useState(null);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const pick = (ids, on) => setF((x) => ({
    ...x, commesse: on ? [...new Set([...x.commesse, ...ids])] : x.commesse.filter((c) => !ids.includes(c)),
  }));
  const groups = useMemo(() => {
    const by = new Map();
    commesse.filter((c) => c.stato !== "chiusa" || f.commesse.includes(c.id)).forEach((c) => {
      const key = c.client_item_id || c.client_name;
      const g = by.get(key) || { client: c.client_name, list: [] };
      g.list.push(c);
      by.set(key, g);
    });
    return [...by.entries()].sort((a, b) => (a[1].client || "").localeCompare(b[1].client || ""));
  }, [commesse, f.commesse]);
  const save = async () => {
    if (!f.first_name.trim() || !f.last_name.trim()) { toast.error("Nome e cognome sono obbligatori"); return; }
    if (f.email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) { toast.error("Email non valida"); return; }
    const typed = f.hourly_rate.trim().replace(/\s|€/g, "");
    const rate = typed ? Number(typed.includes(",") ? typed.replace(/\./g, "").replace(",", ".") : typed) : null;
    if (rate !== null && !(rate >= 0)) { toast.error("Costo orario non valido"); return; }
    const body = { ...f, hourly_rate: rate, ...(rate === null && !isNew ? { clear_hourly_rate: true } : {}) };
    setSaving(true);
    try {
      if (isNew) {
        const r = await api.post("/collaborators", body);
        setInvite(r.data.invite);
        onSaved(false);
      } else {
        await api.patch(`/collaborators/${initial.id}`, body);
        onSaved(true);
      }
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setSaving(false); }
  };
  const field = "h-10 w-full min-w-0 rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none";
  return (
    <GlassSheet title={invite ? "Invito pronto" : isNew ? "Nuovo collaboratore" : "Modifica collaboratore"} onClose={onClose} testid="collab-dialog">
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
            <div>
              <input value={f.phone} onChange={set("phone")} placeholder="Cellulare (es. 333 1234567)" inputMode="tel" data-testid="collab-phone" className={field} />
              <div className="text-[11px] text-white/50 mt-1 px-1">Per i cellulari italiani il +39 non serve; per un numero estero scrivi il prefisso (es. +41 …). Serve per mandare l'invito su WhatsApp.</div>
            </div>
            <input value={f.email} onChange={set("email")} placeholder="Email (facoltativa)" type="email" data-testid="collab-email" className={field} />
            <div className="grid grid-cols-2 gap-2.5">
              <input value={f.role} onChange={set("role")} placeholder="Ruolo (es. idraulico)" data-testid="collab-role" className={field} />
              <input value={f.company} onChange={set("company")} placeholder="Azienda" data-testid="collab-company" className={field} />
            </div>
            <div>
              <div className="relative">
                <input value={f.hourly_rate} onChange={set("hourly_rate")} placeholder="Costo orario (facoltativo)" inputMode="decimal" data-testid="collab-rate" className={`${field} pr-12`} />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-white/50">€/h</span>
              </div>
              <div className="text-[11px] text-white/50 mt-1 px-1">Lo uso per le sue ore nei Costi delle commesse; puoi cambiarlo anche dal diario, in Costi.</div>
            </div>
            <div>
              <div className="kicker mb-2">commesse abilitate</div>
              {groups.length === 0 ? (
                <div className="text-xs text-white/60">Nessuna commessa: le commesse stanno sotto ogni cliente nella lista Clienti.</div>
              ) : (
                <div data-testid="collab-commesse">
                  {groups.map(([key, g]) => (
                    <ClientGroup key={key} client={g.client} list={g.list} selected={f.commesse} onSet={pick} />
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
    </GlassSheet>
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
      setCommesse((b.data || []).filter((c) => !c.shared));   // (a team-mate's commesse: their collaborators)
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
                    <div className="text-xs text-white/60">{[c.role, c.company, c.hourly_rate != null && `${String(c.hourly_rate).replace(".", ",")} €/h`].filter(Boolean).join(" · ") || c.phone || c.email}</div>
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
        <GlassSheet title={`Nuovo codice per ${invite.name}`} onClose={() => setInvite(null)} testid="collab-reinvite-dialog">
          <p className="text-sm text-white/70 mb-3">Il codice precedente non vale più.</p>
          <InviteBox invite={invite.invite} />
        </GlassSheet>
      )}
    </div>
  );
}
