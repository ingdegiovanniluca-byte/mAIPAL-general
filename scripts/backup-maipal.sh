#!/usr/bin/env bash
# Backup dei dati di mAIPAL: database (con i file in GridFS), configurazione, accessi, indice di ricerca.
# Crea backup/maipal-AAAAMMGG-HHMM/ nella cartella del progetto.
#
# Uso (nella cartella del progetto, con i container avviati):   ./scripts/backup-maipal.sh
#
# ATTENZIONE: env.txt contiene le chiavi: tieni il backup in un posto sicuro.
# Ripristino: vedi docs/PROGETTO.md, capitolo 12.
set -euo pipefail
dest="backup/maipal-$(date +%Y%m%d-%H%M)"
mkdir -p "$dest"

echo "== Database (mongodump, file compresi) =="
docker compose exec -T mongodb mongodump --archive --gzip > "$dest/mongo.archive.gz"
if [ "$(wc -c < "$dest/mongo.archive.gz")" -lt 100 ]; then
  echo "mongodump non riuscito: i container sono avviati? (docker compose up -d)" >&2; exit 1
fi

echo "== Configurazione e accessi =="
[ -f .env ] && cp .env "$dest/env.txt" || echo ".env non trovato"
[ -d backend/data/access ] && cp -r backend/data/access "$dest/access"

echo "== Indice di ricerca (facoltativo: si ricostruisce da solo) =="
mkdir -p "$dest/qdrant"
docker compose cp qdrant:/qdrant/storage "$dest/qdrant" >/dev/null 2>&1 \
  || echo "Indice non copiato (non è un problema: il worker lo ricostruisce dal database)."

echo
echo "Fatto: $dest ($(du -sh "$dest" | cut -f1))"
echo "Copialo anche fuori da questa macchina. Contiene le chiavi in env.txt."
