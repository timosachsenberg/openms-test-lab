"""C10: a published OpenMS container image passes the checks of an installed package.

The images (ghcr.io/openms/openms-library, -tools and -tools-thirdparty) are built by
OpenMS' containerdeploy.yml from dockerfiles/Dockerfile, not by the Release workflow: with
Ubuntu's libraries instead of vcpkg's, build options of their own, and the search engines in
/opt/OpenMS/thirdparty. What the installers prove says little about them, yet workflow
systems such as bigbio/quantms run OpenMS from them. This script checks one image:

  1. pristine   the image as published, nothing added: every ELF file under /opt/OpenMS
                resolves its libraries, no symbolic link there dangles, and FileInfo --help
                and OpenMSInfo exit 0
  2. installed  scripts/installed-checks.py inside a throwaway container of the image: every
                tool (C1), the engines (C2), the upstream TOPP tests (C3), bundled libraries
                (F6), the Thermo reader (C5) and OpenMP (C9). For that the container gets git
                (the image has python3), and share/OpenMS/THIRDPARTY/<engine> links to
                /opt/OpenMS/thirdparty/<engine>, where the lab looks for the engines; the
                image has them on its PATH
  3. options    the build options C3 reads from the image are the installers' (--expect):
                PeptDeep/ONNX, Bruker timsTOF and OpenSwath support

    python3 scripts/container-checks.py --image ghcr.io/openms/openms-tools-thirdparty:latest

Reports: reports/container-checks.json, and the reports of step 2 under reports/container/.
Exits 1 when a step failed.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
WORK = ROOT / "downloads" / "container-lab"
# What the Release workflow's installers are built with (the ci-base preset of CMakePresets.json).
EXPECT = "WITH_ONNX=ON,WITH_OPENTIMS=ON,DISABLE_OPENSWATH=OFF"

PRISTINE = r"""
set -u
cd /out
FileInfo --help > fileinfo.log 2>&1; echo $? > fileinfo.rc
OpenMSInfo > openmsinfo.log 2>&1; echo $? > openmsinfo.rc
find /opt/OpenMS -xtype l -printf '%p -> %l\n' > dangling.txt
: > unresolved.txt
case $(uname -m) in x86_64) rid=linux-x64;; aarch64) rid=linux-arm64;; *) rid=none;; esac
find /opt/OpenMS -type f -size +0 | while IFS= read -r f; do
  # .NET applications such as ThermoRawFileParser carry native libraries for every platform
  # under runtimes/<platform>/; only this one's are loaded here.
  case "$f" in */runtimes/*/*) r=${f#*/runtimes/}; [ "${r%%/*}" = "$rid" ] || continue;; esac
  [ "$(head -c 4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ] || continue
  ldd "$f" 2>&1 | grep 'not found' | sed "s|^|$f: |" >> unresolved.txt
done
exit 0
"""

INSTALLED = r"""
set -u
export DEBIAN_FRONTEND=noninteractive
cd /lab
{ apt-get update && apt-get install -y --no-install-recommends git ca-certificates; } > reports/container-apt.log 2>&1 \
  || { echo "installing git failed" >&2; exit 90; }
share=/opt/OpenMS/share/OpenMS
for engine in /opt/OpenMS/thirdparty/*/; do
  engine=${engine%/}
  [ -e "$share/THIRDPARTY/${engine##*/}" ] || ln -s "$engine" "$share/THIRDPARTY/${engine##*/}"
done
echo /opt/OpenMS/bin > reports/openms-bin.txt
python3 scripts/installed-checks.py
"""


def docker(*args, timeout=900, capture=True):
    return subprocess.run(["docker", *args], capture_output=capture, text=True, errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout)


def read(folder, name):
    path = folder / name
    return path.read_text(encoding="utf-8", errors="replace").strip() if path.exists() else None


def pristine(image):
    out = WORK / "pristine"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    ran = docker("run", "--rm", "-v", f"{out.resolve()}:/out", "--entrypoint", "bash", image, "-c", PRISTINE)
    if ran.returncode:
        return {"status": "failed", "reason": f"container exit {ran.returncode}: {ran.stderr.strip()[-500:]}"}
    unresolved = (read(out, "unresolved.txt") or "").splitlines()
    dangling = (read(out, "dangling.txt") or "").splitlines()
    started = {name: {"exit": int(read(out, f"{name}.rc") or -1),
                      "log_tail": (read(out, f"{name}.log") or "").splitlines()[-6:]} for name in ("fileinfo", "openmsinfo")}
    problems = ([f"{len(unresolved)} unresolved libraries"] if unresolved else []) + \
               ([f"{len(dangling)} dangling symbolic links"] if dangling else []) + \
               [f"{name} exit {s['exit']}" for name, s in started.items() if s["exit"]]
    return {"status": "failed" if problems else "passed", "problems": problems, "unresolved": unresolved[:50],
            "dangling_links": dangling[:50], "started": started}


def installed(image):
    """installed-checks.py in a copy of the lab's scripts, so that its reports/ and downloads/
    stay apart from this run's own."""
    shutil.rmtree(WORK / "lab", ignore_errors=True)
    lab = WORK / "lab"
    shutil.copytree(ROOT / "scripts", lab / "scripts")
    (lab / "reports").mkdir()
    env = ["-e", "PYTHONUNBUFFERED=1", "-e", "QT_QPA_PLATFORM=offscreen"]
    for name in ("LAB_TOPP_TEST_SELECTION", "GH_TOKEN"):
        if os.environ.get(name):
            env += ["-e", name]  # passed by name, so the value stays out of the process list
    # A sandbox that intercepts TLS with a certificate authority of its own (as an agent's may)
    # names its bundle in these variables; the container gets the bundle and the variables.
    for name in ("SSL_CERT_FILE", "GIT_SSL_CAINFO", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
        bundle = os.environ.get(name)
        if bundle and Path(bundle).is_file():
            env += ["-e", name, "-v", f"{bundle}:{bundle}:ro"]
    ran = docker("run", "--rm", "-v", f"{lab.resolve()}:/lab", *env, "--entrypoint", "bash", image, "-c", INSTALLED,
                 timeout=7200, capture=False)
    target = REPORTS / "container"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(lab / "reports", target)
    checks = json.loads(read(target, "installed-checks.json") or "{}")
    if ran.returncode == 90 or not checks:
        return {"status": "not run", "reason": f"installed-checks.py did not run (exit {ran.returncode}); "
                                               "see reports/container/container-apt.log"}, None
    upstream = json.loads(read(target, "installed-topp-tests.json") or "{}")
    tools = json.loads(read(target, "topp-tools.json") or "{}")
    thermo = checks.get("thermo", {})
    summary = {"status": checks.get("status"), "exit": ran.returncode, "revision": checks.get("commit"),
               "C1_failed_tools": tools.get("failed_tools"), "C1_versions": tools.get("versions_reported"),
               "C2_not_started": tools.get("thirdparty_not_started"),
               "C3": upstream.get("summary"), "C3_not_registered": upstream.get("not_registered"),
               "C5_thermo": {"status": thermo.get("status"), "reason": thermo.get("reason"),
                             **{mode: f"exit {run.get('exit')}, {run.get('spectra')} spectra"
                                for mode, run in thermo.items()
                                if mode in ("default", "inprocess", "symlink") and "exit" in run}},
               "C9_openmp": checks.get("openmp", {}).get("openmp"), "reports": "reports/container/"}
    return summary, upstream.get("package_configuration")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", default=os.environ.get("LAB_CONTAINER_IMAGE")
                        or "ghcr.io/openms/openms-tools-thirdparty:latest")
    parser.add_argument("--expect", default=EXPECT, help=f"build options the image must have (default {EXPECT})")
    parser.add_argument("--report", default=str(REPORTS / "container-checks.json"))
    args = parser.parse_args()
    REPORTS.mkdir(exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    report = {"image": args.image}
    pulled = docker("pull", "-q", args.image, timeout=1800)
    if pulled.returncode:
        report.update(status="not run", reason=f"pull failed: {pulled.stderr.strip()[-500:]}")
    else:
        inspect = json.loads(docker("image", "inspect", args.image).stdout)[0]
        report.update(digest=(inspect.get("RepoDigests") or [None])[0], created=inspect.get("Created"),
                      platform=f"{inspect.get('Os')}/{inspect.get('Architecture')}",
                      labels=inspect.get("Config", {}).get("Labels"))
        report["pristine"] = pristine(args.image)
        report["installed"], configuration = installed(args.image)
        expected = dict(item.split("=", 1) for item in args.expect.split(",") if "=" in item)
        if configuration is None:
            report["options"] = {"status": "not run", "reason": "no C3 report from the image"}
        else:
            differ = {name: {"image": configuration.get(name, {}).get("value"), "installers": value,
                             "evidence": configuration.get(name, {}).get("evidence")}
                      for name, value in expected.items() if configuration.get(name, {}).get("value") != value}
            report["options"] = {"status": "failed" if differ else "passed", "expected": expected, "differ": differ}
        states = [report[k]["status"] for k in ("pristine", "installed", "options")]
        report["status"] = "failed" if "failed" in states else "not run" if "not run" in states else "passed"
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"C10 container image {args.image}: {report['status']}" +
          (f" ({report['reason']})" if report.get("reason") else ""))
    for step in ("pristine", "installed", "options"):
        if step in report:
            print(f"  {step}: {json.dumps(report[step])[:600]}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"### C10 container image\n\n`{report.get('digest') or args.image}`: **{report['status']}**\n\n"
                         + "".join(f"- {s}: `{json.dumps(report[s])[:800]}`\n"
                                   for s in ("pristine", "installed", "options") if s in report))
    return 1 if report["status"] != "passed" else 0


if __name__ == "__main__":
    sys.exit(main())
