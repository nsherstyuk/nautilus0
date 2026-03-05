import yfinance as yf
import numpy as np
import warnings; warnings.filterwarnings("ignore")

COINS = ["BTC", "ETH", "SOL"]
LOOKBACK   = 40
ENTRY_PCT  = 0.70
VOL_TARGET = 0.40
VOL_WINDOW = 20

tickers = [f"{c}-USD" for c in COINS]
raw = yf.download(tickers, period="60d", interval="1d", progress=False)["Close"]
raw.columns = [c.replace("-USD", "") for c in raw.columns]

today = raw.index[-1].date()

print()
print("=" * 60)
print(f"  CRYPTO DAILY SIGNALS  —  {today}")
print(f"  Strategy: 40d / 70th percentile  |  Vol-target: 40%")
print("=" * 60)

for coin in COINS:
    price = raw[coin].dropna()
    current = float(price.iloc[-1])
    last40  = price.iloc[-LOOKBACK:]
    lvl     = float(last40.quantile(ENTRY_PCT))
    signal  = "LONG" if current > lvl else "FLAT"
    is_long = signal == "LONG"

    rv     = float(price.pct_change().rolling(VOL_WINDOW).std().iloc[-1]) * np.sqrt(365)
    weight = min(VOL_TARGET / rv, 1.0) if rv > 0.01 else 0.0
    deploy = weight if is_long else 0.0

    print()
    print(f"  ── {coin} " + "─" * (52 - len(coin)))
    if is_long:
        print(f"  SIGNAL:  *** LONG ***   deploy {deploy:.0%} of {coin} allocation")
    else:
        gap_pct = (lvl - current) / current
        print(f"  SIGNAL:  FLAT   (need +{gap_pct:.1%} to trigger)")

    print(f"  Price:   ${current:>10,.2f}   Entry level: ${lvl:>10,.2f}")
    print(f"  Vol:     {rv:.0%}/yr            Weight: 40% / {rv:.0%} = {weight:.0%}")

    # Last 7 days
    print()
    print(f"  {'Date':12s}  {'Price':>12s}  {'Entry Level':>12s}  {'Signal':>6s}")
    print(f"  {'─'*12}  {'─'*12}  {'─'*12}  {'─'*6}")
    for dt in price.index[-7:]:
        p   = float(price.loc[dt])
        win = price.loc[:dt].iloc[-LOOKBACK:]
        l   = float(win.quantile(ENTRY_PCT))
        s   = "LONG" if p > l else "FLAT"
        marker = " ◄" if dt == price.index[-1] else ""
        print(f"  {str(dt.date()):12s}  ${p:>11,.2f}  ${l:>11,.2f}  {s:>6s}{marker}")

print()
print("=" * 60)

# ── Portfolio summary ─────────────────────────────────────────────────────
print()
print("  PORTFOLIO SUMMARY  (equal weight, $10,000 total capital)")
print(f"  {'─'*56}")
alloc = 10_000 / len(COINS)
total_deployed = 0.0
for coin in COINS:
    price   = raw[coin].dropna()
    current = float(price.iloc[-1])
    last40  = price.iloc[-LOOKBACK:]
    lvl     = float(last40.quantile(ENTRY_PCT))
    signal  = "LONG" if current > lvl else "FLAT"
    rv      = float(price.pct_change().rolling(VOL_WINDOW).std().iloc[-1]) * np.sqrt(365)
    weight  = min(VOL_TARGET / rv, 1.0) if rv > 0.01 else 0.0
    dollars = alloc * weight if signal == "LONG" else 0.0
    units   = dollars / current if current > 0 else 0.0
    total_deployed += dollars
    action  = f"BUY {units:.6f} {coin}  (${dollars:,.0f})" if signal == "LONG" else "stay cash"
    print(f"  {coin:>4s}  {signal:>4s}  →  {action}")

print(f"  {'─'*56}")
print(f"  Total deployed: ${total_deployed:,.0f} / $10,000  ({total_deployed/10000:.0%})")
print(f"  Cash:           ${10000 - total_deployed:,.0f}")
print()
