"""Check an OpenMS source tree for documentation gaps a release must not ship with.

Run it against the commit the nightly was built from (the Revision in `FileInfo --help`) and
the tag of the previous release, which must be fetched (a shallow fetch is enough, only trees
are compared):

    git -C OpenMS fetch --depth 1 origin tag release/3.5.0
    python scripts/release-docs-audit.py --openms OpenMS --base release/3.5.0 --report reports/docs-audit.json

Checks, named as in RELEASE-READINESS.md:

  DOC-TOOL-INDEX      every registered TOPP tool is listed once in doc/doxygen/public/TOPP.doxygen
  DOC-TOOL-PAGE       every tool has one `@page TOPP_<Tool>` with @brief and the generated
                      parameter includes (TOPP_<Tool>.cli / TOPP_<Tool>.html)
  DOC-TOOL-CHANGELOG  tools added or removed since the base release are named in this
                      release's CHANGELOG section, removed tools under the name users knew
  DOC-STALE-TOOLS     removed tools are no longer referenced by the documentation or examples
  DOC-CLASS-BRIEF     headers added since the base release document their main class
  DOC-CMAKE-OPTIONS   CMake options added since the base release are documented, and removed
                      ones are no longer documented
  DOC-ENV-VARS        environment variables the code reads are documented somewhere
  CHANGELOG-LINT      the release section has no duplicated or orphaned bullet text
  VERSION-STRINGS     every file that carries the release version agrees

Each check reports what it found; RELEASE-READINESS.md decides which findings block a release.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

DOXYGEN_INPUTS = ["doc/doxygen/public", "doc/doxygen/install", "src/topp",
                  "src/openms_gui/source/VISUAL/APPLICATIONS", "src/openms/include",
                  "src/openms_cli/include", "src/openms_gui/include", "src/openswathalgo/include"]
PUBLIC_INCLUDE_DIRS = ["src/openms/include/OpenMS", "src/openms_cli/include/OpenMS",
                       "src/openms_gui/include/OpenMS", "src/openswathalgo/include/OpenMS"]
USER_DOC_DIRS = ["doc/doxygen/public", "doc/doxygen/install", "doc/openms/docs", "doc/pyopenms/docs/source",
                 "doc/thermo_raw_mzml.md", "README.md", "src/pyOpenMS/README.md"]
# Pages that exist for GUI applications, which are not TOPP tools and not in the registry.
GUI_PAGES = {"TOPPView", "TOPPAS", "INIFileEditor", "SwathWizard", "FLASHDeconvWizard"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout


def show(repo, ref, path):
    try:
        return git(repo, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return ""


def read(repo, ref, path):
    return (repo / path).read_text(encoding="utf-8", errors="replace") if ref is None else show(repo, ref, path)


def parse_tools(executables_cmake, gui_cmake):
    """Tool names from either declaration style (3.6: openms_topp_tool(); up to 3.5: set() lists)."""
    tools = set(re.findall(r"openms_topp_tool\(\s*([A-Za-z]\w*)", executables_cmake))
    for text in (executables_cmake, gui_cmake):
        text = re.sub(r"#[^\n]*", "", text)  # comments name categories, not tools
        for block in re.findall(r"set\(\s*(?:TOPP_executables(?:_with_GUIlib)?|UTILS_executables|GUI_TOPP_TOOLS)\b(.*?)\)",
                                text, re.S):
            for token in block.split():
                if re.fullmatch(r"[A-Za-z]\w+", token):
                    tools.add(token)
    return tools


def tool_list(repo, ref):
    return parse_tools(read(repo, ref, "src/topp/executables.cmake"),
                       read(repo, ref, "src/openms_gui/CMakeLists.txt"))


def release_section(changelog, version):
    start = re.search(rf"OpenMS {re.escape(version)}\b[^\n]*", changelog)
    if not start:
        return "", ""
    rest = changelog[start.end():]
    end = re.search(r"^-{20,}\s*\n-{4}\s+OpenMS \d", rest, re.MULTILINE)
    return start.group(0), rest[: end.start()] if end else rest


def doc_files(repo, dirs, suffixes):
    for entry in dirs:
        path = repo / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            for file in path.rglob("*"):
                if file.is_file() and file.suffix in suffixes and "/contrib/" not in str(file):
                    yield file


def check_tools(repo, base):
    head_tools = tool_list(repo, None)
    base_tools = tool_list(repo, base) if base else set()
    index_text = (repo / "doc/doxygen/public/TOPP.doxygen").read_text(encoding="utf-8")
    listed = re.findall(r"@subpage\s+TOPP_(\w+)", index_text)
    pages = {}
    for file in doc_files(repo, DOXYGEN_INPUTS, {".cpp", ".h", ".doxygen"}):
        text = file.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"@page\s+TOPP_(\w+)", text):
            pages.setdefault(match.group(1), []).append((file, text, match.start()))

    index = {"not_listed": sorted(head_tools - set(listed)),
             "listed_but_not_a_tool": sorted(set(listed) - head_tools - GUI_PAGES),
             "listed_twice": sorted({t for t in listed if listed.count(t) > 1})}
    page_problems = {}
    for tool in sorted(head_tools):
        found = pages.get(tool, [])
        problems = []
        if not found:
            problems.append("no @page")
        else:
            if len(found) > 1:
                problems.append("defined in " + ", ".join(str(f.relative_to(repo)) for f, _, _ in found))
            file, text, start = found[0]
            end = text.find("*/", start)
            if "@brief" not in text[start: end if end > 0 else len(text)]:
                problems.append("no @brief in the page's first comment block")
            if f"TOPP_{tool}.cli" not in text:
                problems.append(f"no '@verbinclude TOPP_{tool}.cli' (command-line parameters not shown)")
            if f"TOPP_{tool}.html" not in text:
                problems.append(f"no '@htmlinclude TOPP_{tool}.html' (INI parameters not shown)")
        if problems:
            page_problems[tool] = problems
    return head_tools, base_tools, {"DOC-TOOL-INDEX": index, "DOC-TOOL-PAGE": page_problems}


def check_tool_changelog(added, removed, section):
    new_tools = re.search(r"^\s*New tools:\s*\n(.*?)(?=^\s*Removed tools:|^\S)", section, re.S | re.M)
    removed_block = re.search(r"^\s*Removed tools:\s*\n(.*?)(?=^\S|^\s{0,2}\S)", section, re.S | re.M)
    new_text = new_tools.group(1) if new_tools else ""
    removed_text = removed_block.group(1) if removed_block else ""
    word = lambda name, text: re.search(rf"\b{re.escape(name)}\b", text) is not None
    return {
        "added_since_base": sorted(added),
        "removed_since_base": sorted(removed),
        "added_not_in_new_tools_list": sorted(t for t in added if not word(t, new_text)),
        "added_not_mentioned_anywhere": sorted(t for t in added if not word(t, section)),
        "removed_not_in_removed_tools_list": sorted(t for t in removed if not word(t, removed_text)),
        "removed_not_mentioned_anywhere": sorted(t for t in removed if not word(t, section)),
    }


def check_stale_tools(repo, removed):
    hits = []
    if not removed:
        return hits
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(removed))) + r")\b")
    dirs = USER_DOC_DIRS + ["share/OpenMS/examples", "src/topp", "src/openms_gui/source/VISUAL/APPLICATIONS"]
    for file in doc_files(repo, dirs, {".md", ".rst", ".doxygen", ".cpp", ".toppas", ".txt", ".ini", ".py", ".html"}):
        for number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for match in pattern.finditer(line):
                hits.append({"file": str(file.relative_to(repo)), "line": number, "tool": match.group(1),
                             "text": line.strip()[:160]})
    return hits


def check_class_briefs(repo, base):
    if not base:
        return {"skipped": "no base release given"}
    added = git(repo, "diff", "--name-status", "--diff-filter=A", base, "HEAD", "--", *PUBLIC_INCLUDE_DIRS)
    headers = [line.split("\t", 1)[1] for line in added.splitlines() if line.endswith(".h")]
    undocumented = []
    for header in headers:
        text = (repo / header).read_text(encoding="utf-8", errors="replace")
        declaration = re.search(r"^\s*(?:template\s*<[^>]*>\s*)?(?:class|struct)\s+(?:OPENMS\w*_DLLAPI\s+)?(\w+)\s*(?:final\s*)?[:{]",
                                text, re.M)
        if not declaration:
            continue  # free functions or enums only; not judged here
        before = text[: declaration.start()].rstrip()
        documented = before.endswith("*/") or re.search(r"(///|//!)[^\n]*$", before) is not None
        internal = "namespace Internal" in text or "namespace detail" in text or "@internal" in text
        if not documented:
            undocumented.append({"header": header, "class": declaration.group(1), "internal": internal})
    return {"added_headers": len(headers), "undocumented_main_class": undocumented}


def cmake_options(text):
    """User-settable options: option() and documented cache entries. A FORCEd or INTERNAL
    cache entry configures a bundled dependency or the build itself and is not a user option."""
    options = set(re.findall(r"^\s*option\(\s*([A-Z][A-Z0-9_]+)", text, re.M))
    for name, rest in re.findall(r"^\s*set\(\s*([A-Z][A-Z0-9_]+)\s+([^)\n]*\bCACHE\b[^)\n]*)", text, re.M):
        if re.search(r"\bCACHE\s+(STRING|BOOL|PATH|FILEPATH)\b", rest) and not re.search(r"\bFORCE\b|\bINTERNAL\b", rest):
            options.add(name)
    return options


def cmake_files(repo, ref):
    if ref is None:
        files = [p for p in [repo / "CMakeLists.txt", *repo.glob("cmake/*.cmake"), *repo.glob("src/*/CMakeLists.txt")]]
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files if p.is_file())
    listing = git(repo, "ls-tree", "-r", "--name-only", ref, "--", "CMakeLists.txt", "cmake", "src")
    paths = [p for p in listing.splitlines()
             if p == "CMakeLists.txt" or re.fullmatch(r"cmake/[^/]+\.cmake", p) or re.fullmatch(r"src/[^/]+/CMakeLists\.txt", p)]
    return "\n".join(show(repo, ref, p) for p in paths)


def check_cmake_options(repo, base, docs_text):
    head = cmake_options(cmake_files(repo, None))
    old = cmake_options(cmake_files(repo, base)) if base else set()
    added, removed = sorted(head - old), sorted(old - head)
    word = lambda name: re.search(rf"\b{name}\b", docs_text) is not None
    return {"added": added, "removed": removed,
            "added_undocumented": [o for o in added if not word(o)],
            "removed_still_documented": [o for o in removed if word(o)]}


# Variables of the operating system or shell; OpenMS reading them needs no documentation.
STANDARD_ENV = {"HOME", "USERPROFILE", "PATH", "PATHEXT", "COLUMNS", "XDG_CONFIG_HOME", "TMPDIR", "TEMP",
                "TMP", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL", "SHELL", "USER", "USERNAME"}


def check_env_vars(repo, docs_text):
    names = {}
    for top in ("src/openms", "src/openms_cli", "src/openms_gui", "src/topp", "src/openswathalgo"):
        for file in (repo / top).rglob("*"):
            if file.suffix not in (".cpp", ".h") or "/tests/" in str(file):
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            found = set(re.findall(r"(?:getenv|qgetenv|qEnvironmentVariable\w*|getEnv\w*)\(\s*\"([A-Z][A-Z0-9_]+)\"", text))
            if re.search(r"getenv|qEnvironmentVariable", text):
                # names looked up through a variable, e.g. a loop over {"OPENMS_TOOL_REGISTRY_PATH", ...}
                found |= set(re.findall(r"\"(OPENMS_[A-Z0-9_]+|[A-Z]+_PATH|DOTNET_[A-Z_]+)\"", text))
            for name in found:
                names.setdefault(name, set()).add(str(file.relative_to(repo)))
    return {name: {"read_in": sorted(files)[:3], "documented": re.search(rf"\b{name}\b", docs_text) is not None}
            for name, files in sorted(names.items()) if name not in STANDARD_ENV}


def check_changelog(heading, section):
    bullets, current = [], None
    for line in section.splitlines():
        stripped = line.strip()
        if re.match(r"^- ", stripped):
            current = [stripped[2:]]
            bullets.append(current)
        elif stripped and current is not None and not stripped.endswith(":"):
            current.append(stripped)
        else:
            current = None
    texts = [" ".join(b) for b in bullets]
    seen, duplicated = {}, []
    for text in texts:
        key = re.sub(r"\W+", " ", text[:120]).lower()
        if len(key) > 40 and key in seen:
            duplicated.append(text[:160])
        seen[key] = True
    # A continuation line that starts in lower case right after a line that closed a sentence
    # is usually the tail of an edited bullet left behind, e.g. "the registry check (#10216)."
    orphan_lines, previous = [], ""
    for line in section.splitlines():
        stripped = line.strip()
        if (re.match(r"^\s{4,}[a-z]", line) and not stripped.startswith("- ")
                and re.search(r"(\.|\.\)|\(#\d+(, #\d+)*\)\.)$", previous.strip())):
            orphan_lines.append(stripped[:120])
        previous = line if stripped else ""
    return {"heading": heading.strip(), "under_development": "under development" in heading.lower(),
            "bullets": len(texts), "duplicated_bullets": duplicated,
            "suspicious_short_continuation_lines": orphan_lines}


def check_versions(repo, expected):
    def grab(path, pattern):
        file = repo / path
        if not file.is_file():
            return None
        match = re.search(pattern, file.read_text(encoding="utf-8", errors="replace"), re.M)
        return match.group(1) if match else None

    cmake = repo / "CMakeLists.txt"
    parts = [re.search(rf'OPENMS_PACKAGE_VERSION_{p} "(\d+)"', cmake.read_text()).group(1)
             for p in ("MAJOR", "MINOR", "PATCH")]
    found = {
        "CMakeLists.txt (OPENMS_PACKAGE_VERSION)": ".".join(parts),
        "src/pyOpenMS/pyproject.toml": grab("src/pyOpenMS/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
        "vcpkg.json (version-string)": grab("vcpkg.json", r'"version-string"\s*:\s*"([^"]+)"'),
        "doc/openms/docs/conf.py (release)": grab("doc/openms/docs/conf.py", r"^release\s*=\s*['\"]([^'\"]+)"),
        "doc/pyopenms/docs/source/conf.py (version)": grab("doc/pyopenms/docs/source/conf.py", r"^version\s*=\s*['\"]([^'\"]+)"),
        "CHANGELOG (first release heading)": grab("CHANGELOG", r"OpenMS (\d+\.\d+\.\d+)"),
    }
    expected = expected or found["CMakeLists.txt (OPENMS_PACKAGE_VERSION)"]
    return {"expected": expected, "found": found,
            "mismatched": {k: v for k, v in found.items() if v is not None and v != expected}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--openms", required=True, help="OpenMS source checkout (the nightly's commit)")
    parser.add_argument("--base", help="previous release tag, e.g. release/3.5.0 (must be fetched)")
    parser.add_argument("--version", help="release being prepared; default: the CMakeLists.txt version")
    parser.add_argument("--report", default="reports/docs-audit.json")
    args = parser.parse_args()
    repo = Path(args.openms).resolve()

    versions = check_versions(repo, args.version)
    version = versions["expected"]
    heading, section = release_section((repo / "CHANGELOG").read_text(encoding="utf-8"), version)
    docs_text = "\n".join(f.read_text(encoding="utf-8", errors="replace")
                          for f in doc_files(repo, USER_DOC_DIRS, {".md", ".rst", ".doxygen", ".txt"}))

    head_tools, base_tools, tool_checks = check_tools(repo, args.base)
    added, removed = head_tools - base_tools, (base_tools - head_tools) if args.base else set()
    report = {
        "openms": str(repo), "commit": git(repo, "rev-parse", "HEAD").strip(), "base": args.base,
        "version": version, "registered_tools": len(head_tools),
        **tool_checks,
        "DOC-TOOL-CHANGELOG": check_tool_changelog(added, removed, section) if args.base else {"skipped": "no base"},
        "DOC-STALE-TOOLS": check_stale_tools(repo, removed),
        "DOC-CLASS-BRIEF": check_class_briefs(repo, args.base),
        "DOC-CMAKE-OPTIONS": check_cmake_options(repo, args.base, docs_text) if args.base else {"skipped": "no base"},
        "DOC-ENV-VARS": check_env_vars(repo, docs_text),
        "CHANGELOG-LINT": check_changelog(heading, section),
        "VERSION-STRINGS": versions,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")

    index = report["DOC-TOOL-INDEX"]
    print(f"OpenMS {version} at {report['commit'][:10]} vs {args.base}: {len(head_tools)} registered tools")
    print(f"DOC-TOOL-INDEX      not listed {index['not_listed']}, not a tool {index['listed_but_not_a_tool']}, "
          f"twice {index['listed_twice']}")
    print(f"DOC-TOOL-PAGE       {len(report['DOC-TOOL-PAGE'])} tools with incomplete pages")
    for tool, problems in report["DOC-TOOL-PAGE"].items():
        print(f"    {tool}: {'; '.join(problems)}")
    if args.base:
        tc = report["DOC-TOOL-CHANGELOG"]
        print(f"DOC-TOOL-CHANGELOG  added {tc['added_since_base']}")
        print(f"                    removed {tc['removed_since_base']}")
        print(f"                    added but not under 'New tools': {tc['added_not_in_new_tools_list']}")
        print(f"                    removed but not under 'Removed tools': {tc['removed_not_in_removed_tools_list']}")
    stale = report["DOC-STALE-TOOLS"]
    print(f"DOC-STALE-TOOLS     {len(stale)} references to removed tools")
    for hit in stale[:15]:
        print(f"    {hit['file']}:{hit['line']} {hit['tool']}")
    cb = report["DOC-CLASS-BRIEF"]
    if "undocumented_main_class" in cb:
        public_missing = [c for c in cb["undocumented_main_class"] if not c["internal"]]
        print(f"DOC-CLASS-BRIEF     {len(public_missing)} of {cb['added_headers']} new headers lack a class comment")
    if args.base:
        co = report["DOC-CMAKE-OPTIONS"]
        print(f"DOC-CMAKE-OPTIONS   new undocumented {co['added_undocumented']}; removed but documented {co['removed_still_documented']}")
    undocumented_env = [n for n, v in report["DOC-ENV-VARS"].items() if not v["documented"]]
    print(f"DOC-ENV-VARS        undocumented {undocumented_env}")
    cl = report["CHANGELOG-LINT"]
    print(f"CHANGELOG-LINT      '{cl['heading']}': {cl['bullets']} bullets, {len(cl['duplicated_bullets'])} duplicated, "
          f"{len(cl['suspicious_short_continuation_lines'])} orphaned lines")
    print(f"VERSION-STRINGS     expected {version}; mismatched {versions['mismatched']}")
    print(f"report: {args.report}")


if __name__ == "__main__":
    sys.exit(main())
