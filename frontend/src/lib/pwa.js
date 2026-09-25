// App installabile (PWA): service worker, prompt di installazione e contenuti condivisi
// verso mAIPAL dal menu "Condividi" del telefono (vedi public/sw.js e public/manifest.json).
import { useEffect, useState } from "react";

const BASE = process.env.PUBLIC_URL || "";
let deferredPrompt = null;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn());

export function initPwa() {
  if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register(`${BASE}/sw.js`, { scope: `${BASE}/` }).catch(() => {});
    });
  }
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredPrompt = e; notify(); });
  window.addEventListener("appinstalled", () => { deferredPrompt = null; notify(); });
}

export const isStandalone = () =>
  (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;

export const isIos = () =>
  /iphone|ipad|ipod/i.test(window.navigator.userAgent) || (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1);

export async function promptInstall() {
  if (!deferredPrompt) return "unavailable";
  deferredPrompt.prompt();
  const choice = await deferredPrompt.userChoice.catch(() => ({ outcome: "dismissed" }));
  deferredPrompt = null;
  notify();
  return choice.outcome;
}

export function useInstallState() {
  const read = () => ({ standalone: isStandalone(), canPrompt: !!deferredPrompt, ios: isIos() });
  const [state, setState] = useState(read);
  useEffect(() => {
    const fn = () => setState(read());
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);
  return state;
}

// Files/text another app shared to mAIPAL: parked by the service worker, taken (and
// removed) here once, as { title, text, url, files: File[] } - null when there's nothing.
export async function takeSharedPayload() {
  if (!("caches" in window)) return null;
  try {
    const cache = await caches.open("maipal-share-inbox");
    const metaRes = await cache.match(`${BASE}/__share/meta`);
    if (!metaRes) return null;
    const meta = await metaRes.json();
    const files = [];
    for (const f of meta.files || []) {
      const r = await cache.match(f.key);
      if (r) files.push(new File([await r.blob()], f.name, { type: f.type }));
      await cache.delete(f.key);
    }
    await cache.delete(`${BASE}/__share/meta`);
    return { title: meta.title || "", text: meta.text || "", url: meta.url || "", files };
  } catch {
    return null;
  }
}
