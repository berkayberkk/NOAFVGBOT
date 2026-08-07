# Trade Bot — FVG / Order Block / Destek-Direnç

Kişisel trade stratejisini (FVG + Order Block + Destek/Direnç confluence)
kural tabanlı bir algoritmaya dönüştürüp önce backtest, sonra manuel sinyal,
sonra tam otomatik işlem seviyesine taşımayı hedefleyen proje.

## Klasör yapısı

```
trade-bot/
├── data/                    # geçmiş fiyat verileri + veri yükleme kodu
│   └── loader.py
├── strategy/                 # sinyal mantığı (borsadan/backtestten bağımsız, saf mantık)
│   ├── fvg.py
│   ├── order_block.py
│   ├── support_resistance.py
│   └── signal_engine.py      # üç modülü birleştirip sinyal üretir
├── backtest/                 # backtest motoru ve raporlama
│   └── engine.py
├── mql5/                     # ileride: MT5 EA kodu (canlı/otomatik icra için)
├── notebooks/                 # analiz / görselleştirme
└── tests/                     # birim testler
```

## Tasarım prensibi

`strategy/` klasöründeki kod hem backtest hem (ileride) canlı sinyal
tarafından kullanılacak — mantık bir kere yazılır, iki yerde de aynı
sonucu verir.

## Durum

İskelet aşaması. Fonksiyonlar tanımlı ama içleri boş
(`NotImplementedError` fırlatıyor). Sıradaki adım: FVG tespit
mantığının kurallarını netleştirip `strategy/fvg.py` içini doldurmak.

## Kurulum

```bash
pip install -r requirements.txt
```
