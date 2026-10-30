import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check } from "lucide-react";
import { api } from "@/lib/api";
import GlassBottomSheet from "@/components/GlassBottomSheet";

/* One commessa's diary (costs included) shared with team-mates, from its diary: each one can
   write in it or only read it. Only who has the commessa in their own Clienti list decides. */

function Dot({ on }) {
  return (
    <span className={`h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
      {on && <Check size={12} strokeWidth={2.8} />}
    </span>
  );
}

export default function CommessaShareSheet({ commessa, onClose, onChanged }) {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);
  const base = `/jobs/commesse/${commessa.id}/sharing`;
  useEffect(() => {
    api.get(base).then((r) => setSt(r.data)).catch((e) => { toast.error(e.response?.data?.detail || "Errore"); onClose(); });
  }, [commessa.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async (members) => {
    setBusy(true);
    const shared = members.filter((m) => m.shared);
    try {
      const r = await api.put(base, { user_ids: shared.map((m) => m.user_id), perms: Object.fromEntries(shared.map((m) => [m.user_id, m.perm])) });
      setSt(r.data);
      onChanged?.();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  const change = (id, patch) => save(st.members.map((m) => (m.user_id === id ? { ...m, ...patch } : m)));
  const seg = (on) => `px-2.5 py-1 rounded-full text-[11px] transition-colors ${on ? "bg-white text-[#403A3C] font-semibold" : "text-white/70"}`;
  return (
    <GlassBottomSheet onClose={onClose} testid="commessa-share-sheet" className="max-h-[85vh] md:left-1/2 md:right-auto md:w-[480px] md:-translate-x-1/2 md:bottom-8">
      <div className="kicker">· Condivisione</div>
      <div className="text-lg font-semibold text-white mt-1">{commessa.title} · {commessa.client_name}</div>
      <p className="text-[13px] text-white/70 leading-snug mt-2">
        Il diario di questa commessa (costi compresi) lo vede anche chi scegli del tuo team, nel suo Diario.
        Con «Può modificare» ci scrive anche; con «Solo lettura» lo guarda soltanto.
      </p>
      {!st ? <div className="kicker mt-4">caricamento…</div> : !st.in_team || st.members.length === 0 ? (
        <div className="mt-4 text-[13px] text-white/70" data-testid="commessa-share-empty">
          Per condividere una commessa devi far parte di un team con altre persone (Impostazioni → Team).
        </div>
      ) : (
        <div className="mt-3" data-testid="commessa-share-members">
          {st.members.map((m) => (
            <div key={m.user_id} className="flex items-center gap-3 py-2.5 border-t border-white/[0.13] first:border-t-0" data-testid="commessa-share-member">
              <button type="button" disabled={busy} onClick={() => change(m.user_id, { shared: !m.shared })} aria-pressed={m.shared}
                data-testid={`commessa-share-${m.user_id}`} className="flex-1 min-w-0 flex items-center gap-3 text-left text-[15px] text-white disabled:opacity-60">
                <Dot on={m.shared} />
                <span className="truncate">{m.name}</span>
              </button>
              {m.shared && (
                <span className="inline-flex rounded-full bg-white/10 p-0.5 shrink-0" data-testid={`commessa-share-perm-${m.user_id}`}>
                  <button type="button" disabled={busy} onClick={() => change(m.user_id, { perm: "edit" })} className={seg(m.perm !== "read")}>Può modificare</button>
                  <button type="button" disabled={busy} onClick={() => change(m.user_id, { perm: "read" })} className={seg(m.perm === "read")}>Solo lettura</button>
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </GlassBottomSheet>
  );
}
