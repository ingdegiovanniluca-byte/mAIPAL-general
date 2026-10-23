/* The agents' drops: data from the "Gocce Agenti" prototype (const AGENTS, MATS, STATES, EYES),
   plus the three agents the prototype doesn't have - Referto (vet), Lezioni (fitness), Help -
   drawn in the same style. Only Cerca, Report and Azioni wear an accessory. */

export const AGENTS = {
  cerca:   { name: "Cerca",   a: "#f26a00", b: "#ffa733", mat: "vetro", tip: .72, wav: 1,   glw: .7, acc: "occhiali",   eye: "tondi",     beh: "search" },
  salva:   { name: "Salva",   a: "#00586e", b: "#1fb2cf", mat: "vetro", tip: .6,  wav: .9,  glw: .9, acc: "",           eye: "mezzaluna", beh: "save" },
  task:    { name: "Task",    a: "#ffa733", b: "#ffe2a6", mat: "vetro", tip: .7,  wav: .9,  glw: .7, acc: "",           eye: "normali",   beh: "task" },
  diario:  { name: "Diario",  a: "#7f004b", b: "#d1338a", mat: "vetro", tip: .7,  wav: 1,   glw: .8, acc: "",           eye: "sognanti",  beh: "diary" },
  report:  { name: "Report",  a: "#d6005a", b: "#ff5c94", mat: "vetro", tip: .3,  wav: .8,  glw: .8, acc: "caschetto",  eye: "fessura",   beh: "report" },
  azioni:  { name: "Azioni",  a: "#ff0066", b: "#ff9a1f", mat: "vetro", tip: .8,  wav: 1.1, glw: .8, acc: "mascherina", eye: "decisi",    beh: "action" },
  // the three not in the prototype: a calm mint that reads a chart, a bouncing violet coach,
  // a soft lilac that smiles and thinks looking up (the prototype's "assistente" behaviour)
  referto: { name: "Referto", a: "#00684f", b: "#4fd1a5", mat: "vetro", tip: .62, wav: .85, glw: .8, acc: "",           eye: "normali",   beh: "report" },
  lezioni: { name: "Lezioni", a: "#4b1fd1", b: "#9b7bff", mat: "vetro", tip: .75, wav: 1.05, glw: .8, acc: "",          eye: "decisi",    beh: "action" },
  help:    { name: "Help",    a: "#5b4a8a", b: "#c9b8f0", mat: "vetro", tip: .6,  wav: .9,  glw: .9, acc: "",           eye: "mezzaluna", beh: "assist" },
};

// the chat's agents (ACTIONS[].key in ChatPage) -> their drop
export const DROP_FOR_AGENT = {
  query: "cerca", upload: "salva", todo: "task", journal: "diario", jobdiary: "diario",
  workreport: "report", report: "referto", lesson: "lezioni", scheduled: "azioni", help: "help",
};

export const MATS = {
  vetro: { spec: 1.3, shine: 90, rim: 1.0, glow: 1.0, irid: .15, milk: 0, metal: 0 },
};

export const STATES = {
  idle:   { amp: .035, speed: .35, freq: 1.4, swirl: .3,  glow: 1.0,  scale: 1.0 },
  listen: { amp: .06,  speed: .9,  freq: 1.8, swirl: .5,  glow: 1.35, scale: 1.045 },
  think:  { amp: .03,  speed: 1.4, freq: 1.8, swirl: 2.6, glow: 1.1,  scale: .97 },
  speak:  { amp: .03,  speed: 1.2, freq: 1.6, swirl: .7,  glow: 1.0,  scale: 1.0 },
};

export const EYES = {
  normali:   { rx: .075, ry: .13,  cut: 0,   lid: 1 },
  tondi:     { rx: .1,   ry: .105, cut: 0,   lid: 1 },
  fessura:   { rx: .092, ry: .05,  cut: 0,   lid: 1 },
  mezzaluna: { rx: .09,  ry: .075, cut: .05, lid: 1 },
  sognanti:  { rx: .082, ry: .12,  cut: 0,   lid: .58 },
  decisi:    { rx: .085, ry: .1,   cut: 0,   lid: .8 },
};
