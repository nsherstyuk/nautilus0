"""
audit_crypto_multi.py — ETH + SOL Signal Audit (Daily + 1h)

Same pipeline as BTC audit. Tests trend-following + ML on ETH-USD and SOL-USD.
Data from yfinance (free, no API key).

Usage:
  .venv\\Scripts\\python.exe trading_system_v4\\scripts\\audit_crypto_multi.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "trading_system_v4" / "data"

# -- Parameters ----------------------------------------------------------------
TAKER_FEE   = 0.006       # 0.6% round-trip Coinbase fee
SPREAD_PCT  = 0.0005      # 0.05% spread
TOTAL_COST  = TAKER_FEE + SPREAD_PCT

ANNUAL_DAYS = 365
ANNUAL_HRS  = 365 * 24

TP_ATR = 1.5
SL_ATR = 1.4
BE_WR  = SL_ATR / (SL_ATR + TP_ATR)

LOOKAHEAD_D = 20
PURGE_GAP_D = 25
LOOKAHEAD_H = 72
PURGE_GAP_H = 168

SYMBOLS = [
    ("ETH-USD", "ETH"),
    ("SOL-USD", "SOL"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=period-1, adjust=False).mean()
    return 100 - 100 / (1 + g / (l + 1e-10))

def _atr_s(h, l, c, period):
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period-1, adjust=False).mean()

def _atr14_np(h, l, c):
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = h[0]-l[0]
    return pd.Series(tr).ewm(com=13, adjust=False).mean().to_numpy()

def _adx(h, l, c, period=14):
    up = h - h.shift(1); down = l.shift(1) - l
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
    return ((eq - eq.cummax()) / eq.cummax()).min()


def _stats(ret, label, af=365, verbose=True):
    eq = (1+ret).cumprod()
    sh = _sharpe(ret, af)
    ar = ret.mean()*af*100
    dd = _max_dd(eq)*100
    vol = ret.std()*np.sqrt(af)*100
    cal = ar/abs(dd) if dd!=0 else 0
    wr = (ret>0).mean()*100
    ny = len(ret)/af
    s = dict(label=label, sharpe=sh, ann_ret=ar, max_dd=dd,
             vol=vol, calmar=cal, win_rate=wr)
    if verbose:
        print(f"\n  {label}")
        print(f"    Sharpe: {sh:+.3f}  Ann:{ar:+.1f}%  Vol:{vol:.1f}%  DD:{dd:.1f}%  "
              f"Calmar:{cal:.3f}  WR:{wr:.1f}%  TotRet:{(eq.iloc[-1]-1)*100:+.1f}% ({ny:.1f}yr)")
    return s


# ── Features ──────────────────────────────────────────────────────────────────

def build_features(df, prefix=""):
    eps = 1e-10
    c = df['close'].astype(float)
    o = df['open'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    br = (h-l).clip(lower=eps)
    vol = df['volume'].astype(float) if 'volume' in df.columns else pd.Series(0, index=df.index)

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

    if vol.sum()>0:
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

    if hasattr(df.index,'hour') and df.index.hour.nunique()>1:
        f['hsin'] = np.sin(2*math.pi*df.index.hour/24)
        f['hcos'] = np.cos(2*math.pi*df.index.hour/24)

    print(f"  {prefix}Features: {len(f.columns)}")
    return f


# ── Labeling ──────────────────────────────────────────────────────────────────

def label_tpsl(df, lookahead, spread_pct):
    h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    atr = _atr14_np(h,l,c); N = len(df)
    yl = np.full(N, np.nan); ys = np.full(N, np.nan)
    for i in range(N-lookahead):
        a = atr[i]
        if not np.isfinite(a) or a<=0: continue
        sp = c[i]*spread_pct
        hp = h[i+1:i+1+lookahead]; lp = l[i+1:i+1+lookahead]
        # Long
        el = c[i]+sp; tl = el+a*TP_ATR; sl = el-a*SL_ATR
        isl = np.where(lp<=sl)[0]; itp = np.where(hp>=tl)[0]
        isl = isl[0] if len(isl) else lookahead; itp = itp[0] if len(itp) else lookahead
        yl[i] = 1. if itp<isl and itp<lookahead else 0.
        # Short
        es = c[i]-sp; ts = es-a*TP_ATR; ss = es+a*SL_ATR
        isl = np.where(hp>=ss)[0]; itp = np.where(lp<=ts)[0]
        isl = isl[0] if len(isl) else lookahead; itp = itp[0] if len(itp) else lookahead
        ys[i] = 1. if itp<isl and itp<lookahead else 0.
    return yl, ys


# ── Purged CV ─────────────────────────────────────────────────────────────────

def purged_cv(X, y, gap, label, fcols):
    n = len(X); fs = n//5; results = []
    for fold in range(4):
        te = fs*(fold+1); ts = te+gap; tend = ts+fs
        if tend>n: break
        Xtr,ytr = X[:te],y[:te]; Xte,yte = X[ts:tend],y[ts:tend]
        vtr=np.isfinite(ytr); vte=np.isfinite(yte)
        Xtr,ytr = Xtr[vtr],ytr[vtr]; Xte,yte = Xte[vte],yte[vte]
        if len(Xtr)<100 or len(Xte)<30: continue
        sw = (ytr==0).sum()/((ytr==1).sum()+1e-10)
        m = XGBClassifier(max_depth=4, learning_rate=0.05, n_estimators=300,
                          subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
                          eval_metric="logloss", verbosity=0, random_state=42,
                          scale_pos_weight=sw)
        m.fit(Xtr,ytr)
        p = m.predict_proba(Xte)[:,1]
        auc = roc_auc_score(yte,p)
        br = yte.mean()
        wr = []
        for thr in [0.50,0.55,0.60]:
            mk = p>=thr
            if mk.sum()>10:
                wr.append(f"≥{thr:.2f}:{yte[mk].mean()*100:.1f}%({mk.sum()})")
        results.append(dict(fold=fold+1, auc=auc, br=br, model=m, wr=wr))
        print(f"    Fold {fold+1}: AUC={auc:.4f}  BR={br*100:.1f}%  "
              f"train={len(ytr):,}  test={len(yte):,}")
        if wr: print(f"      WR: {' | '.join(wr)}")
    if results:
        avg = np.mean([r['auc'] for r in results])
        print(f"    → {label} AVG AUC: {avg:.4f}  ({(avg-0.5)*100:+.1f}pp)")
        # Top features
        imp = results[-1]['model'].feature_importances_
        top = np.argsort(imp)[::-1][:8]
        print(f"    TOP FEATURES: {', '.join(fcols[i] for i in top if i<len(fcols))}")
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  Pull data
# ══════════════════════════════════════════════════════════════════════════════

def pull_data(yf_symbol, short_name):
    cache_d = DATA_DIR / f"{short_name.lower()}_usd_daily.parquet"
    cache_h = DATA_DIR / f"{short_name.lower()}_usd_1h.parquet"

    # Daily
    if cache_d.exists():
        df_d = pd.read_parquet(cache_d)
        df_d.index = pd.to_datetime(df_d.index, utc=True)
        print(f"  {short_name} Daily: cache ({len(df_d):,} bars)")
    else:
        print(f"  Fetching {short_name} daily...")
        raw = yf.download(yf_symbol, start="2015-01-01", interval="1d", progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df_d = raw[["Open","High","Low","Close","Volume"]].copy()
        df_d.columns = ["open","high","low","close","volume"]
        df_d.index = pd.to_datetime(df_d.index, utc=True)
        df_d = df_d.dropna(subset=["close"])
        df_d.to_parquet(cache_d)
        print(f"  {short_name} Daily: {len(df_d):,} bars cached")

    print(f"  Range: {df_d.index.min().date()} → {df_d.index.max().date()}")
    print(f"  Price: ${df_d['close'].min():,.2f} → ${df_d['close'].max():,.2f}")
    bnh = df_d['close'].iloc[-1]/df_d['close'].iloc[0]-1
    ny = len(df_d)/365
    print(f"  B&H: {bnh*100:+,.0f}% ({((1+bnh)**(1/ny)-1)*100:+.1f}%/yr, {ny:.1f}yr)")

    # Hourly
    if cache_h.exists():
        df_h = pd.read_parquet(cache_h)
        df_h.index = pd.to_datetime(df_h.index, utc=True)
        print(f"  {short_name} 1h: cache ({len(df_h):,} bars)")
    else:
        print(f"  Fetching {short_name} 1h...")
        raw = yf.download(yf_symbol, period="730d", interval="1h", progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df_h = raw[["Open","High","Low","Close","Volume"]].copy()
        df_h.columns = ["open","high","low","close","volume"]
        df_h.index = pd.to_datetime(df_h.index, utc=True)
        df_h = df_h.dropna(subset=["close"])
        df_h.to_parquet(cache_h)
        print(f"  {short_name} 1h: {len(df_h):,} bars cached")

    print(f"  1h range: {df_h.index.min().date()} → {df_h.index.max().date()}, {len(df_h):,} bars")
    return df_d, df_h


# ══════════════════════════════════════════════════════════════════════════════
#  Analyze one asset
# ══════════════════════════════════════════════════════════════════════════════

def analyze_asset(df_d, df_h, name):
    print("\n" + "=" * 70)
    print(f"  {name}/USD — DAILY TREND-FOLLOWING")
    print("=" * 70)

    c = df_d['close']; h = df_d['high']; l = df_d['low']
    cost = TOTAL_COST
    all_d = {}

    # Buy & Hold
    bnh = c.pct_change().dropna()
    all_d["B&H"] = _stats(bnh, "Buy & Hold", ANNUAL_DAYS)

    # EMA 50/200 L/S
    e50=_ema(c,50); e200=_ema(c,200)
    sig = pd.Series(np.where(e50>e200,1.,-1.), index=c.index)
    pos = sig.shift(1).fillna(0)
    chg = (pos!=pos.shift(1)).astype(float)
    ret = c.pct_change()*pos - chg*cost
    all_d["EMA50/200"] = _stats(ret.dropna(), "EMA 50/200 L/S", ANNUAL_DAYS)

    # EMA 50/200 Long-Only
    pos_lo = pd.Series(np.where(e50>e200,1.,0.), index=c.index).shift(1).fillna(0)
    chg_lo = (pos_lo!=pos_lo.shift(1)).astype(float)
    ret_lo = c.pct_change()*pos_lo - chg_lo*cost
    all_d["EMA50/200 LO"] = _stats(ret_lo.dropna(), "EMA 50/200 Long-Only", ANNUAL_DAYS)

    # EMA 20/50
    e20=_ema(c,20)
    sig2 = pd.Series(np.where(e20>e50,1.,-1.), index=c.index)
    pos2 = sig2.shift(1).fillna(0)
    chg2 = (pos2!=pos2.shift(1)).astype(float)
    ret2 = c.pct_change()*pos2 - chg2*cost
    all_d["EMA20/50"] = _stats(ret2.dropna(), "EMA 20/50 L/S", ANNUAL_DAYS)

    # Donchian 20
    dh = h.rolling(20).max().shift(1); dl = l.rolling(20).min().shift(1)
    ds = pd.Series(0., index=c.index)
    ds[c>dh]=1.; ds[c<dl]=-1.
    ds = ds.replace(0,np.nan).ffill().fillna(0)
    dp = ds.shift(1).fillna(0)
    dc = (dp!=dp.shift(1)).astype(float)
    dr = c.pct_change()*dp - dc*cost
    all_d["Donch20"] = _stats(dr.dropna(), "Donchian 20", ANNUAL_DAYS)

    # Mom 60
    m60 = c.pct_change(60)
    ms = pd.Series(np.where(m60>0,1.,-1.), index=c.index)
    mp = ms.shift(1).fillna(0)
    mc = (mp!=mp.shift(1)).astype(float)
    mr = c.pct_change()*mp - mc*cost
    all_d["Mom60"] = _stats(mr.dropna(), "Momentum 60d", ANNUAL_DAYS)

    # RSI MR
    rsi = _rsi(c,14)
    rs = pd.Series(0., index=c.index)
    rs[rsi<30]=1.; rs[rsi>70]=-1.
    rs = rs.replace(0,np.nan).ffill().fillna(0)
    rp = rs.shift(1).fillna(0)
    rc = (rp!=rp.shift(1)).astype(float)
    rr = c.pct_change()*rp - rc*cost
    all_d["RSI MR"] = _stats(rr.dropna(), "RSI Mean-Rev", ANNUAL_DAYS)

    # Summary
    print(f"\n  DAILY SUMMARY ({name}):")
    print(f"  {'Strategy':<22s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s}")
    print("  " + "-" * 48)
    for k in ["B&H","EMA50/200","EMA50/200 LO","EMA20/50","Donch20","Mom60","RSI MR"]:
        s = all_d[k]
        print(f"  {s['label'][:22]:<22s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% {s['max_dd']:>7.1f}%")

    # Yearly OOS
    years = sorted(df_d.index.year.unique())
    print(f"\n  YEARLY (EMA 50/200 L/S):")
    print(f"  {'Yr':>6s} {'Ret':>8s} {'Sharpe':>8s}")
    print("  " + "-" * 25)
    oos_s = []
    for yr in years:
        mk = df_d.index.year==yr
        yr_r = ret[mk].dropna()
        if len(yr_r)<30: continue
        s = _sharpe(yr_r, ANNUAL_DAYS)
        ar = yr_r.mean()*ANNUAL_DAYS*100
        oos_s.append(s)
        print(f"  {yr:>6d} {ar:>+7.1f}% {s:>+7.3f}  {'✓' if ar>0 else '✗'}")
    win = sum(1 for s in oos_s if s>0)
    print(f"  Win: {win}/{len(oos_s)} ({win/len(oos_s)*100:.0f}%)")

    # Daily ML
    print(f"\n  {name} DAILY ML:")
    feat = build_features(df_d, f"{name} D ")
    fc = np.array(feat.columns.tolist())
    yl, ys = label_tpsl(df_d, LOOKAHEAD_D, SPREAD_PCT)
    valid = np.isfinite(yl)
    print(f"  Labeled: {valid.sum():,}  Long BR: {yl[valid].mean()*100:.1f}%  "
          f"Short BR: {ys[valid].mean()*100:.1f}%  (BE={BE_WR*100:.1f}%)")
    X = np.nan_to_num(feat.values.astype(np.float32))
    w = 200; Xw = X[w:]; ylw = yl[w:]; ysw = ys[w:]
    print(f"  --- LONG ---")
    rdl = purged_cv(Xw, ylw, PURGE_GAP_D, f"{name} D-LONG", fc)
    print(f"  --- SHORT ---")
    rds = purged_cv(Xw, ysw, PURGE_GAP_D, f"{name} D-SHORT", fc)

    # ── Hourly ────────────────────────────────────────────────────────────
    print(f"\n" + "=" * 70)
    print(f"  {name}/USD — 1H TREND-FOLLOWING")
    print("=" * 70)

    ch = df_h['close']; hh = df_h['high']; lh = df_h['low']
    all_h = {}

    bnh_h = ch.pct_change().dropna()
    all_h["B&H"] = _stats(bnh_h, "Buy & Hold 1h", ANNUAL_HRS)

    e24=_ema(ch,24); e72=_ema(ch,72)
    sig_h = pd.Series(np.where(e24>e72,1.,-1.), index=ch.index)
    pos_h = sig_h.shift(1).fillna(0)
    chg_h = (pos_h!=pos_h.shift(1)).astype(float)
    ret_h = ch.pct_change()*pos_h - chg_h*cost
    all_h["EMA24/72"] = _stats(ret_h.dropna(), "EMA 24/72h L/S", ANNUAL_HRS)

    pos_hlo = pd.Series(np.where(e24>e72,1.,0.), index=ch.index).shift(1).fillna(0)
    chg_hlo = (pos_hlo!=pos_hlo.shift(1)).astype(float)
    ret_hlo = ch.pct_change()*pos_hlo - chg_hlo*cost
    all_h["EMA24/72 LO"] = _stats(ret_hlo.dropna(), "EMA 24/72h LO", ANNUAL_HRS)

    # Donchian 48h
    dh48 = hh.rolling(48).max().shift(1); dl48 = lh.rolling(48).min().shift(1)
    ds48 = pd.Series(0., index=ch.index)
    ds48[ch>dh48]=1.; ds48[ch<dl48]=-1.
    ds48 = ds48.replace(0,np.nan).ffill().fillna(0)
    dp48 = ds48.shift(1).fillna(0)
    dc48 = (dp48!=dp48.shift(1)).astype(float)
    dr48 = ch.pct_change()*dp48 - dc48*cost
    all_h["Donch48h"] = _stats(dr48.dropna(), "Donchian 48h", ANNUAL_HRS)

    # RSI MR 1h
    rsi_h = _rsi(ch,14)
    mrs = pd.Series(0., index=ch.index)
    mrs[rsi_h<25]=1.; mrs[rsi_h>75]=-1.
    mrs = mrs.replace(0,np.nan).ffill().fillna(0)
    mrp = mrs.shift(1).fillna(0)
    mrc = (mrp!=mrp.shift(1)).astype(float)
    mrr = ch.pct_change()*mrp - mrc*cost
    all_h["RSI MR 1h"] = _stats(mrr.dropna(), "RSI MR 25/75 1h", ANNUAL_HRS)

    print(f"\n  1H SUMMARY ({name}):")
    print(f"  {'Strategy':<22s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s}")
    print("  " + "-" * 48)
    for k in ["B&H","EMA24/72","EMA24/72 LO","Donch48h","RSI MR 1h"]:
        s = all_h[k]
        print(f"  {s['label'][:22]:<22s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% {s['max_dd']:>7.1f}%")

    # 1h ML
    print(f"\n  {name} 1H ML:")
    feat_h = build_features(df_h, f"{name} 1h ")
    fc_h = np.array(feat_h.columns.tolist())
    ylh, ysh = label_tpsl(df_h, LOOKAHEAD_H, SPREAD_PCT)
    valid_h = np.isfinite(ylh)
    print(f"  Labeled: {valid_h.sum():,}  Long BR: {ylh[valid_h].mean()*100:.1f}%  "
          f"Short BR: {ysh[valid_h].mean()*100:.1f}%")
    Xh = np.nan_to_num(feat_h.values.astype(np.float32))
    Xhw = Xh[w:]; ylhw = ylh[w:]; yshw = ysh[w:]
    print(f"  --- LONG ---")
    rhl = purged_cv(Xhw, ylhw, PURGE_GAP_H, f"{name} 1H-L", fc_h)
    print(f"  --- SHORT ---")
    rhs = purged_cv(Xhw, yshw, PURGE_GAP_H, f"{name} 1H-S", fc_h)

    return all_d, all_h, rdl, rds, rhl, rhs


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    all_results = {}

    for yf_sym, short in SYMBOLS:
        print("\n" + "█" * 70)
        print(f"  ASSET: {short}/USD")
        print("█" * 70)
        df_d, df_h = pull_data(yf_sym, short)
        res = analyze_asset(df_d, df_h, short)
        all_results[short] = res

    # ── Cross-asset comparison ────────────────────────────────────────────
    print("\n" + "█" * 70)
    print("  CROSS-ASSET COMPARISON: ETH vs SOL vs BTC")
    print("█" * 70)

    # Load BTC cache if available
    btc_cache = DATA_DIR / "btc_usd_daily.parquet"
    btc_stats = None
    if btc_cache.exists():
        df_btc = pd.read_parquet(btc_cache)
        df_btc.index = pd.to_datetime(df_btc.index, utc=True)
        c_btc = df_btc['close']
        e50_b = _ema(c_btc,50); e200_b = _ema(c_btc,200)
        sig_b = pd.Series(np.where(e50_b>e200_b,1.,-1.), index=c_btc.index)
        pos_b = sig_b.shift(1).fillna(0)
        chg_b = (pos_b!=pos_b.shift(1)).astype(float)
        ret_b = c_btc.pct_change()*pos_b - chg_b*TOTAL_COST
        btc_stats = _stats(ret_b.dropna(), "BTC EMA50/200", ANNUAL_DAYS, verbose=False)
        bnh_b = _stats(c_btc.pct_change().dropna(), "BTC B&H", ANNUAL_DAYS, verbose=False)

    print(f"\n  {'Asset':<8s} {'Strategy':<22s} {'Sharpe':>7s} {'AnnRet':>8s} {'MaxDD':>8s}")
    print("  " + "-" * 55)

    if btc_stats:
        print(f"  {'BTC':<8s} {'Buy & Hold':<22s} {bnh_b['sharpe']:>+7.3f} {bnh_b['ann_ret']:>+7.1f}% {bnh_b['max_dd']:>7.1f}%")
        print(f"  {'BTC':<8s} {'EMA 50/200 L/S':<22s} {btc_stats['sharpe']:>+7.3f} {btc_stats['ann_ret']:>+7.1f}% {btc_stats['max_dd']:>7.1f}%")

    for short in ["ETH", "SOL"]:
        if short in all_results:
            daily = all_results[short][0]
            for k in ["B&H", "EMA50/200", "EMA50/200 LO"]:
                if k in daily:
                    s = daily[k]
                    print(f"  {short:<8s} {s['label'][:22]:<22s} {s['sharpe']:>+7.3f} {s['ann_ret']:>+7.1f}% {s['max_dd']:>7.1f}%")

    # ML comparison
    print(f"\n  ML AUC COMPARISON:")
    print(f"  {'Asset':<8s} {'TF':<6s} {'LONG':>7s} {'SHORT':>7s}")
    print("  " + "-" * 30)
    for short in ["ETH", "SOL"]:
        if short in all_results:
            _, _, rdl, rds, rhl, rhs = all_results[short]
            dl_auc = np.mean([r['auc'] for r in rdl]) if rdl else 0
            ds_auc = np.mean([r['auc'] for r in rds]) if rds else 0
            hl_auc = np.mean([r['auc'] for r in rhl]) if rhl else 0
            hs_auc = np.mean([r['auc'] for r in rhs]) if rhs else 0
            print(f"  {short:<8s} {'Daily':<6s} {dl_auc:>7.4f} {ds_auc:>7.4f}")
            print(f"  {short:<8s} {'1h':<6s} {hl_auc:>7.4f} {hs_auc:>7.4f}")

    # Verdict
    print(f"\n  {'─' * 60}")
    for short in ["ETH", "SOL"]:
        if short in all_results:
            daily = all_results[short][0]
            best_k = max([k for k in daily if k!="B&H"], key=lambda k: daily[k]['sharpe'])
            best = daily[best_k]
            _, _, rdl, rds, rhl, rhs = all_results[short]
            ml_best = 0
            for r in [rdl, rds, rhl, rhs]:
                if r:
                    ml_best = max(ml_best, np.mean([x['auc'] for x in r]))

            if best['sharpe'] > 0.5 or ml_best > 0.54:
                v = "✅ EDGE"
            elif best['sharpe'] > 0.2 or ml_best > 0.52:
                v = "⚠️  MARGINAL"
            else:
                v = "❌ NO EDGE"
            print(f"  {short}: {v}  (best strat: {best['label']}, Sharpe {best['sharpe']:+.3f}, ML best AUC {ml_best:.4f})")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.0f}s ({elapsed/60:.1f}m)")


if __name__ == "__main__":
    main()
