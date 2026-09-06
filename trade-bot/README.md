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

### GÜNCELLEME — 2026-09-02/03: düzeltilmiş altyapıyla yeniden kalibrasyon TAMAMLANDI

Yukarıdaki iki bulgudan sonra strateji **GOLD, BTCUSD, EURGBP'ye
daraltıldı** (`strategy/config.py:KEPT_SYMBOLS` — 101 sembollük evrenden
kademeli eleme, gerekçe dosyanın kendi içinde tarihçeli olarak belgeli)
ve TÜM yeni kalibrasyon adımları (hacim teyidi, FVG/OB giriş-derinliği,
SL tamponu genişletme) bu kez `backtest/final_holdout.py`'nin rigorous
train/val/holdout + block-bootstrap disipliniyle, HİÇ BAKILMAMIŞ test
kümesinde TEK ATIMLIK doğrulanarak kabul edildi (bkz.
`NOA_KONSEPTI_KAYNAK_ANALIZI.md`, "Win rate araştırması -- Aday 1-8"
bölümleri). Kabul edilenler: hacim teyidi (FVG), giriş-derinliği
(FVG+OB), SL tamponu genişletme (FVG/iFVG/OB/Trendline'ın hepsinde
holdout'ta doğrulandı). Reddedilenler: R-katı yeniden kalibrasyonu
(win rate kaybı expectancy kazancını haklı çıkarmadı), H1 zaman
diliminin devre dışı bırakılması (3 semboldeki holdout sonucu
tutarsız çıktı, daha büyük örneklem gerekiyor — bkz. "Sıradaki adım").
Bu, projenin yukarıdaki iki KRİTİK bulguyu bulan AYNI disiplinle
geçirilmiş, şu ana kadarki EN SIKI doğrulanmış sonuç seti.

## ⚠️ 2026-09-04: aşırı fiyat sıçramalarında R-katı hesaplaması bozuluyordu (düzeltildi)

`backtest/engine.py`'de, bir sinyal süresiz beklerken (broker'da gerçek
pending emir yok, backtest sinyali "dolana kadar" bekliyor) fiyat çok
uzun süre sonra ekstrem bir sıçramayla (gap) seviyeye dokunursa,
`executed_entry` sıçrama fiyatına güncelleniyordu ama R-katının paydası
olan `risk`, hâlâ sinyalin ORİJİNAL `entry`'sinden hesaplanıyordu — bu
da matematiksel olarak anlamsız R değerleri üretiyordu (ör. +413R,
+85R), üstelik aynı anda bayat aynı-bar SL kontrolü yüzünden bu işlemler
YANLIŞLIKLA kayıp (`won=False`) olarak sınıflandırılıyordu. Gerçek
tarihi olaylar: 2015-01-15 SNB CHF-euro sabit kur şoku (CHFJPY, CHFSGD)
ve 2011-12-21 USDZAR aşırı volatilite günü.

**Etki taraması** (`scratch_investigate_outliers.py` + hedefli debug
script'i ile bulundu): CHFJPY/CHFSGD/USDZAR'da (KEPT_SYMBOLS dışı,
101-sembol evreninde) şüpheli (|R|>15) işlemler bulundu; **KEPT_SYMBOLS
içinde BTCUSD'de de 5 şüpheli işlem** tespit edildi (GOLD/EURGBP'de
şüpheli işlem YOK).

**Düzeltme:** `backtest/engine.py`'ye `MAX_GAP_FILL_RISK_MULTIPLE = 3.0`
sınırı eklendi — dolum fiyatı orijinal entry'den `risk * 3.0`'dan daha
uzaksa, o dolum geçersiz sayılır (sinyal "dolmadı" olarak işaretlenir,
sahte bir işlem üretilmez). `pytest tests/test_backtest_engine.py`
(34/34 geçti) ile doğrulandı; CHFJPY'de en yüksek 5 R değeri
`[16.77, 17.54, 26.18, 34.02, 413.77]` → `[3.31, 3.35, 3.42, 3.98, 3.98]`
oldu, şüpheli (|R|>15) işlem sayısı 0'a indi.

**Karar üzerindeki somut etkisi:** OB-crowding derinleştirme analizi
(tek-pozisyon havuzu A/B/C karşılaştırması) düzeltilmiş motorla yeniden
koşuldu. GOLD ve EURGBP'de en iyi strateji önerisi DEĞİŞMEDİ (sırasıyla
"OB'ye ayrı slot ver" ve "mevcut paylaşımlı havuzu koru"). **BTCUSD'de
öneri TERSİNE DÖNDÜ**: düzeltme öncesi mevcut havuzu korumak (A) en
iyiydi (-2.21R); düzeltme sonrası mevcut havuz -7.23R'ye düştü (sahte
pozitif şişirme gitti) ve artık **OB'yi tamamen dışlamak (B, -4.50R)**
en iyi öneri. Bu, hatanın kozmetik değil karar-değiştirici olduğunun
kanıtı — BTCUSD canlı bir KEPT_SYMBOL olduğu için önemli.

Ayrıca düzeltilmiş motorla: KEPT_SYMBOLS modül tanı taraması ve
101-sembol tam evren taraması yeniden koşuldu (bkz.
`module_diagnostic_full_scan_results.json`,
`module_diagnostic_full_universe_results.json`; eski ön-düzeltme evren
sonucu `module_diagnostic_full_universe_results.PREFIX_BACKUP_2026-09-04.json`
olarak yedeklendi), web panelindeki modül örnek galerisi
(`webapp/data_module_examples.json`) yeniden üretildi.

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
│   ├── TradeBot_NOA_Recal.mq5   # GÜNCEL (2026-09-03) -- FVG+iFVG+OB+Trendline, KEPT_SYMBOLS
│   │                              (GOLD/BTCUSD/EURGBP), breakeven-stop, tek dosya çoklu-sembol
│   ├── TradeBot_NOA.mq5           # DEPRECATED -- 28 Ağustos bulgusundan önce, eski A+/trend mantığı
│   └── TradeBot_NOA_MultiSymbol.mq5  # DEPRECATED -- aynı eski mantık, çoklu-sembol iskeleti
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

## Durum (güncel, 2026-09-04)

İki paralel katman var:

**V1 — kural tabanlı strateji (FVG+iFVG+OB+Trendline), execution-ready,
kapsam GOLD/BTCUSD/EURGBP'ye daraltılmış.**
`strategy/config.py:KEPT_SYMBOLS = (GOLD, BTCUSD, EURGBP)` — eski
Round 1-3'teki 101 sembollük/10 sembollük geniş kapsam terk edildi
(bkz. yukarıdaki "2026-09-02/03" güncellemesi). Dört modül bağımsız
sinyal üretiyor (A+ confluence ve trend/EMA filtresi ablation'da fayda
göstermediği için kaldırıldı), her modülün kendi R-katı/SL tamponu/
breakeven-stop eşiği var, hepsi holdout'ta doğrulandı.

`mql5/TradeBot_NOA_Recal.mq5` -- GÜNCEL EA, `TradeBot_NOA.mq5` ve
`TradeBot_NOA_MultiSymbol.mq5`'in (ikisi de DEPRECATED, 28 Ağustos
bulgusundan önceki eski mantığı taşıyor) yerine geçti. Tek dosyada
3 sembolü birden işliyor, tick-bazlı dokunuş-izleme + market emriyle
çalışıyor (gerçek bekleyen limit emri yok). 2026-09-04'te gerçek MT5
Strategy Tester'da (GOLD, 2022-2026) koşuldu: **663 gerçek işlem, 4
modülün ve 3 sembolün hepsi tetiklendi, breakeven-stop doğrulanmış
şekilde çalıştı**; bu koşuda bulunan 2 gerçek hata (sinyal SL'i
geçmişken hâlâ denenmesi → broker reddi; kapalı piyasada breakeven
retry-spam'i) düzeltildi, temiz derleniyor. **Eksik kalan tek adım:**
Python kaynak-doğrusuyla (`strategy/signal_engine.py`) tam otomatik
sinyal-listesi paritesi -- `scratch_dump_signals_for_ea_parity.py` +
`scratch_compare_ea_parity.py` hazır, `LogSignalsOnly=true` ile bir
Strategy Tester koşusu daha gerekiyor (bkz. "Sıradaki adım").

**V2 — çok-zaman-dilimli araştırma hattı, geliştirme aşamasında.**
Immutable thesis lifecycle, leakage-safe feature engineering, causal
liquidity/OB/FVG kalite skorları ve counterfactual entry refinement
içeren kurumsal seviyede bir araştırma altyapısı kuruldu. Gerçek
2 milyon satırlık XAUUSD M1 verisi mevcut (2021–2026), ama discovery
koşusu şu ana kadar sadece küçük bir smoke-test fixture'ında ve bir
"ENGINEERING_SMOKE_ONLY" chunked coverage koşusunda çalıştı — tam
TRAIN/VALIDATION/TEST partition'larında GERÇEK strateji skorlaması
(win-rate/expectancy) henüz koşulmadı, bu yüzden V2'den henüz
kanıtlanmış bir strateji sonucu yok.

## Çoklu-sembol genelleme testi (TARİHSEL — kapsam artık 3 sembolle sınırlı)

`research/v2/data/run_multi_symbol_acquisition.py` ile gerçek MT5 M1
verisi toplanıyor; `backtest/run_multi_symbol_validation.py` ile V1
stratejisi her sembolde kendi train/val/test bölünmesiyle test
ediliyor (sonuçlar `backtest/results/V2_MULTI_*_validation.json`,
özet `backtest/results/V2_MULTI_validation_summary.json`).

**Round 1–2 (32 sembol) ve Round 3 (101 sembol, 54/101 validated)**
sonuçları hâlâ `backtest/results/` altında duruyor ama **bu sonuçlar
eski (28 Ağustos'tan önceki, buggy sinyal üretimiyle hesaplanmış)
metodolojiyle üretildi ve artık güvenilir değil** (bkz. dosyanın en
üstündeki KRİTİK bölüm). Kullanıcı kararıyla kapsam zaten 3 sembole
daraltıldığı için (bkz. "Durum") bu geniş-kapsam sonuçların yeniden
üretilmesi planlanmıyor -- sadece tarihsel referans olarak kalıyor.

## Sıradaki adım

1. **`TradeBot_NOA_Recal.mq5` ile `LogSignalsOnly=true` Strategy
   Tester koşusu (GOLD/BTCUSD/EURGBP)** -- `.set` dosyası hazır
   (`MQL5/Profiles/Tester/NOA_Recal_GOLD.set`), `scratch_compare_ea_
   parity.py` ile Python'un ürettiği sinyal listesiyle (`results/
   ea_parity/*.json`) tam otomatik diff alınacak. Tam eşleşmeden
   demoya alınmamalı.
2. Demo hesapta `TradeBot_NOA_Recal.mq5`'i (parite doğrulaması
   bittikten sonra) çalıştırmaya başlamak ve örneklem biriktirmek --
   `ea_monitor.py` ile izleme altyapısı zaten var.
3. H1 zaman diliminin devre dışı bırakılıp bırakılmayacağı kararı
   ERTELENMİŞ durumda (bkz. `NOA_KONSEPTI_KAYNAK_ANALIZI.md`, en son
   bölüm) -- 3 sembollük küçük holdout örnekleminde tutarsız çıktı
   (2/3 kötüleşti, GOLD'un kendi holdout'u tersini gösterdi). Daha
   büyük örneklem (KEPT_SYMBOLS'ün TÜM geçmişi, tek seferlik %20
   holdout yerine walk-forward/genişleyen pencere) olmadan karar
   verilmeyecek.
4. V2 discovery koşusunu gerçek veride (smoke fixture değil) TRAIN
   partition'ında çalıştırmak. RAM/süre sorunu chunked engineering-
   coverage koşusuyla (`research/v2/engine/run_v2_train_chunked.py`)
   aşıldı (1.003M mum, 51 chunk, tam TRAIN, ~95dk) ama bu sadece
   ENGINEERING_SMOKE_ONLY/QUARANTINED telemetri — gerçek strateji
   skorlaması (win-rate/expectancy) chunk bazında henüz üretilmedi.

## Kurulum

```bash
pip install -r requirements.txt
```
