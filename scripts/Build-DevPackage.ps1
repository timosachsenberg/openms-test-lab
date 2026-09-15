$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$labRoot = Split-Path $PSScriptRoot -Parent
$sourceRoot = Split-Path $labRoot -Parent
Set-Location $sourceRoot
if ($env:LAB_OPENMS_COMMIT -notmatch '^[0-9a-fA-F]{40}$') { throw 'Expected a full source commit.' }
if ((git rev-parse HEAD).Trim() -ne $env:LAB_OPENMS_COMMIT) { throw 'Source commit mismatch.' }
if ($env:LAB_CMAKE_PRESET -ne 'windows-x64-ci') { throw 'Expected the upstream Windows CI preset.' }
$buildRoot = Join-Path $sourceRoot 'build/windows-x64-ci'
$reports = Join-Path $labRoot 'reports'
$exports = Join-Path $labRoot 'exports/dev-package'
# NSIS uses legacy Win32 paths, so keep its staging path short. A fresh job
# gets a fresh directory; no existing filesystem tree is removed.
$stage = 'C:/lab-cpk'
if (Test-Path -LiteralPath $stage) { throw 'Packaging stage already exists.' }
New-Item -ItemType Directory -Force $reports, $exports, $stage | Out-Null
try {
    cmake -S $sourceRoot -B $buildRoot -DPACKAGE_TYPE=nsis "-DSEARCH_ENGINES_DIRECTORY=$sourceRoot/_thirdparty" "-DCPACK_PACKAGE_DIRECTORY=$stage" 2>&1 |
        Tee-Object (Join-Path $reports 'package-configure.log')
    cmake --build $buildRoot --target dist 2>&1 | Tee-Object (Join-Path $reports 'package-build.log')
} finally {
    $nsisLog = Join-Path $stage '_CPack_Packages/win64/NSIS/NSISOutput.log'
    if (Test-Path -LiteralPath $nsisLog) { Copy-Item -LiteralPath $nsisLog -Destination $reports }
    foreach ($name in 'CMakeCache.txt', 'CPackConfig.cmake') {
        $path = Join-Path $buildRoot $name
        if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination $reports }
    }
}
$installers = @(Get-ChildItem -LiteralPath $stage -Filter '*.exe' -File)
if ($installers.Count -ne 1) { throw 'Expected exactly one NSIS installer.' }
$installer = $installers[0]
Copy-Item -LiteralPath $installer.FullName -Destination $exports
$metadata = @{
    source_repository = 'OpenMS/OpenMS'
    source_commit = (git rev-parse HEAD).Trim()
    submodules = @(git submodule status)
    preset = $env:LAB_CMAKE_PRESET
    image = $env:ImageOS
    image_version = $env:ImageVersion
    vctools_version = $env:VCToolsVersion
    vctools_redist_dir = $env:VCToolsRedistDir
    cmake_version = @(cmake --version)
    installer = $installer.Name
    installer_sha256 = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    build_run = "https://github.com/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID"
}
$metadata | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $exports 'build-provenance.json') -Encoding utf8
Copy-Item -LiteralPath (Join-Path $exports 'build-provenance.json') -Destination $reports

