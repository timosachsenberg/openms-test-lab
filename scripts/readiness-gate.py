"""Pin one OpenMS nightly to its commit, and turn the lab results for it into one verdict.

`.github/workflows/nightly-readiness.yml` runs this at both ends:

  resolve   find the nightly built from OPENMS_SHA (blank: the newest complete nightly) and pin
            its files: the four installers of its archive folder and the four wheels of the same
            night on pypi.openms.de, each as an exact URL. Writes reports/candidate.json and the
            job outputs the labs take as inputs.
  verdict   read every lab's job result and reports and decide the automated blocking checks of
            RELEASE-READINESS.md for that commit. Writes reports/gate.json and reports/gate.md;
            exits 1 unless every blocking check passed.
  newest    print the commit of the newest complete nightly (for the daily schedule).

The archive and the wheel index are organised by date, not by commit: a nightly built on a UTC
day lands in that day's folder and gets that day's .dev version, and a second nightly on the same
day overwrites both. `resolve` therefore takes the date from the OpenMS runs that built the commit
and refuses a commit whose files a later nightly replaced; `verdict` then checks the revision every
lab actually installed (A2).

The verdict covers what scripts can decide and names every check it left open. The judgement
checks (D5, E4), the static checks run by hand and the human checks (H) stay with the readiness
report in readiness/.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
sys.path.insert(0, str(ROOT / "scripts"))
import resolve_nightly  # noqa: E402

API = "https://api.github.com/repos/OpenMS/OpenMS"
INSTALLERS = {"windows": "-Win64.exe", "macos": "-macOS-Silicon.pkg",
              "linux_x64": "-Debian-Linux-x86_64.deb", "linux_arm": "-Debian-Linux-aarch64.deb"}
WHEELS = {"windows": lambda tag: tag == "win_amd64",
          "macos": lambda tag: tag.startswith("macosx") and tag.endswith("_arm64"),
          "linux_x64": lambda tag: tag.startswith("manylinux") and tag.endswith("_x86_64"),
          "linux_arm": lambda tag: tag.startswith("manylinux") and tag.endswith("_aarch64")}

# RELEASE-READINESS.md: checks that block, and those that block only at release. Rows whose ID is
# not listed (advisory checks, and sub-checks such as E4b) are reported without blocking.
BLOCKING = {"A1", "A2", "C1", "C2", "C3", "C5", "C6", "C9", "D1", "D2", "D5", "D6", "E2", "E4", "E9", "E11",
            "F1", "F2", "F5", "F6", "F7", "F8", "F11"}
AT_RELEASE = {"A3", "E8"}
# Every check of readiness/TEMPLATE.md, to name the ones a run left to the readiness report.
STANDARD = (["A1", "A2", "A3", "B1", "B2", "B3", "B5", "B6", "B7", "B8", "B9"]
            + [f"C{i}" for i in range(1, 11)] + [f"D{i}" for i in range(1, 7)] + [f"E{i}" for i in range(1, 12)]
            + [f"F{i}" for i in range(1, 12)] + [f"G{i}" for i in range(1, 10)] + [f"H{i}" for i in range(1, 5)])
# What the per-platform row of a lab that installs the desktop package decides (installed-checks.py).
DESKTOP_CHECKS = {"C1", "C2", "C3", "C5", "C9", "F6"}
# The nightly container image (C10): built from the nightly branch like the installers, but under the
# moving tag latest, so resolve pins its digest and the verdict checks the revision it was built from.
IMAGE = "ghcr.io/openms/openms-tools-thirdparty"

# The release matrix for 3.6 (RELEASE-READINESS.md): job id, check, run, platform whose installed
# desktop package the run checks (None for wheel-only runs).
LABS = [
    ("windows-312", "B1", "Windows 3.12, wheel + installer", "Windows"),
    ("windows-314", "B2", "Windows 3.14, wheel", None),
    ("macos-312", "B3", "macOS arm64 3.12, wheel + pkg", "macOS"),
    ("macos-314", "B5", "macOS arm64 3.14, wheel", None),
    ("linux-x64", "B6", "Linux x64 3.12, wheel + DEB", "Linux x64"),
    ("linux-arm", "B7", "Linux arm64 3.12, wheel + DEB", "Linux arm64"),
    ("linux-2204", "B8", "Linux 22.04 3.12, wheel", None),
    ("linux-314", "B9", "Linux x64 3.14, wheel", None),
]


class Unpinnable(Exception):
    """The commit has no complete set of nightly files that can be tested."""


def github(path):
    request = urllib.request.Request(API + path, headers={"User-Agent": "openms-test-lab",
                                                           "Accept": "application/vnd.github+json"})
    if os.environ.get("GH_TOKEN"):
        request.add_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def nightly_runs(workflow):
    """The last 50 runs of an OpenMS workflow on the nightly branch, newest first."""
    return github(f"/actions/workflows/{workflow}/runs?branch=nightly&per_page=50")["workflow_runs"]


def newest_complete(builds, wheels):
    built = {run["head_sha"] for run in wheels if run["conclusion"] == "success"}
    for run in builds:
        if run["conclusion"] == "success" and run["head_sha"] in built:
            return run["head_sha"]
    raise Unpinnable("no nightly in the last 50 has both its installers and its wheels built")


def run_for(runs, sha, what, notes):
    """The newest nightly run of `what` for this commit, and the UTC day its files are filed under."""
    matching = [run for run in runs if run["head_sha"] == sha]
    if not matching:
        raise Unpinnable(f"no {what} run on the nightly branch built {sha[:10]}: it is not a nightly "
                         "(a release-branch commit, or older than the last 50 nights)")
    run = matching[0]
    if run["status"] != "completed":
        raise Unpinnable(f"the {what} run for {sha[:10]} is still {run['status']}: {run['html_url']}")
    if run["conclusion"] != "success":
        raise Unpinnable(f"the {what} run for {sha[:10]} ended {run['conclusion']}: {run['html_url']}")
    day = run["created_at"][:10]
    for later in runs:
        if later["created_at"][:10] != day or later["created_at"] <= run["created_at"] or later["head_sha"] == sha:
            continue
        if later["status"] != "completed" or later["conclusion"] == "success":
            raise Unpinnable(f"a later {what} run on {day} built {later['head_sha'][:10]} and replaces this "
                             f"nightly's files ({later['html_url']}); test that commit instead")
        notes.append(f"a later {what} run on {day} for {later['head_sha'][:10]} ended {later['conclusion']} "
                     "and may have replaced some files; A2 shows which revision each lab installed")
    return run, day


def pin_installers(folder):
    url = f"{resolve_nightly.DESKTOP_INDEX}{folder}/"
    try:
        names = set(re.findall(r'href="([^"?/]+)"', resolve_nightly.fetch(url)))
    except OSError as error:
        raise Unpinnable(f"cannot list {url}: {error}")
    pinned = {}
    for platform, suffix in INSTALLERS.items():
        matches = sorted(name for name in names if name.endswith(suffix))
        if len(matches) != 1:
            raise Unpinnable(f"A1: {url} holds {len(matches)} files ending {suffix}, not exactly one: {matches}")
        pinned[platform] = url + urllib.parse.quote(matches[0])
    return pinned


def pin_wheels(version_suffix):
    index = resolve_nightly.WHEEL_INDEX
    try:
        entries = re.findall(r'href="([^"#]+)#sha256=([0-9a-f]{64})"', resolve_nightly.fetch(index))
    except OSError as error:
        raise Unpinnable(f"cannot list {index}: {error}")
    pinned = {}
    for platform, accepts in WHEELS.items():
        matches = []
        for href, digest in entries:
            name = href.rsplit("/", 1)[-1]
            parts = name[: -len(".whl")].split("-") if name.endswith(".whl") else []
            if len(parts) >= 5 and parts[1].endswith(version_suffix) and accepts(parts[-1]):
                # pip verifies the sha256 fragment, so the digest is enforced, not only recorded
                matches.append(f"{urllib.parse.urljoin(index, href)}#sha256={digest}")
        if len(matches) != 1:
            raise Unpinnable(f"A1: {index} lists {len(matches)} {platform} wheels of version *{version_suffix}, "
                             "not exactly one")
        pinned[platform] = matches[0]
    return pinned


def pin_container(notes):
    """The digest the nightly image tag points at now, or none (C10 is advisory: no reason to stop)."""
    repository = IMAGE.split("/", 1)[1]
    accept = ", ".join(f"application/vnd.{kind}" for kind in (
        "oci.image.index.v1+json", "docker.distribution.manifest.list.v2+json",
        "oci.image.manifest.v1+json", "docker.distribution.manifest.v2+json"))
    try:
        with urllib.request.urlopen(f"https://ghcr.io/token?scope=repository:{repository}:pull", timeout=60) as response:
            token = json.load(response)["token"]
        request = urllib.request.Request(f"https://ghcr.io/v2/{repository}/manifests/latest", method="HEAD",
                                         headers={"Authorization": f"Bearer {token}", "Accept": accept})
        with urllib.request.urlopen(request, timeout=60) as response:
            digest = response.headers["Docker-Content-Digest"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest or ""):
            raise ValueError(f"unexpected digest {digest!r}")
    except (OSError, KeyError, ValueError) as error:
        notes.append(f"C10: cannot pin {IMAGE}:latest ({error}); the container image is not checked")
        return "none"
    return f"{IMAGE}@{digest}"


def output(values):
    if not os.environ.get("GITHUB_OUTPUT"):
        return
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                raise ValueError(f"output {key} spans lines")
            handle.write(f"{key}={value}\n")


def summarize(text):
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def resolve():
    wanted = os.environ.get("OPENMS_SHA", "").strip().lower()
    stage = os.environ.get("STAGE", "").strip() or "nightly"
    notes = []
    REPORTS.mkdir(exist_ok=True)
    try:
        if wanted and not re.fullmatch(r"[0-9a-f]{7,40}", wanted):
            raise Unpinnable(f"openms_sha must be a commit SHA (7 to 40 hex digits), not {wanted!r}")
        builds = nightly_runs("release.yml")
        wheels = nightly_runs("pyopenms-wheels-cibuildwheel.yml")
        if wanted:
            sha = next((run["head_sha"] for run in builds if run["head_sha"].startswith(wanted)), wanted)
        else:
            sha = newest_complete(builds, wheels)
        build, build_day = run_for(builds, sha, "release.yml", notes)
        wheel_run, wheel_day = run_for(wheels, sha, "pyopenms-wheels-cibuildwheel.yml", notes)
        folder = build_day.replace("-", ".")
        version_suffix = ".dev" + wheel_day.replace("-", "")
        installers = pin_installers(folder)
        wheel_files = pin_wheels(version_suffix)
        container = pin_container(notes)
    except Unpinnable as error:
        (REPORTS / "candidate.json").write_text(json.dumps({"requested": wanted, "error": str(error)}, indent=2),
                                                encoding="utf-8")
        output({"error": str(error)})
        summarize(f"### Nightly readiness: nothing to test\n\n{error}\n")
        print(f"::error::{error}")
        return 1
    candidate = {"sha": sha, "stage": stage, "nightly_date": folder, "wheel_version": version_suffix[1:],
                 "release_run": build["html_url"], "wheel_run": wheel_run["html_url"],
                 "installers": installers, "wheels": wheel_files, "container_image": container, "notes": notes}
    (REPORTS / "candidate.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    output({"sha": sha, "nightly_date": folder, "candidate": json.dumps(candidate, separators=(",", ":")),
            "exe": installers["windows"], "pkg": installers["macos"],
            "deb_x64": installers["linux_x64"], "deb_arm": installers["linux_arm"],
            "wheel_windows": wheel_files["windows"], "wheel_macos": wheel_files["macos"],
            "wheel_linux_x64": wheel_files["linux_x64"], "wheel_linux_arm": wheel_files["linux_arm"],
            "container_image": container})
    files = "\n".join(f"- `{url.split('#')[0].rsplit('/', 1)[-1]}`" for url in [*installers.values(), *wheel_files.values()])
    summarize(f"### Nightly readiness: OpenMS `{sha[:10]}`, nightly {folder}\n\n"
              f"[installers built]({build['html_url']}) · [wheels built]({wheel_run['html_url']}) · stage `{stage}`\n\n"
              f"{files}\n" + "".join(f"\n> {note}\n" for note in notes))
    return 0


def load(folder, name):
    path = folder / name if folder else None
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def artifact(artifacts, prefix=None, job=None):
    """The downloaded artifact folder starting with `prefix`, or the lab reports a job uploaded."""
    folders = sorted(p for p in artifacts.iterdir() if p.is_dir()) if artifacts.is_dir() else []
    if prefix:
        return next((p for p in folders if p.name.startswith(prefix)), None)
    mine = [p for p in folders if p.name.endswith(f"-{job}")]
    # The final reports, uploaded after the (skipped) SSH step, else those uploaded before it.
    return next((p for marker in ("-lab-reports-", "-lab-setup-reports-") for p in mine if marker in p.name), None)


def short(value, limit=240):
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def desktop_detail(folder, checks):
    if not checks:
        return "no installed-checks.json"
    if checks.get("status") == "skipped":
        return checks.get("reason", "skipped")
    parts = []
    tools = load(folder, "topp-tools.json")
    if tools:
        parts.append(f"C1/C2 {tools.get('registered_tools')} tools, failed {short(tools.get('failed_tools'), 80)}, "
                     f"engines not started {short(tools.get('thirdparty_not_started'), 80)}")
    upstream = load(folder, "installed-topp-tests.json")
    if upstream:
        parts.append(f"C3 {upstream.get('summary')} of {upstream.get('selected')} ({upstream.get('status')})")
    elif checks.get("upstream_tests"):
        parts.append(f"C3 {checks['upstream_tests']}: {short(checks.get('reason', ''), 120)}")
    parts.append(f"C5 Thermo {(checks.get('thermo') or {}).get('status', '?')}")
    openmp = checks.get("openmp") or {}
    parts.append(f"C9 OpenMP {openmp.get('openmp') or openmp.get('status', '?')}")
    parts.append(f"F6 exit {checks.get('bundled_libs_exit')}")
    return "; ".join(parts)


def readiness_rows(folder):
    """The rows of readiness-summary.md as (check, result, detail), or None without a summary."""
    path = folder / "readiness-summary.md" if folder else None
    if not path or not path.exists():
        return None
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip()[1:-1].split("|")] if line.startswith("| ") else []
        if len(cells) == 3 and cells[0] != "Check" and not cells[0].startswith("---"):
            rows.append(tuple(cells))
    return rows


def verdict(artifacts):
    needs = json.loads(os.environ.get("NEEDS_JSON") or "{}")
    stage = os.environ.get("STAGE", "").strip() or "nightly"
    resolved = needs.get("resolve", {})
    outputs = resolved.get("outputs") or {}
    candidate = json.loads(outputs["candidate"]) if outputs.get("candidate") else {}
    sha = candidate.get("sha", "")
    rows, revisions = [], []

    def row(check, name, ok, detail, blocking=None, evidence=""):
        if blocking is None:
            blocking = check in BLOCKING or (stage == "release" and check in AT_RELEASE)
        rows.append({"check": check, "name": name, "result": {True: "PASS", False: "FAIL"}.get(ok, "NOT RUN"),
                     "blocking": blocking, "detail": detail, "evidence": evidence})

    def job_ok(job):
        result = needs.get(job, {}).get("result")
        return {"success": True, "failure": False}.get(result), result or "missing"

    if resolved.get("result") == "success" and sha:
        row("A1", "The artifact set is complete", True,
            f"nightly {candidate['nightly_date']}: 4 installers, 4 wheels {candidate['wheel_version']}",
            evidence=candidate["release_run"])
        row("D6", "The wheel's own tests passed for this revision", True, "pyopenms-wheels-cibuildwheel.yml succeeded",
            evidence=candidate["wheel_run"])
    else:
        row("A1", "The artifact set is complete", False, outputs.get("error") or f"resolve job {resolved.get('result')}")
        row("D6", "The wheel's own tests passed for this revision", None, "no pinned candidate")

    for job, check, name, platform in LABS:
        ok, result = job_ok(job)
        folder = artifact(artifacts, job=job)
        smoke = load(folder, "python-smoke.json") or {}
        if smoke.get("revision"):
            revisions.append((f"{name} (wheel)", smoke["revision"]))
        row(check, name, ok, f"job {result}; pyOpenMS {smoke.get('pyopenms', '?')} smoke {smoke.get('status', '?')}",
            blocking=True)
        if platform:
            checks = load(folder, "installed-checks.json")
            if checks and checks.get("commit"):
                revisions.append((f"{platform} installer", checks["commit"]))
            status = (checks or {}).get("status")
            row("C", f"Installed desktop package on {platform} (C1–C3, C5, C9, F6)",
                {"passed": True, "failed": False}.get(status), desktop_detail(folder, checks), blocking=True)
        if platform and platform.startswith("Linux"):
            deb = load(folder, "deb-distributions.json")
            row("C6", f"The DEB installs where it claims to ({platform})",
                {"passed": True, "failed": False}.get((deb or {}).get("status")),
                "no deb-distributions.json" if deb is None else "; ".join(
                    f"{d['image']} {d['expect']}: {d['status']}" for d in deb.get("distributions", [])))

    folder = artifact(artifacts, prefix="release-readiness-reports-")
    ok, result = job_ok("readiness")
    summary = readiness_rows(folder)
    # Its checks report failures without failing the job, so a failed job means a phase stopped
    # (install, python, source, docs) and that phase's checks are missing from the summary.
    row("R", "Release readiness ran every phase", ok,
        f"job {result}" + ("" if summary is not None else "; no readiness-summary.md"), blocking=True)
    for check, result_text, detail in summary or []:
        ident = check.split()[0]
        if ident in ("A2", "C10"):  # decided below: across every lab, and against the image's revision
            continue
        row(ident, f"{check[len(ident):].strip()} (release readiness)", {"PASS": True, "FAIL": False}.get(result_text),
            detail)
    state = load(folder, "readiness-state.json") or {}
    if state.get("wheel_revision"):
        revisions.append(("Linux x64 wheel (release readiness)", state["wheel_revision"]))
    checks = load(folder, "installed-checks.json") or {}
    if checks.get("commit"):
        revisions.append(("Linux x64 DEB (release readiness)", checks["commit"]))

    revisions = [(where, rev.strip().lower()) for where, rev in revisions if len(rev.strip()) >= 7]
    if not sha or not revisions:
        row("A2", "All artifacts come from one revision", None, "no pinned commit" if not sha else "no lab reported a revision")
    else:
        other = [f"{where} {rev[:10]}" for where, rev in revisions if not (sha.startswith(rev) or rev.startswith(sha))]
        row("A2", "All artifacts come from one revision", not other,
            f"{len(revisions)} revisions checked against {sha[:10]}" + (f"; different: {', '.join(other)}" if other else ""))

    def container_row(platform, report, job):
        name = f"The container image works like an installed package ({platform})"
        if report is None:
            image = candidate.get("container_image")
            return row("C10", name, None, "image not pinned" if image in (None, "none") else f"no container-checks.json "
                       f"(job {job_ok(job)[1]})")
        revision = ((report.get("installed") or {}).get("revision") or "").lower()
        if sha and revision and not (sha.startswith(revision) or revision.startswith(sha)):
            return row("C10", name, None, f"{report.get('digest') or report.get('image')} was built from "
                       f"{revision[:10]}, not from the candidate")
        row("C10", name, {"passed": True, "failed": False}.get(report.get("status")),
            f"{report.get('digest') or report.get('image')}, revision {revision[:10] or '?'}: "
            + "; ".join(f"{step} {report[step]['status']}" for step in ("pristine", "installed", "options") if step in report))

    container_row("x64, release readiness", load(folder, "container-checks.json"), "readiness")
    container_row("arm64", load(artifact(artifacts, job="container-arm"), "container-checks.json"), "container-arm")

    ok, result = job_ok("pkg-relocation")
    row("C8", "A macOS upgrade installs the apps into the candidate's folder (run 10)", ok,
        f"job {result}; F11 itself blocks through the release readiness row")

    failures = [r for r in rows if r["blocking"] and r["result"] != "PASS"]
    decision = "FAIL" if failures else "PASS"
    decided = {r["check"] for r in rows if r["result"] != "NOT RUN"}
    if "C" in decided:
        decided |= DESKTOP_CHECKS
    not_decided = [check for check in STANDARD if check not in decided]
    run = os.environ.get("RUN_URL", "")
    gate = {"verdict": decision, "sha": sha, "nightly_date": candidate.get("nightly_date"), "stage": stage, "run": run,
            "blocking_failures": [f"{r['check']} {r['name']}" for r in failures], "not_decided": not_decided,
            "candidate": candidate, "rows": rows}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")

    lines = [f"## Nightly readiness: {decision}", "",
             f"OpenMS `{sha[:10] or '?'}` · nightly {candidate.get('nightly_date', '?')} · stage `{stage}`"
             + (f" · [run]({run})" if run else ""), ""]
    if failures:
        lines += [f"**Blocking failures ({len(failures)}):**", ""]
        lines += [f"- {r['check']} {r['name']}: {r['result']} — {r['detail'].replace('|', '/')}" for r in failures]
        lines.append("")
    lines += ["| Check | Result | Blocks | Detail |", "| --- | --- | --- | --- |"]
    lines += [f"| {r['check']} {r['name']} | {r['result']} | {'yes' if r['blocking'] else 'no'} | "
              f"{r['detail'].replace('|', '/')} |" for r in rows]
    lines += ["", *[f"> {note}" for note in candidate.get("notes", [])],
              f"Not decided by this run: {', '.join(not_decided)} (judgement, static, tag-build and human checks). "
              "The readiness report in readiness/ covers them."]
    text = "\n".join(lines) + "\n"
    (REPORTS / "gate.md").write_text(text, encoding="utf-8")
    summarize(text)
    return 0 if decision == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["resolve", "verdict", "newest"])
    parser.add_argument("--artifacts", type=Path, default=ROOT / "labs", help="downloaded artifacts of the run (verdict)")
    arguments = parser.parse_args()
    if arguments.command == "resolve":
        return resolve()
    if arguments.command == "verdict":
        return verdict(arguments.artifacts)
    try:
        print(newest_complete(nightly_runs("release.yml"), nightly_runs("pyopenms-wheels-cibuildwheel.yml")))
    except Unpinnable as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
