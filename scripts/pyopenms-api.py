"""Record the public pyOpenMS API of an installed wheel, and compare two such records.

Release notes say what was meant to change; the wheels say what did. Comparing the public
namespace of the last release with the candidate gives the list a release has to account for:
every removed name should be in the CHANGELOG as BREAKING, and every new name should be
documented. With --docs, the comparison also reads the pyOpenMS user guide and reports

  * new classes that no user-guide page mentions (documentation gaps), and
  * names the user guide still uses although the candidate no longer has them (stale pages).

snapshot runs inside the environment that has the wheel installed:

    .venv-old/bin/python scripts/pyopenms-api.py snapshot --out reports/api-old.json
    .venv-new/bin/python scripts/pyopenms-api.py snapshot --out reports/api-new.json

diff needs neither wheel, only the two records and optionally the docs:

    python scripts/pyopenms-api.py diff reports/api-old.json reports/api-new.json \\
        --docs OpenMS/doc/pyopenms/docs/source/user_guide --out reports/api-diff.json
"""
import argparse
import inspect
import json
from pathlib import Path
import re
import sys

# Names every user guide uses that are not pyOpenMS attributes.
PYTHON_WORDS = {"append", "keys", "values", "items", "format", "split", "join", "strip", "encode",
                "decode", "copy", "sort", "index", "count", "get", "update", "read", "write",
                "close", "shape", "astype", "tolist", "head", "plot", "show", "mean", "sum"}


def public(names):
    return sorted(n for n in names if not n.startswith("_"))


def snapshot(out):
    import importlib
    import pkgutil
    import pyopenms  # imported here so that diff works without a wheel

    seen = {}
    api = {}
    for name in public(dir(pyopenms)):
        obj = getattr(pyopenms, name)
        entry = {"module": getattr(obj, "__module__", None)}
        if inspect.ismodule(obj):
            entry["kind"] = "module"
        elif type(obj).__name__ == "CallableSingleton":
            # 3.6 exposes the chemistry databases as callables returning the one instance;
            # 3.5 exposed them as classes. Record what the instance offers.
            entry["kind"] = "singleton"
            entry["members"] = public(dir(type(obj())))
        elif inspect.isclass(obj):
            entry["kind"] = "class"
            entry["members"] = public(dir(obj))
            real_name = getattr(obj, "__name__", name)
            if real_name != name:
                entry["alias_of"] = real_name
            elif id(obj) in seen:
                entry["alias_of"] = seen[id(obj)]
            seen.setdefault(id(obj), name)
        elif callable(obj):
            entry["kind"] = "function"
        else:
            entry["kind"] = "value"
            entry["type"] = type(obj).__name__
        doc = (getattr(obj, "__doc__", None) or "").strip() if entry["kind"] != "value" else ""
        entry["doc"] = doc.splitlines()[0][:160] if doc else ""
        api[name] = entry
    # Submodules (pyopenms.plotting, pyopenms.Constants) are imported by name, not attributes.
    submodules = public(m.name for m in pkgutil.iter_modules(pyopenms.__path__))
    # Members of every class the package defines, exported or not, so that a method is
    # only reported as gone when no class offers it any more.
    members_anywhere = set()
    for module_info in pkgutil.iter_modules(pyopenms.__path__):
        try:
            module = importlib.import_module(f"pyopenms.{module_info.name}")
        except Exception:  # an optional extra (plotting, dataframes) may lack its dependency
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            members_anywhere.update(public(dir(cls)))
    for entry in api.values():
        members_anywhere.update(entry.get("members", []))
    record = {"version": pyopenms.__version__, "file": pyopenms.__file__, "names": api,
              "submodules": submodules, "members_anywhere": sorted(members_anywhere)}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    classes = sum(1 for e in api.values() if e["kind"] == "class")
    print(f"pyopenms {record['version']}: {len(api)} public names, {classes} classes -> {out}")


def code_blocks(rst):
    """Yield (line, code) for every python code block of an .rst file."""
    lines = rst.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if re.match(r"\s*\.\. code-block::\s*(python|ipython3?|pycon)\s*$", lines[i]):
            start = i + 1
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                if lines[i].strip().startswith(":") and i == start:  # directive options
                    start += 1
                i += 1
            body = [l for l in lines[start:i]]
            indent = min((len(l) - len(l.lstrip()) for l in body if l.strip()), default=0)
            yield start + 1, "\n".join(l[indent:] for l in body)
        else:
            i += 1


def release_section(changelog, version):
    """The CHANGELOG text of one release, e.g. '3.6.0' -> everything up to the next banner."""
    text = Path(changelog).read_text(encoding="utf-8")
    start = re.search(rf"OpenMS {re.escape(version)}\b", text)
    if not start:
        return ""
    end = re.search(r"^-{20,}\s*\n-{4}\s+OpenMS \d", text[start.end():], re.MULTILINE)
    return text[start.end(): start.end() + end.start()] if end else text[start.end():]


def diff(old_path, new_path, docs, out, changelog=None):
    old = json.loads(Path(old_path).read_text(encoding="utf-8"))
    new = json.loads(Path(new_path).read_text(encoding="utf-8"))
    o, n = old["names"], new["names"]
    removed = sorted(set(o) - set(n))
    added = sorted(set(n) - set(o))
    changed = {}
    for name in sorted(set(o) & set(n)):
        if o[name].get("kind") != n[name].get("kind"):
            changed[name] = {"kind": f"{o[name].get('kind')} -> {n[name].get('kind')}"}
        if "members" in o[name] and "members" in n[name]:
            gone = sorted(set(o[name].get("members", [])) - set(n[name].get("members", [])))
            new_members = sorted(set(n[name].get("members", [])) - set(o[name].get("members", [])))
            if gone or new_members:
                changed.setdefault(name, {}).update(removed_members=gone, added_members=new_members)
    new_members_anywhere = set(new.get("members_anywhere") or
                               {m for e in n.values() for m in e.get("members", [])})
    old_members_anywhere = set(old.get("members_anywhere") or
                               {m for e in o.values() for m in e.get("members", [])})
    methods_gone_everywhere = sorted(old_members_anywhere - new_members_anywhere)

    result = {
        "old_version": old["version"], "new_version": new["version"],
        "removed_names": {name: o[name]["kind"] for name in removed},
        "added_names": {name: n[name]["kind"] for name in added},
        "added_classes_without_docstring": [name for name in added if n[name]["kind"] == "class"
                                            and not n[name].get("doc") and "alias_of" not in n[name]],
        "changed_classes": changed,
        "members_removed_from_every_class": methods_gone_everywhere,
    }

    if changelog:
        release = re.match(r"\d+\.\d+\.\d+", new["version"]).group(0)
        notes = release_section(changelog, release)
        result["changelog_release"] = release
        result["removed_names_not_in_changelog"] = [
            name for name in removed if o[name]["kind"] in ("class", "function", "singleton")
            and not re.search(rf"\b{re.escape(name)}\b", notes)]

    if docs:
        pages = sorted(Path(docs).rglob("*.rst"))
        text = {p.name: p.read_text(encoding="utf-8") for p in pages}
        corpus = "\n".join(text.values())
        added_classes = [name for name in added if n[name]["kind"] == "class" and "alias_of" not in n[name]]
        result["added_classes_mentioned_in_docs"] = {
            name: sorted(p for p, t in text.items() if re.search(rf"\b{re.escape(name)}\b", t))
            for name in added_classes if re.search(rf"\b{re.escape(name)}\b", corpus)}
        result["added_classes_not_in_docs"] = [name for name in added_classes
                                               if name not in result["added_classes_mentioned_in_docs"]]
        stale = []
        gone_methods = set(methods_gone_everywhere) - PYTHON_WORDS
        for page in pages:
            for line, code in code_blocks(page):
                for offset, source_line in enumerate(code.splitlines()):
                    for module_name in re.findall(r"\b(?:oms|pyopenms|pms)\.([A-Za-z_]\w*)", source_line):
                        if (module_name not in n and module_name not in new.get("submodules", [])
                                and not module_name.startswith("_")):
                            stale.append({"page": page.name, "line": line + offset, "name": f"pyopenms.{module_name}",
                                          "was_in_old": module_name in o, "code": source_line.strip()[:140]})
                    for method in re.findall(r"\.([A-Za-z_]\w*)\s*\(", source_line):
                        if method in gone_methods:
                            stale.append({"page": page.name, "line": line + offset, "name": f".{method}()",
                                          "was_in_old": True, "code": source_line.strip()[:140]})
        result["docs_using_missing_names"] = stale

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{old['version']} -> {new['version']}: {len(removed)} names removed, {len(added)} added, "
          f"{len(changed)} classes changed")
    if changelog:
        print(f"removed names the {result['changelog_release']} CHANGELOG never mentions: "
              f"{len(result['removed_names_not_in_changelog'])}")
    if docs:
        print(f"new classes not mentioned in the user guide: {len(result['added_classes_not_in_docs'])} "
              f"of {len(result['added_classes_not_in_docs']) + len(result['added_classes_mentioned_in_docs'])}")
        print(f"user-guide code lines using names the new wheel lacks: {len(result['docs_using_missing_names'])}")
    print(f"report: {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--out", required=True)
    cmp_ = sub.add_parser("diff")
    cmp_.add_argument("old")
    cmp_.add_argument("new")
    cmp_.add_argument("--docs", help="user_guide directory of the pyOpenMS documentation")
    cmp_.add_argument("--changelog", help="OpenMS CHANGELOG; removed names it never mentions are reported")
    cmp_.add_argument("--out", default="reports/pyopenms-api-diff.json")
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot(args.out)
    else:
        diff(args.old, args.new, args.docs, args.out, args.changelog)


if __name__ == "__main__":
    sys.exit(main())
