import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Loader2, Mail, ShieldCheck, Trash2, UserPlus, Pause, Play } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";

/* Impostazioni > Organizzazione (its administrators): who subscribed, the plan's limits and what
   is used (users, administrators, collaborators), the users - added by e-mail, as users or (if
   the plan allows) administrators, suspended or removed - and the sharing rules. Nothing of
   another organization is ever shown here. */

const card = "rounded-2xl bg-white/[0.07] border border-white/10 p-4";

function Usage({ label, used, max, testid }) {
  const full = used >= max;
  return (
    <div className="flex-1 min-w-[96px]" data-testid={testid}>
      <div className="text-[10px] uppercase tracking-widest text-white/50">{label}</div>
      <div className="mt-1 text-lg font-semibold text-white">{used}<span className="text-white/45 text-sm font-normal"> / {max}</span></div>
      <div className="mt-1.5 h-1 rounded-full bg-white/10 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, (used / Math.max(1, max)) * 100)}%`, background: full ? "#F2C14E" : "rgba(255,255,255,0.7)" }} />
      </div>
    </div>
  );
}

function Toggle({ on, onClick, title, sub, testid }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on} data-testid={testid} className="w-full flex items-start gap-3 text-left text-sm text-white py-1.5">
      <span className={`mt-0.5 h-5 w-5 shrink-0 rounded-full flex items-center justify-center backdrop-blur-md ${on ? "bg-white/55 text-[#7A2A5C]" : "bg-white/20"}`}>
        {on && <Check size={12} strokeWidth={2.8} />}
      </span>
      <span>{title}<span className="block text-xs text-white/55">{sub}</span></span>
    </button>
  );
}

// the commesse automations: times, tolerances, thresholds (specifica commesse, cap. 7)
const SETTING_ROWS = [
  ["orari in cantiere", [
    ["default_start_time", "Inizio previsto, se non indicato", "time"],
    ["max_presence_hours", "Fine prevista: ore dall'arrivo", "num", "h"],
    ["checkin_tolerance_minutes", "Tolleranza per l'arrivo", "num", "min"],
    ["checkout_tolerance_minutes", "Tolleranza per l'uscita", "num", "min"],
    ["lunch_break_minutes", "Pausa pranzo tolta dalle ore", "num", "min"],
  ]],
  ["messaggi su Telegram", [
    ["day_before_reminder_time", "Promemoria del giorno prima", "time"],
    ["confirmation_nudge_time", "Sollecito se non conferma", "time"],
    ["confirmation_admin_alert_time", "Avviso a te se ancora nessuna conferma", "time"],
    ["daily_message_time", "Messaggio del giorno (fissato)", "time"],
    ["daily_message_lead_minutes", "…o prima dell'inizio di", "num", "min"],
    ["missing_notes_time", "Domanda «com'è andata?» se mancano le note", "time"],
    ["daily_summary_time", "Riepilogo serale per cantiere", "time"],
    ["weekly_report_time", "Report settimanale (venerdì)", "time"],
  ]],
  ["preventivi e meteo", [
    ["quote_followup_days", "Chiedi l'esito del preventivo ogni", "num", "giorni"],
    ["quote_followup_max", "Al massimo", "num", "volte"],
    ["weather_alert_rain_pct", "Avviso pioggia oltre", "num", "%"],
    ["weather_alert_wind_kmh", "Avviso vento oltre", "num", "km/h"],
  ]],
  ["clienti vicino a me", [
    ["nearby_radius_km", "Raggio se non lo dici", "num", "km"],
  ]],
];

function AutomationSettings() {
  const [st, setSt] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { api.get("/tenant/settings").then((r) => setSt(r.data.settings)).catch(() => setSt(null)); }, []);
  const save = async (key, value) => {
    if (String(value) === String(st[key])) return;
    try { const r = await api.patch("/tenant/settings", { [key]: value }); setSt(r.data.settings); toast.success("Salvato"); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); setSt({ ...st }); }
  };
  if (!st) return null;
  return (
    <div className={card} data-testid="org-automations">
      <button type="button" onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between text-left" aria-expanded={open}>
        <span>
          <span className="kicker block">· commesse: orari e automatismi</span>
          <span className="block text-[12px] text-white/55 mt-1">Promemoria, controlli di arrivo e uscita, riepiloghi e solleciti su Telegram.</span>
        </span>
        <span className="text-white/60 text-[12px] shrink-0 ml-3">{open ? "chiudi" : "modifica"}</span>
      </button>
      {open && SETTING_ROWS.map(([title, rows]) => (
        <div key={title} className="mt-3">
          <div className="text-[10px] uppercase tracking-widest text-white/50 mb-1">{title}</div>
          {rows.map(([key, label, kind, unit]) => (
            <label key={key} className="flex items-center gap-3 py-1.5 border-t border-white/[0.08] first:border-t-0">
              <span className="flex-1 text-[13px] text-white/85">{label}</span>
              <input type={kind === "time" ? "time" : "number"} defaultValue={st[key]} key={`${key}-${st[key]}`} data-testid={`setting-${key}`}
                onBlur={(e) => save(key, kind === "time" ? e.target.value : Number(e.target.value))}
                className="h-8 w-[92px] rounded-lg bg-white/10 px-2 text-[13px] text-white text-right outline-none" />
              {unit && <span className="w-12 text-[11px] text-white/50">{unit}</span>}
            </label>
          ))}
        </div>
      ))}
      {open && (
        <div className="mt-3">
          <Toggle on={st.save_position !== false} testid="setting-save-position" onClick={() => save("save_position", !(st.save_position !== false))}
            title="Salva la posizione con il pulsante 📍" sub="Spento: arrivo e uscita si registrano senza posizione." />
        </div>
      )}
    </div>
  );
}

export default function AdminPage() {
  const { user, refresh } = useAuth();
  const [t, setT] = useState(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("user");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");

  const load = async () => {
    try { const r = await api.get("/tenant"); setT(r.data); setName(r.data.name || ""); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore nel caricamento dell'organizzazione"); }
  };
  useEffect(() => { load(); }, []);

  const run = async (fn, ok) => {
    setBusy(true);
    try { const r = await fn(); if (r?.data?.id) setT(r.data); else await load(); if (ok) toast.success(ok); refresh?.(); return true; }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); return false; }
    finally { setBusy(false); }
  };
  const invite = () => {
    const em = email.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(em)) { toast.error("Email non valida"); return; }
    run(() => api.post("/tenant/users", { email: em, role }), `${em} aggiunto: entra in mAIPAL con questa email`).then((done) => { if (done) { setEmail(""); setRole("user"); } });
  };
  const confirm = (msg, label, fn) => toast(msg, { action: { label, onClick: fn }, cancel: { label: "Annulla", onClick: () => {} }, duration: 7000 });

  if (!t) return <div className="kicker">caricamento…</div>;
  const plan = t.plan || {}, usage = t.usage || {};
  const canMoreAdmins = (plan.max_admins || 1) > 1;

  return (
    <div className="space-y-3" data-testid="org-admin">
      <div className={card}>
        <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Nome dell'organizzazione" data-testid="org-name"
          onBlur={() => name.trim() && name.trim() !== t.name && run(() => api.patch("/tenant", { name: name.trim() }), "Nome aggiornato")}
          className="w-full bg-transparent text-lg font-semibold text-white outline-none rounded-lg px-1 -mx-1 focus:bg-white/10" />
        <div className="text-[12px] text-white/55">Abbonamento: i limiti di utenti, collaboratori e amministratori</div>
        <div className="mt-3 flex gap-4 flex-wrap">
          <Usage label="Utenti" used={usage.users || 0} max={plan.max_users || 0} testid="org-usage-users" />
          <Usage label="Collaboratori" used={usage.collaborators || 0} max={plan.max_collaborators || 0} testid="org-usage-collaborators" />
          <Usage label="Amministratori" used={usage.admins || 0} max={plan.max_admins || 0} testid="org-usage-admins" />
        </div>
      </div>

      <div className={card}>
        <div className="kicker mb-2">· utenti</div>
        <div className="text-[12px] text-white/55 mb-3">Accedono all'app e a Telegram con la loro email (password o Google). I collaboratori, solo Telegram, li aggiungi in Collaboratori.</div>
        <div className="flex gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[180px]">
            <Mail size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
            <input value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => e.key === "Enter" && invite()} placeholder="nome@azienda.it"
              data-testid="org-invite-email" className="h-10 w-full rounded-xl bg-white/10 pl-8 pr-3 text-sm text-white placeholder:text-white/40 outline-none" />
          </div>
          {canMoreAdmins && (
            <select value={role} onChange={(e) => setRole(e.target.value)} data-testid="org-invite-role" className="h-10 rounded-xl bg-white/10 px-3 text-sm text-white outline-none">
              <option value="user" className="text-black">Utente</option>
              <option value="admin" className="text-black">Amministratore</option>
            </select>
          )}
          <button type="button" onClick={invite} disabled={busy} data-testid="org-invite" className="h-10 px-4 rounded-full bg-white text-[#403A3C] text-sm font-medium inline-flex items-center gap-1.5 disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />} Aggiungi
          </button>
        </div>
        <div className="mt-3 space-y-1.5" data-testid="org-members">
          {(t.members || []).map((m) => (
            <div key={m.user_id} className="flex items-center gap-2.5 bg-white/5 rounded-xl px-3 py-2" data-testid="org-member">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{m.name || m.email}{m.user_id === user?.user_id ? " (tu)" : ""}</div>
                <div className="text-[11px] text-white/45 truncate">
                  {m.email} · {m.owner ? "titolare" : m.role === "admin" ? "amministratore" : "utente"}{m.suspended ? " · sospeso" : ""}
                </div>
              </div>
              {!m.owner && (
                <>
                  {(canMoreAdmins || m.role === "admin") && (
                    <button type="button" disabled={busy} title={m.role === "admin" ? "Togli i diritti di amministratore" : "Rendi amministratore"}
                      onClick={() => run(() => api.patch(`/tenant/users/${m.user_id}`, { role: m.role === "admin" ? "user" : "admin" }))}
                      className={`p-1.5 rounded-full ${m.role === "admin" ? "text-white" : "text-white/45"} hover:bg-white/10`} data-testid="org-member-admin">
                      <ShieldCheck size={15} />
                    </button>
                  )}
                  <button type="button" disabled={busy} title={m.suspended ? "Riattiva" : "Sospendi (non accede più, i dati restano)"}
                    onClick={() => run(() => api.patch(`/tenant/users/${m.user_id}`, { suspended: !m.suspended }), m.suspended ? "Riattivato" : "Sospeso")}
                    className="p-1.5 rounded-full text-white/55 hover:bg-white/10" data-testid="org-member-suspend">
                    {m.suspended ? <Play size={14} /> : <Pause size={14} />}
                  </button>
                  <button type="button" disabled={busy} title="Togli dall'organizzazione"
                    onClick={() => confirm(`Togliere ${m.name || m.email} dall'organizzazione? Non potrà più accedere.`, "Togli",
                      () => run(() => api.delete(`/tenant/users/${m.user_id}`), "Tolto dall'organizzazione"))}
                    className="p-1.5 rounded-full text-white/45 hover:bg-red-500/10 hover:text-red-400" data-testid="org-member-remove">
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </div>
          ))}
          {(t.invites || []).map((inv) => (
            <div key={inv.email} className="flex items-center gap-2.5 bg-white/[0.03] rounded-xl px-3 py-2" data-testid="org-invite-row">
              <div className="min-w-0 flex-1">
                <div className="text-sm truncate">{inv.email}</div>
                <div className="text-[11px] text-white/45">{inv.role === "admin" ? "amministratore" : "utente"} · non ha ancora fatto il primo accesso</div>
              </div>
              <button type="button" disabled={busy} title="Annulla" onClick={() => run(() => api.delete(`/tenant/invites/${encodeURIComponent(inv.email)}`), "Invito annullato")}
                className="p-1.5 rounded-full text-white/45 hover:bg-red-500/10 hover:text-red-400"><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      </div>

      <div className={card} data-testid="org-sharing">
        <div className="kicker mb-1">· regole di condivisione</div>
        <Toggle on={t.sharing?.users_share !== false} testid="org-rule-users-share"
          onClick={() => run(() => api.patch("/tenant", { users_share: t.sharing?.users_share === false }))}
          title="Gli utenti possono condividere" sub="Liste, diari di commessa, task e informazioni con i colleghi del team. Spento: lo fanno solo gli amministratori." />
        <Toggle on={!!t.sharing?.collab_contacts} testid="org-rule-collab-contacts"
          onClick={() => run(() => api.patch("/tenant", { collab_contacts: !t.sharing?.collab_contacts }))}
          title="I nuovi collaboratori vedono telefono ed email dei clienti" sub="Lo puoi sempre cambiare per ogni collaboratore." />
        <Toggle on={!!t.sharing?.users_see_costs} testid="org-rule-users-costs"
          onClick={() => run(() => api.patch("/tenant", { users_see_costs: !t.sharing?.users_see_costs }))}
          title="Gli utenti vedono valore, costi e margine delle commesse" sub="Spento: li vedono solo gli amministratori. I collaboratori non li vedono mai." />
      </div>
      <AutomationSettings />
    </div>
  );
}
