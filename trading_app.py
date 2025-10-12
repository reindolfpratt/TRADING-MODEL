import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Page configuration
st.set_page_config(
    page_title="Reindolf AI Trading Assistant",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for beautiful UI
st.markdown("""
    <style>
    .stApp {
        background: #ffffff;  /* White background */
    }
    h1 {
        color: #2c3e50;
        text-align: center;
        font-size: 3rem;
        font-weight: 700;
    }
    .stButton>button {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 10px 30px;
        border-radius: 25px;
        font-weight: 600;
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)


# Enhanced Trading Strategy Class (same as before)
class EnhancedTradingStrategy:
    def __init__(self, symbol, start_date, end_date, short_window=20, 
                 long_window=50, initial_capital=10000, 
                 risk_per_trade=0.02, stop_loss_pct=0.05):
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.short_window = short_window
        self.long_window = long_window
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.stop_loss_pct = stop_loss_pct
        self.data = None
        
    def fetch_data(self):
        try:
            self.data = yf.download(self.symbol, start=self.start_date, 
                                   end=self.end_date, progress=False)
            if self.data.empty:
                return False
            if isinstance(self.data.columns, pd.MultiIndex):
                self.data.columns = self.data.columns.get_level_values(0)
            return True
        except:
            return False
    
    def calculate_indicators(self):
        if self.data is None:
            return
        
        self.data['Short_MA'] = self.data['Close'].rolling(window=self.short_window).mean()
        self.data['Long_MA'] = self.data['Close'].rolling(window=self.long_window).mean()
        
        self.data['High-Low'] = self.data['High'] - self.data['Low']
        self.data['High-Close'] = np.abs(self.data['High'] - self.data['Close'].shift())
        self.data['Low-Close'] = np.abs(self.data['Low'] - self.data['Close'].shift())
        self.data['ATR'] = self.data[['High-Low', 'High-Close', 'Low-Close']].max(axis=1).rolling(window=14).mean()
        
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.data['RSI'] = 100 - (100 / (1 + rs))
        
        self.data['Volume_MA'] = self.data['Volume'].rolling(window=20).mean()
        
    def generate_signals(self):
        if self.data is None:
            return
        
        self.data['Signal'] = 0
        
        bullish_cross = (self.data['Short_MA'] > self.data['Long_MA'])
        bearish_cross = (self.data['Short_MA'] < self.data['Long_MA'])
        
        rsi_bullish = (self.data['RSI'] > 40) & (self.data['RSI'] < 70)
        rsi_bearish = (self.data['RSI'] < 60) | (self.data['RSI'] > 70)
        
        volume_confirmed = (self.data['Volume'].values > (self.data['Volume_MA'].values * 0.8))
        
        self.data.loc[bullish_cross & rsi_bullish & volume_confirmed, 'Signal'] = 1
        self.data.loc[bearish_cross & rsi_bearish, 'Signal'] = -1
        
    def execute_backtest(self):
        if self.data is None:
            return [], self.initial_capital
        
        buy_signals = self.data[self.data['Signal'].diff() == 1]
        sell_signals = self.data[self.data['Signal'].diff() == -1]
        
        trades = []
        capital = self.initial_capital
        
        buy_idx = 0
        sell_idx = 0
        
        while buy_idx < len(buy_signals) and sell_idx < len(sell_signals):
            buy_date = buy_signals.index[buy_idx]
            
            valid_sells = sell_signals[sell_signals.index > buy_date]
            if len(valid_sells) == 0:
                break
                
            sell_date = valid_sells.index[0]
            sell_idx = sell_signals.index.get_loc(sell_date)
            
            buy_price = float(buy_signals.loc[buy_date, 'Close'])
            sell_price = float(sell_signals.loc[sell_date, 'Close'])
            atr = float(buy_signals.loc[buy_date, 'ATR'])
            
            risk_amount = capital * self.risk_per_trade
            position_sie = int((risk_amount / (atr * 2)) if atr > 0 else 100)
            position_sie = max(1, min(position_sie, int(capital / buy_price)))
            
            profit_loss = (sell_price - buy_price) * position_sie
            profit_pct = ((sell_price - buy_price) / buy_price) * 100
            capital += profit_loss
            
            hold_days = (sell_date - buy_date).days
            
            trades.append({
                'buy_date': buy_date.date(),
                'buy_price': round(buy_price, 2),
                'sell_date': sell_date.date(),
                'sell_price': round(sell_price, 2),
                'position_sie': position_sie,
                'profit_loss': round(profit_loss, 2),
                'profit_pct': round(profit_pct, 2),
                'hold_days': hold_days,
                'capital': round(capital, 2)
            })
            
            buy_idx += 1
            sell_idx += 1
        
        return trades, capital
    
    def calculate_metrics(self, trades, final_capital):
        if not trades:
            return None
        
        df_trades = pd.DataFrame(trades)
        
        winning_trades = df_trades[df_trades['profit_loss'] > 0]
        losing_trades = df_trades[df_trades['profit_loss'] < 0]
        
        win_rate = (len(winning_trades) / len(df_trades)) * 100 if len(df_trades) > 0 else 0
        
        avg_win = float(winning_trades['profit_loss'].mean()) if len(winning_trades) > 0 else 0
        avg_loss = float(abs(losing_trades['profit_loss'].mean())) if len(losing_trades) > 0 else 0
        
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        
        total_return = final_capital - self.initial_capital
        total_return_pct = ((final_capital - self.initial_capital) / self.initial_capital) * 100
        
        returns = df_trades['profit_pct'].values
        sharpe = float((returns.mean() / returns.std())) if returns.std() > 0 else 0
        
        capital_curve = df_trades['capital'].values
        running_max = np.maximum.accumulate(capital_curve)
        drawdown = (capital_curve - running_max) / running_max * 100
        max_drawdown = float(drawdown.min())
        
        return {
            'total_trades': len(df_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'total_return': round(total_return, 2),
            'total_return_pct': round(total_return_pct, 2),
            'sharpe_ratio': round(sharpe, 2),
            'max_drawdown': round(max_drawdown, 2),
            'avg_hold_days': round(float(df_trades['hold_days'].mean()), 1)
        }
    
    def get_current_signal(self):
        if self.data is None or len(self.data) == 0:
            return None
        
        latest = self.data.iloc[-1]
        
        return {
            'signal': int(latest['Signal']),
            'price': float(latest['Close']),
            'short_ma': float(latest['Short_MA']),
            'long_ma': float(latest['Long_MA']),
            'rsi': float(latest['RSI']),
            'volume': float(latest['Volume']),
            'volume_ma': float(latest['Volume_MA']),
            'atr': float(latest['ATR']),
            'date': self.data.index[-1].date()
        }

# Streamlit App
def main():
    st.markdown("<h1>Reindolf AI Trading Assistant</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #a0a0a0;'>Powered by Moving Average Crossover Strategy with RSI & Volume Filters</p>", unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/stocks.png", width=80)
        st.title("⚙️ Configuration")
        
        symbol = st.text_input("Stock Symbol", value="AAPL", help="Enter ticker symbol (e.g., AAPL, TSLA, GME)").upper()
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=365))
        with col2:
            end_date = st.date_input("End Date", value=datetime.now())
        
        initial_capital = st.number_input("💰 Initial Capital ($)", min_value=100, value=10000, step=100)
        
        st.divider()
        
        with st.expander("Advanced Settings"):
            short_window = st.slider("Short MA Window", 5, 50, 20)
            long_window = st.slider("Long MA Window", 20, 200, 50)
            risk_per_trade = st.slider("Risk Per Trade (%)", 1, 10, 2) / 100
        
        analyze_button = st.button("Analyse Stock", use_container_width=True)
    
    # Main content
    if analyze_button:
        with st.spinner(f"🔍 Analysing {symbol}..."):
            strategy = EnhancedTradingStrategy(
                symbol=symbol,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                short_window=short_window,
                long_window=long_window,
                initial_capital=initial_capital,
                risk_per_trade=risk_per_trade
            )
            
            if not strategy.fetch_data():
                st.error(f"❌ Could not fetch data for {symbol}. Please check the symbol and try again.")
                return
            
            strategy.calculate_indicators()
            strategy.generate_signals()
            trades, final_capital = strategy.execute_backtest()
            metrics = strategy.calculate_metrics(trades, final_capital)
            current_signal = strategy.get_current_signal()
            
            # Current Signal Section
            st.markdown("### 🎯 Current Recommendation")
            
            if current_signal:
                signal_val = current_signal['signal']
                
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    if signal_val == 1:
                        st.success("### 🟢 BUY SIGNAL")
                        st.write("**Strategy suggests BUYING this stock**")
                        st.write("Short-term trend crossed above long-term trend (bullish)")
                    elif signal_val == -1:
                        st.error("### 🔴 SELL SIGNAL")
                        st.write("**Strategy suggests SELLING or staying OUT**")
                        st.write("Short-term trend crossed below long-term trend (bearish)")
                    else:
                        st.warning("### ⚪ WAIT")
                        st.write("**Strategy suggests WAITING (no clear signal)**")
                        st.write("Conditions not met for buy or sell")
                
                with col2:
                    st.metric("Current Price", f"${current_signal['price']:.2f}")
                    st.metric("RSI", f"{current_signal['rsi']:.2f}")
                
                with col3:
                    trend = "📈 Uptrend" if current_signal['short_ma'] > current_signal['long_ma'] else "📉 Downtrend"
                    st.metric("Trend", trend)
                    vol_ratio = (current_signal['volume'] / current_signal['volume_ma']) * 100
                    st.metric("Volume", f"{vol_ratio:.0f}%")
            
            st.divider()
            
            # Performance Metrics
            if metrics:
                st.markdown("### 📊 Strategy Performance")
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Total Return", f"${metrics['total_return']:,.2f}", 
                             delta=f"{metrics['total_return_pct']:.2f}%")
                
                with col2:
                    st.metric("Win Rate", f"{metrics['win_rate']}%", 
                             delta=f"{metrics['winning_trades']}W / {metrics['losing_trades']}L")
                
                with col3:
                    st.metric("Profit Factor", f"{metrics['profit_factor']:.2f}")
                
                with col4:
                    st.metric("Sharpe Ratio", f"{metrics['sharpe_ratio']:.2f}")
                
                st.divider()
                
                # Interactive Chart with Plotly
                st.markdown("### 📈 Price Chart with Signals")
                
                fig = make_subplots(
                    rows=3, cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.05,
                    row_heights=[0.6, 0.2, 0.2],
                    subplot_titles=('Price & Moving Averages', 'RSI', 'Volume')
                )
                
                # Price and MAs
                fig.add_trace(go.Scatter(x=strategy.data.index, y=strategy.data['Close'], 
                                        name='Close', line=dict(color='#667eea', width=2)), row=1, col=1)
                fig.add_trace(go.Scatter(x=strategy.data.index, y=strategy.data['Short_MA'], 
                                        name=f'{short_window}MA', line=dict(color='#f093fb', width=1.5)), row=1, col=1)
                fig.add_trace(go.Scatter(x=strategy.data.index, y=strategy.data['Long_MA'], 
                                        name=f'{long_window}MA', line=dict(color='#4facfe', width=1.5)), row=1, col=1)
                
                # Buy/Sell signals
                buy_signals = strategy.data[strategy.data['Signal'].diff() == 1]
                sell_signals = strategy.data[strategy.data['Signal'].diff() == -1]
                
                fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], 
                                        mode='markers', name='Buy', 
                                        marker=dict(color='green', size=10, symbol='triangle-up')), row=1, col=1)
                fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], 
                                        mode='markers', name='Sell', 
                                        marker=dict(color='red', size=10, symbol='triangle-down')), row=1, col=1)
                
                # RSI
                fig.add_trace(go.Scatter(x=strategy.data.index, y=strategy.data['RSI'], 
                                        name='RSI', line=dict(color='purple', width=1.5)), row=2, col=1)
                fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
                
                # Volume
                colors = ['green' if strategy.data['Close'].iloc[i] >= strategy.data['Open'].iloc[i] 
                         else 'red' for i in range(len(strategy.data))]
                fig.add_trace(go.Bar(x=strategy.data.index, y=strategy.data['Volume'], 
                                    name='Volume', marker_color=colors), row=3, col=1)
                
                fig.update_layout(
                    height=800,
                    template='plotly_dark',
                    showlegend=True,
                    hovermode='x unified'
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Trade History
                st.markdown("### 📜 Trade History")
                
                if trades:
                    df_trades = pd.DataFrame(trades)
                    df_trades['emoji'] = df_trades['profit_loss'].apply(lambda x: '🟢' if x > 0 else '🔴')
                    df_trades = df_trades[['emoji', 'buy_date', 'buy_price', 'sell_date', 'sell_price', 
                                          'position_size', 'profit_loss', 'profit_pct', 'hold_days']]
                    st.dataframe(df_trades, use_container_width=True, hide_index=True)
                else:
                    st.info("No trades generated in this period.")
            
            st.divider()
            st.warning("⚠️ **Disclaimer**: This is NOT financial advice. Always do your own research and never invest more than you can afford to lose. Past performance does NOT guarantee future results.")

if __name__ == "__main__":
    main()
