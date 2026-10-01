param([switch]$Build)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Build) {
    Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } } finally { Pop-Location }
}
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.runtime\neo4j-community-2026.09.0\project-configured')) { & .\start-neo4j.ps1 }
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    & .\stop-background.ps1
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8000 is still occupied by another service.' }
}
$taskService = Start-Process -FilePath (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -ArgumentList '-m','uvicorn','backend.main:app','--host','0.0.0.0','--port','8000' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data\server.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data\server.stderr.log') -PassThru
$taskService.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'data\server.pid')
Write-Host 'Platform restarted in the background: http://localhost:8000/'
