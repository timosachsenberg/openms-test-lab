"""Start every registered TOPP tool of an installed OpenMS and check what it says about itself.

The desktop smoke test in the labs starts FileInfo only. A release ships ~150 tools, and each
one links its own set of libraries, so a missing runtime dependency or a crash at start-up in
one tool says nothing about the others. This script runs every tool named in the installed
tool registry (share/OpenMS/TOOLS/*.tsv) twice:

  <Tool> --help               must exit 0 and print the version line
  <Tool> -write_ctd <dir>     must exit 0 and write <Tool>.ctd, which must parse as XML
                              and carry the same version as every other tool

It also lists executables that are installed but not registered (the GUI applications and
helpers), and the bundled third-party engines under share/OpenMS/THIRDPARTY, which it starts
with a version or usage flag. Engines are reported, not judged: their exit codes for a usage
request differ, so the JSON records what happened and the release checklist says what to do.

Run it with the installed bin directory on PATH (the labs do), or name the directory:

    python scripts/topp-tools-smoke.py --report reports/topp-tools.json
    python scripts/topp-tools-smoke.py --bin-dir "C:/OpenMS/bin" --share-dir "C:/OpenMS/share/OpenMS"
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

WINDOWS = sys.platform.startswith("win")
EXE = ".exe" if WINDOWS else ""
VERSION_LINE = re.compile(r"^Version:\s*(\S+)", re.MULTILINE)
DOC_URL = re.compile(r"Full documentation:\s*(\S+)")
# GUI applications ship next to the tools but are not in the registry; starting them needs a
# display, so they are only listed. Anything else unregistered is worth a look.
KNOWN_UNREGISTERED = {"TOPPView", "TOPPAS", "INIFileEditor", "SwathWizard", "FLASHDeconvWizard"}
# A shared bin directory holds the whole system; only a private one (C:/OpenMS/bin, the
# macOS bundle) can be listed without a package file list.
SYSTEM_BIN_DIRS = {"/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin"}
# Which file starts each bundled engine; the folder names are the ones share/OpenMS/THIRDPARTY uses.
ENGINE_FILES = {
    "Comet": ["comet.exe", "comet"], "Sage": ["sage.exe", "sage"],
    "Percolator": ["percolator.exe", "percolator"], "MaRaCluster": ["maracluster.exe", "maracluster"],
    "SpectraST": ["spectrast.exe", "spectrast"], "XTandem": ["tandem.exe", "tandem"],
    "MSGFPlus": ["MSGFPlus.jar"], "LuciPHOr2": ["luciphor2.jar"],
    "MSFragger": [],  # license forbids redistribution; the folder carries only its license
    "pwiz-bin": ["msconvert.exe", "msconvert"],  # ProteoWizard, Windows installer only
}
# Text a dynamic loader prints when an executable cannot start at all.
LOADER_FAILURE = re.compile(r"error while loading shared libraries|cannot execute binary file|"
                            r"Library not loaded|dyld\[\d+\]|was not found|Exec format error|"
                            r"is not a valid Win32 application|0xc000007b", re.I)


def find_bin_dir(explicit):
    if explicit:
        return Path(explicit)
    found = shutil.which("FileInfo")
    if not found:
        raise SystemExit("FileInfo is not on PATH; pass --bin-dir")
    return Path(found).resolve().parent


def find_share_dir(explicit, bin_dir):
    candidates = [explicit, os.environ.get("OPENMS_DATA_PATH"),
                  bin_dir.parent / "share" / "OpenMS", Path("/usr/share/OpenMS"),
                  bin_dir.parent / "Resources" / "share" / "OpenMS"]
    for candidate in candidates:
        if candidate and (Path(candidate) / "TOOLS").is_dir():
            return Path(candidate)
    raise SystemExit("No share/OpenMS/TOOLS directory found; pass --share-dir")


def read_registry(share_dir):
    tools = {}
    for tsv in sorted((share_dir / "TOOLS").glob("*.tsv")):
        for line in tsv.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, _, category = line.partition("\t")
            tools[name.strip()] = {"category": category.strip(), "registry": tsv.name}
    return tools


def run(command, timeout, cwd=None):
    started = time.monotonic()
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, errors="replace",
                                   timeout=timeout, cwd=cwd, env=env, stdin=subprocess.DEVNULL)
        return {"exit": completed.returncode, "seconds": round(time.monotonic() - started, 2),
                "stdout": completed.stdout, "stderr": completed.stderr}
    except subprocess.TimeoutExpired as error:
        return {"exit": None, "timeout": True, "seconds": timeout,
                "stdout": error.stdout or "", "stderr": error.stderr or ""}
    except OSError as error:
        return {"exit": None, "error": str(error), "seconds": 0, "stdout": "", "stderr": ""}


def tail(text, lines=15):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return "\n".join(text.strip().splitlines()[-lines:])


def check_tool(name, bin_dir, ctd_root, timeout):
    exe = bin_dir / f"{name}{EXE}"
    result = {"tool": name, "executable": str(exe), "problems": []}
    if not exe.is_file():
        result["problems"].append("registered but not installed")
        return result
    help_run = run([str(exe), "--help"], timeout)
    output = help_run["stdout"] + help_run["stderr"]
    version = VERSION_LINE.search(output)
    doc_url = DOC_URL.search(output)
    result.update(help_exit=help_run["exit"], help_seconds=help_run["seconds"],
                  version=version.group(1) if version else None,
                  doc_url=doc_url.group(1) if doc_url else None)
    if help_run["exit"] != 0:
        result["problems"].append(f"--help exited {help_run['exit']}")
        result["help_tail"] = tail(output)
    if not version:
        result["problems"].append("--help printed no 'Version:' line")
    # TOPP tools print their help on stderr, so stderr itself is expected. What is not
    # expected is text from something else, e.g. a shell helper complaining about a
    # missing terminal, which then ends up in every workflow engine's log.
    foreign = [line for line in help_run["stderr"].splitlines()
               if re.match(r"^(stty|sh|tput|which):", line.strip())]
    if foreign:
        result["foreign_stderr"] = foreign[:3]

    ctd_dir = ctd_root / name
    ctd_dir.mkdir(parents=True, exist_ok=True)
    ctd_run = run([str(exe), "-write_ctd", str(ctd_dir)], timeout)
    result.update(ctd_exit=ctd_run["exit"], ctd_seconds=ctd_run["seconds"])
    ctd = ctd_dir / f"{name}.ctd"
    if ctd_run["exit"] != 0:
        result["problems"].append(f"-write_ctd exited {ctd_run['exit']}")
        result["ctd_tail"] = tail(ctd_run["stdout"] + ctd_run["stderr"])
    elif not ctd.is_file():
        result["problems"].append("-write_ctd wrote no .ctd file")
    else:
        try:
            # CTD 1.7 keeps version, category and docurl as attributes of <tool>.
            tool = ET.parse(ctd).getroot()
            result["ctd_version"] = tool.get("version")
            result["ctd_category"] = tool.get("category") or (tool.findtext("category") or "").strip()
            result["ctd_docurl"] = tool.get("docurl") or (tool.findtext("docurl") or "").strip()
            if not result["ctd_category"]:
                result["problems"].append("CTD has an empty category")
        except ET.ParseError as error:
            result["problems"].append(f"CTD does not parse: {error}")
    return result


def check_thirdparty(share_dir, timeout):
    """Start each bundled engine once; record what happened."""
    root = share_dir / "THIRDPARTY"
    java = shutil.which("java")
    probes = []
    scratch = tempfile.mkdtemp(prefix="engines-")  # some engines write a log into the working directory
    if not root.is_dir():
        return probes
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        files = {p.name: p for p in folder.iterdir() if p.is_file()}
        entry = {"folder": folder.name, "files": sorted(files)[:40]}
        payload = next((files[n] for n in ENGINE_FILES.get(folder.name, []) if n in files), None)
        if folder.name == "ThermoRawFileParser":
            entry["note"] = "needs a .NET runtime; exercised by the Thermo .raw conversion check instead"
        elif payload is None:
            entry["note"] = ("no executable payload (documentation or license only)"
                             if folder.name in ENGINE_FILES or not files else "unknown engine folder")
        else:
            if payload.suffix == ".jar":
                if not java:
                    entry.update(executable=payload.name, started=None, note="no java on PATH")
                    probes.append(entry)
                    continue
                attempt = run([java, "-jar", str(payload)], timeout, cwd=scratch)
            else:
                # Engines disagree on how to ask for a version, and several exit non-zero
                # after printing it; what matters here is that the loader started them.
                for flag in ("--version", "--help", None):
                    attempt = run([str(payload)] + ([flag] if flag else []), timeout, cwd=scratch)
                    if attempt["stdout"].strip() or attempt["stderr"].strip():
                        break
            text = (attempt["stdout"] + attempt["stderr"]).strip()
            banner = next((line for line in text.splitlines()
                           if re.search(r"version|release|X! TANDEM|usage|ProteoWizard", line, re.I)),
                          text.splitlines()[0] if text else "")
            entry.update(executable=payload.name, exit=attempt["exit"],
                         banner=banner.replace("Exception caught: ", "").strip()[:160],
                         started=bool(text) and attempt["exit"] is not None and not LOADER_FAILURE.search(text))
            if not entry["started"]:
                entry["output_tail"] = tail(text)
        probes.append(entry)
    shutil.rmtree(scratch, ignore_errors=True)
    return probes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bin-dir")
    parser.add_argument("--share-dir")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--expected-version", help="fail if a tool reports a different version")
    parser.add_argument("--package-files", help="file listing the package's installed paths "
                        "(dpkg -L openms, pkgutil --files ...); needed to find unregistered "
                        "executables when the tools live in a shared directory such as /usr/bin")
    parser.add_argument("--report", default="reports/topp-tools.json")
    args = parser.parse_args()

    bin_dir = find_bin_dir(args.bin_dir)
    share_dir = find_share_dir(args.share_dir, bin_dir)
    registry = read_registry(share_dir)
    ctd_root = Path(tempfile.mkdtemp(prefix="topp-ctd-"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda name: check_tool(name, bin_dir, ctd_root, args.timeout),
                                sorted(registry)))
    for result in results:
        result.update(registry[result["tool"]])

    versions = sorted({r.get("version") for r in results if r.get("version")})
    expected = args.expected_version or (versions[0] if len(versions) == 1 else None)
    for result in results:
        if expected and result.get("version") and result["version"] != expected:
            result["problems"].append(f"reports version {result['version']}, expected {expected}")
        if result.get("ctd_version") and expected and not expected.startswith(result["ctd_version"]):
            result["problems"].append(f"CTD version {result['ctd_version']} does not match {expected}")

    if args.package_files:
        listed = [Path(line.strip()) for line in
                  Path(args.package_files).read_text(encoding="utf-8").splitlines() if line.strip()]
        installed = {p.stem for p in listed if p.parent == bin_dir and (bin_dir / p.name).is_file()}
    elif str(bin_dir) in SYSTEM_BIN_DIRS:
        installed = None
    else:
        installed = {p.stem for p in bin_dir.iterdir()
                     if p.is_file() and (p.suffix.lower() == ".exe" if WINDOWS else os.access(p, os.X_OK))}
    unregistered = sorted(installed - set(registry)) if installed is not None else []
    thirdparty = check_thirdparty(share_dir, min(args.timeout, 60))
    failed = [r for r in results if r["problems"]]
    engines_not_started = [p["folder"] for p in thirdparty if p.get("started") is False]
    report = {
        "platform": platform.platform(),
        "bin_dir": str(bin_dir),
        "share_dir": str(share_dir),
        "registered_tools": len(registry),
        "versions_reported": versions,
        "failed_tools": [r["tool"] for r in failed],
        "tools_with_foreign_stderr": [r["tool"] for r in results if r.get("foreign_stderr")],
        "unregistered_executables": (
            {"gui_applications": [n for n in unregistered if n in KNOWN_UNREGISTERED],
             "other": [n for n in unregistered if n not in KNOWN_UNREGISTERED]}
            if installed is not None else "not listed: shared bin directory, pass --package-files"),
        "thirdparty": thirdparty,
        "thirdparty_not_started": engines_not_started,
        "tools": results,
        "status": "passed" if not failed and len(versions) == 1 and not engines_not_started else "failed",
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    shutil.rmtree(ctd_root, ignore_errors=True)

    print(f"{len(registry)} registered tools, {len(failed)} with problems; versions reported: {versions}")
    for result in failed:
        print(f"  {result['tool']}: {'; '.join(result['problems'])}")
    if report["tools_with_foreign_stderr"]:
        sample = next(r["foreign_stderr"][0] for r in results if r.get("foreign_stderr"))
        print(f"{len(report['tools_with_foreign_stderr'])} tools write foreign text to stderr, e.g. {sample!r}")
    print(f"unregistered executables: {report['unregistered_executables']}")
    for probe in report["thirdparty"]:
        state = {True: "started", False: "DID NOT START", None: "not run"}[probe.get("started")]
        print(f"  THIRDPARTY/{probe['folder']}: {state} {probe.get('banner') or probe.get('note', '')}".rstrip())
    print(f"status: {report['status']}; report: {report_path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
