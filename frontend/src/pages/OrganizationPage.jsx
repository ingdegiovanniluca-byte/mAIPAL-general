import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Users, LogOut, KeyRound, Loader2, Check } from "lucide-react";
import { toast } from "sonner";
import { Field, Input, Select, PRIMARY, SECONDARY } from "@/components/FormFields";

// a team's card (the Profilo's style); the small title above a group of cards
export const teamCard = "card-soft p-5";
export function GroupTitle({ children }) {
  return <div className="text-[13px] font-semibold text-white mb-2 mt-1">{children}</div>;
}
export function MembersCount({ n }) {
  return (
    <span className="shrink-0 inline-flex items-center gap-1 text-xs text-white/70" data-testid="team-members-count" title={`${n} ${n === 1 ? "membro" : "membri"}`}>
      <Users size={13} /> {n}
    </span>
  );
}
// a person of the team: the photo (or the initial), the name, the e-mail
export function PersonRow({ m, me, children }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-t border-white/10 first:border-t-0" data-testid="team-person">
      {m.picture ? (
        <img src={m.picture} alt="" className="h-9 w-9 rounded-full object-cover shrink-0" />
      ) : (
        <div className="h-9 w-9 rounded-full bg-white/12 border border-white/15 flex items-center justify-center text-[13px] font-semibold shrink-0">
          {(m.name || m.email || "?").charAt(0).toUpperCase()}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-white truncate">{m.name || m.email}{me ? " (tu)" : ""}</div>
        {m.name && m.email && <div className="text-[11px] text-white/50 truncate">{m.email}</div>}
      </div>
      {children}
    </div>
  );
}

// Sezione "Team" di Impostazioni, per tutti: gli inviti ricevuti (Accetta / Rifiuta, anche se sei
// già in un altro team), i tuoi team con quello attivo (le liste, le commesse e i task condivisi
// "con il team" sono del team attivo: lo cambi qui), i membri del team attivo e, per chi ha un
// codice, l'ingresso con il codice. La creazione dei team è dell'amministratore (components/TeamPanel).
export default function OrganizationPage({ reloadKey = 0 }) {
  const { user, refresh } = useAuth();
  const [org, setOrg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [joinCode, setJoinCode] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await api.get("/org");
      setOrg(r.data);
    } catch {
      toast.error("Errore nel caricamento del team");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); await Promise.all([load(), refresh()]); if (ok) toast.success(ok); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  const joinOrgCall = () => joinCode.trim() && run(async () => { await api.post("/org/join", { code: joinCode.trim() }); setJoinCode(""); }, "Ti sei unito al team");
  const accept = (inv) => run(() => api.post(`/org/invites/${inv.org_id}/accept`), `Ora fai parte del team «${inv.name}»`);
  const decline = (inv) => run(() => api.post(`/org/invites/${inv.org_id}/decline`), "Invito rifiutato");
  const activate = (t) => run(() => api.post("/org/switch", { org_id: t.id }), `Team attivo: «${t.name}»`);
  const leave = (t) => toast(`Uscire dal team «${t.name}»?`, {
    action: { label: "Esci", onClick: () => run(() => api.post("/org/leave", { org_id: t.id }), "Hai lasciato il team") },
    cancel: { label: "Annulla", onClick: () => {} },
    duration: 6000,
  });

  if (loading) return <div className="text-sm text-white/40">caricamento…</div>;
  const teams = org?.teams || [];
  const invites = org?.invites || [];
  const multi = teams.length > 1;
  const active = teams.find((t) => t.active);

  return (
    <div className="space-y-3">
      {invites.length > 0 && <GroupTitle>Inviti ricevuti</GroupTitle>}
      {invites.map((inv) => (
        <div key={inv.org_id} className={teamCard} data-testid="team-invite">
          <div className="text-lg font-semibold text-white truncate">{inv.name}</div>
          {inv.invited_by && <div className="text-[12px] text-white/55 mt-0.5">Ti ha invitato {inv.invited_by}</div>}
          <div className="grid grid-cols-2 gap-3 mt-4">
            <button type="button" disabled={busy} onClick={() => decline(inv)} data-testid="team-invite-decline" className={SECONDARY}>Rifiuta</button>
            <button type="button" disabled={busy} onClick={() => accept(inv)} data-testid="team-invite-accept" className={PRIMARY}><Check size={15} /> Accetta</button>
          </div>
        </div>
      ))}

      {org?.id && (
        <div className={teamCard} data-testid="my-team">
          {multi ? (
            <Field label="Team attivo" hint="Liste, commesse e task condivisi «con il team» sono quelli del team attivo." testid="my-teams">
              <Select icon={Users} value={active?.id || org.id} testid="team-active-select"
                options={teams.map((t) => [t.id, `${t.name} · ${t.members_count} ${t.members_count === 1 ? "membro" : "membri"}`])}
                onChange={(id) => { const t = teams.find((x) => x.id === id); if (t && !t.active) activate(t); }} />
            </Field>
          ) : (
            <div className="flex items-center gap-3">
              <div className="flex-1 min-w-0 text-lg font-semibold text-white truncate">{org.name}</div>
              <MembersCount n={(org.members || []).length} />
            </div>
          )}
          <div className="text-[12px] font-medium text-white/85 mt-5 mb-1">{multi ? `Membri di «${org.name}»` : "Membri"}</div>
          <div>
            {(org.members || []).map((m) => <PersonRow key={m.user_id} m={m} me={m.user_id === user?.user_id} />)}
          </div>
          <button type="button" onClick={() => leave({ id: org.id, name: org.name })} data-testid="team-leave"
            className={`${SECONDARY} w-full mt-4 text-white/75`}>
            <LogOut size={15} /> Esci da «{org.name}»
          </button>
        </div>
      )}

      <div className={teamCard} data-testid="team-join">
        <Field label={org?.id ? "Entra in un altro team" : "Entra in un team"}
          hint={org?.id ? "Scrivi il codice che ti ha dato l'amministratore." : "Non fai ancora parte di un team: accetta un invito qui sopra o scrivi il codice che ti hanno dato."}>
          <form className="relative" onSubmit={(e) => { e.preventDefault(); joinOrgCall(); }}>
            <Input icon={KeyRound} data-testid="team-join-code" value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="Es. A1B2C3" className="uppercase tracking-widest placeholder:normal-case placeholder:tracking-normal pr-[100px]" autoCapitalize="characters" />
            <button type="submit" data-testid="team-join-btn" disabled={busy || !joinCode.trim()}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 h-8 px-3 rounded-lg bg-white/85 text-[#7A2A5C] text-xs font-semibold disabled:opacity-50 inline-flex items-center gap-1">
              {busy ? <Loader2 size={13} className="animate-spin" /> : "Unisciti"}</button>
          </form>
        </Field>
      </div>
    </div>
  );
}
