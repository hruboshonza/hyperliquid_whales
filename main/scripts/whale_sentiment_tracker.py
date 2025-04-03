#!/usr/bin/env python3
"""
Script to track whale sentiment changes and display new positions.
Run every 15 minutes to track changes in whale positions.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import WHALE_CONFIG

@dataclass
class SentimentSnapshot:
    """Data class to hold sentiment information for a specific timestamp."""
    timestamp: datetime
    score: float
    new_longs: int
    new_shorts: int
    positions: Dict[str, Dict[str, Dict]]  # whale_address -> {coin: position_info}
    
    def to_dict(self) -> Dict:
        """Convert snapshot to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'score': self.score,
            'new_longs': self.new_longs,
            'new_shorts': self.new_shorts,
            'positions': self.positions
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SentimentSnapshot':
        """Create snapshot from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            score=data['score'],
            new_longs=data['new_longs'],
            new_shorts=data['new_shorts'],
            positions=data['positions']
        )

class WhaleSentimentTracker:
    """Track whale sentiment changes and new positions."""
    
    def __init__(self):
        self.info_client = Info(hl_constants.MAINNET_API_URL)
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                       'resources', 'sentiment_history.json')
        self.previous_snapshot = None
        self.config = WHALE_CONFIG
        
        # Load previous snapshot if exists
        self.load_previous_snapshot()

    def load_previous_snapshot(self):
        """Load the previous snapshot from file if it exists."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    # Only try to load if the file has actual data
                    if data and isinstance(data, dict) and 'timestamp' in data:
                        self.previous_snapshot = SentimentSnapshot.from_dict(data)
                    else:
                        self.previous_snapshot = None
            else:
                self.previous_snapshot = None
        except Exception as e:
            print(f"Error loading previous snapshot: {e}")
            self.previous_snapshot = None

    def save_snapshot(self, snapshot: SentimentSnapshot):
        """Save the current snapshot to file."""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(snapshot.to_dict(), f, indent=2)
        except Exception as e:
            print(f"Error saving snapshot: {e}")

    def process_whale(self, whale_address: str) -> Tuple[Dict[str, float], Dict[str, Dict]]:
        """Process a single whale's positions."""
        try:
            # Add delay between API calls to prevent rate limiting
            time.sleep(self.config['rate_limit_delay'])
            
            user_state = self.info_client.user_state(whale_address)
            current_positions = {}
            new_positions = {}
            
            if isinstance(user_state, dict) and 'assetPositions' in user_state:
                # Get timestamp from API response
                api_timestamp = user_state.get('time', 0)
                if api_timestamp > 0:
                    # Convert milliseconds to seconds and ensure it's not in the future
                    position_time = datetime.fromtimestamp(min(api_timestamp / 1000, time.time()))
                else:
                    position_time = datetime.now()
                
                for pos in user_state['assetPositions']:
                    position_data = pos.get('position', {})
                    coin = position_data.get('coin')
                    size = float(position_data.get('szi', 0))
                    position_value = float(position_data.get('positionValue', 0))
                    
                    if size != 0 and position_value >= self.config['min_position_value']:
                        current_positions[coin] = size
                        
                        # Get previous position size if exists
                        prev_size = None
                        if (self.previous_snapshot and 
                            whale_address in self.previous_snapshot.positions and 
                            coin in self.previous_snapshot.positions[whale_address]):
                            prev_size = float(self.previous_snapshot.positions[whale_address][coin].get('size', 0))
                        
                        # Check if this is a new position
                        if prev_size is None or prev_size == 0:
                            position_type = 'Long' if size > 0 else 'Short'
                            new_positions[coin] = {
                                'type': position_type,
                                'value': abs(position_value),
                                'size': size,
                                'time': position_time.strftime('%H:%M:%S'),
                                'timestamp': position_time.timestamp()
                            }
            
            return current_positions, new_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {e}")
            return {}, {}

    def take_snapshot(self) -> SentimentSnapshot:
        """Take a snapshot of current whale positions."""
        try:
            # Get whale addresses from JSON file
            json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                    'resources', 'activeWhales.json')
            
            if not os.path.exists(json_path):
                print(f"Error: activeWhales.json not found at {json_path}")
                return None
            
            with open(json_path, 'r') as f:
                active_whales = json.load(f)
                
            whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
            
            if not whale_addresses:
                print("Error: No whale addresses found in activeWhales.json")
                return None
            
            print(f"Processing {len(whale_addresses)} whales...")
            
            new_longs = 0
            new_shorts = 0
            all_positions = {}
            new_positions_details = {}
            latest_timestamp = 0
            
            # Process each whale
            for whale_address in whale_addresses:
                current_positions, new_positions = self.process_whale(whale_address)
                all_positions[whale_address] = current_positions
                
                # Store new position details
                if new_positions:
                    new_positions_details[whale_address] = new_positions
                
                # Count new positions and track latest timestamp
                for pos_info in new_positions.values():
                    if pos_info['type'] == 'Long':
                        new_longs += 1
                    else:  # short
                        new_shorts += 1
                    latest_timestamp = max(latest_timestamp, pos_info.get('timestamp', 0))
            
            # Calculate score as simple difference between longs and shorts
            score = new_longs - new_shorts
            
            # Use latest position timestamp or current time
            snapshot_time = (datetime.fromtimestamp(latest_timestamp) 
                           if latest_timestamp > 0 
                           else datetime.now())
            
            snapshot = SentimentSnapshot(
                timestamp=snapshot_time,
                score=score,
                new_longs=new_longs,
                new_shorts=new_shorts,
                positions=new_positions_details
            )
            
            return snapshot
            
        except Exception as e:
            print(f"Error taking snapshot: {e}")
            return None

def main():
    print("Starting Whale Sentiment Tracker...")
    tracker = WhaleSentimentTracker()
    
    # Take a new snapshot
    snapshot = tracker.take_snapshot()
    
    if snapshot:
        # Save the snapshot
        tracker.save_snapshot(snapshot)
        
        # Print the snapshot details
        print("\nChanges Since Last Snapshot:")
        print("=" * 80)
        print(f"{'Datetime':<20} {'Score':<8} {'New Long Whales':<15} {'New Short Whales':<15}")
        print("-" * 80)
        
        # Previous snapshot
        if tracker.previous_snapshot:
            prev = tracker.previous_snapshot
            print(f"{prev.timestamp.strftime('%Y-%m-%d %H:%M'):<20} "
                  f"{prev.score:>7.2f} "
                  f"{prev.new_longs:^15} "
                  f"{prev.new_shorts:^15}")
        
        # Current snapshot
        print(f"{snapshot.timestamp.strftime('%Y-%m-%d %H:%M'):<20} "
              f"{snapshot.score:>7.2f} "
              f"{snapshot.new_longs:^15} "
              f"{snapshot.new_shorts:^15}")
        
        # Show changes
        if tracker.previous_snapshot:
            print("-" * 80)
            print(f"{'CHANGE':<20} "
                  f"{(snapshot.score - tracker.previous_snapshot.score):>7.2f} "
                  f"{(snapshot.new_longs - tracker.previous_snapshot.new_longs):^15} "
                  f"{(snapshot.new_shorts - tracker.previous_snapshot.new_shorts):^15}")
        
        # Print detailed position changes
        if snapshot.positions:
            print("\nDetailed Position Changes:")
            print("=" * 120)
            print(f"{'Whale Address':<45} {'Type':<8} {'Token':<10} {'Time':<10} {'Value ($)':<15}")
            print("-" * 120)
            
            # Sort positions by value for better visibility of largest positions
            sorted_positions = []
            for wallet, positions in snapshot.positions.items():
                for token, pos_info in positions.items():
                    sorted_positions.append((wallet, token, pos_info))
            
            # Sort by position value in descending order
            sorted_positions.sort(key=lambda x: x[2]['value'], reverse=True)
            
            # Print positions
            for wallet, token, pos_info in sorted_positions:
                print(f"{wallet[:20] + '...':<45} "
                      f"{pos_info['type']:<8} "
                      f"{token:<10} "
                      f"{pos_info['time']:<10} "
                      f"${pos_info['value']:,.0f}")
    
    print("\nDone!")

if __name__ == "__main__":
    main() 