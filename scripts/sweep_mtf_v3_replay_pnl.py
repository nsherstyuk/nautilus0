from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_SCRIPT = PROJECT_ROOT / "scripts" / "run_backtest_mtf_v3_replay_pnl.py"


@dataclass(frozen=True)
class SweepCase:
    master_threshold: float
    soldier_entry_threshold: float
    tp_atr_mult: float
    sl_atr_mult: float
    cooldown_minutes: int

    def to_env(self) -> Dict[str, str]:
        return {
            "MTF3_MASTER_PREDICTION_THRESHOLD": f"{self.master_threshold:.4f}",
            "MTF3_SOLDIER_ENTRY_THRESHOLD": f"{self.soldier_entry_threshold:.4f}",
            "MTF3_TP_ATR_MULT": f"{self.tp_atr_mult:.4f}",
            "MTF3_SL_ATR_MULT": f"{self.sl_atr_mult:.4f}",
            "MTF3_COOLDOWN_MINUTES": str(self.cooldown_minutes),
        }


def _grid(values: List[float]) -> List[float]:
    return values


def _cases(
    master_thresholds: List[float],
    soldier_thresholds: List[float],
    tp_mults: List[float],
    sl_mults: List[float],
    cooldowns: List[int],
) -> Iterable[SweepCase]:
    for mt in master_thresholds:
        for st in soldier_thresholds:
            for tp in tp_mults:
                for sl in sl_mults:
                    for cd in cooldowns:
                        yield SweepCase(mt, st, tp, sl, cd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parameter sweep for v3 replay PnL backtest")
    parser.add_argument("--instrument", default=os.getenv("MTF3_INSTRUMENT", "EUR/USD.IDEALPRO"))
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--what", default=os.getenv("MTF3_WHAT_TO_SHOW", "MIDPOINT"))
    parser.add_argument("--catalog", default=str(Path("data") / "historical"))

    parser.add_argument("--master-thresholds", default="0.65,0.70,0.75")
    parser.add_argument("--soldier-thresholds", default="0.50,0.60,0.70")
    parser.add_argument("--tp-mults", default="0.40,0.60,0.80")
    parser.add_argument("--sl-mults", default="1.20,1.40,1.60")
    parser.add_argument("--cooldowns", default="20,30,45")

    parser.add_argument(
        "--out-root",
        default=str(PROJECT_ROOT / "backtest_results" / "sweeps"),
        help="Root output directory (each case creates a subdir)",
    )
    parser.add_argument(
        "--threshold-mode",
        default=os.getenv("MTF3_MASTER_THRESHOLD_MODE", "abs"),
        help="Master threshold mode to force during sweep (signed|abs)",
    )
    args = parser.parse_args()

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    master_thresholds = [float(x) for x in args.master_thresholds.split(",") if x.strip()]
    soldier_thresholds = [float(x) for x in args.soldier_thresholds.split(",") if x.strip()]
    tp_mults = [float(x) for x in args.tp_mults.split(",") if x.strip()]
    sl_mults = [float(x) for x in args.sl_mults.split(",") if x.strip()]
    cooldowns = [int(x) for x in args.cooldowns.split(",") if x.strip()]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sweep_dir = out_root / f"SWEEP_V3_{run_id}_{args.instrument.replace('/', '')}"
    sweep_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, object]] = []

    for idx, case in enumerate(_cases(master_thresholds, soldier_thresholds, tp_mults, sl_mults, cooldowns), start=1):
        case_env = os.environ.copy()
        case_env.update(case.to_env())
        case_env["MTF3_MASTER_THRESHOLD_MODE"] = str(args.threshold_mode)

        case_name = (
            f"case_{idx:04d}__mt{case.master_threshold:.2f}__st{case.soldier_entry_threshold:.2f}"
            f"__tp{case.tp_atr_mult:.2f}__sl{case.sl_atr_mult:.2f}__cd{case.cooldown_minutes}"
        )
        out_dir = sweep_dir / case_name

        cmd = [
            sys.executable,
            str(BACKTEST_SCRIPT),
            "--instrument",
            args.instrument,
            "--start",
            args.start,
            "--end",
            args.end,
            "--what",
            args.what,
            "--catalog",
            args.catalog,
            "--out",
            str(out_dir),
        ]

        print(f"[{idx}] {case_name}")
        proc = subprocess.run(cmd, env=case_env, cwd=str(PROJECT_ROOT), capture_output=True, text=True)

        summary_path = out_dir / "summary.json"
        summary: Dict[str, object] = {}
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        results.append(
            {
                "case": case_name,
                "params": {
                    "master_threshold": case.master_threshold,
                    "soldier_entry_threshold": case.soldier_entry_threshold,
                    "tp_atr_mult": case.tp_atr_mult,
                    "sl_atr_mult": case.sl_atr_mult,
                    "cooldown_minutes": case.cooldown_minutes,
                    "master_threshold_mode": str(args.threshold_mode),
                },
                "exit_code": proc.returncode,
                "summary": summary,
                "stdout_tail": proc.stdout[-2000:],
                "stderr_tail": proc.stderr[-2000:],
            }
        )

        if proc.returncode != 0:
            print(f"  FAILED exit={proc.returncode}")
        else:
            net = summary.get("net_pnl")
            trades = summary.get("trades")
            print(f"  ok trades={trades} net_pnl={net}")

    (sweep_dir / "sweep_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote: {sweep_dir / 'sweep_results.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
