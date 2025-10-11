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
# Create email
email_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
</head>
<body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
    <table width="600" cellpadding="0" cellspacing="0" style="margin: 0 auto; background-color: #ffffff; border: 1px solid #ddd;">
        
        <!-- Header -->
        <tr>
            <td style="background-color: #2c3e50; color: #ffffff; text-align: center; padding: 30px;">
                <h1 style="margin: 0; font-size: 24px;">DAILY TRADING SIGNALS</h1>
                <p style="margin: 10px 0 0 0; font-size: 14px;">{date.today()}</p>
            </td>
        </tr>
        
        <!-- Summary -->
        <tr>
            <td style="padding: 20px; text-align: center; background-color: #ecf0f1;">
                <p style="margin: 0; font-size: 16px;">
                    <strong>{buy_count} BUY</strong> | <strong>{sell_count} SELL</strong> | <strong>{wait_count} WAIT</strong>
                </p>
            </td>
        </tr>
        
        <!-- Stock Signals -->
        <tr>
            <td style="padding: 20px;">
                <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
                    <tr style="background-color: #34495e; color: #ffffff;">
                        <th style="text-align: left; padding: 12px; border-bottom: 2px solid #2c3e50;">SYMBOL</th>
                        <th style="text-align: center; padding: 12px; border-bottom: 2px solid #2c3e50;">SIGNAL</th>
                        <th style="text-align: right; padding: 12px; border-bottom: 2px solid #2c3e50;">PRICE</th>
                    </tr>
"""

# Add each stock
for r in results:
    symbol = r['symbol']
    signal = r['signal']
    price = r['price']
    
    # Determine row color based on signal
    if signal == 'BUY':
        row_color = '#d5f4e6'  # Light green
        signal_color = '#27ae60'  # Green
    elif signal == 'SELL':
        row_color = '#fadbd8'  # Light red
        signal_color = '#e74c3c'  # Red
    else:  # WAIT
        row_color = '#f9f9f9'  # Light gray
        signal_color = '#95a5a6'  # Gray
    
    # Format price
    if price >= 1000:
        price_str = f"${price:,.2f}"
    else:
        price_str = f"${price:.2f}"
    
    email_body += f"""
                    <tr style="background-color: {row_color};">
                        <td style="padding: 12px; border-bottom: 1px solid #ddd;"><strong>{symbol}</strong></td>
                        <td style="text-align: center; padding: 12px; border-bottom: 1px solid #ddd; color: {signal_color};"><strong>{signal}</strong></td>
                        <td style="text-align: right; padding: 12px; border-bottom: 1px solid #ddd;"><strong>{price_str}</strong></td>
                    </tr>
"""

email_body += f"""
                </table>
            </td>
        </tr>
        
        <!-- Strategy Info -->
        <tr>
            <td style="padding: 20px; background-color: #ecf0f1; text-align: center;">
                <p style="margin: 0; font-size: 14px; color: #7f8c8d;">
                    <strong>Strategy:</strong> 10/30 MA Crossover + RSI (50-65)
                </p>
            </td>
        </tr>
        
        <!-- Footer -->
        <tr>
            <td style="padding: 20px; background-color: #2c3e50; color: #ffffff; text-align: center;">
                <p style="margin: 0; font-size: 12px;">
                    <strong>MESSAGE FROM REINDOLF:</strong><br>
                    This is not financial advice. Trade responsibly!
                </p>
            </td>
        </tr>
        
    </table>
</body>
</html>
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
    
    msg.attach(MIMEText(message, 'html'))
    
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
