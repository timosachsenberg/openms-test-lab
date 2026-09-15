$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports, downloads/audit-wheel | Out-Null
if ($env:LAB_UPSTREAM_RUN -notmatch '^[1-9][0-9]*$') { throw 'Expected an upstream run ID.' }
$api = 'https://api.github.com/repos/OpenMS/OpenMS'
$headers = @{ Authorization = "Bearer $env:GH_TOKEN"; Accept = 'application/vnd.github+json' }
$run = Invoke-RestMethod "$api/actions/runs/$env:LAB_UPSTREAM_RUN" -Headers $headers
if ($run.path -ne '.github/workflows/pyopenms-wheels-cibuildwheel.yml') { throw 'Not the upstream wheel workflow.' }
$response = Invoke-RestMethod "$api/actions/runs/$($run.id)/artifacts?per_page=100" -Headers $headers
$artifacts = @($response.artifacts | Where-Object { $_.name -eq 'wheels-windows-x64' -and !$_.expired })
if ($artifacts.Count -ne 1) { throw 'Expected exactly one unexpired Windows artifact.' }
$artifact = $artifacts[0]
$archive = Join-Path (Get-Location) 'downloads/audit-wheel.zip'
Invoke-WebRequest "$api/actions/artifacts/$($artifact.id)/zip" -Headers $headers -OutFile $archive
$hash = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($artifact.digest -ne "sha256:$hash") { throw 'Artifact SHA-256 mismatch.' }
Expand-Archive -LiteralPath $archive -DestinationPath downloads/audit-wheel -Force
$wheels = @(Get-ChildItem downloads/audit-wheel -Recurse -Filter '*-win_amd64.whl' -File)
if ($wheels.Count -ne 1) { throw 'Expected one Windows wheel.' }
$wheel = $wheels[0]
@{ upstream_run = $run.html_url; head_sha = $run.head_sha; artifact_id = $artifact.id
   artifact_sha256 = $hash; wheel = $wheel.Name; wheel_sha256 = (Get-FileHash $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant() } |
    ConvertTo-Json | Set-Content reports/audit-source.json -Encoding utf8
$wheel.FullName | Set-Content reports/audit-wheel-path.txt
"LAB_PYOPENMS_SPEC=$($wheel.FullName)" | Add-Content $env:GITHUB_ENV
