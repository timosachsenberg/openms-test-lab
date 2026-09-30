"""Report the versions of security-relevant libraries an OpenMS package bundles.

Check F6 of RELEASE-READINESS.md: a package that carries its own OpenSSL, zlib, curl, SQLite,
bzip2 or Qt is only as current as that copy. This script finds those libraries under a
directory (an installed package, an unpacked wheel or installer), reads the version each one
embeds, and for OpenSSL compares it with the OpenSSL project's own vulnerability list.

A copy is found in two ways: as a file of its own (libcrypto-*.so, zlib1.dll), and linked
statically into another binary. Since 3.6 the Linux and Windows wheels link vcpkg's static
libraries into libOpenMS and OpenMS.dll, so their OpenSSL, zlib, curl, SQLite and bzip2 have no
file of their own. Static copies are reported with "linkage": "static" and judged the same way.

    python3 scripts/bundled-libs.py /usr/lib --only-owned-by openms       # DEB installation
    python3 scripts/bundled-libs.py .venv/lib/python3.12/site-packages/pyopenms
    python3 scripts/bundled-libs.py "C:/OpenMS" --report reports/bundled-libs.json

Other libraries are reported with their version for a person to check; only OpenSSL is
judged automatically, because only its advisories are published in a form this can read.
"""
import argparse
import functools
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

LIBRARIES = {  # name -> (file name pattern, version pattern inside the binary)
    "OpenSSL": (r"^(lib)?(crypto|ssl)[-.0-9_a-z]*\.(so[.0-9]*|dylib|dll)$|^libcrypto", rb"OpenSSL (\d+\.\d+\.\d+[a-z]?)"),
    "zlib": (r"^(lib)?z(lib)?[-.0-9]*\.(so[.0-9]*|dylib|dll)$|^zlib1?\.dll$", rb"(?:deflate|inflate) (\d+\.\d+(?:\.\d+)*) Copyright"),
    "curl": (r"^(lib)?curl[-.0-9a-z]*\.(so[.0-9]*|dylib|dll)$", rb"libcurl/(\d+\.\d+\.\d+)"),
    "SQLite": (r"^(lib)?sqlite3[-.0-9]*\.(so[.0-9]*|dylib|dll)$", rb"(3\.\d{2}\.\d+)\x00"),
    "Qt": (r"^(lib)?Qt6Core(\.so[.0-9]*|\.dylib|\.dll)$|^QtCore$", rb"Qt (\d+\.\d+\.\d+) \("),
    "bzip2": (r"^(lib)?bz2[-.0-9_a-z]*\.(so[.0-9]*|dylib|dll)$", rb"(\d\.\d\.\d+), \d{1,2}-\w{3}-\d{4}"),
}
# Static copies: name -> (texts, version pattern, whether a text alone proves a copy). A binary
# that merely uses a library also names it: libcurl.so.4 among its imports, or the
# OPENSSL_VERSION_TEXT of the headers it was compiled against (Homebrew's libaws-c-cal carries
# "OpenSSL 3.6.3 9 Jun 2026" and loads libcrypto at run time). So the texts are ones only the
# library's own code contains: OpenSSL's source paths and OPENSSLDIR banner, curl's and bzip2's
# error messages, SQLite's file header. zlib's texts only filter; its copyright banner, which the
# version pattern matches, is the proof. curl keeps its version in curl_version(), which a static
# link usually drops, so a static curl may have no version. SQLite's version is a C string with no
# text before it, and its minor version has two digits without a leading zero since 3.10, which
# excludes other numbers such as "3.08.01".
STATIC = {
    "OpenSSL": ((b"OPENSSLDIR: ", b"crypto/evp/"), rb"OpenSSL (\d+\.\d+\.\d+[a-z]?)(?:-[\w.]+)? +\d{1,2} \w{3} \d{4}", True),
    "zlib": ((b" Copyright 1995-",), LIBRARIES["zlib"][1], False),
    "curl": ((b"A libcurl function was given a bad argument",), rb"libcurl/(\d+\.\d+\.\d+)", True),
    "SQLite": ((b"SQLite format 3\x00",), rb"(?<![\x20-\x7e])(3\.[1-9]\d\.\d+)\x00", True),
    "bzip2": ((b"bzip2/libbzip2",), LIBRARIES["bzip2"][1], True),
}
NATIVE_MAGIC = (b"\x7fELF", b"MZ", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe",
                b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")  # ELF, PE, Mach-O (32/64 bit, both byte orders, fat)
# Headers, build metadata and static archives are never loaded at run time.
NOT_BINARIES = {".h", ".hpp", ".prl", ".pri", ".cmake", ".pc", ".txt", ".json", ".la", ".a", ".lib"}
OPENSSL_ADVISORIES = "https://openssl-library.org/news/vulnerabilities-{series}/"


def owned_by(package):
    listing = subprocess.run(["dpkg", "-L", package], capture_output=True, text=True, check=True).stdout
    return {Path(p) for p in listing.splitlines()}


def scan(root, allowed):
    found = []
    # With a file list, visit exactly those files; walking "/" would reach /proc and friends.
    candidates = sorted(p for p in allowed if str(p).startswith(str(root))) if allowed is not None \
        else Path(root).rglob("*")
    for path in candidates:
        if not path.is_file() or path.is_symlink() or path.suffix.lower() in NOT_BINARIES:
            continue
        with open(path, "rb") as handle:
            if not handle.read(4).startswith(NATIVE_MAGIC):
                continue
        data = path.read_bytes()
        by_name = set()
        for name, (file_pattern, version_pattern) in LIBRARIES.items():
            if re.search(file_pattern, path.name, re.I):
                by_name.add(name)
                match = re.search(version_pattern, data)
                found.append({"library": name, "file": str(path), "linkage": "shared",
                              "version": match.group(1).decode() if match else None})
        for name, (texts, version_pattern, text_proves_copy) in STATIC.items():
            if name in by_name or not any(text in data for text in texts):
                continue
            versions = sorted({m.decode() for m in re.findall(version_pattern, data)})
            # One entry per version: two copies of different versions in one binary are two findings.
            for version in versions or ([None] if text_proves_copy else []):
                found.append({"library": name, "file": str(path), "linkage": "static", "version": version})
    return found


@functools.lru_cache(maxsize=None)  # static and shared copies of one version share a lookup
def openssl_findings(version):
    """High and Critical advisories affecting this OpenSSL version, from openssl-library.org."""
    series = ".".join(version.split(".")[:2])
    request = urllib.request.Request(OPENSSL_ADVISORIES.format(series=series), headers={"User-Agent": "openms-test-lab"})
    with urllib.request.urlopen(request, timeout=60) as response:
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", response.read().decode("utf-8", "replace"))))
    patch = int(re.match(r"\d+\.\d+\.(\d+)", version).group(1))
    findings = []
    for entry in re.split(r"(?=CVE-\d{4}-\d{4,6} Severity)", text):
        head = re.match(r"(CVE-\d{4}-\d{4,6}) Severity (\w+) .*?Title (.*?) (?:Found by|Reported by|Fix developed)", entry)
        if not head:
            continue
        for low, high in re.findall(rf"from {re.escape(series)}\.(\d+) before {re.escape(series)}\.(\d+)", entry[:1500]):
            if int(low) <= patch < int(high):
                findings.append({"cve": head.group(1), "severity": head.group(2).capitalize(),
                                 "title": head.group(3)[:120], "fixed_in": f"{series}.{high}"})
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="directory to scan")
    parser.add_argument("--only-owned-by", help="Debian package whose files alone are scanned (for /usr/lib)")
    parser.add_argument("--file-list", help="text file of installed paths (dpkg -L output); only these are scanned")
    parser.add_argument("--report", default="reports/bundled-libs.json")
    args = parser.parse_args()

    allowed = owned_by(args.only_owned_by) if args.only_owned_by else None
    if args.file_list:
        allowed = {Path(line.strip()) for line in Path(args.file_list).read_text(encoding="utf-8").splitlines() if line.strip()}
    libraries = scan(args.root, allowed)
    blocking = []
    for library in libraries:
        if library["library"] == "OpenSSL" and library["version"]:
            try:
                library["advisories"] = openssl_findings(library["version"])
            except Exception as error:  # an unreachable advisory page is reported, not ignored
                library["advisories_error"] = str(error)
                continue
            serious = [a for a in library["advisories"] if a["severity"] in ("High", "Critical")]
            if serious:
                blocking.append({"file": library["file"], "version": library["version"],
                                 "linkage": library["linkage"], "advisories": serious})
    report = {"root": args.root, "libraries": libraries, "blocking": blocking,
              "status": "failed" if blocking else "passed"}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
    for library in libraries:
        counts = {}
        for advisory in library.get("advisories", []):
            counts[advisory["severity"]] = counts.get(advisory["severity"], 0) + 1
        linkage = "static in" if library["linkage"] == "static" else ""
        print(f"{library['library']:8} {library['version'] or '?':10} {linkage:9} {library['file']}  {counts or ''}")
    for item in blocking:
        for advisory in item["advisories"]:
            print(f"BLOCKING {item['file']} OpenSSL {item['version']} ({item['linkage']}): {advisory['cve']} ({advisory['severity']}) "
                  f"{advisory['title']} -- fixed in {advisory['fixed_in']}")
    print(f"status: {report['status']}; report: {args.report}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
