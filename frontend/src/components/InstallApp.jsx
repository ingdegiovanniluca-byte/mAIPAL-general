import React, { useState } from "react";
import { Download, X, Share, SquarePlus, MoreVertical } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useInstallState, promptInstall } from "@/lib/pwa";

const DISMISS_KEY = "maipal-install-banner-dismissed";
const readDismissed = () => { try { return localStorage.getItem(DISMISS_KEY) === "1"; } catch { return false; } };

// Installs the app: the browser's own prompt where there is one (Android / desktop Chrome
// and Edge), step-by-step instructions otherwise (iPhone/iPad Safari has no prompt).
export function useInstallApp() {
  const state = useInstallState();
  const [helpOpen, setHelpOpen] = useState(false);
  const install = async () => {
    if (state.canPrompt) await promptInstall();
    else setHelpOpen(true);
  };
  const dialog = (
    <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
      <DialogContent className="max-w-sm border-0 rounded-2xl liquid-glass-panel text-white" data-testid="install-help">
        <DialogHeader>
          <DialogTitle className="text-lg font-bold text-white">Installa mAIPAL</DialogTitle>
        </DialogHeader>
        {state.ios ? (
          <ol className="space-y-3 text-sm text-white/85">
            <li className="flex items-start gap-2"><span className="font-semibold">1.</span><span>In Safari tocca <Share size={14} className="inline -mt-0.5" /> <b>Condividi</b> nella barra in basso.</span></li>
            <li className="flex items-start gap-2"><span className="font-semibold">2.</span><span>Scorri e scegli <SquarePlus size={14} className="inline -mt-0.5" /> <b>Aggiungi alla schermata Home</b>.</span></li>
            <li className="flex items-start gap-2"><span className="font-semibold">3.</span><span>Tocca <b>Aggiungi</b>: mAIPAL si apre dall'icona, a schermo intero, come un'app.</span></li>
          </ol>
        ) : (
          <ol className="space-y-3 text-sm text-white/85">
            <li className="flex items-start gap-2"><span className="font-semibold">1.</span><span>Apri il menu del browser <MoreVertical size={14} className="inline -mt-0.5" /> (in alto a destra).</span></li>
            <li className="flex items-start gap-2"><span className="font-semibold">2.</span><span>Scegli <b>Installa app</b> (o <b>Aggiungi a schermata Home</b>).</span></li>
            <li className="flex items-start gap-2"><span className="font-semibold">3.</span><span>Su computer puoi anche usare l'icona di installazione nella barra degli indirizzi.</span></li>
          </ol>
        )}
      </DialogContent>
    </Dialog>
  );
  return { ...state, install, dialog };
}

// Small dismissible bar above the bottom navigation, mobile only, until installed or closed.
export function InstallBanner({ onInstall }) {
  const [dismissed, setDismissed] = useState(readDismissed);
  if (dismissed) return null;
  const close = () => { setDismissed(true); try { localStorage.setItem(DISMISS_KEY, "1"); } catch { /* ignore */ } };
  return (
    <div
      data-testid="install-banner"
      className="md:hidden fixed left-3 right-3 z-40 liquid-glass-panel !border-0 rounded-2xl px-3 py-2.5 flex items-center gap-3 shadow-lg"
      style={{ bottom: "calc(env(safe-area-inset-bottom, 0px) + 84px)" }}
    >
      <img src={`${process.env.PUBLIC_URL || ""}/icon-192.png`} alt="" className="h-9 w-9 rounded-xl shrink-0" />
      <div className="flex-1 min-w-0 text-xs text-white/90 leading-snug">Installa mAIPAL come app sul telefono</div>
      <button data-testid="install-banner-btn" onClick={onInstall} className="shrink-0 text-xs font-medium px-3 py-1.5 rounded-full bg-white/20 text-white">Installa</button>
      <button onClick={close} aria-label="Chiudi" className="shrink-0 p-1 text-white/60"><X size={14} /></button>
    </div>
  );
}

export const InstallIcon = Download;
