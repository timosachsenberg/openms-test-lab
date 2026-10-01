"""Does the macOS installer put the OpenMS apps into the folder of the version it installs?

pkgbuild marks every app bundle relocatable unless a component plist says otherwise. The
Installer then updates a bundle with the same identifier wherever it finds one, such as in an
older OpenMS, instead of installing it where the package says (OpenMS/OpenMS#8477, fixed by
OpenMS/OpenMS#8479). The BundleIsRelocatable key in an app's Info.plist has no effect;
pkgbuild reads it only from the component plist it is given.

  upgrade  Check C8 of RELEASE-READINESS.md. Installs the previous release, makes its apps
           findable, installs the candidate over it, and reports where each of the
           candidate's apps landed and whether the previous release's apps were touched.
  cpack    For PRs that change OpenMS's macOS packaging. Runs the packaging scripts of an
           OpenMS checkout (cmake/) through `cpack -G productbuild`, around three stub app
           bundles installed the way add_mac_app_bundle() installs TOPPView, TOPPAS and
           INIFileEditor, and reports which bundles each component lets the Installer relocate.

Packages are `nightly`, `latest`, a release tag, an HTTPS URL or a local file
(scripts/macos_pkg.py). macOS only; reports go to reports/, downloads to downloads/pkg-relocation/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import macos_pkg

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
WORK = ROOT / "downloads" / "pkg-relocation"
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
set(OPENMS_PACKAGE_VERSION 9.9.9)
set(OPENMS_PACKAGE_VERSION_FULLSTRING 9.9.9)
set(CPACK_PACKAGE_NAME OpenMS)
set(CPACK_PACKAGE_VERSION 9.9.9)
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


def macos_version():
    return run(["sw_vers", "-productVersion"], quiet=True).stdout.strip()


def listing(found):
    return ", ".join(f"{name}: {', '.join(ids)}" for name, ids in found.items()) or "none"


def fingerprint(bundle):
    """A digest of an app's Info.plist and executables; None when the app is not there."""
    bundle = Path(bundle)
    if not bundle.is_dir():
        return None
    digest = hashlib.sha256()
    for path in [bundle / "Contents" / "Info.plist", *sorted((bundle / "Contents" / "MacOS").glob("*"))]:
        if path.is_file():
            digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def make_findable(paths):
    """Register the installed apps with Launch Services and Spotlight, which runner images
    turn off, and wait up to five minutes until Spotlight finds each one by its identifier."""
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


def install_log_excerpt(name):
    """The Installer's own account of bundles it relocated, registered or touched."""
    log = Path("/var/log/install.log")
    if log.is_file():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]
        keep = [l for l in lines if "relocated to" in l or "de.openms" in l or "/Applications/OpenMS" in l]
        (REPORTS / name).write_text("\n".join(keep) + "\n", encoding="utf-8")
        return [l.split("PackageKit: ", 1)[-1] for l in keep if "relocated to" in l]
    return None


def upgrade(args):
    report = "upgrade.json"
    shutil.rmtree(WORK / "upgrade", ignore_errors=True)
    record = {"check": "C8", "macos": macos_version(), "status": "downloading"}
    write(report, record)
    packages, apps = {}, {}
    for label, selection in (("previous", args.previous), ("candidate", args.candidate)):
        packages[label], record[label] = macos_pkg.fetch(selection, WORK / "upgrade" / label)
        found = macos_pkg.components(packages[label])
        apps[label] = macos_pkg.applications(found)
        record[label].update(selection=selection, relocatable=macos_pkg.relocatable(found), apps=apps[label])
        write(report, record)
    if record["previous"]["sha256"] == record["candidate"]["sha256"]:
        raise RuntimeError("The previous release and the candidate are the same package")
    if not apps["candidate"]:
        raise RuntimeError(f"The candidate installs no app under /Applications: {record['candidate']['file']}")
    shared = {b for b in apps["candidate"] if apps["candidate"][b] == apps["previous"].get(b)}
    if shared:
        raise RuntimeError(f"Both packages install {sorted(shared)} at the same path, so C8 cannot tell them apart")

    record["status"] = "installing previous"
    write(report, record)
    run(["sudo", "installer", "-pkg", packages["previous"], "-target", "/"], "install-previous.log")
    before = {b: fingerprint(path) for b, path in apps["previous"].items()}
    record["previous"]["installed"] = {b: digest is not None for b, digest in before.items()}
    record["findable"] = make_findable({b: p for b, p in apps["previous"].items() if before[b]})
    record["status"] = "installing candidate"
    write(report, record)
    run(["sudo", "installer", "-pkg", packages["candidate"], "-target", "/", "-verboseR"], "install-candidate.log")
    record["installer_relocations"] = install_log_excerpt("install-log-excerpt.txt")

    outcomes = {}
    for bundle_id, path in apps["candidate"].items():
        previous_path = apps["previous"].get(bundle_id)
        landed = fingerprint(path) is not None
        touched = bool(previous_path) and fingerprint(previous_path) != before.get(bundle_id)
        outcome = ("in place" if landed and not touched else "relocated" if touched and not landed
                   else "in place, and the previous app changed too" if landed else "missing")
        outcomes[bundle_id] = {"candidate_path": path, "previous_path": previous_path, "outcome": outcome}
    passed = all(o["outcome"] == "in place" for o in outcomes.values())
    record.update(status="done", outcomes=outcomes, passed=passed)
    write(report, record)

    lines = [f"### C8 · upgrade `{record['previous']['file']}` → `{record['candidate']['file']}`", "",
             f"macOS {record['macos']}. Candidate sha256 `{record['candidate']['sha256']}`.", "",
             f"- **C8 {'PASS' if passed else 'FAIL'}**: every app of the candidate in its own folder, "
             "the previous release's apps untouched",
             f"- relocatable in the candidate (F11): {listing(record['candidate']['relocatable'])}",
             f"- relocatable in the previous release: {listing(record['previous']['relocatable'])}",
             f"- Spotlight finds the previous release's apps: {'yes' if record['findable']['all_found'] else 'no'}",
             f"- relocations in install.log: {record['installer_relocations'] or 'none'}",
             "", "| App | Candidate path | Landed |", "| --- | --- | --- |"]
    lines += [f"| `{b}` | `{o['candidate_path']}` | {o['outcome']} |" for b, o in outcomes.items()]
    summary(lines)
    if args.expect == "in-place" and not passed:
        print("FAIL C8: an app of the candidate did not land in its own folder")
        return 1
    return 0


def cpack(args):
    openms = Path(args.openms).resolve()
    work = WORK / f"cpack-{args.label}"
    shutil.rmtree(work, ignore_errors=True)
    source, build = work / "source", work / "build"
    source.mkdir(parents=True)
    (source / "cmake").symlink_to(openms / "cmake")
    (source / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (source / "CMakeLists.txt").write_text(HARNESS, encoding="utf-8")
    record = {"label": args.label,
              "openms_revision": run(["git", "-C", openms, "rev-parse", "HEAD"], quiet=True).stdout.strip(),
              "cmake": run(["cmake", "--version"], quiet=True).stdout.splitlines()[0],
              "macos": macos_version(), "status": "configuring"}
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
    found = macos_pkg.components(packages[0])
    record.update(status="packaged", package=packages[0].name, components=found,
                  relocatable=macos_pkg.relocatable(found), applications=macos_pkg.applications(found))
    write(f"cpack-{args.label}.json", record)

    lines = [f"### CPack · {args.label}", "",
             f"OpenMS `{record['openms_revision']}`, {record['cmake']}, macOS {record['macos']}.", "",
             f"- component plist written: {'yes' if record['component_plist'] else 'no'}",
             f"- pkgbuild called with `--component-plist`: "
             f"{'yes' if any('--component-plist' in c for c in record['pkgbuild_commands']) else 'no'}",
             "- apps: " + ", ".join(f"`{p}`" for p in record["applications"].values()),
             f"- relocatable: {listing(record['relocatable'])}"]
    summary(lines)
    if args.expect == "no-relocation" and (record["relocatable"] or not record["component_plist"]):
        print("FAIL: the package lets the Installer relocate a bundle, or no component plist was written")
        return 1
    return 0


def main():
    if sys.platform != "darwin":
        sys.exit("macOS only")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("upgrade", help="C8: install the previous release, then the candidate")
    probe.add_argument("--previous", default="latest", help="latest, a release tag, an HTTPS URL or a .pkg")
    probe.add_argument("--candidate", default="nightly", help="nightly, a release tag, an HTTPS URL or a .pkg")
    probe.add_argument("--expect", choices=["in-place", "report"], default="report")
    probe = commands.add_parser("cpack", help="package stub apps with an OpenMS checkout's packaging scripts")
    probe.add_argument("--openms", required=True, help="OpenMS checkout (cmake/ is enough)")
    probe.add_argument("--label", required=True)
    probe.add_argument("--expect", choices=["no-relocation", "report"], default="report")
    args = parser.parse_args()
    sys.exit(upgrade(args) if args.command == "upgrade" else cpack(args))


if __name__ == "__main__":
    main()
