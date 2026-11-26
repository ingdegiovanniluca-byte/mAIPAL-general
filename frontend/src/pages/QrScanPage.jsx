import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { QrCode, BookOpen, Pencil, ExternalLink, Lock, FileText } from "lucide-react";
import PageBackground from "@/components/PageBackground";
import { api, API } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";

/* A QR label scanned with the phone (APP/q/<code>).
   - Who is in the organization that made it: everything (also a private one), with the commessa's diary and, for the
     administrator, Modifica.
   - Anyone else - logged in elsewhere or with no account: a public QR's content (only what was written for it);
     a private one "not available", the same as a wrong code, with the login for who is in the organization. */
export const AFTER_LOGIN_KEY = "maipal.afterLogin";

export function rememberAfterLogin(path) {
  try { localStorage.setItem(AFTER_LOGIN_KEY, JSON.stringify({ path, at: Date.now() })); } catch { /* private window */ }
}

const IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const day = (iso) => { if (!iso) return ""; const d = new Date(iso); return `${d.getDate()} ${IT_MONTHS[d.getMonth()]} ${d.getFullYear()}`; };

export default function QrScanPage() {
  const { code } = useParams();
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState(null);
  const [error, setError] = useState(null);
  const [reserved, setReserved] = useState(false);   // not public and not logged in: maybe the organization's

  useEffect(() => {
    if (loading) return;
    setQ(null); setError(null); setReserved(false);
    const enc = encodeURIComponent(code);
    const failed = (e) => e.response?.data?.detail || "Non riesco ad aprire questo QR: controlla la connessione e riprova.";
    const publicOne = (fallback) => api.get(`/qr/public/${enc}`).then((r) => setQ(r.data)).catch((e) => {
      if (e.response?.status === 404 && !user) setReserved(true); else setError(fallback || failed(e));
    });
    if (!user) { publicOne(); return; }
    api.get(`/qr/scan/${enc}`).then((r) => setQ(r.data)).catch((e) => {
      // not of my organization: maybe a public one (a supplier's, a site's sign)
      if (e.response?.status === 404) publicOne(failed(e)); else setError(failed(e));
    });
  }, [user, loading, code]);

  const login = () => { rememberAfterLogin(`/q/${code}`); navigate("/"); };

  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="kicker">caricamento…</div></div>;

  return (
    <div className="font-poppins min-h-screen w-full relative">
      <PageBackground />
      <div className="relative z-10 w-full max-w-[560px] mx-auto px-4 pt-8 pb-12 flex flex-col gap-4 text-white">
        <button type="button" onClick={() => navigate(user ? "/dashboard" : "/")} className="self-start text-xs text-white/70">mAIPAL</button>
        {reserved ? (
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
          <>
            <div className="card-soft p-5 flex flex-col gap-3" data-testid="qr-scan">
              <div className="text-[11px] text-white/60 flex items-center gap-1.5"><QrCode size={13} /> {q.kind_label}</div>
              <h1 className="text-2xl font-bold tracking-tight break-words" data-testid="qr-scan-title">{q.title}</h1>
              {q.commessa && (
                <div className="text-sm text-white/85">
                  <span className="font-semibold">{q.commessa.title}</span>{q.commessa.client_name ? ` · ${q.commessa.client_name}` : ""}
                  {q.commessa.address ? <div className="text-white/65 text-xs mt-0.5">{q.commessa.address}</div> : null}
                </div>
              )}
              {q.text ? <div className="text-[15px] whitespace-pre-wrap break-words leading-relaxed" data-testid="qr-scan-text">{q.text}</div> : null}
              {q.links?.length > 0 && (
                <div className="flex flex-col gap-2">
                  {q.links.map((l, i) => (
                    <a key={i} href={l.url} target="_blank" rel="noopener noreferrer"
                      className="h-11 px-4 rounded-xl bg-white/15 text-sm font-medium flex items-center justify-between gap-2">
                      <span className="truncate">{l.label}</span><ExternalLink size={15} className="shrink-0 text-white/70" />
                    </a>
                  ))}
                </div>
              )}
              {q.files?.some((f) => f.kind === "image") && (
                <div className={`grid gap-2 ${q.files.filter((f) => f.kind === "image").length > 1 ? "grid-cols-2" : "grid-cols-1"}`} data-testid="qr-scan-photos">
                  {q.files.filter((f) => f.kind === "image").map((f) => (
                    <a key={f.id} href={`${API}/${f.url}`} target="_blank" rel="noopener noreferrer" className="aspect-[4/3] rounded-xl overflow-hidden bg-white/10">
                      <img src={`${API}/${f.url}`} alt={f.name} className="h-full w-full object-cover" />
                    </a>
                  ))}
                </div>
              )}
              {q.files?.some((f) => f.kind === "pdf") && (
                <div className="flex flex-col gap-2" data-testid="qr-scan-pdfs">
                  {q.files.filter((f) => f.kind === "pdf").map((f) => (
                    <a key={f.id} href={`${API}/${f.url}`} target="_blank" rel="noopener noreferrer"
                      className="h-12 px-4 rounded-xl bg-white/15 text-sm font-medium flex items-center gap-2.5">
                      <FileText size={17} className="shrink-0" /><span className="flex-1 truncate">{f.name}</span>
                      <span className="text-[11px] text-white/60 shrink-0">{f.pages} pag.</span>
                    </a>
                  ))}
                </div>
              )}
              <div className="text-[11px] text-white/55">Aggiornato il {day(q.updated_at)}{q.updated_by_name ? ` da ${q.updated_by_name}` : ""} · <span className="whitespace-nowrap">{q.code_label}</span></div>
            </div>
            <div className="flex flex-wrap gap-2">
              {q.commessa && (
                <button type="button" onClick={() => navigate(`/dashboard/journal?commessa=${q.commessa.id}`)} data-testid="qr-scan-diary"
                  className="h-10 px-4 rounded-full bg-white/85 text-[#7A2A5C] text-sm font-semibold inline-flex items-center gap-1.5">
                  <BookOpen size={15} /> Diario della commessa
                </button>
              )}
              {q.can_edit && (
                <button type="button" onClick={() => navigate(`/dashboard/qr?open=${q.id}`)} data-testid="qr-scan-edit"
                  className="h-10 px-4 rounded-full bg-white/15 text-sm font-medium inline-flex items-center gap-1.5">
                  <Pencil size={14} /> Modifica
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
