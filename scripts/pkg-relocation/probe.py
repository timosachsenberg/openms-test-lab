#!/usr/bin/env python3
"""Checks whether the OpenMS macOS pkg lets the installer relocate the app bundles.

The packages hold three stand-in app bundles (de.openms.INIFileEditor, de.openms.TOPPAS,
de.openms.TOPPView) and are built with the packaging files of an OpenMS checkout (see
CMakeLists.txt here). pkgbuild lists the bundles that the installer may relocate under
<relocate> in the PackageInfo of a component; the installer then updates a bundle with the same
identifier wherever it finds one instead of installing into the folder of the new version.

  build    old (3.6.0) and control (3.7.0) without the component plist, as the packages before
           the fix; fixed (3.7.1) with the component plist of the OpenMS checkout
  inspect  reads the PackageInfo of each Applications component. Fails if fixed lists a
           bundle under <relocate>, or if control does not list all three (then the probe
           could not see the bug)
  install  installs old, control and fixed in that order and records where the bundles land.
           Fails if the bundles of fixed are not in its own folder

Environment: OPENMS_SOURCE_DIR (default <workspace>/openms), PROBE_OUT (default
<workspace>/probe-out).
"""
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE = pathlib.Path(os.environ.get("GITHUB_WORKSPACE", HERE.parents[1]))
OPENMS = pathlib.Path(os.environ.get("OPENMS_SOURCE_DIR", WORKSPACE / "openms"))
OUT = pathlib.Path(os.environ.get("PROBE_OUT", WORKSPACE / "probe-out"))
WORK = pathlib.Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "pkg-relocation"
APPS = ["INIFileEditor", "TOPPAS", "TOPPView"]
BUNDLE_IDS = sorted(f"de.openms.{app}" for app in APPS)
## name, numeric version, whether pkgbuild gets the component plist
PROBES = [("old", "3.6.0", False), ("control", "3.7.0", False), ("fixed", "3.7.1", True)]
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
              "LaunchServices.framework/Support/lsregister")
INSTALL_LOG = pathlib.Path("/var/log/install.log")


def run(cmd, check=True, **kwargs):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=check, **kwargs)


def summary(text=""):
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def folder(name, version):
    return pathlib.Path("/Applications") / f"OpenMS-{version}-probe-{name}"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, version, plist in PROBES:
        build_dir = WORK / f"build-{name}"
        shutil.rmtree(build_dir, ignore_errors=True)
        run(["cmake", "-S", HERE, "-B", build_dir, f"-DOPENMS_SOURCE_DIR={OPENMS}",
             f"-DPROBE_VERSION={version}", f"-DPROBE_SUFFIX=probe-{name}",
             f"-DPROBE_WITHOUT_PLIST={'OFF' if plist else 'ON'}"])
        run(["cmake", "--build", build_dir])
        run(["cpack", "-G", "productbuild"], cwd=build_dir)
        packages = sorted(build_dir.glob("OpenMS-*.pkg"))
        if len(packages) != 1:
            sys.exit(f"{name}: expected one package in {build_dir}, found {packages}")
        shutil.copy(packages[0], OUT / f"{name}.pkg")
        config = (build_dir / "CPackConfig.cmake").read_text(encoding="utf-8")
        match = re.search(r'set\(CPACK_COMPONENT_APPLICATIONS_PLIST "([^"]*)"\)', config)
        print(f"{name}: CPACK_COMPONENT_APPLICATIONS_PLIST = {match.group(1) if match else '(not set)'}")
        if bool(match) != plist:
            sys.exit(f"{name}: CPackConfig.cmake {'lacks' if plist else 'has'} the component plist")
        if match:
            shutil.copy(match.group(1), OUT / f"{name}-ApplicationsComponent.plist")
            print(pathlib.Path(match.group(1)).read_text(encoding="utf-8"))


def package_info(name):
    expanded = WORK / f"expanded-{name}"
    shutil.rmtree(expanded, ignore_errors=True)
    run(["pkgutil", "--expand", OUT / f"{name}.pkg", expanded])
    infos = sorted(expanded.glob("*-Applications.pkg/PackageInfo"))
    if len(infos) != 1:
        sys.exit(f"{name}: expected one Applications component, found {infos}")
    shutil.copy(infos[0], OUT / f"{name}-Applications-PackageInfo.xml")
    print(f"::group::{name}: {infos[0].relative_to(expanded)}")
    print(infos[0].read_text(encoding="utf-8"))
    print("::endgroup::")
    root = ET.parse(infos[0]).getroot()
    bundles = {bundle.get("id"): bundle.get("path") for bundle in root.findall("bundle")}
    relocate = root.find("relocate")
    relocatable = sorted(b.get("id") for b in relocate.findall("bundle")) if relocate is not None else []
    return bundles, relocatable


def inspect():
    failures = []
    summary("## PackageInfo of the Applications component")
    summary()
    summary("| package | component plist | bundles in the package | bundles under `<relocate>` |")
    summary("| --- | --- | --- | --- |")
    for name, version, plist in PROBES:
        bundles, relocatable = package_info(name)
        paths = ", ".join(f"`{bundles[i]}`" for i in sorted(bundles)) or "none"
        summary(f"| {name} ({version}) | {'yes' if plist else 'no'} | {paths} | "
                f"{', '.join(relocatable) or 'none'} |")
        if sorted(bundles) != BUNDLE_IDS:
            failures.append(f"{name}: expected the bundles {BUNDLE_IDS}, found {sorted(bundles)}")
        if plist and relocatable:
            failures.append(f"{name}: the installer may still relocate {relocatable}")
        if not plist and relocatable != BUNDLE_IDS:
            failures.append(f"{name}: without the plist all bundles should be relocatable, "
                            f"found {relocatable}; the probe cannot see the bug")
    summary()
    for failure in failures:
        summary(f"- **FAIL** {failure}")
    if failures:
        sys.exit(1)
    summary("- **PASS** with the component plist no bundle is relocatable; without it all three are")


def install_log_since(offset):
    text = run(["sudo", "cat", INSTALL_LOG], check=False, capture_output=True).stdout
    return text[offset:].decode("utf-8", errors="replace").splitlines()


def locations():
    """Every stand-in bundle under /Applications, with its version."""
    found = []
    for path in sorted(pathlib.Path("/Applications").glob("OpenMS-*-probe-*/*.app")):
        with open(path / "Contents" / "Info.plist", "rb") as handle:
            version = plistlib.load(handle).get("CFBundleShortVersionString")
        found.append(f"{path.parent.name}/{path.name} ({version})")
    return found


def make_findable(name, version):
    """Index the installed bundles the way a Mac that has used them would have them."""
    run(["sudo", "mdutil", "-i", "on", "/"], check=False)
    for app in APPS:
        bundle = folder(name, version) / f"{app}.app"
        run(["mdimport", bundle], check=False)
        run([LSREGISTER, "-f", bundle], check=False)
    time.sleep(20)
    found = run(["mdfind", "kMDItemCFBundleIdentifier == 'de.openms.TOPPView'"],
                check=False, capture_output=True, text=True).stdout.split()
    print(f"Spotlight finds de.openms.TOPPView at: {found or 'nowhere'}")
    return found


def install():
    rows = []
    spotlight = []
    fixed_ok = False
    control_relocated = None
    for name, version, plist in PROBES:
        offset = INSTALL_LOG.stat().st_size if INSTALL_LOG.exists() else 0
        result = run(["sudo", "installer", "-pkg", OUT / f"{name}.pkg", "-target", "/"],
                     check=False, capture_output=True, text=True)
        print(result.stdout, result.stderr)
        log = [line for line in install_log_since(offset)
               if "Touched bundle" in line or "elocat" in line]
        print("\n".join(log))
        own = [app for app in APPS
               if (folder(name, version) / f"{app}.app" / "Contents" / "Info.plist").exists()]
        rows.append(f"| {name} ({version}) | {'yes' if plist else 'no'} | {result.returncode} | "
                    f"{', '.join(own) or 'none'} | "
                    + ("<br>".join(f"`{line.split('PackageKit: ')[-1]}`" for line in log) or "none")
                    + " |")
        if name == "old":
            spotlight = make_findable(name, version)
        elif name == "control":
            control_relocated = len(own) < len(APPS)
        elif name == "fixed":
            fixed_ok = result.returncode == 0 and len(own) == len(APPS)
    summary("## Installing old, then control, then fixed")
    summary()
    summary("| package | component plist | installer exit code | bundles in its own folder | "
            "install.log on bundles |")
    summary("| --- | --- | --- | --- | --- |")
    for row in rows:
        summary(row)
    summary()
    summary("Bundles under /Applications afterwards: "
            + (", ".join(f"`{entry}`" for entry in locations()) or "none"))
    summary()
    summary(f"Before control was installed, Spotlight found de.openms.TOPPView at: "
            f"{', '.join(f'`{path}`' for path in spotlight) or 'nowhere'}")
    summary()
    if control_relocated:
        summary("- control (no plist) left bundles out of its own folder: the runner reproduces the bug")
    else:
        summary("- control (no plist) installed into its own folder: the runner did not reproduce "
                "the relocation, so this step cannot tell the packages apart; the PackageInfo check "
                "above still holds")
    if not fixed_ok:
        summary("- **FAIL** fixed (with plist) did not install all bundles into its own folder")
        sys.exit(1)
    summary("- **PASS** fixed (with plist) installed all bundles into its own folder")


if __name__ == "__main__":
    commands = {"build": build, "inspect": inspect, "install": install}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: {sys.argv[0]} {'|'.join(commands)}")
    commands[sys.argv[1]]()
