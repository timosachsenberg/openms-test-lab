"""Time OpenMS TOPP tools built with and without an MSVC /arch: flag (OpenMS/OpenMS#8845).

OpenMS dropped /arch:AVX for MSVC because the 256-bit Eigen reductions rounded differently
from the 128-bit ones GCC and Clang use (cmake/compiler_flags.cmake). Whether that costs the
Windows binaries anything was never measured. The Windows AVX benchmark workflow builds the
same OpenMS commit once as it is ("baseline") and once per variant, and this script does
the parts of that which are worth testing off the runner. A variant is an /arch: value
(AVX, AVX2, AVX512) or SIMDE_SSSE3, which keeps the default /arch and only lets SIMDe use
the SSSE3 intrinsics instead of emulating them.

    targets                 print the build targets the benchmark needs
    patch                   add the flag of a variant to cmake/compiler_flags.cmake
    package                 collect the built tools and record how they were compiled
    prepare                 turn a Thermo RAW file into the benchmark inputs
    run                     time every tool, variants interleaved, and write the report

Timing rules: every variant runs on the same machine, the order of the variants rotates from
one repetition to the next, a warm-up run of each variant precedes the timed ones, and
repetition i of one variant is compared with repetition i of the baseline, which ran right
next to it. A hosted runner is a shared virtual machine, so read the range, not one number.

    python scripts/avx-benchmark.py run --variant-dir downloads/bin/* \
        --share-dir _openms/share/OpenMS --work work --report reports/avx-benchmark.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time

WINDOWS = sys.platform.startswith("win")
EXE = ".exe" if WINDOWS else ""
ISSUE = "https://github.com/OpenMS/OpenMS/issues/8845"
BASELINE = "baseline"
ARCH_VALUES = {"AVX", "AVX2", "AVX512"}
# OpenMS codes Base64 and transcodes XML strings with SSSE3 intrinsics through SIMDe. GCC and
# Clang get -mssse3. MSVC x64 has no macro that announces SSSE3 below /arch:AVX, so SIMDe
# emulates those intrinsics byte by byte unless this macro tells it to use them; MSVC compiles
# them without any /arch flag. The variant separates that effect from the rest of /arch:AVX.
SIMDE_SSSE3 = "SIMDE_SSSE3"
SIMDE_DEFINE = "SIMDE_X86_SSSE3_NATIVE"

# The two lines OpenMS/OpenMS#8787 left in cmake/compiler_flags.cmake, and what stood there
# before it, with the flag of the variant. Matched exactly: if upstream rewrites the block,
# the build must stop, not time two identical binaries.
FLAGS_FILE = "cmake/compiler_flags.cmake"
SIMD_NOW = ('  if(NOT MSVC AND ${CMAKE_SYSTEM_PROCESSOR} MATCHES "${x64_CPU}")\n'
            '    target_compile_options(${target_name} PUBLIC -mssse3)\n')
SIMD_WITH_FLAG = ('  if(MSVC AND ${CMAKE_SYSTEM_PROCESSOR} MATCHES "${x64_CPU}")\n'
                  '    target_compile_options(${target_name} PUBLIC @FLAG@)\n'
                  '  elseif(NOT MSVC AND ${CMAKE_SYSTEM_PROCESSOR} MATCHES "${x64_CPU}")\n'
                  '    target_compile_options(${target_name} PUBLIC -mssse3)\n')

# name, what the run exercises, input, output suffix, extra arguments.
# profile.mzML and centroided.mzML are written by `prepare`.
STEPS = [
    ("FileConverter", "mzML to mzML: parse, decode, encode and write every spectrum",
     "profile.mzML", ".mzML", []),
    ("NoiseFilterGaussian", "Gaussian smoothing of the profile spectra",
     "profile.mzML", ".mzML", []),
    ("PeakPickerHiRes", "spline peak picking of the profile MS1 spectra",
     "profile.mzML", ".mzML", []),
    ("FeatureFinderCentroided", "isotope pattern seeding and model fitting on centroided MS1",
     "centroided.mzML", ".featureXML", []),
]
HELPERS = ["FileFilter", "FileInfo"]  # used by `prepare` and the smoke test, not timed


def log(message):
    print(message, flush=True)


def variant_flag(variant):
    """What a variant adds to the MSVC x64 compile line; nothing for the baseline."""
    if variant == BASELINE:
        return None
    if variant in ARCH_VALUES:
        return f"/arch:{variant}"
    if variant == SIMDE_SSSE3:
        return f"/D{SIMDE_DEFINE}"
    raise SystemExit(f"Unknown variant '{variant}': use {BASELINE}, {SIMDE_SSSE3} or one of "
                     f"{sorted(ARCH_VALUES)}")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tool_registry(share_dir, work):
    """Where the tools find the TOPP tool registry, or None if the data path already has it.

    A tool looks its own name up in share/OpenMS/TOOLS/*.tsv and refuses to start without it.
    OpenMS generates that file in the build tree, so the source checkout the data path points
    at has none, and the build tree stayed on the build runner. The registry only says that a
    tool exists and which TOPPAS category it is listed under: write one for the tools of this
    benchmark. An installed share directory brings its own, and a second file naming the same
    tools would be a collision.
    """
    if any((Path(share_dir) / "TOOLS").glob("*.tsv")):
        return None
    folder = Path(work) / "registry"
    folder.mkdir(parents=True, exist_ok=True)
    rows = [f"{tool}\tBenchmark" for tool in [name for name, *_ in STEPS] + HELPERS]
    (folder / "avx-benchmark.tsv").write_text(
        "# tool\tcategory (written by scripts/avx-benchmark.py)\n" + "\n".join(rows) + "\n",
        "utf-8")
    return folder


def tool_env(bin_dir, share_dir, registry=None):
    """The environment of one tool: its own bin directory first, the data path of the commit."""
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["OPENMS_DATA_PATH"] = str(share_dir)
    for name in ("OPENMS_TOOL_REGISTRY_PATH", "OPENMS_TTD_INTERNAL_PATH"):
        env.pop(name, None)
    if registry:
        env["OPENMS_TOOL_REGISTRY_PATH"] = str(registry)
    # Otherwise a tool may ask the OpenMS server for a newer version when it starts, and the
    # round trip would be part of its wall time.
    env["OPENMS_DISABLE_UPDATE_CHECK"] = "ON"
    if not WINDOWS:  # an unpacked Linux package, for testing this script off the runner
        lib = Path(bin_dir).parent / "lib"
        env["LD_LIBRARY_PATH"] = str(lib) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    return env


# --- process accounting -------------------------------------------------------------------

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class _MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage")]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(_FILETIME)] * 4
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.K32GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_MEMORY_COUNTERS), wintypes.DWORD]
    _kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    _kernel32.IsProcessorFeaturePresent.argtypes = [wintypes.DWORD]
    _kernel32.IsProcessorFeaturePresent.restype = wintypes.BOOL

    def _seconds(filetime):
        return ((filetime.high << 32) | filetime.low) / 1e7


def timed_run(command, env, log_path):
    """Run one process to its end; wall time, CPU time and peak memory of that process."""
    with open(log_path, "wb") as sink:
        # A hosted runner also runs its agent and Windows services: keep them from
        # preempting the tool. Both variants get the same treatment.
        flags = subprocess.HIGH_PRIORITY_CLASS if WINDOWS else 0
        start = time.perf_counter()
        process = subprocess.Popen(command, env=env, stdout=sink, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=flags)
        if WINDOWS:
            code = process.wait()
            wall = time.perf_counter() - start
            handle = int(process._handle)  # stays open until the Popen object is collected
            created, exited, kernel, user = (_FILETIME() for _ in range(4))
            if not _kernel32.GetProcessTimes(handle, created, exited, kernel, user):
                raise ctypes.WinError(ctypes.get_last_error())
            counters = _MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if not _kernel32.K32GetProcessMemoryInfo(handle, counters, counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            cpu_user, cpu_kernel = _seconds(user), _seconds(kernel)
            peak_mb = counters.PeakWorkingSetSize / 2 ** 20
        else:
            _, status, usage = os.wait4(process.pid, 0)
            wall = time.perf_counter() - start
            code = os.waitstatus_to_exitcode(status)
            process.returncode = code
            cpu_user, cpu_kernel = usage.ru_utime, usage.ru_stime
            peak_mb = usage.ru_maxrss / (2 ** 20 if sys.platform == "darwin" else 2 ** 10)
    return {"exit_code": code, "wall_s": round(wall, 3), "cpu_user_s": round(cpu_user, 3),
            "cpu_kernel_s": round(cpu_kernel, 3), "peak_mb": round(peak_mb, 1)}


def checked_run(command, env, log_path, what):
    result = timed_run([str(part) for part in command], env, log_path)
    if result["exit_code"] != 0:
        tail = Path(log_path).read_text("utf-8", "replace")[-3000:]
        raise SystemExit(f"{what} failed with exit code {result['exit_code']}:\n{tail}")
    return result


# --- what the machine is ------------------------------------------------------------------

def host_info():
    info = {"os": platform.platform(), "logical_cpus": os.cpu_count(),
            "python": platform.python_version(), "runner_image": os.environ.get("ImageVersion"),
            "runner_name": os.environ.get("RUNNER_NAME")}
    if WINDOWS:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        info["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        # PF_AVX_INSTRUCTIONS_AVAILABLE, PF_AVX2_..., PF_AVX512F_... (winnt.h)
        info["cpu_features"] = {name: bool(_kernel32.IsProcessorFeaturePresent(number))
                                for name, number in (("avx", 39), ("avx2", 40), ("avx512f", 41))}
    else:
        text = Path("/proc/cpuinfo").read_text() if Path("/proc/cpuinfo").exists() else ""
        model = re.search(r"model name\s*:\s*(.+)", text)
        flags = set((re.search(r"flags\s*:\s*(.+)", text) or [None, ""])[1].split())
        info["cpu"] = model.group(1).strip() if model else platform.processor()
        info["cpu_features"] = {name: name in flags for name in ("avx", "avx2", "avx512f")}
    return info


# --- patch ---------------------------------------------------------------------------------

def patch(args):
    flag = variant_flag(args.variant)
    if not flag:
        raise SystemExit(f"The {BASELINE} is the source as it is: nothing to patch.")
    path = Path(args.openms) / FLAGS_FILE
    text = path.read_text("utf-8")
    if (text.count(SIMD_NOW) != 1 or "/arch:" in text.replace("do NOT use /arch:AVX", "")
            or SIMDE_DEFINE in text):
        raise SystemExit(f"{path} no longer has the SIMD block this patch expects; "
                         "compare it with OpenMS/OpenMS#8787 and update SIMD_NOW.")
    path.write_text(text.replace(SIMD_NOW, SIMD_WITH_FLAG.replace("@FLAG@", flag)),
                    "utf-8", newline="\n")
    log(f"{FLAGS_FILE}: MSVC x64 targets now compile with {flag}")


# --- package -------------------------------------------------------------------------------

def compile_flags(build_dir):
    """How many translation units were compiled, with which /arch: value and SIMDe macro."""
    commands = json.loads((Path(build_dir) / "compile_commands.json").read_text("utf-8"))
    counts, defined = {}, 0
    for entry in commands:
        line = entry.get("command") or " ".join(entry.get("arguments", []))
        found = re.findall(r"[/-]arch:(\S+)", line)
        key = found[-1].strip('"') if found else "none"
        counts[key] = counts.get(key, 0) + 1
        defined += bool(re.search(rf"[/-]D ?{SIMDE_DEFINE}\b", line))
    return {"translation_units": len(commands), "arch_flag": counts,
            "defines": {SIMDE_DEFINE: defined}}


def flagged_units(flag, flags):
    """Of the counts of compile_flags(), the translation units that carry a variant's flag."""
    if not flag:
        return 0
    if flag.startswith("/arch:"):
        return flags.get("arch_flag", {}).get(flag[len("/arch:"):], 0)
    return flags.get("defines", {}).get(flag[len("/D"):], 0)


def cache_value(build_dir, name):
    match = re.search(rf"^{re.escape(name)}(?::\w+)?=(.*)$",
                      (Path(build_dir) / "CMakeCache.txt").read_text("utf-8", "replace"), re.M)
    return match.group(1).strip() if match else None


def package(args):
    build_dir, out = Path(args.build_dir), Path(args.out)
    bin_dir = build_dir / "bin"
    flags = compile_flags(build_dir)
    flag = variant_flag(args.variant)
    total = flags["translation_units"]
    # The whole point of a variant: if its flag did not reach the compiler, or another
    # variant's flag did, stop here instead of timing two builds of the same code. Vendored
    # libraries set their own flags, so "most of the sources" is the test, not "all".
    has_own = flagged_units(flag, flags) * 2 >= total if flag else True
    others = (total - flags["arch_flag"].get("none", 0) + flags["defines"][SIMDE_DEFINE]
              - flagged_units(flag, flags))
    if total < 100 or not has_own or others * 20 > total:
        raise SystemExit(f"Variant {args.variant}: expected {flag or 'no SIMD flag'} on the "
                         f"OpenMS sources, found {flags['arch_flag']} and {flags['defines']}")
    out.mkdir(parents=True, exist_ok=True)
    tools = [name for name, *_ in STEPS] + HELPERS
    for tool in tools:
        shutil.copy2(bin_dir / f"{tool}{EXE}", out)
    libraries = sorted(bin_dir.glob("*.dll")) if WINDOWS else []
    for library in libraries:
        shutil.copy2(library, out)
    compiler = None
    for candidate in (build_dir / "CMakeFiles").glob("*/CMakeCXXCompiler.cmake"):
        found = re.search(r'CMAKE_CXX_COMPILER_VERSION "([^"]+)"', candidate.read_text("utf-8"))
        compiler = found.group(1) if found else compiler
    commit = subprocess.run(["git", "-C", args.openms, "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    info = {"variant": args.variant, "flag": flag, "openms_commit": commit,
            "compiler_version": compiler,
            "build_type": cache_value(build_dir, "CMAKE_BUILD_TYPE"),
            "vcpkg_triplet": cache_value(build_dir, "VCPKG_TARGET_TRIPLET"),
            "options": {name: cache_value(build_dir, name) for name in (
                "MT_ENABLE_OPENMP", "WITH_THERMO_RAW", "WITH_OPENTIMS", "WITH_MIMALLOC",
                "ENABLE_IPO", "ENABLE_UNITYBUILD")},
            "compile_flags": flags, "tools": tools,
            "files": {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                      for path in sorted(out.iterdir()) if path.is_file()}}
    (out / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", "utf-8")
    log(json.dumps({key: info[key] for key in ("variant", "compiler_version", "compile_flags")}))


# --- prepare -------------------------------------------------------------------------------

SPECTRUM = re.compile(rb"<spectrum [^>]*defaultArrayLength=\"(\d+)\"")
FEATURE = re.compile(rb"<feature id=")
# The lines that carry the numbers a tool computed: the encoded arrays of an mzML file, and
# position, intensity, quality, charge and hull points of a featureXML file.
NUMBERS = re.compile(rb"<binary>|<position dim=|<intensity>|<quality dim=|<overallquality>|"
                     rb"<charge>|<pt x=")


def fingerprint(path):
    """What a tool wrote, without what changes from run to run (ids, timestamps, paths).

    content_sha256 covers every computed number in file order, so two outputs with the same
    value are numerically identical, not merely the same size.
    """
    path = Path(path)
    result = {"bytes": path.stat().st_size}
    spectra = points = features = 0
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for line in handle:
            if NUMBERS.search(line[:200]):
                digest.update(line.strip())
            if len(line) > 4096:  # an encoded array, never a tag we count
                continue
            for match in SPECTRUM.finditer(line):
                spectra += 1
                points += int(match.group(1))
            features += len(FEATURE.findall(line))
    if path.suffix.lower() == ".mzml":
        result.update(spectra=spectra, data_points=points)
    else:
        result.update(features=features)
    result["content_sha256"] = digest.hexdigest()
    return result


def same_content(first, second):
    return all(first[key] == second[key] for key in first if key != "bytes")


def find_variant(directory):
    directory = Path(directory)
    info_file = directory / "build-info.json"
    info = json.loads(info_file.read_text("utf-8")) if info_file.exists() else {}
    return {"name": info.get("variant", directory.name), "dir": directory, "build_info": info}


def preflight(variants, share_dir, registry, logs):
    """Start one tool of every variant: a package that cannot run shows here, not as a timing."""
    for variant in variants:
        log_path = logs / f"preflight-{variant['name']}.log"
        result = timed_run([str(variant["dir"] / f"FileInfo{EXE}"), "--help"],
                           tool_env(variant["dir"], share_dir, registry), log_path)
        text = log_path.read_text("utf-8", "replace")
        if result["exit_code"] != 0 or "FileInfo" not in text:
            raise SystemExit(f"FileInfo of variant {variant['name']} does not start (exit code "
                             f"{result['exit_code']:#x}). With no output below, a runtime DLL "
                             f"is missing next to it:\n{text[-2000:]}")


def prepare(args):
    window = "" if args.rt_window in ("", "all") else args.rt_window
    if window and not re.fullmatch(r"\d+(\.\d+)?:\d+(\.\d+)?", window):
        raise SystemExit("--rt-window is start:end in seconds, or all")
    work = Path(args.work).resolve()
    data = work / "data"
    logs = work / "logs"
    for folder in (data, logs):
        folder.mkdir(parents=True, exist_ok=True)
    bin_dir, share_dir = Path(args.bin_dir).resolve(), Path(args.share_dir).resolve()
    registry = tool_registry(share_dir, work)
    env = tool_env(bin_dir, share_dir, registry)
    preflight([find_variant(bin_dir)], share_dir, registry, logs)
    tool = lambda name: bin_dir / f"{name}{EXE}"
    raw = Path(args.raw).resolve()
    full, profile, centroided = data / "full.mzML", data / "profile.mzML", data / "centroided.mzML"
    digest = sha256(raw)
    if args.raw_sha256 not in ("", "none") and digest != args.raw_sha256.lower():
        raise SystemExit(f"{raw.name} has SHA-256 {digest}, expected {args.raw_sha256}")
    record = {"raw_file": raw.name, "raw_bytes": raw.stat().st_size, "raw_sha256": digest,
              "raw_sha256_verified": args.raw_sha256 not in ("", "none"),
              "source": args.source, "rt_window_s": window or None, "steps": []}

    converter = [str(Path(args.converter).resolve())]
    converter = converter if WINDOWS else ["mono"] + converter
    # -p keeps the profile data of the instrument: PeakPickerHiRes and the noise filter need
    # it, and the centroided input of the feature finder is then made by OpenMS itself.
    convert = converter + [f"-i={raw}", f"-b={full}", "-f=2", "-p"]
    record["steps"].append({"command": "ThermoRawFileParser -i=<raw> -b=full.mzML -f=2 -p",
                            **checked_run(convert, dict(os.environ), logs / "prepare-convert.log",
                                          "RAW conversion")})
    if window:
        command = [tool("FileFilter"), "-in", full, "-out", profile, "-rt", window,
                   "-no_progress"]
        record["steps"].append({"command": f"FileFilter -in full.mzML -out profile.mzML -rt "
                                           f"{window}",
                                **checked_run(command, env, logs / "prepare-filter.log",
                                              "FileFilter")})
        full.unlink()
    else:
        full.replace(profile)
    command = [tool("PeakPickerHiRes"), "-in", profile, "-out", centroided, "-no_progress"]
    record["steps"].append({"command": "PeakPickerHiRes -in profile.mzML -out centroided.mzML",
                            **checked_run(command, env, logs / "prepare-pick.log",
                                          "PeakPickerHiRes")})
    record["files"] = {path.name: fingerprint(path) for path in (profile, centroided)}
    record["prepared_with"] = find_variant(bin_dir)["name"]
    (data / "dataset.json").write_text(json.dumps(record, indent=2) + "\n", "utf-8")
    log(json.dumps(record["files"], indent=2))


# --- run -----------------------------------------------------------------------------------

def summarize(values):
    values = list(values)
    mean = statistics.fmean(values)
    return {"n": len(values), "median": round(statistics.median(values), 3),
            "min": round(min(values), 3), "max": round(max(values), 3),
            "cv_percent": round(100 * statistics.stdev(values) / mean, 2)
            if len(values) > 1 and mean else 0.0}


def paired_speedup(reference, other):
    """baseline time / variant time for the runs that stood next to each other; > 1 is faster."""
    ratios = [ref / val for ref, val in zip(reference, other) if val > 0]
    result = {"median": round(statistics.median(ratios), 4), "min": round(min(ratios), 4),
              "max": round(max(ratios), 4)}
    result["verdict"] = ("faster in every pair" if result["min"] > 1 else
                         "slower in every pair" if result["max"] < 1 else "not separable")
    return result


def run(args):
    work = Path(args.work).resolve()
    share_dir = Path(args.share_dir).resolve()
    data, logs, out = work / "data", work / "logs", work / "out"
    for folder in (logs, out):
        folder.mkdir(parents=True, exist_ok=True)
    variants = [find_variant(Path(directory).resolve()) for directory in args.variant_dir]
    variants.sort(key=lambda variant: (variant["name"] != BASELINE, variant["name"]))
    names = [variant["name"] for variant in variants]
    if names[0] != BASELINE or len(set(names)) != len(names) or len(names) < 2:
        raise SystemExit(f"Need the baseline and at least one other variant, got {names}")
    commits = {variant["build_info"].get("openms_commit") for variant in variants}
    if len(commits) != 1:
        raise SystemExit(f"The variants were built from different commits: {commits}")
    selected = [step for step in STEPS if not args.tools or step[0] in args.tools]
    registry = tool_registry(share_dir, work)
    preflight(variants, share_dir, registry, logs)
    dataset_file = data / "dataset.json"
    report = {
        "schema": 2, "issue": ISSUE, "openms_commit": commits.pop(), "host": host_info(),
        "settings": {"repetitions": args.repetitions, "warmup": args.warmup,
                     "threads": args.threads, "budget_minutes_per_tool": args.budget_minutes,
                     "order": "variants rotate from one repetition to the next",
                     "priority": "high" if WINDOWS else "normal",
                     "tool_registry": "written by the benchmark for its tools" if registry
                     else "of the share directory"},
        "dataset": json.loads(dataset_file.read_text("utf-8")) if dataset_file.exists() else None,
        # "arch_flag" is what packages made before the SIMDe variant existed call the flag.
        "variants": [{"name": variant["name"], "flag": variant["build_info"].get(
                          "flag", variant["build_info"].get("arch_flag")),
                      **{key: variant["build_info"].get(key) for key in
                         ("compiler_version", "build_type", "options", "compile_flags")}}
                     for variant in variants],
        "tools": [],
    }

    def invoke(variant, step, label):
        name, _, source, suffix, extra = step
        target = out / f"{name}{suffix}"  # the same path for every variant: outputs name it
        command = [str(variant["dir"] / f"{name}{EXE}"), "-in", str(data / source), "-out",
                   str(target), "-threads", str(args.threads), "-no_progress"] + extra
        result = timed_run(command, tool_env(variant["dir"], share_dir, registry),
                           logs / f"{name}-{variant['name']}-{label}.log")
        log(f"  {name:<24} {variant['name']:<12} {label:<8} wall {result['wall_s']:8.2f} s  "
            f"cpu {result['cpu_user_s'] + result['cpu_kernel_s']:8.2f} s  "
            f"peak {result['peak_mb']:7.0f} MB  exit {result['exit_code']}")
        if result["exit_code"] != 0:
            tail = (logs / f"{name}-{variant['name']}-{label}.log").read_text("utf-8", "replace")
            raise SystemExit(f"{name} ({variant['name']}) failed with exit code "
                             f"{result['exit_code']:#x}:\n{tail[-3000:]}")
        return result, target

    for step in selected:
        name, description, source, _, extra = step
        log(f"{name}: {description}")
        entry = {"name": name, "description": description, "input": source,
                 "arguments": ["-threads", str(args.threads), "-no_progress"] + extra,
                 "warmup": {variant["name"]: [] for variant in variants},
                 "runs": {variant["name"]: [] for variant in variants}}
        for index in range(args.warmup):
            for variant in variants:
                entry["warmup"][variant["name"]].append(invoke(variant, step, f"warmup{index}")[0])
        # A tool that turns out slow on this runner gets fewer repetitions, never fewer than
        # three: a run cut off by the job timeout reports nothing at all.
        repetitions = args.repetitions
        estimate = [run["wall_s"] for runs in entry["warmup"].values() for run in runs]
        if estimate and args.budget_minutes:
            per_round = statistics.fmean(estimate) * len(variants)
            repetitions = max(3, min(repetitions, int(args.budget_minutes * 60 / per_round)))
        entry["repetitions"] = repetitions
        outputs = {variant["name"]: [] for variant in variants}
        for index in range(repetitions):
            shift = index % len(variants)
            for variant in variants[shift:] + variants[:shift]:
                result, target = invoke(variant, step, f"run{index}")
                entry["runs"][variant["name"]].append(result)
                outputs[variant["name"]].append(fingerprint(target))
                target.unlink()
        # The first output of each variant, whether its repetitions all wrote the same
        # numbers, and whether those are the numbers of the baseline.
        entry["outputs"] = {variant: found[0] for variant, found in outputs.items()}
        entry["deterministic"] = {variant: all(same_content(found[0], other) for other in found)
                                  for variant, found in outputs.items()}
        entry["same_as_baseline"] = {variant: same_content(outputs[BASELINE][0], found[0])
                                     for variant, found in outputs.items() if variant != BASELINE}
        cpu = lambda run: run["cpu_user_s"] + run["cpu_kernel_s"]
        entry["stats"] = {variant: {"wall_s": summarize(run["wall_s"] for run in runs),
                                    "cpu_s": summarize(cpu(run) for run in runs),
                                    "peak_mb": max(run["peak_mb"] for run in runs)}
                          for variant, runs in entry["runs"].items()}
        reference = entry["runs"][BASELINE]
        entry["speedup_vs_baseline"] = {
            variant: {"wall": paired_speedup([run["wall_s"] for run in reference],
                                             [run["wall_s"] for run in runs]),
                      "cpu": paired_speedup([cpu(run) for run in reference],
                                            [cpu(run) for run in runs])}
            for variant, runs in entry["runs"].items() if variant != BASELINE}
        report["tools"].append(entry)
        # Written after every tool: a later failure or a timeout keeps what was measured.
        write_report(report, args)
    log(Path(args.summary).read_text("utf-8"))


def write_report(report, args):
    for target in (args.report, args.summary):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    Path(args.summary).write_text(markdown(report), "utf-8")


def markdown(report):
    host, settings, dataset = report["host"], report["settings"], report["dataset"] or {}
    features = ", ".join(f"{name.upper()} {'yes' if present else 'no'}"
                         for name, present in host["cpu_features"].items())
    lines = [
        f"## MSVC SIMD flag benchmark · OpenMS `{(report['openms_commit'] or '?')[:10]}`", "",
        f"For [OpenMS/OpenMS#8845]({ISSUE}). All variants ran on one machine: "
        f"**{host['cpu']}**, {host['logical_cpus']} logical CPUs ({features}), {host['os']}"
        + (f", runner image {host['runner_image']}" if host.get("runner_image") else "") + ".", "",
        f"Each tool ran with `-threads {settings['threads']}`, {settings['warmup']} warm-up and "
        f"up to {settings['repetitions']} timed runs per variant; the variants alternate and the "
        "speed-up compares the runs that stood next to each other "
        "(baseline time / variant time, above 1 means the variant is faster).", ""]
    if dataset:
        files = dataset.get("files", {})
        window = f", retention time {dataset['rt_window_s']} s" if dataset.get("rt_window_s") else ""
        lines += [f"Input: `{dataset['raw_file']}` ({dataset['raw_bytes'] / 2 ** 30:.2f} GiB, "
                  f"{dataset.get('source') or 'local file'}){window}. " + "; ".join(
                      f"`{name}`: {entry['spectra']} spectra, {entry['data_points']:,} data points, "
                      f"{entry['bytes'] / 2 ** 20:.0f} MiB" for name, entry in files.items()) + ".", ""]
    lines += ["| Variant | Compiler flag | MSVC | Translation units with the flag |",
              "| --- | --- | --- | --- |"]
    for variant in report["variants"]:
        flags = variant.get("compile_flags") or {}
        lines.append(f"| {variant['name']} | {variant.get('flag') or '(none: SSE2)'} | "
                     f"{variant.get('compiler_version') or '?'} | "
                     f"{flagged_units(variant.get('flag'), flags)} of "
                     f"{flags.get('translation_units', '?')} |")
    lines += ["", "| Tool | Variant | Wall median [s] | Wall min – max [s] | CV | CPU median [s] | "
              "Peak RAM [MB] | Speed-up vs baseline (wall) | Output |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"]
    for tool in report["tools"]:
        for variant, stats in tool["stats"].items():
            wall, cpu = stats["wall_s"], stats["cpu_s"]
            speedup = tool["speedup_vs_baseline"].get(variant)
            comparison = "reference" if not speedup else (
                f"**{speedup['wall']['median']:.3f}×** ({speedup['wall']['min']:.3f} – "
                f"{speedup['wall']['max']:.3f}; {speedup['wall']['verdict']})")
            output = tool["outputs"][variant]
            numbers = ", ".join(f"{value:,} {key.replace('_', ' ')}" for key, value in
                                output.items() if key not in ("bytes", "content_sha256"))
            if variant != BASELINE:
                numbers += ("; numbers identical to baseline" if tool["same_as_baseline"][variant]
                            else "; **numbers differ from baseline**")
            if not tool["deterministic"][variant]:
                numbers += "; differs between repetitions"
            lines.append(f"| {tool['name']} | {variant} | {wall['median']:.2f} | "
                         f"{wall['min']:.2f} – {wall['max']:.2f} | {wall['cv_percent']:.1f} % | "
                         f"{cpu['median']:.2f} | {stats['peak_mb']:.0f} | {comparison} | {numbers} |")
    lines += ["", "<details><summary>Every timed run (wall seconds, in run order)</summary>", ""]
    for tool in report["tools"]:
        for variant, runs in tool["runs"].items():
            lines.append(f"- {tool['name']} · {variant}: "
                         + ", ".join(f"{run['wall_s']:.2f}" for run in runs))
    lines += ["", "</details>", ""]
    lines.append("\"Numbers identical\" compares a SHA-256 over every computed value in the output "
                 "(encoded arrays of mzML; positions, intensities, qualities, charges and hull "
                 "points of featureXML), not the file size.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("targets", help="print the build targets the benchmark needs")
    sub = commands.add_parser("patch", help="add a variant's MSVC flag to an OpenMS checkout")
    sub.add_argument("--openms", required=True)
    sub.add_argument("--variant", required=True)
    sub = commands.add_parser("package", help="collect the built tools and their build record")
    sub.add_argument("--build-dir", required=True)
    sub.add_argument("--openms", required=True)
    sub.add_argument("--variant", required=True)
    sub.add_argument("--out", required=True)
    sub = commands.add_parser("prepare", help="convert a RAW file into the benchmark inputs")
    sub.add_argument("--bin-dir", required=True, help="the baseline tools")
    sub.add_argument("--share-dir", required=True, help="share/OpenMS of the benchmarked commit")
    sub.add_argument("--raw", required=True)
    sub.add_argument("--raw-sha256", default="none", help="expected SHA-256, or none")
    sub.add_argument("--source", default="", help="where the RAW file came from, for the report")
    sub.add_argument("--converter", required=True, help="ThermoRawFileParser.exe")
    sub.add_argument("--rt-window", default="all", help="start:end in seconds, or all")
    sub.add_argument("--work", default="work")
    sub = commands.add_parser("run", help="time every tool for every variant")
    sub.add_argument("--variant-dir", nargs="+", required=True)
    sub.add_argument("--share-dir", required=True)
    sub.add_argument("--work", default="work")
    sub.add_argument("--repetitions", type=int, default=7)
    sub.add_argument("--warmup", type=int, default=1)
    sub.add_argument("--threads", type=int, default=1)
    sub.add_argument("--budget-minutes", type=float, default=60,
                     help="timed minutes per tool; repetitions shrink to fit, to three at least")
    sub.add_argument("--tools", nargs="*", default=[], help="only these tools")
    sub.add_argument("--report", default="reports/avx-benchmark.json")
    sub.add_argument("--summary", default="reports/avx-benchmark.md")
    args = parser.parse_args()
    if args.command == "targets":
        print(" ".join([name for name, *_ in STEPS] + HELPERS))
    else:
        {"patch": patch, "package": package, "prepare": prepare, "run": run}[args.command](args)


if __name__ == "__main__":
    main()
