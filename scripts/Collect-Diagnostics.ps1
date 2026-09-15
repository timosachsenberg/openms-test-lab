$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports | Out-Null
@{ os = [Environment]::OSVersion.VersionString; architecture = $env:PROCESSOR_ARCHITECTURE; runner = $env:ImageOS; image_version = $env:ImageVersion; path = $env:PATH } |
    ConvertTo-Json | Set-Content reports/windows.json
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (Test-Path $python) {
    & $python -m pip freeze --all | Set-Content reports/requirements-lock.txt
    & $python -m pip inspect | Set-Content reports/pip-inspect.json
    & $python -m pip debug --verbose 2>&1 | Set-Content reports/pip-debug.txt
}
$roots = @('.venv\Lib\site-packages\pyopenms', '.venv\Lib\site-packages\pyopenms.libs', 'C:\OpenMS') | Where-Object { Test-Path $_ }
$binaries = @($roots | ForEach-Object { Get-ChildItem -LiteralPath $_ -Recurse -File } | Where-Object { $_.Extension -in '.dll', '.pyd', '.exe' })
$binaries | Select-Object FullName, Length, @{n='FileVersion';e={$_.VersionInfo.FileVersion}} |
    Export-Csv reports/binaries.csv -NoTypeInformation
$vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
if (Test-Path $vswhere) {
    $vs = & $vswhere -latest -products '*' -property installationPath
    if ($vs) {
        $dumpbin = Get-ChildItem "$vs\VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe" | Sort-Object FullName -Descending | Select-Object -First 1
        if ($dumpbin) {
            foreach ($binary in ($binaries | Where-Object { $_.Extension -eq '.pyd' -or $_.Name -in 'FileInfo.exe', 'OpenMS.dll' })) {
                "### $($binary.FullName)" | Add-Content reports/dll-dependencies.txt
                & $dumpbin.FullName /DEPENDENTS $binary.FullName 2>&1 | Add-Content reports/dll-dependencies.txt
            }
        }
    }
}
if ($env:GITHUB_STEP_SUMMARY) {
    @'
## Windows lab is prepared

Download the **windows-lab-reports** artifact for package versions, pip checks, native binary dependencies, and smoke tests.

If debugging is enabled, the next step prints the SSH command. Use the dedicated private key supplied with this lab.
Inside the session, save files to `exports/` and run `Finish-Lab` to upload them.
'@ | Add-Content $env:GITHUB_STEP_SUMMARY
}
