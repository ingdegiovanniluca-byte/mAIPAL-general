// The life of a commessa (specifica commesse 3.3, + "sospesa"): the same names as the backend
// (verticals.COMMESSA_STATI); the old ones are read as the new.
export const STATI = ["nuova", "sopralluogo", "preventivo inviato", "in lavorazione", "sospesa", "persa", "completata", "archiviata"];
const LEGACY = { preventivo: "preventivo inviato", "in corso": "in lavorazione", chiusa: "completata" };
export const normStato = (s) => {
  const x = String(s || "").toLowerCase().replace(/_/g, " ").trim().replace(/\s+/g, " ");
  return LEGACY[x] || x || "nuova";
};
export const CLOSED = new Set(["persa", "completata", "archiviata"]);
export const isClosed = (s) => CLOSED.has(normStato(s));
export const STATO_COLOR = {
  nuova: "#B9C3FF", sopralluogo: "#7FD3F0", "preventivo inviato": "#F2C14E", "in lavorazione": "#8ED973",
  sospesa: "#E8A03F", persa: "#F08A8A", completata: "rgba(255,255,255,0.45)", archiviata: "rgba(255,255,255,0.25)",
};
export const stateColor = (s) => STATO_COLOR[normStato(s)] || "rgba(255,255,255,0.4)";
// the list: in lavorazione first, then the ones being prepared, the closed ones last
export const STATO_ORDER = { "in lavorazione": 0, sopralluogo: 1, "preventivo inviato": 2, nuova: 3, sospesa: 4, completata: 5, persa: 6, archiviata: 7 };
export const LOST_CATEGORIES = [
  ["prezzo", "Prezzo"], ["tempi", "Tempi"], ["concorrente", "Concorrente"], ["rinuncia_cliente", "Rinuncia del cliente"], ["altro", "Altro"],
];
