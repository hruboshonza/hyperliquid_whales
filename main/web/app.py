from flask import Flask, render_template, request, jsonify
import sys
import os
from datetime import datetime
import json

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.analyze_whale_token_positions import WhaleTokenAnalyzer
from scripts.show_whale_trades import WhaleTradeTracker

app = Flask(__name__)

def get_whale_addresses():
    """Read whale addresses from activeWhales.json."""
    try:
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'resources', 'activeWhales.json')
        with open(json_path, 'r') as f:
            data = json.load(f)
            return [wallet['fullAddress'] for wallet in data['wallets']]
    except Exception as e:
        print(f"Error reading whale addresses: {e}")
        return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    token = request.form.get('token', '').strip()
    if not token:
        return jsonify({'error': 'Please enter a token symbol'})
    
    try:
        # Initialize analyzer with whale addresses
        whale_addresses = get_whale_addresses()
        if not whale_addresses:
            return jsonify({'error': 'No whale addresses found'})
            
        analyzer = WhaleTokenAnalyzer(token, whale_addresses)
        positions = analyzer.analyze_positions()
        
        if not positions:
            return jsonify({
                'positions': [],
                'summary': {
                    'total_wallets': len(whale_addresses),
                    'wallets_with_positions': 0,
                    'total_long_value': '$0.00',
                    'total_short_value': '$0.00',
                    'total_long_size': '0.0000',
                    'total_short_size': '0.0000',
                    'total_pnl': '$0.00',
                    'avg_long_price': 'N/A',
                    'avg_short_price': 'N/A'
                },
                'token': token
            })
        
        # Prepare the data for the template
        positions_data = []
        for pos in positions:
            positions_data.append({
                'wallet': pos.wallet_address,
                'side': "Long" if pos.size > 0 else "Short",
                'size': f"{abs(pos.size):,.4f}",
                'entry_price': f"${pos.entry_price:,.2f}",
                'position_value': f"${pos.position_value:,.2f}",
                'unrealized_pnl': f"${pos.unrealized_pnl:,.2f}"
            })
        
        # Calculate totals
        total_long_value = sum(pos.position_value for pos in positions if pos.size > 0)
        total_short_value = abs(sum(pos.position_value for pos in positions if pos.size < 0))
        total_long_size = sum(pos.size for pos in positions if pos.size > 0)
        total_short_size = abs(sum(pos.size for pos in positions if pos.size < 0))
        total_pnl = sum(pos.unrealized_pnl for pos in positions)
        
        # Calculate average prices
        avg_long_price = total_long_value / total_long_size if total_long_size > 0 else 0
        avg_short_price = total_short_value / total_short_size if total_short_size > 0 else 0
        
        # Prepare summary data
        summary = {
            'total_wallets': len(whale_addresses),
            'active_positions': len(positions),
            'total_long_value': f"${total_long_value:,.2f}",
            'total_short_value': f"${total_short_value:,.2f}",
            'total_pnl': f"${total_pnl:,.2f}"
        }
        
        return jsonify({
            'positions': positions_data,
            'summary': summary,
            'token': token
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True) 