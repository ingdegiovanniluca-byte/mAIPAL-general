// The diary's "outbox": on a site with no signal an entry is kept on the phone (IndexedDB) and sent by
// itself as soon as the network is back - in the order it was written, with the moment it was written
// (its day is that one) and its own id (sent twice, saved once: the server knows it). A voice note is
// kept as audio and transcribed when it is sent. What mAIPAL answers then (saved, or a question such as
// "quale commessa?") is told to the page that is open, or kept for the chat (takeReplies).
import { api, API } from "@/lib/api";

const DB_NAME = "maipal-outbox";
const ENTRIES = "diary";
const REPLIES = "replies";
const listeners = new Set();

function openDb() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new Error("no indexedDB")); return; }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(ENTRIES)) db.createObjectStore(ENTRIES, { keyPath: "client_id" });
      if (!db.objectStoreNames.contains(REPLIES)) db.createObjectStore(REPLIES, { keyPath: "client_id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function tx(store, mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const out = fn(t.objectStore(store));
    t.oncomplete = () => resolve(out && "result" in out ? out.result : undefined);
    t.onerror = () => reject(t.error);
  });
}
const all = (store) => tx(store, "readonly", (s) => s.getAll()).then((x) => x || []).catch(() => []);

export const newClientId = () =>
  (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

// no answer at all (no network, the connection dropped): not an answer of the server
export const isNetworkError = (e) => !!e && !e.response && (e.code === "ERR_NETWORK" || e.message === "Network Error" || e.code === "ECONNABORTED" || !navigator.onLine || e.name === "TypeError");

export async function pendingCount() { return (await all(ENTRIES)).length; }
export function onOutboxChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
const changed = async () => { const n = await pendingCount(); listeners.forEach((fn) => fn(n)); };

// kept on the phone: {client_id, text, images, voice (Blob), commessa_id, hint_commessa_id, written_at, label}
export async function keepDiaryEntry(entry) {
  const e = { tries: 0, ...entry, written_at: entry.written_at || new Date().toISOString() };
  await tx(ENTRIES, "readwrite", (s) => s.put(e));
  changed();
  return e;
}

async function transcribe(blob) {
  const fd = new FormData();
  fd.append("file", blob, "voice.webm");
  fd.append("action", "job_log");
  const res = await fetch(`${API}/voice/transcribe`, { method: "POST", body: fd, credentials: "include" });
  if (!res.ok) { const err = new Error(`HTTP ${res.status}`); err.response = { status: res.status }; throw err; }
  return ((await res.json()).text || "").trim();
}

// what mAIPAL answered to an entry sent later, when no page took it: shown by the chat when it opens
export async function takeReplies() {
  const list = await all(REPLIES);
  if (list.length) await tx(REPLIES, "readwrite", (s) => list.forEach((r) => s.delete(r.client_id))).catch(() => {});
  return list.sort((a, b) => (a.written_at || "").localeCompare(b.written_at || ""));
}

let running = null;
// sends what is waiting, one after the other; stops at the first network failure (it'll be the next time)
export function flushOutbox() {
  if (running) return running;
  running = (async () => {
    let sent = 0;
    try {
      const list = (await all(ENTRIES)).sort((a, b) => (a.written_at || "").localeCompare(b.written_at || ""));
      for (const e of list) {
        if (typeof navigator !== "undefined" && navigator.onLine === false) break;
        let text = e.text || "";
        try {
          if (e.voice) {
            const said = await transcribe(e.voice);
            text = [text, said].filter(Boolean).join(" ").trim();
            if (!text) text = e.images?.length ? "Foto dal cantiere" : "";
          }
          if (!text) { await tx(ENTRIES, "readwrite", (s) => s.delete(e.client_id)); continue; }
          const r = await api.post("/jobs/logs", { text, images: e.images || [], commessa_id: e.commessa_id || undefined,
            hint_commessa_id: e.hint_commessa_id || undefined, client_id: e.client_id, written_at: e.written_at });
          await tx(ENTRIES, "readwrite", (s) => s.delete(e.client_id));
          sent += 1;
          const reply = { client_id: e.client_id, text, images: e.images || [], written_at: e.written_at, res: r.data, commessa_id: e.commessa_id };
          const ev = new CustomEvent("maipal-outbox-sent", { detail: reply, cancelable: true });
          // a page that shows it (the chat with that entry) calls preventDefault: otherwise kept for later
          if (window.dispatchEvent(ev) && !["ok", "planned", "description", "commessa_update"].includes(r.data?.status)) {
            await tx(REPLIES, "readwrite", (s) => s.put(reply)).catch(() => {});
          }
        } catch (err) {
          if (isNetworkError(err)) break;   // still no network: next time
          // refused by the server (not the network): not sent again forever; told
          await tx(ENTRIES, "readwrite", (s) => s.delete(e.client_id));
          window.dispatchEvent(new CustomEvent("maipal-outbox-failed", { detail: { ...e, error: err.response?.data?.detail || err.message } }));
        }
      }
    } finally {
      running = null;
      changed();
    }
    return sent;
  })();
  return running;
}
