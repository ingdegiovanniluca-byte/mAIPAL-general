import React, { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { ShieldAlert } from "lucide-react";

export default function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);
  const [denied, setDenied] = useState(null); // {message} when 403

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = location.hash || window.location.hash;
    const match = hash.match(/session_id=([^&]+)/);
    if (!match) {
      navigate("/", { replace: true });
      return;
    }
    const sessionId = match[1];

    (async () => {
      try {
        const r = await api.post("/auth/session", { session_id: sessionId });
        setUser(r.data.user);
        window.history.replaceState({}, "", "/dashboard");
        if (r.data.user?.onboarded) {
          navigate("/dashboard", { replace: true, state: { user: r.data.user } });
        } else {
          navigate("/onboarding", { replace: true, state: { user: r.data.user } });
        }
      } catch (e) {
        console.error("auth callback failed", e);
        if (e?.response?.status === 403) {
          setDenied({ message: e.response?.data?.detail || "Accesso non autorizzato." });
          window.history.replaceState({}, "", "/");
          return;
        }
        navigate("/", { replace: true });
      }
    })();
  }, [location, navigate, setUser]);

  if (denied) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6" data-testid="access-denied">
        <div className="max-w-lg p-8 rounded-2xl bg-white/70 border border-white/50 backdrop-blur-xl shadow-lg text-center">
          <div className="mx-auto w-14 h-14 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center mb-4">
            <ShieldAlert size={28} />
          </div>
          <div className="kicker mb-2">· accesso non autorizzato</div>
          <h1 className="text-2xl font-bold tracking-tight mb-3">Il tuo account non è ancora abilitato</h1>
          <p className="text-neutral-600 text-sm leading-relaxed">{denied.message}</p>
          <button
            data-testid="access-denied-home"
            onClick={() => navigate("/", { replace: true })}
            className="mt-6 px-5 py-2 rounded-full bg-neutral-900 text-white text-sm hover:bg-neutral-800"
          >
            Torna alla home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="kicker">accesso in corso…</div>
    </div>
  );
}
