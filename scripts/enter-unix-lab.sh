# Sourced by the interactive Bash session.
cd "$GITHUB_WORKSPACE" || return
if [[ -f .venv/bin/activate ]]; then source .venv/bin/activate; fi
if [[ -f reports/openms-bin.txt ]]; then export PATH="$(cat reports/openms-bin.txt):$PATH"; fi
finish-lab() { touch "$GITHUB_WORKSPACE/continue"; }
export-lab-wheels() { python3 "$GITHUB_WORKSPACE/scripts/unix-lab.py" export; }
test-lab-python() { python3 "$GITHUB_WORKSPACE/scripts/unix-lab.py" python; }
printf '\nOpenMS package lab (%s / %s)\n' "$(uname -s)" "$(uname -m)"
printf 'Python: .venv | Reports: reports/ | Downloads: downloads/ | Save files: exports/\n'
printf 'Commands: test-lab-python, export-lab-wheels, finish-lab\n'
printf 'Disconnecting leaves the session available until its time limit.\n'
