"""Issue-style plot of raw trafo data points (OpenMS/OpenMS#2541) with today's nightly pyOpenMS."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyopenms as oms
from sim_2541 import simulate, align

INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
POINTS, FIT = "#2a78d6", "#eb6834"

runs, obs, distort, shifts = simulate(1, 5, 3000, 180, 40, noise=8.0)
most = int(np.argmax([len(r) for r in runs]))
# most-shifted run that is not the reference run
order = [int(i) for i in np.argsort(-np.abs(shifts)) if int(i) != most]
target = order[0]

panels = [
    ("No reference (default): target = per-peptide median of run medians", align(runs, -1)),
    (f"reference:index = run with most IDs (run {most + 1})", align(runs, most)),
]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8), dpi=150, sharey=True, facecolor=SURFACE)
for ax, (title, trafos) in zip(axes, panels):
    t = trafos[target]
    pts = np.array([(dp.first, dp.second) for dp in t.getDataPoints()])
    ax.set_facecolor(SURFACE)
    ax.scatter(pts[:, 0] / 60, pts[:, 1] - pts[:, 0], s=14, color=POINTS, alpha=0.35,
               edgecolors=SURFACE, linewidths=0.4, label="data points (peptide median RT pairs)", zorder=2)
    grid = np.linspace(pts[:, 0].min(), pts[:, 0].max(), 300)
    ax.plot(grid / 60, [t.apply(float(x)) - x for x in grid], color=FIT, lw=2,
            solid_capstyle="round", label="fitted b_spline (TOPP defaults)", zorder=3)
    ax.set_title(title, fontsize=10, color=INK, loc="left")
    ax.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelcolor=INK2)
    ax.set_xlabel("RT in the aligned run (min)", color=INK2)
axes[0].set_ylabel("target RT − run RT (s)", color=INK2)
axes[0].annotate("parallel bands = peptides whose median\ncame from different subsets of runs",
                 xy=(0.03, 0.04), xycoords="axes fraction", color=INK2, fontsize=9)
axes[1].legend(loc="upper right", frameon=False, labelcolor=INK2, fontsize=9)
fig.suptitle(f"Trafo data points for run {target + 1} (simulated shift {shifts[target]:+.0f} s) — "
             f"pyOpenMS {oms.__version__}", x=0.01, y=0.985, ha="left", fontsize=11, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig("issue2541_nightly.png", facecolor=SURFACE)
print("run", target + 1, "shift", shifts[target], "reference", most + 1)
