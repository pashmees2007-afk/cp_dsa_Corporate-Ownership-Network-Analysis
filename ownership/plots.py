"""Phase 8 - benchmark charts (matplotlib, used only to produce the report figures).

Log-log axes throughout: on them, time proportional to n^k is a straight line
of slope k, so measured growth can be read against the theoretical bound. The
dashed grey lines are reference slopes (1 = linear, 2 = quadratic) drawn
through a measured point.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402

# Reference palette: categorical slots in fixed order, ink and chrome.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def _style(ax, xlabel, ylabel):
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_facecolor(SURFACE)
    ax.grid(True, which="major", color=GRID, linewidth=0.8)
    ax.grid(False, which="minor")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.set_xlabel(xlabel, color=INK2, fontsize=10)
    ax.set_ylabel(ylabel, color=INK2, fontsize=10)


_LABELS = {}                     # axes -> [(x, y, text, colour, size)] placed by _place_labels


def _series(ax, xs, ys, colour, label, marker="o"):
    ax.plot(xs, ys, color=colour, linewidth=2, marker=marker, markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=1.5, label=label)
    _LABELS.setdefault(ax, []).append((xs[-1], ys[-1], label, INK, 9))


def _reference(ax, xs, anchor_x, anchor_y, power, label):
    ys = [anchor_y * (x / anchor_x) ** power for x in xs]
    ax.plot(xs, ys, color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)), zorder=0)
    _LABELS.setdefault(ax, []).append((xs[-1], ys[-1], label, MUTED, 8.5))


def _place_labels(fig, gap_px=15):
    """Direct labels at the line ends, pushed apart vertically so none overlap."""
    fig.canvas.draw()
    for ax, labels in _LABELS.items():
        if ax.figure is not fig:
            continue
        pts = sorted(((ax.transData.transform((x, y))[1], x, y, t, c, sz) for x, y, t, c, sz in labels))
        placed = []
        for py, x, y, t, c, sz in pts:
            target = py if not placed else max(py, placed[-1] + gap_px)
            placed.append(target)
            ax.annotate(t, (x, y), xytext=(8, (target - py) * 72 / fig.dpi), textcoords="offset points",
                        va="center", fontsize=sz, color=c)
    for ax in [a for a in _LABELS if a.figure is fig]:
        del _LABELS[ax]


def _figure(n_panels=1):
    fig, axes = plt.subplots(1, n_panels, figsize=(6.2 * n_panels, 4.4), facecolor=SURFACE)
    return fig, (axes if n_panels > 1 else [axes])


def _title(ax, text, sub):
    ax.set_title(text, loc="left", fontsize=11.5, color=INK, fontweight="bold", pad=22)
    ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=9, color=INK2)


def plot_benchmarks(report, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    rs = report["sizes"]
    size = [r["V"] + r["E"] for r in rs]
    ms = lambda key: [r[key] * 1e3 for r in rs]                      # noqa: E731

    # 1. linear-time traversals
    fig, (ax,) = _figure()
    for colour, (key, label) in zip(SERIES, [("build", "Build graph"), ("dfs", "DFS (back edges)"),
                                             ("tarjan", "Tarjan SCC"), ("components", "Components")]):
        _series(ax, size, ms(key), colour, label)
    _reference(ax, size, size[0], min(ms("dfs")[0], ms("components")[0]) * 0.6, 1, "slope 1 = O(V+E)")
    _style(ax, "Graph size V + E (log)", "Time, ms (log)")
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")
    ax.set_xlim(right=size[-1] * 4)
    _title(ax, "Whole-graph traversals grow linearly",
           "Minimum of 3-5 runs; synthetic graphs shaped like the real data")
    fig.tight_layout()
    _place_labels(fig)
    fig.savefig(outdir / "bench_traversals.png", dpi=150)
    plt.close(fig)

    # 2. per-query operations and output-sensitive chain enumeration
    fig, (a, b) = _figure(2)
    _series(a, size, ms("bfs"), SERIES[0], "BFS")
    _series(a, size, ms("integrated"), SERIES[1], "Integrated stake")
    _reference(a, size, size[0], ms("bfs")[0] * 0.5, 1, "slope 1")
    _style(a, "Graph size V + E (log)", "Time per query, ms (log)")
    a.set_xlim(right=size[-1] * 6)
    _title(a, "Per-company queries", "Mean over up to 20 companies per size")
    out = [r["chain_entities"] for r in rs]
    _series(b, out, [r["chains_time"] * 1e3 for r in rs], SERIES[0], "All chains, all companies")
    _reference(b, out, out[0], rs[0]["chains_time"] * 1e3 * 0.6, 1, "slope 1 = O(output)")
    _style(b, "Output: entities in all chains (log)", "Time, ms (log)")
    b.set_xlim(right=out[-1] * 6)
    _title(b, "Chain enumeration is output-sensitive", "At the 0.01% minimum effective stake")
    fig.tight_layout()
    _place_labels(fig)
    fig.savefig(outdir / "bench_queries.png", dpi=150)
    plt.close(fig)

    # 3. adjacency list vs adjacency matrix
    fig, (a, b) = _figure(2)
    V = [r["V"] for r in rs]
    measured = [r for r in rs if "mem_matrix_bytes" in r]
    mv = [r["V"] for r in measured]
    _series(a, V, [r["mem_list_bytes"] / 1e6 for r in rs], SERIES[0], "Adjacency list")
    _series(a, mv, [r["mem_matrix_bytes"] / 1e6 for r in measured], SERIES[1], "Adjacency matrix")
    est = [r for r in rs if "mem_matrix_bytes_estimated" in r]
    if est:
        a.plot([r["V"] for r in est], [r["mem_matrix_bytes_estimated"] / 1e6 for r in est], linestyle="none",
               marker="o", markersize=7, markerfacecolor=SURFACE, markeredgecolor=SERIES[1], markeredgewidth=2)
        a.annotate("8·V² estimate", (est[-1]["V"], est[-1]["mem_matrix_bytes_estimated"] / 1e6), xytext=(8, 0),
                   textcoords="offset points", va="center", fontsize=8.5, color=INK2)
    _reference(a, V, mv[0], measured[0]["mem_matrix_bytes"] / 1e6 * 2.2, 2, "slope 2")
    _style(a, "Nodes V (log)", "Memory, MB (log)")
    a.set_xlim(right=V[-1] * 5)
    _title(a, "Memory: list O(V+E), matrix O(V²)", "tracemalloc; matrix = V rows of 8-byte doubles")
    _series(b, [r["V"] for r in rs], [r["bfs_list_one"] * 1e3 for r in rs], SERIES[0], "BFS on adjacency list")
    _series(b, mv, [r["bfs_matrix_one"] * 1e3 for r in measured], SERIES[1], "BFS on adjacency matrix")
    _reference(b, mv, mv[0], measured[0]["bfs_matrix_one"] * 1e3 * 2.2, 2, "slope 2")
    _style(b, "Nodes V (log)", "Time, ms (log)")
    b.set_xlim(right=V[-1] * 6)
    _title(b, "One BFS: list O(V+E), matrix O(V²)", "Same source company on both representations")
    fig.tight_layout()
    _place_labels(fig)
    fig.savefig(outdir / "bench_list_vs_matrix.png", dpi=150)
    plt.close(fig)
