import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Mail, Trash2, Copy, RefreshCw, Loader2, Users, KeyRound, Check, X } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import OrganizationPage, { teamCard, GroupTitle, PersonRow } from "@/pages/OrganizationPage";
import { Field, Input, INPUT, PRIMARY, SECONDARY } from "@/components/FormFields";
import { StatTiles, StatTile } from "@/components/StatTiles";

/* Impostazioni > Team. Everyone sees their own team (or joins one with a code); the admin also
   creates the teams ("Nuovo team") and manages them: name, code, members, invitations. */
export default function TeamPanel() {
  const { user } = useAuth();
  const [org, setOrg] = useState(null);
  if (user?.role !== "admin") {
    return (
      <div className="space-y-3">
        <TeamStats org={org} />
        <OrganizationPage onOrg={setOrg} />
      </div>
    );
  }
  return <TeamsAdmin />;
}

// on top: how many teams (created in the organization, for its administrator) and how many you are in
function TeamStats({ org, created }) {
  const teams = org?.teams || [];
  const activeMembers = (org?.members || []).length;
  return (
    <div className={teamCard} data-testid="team-stats">
      <StatTiles>
        {created ? <StatTile label="Team creati" value={created.length} testid="team-stat-created" />
          : <StatTile label="Membri" value={activeMembers} testid="team-stat-members" />}
        <StatTile label="Fai parte di" value={teams.length} testid="team-stat-mine" />
        {created ? <StatTile label="Inviti inviati" value={created.reduce((n, t) => n + (t.invites || []).length, 0)} testid="team-stat-sent" />
          : <StatTile label="Inviti" value={(org?.invites || []).length} testid="team-stat-invites" />}
      </StatTiles>
      <div className="text-[11px] text-white/55 mt-4">
        {created ? "Team creati nell'organizzazione, quelli di cui fai parte, inviti in attesa di risposta."
          : `Membri del team attivo${org?.name ? ` «${org.name}»` : ""}, team di cui fai parte, inviti ricevuti.`}
      </div>
    </div>
  );
}

function TeamsAdmin() {
  const { refresh } = useAuth();
  const [teams, setTeams] = useState(null);
  const [org, setOrg] = useState(null);
  const [mine, setMine] = useState(0);   // reloads "your teams" when the admin changes them
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try { setTeams((await api.get("/admin/teams")).data || []); }
    catch { toast.error("Errore nel caricamento dei team"); setTeams([]); }
    setMine((n) => n + 1);
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    const n = name.trim();
    if (!n) { toast.error("Scrivi il nome del team"); return; }
    setBusy(true);
    try {
      await api.post("/admin/teams", { name: n });
      toast.success(`Team "${n}" creato: ne fai già parte`);
      setName(""); setCreating(false);
      await Promise.all([load(), refresh()]);
    } catch (e) { toast.error(e?.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };

  return (
    <div data-testid="teams-admin" className="space-y-3">
      <TeamStats org={org} created={teams || []} />
      <div className="pt-2"><GroupTitle>Il tuo team</GroupTitle></div>
      <OrganizationPage reloadKey={mine} onOrg={setOrg} />
      <div className="pt-3"><GroupTitle>Gestisci i team</GroupTitle></div>
      {creating ? (
        <div className={teamCard} data-testid="new-team-sheet">
          <Field label="Nome del nuovo team" hint="Ne fai parte subito; gli altri entrano con il codice o con un invito.">
            <Input icon={Users} autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()}
              placeholder="Es. Squadra impianti" data-testid="new-team-name" />
          </Field>
          <div className="grid grid-cols-2 gap-3 mt-4">
            <button type="button" onClick={() => { setCreating(false); setName(""); }} onMouseDown={keepFocus} className={SECONDARY}>Annulla</button>
            <button type="button" onClick={create} onMouseDown={keepFocus} disabled={busy} data-testid="create-team-btn" className={PRIMARY}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Crea team
            </button>
          </div>
        </div>
      ) : (
        <button type="button" data-testid="new-team" onClick={() => setCreating(true)}
          className="w-full h-11 rounded-xl border border-dashed border-white/25 text-[13px] text-white/80 inline-flex items-center justify-center gap-1.5">
          <Plus size={15} /> Nuovo team
        </button>
      )}
      {teams === null ? <div className="kicker">caricamento…</div> : (
        <>
          {teams.length === 0 && <div className="text-sm text-white/60">Nessun team ancora.</div>}
          {teams.map((t) => <TeamCard key={t.id} team={t} onChanged={load} />)}
        </>
      )}
    </div>
  );
}

// a button tapped while typing: the field keeps the focus (the bottom bar doesn't come back under the finger)
const keepFocus = (e) => e.preventDefault();
const ICON_BTN = "h-9 w-9 shrink-0 rounded-lg bg-white/10 border border-white/15 flex items-center justify-center text-white/75 disabled:opacity-50";

function TeamCard({ team, onChanged }) {
  const [name, setName] = useState(team.name);
  const [inviteEmail, setInviteEmail] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setName(team.name); }, [team.name]);
  const members = team.members || [];
  const invites = team.invites || [];

  const renameTeam = async () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === team.name) { setName(team.name); return; }
    try {
      await api.patch(`/admin/teams/${team.id}`, { name: trimmed });
      onChanged();
      toast.success("Nome team aggiornato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); setName(team.name); }
  };
  const regenerateCode = () => toast("Fare un nuovo codice? Quello vecchio non funziona più.", {
    action: { label: "Nuovo codice", onClick: async () => {
      try { await api.post(`/admin/teams/${team.id}/regenerate-code`); onChanged(); toast.success("Nuovo codice generato"); }
      catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    } },
    cancel: { label: "Annulla", onClick: () => {} }, duration: 8000 });
  const copyCode = () => {
    navigator.clipboard?.writeText(team.join_code);
    toast.success("Codice copiato");
  };
  const deleteTeam = () => {
    toast(`Eliminare il team "${team.name}"?`, {
      description: "I membri verranno rimossi dal team. I loro dati non vengono toccati.",
      action: {
        label: "Elimina",
        onClick: async () => {
          try {
            await api.delete(`/admin/teams/${team.id}`);
            onChanged();
            toast.success("Team eliminato");
          } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 8000,
    });
  };
  const invite = async () => {
    const email = inviteEmail.trim().toLowerCase();
    if (!email || !email.includes("@")) { toast.error("Email non valida"); return; }
    setBusy(true);
    try {
      await api.post(`/admin/teams/${team.id}/invites`, { email });
      setInviteEmail("");
      onChanged();
      toast.success(`${email} invitata`);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  const removeInvite = async (email) => {
    try {
      await api.delete(`/admin/teams/${team.id}/invites/${encodeURIComponent(email)}`);
      onChanged();
      toast.success("Invito rimosso");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const removeMember = (m) => toast(`Togliere ${m.name || m.email} dal team?`, {
    action: { label: "Togli", onClick: async () => {
      try { await api.delete(`/admin/teams/${team.id}/members/${m.user_id}`); onChanged(); toast.success("Membro rimosso dal team"); }
      catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    } },
    cancel: { label: "Annulla", onClick: () => {} }, duration: 8000 });

  return (
    <div className={`${teamCard} flex flex-col gap-4`} data-testid="team-card">
      <Field label="Nome del team">
        <Input icon={Users} value={name} onChange={(e) => setName(e.target.value)} onBlur={renameTeam} onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          aria-label="Nome del team" data-testid="team-name" />
      </Field>
      <Field label="Codice per entrare" hint="Dallo a chi deve entrare: lo scrive in Impostazioni → Team.">
        <div className="relative" data-testid="team-code">
          <KeyRound size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/50 pointer-events-none" />
          <div className={`${INPUT} pl-10 pr-[92px] flex items-center font-mono font-semibold tracking-[0.2em]`}>{team.join_code}</div>
          <div className="absolute right-1 top-1/2 -translate-y-1/2 flex gap-1">
            <button type="button" onClick={copyCode} className={ICON_BTN} title="Copia il codice" aria-label="Copia il codice"><Copy size={14} /></button>
            <button type="button" onClick={regenerateCode} className={ICON_BTN} title="Nuovo codice" aria-label="Nuovo codice" data-testid="team-code-new"><RefreshCw size={14} /></button>
          </div>
        </div>
      </Field>
      <Field label={`Membri (${members.length})`}>
        <div>
          {members.length === 0 && <div className="text-[12px] text-white/45">Nessun membro</div>}
          {members.map((m) => (
            <PersonRow key={m.user_id} m={m}>
              <button type="button" onClick={() => removeMember(m)} className={ICON_BTN} title="Togli dal team" aria-label={`Togli ${m.name || m.email} dal team`}>
                <X size={14} /></button>
            </PersonRow>
          ))}
        </div>
      </Field>
      <Field label="Invita per email" hint={invites.length ? null : "Riceve l'invito in Impostazioni → Team quando entra con questa email."}>
        <form className="relative" onSubmit={(e) => { e.preventDefault(); invite(); }}>
          <Input icon={Mail} type="email" inputMode="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="nome@azienda.it"
            className="pr-[84px]" data-testid="team-invite-email" />
          <button type="submit" disabled={busy || !inviteEmail.trim()} data-testid="team-invite-btn" onMouseDown={keepFocus}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 h-8 px-3 rounded-lg bg-white/85 text-[#7A2A5C] text-xs font-semibold disabled:opacity-50 inline-flex items-center gap-1">
            {busy ? <Loader2 size={13} className="animate-spin" /> : "Invita"}</button>
        </form>
        {invites.length > 0 && (
          <div className="mt-1" data-testid="team-invites">
            <div className="text-[11px] text-white/55 mb-0.5">In attesa di risposta</div>
            {invites.map((inv) => (
              <div key={inv.email} className="flex items-center gap-3 py-2 border-t border-white/10 first:border-t-0">
                <Mail size={15} className="text-white/45 shrink-0" />
                <div className="flex-1 min-w-0 text-sm text-white/85 truncate">{inv.email}</div>
                <button type="button" onClick={() => removeInvite(inv.email)} className={ICON_BTN} title="Annulla l'invito" aria-label={`Annulla l'invito a ${inv.email}`}><X size={14} /></button>
              </div>
            ))}
          </div>
        )}
      </Field>
      <button type="button" onClick={deleteTeam} data-testid="team-delete" className={`${SECONDARY} w-full text-red-300`}>
        <Trash2 size={15} /> Elimina il team
      </button>
    </div>
  );
}
