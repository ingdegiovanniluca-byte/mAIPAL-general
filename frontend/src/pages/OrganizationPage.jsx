import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Users, Copy, RefreshCw, LogOut, Trash2, Crown } from "lucide-react";
import { toast } from "sonner";

export default function OrganizationPage() {
  const { user, refresh } = useAuth();
  const [org, setOrg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [orgName, setOrgName] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingName, setEditingName] = useState("");

  const load = async () => {
    try {
      const r = await api.get("/org");
      setOrg(r.data);
      if (r.data) setEditingName(r.data.name);
    } catch {
      toast.error("Errore nel caricamento dell'organizzazione");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const createOrg = async () => {
    if (!orgName.trim()) return;
    setBusy(true);
    try {
      await api.post("/org", { name: orgName.trim() });
      await Promise.all([load(), refresh()]);
      toast.success("Organizzazione creata");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };

  const joinOrgCall = async () => {
    if (!joinCode.trim()) return;
    setBusy(true);
    try {
      await api.post("/org/join", { code: joinCode.trim() });
      await Promise.all([load(), refresh()]);
      toast.success("Ti sei unito all'organizzazione");
    } catch (e) { toast.error(e.response?.data?.detail || "Codice non valido"); }
    finally { setBusy(false); }
  };

  const renameOrg = async () => {
    if (!editingName.trim() || editingName === org.name) return;
    try {
      await api.patch("/org", { name: editingName.trim() });
      await load();
      toast.success("Nome aggiornato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const regenerateCode = async () => {
    try {
      await api.post("/org/regenerate-code");
      await load();
      toast.success("Nuovo codice generato");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const copyCode = () => {
    navigator.clipboard?.writeText(org.join_code);
    toast.success("Codice copiato");
  };

  const removeMember = async (memberId) => {
    try {
      await api.delete(`/org/members/${memberId}`);
      await load();
      toast.success("Membro rimosso");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const leaveOrg = async () => {
    toast("Uscire dall'organizzazione?", {
      action: {
        label: "Esci",
        onClick: async () => {
          try {
            await api.post("/org/leave");
            await Promise.all([load(), refresh()]);
            toast.success("Hai lasciato l'organizzazione");
          } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  if (loading) return <div className="text-center text-white/40 py-24 kicker">caricamento…</div>;

  if (!org) {
    return (
      <div className="max-w-xl mx-auto space-y-6">
        <div className="flex items-center gap-2 mb-2">
          <Users size={20} className="text-white/70" />
          <div className="kicker">organizzazione</div>
        </div>

        <div className="card-soft p-5 rounded-2xl">
          <div className="font-semibold mb-1">Crea la tua organizzazione</div>
          <div className="text-sm text-white/60 mb-4">
            Per condividere task e liste (clienti, esercizi, commesse…) con il tuo team.
          </div>
          <div className="flex gap-2">
            <Input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="es. Studio Rossi" className="h-11 rounded-xl bg-white/10" />
            <button onClick={createOrg} disabled={busy} className="pill-btn shrink-0">Crea</button>
          </div>
        </div>

        <div className="card-soft p-5 rounded-2xl">
          <div className="font-semibold mb-1">Unisciti con un codice</div>
          <div className="text-sm text-white/60 mb-4">
            Chiedi il codice al proprietario dell'organizzazione a cui vuoi unirti.
          </div>
          <div className="flex gap-2">
            <Input value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())} placeholder="es. A1B2C3" className="h-11 rounded-xl bg-white/10 uppercase" />
            <button onClick={joinOrgCall} disabled={busy} className="pill-btn shrink-0">Unisciti</button>
          </div>
        </div>
      </div>
    );
  }

  const isOwner = user?.org_role === "owner";

  return (
    <div className="max-w-xl mx-auto space-y-6">
      <div className="flex items-center gap-2 mb-2">
        <Users size={20} className="text-white/70" />
        <div className="kicker">organizzazione</div>
      </div>

      <div className="card-soft p-5 rounded-2xl">
        {isOwner ? (
          <div className="flex gap-2 mb-4">
            <Input value={editingName} onChange={(e) => setEditingName(e.target.value)} onBlur={renameOrg} className="h-11 rounded-xl bg-white/10 font-semibold" />
          </div>
        ) : (
          <div className="font-semibold text-lg mb-4">{org.name}</div>
        )}

        <div className="flex items-center justify-between gap-3 bg-white/5 rounded-xl p-3">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-white/45 mb-1">codice invito</div>
            <div className="text-xl font-bold tracking-widest">{org.join_code}</div>
          </div>
          <div className="flex gap-1">
            <button onClick={copyCode} className="p-2 rounded-full hover:bg-white/10 text-white/70" title="Copia codice"><Copy size={16} /></button>
            {isOwner && (
              <button onClick={regenerateCode} className="p-2 rounded-full hover:bg-white/10 text-white/70" title="Rigenera codice"><RefreshCw size={16} /></button>
            )}
          </div>
        </div>
      </div>

      <div className="card-soft p-5 rounded-2xl">
        <div className="kicker mb-3">membri ({(org.members || []).length})</div>
        <div className="space-y-2">
          {(org.members || []).map((m) => (
            <div key={m.user_id} className="flex items-center justify-between gap-3 py-1.5">
              <div className="flex items-center gap-2.5 min-w-0">
                {m.picture ? (
                  <img src={m.picture} alt={m.name} className="h-8 w-8 rounded-full object-cover shrink-0" />
                ) : (
                  <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center text-xs font-semibold shrink-0">
                    {(m.name || m.email || "?").charAt(0).toUpperCase()}
                  </div>
                )}
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate flex items-center gap-1.5">
                    {m.name || m.email}
                    {m.org_role === "owner" && <Crown size={12} className="text-amber-400 shrink-0" />}
                  </div>
                  <div className="text-[11px] text-white/45 truncate">{m.email}</div>
                </div>
              </div>
              {isOwner && m.user_id !== user.user_id && (
                <button onClick={() => removeMember(m.user_id)} className="p-1.5 rounded-full text-white/40 hover:bg-red-500/10 hover:text-red-400 shrink-0" title="Rimuovi">
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      <button onClick={leaveOrg} className="flex items-center gap-2 text-sm text-white/50 hover:text-red-400 transition-colors">
        <LogOut size={14} /> Esci dall'organizzazione
      </button>
    </div>
  );
}
