# Backup dei dati di mAIPAL: database (con i file in GridFS), configurazione, accessi, indice di ricerca.
# Crea backup\maipal-AAAAMMGG-HHMM\ nella cartella del progetto.
#
# Uso: apri PowerShell nella cartella del progetto (con i container avviati) e lancia:
#   .\scripts\backup-maipal.ps1
#
# ATTENZIONE: env.txt contiene le chiavi (OpenAI, Google, Telegram...): tieni il backup in un posto sicuro.
# Ripristino: vedi docs\PROGETTO.md, capitolo 12.

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$dest = Join-Path (Get-Location) "backup\maipal-$stamp"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

Write-Host "== Database (mongodump, file compresi) ==" -ForegroundColor Cyan
$archive = Join-Path $dest "mongo.archive.gz"
# (cmd /c: PowerShell 5 rovina i dati binari nelle redirezioni)
cmd /c "docker compose exec -T mongodb mongodump --archive --gzip > `"$archive`""
if ($LASTEXITCODE -ne 0 -or (Get-Item $archive).Length -lt 100) {
    Write-Host "mongodump non riuscito: i container sono avviati? (docker compose up -d)" -ForegroundColor Red
    exit 1
}

Write-Host "== Configurazione e accessi ==" -ForegroundColor Cyan
if (Test-Path ".env") { Copy-Item ".env" (Join-Path $dest "env.txt") } else { Write-Host ".env non trovato" -ForegroundColor Yellow }
if (Test-Path "backend\data\access") { Copy-Item "backend\data\access" (Join-Path $dest "access") -Recurse }

Write-Host "== Indice di ricerca (facoltativo: si ricostruisce da solo) ==" -ForegroundColor Cyan
try {
    $qdir = Join-Path $dest "qdrant"
    New-Item -ItemType Directory -Force -Path $qdir | Out-Null
    docker compose cp qdrant:/qdrant/storage "$qdir" | Out-Null
} catch {
    Write-Host "Indice non copiato (non è un problema: il worker lo ricostruisce dal database)." -ForegroundColor Yellow
}

$size = "{0:N1}" -f ((Get-ChildItem $dest -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host ""
Write-Host "Fatto: $dest ($size MB)" -ForegroundColor Green
Write-Host "Copialo anche fuori da questo PC (disco esterno o cloud). Contiene le chiavi in env.txt." -ForegroundColor Yellow
