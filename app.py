from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://options-monitor-home.onrender.com"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OptionsDataFetcher:
    """Fetch and analyze options data for stocks."""
    
    @staticmethod
    def get_options_data(symbol):
        """Fetch options data for a symbol."""
        try:
            import time
            import requests
            
            # Create session with headers to avoid blocking
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })
            
            # Create ticker with custom session
            ticker = yf.Ticker(symbol, session=session)
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
            
            # Get stock price with error handling
            try:
                stock_info = ticker.history(period='1d')
                if stock_info.empty:
                    # Try alternative method
                    info = ticker.info
                    current_price = float(info.get('currentPrice', info.get('regularMarketPrice', 0)))
                else:
                    current_price = float(stock_info['Close'].iloc[-1])
            except Exception as e:
                logger.warning(f"Could not get price for {symbol}: {e}")
                current_price = 0
            
            # Get all expiration dates
            expirations = ticker.options
            if not expirations or len(expirations) == 0:
                logger.warning(f"No options available for {symbol}")
                return None
            
            # Focus on near-term expirations
            near_expirations = expirations[:min(4, len(expirations))]
            
            all_calls = []
            all_puts = []
            
            for exp_date in near_expirations:
                try:
                    opt_chain = ticker.option_chain(exp_date)
                    
                    calls = opt_chain.calls.copy()
                    puts = opt_chain.puts.copy()
                    
                    if calls.empty or puts.empty:
                        continue
                        
                    calls['expiration'] = exp_date
                    puts['expiration'] = exp_date
                    
                    all_calls.append(calls)
                    all_puts.append(puts)
                    
                    # Small delay between requests
                    time.sleep(0.3)
                    
                except Exception as e:
                    logger.warning(f"Error fetching options chain for {symbol} exp {exp_date}: {e}")
                    continue
            
            if not all_calls or not all_puts:
                logger.warning(f"No valid options data for {symbol}")
                return None
            
            calls_df = pd.concat(all_calls, ignore_index=True)
            puts_df = pd.concat(all_puts, ignore_index=True)
            
            return {
                'calls': calls_df,
                'puts': puts_df,
                'current_price': current_price
            }
            
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {str(e)}")
            return None
    
    # ... keep the rest of the analyze_options method the same
    
    @staticmethod
    def analyze_options(symbol, data):
        """Analyze options data and return metrics."""
        calls_df = data['calls']
        puts_df = data['puts']
        
        # Calculate volumes
        total_call_volume = int(calls_df['volume'].fillna(0).sum())
        total_put_volume = int(puts_df['volume'].fillna(0).sum())
        
        # Calculate open interest
        total_call_oi = int(calls_df['openInterest'].fillna(0).sum())
        total_put_oi = int(puts_df['openInterest'].fillna(0).sum())
        
        # Calculate call/put ratio
        call_put_ratio = round(total_call_volume / total_put_volume, 2) if total_put_volume > 0 else 0
        
        # Calculate average implied volatility
        avg_call_iv = calls_df['impliedVolatility'].mean()
        avg_put_iv = puts_df['impliedVolatility'].mean()
        
        # Find most active call strikes
        top_calls = calls_df.nlargest(5, 'volume')[['strike', 'volume', 'openInterest', 'lastPrice', 'expiration']].to_dict('records')
        
        # Find most active put strikes
        top_puts = puts_df.nlargest(5, 'volume')[['strike', 'volume', 'openInterest', 'lastPrice', 'expiration']].to_dict('records')
        
        # Calculate volume distribution by expiration
        call_vol_by_exp = calls_df.groupby('expiration')['volume'].sum().to_dict()
        put_vol_by_exp = puts_df.groupby('expiration')['volume'].sum().to_dict()
        
        return {
            'symbol': symbol,
            'currentPrice': data['current_price'],
            'callVolume': total_call_volume,
            'putVolume': total_put_volume,
            'ratio': call_put_ratio,
            'callOpenInterest': total_call_oi,
            'putOpenInterest': total_put_oi,
            'impliedVol': round(avg_call_iv, 4) if not pd.isna(avg_call_iv) else 0,
            'avgPutIV': round(avg_put_iv, 4) if not pd.isna(avg_put_iv) else 0,
            'topCallStrikes': top_calls,
            'topPutStrikes': top_puts,
            'callVolumeByExpiration': {str(k): int(v) for k, v in call_vol_by_exp.items()},
            'putVolumeByExpiration': {str(k): int(v) for k, v in put_vol_by_exp.items()},
            'timestamp': datetime.now().isoformat()
        }

# Initialize fetcher
fetcher = OptionsDataFetcher()

@app.route('/')
def index():
    """Root endpoint."""
    return jsonify({
        'status': 'running',
        'message': 'Options Flow Monitor API',
        'endpoints': {
            '/api/scan/<symbol>': 'Get options data for a single symbol',
            '/api/scan-multiple': 'Get options data for multiple symbols (POST)',
            '/api/health': 'Health check'
        }
    })

@app.route('/api/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/api/scan/<symbol>')
def scan_symbol(symbol):
    """Scan a single stock symbol for options data."""
    try:
        symbol = symbol.upper()
        logger.info(f"Scanning {symbol}")
        
        data = fetcher.get_options_data(symbol)
        
        if data is None:
            return jsonify({
                'error': f'Could not fetch data for {symbol}',
                'symbol': symbol
            }), 404
        
        analysis = fetcher.analyze_options(symbol, data)
        return jsonify(analysis)
        
    except Exception as e:
        logger.error(f"Error in scan_symbol: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan-multiple', methods=['POST'])
def scan_multiple():
    """Scan multiple stock symbols for options data."""
    try:
        data = request.get_json()
        symbols = data.get('symbols', [])
        call_vol_threshold = data.get('callVolThreshold', 5000)
        ratio_threshold = data.get('ratioThreshold', 2.0)
        
        if not symbols:
            return jsonify({'error': 'No symbols provided'}), 400
        
        results = []
        
        for symbol in symbols:
            try:
                symbol = symbol.upper().strip()
                logger.info(f"Scanning {symbol}")
                
                options_data = fetcher.get_options_data(symbol)
                
                if options_data is None:
                    results.append({
                        'symbol': symbol,
                        'error': 'Could not fetch data',
                        'flagged': False
                    })
                    continue
                
                analysis = fetcher.analyze_options(symbol, options_data)
                
                # Determine if flagged
                analysis['flagged'] = (
                    analysis['callVolume'] >= call_vol_threshold and 
                    analysis['ratio'] >= ratio_threshold
                )
                
                results.append(analysis)
                
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
                results.append({
                    'symbol': symbol,
                    'error': str(e),
                    'flagged': False
                })
        
        # Calculate summary statistics
        valid_results = [r for r in results if 'error' not in r]
        summary = {
            'totalScanned': len(results),
            'successfulScans': len(valid_results),
            'flaggedCount': sum(1 for r in valid_results if r.get('flagged', False)),
            'avgRatio': round(sum(r['ratio'] for r in valid_results) / len(valid_results), 2) if valid_results else 0,
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify({
            'summary': summary,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error in scan_multiple: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/top-strikes/<symbol>')
def top_strikes(symbol):
    """Get detailed information about top option strikes."""
    try:
        symbol = symbol.upper()
        data = fetcher.get_options_data(symbol)
        
        if data is None:
            return jsonify({'error': f'Could not fetch data for {symbol}'}), 404
        
        calls_df = data['calls']
        puts_df = data['puts']
        
        # Get top 10 by volume for both calls and puts
        top_calls = calls_df.nlargest(10, 'volume')[
            ['strike', 'lastPrice', 'volume', 'openInterest', 'impliedVolatility', 'expiration']
        ].to_dict('records')
        
        top_puts = puts_df.nlargest(10, 'volume')[
            ['strike', 'lastPrice', 'volume', 'openInterest', 'impliedVolatility', 'expiration']
        ].to_dict('records')
        
        return jsonify({
            'symbol': symbol,
            'currentPrice': data['current_price'],
            'topCalls': top_calls,
            'topPuts': top_puts,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error in top_strikes: {e}")
        return jsonify({'error': str(e)}), 500
# For production deployment
if __name__ != '__main__':
    # Gunicorn config
    import logging
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
if __name__ == '__main__':
    print("=" * 60)
    print("Options Flow Monitor Backend Server")
    print("=" * 60)
    print("Server starting on http://localhost:5000")
    print("\nAvailable endpoints:")
    print("  GET  /api/scan/<symbol>        - Scan single stock")
    print("  POST /api/scan-multiple        - Scan multiple stocks")
    print("  GET  /api/top-strikes/<symbol> - Get top option strikes")
    print("  GET  /api/health               - Health check")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
