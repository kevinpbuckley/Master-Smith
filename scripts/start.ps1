# Start Master Smith on Windows: Docker Desktop if it is not running, then both containers, then the browser.
#   .\scripts\start.ps1            # start (or restart) what is built
#   .\scripts\start.ps1 -Build     # rebuild the images first (after pulling code changes)
#   .\scripts\start.ps1 -Down      # stop everything
param([switch]$Build, [switch]$Down)
# No $ErrorActionPreference = "Stop": docker writes progress and warnings to stderr, which PowerShell 5.1 would turn
# into terminating errors. Exit codes are checked instead.
Set-Location (Split-Path -Parent $PSScriptRoot)

function DockerUp { cmd /c "docker info >nul 2>&1"; return ($LASTEXITCODE -eq 0) }

if ($Down) { docker compose down; exit }

if (-not (Test-Path ".env")) { Write-Host "No .env yet: copy .env.example to .env and put your keys in it."; exit 1 }

# Docker Desktop: start it when the daemon does not answer, then wait for it.
if (-not (DockerUp)) {
  $exe = @("$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe", "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $exe) { Write-Host "Docker Desktop is not installed where expected; start it by hand and rerun."; exit 1 }
  Write-Host "Starting Docker Desktop..."
  Start-Process $exe
  $deadline = (Get-Date).AddMinutes(3)
  do { Start-Sleep 3 } while (-not (DockerUp) -and (Get-Date) -lt $deadline)
  if (-not (DockerUp)) { Write-Host "Docker did not come up in 3 minutes."; exit 1 }
}

if ($Build) { docker compose up -d --build } else { docker compose up -d }
if ($LASTEXITCODE -ne 0) { Write-Host "docker compose failed (exit $LASTEXITCODE)."; exit 1 }

# Wait for the API, then open the chat.
$deadline = (Get-Date).AddMinutes(2)
do {
  Start-Sleep 2
  try { $h = Invoke-RestMethod http://localhost:8080/healthz -TimeoutSec 3 } catch { $h = $null }
} while (-not $h -and (Get-Date) -lt $deadline)
if ($h) { Write-Host ("API up: blender={0} local_mode={1}" -f $h.blender, $h.local_mode) } else { Write-Host "API not answering yet; check: docker compose logs api" }
Start-Process "http://localhost:3000"
docker compose ps
