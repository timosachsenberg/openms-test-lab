# Windows test lab for OpenMS

An on-demand `windows-2025` machine for testing installed OpenMS packages and pyOpenMS dependencies. It includes a separate Python virtual environment, package smoke tests, DLL dependency reports, and an optional native PowerShell session through Upterm.

## Build and audit a standalone OpenMS development installer

Use [Windows development build and DLL audit](https://github.com/timosachsenberg/windows-test-lab/actions/workflows/windows-dev-build-audit.yml) when upstream CI has no installer for the commit you need. Enter the exact 40-character OpenMS commit SHA. The initial default matches the previously audited PR #10146 wheel run's head, `760f6ab2e0b49c84e4169e14fe71a72e98571070`.

This workflow builds OpenMS with its own Windows CI recipe, runs the upstream test suite, creates an NSIS installer, and uploads it with the source SHA and checksum. A separate fresh Windows job downloads and verifies that artifact, inventories preinstalled runtimes, installs OpenMS, and audits its binaries and actual `FileInfo` DLL loads. It also records packaged .NET runtime configuration. The build can be resource-intensive; its timeout is three hours. Run it only when you want a new build. It publishes downloadable Actions artifacts, with 14-day retention.

The standalone audit does not install pyOpenMS. Use **Windows DLL audit** for an existing pyOpenMS wheel plus a released desktop package. A successful build or startup check is not a clean-machine certification; inspect the runtime inventory and dependency findings.

## Start a package lab

1. Open [Actions → Windows package lab](https://github.com/timosachsenberg/windows-test-lab/actions/workflows/windows-lab.yml).
2. Select **Run workflow** on `main`.
3. Choose Python, pyOpenMS, extra packages, and an OpenMS installer. Keep **debug** enabled to connect interactively.
4. Open the run. After setup, the **SSH debugging session** log and run summary show your SSH command.

| Input | Default | Examples |
| --- | --- | --- |
| `python_version` | `3.12` | `3.11`, `3.12`, `3.13` (the selected wheel must support it) |
| `pyopenms_spec` | `pyopenms` | `pyopenms==3.5.0`, direct HTTPS `.whl` URL, blank to skip |
| `extra_packages` | blank | `numpy==2.2.6;pandas` (semicolon separates requirements) |
| `openms_package` | `latest` | `release/3.5.0`, public HTTPS `.exe`/`.msi`/`.zip` URL, blank to skip |
| `debug` | enabled | Disable for unattended package checks |
| `session_minutes` | `60` | `15`, `30`, `60`, `120` |

The workflow is manual only. Setup or test failures remain visible and still allow debugging. A session ends cleanly at its time limit. Standard GitHub-hosted runners in public repositories have free compute; downloadable artifacts are kept for seven days.

## Test an OpenMS PR wheel

Open [Actions → Windows PR wheel lab](https://github.com/timosachsenberg/windows-test-lab/actions/workflows/windows-pr-wheel.yml), select **Run workflow**, and enter the OpenMS PR number. The initial defaults target PR #10146 on Python 3.12.

The workflow selects the latest successful upstream wheel build for the **current PR head**, downloads `wheels-windows-x64`, verifies the artifact SHA-256, and installs the exact wheel. An optional upstream `run_id` pins a particular build; a run for a different commit is rejected. The upstream PR must already have a successful wheel build and an unexpired artifact.

Checks cover all 15 extension imports with a minimal Windows/Python `PATH`, the `py.typed` marker, UTF-8 and syntax of the packaged `.pyi` files, stubs for all 13 domain modules, PE DLL imports, absence of `zlib1.dll`, and the loaded bundled libcurl version. `expected_curl` defaults to `8.12.1` for PR #10146; change or clear it when testing a PR that intentionally updates curl. The usual NumPy/mzML smoke test also runs. This workflow does not install desktop OpenMS.

Download **pr-wheel-reports** for results and provenance, and **pr-wheel-exports** for the exact tested wheel. Enable **debug** to open the same SSH lab after the checks, including on failure. `./.venv/Scripts/python.exe scripts/verify-pr-wheel.py` repeats the focused checks interactively. These checks validate the built package; incremental CMake rebuild behavior is a separate source-build test.

## Audit DLL packaging and runner dependencies

[Windows DLL audit](https://github.com/timosachsenberg/windows-test-lab/actions/workflows/windows-dll-audit.yml) accepts an upstream wheel run ID and an optional desktop OpenMS release or installer URL. It inventories MSVC and .NET runtimes before installation, tests Python imports before installing desktop OpenMS, and records actual loaded DLL paths. It traces `FileInfo --help` through Windows DLL-load debug events, so short-lived DLL loads are captured.

The downloadable report contains every installed wheel/desktop PE binary, file version, SHA-256, normal and delayed DLL imports, MSVC imported-symbol checks, managed runtime configuration, and before/after runner runtime inventories. It distinguishes bundled DLL candidates, CPython-supplied runtimes, Windows components, and preinstalled non-OS runtimes. Removing `PATH` entries does **not** remove DLLs from `System32` or CPython; the report therefore does not treat a passing hosted-runner test as proof that the package works on bare Windows. MSVC runtime DLLs in `System32` remain classified as preinstalled redistributables.

The wheel and installer versions can differ; source URLs, commit IDs and checksums are recorded separately. This audit does not change system DLLs or uninstall the runner's runtimes. The runtime trace covers the named imports and CLI startup; additional plugins, GUI interactions and Thermo RAW loading need separate coverage.

## Connect

Use the **private** `windows-test-lab_ed25519` file delivered when this lab was created. It is not stored in this repository or in workflow artifacts. The matching public key is in [`ssh/authorized_keys`](ssh/authorized_keys); no GitHub account SSH key registration is needed.

From the folder containing that private key, run the command shown by the workflow:

```text
ssh -i windows-test-lab_ed25519 SESSION@HOST
```

Replace `SESSION@HOST` with the exact address from that run. On macOS/Linux, first run `chmod 600 windows-test-lab_ed25519`. On Windows, keep the key in your user profile with access restricted to your user. The first connection asks you to trust the Upterm relay host key; your SSH client records it and detects changes on later connections.

You land in native PowerShell, with `.venv` active and the OpenMS `bin` directory on `PATH`.

For file transfers, use `sftp -i windows-test-lab_ed25519 SESSION@HOST`, or the connection bundle's `Connect-Lab.ps1 -Destination SESSION@HOST -Sftp`. In SFTP, use `put` and `get` to transfer files. For example, `get D:/a/windows-test-lab/windows-test-lab/reports/python-smoke.json` downloads the test report. Prefer SFTP: Windows OpenSSH's `scp` may return exit code 1 after a successful copy through Upterm 0.28.0.

```powershell
python -c "import pyopenms; print(pyopenms.__version__)"
python -m pip check
FileInfo --help
python -m pip install 'numpy==2.2.6'
./scripts/Test-Python.ps1
Export-LabWheels
Finish-Lab
```

`Finish-Lab` ends the session and uploads `exports/`. Disconnecting SSH by itself keeps it available until the time limit. This is a disposable Windows runner: put everything you need to keep in `exports/` before finishing.

## Downloads and diagnostics

The run's **Artifacts** section provides:

- **windows-lab-reports**: pip install logs/reports, exact installed versions, dependency consistency checks, wheel compatibility tags, a native binary inventory, `dumpbin /DEPENDENTS` output, and smoke-test results.
- **windows-lab-exports**: files you put in `exports/`, including a wheelhouse made with `Export-LabWheels`. Uploaded when the session ends normally; cancelling the workflow may prevent this upload.

The Python test imports pyOpenMS **before** the desktop OpenMS package is installed. It checks a peptide mass and a NumPy → spectrum → mzML → spectrum round trip, to expose wheel/DLL bundling problems without help from an installed OpenMS. The desktop test starts `FileInfo` and reads the generated mzML file. These are CLI/native-library checks; GUI behavior is not tested.

Downloaded installers are in `downloads/`, the Python environment is `.venv/`, and OpenMS is installed under `C:\OpenMS`. To export an installer, copy it to `exports/`. The workflow records the installer's source URL and SHA-256.

## Custom packages and repeatable tests

- Put persistent Python requirements in [`requirements.txt`](requirements.txt).
- Supply an HTTPS wheel or installer URL for a candidate package. Download GitHub Actions artifacts and attach their extracted package to a release to get a public direct URL, or use SFTP with the same private key to transfer a local file.
- Edit [`scripts/smoke.py`](scripts/smoke.py) for additional package tests.
- Wheel building from source is not automatic; use the installed Visual Studio/CMake tools interactively if needed. This lab tests binary packages rather than duplicating the full OpenMS source CI environment.

## SSH key management

Only clients with a private key matching `ssh/authorized_keys` can connect. There is no web terminal. Upterm 0.28.0 provides native Windows terminal and SCP/SFTP access; its download is pinned and checked with SHA-256. The generated lab key has no passphrase for straightforward use; protect the private file like a password. It grants access to active lab sessions, not to your GitHub account.

To rotate it, generate a new Ed25519 key locally and replace `ssh/authorized_keys` with its `.pub` contents. Never commit the private key. Changes apply to new runs. The job token has read-only repository permissions and checkout does not retain Git credentials.

This is a public test lab: workflow logs, reports, and exported artifacts must contain only data you intend to publish.

## Verified setup

[Run #3](https://github.com/timosachsenberg/windows-test-lab/actions/runs/34990343042) passed on 2026-09-15 with Windows Server 2025, Python 3.12.10, OpenMS/pyOpenMS 3.5.0, and NumPy 2.5.3. Validation included native package tests, private-key SSH login, rejection of an unrelated key, a SFTP download with matching SHA-256, and export of 14 wheels plus the dependency lock file. The validation session was ended with `Finish-Lab`; start a new run when you need a machine.

