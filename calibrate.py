"""
Word-count calibration script for MUNBOT.

Phase 1 — Baseline: 5 tests per page spec (1–5 pages), 25 tests total.
Phase 2 — Recursive: sets of 3 tests per page spec, adjusting WORDS_PER_PAGE
           until mean body-word error is within 5% for every page spec.

Outputs
-------
calibration/baseline_results.json
calibration/calibration_log.json
calibration/baseline_wordcount.png
calibration/baseline_error_pct.png
calibration/calibration_curve.png
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ---------------------------------------------------------------------------
# Patch WORDS_PER_PAGE before importing llm so the calibration can override
# ---------------------------------------------------------------------------
import llm  # noqa: E402  (after matplotlib backend set)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "calibration")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Test matrix  — 5 tests per page spec, varied topics & countries
# ---------------------------------------------------------------------------
TEST_CASES = {
    1: [
        ("The Sudan Refugee Crisis",              "France",        "UNHCR"),
        ("Climate Change and Small Island States","Marshall Islands","UNEP"),
        ("Nuclear Non-Proliferation",             "Germany",       "First Committee"),
        ("Cybersecurity and State-Sponsored Hacking","Japan",      "DISEC"),
        ("Human Trafficking and Forced Migration","Brazil",        "Third Committee"),
    ],
    2: [
        ("The Syrian Civil War and Refugee Crisis","Turkey",       "Security Council"),
        ("Amazon Deforestation and Biodiversity", "Brazil",        "UNEP"),
        ("North Korean Nuclear Program",          "South Korea",   "Security Council"),
        ("Internet Governance and Digital Rights","Germany",       "ITU"),
        ("Yemen Humanitarian Crisis",             "Saudi Arabia",  "Security Council"),
    ],
    3: [
        ("The Taiwan Strait and Regional Stability","United States","Security Council"),
        ("Climate Finance for Developing Nations", "India",        "UNFCCC"),
        ("Drug Trafficking and Organized Crime",   "Mexico",       "UNODC"),
        ("Arctic Sovereignty and Resource Rights", "Canada",       "UNCLOS"),
        ("Palestinian Statehood and Self-Determination","Egypt",   "General Assembly"),
    ],
    4: [
        ("Afghanistan Under Taliban Rule",         "Pakistan",     "Security Council"),
        ("Rohingya Genocide and Accountability",   "Bangladesh",   "Human Rights Council"),
        ("Water Scarcity and Transboundary Rivers","Ethiopia",     "General Assembly"),
        ("Autonomous Weapons and AI in Warfare",   "United Kingdom","DISEC"),
        ("Global Food Security and Famine Prevention","Nigeria",   "FAO"),
    ],
    5: [
        ("The Iran Nuclear Deal and Regional Security","Israel",   "Security Council"),
        ("Debt Relief for Developing Nations",     "Argentina",    "Second Committee"),
        ("Deforestation and Indigenous Rights",    "Indonesia",    "UNEP"),
        ("NATO Expansion and European Security",   "Poland",       "Security Council"),
        ("Global Health Equity and Pandemic Preparedness","Kenya","WHO"),
    ],
}

# ---------------------------------------------------------------------------
# Research cache — run research once per topic, reuse across tests
# ---------------------------------------------------------------------------
_research_cache: dict[str, list[dict]] = {}
_STUB_RESEARCH = False   # set to True via --stub-research flag


def _stub_sources(topic: str, country: str) -> list[dict]:
    return [
        {"title": f"{topic} – UN background", "url": "https://un.org", "text": f"The United Nations has addressed {topic} through various resolutions and committees."},
        {"title": f"{country} policy on {topic}", "url": "https://un.org/policy", "text": f"{country} maintains an active foreign policy position regarding {topic}."},
        {"title": f"Global context: {topic}", "url": "https://un.org/global", "text": f"International cooperation is essential to address {topic} effectively."},
    ]


def _get_sources(topic: str, country: str) -> list[dict]:
    if _STUB_RESEARCH:
        return _stub_sources(topic, country)
    key = f"{topic}|{country}"
    if key not in _research_cache:
        from research import gather_research
        print(f"    [research] {topic} / {country} …", flush=True)
        try:
            sources = gather_research(topic, country)
        except Exception as e:
            print(f"    [research] FAILED ({e}), using stub sources", flush=True)
            sources = _stub_sources(topic, country)
        _research_cache[key] = sources
        time.sleep(2)   # polite delay between DDG batches
    return _research_cache[key]


# ---------------------------------------------------------------------------
# Single test run
# ---------------------------------------------------------------------------

def run_test(pages: int, topic: str, country: str, committee: str) -> dict:
    """Generate one paper and return measured body-word count."""
    target = pages * llm.WORDS_PER_PAGE
    sources = _get_sources(topic, country)

    t0 = time.time()
    try:
        paper = llm.generate_paper(
            topic=topic,
            country=country,
            committee=committee,
            pages=pages,
            sources=sources,
        )
        elapsed = time.time() - t0
        actual = llm._count_body_words(paper)
        error_pct = (actual - target) / target * 100
    except Exception as e:
        elapsed = time.time() - t0
        print(f"    [ERROR] {e}", flush=True)
        actual = 0
        error_pct = -100.0

    return {
        "pages": pages,
        "topic": topic,
        "country": country,
        "committee": committee,
        "words_per_page": llm.WORDS_PER_PAGE,
        "target_words": target,
        "actual_words": actual,
        "error_pct": round(error_pct, 2),
        "elapsed_s": round(elapsed, 1),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def _page_specs():
    return sorted(TEST_CASES.keys())


def plot_baseline(results: list[dict], suffix: str = "") -> None:
    specs = _page_specs()

    # --- target vs actual bar chart ---
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(specs))
    width = 0.35

    targets = [specs[i] * llm.WORDS_PER_PAGE for i in range(len(specs))]
    actuals_mean = []
    actuals_std  = []
    for p in specs:
        vals = [r["actual_words"] for r in results if r["pages"] == p and r["actual_words"] > 0]
        actuals_mean.append(np.mean(vals) if vals else 0)
        actuals_std.append(np.std(vals)  if vals else 0)

    bars1 = ax.bar(x - width/2, targets, width, label="Target words", color="#4C72B0", alpha=0.85)
    bars2 = ax.bar(x + width/2, actuals_mean, width, yerr=actuals_std,
                   label="Actual words (mean ± σ)", color="#DD8452", alpha=0.85,
                   capsize=4)

    ax.set_xlabel("Page spec")
    ax.set_ylabel("Body word count")
    ax.set_title(f"Target vs Actual Word Count by Page Spec{suffix}")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{p} page{'s' if p > 1 else ''}" for p in specs])
    ax.legend()
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

    # annotate each actual bar
    for bar, mean, std in zip(bars2, actuals_mean, actuals_std):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + std + 5,
                f"{int(mean)}", ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    fname = os.path.join(OUTPUT_DIR, f"baseline_wordcount{suffix}.png")
    plt.savefig(fname, dpi=150)
    plt.close()
    print(f"  Saved {fname}")


def plot_error_pct(results: list[dict], suffix: str = "") -> None:
    specs = _page_specs()
    fig, axes = plt.subplots(1, len(specs), figsize=(3 * len(specs), 4), sharey=True)

    for ax, p in zip(axes, specs):
        vals = [r["error_pct"] for r in results if r["pages"] == p]
        colors = ["#2ca02c" if abs(v) <= 5 else "#d62728" for v in vals]
        ax.bar(range(len(vals)), vals, color=colors, alpha=0.8)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.axhline(5,  color="green", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.axhline(-5, color="green", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.set_title(f"{p}p")
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels([r["country"][:4] for r in results if r["pages"] == p],
                           fontsize=7)

    axes[0].set_ylabel("Error %  (actual − target) / target")
    fig.suptitle(f"Per-test error by page spec{suffix}\n(green band = ±5%)")
    plt.tight_layout()
    fname = os.path.join(OUTPUT_DIR, f"baseline_error_pct{suffix}.png")
    plt.savefig(fname, dpi=150)
    plt.close()
    print(f"  Saved {fname}")


def plot_calibration_curve(cal_log: list[dict]) -> None:
    if not cal_log:
        return
    specs = sorted({e["pages"] for e in cal_log})
    fig, axes = plt.subplots(1, len(specs), figsize=(4 * len(specs), 4), sharey=True)
    if len(specs) == 1:
        axes = [axes]

    for ax, p in zip(axes, specs):
        entries = [e for e in cal_log if e["pages"] == p]
        wpp     = [e["words_per_page"] for e in entries]
        mean_err = [e["mean_error_pct"] for e in entries]
        ax.plot(wpp, mean_err, "o-", color="#4C72B0")
        ax.axhline(0,  color="black", linewidth=0.8)
        ax.axhline(5,  color="green", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.axhline(-5, color="green", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.set_xlabel("WORDS_PER_PAGE")
        ax.set_title(f"{p} page{'s' if p > 1 else ''}")

    axes[0].set_ylabel("Mean error % (actual − target) / target")
    fig.suptitle("Calibration curve: mean error vs WORDS_PER_PAGE")
    plt.tight_layout()
    fname = os.path.join(OUTPUT_DIR, "calibration_curve.png")
    plt.savefig(fname, dpi=150)
    plt.close()
    print(f"  Saved {fname}")


# ---------------------------------------------------------------------------
# Phase 1 — Baseline (5 tests × 5 page specs)
# ---------------------------------------------------------------------------

def run_baseline() -> list[dict]:
    results = []
    total = sum(len(v) for v in TEST_CASES.values())
    done  = 0

    print(f"\n{'='*60}")
    print(f"PHASE 1 — Baseline  ({total} tests,  WORDS_PER_PAGE={llm.WORDS_PER_PAGE})")
    print(f"{'='*60}")

    for pages in _page_specs():
        print(f"\n  Page spec: {pages}")
        for topic, country, committee in TEST_CASES[pages]:
            done += 1
            print(f"  [{done}/{total}] {pages}p | {country} | {topic[:45]}…")
            r = run_test(pages, topic, country, committee)
            results.append(r)
            status = "OK" if abs(r["error_pct"]) <= 5 else "OVER" if r["error_pct"] > 0 else "UNDER"
            print(f"         target={r['target_words']}  actual={r['actual_words']}  "
                  f"err={r['error_pct']:+.1f}%  [{status}]  {r['elapsed_s']}s")

    fpath = os.path.join(OUTPUT_DIR, "baseline_results.json")
    with open(fpath, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Saved {fpath}")
    return results


# ---------------------------------------------------------------------------
# Phase 2 — Recursive calibration (3 tests per page spec per iteration)
# ---------------------------------------------------------------------------

CALIB_TESTS_PER_ROUND = 3   # use first N test cases from each page spec
TARGET_ABS_ERR = 5.0        # stop when mean |error| ≤ 5%
MAX_ROUNDS = 6              # safety limit

# Calibration test cases (3 each, subset of baseline)
CALIB_CASES = {p: TEST_CASES[p][:CALIB_TESTS_PER_ROUND] for p in _page_specs()}


def _mean_error_pct(results: list[dict], pages: int) -> float:
    vals = [r["error_pct"] for r in results if r["pages"] == pages and r["actual_words"] > 0]
    return float(np.mean(vals)) if vals else 0.0


def _adjust_wpp(current_wpp: int, mean_err: float) -> int:
    """
    Proportional adjustment: if actual > target (positive error), reduce WPP;
    if actual < target (negative error), increase WPP.
    Step size proportional to error magnitude.
    """
    factor = 1.0 - (mean_err / 100.0) * 0.6   # 60% of error correction per step
    new_wpp = int(round(current_wpp * factor))
    # Clamp to sane range
    return max(150, min(350, new_wpp))


def run_calibration(baseline_results: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    For each page spec independently, run up to MAX_ROUNDS of 3-test batches,
    adjusting WORDS_PER_PAGE until mean |error| ≤ TARGET_ABS_ERR.

    Returns (all_calibration_results, calibration_log)
    """
    cal_results = []
    cal_log     = []

    # Each page spec gets its own WPP (they usually converge to the same value,
    # but track independently to find any per-spec drift)
    wpp_per_spec: dict[int, int] = {p: llm.WORDS_PER_PAGE for p in _page_specs()}
    converged: set[int] = set()

    print(f"\n{'='*60}")
    print("PHASE 2 — Recursive calibration")
    print(f"  target |error| ≤ {TARGET_ABS_ERR}%,  max {MAX_ROUNDS} rounds per spec")
    print(f"{'='*60}")

    for rnd in range(1, MAX_ROUNDS + 1):
        pending = [p for p in _page_specs() if p not in converged]
        if not pending:
            print("\n  All specs converged. Done.")
            break

        print(f"\n  Round {rnd}  (pending specs: {pending})")

        for pages in pending:
            llm.WORDS_PER_PAGE = wpp_per_spec[pages]
            print(f"\n    [{pages}p] WORDS_PER_PAGE={llm.WORDS_PER_PAGE}")

            round_results = []
            for i, (topic, country, committee) in enumerate(CALIB_CASES[pages]):
                print(f"      test {i+1}/{CALIB_TESTS_PER_ROUND}: {country} | {topic[:40]}…")
                r = run_test(pages, topic, country, committee)
                round_results.append(r)
                cal_results.append(r)
                print(f"        target={r['target_words']}  actual={r['actual_words']}  "
                      f"err={r['error_pct']:+.1f}%")

            mean_err = _mean_error_pct(round_results, pages)
            print(f"      → mean error: {mean_err:+.1f}%")

            cal_log.append({
                "round": rnd,
                "pages": pages,
                "words_per_page": wpp_per_spec[pages],
                "mean_error_pct": round(mean_err, 2),
                "results": [r["error_pct"] for r in round_results],
            })

            if abs(mean_err) <= TARGET_ABS_ERR:
                print(f"      ✓ Converged for {pages}p at WPP={wpp_per_spec[pages]}")
                converged.add(pages)
            else:
                new_wpp = _adjust_wpp(wpp_per_spec[pages], mean_err)
                print(f"      → Adjusting WPP: {wpp_per_spec[pages]} → {new_wpp}")
                wpp_per_spec[pages] = new_wpp

    # Report final per-spec WPP
    print("\n  Final calibrated WORDS_PER_PAGE per spec:")
    for p in _page_specs():
        status = "converged" if p in converged else "NOT converged (max rounds hit)"
        print(f"    {p}p → WPP={wpp_per_spec[p]}  [{status}]")

    # Recommend a single WPP (median of converged specs)
    converged_wpps = [wpp_per_spec[p] for p in converged]
    if converged_wpps:
        recommended = int(np.median(converged_wpps))
        print(f"\n  Recommended WORDS_PER_PAGE = {recommended}  (median of converged specs)")
    else:
        recommended = llm.WORDS_PER_PAGE

    fpath = os.path.join(OUTPUT_DIR, "calibration_log.json")
    with open(fpath, "w") as f:
        json.dump({"wpp_per_spec": wpp_per_spec,
                   "recommended_wpp": recommended,
                   "converged_specs": list(converged),
                   "log": cal_log}, f, indent=2)
    print(f"\n  Saved {fpath}")

    return cal_results, cal_log, recommended


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _STUB_RESEARCH
    parser = argparse.ArgumentParser(description="MUNBOT word-count calibration")
    parser.add_argument("--stub-research", action="store_true",
                        help="Skip DDG research; use stub sources (faster, no network needed)")
    args = parser.parse_args()
    _STUB_RESEARCH = args.stub_research
    if _STUB_RESEARCH:
        print("  [mode] stub research — skipping DDG, using placeholder sources")

    # Phase 1
    baseline = run_baseline()

    print("\n  Generating baseline plots…")
    plot_baseline(baseline)
    plot_error_pct(baseline)

    # Summary table
    print(f"\n  {'Page':<6} {'Target':>8} {'Mean actual':>12} {'Mean err%':>10} {'StdDev':>8}")
    print(f"  {'-'*50}")
    for p in _page_specs():
        rows  = [r for r in baseline if r["pages"] == p]
        tgt   = p * llm.WORDS_PER_PAGE
        means = np.mean([r["actual_words"] for r in rows])
        errs  = np.mean([r["error_pct"] for r in rows])
        stds  = np.std([r["error_pct"] for r in rows])
        print(f"  {p}p{'':<4} {tgt:>8,} {means:>12,.0f} {errs:>+10.1f}% {stds:>7.1f}%")

    # Phase 2
    cal_results, cal_log, recommended_wpp = run_calibration(baseline)

    print("\n  Generating calibration plots…")
    all_results = baseline + cal_results
    plot_baseline(all_results, suffix="_post_calibration")
    plot_error_pct(all_results, suffix="_post_calibration")
    plot_calibration_curve(cal_log)

    print(f"\n{'='*60}")
    print(f"  Recommended WORDS_PER_PAGE = {recommended_wpp}")
    print(f"  Update llm.py line ~32:  WORDS_PER_PAGE = {recommended_wpp}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
