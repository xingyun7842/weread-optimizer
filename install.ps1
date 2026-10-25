$ErrorActionPreference = "Stop"

$repo = "https://github.com/xingyun7842/weread-optimizer.git"
$skillDir = Join-Path $env:USERPROFILE ".codex\skills\weread-optimizer"
$parent = Split-Path $skillDir

New-Item -ItemType Directory -Force -Path $parent | Out-Null

if (Test-Path (Join-Path $skillDir ".git")) {
    Write-Host "Updating existing skill at $skillDir"
    git -C $skillDir pull --ff-only
} elseif (Test-Path $skillDir) {
    throw "Path exists but is not a git repo: $skillDir"
} else {
    Write-Host "Installing skill to $skillDir"
    git clone $repo $skillDir
}

$requirements = Join-Path $skillDir "requirements.txt"
if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m pip install -r $requirements
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m pip install -r $requirements
} else {
    Write-Warning "Python was not found. Install Python, then run: python -m pip install -r `"$requirements`""
}

Write-Host "Installed weread-optimizer"
