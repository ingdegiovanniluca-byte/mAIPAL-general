import React, { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { ArrowRight, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import logo3 from "@/assets/logo3.png";

const AUTH_ERROR_MESSAGES = {
  not_whitelisted: "Il tuo account non è ancora abilitato. Contatta l'amministratore per essere aggiunto alla whitelist.",
  denied: "Accesso negato da Google.",
  invalid_state: "Sessione di accesso scaduta, riprova.",
  oauth_failed: "Accesso con Google non riuscito, riprova.",
  no_email: "Impossibile leggere l'email dal tuo account Google.",
};

const DEMO_USER_LINE = "Ricordami di chiamare il fornitore martedì alle 15";
const DEMO_REPLY_LINE = "✅ Fatto — task creato con scadenza, tag e priorità.";

function GoogleGIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332z" />
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.581C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 7.294C4.672 5.167 6.656 3.58 9 3.58z" />
    </svg>
  );
}

function TypewriterDemo() {
  const [userText, setUserText] = useState("");
  const [replyText, setReplyText] = useState("");
  const [phase, setPhase] = useState("user"); // "user" | "reply" | "hold"

  useEffect(() => {
    const timers = [];
    const t = (fn, ms) => timers.push(setTimeout(fn, ms));

    const run = () => {
      setUserText("");
      setReplyText("");
      setPhase("user");
      let i = 0;
      const typeUser = () => {
        i++;
        setUserText(DEMO_USER_LINE.slice(0, i));
        if (i < DEMO_USER_LINE.length) {
          t(typeUser, 40);
        } else {
          t(() => {
            setPhase("reply");
            let j = 0;
            const typeReply = () => {
              j++;
              setReplyText(DEMO_REPLY_LINE.slice(0, j));
              if (j < DEMO_REPLY_LINE.length) {
                t(typeReply, 32);
              } else {
                setPhase("hold");
                t(run, 3200);
              }
            };
            typeReply();
          }, 700);
        }
      };
      typeUser();
    };

    run();
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="liquid-glass-panel rounded-2xl p-5 md:p-6 max-w-2xl w-full" data-testid="login-typing-demo">
      <div className="flex items-start gap-2.5">
        <span className="text-[10px] uppercase tracking-widest text-white/45 shrink-0 mt-1.5">tu</span>
        <div className="text-sm md:text-base font-medium leading-snug min-h-[1.4em]">
          {userText}
          {phase === "user" && <span className="inline-block w-[2px] h-[1em] bg-white/70 align-middle ml-0.5 animate-pulse" />}
        </div>
      </div>
      {(phase === "reply" || phase === "hold") && (
        <div className="flex items-start gap-2.5 mt-3 pt-3 border-t border-white/10">
          <span className="text-[10px] uppercase tracking-widest text-white/45 shrink-0 mt-1.5">mAIPAL</span>
          <div className="text-sm md:text-base font-medium text-white/90 leading-snug min-h-[1.4em]">
            {replyText}
            {phase === "reply" && <span className="inline-block w-[2px] h-[1em] bg-white/70 align-middle ml-0.5 animate-pulse" />}
          </div>
        </div>
      )}
    </div>
  );
}

function EmailPasswordForm({ initialMode = "login" }) {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [mode, setMode] = useState(initialMode); // "login" | "register"
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { setMode(initialMode); }, [initialMode]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/register";
      const body = mode === "login" ? { email, password } : { email, password, name };
      const r = await api.post(path, body);
      setUser(r.data.user);
      navigate(r.data.user?.onboarded ? "/dashboard" : "/onboarding", { replace: true });
    } catch (e) {
      setError(e?.response?.data?.detail || "Operazione non riuscita, riprova.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      {mode === "register" && (
        <div className="mb-3">
          <div className="text-[10px] uppercase tracking-widest text-white/45 mb-1">nome</div>
          <input
            data-testid="register-name-input"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="w-full px-4 py-2.5 rounded-xl bg-white/10 border border-white/15 text-sm text-white outline-none focus:border-white/35"
          />
        </div>
      )}
      <div className="mb-3">
        <div className="text-[10px] uppercase tracking-widest text-white/45 mb-1">email</div>
        <input
          data-testid="email-input"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="w-full px-4 py-2.5 rounded-xl bg-white/10 border border-white/15 text-sm text-white outline-none focus:border-white/35"
        />
      </div>
      <div className="mb-4">
        <div className="text-[10px] uppercase tracking-widest text-white/45 mb-1">password</div>
        <input
          data-testid="password-input"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={mode === "register" ? 8 : undefined}
          className="w-full px-4 py-2.5 rounded-xl bg-white/10 border border-white/15 text-sm text-white outline-none focus:border-white/35"
        />
      </div>

      <button
        data-testid="email-submit-btn"
        type="submit"
        disabled={loading}
        className="w-full py-3 rounded-full bg-black text-white text-sm font-medium hover:bg-black/80 transition-colors disabled:opacity-50"
      >
        {loading ? "…" : mode === "login" ? "Accedi" : "Registrati"}
      </button>

      {error && (
        <div data-testid="email-auth-error" className="mt-3 flex items-center gap-2 text-sm text-amber-400">
          <ShieldAlert size={16} /> {error}
        </div>
      )}

      <button
        type="button"
        data-testid="toggle-register-mode"
        onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}
        className="mt-3 block text-sm text-white/60 hover:text-white/90 underline mx-auto"
      >
        {mode === "login" ? "Non hai un account? Registrati" : "Hai già un account? Accedi"}
      </button>
    </form>
  );
}

function AuthModal({ initialMode, authError, onClose }) {
  const handleGoogleLogin = () => {
    window.location.href = `${process.env.REACT_APP_BACKEND_URL}/api/auth/google/login`;
  };

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent
        className="font-poppins max-w-sm border-0 rounded-3xl liquid-glass-panel wobble-glass text-white [&>button:last-child]:text-white/70 [&>button:last-child]:hover:text-white"
        data-testid="auth-modal"
      >
        <DialogHeader>
          <DialogTitle className="text-center text-lg font-semibold text-white">
            {initialMode === "register" ? "Crea il tuo account" : "Bentornato"}
          </DialogTitle>
        </DialogHeader>

        <button
          data-testid="login-google-btn"
          onClick={handleGoogleLogin}
          className="w-full flex items-center justify-center gap-2.5 py-3 rounded-full bg-white text-[#403A3C] text-sm font-medium hover:bg-white/90 transition-colors"
        >
          <GoogleGIcon /> Continua con Google
        </button>

        <div className="flex items-center gap-3 my-1">
          <div className="flex-1 h-px bg-white/15" />
          <span className="text-xs text-white/50">o</span>
          <div className="flex-1 h-px bg-white/15" />
        </div>

        {authError && (
          <div data-testid="login-auth-error" className="mb-1 flex items-center gap-2 text-sm text-amber-400">
            <ShieldAlert size={16} />
            {AUTH_ERROR_MESSAGES[authError] || "Accesso non riuscito, riprova."}
          </div>
        )}

        <EmailPasswordForm initialMode={initialMode} />
      </DialogContent>
    </Dialog>
  );
}

export default function LoginPage() {
  const [searchParams] = useSearchParams();
  const authError = searchParams.get("auth_error");
  const [authModalMode, setAuthModalMode] = useState(null); // null | "login" | "register"

  useEffect(() => {
    if (authError) setAuthModalMode("login");
  }, [authError]);

  return (
    <div className="font-poppins h-screen w-full relative overflow-hidden">
      <div className="liquid-page-bg" aria-hidden="true">
        <span className="liquid-blob liquid-blob-1" />
        <span className="liquid-blob liquid-blob-2" />
        <span className="liquid-blob liquid-blob-3" />
        <span className="liquid-blob liquid-blob-4" />
        <span className="liquid-blob liquid-blob-5" />
      </div>

      <div className="relative z-10 h-full w-full flex flex-col p-6 md:p-10 xl:p-14">
        <div className="flex items-center justify-between shrink-0">
          <div
            className="logo-wave h-10 md:h-12 aspect-[345/539] shrink-0"
            style={{ WebkitMaskImage: `url(${logo3})`, maskImage: `url(${logo3})` }}
            role="img"
            aria-label="mAIPAL"
          />
          <div className="flex items-center gap-2">
            <button
              data-testid="open-login-btn"
              onClick={() => setAuthModalMode("login")}
              className="liquid-glass-btn text-sm px-5 py-2 rounded-full"
            >
              Accedi
            </button>
            <button
              data-testid="open-register-btn"
              onClick={() => setAuthModalMode("register")}
              className="liquid-glass-btn text-sm px-5 py-2 rounded-full flex items-center gap-1.5"
            >
              Registrati <ArrowRight size={14} />
            </button>
          </div>
        </div>

        <div className="mt-8 md:mt-12 max-w-2xl">
          <p className="text-[10px] uppercase tracking-widest text-white/45 mb-2">cosa vuoi fare oggi?</p>
          <h1 className="text-xl md:text-3xl font-bold text-white leading-tight">
            Fai fare a <span className="gradient-text-wave">mAIPAL</span> quello che non hai tempo di fare.
          </h1>
          <p className="mt-3 text-white/70 text-sm md:text-base">
            Un segretario AI pensato apposta per piccole imprese, privati e liberi professionisti: puoi scegliere il verticale ottimizzato per il tuo specifico lavoro in base alla tua attività. Gestisce task e to-do, genera report, registra informazioni e gestisce i tuoi clienti. Parlaci in chat o con messaggi vocali, anche su Telegram, senza dover imparare una nuova app: proprio come se ti interfacciassi con un vero segretario.
          </p>
        </div>

        <div className="flex-1" />

        <div className="flex justify-center lg:justify-end pb-4 md:pb-8">
          <TypewriterDemo />
        </div>
      </div>

      {authModalMode && (
        <AuthModal
          initialMode={authModalMode}
          authError={authError}
          onClose={() => setAuthModalMode(null)}
        />
      )}
    </div>
  );
}
