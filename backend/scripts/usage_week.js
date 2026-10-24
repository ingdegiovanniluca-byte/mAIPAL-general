// AI calls and spend of the last days, from the llm_calls collection (metadata only: no texts).
// Run it inside the MongoDB container (works the same from cmd, PowerShell or a Linux shell):
//   docker compose cp backend/scripts/usage_week.js mongodb:/tmp/usage_week.js
//   docker compose exec mongodb mongosh maipal --quiet /tmp/usage_week.js
// ("maipal" is DB_NAME in .env.) Each call's cost is the one stored when it was made; calls
// stored without one (llm_pricing not seeded yet - scripts/seed_llm_pricing.py) are costed here
// from their tokens with the same list prices. The amount actually billed is on
// platform.openai.com > Usage.

const DAYS = 7;
// USD, the prices of scripts/seed_llm_pricing.py: per 1M tokens (input, cached input, output); whisper per minute
const P = {
  mini:    { in: 0.15, cached: 0.075, out: 0.60 },
  gpt4o:   { in: 2.50, cached: 1.25,  out: 10.00 },
  whisper: { min: 0.006 },
};

const m = { created_at: { $gte: new Date(Date.now() - DAYS * 864e5).toISOString() } };
const tok = (p) => ({ $divide: [{ $add: [
  { $multiply: [{ $max: [0, { $subtract: [{ $ifNull: ["$input_tokens", 0] }, { $ifNull: ["$cached_input_tokens", 0] }] }] }, p.in] },
  { $multiply: [{ $ifNull: ["$cached_input_tokens", 0] }, p.cached] },
  { $multiply: [{ $ifNull: ["$output_tokens", 0] }, p.out] },
] }, 1e6] });
const model = { $ifNull: ["$model", ""] };
// the stored cost when there is one, else from the tokens (longest model name first: mini before gpt-4o)
const withCost = { $addFields: { est: { $cond: [{ $gt: [{ $ifNull: ["$cost_usd", 0] }, 0] }, "$cost_usd", { $switch: { branches: [
  { case: { $regexMatch: { input: model, regex: /^gpt-4o-mini/ } }, then: tok(P.mini) },
  { case: { $regexMatch: { input: model, regex: /^gpt-4o/ } }, then: tok(P.gpt4o) },
  { case: { $regexMatch: { input: model, regex: /^whisper/ } }, then: { $multiply: [{ $divide: [{ $ifNull: ["$duration_seconds", 0] }, 60] }, P.whisper.min] } },
], default: 0 } }] } } };
const usd = { $sum: "$est" };

const t = db.llm_calls.aggregate([
  { $match: m }, withCost,
  { $group: {
    _id: null, chiamate: { $sum: 1 }, usd,
    tin: { $sum: { $ifNull: ["$input_tokens", 0] } }, tout: { $sum: { $ifNull: ["$output_tokens", 0] } },
    errori: { $sum: { $cond: [{ $eq: ["$status", "errore"] }, 1, 0] } },
    stimate: { $sum: { $cond: [{ $gt: [{ $ifNull: ["$cost_usd", 0] }, 0] }, 0, 1] } },
  } },
]).toArray()[0] || {};

print(`ULTIMI ${DAYS} GIORNI: ${t.chiamate || 0} chiamate · ${(t.usd || 0).toFixed(3)} $ · `
  + `token ${t.tin || 0} in / ${t.tout || 0} out · ${t.errori || 0} errori`);
print(`(${t.stimate || 0} chiamate senza costo registrato: calcolato qui dai token)`);
if (t.chiamate) print(`media ${((t.usd || 0) / t.chiamate * 100).toFixed(2)} centesimi di $ a chiamata · al mese circa ${((t.usd || 0) / DAYS * 30).toFixed(2)} $`);

const per = (titolo, chiave) => {
  print(`\n--- per ${titolo}`);
  db.llm_calls.aggregate([
    { $match: m }, withCost,
    { $group: { _id: chiave, chiamate: { $sum: 1 }, usd, tin: { $sum: { $ifNull: ["$input_tokens", 0] } } } },
    { $sort: { usd: -1, chiamate: -1 } },
  ]).forEach((r) => print(`${JSON.stringify(r._id)} · ${r.chiamate} chiamate · ${r.usd.toFixed(3)} $ · `
    + `${Math.round(r.tin / r.chiamate)} token in a chiamata`));
};
per("giorno", { $substr: ["$created_at", 0, 10] });
per("funzione", "$feature");
per("modello", "$model");
per("canale", { canale: "$channel", da: "$trigger" });
