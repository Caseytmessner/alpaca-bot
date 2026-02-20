import time
import schedule
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

# —————————————————————

# CONFIG

# —————————————————————

import os
API_KEY = os.environ.get("ALPACA_API_KEY")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")

PAPER = True  # Set to False for live trading

SYMBOLS = [“BTC/USD”, “ETH/USD”]
RISK_PER_TRADE = 0.05       # 5% of account per trade
LOSS_FLOOR_PCT = 0.10       # Stop + close all if down 10% on the day
PROFIT_CEILING_PCT = 0.25   # Stop + close all if up 25% on the day
FAST_EMA = 9
SLOW_EMA = 21
RSI_PERIOD = 14
RSI_BUY_MIN = 40
RSI_BUY_MAX = 65
RSI_SELL = 70

# —————————————————————

# CLIENTS

# —————————————————————

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
data_client = CryptoHistoricalDataClient()

# —————————————————————

# STATE

# —————————————————————

starting_equity = None
halted = False

# —————————————————————

# ACCOUNT HELPERS

# —————————————————————

def get_equity():
return float(trading_client.get_account().equity)

def close_all_positions_and_orders():
“”“Cancel all open orders, then close every open position.”””
print(”  Cancelling all open orders…”)
trading_client.cancel_orders()

```
print("  Closing all open positions...")
positions = trading_client.get_all_positions()
if not positions:
    print("  No open positions to close.")
    return
for position in positions:
    try:
        trading_client.close_position(position.symbol)
        print(f"  ✓ Closed position: {position.symbol} ({position.qty} units)")
    except Exception as e:
        print(f"  ✗ Could not close {position.symbol}: {e}")
```

# —————————————————————

# THRESHOLD CHECKS

# —————————————————————

def check_thresholds():
“””
Check whether the daily loss floor or profit ceiling has been hit.
If either is triggered, close all positions/orders and halt for the day.
Returns True if halted, False otherwise.
“””
global halted

```
equity = get_equity()
pct_change = (equity - starting_equity) / starting_equity * 100

print(f"  Equity: ${equity:.2f} ({pct_change:+.2f}% today)")

if equity <= starting_equity * (1 - LOSS_FLOOR_PCT):
    print(f"\n⛔ LOSS FLOOR HIT — down {LOSS_FLOOR_PCT*100:.0f}%")
    print(f"   Closing all positions and halting for the day...")
    close_all_positions_and_orders()
    halted = True

elif equity >= starting_equity * (1 + PROFIT_CEILING_PCT):
    print(f"\n🏆 PROFIT CEILING HIT — up {PROFIT_CEILING_PCT*100:.0f}%")
    print(f"   Locking in gains and halting for the day...")
    close_all_positions_and_orders()
    halted = True

return halted
```

# —————————————————————

# INDICATORS

# —————————————————————

def compute_ema(series, period):
return series.ewm(span=period, adjust=False).mean()

def compute_rsi(series, period=14):
delta = series.diff()
gain = delta.clip(lower=0)
loss = -delta.clip(upper=0)
avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
rs = avg_gain / avg_loss
return 100 - (100 / (1 + rs))

# —————————————————————

# DATA

# —————————————————————

def get_bars(symbol):
request = CryptoBarsRequest(
symbol_or_symbols=symbol,
timeframe=TimeFrame.Minute,
limit=50
)
bars = data_client.get_crypto_bars(request).df
if isinstance(bars.index, pd.MultiIndex):
bars = bars.xs(symbol, level=“symbol”)
return bars

# —————————————————————

# SIGNAL GENERATION

# —————————————————————

def get_signal(symbol):
bars = get_bars(symbol)
close = bars[“close”]

```
fast = compute_ema(close, FAST_EMA)
slow = compute_ema(close, SLOW_EMA)
rsi = compute_rsi(close, RSI_PERIOD)

prev_fast, curr_fast = fast.iloc[-2], fast.iloc[-1]
prev_slow, curr_slow = slow.iloc[-2], slow.iloc[-1]
curr_rsi = rsi.iloc[-1]

bullish_cross = prev_fast <= prev_slow and curr_fast > curr_slow
bearish_cross = prev_fast >= prev_slow and curr_fast < curr_slow

if bullish_cross and RSI_BUY_MIN <= curr_rsi <= RSI_BUY_MAX:
    return "BUY", curr_rsi
elif bearish_cross or curr_rsi >= RSI_SELL:
    return "SELL", curr_rsi
return "HOLD", curr_rsi
```

# —————————————————————

# POSITION HELPERS

# —————————————————————

def get_position_qty(symbol):
try:
position_symbol = symbol.replace(”/”, “”)
position = trading_client.get_open_position(position_symbol)
return float(position.qty)
except Exception:
return 0.0

def place_order(symbol, side, equity):
position_symbol = symbol.replace(”/”, “”)
trade_value = equity * RISK_PER_TRADE

```
bars = get_bars(symbol)
price = bars["close"].iloc[-1]
qty = round(trade_value / price, 6)

if qty <= 0:
    print(f"    Skipping {symbol} — calculated qty too small")
    return

order = MarketOrderRequest(
    symbol=position_symbol,
    qty=qty,
    side=side,
    time_in_force=TimeInForce.GTC
)
trading_client.submit_order(order)
print(f"    ✓ {side} {qty} {symbol} @ ~${price:.2f}")
```

# —————————————————————

# MAIN STRATEGY LOOP

# —————————————————————

def run_strategy():
global halted

```
if halted:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Bot is halted for the day — skipping.")
    return

print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running strategy...")

# Check thresholds before doing anything
if check_thresholds():
    return

equity = get_equity()

for symbol in SYMBOLS:
    print(f"  Checking {symbol}...")
    signal, rsi = get_signal(symbol)
    held_qty = get_position_qty(symbol)
    print(f"    Signal: {signal} | RSI: {rsi:.1f} | Held: {held_qty}")

    if signal == "BUY" and held_qty == 0:
        place_order(symbol, OrderSide.BUY, equity)

    elif signal == "SELL" and held_qty > 0:
        position_symbol = symbol.replace("/", "")
        order = MarketOrderRequest(
            symbol=position_symbol,
            qty=held_qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC
        )
        trading_client.submit_order(order)
        print(f"    ✓ SELL full position: {held_qty} {symbol}")

    # Check thresholds again after each trade
    if check_thresholds():
        return
```

# —————————————————————

# DAILY RESET

# —————————————————————

def reset_daily():
global starting_equity, halted
halted = False
starting_equity = get_equity()
floor = starting_equity * (1 - LOSS_FLOOR_PCT)
ceiling = starting_equity * (1 + PROFIT_CEILING_PCT)
print(f”\n{’=’*50}”)
print(f”🟢 New day started — {datetime.now().strftime(’%Y-%m-%d’)}”)
print(f”   Starting equity : ${starting_equity:.2f}”)
print(f”   Loss floor      : ${floor:.2f}  (-{LOSS_FLOOR_PCT*100:.0f}%)”)
print(f”   Profit ceiling  : ${ceiling:.2f}  (+{PROFIT_CEILING_PCT*100:.0f}%)”)
print(f”{’=’*50}”)

# —————————————————————

# ENTRY POINT

# —————————————————————

if **name** == “**main**”:
reset_daily()

```
# Run strategy every 15 minutes
schedule.every(15).minutes.do(run_strategy)

# Reset state at midnight UTC each day
schedule.every().day.at("00:01").do(reset_daily)

print("Bot running... Press Ctrl+C to stop.\n")
while True:
    schedule.run_pending()
    time.sleep(30)
```
