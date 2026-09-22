# openms-test-lab

On-demand Windows, macOS and Linux runners that test OpenMS and pyOpenMS **packages**. No OpenMS
source lives here; see [README.md](README.md) for Windows and [UNIX-LABS.md](UNIX-LABS.md) for
macOS and Linux.

Read **[AGENTS.md](AGENTS.md)** before working here. It holds the ground rules, the lab-report
layout and the environment gotchas.

## "Run a full package audit"

An unqualified audit request means all three parts, against one set of artifacts, in one report:

1. the nine-run [release test matrix](README.md#release-test-matrix), `debug: false`;
2. the thirteen [static artifact checks](README.md#checks-that-are-not-automated-here), by hand;
3. a functional pyOpenMS suite, covering the previous audit's behavioural findings.

**The default target is the current nightly** — audit a release only when one is named. Resolve
nightly artifacts with `scripts/resolve_nightly.py wheel|desktop` rather than hand-built URLs.

Write the result to `PACKAGE-AUDIT-NIGHTLY-<YYYY-MM-DD>.md` (or `PACKAGE-AUDIT-<version>.md`), link
it from the README, and include a table of which findings of the previous audit are now fixed.
AGENTS.md has the full report contract; [PACKAGE-AUDIT-3.5.0.md](PACKAGE-AUDIT-3.5.0.md) and
[PACKAGE-AUDIT-NIGHTLY-2026-09-22.md](PACKAGE-AUDIT-NIGHTLY-2026-09-22.md) are the worked examples.

## Quick reference

- Labs are `workflow_dispatch` only: `windows-lab.yml`, `macos-lab.yml`, `linux-lab.yml`.
- Read results from the run's `*-lab-reports-<run_id>` artifact, not the job log. `python-selection.json`
  missing means wheel resolution failed; `openms-install.log` explains an install failure.
- Both package inputs take `nightly`, `latest`, a pinned value, an HTTPS URL, or the literal `none`.
- Never commit the lab's private SSH key. This repository is public, and so are its run logs.

## Related

The OpenMS source repository has its own `CLAUDE.md` and `AGENTS.md`. Fixes for anything an audit
finds belong there; this repository records the evidence.
