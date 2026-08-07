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
    
    # EMA 50
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    return df

def calculate_ultra_fast_score(df_1m, df_5m):
    latest_1m = df_1m.iloc[-1]
    prev_1m = df_1m.iloc[-2]
    latest_5m = df_5m.iloc[-1]
    
    bull_score = 0
    bear_score = 0
    
    # 1. INSTANT VELOCITY (50 pts) - The "Rocket" Engine
    # How fast is the current 1-minute candle moving compared to 5-minute ATR?
    body_1m = latest_1m['close'] - latest_1m['open']
    atr_5m = latest_5m['ATR'] if not pd.isna(latest_5m['ATR']) and latest_5m['ATR'] > 0 else 0.5
    
    # Spike Detection: If M1 body is > 30% of M5 ATR, it's a massive move
    velocity = body_1m / atr_5m
    
    if velocity > 0.3: bull_score += 40
    elif velocity > 0.15: bull_score += 20
    
    if velocity < -0.3: bear_score += 40
    elif velocity < -0.15: bear_score += 20
    
    # Price Breakout (10 pts)
    if latest_1m['close'] > df_1m['high'].iloc[-5:-1].max(): bull_score += 10
    if latest_1m['close'] < df_1m['low'].iloc[-5:-1].min(): bear_score += 10

    # 2. 5-MINUTE TREND ALIGNMENT (30 pts)
    # Price vs EMA50 on 5m
    if latest_5m['close'] > latest_5m['EMA50']: bull_score += 15
    else: bear_score += 15
    
    # RSI Alignment
    if latest_5m['RSI'] > 55: bull_score += 15
    if latest_5m['RSI'] < 45: bear_score += 15

    # 3. 1-MINUTE MOMENTUM (20 pts)
    if latest_1m['RSI'] > 60: bull_score += 10
    if latest_1m['RSI'] < 40: bear_score += 10
    
    # Volume expansion on 1m
    avg_vol_1m = df_1m['volume'].rolling(10).mean().iloc[-1]
    if latest_1m['volume'] > 1.5 * avg_vol_1m:
        bull_score += 10
        bear_score += 10

    # WICK FILTER (Safety)
    upper_wick = latest_1m['high'] - max(latest_1m['open'], latest_1m['close'])
    lower_wick = min(latest_1m['open'], latest_1m['close']) - latest_1m['low']
    
    if velocity > 0 and upper_wick > abs(body_1m) * 0.6: bull_score -= 30 # Reject if huge upper wick
    if velocity < 0 and lower_wick > abs(body_1m) * 0.6: bear_score -= 30 # Reject if huge lower wick

    return round(bull_score, 1), round(bear_score, 1), latest_1m['close'], latest_1m['RSI'], velocity

async def send_telegram_alert(message):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")
        logging.info("Telegram alert sent.")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def main():
    logging.info("ULTRA-FAST Bot Started: 1-Minute Triggers, 5-Second Polling...")
    await send_telegram_alert("🚀 *XAUUSD ULTRA-FAST Bot ONLINE* 🚀\n\nEngine: 1m Spike Detection\nScan Rate: Every 5-10 Seconds\nThreshold: 70+")
    
    last_signal_time = None 
    
    while True:
        try:
            # Fetch 1m and 5m data
            df_1m = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_1_minute, n_bars=50)
            df_5m = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_5_minute, n_bars=50)
            
            if df_1m is not None and df_5m is not None:
                df_1m = calculate_indicators(df_1m)
                df_5m = calculate_indicators(df_5m)
                
                bull_score, bear_score, price, rsi_1m, velocity = calculate_ultra_fast_score(df_1m, df_5m)
                
                # Unique ID for signal (Minute + Direction)
                current_minute = str(df_1m.index[-1])
                
                direction = None
                if bull_score >= 70: direction = "BULLISH"
                elif bear_score >= 70: direction = "BEARISH"
                
                if direction:
                    signal_id = f"{current_minute} {direction}"
                    
                    if signal_id != last_signal_time:
                        last_signal_time = signal_id
                        score = bull_score if direction == "BULLISH" else bear_score
                        emoji = "🚀 BUY" if direction == "BULLISH" else "📉 SELL"
                        
                        msg = (
                            f"🔥 *XAUUSD ULTRA-FAST SIGNAL* 🔥\n\n"
                            f"**Action:** {emoji}\n"
                            f"**Score:** `{score} / 100`\n"
                            f"**Velocity:** `{velocity:.2f}x ATR` ⚡\n\n"
                            f"💰 *Price:* `${price:.2f}`\n"
                            f"📊 *1m RSI:* `{rsi_1m:.2f}`\n\n"
                            f"⏱ *Time:* `{current_minute} (UTC)`\n"
                            f"✅ *Entry:* Instant Momentum Detected!"
                        )
                        await send_telegram_alert(msg)
                
                # Log status every 30s to keep Railway alive and show activity
                if int(time.time()) % 30 < 10:
                    logging.info(f"Scanning... Price: {price} | Bull: {bull_score} | Bear: {bear_score}")
            
        except Exception as e:
            logging.error(f"Loop error: {e}")
            
        # FAST POLLING: 7 seconds is a sweet spot for TV free data
        await asyncio.sleep(7)

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("Missing Credentials!")
    else:
        asyncio.run(main())
