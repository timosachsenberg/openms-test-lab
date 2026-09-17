"""Inventory native binaries and dependencies without changing loader search paths."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
MAC = sys.platform == "darwin"
MAGIC = {b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
         b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf"}
inventory = {}
def add(path, owner):
    path = Path(path)
    try:
        if not path.is_file():
            return
        with path.open("rb") as f:
            if f.read(4) not in MAGIC:
                return
        key = str(path.resolve())
        if key in inventory:
            return
        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        inventory[key] = {"path": str(path), "real_path": key, "owner": owner, "sha256": digest, "size": path.stat().st_size}
    except OSError:
        pass

for dist in importlib.metadata.distributions():
    for entry in dist.files or []:
        add(dist.locate_file(entry), dist.metadata["Name"])
package_file = REPORTS / "openms-package.json"
package = json.loads(package_file.read_text()) if package_file.exists() else {}
if package.get("status") == "installed":
    if MAC:
        for location in package["roots"]:
            for path in Path(location).rglob("*"):
                add(path, "OpenMS-desktop")
    else:
        paths = REPORTS / "openms-installed-files.txt"
        for path in paths.read_text().splitlines():
            add(path, "OpenMS-desktop")

details = REPORTS / "native-dependencies.txt"
with details.open("w", encoding="utf-8") as output:
    for key, item in sorted(inventory.items()):
        output.write("\n### " + key + "\n")
        commands = [["otool", "-L", key], ["otool", "-l", key]] if MAC else [["readelf", "-d", key], ["ldd", key]]
        for command in commands:
            run = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            output.write("$ " + " ".join(command) + "\n" + run.stdout)
            if command[0] == "ldd":
                item["unresolved"] = [line.strip() for line in run.stdout.splitlines() if "not found" in line]
                item["resolved_paths"] = re.findall(r"=> (/[^\s]+)", run.stdout)
            elif command[0] == "otool" and command[1] == "-L":
                item["dependencies"] = [line.strip().split(" (compatibility")[0] for line in run.stdout.splitlines()[1:] if line.startswith("\t")]
            elif command[0] == "otool":
                item["rpaths"] = re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset", run.stdout)

def provider(path):
    resolved = str(Path(path).resolve())
    if resolved in inventory:
        return "packaged:" + inventory[resolved]["owner"]
    if "/.venv/" in resolved:
        return "python-environment"
    if resolved.startswith(("/opt/homebrew/", "/usr/local/Cellar/", "/usr/local/opt/")):
        return "preinstalled-homebrew"
    if resolved.startswith(("/System/Library/", "/usr/lib/")) and MAC:
        return "macOS-system"
    if not MAC and resolved.startswith(("/lib/", "/lib64/", "/usr/lib/")):
        return "system-package:see-baseline"
    if resolved.startswith(str(Path(sys.base_prefix).resolve())):
        return "CPython-installation"
    return "other:inspect"

probe_path = REPORTS / "python-probe.json"
probe = json.loads(probe_path.read_text()) if probe_path.exists() else {}
loaded = [{"path": path, "provider": provider(path)} for path in probe.get("loaded_paths", [])]
missing = [{"path": item["path"], "unresolved": item["unresolved"]} for item in inventory.values() if item.get("unresolved")]
summary = {"platform": sys.platform, "binaries": len(inventory), "python_probe": probe.get("status", "not-run"),
           "unresolved_elf_dependencies": missing, "loaded_python_libraries": loaded,
           "limitations": ["Hosted runners include preinstalled libraries; use baseline package lists and actual load paths.",
                           "ELF ldd resolution reflects this runner, not bare Linux.",
                           "Mach-O install names and LC_RPATH are recorded; the static audit does not emulate dyld resolution.",
                           "The Python load trace covers the smoke test; native loader logs cover FileInfo startup.",
                           "GUI plugins, vendor readers, delayed loads and .NET RAW paths need separate functional tests."]}
(REPORTS / "binary-inventory.json").write_text(json.dumps(list(inventory.values()), indent=2) + "\n")
(REPORTS / "dependency-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({"binaries": len(inventory), "unresolved_elf_binaries": len(missing), "python_probe": summary["python_probe"]}, indent=2))
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
        out.write(f"\n## Package diagnostics\n\nNative binaries: {len(inventory)}. Python probe: {summary['python_probe']}. ELF binaries with unresolved dependencies: {len(missing)}.\n\nDownload reports for actual loaded paths, native dependencies, baseline packages and installation logs. A green lab run is a smoke-test result, not a bare-machine certification.\n")
