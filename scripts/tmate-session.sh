#!/usr/bin/env bash
set -euo pipefail
workspace="$(cygpath -u "$GITHUB_WORKSPACE")"
cd "$workspace"
keys="$workspace/ssh/authorized_keys"
socket="/tmp/windows-lab-${GITHUB_RUN_ID}.sock"
minutes="${LAB_SESSION_MINUTES:-60}"
case "$minutes" in 15|30|60|120) ;; *) echo 'Invalid session duration'; exit 1 ;; esac
test -s "$keys" || { echo 'No public SSH key configured; refusing to open a session.'; exit 1; }
pacman -S --noconfirm --needed tmate
ssh-keygen -lf "$keys"
cleanup() { tmate -S "$socket" kill-server >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
# -a requires this public key for every client and disables web access.
tmate -S "$socket" -a "$keys" new-session -d -c "$workspace" \
    'pwsh.exe -NoLogo -NoProfile -NoExit -File ./scripts/Enter-Lab.ps1'
timeout 90 tmate -S "$socket" wait tmate-ready
connection="$(tmate -S "$socket" display -p '#{tmate_ssh}')"
if [[ -z "$connection" ]]; then echo 'tmate did not return a connection command'; exit 1; fi
connection="${connection/ssh /ssh -i windows-test-lab_ed25519 }"
printf '\nConnect with your dedicated private key:\n%s\n\n' "$connection"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
        printf '\n## SSH session\n\n```text\n%s\n```\n\n' "$connection"
        printf 'Session duration: %s minutes. Run `Finish-Lab` in PowerShell to finish and upload exports.\n' "$minutes"
    } >> "$GITHUB_STEP_SUMMARY"
fi
deadline=$((SECONDS + minutes * 60))
while (( SECONDS < deadline )); do
    if [[ -e "$workspace/continue" ]]; then echo 'Finish-Lab requested; uploading exports next.'; exit 0; fi
    if ! tmate -S "$socket" has-session 2>/dev/null; then echo 'Session closed.'; exit 0; fi
    printf 'SSH session ready (%s minutes remaining): %s\n' "$(((deadline - SECONDS + 59) / 60))" "$connection"
    sleep 10
done
echo 'Session time limit reached; uploading exports next.'
