import feedparser
import yfinance as yf
from datetime import datetime, timedelta
import time
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import os
import re
from newspaper import Article

# ════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
STOCKS_TO_MONITOR = [
    "AAPL", "TSLA", "NVDA", "AMZN", "GOOGL",
    "MSFT", "META", "NFLX", "AMD", "COIN",
    "SPY", "QQQ", "DIS", "PLTR", "SOFI"
]
TICKER_TO_COMPANY = {
    "AAPL": "Apple",
    "TSLA": "Tesla",
    "NVDA": "Nvidia",
    "AMZN": "Amazon",
    "GOOGL": "Google",
    "MSFT": "Microsoft",
    "META": "Meta",
    "NFLX": "Netflix",
    "AMD": "AMD",
    "COIN": "Coinbase",
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco QQQ Trust",
    "DIS": "Disney",
    "PLTR": "Palantir",
    "SOFI": "SoFi Technologies"
}
analyzer = SentimentIntensityAnalyzer()
alerted_today = {}

BULLISH_KEYWORDS = [
    'earnings beat', 'record profit', 'surge', 'soar', 'breakthrough',
    'approval', 'deal', 'partnership', 'acquisition', 'upgraded',
    'beats estimates', 'strong growth', 'revenue jump', 'new high',
    'major win', 'expansion', 'breakthrough product'
]
BEARISH_KEYWORDS = [
    'plunge', 'crash', 'downgrade', 'lawsuit', 'investigation',
    'miss', 'disappoints', 'loses', 'cuts guidance', 'bankruptcy',
    'scandal', 'recall', 'suspended', 'warning', 'fraud'
]
NOISE_KEYWORDS = [
    'analyst says', 'could', 'might', 'may', 'opinion',
    'watch', 'what to know', 'should you', 'stock analysis',
    'technical analysis', 'chart', 'levels to watch'
]

# ════════════════════════════════════
# FUNCTIONS
# ════════════════════════════════════

def get_latest_news_rss(symbol):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:7]:  # Get several for skipping capability
        articles.append({
            'title': entry.title,
            'link': entry.link,
            'published': entry.get('published', '')
        })
    return articles

def is_relevant_news(text, symbol):
    company = TICKER_TO_COMPANY.get(symbol, "")
    text_lower = text.lower()
    symbol_lower = symbol.lower()
    company_lower = company.lower()
    # Check if symbol or company name in text
    if symbol_lower in text_lower:
        return True
    if company_lower and company_lower in text_lower:
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
        # Only return if there's enough text content (not an error or short redirect)
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
    # Check for noise
    noise_count = sum(1 for keyword in NOISE_KEYWORDS if keyword in news_lower)
    if noise_count > 0:
        return 0, False, True
    # Impact keywords
    bullish_count = sum(1 for keyword in BULLISH_KEYWORDS if keyword in news_lower)
    bearish_count = sum(1 for keyword in BEARISH_KEYWORDS if keyword in news_lower)
    has_high_impact = (bullish_count >= 2 or bearish_count >= 2)
    quality_score = min(bullish_count + bearish_count, 5)
    # Add bonus for longer article
    word_count = len(news_lower.split())
    if word_count > 300:
        quality_score += 2
    if word_count > 600:
        quality_score += 2
    return quality_score, has_high_impact, False

def analyze_sentiment_and_score(symbol, articles):
    for art in articles:
        # Only analyze if relevant headline
        if not is_relevant_news(art['title'], symbol):
            continue
        full_content = fetch_full_article_content(art['link'])
        if not full_content:
            continue
        # Double relevance check on the actual article content, not just headline
        if not is_relevant_news(full_content, symbol):
            continue
        # Score news content
        quality_score, has_high_impact, is_noise = calculate_news_quality_score(full_content)
        if is_noise:
            continue
        scores = analyzer.polarity_scores(full_content)
        compound = scores['compound']
        if compound >= 0.65 and has_high_impact:
            sentiment = "BULLISH"
            impact = min(10, int((compound - 0.65) * 25) + 7)
        elif compound <= -0.65 and has_high_impact:
            sentiment = "BEARISH"
            impact = min(10, int((-compound - 0.65) * 25) + 7)
        else:
            sentiment = "NEUTRAL"
            impact = max(0, quality_score - 2)
        impact = min(10, int(impact * (quality_score / 10)))
        reasoning = art['title'] if len(art['title']) < 120 else art['title'][:117] + "..."
        # Return first valid/relevant article's signal
        return sentiment, impact, reasoning, quality_score, art['link']
    # If nothing relevant found
    return "NEUTRAL", 0, "No relevant news found", 0, ""

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
        if impact >= 8 and quality_score >= 5 and sentiment != "NEUTRAL":
            print(f"  ✓ Passes strict criteria!")
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
            print(f"  ❌ Rejected: (Impact/Quality/Sentiment too low or NEUTRAL)")
        time.sleep(0.5)
    print(f"\n{'='*60}\nSCAN SUMMARY\n{'='*60}\n✅ Stocks scanned: {len(STOCKS_TO_MONITOR)}\n🎯 Premium opportunities found: {opportunities_found}\n")
    print(f"⏰ Scan completed at {datetime.utcnow().strftime('%H:%M:%S UTC')}\n{'='*60}\n")

# ════════════════════════════════
# RUN THE SCANNER
# ════════════════════════════════

if __name__ == "__main__":
    scan_all_stocks()
