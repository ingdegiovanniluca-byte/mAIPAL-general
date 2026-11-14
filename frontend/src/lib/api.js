import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

// With no signal the app still opens (on a site with no network): the last answer of a few reads is kept on
// the phone and given back when the network doesn't answer at all - who you are, the commesse, the day,
// the tasks and to dos. Only for the network missing: an answer of the server (401, 500...) is never hidden.
const KEEP = [/^\/auth\/me$/, /^\/jobs\/commesse$/, /^\/jobs\/today$/, /^\/tasks$/, /^\/todos$/];
const CACHE_PREFIX = "maipal-cache:";
const kept = (url) => {
  const path = (url || "").replace(API, "").split("?")[0];
  return KEEP.some((re) => re.test(path)) ? path : null;
};
api.interceptors.response.use(
  (res) => {
    const path = res.config?.method === "get" && kept(res.config.url);
    if (path) {
      try {
        const body = JSON.stringify(res.data);
        if (body.length < 1500000) localStorage.setItem(CACHE_PREFIX + path, body);
      } catch { /* full or blocked: never mind */ }
    }
    return res;
  },
  (err) => {
    const cfg = err.config || {};
    const path = cfg.method === "get" && !err.response && kept(cfg.url);
    if (path) {
      try {
        const body = localStorage.getItem(CACHE_PREFIX + path);
        if (body) return Promise.resolve({ data: JSON.parse(body), status: 200, statusText: "OK", headers: {}, config: cfg, fromCache: true });
      } catch { /* nothing kept */ }
    }
    return Promise.reject(err);
  },
);
// out of the account (or another one): nothing of it stays on the phone
export function clearKeptData() {
  try { Object.keys(localStorage).filter((k) => k.startsWith(CACHE_PREFIX)).forEach((k) => localStorage.removeItem(k)); } catch { /* */ }
}

export async function streamChat(payload, onDelta, onDone, onError, onEvent) {
  try {
    const res = await fetch(`${API}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    });
    if (!res.ok || !res.body) {
      onError && onError(new Error(`HTTP ${res.status}`));
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (!line) continue;
        try {
          const evt = JSON.parse(line);
          if (evt.type === "delta") onDelta && onDelta(evt.content);
          else if (evt.type === "done") onDone && onDone(evt.conv_id);
          else if (evt.type === "error") onError && onError(new Error(evt.content));
          else onEvent && onEvent(evt);
        } catch (_) {}
      }
    }
  } catch (e) {
    onError && onError(e);
  }
}
