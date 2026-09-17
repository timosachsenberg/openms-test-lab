# macOS and Linux package labs

These are on-demand environments in the existing public test-lab repository:

- [macOS package lab](https://github.com/timosachsenberg/windows-test-lab/actions/workflows/macos-lab.yml)
- [Linux package lab](https://github.com/timosachsenberg/windows-test-lab/actions/workflows/linux-lab.yml)

Select **Run workflow** on main. The default packages are the current PyPI pyOpenMS wheel and latest released desktop OpenMS. The two versions are recorded independently.

## Runner choices

| Lab | Default | Other choices |
| --- | --- | --- |
| macOS | macos-15, Apple Silicon ARM64 | macos-15-intel, Intel x64 |
| Linux | ubuntu-24.04, x64 | ubuntu-24.04-arm, ARM64; ubuntu-22.04, x64 |

These are standard GitHub-hosted VMs. See [GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) for current architecture and availability. A new run creates a disposable machine; closing SSH does not preserve it.

## Inputs

| Input | Use |
| --- | --- |
| python_version | Defaults to 3.12; choose a version supported by your wheel. |
| pyopenms_spec | A PyPI requirement such as pyopenms==3.5.0, a direct HTTPS wheel URL, or **none** to skip. |
| extra_packages | Semicolon-separated requirements, for example numpy==2.2.6;pandas. Persistent extras can also go in requirements.txt. |
| openms_package | **latest**, a release tag such as release/3.5.0, a public HTTPS PKG/DEB URL, or **none** to skip desktop installation. |
| wheel_run_id | Optional successful upstream OpenMS wheel-workflow run ID. Selects a compatible wheel and overrides pyopenms_spec. |
| debug | Enabled by default. Opens SSH after checks, including if a check failed. Disable for unattended testing. |
| session_minutes | 5, 15, 30, 60 or 120; defaults to 60. |
| export_wheels | Download the installed Python packages and lock file into the exports artifact. |

Use the literal **none** to skip a package; an empty browser field may restore a workflow default. Binary wheels are required during automatic setup. Source builds can be run explicitly in the interactive shell.

Desktop installation uses the matching official PKG on macOS and DEB on Linux. Linux apt resolves declared package dependencies; before/after inventories and the install log show what it added. The lab does not silently install Homebrew libraries or add LD_LIBRARY_PATH/DYLD_LIBRARY_PATH to make package tests pass.

For an upstream run, expected artifact names are wheels-linux-x64, wheels-linux-arm64 and wheels-macos-arm64. Current upstream CI has no wheels-macos-x64 artifact; use PyPI or a direct compatible wheel URL on Intel Mac. Artifact SHA-256 is verified before extraction, wheel compatibility is checked against Python's supported tags, and the source run, head SHA and wheel hash are saved. A PR run's head SHA identifies the PR head; upstream may have built its generated merge commit.

## Connect with the existing key

Use the same private **windows-test-lab_ed25519** key supplied for Windows. Only its matching public key is in the repository. No new key or GitHub account SSH-key registration is needed.

The **SSH debugging session** log and run summary show a command like:

~~~text
ssh -i windows-test-lab_ed25519 SESSION@uptermd.upterm.dev
~~~

Use the exact session address from that run. On macOS/Linux, first restrict the local key permissions with chmod 600. Upterm is pinned to 0.28.0 and its platform-specific download is SHA-256 checked. The session is restricted to ssh/authorized_keys.

You enter Bash in the repository with .venv active and the installed OpenMS bin directory on PATH.

~~~bash
python -c "import pyopenms; print(pyopenms.__version__)"
python -m pip check
FileInfo --help
test-lab-python
export-lab-wheels
finish-lab
~~~

- **test-lab-python** repeats the Python smoke test, stub parsing and library-load capture.
- **export-lab-wheels** saves wheels and requirements-lock.txt under exports/.
- **finish-lab** ends the session and allows final reports/exports to upload.
- Standard **sftp -i windows-test-lab_ed25519 SESSION@uptermd.upterm.dev** transfers files in either direction.
- Save anything you need in **exports/**. For example, copy a downloaded native installer from downloads/ to exports/ before finishing.
- Cancelling the workflow can interrupt artifact uploads; prefer finish-lab or the automatic time limit.

## Tests and diagnostics

The lab inventories the runner **before setup**, **after Python setup**, and **after native installation**. Python tests run before desktop OpenMS installation, with library-search overrides removed.

The Python smoke test imports pyOpenMS, checks peptide mass, and round-trips a NumPy-backed spectrum through mzML. Packaged .pyi files are syntax-checked. A load trace records actual libraries present in that Python process: /proc/self/maps on Linux, and dyld image enumeration on macOS.

The desktop smoke test starts FileInfo and reads the generated mzML. Native loader logs use LD_DEBUG on Linux and DYLD_PRINT_LIBRARIES on macOS; hardened macOS executables can suppress that trace.

Reports include:

- exact installed Python packages, pip consistency checks and wheel compatibility tags;
- wheel/native-package URL, SHA-256 and upstream artifact provenance where applicable;
- all discovered installed ELF/Mach-O binaries and their SHA-256;
- Linux readelf/ldd dependencies, or macOS otool install names and LC_RPATH;
- actual Python loaded-library paths classified as packaged, CPython, system packages, Homebrew or other;
- Debian packages/loader cache or macOS package receipts/Homebrew versions, plus available .NET runtimes;
- native install logs, CLI smoke tests and runtime traces.

Download the **macos-lab-reports-...** or **linux-lab-reports-...** artifacts. A setup-report artifact is available before SSH starts; final reports and exports upload when the session finishes. Artifacts are retained for seven days.

A hosted runner includes many preinstalled dependencies. On Linux, a library supplied by a system package is identified as such, not assumed to be part of bare Linux. On macOS, absolute Homebrew paths can still resolve even with a minimal PATH. Static Mach-O entries are recorded without pretending to emulate all dyld resolution. Tests do not cover every GUI plugin, vendor reader, delayed load or Thermo RAW/.NET path. Inspect the evidence before concluding a package is self-contained.

## Native source builds

These workflows test installed packages. You can compile code interactively using the runner's development tools and export results. They do not automatically duplicate OpenMS's complete source-build CI or the separate Windows development-installer workflow.

## Access and artifacts

The workflows are manual only, use a read-only job token, and do not retain checkout credentials. SSH uses the existing public-key allowlist and has a bounded lifetime. Reports and exports in this public repository are public; use test data intended for publication.
