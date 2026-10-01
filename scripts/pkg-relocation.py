"""Does the macOS installer put the OpenMS apps into the folder of the version it installs?

pkgbuild marks every app bundle relocatable unless a component plist says otherwise. The
Installer then updates a bundle with the same identifier wherever it finds one, such as in an
older OpenMS, instead of installing it where the package says (OpenMS/OpenMS#8477). The
BundleIsRelocatable key in an app's Info.plist has no effect; pkgbuild reads it only from the
component plist it is given.

  cpack    Runs OpenMS's packaging scripts (cmake/ of an OpenMS checkout) through
           `cpack -G productbuild`, around three stub app bundles installed the way
           add_mac_app_bundle() installs TOPPView, TOPPAS and INIFileEditor, and reports which
           bundles each component of the package lets the Installer relocate.
  install  Installs an OpenMS package as the older version and makes its apps findable. Then
           it repackages that package's own Applications component as version 9.9.9, either
           with pkgbuild's defaults or with the component plist that
           cmake/generate_applications_component_plist.cmake writes, installs it, and reports
           where each app landed.

macOS only. Reports go to reports/, everything else to downloads/pkg-relocation/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import resolve_nightly

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
WORK = ROOT / "downloads" / "pkg-relocation"
NEW_VERSION = "9.9.9"
NEW_FOLDER = f"Applications/OpenMS-{NEW_VERSION}"
MARKER = "openms-relocation-probe.txt"
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
              "LaunchServices.framework/Support/lsregister")

# Stands in for the top-level CMakeLists.txt of OpenMS around its packaging scripts: the
# variables they read, three app bundles and one TOPP tool installed the way OpenMS installs
# them, then the includes in the order of the real file. `cmake` is a link to cmake/ of the
# OpenMS checkout under test.
HARNESS = """\
cmake_minimum_required(VERSION 3.24)
project(OpenMSPackageProbe C)
list(PREPEND CMAKE_MODULE_PATH "${PROJECT_SOURCE_DIR}/cmake/Modules")
set(OPENMS_HOST_BINARY_DIRECTORY "${PROJECT_BINARY_DIR}")
set(PACKAGE_TYPE pkg)
set(WITH_GUI ON)
set(OPENMS_GUI_APPLICATIONS_COMPONENT Applications)
set(INSTALL_BIN_DIR bin)
set(INSTALL_LIB_DIR lib)
set(INSTALL_PLUGIN_DIR lib/plugins)
set(INSTALL_SHARE_DIR share/OpenMS)
set(OPENMS_PACKAGE_VERSION @VERSION@)
set(OPENMS_PACKAGE_VERSION_FULLSTRING @VERSION@)
set(CPACK_PACKAGE_NAME OpenMS)
set(CPACK_PACKAGE_VERSION @VERSION@)
set(OPENMS_LOGO_NAME openms_logo_large_transparent.png)
set(OPENMS_LOGOSMALL_NAME openms_logo_corner_small.png)
set(THIRDPARTY_COMPONENT_GROUP)
## ad-hoc signature, so the codesign calls of the install rules succeed
set(CPACK_BUNDLE_APPLE_CERT_APP -)

add_executable(FileInfo main.c)
install(TARGETS FileInfo RUNTIME DESTINATION ${INSTALL_BIN_DIR} COMPONENT Applications)
foreach(_app IN ITEMS TOPPView TOPPAS INIFileEditor)
  add_executable(${_app} MACOSX_BUNDLE main.c)
  set_target_properties(${_app} PROPERTIES
    MACOSX_BUNDLE_GUI_IDENTIFIER "de.openms.${_app}"
    MACOSX_BUNDLE_BUNDLE_VERSION "${OPENMS_PACKAGE_VERSION}"
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${OPENMS_PACKAGE_VERSION}")
  ## the install rule and bookkeeping of add_mac_app_bundle() (src/openms_gui/add_mac_bundle.cmake)
  install(TARGETS ${_app} BUNDLE DESTINATION . COMPONENT ${OPENMS_GUI_APPLICATIONS_COMPONENT})
  set_property(GLOBAL APPEND PROPERTY OPENMS_APP_BUNDLES ${_app})
endforeach()

set(CPACK_GENERATOR productbuild)
include(cmake/package_mac_productbuild.cmake)
include(CPack)
include(cmake/package_components.cmake)
"""


def write(name, value):
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def summary(lines):
    print("\n".join(lines), flush=True)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def run(args, log=None, check=True, cwd=ROOT, quiet=False):
    if not quiet:
        print("+", " ".join(map(str, args)), flush=True)
    result = subprocess.run(list(map(str, args)), cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log:
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / log).write_text(result.stdout, encoding="utf-8")
    if not quiet:
        print(result.stdout[-12000:], flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(map(str, args[:3]))}; see {log}")
    return result


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_revision(checkout):
    return run(["git", "-C", checkout, "rev-parse", "HEAD"], quiet=True).stdout.strip()


def fetch_package(selection):
    """Download `nightly` or an HTTPS PKG URL; return its path and provenance."""
    nightly = None
    if selection == "nightly":
        nightly = resolve_nightly.desktop()
        url = nightly["url"]
    elif selection.startswith("https://"):
        url = selection
    else:
        raise ValueError("The package is 'nightly' or an HTTPS URL of a .pkg")
    name = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name
    if not name.endswith(".pkg"):
        raise ValueError(f"Not a .pkg: {url}")
    target = WORK / name
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "openms-test-lab"})
    with urllib.request.urlopen(request, timeout=600) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return target, {"url": url, "file": name, "sha256": sha(target), "nightly": nightly}


def package_info(path):
    root = ET.parse(path).getroot()
    return {"identifier": root.get("identifier"), "version": root.get("version"),
            "install_location": root.get("install-location"),
            "bundles": {b.get("id"): b.get("path") for b in root.findall("bundle")},
            "relocate": sorted(b.get("id") for b in root.findall("relocate/bundle"))}


def components(package, destination):
    """The PackageInfo of every component of a product archive, or of one component package."""
    shutil.rmtree(destination, ignore_errors=True)
    run(["pkgutil", "--expand", package, destination], quiet=True)
    destination = Path(destination)
    if (destination / "PackageInfo").is_file():
        return {Path(package).name: package_info(destination / "PackageInfo")}
    return {p.parent.name: package_info(p) for p in sorted(destination.glob("*.pkg/PackageInfo"))}


def applications_component(found):
    matches = [name for name, info in found.items() if info["identifier"].endswith(".Applications")]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Applications component; found {matches} in {list(found)}")
    return matches[0]


def relocatable(found):
    return {name: info["relocate"] for name, info in found.items() if info["relocate"]}


def cpack(args):
    openms = Path(args.openms).resolve()
    work = WORK / f"cpack-{args.label}"
    shutil.rmtree(work, ignore_errors=True)
    source, build = work / "source", work / "build"
    source.mkdir(parents=True)
    (source / "cmake").symlink_to(openms / "cmake")
    (source / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (source / "CMakeLists.txt").write_text(HARNESS.replace("@VERSION@", NEW_VERSION), encoding="utf-8")
    record = {"label": args.label, "openms_revision": git_revision(openms),
              "cmake": run(["cmake", "--version"], quiet=True).stdout.splitlines()[0],
              "macos": run(["sw_vers", "-productVersion"], quiet=True).stdout.strip(),
              "status": "configuring"}
    write(f"cpack-{args.label}.json", record)
    run(["cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
         f"-DOPENMS_HOST_DIRECTORY={openms}", "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0"],
        f"cpack-{args.label}-configure.log")
    run(["cmake", "--build", build], f"cpack-{args.label}-build.log")
    record["status"] = "packaging"
    write(f"cpack-{args.label}.json", record)
    result = run(["cpack", "-G", "productbuild", "--verbose"], f"cpack-{args.label}-cpack.log",
                 check=False, cwd=build)
    record["cpack_exit"] = result.returncode
    record["pkgbuild_commands"] = [line.strip() for line in result.stdout.splitlines()
                                   if "pkgbuild" in line and "--root" in line]
    plist = build / "ApplicationsComponent.plist"
    record["component_plist"] = plist.read_text(encoding="utf-8") if plist.is_file() else None
    packages = sorted(build.glob("*.pkg"))
    if result.returncode or len(packages) != 1:
        record["status"] = "cpack failed"
        write(f"cpack-{args.label}.json", record)
        summary([f"### CPack · {args.label}", "", f"`cpack -G productbuild` failed (exit "
                 f"{result.returncode}); see `cpack-{args.label}-cpack.log`."])
        return 1
    found = components(packages[0], work / "expanded")
    applications = applications_component(found)
    record.update(status="packaged", package=packages[0].name, components=found,
                  relocatable=relocatable(found), applications_component=applications)
    write(f"cpack-{args.label}.json", record)

    app_info = found[applications]
    lines = [f"### CPack · {args.label}", "",
             f"OpenMS `{record['openms_revision']}`, {record['cmake']}, macOS {record['macos']}.", "",
             f"- component plist written: {'yes' if record['component_plist'] else 'no'}",
             f"- pkgbuild called with `--component-plist`: "
             f"{'yes' if any('--component-plist' in c for c in record['pkgbuild_commands']) else 'no'}",
             f"- bundles of `{applications}`: " + ", ".join(f"`{p}`" for p in app_info["bundles"].values()),
             f"- relocatable in `{applications}`: " + (", ".join(app_info["relocate"]) or "none"),
             "- relocatable in any other component: "
             + (", ".join(f"{n}: {b}" for n, b in record["relocatable"].items() if n != applications) or "none")]
    summary(lines)
    if args.expect == "no-relocation" and (record["relocatable"] or not record["component_plist"]):
        print("FAIL: the package lets the Installer relocate a bundle, or no component plist was written")
        return 1
    return 0


def generate_plist(openms, apps, work):
    """Write the component plist with cmake/generate_applications_component_plist.cmake."""
    folder = work / "plist"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    driver = folder / "driver.cmake"
    driver.write_text(
        f"set_property(GLOBAL APPEND PROPERTY OPENMS_APP_BUNDLES {' '.join(apps)})\n"
        f'set(CPACK_PACKAGING_INSTALL_PREFIX "/{NEW_FOLDER}")\n'
        f'include("{openms}/cmake/generate_applications_component_plist.cmake")\n'
        'if(NOT APPLICATIONS_COMPONENT_PLIST)\n'
        '  message(FATAL_ERROR "generate_applications_component_plist.cmake wrote no plist")\n'
        'endif()\n', encoding="utf-8")
    # In script mode CMAKE_BINARY_DIR is the working directory.
    run(["cmake", "-P", driver], "plist-generate.log", cwd=folder)
    return folder / "ApplicationsComponent.plist"


def make_findable(paths):
    """Register the installed apps with Launch Services and Spotlight, which runner images
    turn off, and wait until Spotlight finds each one by its bundle identifier."""
    state = {"mdutil_before": run(["mdutil", "-s", "/"], check=False).stdout.strip()}
    for volume in ("/", "/System/Volumes/Data"):
        run(["sudo", "mdutil", "-i", "on", volume], check=False)
    for path in paths.values():
        run([LSREGISTER, "-f", path], check=False)
        run(["mdimport", path], check=False)
    def lookup():
        return {bundle_id: [line.removeprefix("/System/Volumes/Data") for line in
                            run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
                                check=False, quiet=True).stdout.splitlines()]
                for bundle_id in paths}
    deadline = time.time() + 300
    found = lookup()
    while not all(path in found[b] for b, path in paths.items()) and time.time() < deadline:
        time.sleep(10)
        found = lookup()
    state.update(mdutil_after=run(["mdutil", "-s", "/"], check=False).stdout.strip(), mdfind=found,
                 all_found=all(path in found[b] for b, path in paths.items()))
    return state


def install(args):
    work = WORK / f"install-{args.mode}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    openms = Path(args.openms).resolve()
    report = f"install-{args.mode}.json"
    record = {"mode": args.mode, "openms_revision": git_revision(openms),
              "macos": run(["sw_vers", "-productVersion"], quiet=True).stdout.strip(),
              "cmake": run(["cmake", "--version"], quiet=True).stdout.splitlines()[0],
              "status": "downloading"}
    write(report, record)

    # 1. The older OpenMS: the package as published.
    package, record["package"] = fetch_package(args.package)
    older = components(package, work / "older")
    applications = applications_component(older)
    record["older"] = {"components": older, "relocatable": relocatable(older),
                       "applications_component": applications}
    apps = {bundle_id: "/" + path.removeprefix("./")
            for bundle_id, path in older[applications]["bundles"].items()
            if path.endswith(".app") and len(Path(path.removeprefix("./")).parts) == 3}
    if not apps:
        raise RuntimeError(f"No app bundles in {applications}: {older[applications]['bundles']}")
    old_folder = str(Path(next(iter(apps.values()))).parent).lstrip("/")
    record["status"] = "installing older"
    write(report, record)
    run(["sudo", "installer", "-pkg", package, "-target", "/"], "install-older.log")
    record["older"]["installed"] = {bundle_id: Path(path).is_dir() for bundle_id, path in apps.items()}
    record["findable"] = make_findable(apps)
    write(report, record)

    # 2. The newer OpenMS: the same Applications component, moved to OpenMS-9.9.9, its apps
    #    marked and versioned 9.9.9, packaged the way CPack calls pkgbuild.
    run(["pkgutil", "--expand-full", package, work / "older-full"], quiet=True)
    root = work / "newer-root"
    run(["ditto", work / "older-full" / applications / "Payload", root])
    (root / old_folder).rename(root / NEW_FOLDER)
    bundles = sorted((root / NEW_FOLDER).glob("*.app"))
    for bundle in bundles:
        info = bundle / "Contents" / "Info.plist"
        for key in ("CFBundleVersion", "CFBundleShortVersionString"):
            run(["plutil", "-replace", key, "-string", NEW_VERSION, info], quiet=True)
        (bundle / "Contents" / "Resources").mkdir(exist_ok=True)
        (bundle / "Contents" / "Resources" / MARKER).write_text(NEW_VERSION + "\n", encoding="utf-8")
    run(["pkgbuild", "--analyze", "--root", root, work / "analyzed.plist"], "pkgbuild-analyze.log")
    with (work / "analyzed.plist").open("rb") as handle:
        analyzed = plistlib.load(handle)
    record["pkgbuild_default_plist"] = analyzed
    newer = work / f"OpenMS-{NEW_VERSION}-Applications.pkg"
    command = ["pkgbuild", "--root", root, "--identifier", older[applications]["identifier"],
               "--version", NEW_VERSION, "--install-location", "/", newer]
    if args.mode == "component-plist":
        plist = generate_plist(openms, [bundle.stem for bundle in bundles], work)
        with plist.open("rb") as handle:
            generated = plistlib.load(handle)
        record["component_plist"] = generated
        record["plist_paths_match_pkgbuild"] = (
            sorted(entry["RootRelativeBundlePath"] for entry in generated)
            == sorted(entry["RootRelativeBundlePath"] for entry in analyzed
                      if entry["RootRelativeBundlePath"].count("/") == 2))
        # CPack puts the option after the output path (cmCPackProductBuildGenerator)
        command += ["--component-plist", plist]
    run(command, "pkgbuild-newer.log")
    record["newer"] = components(newer, work / "newer")
    record["status"] = "installing newer"
    write(report, record)

    # 3. Where did the newer apps go?
    run(["sudo", "installer", "-pkg", newer, "-target", "/", "-verboseR"], "install-newer.log")
    log = Path("/var/log/install.log")
    if log.is_file():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:]
        (REPORTS / "install-log-excerpt.txt").write_text(
            "\n".join(l for l in lines if "reloc" in l.lower() or "de.openms" in l or "OpenMS" in l) + "\n",
            encoding="utf-8")
    placed = sorted(str(p) for p in Path("/Applications").glob(f"**/Contents/Resources/{MARKER}"))
    outcomes = {}
    for bundle_id, old_path in apps.items():
        new_path = f"/{NEW_FOLDER}/{Path(old_path).name}"
        at_new = (Path(new_path) / "Contents" / "Resources" / MARKER).is_file()
        at_old = (Path(old_path) / "Contents" / "Resources" / MARKER).is_file()
        outcome = ("in place" if at_new and not at_old else "relocated" if at_old and not at_new
                   else "both" if at_new else "missing")
        outcomes[bundle_id] = {"package_path": new_path, "older_path": old_path, "outcome": outcome}
    record.update(status="done", markers_found=placed, outcomes=outcomes)
    write(report, record)

    newer_info = next(iter(record["newer"].values()))
    lines = [f"### Install · {args.mode}", "",
             f"Older OpenMS: `{record['package']['file']}` (sha256 `{record['package']['sha256']}`), "
             f"OpenMS `{record['openms_revision']}`, macOS {record['macos']}.", "",
             f"- relocatable in the older package: "
             + (", ".join(f"{n}: {b}" for n, b in record["older"]["relocatable"].items()) or "none"),
             f"- Spotlight finds every older app: {'yes' if record['findable']['all_found'] else 'no'}",
             f"- relocatable in the newer Applications component: {', '.join(newer_info['relocate']) or 'none'}"]
    if args.mode == "component-plist":
        lines.append(f"- plist paths equal pkgbuild's own: {'yes' if record['plist_paths_match_pkgbuild'] else 'no'}")
    lines += ["", "| App | Package path | Landed |", "|---|---|---|"]
    lines += [f"| `{b}` | `{o['package_path']}` | {o['outcome']} |" for b, o in outcomes.items()]
    summary(lines)
    if args.expect == "in-place":
        failed = (newer_info["relocate"] or not record.get("plist_paths_match_pkgbuild", True)
                  or any(o["outcome"] != "in place" for o in outcomes.values()))
        if failed:
            print("FAIL: an app did not land in the folder of the version installed")
            return 1
    return 0


def main():
    if sys.platform != "darwin":
        sys.exit("macOS only")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("cpack", help="package stub bundles with OpenMS's packaging scripts")
    probe.add_argument("--openms", required=True, help="OpenMS checkout (cmake/ is enough)")
    probe.add_argument("--label", required=True)
    probe.add_argument("--expect", choices=["no-relocation", "report"], default="report")
    probe = commands.add_parser("install", help="install an older and a newer OpenMS and see where the apps land")
    probe.add_argument("--openms", required=True, help="OpenMS checkout whose plist generator to use")
    probe.add_argument("--package", default="nightly", help="nightly or an HTTPS .pkg URL")
    probe.add_argument("--mode", choices=["pkgbuild-default", "component-plist"], required=True)
    probe.add_argument("--expect", choices=["in-place", "report"], default="report")
    args = parser.parse_args()
    sys.exit(cpack(args) if args.command == "cpack" else install(args))


if __name__ == "__main__":
    main()
