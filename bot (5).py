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

# Initialize TV Datafeed (nologin)
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

    # MACD (12, 26, 9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # ROC (Rate of Change - 9)
    df['ROC'] = ((df['close'] - df['close'].shift(9)) / df['close'].shift(9)) * 100

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

def evaluate_market_structure(df):
    highs = df['high'].values
    lows = df['low'].values
    
    recent_highs = highs[-20:]
    recent_lows = lows[-20:]
    
    bullish_score = 0
    bearish_score = 0
    
    if recent_highs[-1] > recent_highs[-10] and recent_lows[-1] > recent_lows[-10]:
        bullish_score += 15
    if recent_highs[-1] > recent_highs[-5]:
        bullish_score += 10

    if recent_lows[-1] < recent_lows[-10] and recent_highs[-1] < recent_highs[-10]:
        bearish_score += 15
    if recent_lows[-1] < recent_lows[-5]:
        bearish_score += 10

    return bullish_score, bearish_score

def calculate_100_point_score(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    bull_score = 0
    bear_score = 0
    
    # 1. Market Structure (25 pts)
    m_bull, m_bear = evaluate_market_structure(df)
    bull_score += min(25, m_bull)
    bear_score += min(25, m_bear)
    
    # 2. Displacement / Price Velocity (25 pts)
    body = latest['close'] - latest['open']
    atr = latest['ATR'] if not pd.isna(latest['ATR']) and latest['ATR'] > 0 else 1.0
    
    if body > 0.8 * atr:
        bull_score += 15
    elif body > 0.4 * atr:
        bull_score += 8
        
    if body < -0.8 * atr:
        bear_score += 15
    elif body < -0.4 * atr:
        bear_score += 8
        
    if (latest['close'] > prev['close']) and (prev['close'] > df.iloc[-3]['close']):
        bull_score += 10
    if (latest['close'] < prev['close']) and (prev['close'] < df.iloc[-3]['close']):
        bear_score += 10

    # 3. Volume / Participation (15 pts)
    vol = latest['volume']
    avg_vol = df['volume'].rolling(10).mean().iloc[-1]
    if not pd.isna(avg_vol) and vol > avg_vol:
        bull_score += 7.5
        bear_score += 7.5
    if body > 0 and vol > 1.2 * avg_vol:
        bull_score += 7.5
    if body < 0 and vol > 1.2 * avg_vol:
        bear_score += 7.5

    # 4. Volatility (15 pts)
    if latest['ATR'] > latest['ATR_MA']:
        bull_score += 7.5
        bear_score += 7.5
    if latest['ATR'] > df['ATR'].rolling(20).mean().iloc[-1]:
        bull_score += 7.5
        bear_score += 7.5

    # 5. Momentum Indicators (20 pts)
    adx = latest['ADX']
    rsi = latest['RSI']
    macd_hist = latest['MACD_hist']
    roc = latest['ROC']
    
    if adx > 35:
        bull_score += 5
        bear_score += 5
    elif adx > 25:
        bull_score += 3
        bear_score += 3
        
    if rsi > 60:
        bull_score += 5
    elif rsi > 52:
        bull_score += 3
        
    if rsi < 40:
        bear_score += 5
    elif rsi < 48:
        bear_score += 3
        
    if macd_hist > 0 and macd_hist > df.iloc[-2]['MACD_hist']:
        bull_score += 5
    elif macd_hist > 0:
        bull_score += 3
        
    if macd_hist < 0 and macd_hist < df.iloc[-2]['MACD_hist']:
        bear_score += 5
    elif macd_hist < 0:
        bear_score += 3
        
    if roc > 0.1:
        bull_score += 5
    if roc < -0.1:
        bear_score += 5

    return round(bull_score, 1), round(bear_score, 1), latest['close'], adx, rsi, latest['ATR']

async def send_telegram_alert(message):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")
        logging.info("Telegram alert sent successfully.")
    except Exception as e:
        logging.error(f"Failed to send Telegram alert: {e}")

async def main():
    logging.info("Bot started using TradingView OANDA XAUUSD data with 100-Point Scoring System...")
    await send_telegram_alert("🚀 *XAUUSD 100-Point Scoring Bot Started*\n\nRunning with Advanced Multi-Indicator & Structure Engine (Threshold: 70+).")
    
    last_signal_time = None
    
    while True:
        try:
            df = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_5_minute, n_bars=60)
            
            if df is not None and not df.empty:
                df = calculate_indicators(df)
                bull_score, bear_score, price, adx, rsi, atr = calculate_100_point_score(df)
                current_time = str(df.index[-1])
                
                logging.info(f"Time: {current_time} | Price: {price} | Bull: {bull_score} | Bear: {bear_score}")
                
                if (bull_score >= 70 or bear_score >= 70) and current_time != last_signal_time:
                    last_signal_time = current_time
                    
                    winning_score = bull_score if bull_score >= 70 else bear_score
                    direction = "🟢 STRONG BULLISH MOMENTUM" if bull_score >= 70 else "🔴 STRONG BEARISH MOMENTUM"
                    
                    msg = (
                        f"🔥 *XAUUSD 100-Point Signal Detected* 🔥\n\n"
                        f"**Direction:** {direction}\n"
                        f"**Score:** `{winning_score} / 100`\n\n"
                        f"💰 *Price (OANDA/Exness):* `${price:.2f}`\n"
                        f"📊 *ADX:* `{adx:.2f}` | *RSI:* `{rsi:.2f}` | *ATR:* `{atr:.2f}`\n\n"
                        f"⏱ *Time:* `{current_time} (UTC)`"
                    )
                    await send_telegram_alert(msg)
            else:
                logging.warning("Failed to fetch data from TradingView. Retrying...")
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
            
        await asyncio.sleep(60)

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("CRITICAL: Missing Telegram Credentials!")
    else:
        asyncio.run(main())
