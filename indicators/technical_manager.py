"""
Technical Indicator Manager for NautilusTrader Strategy

Manages all technical indicators using NautilusTrader's built-in indicators.
"""

from typing import Dict, Any, List
from decimal import Decimal

from nautilus_trader.indicators import (
    SimpleMovingAverage,
    ExponentialMovingAverage,
    RelativeStrengthIndex,
    MovingAverageConvergenceDivergence,
    AverageTrueRange,
)
from nautilus_trader.model.data import Bar


class TechnicalIndicatorManager:
    """
    Manages technical indicators for strategy analysis.

    Uses NautilusTrader's built-in indicators for efficiency and consistency.
    """

    def __init__(
        self,
        sma_periods: List[int] = [5, 20, 50],
        ema_periods: List[int] = [12, 26],
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std: float = 2.0,
        volume_ma_period: int = 20,
        support_resistance_lookback: int = 20,
        atr_period: int = 14,
    ):
        """
        Initialize technical indicator manager.

        Parameters
        ----------
        sma_periods : List[int]
            Periods for Simple Moving Averages
        ema_periods : List[int]
            Periods for Exponential Moving Averages
        rsi_period : int
            Period for RSI
        macd_fast : int
            Fast period for MACD
        macd_slow : int
            Slow period for MACD
        macd_signal : int
            Signal period for MACD
        bb_period : int
            Period for Bollinger Bands
        bb_std : float
            Standard deviation multiplier for Bollinger Bands
        volume_ma_period : int
            Period for volume moving average
        support_resistance_lookback : int
            Lookback period for support/resistance calculation
        atr_period : int
            Period for Average True Range (volatility-based exits)
        """
        # SMA indicators
        self.smas = {period: SimpleMovingAverage(period) for period in sma_periods}

        # EMA indicators (for MACD calculation reference)
        self.emas = {period: ExponentialMovingAverage(period) for period in ema_periods}

        # RSI
        self.rsi = RelativeStrengthIndex(rsi_period)

        # MACD
        self.macd = MovingAverageConvergenceDivergence(
            fast_period=macd_fast,
            slow_period=macd_slow,
        )
        self.macd_signal = ExponentialMovingAverage(macd_signal)

        # For Bollinger Bands calculation
        self.bb_sma = SimpleMovingAverage(bb_period)
        self.bb_period = bb_period
        self.bb_std = bb_std

        # Volume MA
        self.volume_sma = SimpleMovingAverage(volume_ma_period)

        # ATR (volatility-based exits)
        self.atr = AverageTrueRange(atr_period)

        # Store recent bars for calculations
        self.recent_bars: List[Bar] = []
        self.max_bars = max(list(sma_periods) + [bb_period, volume_ma_period, support_resistance_lookback]) + 10

        # Configuration
        self.support_resistance_lookback = support_resistance_lookback
        self.sma_periods = sma_periods
        self.ema_periods = ema_periods
        self.rsi_period = rsi_period
        self.macd_slow_period = macd_slow
        self.macd_fast_period = macd_fast
        self.macd_signal_period = macd_signal

    def update(self, bar: Bar):
        """
        Update all indicators with new bar data.

        Parameters
        ----------
        bar : Bar
            New bar data
        """
        # Store bar for manual calculations
        self.recent_bars.append(bar)
        if len(self.recent_bars) > self.max_bars:
            self.recent_bars.pop(0)

        # Update SMA indicators
        for sma in self.smas.values():
            sma.update_raw(float(bar.close))

        # Update EMA indicators
        for ema in self.emas.values():
            ema.update_raw(float(bar.close))

        # Update RSI
        self.rsi.update_raw(float(bar.close))

        # Update MACD
        self.macd.update_raw(float(bar.close))
        self.macd_signal.update_raw(self.macd.value)

        # Update Bollinger Band SMA
        self.bb_sma.update_raw(float(bar.close))

        # Update Volume SMA
        self.volume_sma.update_raw(float(bar.volume))

        # Update ATR (needs high, low, close)
        self.atr.update_raw(float(bar.high), float(bar.low), float(bar.close))

    def get_technical_data(self, current_price: float) -> Dict[str, Any]:
        """
        Get all technical indicator values.

        Parameters
        ----------
        current_price : float
            Current market price

        Returns
        -------
        Dict
            Dictionary containing all technical indicator values
        """
        # Basic SMA values
        sma_values = {f'sma_{period}': self.smas[period].value for period in self.sma_periods}

        # EMA values
        ema_values = {f'ema_{period}': self.emas[period].value for period in self.ema_periods}

        # RSI (convert from 0-1 scale to 0-100 scale)
        rsi_value = self.rsi.value * 100

        # MACD
        macd_value = self.macd.value
        macd_signal_value = self.macd_signal.value  # Signal line from MACD indicator

        # Bollinger Bands
        bb_middle = self.bb_sma.value
        bb_std_dev = self._calculate_std_dev(self.bb_period)
        bb_upper = bb_middle + (self.bb_std * bb_std_dev)
        bb_lower = bb_middle - (self.bb_std * bb_std_dev)
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

        # Volume analysis
        volume_ma = self.volume_sma.value
        current_volume = float(self.recent_bars[-1].volume) if self.recent_bars else 0
        volume_ratio = current_volume / volume_ma if volume_ma > 0 else 1.0

        # Support and Resistance
        support, resistance = self._calculate_support_resistance()

        # Trend analysis
        trend_data = self._analyze_trend(
            current_price, sma_values, macd_value, macd_signal_value
        )

        # Combine all data
        technical_data = {
            # SMAs
            **sma_values,
            # EMAs
            **ema_values,
            # RSI
            "rsi": rsi_value,
            # MACD
            "macd": macd_value,
            "macd_signal": macd_signal_value,
            "macd_histogram": macd_value - macd_signal_value,
            # Bollinger Bands
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "bb_position": bb_position,
            # Volume
            "volume_ratio": volume_ratio,
            # Support/Resistance
            "support": support,
            "resistance": resistance,
            # Volatility
            "atr": self.atr.value,
            # Trend analysis
            **trend_data,
        }

        return technical_data

    def _calculate_std_dev(self, period: int) -> float:
        """Calculate standard deviation for Bollinger Bands."""
        if len(self.recent_bars) < period:
            return 0.0

        recent_closes = [float(bar.close) for bar in self.recent_bars[-period:]]
        mean = sum(recent_closes) / len(recent_closes)
        variance = sum((x - mean) ** 2 for x in recent_closes) / len(recent_closes)
        return variance ** 0.5

    def _calculate_support_resistance(self) -> tuple:
        """Calculate support and resistance levels."""
        if len(self.recent_bars) < self.support_resistance_lookback:
            return 0.0, 0.0

        recent = self.recent_bars[-self.support_resistance_lookback:]
        support = min(float(bar.low) for bar in recent)
        resistance = max(float(bar.high) for bar in recent)

        return support, resistance

    def _analyze_trend(
        self,
        current_price: float,
        sma_values: Dict[str, float],
        macd_value: float,
        macd_signal_value: float,
    ) -> Dict[str, Any]:
        """
        Analyze market trend using multiple indicators.

        Returns
        -------
        Dict
            Trend analysis data
        """
        sma_20 = sma_values.get('sma_20', current_price)
        sma_50 = sma_values.get('sma_50', current_price)

        # Short-term trend (price vs SMA20)
        short_term_trend = "上涨" if current_price > sma_20 else "下跌"

        # Medium-term trend (price vs SMA50)
        medium_term_trend = "上涨" if current_price > sma_50 else "下跌"

        # MACD trend
        macd_trend = "bullish" if macd_value > macd_signal_value else "bearish"

        # Overall trend
        if short_term_trend == "上涨" and medium_term_trend == "上涨":
            overall_trend = "强势上涨"
        elif short_term_trend == "下跌" and medium_term_trend == "下跌":
            overall_trend = "强势下跌"
        else:
            overall_trend = "震荡整理"

        return {
            'short_term_trend': short_term_trend,
            'medium_term_trend': medium_term_trend,
            'macd_trend': macd_trend,
            'overall_trend': overall_trend,
        }

    def is_initialized(self) -> bool:
        """Check if indicators have enough data to be valid."""
        # Check if we have minimum bars for key indicators
        # Use dynamic calculation based on actual indicator periods
        min_required_bars = max(
            self.rsi_period,  # RSI period (e.g., 7 or 14)
            self.macd_slow_period,  # MACD slow period (e.g., 10 or 26)
            self.bb_period,  # Bollinger Bands period (e.g., 10 or 20)
            min(self.sma_periods) if self.sma_periods else 0  # At least shortest SMA
        )
        
        if len(self.recent_bars) < min_required_bars:
            return False

        # Check if key indicators are initialized
        if not self.rsi.initialized:
            return False

        if not self.macd.initialized:
            return False

        if not self.atr.initialized:
            return False

        # Check if we have at least one SMA initialized (for trend analysis)
        if not any(sma.initialized for sma in self.smas.values()):
            return False

        return True

    def get_kline_data(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent K-line data for analysis.

        Parameters
        ----------
        count : int
            Number of recent bars to return

        Returns
        -------
        List[Dict]
            List of K-line data dictionaries
        """
        if not self.recent_bars:
            return []

        kline_data = []
        for bar in self.recent_bars[-count:]:
            kline_data.append({
                'timestamp': bar.ts_init,
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': float(bar.volume),
            })

        return kline_data
