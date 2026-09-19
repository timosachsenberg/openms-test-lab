"""Resolve the current OpenMS nightly package for this runner.

Nightly artifacts live in two places and neither is a GitHub release:

  wheels   https://pypi.openms.de/simple/pyopenms/        (PEP 503 index, sha256 fragments)
  desktop  https://archive.openms.de/openms/OpenMSInstaller/nightly/<YYYY.MM.DD>/

Both labs call this so the selection rule is written once. Printing JSON on stdout keeps it
usable from PowerShell, which has no way to import a Python module.
"""
import argparse
import json
import platform
import re
import sys
import urllib.parse
import urllib.request

WHEEL_INDEX = "https://pypi.openms.de/simple/pyopenms/"
DESKTOP_INDEX = "https://archive.openms.de/openms/OpenMSInstaller/nightly/"
LOOKBACK = 7
MAC = sys.platform == "darwin"
WINDOWS = sys.platform.startswith("win")
ARM = platform.machine().lower() in {"arm64", "aarch64"}


def fetch(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS downloads are supported")
    request = urllib.request.Request(url, headers={"User-Agent": "openms-test-lab"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8", "replace")


def version_key(version):
    """Order 3.6.0.dev20260919 style versions without depending on packaging."""
    release, _, dev = version.partition(".dev")
    parts = [int(part) for part in re.findall(r"\d+", release)]
    return (parts, int(dev) if dev.isdigit() else -1)


def wheel_platform():
    if WINDOWS:
        return lambda tag: tag == "win_amd64"
    if MAC:
        suffix = "_arm64" if ARM else "_x86_64"
        return lambda tag: tag.startswith("macosx") and tag.endswith(suffix)
    suffix = "_aarch64" if ARM else "_x86_64"
    return lambda tag: tag.startswith(("manylinux", "linux")) and tag.endswith(suffix)


def wheel_compatible(filename, minor):
    """True when this interpreter can install the wheel, honouring abi3."""
    parts = filename[: -len(".whl")].split("-")
    if len(parts) < 5:
        return False
    python_tags, abi_tag, platform_tag = parts[-3], parts[-2], parts[-1]
    if not wheel_platform()(platform_tag):
        return False
    for tag in python_tags.split("."):
        if not tag.startswith("cp3"):
            continue
        built_for = int(tag[3:])
        # An abi3 wheel built for cp3X runs on every later CPython 3 as well.
        if built_for == minor or (abi_tag == "abi3" and built_for <= minor):
            return True
    return False


def wheel():
    if sys.version_info[0] != 3:
        raise RuntimeError("pyOpenMS nightlies are CPython 3 only")
    minor = sys.version_info[1]
    index = fetch(WHEEL_INDEX)
    entries = re.findall(r'href="([^"#]+)#sha256=([0-9a-f]{64})"', index)
    if not entries:
        raise RuntimeError(f"No wheels listed at {WHEEL_INDEX}")
    candidates = []
    for href, digest in entries:
        name = href.rsplit("/", 1)[-1]
        if not name.endswith(".whl"):
            continue
        version = name.split("-")[1]
        if wheel_compatible(name, minor):
            candidates.append((version_key(version), version, href, digest, name))
    if not candidates:
        names = [href.rsplit("/", 1)[-1] for href, _ in entries if href.endswith(".whl")]
        newest = max(version_key(name.split("-")[1]) for name in names)
        platforms = sorted({name[: -len(".whl")].split("-")[-1] for name in names
                            if version_key(name.split("-")[1]) == newest})
        hint = (" macOS Intel nightlies are not published; pass an explicit URL or 'none'."
                if MAC and not ARM else "")
        raise RuntimeError(
            f"No nightly wheel for CPython 3.{minor} on this platform. "
            f"Newest nightly builds for: {', '.join(platforms)}.{hint}"
        )
    _, version, href, digest, name = max(candidates)
    # pip verifies the fragment itself, so the digest is enforced rather than only recorded.
    url = urllib.parse.urljoin(WHEEL_INDEX, href)
    return {"kind": "wheel", "version": version, "file": name, "sha256": digest,
            "url": f"{url}#sha256={digest}", "index": WHEEL_INDEX}


def desktop_suffix():
    if WINDOWS:
        return "-Win64.exe"
    if MAC:
        return "-macOS-Silicon.pkg" if ARM else "-macOS-Intel.pkg"
    return "-Debian-Linux-aarch64.deb" if ARM else "-Debian-Linux-x86_64.deb"


def desktop():
    suffix = desktop_suffix()
    folders = sorted(set(re.findall(r'href="(\d{4}\.\d{2}\.\d{2})/"', fetch(DESKTOP_INDEX))),
                     reverse=True)
    if not folders:
        raise RuntimeError(f"No dated nightly folders at {DESKTOP_INDEX}")
    tried = []
    for folder in folders[:LOOKBACK]:
        listing = fetch(f"{DESKTOP_INDEX}{folder}/")
        matches = sorted({name for name in re.findall(r'href="([^"?/]+)"', listing)
                          if name.endswith(suffix)})
        tried.append(folder)
        if len(matches) == 1:
            return {"kind": "desktop", "folder": folder, "file": matches[0],
                    "url": f"{DESKTOP_INDEX}{folder}/{urllib.parse.quote(matches[0])}",
                    "is_newest": folder == folders[0], "searched": tried,
                    "index": DESKTOP_INDEX}
        if len(matches) > 1:
            raise RuntimeError(f"{folder} holds {len(matches)} packages ending {suffix}: {matches}")
    raise RuntimeError(
        f"No nightly package ending {suffix} in the {len(tried)} most recent folders ({', '.join(tried)}). "
        "macOS Intel nightlies are not published; pass an explicit URL or 'none'."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["wheel", "desktop"])
    arguments = parser.parse_args()
    print(json.dumps(wheel() if arguments.kind == "wheel" else desktop(), indent=2))


if __name__ == "__main__":
    main()
