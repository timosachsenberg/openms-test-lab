"""Run the pyOpenMS user-guide code examples against an installed pyOpenMS.

The user guide (OpenMS/doc/pyopenms/docs/source/user_guide/*.rst) is only linted in CI; its
examples are never executed, so an API change can silently break every page that uses it.
This script executes each page's ``.. code-block:: python`` blocks in order, in one fresh
interpreter per page and a scratch working directory, and records

  * the first block that raises, with its .rst line number and the exception;
  * DeprecationWarning/FutureWarning raised by pyOpenMS while the page ran (an example that
    teaches a deprecated API is a documentation bug even if it still works);
  * pages that could not be judged: a missing optional package, a download that failed,
    or a timeout.

Examples download their input from GitHub, so the runner needs network access.

    .venv/bin/python scripts/doc-examples.py --docs OpenMS/doc/pyopenms/docs/source/user_guide
    python scripts/doc-examples.py --python .venv/bin/python --docs ... --pages ms_data chemistry
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

CODE_BLOCK = re.compile(r"^(\s*)\.\. code-block::\s*python\s*$")
# Blocks that are shell sessions or notebook magics rather than Python.
NOT_PYTHON = re.compile(r"^\s*(\$ |!|%|pip install|conda install|>>> )", re.MULTILINE)

HARNESS = r'''
import contextlib, io, json, sys, traceback, warnings
blocks = json.load(open(sys.argv[1], encoding="utf-8"))
result = {"blocks": len(blocks), "executed": 0, "warnings": []}
namespace = {"__name__": "__main__"}
log = open(sys.argv[3], "w", encoding="utf-8")
try:
    import matplotlib
    matplotlib.use("Agg")
except Exception:
    pass
for index, block in enumerate(blocks):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                exec(compile(block["code"], f"{block['page']}:{block['line']}", "exec"), namespace)
            result["executed"] += 1
        except BaseException as error:  # SystemExit from an example counts as a failure too
            result["failed_block"] = index
            result["failed_line"] = block["line"]
            result["exception"] = f"{type(error).__name__}: {error}"[:600]
            result["exception_type"] = type(error).__name__
            result["missing_module"] = getattr(error, "name", None) if isinstance(error, ModuleNotFoundError) else None
            result["traceback"] = traceback.format_exc()[-2500:]
        for item in caught:
            if issubclass(item.category, (DeprecationWarning, FutureWarning, SyntaxWarning)):
                text = f"{item.category.__name__}: {item.message}"
                origin = str(item.filename)
                if "pyopenms" in origin or "pyopenms" in text.lower() or block["page"] in origin:
                    result["warnings"].append({"line": block["line"], "warning": text[:300],
                                               "origin": origin[-120:]})
    if "failed_block" in result:
        break
json.dump(result, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
'''


def extract_blocks(page):
    lines = page.read_text(encoding="utf-8").splitlines()
    blocks, i = [], 0
    while i < len(lines):
        match = CODE_BLOCK.match(lines[i])
        if not match:
            i += 1
            continue
        i += 1
        while i < len(lines) and lines[i].strip().startswith(":") and lines[i].strip() != ":":
            i += 1  # directive options such as :linenos:
        start = i
        while i < len(lines) and (not lines[i].strip() or
                                  len(lines[i]) - len(lines[i].lstrip()) > len(match.group(1))):
            i += 1
        body = lines[start:i]
        indent = min((len(l) - len(l.lstrip()) for l in body if l.strip()), default=0)
        code = "\n".join(l[indent:] for l in body).strip("\n")
        if code and not NOT_PYTHON.search(code):
            blocks.append({"page": page.name, "line": start + 1, "code": code})
    return blocks


def classify(result):
    if result.get("timeout"):
        return "timeout"
    if "failed_block" not in result:
        return "passed" if result.get("executed") else "no-code"
    kind = result.get("exception_type", "")
    missing = result.get("missing_module")
    if kind == "ModuleNotFoundError" and missing and not missing.startswith("pyopenms"):
        return "needs-dependency"
    if kind in ("URLError", "HTTPError", "ConnectionError", "TimeoutError", "RemoteDisconnected",
                "IncompleteRead", "gaierror"):
        return "network"
    return "failed"


def run_page(python, page, timeout):
    blocks = extract_blocks(page)
    if not blocks:
        return {"page": page.name, "status": "no-code", "blocks": 0}
    with tempfile.TemporaryDirectory(prefix=f"doc-{page.stem}-") as work:
        work = Path(work)
        (work / "blocks.json").write_text(json.dumps(blocks), encoding="utf-8")
        (work / "harness.py").write_text(HARNESS, encoding="utf-8")
        started = time.monotonic()
        env = dict(os.environ, MPLBACKEND="Agg", PYTHONDONTWRITEBYTECODE="1")
        try:
            subprocess.run([python, "harness.py", "blocks.json", "result.json", "output.log"],
                           cwd=work, env=env, timeout=timeout, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
            result_file = work / "result.json"
            result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {
                "exception": "harness produced no result (interpreter crashed?)", "failed_block": -1,
                "exception_type": "Crash"}
        except subprocess.TimeoutExpired:
            result = {"timeout": True, "blocks": len(blocks)}
        result["seconds"] = round(time.monotonic() - started, 1)
        log = work / "output.log"
        if result.get("failed_block") is not None and log.exists():
            result["output_tail"] = log.read_text(encoding="utf-8", errors="replace")[-1500:]
    result.update(page=page.name, status=classify(result))
    if "failed_block" in result and 0 <= result["failed_block"] < len(blocks):
        result["failed_code"] = blocks[result["failed_block"]]["code"][:1500]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--docs", required=True, help="the user_guide directory")
    parser.add_argument("--python", default=sys.executable, help="interpreter that has pyOpenMS installed")
    parser.add_argument("--pages", nargs="*", help="page names (without .rst) to run; default all")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per page")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--baseline", help="report of the same pages run against the previous release; "
                        "pages that passed there and fail here are marked as regressions")
    parser.add_argument("--report", default="reports/doc-examples.json")
    args = parser.parse_args()

    pages = sorted(Path(args.docs).glob("*.rst"))
    if args.pages:
        pages = [p for p in pages if p.stem in set(args.pages)]
    version = subprocess.run([args.python, "-c", "import pyopenms; print(pyopenms.__version__)"],
                             capture_output=True, text=True).stdout.strip()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda page: run_page(args.python, page, args.timeout), pages))

    if args.baseline:
        baseline = {p["page"]: p for p in json.loads(Path(args.baseline).read_text(encoding="utf-8"))["pages"]}
        for result in results:
            before = baseline.get(result["page"], {})
            result["baseline_status"] = before.get("status")
            if result["status"] == "failed":
                result["regression"] = before.get("status") == "passed"
    summary = {}
    for result in results:
        summary[result["status"]] = summary.get(result["status"], 0) + 1
    if args.baseline:
        summary["regressions"] = sum(1 for r in results if r.get("regression"))
    report = {"pyopenms": version, "python": args.python, "docs": str(Path(args.docs).resolve()),
              "summary": summary, "pages": results,
              "status": "passed" if not any(r["status"] in ("failed", "timeout") for r in results) else "failed"}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")

    print(f"pyopenms {version}: {summary}")
    for result in results:
        if result["status"] not in ("passed", "no-code"):
            where = f"{result['page']}:{result.get('failed_line', '?')}"
            label = "REGRESSION" if result.get("regression") else result["status"]
            print(f"  {label:17} {where:40} {result.get('exception', '').splitlines()[0][:150] if result.get('exception') else ''}")
    warned = [r for r in results if r.get("warnings")]
    for result in warned:
        first = result["warnings"][0]
        print(f"  deprecated-api    {result['page']}:{first['line']:<34} {first['warning'][:150]}")
    print(f"status: {report['status']}; report: {args.report}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
