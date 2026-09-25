import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Repeat, Plus, Play, Trash2, List, BarChart3, Bell, CheckSquare, Send, Smartphone, Loader2, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { Switch } from "@/components/ui/switch";

const ACCENT = "#3E7C8C"; // same color as the "Azioni programmate" button in the chat

const KIND_META = {
  list_update: { label: "Modifica lista", icon: List },
  report: { label: "Riepilogo", icon: BarChart3 },
  message: { label: "Promemoria", icon: Bell },
  create_task: { label: "Crea task", icon: CheckSquare },
};

const IT_MONTHS_SHORT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const shortDateTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getDate()} ${IT_MONTHS_SHORT[d.getMonth()]} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

// Results are written for Telegram, where *testo* is bold: render it the same way here.
const renderTelegramText = (text) => String(text || "").split(/(\*[^*\n]+\*)/g).map((part, i) =>
  /^\*[^*\n]+\*$/.test(part) ? <strong key={i} className="font-semibold">{part.slice(1, -1)}</strong> : part
);

function ActionCard({ action, busy, onToggle, onRun, onDelete }) {
  const [open, setOpen] = useState(false);
  const meta = KIND_META[action.kind] || KIND_META.message;
  const KindIcon = meta.icon;
  const ok = action.last_status === "ok";
  const pastRuns = (action.runs || []).slice(0, -1).reverse();
  return (
    <div data-testid="action-card" className={`card-soft p-5 flex flex-col gap-3 transition-opacity ${action.enabled ? "" : "opacity-60"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold leading-snug text-white" data-testid="action-title">{action.title}</div>
          <div className="mt-1 flex items-center gap-1.5 text-xs text-white/75">
            <Repeat size={12} className="shrink-0 text-white/60" />
            <span data-testid="action-schedule">{action.schedule_label}</span>
          </div>
        </div>
        <Switch
          data-testid="action-toggle"
          checked={!!action.enabled}
          disabled={busy}
          onCheckedChange={onToggle}
          title={action.enabled ? "Disattiva" : "Riattiva"}
          className="data-[state=checked]:bg-[#3E7C8C] data-[state=unchecked]:bg-white/20 [&>span]:bg-white"
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white/10 text-white/85"><KindIcon size={11} />{meta.label}</span>
        {(action.kind === "report" || action.kind === "message" || action.notify) && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white/10 text-white/85">
            {action.delivery === "telegram" || action.notify ? <><Send size={11} />Telegram</> : <><Smartphone size={11} />In app</>}
          </span>
        )}
        <span className="text-white/60 ml-auto" data-testid="action-next">
          {action.enabled ? (action.next_run_label ? `Prossima: ${action.next_run_label}` : "") : "In pausa"}
        </span>
      </div>

      <div className="text-xs italic text-white/55 line-clamp-2">«{action.text}»</div>

      {action.last_run_at && (
        <div className="rounded-xl bg-white/5 px-3 py-2.5">
          <button onClick={() => setOpen((v) => !v)} className="w-full flex items-center gap-2 text-[11px] text-white/70">
            <span className="h-2 w-2 rounded-full shrink-0" style={{ background: ok ? "#8ED973" : "#E8663F" }} />
            <span className="truncate">Ultima esecuzione: {shortDateTime(action.last_run_at)}{ok ? "" : " · errore"}</span>
            <ChevronDown size={13} className={`ml-auto shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
          {action.last_result && (
            <div className={`mt-1.5 text-xs text-white/85 whitespace-pre-wrap ${open ? "" : "line-clamp-3"}`} data-testid="action-last-result">{renderTelegramText(action.last_result)}</div>
          )}
          {open && pastRuns.length > 0 && (
            <div className="mt-2 pt-2 border-t border-white/10 space-y-1">
              {pastRuns.map((r, i) => (
                <div key={i} className="flex items-center gap-2 text-[11px] text-white/60">
                  <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ background: r.status === "ok" ? "#8ED973" : "#E8663F" }} />
                  <span className="shrink-0">{shortDateTime(r.at)}{r.manual ? " · manuale" : ""}</span>
                  <span className="truncate">{String(r.result || "").replace(/\*/g, "")}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 mt-auto pt-1">
        <button
          data-testid="action-run"
          onClick={onRun}
          disabled={busy}
          title="Esegui adesso, senza cambiare la programmazione"
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-white/10 hover:bg-white/15 text-white disabled:opacity-50"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Esegui ora
        </button>
        <span className="text-[11px] text-white/45">{action.run_count ? `${action.run_count} esecuzion${action.run_count === 1 ? "e" : "i"}` : "mai eseguita"}</span>
        <button data-testid="action-delete" onClick={onDelete} disabled={busy} title="Elimina" className="ml-auto p-1.5 text-white/55 hover:text-white disabled:opacity-50">
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

export default function ActionsPage() {
  const navigate = useNavigate();
  const [actions, setActions] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = async () => {
    try { const r = await api.get("/scheduled-actions"); setActions(r.data); }
    catch { toast.error("Errore nel caricamento delle azioni"); }
    finally { setLoaded(true); }
  };
  useEffect(() => { load(); }, []);

  const replace = (a) => setActions((xs) => xs.map((x) => (x.id === a.id ? a : x)));

  const toggle = async (a, enabled) => {
    setBusyId(a.id);
    try { const r = await api.patch(`/scheduled-actions/${a.id}`, { enabled }); replace(r.data); toast.success(enabled ? "Azione riattivata" : "Azione disattivata"); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusyId(null); }
  };

  const run = async (a) => {
    setBusyId(a.id);
    try {
      const r = await api.post(`/scheduled-actions/${a.id}/run`);
      replace(r.data);
      if (r.data.last_status === "ok") toast.success("Azione eseguita"); else toast.error("L'azione non è andata a buon fine");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusyId(null); }
  };

  const del = (a) => {
    toast(`Eliminare "${a.title}"?`, {
      action: {
        label: "Elimina",
        onClick: async () => {
          const prev = actions;
          setActions((xs) => xs.filter((x) => x.id !== a.id));
          try { await api.delete(`/scheduled-actions/${a.id}`); toast.success("Azione eliminata"); }
          catch { toast.error("Errore"); setActions(prev); }
        },
      },
      cancel: { label: "Annulla", onClick: () => {} },
      duration: 6000,
    });
  };

  const activeCount = actions.filter((a) => a.enabled).length;
  const newAction = () => navigate("/dashboard/chat", { state: { action: "scheduled_action" } });

  return (
    <div className="w-full">
      <div className="flex items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-2xl bg-white/10 flex items-center justify-center shrink-0"><Repeat size={18} /></div>
          <div className="min-w-0">
            <div className="kicker">· azioni</div>
            <h2 className="text-xl md:text-2xl font-bold tracking-tight">Azioni programmate</h2>
          </div>
        </div>
        <button
          data-testid="new-action-btn"
          onClick={newAction}
          className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium px-3.5 py-2 rounded-full text-white"
          style={{ background: ACCENT }}
        >
          <Plus size={14} /> Nuova
        </button>
      </div>

      {actions.length > 0 && (
        <div className="kicker mb-3 px-1" data-testid="actions-count">
          {activeCount} attiv{activeCount === 1 ? "a" : "e"}{actions.length - activeCount > 0 ? ` · ${actions.length - activeCount} in pausa` : ""}
        </div>
      )}

      {loaded && actions.length === 0 ? (
        <div className="card-soft p-6 md:p-8 max-w-xl" data-testid="actions-empty">
          <div className="font-semibold text-white">Nessuna azione programmata</div>
          <p className="mt-2 text-sm text-white/75 leading-relaxed">
            Scrivi in chat, con il pulsante <span className="inline-flex items-center gap-1 font-medium"><Repeat size={12} /> Azioni</span>, cosa devo fare e con che cadenza. Lo eseguo da solo finché non lo disattivi. Per esempio:
          </p>
          <ul className="mt-3 space-y-1.5 text-sm text-white/85">
            <li>• «Ogni venerdì all'una di notte svuota gli iscritti della lista Lezioni Pilates»</li>
            <li>• «Ogni domenica a mezzanotte calcola la spesa della settimana e mandamela su Telegram»</li>
            <li>• «Il primo di ogni mese crea il task pagare l'affitto»</li>
          </ul>
          <button onClick={newAction} className="mt-5 inline-flex items-center gap-1.5 text-xs font-medium px-3.5 py-2 rounded-full text-white" style={{ background: ACCENT }}>
            <Plus size={14} /> Crea la prima azione
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {actions.map((a) => (
            <ActionCard
              key={a.id}
              action={a}
              busy={busyId === a.id}
              onToggle={(v) => toggle(a, v)}
              onRun={() => run(a)}
              onDelete={() => del(a)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
