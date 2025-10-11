import feedparser
import yfinance as yf
from datetime import datetime, timedelta
import time
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import os

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Stocks to monitor (15 most volatile)
STOCKS_TO_MONITOR = [
    "AAPL", "TSLA", "NVDA", "AMZN", "GOOGL",
    "MSFT", "META", "NFLX", "AMD", "COIN",
    "SPY", "QQQ", "DIS", "PLTR", "SOFI"
]

# Initialize sentiment analyzer
analyzer = SentimentIntensityAnalyzer()

# Track recently alerted stocks (prevent duplicates)
recently_alerted = {}
COOLDOWN_HOURS = 4  # Don't alert same stock for 4 hours

# ═══════════════════════════════════════════════════════════
# FUNCTIONS
# ═══════════════════════════════════════════════════════════

def get_latest_news_rss(symbol):
    """Get latest news from Yahoo Finance RSS feed"""
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        feed = feedparser.parse(url)
        
        articles = []
        for entry in feed.entries[:3]:
            articles.append({
                'title': entry.title,
                'link': entry.link
            })
        
        return articles
    except Exception as e:
        print(f"Error fetching RSS for {symbol}: {e}")
        return []


def analyze_sentiment_vader(headlines):
    """Analyze sentiment using VADER AI"""
    
    if not headlines:
        return "NEUTRAL", 0, "No news available"
    
    text = " ".join([h['title'] for h in headlines])
    scores = analyzer.polarity_scores(text)
    compound = scores['compound']
    
    if compound >= 0.5:
        sentiment = "BULLISH"
        impact = min(10, int((compound - 0.5) * 20) + 6)
    elif compound <= -0.5:
        sentiment = "BEARISH"
        impact = min(10, int((-compound - 0.5) * 20) + 6)
    elif compound >= 0.2:
        sentiment = "BULLISH"
        impact = 5
    elif compound <= -0.2:
        sentiment = "BEARISH"
        impact = 5
    else:
        sentiment = "NEUTRAL"
        impact = 3
    
    reasoning = headlines[0]['title'][:100] if headlines else "No specific news"
    
    return sentiment, impact, reasoning


def get_current_price(symbol):
    """Get current stock price"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period='1d', interval='5m')
        
        if len(hist) < 1:
            return None
        
        current_price = float(hist['Close'].iloc[-1])
        return round(current_price, 2)
        
    except Exception as e:
        print(f"Price error for {symbol}: {e}")
        return None


def send_telegram_alert(symbol, action, price, impact, reasoning):
    """Send instant Telegram alert with trade details"""
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram not configured - Would send: {symbol} {action}")
        return
    
    if "BUY LONG" in action:
        target1 = round(price * 1.03, 2)
        target2 = round(price * 1.05, 2)
        stop = round(price * 0.985, 2)
        
        message = f""" *TRADE ALERT* 

{action} *{symbol}*

 Entry Price: ${price}

 *PROFIT TARGETS:*
   • Take Profit 1: ${target1} (+3%)
   • Take Profit 2: ${target2} (+5%)

 *STOP LOSS:* ${stop} (-1.5%)

 *Impact:* {impact}/10
 
*NEWS:* _{reasoning}_

 {datetime.now().strftime('%H:%M:%S')}"""

    else:
        target1 = round(price * 0.97, 2)
        target2 = round(price * 0.95, 2)
        stop = round(price * 1.015, 2)
        
        message = f""" *TRADE ALERT* 

{action} *{symbol}*

 Entry Price: ${price}

 *PROFIT TARGETS:*
   • Cover at 1: ${target1} (-3%)
   • Cover at 2: ${target2} (-5%)

 *STOP LOSS:* ${stop} (+1.5%)

 Impact: {impact}/10
*NEWS:* _{reasoning}_

 {datetime.now().strftime('%H:%M:%S')}"""

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"✅ Telegram alert sent for {symbol}")
        else:
            print(f"❌ Telegram failed: {response.text}")
    except Exception as e:
        print(f"❌ Telegram error: {e}")


def scan_all_stocks():
    """Main scanner - checks all stocks for news opportunities"""
    
    print(f"\n🔍 Starting market scan at {datetime.now().strftime('%H:%M:%S')}")
    print(f"📊 Monitoring {len(STOCKS_TO_MONITOR)} stocks for breaking news...\n")
    
    opportunities_found = 0
    
    for symbol in STOCKS_TO_MONITOR:
        print(f"Scanning {symbol}...", end=" ")
        
        news = get_latest_news_rss(symbol)
        
        if not news:
            print("No news")
            continue
        
        sentiment, impact, reasoning = analyze_sentiment_vader(news)
        
        print(f"{sentiment} ({impact}/10)", end="")
        
        # Only alert on impact 9+ (HUGE news only)
        if impact >= 9:
            # Check cooldown - don't spam same stock
            now = datetime.now()
            
            if symbol in recently_alerted:
                last_alert_time = recently_alerted[symbol]
                time_since_alert = (now - last_alert_time).total_seconds() / 3600
                
                if time_since_alert < COOLDOWN_HOURS:
                    print(f" (Already alerted {time_since_alert:.1f}h ago - skipping)")
                    continue
            
            price = get_current_price(symbol)
            
            if price:
                print(f" HIGH IMPACT - Sending alert!")
                
                if sentiment == "BULLISH":
                    action = "BUY LONG"
                else:
                    action = "SHORT"
                
                send_telegram_alert(symbol, action, price, impact, reasoning)
                
                # Mark as alerted
                recently_alerted[symbol] = now
                
                opportunities_found += 1
                time.sleep(2)
            else:
                print(" (Price unavailable)")
        else:
            print()
        
        time.sleep(0.5)
    
    print(f"\n✅ Scan complete! Found {opportunities_found} high-impact opportunities.")
    print(f"⏰ Next scan in 10 minutes\n")


# ═══════════════════════════════════════════════════════════
# RUN THE SCANNER
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    scan_all_stocks()
