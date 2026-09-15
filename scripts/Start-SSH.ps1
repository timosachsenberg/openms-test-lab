$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$workspace = (Get-Location).Path
$minutes = [int]$env:LAB_SESSION_MINUTES
if ($minutes -notin 15, 30, 60, 120) { throw 'Invalid session duration.' }
$authorizedKeys = Join-Path $workspace 'ssh\authorized_keys'
if (!(Test-Path $authorizedKeys) -or !(Get-Content $authorizedKeys -Raw).Trim()) {
    throw 'No public SSH key configured; refusing to open a session.'
}
ssh-keygen -lf $authorizedKeys
if ($LASTEXITCODE -ne 0) { throw 'Invalid public SSH key file.' }

$toolDir = Join-Path $env:RUNNER_TEMP 'windows-lab-upterm'
New-Item -ItemType Directory -Force $toolDir | Out-Null
$archive = Join-Path $toolDir 'upterm.tar.gz'
Invoke-WebRequest 'https://github.com/owenthereal/upterm/releases/download/v0.28.0/upterm_windows_amd64.tar.gz' -OutFile $archive
$expectedHash = '7ada369cbbf5c0a4f212dcdb6cc514c783014e9c0c9e8285e7a4ef82686f1be9'
if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Upterm download checksum mismatch.' }
tar -xzf $archive -C $toolDir
if ($LASTEXITCODE -ne 0) { throw 'Could not extract Upterm.' }
$upterm = Join-Path $toolDir 'upterm.exe'
& $upterm version
if ($LASTEXITCODE -ne 0) { throw 'Upterm could not start.' }

# This is a fresh disposable known-hosts file. Upterm's flag accepts unknown host
# keys on first use and checks recorded keys on subsequent connections (TOFU).
$knownHosts = Join-Path $toolDir 'known_hosts'
$sessionShell = 'pwsh.exe -NoLogo -NoProfile -NoExit -File "' + (Join-Path $PSScriptRoot 'Enter-Lab.ps1').Replace('\', '/') + '"'
$startInfo = [Diagnostics.ProcessStartInfo]::new($upterm)
$startInfo.WorkingDirectory = $workspace
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
foreach ($arg in @('host', '--accept', '--hide-client-ip', '--skip-host-key-check', '--known-hosts', $knownHosts,
                   '--server', 'ssh://uptermd.upterm.dev:22', '--authorized-keys', $authorizedKeys,
                   '--force-command', $sessionShell, '--', 'pwsh.exe', '-NoLogo', '-NoProfile', '-File',
                   (Join-Path $PSScriptRoot 'Host-Wait.ps1'))) {
    $startInfo.ArgumentList.Add($arg)
}
$process = [Diagnostics.Process]::new()
$process.StartInfo = $startInfo
$null = $process.Start()
$stdoutBuffer = [char[]]::new(4096)
$stderrBuffer = [char[]]::new(4096)
$stdoutTask = $process.StandardOutput.ReadAsync($stdoutBuffer, 0, $stdoutBuffer.Length)
$stderrTask = $process.StandardError.ReadAsync($stderrBuffer, 0, $stderrBuffer.Length)
$transcript = [Text.StringBuilder]::new()
$startupDeadline = [DateTime]::UtcNow.AddSeconds(90)
$deadline = $null
$connection = $null
try {
    while ($true) {
        foreach ($stream in 'stdout', 'stderr') {
            $task = if ($stream -eq 'stdout') { $stdoutTask } else { $stderrTask }
            if ($null -ne $task -and $task.IsCompleted) {
                $count = $task.GetAwaiter().GetResult()
                $buffer = if ($stream -eq 'stdout') { $stdoutBuffer } else { $stderrBuffer }
                if ($count -gt 0) {
                    $chunk = [string]::new($buffer, 0, $count)
                    $null = $transcript.Append($chunk)
                    Write-Host -NoNewline $chunk
                    if ($stream -eq 'stdout') { $stdoutTask = $process.StandardOutput.ReadAsync($stdoutBuffer, 0, $stdoutBuffer.Length) }
                    else { $stderrTask = $process.StandardError.ReadAsync($stderrBuffer, 0, $stderrBuffer.Length) }
                } elseif ($stream -eq 'stdout') { $stdoutTask = $null }
                else { $stderrTask = $null }
            }
        }
        $plain = $transcript.ToString() -replace '\x1b\[[0-9;?]*[A-Za-z]', ''
        if (!$connection -and $plain -match 'ssh\s+([A-Za-z0-9_:+/=.-]+@uptermd\.upterm\.dev)') {
            $destination = $Matches[1]
            $connection = "ssh -i windows-test-lab_ed25519 $destination"
            $deadline = [DateTime]::UtcNow.AddMinutes($minutes)
            Write-Host "`nSSH READY: $connection"
            if ($env:GITHUB_STEP_SUMMARY) {
                "`n## SSH session`n`n~~~text`n$connection`n~~~`n`nSession duration: $minutes minutes. Run ``Finish-Lab`` to finish and upload exports.`n" |
                    Add-Content $env:GITHUB_STEP_SUMMARY
            }
        }
        if (Test-Path (Join-Path $workspace 'continue')) { Write-Host 'Finish-Lab requested; uploading exports next.'; break }
        if ($deadline -and [DateTime]::UtcNow -ge $deadline) { Write-Host 'Session time limit reached; uploading exports next.'; break }
        if (!$connection -and [DateTime]::UtcNow -ge $startupDeadline) { throw 'Upterm did not become ready within 90 seconds.' }
        if ($process.HasExited -and !$stdoutTask -and !$stderrTask) {
            if ($process.ExitCode -ne 0 -or !$connection) { throw "Upterm exited unexpectedly with code $($process.ExitCode)." }
            break
        }
        Start-Sleep -Milliseconds 200
    }
} finally {
    if (!$process.HasExited) { $process.Kill($true); $process.WaitForExit() }
    $process.Dispose()
}
