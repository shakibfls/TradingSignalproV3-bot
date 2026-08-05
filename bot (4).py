import os
import time
import sys
import logging
import requests
from tradingview_ta import TA_Handler, Interval

# Configure Logging to stdout for Railway
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# TradingView Settings
SYMBOL = "XAUUSD"
SCREENER = "cfd"
EXCHANGE = "OANDA" # Professional Forex/CFD data source
INTERVAL = Interval.INTERVAL_5_MINUTES

def get_analysis():
    try:
        handler = TA_Handler(
            symbol=SYMBOL,
            screener=SCREENER,
            exchange=EXCHANGE,
            interval=INTERVAL,
            timeout=15
        )
        return handler.get_analysis()
    except Exception as e:
        logging.error(f"TradingView Data Error: {e}")
        return None

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            logging.error(f"Telegram Failed: {res.text}")
    except Exception as e:
        logging.error(f"Telegram Error: {e}")

def main():
    logging.info(f"--- XAUUSD Momentum Bot Started (TradingView {EXCHANGE} Source) ---")
    send_telegram_msg(f"🚀 *XAUUSD Momentum Bot is now ONLINE!*\nSource: TradingView ({EXCHANGE} Real-Time)")
    
    last_signal_msg = ""
    heartbeat_count = 0
    
    while True:
        try:
            analysis = get_analysis()
            
            if analysis:
                indicators = analysis.indicators
                
                # Extracting Values
                price = indicators.get("close")
                adx = indicators.get("ADX")
                rsi = indicators.get("RSI")
                plus_di = indicators.get("ADX+DI")
                minus_di = indicators.get("ADX-DI")
                
                # Safety check for None values
                if None in [price, adx, rsi, plus_di, minus_di]:
                    logging.warning("Some indicators are missing, skipping...")
                    time.sleep(30)
                    continue

                momentum = "Low"
                trend = "Neutral"
                
                # Momentum Logic (Same as requested)
                if plus_di > minus_di:
                    trend = "Bullish"
                    if adx > 40 and rsi > 70:
                        momentum = "Strong"
                    elif adx > 25 and rsi > 60:
                        momentum = "Medium"
                elif minus_di > plus_di:
                    trend = "Bearish"
                    if adx > 40 and rsi < 30:
                        momentum = "Strong"
                    elif adx > 25 and rsi < 40:
                        momentum = "Medium"
                
                # Heartbeat log every ~5 minutes
                heartbeat_count += 1
                if heartbeat_count >= 10:
                    logging.info(f"Heartbeat: {SYMBOL} is {trend} ({momentum}) at {price}")
                    heartbeat_count = 0
                
                # Signal Notification
                if momentum in ["Medium", "Strong"]:
                    emoji = "🚀" if trend == "Bullish" else "📉"
                    strength_emoji = "🔥" if momentum == "Strong" else "⚡"
                    
                    msg = (
                        f"{emoji} *XAUUSD Signal Detected!*\n\n"
                        f"Trend: *{trend}*\n"
                        f"Momentum: *{momentum}* {strength_emoji}\n"
                        f"Price: `${price:.2f}`\n"
                        f"ADX: `{adx:.2f}`\n"
                        f"RSI: `{rsi:.2f}`\n\n"
                        f"Source: TradingView ({EXCHANGE})"
                    )
                    
                    # Avoid duplicate spamming if the message is identical
                    if msg != last_signal_msg:
                        logging.info(f"SIGNAL SENT: {trend} {momentum} at {price}")
                        send_telegram_msg(msg)
                        last_signal_msg = msg
            
        except Exception as e:
            logging.error(f"Unexpected loop error: {e}")
            
        # Poll every 60 seconds to stay within safe limits
        time.sleep(60)

if __name__ == "__main__":
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("CRITICAL: Missing Telegram Credentials!")
    else:
        main()
