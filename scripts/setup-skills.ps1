$ErrorActionPreference = 'Stop'

# Share the whole skill directory so new skills appear in both agents.
$repoRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repoRoot '.claude/skills'
$agentsRoot = Join-Path $repoRoot '.agents'
$destination = Join-Path $agentsRoot 'skills'

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
  throw "Shared skill directory is missing: $source"
}

$existing = Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
if ($null -ne $existing) {
  if ($existing.LinkType -eq 'Junction' -and $existing.Target -contains $source) {
    Write-Output "Shared skills already linked: $destination -> $source"
    exit 0
  }
  throw "Cannot link skills: $destination already exists. Its contents have been left intact."
}

New-Item -ItemType Directory -Path $agentsRoot -Force | Out-Null
# A Windows junction works without administrator rights or Developer Mode.
New-Item -ItemType Junction -Path $destination -Target $source | Out-Null
Write-Output "Shared skills linked: $destination -> $source"
