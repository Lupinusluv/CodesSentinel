"""
CodeSentinel Evaluation Script

Compares Multi-Agent system against a Single-LLM baseline on hand-labelled samples.

Usage (run from backend/ directory):
    python scripts/run_eval.py                   # all 40 samples
    python scripts/run_eval.py --subset security
    python scripts/run_eval.py --subset security,performance
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# backend/ is the working directory; add it to path for app.* imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.graph import compiled_graph
from app.agents.llm import get_llm
from app.agents.state import IssueOutput, ReviewState
from app.agents.synthesis_agent import deduplicate_issues
from app.core.logging import get_logger

log = get_logger(__name__)

EVAL_DATA_DIR = Path(__file__).parent / "eval_data"

_BASELINE_SYSTEM = """\
You are a code reviewer. Analyse the provided code and identify security, performance, and style issues.

Return ONLY a JSON object — no markdown, no explanation — in exactly this format:
{
  "issues": [
    {
      "category": "security|performance|style",
      "severity": "critical|warning|suggestion",
      "line_start": <integer>,
      "description": "<concise description of the issue>"
    }
  ]
}

Rules:
- category must be exactly one of: security, performance, style
- severity must be exactly one of: critical, warning, suggestion
- line_start is the first line where the issue appears (1-indexed)
- Report every real issue you find; do not hallucinate issues that are not present\
"""


# ── Data loading ──────────────────────────────────────────────────────────────


def load_samples(subset: list[str] | None = None) -> list[dict]:
    categories = subset or ["security", "performance", "style"]
    samples: list[dict] = []
    for cat in categories:
        path = EVAL_DATA_DIR / f"{cat}.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        samples.extend(data["samples"])
    return samples


# ── Matching logic ─────────────────────────────────────────────────────────────


def _issue_matches(predicted: dict, expected: dict) -> bool:
    """True when predicted issue satisfies all three criteria for expected."""
    # 1. Category exact match
    pred_cat = predicted.get("category", "")
    if hasattr(pred_cat, "value"):
        pred_cat = pred_cat.value
    if pred_cat != expected["category"]:
        return False

    # 2. Line proximity (±3 tolerance; skip check if expected omits line_start)
    exp_line = expected.get("line_start")
    if exp_line is not None:
        pred_line = predicted.get("line_start")
        if pred_line is None or abs(int(pred_line) - exp_line) > 3:
            return False

    # 3. At least one keyword present in description (case-insensitive)
    desc = (predicted.get("description") or "").lower()
    if not any(kw.lower() in desc for kw in expected.get("keywords", [])):
        return False

    return True


def compute_metrics(
    all_predicted: list[list[dict]],
    all_expected: list[list[dict]],
) -> dict:
    """Greedy bipartite matching → per-category and overall P/R/F1."""
    tp_total = fp_total = fn_total = 0
    cat_stats: dict[str, dict[str, int]] = {}

    for predicted, expected in zip(all_predicted, all_expected):
        for exp in expected:
            cat_stats.setdefault(exp["category"], {"tp": 0, "fp": 0, "fn": 0})

        matched_pred: set[int] = set()
        matched_exp: set[int] = set()

        for ei, exp in enumerate(expected):
            for pi, pred in enumerate(predicted):
                if pi in matched_pred:
                    continue
                if _issue_matches(pred, exp):
                    matched_pred.add(pi)
                    matched_exp.add(ei)
                    break

        tp = len(matched_exp)
        fp = len(predicted) - len(matched_pred)
        fn = len(expected) - tp

        tp_total += tp
        fp_total += fp
        fn_total += fn

        for ei, exp in enumerate(expected):
            cat = exp["category"]
            if ei in matched_exp:
                cat_stats[cat]["tp"] += 1
            else:
                cat_stats[cat]["fn"] += 1

        for pi, pred in enumerate(predicted):
            pred_cat = pred.get("category", "")
            if hasattr(pred_cat, "value"):
                pred_cat = pred_cat.value
            if pi not in matched_pred and pred_cat in cat_stats:
                cat_stats[pred_cat]["fp"] += 1

    def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        return p, r, f

    overall_p, overall_r, overall_f = _prf(tp_total, fp_total, fn_total)

    per_cat: dict[str, dict[str, float]] = {}
    for cat, s in cat_stats.items():
        p, r, f = _prf(s["tp"], s["fp"], s["fn"])
        per_cat[cat] = {"precision": p, "recall": r, "f1": f}

    return {"precision": overall_p, "recall": overall_r, "f1": overall_f, "per_category": per_cat}


# ── Runners ───────────────────────────────────────────────────────────────────


def _normalise_issues(issues: list[IssueOutput]) -> list[dict]:
    return [
        {
            "category": i.category.value if hasattr(i.category, "value") else str(i.category),
            "severity": i.severity.value if hasattr(i.severity, "value") else str(i.severity),
            "line_start": i.line_start,
            "description": i.description,
        }
        for i in issues
    ]


async def run_multi_agent(sample: dict) -> list[dict]:
    state: ReviewState = {
        "source_code": sample["source_code"],
        "language": sample["language"],
        "rag_context": "",  # no DB during eval
        "issues": [],
        "report_text": "",
        "error": None,
    }
    try:
        final = await compiled_graph.ainvoke(state)
        raw: list[IssueOutput] = deduplicate_issues(final.get("issues", []))
        return _normalise_issues(raw)
    except Exception as exc:
        print(f"\n  [multi-agent error] {sample['id']}: {exc}")
        return []


async def run_baseline(sample: dict) -> list[dict]:
    llm = get_llm(temperature=0)
    user_msg = f"Language: {sample['language']}\n\nCode:\n```{sample['language']}\n{sample['source_code']}\n```"
    try:
        resp = await llm.ainvoke(
            [
                SystemMessage(content=_BASELINE_SYSTEM),
                HumanMessage(content=user_msg),
            ]
        )
        text = resp.content.strip()
        # Strip markdown fences if the model adds them
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(text)
        return data.get("issues", [])
    except Exception as exc:
        print(f"\n  [baseline error] {sample['id']}: {exc}")
        return []


# ── Output formatting ─────────────────────────────────────────────────────────


def print_results(multi: dict, base: dict) -> None:
    cats = ["security", "performance", "style"]
    W = 56

    print("\n" + "=" * W)
    print("  CodeSentinel Eval Results")
    print("=" * W)
    print(f"  {'':14s} | {'Multi-Agent':>12} | {'Single-LLM':>10}")
    print("  " + "-" * (W - 2))
    print(f"  {'Precision':14s} | {multi['precision']:>11.1%} | {base['precision']:>9.1%}")
    print(f"  {'Recall':14s} | {multi['recall']:>11.1%} | {base['recall']:>9.1%}")
    print(f"  {'F1':14s} | {multi['f1']:>11.1%} | {base['f1']:>9.1%}")
    print("  " + "-" * (W - 2))
    for cat in cats:
        m = multi["per_category"].get(cat, {})
        b = base["per_category"].get(cat, {})
        mp, mr = m.get("precision", 0), m.get("recall", 0)
        bp, br = b.get("precision", 0), b.get("recall", 0)
        label = cat.capitalize()
        print(
            f"  {label:14s} | P={mp:.0%} R={mr:.0%} F1={m.get('f1', 0):.0%}   "
            f"| P={bp:.0%} R={br:.0%} F1={b.get('f1', 0):.0%}"
        )
    print("=" * W)


# ── Result persistence ────────────────────────────────────────────────────────


def _write_payload(out_path: Path, payload: dict) -> None:
    """Atomic-ish write: write to tmp then rename, so a crash mid-flush can't truncate."""
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)


# ── Entry point ───────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CodeSentinel vs single-LLM baseline")
    parser.add_argument(
        "--subset",
        default=None,
        metavar="CATS",
        help="Comma-separated categories to run, e.g. 'security' or 'security,performance'",
    )
    parser.add_argument(
        "--reuse-baseline",
        default=None,
        metavar="PATH",
        help="Path to a previous result JSON; reuse its baseline_predicted/metrics instead of re-running baseline",
    )
    args = parser.parse_args()

    subset = [s.strip() for s in args.subset.split(",")] if args.subset else None
    samples = load_samples(subset)

    reuse_baseline_map: dict[str, list[dict]] | None = None
    if args.reuse_baseline:
        with open(args.reuse_baseline, encoding="utf-8") as f:
            old = json.load(f)
        reuse_baseline_map = {s["id"]: s["baseline_predicted"] for s in old.get("per_sample", [])}
        missing = [s["id"] for s in samples if s["id"] not in reuse_baseline_map]
        if missing:
            raise SystemExit(f"--reuse-baseline missing predictions for: {missing[:3]} ...")
        print(
            f"Reusing baseline predictions from {args.reuse_baseline} (metrics will be re-computed against current expected_issues)"
        )

    if reuse_baseline_map is not None:
        print(f"Loaded {len(samples)} samples. Running multi-agent only (baseline reused)...")
    else:
        print(
            f"Loaded {len(samples)} samples. Running multi-agent and baseline in parallel per sample..."
        )

    results_dir = Path(__file__).parent / "eval_results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = results_dir / f"{ts}.json"
    print(f"Incremental results → {out_path}")

    multi_predicted: list[list[dict]] = []
    baseline_predicted: list[list[dict]] = []
    all_expected: list[list[dict]] = []
    per_sample: list[dict] = []
    total_elapsed = 0.0

    base_payload: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(samples),
        "completed_count": 0,
        "categories": sorted({s["id"].split("_")[0] for s in samples}),
        "elapsed_seconds": 0.0,
        "per_sample": per_sample,
        "multi_agent": None,
        "single_llm_baseline": None,
    }

    for i, sample in enumerate(samples, 1):
        print(f"[{i:2d}/{len(samples)}] {sample['id']} ...", end=" ", flush=True)
        t0 = time.monotonic()

        if reuse_baseline_map is not None:
            m_issues = await run_multi_agent(sample)
            b_issues = reuse_baseline_map[sample["id"]]
        else:
            m_issues, b_issues = await asyncio.gather(
                run_multi_agent(sample),
                run_baseline(sample),
            )

        elapsed = time.monotonic() - t0
        total_elapsed += elapsed
        print(f"multi={len(m_issues)} baseline={len(b_issues)} ({elapsed:.1f}s)")

        multi_predicted.append(m_issues)
        baseline_predicted.append(b_issues)
        all_expected.append(sample["expected_issues"])

        per_sample.append(
            {
                "id": sample["id"],
                "category": sample["id"].split("_")[0],
                "elapsed_s": round(elapsed, 2),
                "expected": sample["expected_issues"],
                "multi_predicted": m_issues,
                "baseline_predicted": b_issues,
            }
        )

        # Incremental snapshot — survives Ctrl-C / crash on later samples
        base_payload["completed_count"] = i
        base_payload["elapsed_seconds"] = round(total_elapsed, 1)
        _write_payload(out_path, base_payload)

    multi_metrics = compute_metrics(multi_predicted, all_expected)
    # Always re-compute baseline metrics from predictions against current expected_issues.
    # This is critical when expected_issues' keyword set has changed since the cached run.
    baseline_metrics = compute_metrics(baseline_predicted, all_expected)

    print(f"\nTotal elapsed: {total_elapsed:.0f}s")
    print_results(multi_metrics, baseline_metrics)

    base_payload["multi_agent"] = multi_metrics
    base_payload["single_llm_baseline"] = baseline_metrics
    _write_payload(out_path, base_payload)
    print(f"Results saved → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
