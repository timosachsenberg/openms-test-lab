# openms-test-lab — Agent Notes

Context and instructions for AI agents working in this repository. Follows the
[AGENTS.md](https://agents.md) standard. `CLAUDE.md` points here.

This repository is **a test lab, not a product**. It contains no OpenMS source. Its job is to run
OpenMS and pyOpenMS *packages* on real machines and to record what they do. Changes here are
workflows, helper scripts and audit reports.

## What "run a full package audit" means

An unqualified request to *run a full package audit*, *audit the packages*, or *do an audit* means
all three of the following, against one set of artifacts, written up as one report. It is not the
nine lab runs alone, and not the static checks alone.

1. **The nine-run release test matrix** in [README.md](README.md#release-test-matrix), dispatched
   with `debug: false` so the runs are unattended.
2. **The static artifact analysis** — the thirteen checks listed under
   [*Checks that are not automated here*](README.md#checks-that-are-not-automated-here), run by hand
   against every published artifact for the target.
3. **A functional pyOpenMS suite** on at least one platform, covering the behavioural findings the
   previous audit recorded so regressions and fixes are both visible.

### The default target is the current nightly

Audit **the current nightly packages** unless the request names a release, a version or a PR. The
labs default to `nightly` for both package inputs for the same reason: nightly is where a problem
can still be fixed before it ships. "Audit 3.5.0" or "audit the release candidate" means pin the
exact version instead — a requirement and a release tag, never a bare `pyopenms`.

A nightly audit has two sources, and they are not GitHub releases:

- wheels — the PEP 503 index at `https://pypi.openms.de/simple/pyopenms/`
- desktop installers — dated folders under `https://archive.openms.de/openms/OpenMSInstaller/nightly/`

`scripts/resolve_nightly.py wheel|desktop` resolves both and prints what it picked; use it rather
than hand-building URLs, so the audit tests what the labs test.

### The report

Write `PACKAGE-AUDIT-<target>.md` at the repository root — `PACKAGE-AUDIT-3.5.0.md` for a release,
`PACKAGE-AUDIT-NIGHTLY-<YYYY-MM-DD>.md` for a nightly — and link it from `README.md`. Follow the
shape of the existing reports:

- state the exact artifacts and the source revision, so the audit can be repeated;
- order findings by release impact (Blocker / High / Medium / Low) behind a summary table;
- for each finding, say **what was observed and how it was observed** — the command, the output, the
  file and line — so a reader can re-check it independently;
- carry a **What the previous audit fixed** table. An audit that does not say which earlier findings
  are now resolved makes the next one repeat the work;
- keep a **What was verified as sound** section for the same reason;
- list the lab run IDs.

### Existing audits

| Report | Target | Date |
|---|---|---|
| [PACKAGE-AUDIT-3.5.0.md](PACKAGE-AUDIT-3.5.0.md) | release 3.5.0 — 8 release assets, 25 wheels | 2026-09-19 |
| [PACKAGE-AUDIT-NIGHTLY-2026-09-22.md](PACKAGE-AUDIT-NIGHTLY-2026-09-22.md) | nightly `3.6.0-pre-nightly-2026-09-21` / `3.6.0.dev20260922` | 2026-09-22 |

## Ground rules

- **Never soften a finding to make a run look clean.** A failed run with a diagnosed cause is worth
  more than a green one. Equally, do not report a defect you have not demonstrated: run the command,
  quote the output.
- **Check the OpenMS source before calling something a bug.** `/home/user/OpenMS`, or the
  [repository](https://github.com/OpenMS/OpenMS), answers most "is this layout wrong?" questions
  outright. Two candidate findings in the 2026-09-22 audit dissolved this way.
- **Distinguish "present" from "reachable".** An unsafe RUNPATH that the normal load order never
  consults is a latent defect, not an exploit; say which it is and show the trace.
- **This is a public repository.** Workflow logs, reports and exported artifacts must contain only
  data intended for publication. Never commit the lab's private SSH key.
- **A passing run is not a clean-machine certification.** Hosted runners come with many
  dependencies preinstalled; read the dependency report before calling a package self-contained.

## Running the labs

Dispatch is `workflow_dispatch` only, on `windows-lab.yml`, `macos-lab.yml` and `linux-lab.yml`.
Dispatch from the branch you are working on when it carries script changes, and record the ref in
the report. Reports land in the run's `*-lab-reports-<run_id>` artifact — prefer them to the job
logs, which are long and mostly runner noise. The useful files:

| File | Holds |
|---|---|
| `python-selection.json` | the wheel that was resolved, with version and digest. **Absent means resolution failed** |
| `openms-package.json` | the installer URL, SHA-256, and whether installation succeeded |
| `openms-install.log` | the package manager's own output — the first place to look at an install failure |
| `python-smoke.json`, `python-probe.json` | the smoke test, stub parse and loaded-library capture |
| `dependency-summary.json`, `binary-inventory.json` | the native inventory |

## Environment notes

Things that cost time in a previous audit:

- **`xar` and `cpio` are not installed** in the agent container. A macOS `.pkg` is a XAR archive —
  a 28-byte header, then a zlib-compressed XML table of contents — and its component payloads are
  gzipped **old-format (`070707`) cpio**, not `newc`. Both parse in a few lines of Python; see the
  2026-09-22 audit for what to extract (`Distribution`, `PackageInfo`, `Payload`).
- **`pefile`, `macholib` and `auditwheel` are not preinstalled** but do install from PyPI, which is
  reachable directly. `pypi.openms.de` and `archive.openms.de` go through the egress proxy.
- **The nightly wheel index can be down.** It returned HTTP 504 for the whole 2026-09-22 audit. When
  it is, the wheels of the same build can be taken from the `pyopenms-wheels-cibuildwheel` run on
  the `nightly` branch of OpenMS/OpenMS — but that is the CI artifact, not the published file, so
  say so in the report and leave the published-hash check outstanding.
- **A nightly folder is named for the upload date; the package inside is named for the commit
  date.** `2026.09.22/` holds `…-nightly-2026-09-21-…`. Do not treat the mismatch as a defect.
- **Desktop artifacts are ~200–260 MB each and extract to ~900 MB.** Download to the scratchpad
  directory, not the repository, and check free space before extracting both architectures.

## Repository layout

| Path | Purpose |
|---|---|
| `.github/workflows/` | the six lab workflows; all `workflow_dispatch` |
| `scripts/resolve_nightly.py` | shared nightly resolution for all three labs |
| `scripts/smoke.py` | the pyOpenMS smoke test; extend it for new package checks |
| `scripts/unix-lab.py`, `unix-audit.py`, `unix-probe.py`, `trace-native.py` | macOS/Linux lab driver and native inspection |
| `scripts/*.ps1`, `scripts/dll-audit.py`, `verify-pr-wheel.py` | the Windows equivalents |
| `PACKAGE-AUDIT-*.md` | audit reports |
| `README.md`, `UNIX-LABS.md` | Windows and macOS/Linux instructions |

Keep `README.md`, `UNIX-LABS.md` and the workflow inputs in step: the README's matrix and input
tables are what a person reads before dispatching a run.
