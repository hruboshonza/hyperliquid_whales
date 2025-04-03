#!/usr/bin/env python3
"""
Script to track new whale positions and calculate scores based on long vs short positions.
Runs every 15 minutes to detect new positions and update scores.
A new position is counted only when a whale opens a position in an asset they didn't have before.
Keeps history for 72 hours.
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple
import concurrent.futures
from dataclasses import dataclass
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import atexit
import traceback
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

# Constants
DEBUG_MODE = False  # Will be overridden in __main__
BASE_DELAY = 5  # Base delay for exponential backoff (seconds)
MAX_DELAY = 300  # Maximum delay between retries (5 minutes)
RATE_LIMIT_DELAY = 0.1  # Delay between API calls
MIN_POSITION_TRACKER_VALUE = 50000  # Minimum position value to track

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from config import (
    TIME_PERIOD_HOURS, MAX_RETRIES, MAX_WORKERS
)

@dataclass
class ScoreSnapshot:
    """Data class to hold score information for a specific timestamp."""
    timestamp: datetime
    score: int  # Difference between new longs and new shorts
    longing_wallets: int  # Number of wallets that opened new long positions
    shorting_wallets: int  # Number of wallets that opened new short positions
    
    def to_dict(self) -> Dict:
        """Convert snapshot to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'score': self.score,
            'longing_wallets': self.longing_wallets,
            'shorting_wallets': self.shorting_wallets
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ScoreSnapshot':
        """Create snapshot from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            score=data['score'],
            longing_wallets=data['longing_wallets'],
            shorting_wallets=data['shorting_wallets']
        )

class WhaleScoreTracker:
    """Track new whale positions and calculate scores."""
    
    def __init__(self):
        self.info_client = Info(hl_constants.MAINNET_API_URL)  # Initialize with API URL
        self.position_tracker = PositionTracker()
        self.lock = threading.Lock()
        self.previous_positions: Dict[str, Set[str]] = {}  # wallet -> set of assets
        self.score_history: List[ScoreSnapshot] = []
        self.running = True
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                       'resources', 'score_history.json')
        
        # Load existing history
        self.load_history()
        
        # Start the tracking thread
        self.tracking_thread = threading.Thread(target=self.run_tracking_loop)
        self.tracking_thread.daemon = True
        self.tracking_thread.start()
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
    
    def save_history(self):
        """Save score history to JSON file."""
        try:
            with self.lock:
                # Ensure directory exists
                os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
                
                # Sort history by timestamp before saving
                self.score_history.sort(key=lambda x: x.timestamp)
                
                # Convert to dict format
                history_data = []
                for snapshot in self.score_history:
                    history_data.append({
                        'datetime': snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        'score': snapshot.score,
                        'longing_wallets': snapshot.longing_wallets,
                        'shorting_wallets': snapshot.shorting_wallets
                    })
                
                # Save with pretty formatting
                with open(self.history_file, 'w') as f:
                    json.dump({
                        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'history': history_data
                    }, f, indent=2)
                    
                if DEBUG_MODE:
                    print(f"Saved {len(history_data)} snapshots to {self.history_file}")
                    
        except Exception as e:
            print(f"Error saving history: {str(e)}")
            if DEBUG_MODE:
                traceback.print_exc()
    
    def load_history(self):
        """Load score history from JSON file."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    history_data = data.get('history', [])
                    self.score_history = []
                    
                    for snapshot in history_data:
                        try:
                            timestamp = datetime.strptime(snapshot['datetime'], '%Y-%m-%d %H:%M:%S')
                            # Only load snapshots from the past
                            if timestamp <= datetime.now():
                                self.score_history.append(ScoreSnapshot(
                                    timestamp=timestamp,
                                    score=snapshot['score'],
                                    longing_wallets=snapshot['longing_wallets'],
                                    shorting_wallets=snapshot['shorting_wallets']
                                ))
                        except Exception as e:
                            if DEBUG_MODE:
                                print(f"Error parsing snapshot: {e}")
                            continue
                    
                    # Remove old entries
                    cutoff_time = datetime.now() - timedelta(hours=72)
                    self.score_history = [s for s in self.score_history if s.timestamp > cutoff_time]
                    
                    # Sort by timestamp
                    self.score_history.sort(key=lambda x: x.timestamp)
                    
                    if DEBUG_MODE:
                        print(f"Loaded {len(self.score_history)} snapshots from {self.history_file}")
            else:
                self.score_history = []
                
        except Exception as e:
            print(f"Error loading history: {str(e)}")
            if DEBUG_MODE:
                traceback.print_exc()
            self.score_history = []
    
    def process_whale(self, whale_address: str) -> Tuple[Set[str], Dict[str, str]]:
        """Process a single whale's positions.
        
        Returns:
            Tuple containing:
            - Set of current assets
            - Dict mapping new assets to their position type (long/short)
        """
        try:
            # Add delay between API calls to prevent rate limiting
            time.sleep(RATE_LIMIT_DELAY)
            
            user_state = self.info_client.user_state(whale_address)
            current_assets = set()
            new_positions = {}
            
            if DEBUG_MODE:
                print(f"\nProcessing whale: {whale_address}")
                print(f"User state: {json.dumps(user_state, indent=2)}")
            
            if isinstance(user_state, dict) and 'assetPositions' in user_state:
                for pos in user_state['assetPositions']:
                    position_data = pos.get('position', {})
                    coin = position_data.get('coin')
                    size = float(position_data.get('szi', 0))
                    position_value = float(position_data.get('positionValue', 0))
                    
                    if DEBUG_MODE:
                        print(f"\nPosition details for {coin}:")
                        print(f"Size: {size}")
                        print(f"Position value: {position_value}")
                        print(f"Min value required: {MIN_POSITION_TRACKER_VALUE}")
                        print(f"Previous positions for this whale: {self.previous_positions.get(whale_address, set())}")
                        print(f"Is non-zero size: {size != 0}")
                        print(f"Meets minimum value: {position_value >= MIN_POSITION_TRACKER_VALUE}")
                    
                    if size != 0 and position_value >= MIN_POSITION_TRACKER_VALUE:
                        current_assets.add(coin)
                        # Check if this is a new position
                        is_new_position = (whale_address not in self.previous_positions or 
                                         coin not in self.previous_positions[whale_address])
                        
                        if DEBUG_MODE:
                            print(f"Is new position: {is_new_position}")
                        
                        if is_new_position:
                            position_type = 'long' if size > 0 else 'short'
                            new_positions[coin] = position_type
                            
                            if DEBUG_MODE:
                                print(f"New position detected: {coin} {position_type}")
            
            if DEBUG_MODE:
                print(f"\nCurrent assets: {current_assets}")
                print(f"New positions: {new_positions}")
                print(f"Previous positions for this whale: {self.previous_positions.get(whale_address, set())}")
            
            return current_assets, new_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {str(e)}")
            if DEBUG_MODE:
                traceback.print_exc()
            # Add exponential backoff on error
            time.sleep(BASE_DELAY)
            return set(), {}
    
    def analyze_positions(self) -> Tuple[ScoreSnapshot, Dict[str, Dict[str, str]]]:
        """Analyze all whale positions and return a score snapshot and detailed position info."""
        # Get whale addresses from JSON file
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'resources', 'activeWhales.json')
        
        with open(json_path, 'r') as f:
            active_whales = json.load(f)
            
        whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
        
        new_longs = 0
        new_shorts = 0
        longing_wallets = set()
        shorting_wallets = set()
        
        # Track detailed position info per whale
        whale_positions = {}  # whale_address -> {coin: position_type}
        
        # Process whales in parallel with reduced number of workers
        with ThreadPoolExecutor(max_workers=3) as executor:  # Reduced from MAX_WORKERS to 3
            future_to_whale = {
                executor.submit(self.process_whale, address): address 
                for address in whale_addresses
            }
            
            for future in concurrent.futures.as_completed(future_to_whale):
                whale_address = future_to_whale[future]
                try:
                    current_assets, new_positions = future.result()
                    
                    # Update previous positions
                    with self.lock:
                        self.previous_positions[whale_address] = current_assets
                    
                    # Store whale's new positions
                    if new_positions:
                        whale_positions[whale_address] = new_positions
                    
                    # Count new positions
                    has_new_long = False
                    has_new_short = False
                    for position_type in new_positions.values():
                        if position_type == 'long':
                            new_longs += 1
                            has_new_long = True
                        else:  # short
                            new_shorts += 1
                            has_new_short = True
                    
                    if has_new_long:
                        longing_wallets.add(whale_address)
                    if has_new_short:
                        shorting_wallets.add(whale_address)
                        
                except Exception as e:
                    print(f"Error processing whale {whale_address}: {str(e)}")
                    # Add delay on error
                    time.sleep(BASE_DELAY)
        
        # Calculate score (difference between new longs and shorts)
        score = new_longs - new_shorts
        
        # Create snapshot with current time
        current_time = datetime.now()
        if DEBUG_MODE:
            print(f"Creating snapshot with current time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
        snapshot = ScoreSnapshot(
            timestamp=current_time,
            score=score,
            longing_wallets=len(longing_wallets),
            shorting_wallets=len(shorting_wallets)
        )
        
        return snapshot, whale_positions
    
    def run_tracking_loop(self):
        """Main tracking loop that runs every 15 minutes."""
        retry_count = 0
        while self.running:
            try:
                start_time = datetime.now()
                print(f"\n{'='*50}")
                print(f"Starting analysis at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*50}")
                
                # Refresh connection if needed
                if retry_count > 0:
                    print("Refreshing connection...")
                    self.info_client = Info(hl_constants.MAINNET_API_URL)
                    time.sleep(1)  # Give connection time to establish
                
                snapshot, whale_positions = self.analyze_positions()
                
                # Verify snapshot timestamp is not in the future
                if snapshot.timestamp > datetime.now():
                    print("Warning: Future timestamp detected, correcting to current time")
                    snapshot.timestamp = datetime.now()
                
                with self.lock:
                    self.score_history.append(snapshot)
                    # Keep only last 72 hours of data
                    cutoff_time = datetime.now() - timedelta(hours=72)
                    self.score_history = [s for s in self.score_history if s.timestamp > cutoff_time]
                    # Sort by timestamp
                    self.score_history.sort(key=lambda x: x.timestamp)
                    # Save after each update
                    self.save_history()
                
                # Print all snapshots in table format
                print("\nPosition History:")
                print(f"{'-'*80}")
                print(f"{'datetime':<20} {'score':<8} {'longing_wallets':<15} {'shorting_wallets':<15}")
                print(f"{'-'*80}")
                
                for hist in self.score_history:
                    print(f"{hist.timestamp.strftime('%Y-%m-%d %H:%M:%S'):<20} "
                          f"{hist.score:<8} "
                          f"{hist.longing_wallets:<15} "
                          f"{hist.shorting_wallets:<15}")
                
                # Print new positions from this run
                if whale_positions:
                    print(f"\nNew Positions in This Run:")
                    print(f"{'='*80}")
                    print(f"{'Wallet Address':<45} {'Asset':<10} {'Position Type':<12}")
                    print(f"{'-'*80}")
                    
                    for whale_addr, positions in sorted(whale_positions.items()):
                        for asset, pos_type in sorted(positions.items()):
                            print(f"{whale_addr:<45} {asset:<10} {pos_type:<12}")
                
                print(f"\nNext update in 15 minutes...")
                print(f"{'='*50}")
                
                # Reset retry count on successful run
                retry_count = 0
                
                # Calculate exact sleep time
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(0, (15 * 60) - elapsed)  # 15 minutes minus elapsed time
                time.sleep(sleep_time)
                
            except Exception as e:
                retry_count += 1
                print(f"Error in tracking loop (attempt {retry_count}): {str(e)}")
                if DEBUG_MODE:
                    traceback.print_exc()
                
                # Exponential backoff with max delay
                delay = min(BASE_DELAY * (2 ** (retry_count - 1)), MAX_DELAY)
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)

    def cleanup(self):
        """Clean up resources on exit."""
        print("\nCleaning up resources...")
        self.running = False
        if hasattr(self, 'tracking_thread') and self.tracking_thread.is_alive():
            self.tracking_thread.join()
        # Save history one last time before exiting
        self.save_history()
        print("Cleanup complete.")

if __name__ == "__main__":
    print("Starting Whale Score Tracker with debug mode enabled...")
    DEBUG_MODE = True  # Enable debug mode
    tracker = WhaleScoreTracker()
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        tracker.cleanup() 