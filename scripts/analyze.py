"""Analyze benchmark runs: CSV tables, markdown tables and charts under report/.

Usage: analyze.py <run_id> [<run_id> ...]   (results/<run_id>/results.jsonl, merged)"""
import json
import random
import sys
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "report"
DATA, CHARTS = REPORT / "data", REPORT / "charts"

CONFIG_ORDER = ["l4_off", "l4_high", "sol_low", "sol_high", "l3"]
LABELS = {"l4_off": "Large 4 · reasoning off", "l4_high": "Large 4 · reasoning high",
          "sol_low": "GPT-6.1 Sol · low", "sol_high": "GPT-6.1 Sol · high", "l3": "Large 3"}
# categorical slots 1-5 of the validated reference palette, fixed per config (never re-ordered)
COLORS = {"l4_off": "#2a78d6", "l4_high": "#eb6834", "sol_low": "#1baf7a", "sol_high": "#eda100", "l3": "#e87ba4"}
CATS = ["reasoning", "coding", "agentic", "grounding", "your_data"]
CAT_LABELS = {"reasoning": "Reasoning", "coding": "Coding", "agentic": "Agentic tool use",
              "grounding": "Web-grounded", "your_data": "Your documents"}
# list prices, USD per 1M tokens (input, output) on 2026-10-24
PRICES = {"mistral-large-4": (1.36, 4.18), "mistral-large-2512": (0.50, 1.50), "gpt-6.1-sol": (2.00, 10.00),
          "gpt-6-astra": (10.00, 50.00)}

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e2dc"


def load(run_ids):
    rows = []
    for rid in run_ids:
        p = ROOT / "results" / rid / "results.jsonl"
        main = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        # swap in repaired results (scripts/repair.py) for calls that failed at the API level
        for rp in sorted((ROOT / "results").glob(f"repair-{rid}-*/results.jsonl")):
            for rep in (json.loads(line) for line in rp.read_text().splitlines() if line.strip()):
                for i, orig in enumerate(main):
                    if (not orig["api_ok"] and orig["item_id"] == rep["item_id"]
                            and orig["config_id"] == rep["config_id"]):
                        main[i] = {**rep, "run_id": rid, "repeat": orig["repeat"], "repaired": True}
                        break
        rows += main
    df = pd.DataFrame(rows)
    # if an (item, config, repeat) was re-run, keep the latest record
    df = df.sort_values("recorded_at").drop_duplicates(["item_id", "config_id", "repeat", "run_id"], keep="last")
    u = pd.json_normalize(df["usage"].fillna({}).tolist()) if len(df) else pd.DataFrame()
    for col in ["input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "search_calls", "search_tokens"]:
        df[col] = pd.to_numeric(u.get(col), errors="coerce").fillna(0).values if col in u else 0
    df["answer_tokens"] = (df["output_tokens"] - df["reasoning_tokens"]).clip(lower=0)
    df["latency_s"] = df["latency_ms"] / 1000.0
    df["hit_token_cap"] = df["finish_reason"].eq("length")
    df["cfg_rank"] = df["config_id"].map({c: i for i, c in enumerate(CONFIG_ORDER)})
    return df


def boot_ci(item_means, n=2000, seed=7):
    vals = list(item_means)
    if not vals:
        return (None, None)
    rnd = random.Random(seed)
    stats = sorted(sum(rnd.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def cost_usd(r):
    pin, pout = PRICES.get(r["model"], (0, 0))
    return (r["input_tokens"] * pin + r["output_tokens"] * pout) / 1e6


def summarize(df):
    out = []
    for cid in CONFIG_ORDER:
        d = df[df.config_id == cid]
        if d.empty:
            continue
        item_pass = d.groupby("item_id")["pass"].mean()
        lo, hi = boot_ci(item_pass.values)
        out.append({
            "config": cid, "label": LABELS[cid], "runs": len(d), "items": d.item_id.nunique(),
            "pass_rate": round(d["pass"].mean(), 3), "ci95_low": round(lo, 3), "ci95_high": round(hi, 3),
            "api_errors": int((~d.api_ok).sum()), "hit_token_cap": int(d.hit_token_cap.sum()),
            "latency_median_s": round(d.latency_s.median(), 1), "latency_p90_s": round(d.latency_s.quantile(0.9), 1),
            "output_tokens_mean": int(d.output_tokens.mean()), "reasoning_tokens_mean": int(d.reasoning_tokens.mean()),
            "output_tokens_median": int(d.output_tokens.median()),
            "tokens_total": int(d.input_tokens.sum() + d.output_tokens.sum()),
            "est_cost_usd_list": round(d.apply(cost_usd, axis=1).sum(), 2),
        })
    return pd.DataFrame(out)


def by_category(df):
    piv = df.pivot_table(index="category", columns="config_id", values="pass", aggfunc="mean")
    piv = piv.reindex(index=[c for c in CATS if c in piv.index], columns=[c for c in CONFIG_ORDER if c in piv.columns])
    lat = df.pivot_table(index="category", columns="config_id", values="latency_s", aggfunc="median")
    lat = lat.reindex(index=piv.index, columns=piv.columns)
    tok = df.pivot_table(index="category", columns="config_id", values="output_tokens", aggfunc="median")
    tok = tok.reindex(index=piv.index, columns=piv.columns)
    return piv, lat, tok


def per_item(df):
    piv = df.pivot_table(index=["item_id", "category", "title"], columns="config_id", values="pass", aggfunc="mean")
    return piv.reindex(columns=[c for c in CONFIG_ORDER if c in piv.columns]).reset_index()


def grounding_behavior(df):
    g = df[df.category == "grounding"]
    if g.empty:
        return pd.DataFrame()
    cited = g["detail"].apply(lambda d: bool((d or {}).get("cited")))
    g = g.assign(cited=cited)
    t = g.groupby("config_id").agg(pass_rate=("pass", "mean"), searches_mean=("search_calls", "mean"),
                                   search_tokens_mean=("search_tokens", "mean"), input_tokens_mean=("input_tokens", "mean"),
                                   cited_rate=("cited", "mean"), latency_median_s=("latency_s", "median"))
    return t.reindex([c for c in CONFIG_ORDER if c in t.index]).round(2).reset_index()


def agentic_behavior(df):
    a = df[df.category == "agentic"]
    if a.empty:
        return pd.DataFrame()
    forb = a["detail"].apply(lambda d: len((d or {}).get("forbidden_made") or []))
    miss = a["detail"].apply(lambda d: len((d or {}).get("missing_required") or []))
    a = a.assign(forbidden=forb, missing=miss)
    t = a.groupby("config_id").agg(pass_rate=("pass", "mean"), turns_mean=("turns", "mean"),
                                   runs_with_forbidden_action=("forbidden", lambda s: int((s > 0).sum())),
                                   runs_missing_required_action=("missing", lambda s: int((s > 0).sum())),
                                   latency_median_s=("latency_s", "median"))
    return t.reindex([c for c in CONFIG_ORDER if c in t.index]).round(2).reset_index()


def judge_agreement(df):
    y = df[df.category == "your_data"]
    rows = []
    for _, r in y.iterrows():
        d = r["detail"] or {}
        j, p = d.get("judge") or {}, d.get("programmatic") or {}
        if j:
            rows.append({"config_id": r.config_id, "judge_pass": bool(j.get("correct") and j.get("faithful")),
                         "programmatic_pass": bool(p.get("pass")), "hallucinations": len(j.get("hallucinations") or [])})
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["agree"] = t.judge_pass == t.programmatic_pass
    return t.groupby("config_id").agg(judge_pass_rate=("judge_pass", "mean"), programmatic_pass_rate=("programmatic_pass", "mean"),
                                      agreement=("agree", "mean"), runs_with_hallucination=("hallucinations", lambda s: int((s > 0).sum()))
                                      ).reindex([c for c in CONFIG_ORDER if c in t.config_id.unique()]).round(2).reset_index()


def consistency(df):
    """Per config: items passed in every repeat, in some, in none."""
    out = []
    for cid in CONFIG_ORDER:
        d = df[df.config_id == cid]
        if d.empty:
            continue
        g = d.groupby("item_id")["pass"].agg(["sum", "count"])
        out.append({"config_id": cid, "items": len(g), "passed_every_run": int((g["sum"] == g["count"]).sum()),
                    "passed_some_runs": int(((g["sum"] > 0) & (g["sum"] < g["count"])).sum()),
                    "never_passed": int((g["sum"] == 0).sum())})
    return pd.DataFrame(out)


def head_to_head(df, a, b):
    """Item-level comparison of two configs by per-item pass rate."""
    pa = df[df.config_id == a].groupby("item_id")["pass"].mean()
    pb = df[df.config_id == b].groupby("item_id")["pass"].mean()
    both = pa.index.intersection(pb.index)
    return {"first": LABELS[a], "second": LABELS[b], "items": len(both),
            "first_better": int((pa[both] > pb[both]).sum()), "tied": int((pa[both] == pb[both]).sum()),
            "second_better": int((pa[both] < pb[both]).sum())}


# ------------------------------------------------------------------ charts

def _style(ax, title=None):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#bdbab2")
    ax.tick_params(colors=INK2, labelsize=10, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", color=INK, fontsize=13, fontweight="bold", pad=22)


def _fig(w=11, h=5.2):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    return fig, ax


def _round_ends(ax, bars, horizontal=False, r_px=7):
    """Round the data end of each bar (4px at 1x) and keep the baseline end square."""
    fig = ax.figure
    fig.canvas.draw()
    ext = ax.get_window_extent()
    xpp = (ax.get_xlim()[1] - ax.get_xlim()[0]) / ext.width
    ypp = (ax.get_ylim()[1] - ax.get_ylim()[0]) / ext.height
    if ax.get_xscale() == "log" or ax.get_yscale() == "log":
        return
    for b in list(bars):
        x, y, w, h = b.get_x(), b.get_y(), b.get_width(), b.get_height()
        fc, ec, lw = b.get_facecolor(), b.get_edgecolor(), b.get_linewidth()
        if (h <= 0) or (w <= 0):
            continue
        aspect = ypp / xpp                      # rounding_size is in x units; y is scaled by aspect
        if not horizontal:
            r = min(r_px * xpp, w / 2, h / aspect / 2)
            base = Rectangle((x, y), w, r * aspect, fc=fc, ec="none")
        else:
            r = min(r_px * xpp, w / 2, h / aspect / 2)
            base = Rectangle((x, y), r, h, fc=fc, ec="none")
        cap = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", mutation_aspect=aspect,
                             fc=fc, ec="none", lw=0)
        b.remove()
        ax.add_patch(cap)
        ax.add_patch(base)


def _save(fig, name):
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHARTS / f"{name}.png", facecolor=SURFACE, bbox_inches="tight")
    fig.savefig(CHARTS / f"{name}.svg", facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def chart_pass_by_category(df, summ):
    piv, _, _ = by_category(df)
    groups = list(piv.index) + ["overall"]
    cfgs = list(piv.columns)
    fig, ax = _fig()
    n = len(cfgs)
    width = 0.8 / n
    all_bars = []
    for i, cid in enumerate(cfgs):
        vals = [piv.loc[g, cid] if g != "overall" else df[df.config_id == cid]["pass"].mean() for g in groups]
        xs = [k + (i - (n - 1) / 2) * width for k in range(len(groups))]
        bars = ax.bar(xs, vals, width=width * 0.86, color=COLORS[cid], label=LABELS[cid], edgecolor=SURFACE, linewidth=1)
        all_bars.extend(bars)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([CAT_LABELS.get(g, "All categories") for g in groups], color=INK2)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_ylim(0, 1.05)
    _style(ax, "Pass rate by task category")
    ax.legend(ncol=n, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.0), fontsize=9.5, labelcolor=INK2,
              handlelength=1.2, columnspacing=1.4)
    ax.set_ylim(0, 1.18)
    _round_ends(ax, all_bars)
    _save(fig, "pass_rate_by_category")


def chart_latency(df):
    fig, ax = _fig(10, 4.9)
    cfgs = [c for c in CONFIG_ORDER if c in df.config_id.unique()]
    lat = df[df.latency_s.notna()]
    for i, cid in enumerate(cfgs):
        d = lat[lat.config_id == cid].latency_s
        q1, med, q3, p90 = d.quantile(0.25), d.median(), d.quantile(0.75), d.quantile(0.9)
        y = len(cfgs) - 1 - i
        ax.plot([q3, p90], [y, y], color=COLORS[cid], linewidth=2, solid_capstyle="round", alpha=0.45)
        ax.plot([q1, q3], [y, y], color=COLORS[cid], linewidth=7, solid_capstyle="round", alpha=0.45)
        ax.scatter([med], [y], s=80, color=COLORS[cid], edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.annotate(f"{med:.0f}s", (med, y), xytext=(0, 9), textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, color=INK2)
    ax.set_yticks(range(len(cfgs)))
    ax.set_yticklabels([LABELS[c] for c in reversed(cfgs)], color=INK)
    ax.set_ylim(-0.6, len(cfgs) - 0.3)
    ax.set_xscale("log")
    ticks = [t for t in (1, 2, 5, 10, 20, 50, 100, 200, 500) if lat.latency_s.min() * 0.8 <= t <= lat.latency_s.quantile(0.95) * 1.6]
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}s"))
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
    _style(ax, "Time to answer per eval item")
    ax.text(0, 1.02, "Dot: median · thick bar: middle 50% · thin line: up to the 90th percentile · log scale · agentic items include every tool-use turn",
            transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    _save(fig, "latency_by_config")


def chart_tokens(df):
    fig, ax = _fig(10, 4.6)
    cfgs = [c for c in CONFIG_ORDER if c in df.config_id.unique()]
    ans = [df[df.config_id == c].answer_tokens.mean() for c in cfgs]
    rea = [df[df.config_id == c].reasoning_tokens.mean() for c in cfgs]
    ys = list(range(len(cfgs)))[::-1]
    b1 = ax.barh(ys, ans, color="#2a78d6", height=0.55, label="Answer tokens", edgecolor=SURFACE, linewidth=1)
    b2 = ax.barh(ys, rea, left=ans, color="#eb6834", height=0.55, label="Reasoning (thinking) tokens", edgecolor=SURFACE, linewidth=1)
    for y, a, r in zip(ys, ans, rea):
        ax.text(a + r, y, f"  {a + r:,.0f}", va="center", fontsize=9, color=INK2)
    ax.set_yticks(ys)
    ax.set_yticklabels([LABELS[c] for c in cfgs], color=INK)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    _style(ax, "Average output tokens per call")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower right", fontsize=9.5, labelcolor=INK2)
    ax.set_xlim(0, max(a + r for a, r in zip(ans, rea)) * 1.15)
    # round the data end of whichever segment is outermost on each row
    outer = [b2[i] if rea[i] > 0 else b1[i] for i in range(len(ys))]
    _round_ends(ax, outer, horizontal=True)
    _save(fig, "tokens_by_config")


def chart_quality_vs_latency(summ):
    fig, ax = _fig(8.5, 5.2)
    offsets = {"sol_low": (8, -16)}  # keep the two Sol labels apart
    for _, r in summ.iterrows():
        ax.scatter(r.latency_median_s, r.pass_rate, s=90, color=INK2, edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.annotate(r.label, (r.latency_median_s, r.pass_rate), xytext=offsets.get(r.config, (8, 6)),
                    textcoords="offset points", fontsize=9.5, color=INK)
    ax.set_xscale("log")
    lo_x, hi_x = summ.latency_median_s.min(), summ.latency_median_s.max()
    ax.set_xlim(lo_x * 0.8, hi_x * 1.9)
    ax.set_xticks([t for t in (2, 3, 5, 7, 10, 15, 20, 30, 50) if lo_x * 0.8 <= t <= hi_x * 1.9])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}s"))
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Median time to answer (log scale)", color=INK2, fontsize=10)
    ax.set_ylabel("Pass rate, all categories", color=INK2, fontsize=10)
    _style(ax, "Pass rate vs. median time to answer")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    lo = max(0, summ.pass_rate.min() - 0.1)
    ax.set_ylim(lo, min(1.02, summ.pass_rate.max() + 0.08))
    _save(fig, "quality_vs_latency")


# ------------------------------------------------------------------ markdown

def md_table(df, fmt=None):
    fmt = fmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in fmt and pd.notna(v):
                v = fmt[c](v)
            cells.append("" if pd.isna(v) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(run_ids):
    df = load(run_ids)
    DATA.mkdir(parents=True, exist_ok=True)
    summ = summarize(df)
    piv, lat, tok = by_category(df)
    items = per_item(df)
    gb, ab, ja = grounding_behavior(df), agentic_behavior(df), judge_agreement(df)
    cons = consistency(df)
    h2h = pd.DataFrame([head_to_head(df, x, y) for x, y in (("l4_off", "sol_low"), ("l4_high", "sol_high"),
                                                             ("l4_off", "l4_high"), ("l4_off", "l3"))
                        if x in df.config_id.unique() and y in df.config_id.unique()])
    cons.to_csv(DATA / "consistency.csv", index=False)
    h2h.to_csv(DATA / "head_to_head.csv", index=False)
    summ.to_csv(DATA / "summary_by_config.csv", index=False)
    piv.round(3).to_csv(DATA / "pass_rate_by_category.csv")
    lat.round(1).to_csv(DATA / "latency_median_s_by_category.csv")
    tok.round(0).to_csv(DATA / "output_tokens_median_by_category.csv")
    items.round(3).to_csv(DATA / "pass_rate_by_item.csv", index=False)
    if not gb.empty:
        gb.to_csv(DATA / "grounding_behavior.csv", index=False)
    if not ab.empty:
        ab.to_csv(DATA / "agentic_behavior.csv", index=False)
    if not ja.empty:
        ja.to_csv(DATA / "judge_agreement.csv", index=False)
    flat = df.drop(columns=["usage", "detail"]).copy()
    flat.to_csv(DATA / "all_results_flat.csv", index=False)

    chart_pass_by_category(df, summ)
    chart_latency(df)
    chart_tokens(df)
    chart_quality_vs_latency(summ)

    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731
    sec = lambda v: f"{v:.1f}"  # noqa: E731
    md = ["# Tables (generated by scripts/analyze.py)", "", f"Runs: {', '.join(run_ids)} · {len(df)} scored calls", ""]
    t = summ[["label", "runs", "pass_rate", "ci95_low", "ci95_high", "latency_median_s", "latency_p90_s",
              "output_tokens_mean", "reasoning_tokens_mean", "hit_token_cap", "api_errors"]].copy()
    t["pass_rate"] = t.apply(lambda r: f"{r.pass_rate * 100:.0f}% ({r.ci95_low * 100:.0f}–{r.ci95_high * 100:.0f}%)", axis=1)
    t = t.drop(columns=["ci95_low", "ci95_high"]).rename(columns={
        "label": "Config", "runs": "Calls", "pass_rate": "Pass rate (95% CI)", "latency_median_s": "Median latency (s)",
        "latency_p90_s": "p90 latency (s)", "output_tokens_mean": "Avg output tokens", "reasoning_tokens_mean": "Avg thinking tokens",
        "hit_token_cap": "Hit 32k cap", "api_errors": "API errors"})
    md += ["## Overall", "", md_table(t), ""]
    c = piv.copy()
    c.columns = [LABELS[x] for x in c.columns]
    c.index = [CAT_LABELS[x] for x in c.index]
    md += ["## Pass rate by category", "", md_table(c.reset_index().rename(columns={"index": "Category"}),
                                                   {k: pct for k in c.columns}), ""]
    l2 = lat.copy()
    l2.columns = [LABELS[x] for x in l2.columns]
    l2.index = [CAT_LABELS[x] for x in l2.index]
    md += ["## Median latency by category (seconds)", "", md_table(l2.reset_index().rename(columns={"index": "Category"}),
                                                                   {k: sec for k in l2.columns}), ""]
    if not gb.empty:
        g2 = gb.copy()
        g2["config_id"] = g2.config_id.map(LABELS)
        md += ["## Web-grounded questions: search behavior", "", md_table(g2), ""]
    if not ab.empty:
        a2 = ab.copy()
        a2["config_id"] = a2.config_id.map(LABELS)
        md += ["## Agentic scenarios: behavior", "", md_table(a2), ""]
    if not ja.empty:
        j2 = ja.copy()
        j2["config_id"] = j2.config_id.map(LABELS)
        md += ["## Your-documents questions: judge vs programmatic check", "", md_table(j2), ""]
    c3 = cons.copy()
    c3["config_id"] = c3.config_id.map(LABELS)
    md += ["## Consistency across the three runs (items)", "", md_table(c3), ""]
    if not h2h.empty:
        md += ["## Head to head (items where one config's pass rate is higher)", "", md_table(h2h.fillna(0)), ""]
    cost = summ[["label", "tokens_total", "est_cost_usd_list"]].rename(columns={
        "label": "Config", "tokens_total": "Tokens (in + out)", "est_cost_usd_list": "Est. cost at list price (USD)"})
    md += ["## Appendix: token totals and list-price cost", "", md_table(cost), ""]
    (REPORT / "tables.md").write_text("\n".join(md))
    print((REPORT / "tables.md").read_text()[:6000])


if __name__ == "__main__":
    main(sys.argv[1:] or ["full-r1"])
