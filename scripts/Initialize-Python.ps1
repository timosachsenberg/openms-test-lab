$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports, downloads, exports | Out-Null
python -m venv .venv
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
$requirements = [System.Collections.Generic.List[string]]::new()
# Accept the same 'none' skip value as the macOS and Linux labs, and normalise it for the later
# steps so the smoke test sees a blank spec and reports 'skipped' instead of failing to import.
$pyopenmsSpec = if ($env:LAB_PYOPENMS_SPEC) { $env:LAB_PYOPENMS_SPEC.Trim() } else { '' }
if ($pyopenmsSpec -eq 'none') { $pyopenmsSpec = '' }
if ($pyopenmsSpec -eq 'nightly') {
    # Same selection rule as the macOS and Linux labs; the URL carries a sha256 fragment
    # that pip verifies.
    $nightly = & $python scripts/resolve_nightly.py wheel | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the current nightly pyOpenMS wheel.' }
    $nightly | ConvertTo-Json | Set-Content reports/python-selection.json
    $pyopenmsSpec = $nightly.url
}
if ($env:GITHUB_ENV) {
    if ($pyopenmsSpec -match '[\r\n]') { throw 'Package requirement must be a single line.' }
    "LAB_PYOPENMS_SPEC=$pyopenmsSpec" | Add-Content $env:GITHUB_ENV
}
if ($pyopenmsSpec) { $requirements.Add($pyopenmsSpec) }
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
