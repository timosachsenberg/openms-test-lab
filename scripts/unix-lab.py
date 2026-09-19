"""Package setup and evidence collection for disposable macOS/Linux runners."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import venv
import zipfile

import resolve_nightly

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOWNLOADS = ROOT / "downloads"
EXPORTS = ROOT / "exports"
API = "https://api.github.com/repos/OpenMS/OpenMS"
MAC = sys.platform == "darwin"
ARM = platform.machine().lower() in {"arm64", "aarch64"}

def write(name, value):
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()

def run(args, log=None, check=True, env=None):
    print("+", " ".join(map(str, args)), flush=True)
    env = (env or os.environ).copy()
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    result = subprocess.run(list(map(str, args)), cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log:
        (REPORTS / log).write_text(result.stdout, encoding="utf-8")
    print(result.stdout[-12000:], flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0]}; see {log}")
    return result

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected

def request(url, authenticated=False):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS downloads are supported")
    headers = {"User-Agent": "OpenMS-package-lab", "Accept": "application/vnd.github+json"}
    if authenticated:
        if urllib.parse.urlsplit(url).netloc != "api.github.com":
            raise ValueError("GitHub credentials are restricted to api.github.com")
        if os.environ.get("GH_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    return urllib.request.build_opener(Redirect()).open(urllib.request.Request(url, headers=headers), timeout=120)

def api(path):
    with request(API + path, authenticated=True) as response:
        return json.load(response)

def download(url, destination, expected=None, authenticated=False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with request(url, authenticated) as response, destination.open("wb") as target:
        shutil.copyfileobj(response, target)
    digest = sha(destination)
    if expected and digest != expected.removeprefix("sha256:"):
        raise RuntimeError(f"Checksum mismatch for {destination.name}")
    return digest

def clean_env():
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("DYLD_", "LD_", "PYTHON", "OPENMS_", "QT_")) or key in {"GH_TOKEN", "GITHUB_TOKEN"}:
            env.pop(key, None)
    env["PATH"] = os.pathsep.join([str(ROOT / ".venv/bin"), str(Path(sys.executable).parent),
                                  "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    env["QT_QPA_PLATFORM"] = "offscreen"
    return env

def baseline(label):
    info = {"platform": platform.platform(), "machine": platform.machine(),
            "image": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion"),
            "path": os.environ.get("PATH"), "python": sys.version}
    commands = {"dotnet": ["dotnet", "--list-runtimes"]}
    if MAC:
        commands.update({"os": ["sw_vers"], "packages": ["pkgutil", "--pkgs"],
                         "homebrew": ["brew", "list", "--versions"], "xcode": ["xcodebuild", "-version"]})
    else:
        commands.update({"packages": ["dpkg-query", "-W"],
                         "loader_cache": ["/sbin/ldconfig", "-p"],
                         "libc": ["getconf", "GNU_LIBC_VERSION"]})
    for name, args in commands.items():
        if shutil.which(args[0]):
            result = run(args, f"{label}-{name}.txt", check=False)
            info[name] = {"exit_code": result.returncode, "report": f"{label}-{name}.txt"}
    write(f"{label}.json", info)

def upstream_wheel(run_id):
    if not run_id.isdigit() or int(run_id) < 1:
        raise ValueError("wheel_run_id must be a positive upstream Actions run ID")
    build = api(f"/actions/runs/{run_id}")
    if build["path"].split("@")[0] != ".github/workflows/pyopenms-wheels-cibuildwheel.yml":
        raise ValueError("Expected the OpenMS pyopenms-wheels-cibuildwheel workflow")
    if build["status"] != "completed":
        raise ValueError("Upstream wheel run must be completed")
    artifact_name = "wheels-" + ("macos" if MAC else "linux") + ("-arm64" if ARM else "-x64")
    artifacts = api(f"/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    matches = [item for item in artifacts if item["name"] == artifact_name and not item["expired"]]
    if len(matches) != 1:
        raise ValueError(f"Expected one unexpired {artifact_name} artifact; found {len(matches)}. macOS Intel may need a PyPI wheel or direct URL.")
    artifact = matches[0]
    if not artifact.get("digest"):
        raise ValueError("Upstream artifact has no SHA-256 digest")
    archive = DOWNLOADS / "upstream-wheel.zip"
    digest = download(artifact["archive_download_url"], archive, artifact["digest"], authenticated=True)
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import parse_wheel_filename
    supported = list(sys_tags())
    selected = []
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not name.endswith(".whl"):
                continue
            filename = Path(name).name
            _, _, _, tags = parse_wheel_filename(filename)
            ranks = [supported.index(tag) for tag in tags if tag in supported]
            if ranks:
                selected.append((min(ranks), name))
        if not selected:
            raise ValueError("No upstream wheel supports this runner architecture and Python")
        _, member = sorted(selected)[0]
        wheel = DOWNLOADS / Path(member).name
        with bundle.open(member) as source, wheel.open("wb") as target:
            shutil.copyfileobj(source, target)
    source = {"upstream_run": build["html_url"], "head_sha": build["head_sha"],
              "upstream_conclusion": build["conclusion"],
              "head_branch": build["head_branch"], "event": build["event"],
              "pull_requests": build.get("pull_requests", []), "artifact": artifact_name,
              "artifact_id": artifact["id"], "artifact_sha256": digest,
              "wheel": wheel.name, "wheel_sha256": sha(wheel),
              "note": "For pull_request runs, head_sha is the PR head; the upstream checkout may be a generated merge commit."}
    write("wheel-source.json", source)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write(f"\n## Upstream wheel\n\nRun: {build['html_url']}\n\nUpstream conclusion: **{build['conclusion']}**. This lab tests the selected artifact independently; an available wheel does not imply all upstream tests passed.\n")
    shutil.copy2(wheel, EXPORTS / wheel.name)
    shutil.copy2(REPORTS / "wheel-source.json", EXPORTS / "wheel-source.json")
    return str(wheel)

def setup():
    venv.create(ROOT / ".venv", with_pip=True)
    python = ROOT / ".venv/bin/python"
    run([python, "-m", "pip", "install", "--upgrade", "pip"], "pip-upgrade.log")
    spec = os.environ.get("LAB_PYOPENMS_SPEC", "pyopenms").strip()
    if os.environ.get("LAB_WHEEL_RUN_ID", "").strip():
        spec = upstream_wheel(os.environ["LAB_WHEEL_RUN_ID"].strip())
    if spec.lower() == "none":
        spec = ""
    nightly = None
    if spec.lower() == "nightly":
        nightly = resolve_nightly.wheel()
        # pip verifies the index's sha256 fragment carried on this URL.
        spec = nightly["url"]
    write("python-selection.json", {"pyopenms_spec": spec, "nightly": nightly})
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as out:
            if "\n" in spec or "\r" in spec:
                raise ValueError("Package requirement must be a single line")
            out.write(f"LAB_PYOPENMS_SPEC={spec}\n")
    requirements = [item.strip() for item in os.environ.get("LAB_EXTRA_PACKAGES", "").split(";") if item.strip()]
    if spec:
        requirements.insert(0, spec)
    if any(item.startswith("-") for item in requirements):
        raise ValueError("Package inputs must be requirements, not pip options")
    persistent = ROOT / "requirements.txt"
    args = [python, "-m", "pip", "install", "--only-binary=:all:", "--report", REPORTS / "pip-install.json"]
    if persistent.exists():
        args.extend(["-r", persistent])
    args.extend(requirements)
    run(args, "pip-install.log")
    run([python, "-m", "pip", "freeze", "--all"], "requirements-lock.txt")
    run([python, "-m", "pip", "debug", "--verbose"], "pip-debug.txt")
    run([python, "-m", "pip", "check"], "pip-check.txt")

def python_test():
    run([ROOT / ".venv/bin/python", ROOT / "scripts/unix-probe.py"],
        "python-smoke.log", env=clean_env())

def native():
    selection = os.environ.get("LAB_OPENMS_PACKAGE", "latest").strip()
    if selection.lower() in {"", "none"}:
        write("openms-package.json", {"status": "skipped"})
        return
    expected = None
    release_tag = None
    nightly = None
    if selection.lower() == "nightly":
        nightly = resolve_nightly.desktop()
        url = nightly["url"]
    elif selection.startswith("https://"):
        url = selection
    else:
        release = api("/releases/latest" if selection == "latest" else "/releases/tags/" + urllib.parse.quote(selection, safe=""))
        release_tag = release["tag_name"]
        suffix = ("-macOS-Silicon.pkg" if ARM else "-macOS-Intel.pkg") if MAC else ("-Linux-aarch64.deb" if ARM else "-Linux-x86_64.deb")
        assets = [a for a in release["assets"] if a["name"].endswith(suffix)]
        if len(assets) != 1:
            raise ValueError(f"Expected one release asset ending {suffix}; got {len(assets)}")
        url, expected = assets[0]["browser_download_url"], assets[0].get("digest")
    filename = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name
    if not filename.endswith(".pkg" if MAC else ".deb"):
        raise ValueError("macOS requires a PKG URL; Linux requires a DEB URL")
    package = DOWNLOADS / filename
    digest = download(url, package, expected)
    record = {"status": "downloaded", "url": url, "release": release_tag, "sha256": digest,
              "expected_digest": expected, "digest_verified": bool(expected), "file": filename,
              "nightly": nightly}
    write("openms-package.json", record)
    if MAC:
        run(["sudo", "installer", "-pkg", package, "-target", "/"], "openms-install.log")
        roots = sorted(Path("/Applications").glob("OpenMS*"))
        candidates = [p for root in roots for p in root.rglob("FileInfo") if p.is_file() and p.parent.name == "bin"]
    else:
        name = run(["dpkg-deb", "-f", package, "Package"], "openms-deb-name.txt").stdout.strip()
        run(["sudo", "apt-get", "update"], "apt-update.log")
        run(["sudo", "apt-get", "install", "-y", "--no-install-recommends", package], "openms-install.log")
        paths = run(["dpkg-query", "-L", name], "openms-installed-files.txt").stdout.splitlines()
        candidates = [Path(p) for p in paths if Path(p).name == "FileInfo" and Path(p).is_file()]
        roots = sorted({p.parent.parent for p in candidates})
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one installed FileInfo; found {candidates}")
    binary = candidates[0]
    record.update(status="installed", executable=str(binary), roots=[str(p) for p in roots])
    write("openms-package.json", record)
    (REPORTS / "openms-bin.txt").write_text(str(binary.parent), encoding="utf-8")
    env = clean_env()
    env["PATH"] = str(binary.parent) + os.pathsep + env["PATH"]
    if MAC:
        env["DYLD_PRINT_LIBRARIES"] = "1"
    else:
        env["LD_DEBUG"] = "libs"
    result = run([binary, "--help"], "native-loader.log", env=env, check=False)
    write("native-smoke.json", {"executable": str(binary), "help_exit_code": result.returncode,
                               "loader_trace": "native-loader.log",
                               "note": "macOS hardened executables may ignore DYLD tracing; empty traces are not proof of isolation."})
    if result.returncode:
        raise RuntimeError("Installed FileInfo failed; inspect native-loader.log")
    if (REPORTS / "smoke.mzML").exists():
        run([binary, "-in", REPORTS / "smoke.mzML"], "native-mzml.log", env=clean_env())

def diagnostics():
    run([ROOT / ".venv/bin/python", ROOT / "scripts/unix-audit.py"], "audit.log", env=clean_env())

def export():
    python = ROOT / ".venv/bin/python"
    lock = run([python, "-m", "pip", "freeze"], "export-requirements.txt").stdout
    (EXPORTS / "requirements-lock.txt").write_text(lock, encoding="utf-8")
    run([python, "-m", "pip", "download", "--only-binary=:all:", "-r",
         EXPORTS / "requirements-lock.txt", "--dest", EXPORTS / "wheelhouse"], "export-wheels.log")

if __name__ == "__main__":
    os.chdir(ROOT)
    for folder in (REPORTS, DOWNLOADS, EXPORTS):
        folder.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline-before", "baseline-python", "baseline-after", "setup", "python", "native", "diagnostics", "export"])
    phase = parser.parse_args().phase
    if phase.startswith("baseline-"):
        baseline(phase)
    else:
        {"setup": setup, "python": python_test, "native": native, "diagnostics": diagnostics, "export": export}[phase]()
