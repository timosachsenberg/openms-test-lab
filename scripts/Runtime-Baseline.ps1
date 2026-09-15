param([ValidateSet('before','after')][string]$Phase)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports | Out-Null
$runtimes = @(Get-ChildItem "$env:SystemRoot\System32" -Filter *.dll -File | Where-Object {
    $_.Name -match '^(msvcp|msvcr|vcruntime|concrt|vcomp|vccorlib|mfc|mfcm|vcamp)[0-9]' -or $_.Name -eq 'ucrtbase.dll'
} | ForEach-Object {
    @{ path = $_.FullName; name = $_.Name; version = $_.VersionInfo.FileVersion
       product = $_.VersionInfo.ProductName; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
})
$installed = @(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'Visual C\+\+|\.NET.*Runtime' } |
    Select-Object DisplayName, DisplayVersion, Publisher)
$dotnet = if (Get-Command dotnet -ErrorAction SilentlyContinue) { @(dotnet --list-runtimes) } else { @() }
@{ phase = $Phase; image = $env:ImageOS; image_version = $env:ImageVersion
   os = [Environment]::OSVersion.VersionString; runtimes = $runtimes
   installed_runtime_packages = $installed; dotnet_runtimes = $dotnet } |
    ConvertTo-Json -Depth 8 | Set-Content "reports/runner-$Phase.json" -Encoding utf8
Write-Host "Recorded $($runtimes.Count) system runtime DLLs before/after package installation ($Phase)."
