from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _decode_fixed8_le_int64_series(s: pd.Series) -> np.ndarray:
    # Nautilus parquet stores numeric fields as fixed_size_binary[8] (int64 little-endian).
    if s.dtype != object:
        return pd.to_numeric(s, errors="coerce").astype(float).to_numpy()

    sample = None
    for v in s[:50].tolist():
        if v is None:
            continue
        if isinstance(v, float) and np.isnan(v):
            continue
        sample = v
        break

    if sample is None:
        return pd.to_numeric(s, errors="coerce").astype(float).to_numpy()

    try:
        b0 = bytes(sample)
    except Exception:
        return pd.to_numeric(s, errors="coerce").astype(float).to_numpy()

    if len(b0) != 8:
        return pd.to_numeric(s, errors="coerce").astype(float).to_numpy()

    arr = s.to_numpy()
    mask = pd.isna(s).to_numpy()
    out = np.empty(len(arr), dtype=np.float64)
    out[:] = np.nan

    if (~mask).sum() == 0:
        return out

    buf = b"".join(bytes(x) for x in arr[~mask])
    ints = np.frombuffer(buf, dtype="<i8")
    out[~mask] = ints.astype(np.float64)
    return out


def _choose_scale(median_abs_raw: float, candidates: tuple[float, ...], expected_range: tuple[float, float]) -> float:
    if not np.isfinite(median_abs_raw) or median_abs_raw == 0.0:
        return candidates[-1]
    lo, hi = expected_range
    for sc in candidates:
        v = median_abs_raw / sc
        if lo <= v <= hi:
            return sc
    return candidates[-1]


def _coerce_bar_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Decode OHLC to float price units.
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            raw = _decode_fixed8_le_int64_series(df[col])
            med = float(np.nanmedian(np.abs(raw))) if raw.size else 0.0
            scale = _choose_scale(med, candidates=(1e5, 1e6, 1e7, 1e8, 1e9, 1e10), expected_range=(1e-6, 1e6))
            df[col] = (raw / scale).astype(float)

    if "volume" in df.columns:
        # MID bars frequently carry no volume; keep numeric.
        rawv = _decode_fixed8_le_int64_series(df["volume"])
        df["volume"] = np.nan_to_num(rawv, nan=0.0).astype(float)

    return df



def _is_fixed8_binary_series(s: pd.Series) -> bool:
    if s.dtype != object:
        return False
    for v in s[:50].tolist():
        if v is None:
            continue
        if isinstance(v, float) and np.isnan(v):
            continue
        try:
            b = bytes(v)
        except Exception:
            continue
        if len(b) == 8:
            return True
    return False


def _decode_fixed8_le_int64(s: pd.Series) -> np.ndarray:
    arr = s.to_numpy()
    mask = pd.isna(s).to_numpy()
    out = np.empty(len(arr), dtype=np.float64)
    out[:] = np.nan

    if (~mask).sum() == 0:
        return out

    buf = b"".join(bytes(x) for x in arr[~mask])
    ints = np.frombuffer(buf, dtype="<i8")
    out[~mask] = ints.astype(np.float64)
    return out


def _decode_fixed8_to_float(
    s: pd.Series,
    *,
    scale_candidates: Tuple[float, ...],
    expected_range: Tuple[float, float],
) -> pd.Series:
    if not _is_fixed8_binary_series(s):
        return pd.to_numeric(s, errors="coerce").astype(float)

    raw = _decode_fixed8_le_int64(s)
    raw_nz = raw[~np.isnan(raw)]
    if raw_nz.size == 0:
        return pd.Series(raw, index=s.index, name=s.name)

    med = float(np.nanmedian(np.abs(raw_nz)))
    if med == 0.0:
        scaled = raw
    else:
        lo, hi = expected_range
        scale = scale_candidates[-1]
        for sc in scale_candidates:
            v = med / sc
            if lo <= v <= hi:
                scale = sc
                break
        scaled = raw / scale

    return pd.Series(scaled, index=s.index, name=s.name)


def _coerce_bar_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Nautilus parquet stores prices/sizes as fixed_size_binary[8] (int64 little-endian).
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = _decode_fixed8_to_float(
                df[col],
                scale_candidates=(1e5, 1e6, 1e7, 1e8, 1e9, 1e10),
                expected_range=(1e-6, 1e6),
            )

    if "volume" in df.columns:
        # Often 0 for MID bars, but decode if present.
        df["volume"] = (
            _decode_fixed8_to_float(
                df["volume"],
                scale_candidates=(1.0, 1e1, 1e2, 1e3, 1e6, 1e9),
                expected_range=(0.0, 1e12),
            )
            .fillna(0.0)
            .astype(float)
        )

    return df

def _utc_date(value: str) -> datetime:
    # YYYY-MM-DD -> UTC midnight
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt


def _instrument_to_dataset_prefix(instrument: str) -> str:
    # "EUR/USD.IDEALPRO" -> "EURUSD.IDEALPRO"
    s = str(instrument).strip()
    if "." in s:
        sym, venue = s.split(".", 1)
    else:
        sym, venue = s, "IDEALPRO"

    sym = sym.replace("/", "").replace("-", "")
    return f"{sym}.{venue}"


def _find_dataset_dir(root: Path, prefix: str, spec_suffix: str) -> Path:
    # Example suffix: "5-MINUTE-MID-EXTERNAL"
    exact = root / f"{prefix}-{spec_suffix}"
    if exact.exists():
        return exact

    # Fallback: find directory containing both prefix and the bar spec parts
    candidates = [p for p in root.glob(f"{prefix}-*{spec_suffix}*") if p.is_dir()]
    if len(candidates) == 1:
        return candidates[0]

    raise FileNotFoundError(f"Could not locate dataset dir under {root} for {prefix}-{spec_suffix}")


def _read_parquet_dataset(dataset_dir: Path, start: datetime, end_exclusive: datetime) -> pd.DataFrame:
    files = sorted(dataset_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files in {dataset_dir}")

    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end_exclusive.timestamp() * 1_000_000_000)

    frames = []
    for f in files:
        df = pd.read_parquet(f)
        if "ts_event" not in df.columns:
            raise ValueError(f"Missing ts_event in {f}")

        df = df[(df["ts_event"] >= start_ns) & (df["ts_event"] < end_ns)]
        if df.empty:
            continue

        # Normalize expected columns
        keep = [c for c in ["ts_event", "open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[keep].copy()
        df = _coerce_bar_numeric_columns(df)
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["ts_event", "open", "high", "low", "close", "volume"])

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("ts_event").drop_duplicates(subset=["ts_event"], keep="last")
    out["ts"] = pd.to_datetime(out["ts_event"].astype(np.int64), unit="ns", utc=True)
    return out


def _compute_master_predictions(df15: pd.DataFrame, model_path: Path) -> pd.DataFrame:
    """Compute master (15m) predictions using the retrained RandomForest model features.
    
    Matches features in retrain_model.py.
    """
    import joblib

    if df15.empty:
        return pd.DataFrame(columns=["ts_master_15m_close", "last_15m_prediction", "atr_15m"])

    df = df15[["ts", "open", "high", "low", "close", "volume"]].copy()
    df = df.set_index("ts").sort_index()
    
    # Ensure numeric
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # --- MTF Feature Calculation (10 features matching V2 strategy) ---
    import pandas_ta as ta
    
    close = df["close"]
    high = df["high"]
    low = df["low"]
    
    # === 15m Features ===
    # 1. Log Returns
    df['log_ret'] = np.log(close / close.shift(1)) * 100
    
    # 2. MAMA Diff
    hl2 = (high + low) / 2.0
    mama = ta.mama(hl2, fastlimit=0.5, slowlimit=0.05)
    if mama is not None and getattr(mama, "shape", (0, 0))[1] >= 2:
        df['mama_diff'] = (mama.iloc[:, 0] - mama.iloc[:, 1]) / close
    else:
        df['mama_diff'] = 0.0
        
    # 8. ATR (15m)
    df['atr'] = ta.atr(high, low, close, length=14)
    df['atr_norm'] = df['atr'] / close
    
    # 9. Hour & 10. Day of Week
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    # === 30m Features ===
    df30 = df.resample("30min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    
    # 3. DMP & 4. DMN (30m)
    adx = ta.adx(df30["high"], df30["low"], df30["close"], length=14)
    dmp = adx["DMP_14"] if adx is not None and "DMP_14" in adx.columns else pd.Series(0.0, index=df30.index)
    dmn = adx["DMN_14"] if adx is not None and "DMN_14" in adx.columns else pd.Series(0.0, index=df30.index)
    
    # 5. Stoch K & 6. Stoch D (30m)
    stoch = ta.stoch(df30["high"], df30["low"], df30["close"], k=14, d=3, smooth_k=3)
    if stoch is not None and getattr(stoch, "shape", (0, 0))[1] >= 2:
        stoch_k = stoch.iloc[:, 0]
        stoch_d = stoch.iloc[:, 1]
    else:
        stoch_k = pd.Series(50.0, index=df30.index)
        stoch_d = pd.Series(50.0, index=df30.index)
        
    # 7. WMA Diff (30m)
    wma_fast = ta.wma(df30["close"], length=9)
    wma_slow = ta.wma(df30["close"], length=23)
    if wma_fast is not None and wma_slow is not None:
        wma_diff = (wma_fast - wma_slow) / df30["close"]
    else:
        wma_diff = pd.Series(0.0, index=df30.index)
        
    # Create 30m DataFrame for merging
    df30_ind = pd.DataFrame({
        "ts": df30.index,
        "dmp_30m": dmp.values,
        "dmn_30m": dmn.values,
        "stoch_k_30m": stoch_k.values,
        "stoch_d_30m": stoch_d.values,
        "wma_diff_30m": wma_diff.values,
    }).sort_values("ts")
    
    # Prepare 15m DataFrame for merging
    df15_base = pd.DataFrame({
        "ts": df.index,
        "log_ret": df['log_ret'].values,
        "mama_diff": df['mama_diff'].values,
        "atr": df['atr'].values,
        "atr_norm": df['atr_norm'].values,
        "hour": df['hour'].values,
        "day_of_week": df['day_of_week'].values,
    }).sort_values("ts")
    
    # Merge 30m features onto 15m bars (backward fill)
    dfm = pd.merge_asof(df15_base, df30_ind, on="ts", direction="backward")
    dfm = dfm.set_index("ts")
    
    # Define feature columns (MUST match training order - 10 features)
    feature_cols = [
        "log_ret",
        "mama_diff",
        "dmp_30m",
        "dmn_30m",
        "stoch_k_30m",
        "stoch_d_30m",
        "wma_diff_30m",
        "atr_norm",
        "hour",
        "day_of_week",
    ]
    
    # Drop NaNs
    dfm = dfm.dropna(subset=feature_cols + ["atr"])

    if dfm.empty:
        return pd.DataFrame(columns=["ts_master_15m_close", "last_15m_prediction", "atr_15m"])

    model = joblib.load(model_path)
    X = dfm[feature_cols].astype(float).to_numpy()

    pred = model.predict(X)
    try:
        proba = model.predict_proba(X)
        conf = np.max(proba, axis=1)
    except Exception:
        # Fallback if predict_proba not available
        conf = np.ones(len(pred), dtype=float) * 0.5

    conf_signed = np.where(pred == 1, conf, -conf)

    out = pd.DataFrame({
        "ts_master_15m_close": dfm.index,
        "last_15m_prediction": conf_signed.astype(float),
        "atr_15m": dfm["atr"].astype(float).values,
    })
    out = out.sort_values("ts_master_15m_close")
    return out


def _compute_soldier_features(df5: pd.DataFrame) -> pd.DataFrame:
    from live.hmtf_features import make_default_soldier_indicators, candle_body_wicks

    ind = make_default_soldier_indicators()

    rsi_list = []
    macd_list = []
    macd_sig_list = []
    macd_hist_list = []
    bbw_list = []
    body_list = []
    uw_list = []
    lw_list = []

    for o, h, l, c in zip(df5["open"].astype(float), df5["high"].astype(float), df5["low"].astype(float), df5["close"].astype(float)):
        rsi = ind.rsi.update(c)
        macd, macd_sig, macd_hist = ind.macd.update(c)
        bbw = ind.bb_width.update(c)
        body, uw, lw = candle_body_wicks(o, h, l, c)

        rsi_list.append(float(rsi))
        macd_list.append(float(macd))
        macd_sig_list.append(float(macd_sig))
        macd_hist_list.append(float(macd_hist))
        bbw_list.append(float(bbw))
        body_list.append(float(body))
        uw_list.append(float(uw))
        lw_list.append(float(lw))

    out = df5.copy()
    out["rsi_5m"] = rsi_list
    out["macd_5m"] = macd_list
    out["macd_signal_5m"] = macd_sig_list
    out["macd_hist_5m"] = macd_hist_list
    out["bb_width_5m"] = bbw_list
    out["body_5m"] = body_list
    out["upper_wick_5m"] = uw_list
    out["lower_wick_5m"] = lw_list
    return out


def _label_tp_before_sl(
    high: np.ndarray,
    low: np.ndarray,
    entry: np.ndarray,
    atr15: np.ndarray,
    direction: np.ndarray,
    tp_mult: float,
    sl_mult: float,
    max_lookahead: int,
) -> np.ndarray:
    """Compute label per row: 1 if TP hit before SL, else 0; NaN if unknown."""
    n = len(entry)
    y = np.full(n, np.nan, dtype=float)

    for i in range(n):
        atr = atr15[i]
        if not np.isfinite(atr) or atr <= 0:
            continue

        d = direction[i]
        if d == 0 or not np.isfinite(d):
            continue

        e = entry[i]
        if not np.isfinite(e):
            continue

        if d > 0:
            tp = e + tp_mult * atr
            sl = e - sl_mult * atr
            tp_hit = lambda hh, ll: hh >= tp
            sl_hit = lambda hh, ll: ll <= sl
        else:
            tp = e - tp_mult * atr
            sl = e + sl_mult * atr
            tp_hit = lambda hh, ll: ll <= tp
            sl_hit = lambda hh, ll: hh >= sl

        end = min(n - 1, i + max_lookahead)
        j = i + 1
        while j <= end:
            hh = high[j]
            ll = low[j]
            if tp_hit(hh, ll):
                y[i] = 1.0
                break
            if sl_hit(hh, ll):
                y[i] = 0.0
                break
            j += 1

    return y


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--instrument", default=os.getenv("MTF3_INSTRUMENT", "EUR/USD.IDEALPRO"))
    p.add_argument("--start", default="2024-01-01")
    # End is exclusive; default to Dec 1 of this year to cover "through November"
    p.add_argument("--end_exclusive", default="2025-12-01")
    p.add_argument("--out", default=os.getenv("MTF3_DATASET_PATH", "logs/live_mtf/hmtf_5m_dataset.csv"))
    p.add_argument("--model_path", default=os.getenv("MTF2_MODEL_PATH", os.getenv("MTF3_MASTER_MODEL_PATH", "models/ml_model_mtf.pkl")))
    p.add_argument("--tp_atr_mult", type=float, default=float(os.getenv("MTF3_TP_ATR_MULT", "0.6")))
    p.add_argument("--sl_atr_mult", type=float, default=float(os.getenv("MTF3_SL_ATR_MULT", "1.4")))
    p.add_argument("--max_lookahead_5m_bars", type=int, default=288)
    args = p.parse_args()

    start = _utc_date(args.start)
    end_excl = _utc_date(args.end_exclusive)

    project_root = Path(__file__).resolve().parent.parent
    bar_root = project_root / "data" / "historical" / "data" / "bar"

    prefix = _instrument_to_dataset_prefix(args.instrument)

    ds5 = _find_dataset_dir(bar_root, prefix, "5-MINUTE-MID-EXTERNAL")
    ds15 = _find_dataset_dir(bar_root, prefix, "15-MINUTE-MID-EXTERNAL")

    print(f"Reading 5m from: {ds5}")
    df5 = _read_parquet_dataset(ds5, start, end_excl)
    print(f"5m rows: {len(df5)}")

    print(f"Reading 15m from: {ds15}")
    df15 = _read_parquet_dataset(ds15, start, end_excl)
    print(f"15m rows: {len(df15)}")

    if df5.empty or df15.empty:
        raise SystemExit("Insufficient data: df5 or df15 empty for the requested range")

    model_path = (project_root / args.model_path) if not Path(args.model_path).is_absolute() else Path(args.model_path)
    if not model_path.exists():
        raise SystemExit(f"Master model not found: {model_path}")

    print(f"Computing master predictions using model: {model_path}")
    master = _compute_master_predictions(df15, model_path=model_path)
    print(f"Master signal rows: {len(master)}")

    if master.empty:
        raise SystemExit("Master predictions are empty (warmup/feature calc failure)")

    # Soldier features
    df5_feat = _compute_soldier_features(df5)

    # Stitch lagged master onto 5m
    df5s = df5_feat.sort_values("ts")
    master_s = master.sort_values("ts_master_15m_close")

    # Ensure merge keys have identical dtype (tz-aware UTC) for merge_asof.
    df5s["ts"] = pd.to_datetime(df5s["ts"], utc=True)
    master_s["ts_master_15m_close"] = pd.to_datetime(master_s["ts_master_15m_close"], utc=True)

    stitched = pd.merge_asof(
        df5s,
        master_s,
        left_on="ts",
        right_on="ts_master_15m_close",
        direction="backward",
    )

    stitched = stitched.dropna(subset=["ts_master_15m_close", "last_15m_prediction", "atr_15m"])

    # Direction derived from signed master confidence
    stitched["direction"] = np.where(stitched["last_15m_prediction"].astype(float) >= 0.0, 1.0, -1.0)

    # Labeling
    print(f"Labeling with max_lookahead={args.max_lookahead_5m_bars} (5m bars)")
    y = _label_tp_before_sl(
        high=stitched["high"].to_numpy(dtype=float),
        low=stitched["low"].to_numpy(dtype=float),
        entry=stitched["close"].to_numpy(dtype=float),
        atr15=stitched["atr_15m"].to_numpy(dtype=float),
        direction=stitched["direction"].to_numpy(dtype=float),
        tp_mult=args.tp_atr_mult,
        sl_mult=args.sl_atr_mult,
        max_lookahead=args.max_lookahead_5m_bars,
    )
    stitched["y"] = y
    stitched = stitched.dropna(subset=["y"]).copy()

    stitched["sample_weight"] = stitched["last_15m_prediction"].abs().astype(float)

    # Output columns
    out_cols = [
        "ts",
        "ts_master_15m_close",
        "last_15m_prediction",
        "atr_15m",
        "direction",
        "y",
        "sample_weight",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "rsi_5m",
        "macd_5m",
        "macd_signal_5m",
        "macd_hist_5m",
        "bb_width_5m",
        "body_5m",
        "upper_wick_5m",
        "lower_wick_5m",
    ]

    stitched_out = stitched[out_cols].copy()
    stitched_out = stitched_out.rename(columns={
        "ts": "ts_5m_close",
    })

    out_path = project_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stitched_out.to_csv(out_path, index=False)

    print(f"Wrote stitched dataset: {out_path} rows={len(stitched_out)}")
    print(f"Label distribution: {stitched_out['y'].value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

