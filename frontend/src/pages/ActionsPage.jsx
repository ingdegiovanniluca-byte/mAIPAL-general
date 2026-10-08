import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Repeat, Plus, Play, Trash2, List, BarChart3, Bell, CheckSquare, Send, Smartphone, Loader2, ChevronDown, ChevronRight, Newspaper, ArrowLeft, Check } from "lucide-react";
import { api } from "@/lib/api";

const ACCENT = "#3E7C8C"; // same color as the "Azioni programmate" button in the chat

const KIND_META = {
  list_update: { label: "Modifica lista", icon: List },
  report: { label: "Riepilogo", icon: BarChart3 },
  message: { label: "Promemoria", icon: Bell },
  create_task: { label: "Crea task", icon: CheckSquare },
  list_delete: { label: "Elimina lista", icon: Trash2 },
  news_delete: { label: "Pulizia news", icon: Newspaper },
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

// The lists' selection dot (Liste, Spesa...): here it turns the action on and off.
function ActiveDot({ on, busy, onToggle, testid }) {
  return (
    <button type="button" data-testid={testid} disabled={busy} aria-pressed={!!on}
      onClick={(e) => { e.stopPropagation(); onToggle(!on); }}
      title={on ? "Attiva: tocca per metterla in pausa" : "In pausa: tocca per riattivarla"}
      aria-label={on ? "Metti in pausa l'azione" : "Riattiva l'azione"}
      className="h-8 w-8 -m-1.5 shrink-0 flex items-center justify-center disabled:opacity-60">
      <span className={`h-5 w-5 rounded-full flex items-center justify-center backdrop-blur-md transition-colors ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
        {on && <Check size={12} strokeWidth={2.8} />}
      </span>
    </button>
  );
}

// One action in the list: like a tile of Impostazioni, one per row - the dot (on / paused),
// the title on one line and, in grey, when it repeats; tapping it opens its card.
function ActionTile({ action, busy, onToggle, onOpen }) {
  const on = !!action.enabled;
  return (
    <div role="button" tabIndex={0} data-testid="action-tile" onClick={onOpen} onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}
      className={`w-full text-left rounded-[20px] px-3 h-[64px] flex items-center gap-2.5 backdrop-blur-xl transition-colors cursor-pointer ${on ? "bg-white/[0.22] border border-white/30" : "bg-white/[0.07] border border-white/10"}`}>
      <ActiveDot on={on} busy={busy} onToggle={onToggle} testid="action-toggle" />
      <span className="flex-1 min-w-0">
        <span className="block text-[13px] font-semibold text-white leading-tight whitespace-nowrap overflow-hidden text-ellipsis" data-testid="action-title">{action.title}</span>
        <span className="block text-[11px] text-white/60 leading-tight mt-0.5 whitespace-nowrap overflow-hidden text-ellipsis" data-testid="action-schedule">{action.schedule_label}</span>
      </span>
      <ChevronRight size={14} className="shrink-0 text-white/45" />
    </div>
  );
}

function ActionCard({ action, busy, onToggle, onRun, onDelete }) {
  const [open, setOpen] = useState(false);
  const meta = KIND_META[action.kind] || KIND_META.message;
  const KindIcon = meta.icon;
  const ok = action.last_status === "ok";
  const pastRuns = (action.runs || []).slice(0, -1).reverse();
  return (
    <div data-testid="action-card" className="card-soft p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs text-white/75">
            <Repeat size={12} className="shrink-0 text-white/60" />
            <span data-testid="action-card-schedule">{action.schedule_label}</span>
          </div>
        </div>
        <span className="flex items-center gap-2 text-[11px] text-white/70 shrink-0">
          {action.enabled ? "Attiva" : "In pausa"}
          <ActiveDot on={!!action.enabled} busy={busy} onToggle={onToggle} testid="action-card-toggle" />
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white/10 text-white/85"><KindIcon size={11} />{meta.label}</span>
        {(action.kind === "report" || action.kind === "message" || action.notify) && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white/10 text-white/85">
            {action.delivery === "telegram" || action.notify ? <><Send size={11} />Telegram</> : <><Smartphone size={11} />In app</>}
          </span>
        )}
      </div>
      {/* the next run on its own line, aligned left like the rest */}
      <div className="text-[11px] text-white/60" data-testid="action-next">
        {action.enabled ? (action.next_run_label ? `Prossima: ${action.next_run_label}` : "") : "In pausa"}
      </div>

      {/* what the action does, written well (not the message as typed), all of it */}
      <div className="text-xs italic text-white/55 whitespace-pre-wrap break-words" data-testid="action-description">{action.description || action.text}</div>

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
  const [params, setParams] = useSearchParams();
  const openId = params.get("a");   // the action whose card is open (?a=id: the phone's back goes to the list)
  const openAction = (a) => setParams({ a: a.id });
  const closeAction = () => setParams({}, { replace: false });
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
          if (openId === a.id) closeAction();
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

  const current = openId ? actions.find((a) => a.id === openId) : null;

  // ===== an action's card =====
  if (openId) {
    return (
      <div className="w-full max-w-2xl settings-page" data-testid="action-detail">
        <button onClick={closeAction} data-testid="action-back" className="flex items-center gap-1.5 text-sm text-white/70 mb-4">
          <ArrowLeft size={16} /> Azioni
        </button>
        {!loaded ? <div className="kicker">caricamento…</div> : !current ? (
          <div className="text-sm text-white/70">Questa azione non c'è più.</div>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-5">
              <span className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center shrink-0"><Repeat size={19} /></span>
              <h2 className="text-2xl font-bold tracking-tight min-w-0 break-words" data-testid="action-detail-title">{current.title}</h2>
            </div>
            <ActionCard action={current} busy={busyId === current.id}
              onToggle={(v) => toggle(current, v)} onRun={() => run(current)} onDelete={() => del(current)} />
          </>
        )}
      </div>
    );
  }

  // ===== the list: one tile per row, like Impostazioni =====
  return (
    <div className="w-full max-w-2xl settings-page" data-testid="actions-page">
      <div className="flex items-center gap-3 mb-5">
        <button data-testid="new-action-btn" onClick={newAction} title="Nuova azione" aria-label="Nuova azione"
          className="lg-glass h-9 w-9 shrink-0 rounded-full flex items-center justify-center text-white active:scale-95 transition-transform">
          <Plus size={17} strokeWidth={1.7} />
        </button>
        {actions.length > 0 && (
          <span className="kicker" data-testid="actions-count">
            {activeCount} attiv{activeCount === 1 ? "a" : "e"}{actions.length - activeCount > 0 ? ` · ${actions.length - activeCount} in pausa` : ""}
          </span>
        )}
      </div>

      {loaded && actions.length === 0 ? (
        <div className="card-soft p-6 md:p-8" data-testid="actions-empty">
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
        <div className="flex flex-col gap-3" data-testid="actions-list">
          {actions.map((a) => (
            <ActionTile key={a.id} action={a} busy={busyId === a.id} onToggle={(v) => toggle(a, v)} onOpen={() => openAction(a)} />
          ))}
        </div>
      )}
    </div>
  );
}
