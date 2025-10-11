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
            return symbol, "ERROR", 0.0
        
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
        price = float(latest['Close'])
        short_ma = float(latest['Short_MA'])
        long_ma = float(latest['Long_MA'])
        rsi = float(latest['RSI'])
        
        # Determine signal
        if pd.isna(short_ma) or pd.isna(long_ma):
            return symbol, "WAIT", price
        elif short_ma > long_ma and 50 < rsi < 65:
            return symbol, "BUY", price
        elif short_ma < long_ma:
            return symbol, "SELL", price
        else:
            return symbol, "WAIT", price
        
    except Exception as e:
        return symbol, "ERROR", 0.0

def create_beautiful_email():
    """Create beautiful formatted email"""
    results = []
    
    for stock in STOCKS:
        symbol, signal, price = get_signal_for_stock(stock)
        results.append({
            'symbol': symbol,
            'signal': signal,
            'price': price
        })
    
    # Count signals
    buy_count = sum(1 for r in results if r['signal'] == 'BUY')
    sell_count = sum(1 for r in results if r['signal'] == 'SELL')
    wait_count = sum(1 for r in results if r['signal'] == 'WAIT')
    
    # Create email
    email_body = f"""

          DAILY TRADING SIGNALS  
          
             {date.today()}                 


 Summary: {buy_count} BUY | {sell_count} SELL | {wait_count} WAIT


"""
    
    # Add each stock
    for r in results:
        symbol = r['symbol']
        signal = r['signal']
        price = r['price']
        
        # Signal emoji
        if signal == 'BUY':
            emoji = '🟢'
        elif signal == 'SELL':
            emoji = '🔴'
        elif signal == 'WAIT':
            emoji = '⚪'
        else:
            emoji = '⚠️'
        
        # Format price
        if price >= 1000:
            price_str = f"${price:,.2f}"
        else:
            price_str = f"${price:.2f}"
        
        email_body += f"""
{emoji} {symbol:<6} → {signal:<4}  |  Price: {price_str}
"""
    
    email_body += """


Strategy: 10/30 MA Crossover + RSI (50-65)



⚠️MESSAGE FROM REINDOLF:
This is no financial advice. Trade responsibly!


"""
    
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
    msg['Subject'] = f' Trading Signals - {date.today()}'
    
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
    email_message = create_beautiful_email()
    print(email_message)
    send_email(email_message)
