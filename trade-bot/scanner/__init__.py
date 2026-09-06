"""
Market Research / Multi-Timeframe Scanner.

Bu paket, projenin desteklediği TÜM enstrümanları (strategy/config.py:_ALL_101_SYMBOLS)
AYNI standartla (aynı strategy modülleri, aynı zaman dilimi seti) tarayan CANLI bir
araştırma katmanıdır -- backtest DEĞİLDİR, "şu an piyasada setup var mı" sorusuna
cevap verir (bkz. scanner/engine.py docstring'i).

KRİTİK TASARIM KURALI: hiçbir sembole özel davranış YOK. GOLD/BTCUSD gibi
KEPT_SYMBOLS canlı-trade kapsamında kalmaya devam ediyor (mql5/TradeBot_NOA_Recal.mq5,
strategy/config.py DEĞİŞMEDİ) ama bu scanner'ın kendisi KEPT_SYMBOLS'u ÖZEL
muamele etmez -- 101 sembolün hepsini eşit pipeline'dan geçirir.

Strateji mantığı burada TEKRAR YAZILMADI -- strategy/signal_engine.py:generate_signals
DEĞİŞTİRİLMEDEN çağrılıyor (bkz. engine.py).
"""
