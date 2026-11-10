"""E1 figure: slowdown of each placement with respect to All-on-DRAM.

Reads ../../e1_total.log (lines: "<config> <rep> <metric> <seconds>")
and writes e1_slowdown.pdf next to this script.
"""
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
LOG = HERE.parent.parent / "e1_total.log"

BLUE, ORANGE = "#2a78d6", "#eb6834"  # categorical slots 1-2 (validated)
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

CONFIGS = [("all_slow", "All-on-\nSlow"), ("hot_on_dram", "Hot-on-\nDRAM"), ("cold_on_dram", "Cold-on-\nDRAM")]
NEUTRAL = "#7a7974"  # panel (a): one series, kept neutral so blue keeps meaning "pointer chasing" in (b)

data = defaultdict(list)
for line in LOG.read_text().splitlines():
    cfg, _rep, metric, value = line.split()
    data[(cfg, metric)].append(float(value))


def slowdown(cfg, metric):
    """Mean slowdown (%) vs All-on-DRAM, and its std from the run-to-run spread."""
    base = st.mean(data[("all_dram", metric)])
    vals = [(v / base - 1) * 100 for v in data[(cfg, metric)]]
    return st.mean(vals), st.stdev(vals)


plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
})
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.5, 2.5), gridspec_kw={"width_ratios": [1, 1.4]})
x = range(len(CONFIGS))
labels = [name for _, name in CONFIGS]

# (a) Total program time: single series, direct labels.
tot = [slowdown(c, "total_time_s") for c, _ in CONFIGS]
ax1.bar(x, [m for m, _ in tot], yerr=[s for _, s in tot], width=0.55, color=NEUTRAL,
        error_kw={"ecolor": INK, "elinewidth": 0.8, "capsize": 2})
for i, (m, _) in enumerate(tot):
    ax1.text(i, m + 1.5, f"+{m:.0f}%", ha="center", va="bottom", color=INK)
ax1.set_title("(a) Total time", color=INK, fontsize=9)

# (b) Main loop of each thread: two series, legend.
w = 0.36
pc = [slowdown(c, "pc_time_s") for c, _ in CONFIGS]
bw = [slowdown(c, "bw_time_s") for c, _ in CONFIGS]
ax2.bar([i - w / 2 - 0.01 for i in x], [m for m, _ in pc], width=w, color=BLUE, label="Pointer chasing (cold)")
ax2.bar([i + w / 2 + 0.01 for i in x], [m for m, _ in bw], width=w, color=ORANGE, label="Sequential (hot)")
def pct(v):
    return "0%" if round(v) == 0 else f"{v:+.0f}%"


for i, ((mp, _), (mb, _)) in enumerate(zip(pc, bw)):  # label only the near-zero bars, which are otherwise invisible
    if abs(mp) < 5:
        ax2.text(i - w / 2 - 0.01, max(mp, 0) + 1.5, pct(mp), ha="center", va="bottom", color=INK, fontsize=8)
    if abs(mb) < 5:
        ax2.text(i + w / 2 + 0.01, max(mb, 0) + 1.5, pct(mb), ha="center", va="bottom", color=INK, fontsize=8)
ax2.set_title("(b) Main loop of each thread", color=INK, fontsize=9)
ax2.legend(frameon=False, fontsize=8, loc="upper right")

for ax in (ax1, ax2):
    ax.set_xticks(list(x), labels)
    ax.set_ylim(-3, 62)
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
ax1.set_ylabel("Slowdown vs All-on-DRAM (%)")

fig.tight_layout()
fig.savefig(HERE / "e1_slowdown.pdf")
fig.savefig(HERE / "e1_slowdown.png", dpi=200)
