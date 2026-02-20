import os
import time
import schedule
from datetime import datetime
import pandas as pd
import numpy as np
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
# ---------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------
API_KEY = os.environ.get("ALPACA_API_KEY")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
PAPER = True
SYMBOLS = ["BTC/USD", "ETH/USD"]
RISK_PER_TRADE = 0.05
LOSS_FLOOR_PCT = 0.10
PROFIT_CEILING_PCT = 0.25
FAST_EMA = 9
SLOW_EMA = 21
RSI_PERIOD = 14
RSI_BUY_MIN = 40
RSI_BUY_MAX = 65
RSI_SELL = 70
# ---------------------------------------------------------------
# CLIENTS
# ---------------------------------------------------------------
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
data_client = CryptoHistoricalDataClient()
# ---------------------------------------------------------------
# STATE
# ---------------------------------------------------------------
starting_equity = None
halted = False
# ---------------------------------------------------------------
# ACCOUNT HELPERS
# ---------------------------------------------------------------
def get_equity():
return float(trading_client.get_account().equity)
def close_all_positions_and_orders():
print(" Cancelling all open orders...")
trading_client.cancel_orders()
print(" Closing all open positions...")
positions = trading_client.get_all_positions()
if not positions:
print(" No open positions to close.")
return
for position in positions:
try:
trading_client.close_position(position.symbol)
print(" Closed position: " + position.symbol)
except Exception as e:
print(" Could not close " + position.symbol + ": " + str(e))
# ---------------------------------------------------------------
# THRESHOLD CHECKS
# ---------------------------------------------------------------
def check_thresholds():
global halted
equity = get_equity()
pct_change = (equity - starting_equity) / starting_equity * 100
print(" Equity: $" + str(round(equity, 2)) + " (" + str(round(pct_change, 2)) + "% today)")
if equity <= starting_equity * (1 - LOSS_FLOOR_PCT):
print("LOSS FLOOR HIT - closing all positions and halting for the day.")
close_all_positions_and_orders()
halted = True
elif equity >= starting_equity * (1 + PROFIT_CEILING_PCT):
print("PROFIT CEILING HIT - locking in gains and halting for the day.")
close_all_positions_and_orders()
halted = True
return halted
# ---------------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------------
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
# ---------------------------------------------------------------
# DATA
# ---------------------------------------------------------------
def get_bars(symbol):
request = CryptoBarsRequest(
symbol_or_symbols=symbol,
timeframe=TimeFrame.Minute,
limit=50
)
bars = data_client.get_crypto_bars(request).df
if isinstance(bars.index, pd.MultiIndex):
bars = bars.xs(symbol, level="symbol")
return bars
# ---------------------------------------------------------------
# SIGNAL GENERATION
# ---------------------------------------------------------------
def get_signal(symbol):
bars = get_bars(symbol)
close = bars["close"]
fast = compute_ema(close, FAST_EMA)
slow = compute_ema(close, SLOW_EMA)
rsi = compute_rsi(close, RSI_PERIOD)
prev_fast = fast.iloc[-2]
curr_fast = fast.iloc[-1]
prev_slow = slow.iloc[-2]
curr_slow = slow.iloc[-1]
curr_rsi = rsi.iloc[-1]
bullish_cross = prev_fast <= prev_slow and curr_fast > curr_slow
bearish_cross = prev_fast >= prev_slow and curr_fast < curr_slow
if bullish_cross and RSI_BUY_MIN <= curr_rsi <= RSI_BUY_MAX:
return "BUY", curr_rsi
elif bearish_cross or curr_rsi >= RSI_SELL:
return "SELL", curr_rsi
return "HOLD", curr_rsi
# ---------------------------------------------------------------
# POSITION HELPERS
# ---------------------------------------------------------------
def get_position_qty(symbol):
try:
position_symbol = symbol.replace("/", "")
position = trading_client.get_open_position(position_symbol)
return float(position.qty)
except Exception:
return 0.0
def place_order(symbol, side, equity):
position_symbol = symbol.replace("/", "")
trade_value = equity * RISK_PER_TRADE
bars = get_bars(symbol)
price = bars["close"].iloc[-1]
qty = round(trade_value / price, 6)
if qty <= 0:
print(" return
Skipping " + symbol + " - qty too small")
order = MarketOrderRequest(
symbol=position_symbol,
qty=qty,
side=side,
time_in_force=TimeInForce.GTC
)
trading_client.submit_order(order)
print(" " + str(side) + " " + str(qty) + " " + symbol + " at ~$" + str(round(price, 2)
# ---------------------------------------------------------------
# MAIN STRATEGY LOOP
# ---------------------------------------------------------------
def run_strategy():
global halted
if halted:
return
print("[" + datetime.now().strftime("%H:%M:%S") + "] Bot is halted for the day.")
print("\n[" + datetime.now().strftime("%H:%M:%S") + "] Running strategy...")
if check_thresholds():
return
equity = get_equity()
for symbol in SYMBOLS:
print(" Checking " + symbol + "...")
signal, rsi = get_signal(symbol)
held_qty = get_position_qty(symbol)
print(" Signal: " + signal + " | RSI: " + str(round(rsi, 1)) + " | Held: " + str(h
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
print(" SELL full position: " + str(held_qty) + " " + symbol)
if check_thresholds():
return
# ---------------------------------------------------------------
# DAILY RESET
# ---------------------------------------------------------------
def reset_daily():
global starting_equity, halted
halted = False
starting_equity = get_equity()
floor = starting_equity * (1 - LOSS_FLOOR_PCT)
ceiling = starting_equity * (1 + PROFIT_CEILING_PCT)
print("==================================================")
print("New day started - " + datetime.now().strftime("%Y-%m-%d"))
print("Starting equity : $" + str(round(starting_equity, 2)))
print("Loss floor : $" + str(round(floor, 2)) + " (-10%)")
print("Profit ceiling : $" + str(round(ceiling, 2)) + " (+25%)")
print("==================================================")
# ---------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------
if __name__ == "__main__":
reset_daily()
schedule.every(15).minutes.do(run_strategy)
schedule.every().day.at("00:01").do(reset_daily)
print("Bot running...\n")
while True:
schedule.run_pending()
time.sleep(30)
