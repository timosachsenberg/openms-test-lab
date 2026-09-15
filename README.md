# Windows test lab for OpenMS

An on-demand `windows-2025` machine for testing installed OpenMS packages and pyOpenMS dependencies. It includes a separate Python virtual environment, package smoke tests, DLL dependency reports, and an optional native PowerShell session through Upterm.

## Start a lab

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

## Connect

Use the **private** `windows-test-lab_ed25519` file delivered when this lab was created. It is not stored in this repository or in workflow artifacts. The matching public key is in [`ssh/authorized_keys`](ssh/authorized_keys); no GitHub account SSH key registration is needed.

From the folder containing that private key, run the command shown by the workflow:

```text
ssh -i windows-test-lab_ed25519 SESSION@HOST
```

Replace `SESSION@HOST` with the exact address from that run. On macOS/Linux, first run `chmod 600 windows-test-lab_ed25519`. On Windows, keep the key in your user profile with access restricted to your user. The first connection asks you to trust the Upterm relay host key; your SSH client records it and detects changes on later connections.

You land in native PowerShell, with `.venv` active and the OpenMS `bin` directory on `PATH`.

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
- Supply an HTTPS wheel or installer URL for a candidate package. Download GitHub Actions artifacts and attach their extracted package to a release to get a public direct URL, or use SCP/SFTP with the same private key to transfer a local file. Upterm prints example SCP commands in the session log; add `-i windows-test-lab_ed25519` to use your lab key.
- Edit [`scripts/smoke.py`](scripts/smoke.py) for additional package tests.
- Wheel building from source is not automatic; use the installed Visual Studio/CMake tools interactively if needed. This lab tests binary packages rather than duplicating the full OpenMS source CI environment.

## SSH key management

Only clients with a private key matching `ssh/authorized_keys` can connect. There is no web terminal. Upterm 0.28.0 provides native Windows terminal and SCP/SFTP access; its download is pinned and checked with SHA-256. The generated lab key has no passphrase for straightforward use; protect the private file like a password. It grants access to active lab sessions, not to your GitHub account.

To rotate it, generate a new Ed25519 key locally and replace `ssh/authorized_keys` with its `.pub` contents. Never commit the private key. Changes apply to new runs. The job token has read-only repository permissions and checkout does not retain Git credentials.

This is a public test lab: workflow logs, reports, and exported artifacts must contain only data you intend to publish.
