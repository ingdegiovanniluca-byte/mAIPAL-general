import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Mail, ShieldCheck, UserPlus, Pause, Play, Building2, UserCog, X, ChevronDown, Clock, MoreHorizontal, UserMinus } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Field, Input, Select, INPUT, PRIMARY, ICON_BTN } from "@/components/FormFields";
import GlassMenu, { GlassMenuItem } from "@/components/GlassMenu";
import { StatTiles, StatTile } from "@/components/StatTiles";
import { teamCard as card, GroupTitle, PersonRow } from "@/pages/OrganizationPage";
import IosSwitch from "@/components/IosSwitch";

/* Impostazioni > Organizzazione (its administrators): who subscribed, the plan's limits and what
   is used (users, administrators, collaborators), the users - added by e-mail, as users or (if
   the plan allows) administrators, suspended or removed - and the sharing rules. Nothing of
   another organization is ever shown here. */

// a person's actions (administrator, suspend, remove): in a menu, so the name keeps the whole row
function MemberMenu({ m, busy, canAdmin, onAdmin, onSuspend, onRemove }) {
  const [open, setOpen] = useState(false);
  const btn = useRef(null), panel = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const out = (e) => { if (!btn.current?.contains(e.target) && !panel.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", out);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", out); document.removeEventListener("keydown", esc); };
  }, [open]);
  const pick = (fn) => () => { setOpen(false); fn(); };
  return (
    <>
      <button ref={btn} type="button" disabled={busy} onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        aria-label={`Azioni per ${m.name || m.email}`} data-testid="org-member-menu" className={ICON_BTN}>
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <GlassMenu anchorRef={btn} panelRef={panel} testid="org-member-actions" width={292}>
          {canAdmin && <GlassMenuItem icon={ShieldCheck} testid="org-member-admin" onClick={pick(onAdmin)}
            label={m.role === "admin" ? "Togli i diritti di amministratore" : "Rendi amministratore"} />}
          <GlassMenuItem icon={m.suspended ? Play : Pause} testid="org-member-suspend" onClick={pick(onSuspend)}
            label={m.suspended ? "Riattiva" : "Sospendi"} />
          <GlassMenuItem icon={UserMinus} testid="org-member-remove" onClick={pick(onRemove)} danger label="Togli dall'organizzazione" />
        </GlassMenu>
      )}
    </>
  );
}

// a rule: what it does on the left, the switch on the right
function Rule({ on, onChange, title, sub, testid }) {
  return (
    <div className="flex items-center gap-3 py-3 border-t border-white/10 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex-1 min-w-0">
        <div className="text-sm text-white">{title}</div>
        <div className="text-[12px] leading-[16px] text-white/55 mt-0.5">{sub}</div>
      </div>
      <IosSwitch checked={on} onChange={onChange} label={title} testid={testid} />
    </div>
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
      <button type="button" onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-3 text-left" aria-expanded={open} data-testid="org-automations-toggle">
        <Clock size={17} className="shrink-0 text-white/60" />
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-medium text-white">Commesse: orari e automatismi</span>
          <span className="block text-[12px] text-white/55 mt-0.5">Promemoria, arrivo e uscita, riepiloghi e solleciti su Telegram.</span>
        </span>
        <ChevronDown size={17} className={`shrink-0 text-white/60 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && SETTING_ROWS.map(([title, rows]) => (
        <div key={title} className="mt-5">
          <div className="text-[12px] font-medium text-white/85 mb-1 first-letter:uppercase">{title}</div>
          {rows.map(([key, label, kind, unit]) => (
            <label key={key} className="flex items-center gap-3 py-2 border-t border-white/10 first:border-t-0">
              <span className="flex-1 min-w-0 text-[13px] text-white/85 leading-snug">{label}</span>
              <span className="relative shrink-0">
                <input type={kind === "time" ? "time" : "number"} inputMode={kind === "time" ? undefined : "numeric"} defaultValue={st[key]} key={`${key}-${st[key]}`} data-testid={`setting-${key}`}
                  onBlur={(e) => save(key, kind === "time" ? e.target.value : Number(e.target.value))}
                  className={`${INPUT} !h-10 !w-[112px] ${kind === "time" ? "time-field px-3 text-center" : `pl-3 text-right ${unit ? "pr-[52px]" : "pr-3"}`}`} />
                {unit && kind !== "time" && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] text-white/50 pointer-events-none">{unit}</span>}
              </span>
            </label>
          ))}
        </div>
      ))}
      {open && (
        <div className="mt-5">
          <Rule on={st.save_position !== false} testid="setting-save-position" onChange={(v) => save("save_position", v)}
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
  const members = t.members || [], invites = t.invites || [];
  const roleOf = (m) => (m.owner ? "titolare" : m.role === "admin" ? "amministratore" : "utente");

  return (
    <div className="space-y-3" data-testid="org-admin">
      {/* on top: the plan's limits and what is used */}
      <div className={card} data-testid="org-usage">
        <StatTiles>
          <StatTile label="Utenti" value={usage.users || 0} max={plan.max_users || 0} testid="org-usage-users" />
          <StatTile label="Collaboratori" value={usage.collaborators || 0} max={plan.max_collaborators || 0} testid="org-usage-collaborators" />
          <StatTile label="Amministratori" value={usage.admins || 0} max={plan.max_admins || 0} testid="org-usage-admins" />
        </StatTiles>
        <div className="text-[11px] text-white/55 mt-4">I limiti del tuo abbonamento: usati / disponibili.</div>
      </div>

      <div className={card}>
        <Field label="Nome dell'organizzazione">
          <Input icon={Building2} value={name} onChange={(e) => setName(e.target.value)} aria-label="Nome dell'organizzazione" data-testid="org-name"
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
            onBlur={() => name.trim() && name.trim() !== t.name && run(() => api.patch("/tenant", { name: name.trim() }), "Nome aggiornato")} />
        </Field>
      </div>

      <div className="pt-2"><GroupTitle>Utenti</GroupTitle></div>
      <div className={`${card} flex flex-col gap-4`}>
        <Field label="Aggiungi un utente" hint="Entra nell'app e su Telegram con questa email (password o Google). I collaboratori, solo Telegram, li aggiungi in Collaboratori.">
          <Input icon={Mail} type="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => e.key === "Enter" && invite()}
            placeholder="nome@azienda.it" data-testid="org-invite-email" />
        </Field>
        {canMoreAdmins && (
          <Field label="Ruolo">
            <Select icon={UserCog} value={role} onChange={setRole} testid="org-invite-role" options={[["user", "Utente"], ["admin", "Amministratore"]]} />
          </Field>
        )}
        <button type="button" onClick={invite} disabled={busy || !email.trim()} data-testid="org-invite" className={`${PRIMARY} w-full`}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <UserPlus size={15} />} Aggiungi
        </button>
      </div>

      <div className={card} data-testid="org-members">
        <div className="text-[12px] font-medium text-white/85 mb-1">Nell'organizzazione ({members.length})</div>
        {members.map((m) => (
          <div key={m.user_id} data-testid="org-member">
            <PersonRow m={{ ...m, email: `${m.email} · ${roleOf(m)}${m.suspended ? " · sospeso" : ""}` }} me={m.user_id === user?.user_id}>
              {!m.owner && (
                <MemberMenu m={m} busy={busy} canAdmin={canMoreAdmins || m.role === "admin"}
                  onAdmin={() => run(() => api.patch(`/tenant/users/${m.user_id}`, { role: m.role === "admin" ? "user" : "admin" }),
                    m.role === "admin" ? "Non è più amministratore" : "Ora è amministratore")}
                  onSuspend={() => run(() => api.patch(`/tenant/users/${m.user_id}`, { suspended: !m.suspended }), m.suspended ? "Riattivato" : "Sospeso")}
                  onRemove={() => confirm(`Togliere ${m.name || m.email} dall'organizzazione? Non potrà più accedere.`, "Togli",
                    () => run(() => api.delete(`/tenant/users/${m.user_id}`), "Tolto dall'organizzazione"))} />
              )}
            </PersonRow>
          </div>
        ))}
        {invites.length > 0 && (
          <div className="mt-4">
            <div className="text-[11px] text-white/55 mb-0.5">Non hanno ancora fatto il primo accesso</div>
            {invites.map((inv) => (
              <div key={inv.email} className="flex items-center gap-3 py-2 border-t border-white/10 first:border-t-0" data-testid="org-invite-row">
                <Mail size={15} className="text-white/45 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-white/85 truncate">{inv.email}</div>
                  <div className="text-[11px] text-white/50">{inv.role === "admin" ? "amministratore" : "utente"}</div>
                </div>
                <button type="button" disabled={busy} title="Annulla" aria-label={`Annulla l'invito a ${inv.email}`}
                  onClick={() => run(() => api.delete(`/tenant/invites/${encodeURIComponent(inv.email)}`), "Invito annullato")} className={ICON_BTN}><X size={14} /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="pt-2"><GroupTitle>Regole di condivisione</GroupTitle></div>
      <div className={card} data-testid="org-sharing">
        <Rule on={t.sharing?.users_share !== false} testid="org-rule-users-share"
          onChange={(v) => run(() => api.patch("/tenant", { users_share: v }))}
          title="Gli utenti possono condividere" sub="Liste, diari di commessa, task e informazioni con i colleghi del team. Spento: lo fanno solo gli amministratori." />
        <Rule on={!!t.sharing?.collab_contacts} testid="org-rule-collab-contacts"
          onChange={(v) => run(() => api.patch("/tenant", { collab_contacts: v }))}
          title="I nuovi collaboratori vedono telefono ed email dei clienti" sub="Lo puoi sempre cambiare per ogni collaboratore." />
        <Rule on={!!t.sharing?.users_see_costs} testid="org-rule-users-costs"
          onChange={(v) => run(() => api.patch("/tenant", { users_see_costs: v }))}
          title="Gli utenti vedono valore, costi e margine delle commesse" sub="Spento: li vedono solo gli amministratori. I collaboratori non li vedono mai." />
      </div>

      <div className="pt-2"><GroupTitle>Automatismi</GroupTitle></div>
      <AutomationSettings />
    </div>
  );
}
