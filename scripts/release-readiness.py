"""Run the automated part of the release-readiness gate on one Linux machine.

This is what `.github/workflows/release-readiness.yml` runs, and what an agent runs in its
own Linux sandbox (it needs sudo/root for apt). Every phase writes JSON under reports/;
RELEASE-READINESS.md says how each result is judged.

    python3 scripts/release-readiness.py all                  # nightly wheel + nightly DEB
    LAB_PYOPENMS_SPEC=pyopenms==3.6.0 LAB_OPENMS_PACKAGE=release/3.6.0 \\
        python3 scripts/release-readiness.py all              # a release candidate

Phases, in order (each can also be run alone):

  resolve   pick the candidate wheel and DEB, and the previous release as baseline
  desktop   install the DEB, start every tool, run upstream TOPP tests (installed-checks.py)
  python    candidate and baseline pyOpenMS in separate venvs, public API snapshot of each
  source    the OpenMS sources of the candidate's revision, plus the baseline release tag
  docs      user-guide examples on baseline and candidate, API diff, source docs audit
  summary   one Markdown table of every automated check (reports/readiness-summary.md)
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
WORK = ROOT / "downloads" / "readiness"
SRC = WORK / "OpenMS"
DOC_EXTRAS = ["pandas", "matplotlib", "scikit-learn", "seaborn", "tabulate", "requests", "plotly", "xgboost"]
sys.path.insert(0, str(ROOT / "scripts"))


def run(args, check=True, env=None, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=check, env=env, **kwargs)


def state(update=None):
    path = REPORTS / "readiness-state.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if update:
        data.update(update)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "openms-test-lab"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def resolve():
    import resolve_nightly
    spec = os.environ.get("LAB_PYOPENMS_SPEC", "nightly").strip() or "nightly"
    if spec == "nightly":
        wheel = resolve_nightly.wheel()
        candidate = {"spec": wheel["url"], "version": wheel["version"], "sha256": wheel["sha256"]}
    else:
        candidate = {"spec": spec}
    baseline = os.environ.get("LAB_BASELINE", "").strip() or fetch_json("https://pypi.org/pypi/pyopenms/json")["info"]["version"]
    state({"candidate": candidate, "baseline": baseline, "baseline_tag": f"release/{baseline}",
           "openms_package": os.environ.get("LAB_OPENMS_PACKAGE", "nightly")})
    print(json.dumps(state(), indent=2))


def desktop():
    env = dict(os.environ, LAB_OPENMS_PACKAGE=os.environ.get("LAB_OPENMS_PACKAGE", "nightly"))
    run([sys.executable, ROOT / "scripts/unix-lab.py", "native"], env=env)
    result = run([sys.executable, ROOT / "scripts/installed-checks.py"], check=False)
    state({"desktop_exit": result.returncode})


def venv(name, requirement):
    path = WORK / name
    python = path / "bin" / "python"
    if not python.exists():
        run([sys.executable, "-m", "venv", path])
        run([python, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "-q", requirement] + DOC_EXTRAS)
    return python


def python_phase():
    data = state()
    WORK.mkdir(parents=True, exist_ok=True)
    candidate = venv("venv-candidate", data["candidate"]["spec"])
    baseline = venv("venv-baseline", f"pyopenms=={data['baseline']}")
    for python, label in ((candidate, "candidate"), (baseline, "baseline")):
        run([python, ROOT / "scripts/pyopenms-api.py", "snapshot", "--out", REPORTS / f"pyopenms-api-{label}.json"])
    revision = run([candidate, "-c", "import pyopenms; print(pyopenms.VersionInfo.getRevision())"],
                   capture_output=True, text=True).stdout.strip()
    site = run([candidate, "-c", "import pyopenms, pathlib; print(pathlib.Path(pyopenms.__file__).parents[1])"],
               capture_output=True, text=True).stdout.strip()
    # F6 for the wheel: its own directory and the auditwheel/delocate library folder beside it
    for folder in [p for p in Path(site).glob("pyopenms*") if p.is_dir()]:
        run([sys.executable, ROOT / "scripts/bundled-libs.py", folder,
             "--report", REPORTS / f"bundled-libs-wheel-{folder.name}.json"], check=False)
    merged = {"libraries": [], "blocking": []}
    for part in REPORTS.glob("bundled-libs-wheel-*.json"):
        data_part = json.loads(part.read_text(encoding="utf-8"))
        merged["libraries"] += data_part["libraries"]
        merged["blocking"] += data_part["blocking"]
    (REPORTS / "bundled-libs-wheel.json").write_text(json.dumps(merged, indent=1), encoding="utf-8")
    state({"python_candidate": str(candidate), "python_baseline": str(baseline), "wheel_revision": revision})


def source():
    data = state()
    revision = data.get("wheel_revision") or data.get("desktop_revision")
    if not revision:
        raise SystemExit("run the python phase first: the candidate's revision is not known")
    commit = fetch_json(f"https://api.github.com/repos/OpenMS/OpenMS/commits/{revision}")["sha"]
    SRC.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", SRC]
    if not (SRC / ".git").exists():
        run(git + ["init", "-q"])
        run(git + ["remote", "add", "origin", "https://github.com/OpenMS/OpenMS"])
    # Everything the documentation audit reads. The test data is left out (installed-checks
    # fetches what it needs on its own), but not src/tests/CMakeLists.txt and friends, which
    # declare options such as ENABLE_TOPP_TESTING that the audit compares.
    run(git + ["sparse-checkout", "set", "--no-cone", "/*", "!/contrib/", "!/src/tests/topp/",
               "!/src/tests/class_tests/"])
    run(git + ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit])
    run(git + ["checkout", "-q", "FETCH_HEAD"])
    run(git + ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", "tag", data["baseline_tag"]])
    state({"source_commit": commit})


def docs():
    data = state()
    user_guide = SRC / "doc/pyopenms/docs/source/user_guide"
    run([sys.executable, ROOT / "scripts/doc-examples.py", "--python", data["python_baseline"], "--docs", user_guide,
         "--report", REPORTS / "doc-examples-baseline.json"], check=False)
    run([sys.executable, ROOT / "scripts/doc-examples.py", "--python", data["python_candidate"], "--docs", user_guide,
         "--baseline", REPORTS / "doc-examples-baseline.json", "--report", REPORTS / "doc-examples-candidate.json"],
        check=False)
    run([sys.executable, ROOT / "scripts/pyopenms-api.py", "diff", REPORTS / "pyopenms-api-baseline.json",
         REPORTS / "pyopenms-api-candidate.json", "--docs", user_guide, "--changelog", SRC / "CHANGELOG",
         "--out", REPORTS / "pyopenms-api-diff.json"])
    run([sys.executable, ROOT / "scripts/release-docs-audit.py", "--openms", SRC, "--base", data["baseline_tag"],
         "--report", REPORTS / "docs-audit.json"], check=False)


def load(name):
    path = REPORTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def summary():
    rows = []

    def row(check, ok, detail):
        rows.append((check, {True: "PASS", False: "FAIL", None: "NOT RUN"}[ok], detail))

    data = state()
    tools = load("topp-tools.json")
    row("C1 every registered tool starts", None if tools is None else not tools["failed_tools"],
        "no report" if tools is None else f"{tools['registered_tools']} tools, failed {tools['failed_tools']}, "
                                          f"versions {tools['versions_reported']}")
    row("C2 bundled engines start", None if tools is None else not tools["thirdparty_not_started"],
        "no report" if tools is None else f"not started: {tools['thirdparty_not_started']}")
    upstream = load("installed-topp-tests.json")
    row("C3 upstream TOPP and TOPPAS tests on the installed package",
        None if upstream is None else upstream["status"] == "passed" and not upstream.get("replay_notes"),
        "no report" if upstream is None else
        f"{upstream['summary']} of {upstream['selected']} selected; {upstream.get('not_registered', 0)} not "
        f"registered for this package; replay notes: {upstream.get('replay_notes') or 'none'}")
    diff = load("pyopenms-api-diff.json")
    if diff:
        row("D1 removed Python names are in the CHANGELOG", not diff.get("removed_names_not_in_changelog"),
            f"{len(diff['removed_names'])} removed; not in CHANGELOG: {diff.get('removed_names_not_in_changelog')}")
        row("D4 new classes have docstrings", not diff["added_classes_without_docstring"],
            f"without docstring: {diff['added_classes_without_docstring']}")
        row("E4b user guide uses no removed names", not diff.get("docs_using_missing_names"),
            "; ".join(f"{d['page']}:{d['line']} {d['name']}" for d in diff.get("docs_using_missing_names", [])) or "none")
    else:
        row("D1 removed Python names are in the CHANGELOG", None, "no report")
    examples = load("doc-examples-candidate.json")
    if examples:
        regressions = [f"{p['page']}:{p.get('failed_line')}" for p in examples["pages"] if p.get("regression")]
        deprecated = sorted({p["page"] for p in examples["pages"] if p.get("warnings")})
        row("D2 no user-guide page regressed", not regressions, f"{examples['summary']}; regressions: {regressions}")
        row("D3 user guide teaches no deprecated API", not deprecated, f"pages: {deprecated}")
    else:
        row("D2 no user-guide page regressed", None, "no report")
    audit = load("docs-audit.json")
    if audit:
        index = audit["DOC-TOOL-INDEX"]
        row("E1 TOPP index and tool pages complete", not (index["not_listed"] or audit["DOC-TOOL-PAGE"]),
            f"not listed {index['not_listed']}; incomplete pages {sorted(audit['DOC-TOOL-PAGE'])}; twice {index['listed_twice']}")
        tc = audit["DOC-TOOL-CHANGELOG"]
        if "skipped" not in tc:
            row("E2 new/removed tools named in the CHANGELOG",
                not (tc["added_not_in_new_tools_list"] or tc["removed_not_in_removed_tools_list"]),
                f"new tools missing {tc['added_not_in_new_tools_list']}; removed tools missing {tc['removed_not_in_removed_tools_list']}")
        row("E3 no references to removed tools", not audit["DOC-STALE-TOOLS"],
            "; ".join(f"{h['file']}:{h['line']} {h['tool']}" for h in audit["DOC-STALE-TOOLS"][:8]) or "none")
        cb = audit["DOC-CLASS-BRIEF"]
        if "undocumented_main_class" in cb:
            missing = [c["class"] for c in cb["undocumented_main_class"] if not c["internal"]]
            row("E5 new public classes documented", not missing, f"{missing}")
        co = audit["DOC-CMAKE-OPTIONS"]
        if "skipped" not in co:
            row("E6 CMake options documented", not (co["added_undocumented"] or co["removed_still_documented"]),
                f"undocumented {co['added_undocumented']}; removed but documented {co['removed_still_documented']}")
        env_missing = [n for n, v in audit["DOC-ENV-VARS"].items() if not v["documented"]]
        row("E7 environment variables documented", not env_missing, f"{env_missing}")
        cl = audit["CHANGELOG-LINT"]
        row("E8 CHANGELOG clean", not (cl["duplicated_bullets"] or cl["suspicious_short_continuation_lines"]),
            f"'{cl['heading']}'; duplicated {len(cl['duplicated_bullets'])}; orphaned lines {cl['suspicious_short_continuation_lines']}")
        row("A3 version strings agree", not audit["VERSION-STRINGS"]["mismatched"],
            f"expected {audit['VERSION-STRINGS']['expected']}; mismatched {audit['VERSION-STRINGS']['mismatched']}")
    libs = load("bundled-libs.json")
    row("F6 no known-vulnerable bundled OpenSSL (desktop package)", None if libs is None else not libs["blocking"],
        "no report" if libs is None else "; ".join(f"{b['file']} OpenSSL {b['version']}: " +
                                                  ", ".join(a["cve"] for a in b["advisories"]) for b in libs["blocking"]) or
        ", ".join(f"{l['library']} {l['version']}" for l in libs["libraries"] if l["version"]))
    wheel_libs = load("bundled-libs-wheel.json")
    if wheel_libs is not None:
        row("F6 no known-vulnerable bundled OpenSSL (wheel)", not wheel_libs["blocking"],
            ", ".join(f"{l['library']} {l['version']}" for l in wheel_libs["libraries"] if l["version"]))
    revisions = {k: v for k, v in (("wheel", data.get("wheel_revision")), ("desktop", read_desktop_revision())) if v}
    row("A2 artifacts come from one revision", None if len(revisions) < 2 else len(set(revisions.values())) == 1,
        f"{revisions}")

    lines = ["| Check | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {c} | {r} | {d.replace('|', '/')} |" for c, r, d in rows]
    text = (f"### Release readiness: automated Linux checks\n\nCandidate: `{data.get('candidate', {}).get('version') or data.get('candidate', {}).get('spec')}`, "
            f"baseline `{data.get('baseline')}`, source `{data.get('source_commit', '?')[:10]}`\n\n" + "\n".join(lines) + "\n")
    (REPORTS / "readiness-summary.md").write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(text)
    print(text)


def read_desktop_revision():
    checks = load("installed-checks.json") or {}
    commit = checks.get("commit")
    return commit[:7] if commit else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phase", choices=["resolve", "desktop", "python", "source", "docs", "summary", "all"])
    phase = parser.parse_args().phase
    os.chdir(ROOT)
    REPORTS.mkdir(exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    phases = {"resolve": resolve, "desktop": desktop, "python": python_phase, "source": source,
              "docs": docs, "summary": summary}
    for name in (list(phases) if phase == "all" else [phase]):
        if name == "desktop" and os.environ.get("LAB_OPENMS_PACKAGE", "nightly").strip().lower() in ("", "none"):
            continue
        phases[name]()


if __name__ == "__main__":
    main()
