"""Run upstream TOPP tests against an installed OpenMS instead of a build tree.

OpenMS CI runs its TOPP tests (src/tests/topp/CMakeLists.txt) against the binaries in the
build directory. A package is a different thing: it has to find its shared data, bundled
engines, plugins and runtime libraries from wherever the installer put them. This script
reads the same add_test() definitions, points them at the installed tools, and runs a
selection, so a release is judged by what users install rather than by what CI built.

It needs a checkout of the OpenMS commit the package was built from (the Revision printed by
`FileInfo --help`); only src/tests/topp is read, so a sparse checkout is enough:

    git clone --filter=blob:none --sparse https://github.com/OpenMS/OpenMS
    git -C OpenMS sparse-checkout set src/tests/topp && git -C OpenMS checkout <revision>
    python scripts/installed-topp-tests.py --openms OpenMS --select release-gate
    python scripts/installed-topp-tests.py --openms OpenMS --select 'TOPP_(ProSE|UniPEFF)_'

A test's diff companions (TOPP_X_1_out, which DEPEND on TOPP_X_1) are selected with it, and
the tests it depends on run first. Tests whose command needs something this script cannot
provide (a CMake variable it does not know, a helper executable that is not installed) are
reported as skipped with the reason, never counted as passed.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

WINDOWS = sys.platform.startswith("win")
EXE = ".exe" if WINDOWS else ""
# The release gate's default: every tool new in 3.6, the one-command workflows, the native
# file formats, compressed input, and the adapters of the engines the installers bundle.
RELEASE_GATE = (r"TOPP_(MS1LabeledWorkflow|FeatureLinkerWNet|UniPEFF|OpenSwathInfer|OpenSwathExport|"
                r"OpenSwathPercolatorScoring|OpenSwathPeakMapExtractor|TransitionListEvidenceFilter|"
                r"ParquetConverter|ParquetDiff|ProSE|ProteomicsLFQ|IsobaricWorkflow|OpenSwathWorkflow|"
                r"IDMerger_idparquet|FileFilter_2[5-9]|FileFilter_30|PercolatorAdapter|CometAdapter|"
                r"SageAdapter|SimpleSearchEngine|FileConverter|IDFileConverter|PeakPickerHiRes|"
                r"FeatureFinderCentroided|FeatureFinderMetabo|MapAlignerPoseClustering|FeatureLinkerUnlabeledQT|"
                r"ProteinQuantifier|TextExporter|MzTabExporter)_")
ENGINES = {  # CMake variable -> (THIRDPARTY folder, candidate file names)
    "COMET_BINARY": ("Comet", ["comet.exe", "comet"]), "SAGE_BINARY": ("Sage", ["sage.exe", "sage"]),
    "PERCOLATOR_BINARY": ("Percolator", ["percolator.exe", "percolator"]),
    "MSGFPLUS_BINARY": ("MSGFPlus", ["MSGFPlus.jar"]), "LUCIPHOR_BINARY": ("LuciPHOr2", ["luciphor2.jar"]),
    "MARACLUSTER_BINARY": ("MaRaCluster", ["maracluster.exe", "maracluster"]),
    "SPECTRAST_BINARY": ("SpectraST", ["spectrast.exe", "spectrast"]),
    "XTANDEM_BINARY": ("XTandem", ["tandem.exe", "tandem"]),
}


def strip_comments(text):
    out = []
    for line in text.splitlines():
        quoted, cut = False, len(line)
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                quoted = not quoted
            elif ch == "#" and not quoted:
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def expand_foreach(text):
    """Unroll simple `foreach(var a b c) ... endforeach()` loops, innermost first."""
    pattern = re.compile(r"foreach\s*\(\s*(\w+)\s+([^)]*)\)((?:(?!foreach\s*\().)*?)endforeach\s*\([^)]*\)", re.S | re.I)
    for _ in range(20):
        match = pattern.search(text)
        if not match:
            break
        var, items, body = match.group(1), tokenize(match.group(2)), match.group(3)
        if items and items[0] in ("IN", "RANGE"):
            items = items[2:] if items[0] == "IN" else []  # IN LISTS/ITEMS or RANGE: not unrolled
        unrolled = "\n".join(body.replace("${" + var + "}", item) for item in items)
        text = text[: match.start()] + unrolled + text[match.end():]
    return text


def calls(text, command):
    """Yield (argument string, condition stack) of every `command(...)` call, in file order."""
    conditions, pos = [], 0
    pattern = re.compile(rf"\b(if|elseif|else|endif|{command})\s*\(", re.I)
    while True:
        match = pattern.search(text, pos)
        if not match:
            return
        depth, i, quoted = 1, match.end(), False
        while i < len(text) and depth:
            ch = text[i]
            if ch == '"' and text[i - 1] != "\\":
                quoted = not quoted
            elif not quoted and ch == "(":
                depth += 1
            elif not quoted and ch == ")":
                depth -= 1
            i += 1
        args = text[match.end(): i - 1]
        word = match.group(1).lower()
        if word == "if":
            conditions.append(args.strip())
        elif word in ("elseif", "else") and conditions:
            conditions[-1] = f"not ({conditions[-1]})" + (f" and {args.strip()}" if args.strip() else "")
        elif word == "endif" and conditions:
            conditions.pop()
        elif word == command.lower():
            yield args, list(conditions)
        pos = i


def tokenize(args):
    tokens = []
    for token in re.findall(r'"(?:[^"\\]|\\.)*"|[^\s"]+', args):
        if token.startswith('"'):
            # CMake escapes in quoted arguments: \" \\ \; \$ and \t \n \r
            token = re.sub(r'\\([tnr"\\;$])', lambda m: {"t": "\t", "n": "\n", "r": "\r"}.get(m.group(1), m.group(1)),
                           token[1:-1])
        tokens.append(token)
    return tokens


def load_tests(openms):
    topp = openms / "src/tests/topp"
    sources = [topp / "CMakeLists.txt", topp / "THIRDPARTY/third_party_tests.cmake"]
    tests, order, variables, copies = {}, [], {}, []
    for source in sources:
        if not source.exists():
            continue
        text = expand_foreach(strip_comments(source.read_text(encoding="utf-8", errors="replace")))
        for args, _ in calls(text, "set"):
            tokens = tokenize(args)
            if tokens and re.fullmatch(r"[A-Z][A-Z0-9_]*", tokens[0]) and "CACHE" not in tokens and "PARENT_SCOPE" not in tokens:
                variables.setdefault(tokens[0], tokens[1:])
        for args, _ in calls(text, "configure_file"):
            tokens = tokenize(args)
            if len(tokens) >= 2 and "COPYONLY" in tokens:
                copies.append((tokens[0], tokens[1]))
        for args, conditions in calls(text, "add_test"):
            tokens = tokenize(args)
            if not tokens:
                continue
            if tokens[0] == "NAME" and "COMMAND" in tokens:
                name, command = tokens[1], tokens[tokens.index("COMMAND") + 1:]
            else:
                name, command = tokens[0], tokens[1:]
            tests[name] = {"name": name, "command": command, "conditions": conditions, "depends": [],
                           "will_fail": False, "pass_regex": None, "fail_regex": None, "skip_code": None,
                           "source": source.name}
            order.append(name)
        for args, _ in calls(text, "set_tests_properties"):
            tokens = tokenize(args)
            if "PROPERTIES" not in tokens:
                continue
            names, props = tokens[: tokens.index("PROPERTIES")], tokens[tokens.index("PROPERTIES") + 1:]
            for key, value in zip(props[::2], props[1::2]):
                for name in names:
                    if name not in tests:
                        continue
                    if key == "DEPENDS":
                        tests[name]["depends"] += [d for d in value.split(";") if d]
                    elif key == "WILL_FAIL":
                        tests[name]["will_fail"] = value.upper() in ("1", "ON", "TRUE", "YES")
                    elif key == "PASS_REGULAR_EXPRESSION":
                        tests[name]["pass_regex"] = value
                    elif key == "FAIL_REGULAR_EXPRESSION":
                        tests[name]["fail_regex"] = value
                    elif key == "SKIP_RETURN_CODE":
                        tests[name]["skip_code"] = int(value) if value.isdigit() else None
    return tests, order, variables, copies


def expand(tokens, variables, missing, depth=0):
    out = []
    for token in tokens:
        whole = re.fullmatch(r"\$\{(\w+)\}", token)
        value = variables.get(whole.group(1)) if whole else None
        if whole and isinstance(value, list) and depth < 5:
            # A variable holding a list (DIFF, OLD_OSW_PARAM) expands to several arguments.
            out += expand(value, variables, missing, depth + 1)
            continue

        def substitute(match):
            found = variables.get(match.group(1))
            if found is None:
                missing.add(match.group(1))
                return match.group(0)
            return found if isinstance(found, str) else ";".join(expand(found, variables, missing, depth + 1))
        out.append(re.sub(r"\$\{(\w+)\}", substitute, token))
    return out


def resolve(test, variables):
    missing = set()
    command = expand(test["command"], variables, missing)
    return command, sorted(missing)


def select(tests, order, pattern):
    chosen = {n for n in order if re.search(pattern, n)}
    changed = True
    while changed:  # add what the chosen tests depend on, and the diff tests that depend on them
        changed = False
        for name in order:
            test = tests[name]
            if name in chosen:
                new = {d for d in test["depends"] if d in tests} - chosen
            elif any(d in chosen for d in test["depends"]):
                new = {name}
            else:
                new = set()
            if new:
                chosen |= new
                changed = True
    return [n for n in order if n in chosen]


def run_group(names, tests, variables, work, timeout, bin_dir, results):
    for name in names:
        test = tests[name]
        failed_deps = [d for d in test["depends"] if results.get(d, {}).get("status") not in (None, "passed")]
        command, missing = resolve(test, variables)
        result = {"test": name, "conditions": test["conditions"], "source": test["source"]}
        executable = Path(command[0]) if command else None
        # Inputs are read from the source checkout; outputs go to the scratch directory. An
        # input the checkout lacks (e.g. class-test data outside src/tests/topp) is a limit
        # of this harness, not a failure of the package.
        absent = [t for t in command[1:] if t.startswith(str(variables["OPENMS_HOST_DIRECTORY"]))
                  and not Path(t).exists()]
        if missing:
            result.update(status="skipped", reason=f"unknown CMake variables {missing}")
        elif absent:
            result.update(status="skipped", reason=f"input not in the source checkout: {Path(absent[0]).name}")
        elif failed_deps:
            result.update(status="skipped", reason=f"depends on {failed_deps}, which did not pass")
        elif executable is None or not (executable.is_file() or shutil.which(str(executable))):
            result.update(status="skipped", reason=f"executable not installed: {command[0] if command else ''}")
        else:
            started = time.monotonic()
            try:
                completed = subprocess.run(command, cwd=work, capture_output=True, text=True, errors="replace",
                                           timeout=timeout, stdin=subprocess.DEVNULL,
                                           env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
                output = completed.stdout + completed.stderr
                if test["pass_regex"] is not None:  # like ctest: the regex decides, the exit code does not
                    ok = re.search(test["pass_regex"], output) is not None
                else:
                    ok = (completed.returncode != 0) if test["will_fail"] else (completed.returncode == 0)
                if test["fail_regex"] is not None and re.search(test["fail_regex"], output):
                    ok = False
                status = "passed" if ok else "failed"
                if test["skip_code"] is not None and completed.returncode == test["skip_code"]:
                    status = "passed"  # ctest reports it as skipped by design; the tool behaved as specified
                result.update(status=status, exit=completed.returncode)
                if status == "failed":
                    result["output_tail"] = "\n".join(output.strip().splitlines()[-40:])
                    if test["pass_regex"] is not None:  # show what the expected line said instead
                        words = [w for w in re.findall(r"[A-Za-z]{4,}", test["pass_regex"])][:2]
                        result["near_expected"] = [l for l in output.splitlines() if words and all(w in l for w in words)][:5]
            except subprocess.TimeoutExpired:
                result.update(status="failed", reason=f"timeout after {timeout}s")
            result["seconds"] = round(time.monotonic() - started, 1)
            result["command"] = " ".join(command)
        results[name] = result


def fetch_missing_inputs(openms, selected, variables):
    """Add inputs outside src/tests/topp (class-test data) to a sparse checkout, file by file."""
    wanted = set()
    for test in selected:
        command, _ = resolve(test, variables)
        for token in command[1:]:
            path = Path(token)
            if token.startswith(str(openms)) and not path.exists() and "tmp" not in path.name:
                wanted.add("/" + path.relative_to(openms).as_posix())
    if not wanted or not (openms / ".git").exists():
        return
    try:
        subprocess.run(["git", "-C", str(openms), "sparse-checkout", "add", *sorted(wanted)], check=True)
    except subprocess.CalledProcessError as error:  # e.g. a cone-mode checkout; tests are then skipped
        print(f"could not add {len(wanted)} inputs to the sparse checkout: {error}")


def components(names, tests):
    """Split the selection into groups that share no dependency, keeping file order inside a group."""
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    first_of_tool = {}
    for name in names:
        for dep in tests[name]["depends"]:
            if dep in parent:
                parent[find(name)] = find(dep)
        # Tests of one tool often share files in the temp directory without declaring it,
        # so a tool's tests run one after another; different tools still run in parallel.
        tool = re.match(r"(TOPP_[A-Za-z0-9]+)", name)
        key = tool.group(1) if tool else name
        if key in first_of_tool:
            parent[find(name)] = find(first_of_tool[key])
        else:
            first_of_tool[key] = name
    groups = {}
    for name in names:
        groups.setdefault(find(name), []).append(name)
    return list(groups.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--openms", required=True, help="OpenMS checkout at the package's revision")
    parser.add_argument("--bin-dir", help="installed bin directory; default: where FileInfo is on PATH")
    parser.add_argument("--share-dir", help="installed share/OpenMS; default: next to bin, or /usr/share/OpenMS")
    parser.add_argument("--select", default="release-gate", help="regex on test names, 'release-gate' or 'all'")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--fetch-missing", action="store_true",
                        help="add inputs outside src/tests/topp to the (non-cone) sparse checkout")
    parser.add_argument("--report", default="reports/installed-topp-tests.json")
    args = parser.parse_args()

    openms = Path(args.openms).resolve()
    bin_dir = Path(args.bin_dir) if args.bin_dir else Path(shutil.which("FileInfo") or "").resolve().parent
    if not (bin_dir / f"FileInfo{EXE}").is_file():
        raise SystemExit("installed FileInfo not found; pass --bin-dir")
    share = next((Path(p) for p in [args.share_dir, bin_dir.parent / "share/OpenMS", "/usr/share/OpenMS",
                                     bin_dir.parent / "Resources/share/OpenMS"] if p and (Path(p) / "CHEMISTRY").is_dir()), None)
    if share is None:
        raise SystemExit("installed share/OpenMS not found; pass --share-dir")

    # Mirror the build tree's layout: tests run in the test binary directory and several
    # write to a relative "tmp_path/..." as well as to ${TESTS_TEMP_DIR}.
    work = Path(tempfile.mkdtemp(prefix="installed-topp-"))
    (work / "tmp_path").mkdir()
    topp = openms / "src/tests/topp"
    tests, order, defined, copies = load_tests(openms)
    variables = {name: value for name, value in defined.items()}
    variables.update({
        "TOPP_BIN_PATH": str(bin_dir), "DATA_DIR_TOPP": str(topp), "DATA_DIR_SHARE": str(share),
        "DATA_DIR_TOPP_BIN": str(work), "TESTS_TEMP_DIR": str(work / "tmp_path"),
        "DIFF": [str(bin_dir / f"FuzzyDiff{EXE}"), "-test", "-ini", str(topp / "FuzzyDiff.ini")],
        # build-tree locations some tests name directly
        "CMAKE_CURRENT_SOURCE_DIR": str(topp), "PROJECT_SOURCE_DIR": str(topp),
        "CMAKE_BINARY_DIR": str(work), "CMAKE_CURRENT_BINARY_DIR": str(work), "PROJECT_BINARY_DIR": str(work),
        "OPENMS_HOST_DIRECTORY": str(openms),
    })
    if shutil.which("cmake"):
        variables["CMAKE_COMMAND"] = shutil.which("cmake")
    for source, target in copies:  # inputs the build stages with configure_file(... COPYONLY)
        (src,), (dst,) = expand([source], variables, set()), expand([target], variables, set())
        if Path(src).is_file() and "${" not in dst:
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    for variable, (folder, candidates) in ENGINES.items():
        found = next((share / "THIRDPARTY" / folder / c for c in candidates
                      if (share / "THIRDPARTY" / folder / c).is_file()), None)
        if found:
            variables[variable] = str(found)

    pattern = {"release-gate": RELEASE_GATE, "all": "."}.get(args.select, args.select)
    chosen = select(tests, order, pattern)
    if args.fetch_missing:
        fetch_missing_inputs(openms, [tests[n] for n in chosen], variables)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda group: run_group(group, tests, variables, work, args.timeout, bin_dir, results),
                      components(chosen, tests)))

    ordered = [results[n] for n in chosen]
    summary = {}
    for result in ordered:
        summary[result["status"]] = summary.get(result["status"], 0) + 1
    report = {"openms": str(openms), "bin_dir": str(bin_dir), "share_dir": str(share), "selection": pattern,
              "defined_tests": len(order), "selected": len(chosen), "summary": summary, "tests": ordered,
              "status": "passed" if not summary.get("failed") else "failed"}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)

    print(f"{len(chosen)} of {len(order)} upstream TOPP tests selected: {summary}")
    for result in ordered:
        if result["status"] == "failed":
            last = (result.get("output_tail") or result.get("reason") or "").splitlines()[-1:] or [""]
            print(f"  FAILED  {result['test']}: {last[0][:160]}")
    skipped = {}
    for result in ordered:
        if result["status"] == "skipped":
            skipped[result["reason"][:90]] = skipped.get(result["reason"][:90], 0) + 1
    for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  skipped x{count}: {reason}")
    print(f"status: {report['status']}; report: {args.report}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
