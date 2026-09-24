"""Exercise an installed desktop OpenMS beyond FileInfo: every tool, then upstream TOPP tests.

The labs install the package and leave its bin directory in reports/openms-bin.txt. This
step then

  1. starts every registered tool (scripts/topp-tools-smoke.py), and
  2. fetches src/tests/topp of the exact commit the package was built from (the Revision
     that `FileInfo --help` prints) and replays the upstream TOPP tests against the
     installed binaries (scripts/installed-topp-tests.py): all of them by default, or the
     selection in LAB_TOPP_TEST_SELECTION (release-gate, all, or a regex on test names).

Nothing is installed or changed on the system. When no desktop package was installed the
step records that and succeeds. It exits non-zero when either check failed, after writing
both reports, so the lab run shows red while later steps still run.
"""
import json
import os
from pathlib import Path
import re
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
    """Only the commit's src/tests/topp, without history or other blobs."""
    SOURCE.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", str(SOURCE)]
    if not (SOURCE / ".git").exists():
        subprocess.run(git + ["init", "-q"], check=True, env=env)
        subprocess.run(git + ["remote", "add", "origin", "https://github.com/OpenMS/OpenMS"], check=True, env=env)
    # Non-cone mode, so that single class-test data files can be added later (--fetch-missing).
    subprocess.run(git + ["sparse-checkout", "set", "--no-cone", "/src/tests/topp/"], check=True, env=env)
    subprocess.run(git + ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit], check=True, env=env)
    subprocess.run(git + ["checkout", "-q", "FETCH_HEAD"], check=True, env=env)


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
    failed = (summary.get("tools_exit") or summary.get("upstream_exit") or summary.get("bundled_libs_exit")
              or summary.get("upstream_tests") == "error")
    summary["status"] = "failed" if failed else "passed"
    (REPORTS / "installed-checks.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
