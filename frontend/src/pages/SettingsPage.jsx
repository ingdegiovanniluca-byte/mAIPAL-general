import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Cloud, MessageCircle, Copy, ExternalLink, Check, Unlink } from "lucide-react";

export default function SettingsPage() {
  const [status, setStatus] = useState(null);
  const [linkCode, setLinkCode] = useState(null);
  const [params] = useSearchParams();

  const load = async () => {
    const r = await api.get("/integrations/status");
    setStatus(r.data);
  };

  useEffect(() => {
    load();
    if (params.get("google") === "ok") toast.success("Google Workspace collegato");
    if (params.get("google") === "error") toast.error("Errore collegamento Google");
  }, []);

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
    <div className="max-w-3xl">
      <div className="kicker mb-2">· impostazioni</div>
      <h2 className="text-3xl font-bold tracking-tight">Integrazioni</h2>
      <p className="text-neutral-500 mt-2">Collega servizi esterni per estendere le capacità di mAIPAL.</p>

      <div className="mt-8 space-y-4">
        {/* GOOGLE */}
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
                Drive: crea cartella <code className="text-black">mAIPAL</code> e archivia file. Calendar: crea eventi dai task con scadenza.
              </div>
              {status.google.connected && status.google.email && (
                <div className="kicker mt-2">connesso come · {status.google.email}</div>
              )}
              {!status.google.configured && (
                <div className="text-xs text-neutral-500 mt-3 bg-neutral-100 rounded-xl p-3">
                  <b>Come attivare:</b> l'amministratore deve creare un OAuth Client su
                  {" "}<a href="https://console.cloud.google.com" target="_blank" rel="noreferrer" className="text-blue-600 underline">Google Cloud Console</a>{" "}
                  con scope <code>drive.file</code> + <code>calendar.events</code> e impostare le variabili <code>GOOGLE_CLIENT_ID</code> / <code>GOOGLE_CLIENT_SECRET</code>.
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

        {/* TELEGRAM */}
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
                        1. Apri il bot con il pulsante sopra · 2. Premi Avvia · 3. Il messaggio <code>/start {linkCode.code}</code> collegherà il tuo account.
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
