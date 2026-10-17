import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Mail, Trash2, Copy, RefreshCw, UserPlus, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/auth/AuthContext";
import OrganizationPage, { teamCard, MembersCount } from "@/pages/OrganizationPage";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* Impostazioni > Team. Everyone sees their own team (or joins one with a code); the admin also
   creates the teams (the round "+", as for a new list) and manages them: name, code, members,
   invitations. */
export default function TeamPanel() {
  const { user } = useAuth();
  if (user?.role !== "admin") return <OrganizationPage />;
  return <TeamsAdmin inTeam={!!user?.org_id} />;
}

function TeamsAdmin({ inTeam }) {
  const [teams, setTeams] = useState(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try { setTeams((await api.get("/admin/teams")).data || []); }
    catch { toast.error("Errore nel caricamento dei team"); setTeams([]); }
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    const n = name.trim();
    if (!n) { toast.error("Scrivi il nome del team"); return; }
    setBusy(true);
    try {
      await api.post("/admin/teams", { name: n });
      toast.success(`Team "${n}" creato`);
      setName(""); setCreating(false);
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };

  return (
    <div data-testid="teams-admin">
      <div className="flex items-center mb-4">
        <button type="button" data-testid="new-team" onClick={() => setCreating(true)} title="Nuovo team" aria-label="Nuovo team"
          className="lg-glass shrink-0 h-11 w-11 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
          <Plus size={22} strokeWidth={1.7} />
        </button>
      </div>
      {!inTeam && <div className="mb-4"><OrganizationPage /></div>}
      {teams === null ? <div className="kicker">caricamento…</div> : (
        <div className="space-y-3">
          {teams.length === 0 && <div className="text-sm text-white/60">Nessun team ancora: crealo con il +.</div>}
          {teams.map((t) => <TeamCard key={t.id} team={t} onChanged={load} />)}
        </div>
      )}
      {creating && (
        <GlassBottomSheet onClose={() => setCreating(false)} testid="new-team-sheet" className="max-h-[60vh] md:left-1/2 md:right-auto md:w-[460px] md:-translate-x-1/2 md:bottom-8">
          <div className="text-lg font-semibold text-white mb-4">Nuovo team</div>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()}
            placeholder="Nome del team" data-testid="new-team-name"
            className="h-11 w-full rounded-xl bg-white/10 px-3 text-sm text-white placeholder:text-white/40 outline-none" />
          <div className="flex justify-end gap-2 mt-4">
            <button onClick={() => setCreating(false)} className="px-4 py-2 rounded-full text-sm text-white/80 hover:bg-white/10">Annulla</button>
            <button onClick={create} disabled={busy} data-testid="create-team-btn"
              className="px-4 py-2 rounded-full text-sm bg-white text-[#403A3C] font-medium disabled:opacity-50 inline-flex items-center gap-1.5">
              {busy && <Loader2 size={14} className="animate-spin" />} Crea
            </button>
          </div>
        </GlassBottomSheet>
      )}
    </div>
  );
}

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
  const regenerateCode = async () => {
    try {
      await api.post(`/admin/teams/${team.id}/regenerate-code`);
      onChanged();
      toast.success("Nuovo codice generato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
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
  const removeMember = async (userId) => {
    try {
      await api.delete(`/admin/teams/${team.id}/members/${userId}`);
      onChanged();
      toast.success("Membro rimosso dal team");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  return (
    <div className={teamCard} data-testid="team-card">
      {/* the name (editable in place) and, on its right, how many members */}
      <div className="flex items-center gap-3">
        <input value={name} onChange={(e) => setName(e.target.value)} onBlur={renameTeam} onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          aria-label="Nome del team" data-testid="team-name"
          className="flex-1 min-w-0 bg-transparent text-lg font-semibold text-white outline-none rounded-lg px-1 -mx-1 focus:bg-white/10" />
        <MembersCount n={members.length} />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex items-center gap-2 bg-white/10 rounded-xl px-3 py-1.5">
          <span className="text-[10px] uppercase tracking-widest text-white/45">codice</span>
          <span className="font-bold tracking-widest text-sm">{team.join_code}</span>
          <button onClick={copyCode} className="p-1 rounded-full hover:bg-white/10 text-white/70" title="Copia codice"><Copy size={13} /></button>
          <button onClick={regenerateCode} className="p-1 rounded-full hover:bg-white/10 text-white/70" title="Rigenera codice"><RefreshCw size={13} /></button>
        </div>
        <button onClick={deleteTeam} className="ml-auto p-2 rounded-full text-white/40 hover:bg-red-500/10 hover:text-red-400" title="Elimina team">
          <Trash2 size={14} />
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
        <div>
          <div className="kicker mb-2">· membri</div>
          <div className="space-y-1.5">
            {members.length === 0 && <div className="text-xs text-white/40">Nessun membro</div>}
            {members.map((m) => (
              <div key={m.user_id} className="flex items-center justify-between gap-2 bg-white/5 rounded-lg px-2.5 py-1.5">
                <div className="min-w-0">
                  <div className="text-xs font-medium truncate">{m.name || m.email}</div>
                  <div className="text-[10px] text-white/40 truncate">{m.email}</div>
                </div>
                <button onClick={() => removeMember(m.user_id)} className="p-1 rounded-full text-white/40 hover:bg-red-500/10 hover:text-red-400 shrink-0" title="Rimuovi dal team">
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="kicker mb-2">· inviti in sospeso ({invites.length})</div>
          <div className="flex items-center gap-1.5 mb-2">
            <div className="relative flex-1">
              <Mail size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
              <Input value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="nome@dominio.com" className="pl-8 h-8 rounded-lg bg-white/10 text-xs" />
            </div>
            <button onClick={invite} disabled={busy} className="p-1.5 rounded-lg bg-white/10 hover:bg-white/15 text-white/80 shrink-0" title="Invita">
              <UserPlus size={14} />
            </button>
          </div>
          <div className="space-y-1.5">
            {invites.length === 0 && <div className="text-xs text-white/40">Nessun invito in sospeso</div>}
            {invites.map((inv) => (
              <div key={inv.email} className="flex items-center justify-between gap-2 bg-white/5 rounded-lg px-2.5 py-1.5">
                <div className="text-xs truncate">{inv.email}</div>
                <button onClick={() => removeInvite(inv.email)} className="p-1 rounded-full text-white/40 hover:bg-red-500/10 hover:text-red-400 shrink-0" title="Annulla invito">
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
