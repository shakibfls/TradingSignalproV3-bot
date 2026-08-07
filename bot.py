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
        # Bullish FVG (Gap between High of candle 1 and Low of candle 3)
        if df['low'].iloc[i] > df['high'].iloc[i-2]:
            fvg_list.append({'index': df.index[i-1], 'type': 'BULLISH', 'top': df['low'].iloc[i], 'bottom': df['high'].iloc[i-2]})
        # Bearish FVG (Gap between Low of candle 1 and High of candle 3)
        elif df['high'].iloc[i] < df['low'].iloc[i-2]:
            fvg_list.append({'index': df.index[i-1], 'type': 'BEARISH', 'top': df['low'].iloc[i-2], 'bottom': df['high'].iloc[i]})
    return fvg_list

def detect_bos(df):
    """Detect Break of Structure (BOS)"""
    recent_high = df['high'].iloc[-15:-2].max()
    recent_low = df['low'].iloc[-15:-2].min()
    
    current_close = df['close'].iloc[-1]
    
    if current_close > recent_high:
        return 'BULLISH_BOS'
    elif current_close < recent_low:
        return 'BEARISH_BOS'
    return None

def get_market_context(df):
    """Determine institutional trend using EMA 200"""
    ema200 = df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
    current_price = df['close'].iloc[-1]
    return 'BULLISH' if current_price > ema200 else 'BEARISH'

def is_active_session():
    """Check if London or NY sessions are active (Best for Gold)"""
    now = datetime.now(pytz.utc)
    # London: 08:00 - 16:00 UTC
    # NY: 13:00 - 21:00 UTC
    if 8 <= now.hour <= 21:
        return True
    return False

async def send_telegram_alert(message):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")
        logging.info("SMC Signal sent.")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def main():
    logging.info("Manus X-Gold SMC Algorithm Started...")
    await send_telegram_alert("🏦 *Manus X-Gold Institutional Algorithm ONLINE* 🏦\n\nStrategy: Smart Money Concepts (SMC)\nLogic: FVG + BOS + Order Flow\nMonitoring: XAUUSD (5m/15m)")
    
    last_signal_time = None
    
    while True:
        try:
            # Fetch 5m data for signals
            df = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_5_minute, n_bars=100)
            
            if df is not None and not df.empty:
                context = get_market_context(df)
                bos = detect_bos(df)
                fvgs = detect_fvg(df)
                
                latest_price = df['close'].iloc[-1]
                current_time = str(df.index[-1])
                
                # Logic: If BOS occurs in the direction of the Context AND there's a recent FVG
                signal = None
                if bos == 'BULLISH_BOS' and context == 'BULLISH':
                    # Check if there's a Bullish FVG in the last 5 candles
                    recent_fvgs = [f for f in fvgs[-5:] if f['type'] == 'BULLISH']
                    if recent_fvgs:
                        signal = 'BUY'
                        
                elif bos == 'BEARISH_BOS' and context == 'BEARISH':
                    # Check if there's a Bearish FVG in the last 5 candles
                    recent_fvgs = [f for f in fvgs[-5:] if f['type'] == 'BEARISH']
                    if recent_fvgs:
                        signal = 'SELL'
                
                if signal:
                    signal_id = f"{current_time} {signal}"
                    if signal_id != last_signal_time:
                        last_signal_time = signal_id
                        
                        emoji = "🟢 INSTITUTIONAL BUY" if signal == 'BUY' else "🔴 INSTITUTIONAL SELL"
                        session_status = "✅ High Liquidity Session" if is_active_session() else "⚠️ Low Liquidity (Asian)"
                        
                        msg = (
                            f"🏦 *MANUS X-GOLD SMC SIGNAL* 🏦\n\n"
                            f"**Action:** {emoji}\n"
                            f"**Market Context:** `{context} TREND`\n"
                            f"**Trigger:** `BOS + FVG Detected` ⚡\n\n"
                            f"💰 *Entry Price:* `${latest_price:.2f}`\n"
                            f"🛡 *Stop Loss:* `Below recent swing`\n"
                            f"🎯 *Target:* `Next Liquidity Zone`\n\n"
                            f"🌐 *Session:* {session_status}\n"
                            f"⏱ *Time:* `{current_time} (UTC)`\n\n"
                            f"💡 *Manus Tip:* Look for price to retrace into the FVG before entry for better Risk/Reward."
                        )
                        await send_telegram_alert(msg)
                
                # Periodic log
                if int(time.time()) % 60 < 10:
                    logging.info(f"Scanning XAUUSD... Price: {latest_price} | Context: {context}")
            
        except Exception as e:
            logging.error(f"Loop error: {e}")
            
        await asyncio.sleep(15) # Check every 15 seconds

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("Missing Credentials!")
    else:
        asyncio.run(main())
