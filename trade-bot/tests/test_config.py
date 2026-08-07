"""
Strateji Yapılandırması Regresyon Testleri (Configuration Regression Tests).

Bu testler, merkezi StrategyConfig nesnesindeki varsayılan değerlerin
orijinal strateji parametreleriyle birebir eşleştiğini doğrular.
"""

from strategy.config import DEFAULT_CONFIG, StrategyConfig
import strategy.fvg as fvg_module
import strategy.order_block as ob_module
import strategy.support_resistance as sr_module
import strategy.trend as trend_module
import backtest.engine as engine_module


def test_default_config_values():
    config = DEFAULT_CONFIG
    assert config.atr_period == 14
    assert config.min_gap_to_atr_ratio == 0.15
    assert config.max_gap_to_atr_ratio == 2.5
    assert config.max_middle_candle_ratio == 3.0
    assert config.avg_range_period == 14
    assert config.strong_move_ratio == 2.0
    assert config.swing_lookback == 5
    assert config.tolerance_atr_ratio == 0.5
    assert config.min_level_touch_count == 2
    assert config.ema_period == 50


def test_module_constants_match_default_config():
    assert fvg_module.ATR_PERIOD == DEFAULT_CONFIG.atr_period
    assert fvg_module.MIN_GAP_TO_ATR_RATIO == DEFAULT_CONFIG.min_gap_to_atr_ratio
    assert fvg_module.MAX_GAP_TO_ATR_RATIO == DEFAULT_CONFIG.max_gap_to_atr_ratio
    assert fvg_module.MAX_MIDDLE_CANDLE_RATIO == DEFAULT_CONFIG.max_middle_candle_ratio

    assert ob_module.AVG_RANGE_PERIOD == DEFAULT_CONFIG.avg_range_period
    assert ob_module.STRONG_MOVE_RATIO == DEFAULT_CONFIG.strong_move_ratio

    assert sr_module.SWING_LOOKBACK == DEFAULT_CONFIG.swing_lookback
    assert sr_module.TOLERANCE_ATR_RATIO == DEFAULT_CONFIG.tolerance_atr_ratio

    assert trend_module.EMA_PERIOD == DEFAULT_CONFIG.ema_period

    assert engine_module.MIN_LEVEL_TOUCH_COUNT == DEFAULT_CONFIG.min_level_touch_count
