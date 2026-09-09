# Ferma mAIPAL: chiude il tunnel Cloudflare e spegne i container dell'app.
# Docker Desktop resta aperto (per chiuderlo del tutto, esci dall'icona nella tray).
#
# Uso: apri PowerShell nella cartella del progetto e lancia:
#   .\scripts\stop-maipal.ps1

Write-Host "== Chiudo il tunnel Cloudflare ==" -ForegroundColor Cyan
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "Tunnel chiuso (o non era attivo)." -ForegroundColor Green

Write-Host "== Spengo i container dell'app ==" -ForegroundColor Cyan
docker compose down

Write-Host ""
Write-Host "Fatto. L'app non e' piu' raggiungibile pubblicamente." -ForegroundColor Green
Write-Host "maipal.it (root) resta invariato, non e' stato toccato."
