# Instructions for agents

This repository tests OpenMS packages on hosted Windows, macOS and Linux runners. Humans read
[README.md](README.md); this file tells an agent where to start.

## "Check our nightlies" / "Can we release?"

Follow [RELEASE-READINESS.md](RELEASE-READINESS.md) from top to bottom. It defines the quality
standard (blocking, advisory and human checks, each with an ID), the verdict rules, and the
commands that produce the evidence. In short:

1. Identify the candidate and its revision (A1, A2).
2. Run the automated Linux gate: dispatch the **Release readiness** workflow, or run
   `python3 scripts/release-readiness.py all` on a Linux machine with sudo, and read
   `reports/readiness-summary.md`.
3. Dispatch the release matrix of the package labs with `debug=false` and read each run's
   `reports/installed-checks.json`, `topp-tools.json` and `installed-topp-tests.json`.
4. Do the static (F) and judgement checks (D5, E4).
5. Copy [readiness/TEMPLATE.md](readiness/TEMPLATE.md) to
   `readiness/<date>-<version>-<candidate>.md`, fill in every checkbox with evidence, and end
   with one verdict: NOT READY, READY FOR RC or READY TO RELEASE.

## Rules

- A check you could not run is **not run**, never passed. Say why.
- Never waive a blocking check or relabel it advisory; only a maintainer can, in writing.
- Pass `debug=false` to every lab you dispatch. The default opens an SSH session that holds
  the runner for up to an hour.
- Work on a branch and do not merge. Committing a report is fine when you were asked to
  write one; opening issues or PRs in OpenMS/OpenMS needs an explicit request.
- Everything a lab uploads is public. Do not put credentials or private data in inputs,
  reports or exports.
- Pin what you test. A nightly is identified by its date, file names, SHA-256 and git
  revision; a release candidate by exact versions or URLs, never by `latest`.

## Useful commands

```bash
python3 scripts/resolve_nightly.py wheel        # newest compatible nightly wheel + sha256
python3 scripts/resolve_nightly.py desktop      # newest nightly installer for this platform
python3 scripts/topp-tools-smoke.py             # C1/C2 against the OpenMS on PATH
python3 scripts/installed-topp-tests.py --openms <OpenMS checkout> --select all --fetch-missing  # C3
python3 scripts/pyopenms-api.py snapshot --out <file>                                       # in each venv
python3 scripts/pyopenms-api.py diff <old> <new> --docs <user_guide> --changelog <CHANGELOG> # D1, D4
python3 scripts/doc-examples.py --python <venv python> --docs <user_guide> [--baseline <report>]  # D2, D3
python3 scripts/release-docs-audit.py --openms <OpenMS checkout> --base release/<previous>    # A3, E1-E8
```
