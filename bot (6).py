import os
import time
import logging
import pandas as pd
import numpy as np
from tvDatafeed import TvDatafeed, Interval
from telegram import Bot
import asyncio

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Initialize TV Datafeed
tv = TvDatafeed()

def calculate_indicators(df):
    # RSI 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # ATR 14
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(window=14).mean()
    df['ATR_MA'] = df['ATR'].rolling(window=5).mean()

    # EMA 50 for trend
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()

    # ADX approximation
    plus_dm = df['high'].diff()
    minus_dm = df['low'].diff()
    plus_dm = np.where((plus_dm > 0) & (plus_dm > minus_dm), plus_dm, 0)
    minus_dm = np.where((minus_dm > 0) & (minus_dm > plus_dm), minus_dm, 0)
    tr14 = true_range.rolling(14).sum()
    plus_di = 100 * (pd.Series(plus_dm).rolling(14).sum() / tr14)
    minus_di = 100 * (pd.Series(minus_dm).rolling(14).sum() / tr14)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    df['ADX'] = dx.rolling(14).mean().fillna(25)

    return df

def calculate_100_point_score(df_5m):
    latest_5m = df_5m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    
    bull_score = 0
    bear_score = 0
    
    # 1. Displacement / Price Velocity (40 pts) - High weight for pure 5m momentum
    body = latest_5m['close'] - latest_5m['open']
    atr = latest_5m['ATR'] if not pd.isna(latest_5m['ATR']) and latest_5m['ATR'] > 0 else 1.0
    
    # Wick rejection filter
    upper_wick = latest_5m['high'] - max(latest_5m['open'], latest_5m['close'])
    lower_wick = min(latest_5m['open'], latest_5m['close']) - latest_5m['low']
    
    if body > 0.4 * atr:
        if upper_wick < body * 0.4: # Strict wick filter
            bull_score += 30
        if latest_5m['close'] > prev_5m['high']: 
            bull_score += 10
            
    if body < -0.4 * atr:
        if lower_wick < abs(body) * 0.4:
            bear_score += 30
        if latest_5m['close'] < prev_5m['low']: 
            bear_score += 10

    # 2. Market Structure (30 pts)
    # Check if price is breaking out of recent 10-candle range
    recent_high = df_5m['high'].iloc[-11:-1].max()
    recent_low = df_5m['low'].iloc[-11:-1].min()
    
    if latest_5m['close'] > recent_high: bull_score += 20
    if latest_5m['low'] > df_5m['low'].iloc[-10:].mean(): bull_score += 10
    
    if latest_5m['close'] < recent_low: bear_score += 20
    if latest_5m['high'] < df_5m['high'].iloc[-10:].mean(): bear_score += 10

    # 3. Indicators (30 pts)
    adx = latest_5m['ADX']
    rsi = latest_5m['RSI']
    
    if adx > 25: bull_score += 10; bear_score += 10
    if rsi > 55: bull_score += 10
    if rsi < 45: bear_score += 10
    if latest_5m['close'] > latest_5m['EMA50']: bull_score += 10
    if latest_5m['close'] < latest_5m['EMA50']: bear_score += 10

    return round(bull_score, 1), round(bear_score, 1), latest_5m['close'], adx, rsi, latest_5m['ATR']

async def send_telegram_alert(message):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")
        logging.info("Telegram alert sent.")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def main():
    logging.info("Bot started: PURE 5m EARLY DETECTION (15m Filter Removed)...")
    await send_telegram_alert("⚡ *XAUUSD Pure 5m Early Detection Bot Started*\n\n15m filter removed. Monitoring 5m momentum only for faster alerts.")
    
    last_signal_time = None 
    
    while True:
        try:
            # Fetch only 5m data
            df_5m = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_5_minute, n_bars=60)
            
            if df_5m is not None and not df_5m.empty:
                df_5m = calculate_indicators(df_5m)
                bull_score, bear_score, price, adx, rsi, atr = calculate_100_point_score(df_5m)
                
                candle_time = str(df_5m.index[-1])
                logging.info(f"[{candle_time}] Price: {price} | Bull: {bull_score} | Bear: {bear_score}")
                
                direction = None
                if bull_score >= 70: direction = "BULLISH"
                elif bear_score >= 70: direction = "BEARISH"
                
                if direction:
                    signal_id = f"{candle_time} {direction}"
                    
                    if signal_id != last_signal_time:
                        last_signal_time = signal_id
                        score = bull_score if direction == "BULLISH" else bear_score
                        emoji = "🟢" if direction == "BULLISH" else "🔴"
                        
                        msg = (
                            f"⚡ *XAUUSD 5m MOMENTUM SIGNAL* ⚡\n\n"
                            f"**Direction:** {emoji} {direction}\n"
                            f"**Score:** `{score} / 100`\n"
                            f"**Status:** `Early Detection (In-Progress)`\n\n"
                            f"💰 *Current Price:* `${price:.2f}`\n"
                            f"📊 *ADX:* `{adx:.2f}` | *RSI:* `{rsi:.2f}`\n"
                            f"📏 *ATR:* `{atr:.2f}`\n\n"
                            f"⚠️ *Fast Entry:* Detected before 5m candle close."
                        )
                        await send_telegram_alert(msg)
            
        except Exception as e:
            logging.error(f"Loop error: {e}")
            
        await asyncio.sleep(30)

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("Missing Credentials!")
    else:
        asyncio.run(main())
