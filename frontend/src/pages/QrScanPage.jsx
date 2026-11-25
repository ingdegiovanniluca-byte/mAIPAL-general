import React, { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { QrCode, BookOpen, Pencil, ExternalLink } from "lucide-react";
import PageBackground from "@/components/PageBackground";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";

/* A QR label scanned with the phone (APP/q/<code>): what it shows, for who is in the organization that made it.
   Not logged in: the login first, then back here. Anyone else gets "not found" - the same as a wrong code. */
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

  useEffect(() => {
    if (!user) return;
    setQ(null); setError(null);
    api.get(`/qr/scan/${encodeURIComponent(code)}`)
      .then((r) => setQ(r.data))
      .catch((e) => setError(e.response?.data?.detail || "Non riesco ad aprire questo QR: controlla la connessione e riprova."));
  }, [user, code]);

  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="kicker">caricamento…</div></div>;
  if (!user) {
    rememberAfterLogin(`/q/${code}`);
    return <Navigate to="/" replace />;
  }

  return (
    <div className="font-poppins min-h-screen w-full relative">
      <PageBackground />
      <div className="relative z-10 w-full max-w-[560px] mx-auto px-4 pt-8 pb-12 flex flex-col gap-4 text-white">
        <button type="button" onClick={() => navigate("/dashboard")} className="self-start text-xs text-white/70">mAIPAL</button>
        {error ? (
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
