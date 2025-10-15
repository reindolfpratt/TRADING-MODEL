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

# Track alerted stocks - ONE ALERT PER DAY MAX
alerted_today = {}

# High-impact keywords for filtering
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

# Noise keywords to IGNORE (too common, not actionable)
NOISE_KEYWORDS = [
    'analyst says', 'could', 'might', 'may', 'opinion',
    'watch', 'what to know', 'should you', 'stock analysis',
    'technical analysis', 'chart', 'levels to watch'
]

# ═══════════════════════════════════════════════════════════
# FUNCTIONS
# ═══════════════════════════════════════════════════════════

def get_latest_news_rss(symbol):
    """Get latest news from Yahoo Finance RSS feed"""
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        feed = feedparser.parse(url)
        
        articles = []
        for entry in feed.entries[:5]:  # Get more articles for better analysis
            articles.append({
                'title': entry.title,
                'link': entry.link,
                'published': entry.get('published', '')
            })
        
        return articles
    except Exception as e:
        print(f"Error fetching RSS for {symbol}: {e}")
        return []


def calculate_news_quality_score(headlines):
    """
    Calculate news quality score based on multiple factors
    Returns: (quality_score, has_high_impact_keywords, is_noise)
    """
    if not headlines:
        return 0, False, True
    
    text = " ".join([h['title'].lower() for h in headlines])
    
    # Check for noise - REJECT if found
    noise_count = sum(1 for keyword in NOISE_KEYWORDS if keyword in text)
    if noise_count > 0:
        return 0, False, True
    
    # Count high-impact keywords
    bullish_count = sum(1 for keyword in BULLISH_KEYWORDS if keyword in text)
    bearish_count = sum(1 for keyword in BEARISH_KEYWORDS if keyword in text)
    
    has_high_impact = (bullish_count >= 2 or bearish_count >= 2)
    
    # Quality scoring
    quality_score = 0
    
    # Multiple articles about same topic = higher quality
    if len(headlines) >= 3:
        quality_score += 3
    
    # Strong keywords present
    quality_score += min(bullish_count + bearish_count, 5)
    
    # Recency bonus (if published today)
    try:
        if headlines[0].get('published'):
            pub_date = datetime.strptime(headlines[0]['published'], '%a, %d %b %Y %H:%M:%S %z')
            if (datetime.now(pub_date.tzinfo) - pub_date).days == 0:
                quality_score += 2
    except:
        pass
    
    return quality_score, has_high_impact, False


def analyze_sentiment_vader(headlines):
    """Analyze sentiment using VADER AI with strict thresholds"""
    
    if not headlines:
        return "NEUTRAL", 0, "No news available", 0
    
    # Calculate news quality first
    quality_score, has_high_impact, is_noise = calculate_news_quality_score(headlines)
    
    # REJECT noise immediately
    if is_noise:
        return "NEUTRAL", 0, "Low quality news", 0
    
    text = " ".join([h['title'] for h in headlines])
    scores = analyzer.polarity_scores(text)
    compound = scores['compound']
    
    # MUCH STRICTER thresholds
    if compound >= 0.65 and has_high_impact:  # Was 0.5, now 0.65
        sentiment = "BULLISH"
        impact = min(10, int((compound - 0.65) * 25) + 7)
    elif compound <= -0.65 and has_high_impact:  # Was -0.5, now -0.65
        sentiment = "BEARISH"
        impact = min(10, int((-compound - 0.65) * 25) + 7)
    else:
        sentiment = "NEUTRAL"
        impact = max(0, quality_score - 2)  # Lower baseline impact
    
    # Apply quality multiplier
    impact = min(10, int(impact * (quality_score / 10)))
    
    reasoning = headlines[0]['title'][:120] if headlines else "No specific news"
    
    return sentiment, impact, reasoning, quality_score


def get_price_momentum(symbol):
    """Check if price is already moving (confirmation)"""
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
    """Check if we already alerted this stock today"""
    today = datetime.now().date()
    
    if symbol in alerted_today:
        last_alert_date = alerted_today[symbol]
        if last_alert_date == today:
            return False  # Already alerted today
    
    return True  # OK to alert


def send_telegram_alert(symbol, action, price, impact, reasoning, momentum, quality_score):
    """Send instant Telegram alert with trade details"""
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram not configured - Would send: {symbol} {action}")
        return
    
    momentum_emoji = "📈" if momentum > 0 else "📉"
    
    if "BUY LONG" in action:
        target1 = round(price * 1.03, 2)
        target2 = round(price * 1.05, 2)
        stop = round(price * 0.985, 2)
        
        message = f"""🚨 *PREMIUM TRADE ALERT* 🚨

{action} *{symbol}*

💰 Entry Price: ${price}
{momentum_emoji} Momentum: {momentum:+.2f}%

*PROFIT TARGETS:*
  • TP1: ${target1} (+3%)
  • TP2: ${target2} (+5%)

🛑 *STOP LOSS:* ${stop} (-1.5%)

📊 *Quality Score:* {quality_score}/10
⚡ *Impact:* {impact}/10

📰 *CATALYST:*
_{reasoning}_

🕐 {datetime.now().strftime('%H:%M:%S')}"""

    else:
        target1 = round(price * 0.97, 2)
        target2 = round(price * 0.95, 2)
        stop = round(price * 1.015, 2)
        
        message = f"""🚨 *PREMIUM TRADE ALERT* 🚨

{action} *{symbol}*

💰 Entry Price: ${price}
{momentum_emoji} Momentum: {momentum:+.2f}%

*PROFIT TARGETS:*
  • TP1: ${target1} (-3%)
  • TP2: ${target2} (-5%)

🛑 *STOP LOSS:* ${stop} (+1.5%)

📊 *Quality Score:* {quality_score}/10
⚡ *Impact:* {impact}/10

📰 *CATALYST:*
_{reasoning}_

🕐 {datetime.now().strftime('%H:%M:%S')}"""

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
    """Main scanner - STRICT filtering for premium trades only"""
    
    print(f"\n{'='*60}")
    print(f"🔍 PREMIUM MARKET SCAN - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"📊 Monitoring {len(STOCKS_TO_MONITOR)} stocks\n")
    
    # Check Telegram config
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        print(f"✅ Telegram configured (Token: {TELEGRAM_BOT_TOKEN[:10]}...)")
    else:
        print(f"⚠️ WARNING: Telegram NOT configured!")
        print(f"   TELEGRAM_BOT_TOKEN: {'SET' if TELEGRAM_BOT_TOKEN else 'MISSING'}")
        print(f"   TELEGRAM_CHAT_ID: {'SET' if TELEGRAM_CHAT_ID else 'MISSING'}")
    print()
    
    opportunities_found = 0
    detailed_results = []
    
    for symbol in STOCKS_TO_MONITOR:
        print(f"{'─'*60}")
        print(f"Scanning {symbol}...")
        
        # Check daily cooldown first
        if not check_daily_cooldown(symbol):
            print(f"  ⏭️ Already alerted today - skipping")
            continue
        
        news = get_latest_news_rss(symbol)
        
        if not news:
            print(f"  ℹ️ No news found")
            continue
        
        print(f"  📰 Found {len(news)} articles")
        for i, article in enumerate(news[:2], 1):
            print(f"     {i}. {article['title'][:80]}...")
        
        sentiment, impact, reasoning, quality_score = analyze_sentiment_vader(news)
        
        print(f"  📊 Analysis:")
        print(f"     Sentiment: {sentiment}")
        print(f"     Impact: {impact}/10")
        print(f"     Quality: {quality_score}/10")
        
        # Store for summary
        detailed_results.append({
            'symbol': symbol,
            'sentiment': sentiment,
            'impact': impact,
            'quality': quality_score,
            'news_count': len(news)
        })
        
        # STRICT CRITERIA: Impact 9+, Quality 6+, Strong sentiment
        if impact >= 9 and quality_score >= 6 and sentiment != "NEUTRAL":
            print(f"  ✓ Passes strict criteria!")
            
            price, momentum = get_price_momentum(symbol)
            
            if price:
                print(f"  💰 Price: ${price}, Momentum: {momentum:+.2f}%")
                
                # Additional momentum filter
                if sentiment == "BULLISH" and momentum < -2:
                    print(f"  ⚠️ Negative momentum {momentum}% conflicts with BULLISH - REJECTED")
                    continue
                
                if sentiment == "BEARISH" and momentum > 2:
                    print(f"  ⚠️ Positive momentum {momentum}% conflicts with BEARISH - REJECTED")
                    continue
                
                print(f"  🎯 PREMIUM OPPORTUNITY CONFIRMED!")
                print(f"  📤 Sending Telegram alert...")
                
                if sentiment == "BULLISH":
                    action = "🟢 BUY LONG"
                else:
                    action = "🔴 SHORT"
                
                send_telegram_alert(symbol, action, price, impact, reasoning, momentum, quality_score)
                
                # Mark as alerted TODAY
                alerted_today[symbol] = datetime.now().date()
                
                opportunities_found += 1
                time.sleep(2)
            else:
                print(f"  ❌ Price unavailable")
        else:
            reasons = []
            if impact < 9:
                reasons.append(f"Impact too low ({impact}<9)")
            if quality_score < 6:
                reasons.append(f"Quality too low ({quality_score}<6)")
            if sentiment == "NEUTRAL":
                reasons.append("Sentiment is NEUTRAL")
            print(f"  ❌ Rejected: {', '.join(reasons)}")
        
        time.sleep(0.5)
    
    print(f"\n{'='*60}")
    print(f"SCAN SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Stocks scanned: {len(STOCKS_TO_MONITOR)}")
    print(f"🎯 Premium opportunities found: {opportunities_found}")
    
    if opportunities_found == 0:
        print(f"\n📊 Top candidates (didn't meet threshold):")
        sorted_results = sorted(detailed_results, key=lambda x: (x['impact'], x['quality']), reverse=True)
        for i, result in enumerate(sorted_results[:5], 1):
            print(f"   {i}. {result['symbol']}: {result['sentiment']} "
                  f"(Impact: {result['impact']}/10, Quality: {result['quality']}/10)")
    
    print(f"\n⏰ Scan completed at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════
# RUN THE SCANNER
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    scan_all_stocks()
