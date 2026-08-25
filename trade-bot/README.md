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
│   ├── trend.py
│   └── signal_engine.py      # üç modülü birleştirip sinyal üretir
├── backtest/                 # backtest motoru, walk-forward/holdout validasyon, forward/shadow runner
│   ├── engine.py
│   ├── validation.py
│   ├── robustness.py
│   ├── final_holdout.py
│   ├── forward.py / forward_store.py / forward_drift.py
│   └── mt5_shadow.py / run_shadow.py
├── mql5/                     # MT5 EA (canlı/otomatik icra) — derleniyor, gerçek emir gönderiyor
│   └── TradeBot_NOA.mq5
├── research/v2/               # V2: çok-zaman-dilimli (M30→M15→M5→M3) thesis/discovery araştırma hattı
│   ├── core/                  # ParentThesis lifecycle & provenance
│   ├── data/                  # gerçek MT5 veri edinimi, hizalama, denetim
│   ├── features/               # leakage-safe FVG/OB/liquidity/structure feature'ları
│   ├── dataset/                # ResearchRow şeması, leakage validasyonu, dataset builder
│   ├── engine/                  # multi-timeframe backtester, train runner
│   └── telemetry/                # passport, excursion, dashboard, visualizer
├── notebooks/                 # analiz / görselleştirme (henüz boş)
└── tests/                     # birim testler (400+)
```

## Tasarım prensibi

`strategy/` klasöründeki kod hem backtest hem canlı sinyal (MT5 EA)
tarafından kullanılıyor — mantık bir kere yazılır, iki yerde de aynı
sonucu verir.

## Durum (güncel)

İki paralel katman var:

**V1 — kural tabanlı strateji, execution-ready.**
FVG + Order Block + Destek/Direnç confluence sinyalleri üretiliyor,
backtest motoru chronological train/val/holdout split + walk-forward +
block-bootstrap güven aralığı ile disiplinli şekilde doğrulanıyor.
`mql5/TradeBot_NOA.mq5` gerçek emir gönderiyor (risk bazlı lot
hesaplama, max lot güvenlik kepi) ve hatasız derleniyor. Final holdout
sonucu güçlü ama örneklem küçük (19 trade) — geniş çaplı forward/demo
doğrulaması henüz tamamlanmadı.

**V2 — çok-zaman-dilimli araştırma hattı, geliştirme aşamasında.**
Immutable thesis lifecycle, leakage-safe feature engineering, causal
liquidity/OB/FVG kalite skorları ve counterfactual entry refinement
içeren kurumsal seviyede bir araştırma altyapısı kuruldu. Gerçek
2 milyon satırlık XAUUSD M1 verisi mevcut (2021–2026), ama discovery
koşusu şu ana kadar sadece küçük bir smoke-test fixture'ında çalıştı —
tam TRAIN/VALIDATION/TEST partition'larında henüz koşulmadı, bu yüzden
V2'den henüz kanıtlanmış bir strateji sonucu yok.

## Çoklu-sembol genelleme testi

`research/v2/data/run_multi_symbol_acquisition.py` ile GOLD dışında 32
sembolün (major FX çaprazları + BTCUSD + WTI + Nasdaq/Silver) gerçek
MT5 M1 verisi toplandı; `backtest/run_multi_symbol_validation.py` ile
V1 stratejisi her sembolde kendi train/val/test bölünmesiyle test
edildi (sonuçlar `backtest/results/V2_MULTI_*_validation.json`).
32 sembolün 11'inde %95 block-bootstrap güven aralığı sıfırı
kapsamıyor — GBPJPY, GBPUSD, GBPAUD, EURAUD, BTCUSD, SILVER, EURJPY,
EURNZD, USDCHF istatistiksel olarak sağlam pozitif; NASDAQ ve NZDCHF
sağlam negatif (strateji bu enstrümanlarda gerçekten işlemiyor).
USDCHF hariç tüm CHF çaprazları başarısız — muhtemelen GOLD'a göre
kalibre edilmiş ATR eşiklerinin CHF'nin düşük volatilitesine uymaması.

`mql5/TradeBot_NOA_MultiSymbol.mq5` bu 9 sağlam sembol + GOLD'u tek EA
instance'ında (OnTimer tabanlı, sembol başına ayrı ATR/EMA handle,
portföy risk tavanlı) işlem yapacak şekilde genişletir. Strateji
mantığı `TradeBot_NOA.mq5` (tek sembol, kanıtlanmış GOLD versiyonu)
ile birebir aynı — o dosyaya dokunulmadı, ayrı ve kanıtlanmış haliyle
duruyor. Derlendi (0 hata), henüz demo hesapta çalıştırılmadı.

## Sıradaki adım

1. `TradeBot_NOA_MultiSymbol.mq5`'i demo hesapta bir grafiğe ekleyip
   (AutoTrading açık) uzun süreli forward-test'e sokmak — örneklem
   büyütmenin tek yolu bu.
2. V2 discovery koşusunu gerçek veride (smoke fixture değil) TRAIN
   partition'ında çalıştırmak — ama önce 100k-mum ölçeğinde tespit
   edilen ~11GB RAM / 48dk+ performans sorunu profillenip çözülmeli.

## Kurulum

```bash
pip install -r requirements.txt
```
