// AI calls and spend of the last days, from the llm_calls collection (metadata only: no texts).
// Run it inside the MongoDB container (works the same from cmd, PowerShell or a Linux shell):
//   docker compose cp backend/scripts/usage_week.js mongodb:/tmp/usage_week.js
//   docker compose exec mongodb mongosh maipal --quiet /tmp/usage_week.js
// ("maipal" is DB_NAME in .env.) The cost is the estimate stored at call time from llm_pricing;
// the amount actually billed is on platform.openai.com > Usage.

const DAYS = 7;
const m = { created_at: { $gte: new Date(Date.now() - DAYS * 864e5).toISOString() } };
const usd = { $sum: { $ifNull: ["$cost_usd", 0] } };

const t = db.llm_calls.aggregate([
  { $match: m },
  { $group: {
    _id: null, chiamate: { $sum: 1 }, usd, token: { $sum: "$total_tokens" },
    errori: { $sum: { $cond: [{ $eq: ["$status", "errore"] }, 1, 0] } },
    senza_prezzo: { $sum: { $cond: [{ $eq: [{ $ifNull: ["$cost_usd", "NA"] }, "NA"] }, 1, 0] } },
  } },
]).toArray()[0] || {};

print(`ULTIMI ${DAYS} GIORNI: ${t.chiamate || 0} chiamate, ${(t.usd || 0).toFixed(2)} $, ${t.token || 0} token, `
  + `${t.errori || 0} errori, ${t.senza_prezzo || 0} senza prezzo`);

const per = (titolo, chiave) => {
  print(`\n--- per ${titolo}`);
  db.llm_calls.aggregate([
    { $match: m },
    { $group: { _id: chiave, chiamate: { $sum: 1 }, usd } },
    { $sort: { usd: -1, chiamate: -1 } },
  ]).forEach((r) => print(`${JSON.stringify(r._id)} · ${r.chiamate} chiamate · ${r.usd.toFixed(3)} $`));
};
per("giorno", { $substr: ["$created_at", 0, 10] });
per("funzione", "$feature");
per("modello", "$model");
per("canale", { canale: "$channel", da: "$trigger" });
