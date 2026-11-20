#!/usr/bin/env python3
"""
KuCoin API Client for Binance Hunter Migration
REST: https://api.kucoin.com
WS: wss://ws-api-spot.kucoin.com
Symbol format: BTC-USDT (with hyphen)
Auth: HMAC-SHA256 with timestamp + method + endpoint + body
"""
import os
import json
import time
import hmac
import hashlib
import base64
import requests
import threading
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict, deque

# KuCoin API Configuration
KUCOIN_API_BASE = "https://api.kucoin.com"
KUCOIN_WS_BASE = "wss://ws-api-spot.kucoin.com"
KUCOIN_API_KEY = os.environ.get("KUCOIN_API_KEY", "")
KUCOIN_API_SECRET = os.environ.get("KUCOIN_API_SECRET", "")
KUCOIN_API_PASSPHRASE = os.environ.get("KUCOIN_API_PASSPHRASE", "")

logger = logging.getLogger(__name__)


class KuCoinClient:
    """KuCoin Spot API Client with WebSocket support"""
    
    def __init__(self, api_key: str = "", api_secret: str = "", passphrase: str = ""):
        self.api_key = api_key or KUCOIN_API_KEY
        self.api_secret = api_secret or KUCOIN_API_SECRET
        self.passphrase = passphrase or KUCOIN_API_PASSPHRASE
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "BinanceHunter-KuCoin/1.0"
        })
        self._ws_token = None
        self._ws_token_expiry = 0
        
    def _sign_request(self, timestamp: str, method: str, endpoint: str, body: str = "") -> Dict[str, str]:
        """Generate KuCoin signature headers"""
        message = timestamp + method + endpoint + body
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        passphrase_sig = base64.b64encode(
            hmac.new(
                self.api_secret.encode('utf-8'),
                self.passphrase.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        return {
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-KEY": self.api_key,
            "KC-API-PASSPHRASE": passphrase_sig,
            "KC-API-KEY-VERSION": "2"
        }
    
    def _request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Dict:
        """Make authenticated request to KuCoin API"""
        timestamp = str(int(time.time() * 1000))
        body = json.dumps(data) if data else ""
        query_string = "&".join([f"{k}={v}" for k, v in params.items()]) if params else ""
        full_endpoint = endpoint + ("?" + query_string if query_string else "")
        
        headers = self._sign_request(timestamp, method.upper(), full_endpoint, body)
        self.session.headers.update(headers)
        
        url = KUCOIN_API_BASE + full_endpoint
        try:
            if method.upper() == "GET":
                response = self.session.get(url, timeout=10)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data, timeout=10)
            elif method.upper() == "DELETE":
                response = self.session.delete(url, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") != "200000":
                logger.error(f"KuCoin API error: {result}")
                raise Exception(f"KuCoin API error: {result.get('msg', 'Unknown error')}")
            
            return result.get("data", {})
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise
        finally:
            # Remove auth headers for subsequent requests
            for key in ["KC-API-SIGN", "KC-API-TIMESTAMP", "KC-API-KEY", "KC-API-PASSPHRASE", "KC-API-KEY-VERSION"]:
                self.session.headers.pop(key, None)
    
    # Public Market Data Endpoints
    def get_symbols(self) -> List[Dict]:
        """Get all trading symbols"""
        return self._request("GET", "/api/v2/symbols")
    
    def get_ticker(self, symbol: str) -> Dict:
        """Get 24hr ticker for a symbol"""
        return self._request("GET", "/api/v1/market/orderbook/level1", params={"symbol": symbol})
    
    def get_all_tickers(self) -> List[Dict]:
        """Get all tickers"""
        return self._request("GET", "/api/v1/market/allTickers")
    
    def get_klines(self, symbol: str, interval: str, start_at: int = None, end_at: int = None, limit: int = None) -> List[List]:
        """Get klines/candlesticks
        Intervals: 1min, 3min, 5min, 15min, 30min, 1hour, 2hour, 4hour, 6hour, 8hour, 12hour, 1day, 1week
        """
        params = {"symbol": symbol, "type": interval}
        if start_at:
            params["startAt"] = start_at
        if end_at:
            params["endAt"] = end_at
        if limit:
            params["limit"] = limit
        return self._request("GET", "/api/v1/market/candles", params=params)
    
    def get_order_book(self, symbol: str, level: int = 20) -> Dict:
        """Get order book (level2_20, level2_100, level3)"""
        endpoint = f"/api/v1/market/orderbook/level2_{level}"
        return self._request("GET", endpoint, params={"symbol": symbol})
    
    def get_trade_histories(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Get recent trade histories"""
        return self._request("GET", "/api/v1/market/histories", params={"symbol": symbol, "limit": limit})
    
    def get_24hr_stats(self, symbol: str) -> Dict:
        """Get 24hr statistics"""
        return self._request("GET", "/api/v1/market/stats", params={"symbol": symbol})
    
    # Private Account Endpoints (require auth)
    def get_accounts(self) -> List[Dict]:
        """Get account list"""
        return self._request("GET", "/api/v1/accounts")
    
    def get_account_balance(self, currency: str) -> Dict:
        """Get single account balance"""
        return self._request("GET", f"/api/v1/accounts/{currency}")
    
    def get_trade_fees(self, symbol: str) -> Dict:
        """Get trade fees"""
        return self._request("GET", "/api/v1/trade-fees", params={"symbol": symbol})
    
    # Order Management
    def place_order(self, symbol: str, side: str, order_type: str, size: str, 
                    price: str = None, client_oid: str = None) -> Dict:
        """Place an order"""
        data = {
            "clientOid": client_oid or str(int(time.time() * 1000)),
            "symbol": symbol,
            "side": side.lower(),  # buy/sell
            "type": order_type.lower(),  # limit/market
            "size": size
        }
        if price and order_type.lower() == "limit":
            data["price"] = price
        return self._request("POST", "/api/v1/orders", data=data)
    
    def cancel_order(self, order_id: str) -> Dict:
        """Cancel an order"""
        return self._request("DELETE", f"/api/v1/orders/{order_id}")
    
    def get_order(self, order_id: str) -> Dict:
        """Get order details"""
        return self._request("GET", f"/api/v1/orders/{order_id}")
    
    def get_active_orders(self, symbol: str = None) -> List[Dict]:
        """Get active orders"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v1/orders", params=params)
    
    def get_fills(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """Get recent fills"""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v1/fills", params=params)
    
    # WebSocket Token
    def get_ws_token(self) -> str:
        """Get WebSocket connection token"""
        if self._ws_token and time.time() < self._ws_token_expiry:
            return self._ws_token
        
        data = self._request("POST", "/api/v1/bullet-public")
        self._ws_token = data.get("token", "")
        self._ws_token_expiry = time.time() + data.get("instanceServers", [{}])[0].get("pingInterval", 18000) / 1000 - 60
        return self._ws_token
    
    def get_ws_endpoint(self) -> str:
        """Get WebSocket endpoint with token"""
        token = self.get_ws_token()
        endpoint = data.get("instanceServers", [{}])[0].get("endpoint", KUCOIN_WS_BASE)
        return f"{endpoint}?token={token}"
    
    # Symbol conversion helpers
    @staticmethod
    def to_kucoin_symbol(symbol: str) -> str:
        """Convert BTCUSDT -> BTC-USDT"""
        if "-" in symbol:
            return symbol
        # Handle common quote currencies
        for quote in ["USDT", "BTC", "ETH", "USDC", "BNB", "KCS"]:
            if symbol.endswith(quote):
                return symbol[:-len(quote)] + "-" + quote
        return symbol
    
    @staticmethod
    def to_standard_symbol(symbol: str) -> str:
        """Convert BTC-USDT -> BTCUSDT"""
        return symbol.replace("-", "")
    
    @staticmethod
    def normalize_interval(interval: str) -> str:
        """Convert standard intervals to KuCoin format"""
        mapping = {
            "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min",
            "30m": "30min", "1h": "1hour", "2h": "2hour", "4h": "4hour",
            "6h": "6hour", "8h": "8hour", "12h": "12hour", "1d": "1day", "1w": "1week"
        }
        return mapping.get(interval, interval)


# Global client instance
kucoin_client = KuCoinClient()


# Compatibility functions for existing code
def get_klines(symbol: str, interval: str, limit: int = 500) -> List[List]:
    """Compatibility wrapper for existing code"""
    kucoin_symbol = KuCoinClient.to_kucoin_symbol(symbol)
    kucoin_interval = KuCoinClient.normalize_interval(interval)
    end_at = int(time.time())
    start_at = end_at - (limit * _interval_to_seconds(interval))
    return kucoin_client.get_klines(kucoin_symbol, kucoin_interval, start_at, end_at)


def get_depth(symbol: str, limit: int = 20) -> Dict:
    """Compatibility wrapper for order book"""
    kucoin_symbol = KuCoinClient.to_kucoin_symbol(symbol)
    return kucoin_client.get_order_book(kucoin_symbol, min(limit, 100))


def get_agg_trades(symbol: str, limit: int = 100) -> List[Dict]:
    """Compatibility wrapper for agg trades"""
    kucoin_symbol = KuCoinClient.to_kucoin_symbol(symbol)
    return kucoin_client.get_trade_histories(kucoin_symbol, limit)


def get_ticker_price(symbol: str) -> Dict:
    """Get ticker price"""
    kucoin_symbol = KuCoinClient.to_kucoin_symbol(symbol)
    return kucoin_client.get_ticker(kucoin_symbol)


def get_24hr_ticker(symbol: str) -> Dict:
    """Get 24hr ticker"""
    kucoin_symbol = KuCoinClient.to_kucoin_symbol(symbol)
    return kucoin_client.get_24hr_stats(kucoin_symbol)


def _interval_to_seconds(interval: str) -> int:
    """Convert interval to seconds"""
    mapping = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
        "6h": 21600, "8h": 28800, "12h": 43200, "1d": 86400, "1w": 604800
    }
    return mapping.get(interval, 3600)


if __name__ == "__main__":
    # Test the client
    client = KuCoinClient()
    try:
        symbols = client.get_symbols()
        print(f"Loaded {len(symbols)} symbols")
        
        # Test BTC-USDT
        ticker = client.get_ticker("BTC-USDT")
        print(f"BTC-USDT: {ticker}")
        
        klines = client.get_klines("BTC-USDT", "1hour", limit=10)
        print(f"Klines: {len(klines)} candles")
        
    except Exception as e:
        print(f"Test failed: {e}")