import os
import time
import requests
import pandas as pd
import pandas_ta as ta
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment Variables (User will set these)
OANDA_API_KEY = os.getenv("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "XAU_USD"
TIMEFRAME = "M5"  # 5 Minutes

OANDA_URL = f"https://api-fxpractice.oanda.com/v3/accounts/{OANDA_ACCOUNT_ID}/instruments/{SYMBOL}/candles"

def get_candles(count=50):
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    params = {
        "count": count,
        "granularity": TIMEFRAME,
        "price": "M"  # Midpoint
    }
    try:
        response = requests.get(OANDA_URL, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            candles = data.get("candles", [])
            df_data = []
            for c in candles:
                if c['complete']:
                    df_data.append({
                        "time": c['time'],
                        "open": float(c['mid']['o']),
                        "high": float(c['mid']['h']),
                        "low": float(c['mid']['l']),
                        "close": float(c['mid']['c']),
                    })
            return pd.DataFrame(df_data)
        else:
            logging.error(f"OANDA API Error: {response.text}")
            return None
    except Exception as e:
        logging.error(f"Error fetching candles: {e}")
        return None

def calculate_momentum(df):
    # Calculate ADX
    adx = df.ta.adx(length=14)
    df = pd.concat([df, adx], axis=1)
    
    # Calculate RSI
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # Get last row
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    adx_val = last['ADX_14']
    rsi_val = last['rsi']
    plus_di = last['DMP_14']
    minus_di = last['DMN_14']
    
    momentum = "Low"
    trend = "Neutral"
    
    # Logic
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
    logging.info("Bot started...")
    last_signal_time = None
    
    while True:
        df = get_candles()
        if df is not None and len(df) > 20:
            trend, momentum, adx, rsi, price = calculate_momentum(df)
            current_time = df.iloc[-1]['time']
            
            if momentum in ["Medium", "Strong"] and current_time != last_signal_time:
                emoji = "🚀" if trend == "Bullish" else "📉"
                strength_emoji = "🔥" if momentum == "Strong" else "⚡"
                
                msg = (
                    f"{emoji} *XAUUSD Signal Detected!*\n\n"
                    f"Trend: *{trend}*\n"
                    f"Momentum: *{momentum}* {strength_emoji}\n"
                    f"Price: `{price}`\n"
                    f"ADX: `{adx:.2f}`\n"
                    f"RSI: `{rsi:.2f}`\n\n"
                    f"Time: {current_time}"
                )
                
                logging.info(f"Signal: {trend} {momentum} at {price}")
                send_telegram_msg(msg)
                last_signal_time = current_time
        
        # Wait for 30 seconds before next check
        time.sleep(30)

if __name__ == "__main__":
    if not all([OANDA_API_KEY, OANDA_ACCOUNT_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("Missing Environment Variables!")
    else:
        main()
