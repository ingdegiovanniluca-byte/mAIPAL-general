// @agenti nella chat - same rules as backend/mentions.py: "@task ..." (or dictated
// "agente task ..." / "chiocciola task ...") at the start of a word; an e-mail address is
// never a tag. Used for the "@" menu, the chips under the box and the highlighted tags.
export const MENTION_AGENTS = [
  { key: "task_todo", tag: "task", aliases: ["task", "todo", "to-do", "promemoria"], label: "Task / To-Do", hint: "crea un task o un promemoria", color: "#7C6A7D" },
  { key: "info_upload", tag: "nota", aliases: ["nota", "salva", "info"], label: "Salva informazione", hint: "salva un'informazione", color: "#6D6181" },
  { key: "info_request", tag: "cerca", aliases: ["cerca", "chiedi"], label: "Cerca", hint: "fai una domanda sui tuoi dati", color: "#DD772F" },
  { key: "journal", tag: "diario", aliases: ["diario"], label: "Diario", hint: "aggiungi al diario", color: "#8E2E11" },
  { key: "list_update", tag: "lista", aliases: ["lista", "liste"], label: "Lista", hint: "modifica una lista", color: "#2E5F7D" },
  { key: "scheduled_action", tag: "azione", aliases: ["azione", "azioni"], label: "Azione programmata", hint: "programma un'azione ricorrente", color: "#3E7C8C" },
];
const BY_ALIAS = {};
MENTION_AGENTS.forEach((a) => a.aliases.forEach((al) => { BY_ALIAS[al] = a; }));
const NAMES = Object.keys(BY_ALIAS).sort((a, b) => b.length - a.length).map((n) => n.replace(/[-]/g, "\\-")).join("|");
const TAG_RE = new RegExp(`(^|[\\s(\\[,;.!?])((?:@\\s?|(?:agente|chiocciola)\\s+)(${NAMES}))(?![\\w-])\\s*[:,]?`, "gi");

export const agentByKey = (key) => MENTION_AGENTS.find((a) => a.key === key);

// -> { main, parts: [{ agent, tag, text }] }
export function splitMentions(text) {
  const t = text || "";
  const matches = [];
  TAG_RE.lastIndex = 0;
  let m;
  while ((m = TAG_RE.exec(t)) !== null) {
    matches.push({ start: m.index + m[1].length, end: TAG_RE.lastIndex, alias: m[3].toLowerCase() });
  }
  if (!matches.length) return { main: t.trim(), parts: [] };
  const parts = [];
  matches.forEach((mm, i) => {
    const end = i + 1 < matches.length ? matches[i + 1].start : t.length;
    const piece = t.slice(mm.end, end).trim().replace(/^[,;]+|[,;]+$/g, "").trim();
    if (piece) parts.push({ agent: BY_ALIAS[mm.alias].key, tag: mm.alias, text: piece });
  });
  return { main: t.slice(0, matches[0].start).trim(), parts };
}

// Splits text into plain strings and { tag, agent } tokens, for colored rendering.
export function tokenizeMentions(text) {
  const t = text || "";
  const out = [];
  let last = 0;
  TAG_RE.lastIndex = 0;
  let m;
  while ((m = TAG_RE.exec(t)) !== null) {
    const start = m.index + m[1].length;
    if (start > last) out.push(t.slice(last, start));
    out.push({ tag: m[2].trim(), agent: BY_ALIAS[m[3].toLowerCase()] });
    last = start + m[2].length;
  }
  if (last < t.length) out.push(t.slice(last));
  return out;
}

// The "@..." being typed right before the caret, or null.
export function mentionQueryAt(text, caret) {
  const before = (text || "").slice(0, caret);
  const m = before.match(/(^|\s)@([\w-]*)$/);
  return m ? m[2].toLowerCase() : null;
}

// ===== persone e gruppi del team (same slugs as backend/mentions.py people_directory) =====
export const GROUP_TAGS = ["team", "tutti"];
const AGENT_ALIASES = new Set(Object.keys(BY_ALIAS));
export const PERSON_COLOR = "#4E7FA8";

export function slugify(name) {
  const s = (name || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, ".").replace(/^\.+|\.+$/g, "");
  return s || "utente";
}

// -> [{ slug, name, user_id, kind: "person" | "group" }] for the "@" menu
export function buildPeopleDirectory(members, selfId) {
  const out = [];
  const used = new Set();
  [...(members || [])].sort((a, b) => ((a.user_id || "") < (b.user_id || "") ? -1 : 1)).forEach((m) => {
    let slug = slugify(m.name || (m.email || "").split("@")[0]);
    if (used.has(slug) || GROUP_TAGS.includes(slug) || AGENT_ALIASES.has(slug)) slug = `${slug}-${(m.user_id || "").slice(-4)}`;
    used.add(slug);
    if (m.user_id !== selfId) out.push({ slug, name: m.name || m.email, user_id: m.user_id, kind: "person" });
  });
  if (out.length) out.unshift({ slug: "team", name: "Tutto il team", kind: "group" });
  return out;
}

const PEOPLE_RE = /(^|[\s(\[,;.!?])@([a-z0-9][a-z0-9.-]*[a-z0-9]|[a-z0-9])(?![\w@])/gi;

// The people/group tags present in a text -> [{ slug, name }]
export function findPeople(text, directory) {
  const bySlug = Object.fromEntries((directory || []).map((p) => [p.slug, p]));
  const found = [];
  let m;
  PEOPLE_RE.lastIndex = 0;
  while ((m = PEOPLE_RE.exec(text || "")) !== null) {
    const slug = m[2].toLowerCase().replace(/\.+$/, "");
    const p = bySlug[slug];
    if (p && !found.some((f) => f.slug === slug)) found.push(p);
  }
  return found;
}

// tokenizeMentions + person/group tags, for the colored rendering of a sent message
export function tokenizeAll(text, directory) {
  const bySlug = Object.fromEntries((directory || []).map((p) => [p.slug, p]));
  const out = [];
  tokenizeMentions(text).forEach((tk) => {
    if (typeof tk !== "string") { out.push(tk); return; }
    let last = 0;
    let m;
    PEOPLE_RE.lastIndex = 0;
    while ((m = PEOPLE_RE.exec(tk)) !== null) {
      const slug = m[2].toLowerCase().replace(/\.+$/, "");
      const p = bySlug[slug];
      if (!p) continue;
      const start = m.index + m[1].length;
      if (start > last) out.push(tk.slice(last, start));
      out.push({ tag: `@${m[2]}`, person: p });
      last = start + 1 + m[2].length;
    }
    if (last < tk.length) out.push(tk.slice(last));
  });
  return out;
}
