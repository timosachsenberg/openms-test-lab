"""Bar chart: RT spread left between runs after alignment, old vs. new default (sim_topp_results.json)."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
OLD, NEW = "#898781", "#2a78d6"  # de-emphasised old default, accent for the new default

res = json.load(open("sim_topp_results.json"))
labels = list(res.keys())
old = [res[k]["old default (consensus)"][2] for k in labels]
new = [res[k]["new default (most_ids)"][2] for k in labels]
before = [res[k]["before alignment"][2] for k in labels]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
fig, ax = plt.subplots(figsize=(8.6, 3.6), dpi=150, facecolor=SURFACE)
ax.set_facecolor(SURFACE)
y = np.arange(len(labels))[::-1]
h = 0.34
ax.barh(y + h / 2 + 0.01, old, height=h, color=OLD, label="old default: consensus of all runs")
ax.barh(y - h / 2 - 0.01, new, height=h, color=NEW, label="new default: run with most IDs")
for yi, o, n, b in zip(y, old, new, before):
    ax.text(o + 0.6, yi + h / 2 + 0.01, f"{o:.1f} s  ({100 * o / b:.0f}% of {b:.0f} s before)", va="center",
            color=INK2, fontsize=9)
    ax.text(n + 0.6, yi - h / 2 - 0.01, f"{n:.1f} s", va="center", color=INK2, fontsize=9)
ax.set_yticks(y, [l.replace("+-", "±") for l in labels], color=INK2)
ax.set_xlim(0, max(old) * 1.55)
ax.set_xlabel("RT spread between runs left after alignment (s, median over the gradient)", color=INK2)
ax.grid(True, axis="x", color=GRID, lw=0.8)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(AXIS)
ax.tick_params(axis="x", colors=MUTED, labelcolor=INK2)
ax.tick_params(axis="y", length=0)
ax.legend(loc="upper right", frameon=False, labelcolor=INK2, fontsize=9)
fig.suptitle("MapAlignerIdentification without a reference: old vs. new default (simulated runs, 3 seeds each)",
             x=0.01, ha="left", fontsize=11, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig("issue2541_after.png", facecolor=SURFACE)
