# Keeps the Upterm host alive. Each SSH client gets its own PowerShell via --force-command.
while (!(Test-Path -LiteralPath (Join-Path $env:GITHUB_WORKSPACE 'continue'))) {
    Start-Sleep -Seconds 5
}
