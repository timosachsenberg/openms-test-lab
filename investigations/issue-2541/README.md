# OpenMS/OpenMS#2541: MapAlignerIdentification without a reference

Evidence for [OpenMS/OpenMS#2541](https://github.com/OpenMS/OpenMS/issues/2541): simulated LC-MS/MS
runs with known, smooth RT distortions, DDA-like partial identification overlap and 8 s RT noise,
aligned with `MapAlignmentAlgorithmIdentification` and the default `b_spline` model.

| File | What it does |
|---|---|
| `sim_2541.py` | Simulates the runs and aligns them with the nightly pyOpenMS in several modes (no reference, run twice, `min_run_occur` = number of runs, reference = run with most IDs). Prints the spread left between runs after alignment. |
| `plot_2541.py` | `issue2541_nightly.png`: the trafo data points of the most-shifted run, with and without a reference (the plot from the issue, redone). |
| `sim_topp.py` | Writes the runs as idXML and aligns them with a `MapAlignerIdentification` binary, old default (`-algorithm:auto_reference consensus`) against new default; writes `sim_topp_results.json`. |
| `plot_after.py` | `issue2541_after.png` from `sim_topp_results.json`. |

Run with pyOpenMS, numpy and matplotlib installed:

```bash
python3 sim_2541.py
python3 plot_2541.py
python3 sim_topp.py <path to MapAlignerIdentification>
python3 plot_after.py
```
