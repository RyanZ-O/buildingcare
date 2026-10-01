$ErrorActionPreference = 'Stop'
$taskNeoHome = Join-Path $PSScriptRoot '.runtime\neo4j-community-2026.09.0'
if (-not (Test-Path -LiteralPath (Join-Path $taskNeoHome 'project-configured'))) {
    throw 'Run .venv\Scripts\python.exe tools\setup_local_neo4j.py to prepare the local database.'
}
$taskListener = Get-NetTCPConnection -LocalPort 17687 -State Listen -ErrorAction SilentlyContinue
if ($taskListener) {
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($taskListener[0].OwningProcess)"
    if ($taskProcess.CommandLine -notlike "*$taskNeoHome*") { throw 'Port 17687 belongs to a different process.' }
    Write-Host 'Project Neo4j is already running.'
    return
}
$taskShell = (Get-Process -Id $PID).Path
$taskScript = Join-Path $PSScriptRoot 'tools\run_local_neo4j.ps1'
$taskService = Start-Process -FilePath $taskShell -ArgumentList '-NoProfile','-File',('"' + $taskScript + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data\neo4j.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data\neo4j.stderr.log') -PassThru
$taskService.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'data\neo4j.pid')
Write-Host 'Project Neo4j is starting in the background on ports 17687 and 17474.'
