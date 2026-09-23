# Tear Master Smith down when you are not using it. Containers are removed; the mastersmith-data volume (builds,
# uploads, the spend ledger) stays.   .\scripts\stop.ps1 -Wipe   also deletes that volume.
param([switch]$Wipe)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if ($Wipe) { docker compose down -v } else { docker compose down }
docker compose ps
