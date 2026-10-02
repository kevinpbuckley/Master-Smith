param(
  # also link each shared skill into the user's Codex skills folder, so `$forge` is offered whichever folder Codex
  # was started in (2026-09-30: a session started in another repo had no forge skill and asked which project it was)
  [switch]$User
)
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
  if ($existing.LinkType -eq 'Junction' -or $existing.LinkType -eq 'SymbolicLink') {
    Write-Output "Shared skills already linked: $destination -> $($existing.Target)"
  } else {
    throw "Cannot link skills: $destination already exists. Its contents have been left intact."
  }
} else {
  New-Item -ItemType Directory -Path $agentsRoot -Force | Out-Null
  # A Windows junction works without administrator rights or Developer Mode.
  New-Item -ItemType Junction -Path $destination -Target $source | Out-Null
  Write-Output "Shared skills linked: $destination -> $source"
}

if ($User) {
  $codexSkills = Join-Path $env:USERPROFILE '.codex/skills'
  New-Item -ItemType Directory -Path $codexSkills -Force | Out-Null
  foreach ($skill in Get-ChildItem -LiteralPath $source -Directory) {
    $link = Join-Path $codexSkills $skill.Name
    $have = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
    if ($null -ne $have) {
      Write-Output "Codex user skill already there, left as it is: $link"
      continue
    }
    New-Item -ItemType Junction -Path $link -Target $skill.FullName | Out-Null
    Write-Output "Codex user skill linked: $link -> $($skill.FullName)"
  }
}
