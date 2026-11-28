import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { QrCode, BookOpen, Pencil, ExternalLink, Lock, FileText, MapPin, Loader2, Wrench, Undo2, Hand } from "lucide-react";
import { toast } from "sonner";
import PageBackground from "@/components/PageBackground";
import { api, API } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";

/* A QR label scanned with the phone (APP/q/<code>): its content first, as a page to read - the title, what was written,
   the photos, the PDFs, the links. A tool's QR says who has the tool and has the buttons to take it or give it back.
   - Who is in the organization that made it: everything (also a private one), with the commessa's diary and, for the
     administrator, a small pencil to change it.
   - Anyone else - logged in elsewhere or with no account: a public QR's content (only what was written for it);
     a private one "not available", the same as a wrong code, with the login for who is in the organization. */

export const AFTER_LOGIN_KEY = "maipal.afterLogin";

export function rememberAfterLogin(path) {
  try { localStorage.setItem(AFTER_LOGIN_KEY, JSON.stringify({ path, at: Date.now() })); } catch { /* private window */ }
}

const IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
// The phone's position (for a QR that opens only in one place): -> {lat, lon, acc} or an error message.
export function phonePosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error("Questo browser non dà la posizione del telefono.")); return; }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, acc: Math.round(p.coords.accuracy || 9999) }),
      (e) => reject(new Error(e.code === 1
        ? "Hai negato la posizione: consentila a questo sito nelle impostazioni del browser (o del telefono) e riprova."
        : "Non riesco a leggere la posizione: attiva il GPS e riprova, meglio all'aperto.")),
      // (maximumAge 0: always a fresh one - walking to the place, a remembered one would still be "too far")
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
  });
}

const day = (iso) => { if (!iso) return ""; const d = new Date(iso); return `${d.getDate()} ${IT_MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
// "oggi alle 9:40", "ieri alle 17:05", "il 24 novembre"
const since = (iso) => {
  if (!iso) return "";
  const d = new Date(iso), now = new Date();
  const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
  const hm = `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
  return days <= 0 ? `oggi alle ${hm}` : days === 1 ? `ieri alle ${hm}` : `il ${d.getDate()} ${IT_MONTHS[d.getMonth()]}`;
};

/* A tool's QR: who has it now and the buttons - Prendi (also from a colleague), Restituisci (who has it, or an
   administrator for anyone). */
function ToolBox({ q, onTool }) {
  const [busy, setBusy] = useState(null);
  const t = q.tool;
  const h = t.holder;
  const act = async (action) => {
    setBusy(action);
    try {
      const r = await api.post(`/qr/scan/${encodeURIComponent(q.code)}/tool`, { action, token: q.pass || null });
      onTool(r.data.tool);
      toast.success(action === "take" ? "Preso: ora risulta a te" : "Restituito");
    } catch (e) { toast.error((typeof e.response?.data?.detail === "string" && e.response.data.detail) || "Non riuscito, riprova"); }
    finally { setBusy(null); }
  };
  const big = "h-12 rounded-2xl text-[15px] font-semibold inline-flex items-center justify-center gap-2 disabled:opacity-60";
  return (
    <div className="card-soft p-4 flex flex-col gap-3" data-testid="qr-scan-tool">
      <div className="flex items-center gap-3">
        <span className={`h-10 w-10 shrink-0 rounded-full flex items-center justify-center ${h ? "bg-amber-300/25" : "bg-emerald-300/25"}`}><Wrench size={18} /></span>
        <div className="min-w-0">
          <div className="text-[15px] font-semibold leading-tight" data-testid="qr-scan-tool-state">
            {!h ? "Disponibile" : h.mine ? "Ce l'hai tu" : `Ce l'ha ${h.name}`}
          </div>
          <div className="text-[12px] text-white/65 mt-0.5">
            {h ? `Preso ${since(h.since)}` : "Nessuno l'ha preso"}{t.name && t.name !== q.title ? ` · ${t.name}` : ""}
          </div>
        </div>
      </div>
      {!h?.mine && (
        <button type="button" onClick={() => act("take")} disabled={!!busy} data-testid="qr-scan-take" className={`${big} bg-white/90 text-[#7A2A5C]`}>
          {busy === "take" ? <Loader2 size={17} className="animate-spin" /> : <Hand size={17} />} {h ? "Lo prendo io" : "Prendi"}
        </button>
      )}
      {h && (h.mine || q.can_edit) && (
        <button type="button" onClick={() => act("return")} disabled={!!busy} data-testid="qr-scan-return"
          className={`${big} ${h.mine ? "bg-white/90 text-[#7A2A5C]" : "bg-white/15 text-white"}`}>
          {busy === "return" ? <Loader2 size={17} className="animate-spin" /> : <Undo2 size={17} />} Restituisci
        </button>
      )}
    </div>
  );
}

export default function QrScanPage() {
  const { code } = useParams();
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState(null);
  const [error, setError] = useState(null);
  const [reserved, setReserved] = useState(false);   // not public and not logged in: maybe the organization's
  const [place, setPlace] = useState(null);          // it opens only in one place: why not yet (ask the position, too far...)
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState(null);

  const load = React.useCallback((geo) => {
    setError(null); setReserved(false);
    const enc = encodeURIComponent(code);
    const opts = geo ? { headers: { "X-Geo": `${geo.lat},${geo.lon},${geo.acc}` } } : undefined;
    const failed = (e) => (typeof e.response?.data?.detail === "string" && e.response.data.detail) || "Non riesco ad aprire questo QR: controlla la connessione e riprova.";
    const got = (r) => { setPlace(null); setQ(r.data); };
    const placeNeeded = (e) => { if (e.response?.status === 428 && e.response?.data?.detail?.code === "place") { setQ(null); setPlace(e.response.data.detail); return true; } return false; };
    const publicOne = (fallback) => api.get(`/qr/public/${enc}`, opts).then(got).catch((e) => {
      if (placeNeeded(e)) return;
      if (e.response?.status === 404 && !user) setReserved(true); else setError(fallback || failed(e));
    });
    if (!user) return publicOne();
    return api.get(`/qr/scan/${enc}`, opts).then(got).catch((e) => {
      if (placeNeeded(e)) return;
      // not of my organization: maybe a public one (a supplier's, a site's sign)
      if (e.response?.status === 404) publicOne(failed(e)); else setError(failed(e));
    });
  }, [code, user]);

  const locate = React.useCallback(async () => {
    setLocating(true); setGeoError(null);
    try { await load(await phonePosition()); }
    catch (e) { setGeoError(e.message); }
    finally { setLocating(false); }
  }, [load]);

  useEffect(() => {
    if (loading) return;
    setQ(null); setPlace(null);
    load();
  }, [loading, load]);

  // the position already allowed for this site: no need to tap
  useEffect(() => {
    if (place?.reason !== "need" || !navigator.permissions?.query) return;
    navigator.permissions.query({ name: "geolocation" }).then((st) => { if (st.state === "granted") locate(); }).catch(() => {});
  }, [place?.reason]); // eslint-disable-line react-hooks/exhaustive-deps

  const login = () => { rememberAfterLogin(`/q/${code}`); navigate("/"); };

  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="kicker">caricamento…</div></div>;

  return (
    <div className="font-poppins min-h-screen w-full relative">
      <PageBackground />
      <div className="relative z-10 w-full max-w-[560px] mx-auto px-4 pt-8 pb-12 flex flex-col gap-4 text-white">
        <button type="button" onClick={() => navigate(user ? "/dashboard" : "/")} className="self-start text-xs text-white/70">mAIPAL</button>
        {place ? (
          <div className="card-soft p-6 flex flex-col gap-3" data-testid="qr-scan-place">
            <div className="flex items-center gap-2 font-semibold"><MapPin size={17} /> Si apre solo sul posto</div>
            <p className="text-sm text-white/85 leading-relaxed" data-testid="qr-scan-place-msg">{place.message}</p>
            {geoError && <p className="text-sm text-white/80 leading-relaxed" data-testid="qr-scan-geo-error">{geoError}</p>}
            <button type="button" onClick={locate} disabled={locating} data-testid="qr-scan-locate"
              className="self-start h-10 px-5 rounded-full bg-white/85 text-[#7A2A5C] text-sm font-semibold inline-flex items-center gap-2 disabled:opacity-70">
              {locating ? <Loader2 size={15} className="animate-spin" /> : <MapPin size={15} />}
              {place.reason === "need" ? "Usa la mia posizione" : "Riprova"}
            </button>
            <p className="text-[11px] text-white/55 leading-snug">La posizione serve solo a controllare la distanza da questo posto e non viene salvata: per chi è dell'organizzazione resta solo la distanza.</p>
          </div>
        ) : reserved ? (
          <div className="card-soft p-6 flex flex-col gap-3" data-testid="qr-scan-reserved">
            <div className="flex items-center gap-2 font-semibold"><Lock size={17} /> QR riservato</div>
            <p className="text-sm text-white/80 leading-relaxed">
              Questo QR non è pubblico: lo vede solo chi fa parte dell'organizzazione che l'ha creato. Se ne fai parte, accedi con il tuo account mAIPAL.
            </p>
            <button type="button" onClick={login} data-testid="qr-scan-login"
              className="self-start h-10 px-5 rounded-full bg-white/85 text-[#7A2A5C] text-sm font-semibold">Accedi</button>
          </div>
        ) : error ? (
          <div className="card-soft p-6" data-testid="qr-scan-error">
            <div className="flex items-center gap-2 font-semibold"><QrCode size={18} /> QR</div>
            <p className="mt-2 text-sm text-white/80 leading-relaxed">{error}</p>
          </div>
        ) : !q ? (
          <div className="kicker">caricamento…</div>
        ) : (
          <div className="flex flex-col gap-5" data-testid="qr-scan">
            <div className="flex items-start gap-3">
              <h1 className="flex-1 min-w-0 text-[28px] font-bold tracking-tight leading-tight break-words" data-testid="qr-scan-title">{q.title}</h1>
              {q.can_edit && (
                <button type="button" onClick={() => navigate(`/dashboard/qr?open=${q.id}`)} data-testid="qr-scan-edit" aria-label="Modifica il QR" title="Modifica il QR"
                  className="mt-1 h-9 w-9 shrink-0 rounded-full bg-white/15 flex items-center justify-center"><Pencil size={15} /></button>
              )}
            </div>
            {q.commessa && (
              <div className="-mt-3 text-sm text-white/85">
                <span className="font-semibold">{q.commessa.title}</span>{q.commessa.client_name ? ` · ${q.commessa.client_name}` : ""}
                {q.commessa.address ? <div className="text-white/65 text-xs mt-0.5">{q.commessa.address}</div> : null}
              </div>
            )}
            {q.place_note ? <div className="text-xs text-white/70 bg-white/10 rounded-xl px-3 py-2" data-testid="qr-scan-place-note">{q.place_note}</div> : null}
            {q.tool && !q.public && <ToolBox q={q} onTool={(tool) => setQ((x) => ({ ...x, tool }))} />}
            {q.text ? <div className="text-[16px] whitespace-pre-wrap break-words leading-relaxed" data-testid="qr-scan-text">{q.text}</div> : null}
            {q.files?.some((f) => f.kind === "image") && (
              <div className={`grid gap-2 ${q.files.filter((f) => f.kind === "image").length > 1 ? "grid-cols-2" : "grid-cols-1"}`} data-testid="qr-scan-photos">
                {q.files.filter((f) => f.kind === "image").map((f) => (
                  <a key={f.id} href={`${API}/${f.url}`} target="_blank" rel="noopener noreferrer" className="aspect-[4/3] rounded-2xl overflow-hidden bg-white/10">
                    <img src={`${API}/${f.url}`} alt={f.name} className="h-full w-full object-cover" />
                  </a>
                ))}
              </div>
            )}
            {(q.files?.some((f) => f.kind === "pdf") || q.links?.length > 0) && (
              <div className="flex flex-col gap-2" data-testid="qr-scan-pdfs">
                {q.files.filter((f) => f.kind === "pdf").map((f) => (
                  <a key={f.id} href={`${API}/${f.url}`} target="_blank" rel="noopener noreferrer"
                    className="h-12 px-4 rounded-2xl bg-white/15 text-sm font-medium flex items-center gap-2.5">
                    <FileText size={17} className="shrink-0" /><span className="flex-1 truncate">{f.name}</span>
                    <span className="text-[11px] text-white/60 shrink-0">{f.pages} pag.</span>
                  </a>
                ))}
                {(q.links || []).map((l, i) => (
                  <a key={i} href={l.url} target="_blank" rel="noopener noreferrer"
                    className="h-12 px-4 rounded-2xl bg-white/15 text-sm font-medium flex items-center gap-2.5">
                    <ExternalLink size={16} className="shrink-0" /><span className="flex-1 truncate">{l.label}</span>
                  </a>
                ))}
              </div>
            )}
            {q.commessa && (
              <button type="button" onClick={() => navigate(`/dashboard/journal?commessa=${q.commessa.id}`)} data-testid="qr-scan-diary"
                className="self-start h-10 px-4 rounded-full bg-white/15 text-sm font-medium inline-flex items-center gap-1.5">
                <BookOpen size={15} /> Diario della commessa
              </button>
            )}
            {!q.text && !q.files?.length && !q.links?.length && !q.tool && (
              <div className="text-sm text-white/60" data-testid="qr-scan-empty">Questo QR non ha ancora un contenuto.</div>
            )}
            <div className="pt-2 text-[11px] text-white/50">Aggiornato il {day(q.updated_at)}{q.updated_by_name ? ` da ${q.updated_by_name}` : ""} · <span className="whitespace-nowrap">{q.code_label}</span></div>
          </div>
        )}
      </div>
    </div>
  );
}
