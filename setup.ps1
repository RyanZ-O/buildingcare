param([switch]$PrepareModel, [switch]$Dev)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 environment creation failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination (Join-Path $PSScriptRoot '.env')
}
& $taskPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
if ($Dev) {
    & $taskPython -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Test dependency installation failed.' }
}
$taskModelFile = Join-Path $PSScriptRoot 'data\building.json'
if ($PrepareModel -or -not (Test-Path -LiteralPath $taskModelFile)) {
    & $taskPython -m pip install -r requirements-model.txt
    if ($LASTEXITCODE -ne 0) { throw 'Model dependency installation failed.' }
    & $taskPython tools/prepare_model.py
    if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed.' }
}
$taskBuilding = Get-Content -LiteralPath $taskModelFile -Raw | ConvertFrom-Json
foreach ($taskChunk in $taskBuilding.chunks) {
    $taskAsset = Join-Path (Join-Path $PSScriptRoot 'data') $taskChunk.url.TrimStart('/')
    if (-not (Test-Path -LiteralPath $taskAsset) -or (Get-Item -LiteralPath $taskAsset).Length -ne $taskChunk.bytes) {
        throw 'A prepared model asset is missing or is a Git LFS pointer. Run git lfs pull, then setup.ps1 again.'
    }
}
Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'Setup complete. Run .\start.ps1 to launch.'
