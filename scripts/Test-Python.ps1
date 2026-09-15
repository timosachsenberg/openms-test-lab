$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports | Out-Null
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw 'Python environment was not created; inspect the setup log.' }
$PSNativeCommandUseErrorActionPreference = $false
& $python -m pip check 2>&1 | Tee-Object reports/pip-check.txt
$pipExit = $LASTEXITCODE
& $python scripts/smoke.py 2>&1 | Tee-Object reports/python-smoke.log
$smokeExit = $LASTEXITCODE
if ($pipExit -ne 0 -or $smokeExit -ne 0) { throw "Python checks failed (pip=$pipExit, smoke=$smokeExit). The SSH session will still open." }
