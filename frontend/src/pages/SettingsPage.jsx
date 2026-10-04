import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Cloud, Cloudy, MessageCircle, Copy, ExternalLink, Check, Unlink, User as UserIcon, Home, Briefcase, Camera, Users, Shield, ChevronDown, Factory, LayoutGrid, Heart, MessageSquareText, Building2, Newspaper, Sunrise, Compass, FolderSync, ChevronRight, ArrowLeft, Link2, Mic, Watch, Trash2 } from "lucide-react";
import { usePref } from "@/lib/prefs";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/auth/AuthContext";
import { useIsMobile } from "@/hooks/use-is-mobile";
import OrganizationPage from "@/pages/OrganizationPage";
import AdminPage from "@/pages/AdminPage";

const VERTICALS = ["Lavoro", "Gestione tempo libero", "Vita privata"];
const TONES = ["formale", "informale", "sintetico", "dettagliato"];
const BUSINESS_VERTICALS = [
  { key: "veterinario", label: "Veterinario" },
  { key: "fitness", label: "Fitness" },
  { key: "artigiano", label: "Artigiano" },
];

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const [status, setStatus] = useState(null);
  const [linkCode, setLinkCode] = useState(null);
  const [watches, setWatches] = useState([]);
  const [watchCode, setWatchCode] = useState("");
  const [watchBusy, setWatchBusy] = useState(false);
  const [params, setParams] = useSearchParams();
  const isMobile = useIsMobile();
  const [orgName, setOrgName] = useState("");
  useEffect(() => {
    if (!user?.org_id) { setOrgName(""); return; }
    api.get("/org").then((r) => setOrgName(r.data?.name || r.data?.org?.name || "")).catch(() => {});
  }, [user?.org_id]);

  const [profession, setProfession] = useState("");
  const [sector, setSector] = useState("");
  const [verticals, setVerticals] = useState([]);
  const [interests, setInterests] = useState("");
  const [tone, setTone] = useState("informale");
  const [micSide, setMicSide] = usePref("micSide");   // this device only, applied at once
  const [homeAddress, setHomeAddress] = useState("");
  const [workAddress, setWorkAddress] = useState("");
  const [newsTime, setNewsTime] = useState("08:00");
  const [summaryTime, setSummaryTime] = useState("07:00");
  const [savingProfile, setSavingProfile] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const avatarInputRef = useRef(null);
  const [businessVertical, setBusinessVertical] = useState(null);
  const [savingVertical, setSavingVertical] = useState(false);

  const chooseBusinessVertical = async (key) => {
    if (key === businessVertical) return;
    const prev = businessVertical;
    setBusinessVertical(key);
    setSavingVertical(true);
    try {
      const r = await api.patch("/profile", { business_vertical: key });
      setUser(r.data);
      toast.success("Verticale aggiornato");
    } catch (e) {
      setBusinessVertical(prev);
      toast.error(e.response?.data?.detail || "Errore salvataggio verticale");
    } finally { setSavingVertical(false); }
  };

  useEffect(() => {
    if (!user) return;
    setProfession(user.profession || "");
    setSector(user.sector || "");
    setVerticals(user.verticals || []);
    setInterests((user.interests || []).join(", "));
    setTone(user.tone || "informale");
    setHomeAddress(user.home_address || "");
    setWorkAddress(user.work_address || "");
    setNewsTime(user.news_time || "08:00");
    setSummaryTime(user.summary_time || "07:00");
    setBusinessVertical(user.business_vertical || null);
  }, [user]);

  const load = async () => {
    const r = await api.get("/integrations/status");
    setStatus(r.data);
    api.get("/watch/devices").then((w) => setWatches(w.data || [])).catch(() => {});
  };

  useEffect(() => {
    load();
    if (params.get("google") === "ok") toast.success("Google Workspace collegato");
    if (params.get("google") === "error") toast.error("Errore collegamento Google");
    if (params.get("microsoft") === "ok") toast.success("Account Microsoft collegato");
    if (params.get("microsoft") === "error") toast.error("Errore collegamento Microsoft");
    // back from Google/Microsoft sign-in: straight to Collegamenti (on the phone it's a tile)
    if (["google", "microsoft"].some((k) => params.get(k))) setParams({ s: "links" }, { replace: true });
  }, []);

  const toggleV = (v) => setVerticals((s) => (s.includes(v) ? s.filter((x) => x !== v) : [...s, v]));

  const saveProfile = async () => {
    setSavingProfile(true);
    try {
      const r = await api.patch("/profile", {
        profession, sector, verticals,
        interests: interests.split(",").map((s) => s.trim()).filter(Boolean),
        tone, home_address: homeAddress, work_address: workAddress,
        news_time: newsTime, summary_time: summaryTime,
      });
      setUser(r.data);
      toast.success("Profilo aggiornato");
    } catch (e) {
      toast.error("Errore salvataggio profilo");
    } finally { setSavingProfile(false); }
  };

  const onAvatarPicked = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploadingAvatar(true);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      const r = await api.post("/profile/avatar", fd);
      setUser(r.data);
      toast.success("Foto profilo aggiornata");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore caricamento immagine");
    } finally { setUploadingAvatar(false); }
  };

  const connectGoogle = async () => {
    try {
      const r = await api.get("/integrations/google/authorize");
      window.location.href = r.data.authorization_url;
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    }
  };

  const disconnectGoogle = async () => {
    await api.post("/integrations/google/disconnect");
    toast.success("Google scollegato");
    load();
  };

  const connectMicrosoft = async () => {
    try {
      const r = await api.get("/integrations/microsoft/authorize");
      window.location.href = r.data.url;
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    }
  };

  const disconnectMicrosoft = async () => {
    await api.post("/integrations/microsoft/disconnect");
    toast.success("Microsoft scollegato");
    load();
  };

  // Where files are saved / which calendars tasks go to: any combination of the connected ones.
  const toggleTarget = async (kind, value) => {
    const key = kind === "storage" ? "storage_targets" : "calendar_targets";
    const current = status[key] || [];
    const next = current.includes(value) ? current.filter((x) => x !== value) : [...current, value];
    try {
      const r = await api.put("/integrations/preferences", { [key]: next });
      setStatus((st) => ({ ...st, ...r.data }));
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const genTelegramCode = async () => {
    try {
      const r = await api.post("/integrations/telegram/link-code");
      setLinkCode(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const disconnectTg = async () => {
    await api.post("/integrations/telegram/disconnect");
    toast.success("Telegram scollegato");
    setLinkCode(null);
    load();
  };

  // Galaxy Watch: the watch shows a 6-digit code, typed here to link it to this account
  const pairWatch = async () => {
    const code = watchCode.replace(/\D/g, "");
    if (code.length !== 6) { toast.error("Il codice ha 6 cifre"); return; }
    setWatchBusy(true);
    try {
      await api.post("/watch/pair/confirm", { code });
      toast.success("Orologio collegato");
      setWatchCode("");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setWatchBusy(false); }
  };

  const unpairWatch = async (id) => {
    await api.delete(`/watch/devices/${id}`);
    toast.success("Orologio scollegato");
    load();
  };

  const copy = (t) => { navigator.clipboard.writeText(t); toast.success("Copiato"); };

  if (!status) return <div className="kicker">caricamento…</div>;

  // ===== Impostazioni: the sections, shared by the desktop list and the mobile tiles =====
  const secProfile = (mode) => (
    <Section mode={mode} id="profile" testid="profile-card" icon={UserIcon} title="Profilo" defaultOpen>
      <div className="flex items-center gap-4 mb-5">
        <button
          data-testid="avatar-upload-btn"
          onClick={() => avatarInputRef.current?.click()}
          disabled={uploadingAvatar}
          title="Cambia foto profilo"
          className="relative group w-14 h-14 rounded-full overflow-hidden bg-white/10 border border-white/20 flex items-center justify-center shrink-0"
        >
          {user?.picture ? (
            <img src={user.picture} alt="" className="w-full h-full object-cover" />
          ) : (
            <UserIcon size={22} />
          )}
          <span className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
            <Camera size={16} className="text-white" />
          </span>
        </button>
        <input ref={avatarInputRef} type="file" accept="image/*" hidden onChange={onAvatarPicked} data-testid="avatar-input" />
        <div className="text-sm text-white/60">Queste informazioni personalizzano ogni risposta di mAIPAL. Tocca la foto per cambiarla.</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <FieldLabel icon={Briefcase}>professione</FieldLabel>
          <Input data-testid="prof-profession" value={profession} onChange={(e) => setProfession(e.target.value)} placeholder="es. Product Manager" className="h-11 rounded-xl bg-white/10" />
        </div>
        <div>
          <FieldLabel icon={Factory}>settore</FieldLabel>
          <Input data-testid="prof-sector" value={sector} onChange={(e) => setSector(e.target.value)} placeholder="es. Fintech" className="h-11 rounded-xl bg-white/10" />
        </div>
        <div className="md:col-span-2">
          <FieldLabel icon={LayoutGrid} mb="mb-2">verticali d'uso</FieldLabel>
          <div className="flex flex-wrap gap-2">
            {VERTICALS.map((v) => (
              <button key={v} data-testid={`prof-v-${v}`} onClick={() => toggleV(v)}
                      style={verticals.includes(v) ? { backgroundColor: "#CECAD0", color: "#fff", border: "none" } : {}}
                      className={`px-4 py-2 rounded-full text-sm transition-colors duration-150 ${verticals.includes(v) ? "" : "bg-white/10  hover:"}`}>
                {v}
              </button>
            ))}
          </div>
        </div>
        <div className="md:col-span-2">
          <FieldLabel icon={Heart}>interessi (separati da virgola)</FieldLabel>
          <Input data-testid="prof-interests" value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="palestra, viaggi, cucina" className="h-11 rounded-xl bg-white/10" />
        </div>
        <div className="md:col-span-2">
          <FieldLabel icon={MessageSquareText} mb="mb-2">tono di risposta</FieldLabel>
          <div className="flex flex-wrap gap-2">
            {TONES.map((t) => (
              <button key={t} data-testid={`prof-tone-${t}`} onClick={() => setTone(t)}
                      style={tone === t ? { backgroundColor: "#CECAD0", color: "#fff", border: "none" } : {}}
                      className={`px-4 py-2 rounded-full text-sm transition-colors duration-150 ${tone === t ? "" : "bg-white/10  hover:"}`}>
                {t}
              </button>
            ))}
          </div>
        </div>
        <div className="md:col-span-2">
          <FieldLabel icon={Mic} mb="mb-2">microfono nella chat</FieldLabel>
          <div className="flex flex-wrap gap-2" data-testid="mic-side">
            {[["left", "Sinistra"], ["right", "Destra"]].map(([v, label]) => (
              <button key={v} data-testid={`mic-side-${v}`} onClick={() => setMicSide(v)}
                      style={micSide === v ? { backgroundColor: "#CECAD0", color: "#fff", border: "none" } : {}}
                      className={`px-4 py-2 rounded-full text-sm transition-colors duration-150 ${micSide === v ? "" : "bg-white/10  hover:"}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="text-xs text-white/50 mt-1.5">Da che lato della barra di scrittura sta il tasto dei vocali. Vale su questo dispositivo, subito.</div>
        </div>
        <div>
          <FieldLabel icon={Home}>indirizzo casa</FieldLabel>
          <Input data-testid="prof-home" value={homeAddress} onChange={(e) => setHomeAddress(e.target.value)} placeholder="Via, Numero, Città" className="h-11 rounded-xl bg-white/10" />
        </div>
        <div>
          <FieldLabel icon={Building2}>indirizzo lavoro</FieldLabel>
          <Input data-testid="prof-work" value={workAddress} onChange={(e) => setWorkAddress(e.target.value)} placeholder="Via, Numero, Città" className="h-11 rounded-xl bg-white/10" />
        </div>
        <div>
          <FieldLabel icon={Newspaper}>orario invio news</FieldLabel>
          <Input data-testid="prof-news-time" type="time" value={newsTime} onChange={(e) => setNewsTime(e.target.value)} className="h-11 rounded-xl bg-white/10" />
        </div>
        <div>
          <FieldLabel icon={Sunrise}>orario riepilogo mattutino</FieldLabel>
          <Input data-testid="prof-summary-time" type="time" value={summaryTime} onChange={(e) => setSummaryTime(e.target.value)} className="h-11 rounded-xl bg-white/10" />
        </div>
      </div>

      <div className="mt-6 flex justify-end">
        <button data-testid="prof-save" onClick={saveProfile} disabled={savingProfile} className="pill-btn">
          {savingProfile ? "Salvo…" : "Salva profilo"}
        </button>
      </div>
    </Section>
  );
  const secVertical = (mode) => (
    <Section mode={mode} id="vertical" testid="vertical-card" icon={Compass} title="Verticale"
      subtitle="Il settore in cui operi: personalizza le funzionalità dedicate di mAIPAL. In futuro sarà legato al tuo abbonamento.">
      <div className="flex flex-wrap items-center gap-2">
        {BUSINESS_VERTICALS.map((v) => (
          <button
            key={v.key}
            data-testid={`vertical-${v.key}`}
            onClick={() => chooseBusinessVertical(v.key)}
            disabled={savingVertical}
            className="liquid-glass-btn text-sm px-5 py-2 rounded-full disabled:opacity-50"
            style={businessVertical === v.key ? { borderColor: "#FFFFFF" } : undefined}
          >
            {v.label}
          </button>
        ))}
      </div>
    </Section>
  );
  const secGoogle = (mode) => (
    <Section mode={mode} id="google" testid="google-card" icon={Cloud} title="Google Workspace"
      badge={<>{status.google.connected && <ConnectedBadge />}{!status.google.configured && <NotConfiguredBadge />}</>}>
      <div className="text-sm text-white/60">
        Drive: cartella <code className="text-black">mAIPAL</code> per file/allegati. Calendar: eventi dai task con scadenza.
      </div>
      {status.google.connected && status.google.email && (
        <div className="kicker mt-2">connesso come · {status.google.email}</div>
      )}
      {!status.google.configured && (
        <div className="text-xs text-white/60 mt-3 bg-white/10 rounded-xl p-3">
          <b>Come attivare:</b> l'amministratore deve creare un OAuth Client su
          {" "}<a href="https://console.cloud.google.com" target="_blank" rel="noreferrer" className="text-blue-600 underline">Google Cloud Console</a>{" "}
          con scope <code>drive.file</code> + <code>calendar.events</code> e impostare <code>GOOGLE_CLIENT_ID</code> / <code>GOOGLE_CLIENT_SECRET</code>.
        </div>
      )}
      <div className="mt-4 flex gap-2">
        {status.google.connected ? (
          <button data-testid="google-disconnect" onClick={disconnectGoogle} className="px-4 py-2 rounded-full text-sm bg-white/10  hover:border-red-300 text-red-600 flex items-center gap-2">
            <Unlink size={14} /> Scollega
          </button>
        ) : (
          <button data-testid="google-connect" onClick={connectGoogle} disabled={!status.google.configured} className="pill-btn">
            Collega Google Workspace →
          </button>
        )}
      </div>
    </Section>
  );
  const secMicrosoft = (mode) => (
    <Section mode={mode} id="microsoft" testid="microsoft-card" icon={Cloudy} title="Microsoft · OneDrive e Outlook"
      badge={<>{status.microsoft?.connected && <ConnectedBadge />}{!status.microsoft?.configured && <NotConfiguredBadge />}</>}>
      <div className="text-sm text-white/60">
        OneDrive: i file vanno nella cartella dell'app (<code className="text-black">Apps/mAIPAL</code>). Calendario di Outlook: eventi dai task con scadenza. Account personali (outlook.com, hotmail) e di lavoro.
      </div>
      {status.microsoft?.connected && status.microsoft?.email && (
        <div className="kicker mt-2">connesso come · {status.microsoft.email}</div>
      )}
      {!status.microsoft?.configured && (
        <div className="text-xs text-white/60 mt-3 bg-white/10 rounded-xl p-3">
          <b>Come attivare:</b> l'amministratore registra l'app su
          {" "}<a href="https://entra.microsoft.com" target="_blank" rel="noreferrer" className="text-blue-600 underline">Microsoft Entra</a>{" "}
          e imposta <code>MS_CLIENT_ID</code> / <code>MS_CLIENT_SECRET</code> nel file .env (guida in DEPLOY.md).
        </div>
      )}
      <div className="mt-4 flex gap-2">
        {status.microsoft?.connected ? (
          <button data-testid="microsoft-disconnect" onClick={disconnectMicrosoft} className="px-4 py-2 rounded-full text-sm bg-white/10  hover:border-red-300 text-red-600 flex items-center gap-2">
            <Unlink size={14} /> Scollega
          </button>
        ) : (
          <button data-testid="microsoft-connect" onClick={connectMicrosoft} disabled={!status.microsoft?.configured} className="pill-btn">
            Collega account Microsoft →
          </button>
        )}
      </div>
    </Section>
  );
  const secTargets = (mode) => ((status.google.connected || status.microsoft?.connected)) ? (
    <Section mode={mode} id="cloud-targets" testid="cloud-targets-card" icon={FolderSync} title="Dove salvo file ed eventi">
      <div className="text-sm text-white/60">Puoi sceglierne uno o entrambi.</div>
      <div className="mt-4 space-y-3">
        {[
          { kind: "storage", label: "Salva i file su", opts: [["google", "Google Drive", status.google.connected], ["onedrive", "OneDrive", status.microsoft?.connected]] },
          { kind: "calendar", label: "Sincronizza i task con", opts: [["google", "Google Calendar", status.google.connected], ["outlook", "Calendario di Outlook", status.microsoft?.connected]] },
        ].map((row) => {
          const chosen = status[row.kind === "storage" ? "storage_targets" : "calendar_targets"] || [];
          return (
            <div key={row.kind} className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-white/80 w-full sm:w-44">{row.label}</span>
              {row.opts.filter((o) => o[2]).map(([value, label]) => {
                const on = chosen.includes(value);
                return (
                  <button
                    key={value}
                    data-testid={`target-${row.kind}-${value}`}
                    onClick={() => toggleTarget(row.kind, value)}
                    className={`text-xs px-3 py-1.5 rounded-full transition-colors inline-flex items-center gap-1.5 ${on ? "bg-[#00B0F0]/25 text-[#00B0F0]" : "bg-white/10 text-white/70"}`}
                  >
                    {on && <Check size={12} />} {label}
                  </button>
                );
              })}
              {chosen.length === 0 && <span className="text-xs text-amber-300">nessuno: {row.kind === "storage" ? "i file restano solo nell'app" : "i task non vanno su nessun calendario"}</span>}
            </div>
          );
        })}
      </div>
    </Section>
  ) : null;
  const secTelegram = (mode) => (
    <Section mode={mode} id="telegram" testid="telegram-card" icon={MessageCircle} title="Telegram Bot"
      badge={status.telegram.connected && <ConnectedBadge />}>
      <div className="text-sm text-white/60">
        Chatta con mAIPAL da mobile via <code>@{status.telegram.bot_username || "…"}</code>. Comandi: <code>/ask</code>, <code>/save</code>, <code>/task</code>.
      </div>

      {!status.telegram.connected && (
        <div className="mt-4">
          {!linkCode ? (
            <button data-testid="tg-gen-code" onClick={genTelegramCode} className="pill-btn">Genera codice di collegamento</button>
          ) : (
            <div className="bg-white/10 rounded-xl p-4 space-y-3">
              <div className="kicker">codice · usa una volta sola</div>
              <div className="flex items-center gap-2">
                <code data-testid="tg-code" className="flex-1 bg-white/10 px-3 py-2 rounded-lg font-mono-tight text-sm">/start {linkCode.code}</code>
                <button onClick={() => copy(`/start ${linkCode.code}`)} className="p-2 rounded-lg bg-white/10 border"><Copy size={14} /></button>
              </div>
              <a href={linkCode.deep_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 pill-btn text-sm">
                <ExternalLink size={14} /> Apri {"@"}{linkCode.bot_username} su Telegram
              </a>
              <div className="text-xs text-white/60">
                1. Apri il bot · 2. Premi Avvia · 3. Il messaggio <code>/start {linkCode.code}</code> collegherà il tuo account.
              </div>
            </div>
          )}
        </div>
      )}

      {status.telegram.connected && (
        <div className="mt-4 flex gap-2">
          <button data-testid="tg-disconnect" onClick={disconnectTg} className="px-4 py-2 rounded-full text-sm bg-white/10  hover:border-red-300 text-red-600 flex items-center gap-2">
            <Unlink size={14} /> Scollega Telegram
          </button>
        </div>
      )}
    </Section>
  );
  const secWatch = (mode) => (
    <Section mode={mode} id="watch" testid="watch-card" icon={Watch} title="Orologio · Galaxy Watch"
      badge={watches.length > 0 && <ConnectedBadge />}>
      <div className="text-sm text-white/60">
        Parla con gli agenti e guarda task, to-do e liste dal polso. Apri mAIPAL sull'orologio: mostra un codice di 6 cifre, scrivilo qui.
      </div>
      <div className="mt-4 flex gap-2">
        <Input data-testid="watch-code" inputMode="numeric" maxLength={7} placeholder="123456" value={watchCode}
          onChange={(e) => setWatchCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && pairWatch()}
          className="w-36 font-mono-tight tracking-[0.3em] text-center" />
        <button data-testid="watch-pair" onClick={pairWatch} disabled={watchBusy} className="pill-btn disabled:opacity-60">Collega</button>
      </div>
      {watches.length > 0 && (
        <div className="mt-4 space-y-2">
          {watches.map((w) => (
            <div key={w.device_id} data-testid="watch-device" className="flex items-center gap-3 bg-white/10 rounded-xl px-3 py-2.5">
              <Watch size={16} className="shrink-0" />
              <span className="flex-1 min-w-0">
                <span className="block text-sm">{w.name}</span>
                <span className="block text-xs text-white/55">
                  {w.last_seen ? `usato il ${new Date(w.last_seen).toLocaleString("it-IT", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "collegato, mai usato"}
                </span>
              </span>
              <button onClick={() => unpairWatch(w.device_id)} title="Scollega" className="p-2 rounded-full hover:bg-white/10 text-red-300"><Trash2 size={15} /></button>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
  const secTeam = (mode) => (
    <Section mode={mode} id="team" testid="team-card-settings" icon={Users} title="Team"
      subtitle="Condividi task e liste con le persone del tuo team.">
      <OrganizationPage />
    </Section>
  );
  const secAdmin = (mode) => (user?.role === "admin") ? (
    <Section mode={mode} id="admin" testid="admin-card-settings" icon={Shield} title="Amministrazione"
      subtitle="Whitelist accessi, utenti e team.">
      <AdminPage />
    </Section>
  ) : null;

  const panel = params.get("s");
  const openPanel = (id) => setParams({ s: id });
  const closePanel = () => setParams({});
  const linkServices = [
    status.google.configured && { key: "google", icon: Cloud, label: "Google", on: status.google.connected },
    status.microsoft?.configured && { key: "microsoft", icon: Cloudy, label: "Microsoft", on: !!status.microsoft?.connected },
    status.telegram.configured && { key: "telegram", icon: MessageCircle, label: "Telegram", on: status.telegram.connected },
    { key: "watch", icon: Watch, label: "Orologio", on: watches.length > 0 },
  ].filter(Boolean);
  const linksOn = linkServices.filter((l) => l.on).length;
  const tiles = [
    { id: "profile", icon: UserIcon, title: "Profilo", sub: profession || "Incompleto", on: !!profession },
    { id: "vertical", icon: Compass, title: "Verticale", sub: BUSINESS_VERTICALS.find((v) => v.key === businessVertical)?.label || "Nessuno", on: !!businessVertical },
    { id: "links", icon: Link2, title: "Collegamenti", sub: linksOn ? `${linksOn} attiv${linksOn === 1 ? "o" : "i"}` : "Nessuno attivo", on: linksOn > 0, services: linkServices },
    { id: "team", icon: Users, title: "Team", sub: user?.org_id ? (orgName || "Nel tuo team") : "Nessun team", on: !!user?.org_id },
    ...(user?.role === "admin" ? [{ id: "admin", icon: Shield, title: "Admin", full: "Amministrazione", sub: "Accessi e utenti", on: false }] : []),
  ];
  const panelTile = tiles.find((t) => t.id === panel);

  if (isMobile) {
    if (panelTile) {
      return (
        <div className="settings-page" data-testid={`settings-panel-${panel}`}>
          <button onClick={closePanel} data-testid="settings-back" className="flex items-center gap-1.5 text-sm text-white/70 mb-4">
            <ArrowLeft size={16} /> Impostazioni
          </button>
          <div className="flex items-center gap-3 mb-5">
            <span className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center"><panelTile.icon size={19} /></span>
            <h2 className="text-2xl font-bold tracking-tight">{panelTile.full || panelTile.title}</h2>
          </div>
          <div className="space-y-3">
            {panel === "profile" && secProfile("bare")}
            {panel === "vertical" && secVertical("bare")}
            {panel === "links" && <>{secGoogle("static")}{secMicrosoft("static")}{secTargets("static")}{secTelegram("static")}{secWatch("static")}</>}
            {panel === "team" && secTeam("bare")}
            {panel === "admin" && secAdmin("bare")}
          </div>
        </div>
      );
    }
    return (
      <div className="settings-page" data-testid="settings-tiles">
        <button onClick={() => openPanel("profile")} className="w-full flex items-center gap-3 mb-5 text-left" data-testid="settings-me">
          <span className="w-12 h-12 rounded-full overflow-hidden bg-white/10 border border-white/20 flex items-center justify-center shrink-0">
            {user?.picture ? <img src={user.picture} alt="" className="w-full h-full object-cover" /> : <UserIcon size={20} />}
          </span>
          <span className="min-w-0">
            <span className="block text-lg font-semibold text-white truncate">{user?.name}</span>
            <span className="block text-xs text-white/55 truncate">{user?.email}</span>
          </span>
        </button>
        <div className="grid grid-cols-2 gap-3">
          {tiles.map((t) => (
            <button
              key={t.id}
              data-testid={`settings-tile-${t.id}`}
              onClick={() => openPanel(t.id)}
              className={`text-left rounded-[20px] px-3 h-[64px] flex flex-col justify-center backdrop-blur-xl transition-colors ${t.on ? "bg-white/[0.22] border border-white/30" : "bg-white/[0.07] border border-white/10"}`}
            >
              <span className="flex items-center gap-2">
                <t.icon size={17} className={`shrink-0 ${t.on ? "text-white" : "text-white/55"}`} />
                <span className="flex-1 min-w-0">
                  <span className="block text-[13px] font-semibold text-white leading-tight whitespace-nowrap overflow-hidden text-ellipsis">{t.title}</span>
                  <span className="block text-[11px] text-white/60 leading-tight mt-0.5 whitespace-nowrap overflow-hidden text-ellipsis">{t.sub}</span>
                </span>
                <ChevronRight size={14} className="shrink-0 text-white/45" />
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl settings-page">
      <div className="kicker mb-2">· impostazioni</div>
      <h2 className="text-3xl font-bold tracking-tight">Profilo & integrazioni</h2>
      <p className="text-white/60 mt-2">Modifica il profilo con cui mAIPAL ti conosce e collega i servizi esterni.</p>

      <div className="mt-8 space-y-4">
        {secProfile()}
        {secVertical()}
        {secGoogle()}
        {secMicrosoft()}
        {secTargets()}
        {secTelegram()}
        {secWatch()}
        {secTeam()}
        {secAdmin()}
      </div>
    </div>
  );
}

// A settings box that opens and closes on its title (only the title row and the arrow when
// closed); the choice is remembered on this device. Profilo starts open, the rest closed.
// mode "static" (mobile, inside Collegamenti): always open, no arrow; "bare" (mobile, a tile's
// own page): just the content, the page already shows the title.
function Section({ id, testid, icon: Icon, title, badge, subtitle, defaultOpen = false, mode, children }) {
  const key = `maipal.settings.${id}`;
  const [open, setOpen] = useState(() => {
    try { const v = localStorage.getItem(key); return v === null ? defaultOpen : v === "1"; } catch { return defaultOpen; }
  });
  const toggle = () => setOpen((o) => {
    try { localStorage.setItem(key, o ? "0" : "1"); } catch { /* private mode */ }
    return !o;
  });
  if (mode === "bare") {
    return (
      <div className="card-soft p-5" data-testid={testid}>
        {subtitle && <div className="text-sm text-white/60 mb-4">{subtitle}</div>}
        {children}
      </div>
    );
  }
  if (mode === "static") {
    return (
      <div className="card-soft" data-testid={testid}>
        <div className="flex items-center gap-3 px-5 pt-4 pb-3">
          <span className="w-9 h-9 rounded-xl bg-white/10 flex items-center justify-center shrink-0"><Icon size={18} /></span>
          <span className="flex-1 min-w-0 flex items-center gap-2 flex-wrap"><span className="text-lg font-semibold">{title}</span>{badge}</span>
        </div>
        <div className="px-5 pb-5">
          {subtitle && <div className="text-sm text-white/60 mb-4">{subtitle}</div>}
          {children}
        </div>
      </div>
    );
  }
  return (
    <div className="card-soft" data-testid={testid}>
      <button type="button" onClick={toggle} aria-expanded={open} data-testid={`${testid}-toggle`}
        className="w-full flex items-center gap-3 px-5 py-4 text-left">
        <span className="w-9 h-9 rounded-xl bg-white/10 flex items-center justify-center shrink-0"><Icon size={18} /></span>
        <span className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
          <span className="text-lg font-semibold">{title}</span>
          {badge}
        </span>
        <ChevronDown size={20} className={`shrink-0 text-white/60 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="px-5 pb-5">
          {subtitle && <div className="text-sm text-white/60 mb-4">{subtitle}</div>}
          {children}
        </div>
      )}
    </div>
  );
}

// field title with a small icon as tall as the title itself
function FieldLabel({ icon: Icon, mb = "mb-1", children }) {
  return (
    <div className={`kicker ${mb} flex items-center gap-1.5`}>
      <Icon size={12} className="shrink-0" /> {children}
    </div>
  );
}

function ConnectedBadge() {
  return (
    <span className="text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-green-50 text-green-700 border border-green-500/30">
      <Check size={10} className="inline mr-1" /> connesso
    </span>
  );
}

function NotConfiguredBadge() {
  return (
    <span className="text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-amber-50 text-amber-700 border border-amber-500/30">
      non configurato
    </span>
  );
}
