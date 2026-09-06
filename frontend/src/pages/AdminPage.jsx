import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Shield, Mail, UserCheck, UserX, Trash2, PlusCircle, Loader2, CheckCircle2, RotateCcw } from "lucide-react";

export default function AdminPage() {
  const [tab, setTab] = useState("whitelist");
  const [allowlist, setAllowlist] = useState([]);
  const [users, setUsers] = useState([]);
  const [newEmail, setNewEmail] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const loadAll = async () => {
    try {
      const [a, u] = await Promise.all([
        api.get("/admin/allowlist"),
        api.get("/admin/users"),
      ]);
      setAllowlist(a.data);
      setUsers(u.data);
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

  return (
    <div className="max-w-5xl">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-2xl bg-[#403A3C] text-white flex items-center justify-center"><Shield size={18} /></div>
        <div>
          <div className="kicker">· admin</div>
          <h2 className="text-2xl font-bold tracking-tight">Pannello amministratore</h2>
        </div>
      </div>

      {/* Tabs */}
      <div className="inline-flex items-center gap-1 p-1 rounded-full bg-white/10 mb-6" data-testid="admin-tabs">
        <TabBtn active={tab==="whitelist"} onClick={() => setTab("whitelist")} label={`Whitelist (${allowlist.length})`} testid="tab-whitelist" />
        <TabBtn active={tab==="users"}     onClick={() => setTab("users")}     label={`Utenti (${users.length})`}    testid="tab-users" />
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
