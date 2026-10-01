#!/usr/bin/env python3
"""Checks whether the OpenMS macOS pkg lets the installer relocate the app bundles.

pkgbuild lists the bundles that the installer may relocate under <relocate> in the PackageInfo
of a component; the installer then updates a bundle with the same identifier wherever it finds
one, e.g. in an older OpenMS, instead of installing into the folder of the new version
(OpenMS/OpenMS#8461).

  package  checks a real installer: LAB_OPENMS_PACKAGE is nightly, latest, a release tag or an
           HTTPS PKG URL, resolved and downloaded like in the package labs. Fails if a component
           lists a bundle under <relocate>. Then installs an older copy (version 0.0.1) of every
           app of the package into another folder, as an earlier OpenMS would be, lets Spotlight
           index it, installs the package and fails if an app of the package lands anywhere but
           in its own folder

The other commands test the packaging files of an OpenMS commit that has no installer yet, with
packages of three stand-in app bundles (see CMakeLists.txt here). Their versions only order the
three packages:

  build    old (3.6.0) and control (3.7.0) without the component plist, as the packages before
           the fix; fixed (3.7.1) with the component plist of the OpenMS checkout
  inspect  reads the PackageInfo of each Applications component. Fails if fixed lists a
           bundle under <relocate>, or if control does not list all three (then the probe
           could not see the bug)
  install  installs old, control and fixed in that order and records where the bundles land.
           Fails if the bundles of fixed are not in its own folder

Environment: LAB_OPENMS_PACKAGE (package), OPENMS_SOURCE_DIR (default <workspace>/openms),
PROBE_OUT (default <workspace>/probe-out).
"""
import importlib.util
import json
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
## Older than every OpenMS, so the installer would upgrade it in place if it may relocate
DECOY_VERSION = "0.0.1"
DECOY_FOLDER = pathlib.Path("/Applications/OpenMS-relocation-decoy")


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


def lab_module():
    """scripts/unix-lab.py, which resolves and downloads the packages of the package labs."""
    scripts = HERE.parent
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("unix_lab", scripts / "unix-lab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle_version(bundle):
    info = bundle / "Contents" / "Info.plist"
    if not info.exists():
        return None
    with open(info, "rb") as handle:
        return plistlib.load(handle).get("CFBundleShortVersionString")


def install_decoys(apps, component):
    """An older OpenMS as a user has it: every app of the package with version DECOY_VERSION in
    DECOY_FOLDER, installed by a pkg with the identifier of the package's component. Bundles
    written to disk by hand were not indexed by Spotlight on the runner; installed ones were."""
    root = WORK / "decoy-root"
    shutil.rmtree(root, ignore_errors=True)
    stub = WORK / "decoy-stub"
    stub.with_suffix(".c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    run(["cc", "-o", stub, stub.with_suffix(".c")])
    for identifier, (path, _) in apps.items():
        bundle = root / DECOY_FOLDER.relative_to("/") / pathlib.Path(path).name
        (bundle / "Contents" / "MacOS").mkdir(parents=True)
        with open(bundle / "Contents" / "Info.plist", "wb") as handle:
            plistlib.dump({"CFBundleIdentifier": identifier, "CFBundleName": bundle.stem,
                           "CFBundleExecutable": bundle.stem, "CFBundlePackageType": "APPL",
                           "CFBundleInfoDictionaryVersion": "6.0",
                           "CFBundleShortVersionString": DECOY_VERSION,
                           "CFBundleVersion": DECOY_VERSION}, handle)
        shutil.copy(stub, bundle / "Contents" / "MacOS" / bundle.stem)
    decoy = WORK / "decoy.pkg"
    run(["pkgbuild", "--root", root, "--install-location", "/", "--identifier", component,
         "--version", DECOY_VERSION, decoy])
    return run(["sudo", "installer", "-pkg", decoy, "-target", "/"], check=False,
               capture_output=True, text=True).returncode


def wait_until_findable(decoys, timeout=180):
    """Index the decoys as Spotlight indexes the apps a user has; returns the identifiers it finds."""
    run(["sudo", "mdutil", "-i", "on", "/"], check=False)
    for bundle in decoys.values():
        run(["mdimport", bundle], check=False)
        run([LSREGISTER, "-f", bundle], check=False)
    missing = dict(decoys)
    deadline = time.time() + timeout
    while missing and time.time() < deadline:
        time.sleep(10)
        for identifier, bundle in list(missing.items()):
            found = run(["mdfind", f"kMDItemCFBundleIdentifier == '{identifier}'"], check=False,
                        capture_output=True, text=True).stdout.split("\n")
            if str(bundle) in found:
                del missing[identifier]
    return sorted(set(decoys) - set(missing))


def package():
    selection = os.environ.get("LAB_OPENMS_PACKAGE", "nightly").strip()
    lab = lab_module()
    target = lab.resolve_package(selection)
    OUT.mkdir(parents=True, exist_ok=True)
    pkg = WORK / target["file"]
    digest = lab.download(target["url"], pkg, target["expected"])
    record = {"selection": selection, "url": target["url"], "file": target["file"],
              "sha256": digest, "digest_verified": bool(target["expected"]),
              "release": target["release"], "nightly": target["nightly"]}
    summary(f"## {target['file']}")
    summary()
    summary(f"`{selection}` resolved to {target['url']}, SHA-256 `{digest}`")
    summary()

    expanded = WORK / "expanded-package"
    shutil.rmtree(expanded, ignore_errors=True)
    run(["pkgutil", "--expand", pkg, expanded])
    apps = {}  # identifier: (path in the package, version)
    components = set()  # package identifiers of the components that hold apps
    relocatable = {}  # component: identifiers
    for info in sorted(expanded.glob("*.pkg/PackageInfo")):
        root = ET.parse(info).getroot()
        for bundle in root.findall("bundle"):
            path = bundle.get("path", "")
            ## The apps themselves, not helper apps inside another bundle or a framework
            if path.endswith(".app") and ".app/" not in path and ".framework/" not in path:
                apps[bundle.get("id")] = (path, bundle.get("CFBundleShortVersionString"))
                components.add(root.get("identifier"))
        relocate = root.find("relocate")
        listed = sorted(b.get("id") for b in relocate.findall("bundle")) if relocate is not None else []
        if listed:
            relocatable[info.parent.name] = listed
            shutil.copy(info, OUT / f"{info.parent.name}-PackageInfo.xml")
    record.update(apps={i: {"path": p, "version": v} for i, (p, v) in apps.items()},
                  relocatable=relocatable)
    summary("| app | path in the package | version | under `<relocate>` |")
    summary("| --- | --- | --- | --- |")
    listed_anywhere = {i for ids in relocatable.values() for i in ids}
    for identifier, (path, version) in sorted(apps.items()):
        summary(f"| {identifier} | `{path}` | {version} | "
                f"{'**yes**' if identifier in listed_anywhere else 'no'} |")
    summary()
    failures = []
    if not apps:
        failures.append("the package holds no app bundle")
    for component, ids in relocatable.items():
        failures.append(f"{component} lets the installer relocate {', '.join(ids)}")

    decoys = {identifier: DECOY_FOLDER / pathlib.Path(path).name
              for identifier, (path, _) in apps.items()}
    if len(components) > 1:
        failures.append(f"the apps are spread over several components ({sorted(components)}); "
                        "the decoys mimic one")
    decoy_exit = install_decoys(apps, min(components)) if apps else None
    findable = wait_until_findable(decoys)
    offset = INSTALL_LOG.stat().st_size if INSTALL_LOG.exists() else 0
    result = run(["sudo", "installer", "-pkg", pkg, "-target", "/"], check=False,
                 capture_output=True, text=True)
    print(result.stdout, result.stderr)
    log = [line.split("PackageKit: ")[-1] for line in install_log_since(offset)
           if "relocated to" in line]
    summary(f"An older copy ({DECOY_VERSION}) of each app was installed into `{DECOY_FOLDER}` by a "
            f"pkg with the identifier `{min(components) if components else '-'}` (installer exit "
            f"code {decoy_exit}); Spotlight found {len(findable)} of {len(decoys)} before the "
            f"installation. `installer` exit code for the package: {result.returncode}.")
    summary()
    summary("| app | in its own folder | decoy afterwards | install.log |")
    summary("| --- | --- | --- | --- |")
    landed = {}
    for identifier, (path, version) in sorted(apps.items()):
        own = bundle_version(pathlib.Path("/") / path.removeprefix("./"))
        decoy = bundle_version(decoys[identifier])
        moved = [line for line in log if pathlib.Path(path).name in line]
        landed[identifier] = {"own_folder_version": own, "decoy_version": decoy, "log": moved}
        summary(f"| {identifier} | {own or '**missing**'} | {decoy or 'missing'} | "
                + ("<br>".join(f"`{line}`" for line in moved) or "-") + " |")
        if decoy != DECOY_VERSION:
            failures.append(f"{identifier} replaced the older copy in {DECOY_FOLDER}")
        if own is None or (version and own != version):
            failures.append(f"{identifier} {version} is not in its own folder ({path})")
    summary()
    record.update(decoy_installer_exit_code=decoy_exit, decoys_findable=findable,
                  installer_exit_code=result.returncode, landed=landed)
    if decoy_exit:
        failures.append(f"the decoy pkg did not install (exit code {decoy_exit}), so the "
                        "installation check is void")
    if result.returncode:
        failures.append(f"installer failed with exit code {result.returncode}")
    record["failures"] = failures
    (OUT / "package.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    moved = any(entry["decoy_version"] != DECOY_VERSION for entry in landed.values())
    if relocatable and not moved:
        summary("- the installation did not move an app into the older copies this time; the "
                "`<relocate>` list still lets the installer do it on a Mac that knows them")
    for failure in failures:
        summary(f"- **FAIL** {failure}")
    if failures:
        sys.exit(1)
    if len(findable) < len(decoys):
        summary("- **PASS** no bundle is relocatable; Spotlight did not find every older copy "
                "before the installation, so that part only shows the installer did not move them")
    else:
        summary("- **PASS** no bundle is relocatable, and every app went into its own folder "
                "although Spotlight knew an older copy")


if __name__ == "__main__":
    commands = {"build": build, "inspect": inspect, "install": install, "package": package}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: {sys.argv[0]} {'|'.join(commands)}")
    commands[sys.argv[1]]()
