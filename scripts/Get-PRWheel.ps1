$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force reports, downloads/pr-wheel, exports | Out-Null
if ($env:LAB_PR_NUMBER -notmatch '^[1-9][0-9]*$') { throw 'PR number must be a positive integer.' }
if ($env:LAB_UPSTREAM_RUN -and $env:LAB_UPSTREAM_RUN -notmatch '^[1-9][0-9]*$') { throw 'Run ID must be a positive integer or blank.' }
$api = 'https://api.github.com/repos/OpenMS/OpenMS'
$headers = @{ Authorization = "Bearer $env:GH_TOKEN"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
$pr = Invoke-RestMethod "$api/pulls/$env:LAB_PR_NUMBER" -Headers $headers
$sha = $pr.head.sha
if ($env:LAB_UPSTREAM_RUN) {
    $run = Invoke-RestMethod "$api/actions/runs/$env:LAB_UPSTREAM_RUN" -Headers $headers
} else {
    $runs = Invoke-RestMethod "$api/actions/workflows/pyopenms-wheels-cibuildwheel.yml/runs?head_sha=$sha&status=success&per_page=100" -Headers $headers
    $run = $runs.workflow_runs | Sort-Object created_at -Descending | Select-Object -First 1
}
if (!$run) { throw "No successful wheel run exists for PR #$env:LAB_PR_NUMBER at $sha. Build the PR wheel upstream first." }
if ($run.head_sha -ne $sha) { throw "Run $($run.id) belongs to $($run.head_sha), not the current PR head $sha." }
if ($run.path -ne '.github/workflows/pyopenms-wheels-cibuildwheel.yml') { throw 'Selected run is not the upstream wheel workflow.' }
if ($run.conclusion -ne 'success') { throw 'Selected upstream wheel run has not succeeded.' }
$artifacts = Invoke-RestMethod "$api/actions/runs/$($run.id)/artifacts?per_page=100" -Headers $headers
$candidates = @($artifacts.artifacts | Where-Object { $_.name -eq 'wheels-windows-x64' -and !$_.expired })
if ($candidates.Count -ne 1) { throw "Expected one unexpired Windows wheel artifact; found $($candidates.Count)." }
$artifact = $candidates[0]
$archive = Join-Path (Get-Location) 'downloads/pr-wheel.zip'
Invoke-WebRequest "$api/actions/artifacts/$($artifact.id)/zip" -Headers $headers -OutFile $archive
$digest = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if (!$artifact.digest -or $artifact.digest -ne "sha256:$digest") { throw 'GitHub artifact SHA-256 verification failed.' }
Expand-Archive -LiteralPath $archive -DestinationPath downloads/pr-wheel -Force
$wheels = @(Get-ChildItem downloads/pr-wheel -Recurse -Filter '*-win_amd64.whl' -File)
if ($wheels.Count -ne 1) { throw "Expected one Windows x64 wheel; found $($wheels.Count)." }
$wheel = $wheels[0]
$provenance = [ordered]@{
    pr = $pr.html_url; head_sha = $sha; upstream_run = $run.html_url
    artifact_id = $artifact.id; artifact_sha256 = $digest
    wheel = $wheel.Name; wheel_sha256 = (Get-FileHash $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$provenance | ConvertTo-Json | Set-Content reports/pr-wheel-source.json -Encoding utf8
Copy-Item reports/pr-wheel-source.json exports/pr-wheel-source.json
Copy-Item -LiteralPath $wheel.FullName -Destination exports/
$wheel.FullName | Set-Content reports/pr-wheel-path.txt
"LAB_PYOPENMS_SPEC=$($wheel.FullName)" | Add-Content $env:GITHUB_ENV
@"
## PR wheel selected

- PR: $($pr.html_url)
- Commit: $sha
- Build: $($run.html_url)
- Wheel: $($wheel.Name)
- Artifact SHA-256 verified: $digest

The lab installs this exact wheel into a fresh virtual environment. Desktop OpenMS is not installed in this workflow.
"@ | Add-Content $env:GITHUB_STEP_SUMMARY
Write-Host "Verified PR #$env:LAB_PR_NUMBER at $sha; artifact $($artifact.id); wheel $($wheel.Name)"
