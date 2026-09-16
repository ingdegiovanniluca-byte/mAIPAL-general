import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Shield, Mail, UserCheck, UserX, Trash2, PlusCircle, Loader2, CheckCircle2, RotateCcw, Users, Copy, RefreshCw, UserPlus } from "lucide-react";

export default function AdminPage() {
  const [tab, setTab] = useState("whitelist");
  const [allowlist, setAllowlist] = useState([]);
  const [users, setUsers] = useState([]);
  const [teams, setTeams] = useState([]);
  const [newEmail, setNewEmail] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [newTeamName, setNewTeamName] = useState("");
  const [busy, setBusy] = useState(false);

  const loadAll = async () => {
    try {
      const [a, u, t] = await Promise.all([
        api.get("/admin/allowlist"),
        api.get("/admin/users"),
        api.get("/admin/teams"),
      ]);
      setAllowlist(a.data);
      setUsers(u.data);
      setTeams(t.data);
    } catch (e) {
      if (e?.response?.status === 403) toast.error("Solo l'amministratore può accedere a questa pagina");
      else toast.error("Errore caricamento admin");
    }
  };
  useEffect(() => { loadAll(); }, []);

  const addEmail = async () => {
    const email = newEmail.trim().toLowerCase();
    if (!email || !email.includes("@")) { toast.error("Email non valida"); return; }
    setBusy(true);
    try {
      await api.post("/admin/allowlist", { email, notes: newNotes });
      setNewEmail(""); setNewNotes("");
      await loadAll();
      toast.success(`${email} aggiunta alla whitelist`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore");
    } finally { setBusy(false); }
  };

  const removeEmail = async (email) => {
    toast(`Rimuovere ${email} dalla whitelist?`, {
      description: "L'utente non potrà più accedere.",
      action: {
        label: "Rimuovi",
        onClick: async () => {
          try {
            await api.delete(`/admin/allowlist/${encodeURIComponent(email)}`);
            await loadAll();
            toast.success("Rimosso");
          } catch (e) { toast.error(e?.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 8000,
    });
  };

  const revokeUser = async (u) => {
    toast(`Revocare l'accesso a ${u.email}?`, {
      description: "Le sessioni verranno chiuse e verrà rimosso dalla whitelist. I dati saranno mantenuti.",
      action: {
        label: "Revoca",
        onClick: async () => {
          try {
            await api.post(`/admin/users/${u.user_id}/revoke`);
            await loadAll();
            toast.success(`Accesso revocato a ${u.email}`);
          } catch (e) { toast.error(e?.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 8000,
    });
  };

  const restoreUser = async (u) => {
    try {
      await api.post(`/admin/users/${u.user_id}/restore`);
      await loadAll();
      toast.success(`${u.email} ripristinato`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Errore"); }
  };

  const deleteUser = async (u) => {
    toast(`Eliminare completamente ${u.email}?`, {
      description: "Verranno cancellati account, task, to-do, diario, KB, conversazioni e sessioni. IRREVERSIBILE.",
      action: {
        label: "Elimina",
        onClick: async () => {
          try {
            const r = await api.delete(`/admin/users/${u.user_id}`);
            await loadAll();
            const c = r.data?.deleted || {};
            const tot = Object.values(c).reduce((a, b) => a + (b || 0), 0);
            toast.success(`${u.email} eliminato · ${tot} record rimossi`);
          } catch (e) { toast.error(e?.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 10000,
    });
  };

  const createTeam = async () => {
    const name = newTeamName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.post("/admin/teams", { name });
      setNewTeamName("");
      await loadAll();
      toast.success(`Team "${name}" creato`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };

  return (
    <div>
      {/* Tabs */}
      <div className="inline-flex items-center gap-1 p-1 rounded-full bg-white/10 mb-6" data-testid="admin-tabs">
        <TabBtn active={tab==="whitelist"} onClick={() => setTab("whitelist")} label={`Whitelist (${allowlist.length})`} testid="tab-whitelist" />
        <TabBtn active={tab==="users"}     onClick={() => setTab("users")}     label={`Utenti (${users.length})`}    testid="tab-users" />
        <TabBtn active={tab==="teams"}     onClick={() => setTab("teams")}     label={`Team (${teams.length})`}      testid="tab-teams" />
      </div>

      {tab === "whitelist" && (
        <div>
          <div className="p-5 rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm">
            <div className="kicker mb-3">· aggiungi email autorizzata</div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative flex-1 min-w-[240px]">
                <Mail size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/40" />
                <Input data-testid="new-email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="nome@dominio.com" className="pl-10 h-10 rounded-full bg-white/10" />
              </div>
              <Input data-testid="new-notes" value={newNotes} onChange={(e) => setNewNotes(e.target.value)} placeholder="Note (opzionali)" className="h-10 rounded-full bg-white/10 min-w-[200px] flex-1" />
              <button data-testid="add-email-btn" onClick={addEmail} disabled={busy} className="px-4 h-10 rounded-full bg-[#403A3C] text-white inline-flex items-center gap-2 disabled:opacity-50 hover:bg-[#403A3C] text-sm">
                {busy ? <Loader2 size={14} className="animate-spin" /> : <PlusCircle size={14} />} aggiungi
              </button>
            </div>
          </div>

          <div className="mt-6">
            <div className="kicker mb-3">· email autorizzate ({allowlist.length})</div>
            <div className="rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm overflow-hidden">
              {allowlist.length === 0 && <div className="p-6 text-sm text-white/60">Nessuna email in whitelist</div>}
              {allowlist.map((a) => (
                <div key={a.email} className="flex items-center justify-between px-5 py-3 border-b  last:border-0" data-testid="allowlist-row">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center shrink-0"><CheckCircle2 size={14} /></div>
                    <div className="min-w-0">
                      <div className="font-medium truncate">{a.email}</div>
                      <div className="kicker-p">
                        {a.notes ? `${a.notes} · ` : ""}
                        aggiunto {new Date(a.added_at).toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric" })}
                        {a.added_by ? ` da ${a.added_by}` : ""}
                      </div>
                    </div>
                  </div>
                  <button
                    data-testid={`remove-${a.email}`}
                    onClick={() => removeEmail(a.email)}
                    className="p-2 rounded-full text-white/40 hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
                    disabled={a.notes === "amministratore"}
                    title={a.notes === "amministratore" ? "Impossibile rimuovere l'amministratore" : "Rimuovi dalla whitelist"}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === "users" && (
        <div>
          <div className="kicker mb-3">· utenti registrati ({users.length})</div>
          <div className="rounded-2xl bg-white/5  backdrop-blur-xl shadow-sm overflow-hidden">
            {users.length === 0 && <div className="p-6 text-sm text-white/60">Nessun utente ancora</div>}
            {users.map((u) => (
              <div key={u.user_id} className="flex items-center justify-between px-5 py-3 border-b  last:border-0" data-testid="user-row">
                <div className="flex items-center gap-3 min-w-0">
                  {u.picture ? (
                    <img src={u.picture} alt="" className="w-9 h-9 rounded-full shrink-0" />
                  ) : (
                    <div className="w-9 h-9 rounded-full bg-white/10 text-white/60 flex items-center justify-center shrink-0">
                      {u.name?.[0]?.toUpperCase() || "?"}
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="font-medium truncate flex items-center gap-2">
                      {u.name || u.email}
                      {u.role === "admin" && <span className="text-[9px] font-mono-tight tracking-widest uppercase px-1.5 py-0.5 rounded-md bg-[#403A3C] text-white">admin</span>}
                      {u.revoked_at && <span className="text-[9px] font-mono-tight tracking-widest uppercase px-1.5 py-0.5 rounded-md bg-red-100 text-red-700" data-testid="revoked-badge">revocato</span>}
                      {!u.onboarded && !u.revoked_at && <span className="text-[9px] font-mono-tight tracking-widest uppercase px-1.5 py-0.5 rounded-md bg-amber-100 text-amber-700">no-onboarding</span>}
                    </div>
                    <div className="kicker-p">
                      {u.email}
                      {u.last_session_at ? ` · ultimo accesso ${new Date(u.last_session_at).toLocaleDateString("it-IT", { day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit" })}` : ""}
                      {u.telegram_chat_id ? " · telegram ✓" : ""}
                      {u.revoked_at ? ` · revocato il ${new Date(u.revoked_at).toLocaleDateString("it-IT", { day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit" })}` : ""}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {u.revoked_at ? (
                    <button
                      data-testid={`restore-${u.user_id}`}
                      onClick={() => restoreUser(u)}
                      disabled={u.role === "admin"}
                      className="px-3 py-1.5 rounded-full text-xs inline-flex items-center gap-1.5 text-emerald-600 hover:bg-emerald-50 disabled:opacity-30 disabled:hover:bg-transparent"
                      title="Riabilita l'accesso"
                    >
                      <RotateCcw size={13} /> ripristina
                    </button>
                  ) : (
                    <button
                      data-testid={`revoke-${u.user_id}`}
                      onClick={() => revokeUser(u)}
                      disabled={u.role === "admin"}
                      className="px-3 py-1.5 rounded-full text-xs inline-flex items-center gap-1.5 text-amber-700 hover:bg-amber-50 disabled:opacity-30 disabled:hover:bg-transparent"
                      title={u.role === "admin" ? "Impossibile revocare l'amministratore" : "Revoca accesso (dati mantenuti)"}
                    >
                      <UserX size={13} /> revoca
                    </button>
                  )}
                  <button
                    data-testid={`delete-${u.user_id}`}
                    onClick={() => deleteUser(u)}
                    disabled={u.role === "admin"}
                    className="px-3 py-1.5 rounded-full text-xs inline-flex items-center gap-1.5 text-red-600 hover:bg-red-50 disabled:opacity-30 disabled:hover:bg-transparent"
                    title={u.role === "admin" ? "Impossibile eliminare l'amministratore" : "Elimina utente e tutti i suoi dati"}
                  >
                    <Trash2 size={13} /> elimina
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "teams" && (
        <div>
          <div className="p-5 rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm">
            <div className="kicker mb-3">· crea un nuovo team</div>
            <div className="flex items-center gap-2 flex-wrap">
              <Input data-testid="new-team-name" value={newTeamName} onChange={(e) => setNewTeamName(e.target.value)} placeholder="es. Team 1" className="h-10 rounded-full bg-white/10 min-w-[200px] flex-1" />
              <button data-testid="create-team-btn" onClick={createTeam} disabled={busy} className="px-4 h-10 rounded-full bg-[#403A3C] text-white inline-flex items-center gap-2 disabled:opacity-50 text-sm">
                {busy ? <Loader2 size={14} className="animate-spin" /> : <PlusCircle size={14} />} crea team
              </button>
            </div>
          </div>

          <div className="mt-6 space-y-4">
            {teams.length === 0 && <div className="p-6 text-sm text-white/60">Nessun team ancora</div>}
            {teams.map((t) => (
              <TeamCard key={t.id} team={t} onChanged={loadAll} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TeamCard({ team, onChanged }) {
  const [name, setName] = useState(team.name);
  const [inviteEmail, setInviteEmail] = useState("");
  const [busy, setBusy] = useState(false);

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

  const deleteTeam = async () => {
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
    <div className="rounded-2xl bg-white/5 backdrop-blur-xl shadow-sm p-5" data-testid="team-card">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <Users size={16} className="text-white/50 shrink-0" />
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={renameTeam}
            className="h-9 rounded-xl bg-white/10 font-semibold min-w-[160px] w-auto"
          />
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 bg-white/10 rounded-xl px-3 py-1.5">
            <span className="text-[10px] uppercase tracking-widest text-white/45">codice</span>
            <span className="font-bold tracking-widest text-sm">{team.join_code}</span>
            <button onClick={copyCode} className="p-1 rounded-full hover:bg-white/10 text-white/70" title="Copia codice"><Copy size={13} /></button>
            <button onClick={regenerateCode} className="p-1 rounded-full hover:bg-white/10 text-white/70" title="Rigenera codice"><RefreshCw size={13} /></button>
          </div>
          <button onClick={deleteTeam} className="p-2 rounded-full text-white/40 hover:bg-red-500/10 hover:text-red-400" title="Elimina team">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
        <div>
          <div className="kicker mb-2">· membri ({(team.members || []).length})</div>
          <div className="space-y-1.5">
            {(team.members || []).length === 0 && <div className="text-xs text-white/40">Nessun membro</div>}
            {(team.members || []).map((m) => (
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
          <div className="kicker mb-2">· inviti in sospeso ({(team.invites || []).length})</div>
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
            {(team.invites || []).length === 0 && <div className="text-xs text-white/40">Nessun invito in sospeso</div>}
            {(team.invites || []).map((inv) => (
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

function TabBtn({ active, onClick, label, testid }) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={`px-4 py-1.5 rounded-full text-xs font-medium inline-flex items-center gap-1.5 transition-all ${active ? "bg-white/10 shadow-sm" : "text-white/60 hover:text-white"}`}
    >
      {active && <UserCheck size={13} />} {label}
    </button>
  );
}
