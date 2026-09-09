import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/auth/AuthContext";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const VERTICALS = ["Lavoro", "Gestione tempo libero", "Vita privata"];
const TONES = ["formale", "informale", "sintetico", "dettagliato"];

export default function OnboardingPage() {
  const nav = useNavigate();
  const { user, setUser } = useAuth();
  const [step, setStep] = useState(0);
  const [profession, setProfession] = useState("");
  const [sector, setSector] = useState("");
  const [verticals, setVerticals] = useState([]);
  const [interests, setInterests] = useState("");
  const [tone, setTone] = useState("informale");
  const [homeAddress, setHomeAddress] = useState("");
  const [workAddress, setWorkAddress] = useState("");
  const [saving, setSaving] = useState(false);

  const toggleVertical = (v) => {
    setVerticals((s) => (s.includes(v) ? s.filter((x) => x !== v) : [...s, v]));
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.post("/onboarding", {
        profession, sector, verticals,
        interests: interests.split(",").map((s) => s.trim()).filter(Boolean),
        tone,
        home_address: homeAddress,
        work_address: workAddress,
      });
      const me = await api.get("/auth/me");
      setUser(me.data);
      nav("/dashboard", { replace: true });
    } finally { setSaving(false); }
  };

  const steps = [
    {
      title: "Raccontami qualcosa sul tuo lavoro",
      body: (
        <div className="space-y-4">
          <div>
            <div className="kicker mb-2">professione</div>
            <Input data-testid="ob-profession" value={profession} onChange={(e) => setProfession(e.target.value)} placeholder="es. Product Manager" className="h-14 rounded-2xl text-lg bg-white/10" />
          </div>
          <div>
            <div className="kicker mb-2">settore</div>
            <Input data-testid="ob-sector" value={sector} onChange={(e) => setSector(e.target.value)} placeholder="es. Fintech" className="h-14 rounded-2xl text-lg bg-white/10" />
          </div>
        </div>
      ),
    },
    {
      title: "Per cosa userai mAIPAL?",
      body: (
        <div className="flex flex-wrap gap-3">
          {VERTICALS.map((v) => (
            <button
              key={v}
              data-testid={`ob-vertical-${v}`}
              onClick={() => toggleVertical(v)}
              style={verticals.includes(v) ? { backgroundColor: "#CECAD0", color: "#fff", border: "none" } : {}}
              className={`px-5 py-3 rounded-full transition-colors duration-150 ${verticals.includes(v) ? "" : "bg-white/10  hover:"}`}
            >{v}</button>
          ))}
        </div>
      ),
    },
    {
      title: "Cosa ti interessa fuori dal lavoro?",
      body: (
        <div>
          <div className="kicker mb-2">tag separati da virgola</div>
          <Textarea data-testid="ob-interests" value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="palestra, viaggi, cucina, cinema" className="rounded-2xl text-lg bg-white/10 min-h-[120px]" />
        </div>
      ),
    },
    {
      title: "Che tono preferisci?",
      body: (
        <div className="flex flex-wrap gap-3">
          {TONES.map((t) => (
            <button
              key={t}
              data-testid={`ob-tone-${t}`}
              onClick={() => setTone(t)}
              style={tone === t ? { backgroundColor: "#CECAD0", color: "#fff", border: "none" } : {}}
              className={`px-5 py-3 rounded-full transition-colors duration-150 ${tone === t ? "" : "bg-white/10  hover:"}`}
            >{t}</button>
          ))}
        </div>
      ),
    },
    {
      title: "I tuoi indirizzi (facoltativi)",
      body: (
        <div className="space-y-4">
          <div>
            <div className="kicker mb-2">indirizzo di casa</div>
            <Input data-testid="ob-home" value={homeAddress} onChange={(e) => setHomeAddress(e.target.value)} placeholder="Via Roma 10, Milano" className="h-14 rounded-2xl text-lg bg-white/10" />
          </div>
          <div>
            <div className="kicker mb-2">indirizzo di lavoro</div>
            <Input data-testid="ob-work" value={workAddress} onChange={(e) => setWorkAddress(e.target.value)} placeholder="Via Uffici 20, Milano" className="h-14 rounded-2xl text-lg bg-white/10" />
          </div>
          <div className="text-xs text-white/60">Servono a mAIPAL per calcolare tragitti, aggiungerli agli eventi, o rispondere a domande contestuali.</div>
        </div>
      ),
    },
  ];

  const current = steps[step];
  const isLast = step === steps.length - 1;

  return (
    <div className="min-h-screen p-10 md:p-16 max-w-3xl mx-auto flex flex-col">
      <div className="kicker">onboarding · {step + 1} / {steps.length}</div>
      <h1 className="mt-3 text-4xl md:text-5xl font-bold tracking-tight">
        Ciao {user?.name?.split(" ")[0] || ""}, <span className="gradient-word">personalizziamoci</span>.
      </h1>
      <p className="mt-3 text-white/70 text-lg">{current.title}</p>

      <div className="mt-10 flex-1">{current.body}</div>

      <div className="mt-10 flex items-center justify-between">
        <button
          data-testid="ob-back"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          className="text-white/60 hover:text-black disabled:opacity-30"
        >← indietro</button>
        {!isLast ? (
          <button data-testid="ob-next" onClick={() => setStep((s) => s + 1)} className="pill-btn">Avanti →</button>
        ) : (
          <button data-testid="ob-save" onClick={save} disabled={saving} className="pill-btn">
            {saving ? "Salvo…" : "Fatto, avvia mAIPAL →"}
          </button>
        )}
      </div>
    </div>
  );
}
