import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Cloud, MessageCircle, Copy, ExternalLink, Check, Unlink, User as UserIcon, Home, Briefcase } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/auth/AuthContext";

const VERTICALS = ["Lavoro", "Gestione tempo libero", "Vita privata"];
const TONES = ["formale", "informale", "sintetico", "dettagliato"];

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const [status, setStatus] = useState(null);
  const [linkCode, setLinkCode] = useState(null);
  const [params] = useSearchParams();

  const [profession, setProfession] = useState("");
  const [sector, setSector] = useState("");
  const [verticals, setVerticals] = useState([]);
  const [interests, setInterests] = useState("");
  const [tone, setTone] = useState("informale");
  const [homeAddress, setHomeAddress] = useState("");
  const [workAddress, setWorkAddress] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);

  useEffect(() => {
    if (!user) return;
    setProfession(user.profession || "");
    setSector(user.sector || "");
    setVerticals(user.verticals || []);
    setInterests((user.interests || []).join(", "));
    setTone(user.tone || "informale");
    setHomeAddress(user.home_address || "");
    setWorkAddress(user.work_address || "");
  }, [user]);

  const load = async () => {
    const r = await api.get("/integrations/status");
    setStatus(r.data);
  };

  useEffect(() => {
    load();
    if (params.get("google") === "ok") toast.success("Google Workspace collegato");
    if (params.get("google") === "error") toast.error("Errore collegamento Google");
  }, []);

  const toggleV = (v) => setVerticals((s) => (s.includes(v) ? s.filter((x) => x !== v) : [...s, v]));

  const saveProfile = async () => {
    setSavingProfile(true);
    try {
      const r = await api.patch("/profile", {
        profession, sector, verticals,
        interests: interests.split(",").map((s) => s.trim()).filter(Boolean),
        tone, home_address: homeAddress, work_address: workAddress,
      });
      setUser(r.data);
      toast.success("Profilo aggiornato");
    } catch (e) {
      toast.error("Errore salvataggio profilo");
    } finally { setSavingProfile(false); }
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

  const copy = (t) => { navigator.clipboard.writeText(t); toast.success("Copiato"); };

  if (!status) return <div className="kicker">caricamento…</div>;

  return (
    <div className="max-w-4xl">
      <div className="kicker mb-2">· impostazioni</div>
      <h2 className="text-3xl font-bold tracking-tight">Profilo & integrazioni</h2>
      <p className="text-neutral-500 mt-2">Modifica il profilo con cui mAIPAL ti conosce e collega i servizi esterni.</p>

      <div className="card-soft p-6 mt-8" data-testid="profile-card">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-2xl bg-neutral-100 flex items-center justify-center"><UserIcon size={18} /></div>
          <div>
            <div className="text-lg font-semibold">Il tuo profilo</div>
            <div className="text-sm text-neutral-500">Queste informazioni personalizzano ogni risposta di mAIPAL</div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div className="kicker mb-1">professione</div>
            <Input data-testid="prof-profession" value={profession} onChange={(e) => setProfession(e.target.value)} placeholder="es. Product Manager" className="h-11 rounded-xl bg-white" />
          </div>
          <div>
            <div className="kicker mb-1">settore</div>
            <Input data-testid="prof-sector" value={sector} onChange={(e) => setSector(e.target.value)} placeholder="es. Fintech" className="h-11 rounded-xl bg-white" />
          </div>
          <div className="md:col-span-2">
            <div className="kicker mb-2">verticali d'uso</div>
            <div className="flex flex-wrap gap-2">
              {VERTICALS.map((v) => (
                <button key={v} data-testid={`prof-v-${v}`} onClick={() => toggleV(v)}
                        style={verticals.includes(v) ? { backgroundColor: "#6EB7EC", color: "#fff", border: "none" } : {}}
                        className={`px-4 py-2 rounded-full text-sm transition-colors duration-150 ${verticals.includes(v) ? "" : "bg-white border border-neutral-200 hover:border-neutral-400"}`}>
                  {v}
                </button>
              ))}
            </div>
          </div>
          <div className="md:col-span-2">
            <div className="kicker mb-1">interessi (separati da virgola)</div>
            <Input data-testid="prof-interests" value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="palestra, viaggi, cucina" className="h-11 rounded-xl bg-white" />
          </div>
          <div className="md:col-span-2">
            <div className="kicker mb-2">tono di risposta</div>
            <div className="flex flex-wrap gap-2">
              {TONES.map((t) => (
                <button key={t} data-testid={`prof-tone-${t}`} onClick={() => setTone(t)}
                        style={tone === t ? { backgroundColor: "#6EB7EC", color: "#fff", border: "none" } : {}}
                        className={`px-4 py-2 rounded-full text-sm transition-colors duration-150 ${tone === t ? "" : "bg-white border border-neutral-200 hover:border-neutral-400"}`}>
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="kicker mb-1 flex items-center gap-1"><Home size={11} /> indirizzo casa</div>
            <Input data-testid="prof-home" value={homeAddress} onChange={(e) => setHomeAddress(e.target.value)} placeholder="Via, Numero, Città" className="h-11 rounded-xl bg-white" />
          </div>
          <div>
            <div className="kicker mb-1 flex items-center gap-1"><Briefcase size={11} /> indirizzo lavoro</div>
            <Input data-testid="prof-work" value={workAddress} onChange={(e) => setWorkAddress(e.target.value)} placeholder="Via, Numero, Città" className="h-11 rounded-xl bg-white" />
          </div>
        </div>

        <div className="mt-6 flex justify-end">
          <button data-testid="prof-save" onClick={saveProfile} disabled={savingProfile} className="pill-btn">
            {savingProfile ? "Salvo…" : "Salva profilo"}
          </button>
        </div>
      </div>

      <div className="mt-8 space-y-4">
        <div className="card-soft p-6" data-testid="google-card">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-2xl bg-neutral-100 flex items-center justify-center">
              <Cloud size={22} />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-3 flex-wrap">
                <div className="text-lg font-semibold">Google Workspace</div>
                {status.google.connected && (
                  <span className="text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-green-50 text-green-700 border border-green-500/30">
                    <Check size={10} className="inline mr-1" /> connesso
                  </span>
                )}
                {!status.google.configured && (
                  <span className="text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-amber-50 text-amber-700 border border-amber-500/30">
                    non configurato
                  </span>
                )}
              </div>
              <div className="text-sm text-neutral-500 mt-1">
                Drive: cartella <code className="text-black">mAIPAL</code> per file/allegati. Calendar: eventi dai task con scadenza.
              </div>
              {status.google.connected && status.google.email && (
                <div className="kicker mt-2">connesso come · {status.google.email}</div>
              )}
              {!status.google.configured && (
                <div className="text-xs text-neutral-500 mt-3 bg-neutral-100 rounded-xl p-3">
                  <b>Come attivare:</b> l'amministratore deve creare un OAuth Client su
                  {" "}<a href="https://console.cloud.google.com" target="_blank" rel="noreferrer" className="text-blue-600 underline">Google Cloud Console</a>{" "}
                  con scope <code>drive.file</code> + <code>calendar.events</code> e impostare <code>GOOGLE_CLIENT_ID</code> / <code>GOOGLE_CLIENT_SECRET</code>.
                </div>
              )}
              <div className="mt-4 flex gap-2">
                {status.google.connected ? (
                  <button data-testid="google-disconnect" onClick={disconnectGoogle} className="px-4 py-2 rounded-full text-sm bg-white border border-neutral-200 hover:border-red-300 text-red-600 flex items-center gap-2">
                    <Unlink size={14} /> Scollega
                  </button>
                ) : (
                  <button data-testid="google-connect" onClick={connectGoogle} disabled={!status.google.configured} className="pill-btn">
                    Collega Google Workspace →
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="card-soft p-6" data-testid="telegram-card">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-2xl bg-neutral-100 flex items-center justify-center">
              <MessageCircle size={22} />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-3 flex-wrap">
                <div className="text-lg font-semibold">Telegram Bot</div>
                {status.telegram.connected && (
                  <span className="text-[10px] font-mono-tight tracking-widest uppercase px-2 py-1 rounded-md bg-green-50 text-green-700 border border-green-500/30">
                    <Check size={10} className="inline mr-1" /> connesso
                  </span>
                )}
              </div>
              <div className="text-sm text-neutral-500 mt-1">
                Chatta con mAIPAL da mobile via <code>@{status.telegram.bot_username || "…"}</code>. Comandi: <code>/ask</code>, <code>/save</code>, <code>/task</code>.
              </div>

              {!status.telegram.connected && (
                <div className="mt-4">
                  {!linkCode ? (
                    <button data-testid="tg-gen-code" onClick={genTelegramCode} className="pill-btn">Genera codice di collegamento</button>
                  ) : (
                    <div className="bg-neutral-100 rounded-xl p-4 space-y-3">
                      <div className="kicker">codice · usa una volta sola</div>
                      <div className="flex items-center gap-2">
                        <code data-testid="tg-code" className="flex-1 bg-white px-3 py-2 rounded-lg font-mono-tight text-sm">/start {linkCode.code}</code>
                        <button onClick={() => copy(`/start ${linkCode.code}`)} className="p-2 rounded-lg bg-white border"><Copy size={14} /></button>
                      </div>
                      <a href={linkCode.deep_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 pill-btn text-sm">
                        <ExternalLink size={14} /> Apri {"@"}{linkCode.bot_username} su Telegram
                      </a>
                      <div className="text-xs text-neutral-500">
                        1. Apri il bot · 2. Premi Avvia · 3. Il messaggio <code>/start {linkCode.code}</code> collegherà il tuo account.
                      </div>
                    </div>
                  )}
                </div>
              )}

              {status.telegram.connected && (
                <div className="mt-4 flex gap-2">
                  <button data-testid="tg-disconnect" onClick={disconnectTg} className="px-4 py-2 rounded-full text-sm bg-white border border-neutral-200 hover:border-red-300 text-red-600 flex items-center gap-2">
                    <Unlink size={14} /> Scollega Telegram
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
