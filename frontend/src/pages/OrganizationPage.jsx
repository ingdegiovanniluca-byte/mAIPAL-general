import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Users, LogOut } from "lucide-react";
import { toast } from "sonner";

// Sezione "Il tuo team", pensata per stare dentro Impostazioni. La creazione dei team,
// gli inviti e il codice sono gestiti dall'amministratore (vedi AdminPage) - qui l'utente
// può solo unirsi con un codice ricevuto (se la sua email è stata invitata) o uscire.
export default function OrganizationPage() {
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

  useEffect(() => { load(); }, []);

  const joinOrgCall = async () => {
    if (!joinCode.trim()) return;
    setBusy(true);
    try {
      await api.post("/org/join", { code: joinCode.trim() });
      await Promise.all([load(), refresh()]);
      toast.success("Ti sei unito al team");
    } catch (e) { toast.error(e.response?.data?.detail || "Codice non valido"); }
    finally { setBusy(false); }
  };

  const leaveOrg = async () => {
    toast("Uscire dal team?", {
      action: {
        label: "Esci",
        onClick: async () => {
          try {
            await api.post("/org/leave");
            await Promise.all([load(), refresh()]);
            toast.success("Hai lasciato il team");
          } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  if (loading) return <div className="text-sm text-white/40">caricamento…</div>;

  if (!org) {
    return (
      <div>
        <div className="text-sm text-white/60 mb-4">
          Non fai ancora parte di un team. Se un amministratore ti ha invitato, inserisci qui il codice che ti ha fornito.
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
    );
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <Users size={16} className="text-white/70" />
        <div className="font-semibold text-lg">{org.name}</div>
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

      <button onClick={leaveOrg} className="mt-4 flex items-center gap-2 text-sm text-white/50 hover:text-red-400 transition-colors">
        <LogOut size={14} /> Esci dal team
      </button>
    </div>
  );
}
