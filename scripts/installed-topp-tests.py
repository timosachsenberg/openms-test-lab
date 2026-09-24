"""Run upstream TOPP tests against an installed OpenMS instead of a build tree.

OpenMS CI runs its TOPP tests (src/tests/topp/CMakeLists.txt) against the binaries in the
build directory. A package is a different thing: it has to find its shared data, bundled
engines, plugins and runtime libraries from wherever the installer put them. This script
replays the same CMake files against the installed tools and runs a selection of the tests
they define, so a release is judged by what users install rather than by what CI built.

It needs a checkout of the OpenMS commit the package was built from (the Revision printed by
`FileInfo --help`); only src/tests/topp is read, so a sparse checkout is enough:

    git clone --filter=blob:none --sparse https://github.com/OpenMS/OpenMS
    git -C OpenMS sparse-checkout set src/tests/topp && git -C OpenMS checkout <revision>
    python scripts/installed-topp-tests.py --openms OpenMS --select release-gate
    python scripts/installed-topp-tests.py --openms OpenMS --select all --fetch-missing
    python scripts/installed-topp-tests.py --openms OpenMS --select 'TOPP_(ProSE|UniPEFF)_'

The files are interpreted in order, as a configure step would: set(), list(), if(), foreach(),
macro(), include(), find_program(), configure_file() and the few other commands they use.
What the build knew is supplied as variables: the tools in the package's registry, the build
options its tools reveal (OpenSwath, WNetAlign, GUI, OpenTIMS, CWL export, zlib-ng) and the
platform; -D NAME=VALUE adds or overrides one, as with cmake. A test inside an if() that is
false for this package is reported as skipped with the condition, as is a test whose command
needs something missing (a variable, an input outside the checkout, an executable). Nothing
skipped is counted as passed.

A test's diff companions (TOPP_X_1_out, which DEPEND on TOPP_X_1) are selected with it, and
the tests it depends on run first. As in upstream CI, the bundled engines are on PATH while
the tests run; whether the package finds them without help is a separate check (C4 in
RELEASE-READINESS.md). DATA_DIR_SHARE points at the installed share/OpenMS, because that is
what users get; every other variable keeps the meaning the test files give it.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import platform
import posixpath
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

# ------------------------------------------------------------------------------------------
# A CMake interpreter for the commands the TOPP test files use
# ------------------------------------------------------------------------------------------
DOLLAR = "\x00"  # an escaped or substituted '$': expansion never runs twice over one value
REFERENCE = re.compile(r"\$(ENV)?\{([^${}]*)\}")
BRACKET = re.compile(r"\[(=*)\[")
TRUE_WORDS = {"1", "ON", "YES", "TRUE", "Y"}
FALSE_WORDS = {"0", "OFF", "NO", "FALSE", "N", "IGNORE", "NOTFOUND", ""}
UNARY = {"DEFINED", "EXISTS", "IS_DIRECTORY", "IS_ABSOLUTE", "IS_SYMLINK", "COMMAND", "TEST", "TARGET", "POLICY"}
BINARY = {"STREQUAL", "STRLESS", "STRGREATER", "STRLESS_EQUAL", "STRGREATER_EQUAL", "MATCHES", "EQUAL", "LESS",
          "GREATER", "LESS_EQUAL", "GREATER_EQUAL", "VERSION_EQUAL", "VERSION_LESS", "VERSION_GREATER",
          "VERSION_LESS_EQUAL", "VERSION_GREATER_EQUAL", "IN_LIST", "PATH_EQUAL"}
FIND_OPTIONS = {"NAMES", "HINTS", "PATHS", "PATH_SUFFIXES", "DOC", "ENV", "REQUIRED", "NO_CACHE", "NAMES_PER_DIR",
                "NO_DEFAULT_PATH", "NO_SYSTEM_ENVIRONMENT_PATH", "NO_CMAKE_PATH", "NO_CMAKE_SYSTEM_PATH"}
PROCESS_OPTIONS = {"COMMAND", "WORKING_DIRECTORY", "TIMEOUT", "RESULT_VARIABLE", "OUTPUT_VARIABLE", "ERROR_VARIABLE",
                   "INPUT_FILE", "OUTPUT_QUIET", "ERROR_QUIET", "OUTPUT_STRIP_TRAILING_WHITESPACE",
                   "ERROR_STRIP_TRAILING_WHITESPACE", "ENCODING", "COMMAND_ECHO"}
NO_EFFECT = {"project", "cmake_minimum_required", "cmake_policy", "enable_testing"}


def unescape(raw):
    """CMake escapes: \\t \\n \\r are control characters, \\; stays (it keeps a list from being
    split there), \\$ is a literal dollar sign, a backslash before a newline joins lines, and
    any other \\x is x."""
    table = {"t": "\t", "n": "\n", "r": "\r", ";": "\\;", "$": DOLLAR, "\n": ""}
    return re.sub(r"\\(.)", lambda m: table.get(m.group(1), m.group(1)), raw, flags=re.S)


def parse(text, source):
    """The commands of a CMake file as (name, [(argument, quoted)], line, file). Comments are
    dropped; parentheses nested in the arguments, as in if(), are arguments of their own."""
    commands, i, n, line, counted = [], 0, len(text), 1, 0
    command_start = re.compile(r"([A-Za-z_]\w*)[ \t]*\(")

    def after_comment(i):
        opened = BRACKET.match(text, i + 1)
        if opened:
            end = text.find("]" + opened.group(1) + "]", opened.end())
            return n if end < 0 else end + len(opened.group(0))
        end = text.find("\n", i)
        return n if end < 0 else end

    def after_quote(j):  # index of the closing quote of a quoted argument opened before j
        while j < n and text[j] != '"':
            j += 2 if text[j] == "\\" else 1
        return j

    while i < n:
        if text[i] == "#":
            i = after_comment(i)
            continue
        start = command_start.match(text, i)
        if not start:
            i += 1
            continue
        line, counted = line + text.count("\n", counted, i), i
        i, depth, args = start.end(), 0, []
        while i < n:
            c = text[i]
            if c in " \t\r\n":
                i += 1
            elif c == "#":
                i = after_comment(i)
            elif c == "(":
                depth, i = depth + 1, i + 1
                args.append(("(", False))
            elif c == ")":
                i += 1
                if depth == 0:
                    break
                depth -= 1
                args.append((")", False))
            elif c == '"':
                j = after_quote(i + 1)
                args.append((unescape(text[i + 1:j]), True))
                i = j + 1
            elif BRACKET.match(text, i):  # [[...]]: taken literally, never expanded
                opened = BRACKET.match(text, i)
                end = text.find("]" + opened.group(1) + "]", opened.end())
                body = text[opened.end():end]
                args.append(((body[1:] if body.startswith("\n") else body).replace("$", DOLLAR), True))
                i = end + len(opened.group(0))
            else:
                j = i
                while j < n and text[j] not in ' \t\r\n()#':
                    if text[j] == "\\":
                        j += 1
                    elif text[j] == '"':  # legacy a="b c": the quotes stay part of the argument
                        j = after_quote(j + 1)
                    j += 1
                args.append((unescape(text[i:j]), False))
                i = j
        commands.append((start.group(1).lower(), args, line, source))
    return commands


def split_list(value):
    """A CMake list's elements, as cmExpandList makes them: split at ';' unless the ';' is
    escaped or inside [], '\\;' becomes ';', empty elements are dropped."""
    items, current, depth, i = [], [], 0, 0
    while i < len(value):
        c = value[i]
        if c == "\\" and value[i + 1:i + 2] == ";":
            current.append(";")
            i += 2
            continue
        if c == ";" and depth == 0:
            if current:
                items.append("".join(current))
            current = []
        else:
            depth += {"[": 1, "]": -1}.get(c, 0)
            current.append(c)
        i += 1
    if current:
        items.append("".join(current))
    return items


def constant(value):
    """True or False for a CMake boolean constant, None for any other word."""
    word = value.upper()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS or word.endswith("-NOTFOUND"):
        return False
    if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", value):
        return float(value) != 0
    return None


def version_key(text):
    parts = [int(re.match(r"\d*", p).group() or 0) for p in text.split(".")]
    return parts + [0] * (4 - len(parts))


def matching(commands, start, opener, closer):
    depth = 0
    for j in range(start + 1, len(commands)):
        if commands[j][0] == opener:
            depth += 1
        elif commands[j][0] == closer:
            if depth == 0:
                return j
            depth -= 1
    raise ValueError(f"{opener}() at {commands[start][3]}:{commands[start][2]} has no {closer}()")


def branches(commands, start):
    """The branches of the if() at start, as (kind, condition, body, line), and where it ends."""
    found, depth, kind, condition, first, line = [], 0, "if", commands[start][1], start + 1, commands[start][2]
    for j in range(start + 1, len(commands)):
        word = commands[j][0]
        if word == "if":
            depth += 1
        elif word == "endif" and depth:
            depth -= 1
        elif depth == 0 and word in ("elseif", "else", "endif"):
            found.append((kind, condition, commands[first:j], line))
            if word == "endif":
                return found, j
            kind, condition, first, line = word, commands[j][1], j + 1, commands[j][2]
    raise ValueError(f"if() at {commands[start][3]}:{commands[start][2]} has no endif()")


def condition_text(args):
    return " ".join(f'"{raw}"' if quoted else raw for raw, quoted in args).replace(DOLLAR, "$")


class Replay:
    """Runs the TOPP test CMake files the way a configure step would and collects their tests."""

    def __init__(self, variables, pinned, env):
        self.vars = {**variables, **pinned}
        self.known = set(self.vars)  # names that were given a value, or explicitly unset, at some point
        self.pinned = dict(pinned)   # values set() does not replace
        self.env = env               # what $ENV{...} reads, and where find_program() looks
        self.macros, self.tests, self.order = {}, {}, []
        self.excluded = {}           # tests of if() branches not taken: name -> reason, source
        self.notes = []              # what this replay could not do exactly as CMake would
        self.missing = set()
        self.loop_variables = set()

    # -- values
    def expand(self, text):
        while True:
            match = REFERENCE.search(text)  # innermost first: its name holds no further reference
            if not match:
                return text
            name = match.group(2)
            if match.group(1):
                value = self.env.get(name, "")
            else:
                value = self.vars.get(name)
                if value is None:
                    value = ""
                    if name not in self.known:
                        self.missing.add(name)
            text = text[:match.start()] + value.replace("$", DOLLAR) + text[match.end():]

    def arguments(self, args):
        """Arguments as a command receives them: unquoted ones expand into list elements."""
        values = []
        for raw, quoted in args:
            value = self.expand(raw)
            values += [value] if quoted else split_list(value)
        return [v.replace(DOLLAR, "$") for v in values]

    def assign(self, name, value):
        self.known.add(name)
        if name in self.pinned:
            return
        if value is None:
            self.vars.pop(name, None)
        else:
            self.vars[name] = value

    # -- if()
    def evaluate(self, args):
        """An if() condition with CMake's precedence: parentheses, unary tests, binary tests,
        NOT, AND, OR. Quoted arguments are strings, never variables or keywords (CMP0054)."""
        tokens = []
        for raw, quoted in args:
            value = self.expand(raw)
            tokens += [(value, True)] if quoted else [(v, False) for v in split_list(value)]
        tokens = [(v.replace(DOLLAR, "$"), q) for v, q in tokens]
        pos = 0

        def keyword(*words):
            return pos < len(tokens) and not tokens[pos][1] and tokens[pos][0] in words

        def take():
            nonlocal pos
            if pos >= len(tokens):
                raise ValueError("the condition ends early")
            pos += 1
            return tokens[pos - 1]

        def value(token):
            text, quoted = token
            return self.vars[text] if not quoted and text in self.vars else text

        def truth(token):
            text, quoted = token
            known = constant(text)
            if known is not None or quoted:
                return bool(known)
            return text in self.vars and constant(self.vars[text]) is not False

        def comparison():
            if keyword("("):
                take()
                result = disjunction()
                if not keyword(")"):
                    raise ValueError("unbalanced parentheses")
                take()
                return result
            token = take()
            if not token[1] and token[0] in UNARY:
                return self.unary(token[0], take()[0])
            if keyword(*BINARY):
                operator = take()[0]
                right = take()
                return self.binary(operator, value(token), value(right), right)
            return truth(token)

        def negation():
            if keyword("NOT"):
                take()
                return not negation()
            return comparison()

        def conjunction():
            result = negation()
            while keyword("AND"):
                take()
                result = negation() and result
            return result

        def disjunction():
            result = conjunction()
            while keyword("OR"):
                take()
                result = conjunction() or result
            return result

        result = disjunction()
        if pos != len(tokens):
            raise ValueError(f"unexpected {tokens[pos][0]!r}")
        return result

    def unary(self, test, operand):
        if test == "DEFINED":
            env = re.fullmatch(r"ENV\{(.*)\}", operand)
            return env.group(1) in self.env if env else operand in self.vars
        if test in ("EXISTS", "IS_DIRECTORY", "IS_SYMLINK"):
            path = Path(operand)
            return bool(operand) and {"EXISTS": path.exists, "IS_DIRECTORY": path.is_dir,
                                      "IS_SYMLINK": path.is_symlink}[test]()
        if test == "IS_ABSOLUTE":
            return operand.startswith("/") or re.match(r"[A-Za-z]:[/\\]", operand) is not None
        if test == "COMMAND":
            return operand.lower() in self.macros or hasattr(self, "do_" + operand.lower())
        if test == "TEST":
            return operand in self.tests
        raise ValueError(f"if({test} ...) has no answer for an installed package")

    def binary(self, operator, left, right, right_token):
        if operator == "IN_LIST":
            return left in split_list(self.vars.get(right_token[0], ""))
        if operator == "MATCHES":
            return re.search(right, left) is not None
        if operator.startswith("VERSION_"):
            a, b = version_key(left), version_key(right)
        elif operator.startswith("STR") or operator == "PATH_EQUAL":
            a, b = left, right
        else:
            try:
                a, b = float(left), float(right)
            except ValueError:
                return False
        relation = re.sub(r"^(STR|VERSION_|PATH_)", "", operator)
        return {"EQUAL": a == b, "LESS": a < b, "GREATER": a > b,
                "LESS_EQUAL": a <= b, "GREATER_EQUAL": a >= b}[relation]

    @staticmethod
    def read_by(args):
        """The variables an if() condition reads."""
        names = []
        for raw, quoted in args:
            for name in re.findall(r"\$\{(\w+)\}", raw) + ([] if quoted else re.findall(r"^[A-Za-z_]\w*$", raw)):
                if name not in names and name not in UNARY | BINARY | {"NOT", "AND", "OR"} and constant(name) is None:
                    names.append(name)
        return names

    def explain(self, args):
        """The variables an if() reads, with their values, for the report."""
        return ", ".join(f"{n}={self.vars[n][:60]}" if n in self.vars else f"{n} undefined" for n in self.read_by(args))

    # -- control flow
    def run_file(self, path):
        path = Path(path)
        self.execute(parse(path.read_text(encoding="utf-8", errors="replace"), path.name))

    def execute(self, commands):
        i = 0
        while i < len(commands):
            name, args, line, source = commands[i]
            if name == "if":
                found, end = branches(commands, i)
                chosen = False
                for kind, condition, body, branch_line in found:
                    if chosen:
                        self.exclude(body, "an earlier branch of its if() applies")
                        continue
                    if kind == "else":
                        chosen = True
                    else:
                        try:
                            chosen = self.evaluate(condition)
                        except (ValueError, re.error) as error:
                            self.notes.append(f"{source}:{branch_line}: if({condition_text(condition)}) "
                                              f"could not be evaluated ({error}); taken as false")
                    if chosen:
                        self.execute(body)
                    elif not set(self.read_by(condition)) <= self.loop_variables:
                        # (a branch that only a foreach() variable decides is not about the package)
                        self.exclude(body, f"if({condition_text(condition)}) is false for this package "
                                           f"({self.explain(condition)})")
                i = end + 1
            elif name == "foreach":
                end = matching(commands, i, "foreach", "endforeach")
                words = self.arguments(args)
                variable, items = words[0], words[1:]
                if items[:1] == ["RANGE"]:
                    bounds = [int(x) for x in items[1:]]
                    first, last, step = (0, bounds[0], 1) if len(bounds) == 1 else (bounds + [1])[:3]
                    items = [str(k) for k in range(first, last + 1, step)]
                elif items[:1] == ["IN"]:
                    values, mode = [], "ITEMS"
                    for word in items[1:]:
                        if word in ("LISTS", "ITEMS"):
                            mode = word
                        else:
                            values += split_list(self.vars.get(word, "")) if mode == "LISTS" else [word]
                    items = values
                self.loop_variables.add(variable)
                for item in items:
                    self.assign(variable, item)
                    self.execute(commands[i + 1:end])
                i = end + 1
            elif name in ("macro", "function"):
                end = matching(commands, i, name, "end" + name)
                signature = self.arguments(args)
                if name == "function":
                    self.notes.append(f"{source}:{line}: function {signature[0]}() is replayed as a macro")
                self.macros[signature[0].lower()] = (signature[1:], commands[i + 1:end])
                i = end + 1
            else:
                if name in self.macros:
                    self.call(name, args)
                elif hasattr(self, "do_" + name):
                    getattr(self, "do_" + name)(args, f"{source}:{line}")
                elif name not in NO_EFFECT:
                    self.notes.append(f"{source}:{line}: {name}() is not replayed")
                i += 1

    def call(self, name, args):
        parameters, body = self.macros[name]
        values = self.arguments(args)
        names = {p: "" for p in parameters}
        names.update(zip(parameters, values))
        names.update(ARGC=str(len(values)), ARGV=";".join(values), ARGN=";".join(values[len(parameters):]))
        names.update({f"ARGV{k}": v for k, v in enumerate(values)})

        def substitute(raw):  # a macro's parameters are replaced in its text before it runs
            return re.sub(r"\$\{(\w+)\}", lambda m: names.get(m.group(1), m.group(0)), raw)
        self.execute([(n, [(substitute(r), q) for r, q in a], l, s) for n, a, l, s in body])

    def exclude(self, body, reason):
        for name, args, line, source in body:
            if name == "add_test" and args:
                words = [self.expand(raw).replace(DOLLAR, "$") for raw, _ in args[:2]]
                test = words[1] if words[0] == "NAME" and len(words) > 1 else words[0]
                self.excluded.setdefault(test, {"reason": reason, "source": f"{source}:{line}"})

    # -- commands
    def do_set(self, args, where):
        words = self.arguments(args)
        if not words or "PARENT_SCOPE" in words[1:]:
            return  # nothing to set, or a parent scope the top level does not have
        name, values = words[0], words[1:]
        if "CACHE" in values:
            values, force = values[:values.index("CACHE")], "FORCE" in values
            if name in self.vars and not force:
                return
        self.assign(name, ";".join(values) if values else None)

    def do_unset(self, args, where):
        self.assign(self.arguments(args)[0], None)

    def do_option(self, args, where):
        words = self.arguments(args)
        if words[0] not in self.vars:
            self.assign(words[0], words[2] if len(words) > 2 else "OFF")

    def do_list(self, args, where):
        words = self.arguments(args)
        operation, name, items = words[0], words[1], words[2:]
        current = split_list(self.vars.get(name, ""))
        if operation == "APPEND":
            current += items
        elif operation == "PREPEND":
            current = items + current
        elif operation == "REMOVE_ITEM":
            current = [c for c in current if c not in items]
        elif operation == "REMOVE_DUPLICATES":
            current = list(dict.fromkeys(current))
        elif operation == "LENGTH":
            return self.assign(items[0], str(len(current)))
        elif operation == "GET":
            return self.assign(items[-1], ";".join(current[int(k)] for k in items[:-1]))
        else:
            return self.notes.append(f"{where}: list({operation}) is not replayed")
        self.assign(name, ";".join(current))

    def do_string(self, args, where):
        words = self.arguments(args)
        if words[0] == "REPLACE":
            self.assign(words[3], "".join(words[4:]).replace(words[1], words[2]))
        elif words[:2] == ["REGEX", "MATCH"]:
            found = re.search(words[2], "".join(words[4:]))
            self.assign(words[3], found.group(0) if found else "")
        elif words[:2] == ["REGEX", "REPLACE"]:
            replacement = re.sub(r"\\(\d)", r"\\g<\1>", words[3])
            self.assign(words[4], re.sub(words[2], replacement, "".join(words[5:])))
        elif words[0] in ("TOLOWER", "TOUPPER"):
            self.assign(words[2], words[1].lower() if words[0] == "TOLOWER" else words[1].upper())
        else:
            self.notes.append(f"{where}: string({words[0]}) is not replayed")

    def do_message(self, args, where):
        words = self.arguments(args)
        if words[:1] in (["FATAL_ERROR"], ["SEND_ERROR"]):
            self.notes.append(f"{where}: configuring would stop here: {' '.join(words[1:])[:200]}")

    def do_find_program(self, args, where):
        words = self.arguments(args)
        name = words[0]
        if self.vars.get(name) and not self.vars[name].endswith("NOTFOUND"):
            return  # found before, e.g. a bundled engine: CMake does not search again
        candidates = []
        for word in words[1:]:
            if word in FIND_OPTIONS - {"NAMES"}:
                break
            if word != "NAMES":
                candidates.append(word)
        found = next(filter(None, (shutil.which(c, path=self.env.get("PATH")) for c in candidates)), None)
        self.assign(name, Path(found).as_posix() if found else f"{name}-NOTFOUND")

    def do_get_filename_component(self, args, where):
        words = self.arguments(args)
        name, path, mode = words[0], Path(words[1]), words[2]
        parts = path.name.split(".", 1)
        value = {"NAME": path.name, "DIRECTORY": path.parent.as_posix(), "PATH": path.parent.as_posix(),
                 "NAME_WE": parts[0], "EXT": "." + parts[1] if len(parts) > 1 else "",
                 "ABSOLUTE": path.absolute().as_posix(), "REALPATH": path.resolve().as_posix()}.get(mode)
        if value is None:
            return self.notes.append(f"{where}: get_filename_component({mode}) is not replayed")
        self.assign(name, value)

    def do_execute_process(self, args, where):
        options, key = {}, None
        for word in self.arguments(args):
            if word in PROCESS_OPTIONS:
                key = word
                options.setdefault(key, [])
            elif key:
                options[key].append(word)
        if not options.get("COMMAND"):
            return
        try:
            with open(options["INPUT_FILE"][0], "rb") if options.get("INPUT_FILE") else open(os.devnull, "rb") as stdin:
                done = subprocess.run(options["COMMAND"], stdin=stdin, capture_output=True, timeout=120, env=self.env)
            result, out, err = str(done.returncode), done.stdout.decode(errors="replace"), done.stderr.decode(errors="replace")
        except (OSError, subprocess.TimeoutExpired) as error:
            result, out, err = str(error), "", ""
        output, errors = (options.get("OUTPUT_VARIABLE") or [None])[0], (options.get("ERROR_VARIABLE") or [None])[0]
        if output and output == errors:
            out, err = out + err, out + err
        for option, value in (("RESULT_VARIABLE", result), ("OUTPUT_VARIABLE", out), ("ERROR_VARIABLE", err)):
            if options.get(option):
                self.assign(options[option][0], value)

    def do_file(self, args, where):
        words = self.arguments(args)
        if words[0] == "MAKE_DIRECTORY":
            for folder in words[1:]:
                Path(self.vars["CMAKE_CURRENT_BINARY_DIR"], folder).mkdir(parents=True, exist_ok=True)
        elif words[0] == "CREATE_LINK":
            target, link = Path(words[1]), Path(words[2])
            try:
                link.unlink(missing_ok=True)
                link.symlink_to(target) if "SYMBOLIC" in words else os.link(target, link)
            except OSError as error:
                self.notes.append(f"{where}: file(CREATE_LINK) failed: {error}")
        else:
            self.notes.append(f"{where}: file({words[0]}) is not replayed")

    def do_configure_file(self, args, where):
        words = self.arguments(args)
        source = Path(self.vars["CMAKE_CURRENT_SOURCE_DIR"], words[0])
        target = Path(self.vars["CMAKE_CURRENT_BINARY_DIR"], words[1])
        if target.is_dir():
            target = target / source.name
        if not source.is_file():
            return self.notes.append(f"{where}: configure_file() input {words[0]} is not in the checkout")
        target.parent.mkdir(parents=True, exist_ok=True)
        if "COPYONLY" in words:
            return shutil.copyfile(source, target)
        text = re.sub(r"@(\w+)@", lambda m: self.vars.get(m.group(1), ""),
                      source.read_text(encoding="utf-8", errors="replace"))
        if "@ONLY" not in words:
            text = re.sub(r"\$\{(\w+)\}", lambda m: self.vars.get(m.group(1), ""), text)
        target.write_text(text, encoding="utf-8")

    def do_include(self, args, where):
        words = self.arguments(args)
        path = Path(self.vars["CMAKE_CURRENT_SOURCE_DIR"], words[0])
        if path.is_file():
            self.run_file(path)
        elif "OPTIONAL" not in words:
            self.notes.append(f"{where}: include({words[0]}) is not in the checkout")

    def do_add_test(self, args, where):
        self.missing = set()
        words = self.arguments(args)
        test = {"depends": [], "will_fail": False, "pass_regex": None, "fail_regex": None, "skip_regex": None,
                "skip_code": None, "timeout": None, "environment": [], "working_directory": None, "source": where}
        if words[:1] == ["NAME"]:
            name, command, key = words[1], [], None
            for word in words[2:]:
                if word in ("COMMAND", "CONFIGURATIONS", "WORKING_DIRECTORY", "COMMAND_EXPAND_LISTS"):
                    key = word
                elif key == "COMMAND":
                    command.append(word)
                elif key == "WORKING_DIRECTORY":
                    test["working_directory"] = word
        else:
            name, command = words[0], words[1:]
        test.update(name=name, command=command, missing=sorted(self.missing))
        if name not in self.tests:
            self.order.append(name)
        self.tests[name] = test

    def do_set_tests_properties(self, args, where):
        words = self.arguments(args)
        if "PROPERTIES" not in words:
            return
        k = words.index("PROPERTIES")
        for name in words[:k]:
            test = self.tests.get(name)
            if test is None:
                self.notes.append(f"{where}: set_tests_properties() names {name}, which is not defined")
                continue
            for key, value in zip(words[k + 1::2], words[k + 2::2]):
                if key == "DEPENDS":
                    test["depends"] += split_list(value)
                elif key == "WILL_FAIL":
                    test["will_fail"] = constant(value) is True
                elif key in ("PASS_REGULAR_EXPRESSION", "FAIL_REGULAR_EXPRESSION", "SKIP_REGULAR_EXPRESSION"):
                    test[key.split("_")[0].lower() + "_regex"] = split_list(value)
                elif key == "SKIP_RETURN_CODE":
                    test["skip_code"] = int(value)
                elif key == "TIMEOUT":
                    test["timeout"] = float(value)
                elif key == "ENVIRONMENT":
                    test["environment"] = split_list(value)
                elif key == "WORKING_DIRECTORY":
                    test["working_directory"] = value


# ------------------------------------------------------------------------------------------
# What the package was built with
# ------------------------------------------------------------------------------------------
def probe(*command, env=None):
    try:
        return subprocess.run([str(c) for c in command], capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=120, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def loads_zlib_ng(bin_dir):
    """Whether the tools load zlib-ng, which the build records as HAVE_ZLIB_NG (its zlib.h
    defines ZLIBNG_VERSION). zlib-ng names itself in the version it reports, classic zlib
    does not, so the loaded zlib and OpenMS libraries (zlib may be linked in) are searched."""
    tool = bin_dir / f"FileInfo{EXE}"
    if sys.platform == "darwin":
        loaded = probe(tool, "--help", env=dict(os.environ, DYLD_PRINT_LIBRARIES="1"))
        libraries = re.findall(r"(/\S+\.dylib)", loaded.stderr) if loaded else []
    elif WINDOWS:  # the loader looks next to the executable first
        libraries = [str(p) for p in bin_dir.glob("*.dll")]
    else:
        listing = probe("ldd", tool)
        libraries = re.findall(r"=>\s*(/\S+)", listing.stdout) if listing else []
    candidates = sorted({p for p in libraries
                         if re.match(r"(lib)?(z|zlib1?|z-ng|zlib-ng2?|OpenMS)[.-]", Path(p).name, re.I)})
    if not candidates:
        return False, "no zlib or OpenMS library found among the loaded libraries; assumed classic zlib"
    marked = [p for p in candidates if b"zlib-ng" in Path(p).read_bytes()]
    return bool(marked), ("zlib-ng in " + ", ".join(marked)) if marked else "no zlib-ng in " + ", ".join(candidates)


def package_configuration(bin_dir, share):
    """The variables the TOPP test files take from the build (TOPP_TOOLS, build options,
    platform), as this package answers them, and how each answer was found."""
    registry = sorted((share / "TOOLS").glob("*.tsv"))
    tools = [line.split("\t")[0] for path in registry for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    listed = probe(bin_dir / f"FileConverter{EXE}", "--help")  # TOPP tools print their help on stderr
    formats = listed.stdout + listed.stderr if listed else ""
    with tempfile.TemporaryDirectory() as folder:  # CWL export exists only with ENABLE_TDL
        cwl = probe(bin_dir / f"FileInfo{EXE}", "-write_cwl", folder)
        writes_cwl = cwl is not None and cwl.returncode == 0 and any(p.stat().st_size for p in Path(folder).iterdir())
    zlib_ng, zlib_evidence = loads_zlib_ng(bin_dir)
    on = lambda flag: "ON" if flag else "OFF"
    found = {
        "TOPP_TOOLS": (";".join(tools), f"{len(tools)} tools in {', '.join(p.as_posix() for p in registry)}"),
        "OPENMS_TOOL_REGISTRY_BUILD_FILE": (registry[0].as_posix() if registry else "", "the installed registry"),
        "DISABLE_OPENSWATH": (on("OpenSwathWorkflow" not in tools), "OpenSwathWorkflow in the registry or not"),
        "WITH_WNETALIGN": (on("FeatureLinkerWNet" in tools), "FeatureLinkerWNet in the registry or not"),
        "WITH_GUI": (on("ImageCreator" in tools), "ImageCreator (built only WITH_GUI) in the registry or not"),
        "HAS_XSERVER": ("ON", "CMake default; tests run with QT_QPA_PLATFORM=offscreen"),
        "WITH_OPENTIMS": (on("'d'" in formats), "'d' among FileConverter's input formats or not"),
        "ENABLE_TDL": (on(writes_cwl), "FileInfo -write_cwl " + ("wrote a CWL file" if writes_cwl else
                       f"failed (exit {cwl.returncode if cwl else 'n/a'})")),
        "HAVE_ZLIB_NG": (on(zlib_ng), zlib_evidence),
        "CMAKE_SYSTEM_NAME": ({"win32": "Windows", "darwin": "Darwin"}.get(sys.platform, "Linux"), "this machine"),
        "CMAKE_HOST_SYSTEM_PROCESSOR": (platform.machine(), "this machine"),
    }
    flags = {"WIN32": WINDOWS, "MSVC": WINDOWS, "APPLE": sys.platform == "darwin", "UNIX": not WINDOWS}
    found.update({flag: ("1", "this machine") for flag, true in flags.items() if true})
    return {k: v for k, (v, _) in found.items()}, {k: e for k, (_, e) in found.items()}


# ------------------------------------------------------------------------------------------
# Running the tests
# ------------------------------------------------------------------------------------------
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


def posix_shell(name):
    """A usable bash/sh. On Windows, System32's bash.exe is the WSL launcher, which fails on
    runners without a Linux distribution; Git for Windows ships a real one."""
    found = shutil.which(name)
    if not WINDOWS:
        return found
    if found and "system32" not in found.lower():
        return found
    for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), r"C:\Program Files\Git"):
        for candidate in (Path(root) / "Git" / "bin" / f"{name}.exe", Path(root) / "bin" / f"{name}.exe"):
            if candidate.is_file():
                return str(candidate)
    return None


def any_match(patterns, text):
    """ctest's regular-expression properties are lists; one matching element is enough."""
    return any(re.search(p, text) for p in patterns)


def tracked_files(openms):
    """The files of the checkout's revision, including those a sparse checkout leaves out."""
    try:
        listing = subprocess.run(["git", "-C", str(openms), "ls-files"], capture_output=True, text=True,
                                 check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {posixpath.join(openms.as_posix(), line) for line in listing.splitlines()}


def absent_inputs(command, tracked):
    """Files of the revision that a command names but the sparse checkout does not have. A
    path the revision does not have either is left alone: some tests expect it to be missing."""
    absent = []
    for token in command[1:]:
        value = token.split("=", 1)[1] if token.startswith("-D") and "=" in token else token
        for piece in value.split():  # a list parameter can be one argument of several paths
            path = posixpath.normpath(piece)
            if path in tracked and not Path(path).exists():
                absent.append(path)
    return absent


def run_group(names, tests, work, timeout, results, env, tracked):
    for name in names:
        test = tests[name]
        failed_deps = [d for d in test["depends"] if d in tests and results.get(d, {}).get("status") not in (None, "passed")]
        command = list(test["command"])
        if command and command[0] in ("bash", "sh"):
            shell = posix_shell(command[0])
            command = [shell] + command[1:] if shell else command
        result = {"test": name, "source": test["source"]}
        executable = Path(command[0]) if command else None
        # Inputs are read from the source checkout; outputs go to the scratch directory. An
        # input the checkout lacks (e.g. class-test data outside src/tests/topp) is a limit
        # of this harness, not a failure of the package.
        absent = absent_inputs(command, tracked)
        if test["missing"]:
            result.update(status="skipped", reason=f"uses CMake variables nothing defines: {test['missing']}")
        elif absent:
            result.update(status="skipped", reason=f"input not in the source checkout: {Path(absent[0]).name}")
        elif failed_deps:
            result.update(status="skipped", reason=f"depends on {failed_deps}, which did not pass")
        elif executable is None or not (executable.is_file() or shutil.which(str(executable))):
            result.update(status="skipped", reason=f"executable not installed: {command[0] if command else ''}")
        else:
            test_env = dict(env, **dict(e.split("=", 1) for e in test["environment"] if "=" in e))
            limit = test["timeout"] or timeout
            started = time.monotonic()
            try:
                completed = subprocess.run(command, cwd=test["working_directory"] or work, capture_output=True,
                                           text=True, errors="replace", timeout=limit, stdin=subprocess.DEVNULL,
                                           env=test_env)
                output, code = completed.stdout + completed.stderr, completed.returncode
                # ctest's rules: a PASS_REGULAR_EXPRESSION replaces the exit code as the verdict,
                # a FAIL_REGULAR_EXPRESSION match fails, WILL_FAIL inverts the outcome.
                forced = ((test["pass_regex"] and not any_match(test["pass_regex"], output))
                          or (test["fail_regex"] and any_match(test["fail_regex"], output)))
                success = not forced and (code == 0 or bool(test["pass_regex"]))
                if test["skip_code"] is not None and code == test["skip_code"]:
                    # ctest lists this as not run; the test uses it to assert this exact exit code
                    status = "passed"
                    result["note"] = f"exit {code} is the test's SKIP_RETURN_CODE"
                elif test["skip_regex"] and any_match(test["skip_regex"], output):
                    status = "skipped"
                    result["reason"] = "its SKIP_REGULAR_EXPRESSION matched"
                else:
                    status = "passed" if success != test["will_fail"] else "failed"
                result.update(status=status, exit=code)
                if status == "failed":
                    result["output_tail"] = "\n".join(output.strip().splitlines()[-40:])
                    if test["pass_regex"]:  # show what the expected line said instead
                        words = re.findall(r"[A-Za-z]{4,}", test["pass_regex"][0])[:2]
                        result["near_expected"] = [l for l in output.splitlines() if words and all(w in l for w in words)][:5]
            except subprocess.TimeoutExpired:
                result.update(status="failed", reason=f"timeout after {limit}s")
            result["seconds"] = round(time.monotonic() - started, 1)
            result["command"] = " ".join(command)
        results[name] = result


def fetch_missing_inputs(openms, selected, tracked):
    """Add inputs outside src/tests/topp (class-test data) to a sparse checkout, file by file."""
    wanted = {"/" + posixpath.relpath(path, openms.as_posix())
              for test in selected for path in absent_inputs(test["command"], tracked)}
    if not wanted:
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
    parser.add_argument("-D", dest="define", action="append", default=[], metavar="NAME=VALUE",
                        help="set a variable before the test files are read, e.g. -D OPENTIMS_DDA_TEST_DATA=<dir.d>")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--timeout", type=int, default=900, help="seconds per test without its own TIMEOUT")
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
    topp = openms / "src/tests/topp"
    if not (topp / "CMakeLists.txt").is_file():
        raise SystemExit(f"{topp / 'CMakeLists.txt'} not found; check out src/tests/topp")

    # Tests run in a scratch copy of the test binary directory, as in the build tree, where
    # several write to a relative "tmp_path/..." as well as to ${TESTS_TEMP_DIR}.
    work = Path(tempfile.mkdtemp(prefix="installed-topp-"))
    engines = {}
    for variable, (folder, candidates) in ENGINES.items():
        found = next((share / "THIRDPARTY" / folder / c for c in candidates
                      if (share / "THIRDPARTY" / folder / c).is_file()), None)
        if found:
            engines[variable] = found
    # CI finds the engines on PATH (find_program(... PATHS ENV PATH)), and a few tools call
    # other tools by name, so the tests run with the bin directory and the engines on PATH.
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PATH=os.pathsep.join([str(bin_dir)] + sorted({str(p.parent) for p in engines.values()})
                                    + [os.environ.get("PATH", "")]))
    configuration, evidence = package_configuration(bin_dir, share)
    # Forward slashes everywhere: the OpenMS tools accept them on Windows, and a path that
    # ends up inside a `bash -c "..."` script must not carry backslash escapes.
    posix = lambda path: Path(path).as_posix()
    variables = {
        **configuration,
        **{name: posix(path) for name, path in engines.items()},
        "CMAKE_RUNTIME_OUTPUT_DIRECTORY": posix(bin_dir), "OPENMS_HOST_DIRECTORY": posix(openms),
        "CMAKE_SOURCE_DIR": posix(openms), "PROJECT_SOURCE_DIR": posix(topp), "CMAKE_CURRENT_SOURCE_DIR": posix(topp),
        "CMAKE_CURRENT_LIST_DIR": posix(topp), "PROJECT_BINARY_DIR": posix(work),
        "CMAKE_CURRENT_BINARY_DIR": posix(work), "CMAKE_BINARY_DIR": posix(work),
    }
    if shutil.which("cmake"):
        variables["CMAKE_COMMAND"] = posix(shutil.which("cmake"))
    for definition in args.define:
        name, _, value = definition.partition("=")
        variables[name] = value
        evidence[name] = "set with -D"
    replay = Replay(variables, {"DATA_DIR_SHARE": posix(share)}, env)
    replay.run_file(topp / "CMakeLists.txt")
    tests, order = replay.tests, replay.order

    pattern = {"release-gate": RELEASE_GATE, "all": "."}.get(args.select, args.select)
    chosen = select(tests, order, pattern)
    not_registered = [n for n in replay.excluded if n not in tests and re.search(pattern, n)]
    tracked = tracked_files(openms)
    if args.fetch_missing:
        fetch_missing_inputs(openms, [tests[n] for n in chosen], tracked)
    results = {n: {"test": n, "source": replay.excluded[n]["source"], "status": "skipped",
                   "reason": "not registered: " + replay.excluded[n]["reason"]} for n in not_registered}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda group: run_group(group, tests, work, args.timeout, results, env, tracked),
                      components(chosen, tests)))

    ordered = [results[n] for n in chosen + not_registered]
    summary = {}
    for result in ordered:
        summary[result["status"]] = summary.get(result["status"], 0) + 1
    report = {"openms": str(openms), "bin_dir": str(bin_dir), "share_dir": str(share), "selection": pattern,
              "package_configuration": {k: {"value": variables[k][:200], "evidence": evidence[k]} for k in evidence},
              "replay_notes": replay.notes, "defined_tests": len(order), "not_registered": len(replay.excluded),
              "selected": len(ordered), "summary": summary, "tests": ordered,
              "status": "passed" if not summary.get("failed") else "failed"}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)

    for name in ("ENABLE_TDL", "HAVE_ZLIB_NG", "WITH_OPENTIMS", "WITH_GUI", "DISABLE_OPENSWATH", "WITH_WNETALIGN"):
        print(f"  {name}={variables[name]} ({evidence[name]})")
    for note in replay.notes:
        print(f"  replay note: {note}")
    print(f"{len(chosen)} of the {len(order)} upstream TOPP tests registered for this package selected, and "
          f"{len(not_registered)} of the {len(replay.excluded)} it does not register: {summary}")
    for result in ordered:
        if result["status"] == "failed":
            last = (result.get("output_tail") or result.get("reason") or "").splitlines()[-1:] or [""]
            print(f"  FAILED  {result['test']}: {last[0][:160]}")
    skipped = {}
    for result in ordered:
        if result["status"] == "skipped":
            skipped[result["reason"][:110]] = skipped.get(result["reason"][:110], 0) + 1
    for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  skipped x{count}: {reason}")
    print(f"status: {report['status']}; report: {args.report}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
