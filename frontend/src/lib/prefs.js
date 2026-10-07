import { useEffect, useState } from "react";

/* Per-device preferences kept in localStorage. Changing one fires "maipal:prefs" so every
   open page picks it up at once (Impostazioni -> Chat without a reload). */
const KEY = "maipal.prefs";
const DEFAULTS = {
  micSide: "right",   // chat composer: voice button on the right or left
  // mobile bottom bar: the sections next to Chat (at most 3), chosen in the "+" menu
  pinnedSections: ["/dashboard/tasks", "/dashboard/todos", "/dashboard/liste"],
};

function readAll() {
  try { return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) || "{}") || {}) }; }
  catch { return { ...DEFAULTS }; }
}

export function getPref(name) { return readAll()[name]; }

export function setPref(name, value) {
  const all = { ...readAll(), [name]: value };
  try { localStorage.setItem(KEY, JSON.stringify(all)); } catch { /* private mode: this session only */ }
  window.dispatchEvent(new CustomEvent("maipal:prefs", { detail: { name, value } }));
}

export function usePref(name) {
  const [value, setValue] = useState(() => getPref(name));
  useEffect(() => {
    const on = (e) => { if (!e.detail || e.detail.name === name) setValue(getPref(name)); };
    window.addEventListener("maipal:prefs", on);
    return () => window.removeEventListener("maipal:prefs", on);
  }, [name]);
  return [value, (v) => setPref(name, v)];
}
