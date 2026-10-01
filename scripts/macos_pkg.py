"""Find and read the macOS OpenMS package (.pkg), on any OS.

As a script this is check F11 of RELEASE-READINESS.md: it lists the components of a product
archive and the app bundles each one lets the Installer relocate. A relocatable bundle is
installed wherever the Installer finds a bundle with the same identifier, such as in an older
OpenMS, instead of where the package says (OpenMS/OpenMS#8477). Since OpenMS/OpenMS#8479 the
Applications component relocates nothing. The PackageInfo files are read straight from the xar
archive, so no pkgutil and no Mac is needed.

    python3 scripts/macos_pkg.py nightly --expect-no-relocation
    python3 scripts/macos_pkg.py v3.6.0 --report reports/macos-pkg.json
    python3 scripts/macos_pkg.py https://.../OpenMS-<version>-macOS-Silicon.pkg
    python3 scripts/macos_pkg.py downloads/OpenMS-<version>-macOS-Silicon.pkg

A package is `nightly` (scripts/resolve_nightly.py), `latest` or a release tag (the asset of
that GitHub release, checked against its published digest), an HTTPS URL, or a local file.
Prints JSON; with --expect-no-relocation the exit status is 1 when a component relocates a
bundle. A pass says what the package asks of the Installer, not where a given Mac puts the
apps; check C8 installs one package over another to see that.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

import resolve_nightly

SUFFIX = "-macOS-Silicon.pkg"
API = "https://api.github.com/repos/OpenMS/OpenMS"


def request(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS downloads are supported")
    headers = {"User-Agent": "openms-test-lab"}
    token = os.environ.get("GH_TOKEN")
    if token and urllib.parse.urlsplit(url).netloc == "api.github.com":
        headers.update(Accept="application/vnd.github+json", Authorization=f"Bearer {token}")
    return urllib.request.Request(url, headers=headers)


def resolve(selection):
    """Where `nightly`, `latest`, a release tag or an HTTPS URL is, and its expected digest."""
    selection = selection.strip()
    if selection == "nightly":
        nightly = resolve_nightly.desktop(SUFFIX)
        return {"url": nightly["url"], "nightly": nightly}
    if selection.startswith("https://"):
        return {"url": selection}
    path = "/releases/latest" if selection == "latest" else "/releases/tags/" + urllib.parse.quote(selection, safe="")
    with urllib.request.urlopen(request(API + path), timeout=60) as response:
        release = json.load(response)
    assets = [a for a in release["assets"] if a["name"].endswith(SUFFIX)]
    if len(assets) != 1:
        raise RuntimeError(f"Expected one asset ending {SUFFIX} in release {release['tag_name']}; got {len(assets)}")
    return {"url": assets[0]["browser_download_url"], "release": release["tag_name"],
            "expected_sha256": (assets[0].get("digest") or "").removeprefix("sha256:") or None}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def fetch(selection, folder):
    """The package as a local file, and where it came from: (path, record)."""
    if Path(selection).is_file():
        return Path(selection), {"file": Path(selection).name, "sha256": sha256(selection)}
    record = resolve(selection)
    name = Path(urllib.parse.unquote(urllib.parse.urlsplit(record["url"]).path)).name
    if not name.endswith(".pkg"):
        raise ValueError(f"Not a .pkg: {record['url']}")
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {record['url']}", file=sys.stderr, flush=True)
    with urllib.request.urlopen(request(record["url"]), timeout=600) as response, path.open("wb") as handle:
        record["last_modified"] = response.headers.get("Last-Modified")
        while block := response.read(1 << 20):
            handle.write(block)
    record.update(file=name, sha256=sha256(path))
    if record.get("expected_sha256") and record["expected_sha256"] != record["sha256"]:
        raise RuntimeError(f"Checksum mismatch for {name}: published {record['expected_sha256']}, got {record['sha256']}")
    return path, record


def xar_files(path):
    """Yield (path inside the archive, content) for every file of a xar archive."""
    with open(path, "rb") as handle:
        magic, header_size, _, toc_length, _, _ = struct.unpack(">4sHHQQI", handle.read(28))
        if magic != b"xar!":
            raise ValueError(f"{path} is not a xar archive, so not a .pkg")
        handle.seek(header_size)
        toc = ET.fromstring(zlib.decompress(handle.read(toc_length)))
        heap = header_size + toc_length

        def walk(element, prefix):
            for item in element.findall("file"):
                name = prefix + item.findtext("name")
                if item.findtext("type") == "directory":
                    yield from walk(item, name + "/")
                    continue
                data = item.find("data")
                if data is None:
                    continue
                handle.seek(heap + int(data.findtext("offset")))
                raw = handle.read(int(data.findtext("length")))
                encoding = data.find("encoding")
                # xar's "application/x-gzip" is a zlib stream
                yield name, zlib.decompress(raw) if encoding is not None and "gzip" in encoding.get("style", "") else raw

        yield from walk(toc.find("toc"), "")


def package_info(text):
    root = ET.fromstring(text)
    return {"identifier": root.get("identifier"), "version": root.get("version"),
            "install_location": root.get("install-location"),
            "bundles": {b.get("id"): b.get("path") for b in root.findall("bundle")},
            "relocate": sorted(b.get("id") for b in root.findall("relocate/bundle"))}


def components(path):
    """The PackageInfo of every component of a product archive, or of one component package."""
    found = {}
    for name, data in xar_files(path):
        if name == "PackageInfo":
            found[Path(path).name] = package_info(data)
        elif name.endswith(".pkg/PackageInfo") and name.count("/") == 1:
            found[name.removesuffix("/PackageInfo")] = package_info(data)
    if not found:
        raise RuntimeError(f"No PackageInfo in {path}")
    return found


def relocatable(found):
    return {name: info["relocate"] for name, info in found.items() if info["relocate"]}


def applications(found):
    """The app bundles the package installs at /Applications/<folder>/<App>.app, by identifier."""
    return {bundle_id: "/" + path.removeprefix("./")
            for info in found.values() for bundle_id, path in info["bundles"].items()
            if path.endswith(".app") and len(Path(path.removeprefix("./")).parts) == 3
            and path.removeprefix("./").startswith("Applications/")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", help="nightly, latest, a release tag, an HTTPS URL or a local .pkg")
    parser.add_argument("--expect-no-relocation", action="store_true")
    parser.add_argument("--report", type=Path, help="also write the JSON here")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        path, record = fetch(args.package, folder)
        found = components(path)
    record.update(selection=args.package, components=found, relocatable=relocatable(found),
                  applications=applications(found))
    text = json.dumps(record, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    if args.expect_no_relocation and record["relocatable"]:
        print(f"FAIL F11: relocatable bundles {record['relocatable']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
