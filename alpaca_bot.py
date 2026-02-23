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
API_KEY = os.environ.get("ALPACA_API_KEY")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
PAPER = True
SYMBOLS = ["BTC/USD", "ETH/USD", "DOGE/USD", "SOL/USD", "AVAX/USD"]
LOSS_FLOOR_PCT = 0.10
PROFIT_CEILING_PCT = 0.25
FAST_EMA = 9
SLOW_EMA = 21
RSI_PERIOD = 14
WEAK_SIGNAL_PCT = 0.05
MEDIUM_SIGNAL_PCT = 0.20
STRONG_SIGNAL_PCT = 0.40
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
data_client = CryptoHistoricalDataClient()
starting_equity = None
halted = False
def get_equity():
return float(trading_client.get_account().equity)
def close_all_positions_and_orders():
print("Cancelling all open orders...")
trading_client.cancel_orders()
print("Closing all open positions...")
positions = trading_client.get_all_positions()
if not positions:
print("No open positions to close.")
return
for position in positions:
try:
trading_client.close_position(position.symbol)
print("Closed: " + position.symbol)
except Exception as e:
print("Could not close " + position.symbol + ": " + str(e))
def check_thresholds():
global halted
equity = get_equity()
pct_change = (equity - starting_equity) / starting_equity * 100
pct_str = str(round(pct_change, 2))
eq_str = str(round(equity, 2))
print("Equity: $" + eq_str + " (" + pct_str + "% today)")
if equity <= starting_equity * (1 - LOSS_FLOOR_PCT):
print("LOSS FLOOR HIT - closing all and halting.")
close_all_positions_and_orders()
halted = True
elif equity >= starting_equity * (1 + PROFIT_CEILING_PCT):
print("PROFIT CEILING HIT - locking in gains and halting.")
close_all_positions_and_orders()
halted = True
return halted
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
ema_gap = abs(curr_fast - curr_slow) / curr_slow * 100
bullish_cross = prev_fast <= prev_slow and curr_fast > curr_slow
bearish_cross = prev_fast >= prev_slow and curr_fast < curr_slow
bullish_trend = curr_fast > curr_slow
if bullish_cross or (bullish_trend and curr_rsi < 70):
if curr_rsi > 60 and ema_gap > 0.3:
return "BUY", "STRONG", curr_rsi
elif curr_rsi > 45 and ema_gap > 0.1:
return "BUY", "MEDIUM", curr_rsi
elif curr_rsi > 35:
return "BUY", "WEAK", curr_rsi
if bearish_cross or curr_rsi >= 72 or curr_rsi <= 28:
return "SELL", "STRONG", curr_rsi
return "HOLD", "NONE", curr_rsi
def get_signal_pct(strength):
if strength == "STRONG":
return STRONG_SIGNAL_PCT
elif strength == "MEDIUM":
return MEDIUM_SIGNAL_PCT
return WEAK_SIGNAL_PCT
def get_position_qty(symbol):
try:
position_symbol = symbol.replace("/", "")
position = trading_client.get_open_position(position_symbol)
return float(position.qty)
except Exception:
return 0.0
def place_order(symbol, side, equity, strength="WEAK"):
position_symbol = symbol.replace("/", "")
trade_pct = get_signal_pct(strength)
trade_value = equity * trade_pct
bars = get_bars(symbol)
price = bars["close"].iloc[-1]
qty = round(trade_value / price, 6)
if qty <= 0:
print("Skipping " + symbol + " - qty too small")
return
order = MarketOrderRequest(
symbol=position_symbol,
qty=qty,
side=side,
time_in_force=TimeInForce.GTC
)
trading_client.submit_order(order)
pct_label = str(round(trade_pct * 100)) + "%"
print(str(side) + " " + str(qty) + " " + symbol + " at $" + str(round(price, 2)) + " [" +
def run_strategy():
global halted
if halted:
print("Bot is halted for the day.")
return
print("Running strategy - " + datetime.now().strftime("%H:%M:%S"))
if check_thresholds():
return
equity = get_equity()
for symbol in SYMBOLS:
print("Checking " + symbol)
try:
signal, strength, rsi = get_signal(symbol)
held_qty = get_position_qty(symbol)
print("Signal: " + signal + " [" + strength + "] RSI: " + str(round(rsi, 1)) + "
if signal == "BUY" and held_qty == 0:
place_order(symbol, OrderSide.BUY, equity, strength)
elif signal == "SELL" and held_qty > 0:
position_symbol = symbol.replace("/", "")
order = MarketOrderRequest(
symbol=position_symbol,
qty=held_qty,
side=OrderSide.SELL,
time_in_force=TimeInForce.GTC
)
trading_client.submit_order(order)
print("SELL full position: " + str(held_qty) + " " + symbol)
if check_thresholds():
return
except Exception as e:
print("Error on " + symbol + ": " + str(e))
continue
def reset_daily():
global starting_equity, halted
halted = False
starting_equity = get_equity()
floor = starting_equity * (1 - LOSS_FLOOR_PCT)
ceiling = starting_equity * (1 + PROFIT_CEILING_PCT)
print("==================================================")
print("New day started - " + datetime.now().strftime("%Y-%m-%d"))
print("Starting equity: $" + str(round(starting_equity, 2)))
print("Loss floor: $" + str(round(floor, 2)) + " (-10%)")
print("Profit ceiling: $" + str(round(ceiling, 2)) + " (+25%)")
print("==================================================")
if __name__ == "__main__":
reset_daily()
schedule.every(10).minutes.do(run_strategy)
schedule.every().day.at("00:01").do(reset_daily)
print("Bot running...")
while True:
schedule.run_pending()
time.sleep(30)
