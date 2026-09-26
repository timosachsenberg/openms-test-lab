<#
.SYNOPSIS
  Runs MaRaCluster's batch step many times on the MaRaClusterAdapter test inputs and counts crashes.

.DESCRIPTION
  OpenMS/OpenMS#10259 moves the bundled MaRaCluster from 0.05.0 to 1.04.1. On windows-2025,
  TOPP_MaRaClusterAdapter_1 once crashed inside 1.04.1's batch step, right after it started
  converting the two input files in parallel (OpenMP); the same command passed in other runs.
  Upstream's only Windows build of 1.04.1 is a mixed-mode .NET assembly, unlike 0.05.0.

  Each mode runs the adapter's batch command (-p 20.0ppm -t -10.0 -c -10.0) Iterations times, either
  alone or as two concurrent processes (ctest starts TOPP_MaRaClusterAdapter_1 and _2 together), and
  with or without OMP_NUM_THREADS=1. The index-first modes run 'index' with OMP_NUM_THREADS=1 before
  'batch', which then reuses the converted files: the conversion runs single-threaded, the
  clustering does not. 0.05.0 runs the concurrent mode as a control. Windows Error Reporting keeps a
  minidump of every crash, and cdb, if the runner has it, prints the first one.
#>
param(
  [int]$Iterations = 60
)

$ErrorActionPreference = 'Stop'
$root = Join-Path $env:RUNNER_TEMP 'maracluster-probe'
$reports = Join-Path $PWD 'reports'
$dumps = Join-Path $reports 'dumps'
New-Item -ItemType Directory -Force $root, $reports, $dumps | Out-Null

$thirdparty = 'https://raw.githubusercontent.com/OpenMS/THIRDPARTY'
$binaries = [ordered]@{
  '1.04.1' = "$thirdparty/00c619ea336cd74e24f714a43275767e6992608a/Windows/x86_64/MaRaCluster/maracluster.exe"
  '0.05.0' = "$thirdparty/306efdbd08266e70769a9221eccb94538cbd9954/Windows/x86_64/MaRaCluster/maracluster.exe"
}
$exe = @{}
foreach ($version in $binaries.Keys) {
  $dir = Join-Path $root $version
  New-Item -ItemType Directory -Force $dir | Out-Null
  $exe[$version] = Join-Path $dir 'maracluster.exe'
  Invoke-WebRequest $binaries[$version] -OutFile $exe[$version]
  $hash = (Get-FileHash $exe[$version] -Algorithm SHA256).Hash
  Write-Host "MaRaCluster $version`: $hash"
}

$data = 'https://raw.githubusercontent.com/OpenMS/OpenMS/95fd8cb7e49b491c11471be3a3b55de6c03732e9/src/tests/topp/THIRDPARTY'
$inputs = foreach ($i in 1, 2) {
  $file = Join-Path $root "MaRaClusterAdapter_1_in_$i.mzML"
  Invoke-WebRequest "$data/MaRaClusterAdapter_1_in_$i.mzML" -OutFile $file
  $file -replace '\\', '/'
}

# Keep a minidump of every maracluster.exe crash.
$wer = 'HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting'
New-Item -Force "$wer\LocalDumps\maracluster.exe" | Out-Null
New-ItemProperty "$wer\LocalDumps\maracluster.exe" -Name DumpFolder -Value $dumps -PropertyType ExpandString -Force | Out-Null
New-ItemProperty "$wer\LocalDumps\maracluster.exe" -Name DumpType -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty "$wer\LocalDumps\maracluster.exe" -Name DumpCount -Value 50 -PropertyType DWord -Force | Out-Null
New-ItemProperty $wer -Name DontShowUI -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty $wer -Name Disabled -Value 0 -PropertyType DWord -Force | Out-Null

function Start-MaRaCluster([string]$version, [string]$tag, [string]$step, [string[]]$extra, [bool]$singleThread) {
  $dir = Join-Path $root "runs/$tag"
  New-Item -ItemType Directory -Force $dir | Out-Null
  $list = Join-Path $dir 'file_list.txt'
  Set-Content -Path $list -Value $inputs -Encoding ascii
  $psi = [System.Diagnostics.ProcessStartInfo]::new($exe[$version])
  foreach ($arg in @($step, '-b', ($list -replace '\\', '/'), '-f', (($dir -replace '\\', '/') + '/'),
                     '-a', $tag, '-p', '20.0ppm') + $extra) {
    $psi.ArgumentList.Add($arg)
  }
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.WorkingDirectory = $dir
  if ($singleThread) { $psi.Environment['OMP_NUM_THREADS'] = '1' }
  $process = [System.Diagnostics.Process]::Start($psi)
  [pscustomobject]@{
    Tag = "$tag ($step)"
    Process = $process
    Out = $process.StandardOutput.ReadToEndAsync()
    Err = $process.StandardError.ReadToEndAsync()
  }
}

# The batch step; with -IndexFirst, as the adapter does it: 'index' single-threaded, then 'batch',
# which reuses the index. A failed index run is returned instead of the batch.
function Start-Batch([string]$version, [string]$tag, [bool]$singleThread, [bool]$indexFirst) {
  if ($indexFirst) {
    $index = Wait-Batch (Start-MaRaCluster $version $tag 'index' @() $true)
    if ($index.ExitCode -ne 0) { return [pscustomobject]@{ Done = $index } }
  }
  Start-MaRaCluster $version $tag 'batch' @('-t', '-10.0', '-c', '-10.0') $singleThread
}

function Wait-Batch($run) {
  if ($run.PSObject.Properties['Done']) { return $run.Done }
  # A hang counts as a failure too; int.MaxValue marks it.
  if (-not $run.Process.WaitForExit(300000)) {
    $run.Process.Kill($true)
    return [pscustomobject]@{ Tag = $run.Tag; ExitCode = [int]::MaxValue; Err = 'timed out after 300 s' }
  }
  $run.Process.WaitForExit()
  [pscustomobject]@{
    Tag = $run.Tag
    ExitCode = $run.Process.ExitCode
    Err = $run.Err.Result
  }
}

$modes = @(
  @{ Name = '1.04.1, one process'; Version = '1.04.1'; Concurrent = 1; SingleThread = $false; IndexFirst = $false },
  @{ Name = '1.04.1, index with OMP_NUM_THREADS=1, then batch; one process'; Version = '1.04.1'; Concurrent = 1; SingleThread = $false; IndexFirst = $true },
  @{ Name = '1.04.1, index with OMP_NUM_THREADS=1, then batch; two concurrent processes'; Version = '1.04.1'; Concurrent = 2; SingleThread = $false; IndexFirst = $true },
  @{ Name = '1.04.1, two concurrent processes'; Version = '1.04.1'; Concurrent = 2; SingleThread = $false; IndexFirst = $false },
  @{ Name = '1.04.1, two concurrent processes, OMP_NUM_THREADS=1'; Version = '1.04.1'; Concurrent = 2; SingleThread = $true; IndexFirst = $false },
  @{ Name = '0.05.0, two concurrent processes'; Version = '0.05.0'; Concurrent = 2; SingleThread = $false; IndexFirst = $false }
)

$summary = [System.Collections.Generic.List[string]]::new()
$summary.Add("| Mode | Runs | Crashes | Exit codes |")
$summary.Add("| --- | --- | --- | --- |")
$modeIndex = 0
foreach ($mode in $modes) {
  $modeIndex++
  $results = [System.Collections.Generic.List[object]]::new()
  $watch = [System.Diagnostics.Stopwatch]::StartNew()
  for ($i = 1; $i -le $Iterations; $i++) {
    $runs = foreach ($c in 1..$mode.Concurrent) { Start-Batch $mode.Version "m$modeIndex-i$i-p$c" $mode.SingleThread $mode.IndexFirst }
    foreach ($run in $runs) { $results.Add((Wait-Batch $run)) }
  }
  $crashes = @($results | Where-Object { $_.ExitCode -ne 0 })
  $codes = ($crashes | Group-Object ExitCode | ForEach-Object { '0x{0:X8} x{1}' -f [int]$_.Name, $_.Count }) -join ', '
  $line = "| $($mode.Name) | $($results.Count) | $($crashes.Count) | $codes |"
  $summary.Add($line)
  Write-Host "$line ($([int]$watch.Elapsed.TotalSeconds) s)"
  foreach ($crash in ($crashes | Select-Object -First 3)) {
    Write-Host "--- $($crash.Tag): exit code $('0x{0:X8}' -f $crash.ExitCode); last lines of stderr:"
    ($crash.Err -split "`n" | Select-Object -Last 8) | ForEach-Object { Write-Host "    $_" }
  }
}

$summary | Set-Content (Join-Path $reports 'summary.md')
if ($env:GITHUB_STEP_SUMMARY) { $summary | Add-Content $env:GITHUB_STEP_SUMMARY }

# Print the first crash dump's exception and stack if the runner has cdb.
$dumpFiles = @(Get-ChildItem $dumps -Filter *.dmp -ErrorAction SilentlyContinue)
Write-Host "Crash dumps: $($dumpFiles.Count)"
$cdb = @(
  "${env:ProgramFiles(x86)}\Windows Kits\10\Debuggers\x64\cdb.exe",
  "$env:ProgramFiles\Windows Kits\10\Debuggers\x64\cdb.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($dumpFiles.Count -gt 0 -and $cdb) {
  & $cdb -z $dumpFiles[0].FullName -c '.exr -1; .ecxr; kn 40; ~*kn 12; lmvm maracluster; q' 2>&1 |
    Tee-Object (Join-Path $reports 'first-dump-cdb.txt') | Write-Host
} elseif ($dumpFiles.Count -gt 0) {
  Write-Host 'cdb not found; the dumps are in the artifact.'
}
