import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Users, LogOut } from "lucide-react";
import { toast } from "sonner";

// a team's card: it opens with the name, the number of members on its right
export const teamCard = "rounded-2xl bg-white/[0.07] border border-white/10 p-4";
export function MembersCount({ n }) {
  return (
    <span className="shrink-0 inline-flex items-center gap-1 text-xs text-white/70" data-testid="team-members-count" title={`${n} ${n === 1 ? "membro" : "membri"}`}>
      <Users size={13} /> {n}
    </span>
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

  return (
    <div className="space-y-3">
      {invites.map((inv) => (
        <div key={inv.org_id} className={teamCard} data-testid="team-invite">
          <div className="text-[11px] uppercase tracking-widest text-white/50">Invito</div>
          <div className="mt-1 font-semibold text-lg truncate">{inv.name}</div>
          {inv.invited_by && <div className="text-[12px] text-white/55">da {inv.invited_by}</div>}
          <div className="mt-3 flex gap-2">
            <button type="button" disabled={busy} onClick={() => accept(inv)} data-testid="team-invite-accept"
              className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50">Accetta</button>
            <button type="button" disabled={busy} onClick={() => decline(inv)} data-testid="team-invite-decline"
              className="px-4 py-2 rounded-full text-sm bg-white/15 text-white disabled:opacity-50">Rifiuta</button>
          </div>
        </div>
      ))}

      {multi && (
        <div className={teamCard} data-testid="my-teams">
          <div className="kicker mb-2">· i tuoi team</div>
          {teams.map((t) => (
            <div key={t.id} className="flex items-center gap-3 py-2 border-t border-white/[0.1] first:border-t-0" data-testid="my-team-row">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{t.name}</div>
                <div className="text-[11px] text-white/50">{t.members_count} {t.members_count === 1 ? "membro" : "membri"}</div>
              </div>
              {t.active ? (
                <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/20 text-white" data-testid="team-active">Attivo</span>
              ) : (
                <button type="button" disabled={busy} onClick={() => activate(t)} data-testid="team-activate"
                  className="text-[12px] px-3 py-1 rounded-full bg-white/10 hover:bg-white/15 text-white disabled:opacity-50">Usa questo</button>
              )}
              <button type="button" onClick={() => leave(t)} title="Esci dal team" aria-label={`Esci dal team ${t.name}`}
                className="p-1.5 rounded-full text-white/45 hover:text-red-400"><LogOut size={14} /></button>
            </div>
          ))}
          <div className="text-[11px] text-white/45 mt-2">Liste, commesse e task condivisi «con il team» sono quelli del team attivo.</div>
        </div>
      )}

      {org?.id && (
        <div className={teamCard} data-testid="my-team">
          <div className="flex items-center gap-3 mb-3">
            <div className="flex-1 min-w-0 font-semibold text-lg truncate">{org.name}</div>
            {multi && <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/20 text-white">Attivo</span>}
            <MembersCount n={(org.members || []).length} />
          </div>
          <div className="space-y-2">
            {(org.members || []).map((m) => (
              <div key={m.user_id} className="flex items-center gap-2.5 py-1.5">
                {m.picture ? (
                  <img src={m.picture} alt={m.name} className="h-8 w-8 rounded-full object-cover shrink-0" />
                ) : (
                  <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center text-xs font-semibold shrink-0">
                    {(m.name || m.email || "?").charAt(0).toUpperCase()}
                  </div>
                )}
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">{m.name || m.email}{m.user_id === user?.user_id ? " (tu)" : ""}</div>
                  <div className="text-[11px] text-white/45 truncate">{m.email}</div>
                </div>
              </div>
            ))}
          </div>
          {!multi && (
            <button onClick={() => leave({ id: org.id, name: org.name })} className="mt-4 flex items-center gap-2 text-sm text-white/50 hover:text-red-400 transition-colors">
              <LogOut size={14} /> Esci dal team
            </button>
          )}
        </div>
      )}

      <div className={teamCard} data-testid="team-join">
        <div className="text-sm text-white/60 mb-3">
          {org?.id ? "Hai un codice per entrare in un altro team? Scrivilo qui." : "Non fai ancora parte di un team. Se sei stato invitato, accetta l'invito qui sopra oppure inserisci il codice che ti hanno dato."}
        </div>
        <div className="flex gap-2">
          <Input
            data-testid="team-join-code"
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
            placeholder="es. A1B2C3"
            className="h-11 rounded-xl bg-white/10 uppercase"
          />
          <button data-testid="team-join-btn" onClick={joinOrgCall} disabled={busy} className="pill-btn shrink-0">Unisciti</button>
        </div>
      </div>
    </div>
  );
}
