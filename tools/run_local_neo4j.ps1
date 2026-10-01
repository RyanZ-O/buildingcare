$ErrorActionPreference = 'Stop'
$taskNeoHome = Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime\neo4j-community-2026.09.0'
$env:NEO4J_HOME = $taskNeoHome
Set-Location -LiteralPath $taskNeoHome
& (Join-Path $taskNeoHome 'bin\neo4j.bat') console
exit $LASTEXITCODE
