"""List the components of a macOS product archive (.pkg) and what each lets the Installer relocate.

Reads the PackageInfo of every component straight from the xar archive, so it runs on any OS
and needs no pkgutil. A component lists under <relocate> the app bundles the Installer may
install wherever it finds a bundle with the same identifier instead of where the package says
(OpenMS/OpenMS#8477). From OpenMS/OpenMS#8479 on, the Applications component relocates nothing.

  python3 scripts/pkg-components.py nightly --expect-no-relocation
  python3 scripts/pkg-components.py https://.../OpenMS-...-macOS-Silicon.pkg
  python3 scripts/pkg-components.py downloads/OpenMS-...-macOS-Silicon.pkg

`nightly` is the newest macOS Silicon nightly (scripts/resolve_nightly.py). A URL is downloaded
in full, so the report carries its SHA-256. Prints JSON; with --expect-no-relocation the exit
status is 1 when any component relocates a bundle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

import resolve_nightly


def nightly_url():
    resolve_nightly.MAC, resolve_nightly.ARM, resolve_nightly.WINDOWS = True, True, False
    return resolve_nightly.desktop()


def download(url, target):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS downloads are supported")
    request = urllib.request.Request(url, headers={"User-Agent": "openms-test-lab"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=600) as response, target.open("wb") as handle:
        headers = {"Last-Modified": response.headers.get("Last-Modified"),
                   "ETag": response.headers.get("ETag")}
        while block := response.read(1 << 20):
            digest.update(block)
            handle.write(block)
    return digest.hexdigest(), headers


def xar_files(path):
    """Yield (path inside the archive, bytes) for every file of a xar archive."""
    with open(path, "rb") as handle:
        magic, header_size, _, toc_compressed, _, _ = struct.unpack(">4sHHQQI", handle.read(28))
        if magic != b"xar!":
            raise ValueError(f"{path} is not a xar archive (.pkg product archive)")
        handle.seek(header_size)
        toc = ET.fromstring(zlib.decompress(handle.read(toc_compressed)))
        heap = header_size + toc_compressed

        def walk(element, prefix):
            for item in element.findall("file"):
                name = f"{prefix}{item.findtext('name')}"
                if item.findtext("type") == "directory":
                    yield from walk(item, name + "/")
                    continue
                data = item.find("data")
                if data is None:
                    continue
                handle.seek(heap + int(data.findtext("offset")))
                raw = handle.read(int(data.findtext("length")))
                style = data.find("encoding").get("style") if data.find("encoding") is not None else ""
                # xar's "application/x-gzip" is a zlib stream
                yield name, zlib.decompress(raw) if "gzip" in style else raw

        yield from walk(toc.find("toc"), "")


def package_info(text):
    root = ET.fromstring(text)
    return {"identifier": root.get("identifier"), "version": root.get("version"),
            "install_location": root.get("install-location"),
            "bundles": {b.get("id"): b.get("path") for b in root.findall("bundle")},
            "relocate": sorted(b.get("id") for b in root.findall("relocate/bundle"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", help="nightly, an HTTPS URL of a .pkg, or a local .pkg")
    parser.add_argument("--expect-no-relocation", action="store_true")
    args = parser.parse_args()

    record = {"package": args.package}
    with tempfile.TemporaryDirectory() as work:
        if args.package == "nightly" or args.package.startswith("https://"):
            if args.package == "nightly":
                record["nightly"] = nightly_url()
                url = record["nightly"]["url"]
            else:
                url = args.package
            path = Path(work) / Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name
            record["url"], record["file"] = url, path.name
            record["sha256"], record["http"] = download(url, path)
        else:
            path = Path(args.package)
            record["file"] = path.name
            with path.open("rb") as handle:
                record["sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        components = {name.removesuffix("/PackageInfo"): package_info(data)
                      for name, data in xar_files(path) if name.endswith(".pkg/PackageInfo")}
    if not components:
        raise RuntimeError("No component PackageInfo found; is this a product archive?")
    record["components"] = components
    record["relocatable"] = {name: info["relocate"] for name, info in components.items() if info["relocate"]}
    print(json.dumps(record, indent=2))
    if args.expect_no_relocation and record["relocatable"]:
        print(f"FAIL: relocatable bundles: {record['relocatable']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
