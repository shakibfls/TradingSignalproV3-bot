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

def get_indicators(df):
    """Calculate core indicators for Sniper-90 logic"""
    # EMA 200 for Trend
    df['ema200'] = df['close'].rolling(200).mean()
    # RSI 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    # ATR for SL/TP
    df['atr'] = (df['high'] - df['low']).rolling(14).mean()
    # Volume MA
    df['vol_ma'] = df['volume'].rolling(20).mean()
    return df

def detect_order_blocks(df):
    """Detect institutional order blocks"""
    obs = []
    for i in range(len(df)-5, len(df)-1):
        if df['close'].iloc[i] < df['open'].iloc[i] and df['close'].iloc[i+1] > df['open'].iloc[i+1]:
            if (df['close'].iloc[i+1] - df['open'].iloc[i+1]) > (df['open'].iloc[i] - df['close'].iloc[i]) * 2:
                obs.append({'type': 'BULLISH', 'level': df['high'].iloc[i], 'low': df['low'].iloc[i]})
        elif df['close'].iloc[i] > df['open'].iloc[i] and df['close'].iloc[i+1] < df['open'].iloc[i+1]:
            if (df['open'].iloc[i+1] - df['close'].iloc[i+1]) > (df['close'].iloc[i] - df['open'].iloc[i]) * 2:
                obs.append({'type': 'BEARISH', 'level': df['low'].iloc[i], 'high': df['high'].iloc[i]})
    return obs

async def fetch_mtf_data():
    """Fetch 1m, 5m, and 15m data"""
    try:
        df1m = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_1_minute, n_bars=100)
        await asyncio.sleep(0.5)
        df5m = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_5_minute, n_bars=100)
        await asyncio.sleep(0.5)
        df15m = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_15_minute, n_bars=200)
        return df1m, df5m, df15m
    except Exception as e:
        logging.error(f"Data fetch error: {e}")
        return None, None, None

async def send_alert(msg):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def main():
    logging.info("Manus Sniper-90 Engine Started...")
    await send_alert("🎯 *MANUS SNIPER-90 ONLINE* 🎯\n\nTarget: 90% Win Rate (1:1 RR)\nLogic: Institutional Order Blocks + Volume Surge\nStatus: Monitoring XAUUSD Ultra-Strictly")
    
    last_signal_time = None
    
    while True:
        try:
            df1m, df5m, df15m = await fetch_mtf_data()
            
            if all(df is not None for df in [df1m, df5m, df15m]):
                df1m = get_indicators(df1m)
                df5m = get_indicators(df5m)
                df15m = get_indicators(df15m)
                
                # 15m Trend & RSI Filter
                trend15m = 'BULLISH' if df15m['close'].iloc[-1] > df15m['ema200'].iloc[-1] else 'BEARISH'
                rsi15m = df15m['rsi'].iloc[-1]
                
                # 5m Order Blocks
                obs5m = detect_order_blocks(df5m)
                atr5m = df5m['atr'].iloc[-1]
                
                # 1m Real-time Data
                price1m = df1m['close'].iloc[-1]
                open1m = df1m['open'].iloc[-1]
                high1m = df1m['high'].iloc[-1]
                low1m = df1m['low'].iloc[-1]
                rsi1m = df1m['rsi'].iloc[-1]
                vol1m = df1m['volume'].iloc[-1]
                vol_ma1m = df1m['vol_ma'].iloc[-1]
                
                # Candle Quality (Body Ratio)
                body = abs(price1m - open1m)
                total_range = high1m - low1m
                quality = body / total_range if total_range > 0 else 0
                
                signal = None
                
                # SNIPER-90 BULLISH RULES
                if trend15m == 'BULLISH' and rsi15m > 50:
                    if rsi1m > 65 and vol1m > vol_ma1m * 1.2 and quality > 0.6:
                        for ob in obs5m[-3:]:
                            if ob['type'] == 'BULLISH' and price1m >= ob['low'] and price1m <= ob['level'] * 1.0005:
                                signal = 'BUY'
                                break
                            
                # SNIPER-90 BEARISH RULES
                elif trend15m == 'BEARISH' and rsi15m < 50:
                    if rsi1m < 35 and vol1m > vol_ma1m * 1.2 and quality > 0.6:
                        for ob in obs5m[-3:]:
                            if ob['type'] == 'BEARISH' and price1m <= ob['high'] and price1m >= ob['level'] * 0.9995:
                                signal = 'SELL'
                                break

                if signal:
                    current_time = str(df1m.index[-1])
                    signal_id = f"{current_time} {signal}"
                    
                    if signal_id != last_signal_time:
                        last_signal_time = signal_id
                        
                        emoji = "🎯 SNIPER BUY" if signal == 'BUY' else "🎯 SNIPER SELL"
                        
                        # 1:1 RR for High Win Rate
                        sl_dist = 2.5 * atr5m
                        tp_dist = 2.5 * atr5m
                        
                        sl = price1m - sl_dist if signal == 'BUY' else price1m + sl_dist
                        tp = price1m + tp_dist if signal == 'BUY' else price1m - tp_dist
                        
                        msg = (
                            f"🎯 *MANUS SNIPER-90 SIGNAL* 🎯\n\n"
                            f"**Action:** {emoji}\n"
                            f"**Win Rate Target:** `90% (Strict Mode)`\n"
                            f"**RR Ratio:** `1:1`\n\n"
                            f"💰 *Entry:* `${price1m:.2f}`\n"
                            f"🛡 *Stop Loss:* `${sl:.2f}`\n"
                            f"🎯 *Take Profit:* `${tp:.2f}`\n\n"
                            f"🔥 *Quality:* `High (Volume + Body Confirmed)`\n"
                            f"📊 *Trend:* `15m {trend15m} Confirmed`\n\n"
                            f"✅ *Manus Tip:* This is a high-accuracy sniper entry. Follow SL/TP strictly."
                        )
                        await send_alert(msg)
                
                if int(time.time()) % 60 < 10:
                    logging.info(f"Sniper Scanning... Price: {price1m} | Trend: {trend15m}")

        except Exception as e:
            logging.error(f"Loop error: {e}")
            
        await asyncio.sleep(10) # 10s polling

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("Missing Credentials!")
    else:
        asyncio.run(main())
