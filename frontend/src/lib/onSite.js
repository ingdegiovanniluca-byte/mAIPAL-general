/* Who is on site now, grouped by their role (elettricisti, idraulici…): the team of the app
   together, the collaborators without a role last. Used by the diary's figures and the map. */

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// "elettricista" -> "elettricisti", "idraulico" -> "idraulici", "muratore" -> "muratori"
// (only the first word: "tecnico caldaie" -> "tecnici caldaie")
export function pluralRole(role) {
  const [w, ...rest] = role.split(" ");
  // the roles of a site are masculine nouns: -o, -e, -a -> -i ("geometra" -> "geometri")
  return [/[oea]$/i.test(w) ? w.slice(0, -1) + "i" : w, ...rest].join(" ");
}

export function groupOnSite(people = []) {
  const groups = new Map();
  people.forEach((p) => {
    const role = (p.role || "").trim().replace(/\s+/g, " ");
    const key = p.is_user ? "~team" : role ? role.toLowerCase() : "~other";
    const g = groups.get(key) || { key, role: p.is_user ? "" : role, people: [] };
    g.people.push(p);
    groups.set(key, g);
  });
  const rank = (g) => (g.key === "~team" ? 0 : g.key === "~other" ? 2 : 1);
  return [...groups.values()]
    .sort((a, b) => rank(a) - rank(b) || a.key.localeCompare(b.key))
    .map((g) => ({
      ...g,
      label: g.key === "~team" ? "Squadra" : g.key === "~other" ? "Altri" : cap(g.people.length > 1 ? pluralRole(g.role.toLowerCase()) : g.role.toLowerCase()),
    }));
}

// "2 elettricisti, 1 idraulico" (or the names, when nobody has a role)
export function onSiteSummary(people = []) {
  const groups = groupOnSite(people);
  if (groups.length === 1 && groups[0].key === "~other") return "";
  const n = (g) => g.people.length;
  return groups.map((g) => (g.key === "~team" ? `${n(g)} della squadra` : g.key === "~other" ? `${n(g)} ${n(g) > 1 ? "altri" : "altro"}`
    : `${n(g)} ${g.label.toLowerCase()}`)).join(", ");
}

export const firstName = (p) => (p.name || "").split(" ")[0];
