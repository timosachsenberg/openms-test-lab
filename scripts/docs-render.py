"""E11: the published documentation of a version renders correctly on Read the Docs.

Read the Docs builds `latest` from the newest develop commit, and pyOpenMS's API reference
from the newest nightly wheel (doc/pyopenms/docs/install_pyopenms.py runs
`pip install --pre pyopenms` against pypi.openms.de); a tag version v<version> from the tag
and that release's wheel. The API pages are generated from the wheel's docstrings, so a
build can succeed and still render them wrongly: in 3.6.0, examples collapsed into one
paragraph, get/set docs were swapped, and methods showed as <nanobind.nb_func object> under
private module names (OpenMS/OpenMS#10599). E9 does not see that: it builds the docs with the
pyopenms release from PyPI, not with the candidate's wheel.

It reads the pages from one of two sources:

  --html DIR       a local Sphinx build: every page, no network. Release readiness builds
                   doc/pyopenms of the candidate's revision with the candidate's wheel, as
                   Read the Docs does, and scans that.
  --version SLUG   the published version on Read the Docs. It records the newest build
                   (finished and successful, its commit, the pyopenms wheel it installed and
                   its Sphinx warning count, from the build log) and scans a sample of pages
                   (--pages sample: the start pages, the user guide, well-known classes and
                   every 20th API page) or all of them (--pages all, throttled: Read the Docs
                   answers a fast crawl with 429).

API reference pages (apidocs/) are scanned for
            nanobind  functions shown as nanobind objects (nb_func, nb_method)
            private   private module names (pyopenms._pyopenms_kernel) in the text
            rest      reST or MyST markup left unrendered outside code: directives
                      (.. code-block::), field lists (:param x:, :return:), doctest prompts
                      (>>>), MyST fences and roles
            cpp       raw C++ types in signatures (std::, OpenMS::, libcpp)
            accessor  a getter documented as a setter or a setter as a getter (advisory: a
                      heuristic on the first sentence)
          and the share of methods without any description; every other page for rest
          findings only (help() output and developer notes name private modules on purpose).

The check passes when no page has a nanobind, private, rest or cpp finding and, online, the
build succeeded. When the newest build installed another wheel than --expect-wheel, the
published pages do not show the candidate, and the check is not run.

    python3 scripts/docs-render.py --html <build>/html --project pyopenms
    python3 scripts/docs-render.py --project pyopenms --version latest --expect-wheel 3.7.0.dev20261017
    python3 scripts/docs-render.py --project pyopenms --version v3.6.0 --pages all
    python3 scripts/docs-render.py --project openms --version latest
"""
import argparse
import concurrent.futures
import html
import json
from pathlib import Path
import re
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
HOSTS = {"pyopenms": "https://pyopenms.readthedocs.io", "openms": "https://openms.readthedocs.io"}
BLOCKING = ("nanobind", "private", "rest", "cpp")

# Visible text: the page's <article>, without scripts, styles, code blocks and inline code
DROP = re.compile(r"<(script|style|pre|code)\b.*?</\1>|<div class=\"highlight[^\"]*\">.*?</div>", re.S)
PATTERNS = {
    "nanobind": re.compile(r"nb_func|nb_method|nanobind\.nb_"),
    "private": re.compile(r"pyopenms\._[a-z]\w*|_pyopenms_kernel"),
    "rest": re.compile(r"(?:^|\s)\.\. [a-z][a-z-]*::"                               # directive
                       r"|(?:^|\s):(?:param|parameter|arg|type|returns?|rtype|raises?)(?:\s[^:\s]+)?:\s"
                       r"|(?:^|\s)>>> "                                              # doctest prompt
                       r"|```\{|:::\{|\{(?:note|warning|code-block|eval-rst)\}"       # MyST
                       r"|(?:^|\s):(?:py:)?(?:class|meth|func|attr|ref|doc):`"),       # unresolved role
    "cpp": re.compile(r"std::|OpenMS::|libcpp"),
}
SIGNATURE = re.compile(r'<dt class="sig sig-object py" id="([^"]+)">(.*?)</dt>\s*<dd>\s*(<p>(.*?)</p>|<dl|</dd>)', re.S)


class Throttle:
    """At most `rate` requests per second across all threads: Read the Docs answers a fast
    crawl with 429 Too Many Requests."""

    def __init__(self, rate):
        self.interval, self.next, self.lock = 1.0 / rate, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            self.next = max(self.next, now) + self.interval
            delay = self.next - self.interval - now
        if delay > 0:
            time.sleep(delay)


THROTTLE = Throttle(3)


def fetch(url, binary=False, attempts=6):
    for attempt in range(attempts):
        THROTTLE.wait()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "openms-test-lab docs-render"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
                return data if binary else data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            if error.code == 404 or attempt == attempts - 1:
                raise
            retry_after = error.headers.get("Retry-After") if error.code == 429 else None
            time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else min(60, 5 * 2 ** attempt))
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(min(60, 5 * 2 ** attempt))


def text_of(fragment):
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def build_info(project, version):
    """The newest build of the version, with the wheel it installed and its Sphinx warnings."""
    builds = json.loads(fetch(f"https://readthedocs.org/api/v3/projects/{project}/versions/{version}/builds/?limit=1"))
    if not builds.get("results"):
        return {"status": "not run", "reason": f"Read the Docs lists no build of {project} {version}"}
    newest = builds["results"][0]
    info = {"id": newest["id"], "state": newest["state"]["code"], "success": newest["success"],
            "commit": newest["commit"], "finished": newest["finished"],
            "url": f"https://app.readthedocs.org/projects/{project}/builds/{newest['id']}/"}
    try:
        detail = json.loads(fetch(f"https://readthedocs.org/api/v2/build/{newest['id']}.json"))
        log = "\n".join((c.get("output") or "") for c in detail.get("commands", []))
        wheel = re.findall(r"Successfully installed[^\n]*?\bpyopenms-(\S+)", log)
        warnings = re.findall(r"build succeeded, (\d+) warnings?", log)
        info.update(pyopenms=wheel[-1] if wheel else None, sphinx_warnings=int(warnings[-1]) if warnings else None)
    except (urllib.error.URLError, ValueError) as error:
        info["log_error"] = str(error)
    return info


def scan(page, api):
    """Findings on one page. Only API reference pages (api) are held to the API rules:
    elsewhere, help() output and developer notes name private modules on purpose."""
    article = re.search(r"<article\b.*?</article>", page, re.S)
    body = article.group(0) if article else page
    visible = text_of(DROP.sub(" ", body))
    findings = {}
    for name, pattern in PATTERNS.items():
        if name != "rest" and not api:
            continue
        if name == "cpp":  # only signatures: prose may name C++ types on purpose
            haystack = " ".join(text_of(m.group(2)) for m in SIGNATURE.finditer(body))
        elif name in ("nanobind", "private"):  # also in signatures and base-class lists
            haystack = text_of(body)
        else:
            haystack = visible
        hits = sorted({m.group(0).strip() for m in pattern.finditer(haystack)})
        if hits:
            findings[name] = hits[:5]
    methods = undocumented = 0
    swapped = []
    for m in SIGNATURE.finditer(body if api else ""):
        name = m.group(1).rsplit(".", 1)[-1]
        if not re.match(r"[a-z]", name) or name.startswith("_"):
            continue
        methods += 1
        summary = text_of(m.group(4) or "").strip()
        if not summary:
            undocumented += 1
        elif (re.match(r"get[A-Z]", name) and re.match(r"Sets?\b", summary)) or \
             (re.match(r"set[A-Z]", name) and re.match(r"(Returns?|Gets?|Checks?)\b", summary)):
            swapped.append(f"{name}: {summary[:80]}")
    if swapped:
        findings["accessor"] = swapped[:5]
    return {"findings": findings, "members": methods, "undocumented": undocumented}


# Pages read with --pages sample, besides the start pages and the user guide
WELL_KNOWN = ["AASequence", "ConsensusMap", "FeatureMap", "MSExperiment", "MSSpectrum", "MzMLFile",
              "PeptideHit", "PeptideIdentification", "ProteinIdentification", "TheoreticalSpectrumGenerator"]


def sample(names):
    api = [n for n in names if n.startswith("apidocs/_autosummary/")]
    chosen = {n for n in names if not n.startswith("apidocs/_autosummary/")}
    chosen |= {n for n in api if n.rsplit(".", 1)[-1] in WELL_KNOWN} | set(api[::20])
    return sorted(chosen)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", choices=sorted(HOSTS), default="pyopenms")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--html", help="a local Sphinx HTML build to scan instead of Read the Docs")
    source.add_argument("--version", default="latest", help="Read the Docs version slug: latest, v<version>, ...")
    parser.add_argument("--pages", choices=["sample", "all"], default="sample", help="online: which pages to read")
    parser.add_argument("--expect-wheel", help="online: the pyopenms version the build must have installed")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--rate", type=float, default=3, help="online: requests per second (default 3)")
    parser.add_argument("--sphinx-log", help="with --html: the build's log, to count its warnings")
    parser.add_argument("--report", help="default: reports/docs-render-<project>-<version or local>.json")
    args = parser.parse_args()
    global THROTTLE
    THROTTLE = Throttle(args.rate)
    label = "local" if args.html else args.version
    report_path = Path(args.report or ROOT / "reports" / f"docs-render-{args.project}-{label}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {"project": args.project, "source": args.html or f"{HOSTS[args.project]}/en/{args.version}/"}
    pages, names, problems = {}, [], []
    if args.html:
        root = Path(args.html)
        files = sorted(p for p in root.rglob("*.html")
                       if not {"_static", "_sources", "_images"} & set(p.relative_to(root).parts)
                       and p.name not in ("genindex.html", "search.html", "py-modindex.html"))
        names = [p.relative_to(root).with_suffix("").as_posix() for p in files]
        for name, path in zip(names, files):
            pages[name] = scan(path.read_text(encoding="utf-8", errors="replace"), name.startswith("apidocs/"))
        if not names:
            report.update(status="not run", reason=f"no HTML pages under {root}")
        if args.sphinx_log and Path(args.sphinx_log).is_file():
            report["sphinx_warnings"] = Path(args.sphinx_log).read_text(errors="replace").count("WARNING")
    else:
        base = report["source"]
        try:
            report["build"] = build_info(args.project, args.version)
            index = fetch(base + "searchindex.js")
            names = json.loads(index[index.index("(") + 1:index.rindex(")")])["docnames"]
            report["pages_published"] = len(names)
            names = names if args.pages == "all" else sample(names)
        except (urllib.error.URLError, ValueError, KeyError) as error:
            report.update(status="not run", reason=f"{type(error).__name__}: {error}")
            names = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(fetch, base + name + ".html"): name for name in names}
            for future in concurrent.futures.as_completed(futures):
                try:
                    pages[futures[future]] = scan(future.result(), futures[future].startswith("apidocs/"))
                except (urllib.error.URLError, TimeoutError) as error:
                    pages[futures[future]] = {"error": str(error)}
        build = report.get("build", {})
        if names:
            if build.get("status") == "not run" or not build.get("success"):
                problems.append(f"the newest build is {build.get('state', 'missing')}, success={build.get('success')}")
            if args.expect_wheel and build.get("pyopenms") and build["pyopenms"] != args.expect_wheel:
                report["reason"] = (f"the newest build installed pyopenms {build['pyopenms']}, not "
                                    f"{args.expect_wheel}: the published pages do not show the candidate")
    if names:
        broken = {n: p["findings"] for n, p in sorted(pages.items()) if p.get("findings")}
        counts = {kind: sum(kind in f for f in broken.values()) for kind in BLOCKING + ("accessor",)}
        members = sum(p.get("members", 0) for p in pages.values())
        undocumented = sum(p.get("undocumented", 0) for p in pages.values())
        unreadable = sorted(n for n, p in pages.items() if "error" in p)
        problems = [f"{counts[k]} pages with {k} findings" for k in BLOCKING if counts[k]] + problems
        if unreadable:
            problems.append(f"{len(unreadable)} pages could not be read")
        status = "failed" if problems else "not run" if report.get("reason") else "passed"
        report.update(status=status, problems=problems, pages=len(names),
                      pages_with_findings=counts, members=members, undocumented=undocumented,
                      undocumented_share=round(undocumented / members, 3) if members else None,
                      unreadable=unreadable[:20], findings=broken)
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print(f"E11 {args.project} {label}: {report['status']}" + (f" ({report.get('reason')})" if report.get("reason") else ""))
    build = report.get("build")
    if build:
        print(f"  build {build.get('id')}: {build.get('state')}, success {build.get('success')}, commit "
              f"{(build.get('commit') or '?')[:10]}, pyopenms {build.get('pyopenms')}, "
              f"{build.get('sphinx_warnings')} Sphinx warnings, finished {build.get('finished')}")
    if names:
        print(f"  {report['pages']} pages read; with findings: {report['pages_with_findings']}; "
              f"{report['undocumented']} of {report['members']} members without a description")
        for problem in report["problems"]:
            print(f"  FAIL: {problem}")
        for name, found in list(report["findings"].items())[:8]:
            print(f"    {name}: {json.dumps(found)[:300]}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
