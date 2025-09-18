
import asyncio
import aiohttp
from datetime import datetime
import sqlite3
import json
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button
import matplotlib.dates as mdates
import threading

class CryptoArbitrageSimulator:
    def __init__(self, initial_balance=1000000, trading_fee=0.00001):
        self.exchanges = {
            'binance': {'ws_url': 'wss://stream.binance.com:9443/ws/btcusdt@ticker', 'rest_url': 'https://api.binance.com/api/v3/ticker/bookTicker?symbol=BTCUSDT'},
            'kraken': {'ws_url': 'wss://ws.kraken.com', 'rest_url': 'https://api.kraken.com/0/public/Ticker?pair=XBTUSD'},
            'coinbase': {'ws_url': 'wss://ws-feed.exchange.coinbase.com', 'rest_url': 'https://api.exchange.coinbase.com/products/BTC-USD/book'}
        }
        self.prices = {exchange: {'bid': 0, 'ask': 0, 'last': 0} for exchange in self.exchanges}
        self.arbitrage_opportunities = []
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.btc_balance = 0
        self.trading_fee = trading_fee
        self.running = False
        self.websockets = {}
        self.loop = None
        self.toggle_state = False
        
        # Setup database
        self.setup_database()
        
        # Setup matplotlib figure
        self.setup_plots()

    def setup_database(self):
        # Create a thread-safe connection
        self.conn = sqlite3.connect('arbitrage.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Create tables if they don't exist
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                exchange TEXT,
                bid REAL,
                ask REAL,
                last REAL
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS arbitrage_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                buy_exchange TEXT,
                sell_exchange TEXT,
                buy_price REAL,
                sell_price REAL,
                spread REAL,
                potential_profit REAL,
                executed INTEGER DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                type TEXT,
                exchange TEXT,
                price REAL,
                amount REAL,
                total REAL,
                fee REAL
            )
        ''')
        
        self.conn.commit()
    
    def setup_plots(self):
        plt.style.use('dark_background')
        self.fig = plt.figure(figsize=(15, 10))
        self.fig.suptitle('Cryptocurrency Arbitrage & Market Maker Simulator', fontsize=16, fontweight='bold')
        
        # Create subplots with adjusted layout
        self.ax1 = plt.subplot2grid((4, 4), (0, 0), colspan=2, rowspan=2)
        self.ax2 = plt.subplot2grid((4, 4), (0, 2), colspan=2, rowspan=1)
        self.ax3 = plt.subplot2grid((4, 4), (1, 2), colspan=2, rowspan=1)
        self.ax4 = plt.subplot2grid((4, 4), (2, 0), colspan=4, rowspan=2)
        
        # Add buttons
        ax_start = plt.axes([0.1, 0.02, 0.1, 0.05])
        ax_stop = plt.axes([0.25, 0.02, 0.1, 0.05])
        ax_execute = plt.axes([0.4, 0.02, 0.1, 0.05])
        ax_clear = plt.axes([0.55, 0.02, 0.1, 0.05])

        self.start_button = Button(ax_start, 'Start', color="0.5", hovercolor="0.4")
        self.stop_button = Button(ax_stop, 'Stop', color="0.5", hovercolor="0.4")
        self.execute_button = Button(ax_execute, 'Execute Best', color="0.5", hovercolor="0.4")
        self.clear_button = Button(ax_clear, 'Clear DB', color="0.5", hovercolor="0.4")
        
        self.start_button.on_clicked(self.start_simulation)
        self.stop_button.on_clicked(self.stop_simulation)
        self.execute_button.on_clicked(self.execute_best_arbitrage)
        self.clear_button.on_clicked(self.clear_database)
        
        # Initialize plots - use spread-focused visualization
        self.exchanges_list = list(self.exchanges.keys())
        self.spread_bars = []
        
        for i, exchange in enumerate(self.exchanges_list):
            bar = self.ax1.bar(i, 0, color='blue', alpha=0.6, label='Bid-Ask Spread' if i == 0 else "")
            self.spread_bars.append(bar[0])
        
        self.ax1.set_title('Bid-Ask Spread by Exchange')
        self.ax1.set_xticks(range(len(self.exchanges_list)))
        self.ax1.set_xticklabels([ex.capitalize() for ex in self.exchanges_list])
        self.ax1.set_ylim(1, 10)
        self.ax1.set_ylabel("Spread (USD)")
        self.ax1.axhline(y=0, color='white', linestyle='-', alpha=0.3)
        

        self.ax2.set_title('Account Balance')
        self.balance_text = self.ax2.text(0.5, 0.5, f'USD: ${self.balance:.2f}\nBTC: {self.btc_balance:.6f}', 
                                        ha='center', va='center', fontsize=12)
        self.ax2.axis('off')
        
        self.ax3.set_title('Best Arbitrage Opportunity')
        self.arbitrage_text = self.ax3.text(0.5, 0.5, 'No opportunities found', 
                                        ha='center', va='center', fontsize=10)
        self.ax3.axis('off')
        
        self.ax4.set_title('Price Disparity Across Exchanges')
        self.ax4.set_ylabel('Price (USD)')
        self.ax4.set_xlabel('Time')
        
        # Adjust layout to prevent overlap
        plt.subplots_adjust(bottom=0.15, top=0.9, hspace=0.5)
    


    def update_plots(self, frame=None):
        """Update the matplotlib plots"""
        # Update spread bars
        for i, exchange in enumerate(self.exchanges_list):
            if self.prices[exchange]['bid'] > 100 and self.prices[exchange]['ask'] > 100:
                spread = self.prices[exchange]['ask'] - self.prices[exchange]['bid']
                self.spread_bars[i].set_height(spread)

        # Update balance text
        valid_prices = [self.prices[ex]['last'] for ex in self.exchanges if self.prices[ex]['last'] > 0]
        avg_price = sum(valid_prices) / len(valid_prices) if valid_prices else 0
        total_value = self.balance + self.btc_balance * avg_price
        self.balance_text.set_text(f'USD: ${self.balance:.2f}\nBTC: {self.btc_balance:.6f}\nTotal: ${total_value:.2f}')
        
        # Update arbitrage opportunities text
        if self.arbitrage_opportunities:
            best = self.arbitrage_opportunities[0]
            self.arbitrage_text.set_text(f"Best: {best['buy_exchange']}→{best['sell_exchange']}\n"
                                        f"Spread: {best['spread']:.2f}%\n"
                                        f"Profit: ${best['potential_profit']:.2f}")
        else:
            self.arbitrage_text.set_text('No opportunities found')
        
        # Update price disparity chart
        self.ax4.clear()
        
        # Get historical data from database
        try:
            with threading.Lock():
                min_data_points = float('inf')
                prices_data = {}
                timestamps = None
                
                for exchange in self.exchanges:
                    self.cursor.execute(
                        "SELECT timestamp, last FROM price_data WHERE exchange = ? ORDER BY timestamp DESC LIMIT 20",
                        (exchange,)
                    )
                    data = self.cursor.fetchall()
                    
                    if len(data) < min_data_points:
                        min_data_points = len(data)
                    
                    prices_data[exchange] = [row[1] for row in data]
                    
                    if timestamps is None:
                        timestamps = [row[0] for row in data]
                
                if min_data_points > 0 and timestamps:
                    timestamps.reverse()
                    timestamps = timestamps[:min_data_points]
                    
                    try:
                        timestamps = [datetime.strptime(ts.split('.')[0], '%Y-%m-%d %H:%M:%S') for ts in timestamps]
                    except:
                        try:
                            timestamps = [datetime.strptime(ts, '%Y-%m-%d %H:%M:%S') for ts in timestamps]
                        except:
                            timestamps = list(range(min_data_points))
                    
                    for exchange in self.exchanges:
                        if len(prices_data[exchange]) >= min_data_points:
                            exchange_prices = prices_data[exchange][:min_data_points]
                            exchange_prices.reverse()
                            self.ax4.plot(timestamps, exchange_prices, label=exchange.capitalize(), linewidth=2)
                    
                    self.ax4.set_ylabel('Price (USD)')
                    self.ax4.set_title('Price Disparity Across Exchanges')
                    self.ax4.set_ylim(self.prices[exchange]['bid']-200,self.prices[exchange]['ask']+200)
                    self.ax4.legend()
                    
                    if isinstance(timestamps[0], datetime):
                        self.ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                        plt.setp(self.ax4.xaxis.get_majorticklabels(), rotation=45)
        
        except Exception as e:
            print(f"Error updating price disparity chart: {e}")
        
        self.fig.canvas.draw_idle()
        return self.spread_bars + [self.balance_text, self.arbitrage_text]

    async def connect_to_exchange(self, exchange):
        """Connect to exchange WebSocket and start receiving data"""
        print(f"Attempting to connect to {exchange} WebSocket...")
        ws_url = self.exchanges[exchange]['ws_url']
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url) as ws:
                    self.websockets[exchange] = ws
                    
                    # Send subscription message for Kraken and Coinbase
                    if exchange == 'kraken':
                        subscribe_msg = {
                            "event": "subscribe",
                            "pair": ["XBT/USD"],
                            "subscription": {"name": "ticker"}
                        }
                        await ws.send_json(subscribe_msg)
                    elif exchange == 'coinbase':
                        subscribe_msg = {
                            "type": "subscribe",
                            "product_ids": ["BTC-USD"],
                            "channels": ["ticker"]
                        }
                        await ws.send_json(subscribe_msg)
                    
                    async for msg in ws:
                        if not self.running:
                            break
                            
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            self.process_message(exchange, data)
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
        except Exception as e:
            print(f"Error connecting to {exchange}: {e}")
            # Fall back to REST API if WebSocket fails
            await self.poll_rest_api(exchange)

    async def poll_rest_api(self, exchange):
        """Poll REST API as fallback if WebSocket fails"""
        print(f"WebSocket failed, polling REST API for {exchange}")
        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.exchanges[exchange]['rest_url']) as response:
                        data = await response.json()
                        self.process_rest_data(exchange, data)
            except Exception as e:
                print(f"Error polling REST API for {exchange}: {e}")
            
            await asyncio.sleep(5)  # Poll every 5 seconds

    def process_message(self, exchange, data):
        """Process WebSocket message from exchange"""
        if exchange == 'binance':
            if 'b' in data and 'a' in data and 'c' in data:
                self.prices[exchange]['bid'] = float(data['b'])
                self.prices[exchange]['ask'] = float(data['a'])
                self.prices[exchange]['last'] = float(data['c'])
                
        elif exchange == 'kraken':
            if isinstance(data, list) and len(data) > 1:
                ticker_data = data[1]
                if 'b' in ticker_data and 'a' in ticker_data and 'c' in ticker_data:
                    self.prices[exchange]['bid'] = float(ticker_data['b'][0])
                    self.prices[exchange]['ask'] = float(ticker_data['a'][0])
                    self.prices[exchange]['last'] = float(ticker_data['c'][0])
                    
        elif exchange == 'coinbase':
            if data['type'] == 'ticker':
                self.prices[exchange]['bid'] = float(data['best_bid'])
                self.prices[exchange]['ask'] = float(data['best_ask'])
                self.prices[exchange]['last'] = float(data['price'])
        
        # print(f"{exchange}: Bid=${self.prices[exchange]['bid']}, Ask=${self.prices[exchange]['ask']}")
        # Save to database
        self.save_price_data(exchange)

    def process_rest_data(self, exchange, data):
        """Process REST API response"""
        try:
            if exchange == 'binance':
                # Use bookTicker endpoint for bid/ask
                self.prices[exchange]['bid'] = float(data['bidPrice'])
                self.prices[exchange]['ask'] = float(data['askPrice'])
                self.prices[exchange]['last'] = (float(data['bidPrice']) + float(data['askPrice'])) / 2
                
            elif exchange == 'kraken':
                # Use Ticker endpoint for bid/ask
                result = data['result']['XXBTZUSD']
                self.prices[exchange]['bid'] = float(result['b'][0])
                self.prices[exchange]['ask'] = float(result['a'][0])
                self.prices[exchange]['last'] = float(result['c'][0])
                    
            elif exchange == 'coinbase':
                # Use book endpoint for bid/ask
                self.prices[exchange]['bid'] = float(data['bids'][0][0]) if data['bids'] else 0
                self.prices[exchange]['ask'] = float(data['asks'][0][0]) if data['asks'] else 0
                self.prices[exchange]['last'] = (self.prices[exchange]['bid'] + self.prices[exchange]['ask']) / 2
                
            print(f"REST {exchange}: Bid=${self.prices[exchange]['bid']}, Ask=${self.prices[exchange]['ask']}")
            # Save to database
            self.save_price_data(exchange)
        except Exception as e:
            print(f"Error processing REST data for {exchange}: {e}")

    def save_price_data(self, exchange):
        try:
            if self.prices[exchange]['bid'] > 100 and self.prices[exchange]['ask'] > 100:
                # Only save realistic prices to database
                with threading.Lock():
                    cursor = self.conn.cursor()
                    cursor.execute(
                        "INSERT INTO price_data (exchange, bid, ask, last) VALUES (?, ?, ?, ?)",
                        (exchange, self.prices[exchange]['bid'], self.prices[exchange]['ask'], self.prices[exchange]['last'])
                    )
                    self.conn.commit()
        except Exception as e:
            print(f"Error saving price data: {e}")

    def find_arbitrage_opportunities(self):
        # Add this at the start of find_arbitrage_opportunities for testing
        if all(self.prices[ex]['bid'] < 100 for ex in self.exchanges):
            print("No price data received - using arbitrage Test data")
            # Create REAL arbitrage opportunities (bigger spreads)
            self.prices['binance'] = {'bid': 115000, 'ask': 115010, 'last': 115005}
            self.prices['kraken'] = {'bid': 115200, 'ask': 115210, 'last': 115205}  # 200 USD higher!
            self.prices['coinbase'] = {'bid': 114800, 'ask': 114810, 'last': 114805}  # 200 USD lower!

        """Find arbitrage opportunities across exchanges"""
        opportunities = []
        
        print(f"\n=== ARBITRAGE CALCULATION ===")
        print(f"Prices: Binance={self.prices['binance']}, Kraken={self.prices['kraken']}, Coinbase={self.prices['coinbase']}")
        
        # Check all possible exchange pairs
        for buy_exchange in self.exchanges:
            for sell_exchange in self.exchanges:
                if buy_exchange != sell_exchange:
                    buy_price = self.prices[buy_exchange]['ask']
                    sell_price = self.prices[sell_exchange]['bid']
                    
                    if buy_price > 100 and sell_price > 100:  # Only consider realistic Bitcoin prices
                        spread = ((sell_price - buy_price) / buy_price) * 100
                        
                        # Calculate potential profit after fees
                        trade_amount = self.balance / buy_price  # Use all USD balance
                        buy_cost = buy_price * trade_amount #* (1 + self.trading_fee)
                        sell_revenue = sell_price * trade_amount #* (1 - self.trading_fee)
                        potential_profit = sell_revenue - buy_cost
                        
                        print(f"{buy_exchange}→{sell_exchange}: Buy@{buy_price} → Sell@{sell_price}")
                        print(f"  Spread: {spread:.3f}%, Profit: ${potential_profit:.2f}")
                        
                        if spread > 0.00001 and potential_profit > 0:
                            opportunities.append({
                                'buy_exchange': buy_exchange,
                                'sell_exchange': sell_exchange,
                                'buy_price': buy_price,
                                'sell_price': sell_price,
                                'spread': spread,
                                'potential_profit': potential_profit
                            })
                            print(f"  ✓ ARBITRAGE FOUND!")
                            
                        # else:
                        #     print(f"  ✗ No arbitrage (spread: {spread:.3f}%, profit: ${potential_profit:.2f})")
        
        # Sort by highest spread
        opportunities.sort(key=lambda x: x['spread'], reverse=True)
        self.arbitrage_opportunities = opportunities
        
        # Save to database
        for opportunity in opportunities:
            try:
                self.cursor.execute(
                    "INSERT INTO arbitrage_opportunities (buy_exchange, sell_exchange, buy_price, sell_price, spread, potential_profit) VALUES (?, ?, ?, ?, ?, ?)",
                    (opportunity['buy_exchange'], opportunity['sell_exchange'], opportunity['buy_price'], 
                     opportunity['sell_price'], opportunity['spread'], opportunity['potential_profit'])
                )
                self.conn.commit()
            except Exception as e:
                print(f"Error saving arbitrage opportunity: {e}")


    def execute_arbitrage(self, buy_exchange, sell_exchange, amount_btc=None):
        """Execute an arbitrage trade"""
        buy_price = self.prices[buy_exchange]['ask']
        sell_price = self.prices[sell_exchange]['bid']
        
        if amount_btc is None:
            # Use all available balance
            amount_btc = self.balance / buy_price
        
        # Calculate costs and proceeds
        buy_cost = buy_price * amount_btc #* (1 + self.trading_fee)
        sell_proceeds = sell_price * amount_btc #* (1 - self.trading_fee)
        
        if buy_cost > self.balance:
            print("Not enough USD balance to execute trade")
            return False
        
        # Execute the trades
        self.balance -= buy_cost
        self.btc_balance += amount_btc
        
        self.balance += sell_proceeds
        self.btc_balance -= amount_btc
        
        # Record trades in database
        try:
            self.cursor.execute(
                "INSERT INTO trades (type, exchange, price, amount, total, fee) VALUES (?, ?, ?, ?, ?, ?)",
                ('buy', buy_exchange, buy_price, amount_btc, buy_cost, buy_price * amount_btc * self.trading_fee)
            )
            
            self.cursor.execute(
                "INSERT INTO trades (type, exchange, price, amount, total, fee) VALUES (?, ?, ?, ?, ?, ?)",
                ('sell', sell_exchange, sell_price, amount_btc, sell_proceeds, sell_price * amount_btc * self.trading_fee)
            )
            
            self.conn.commit()
        except Exception as e:
            print(f"Error saving trade: {e}")
        
        print(f"Executed arbitrage: Bought {amount_btc:.6f} BTC on {buy_exchange} at ${buy_price:.2f}, "
              f"Sold on {sell_exchange} at ${sell_price:.2f}, Profit: ${sell_proceeds - buy_cost:.2f}")
        
        return True

    def execute_best_arbitrage(self, event=None):
        """Execute the best available arbitrage opportunity"""
        if not self.arbitrage_opportunities:
            print("No arbitrage opportunities available")
            return
        
        best_opportunity = self.arbitrage_opportunities[0]
        self.execute_arbitrage(best_opportunity['buy_exchange'], best_opportunity['sell_exchange'])

    def start_simulation(self, event=None):
        """Start the simulation"""
        if not self.running:
            self.running = True
            # Start the asyncio event loop in a separate thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Start the simulation tasks
            self.loop.create_task(self.run_simulation())
            
            # Run the event loop in a separate thread
            self.thread = threading.Thread(target=self.run_async_tasks)
            self.thread.daemon = True
            self.thread.start()
            
            print("Simulation started")

    def run_async_tasks(self):
        """Run async tasks in the event loop"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop_simulation(self, event=None):
        """Stop the simulation"""
        self.running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        print("Simulation stopped")

    async def run_simulation(self):
        """Main simulation loop"""
        # Connect to all exchanges
        for exchange in self.exchanges:
            asyncio.create_task(self.connect_to_exchange(exchange))
        
        # Main loop
        while self.running:
            # Find arbitrage opportunities
            self.find_arbitrage_opportunities()
            
            # Update plots
            self.update_plots()
            
            await asyncio.sleep(5)  # Update every second


    
    def run(self):
        """Run the application"""
        # Start the animation with proper parameters
        self.ani = FuncAnimation(self.fig, self.update_plots, interval=1000, cache_frame_data=False, save_count=50)
        plt.show()


    def clear_database(self, event=None):
        """Clear all data from database"""
        with threading.Lock():
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM price_data")
            cursor.execute("DELETE FROM arbitrage_opportunities")
            cursor.execute("DELETE FROM trades")
            self.conn.commit()
        print("Database cleared")
    
# Run the application
if __name__ == "__main__":
    simulator = CryptoArbitrageSimulator()
    simulator.run()