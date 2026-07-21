"""
Alternative.me Fear & Greed Index Sentiment Fetcher for NautilusTrader

Fetches the crypto Fear & Greed Index from alternative.me (free, no API key
required) and maps it to the positive/negative sentiment structure used by
the strategy.

The index is a daily value in [0, 100]:
    0   = Extreme Fear
    100 = Extreme Greed

Mapping:
    positive_ratio = value / 100
    negative_ratio = 1 - value / 100
    net_sentiment  = (value - 50) / 50   (range -1 .. +1, == positive - negative)
"""

import requests
from typing import Dict, Any, Optional
from datetime import datetime


class SentimentDataFetcher:
    """
    Fetches the crypto Fear & Greed Index from alternative.me.

    Provides positive/negative sentiment ratios and net sentiment scores
    derived from the daily index value.
    """

    API_URL = "https://api.alternative.me/fng/"

    def __init__(self, lookback_hours: int = 4, timeframe: str = "15m"):
        """
        Initialize sentiment data fetcher.

        Parameters
        ----------
        lookback_hours : int
            Kept for interface compatibility; the FNG index is daily,
            so this parameter is unused.
        timeframe : str
            Kept for interface compatibility; unused.
        """
        self.lookback_hours = lookback_hours
        self.timeframe = timeframe

    def fetch(self, token: str = "BTC") -> Optional[Dict[str, Any]]:
        """
        Fetch the latest Fear & Greed Index value.

        Parameters
        ----------
        token : str
            Kept for interface compatibility; the FNG index is
            market-wide (BTC-dominated), so this parameter is unused.

        Returns
        -------
        Dict or None
            Sentiment data with structure:
            {
                'positive_ratio': float,
                'negative_ratio': float,
                'net_sentiment': float,
                'data_time': str,
                'data_delay_minutes': int,
                'classification': str
            }
        """
        try:
            response = requests.get(self.API_URL, params={"limit": 1}, timeout=10)

            if response.status_code != 200:
                print(f"⚠️ alternative.me FNG API returned status: {response.status_code}")
                return None

            payload = response.json()
            entries = payload.get("data") or []
            if not entries:
                print("⚠️ alternative.me FNG API returned empty data")
                return None

            entry = entries[0]
            value = float(entry["value"])  # 0-100
            classification = entry.get("value_classification", "")
            data_time = datetime.fromtimestamp(int(entry["timestamp"]))

            positive = value / 100.0
            negative = 1.0 - positive
            net_sentiment = (value - 50.0) / 50.0

            data_delay = int((datetime.now() - data_time).total_seconds() // 60)

            print(
                f"✅ Using FNG sentiment data from: "
                f"{data_time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"(value: {value:.0f} {classification}, delay: {data_delay} minutes)"
            )

            return {
                'positive_ratio': positive,
                'negative_ratio': negative,
                'net_sentiment': net_sentiment,
                'data_time': data_time.strftime('%Y-%m-%d %H:%M:%S'),
                'data_delay_minutes': data_delay,
                'classification': classification,
            }

        except Exception as e:
            print(f"❌ Sentiment data fetch failed: {e}")
            return None

    def format_for_display(self, sentiment_data: Optional[Dict[str, Any]]) -> str:
        """
        Format sentiment data for logging/display.

        Parameters
        ----------
        sentiment_data : Dict or None
            Sentiment data from fetch()

        Returns
        -------
        str
            Formatted sentiment string
        """
        if not sentiment_data:
            return "Market Sentiment: Data unavailable"

        sign = '+' if sentiment_data['net_sentiment'] >= 0 else ''
        classification = sentiment_data.get('classification', '')
        label = f" ({classification})" if classification else ""
        return (
            f"Market Sentiment: "
            f"Bullish {sentiment_data['positive_ratio']:.1%} | "
            f"Bearish {sentiment_data['negative_ratio']:.1%} | "
            f"Net {sign}{sentiment_data['net_sentiment']:.3f}{label} | "
            f"Delay {sentiment_data['data_delay_minutes']}min"
        )
