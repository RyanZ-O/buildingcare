$ErrorActionPreference = 'Stop'
$taskPidFile = Join-Path $PSScriptRoot 'data\server.pid'
if (-not (Test-Path -LiteralPath $taskPidFile)) {
    Write-Host 'No background service started by this project is recorded.'
    exit 0
}
$taskServiceId = [int](Get-Content -LiteralPath $taskPidFile -Raw).Trim()
$taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskServiceId"
$taskExpectedExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not $taskProcess) { Write-Host 'The recorded background service has already stopped.'; exit 0 }
if ($taskProcess.ExecutablePath -ne $taskExpectedExe -or $taskProcess.CommandLine -notlike '*uvicorn backend.main:app*') {
    throw 'The recorded process no longer matches this project. No process was stopped.'
}
$taskChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId = $taskServiceId"
foreach ($taskChild in $taskChildren) {
    if ($taskChild.CommandLine -like '*uvicorn backend.main:app*') {
        Stop-Process -Id $taskChild.ProcessId -ErrorAction SilentlyContinue
    }
}
Stop-Process -Id $taskServiceId -ErrorAction SilentlyContinue
Write-Host 'Project background service stopped.'
