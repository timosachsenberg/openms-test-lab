Set-Location $env:GITHUB_WORKSPACE
if (Test-Path .venv/Scripts/Activate.ps1) { . .venv/Scripts/Activate.ps1 }
if (Test-Path reports/openms-bin.txt) { $env:PATH = (Get-Content reports/openms-bin.txt -Raw).Trim() + ';' + $env:PATH }
function global:Finish-Lab { New-Item -ItemType File -Force (Join-Path $env:GITHUB_WORKSPACE 'continue') | Out-Null }
function global:Export-LabWheels {
    python -m pip freeze | Set-Content exports/requirements-lock.txt
    python -m pip download -r exports/requirements-lock.txt --dest exports/wheelhouse
}
Write-Host "`nWindows OpenMS package lab" -ForegroundColor Cyan
Write-Host 'Python environment: .venv    OpenMS: C:\OpenMS'
Write-Host 'Reports: reports/    Downloads: downloads/    Save files to: exports/'
Write-Host 'Export-LabWheels downloads installed Python packages for export.'
Write-Host 'Finish-Lab ends the session and uploads exports/.'
Write-Host 'Closing SSH alone leaves the session available until its time limit.'
