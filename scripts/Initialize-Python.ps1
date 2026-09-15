$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports, downloads, exports | Out-Null
python -m venv .venv
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
$requirements = [System.Collections.Generic.List[string]]::new()
if ($env:LAB_PYOPENMS_SPEC) { $requirements.Add($env:LAB_PYOPENMS_SPEC.Trim()) }
foreach ($spec in ($env:LAB_EXTRA_PACKAGES -split ';')) {
    if ($spec.Trim()) { $requirements.Add($spec.Trim()) }
}
foreach ($spec in $requirements) {
    if ($spec.StartsWith('-')) { throw 'Use package requirements or wheel URLs, not pip command-line options.' }
}
$requirements | Set-Content reports/requested-packages.txt
if ($requirements.Count -gt 0) {
    & $python -m pip install --report reports/pip-install.json @requirements 2>&1 | Tee-Object reports/pip-install.log
}
& $python -m pip install --report reports/extra-install.json -r requirements.txt 2>&1 | Tee-Object reports/extra-install.log
& $python -m pip freeze --all | Set-Content reports/requirements-lock.txt
