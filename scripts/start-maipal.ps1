# Avvia mAIPAL: Docker Desktop, i container dell'app, e il tunnel Cloudflare
# verso https://maipal.it/general
#
# Uso: apri PowerShell nella cartella del progetto e lancia:
#   .\scripts\start-maipal.ps1

$ErrorActionPreference = "Stop"

Write-Host "== Avvio Docker Desktop (se non gia' attivo) ==" -ForegroundColor Cyan
$dockerRunning = $false
try { docker info *> $null; $dockerRunning = $true } catch { $dockerRunning = $false }

if (-not $dockerRunning) {
    $dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Start-Process $dockerExe
    } else {
        Write-Host "Docker Desktop.exe non trovato nel percorso standard. Avvialo manualmente." -ForegroundColor Yellow
    }
    Write-Host "Attendo che Docker sia pronto (puo' richiedere fino a un minuto)..."
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 3
        try { docker info *> $null; $ready = $true; break } catch { $ready = $false }
    }
    if (-not $ready) {
        Write-Host "Docker non risulta pronto. Controlla Docker Desktop manualmente e rilancia questo script." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Docker pronto." -ForegroundColor Green

Write-Host "== Avvio i container dell'app ==" -ForegroundColor Cyan
docker compose up -d

Write-Host "== Avvio il tunnel Cloudflare (finestra separata) ==" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cloudflared tunnel run maipal-general"

Write-Host ""
Write-Host "Fatto. Entro qualche secondo l'app sara' raggiungibile su:" -ForegroundColor Green
Write-Host "  https://maipal.it/general/"
Write-Host ""
Write-Host "Lascia aperta la finestra del tunnel Cloudflare che si e' appena aperta." -ForegroundColor Yellow
