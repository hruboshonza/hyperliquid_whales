from flask import Flask, render_template, request, jsonify
import sys
import os
from datetime import datetime
import json
import logging
from pathlib import Path

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.actual_positions_by_asset import WhaleTokenAnalyzer
from scripts.show_whale_trades import WhaleTradeTracker
from scripts.recent_24h_positions import RecentPositionAnalyzer
from config import (
    DEBUG_MODE, ERROR_MESSAGES, SUCCESS_MESSAGES,
    TABLE_FORMAT, ADDRESS_DISPLAY_LENGTH,
    POSITION_TYPES, ACTION_TYPES, ORDER_TYPES
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('whale_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WhaleTrackerWebApp:
    """Web application for the Hyperliquid Whale Tracker."""
    
    def __init__(self):
        """Initialize the web application."""
        self.app = Flask(__name__)
        self.setup_routes()
        
    def setup_routes(self):
        """Set up all application routes."""
        self.app.route('/')(self.index)
        self.app.route('/analyze', methods=['POST'])(self.analyze)
        self.app.route('/recent_positions', methods=['GET'])(self.get_recent_positions)
        
    def get_whale_addresses(self):
        """Read whale addresses from activeWhales.json."""
        try:
            json_path = Path(__file__).parent.parent.parent / 'resources' / 'activeWhales.json'
            with open(json_path, 'r') as f:
                data = json.load(f)
                return [wallet['fullAddress'] for wallet in data['wallets']]
        except Exception as e:
            logger.error(f"Error reading whale addresses: {e}")
            return []
            
    def index(self):
        """Render the main page."""
        return render_template('index.html')
        
    def analyze(self):
        """Analyze positions for a specific token."""
        token = request.form.get('token', '').strip()
        if not token:
            return jsonify({'error': ERROR_MESSAGES["MISSING_TOKEN"]})
        
        try:
            # Initialize analyzer with whale addresses
            whale_addresses = self.get_whale_addresses()
            if not whale_addresses:
                return jsonify({'error': ERROR_MESSAGES["NO_WHALES"]})
                
            analyzer = WhaleTokenAnalyzer(token, whale_addresses)
            
            try:
                positions = analyzer.analyze_positions()
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "rate limited" in error_msg.lower():
                    logger.warning("Rate limit hit during position analysis")
                    return jsonify({
                        'error': "Rate limit reached. Please try again in a few moments.",
                        'status': 'rate_limited',
                        'retry_after': 30  # Suggest retry after 30 seconds
                    })
                else:
                    logger.error(f"Error analyzing positions: {e}")
                    return jsonify({
                        'error': "An error occurred while analyzing positions. Please try again later.",
                        'status': 'error'
                    })
            
            if not positions:
                return self._create_empty_response(token, len(whale_addresses))
            
            return self._create_analysis_response(positions, token, whale_addresses)
            
        except Exception as e:
            logger.error(f"Error analyzing positions: {e}")
            return jsonify({
                'error': "An unexpected error occurred. Please try again later.",
                'status': 'error'
            })
            
    def _create_empty_response(self, token, total_wallets):
        """Create an empty response when no positions are found."""
        return jsonify({
            'positions': [],
            'summary': {
                'total_wallets': total_wallets,
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
        
    def _create_analysis_response(self, positions, token, whale_addresses):
        """Create a response with position analysis data."""
        positions_data = [{
            'wallet': pos.wallet_address[:ADDRESS_DISPLAY_LENGTH] + '...',
            'side': POSITION_TYPES["LONG"] if pos.size > 0 else POSITION_TYPES["SHORT"],
            'size': f"{abs(pos.size):,.4f}",
            'entry_price': f"${pos.entry_price:,.2f}",
            'position_value': f"${pos.position_value:,.2f}",
            'unrealized_pnl': f"${pos.unrealized_pnl:,.2f}"
        } for pos in positions]
        
        # Calculate totals
        total_long_value = sum(pos.position_value for pos in positions if pos.size > 0)
        total_short_value = abs(sum(pos.position_value for pos in positions if pos.size < 0))
        total_long_size = sum(pos.size for pos in positions if pos.size > 0)
        total_short_size = abs(sum(pos.size for pos in positions if pos.size < 0))
        total_pnl = sum(pos.unrealized_pnl for pos in positions)
        
        # Calculate average prices
        avg_long_price = total_long_value / total_long_size if total_long_size > 0 else 0
        avg_short_price = total_short_value / total_short_size if total_short_size > 0 else 0
        
        return jsonify({
            'positions': positions_data,
            'summary': {
                'total_wallets': len(whale_addresses),
                'active_positions': len(positions),
                'total_long_value': f"${total_long_value:,.2f}",
                'total_short_value': f"${total_short_value:,.2f}",
                'total_pnl': f"${total_pnl:,.2f}"
            },
            'token': token
        })
        
    def get_recent_positions(self):
        """Get recent position data for all assets."""
        try:
            # Get whale addresses first
            whale_addresses = self.get_whale_addresses()
            if not whale_addresses:
                return jsonify({'error': ERROR_MESSAGES["NO_WHALES"]})
                
            analyzer = RecentPositionAnalyzer()
            
            try:
                analyzer.analyze_positions()
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "rate limited" in error_msg.lower():
                    logger.warning("Rate limit hit during position analysis")
                    return jsonify({
                        'error': "Rate limit reached. Please try again in a few moments.",
                        'status': 'rate_limited',
                        'retry_after': 30  # Suggest retry after 30 seconds
                    })
                else:
                    logger.error(f"Error analyzing positions: {e}")
                    return jsonify({
                        'error': "An error occurred while analyzing positions. Please try again later.",
                        'status': 'error'
                    })
            
            # Sort assets by new long and short value
            sorted_longs = sorted(
                analyzer.asset_positions.items(),
                key=lambda x: x[1].total_new_long_value,
                reverse=True
            )[:10]
            
            sorted_shorts = sorted(
                analyzer.asset_positions.items(),
                key=lambda x: x[1].total_new_short_value,
                reverse=True
            )[:10]
            
            # Calculate totals
            total_new_long_positions = sum(pos.new_long_count for _, pos in analyzer.asset_positions.items())
            total_new_short_positions = sum(pos.new_short_count for _, pos in analyzer.asset_positions.items())
            total_closed_long_positions = sum(pos.closed_long_count for _, pos in analyzer.asset_positions.items())
            total_closed_short_positions = sum(pos.closed_short_count for _, pos in analyzer.asset_positions.items())
            
            # Prepare data for the template
            long_positions = [{
                'asset': asset,
                'value': f"${pos.total_new_long_value:,.2f}",
                'size': f"{pos.total_new_long_size:,.2f}",
                'new_count': pos.new_long_count,
                'closed_count': pos.closed_long_count,
                'whale_count': pos.new_long_count
            } for asset, pos in sorted_longs]
            
            short_positions = [{
                'asset': asset,
                'value': f"${pos.total_new_short_value:,.2f}",
                'size': f"{pos.total_new_short_size:,.2f}",
                'new_count': pos.new_short_count,
                'closed_count': pos.closed_short_count,
                'whale_count': pos.new_short_count
            } for asset, pos in sorted_shorts]
            
            return jsonify({
                'long_positions': long_positions,
                'short_positions': short_positions,
                'summary': {
                    'total_new_long': total_new_long_positions,
                    'total_new_short': total_new_short_positions,
                    'total_closed_long': total_closed_long_positions,
                    'total_closed_short': total_closed_short_positions,
                    'total_wallets': len(whale_addresses)
                },
                'status': 'success'
            })
            
        except Exception as e:
            logger.error(f"Error getting recent positions: {e}")
            return jsonify({
                'error': "An unexpected error occurred. Please try again later.",
                'status': 'error'
            })
            
    def run(self):
        """Run the Flask application."""
        self.app.run(debug=DEBUG_MODE)

def main():
    """Main entry point."""
    app = WhaleTrackerWebApp()
    app.run()

if __name__ == '__main__':
    main() 