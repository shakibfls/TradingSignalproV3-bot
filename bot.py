import os
import time
import pandas as pd
import pandas_ta as ta
import requests
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "PAXGUSD"
INTERVAL = 5  # 5 minutes

def get_kraken_candles(pair=SYMBOL, interval=INTERVAL):
    url = "https://api.kraken.com/0/public/OHLC"
    params = {
        "pair": pair,
        "interval": interval
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                # Kraken returns a dynamic key for the pair, e.g., 'PAXGUSD' or 'XPAXGZUSD'
                pair_key = list(data['result'].keys())[0]
                candles = data['result'][pair_key]
                
                # Kraken OHLC format: [time, open, high, low, close, vwap, volume, count]
                df = pd.DataFrame(candles, columns=[
                    "time", "open", "high", "low", "close", "vwap", "volume", "count"
                ])
                
                # Convert to numeric
                df["open"] = pd.to_numeric(df["open"])
                df["high"] = pd.to_numeric(df["high"])
                df["low"] = pd.to_numeric(df["low"])
                df["close"] = pd.to_numeric(df["close"])
                
                # Convert timestamp to readable time
                df["time"] = pd.to_datetime(df["time"], unit='s')
                return df
            else:
                logging.error(f"Kraken API Result Error: {data}")
                return None
        else:
            logging.error(f"Kraken HTTP Error: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Error fetching Kraken data: {e}")
        return None

def calculate_momentum(df):
    # Calculate ADX (14)
    # pandas_ta expects 'high', 'low', 'close' columns
    adx = df.ta.adx(length=14)
    df = pd.concat([df, adx], axis=1)
    
    # Calculate RSI (14)
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # Get last row
    last = df.iloc[-1]
    
    adx_val = last['ADX_14']
    rsi_val = last['rsi']
    plus_di = last['DMP_14']
    minus_di = last['DMN_14']
    
    momentum = "Low"
    trend = "Neutral"
    
    # Momentum Logic
    if plus_di > minus_di:
        trend = "Bullish"
        if adx_val > 40 and rsi_val > 70:
            momentum = "Strong"
        elif adx_val > 25 and rsi_val > 60:
            momentum = "Medium"
    elif minus_di > plus_di:
        trend = "Bearish"
        if adx_val > 40 and rsi_val < 30:
            momentum = "Strong"
        elif adx_val > 25 and rsi_val < 40:
            momentum = "Medium"
            
    return trend, momentum, adx_val, rsi_val, last['close']

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logging.error(f"Telegram Error: {e}")

def main():
    logging.info(f"Bot started using Kraken {SYMBOL} real-time data...")
    send_telegram_msg("✅ *XAUUSD Momentum Bot is now ONLINE!*\n(Source: Kraken Real-Time Data)")
    
    last_signal_time = None
    
    while True:
        df = get_kraken_candles()
        if df is not None and len(df) > 20:
            trend, momentum, adx, rsi, price = calculate_momentum(df)
            current_time = str(df.iloc[-1]['time'])
            
            # Check for Medium or Strong momentum
            if momentum in ["Medium", "Strong"] and current_time != last_signal_time:
                emoji = "🚀" if trend == "Bullish" else "📉"
                strength_emoji = "🔥" if momentum == "Strong" else "⚡"
                
                msg = (
                    f"{emoji} *XAUUSD Signal Detected!*\n\n"
                    f"Trend: *{trend}*\n"
                    f"Momentum: *{momentum}* {strength_emoji}\n"
                    f"Price: `${price:.2f}`\n"
                    f"ADX: `{adx:.2f}`\n"
                    f"RSI: `{rsi:.2f}`\n\n"
                    f"Time: {current_time} (UTC)"
                )
                
                logging.info(f"Signal: {trend} {momentum} at {price}")
                send_telegram_msg(msg)
                last_signal_time = current_time
        
        # Check every 30 seconds for instant updates
        time.sleep(30)

if __name__ == "__main__":
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("Missing Environment Variables!")
    else:
        main()
