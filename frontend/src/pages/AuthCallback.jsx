import React, { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";

export default function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);

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
        navigate("/", { replace: true });
      }
    })();
  }, [location, navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="kicker">accesso in corso…</div>
    </div>
  );
}
