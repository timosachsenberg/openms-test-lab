$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports | Out-Null
$provenancePath = 'downloads/dev-package/build-provenance.json'
$provenance = Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json
if ($provenance.source_repository -ne 'OpenMS/OpenMS' -or $provenance.source_commit -ne $env:LAB_OPENMS_COMMIT) {
    throw 'Development installer source identity does not match the requested commit.'
}
$installers = @(Get-ChildItem downloads/dev-package -Filter '*.exe' -File)
if ($installers.Count -ne 1 -or $installers[0].Name -ne $provenance.installer) { throw 'Unexpected installer artifact contents.' }
$installer = $installers[0]
$hash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne $provenance.installer_sha256) { throw 'Development installer checksum mismatch.' }
Copy-Item -LiteralPath $provenancePath -Destination reports/build-provenance.json
@{ url = $provenance.build_run; source_commit = $provenance.source_commit; sha256 = $hash; file = $installer.Name } |
    ConvertTo-Json | Set-Content reports/openms-package.json -Encoding utf8
if (Test-Path -LiteralPath 'C:/OpenMS') { throw 'Audit runner already has an OpenMS installation at the test location.' }
$process = Start-Process -FilePath $installer.FullName -ArgumentList '/currentuser /S /D=C:\OpenMS' -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -notin 0, 3010) { throw "Development installer exited with $($process.ExitCode)." }
$fileinfos = @(Get-ChildItem -LiteralPath 'C:/OpenMS' -Filter FileInfo.exe -Recurse -File)
if ($fileinfos.Count -ne 1) { throw 'Expected one FileInfo.exe in the development package.' }
$fileinfos[0].DirectoryName | Set-Content reports/openms-bin.txt
'Development package installed; native startup is checked by the subsequent DLL tracer.' | Set-Content reports/openms-status.txt

