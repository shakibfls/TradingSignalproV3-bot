import os
import time
import logging
import pandas as pd
import numpy as np
from tvDatafeed import TvDatafeed, Interval
from telegram import Bot
import asyncio
from datetime import datetime
import pytz

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Initialize TV Datafeed
tv = TvDatafeed()

def detect_fvg(df):
    """Detect Fair Value Gaps (FVG)"""
    fvg_list = []
    for i in range(2, len(df)):
        if df['low'].iloc[i] > df['high'].iloc[i-2]:
            fvg_list.append({'index': df.index[i-1], 'type': 'BULLISH'})
        elif df['high'].iloc[i] < df['low'].iloc[i-2]:
            fvg_list.append({'index': df.index[i-1], 'type': 'BEARISH'})
    return fvg_list

def detect_bos(df):
    """Detect Break of Structure (BOS) - Early detection version"""
    recent_high = df['high'].iloc[-10:-1].max()
    recent_low = df['low'].iloc[-10:-1].min()
    current_close = df['close'].iloc[-1]
    
    if current_close > recent_high:
        return 'BULLISH_BOS'
    elif current_close < recent_low:
        return 'BEARISH_BOS'
    return None

def get_momentum_score(df):
    """Calculate raw momentum based on price velocity"""
    body = df['close'].iloc[-1] - df['open'].iloc[-1]
    # ATR approximation
    high_low = df['high'] - df['low']
    atr = high_low.rolling(14).mean().iloc[-1]
    if pd.isna(atr) or atr == 0: atr = 0.5
    
    velocity = body / atr
    return velocity

async def send_telegram_alert(message):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")
        logging.info("Hybrid Signal sent.")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def main():
    logging.info("Manus Hybrid X-Gold Algorithm Started...")
    await send_telegram_alert("⚡ *Manus Hybrid X-Gold Algorithm ONLINE* ⚡\n\nStrategy: SMC + Momentum Breakout\nMode: High Frequency\nMonitoring: XAUUSD (5m)")
    
    last_signal_time = None
    
    while True:
        try:
            df = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_5_minute, n_bars=100)
            
            if df is not None and not df.empty:
                bos = detect_bos(df)
                fvgs = detect_fvg(df)
                velocity = get_momentum_score(df)
                
                latest_price = df['close'].iloc[-1]
                current_time = str(df.index[-1])
                
                signal = None
                signal_type = ""
                
                # 1. Primary: SMC Logic (BOS + FVG)
                recent_fvgs_bull = [f for f in fvgs[-5:] if f['type'] == 'BULLISH']
                recent_fvgs_bear = [f for f in fvgs[-5:] if f['type'] == 'BEARISH']
                
                if bos == 'BULLISH_BOS' and recent_fvgs_bull:
                    signal = 'BUY'
                    signal_type = "🏦 Institutional SMC"
                elif bos == 'BEARISH_BOS' and recent_fvgs_bear:
                    signal = 'SELL'
                    signal_type = "🏦 Institutional SMC"
                
                # 2. Secondary: Momentum Breakout (If no SMC but strong move)
                elif not signal:
                    if bos == 'BULLISH_BOS' and velocity > 0.4:
                        signal = 'BUY'
                        signal_type = "🚀 Momentum Breakout"
                    elif bos == 'BEARISH_BOS' and velocity < -0.4:
                        signal = 'SELL'
                        signal_type = "📉 Momentum Breakout"
                
                if signal:
                    signal_id = f"{current_time} {signal}"
                    if signal_id != last_signal_time:
                        last_signal_time = signal_id
                        
                        emoji = "🟢 BUY" if signal == 'BUY' else "🔴 SELL"
                        
                        msg = (
                            f"⚡ *XAUUSD HYBRID SIGNAL* ⚡\n\n"
                            f"**Action:** {emoji}\n"
                            f"**Logic:** `{signal_type}`\n"
                            f"**Velocity:** `{velocity:.2f}x ATR` ⚡\n\n"
                            f"💰 *Price:* `${latest_price:.2f}`\n"
                            f"⏱ *Time:* `{current_time} (UTC)`\n\n"
                            f"✅ *Note:* Signal triggered by combined SMC and Momentum analysis."
                        )
                        await send_telegram_alert(msg)
                
                if int(time.time()) % 60 < 15:
                    logging.info(f"Scanning... Price: {latest_price} | Velocity: {velocity:.2f}")
            
        except Exception as e:
            logging.error(f"Loop error: {e}")
            
        await asyncio.sleep(15)

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("Missing Credentials!")
    else:
        asyncio.run(main())
