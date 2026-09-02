# Trade Bot — FVG / Order Block / Destek-Direnç

Kişisel trade stratejisini (FVG + Order Block + Destek/Direnç confluence)
kural tabanlı bir algoritmaya dönüştürüp önce backtest, sonra manuel sinyal,
sonra tam otomatik işlem seviyesine taşımayı hedefleyen proje.

## ⚠️ KRİTİK — 2026-08-28: V1'in "VALIDATED" sonuçları geçersiz çıktı

`strategy/fvg.py`/`strategy/signal_engine.py`'de ciddi bir **lookahead/
survivorship bias** bulundu ve düzeltildi (bkz. commit geçmişi ve
`NOA_KONSEPTI_KAYNAK_ANALIZI.md`'deki "Kritik bulgu" bölümü). Özet:
sinyal üretimi, bir FVG/Order Block'un **candles dizisinin TAMAMINA
(geleceğe de) bakarak** "hiç dolmadı/kırılmadı mı" diye kontrol ediyordu
— bu hem FVG için matematiksel olarak sinyalleri hiç doldurulamaz hale
getiriyordu (FVG_ONLY sinyalleri **156K'lık tam GOLD geçmişinde tek bir
kez bile dolmamış**), hem de OB için gelecekte hiç kırılmayan (yani
zaten "doğru çıkmış") kurulumları seçerek win rate'i yapay şekilde
şişiriyordu.

Düzeltme sonrası GOLD'da resmi metodoloji (train/val/holdout + block-
bootstrap) ile yeniden koşulan sonuç (son 20.000 M30 mum,
`scratch_causal_fix_revalidation.py`):

```
TEST (holdout): win=41.6%  expectancy_r=-0.1624  profit_factor=0.71
evidence_classification: FAILED TO GENERALIZE
block_bootstrap 95% CI: [-0.2949, -0.0241]  (tamamen negatif, sıfırı kapsamıyor)
```

**Bu, önceki "VALIDATED STRONG, %92.7 win rate" sonucunun tam tersi ve
istatistiksel olarak sağlam (CI sıfırı kapsamıyor).** Aşağıdaki "V1 —
execution-ready" durumu ve Round 1-3'teki "54/101 sembol validated"
sonuçları (`backtest/results/V2_MULTI_*.json`) **hepsi eski, buggy
sinyal üretimiyle hesaplandı ve artık güvenilir değil.**

**Bu GOLD'a özgü değil.** Aynı metodoloji 5 farklı varlık sınıfında
(GOLD, EURUSD, BTCUSD, US500, GBPJPY) tekrarlandı — **5/5 sembol
"FAILED TO GENERALIZE", 5/5'inde %95 güven aralığı tamamen negatif.**
Düzeltilmiş (causal) ölçümle V1 stratejisinin gerçek bir pozitif
edge'i olduğuna dair hiçbir kanıt yok; sistematik negatif edge
gösteriyor. Ayrıntı: `NOA_KONSEPTI_KAYNAK_ANALIZI.md`.

**Demo hesapta çalışan `TradeBot_NOA_MultiSymbol.mq5`, bu geçersiz
çıkan varsayıma dayanıyor — durdurulması ciddi şekilde düşünülmeli.**

## ⚠️ KRİTİK — 2026-09-02: Yeniden kalibre edilen FVG/iFVG/OB/Trendline'ın
## (bu oturumun tüm çalışması) pozitif sonuçları da AYNI hata sınıfından
## dolayı büyük ölçüde şişirilmişti

Yukarıdaki 2026-08-28 bulgusu V1'in ESKİ (FVG+OB+Destek/Direnç, trend
filtreli) tanımıyla ilgiliydi. Bu bölüm, o bulgudan SONRA bir sonraki
oturumda yapılan tüm işi (FVG/iFVG/Order Block/Trendline'ın R-katı
hedefleri, SL tamponları, breakeven-stop eşiği — `strategy/config.py`'de
kalibre edilen HER ŞEY) kapsıyor. Bu iş, kaynağı `NOA_KONSEPTI_KAYNAK_ANALIZI.md`'de
belgelenen ~100 `scratch_*.py` script'iyle, `backtest/final_holdout.py`/
`validation.py`/`robustness.py`/`regime.py`'deki mevcut (2026-08-28
bulgusunu bulan) rigorous walk-forward/holdout altyapısı kullanılmadan
yapıldı.

Bu altyapıya (`strategy/signal_engine.py`+`backtest/engine.py` güncellenip
bu oturumun stratejisini kullanacak şekilde bağlandıktan sonra, bkz.
commit geçmişi) geçirildiğinde **GOLD/BTCUSD/EURGBP'nin ÜÇÜNDE de TRAIN
partisyonunda (in-sample!) bile expectancy NEGATİF çıktı**, holdout
"FAILED TO GENERALIZE", block-bootstrap %95 CI tamamen negatif (bkz.
`holdout_validation_results.json`, `results/holdout_validation/`).

**Kök neden araştırması (kod hatası DEĞİL, metodolojik iyimserlik):**
scratch script'lerin ORTAK `_scan_fill_and_exit`-tipi simülasyon
fonksiyonları iki ayrı, ölçülebilir iyimserlik içeriyordu:

1. **Order Block'ta "impuls barının kendisiyle aynı barda dolum"**:
   OB'nin dolum taraması `ob.impulse_index`'ten (dahil) başlıyordu --
   ama o barın TAM aralığının (impuls'u onaylayan güçlü hareket)
   bilinmesi için barın KAPANMASI gerekiyor, ve o kapanıştan SONRA
   "bu bar aynı zamanda girişe de geri çekildi" demek gerçek hayatta
   asla mümkün olmayan bir bilgiyi (barın kapanmadan önceki dip/tepe
   noktasını) kullanmak demek. Düzeltme (`impulse_index+1`'den
   başlamak) tek başına GOLD'un son 6.000 mumluk diliminde OB win
   rate'ini %33.8'den %23.3'e, beklentiyi +0.35R'den -0.07R'ye düşürdü.
2. **TÜM modüllerde "aynı barda iyimser TP kabul etme"**: scratch
   script'ler, dolum barının KENDİSİNDE hem SL hem TP seviyesine
   ulaşılabiliyorsa, TP'nin ÖNCE vurulduğunu varsayıyordu -- ama bu
   sıralama tek bir OHLC barından ASLA kesin bilinemez (bkz.
   `backtest/engine.py`'nin çok daha önceden -- bu bulgudan bağımsız
   olarak -- test edilmiş `test_same_bar_entry_and_tp_ambiguity_no_optimistic_tp`
   kuralı, hep muhafazakar/pessimistik SL öncelikli kabul eder, TP'yi
   HER ZAMAN bir sonraki bara erteler). Bu TEK kuralı izole edip FVG'de
   test etmek: win rate %51.8'den %36.0'a, beklenti +0.29R'den
   -0.10R'ye düştü -- OB'deki kadar büyük, TEK BAŞINA gözlemlenen
   toplam farkın neredeyse tamamını açıklıyor.

**Sonuç:** `strategy/signal_engine.py`/`backtest/engine.py`'ye yapılan
entegrasyon KOD OLARAK doğru (yukarıdaki iki iyimserlikten HİÇBİRİNİ
içermiyor, holdout altyapısının zaten var olan muhafazakar kurallarını
miras alıyor) -- düzeltilecek bir hata YOK, dolayısıyla holdout'u
tekrar çalıştırmak (deterministik, aynı kod/veri) aynı sonucu verir.
Bu oturumun ürettiği TÜM pozitif sonuçlar (breakeven-stop eşiği,
R-katı/SL tamponu kalibrasyonları, GOLD $10k hesap simülasyonu, 95
sembollük tam işlem arşivi) bu iki iyimserlik yüzünden gerçek olandan
daha iyi görünüyor olabilir -- ne kadar, sembol/modüle göre değişiyor
(OB en çok etkilenen, FVG de neredeyse aynı derecede, ayrıntı için
`NOA_KONSEPTI_KAYNAK_ANALIZI.md`).

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

`research/v2/data/run_multi_symbol_acquisition.py` ile gerçek MT5 M1
verisi toplanıyor; `backtest/run_multi_symbol_validation.py` ile V1
stratejisi her sembolde kendi train/val/test bölünmesiyle test
ediliyor (sonuçlar `backtest/results/V2_MULTI_*_validation.json`,
özet `backtest/results/V2_MULTI_validation_summary.json`).

**Round 1–2 (32 sembol, major FX + BTCUSD/WTI/Nasdaq/Silver):** 11
sembol %95 block-bootstrap güven aralığı sıfırı kapsamıyor —
istatistiksel olarak sağlam pozitif. USDCHF hariç tüm CHF çaprazları
başarısız (muhtemelen GOLD'a göre kalibre ATR eşiklerinin CHF'nin
düşük volatilitesine uymaması).

**Round 3 (maksimum genişlik, 101 sembol, veri derinliği 2010'a
kadar):** major/exotic FX çaprazları, 23 global endeks (US30, GER40,
JP225, HK50, UK100 vb.), metal/enerji (PLATINUM, PALLADIUM, BRENT) ve
15 büyük kripto para eklendi. Sonuç: **54/101 sembol validated** (17
STRONG + 37 MODERATE), 47 generalize olamadı. Öne çıkan bulgu: STRONG
sınıfının 11/17'si global endeks (CA60, GER40, IT40, US30, CHINAH,
NETH25, FRA40, HK50, JP225, EU50, US500) — strateji FX'ten çok endeks
piyasalarında güçlü genelleme gösteriyor. (İstisna: USFANG "STRONG"
etiketli ama sadece 1 trade/pf=inf — örneklem gürültüsü, kanıt olarak
sayılmamalı.) Şu an canlı EA'da olan 10 sembolün (GOLD, GBPJPY,
GBPUSD, GBPAUD, EURAUD, BTCUSD, SILVER, EURJPY, EURNZD, USDCHF)
tamamı Round 3'te de validated çıktı — regresyon yok.

`mql5/TradeBot_NOA_MultiSymbol.mq5` bu 9 sağlam sembol (Round 1-2) +
GOLD'u tek EA instance'ında (OnTimer tabanlı, sembol başına ayrı
ATR/EMA handle, portföy risk tavanlı) işlem yapacak şekilde genişletir.
Strateji mantığı `TradeBot_NOA.mq5` (tek sembol, kanıtlanmış GOLD
versiyonu) ile birebir aynı — o dosyaya dokunulmadı, ayrı ve kanıtlanmış
haliyle duruyor. Derlendi (0 hata), demo hesapta forward-test'te
(bkz. `backtest/ea_monitor.py`).

**EA'ya eklenmeye aday, Round 3'te STRONG çıkan yeni semboller**
(henüz canlıda değil): USDJPY, BRENT + endeks grubu (CA60, GER40,
IT40, US30, CHINAH, NETH25, FRA40, HK50, JP225, EU50, US500). Karar
verilmedi — endekslerin işlem saatleri/swap/margin rejimi FX'ten
farklı, EA'nın portföy risk mantığının bunlara uyarlanması gerekip
gerekmediği ayrıca değerlendirilmeli.

## Sıradaki adım

1. Demo hesaptaki forward-test'i sürdürmek ve `ea_monitor.py` ile
   izlemeye devam etmek — örneklem büyütmenin tek yolu bu.
2. Round 3'te STRONG çıkan endeks/USDJPY/BRENT'in
   `TradeBot_NOA_MultiSymbol.mq5`'e eklenip eklenmeyeceğine karar
   vermek (işlem saati/margin/swap farklarını değerlendirdikten sonra).
3. V2 discovery koşusunu gerçek veride (smoke fixture değil) TRAIN
   partition'ında çalıştırmak. RAM/süre sorunu chunked engineering-
   coverage koşusuyla (`research/v2/engine/run_v2_train_chunked.py`)
   aşıldı (1.003M mum, 51 chunk, tam TRAIN, ~95dk) ama bu sadece
   ENGINEERING_SMOKE_ONLY/QUARANTINED telemetri — gerçek strateji
   skorlaması (win-rate/expectancy) chunk bazında henüz üretilmedi.

## Kurulum

```bash
pip install -r requirements.txt
```
