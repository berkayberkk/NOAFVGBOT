"""Unit tests for forex_daytrade.types.aliases."""

from forex_daytrade.types.aliases import Pips, Price, SymbolName, Volume


def test_price_alias_resolves_to_float() -> None:
    assert Price.__value__ is float


def test_pips_alias_resolves_to_float() -> None:
    assert Pips.__value__ is float


def test_volume_alias_resolves_to_float() -> None:
    assert Volume.__value__ is float


def test_symbol_name_alias_resolves_to_str() -> None:
    assert SymbolName.__value__ is str


def test_aliases_usable_as_annotations() -> None:
    def notional(price: Price, volume: Volume, symbol: SymbolName) -> Pips:
        assert symbol
        return price * volume

    assert notional(1.1, 2.0, "EURUSD") == 2.2
