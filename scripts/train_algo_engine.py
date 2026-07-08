"""Runs the AlgoEngine's signal-library search + backtest-ranked ensemble
fusion and saves the winning models + manifest for `agents/algo_engine.py`
to load. Mirrors `scripts/train_forecasting_model.py`'s shape: run this once
(and re-run periodically) before the AlgoEngine agent produces real
predictions -- until then it degrades to WAIT like Forecasting does without
a model.

Usage:
    python scripts/train_algo_engine.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.committee.algo_engine.ensemble import build_ensemble, write_manifest  # noqa: E402
from backend.committee.algo_engine.search import load_universe, run_search  # noqa: E402
from backend.committee.config import (  # noqa: E402
    ALGO_ENSEMBLE_MANIFEST_PATH,
    ALGO_MIN_TRAINING_ROWS,
    ALGO_MODEL_ARCHITECTURES,
    ALGO_MODEL_DIR,
    ALGO_SEED,
    ALGO_TOP_K,
    ALGO_TRAIN_INTERVAL,
    ALGO_TRAIN_PERIOD,
    ALGO_WALK_FORWARD_FOLDS,
    WATCHLIST,
)


def main() -> None:
    print(f"Pulling {ALGO_TRAIN_PERIOD} of {ALGO_TRAIN_INTERVAL} history for {len(WATCHLIST)} watchlist symbols...")
    symbol_data = load_universe(WATCHLIST, ALGO_TRAIN_PERIOD, ALGO_TRAIN_INTERVAL)
    total_rows = sum(len(sd.signals) for sd in symbol_data)
    if total_rows < ALGO_MIN_TRAINING_ROWS:
        raise SystemExit(
            f"Only {total_rows} rows pooled across {len(symbol_data)} symbols (need >= {ALGO_MIN_TRAINING_ROWS}). "
            "Check BREEZE_SESSION_TOKEN hasn't expired (refresh it daily) and try again."
        )
    print(f"  loaded {len(symbol_data)}/{len(WATCHLIST)} symbols, {total_rows} total rows")

    print(f"\nSearching (feature subset x model architecture) candidates over {ALGO_WALK_FORWARD_FOLDS - 1} walk-forward folds...")
    results = run_search(symbol_data=symbol_data, folds=ALGO_WALK_FORWARD_FOLDS, architectures=ALGO_MODEL_ARCHITECTURES, seed=ALGO_SEED)

    print(f"\nTop {min(10, len(results))} candidates by average backtested Sharpe:")
    print(f"  {'subset':<20} {'model':<14} {'sharpe':>10} {'folds':>7}")
    for r in results[:10]:
        print(f"  {r.subset_name:<20} {r.model_type:<14} {r.sharpe:>10.3f} {r.folds_evaluated:>7}")

    print(f"\nFusing top {ALGO_TOP_K} candidates into the final ensemble...")
    members = build_ensemble(results, symbol_data, top_k=ALGO_TOP_K, seed=ALGO_SEED, model_dir=Path(ALGO_MODEL_DIR))
    for m in members:
        print(f"  weight={m.weight:.3f}  sharpe={m.backtest_sharpe:.3f}  {m.subset_name}/{m.model_type} -> {m.model_path}")

    write_manifest(members, Path(ALGO_ENSEMBLE_MANIFEST_PATH))
    print(f"\nSaved ensemble manifest to {ALGO_ENSEMBLE_MANIFEST_PATH}")


if __name__ == "__main__":
    main()
