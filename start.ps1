param([int]$Port = 8000, [switch]$Build)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.runtime\neo4j-community-2026.09.0\project-configured')) {
    & (Join-Path $PSScriptRoot 'start-neo4j.ps1')
}
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Python environment is missing. Run setup.ps1 first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'data\building.json'))) {
    throw 'Prepared model is missing. Run setup.ps1 -PrepareModel first.'
}
if ($Build -or -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\dist\index.html'))) {
    Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
Write-Host "Maintenance desk: http://localhost:$Port/"
Write-Host "Resident reports: http://localhost:$Port/report"
$taskAddresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
    $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.AddressState -eq 'Preferred'
}
foreach ($taskAddress in $taskAddresses) {
    Write-Host "Phone on the same network: http://$($taskAddress.IPAddress):$Port/report"
}
Write-Host 'Keep this window open. Press Ctrl+C to stop.'
& $taskPython -m uvicorn backend.main:app --host 0.0.0.0 --port $Port
