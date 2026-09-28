"""Run the #2541 simulation through a MapAlignerIdentification binary (e.g. a patched build).

Writes the simulated runs as idXML (with the nightly pyOpenMS), aligns them with the given
TOPP tool in several modes and evaluates the stored trafoXML files like sim_2541.py does.
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pyopenms as oms

from sim_2541 import simulate, evaluate, Identity

TOOL = sys.argv[1] if len(sys.argv) > 1 else "/home/user/OpenMS/OpenMS-build/bin/MapAlignerIdentification"


def store_runs(runs, workdir):
    paths = []
    for r, plist in enumerate(runs):
        prot = oms.ProteinIdentification()
        prot.setIdentifier("run")
        prot.setSearchEngine("simulation")
        prot.setScoreType("q-value")
        prot.setHigherScoreBetter(False)
        for pid in plist:
            pid.setIdentifier("run")
        path = os.path.join(workdir, f"run{r + 1}.idXML")
        oms.IdXMLFile().store(path, [prot], plist)
        paths.append(path)
    return paths


def run_tool(paths, workdir, tag, extra):
    trafos = [os.path.join(workdir, f"{tag}_{i + 1}.trafoXML") for i in range(len(paths))]
    cmd = [TOOL, "-in", *paths, "-trafo_out", *trafos, "-threads", "1", *extra]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stdout + out.stderr)
    chosen = [line for line in out.stdout.splitlines() if "No reference given" in line]
    loaded = []
    for path in trafos:
        td = oms.TransformationDescription()
        oms.TransformationXMLFile().load(path, td, True)
        loaded.append(td)
    return loaded, (chosen[0].strip() if chosen else "")


def main():
    scenarios = [("5 runs, shifts +-60 s", 5, 60, 20), ("5 runs, shifts +-180 s", 5, 180, 40),
                 ("10 runs, shifts +-180 s", 10, 180, 40)]
    modes = {
        "before alignment": None,
        "old default (consensus)": ["-algorithm:auto_reference", "consensus"],
        "new default (most_ids)": [],
    }
    results = {}
    for label, n_runs, spread, warp in scenarios:
        acc = {name: [] for name in modes}
        for seed in (1, 2, 3):
            runs, obs, distort, _ = simulate(seed, n_runs, 3000, spread, warp, noise=8.0)
            with tempfile.TemporaryDirectory() as workdir:
                paths = store_runs(runs, workdir)
                for name, extra in modes.items():
                    if extra is None:
                        trafos = [Identity()] * n_runs
                    else:
                        trafos, chosen = run_tool(paths, workdir, name.split()[0], extra)
                        if chosen and seed == 1:
                            print(f"[{label}] {chosen}")
                    acc[name].append(evaluate(trafos, obs, distort, n_runs))
        results[label] = {name: np.mean(np.array(v), axis=0).tolist() for name, v in acc.items()}
        print(f"\n## {label}")
        for name, v in results[label].items():
            print(f"  {name:28s} {v[0]:7.1f} {v[1]:7.1f} {v[2]:7.1f} {v[3]:7.1f}")
    with open("sim_topp_results.json", "w") as fh:
        json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
