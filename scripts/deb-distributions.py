"""C6: install the DEB on every distribution the documentation names, in clean containers.

The Linux labs install the DEB on the runner, which is Ubuntu 24.04: the distribution the
package is built on, and so the one where the dependency names dpkg-shlibdeps writes are
sure to exist. The installation page (doc/openms/docs/about/installation/
installation-on-gnu-linux.md) also promises Ubuntu 26.04 and Debian 13, where several of
those libraries carry other package names after the 64-bit time_t transition (3.6.0 did not
install there, OpenMS/OpenMS#10351), and it says that Ubuntu 22.04 and Debian 12 are refused
for their older glibc. This script checks both directions, each in a fresh container:

  installs  apt-get installs the DEB with its dependencies; every ELF file of the package
            resolves its shared libraries (ldd), no symbolic link of the package dangles,
            and FileInfo --help, OpenMSInfo and TOPPView --help exit 0
  refused   apt-get refuses the DEB for an unmet dependency instead of installing a
            package that cannot run

    python3 scripts/deb-distributions.py                     # the DEB this lab run installed
    python3 scripts/deb-distributions.py --deb x.deb --installs ubuntu:24.04,debian:13 --refused ubuntu:22.04

Images are pulled from Docker Hub, or from its mirror on mirror.gcr.io when Docker Hub
refuses (its rate limit for anonymous pulls); the report records the digest of each. The
DEB is mounted read-only; nothing outside the containers changes. Exits 1 when a
distribution fails or a check could not run although a DEB was there.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOWNLOADS = ROOT / "downloads"
# Keep in step with installation-on-gnu-linux.md of the candidate's revision.
INSTALLS = "ubuntu:24.04,ubuntu:26.04,debian:13"
REFUSED = "ubuntu:22.04,debian:12"

# Runs inside the container as root. Every result goes to a file under /out.
CONTAINER_SCRIPT = r"""
set -u
export DEBIAN_FRONTEND=noninteractive
cd /out
. /etc/os-release
printf '%s\n' "$PRETTY_NAME" > os.txt
ldd --version 2>&1 | head -n 1 > glibc.txt
apt-get update > apt-update.log 2>&1
echo $? > apt-update.rc
apt-get install -y --no-install-recommends "/pkg/$DEB" > install.log 2>&1
echo $? > install.rc
[ "$(cat install.rc)" = 0 ] || exit 0
dpkg-query -W -f '${Package} ${Version}\n' | grep -E '^libqt6(core|gui|widgets)6' > qt.txt
dpkg -L "$(dpkg-deb -f "/pkg/$DEB" Package)" > files.txt
: > unresolved.txt
: > dangling.txt
case $(uname -m) in x86_64) rid=linux-x64;; aarch64) rid=linux-arm64;; *) rid=none;; esac
while IFS= read -r f; do
  if [ -L "$f" ]; then
    [ -e "$f" ] || printf '%s -> %s\n' "$f" "$(readlink "$f")" >> dangling.txt
    continue
  fi
  [ -f "$f" ] || continue
  # .NET applications carry native libraries for every platform under runtimes/<platform>/
  case "$f" in */runtimes/*/*) r=${f#*/runtimes/}; [ "${r%%/*}" = "$rid" ] || continue;; esac
  [ "$(head -c 4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ] || continue
  ldd "$f" 2>&1 | grep 'not found' | sed "s|^|$f: |" >> unresolved.txt
done < files.txt
run() {  # run <name> <command...>: exit code to <name>.rc, output to <name>.log
  name=$1; shift
  QT_QPA_PLATFORM=offscreen timeout 300 "$@" > "$name.log" 2>&1 < /dev/null
  echo $? > "$name.rc"
}
command -v FileInfo > /dev/null && run fileinfo FileInfo --help
command -v OpenMSInfo > /dev/null && run openmsinfo OpenMSInfo
command -v TOPPView > /dev/null && run toppview TOPPView --help
exit 0
"""


def docker(*args, timeout=600):
    return subprocess.run(["docker", *args], capture_output=True, text=True, errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout)


def mirror(image):
    """The image on Google's Docker Hub mirror, for an image of Docker Hub."""
    first = image.split("/")[0]
    if "/" in image and ("." in first or ":" in first or first == "localhost"):
        return None  # another registry
    return "mirror.gcr.io/" + (image if "/" in image else "library/" + image)


def pull(image):
    errors = []
    for reference in filter(None, (image, mirror(image))):
        for _ in range(2):
            pulled = docker("pull", "-q", reference)
            if pulled.returncode == 0:
                digest = docker("image", "inspect", "--format", "{{index .RepoDigests 0}}", reference).stdout.strip()
                return reference, digest, errors
            errors.append(f"{reference}: {pulled.stderr.strip().splitlines()[-1:] or pulled.returncode}")
    return None, None, errors


def read(folder, name):
    path = folder / name
    return path.read_text(encoding="utf-8", errors="replace").strip() if path.exists() else None


def lines(folder, name):
    text = read(folder, name)
    return text.splitlines() if text else []


def check(image, mode, deb):
    """One distribution in one container; mode is "installs" or "refused"."""
    result = {"image": image, "expect": mode}
    reference, digest, errors = pull(image)
    if not reference:
        return dict(result, status="not run", reason="pull failed: " + "; ".join(errors))
    result.update(reference=reference, digest=digest)
    out = REPORTS / "deb-distributions" / re.sub(r"[^A-Za-z0-9._-]+", "-", image)
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    try:
        ran = docker("run", "--rm", "-v", f"{deb.parent.resolve()}:/pkg:ro", "-v", f"{out.resolve()}:/out",
                     "-e", f"DEB={deb.name}", reference, "bash", "-c", CONTAINER_SCRIPT, timeout=1800)
    except subprocess.TimeoutExpired:
        return dict(result, status="not run", reason="container timed out after 30 minutes")
    result.update(os=read(out, "os.txt"), glibc=read(out, "glibc.txt"), logs=str(out.relative_to(ROOT)))
    if ran.returncode or read(out, "apt-update.rc") != "0":
        return dict(result, status="not run", reason=f"container exit {ran.returncode}, apt-get update exit "
                                                     f"{read(out, 'apt-update.rc')}: {ran.stderr.strip()[-500:]}")
    install_log = lines(out, "install.log")
    installed = read(out, "install.rc") == "0"
    result["install_exit"] = int(read(out, "install.rc") or -1)
    if mode == "refused":
        # apt-get explains an unmet dependency with lines such as
        # " openms : Depends: libc6 (>= 2.38) but 2.35-0ubuntu3 is to be installed"
        reasons = [l.strip() for l in install_log if "Depends:" in l or "not installable" in l]
        if installed:
            return dict(result, status="failed", reason="installs, although the documentation says it is refused")
        if not reasons:
            return dict(result, status="not run", reason="apt-get failed without naming a dependency",
                        log_tail=install_log[-12:])
        return dict(result, status="passed", refused_for=reasons[:12])
    if not installed:
        return dict(result, status="failed", reason="apt-get install failed",
                    unmet=[l.strip() for l in install_log if "Depends:" in l or "not installable" in l][:20],
                    log_tail=install_log[-12:])
    unresolved, dangling = lines(out, "unresolved.txt"), lines(out, "dangling.txt")
    started = {}
    for name in ("fileinfo", "openmsinfo", "toppview"):
        if read(out, f"{name}.rc") is not None:
            started[name] = {"exit": int(read(out, f"{name}.rc")), "log_tail": lines(out, f"{name}.log")[-6:]}
    result.update(qt=lines(out, "qt.txt"), files=len(lines(out, "files.txt")), unresolved=unresolved[:50],
                  dangling_links=dangling[:50], started=started)
    problems = []
    if unresolved:
        problems.append(f"{len(unresolved)} unresolved libraries")
    if dangling:
        problems.append(f"{len(dangling)} dangling symbolic links")
    if "fileinfo" not in started:
        problems.append("FileInfo not on PATH")
    problems += [f"{name} exit {s['exit']}" for name, s in started.items() if s["exit"]]
    return dict(result, status="failed" if problems else "passed", problems=problems)


def find_deb(explicit):
    if explicit:
        return Path(explicit)
    record = REPORTS / "openms-package.json"
    if record.exists():
        data = json.loads(record.read_text(encoding="utf-8"))
        if data.get("status") == "installed" and str(data.get("file", "")).endswith(".deb"):
            return DOWNLOADS / data["file"]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deb", help="the DEB to test; default: the one reports/openms-package.json names")
    parser.add_argument("--installs", default=os.environ.get("LAB_DEB_INSTALLS") or INSTALLS,
                        help=f"comma-separated images the DEB must install on (default {INSTALLS})")
    parser.add_argument("--refused", default=os.environ.get("LAB_DEB_REFUSED") or REFUSED,
                        help=f"comma-separated images that must refuse it (default {REFUSED}); 'none' for none")
    parser.add_argument("--report", default=str(REPORTS / "deb-distributions.json"))
    args = parser.parse_args()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    deb = find_deb(args.deb)
    if deb is None:
        report = {"status": "skipped", "reason": "no DEB was installed in this run"}
    elif not deb.is_file():
        report = {"status": "not run", "reason": f"{deb} does not exist"}
    elif not shutil.which("docker") or docker("info", timeout=60).returncode:
        report = {"status": "not run", "deb": deb.name, "reason": "no usable docker on this machine"}
    else:
        with deb.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        fields = {}
        if shutil.which("dpkg-deb"):
            for field in ("Package", "Version", "Architecture", "Depends"):
                fields[field.lower()] = subprocess.run(["dpkg-deb", "-f", str(deb), field], capture_output=True,
                                                       text=True).stdout.strip()
        split = lambda value: [i.strip() for i in value.split(",") if i.strip() and i.strip().lower() != "none"]
        results = [check(image, "installs", deb) for image in split(args.installs)]
        results += [check(image, "refused", deb) for image in split(args.refused)]
        states = {r["status"] for r in results}
        status = "failed" if "failed" in states else "not run" if "not run" in states or not results else "passed"
        report = {"status": status, "deb": deb.name, "sha256": digest, **fields, "distributions": results}
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"C6 DEB on every documented distribution: {report['status']}" +
          (f" ({report['reason']})" if report.get("reason") else ""))
    for r in report.get("distributions", []):
        detail = r.get("reason") or "; ".join(r.get("problems") or r.get("refused_for", [])[:1]) or "ok"
        print(f"  {r['status']:8} {r['expect']:8} {r['image']:14} {r.get('os') or ''}: {detail}")
    return 1 if report["status"] in ("failed", "not run") else 0


if __name__ == "__main__":
    sys.exit(main())
