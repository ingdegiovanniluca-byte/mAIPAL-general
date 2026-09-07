import React from "react";
import { useSearchParams } from "react-router-dom";
import { Sparkles, ArrowRight, ShieldAlert } from "lucide-react";

const AUTH_ERROR_MESSAGES = {
  not_whitelisted: "Il tuo account non è ancora abilitato. Contatta l'amministratore per essere aggiunto alla whitelist.",
  denied: "Accesso negato da Google.",
  invalid_state: "Sessione di accesso scaduta, riprova.",
  oauth_failed: "Accesso con Google non riuscito, riprova.",
  no_email: "Impossibile leggere l'email dal tuo account Google.",
};

export default function LoginPage() {
  const [searchParams] = useSearchParams();
  const authError = searchParams.get("auth_error");

  const handleLogin = () => {
    window.location.href = `${process.env.REACT_APP_BACKEND_URL}/api/auth/google/login`;
  };

  return (
    <div className="min-h-screen w-full flex flex-col md:flex-row">
      <div className="flex-1 flex flex-col justify-between p-10 md:p-16">
        <div>
          <div className="kicker" data-testid="brand-kicker">mAIPAL · segretario digitale</div>
        </div>

        <div className="max-w-xl">
          <div className="kicker mb-4">Cosa vuoi fare oggi?</div>
          <h1 className="text-5xl md:text-7xl font-bold tracking-tight leading-[1.02]">
            Fai fare a{" "}
            <span className="gradient-word">mAIPAL</span>
            <br />
            quello che non hai tempo di fare.
          </h1>
          <p className="mt-6 text-lg text-white/70 max-w-lg">
            Un assistente personale che apprende dalle tue informazioni, gestisce task e to-do,
            e risponde con la tua knowledge base. Chatta, salva, organizza.
          </p>

          <button
            data-testid="login-google-btn"
            onClick={handleLogin}
            className="pill-btn mt-10 text-base px-6 py-3.5"
          >
            <Sparkles size={16} /> Accedi con Google
            <ArrowRight size={18} />
          </button>

          {authError && (
            <div data-testid="login-auth-error" className="mt-4 flex items-center gap-2 text-sm text-amber-400">
              <ShieldAlert size={16} />
              {AUTH_ERROR_MESSAGES[authError] || "Accesso non riuscito, riprova."}
            </div>
          )}

          <div className="mt-4 kicker">powered by claude sonnet 5</div>
        </div>

        <div className="flex items-center gap-6 kicker">
          <span>chat</span><span>·</span><span>task</span><span>·</span><span>to-do</span>
        </div>
      </div>

      <div
        className="hidden md:block md:flex-1 relative overflow-hidden"
        style={{
          backgroundImage:
            "url('https://images.unsplash.com/photo-1646038572822-432f8ccf2522?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2MzR8MHwxfHNlYXJjaHwxfHxhYnN0cmFjdCUyMGdyYWRpZW50JTIwYmx1ciUyMG9yYW5nZSUyMGJsdWV8ZW58MHx8fHwxNzg4Njk5Mzc4fDA&ixlib=rb-4.1.0&q=85')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-black/5" />
        <div className="absolute bottom-10 left-10 right-10 bg-white/5 backdrop-blur-md rounded-2xl p-6 ">
          <div className="kicker">preview</div>
          <div className="mt-2 text-lg font-medium">
            &ldquo;Ricordami di chiamare il fornitore martedì alle 15&rdquo; → task creato con scadenza, tag e priorità.
          </div>
        </div>
      </div>
    </div>
  );
}
