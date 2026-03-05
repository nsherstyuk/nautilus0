"""
audit_eth_ml_deep.py — Deep-dive into ETH/USD ML signal

Prior finding: ETH daily ML showed AUC 0.5473 LONG, 0.5575 SHORT (+4.7/+5.7pp).
This is the strongest ML signal found across all assets/timeframes.

This script:
  A. Walk-forward expanding-window backtest (train on all prior data, predict next quarter)
  B. ML-filtered trend strategy (only trade when ML agrees with trend)
  C. Probability threshold analysis (trade only at high-confidence predictions)
  D. Feature stability analysis (do the same features matter across time?)
  E. Actual PnL simulation with position sizing & realistic fees
  F. Robustness checks: random seed stability, subsample stability
  G. Verdict: is this a real edge or overfitting?

Usage:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\audit_eth_ml_deep.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

# Parameters
TAKER_FEE  = 0.006      # 0.6% round-trip
SPREAD_PCT = 0.0005
TOTAL_COST = TAKER_FEE + SPREAD_PCT

TP_ATR = 1.5
SL_ATR = 1.4
BE_WR  = SL_ATR / (SL_ATR + TP_ATR)   # 48.3%

ANNUAL = 365
INITIAL_CAPITAL = 10_000  # $10k starting capital

# Walk-forward: train expanding, test on 90-day windows
WF_TEST_DAYS = 90
WF_MIN_TRAIN = 365       # at least 1 year of training data
PURGE_GAP    = 25


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    lo = (-d).clip(lower=0).ewm(com=period-1, adjust=False).mean()
    return 100 - 100/(1 + g/(lo+1e-10))

def _atr_s(h, l, c, period):
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period-1, adjust=False).mean()

def _atr14_np(h, l, c):
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = h[0]-l[0]
    return pd.Series(tr).ewm(com=13, adjust=False).mean().to_numpy()

def _adx(h, l, c, period=14):
    up = h-h.shift(1); down = l.shift(1)-l
    pdm = pd.Series(np.where((up>down)&(up>0), up, 0.), index=h.index)
    mdm = pd.Series(np.where((down>up)&(down>0), down, 0.), index=h.index)
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    aw = tr.ewm(com=period-1, adjust=False).mean()
    pdi = 100*pdm.ewm(com=period-1, adjust=False).mean()/(aw+1e-10)
    mdi = 100*mdm.ewm(com=period-1, adjust=False).mean()/(aw+1e-10)
    dx = 100*(pdi-mdi).abs()/(pdi+mdi+1e-10)
    return dx.ewm(com=period-1, adjust=False).mean()/100

def _sharpe(r, af=365):
    return r.mean()/(r.std()+1e-10)*np.sqrt(af)

def _max_dd(eq):
    return ((eq - eq.cummax())/ eq.cummax()).min()


# ── Features (same as audit_crypto_multi) ─────────────────────────────────────

def build_features(df):
    eps = 1e-10
    c = df['close'].astype(float)
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    br = (h-l).clip(lower=eps)
    vol = df['volume'].astype(float)

    f = pd.DataFrame(index=df.index)
    f['body']  = (c-o)/br
    f['uwk']   = (h-np.maximum(o,c))/br
    f['lwk']   = (np.minimum(o,c)-l)/br

    for n in [1,2,3,5,10,20,40,60]:
        f[f'r{n}'] = c.pct_change(n, fill_method=None)

    a5 = _atr_s(h,l,c,5); a14 = _atr_s(h,l,c,14)
    f['atr_r'] = a5/(a14+eps)
    f['atr_n'] = a14/(c+eps)
    f['v5']    = c.pct_change().rolling(5).std()
    f['v20']   = c.pct_change().rolling(20).std()
    f['v_r']   = f['v5']/(f['v20']+eps)

    e10=_ema(c,10); e20=_ema(c,20); e50=_ema(c,50); e200=_ema(c,200)
    f['ce10']  = c/(e10+eps)-1
    f['ce20']  = c/(e20+eps)-1
    f['ce50']  = c/(e50+eps)-1
    f['ce200'] = c/(e200+eps)-1
    f['e10_20']= e10/(e20+eps)-1
    f['e20_50']= e20/(e50+eps)-1
    f['e50_200']= e50/(e200+eps)-1

    f['rsi']   = _rsi(c,14)/100-0.5
    f['adx']   = _adx(h,l,c,14)

    h20=h.rolling(20).max(); l20=l.rolling(20).min()
    h60=h.rolling(60).max(); l60=l.rolling(60).min()
    f['dc20']  = (c-l20)/(h20-l20+eps)
    f['dc60']  = (c-l60)/(h60-l60+eps)
    f['vreg']  = a14/(a14.rolling(50).mean()+eps)

    vm = vol.rolling(20).mean()
    f['vol_r20'] = vol/(vm+eps)
    f['pv_c10']  = c.pct_change().rolling(10).corr(vol.pct_change())

    bull = (c>c.shift(1)); bear = (c<c.shift(1))
    bg = (~bull).cumsum(); rg = (~bear).cumsum()
    f['cup']  = bull.astype(int).groupby(bg).cumsum().clip(upper=10)/10
    f['cdn']  = bear.astype(int).groupby(rg).cumsum().clip(upper=10)/10
    f['d2hi'] = (h20-c)/(a14+eps)
    f['d2lo'] = (c-l20)/(a14+eps)

    dow = df.index.dayofweek
    f['dsin'] = np.sin(2*math.pi*dow/7)
    f['dcos'] = np.cos(2*math.pi*dow/7)

    return f


# ── Labeling ──────────────────────────────────────────────────────────────────

def label_tpsl(df, lookahead=20):
    h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    atr = _atr14_np(h,l,c); N = len(df)
    yl = np.full(N, np.nan); ys = np.full(N, np.nan)
    for i in range(N-lookahead):
        a = atr[i]
        if not np.isfinite(a) or a<=0: continue
        sp = c[i]*SPREAD_PCT
        hp = h[i+1:i+1+lookahead]; lp = l[i+1:i+1+lookahead]
        el = c[i]+sp; tl = el+a*TP_ATR; sl = el-a*SL_ATR
        isl = np.where(lp<=sl)[0]; itp = np.where(hp>=tl)[0]
        isl = isl[0] if len(isl) else lookahead; itp = itp[0] if len(itp) else lookahead
        yl[i] = 1. if itp<isl and itp<lookahead else 0.
        es = c[i]-sp; ts = es-a*TP_ATR; ss = es+a*SL_ATR
        isl = np.where(hp>=ss)[0]; itp = np.where(lp<=ts)[0]
        isl = isl[0] if len(isl) else lookahead; itp = itp[0] if len(itp) else lookahead
        ys[i] = 1. if itp<isl and itp<lookahead else 0.
    return yl, ys


def _train_model(X_tr, y_tr, seed=42):
    pos = (y_tr==1).sum(); neg = (y_tr==0).sum()
    sw = neg/(pos+1e-10)
    m = XGBClassifier(max_depth=4, learning_rate=0.05, n_estimators=300,
                      subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
                      eval_metric="logloss", verbosity=0, random_state=seed,
                      scale_pos_weight=sw)
    m.fit(X_tr, y_tr)
    return m


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION A: Walk-Forward Expanding Window
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward(df, feat, y_long, y_short, feature_cols):
    print("\n" + "=" * 70)
    print("  SECTION A: WALK-FORWARD EXPANDING WINDOW (90-day OOS)")
    print("=" * 70)

    X = np.nan_to_num(feat.values.astype(np.float32))
    N = len(df)
    dates = df.index

    # Build windows
    windows = []
    warmup = max(200, WF_MIN_TRAIN)
    cursor = warmup
    while cursor + PURGE_GAP + WF_TEST_DAYS <= N:
        train_end = cursor
        test_start = cursor + PURGE_GAP
        test_end = min(test_start + WF_TEST_DAYS, N)
        windows.append((train_end, test_start, test_end))
        cursor = test_end  # non-overlapping test windows

    print(f"  Windows: {len(windows)} x {WF_TEST_DAYS}-day OOS, purge={PURGE_GAP}")

    # Collect OOS predictions
    oos_long_prob  = np.full(N, np.nan)
    oos_short_prob = np.full(N, np.nan)
    oos_long_auc   = []
    oos_short_auc  = []

    print(f"\n  {'Window':<8s} {'Train':>6s} {'Test':>5s} {'Period':<25s} "
          f"{'L-AUC':>6s} {'S-AUC':>6s} {'L-BR':>5s} {'S-BR':>5s}")
    print("  " + "-" * 72)

    for i, (te, ts, tend) in enumerate(windows):
        X_tr_l = X[:te]; y_tr_l = y_long[:te]
        X_tr_s = X[:te]; y_tr_s = y_short[:te]
        X_te = X[ts:tend]
        y_te_l = y_long[ts:tend]; y_te_s = y_short[ts:tend]

        vtr_l = np.isfinite(y_tr_l); vtr_s = np.isfinite(y_tr_s)
        vte_l = np.isfinite(y_te_l); vte_s = np.isfinite(y_te_s)

        # Long model
        auc_l = np.nan
        if vtr_l.sum() > 100 and vte_l.sum() > 10:
            m_l = _train_model(X_tr_l[vtr_l], y_tr_l[vtr_l])
            prob_l = m_l.predict_proba(X_te)[:,1]
            oos_long_prob[ts:tend] = prob_l
            if y_te_l[vte_l].std() > 0:
                auc_l = roc_auc_score(y_te_l[vte_l], prob_l[vte_l])
                oos_long_auc.append(auc_l)

        # Short model
        auc_s = np.nan
        if vtr_s.sum() > 100 and vte_s.sum() > 10:
            m_s = _train_model(X_tr_s[vtr_s], y_tr_s[vtr_s])
            prob_s = m_s.predict_proba(X_te)[:,1]
            oos_short_prob[ts:tend] = prob_s
            if y_te_s[vte_s].std() > 0:
                auc_s = roc_auc_score(y_te_s[vte_s], prob_s[vte_s])
                oos_short_auc.append(auc_s)

        period = f"{dates[ts].date()} → {dates[tend-1].date()}"
        br_l = y_te_l[vte_l].mean()*100 if vte_l.sum()>0 else 0
        br_s = y_te_s[vte_s].mean()*100 if vte_s.sum()>0 else 0
        print(f"  {i+1:<8d} {te:>6d} {tend-ts:>5d} {period:<25s} "
              f"{auc_l:>6.3f} {auc_s:>6.3f} {br_l:>4.1f}% {br_s:>4.1f}%")

    # Summary
    avg_l = np.nanmean(oos_long_auc) if oos_long_auc else 0
    avg_s = np.nanmean(oos_short_auc) if oos_short_auc else 0
    wins_l = sum(1 for a in oos_long_auc if a > 0.5)
    wins_s = sum(1 for a in oos_short_auc if a > 0.5)

    print(f"\n  WALK-FORWARD SUMMARY:")
    print(f"    LONG:  Avg AUC={avg_l:.4f} ({(avg_l-0.5)*100:+.1f}pp)  "
          f"Win windows: {wins_l}/{len(oos_long_auc)}")
    print(f"    SHORT: Avg AUC={avg_s:.4f} ({(avg_s-0.5)*100:+.1f}pp)  "
          f"Win windows: {wins_s}/{len(oos_short_auc)}")

    return oos_long_prob, oos_short_prob, oos_long_auc, oos_short_auc


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION B: ML-Filtered Trend Strategy
# ══════════════════════════════════════════════════════════════════════════════

def ml_filtered_trend(df, oos_long_prob, oos_short_prob):
    print("\n" + "=" * 70)
    print("  SECTION B: ML-FILTERED TREND STRATEGY")
    print("=" * 70)

    c = df['close']
    e20 = _ema(c, 20); e50 = _ema(c, 50)

    # Base trend signal
    trend_sig = pd.Series(np.where(e20 > e50, 1.0, -1.0), index=c.index)
    trend_pos = trend_sig.shift(1).fillna(0)

    daily_ret = c.pct_change()

    # Strategy 1: Trend only (EMA 20/50 best from prior test)
    chg = (trend_pos != trend_pos.shift(1)).astype(float)
    trend_ret = daily_ret * trend_pos - chg * TOTAL_COST
    trend_ret = trend_ret.dropna()

    print(f"\n  1. Trend Only (EMA 20/50 L/S):")
    sh = _sharpe(trend_ret)
    eq = (1+trend_ret).cumprod()
    dd = _max_dd(eq)*100
    ar = trend_ret.mean()*ANNUAL*100
    print(f"     Sharpe={sh:+.3f}  Ann={ar:+.1f}%  DD={dd:.1f}%")

    # Strategy 2: ML-filtered trend (only trade when ML agrees)
    for thr_name, long_thr, short_thr in [
        ("ML p>0.50", 0.50, 0.50),
        ("ML p>0.52", 0.52, 0.52),
        ("ML p>0.55", 0.55, 0.55),
        ("ML p>0.58", 0.58, 0.58),
        ("ML p>0.60", 0.60, 0.60),
    ]:
        # Position: trend direction, but only if ML probability exceeds threshold
        ml_long  = pd.Series(oos_long_prob, index=df.index)
        ml_short = pd.Series(oos_short_prob, index=df.index)

        ml_pos = pd.Series(0.0, index=df.index)
        # Go long when trend is up AND ML long prob > threshold
        long_ok  = (trend_sig > 0) & (ml_long.shift(1) >= long_thr)
        short_ok = (trend_sig < 0) & (ml_short.shift(1) >= short_thr)
        ml_pos[long_ok]  = 1.0
        ml_pos[short_ok] = -1.0
        ml_pos = ml_pos.shift(1).fillna(0)

        chg_ml = (ml_pos != ml_pos.shift(1)).astype(float)
        ml_ret = daily_ret * ml_pos - chg_ml * TOTAL_COST
        ml_ret = ml_ret.dropna()

        # Only count periods where we have OOS predictions
        has_pred = np.isfinite(oos_long_prob) | np.isfinite(oos_short_prob)
        ml_ret_oos = ml_ret[has_pred[:-1] if len(has_pred)>len(ml_ret) else has_pred[:len(ml_ret)]]

        if len(ml_ret_oos) < 30:
            print(f"\n  {thr_name}: too few OOS periods")
            continue

        sh_ml = _sharpe(ml_ret_oos)
        eq_ml = (1+ml_ret_oos).cumprod()
        dd_ml = _max_dd(eq_ml)*100
        ar_ml = ml_ret_oos.mean()*ANNUAL*100
        n_trades = chg_ml[has_pred[:len(chg_ml)]].sum()
        exposure = (ml_pos[has_pred[:len(ml_pos)]] != 0).mean()*100

        print(f"\n  {thr_name}:")
        print(f"     Sharpe={sh_ml:+.3f}  Ann={ar_ml:+.1f}%  DD={dd_ml:.1f}%  "
              f"Trades={n_trades:.0f}  Exposure={exposure:.0f}%")

    # Strategy 3: Pure ML signal (no trend filter)
    print(f"\n  --- PURE ML (no trend filter) ---")
    for thr in [0.50, 0.52, 0.55, 0.58, 0.60]:
        ml_long  = pd.Series(oos_long_prob, index=df.index).shift(1)
        ml_short = pd.Series(oos_short_prob, index=df.index).shift(1)

        pure_pos = pd.Series(0.0, index=df.index)
        # Net ML signal: go long if long_prob > thr and long > short, else short
        long_sig  = ml_long >= thr
        short_sig = ml_short >= thr

        # If both or neither qualify, stay flat
        pure_pos[long_sig & ~short_sig] = 1.0
        pure_pos[short_sig & ~long_sig] = -1.0
        # If both qualify, pick stronger
        both = long_sig & short_sig
        pure_pos[both & (ml_long > ml_short)] = 1.0
        pure_pos[both & (ml_short >= ml_long)] = -1.0

        chg_p = (pure_pos != pure_pos.shift(1)).astype(float)
        pure_ret = daily_ret * pure_pos - chg_p * TOTAL_COST
        pure_ret = pure_ret.dropna()

        has_pred_ = np.isfinite(oos_long_prob)
        pure_oos = pure_ret[has_pred_[:len(pure_ret)]]
        if len(pure_oos) < 30:
            continue

        sh_p = _sharpe(pure_oos)
        ar_p = pure_oos.mean()*ANNUAL*100
        eq_p = (1+pure_oos).cumprod()
        dd_p = _max_dd(eq_p)*100
        exp_p = (pure_pos[has_pred_[:len(pure_pos)]] != 0).mean()*100

        print(f"     p≥{thr:.2f}: Sharpe={sh_p:+.3f}  Ann={ar_p:+.1f}%  DD={dd_p:.1f}%  Exp={exp_p:.0f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION C: Probability Threshold Analysis
# ══════════════════════════════════════════════════════════════════════════════

def threshold_analysis(df, oos_long_prob, oos_short_prob, y_long, y_short):
    print("\n" + "=" * 70)
    print("  SECTION C: PROBABILITY THRESHOLD → WIN RATE")
    print("=" * 70)

    has_pred = np.isfinite(oos_long_prob) & np.isfinite(y_long)

    print(f"\n  LONG predictions:")
    print(f"  {'Threshold':>10s} {'Count':>7s} {'WinRate':>8s} {'vs BE':>8s} {'Verdict':>8s}")
    print("  " + "-" * 45)

    for thr in [0.40, 0.45, 0.50, 0.52, 0.55, 0.58, 0.60, 0.65, 0.70]:
        mask = has_pred & (oos_long_prob >= thr)
        n = mask.sum()
        if n < 10:
            continue
        wr = y_long[mask].mean() * 100
        vs_be = wr - BE_WR * 100
        verdict = "✅" if vs_be > 2 else "⚠️ " if vs_be > 0 else "❌"
        print(f"  {thr:>10.2f} {n:>7d} {wr:>7.1f}% {vs_be:>+7.1f}pp {verdict:>8s}")

    has_pred_s = np.isfinite(oos_short_prob) & np.isfinite(y_short)

    print(f"\n  SHORT predictions:")
    print(f"  {'Threshold':>10s} {'Count':>7s} {'WinRate':>8s} {'vs BE':>8s} {'Verdict':>8s}")
    print("  " + "-" * 45)

    for thr in [0.40, 0.45, 0.50, 0.52, 0.55, 0.58, 0.60, 0.65, 0.70]:
        mask = has_pred_s & (oos_short_prob >= thr)
        n = mask.sum()
        if n < 10:
            continue
        wr = y_short[mask].mean() * 100
        vs_be = wr - BE_WR * 100
        verdict = "✅" if vs_be > 2 else "⚠️ " if vs_be > 0 else "❌"
        print(f"  {thr:>10.2f} {n:>7d} {wr:>7.1f}% {vs_be:>+7.1f}pp {verdict:>8s}")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION D: Feature Stability
# ══════════════════════════════════════════════════════════════════════════════

def feature_stability(df, feat, y_long, y_short, feature_cols):
    print("\n" + "=" * 70)
    print("  SECTION D: FEATURE STABILITY ACROSS TIME")
    print("=" * 70)

    X = np.nan_to_num(feat.values.astype(np.float32))
    N = len(df)

    # Train models on different time periods and compare top features
    periods = [
        ("First half",  0, N//2),
        ("Second half",  N//2, N),
        ("2019-2021", None, None),
        ("2022-2024", None, None),
    ]

    # Build index-based periods
    real_periods = []
    real_periods.append(("First half", 0, N//2))
    real_periods.append(("Second half", N//2, N))

    for yr_range, yr_start, yr_end in [("2019-2021", 2019, 2021), ("2022-2024", 2022, 2024)]:
        mask = (df.index.year >= yr_start) & (df.index.year <= yr_end)
        idx = np.where(mask)[0]
        if len(idx) > 100:
            real_periods.append((yr_range, idx[0], idx[-1]+1))

    print(f"\n  LONG model — Top 10 features by period:")
    for pname, start, end in real_periods:
        Xp = X[start:end]; yp = y_long[start:end]
        v = np.isfinite(yp)
        if v.sum() < 100:
            continue
        m = _train_model(Xp[v], yp[v])
        imp = m.feature_importances_
        top = np.argsort(imp)[::-1][:10]
        top_names = [feature_cols[i] for i in top]
        print(f"    {pname:>12s}: {', '.join(top_names[:6])}")

    print(f"\n  SHORT model — Top 10 features by period:")
    for pname, start, end in real_periods:
        Xp = X[start:end]; yp = y_short[start:end]
        v = np.isfinite(yp)
        if v.sum() < 100:
            continue
        m = _train_model(Xp[v], yp[v])
        imp = m.feature_importances_
        top = np.argsort(imp)[::-1][:10]
        top_names = [feature_cols[i] for i in top]
        print(f"    {pname:>12s}: {', '.join(top_names[:6])}")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION E: PnL Simulation
# ══════════════════════════════════════════════════════════════════════════════

def pnl_simulation(df, oos_long_prob, oos_short_prob):
    print("\n" + "=" * 70)
    print("  SECTION E: PnL SIMULATION ($10k starting capital)")
    print("=" * 70)

    c = df['close']
    daily_ret = c.pct_change()
    e20 = _ema(c, 20); e50 = _ema(c, 50)
    trend = pd.Series(np.where(e20 > e50, 1.0, -1.0), index=c.index)

    ml_long  = pd.Series(oos_long_prob, index=df.index).shift(1)
    ml_short = pd.Series(oos_short_prob, index=df.index).shift(1)

    has_pred = np.isfinite(oos_long_prob)
    oos_dates = df.index[has_pred]
    if len(oos_dates) == 0:
        print("  No OOS predictions available")
        return

    print(f"  OOS period: {oos_dates[0].date()} → {oos_dates[-1].date()} ({len(oos_dates)} days)")

    # Test several allocation strategies
    strategies = [
        ("Trend only (EMA20/50)", "trend"),
        ("ML-filtered trend (p>0.52)", "ml_trend_52"),
        ("ML-filtered trend (p>0.55)", "ml_trend_55"),
        ("Pure ML (p>0.55)", "pure_55"),
        ("Buy & Hold", "bnh"),
    ]

    print(f"\n  {'Strategy':<35s} {'FinalVal':>9s} {'Return':>8s} {'Sharpe':>7s} "
          f"{'MaxDD':>7s} {'Trades':>7s}")
    print("  " + "-" * 75)

    for strat_name, strat_type in strategies:
        pos = pd.Series(0.0, index=df.index)

        if strat_type == "bnh":
            pos[:] = 1.0
        elif strat_type == "trend":
            pos = trend.shift(1).fillna(0)
        elif strat_type.startswith("ml_trend"):
            thr = float(strat_type.split("_")[-1]) / 100
            long_ok  = (trend > 0) & (ml_long >= thr)
            short_ok = (trend < 0) & (ml_short >= thr)
            pos[long_ok]  = 1.0
            pos[short_ok] = -1.0
            pos = pos.shift(1).fillna(0)
        elif strat_type.startswith("pure"):
            thr = float(strat_type.split("_")[-1]) / 100
            long_sig  = ml_long >= thr
            short_sig = ml_short >= thr
            pos[long_sig & ~short_sig] = 1.0
            pos[short_sig & ~long_sig] = -1.0
            both = long_sig & short_sig
            pos[both & (ml_long > ml_short)] = 1.0
            pos[both & (ml_short >= ml_long)] = -1.0

        chg = (pos != pos.shift(1)).astype(float)
        strat_ret = daily_ret * pos - chg * TOTAL_COST

        # Only OOS period
        oos_ret = strat_ret[has_pred[:len(strat_ret)]]
        oos_ret = oos_ret.dropna()
        if len(oos_ret) < 10:
            continue

        eq = INITIAL_CAPITAL * (1 + oos_ret).cumprod()
        final = eq.iloc[-1]
        total_ret = (final / INITIAL_CAPITAL - 1) * 100
        sh = _sharpe(oos_ret)
        dd = _max_dd(eq) * 100
        trades = chg[has_pred[:len(chg)]].sum()

        print(f"  {strat_name:<35s} ${final:>8,.0f} {total_ret:>+7.1f}% {sh:>+6.3f} "
              f"{dd:>6.1f}% {trades:>7.0f}")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION F: Robustness Checks
# ══════════════════════════════════════════════════════════════════════════════

def robustness_checks(df, feat, y_long, y_short):
    print("\n" + "=" * 70)
    print("  SECTION F: ROBUSTNESS CHECKS")
    print("=" * 70)

    X = np.nan_to_num(feat.values.astype(np.float32))
    N = len(X)
    fold_size = N // 5

    # 1. Random seed stability
    print(f"\n  1. RANDOM SEED STABILITY (last fold, 5 seeds):")
    train_end = fold_size * 3
    test_start = train_end + PURGE_GAP
    test_end = test_start + fold_size
    if test_end <= N:
        X_tr = X[:train_end]; y_tr_l = y_long[:train_end]; y_tr_s = y_short[:train_end]
        X_te = X[test_start:test_end]
        y_te_l = y_long[test_start:test_end]; y_te_s = y_short[test_start:test_end]

        vtr_l = np.isfinite(y_tr_l); vte_l = np.isfinite(y_te_l)
        vtr_s = np.isfinite(y_tr_s); vte_s = np.isfinite(y_te_s)

        print(f"     {'Seed':>6s} {'L-AUC':>7s} {'S-AUC':>7s}")
        seed_l = []; seed_s = []
        for seed in [42, 123, 456, 789, 2026]:
            auc_l = auc_s = np.nan
            if vtr_l.sum()>100 and vte_l.sum()>10:
                m = _train_model(X_tr[vtr_l], y_tr_l[vtr_l], seed=seed)
                p = m.predict_proba(X_te)[:,1]
                auc_l = roc_auc_score(y_te_l[vte_l], p[vte_l])
                seed_l.append(auc_l)
            if vtr_s.sum()>100 and vte_s.sum()>10:
                m = _train_model(X_tr[vtr_s], y_tr_s[vtr_s], seed=seed)
                p = m.predict_proba(X_te)[:,1]
                auc_s = roc_auc_score(y_te_s[vte_s], p[vte_s])
                seed_s.append(auc_s)
            print(f"     {seed:>6d} {auc_l:>7.4f} {auc_s:>7.4f}")

        if seed_l:
            print(f"     L range: {min(seed_l):.4f} → {max(seed_l):.4f} (spread={max(seed_l)-min(seed_l):.4f})")
        if seed_s:
            print(f"     S range: {min(seed_s):.4f} → {max(seed_s):.4f} (spread={max(seed_s)-min(seed_s):.4f})")

    # 2. Shuffled label baseline (how much AUC do random labels get?)
    print(f"\n  2. SHUFFLED LABEL BASELINE (permutation test, 5 trials):")
    if test_end <= N:
        shuf_l = []; shuf_s = []
        for trial in range(5):
            rng = np.random.RandomState(trial)
            y_shuf_l = y_tr_l.copy(); y_shuf_l[vtr_l] = rng.permutation(y_shuf_l[vtr_l])
            y_shuf_s = y_tr_s.copy(); y_shuf_s[vtr_s] = rng.permutation(y_shuf_s[vtr_s])

            if vtr_l.sum()>100 and vte_l.sum()>10:
                m = _train_model(X_tr[vtr_l], y_shuf_l[vtr_l])
                p = m.predict_proba(X_te)[:,1]
                a = roc_auc_score(y_te_l[vte_l], p[vte_l])
                shuf_l.append(a)
            if vtr_s.sum()>100 and vte_s.sum()>10:
                m = _train_model(X_tr[vtr_s], y_shuf_s[vtr_s])
                p = m.predict_proba(X_te)[:,1]
                a = roc_auc_score(y_te_s[vte_s], p[vte_s])
                shuf_s.append(a)

        if shuf_l:
            print(f"     Shuffled LONG  AUC: {np.mean(shuf_l):.4f} ± {np.std(shuf_l):.4f}")
        if shuf_s:
            print(f"     Shuffled SHORT AUC: {np.mean(shuf_s):.4f} ± {np.std(shuf_s):.4f}")
        if seed_l and shuf_l:
            real_l = np.mean(seed_l)
            print(f"     Real LONG AUC {real_l:.4f} vs shuffled {np.mean(shuf_l):.4f}  "
                  f"→ {'GENUINE SIGNAL' if real_l > np.mean(shuf_l)+2*np.std(shuf_l) else 'NOT SIGNIFICANT'}")
        if seed_s and shuf_s:
            real_s = np.mean(seed_s)
            print(f"     Real SHORT AUC {real_s:.4f} vs shuffled {np.mean(shuf_s):.4f}  "
                  f"→ {'GENUINE SIGNAL' if real_s > np.mean(shuf_s)+2*np.std(shuf_s) else 'NOT SIGNIFICANT'}")


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION G: Verdict
# ══════════════════════════════════════════════════════════════════════════════

def print_verdict(oos_long_auc, oos_short_auc):
    print("\n" + "=" * 70)
    print("  SECTION G: FINAL VERDICT — ETH/USD ML DEEP DIVE")
    print("=" * 70)

    avg_l = np.nanmean(oos_long_auc) if oos_long_auc else 0
    avg_s = np.nanmean(oos_short_auc) if oos_short_auc else 0
    wins_l = sum(1 for a in oos_long_auc if a > 0.5)
    wins_s = sum(1 for a in oos_short_auc if a > 0.5)
    total_w = len(oos_long_auc)

    print(f"\n  Walk-Forward OOS (90-day windows):")
    print(f"    LONG:  Avg AUC={avg_l:.4f} ({(avg_l-0.5)*100:+.1f}pp)  Win={wins_l}/{total_w}")
    print(f"    SHORT: Avg AUC={avg_s:.4f} ({(avg_s-0.5)*100:+.1f}pp)  Win={wins_s}/{len(oos_short_auc)}")

    # Assessment
    print(f"\n  {'─' * 60}")
    if avg_l > 0.53 and avg_s > 0.53 and wins_l/total_w > 0.6:
        print(f"  VERDICT: ✅ GENUINE ML EDGE ON ETH/USD")
        print(f"  Both directions show consistent OOS predictive power.")
        print(f"  Recommended: ML-filtered trend on daily timeframe.")
    elif avg_l > 0.52 or avg_s > 0.52:
        print(f"  VERDICT: ⚠️  WEAK/UNSTABLE ML SIGNAL ON ETH/USD")
        print(f"  Some predictive power but inconsistent across windows.")
        print(f"  May work as a secondary filter, not a standalone signal.")
    else:
        print(f"  VERDICT: ❌ ML EDGE DOES NOT SURVIVE WALK-FORWARD")
        print(f"  Prior CV results were likely overfitted.")
        print(f"  The AUC 0.55 from purged CV did not hold in true OOS.")

    # Comparison to prior results
    print(f"\n  COMPARISON TO PRIOR AUDITS:")
    print(f"    EURUSD 15m:    AUC ~0.50 (zero)")
    print(f"    XAUUSD 15m:    AUC 0.526 (noise)")
    print(f"    XAUUSD 1h:     AUC 0.509 (zero)")
    print(f"    XAUUSD daily:  AUC 0.479 (below random)")
    print(f"    BTC daily:     AUC 0.523 (marginal)")
    print(f"    ETH daily:     AUC {max(avg_l, avg_s):.3f} (THIS TEST)")
    print(f"    SOL daily:     AUC 0.507 (noise)")

    print("=" * 70)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    # Load cached ETH data
    cache = DATA_DIR / "eth_usd_daily.parquet"
    if not cache.exists():
        print("ERROR: Run audit_crypto_multi.py first to download ETH data")
        return

    df = pd.read_parquet(cache)
    df.index = pd.to_datetime(df.index, utc=True)
    print(f"ETH/USD daily: {len(df):,} bars  {df.index.min().date()} → {df.index.max().date()}")
    print(f"Price: ${df['close'].min():,.2f} → ${df['close'].max():,.2f}")

    feat = build_features(df)
    feature_cols = feat.columns.tolist()
    y_long, y_short = label_tpsl(df, lookahead=20)

    valid = np.isfinite(y_long)
    print(f"Labeled: {valid.sum():,}  Long BR: {y_long[valid].mean()*100:.1f}%  "
          f"Short BR: {y_short[valid].mean()*100:.1f}%")

    # Run all sections
    oos_lp, oos_sp, oos_la, oos_sa = walk_forward(df, feat, y_long, y_short, feature_cols)
    ml_filtered_trend(df, oos_lp, oos_sp)
    threshold_analysis(df, oos_lp, oos_sp, y_long, y_short)
    feature_stability(df, feat, y_long, y_short, feature_cols)
    pnl_simulation(df, oos_lp, oos_sp)
    robustness_checks(df, feat, y_long, y_short)
    print_verdict(oos_la, oos_sa)

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.0f}s ({elapsed/60:.1f}m)")


if __name__ == "__main__":
    main()
