"""Exercise an installed desktop OpenMS beyond FileInfo: every tool, then upstream TOPP tests.

The labs install the package and leave its bin directory in reports/openms-bin.txt. This
step then

  1. starts every registered tool (scripts/topp-tools-smoke.py), and
  2. fetches src/tests/topp and src/tests/toppas of the exact commit the package was built
     from (the Revision that `FileInfo --help` prints) and replays the upstream TOPP and
     TOPPAS pipeline tests against the installed binaries (scripts/installed-topp-tests.py):
     all of them by default, or the selection in LAB_TOPP_TEST_SELECTION (release-gate, all,
     or a regex on test names), and
  3. converts the Thermo .raw file among those tests with FileConverter's default reader and
     with each reader explicitly (C5 for Thermo; see check_thermo).

Nothing is installed or changed on the system. When no desktop package was installed the
step records that and succeeds. It exits non-zero when either check failed, after writing
all reports, so the lab run shows red while later steps still run.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SOURCE = ROOT / "downloads" / "openms-tests"
EXE = ".exe" if sys.platform.startswith("win") else ""


def resolve_commit(short):
    """Full SHA for the short revision a TOPP tool prints; git can only fetch full ones."""
    request = urllib.request.Request(f"https://api.github.com/repos/OpenMS/OpenMS/commits/{short}",
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": "openms-test-lab"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["sha"]


def fetch_tests(commit, env):
    """Only the commit's src/tests/topp and src/tests/toppas, without history or other blobs."""
    SOURCE.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", str(SOURCE)]
    if not (SOURCE / ".git").exists():
        subprocess.run(git + ["init", "-q"], check=True, env=env)
        subprocess.run(git + ["remote", "add", "origin", "https://github.com/OpenMS/OpenMS"], check=True, env=env)
    # Non-cone mode, so that single class-test data files can be added later (--fetch-missing).
    subprocess.run(git + ["sparse-checkout", "set", "--no-cone", "/src/tests/topp/", "/src/tests/toppas/"],
                   check=True, env=env)
    subprocess.run(git + ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit], check=True, env=env)
    subprocess.run(git + ["checkout", "-q", "FETCH_HEAD"], check=True, env=env)


def session_env(env):
    """The environment of a new login session after the installation.

    The Windows installer appends bin and every THIRDPARTY folder to the PATH in the registry,
    which the job's later steps do not pick up: a user's new session sees the system PATH
    followed by the user PATH. Elsewhere the environment is left as it is."""
    if not sys.platform.startswith("win"):
        return env
    import winreg
    parts = []
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(root, key) as handle:
                parts.append(os.path.expandvars(winreg.QueryValueEx(handle, "Path")[0]))
        except OSError:
            pass
    return dict(env, PATH=";".join(part.strip(";") for part in parts if part))


def check_thermo(bin_dir, env):
    """C5 for Thermo: FileConverter converts the fixture with its default reader, and the
    in-process reader writes as many spectra.

    The explicit external run shows whether ThermoRawFileParser works as installed (on the
    PATH, plus mono on Linux and macOS). The in-process reader needs a .NET 8 runtime; the hosted
    runners have one, which a user's machine may lack, so the report lists the runtimes.

    The reader locates .NET through nethost, which consults DOTNET_ROOT and the global install
    location but not the PATH. The hosted macOS runners keep .NET in ~/.dotnet, so when
    DOTNET_ROOT is unset, the conversions get it pointed at the installation the PATH leads to,
    as the reader's own error message tells users to do. The report records that."""
    raw = SOURCE / "src" / "tests" / "topp" / "THIRDPARTY" / "ginkgotoxin-ms-switching.raw"
    if not raw.is_file():
        return {"status": "skipped", "reason": f"{raw.name} is not in the fetched tests"}
    run_env = session_env(env)
    search_path = run_env.get("PATH", "")
    result = {"input": raw.name,
              "thermorawfileparser_on_path": shutil.which("ThermoRawFileParser.exe", path=search_path),
              "mono_on_path": shutil.which("mono", path=search_path)}
    dotnet = shutil.which("dotnet", path=search_path)
    if dotnet:
        listed = subprocess.run([dotnet, "--list-runtimes"], capture_output=True, text=True, errors="replace",
                                stdin=subprocess.DEVNULL, env=run_env)
        result["dotnet_runtimes"] = listed.stdout.splitlines()
        if not run_env.get("DOTNET_ROOT"):
            run_env = dict(run_env, DOTNET_ROOT=str(Path(dotnet).resolve().parent))
            result["dotnet_root_set_by_check"] = run_env["DOTNET_ROOT"]
    scratch = ROOT / "downloads" / "thermo-check"
    scratch.mkdir(parents=True, exist_ok=True)
    for mode, options in (("default", []), ("external", ["-RawToMzML:reader", "external"]),
                          ("inprocess", ["-RawToMzML:reader", "inprocess"])):
        out = scratch / f"{mode}.mzML"
        out.unlink(missing_ok=True)
        try:
            converted = subprocess.run([str(bin_dir / f"FileConverter{EXE}"), "-in", str(raw), "-out", str(out),
                                        "-no_progress", *options], capture_output=True, text=True, errors="replace",
                                       stdin=subprocess.DEVNULL, env=run_env, timeout=900)
            code, log = converted.returncode, converted.stdout + converted.stderr
        except subprocess.TimeoutExpired:
            code, log = "timeout", ""
        spectra = out.read_text(encoding="utf-8", errors="replace").count("<spectrum ") if out.is_file() else 0
        result[mode] = {"exit": code, "spectra": spectra, "log_tail": log.strip().splitlines()[-12:]}
    default, inprocess = result["default"], result["inprocess"]
    passed = default["exit"] == 0 and default["spectra"] > 0 and inprocess["spectra"] == default["spectra"]
    result["status"] = "passed" if passed else "failed"
    return result


def main():
    bin_file = REPORTS / "openms-bin.txt"
    if not bin_file.exists():
        (REPORTS / "installed-checks.json").write_text(json.dumps({"status": "skipped",
                                                                   "reason": "no desktop package installed"}))
        print("No desktop OpenMS installed; nothing to check.")
        return 0
    bin_dir = Path(bin_file.read_text(encoding="utf-8").strip())
    python = sys.executable
    # The job token is only for the commit lookup; the tools under test never see it.
    child_env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    summary = {"bin_dir": str(bin_dir)}

    smoke = [python, str(ROOT / "scripts/topp-tools-smoke.py"), "--bin-dir", str(bin_dir),
             "--report", str(REPORTS / "topp-tools.json")]
    package_files = REPORTS / "openms-installed-files.txt"
    if package_files.exists():
        smoke += ["--package-files", str(package_files)]
    summary["tools_exit"] = subprocess.run(smoke, env=child_env).returncode

    help_text = subprocess.run([str(bin_dir / f"FileInfo{EXE}"), "--help"], capture_output=True, text=True,
                               errors="replace", stdin=subprocess.DEVNULL, env=child_env)
    revision = re.search(r"Revision:\s*([0-9a-f]{7,40})", help_text.stdout + help_text.stderr)
    if not revision:
        summary.update(upstream_tests="skipped", reason="FileInfo --help printed no Revision")
    else:
        try:
            commit = resolve_commit(revision.group(1))
            fetch_tests(commit, child_env)
            summary["commit"] = commit
            summary["upstream_exit"] = subprocess.run(
                [python, str(ROOT / "scripts/installed-topp-tests.py"), "--openms", str(SOURCE),
                 "--bin-dir", str(bin_dir), "--select", os.environ.get("LAB_TOPP_TEST_SELECTION") or "all",
                 "--fetch-missing",
                 "--report", str(REPORTS / "installed-topp-tests.json")], env=child_env).returncode
        except Exception as error:  # network or git trouble is reported, not hidden
            summary.update(upstream_tests="error", reason=str(error))
    # F6: security-relevant libraries the package carries. On Linux only the package's own
    # files are scanned; elsewhere the installation root is private to OpenMS.
    libs = [python, str(ROOT / "scripts/bundled-libs.py"), "--report", str(REPORTS / "bundled-libs.json")]
    libs += (["/", "--file-list", str(package_files)] if package_files.exists() else [str(bin_dir.parent)])
    summary["bundled_libs_exit"] = subprocess.run(libs, env=child_env).returncode
    summary["thermo"] = check_thermo(bin_dir, child_env)
    failed = (summary.get("tools_exit") or summary.get("upstream_exit") or summary.get("bundled_libs_exit")
              or summary.get("upstream_tests") == "error" or summary["thermo"]["status"] == "failed")
    summary["status"] = "failed" if failed else "passed"
    (REPORTS / "installed-checks.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
