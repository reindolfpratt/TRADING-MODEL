import feedparser
import yfinance as yf
from datetime import datetime, timedelta
import time
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import os
import re
from newspaper import Article
import pandas as pd
from dateutil import parser as dateparser

def get_sp500_tickers():
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
    df = pd.read_csv(url)
    return list(df['Symbol'])

# CONFIGURATION
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STOCKS_TO_MONITOR = get_sp500_tickers()
analyzer = SentimentIntensityAnalyzer()
alerted_today = {}

BULLISH_KEYWORDS = [
    'earnings beat', 'record profit', 'surge', 'soar', 'layoff', 
    'breakthrough', 'approval', 'deal', 'partnership', 'acquisition', 
    'upgraded', 'beats estimates', 'strong growth', 'revenue jump', 
    'new high', 'major win', 'expansion', 'breakthrough product',
    'buyback', 'raises outlook', 'guidance raised', 'outperforms', 
    'increases dividend', 'record sales', 'positive forecast', 
    'achieves milestone', 'profit rises', 'beats guidance', 
    'initiates dividend', 'unveils', 'launch', 'all-time high', 
    'surpassed expectations', 'resilient demand'
]

BEARISH_KEYWORDS = [
    'plunge', 'crash', 'downgrade', 'lawsuit', 'investigation', 
    'miss', 'disappoints', 'loses', 'cuts guidance', 'bankruptcy', 
    'scandal', 'recall', 'suspended', 'warning', 'fraud',
    'profit warning', 'misses expectations', 'slumps', 'profit falls', 
    'guidance cut', 'dividend cut', 'default', 'layoff', 'fires ceo', 
    'restatement', 'delisted', 'weak demand', 'slashed forecast', 
    'cutbacks', 'cut jobs', 'downgraded', 'resignation', 'missed estimates'
]
NOISE_KEYWORDS = [
    'analyst says', 'could', 'might', 'may', 'opinion',
    'watch', 'what to know', 'should you', 'stock analysis',
    'technical analysis', 'chart', 'levels to watch'
]

def get_latest_news_rss(symbol):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    feed = feedparser.parse(url)
    articles = []
    cutoff = datetime.utcnow() - timedelta(days=2)
    for entry in feed.entries[:7]:
        pub_str = entry.get('published', '') or entry.get('pubDate', '')
        if pub_str:
            try:
                pub_dt = dateparser.parse(pub_str)
                if pub_dt < cutoff:
                    continue
            except Exception:
                pass
        articles.append({
            'title': entry.title,
            'link': entry.link,
            'published': pub_str
        })
    return articles

def is_relevant_news(text, symbol):
    text_lower = text.lower()
    symbol_lower = symbol.lower()
    if symbol_lower in text_lower:
        return True
    if re.search(rf'(\${symbol_lower}|(?<!\w){symbol_lower}(?!\w))', text_lower):
        return True
    return False

def fetch_full_article_content(link):
    try:
        article = Article(link)
        article.download()
        article.parse()
        text = article.text
        if not text or len(text.split()) < 100:
            return None
        return text.strip()
    except Exception as e:
        print(f"❌ Article error ({link}): {e}")
        return None

def calculate_news_quality_score(text):
    if not text:
        return 0, False, True
    news_lower = text.lower()
    noise_count = sum(1 for keyword in NOISE_KEYWORDS if keyword in news_lower)
    if noise_count > 0:
        return 0, False, True
    bullish_count = sum(1 for keyword in BULLISH_KEYWORDS if keyword in news_lower)
    bearish_count = sum(1 for keyword in BEARISH_KEYWORDS if keyword in news_lower)
    has_high_impact = (bullish_count >= 2 or bearish_count >= 2)
    quality_score = min(bullish_count + bearish_count, 5)
    word_count = len(news_lower.split())
    if word_count > 300:
        quality_score += 2
    if word_count > 600:
        quality_score += 2
    return quality_score, has_high_impact, False

def analyze_sentiment_and_score(symbol, articles):
    for art in articles:
        if not is_relevant_news(art['title'], symbol):
            continue
        full_content = fetch_full_article_content(art['link'])
        if not full_content:
            continue
        if not is_relevant_news(full_content, symbol):
            continue
        quality_score, has_high_, is_noise = calculate_news_quality_score(full_content)
        if is_noise:
            continue
        scores = analyzer.polarity_scores(full_content)
        compound = scores['compound']
        if compound >= 0.65 and has_high_:
            sentiment = "BULLISH"
            impact = min(10, int((compound - 0.65) * 25) + 7)
        elif compound <= -0.65 and has_high_:
            sentiment = "BEARISH"
            impact = min(10, int((-compound - 0.65) * 25) + 7)
        else:
            sentiment = "NEUTRAL"
            impact = max(0, quality_score - 2)
        impact = min(10, int(impact * (quality_score / 10))) if sentiment == "NEUTRAL" else impact
        reasoning = art['title'] if len(art['title']) < 120 else art['title'][:117] + "..."
        return sentiment, impact, reasoning, quality_score, art['link']
    return "NEUTRAL", 0, "No relevant news found", 0, ""

def moving_average_confirmation(symbol, sentiment, short_window=20, long_window=50):
    df = yf.download(symbol, period='6mo', interval='1d', progress=False)
    if df.empty or len(df) < long_window + 1:
        print(f"  [MA] Not enough data for moving average check")
        return False
    df['Short_MA'] = df['Close'].rolling(window=short_window).mean()
    df['Long_MA'] = df['Close'].rolling(window=long_window).mean()
    short_ma = float(df['Short_MA'].iloc[-1])
    long_ma = float(df['Long_MA'].iloc[-1])
    if sentiment == "BULLISH" and short_ma > long_ma:
        print(f"  [MA] BULLISH confirmed by MA: Short_MA ({short_ma:.2f}) > Long_MA ({long_ma:.2f})")
        return True
    if sentiment == "BEARISH" and short_ma < long_ma:
        print(f"  [MA] BEARISH confirmed by MA: Short_MA ({short_ma:.2f}) < Long_MA ({long_ma:.2f})")
        return True
    print(f"  [MA] No confirmation from moving average for {sentiment}")
    return False

def get_price_momentum(symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period='1d', interval='5m')
        if len(hist) < 6:
            return None, 0
        current_price = float(hist['Close'].iloc[-1])
        price_30min_ago = float(hist['Close'].iloc[-6])
        momentum = ((current_price - price_30min_ago) / price_30min_ago) * 100
        return round(current_price, 2), round(momentum, 2)
    except Exception as e:
        print(f"Price error for {symbol}: {e}")
        return None, 0

def check_daily_cooldown(symbol):
    today = datetime.now().date()
    if symbol in alerted_today and alerted_today[symbol] == today:
        return False
    return True

def send_telegram_alert(symbol, action, price, impact, reasoning, momentum, quality_score, link):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram not configured - Would send: {symbol} {action}")
        return
    momentum_emoji = "📈" if momentum > 0 else "📉"
    if "BUY LONG" in action:
        target1, target2, stop = round(price * 1.03, 2), round(price * 1.05, 2), round(price * 0.985, 2)
        line_targets = f"*PROFIT TARGETS:*  • TP1: ${target1} (+3%)  • TP2: ${target2} (+5%)\n🛑 *STOP LOSS:* ${stop} (-1.5%)"
    else:
        target1, target2, stop = round(price * 0.97, 2), round(price * 0.95, 2), round(price * 1.015, 2)
        line_targets = f"*PROFIT TARGETS:*  • TP1: ${target1} (-3%)  • TP2: ${target2} (-5%)\n🛑 *STOP LOSS:* ${stop} (+1.5%)"
    message = f"""🚨 *PREMIUM TRADE ALERT* 🚨

{action} *{symbol}*

💰 Entry Price: ${price}
{momentum_emoji} Momentum: {momentum:+.2f}%

{line_targets}

📊 Quality Score: {quality_score}/10
⚡ Impact: {impact}/10

📰 *CATALYST:* [{reasoning}]({link})

⏰ {datetime.utcnow().strftime('%H:%M:%S')} (UTC)
🔗 [Source & Trade Details](https://finance.yahoo.com/quote/{symbol})
"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"✅ Telegram alert sent for {symbol}")
        else:
            print(f"❌ Telegram failed: {response.text}")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

def scan_all_stocks():
    print(f"{'='*60}\n🔍 PREMIUM MARKET SCAN - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n{'='*60}\n📊 Monitoring {len(STOCKS_TO_MONITOR)} stocks\n")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        print(f"✅ Telegram configured (Token: {TELEGRAM_BOT_TOKEN[:10]}...)")
    else:
        print(f"⚠️ WARNING: Telegram NOT configured!")
    opportunities_found = 0
    for symbol in STOCKS_TO_MONITOR:
        print(f"{'─'*60}\nScanning {symbol}...")
        if not check_daily_cooldown(symbol):
            print(f"  ⏭️ Already alerted today - skipping")
            continue
        articles = get_latest_news_rss(symbol)
        if not articles:
            print(f"  ℹ️ No news found")
            continue
        print(f"  📰 Found {len(articles)} article(s)")
        sentiment, impact, reasoning, quality_score, link = analyze_sentiment_and_score(symbol, articles)
        print(f"  📊 Analysis: Sentiment: {sentiment}, Impact: {impact}/10, Quality: {quality_score}/10")
        # <<<<< NEW LOGIC: Require MA confirmation >>>>>
        if (
            impact >= 8 and quality_score >= 5 and sentiment != "NEUTRAL"
            and moving_average_confirmation(symbol, sentiment)
        ):
            print(f"  ✓ Passes strict criteria AND moving average confirmed!")
            price, momentum = get_price_momentum(symbol)
            if price:
                print(f"  💰 Price: ${price}, Momentum: {momentum:+.2f}%")
                if sentiment == "BULLISH" and momentum < -2:
                    print(f"  ⚠️ Negative momentum {momentum}% conflicts with BULLISH - REJECTED")
                    continue
                if sentiment == "BEARISH" and momentum > 2:
                    print(f"  ⚠️ Positive momentum {momentum}% conflicts with BEARISH - REJECTED")
                    continue
                print(f"  🎯 PREMIUM OPPORTUNITY CONFIRMED! 📤 Sending Telegram alert...")
                action = "🟢 BUY LONG" if sentiment == "BULLISH" else "🔴 SHORT"
                send_telegram_alert(symbol, action, price, impact, reasoning, momentum, quality_score, link)
                alerted_today[symbol] = datetime.now().date()
                opportunities_found += 1
                time.sleep(2)
            else:
                print(f"  ❌ Price unavailable")
        else:
            print(f"  ❌ Rejected: (Impact/Quality/Sentiment too low, NEUTRAL, or failed MA check)")
        time.sleep(0.5)
    print(f"\n{'='*60}\nSCAN SUMMARY\n{'='*60}\n✅ Stocks scanned: {len(STOCKS_TO_MONITOR)}\n🎯 Premium opportunities found: {opportunities_found}\n")
    print(f"⏰ Scan completed at {datetime.utcnow().strftime('%H:%M:%S UTC')}\n{'='*60}\n")

if __name__ == "__main__":
    scan_all_stocks()
