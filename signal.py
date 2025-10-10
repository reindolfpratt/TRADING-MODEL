import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# YOUR STOCKS
STOCKS = ["SPY", "AMZN", "MSFT", "NVDA", "TSLA", "GOOGL"]

def get_signal_for_stock(symbol):
    """Get trading signal for a single stock"""
    END_DATE = str(date.today())
    START_DATE = "2025-09-01"
    
    try:
        data = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
        
        if data.empty:
            return symbol, "ERROR"
        
        # Calculate indicators
        data['Short_MA'] = data['Close'].rolling(window=10).mean()
        data['Long_MA'] = data['Close'].rolling(window=30).mean()
        
        # RSI
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        data['RSI'] = 100 - (100 / (1 + rs))
        
        latest = data.iloc[-1]
        short_ma = float(latest['Short_MA'])
        long_ma = float(latest['Long_MA'])
        rsi = float(latest['RSI'])
        
        # Determine signal
        if pd.isna(short_ma) or pd.isna(long_ma):
            return symbol, "WAIT"
        elif short_ma > long_ma and 50 < rsi < 65:
            return symbol, "BUY"
        elif short_ma < long_ma:
            return symbol, "SELL"
        else:
            return symbol, "WAIT"
        
    except Exception as e:
        return symbol, "ERROR"

def create_simple_email():
    """Create simple email with just stock + action"""
    results = []
    
    for stock in STOCKS:
        symbol, signal = get_signal_for_stock(stock)
        results.append(f"{symbol} - {signal}")
    
    email_body = f"Daily Signals - {date.today()}\n\n"
    email_body += "\n".join(results)
    
    return email_body

def send_email(message):
    """Send email"""
    sender_email = os.environ.get('EMAIL_USER')
    sender_password = os.environ.get('EMAIL_PASSWORD')
    receiver_email = os.environ.get('EMAIL_USER')
    
    if not sender_email or not sender_password:
        print("⚠️ Email credentials not set")
        return
    
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = f'Trading Signals - {date.today()}'
    
    msg.attach(MIMEText(message, 'plain'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent!")
    except Exception as e:
        print(f"❌ Email failed: {str(e)}")

if __name__ == "__main__":
    email_message = create_simple_email()
    print(email_message)
    send_email(email_message)
