$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports, downloads | Out-Null
$source = $env:LAB_OPENMS_PACKAGE
# 'none' is the documented skip value on every lab; blank is accepted because clearing the
# browser form can send an empty string.
if ([string]::IsNullOrWhiteSpace($source) -or $source.Trim() -eq 'none') {
    'OpenMS installation skipped.' | Set-Content reports/openms-status.txt
    @{ status = 'skipped' } | ConvertTo-Json | Set-Content reports/openms-package.json
    return
}
$source = $source.Trim()
$expected = $null
$releaseTag = $null
if ($source -match '^https://') {
    $url = $source
} else {
    $endpoint = if ($source -eq 'latest') { 'latest' } else { 'tags/' + [uri]::EscapeDataString($source) }
    $release = Invoke-RestMethod "https://api.github.com/repos/OpenMS/OpenMS/releases/$endpoint" -Headers @{ 'User-Agent' = 'openms-test-lab' }
    $releaseTag = $release.tag_name
    $assets = @($release.assets | Where-Object { $_.name -match 'Win64\.exe$' })
    if ($assets.Count -ne 1) { throw 'Expected exactly one Win64 installer in the selected release.' }
    $url = $assets[0].browser_download_url
    $expected = $assets[0].digest
}
$uri = [uri]$url
if ($uri.Scheme -ne 'https' -or $uri.UserInfo) { throw 'Use a public HTTPS URL without embedded credentials.' }
$name = [uri]::UnescapeDataString([IO.Path]::GetFileName($uri.AbsolutePath))
$extension = [IO.Path]::GetExtension($name).ToLowerInvariant()
if ($extension -notin '.exe', '.msi', '.zip') { throw 'Supported OpenMS package types: EXE (NSIS), MSI, ZIP.' }
$package = Join-Path (Resolve-Path downloads) ('openms-package' + $extension)
Invoke-WebRequest $url -OutFile $package
$hash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
$verified = $false
if ($expected) {
    $want = ($expected -replace '^sha256:', '').ToLowerInvariant()
    if ($hash -ne $want) { throw "Checksum mismatch for ${name}: expected $want, downloaded $hash." }
    $verified = $true
}
$record = [ordered]@{ status = 'downloaded'; url = $url; release = $releaseTag; sha256 = $hash
                      expected_digest = $expected; digest_verified = $verified; file = $name }
$record | ConvertTo-Json | Set-Content reports/openms-package.json
$installRoot = 'C:\OpenMS'
switch ($extension) {
    '.exe' {
        $process = Start-Process -FilePath $package -ArgumentList "/currentuser /S /D=$installRoot" -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -notin 0, 3010) { throw "OpenMS installer exited with $($process.ExitCode)" }
    }
    '.msi' {
        $process = Start-Process msiexec.exe -ArgumentList "/i `"$package`" /qn /norestart INSTALLDIR=$installRoot /L*v `"$((Resolve-Path reports).Path)\msi.log`"" -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -notin 0, 3010) { throw "MSI installer exited with $($process.ExitCode)" }
    }
    '.zip' { Expand-Archive -LiteralPath $package -DestinationPath $installRoot -Force }
}
$fileInfo = Get-ChildItem -LiteralPath $installRoot -Filter FileInfo.exe -File -Recurse | Select-Object -First 1
if (!$fileInfo) { throw "FileInfo.exe was not found under $installRoot" }
$fileInfo.DirectoryName | Set-Content reports/openms-bin.txt
$record['status'] = 'installed'
$record['executable'] = $fileInfo.FullName
$record | ConvertTo-Json | Set-Content reports/openms-package.json
$PSNativeCommandUseErrorActionPreference = $false
& $fileInfo.FullName --help 2>&1 | Tee-Object reports/openms-help.txt
if ($LASTEXITCODE -ne 0) { throw 'OpenMS FileInfo could not start. Inspect DLL diagnostics.' }
if (Test-Path reports/smoke.mzML) {
    & $fileInfo.FullName -in reports/smoke.mzML 2>&1 | Tee-Object reports/openms-fileinfo.txt
    if ($LASTEXITCODE -ne 0) { throw 'OpenMS FileInfo could not read the generated mzML file.' }
}
'OpenMS CLI smoke test passed.' | Set-Content reports/openms-status.txt
