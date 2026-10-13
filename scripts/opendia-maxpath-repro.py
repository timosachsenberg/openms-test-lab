"""Throwaway reproduction: does OpenDIA's sqlite workflow fail on Windows once its
intermediate paths approach MAX_PATH? Runs the command of TOPP_OpenDIA_auto_transition_list_sqlite
with intermediate directories of growing depth and records where it breaks."""
import json, os, re, subprocess, sys, urllib.request, winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
bin_dir = Path((REPORTS / "openms-bin.txt").read_text(encoding="utf-8").strip())
help_text = subprocess.run([str(bin_dir / "FileInfo.exe"), "--help"], capture_output=True, text=True, errors="replace")
revision = re.search(r"Revision:\s*([0-9a-f]{7,40})", help_text.stdout + help_text.stderr).group(1)
data = Path("D:/opendia-data")
data.mkdir(exist_ok=True)
for name in ("OpenSwathWorkflow_17_input.mzML", "OpenSwathWorkflow_17_input.tsv"):
    url = f"https://raw.githubusercontent.com/OpenMS/OpenMS/{revision}/src/tests/topp/{name}"
    urllib.request.urlretrieve(url, data / name)
try:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
        long_paths = winreg.QueryValueEx(key, "LongPathsEnabled")[0]
except OSError:
    long_paths = None

results = []
for pad in (0, 60, 90, 100, 105, 110, 115, 120, 125, 130, 140, 160):
    parent = f"D:/r/{'x' * pad}_{pad}"
    out_dir = f"D:/o/{pad}"
    command = [str(bin_dir / "OpenDIA.exe"), "-test", "-in", str(data / "OpenSwathWorkflow_17_input.mzML"),
               "-tr", str(data / "OpenSwathWorkflow_17_input.tsv"), "-workflow:library_mode", "auto",
               "-workflow:working_format", "sqlite", "-workflow:keep_intermediate_files", "false",
               "-workflow:intermediate_dir", parent, "-out_dir", out_dir,
               "-PeptideQueryParameters:DecoyGenerator:min_decoy_fraction", "0.0",
               "-TargetedDataExtraction:readOptions", "workingInMemory",
               "-TargetedDataExtraction:ion_mobility_window", "0.05",
               "-TargetedDataExtraction:use_ms1_ion_mobility", "false",
               "-TargetedDataExtraction:Scoring:Scores:use_ion_mobility_scores", "true",
               "-TargetedDataExtraction:Calibration:auto_irt:enabled", "false",
               "-TargetedDataExtraction:Calibration:windows:estimate_rt", "false",
               "-TargetedDataExtraction:Calibration:windows:estimate_mz", "false",
               "-TargetedDataExtraction:Calibration:windows:estimate_im", "false"]
    ran = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=900)
    log = ran.stdout + ran.stderr
    kept = re.search(r"preserved in: (\S+)", log)
    intermediate = kept.group(1) if kept else None
    files = sorted(os.listdir(intermediate)) if intermediate and os.path.isdir(intermediate) else []
    results.append({
        "pad": pad, "parent_length": len(parent), "exit": ran.returncode,
        "intermediate": intermediate, "intermediate_length": len(intermediate) if intermediate else None,
        "files_left": files,
        "zero_transitions": "Assay preparation produced zero transitions" in log,
        "cannot_open": "unable to open database file" in log,
        "error_lines": [l for l in log.splitlines() if "rror" in l][-4:],
    })
    print(json.dumps(results[-1]), flush=True)
report = {"revision": revision, "long_paths_enabled": long_paths, "results": results}
(REPORTS / "opendia-maxpath.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
