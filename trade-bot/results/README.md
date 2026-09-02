# Sonuç Arşivi (results/)

Bu klasör, projede şimdiye kadar üretilen tüm önemli test/kalibrasyon
sonuçlarının **kalıcı, git'e commit'lenen** kopyalarını tutar. Amaç:
bir bulguya tekrar ihtiyaç duyulduğunda, saatler süren backtest'leri
yeniden çalıştırmak yerine doğrudan bu dosyaları okumak.

**⚠️ ÖNCE OKU — 2026-09-02 KRİTİK BULGU:** Aşağıdaki `fvg/`, `ifvg/`,
`order_block/`, `trendline/`, `breakeven/`, `account_simulation/`
altındaki TÜM sonuçlar, projenin `backtest/final_holdout.py`/
`validation.py`/`regime.py`'deki rigorous walk-forward/holdout/block-
bootstrap altyapısından GEÇİRİLMEDEN, basit scratch-script simülasyonuyla
üretildi. Bu altyapıdan geçirildiğinde (bkz. `holdout_validation/`),
GOLD/BTCUSD/EURGBP'nin ÜÇÜNDE de TRAIN partisyonunda bile expectancy
NEGATİF çıktı, holdout "FAILED TO GENERALIZE" -- kök neden iki ayrı
metodolojik iyimserlik (OB'de aynı-barda-impuls-dolumu, TÜM modüllerde
aynı-barda-iyimser-TP-kabulü, ayrıntı `NOA_KONSEPTI_KAYNAK_ANALIZI.md`
"KRİTİK BULGU" bölümü ve `../README.md`). Aşağıdaki dosyalardaki
pozitif sayılar bu yüzden GERÇEK OLANDAN İYİ GÖRÜNÜYOR OLABİLİR --
bunları "kanıtlanmış edge" olarak DEĞİL, "ne kadar iyimser olduğu artık
bilinen, tarihsel bir çalışma kaydı" olarak oku.

Kaynak scriptler (`scratch_*.py`, hepsi proje kökünde) hâlâ bu dosyaları
üretebilir/güncelleyebilir — buradaki kopyalar üretildikleri anın
"dondurulmuş" hâlidir. Bir script yeniden çalıştırılıp sonuç değişirse,
yeni dosyayı bu klasöre kopyalayıp burayı güncellemek gerekir (otomatik
senkronize olmuyor).

Anlatım/gerekçe/karar tarihçesi için asıl kaynak her zaman
`../NOA_KONSEPTI_KAYNAK_ANALIZI.md` — bu README sadece "hangi dosyada ne
var" sorusuna hızlı cevap vermek için, tam hikaye orada.

Kapsam dışı bırakılanlar (bilinçli, boyut/önem nedeniyle):
- `trade_archive/` (95 sembol, 230.068 işlem, 618MB, mum pencereleriyle)
  -- git için çok büyük, proje kökünde `.gitignore`'da kalıyor, sadece
  yerel diskte duruyor. Yeniden üretmek için `scratch_trade_archive.py`
  (~5 saat, 95 sembol).
- `*_checkpoint.json` dosyaları -- bunlar nihai sonuç değil, kesintiye
  dayanıklılık için ara durum (resume noktası), tekrar üretilebilir.
- Erken D1-ölçekli prototip dosyaları (`gold_d1_*`) -- M30'a resmi geçiş
  öncesi keşif çalışmaları, sonraki M30 çalışmalarıyla süperseded.

---

## fvg/ — Fair Value Gap

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `fvg_tp_sl_study_results.json` | 101 sembol × 6 zaman dilimi × 8 R-katı taraması (RR-TP yöntemi) | `scratch_fvg_tp_sl_study.py` |
| `fvg_tp_sl_report_data.json` | Yukarıdakinin rapor/artifact için özetlenmiş hali | `scratch_fvg_tp_sl_study.py` |
| `fvg_tp_comparison_report_data.json` | RR-TP vs likidite-TP (en yakın alınmamış swing) karşılaştırması — RR açık farkla kazandı | `scratch_fvg_liquidity_tp_study.py` |
| `fvg_tp_study_liquidity_results.json` | Likidite-TP yönteminin ham tarama sonuçları | `scratch_fvg_liquidity_tp_study.py` |
| `fvg_report_data.json` | FVG modülünün ilk görsel doğrulama raporu verisi (GOLD D1) | erken keşif |

**Resmi parametreler** (`strategy/config.py`): R=1.5, SL tamponu=gap×1.0, H4 devre dışı.

## ifvg/ — Inverse FVG

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `ifvg_tp_sl_study_results.json` | 101 sembol × 6 zaman dilimi R-katı taraması (kırılım+retest+reddiye tanımıyla) | `scratch_ifvg_tp_sl_study.py` |
| `ifvg_top_trades_data.json` | Her sembolün en karlı iFVG işlemi + grafik penceresi (görselleştirme galerisi verisi) | `scratch_ifvg_top_trades.py` |
| `ifvg_vs_fvg_report_data.json` | iFVG'nin FVG'ye göre kalite karşılaştırması | erken keşif |

**Resmi parametreler:** R=1.5, SL tamponu=gap×1.0, H4 devre dışı.

## order_block/ — Order Block

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `ob_tp_sl_study_results.json` | 101 sembol × 6 zaman dilimi R-katı taraması (düzeltilmiş tanım: son zıt mum) | `scratch_ob_tp_sl_study.py` |
| `ob_tp_sl_report_data.json` | Rapor/artifact özeti | `scratch_ob_tp_sl_study.py` |
| `ob_top_trades_data.json` | Her sembolün en karlı OB işlemi + grafik penceresi | `scratch_ob_top_trades.py` |
| `ob_filters_study_results.json` | **NEGATİF SONUÇ**: engulfing/likidite-süpürmesi/HTF-premium-discount filtrelerinin hiçbiri kabul edilmedi — hepsi baseline'dan kötü çıktı (2026-09-02) | `scratch_ob_filters_study.py` |

**Resmi parametreler:** R=3.0, SL tamponu=gövde×3.0, W1 devre dışı.

## trendline/ — Trendline (diyagonal destek/direnç)

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `trendline_tp_sl_study_results.json` | 95 sembol × 6 zaman dilimi R-katı taraması (bounce + kırılım+retest) | `scratch_trendline_tp_sl_study.py` |
| `trendline_tp_sl_report_data.json` | Rapor/artifact özeti | `scratch_trendline_tp_sl_study.py` |
| `trendline_examples_data.json` | 8 gerçek GOLD örneği (ilk görsel doğrulama) | erken keşif |
| `trendline_top10_examples_data.json` | 10 örneklik galeri (TP/SL araştırmasından sonra) | `scratch_trendline_top10_examples.py` |
| `trendline_top20_examples_data.json` | 20 örneklik galeri (kırılım+retest eklendikten sonra) | `scratch_trendline_top20_examples.py` |

**Resmi parametreler:** R=2.0, SL tamponu=dokunuş barı ATR'sinin×0.5, H4 devre dışı. Dört modül
arasında hem en yüksek beklentili hem sembol bazında en tutarlı modül —
en kötü 10 sembolü bile pozitif beklenti veriyor.

## breakeven/ — Breakeven-Stop Eşik Kalibrasyonu

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `breakeven_sl_study_results.json` | İlk doğrulama: BE-stop (o zamanki %60 eşik) açık/kapalı karşılaştırması, KEPT_SYMBOLS | `scratch_breakeven_sl_study.py` |
| `breakeven_trigger_sweep_results.json` | Kaba tarama %30-80 (spread=0) — %60 optimal DEĞİL bulundu | `scratch_breakeven_trigger_sweep_study.py` |
| `breakeven_trigger_sweep_fine_results.json` | İnce tarama %5-30 (spread=0) — %5'te bile tepe bulunamadı, be oranı %46'ya çıktı | aynı script, `TRIGGER_PCTS` değiştirilerek |
| `breakeven_trigger_spread_sweep_results.json` | Temsili spread dahil tarama — sıralama aynı kaldı, mutlak değerler negatife döndü (BTCUSD/EURGBP'de) | `scratch_breakeven_trigger_spread_sweep_study.py` |

**Karar (2026-09-02):** `BREAKEVEN_TRIGGER_PCT = 0.5` (eskiden 0.6),
`BREAKEVEN_ENABLED_MODULES = ("fvg","ifvg","ob")` — Trendline hariç.
GOLD $10k hesap simülasyonunda doğrulandı: bileşik model ~7×, sabit-$
model +%21, max drawdown %22.6→%11.8 (bkz. `account_simulation/`).

## account_simulation/ — $10.000 Hesap Simülasyonları

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `gold_account_report_data.json` | **İLK TEST** — GOLD, 4 modül, 2020-2025, breakeven YOK. Bitiş: $25.44M (bileşik) / $90.950 (sabit-$), win %47.9, max DD %22.6 | `scratch_gold_account_simulation.py` + `_equity.py` |
| `gold_account_report_data_breakeven50.json` | **YENİ** — aynı kurulum, breakeven-stop %50 açık. Bitiş: $177.66M (bileşik) / $110.350 (sabit-$), win %39.1 (645 breakeven), max DD %11.8 | `scratch_gold_account_simulation_breakeven.py` |
| `gold_account_equity_data.json` | İlk testin equity eğrisi + top10 kazanan/kaybeden (grafik pencereli) | `scratch_gold_account_equity.py` |
| `multi_symbol_account_results.json` | 95 sembol, her biri bağımsız $10k hesap, breakeven YOK (eski metodoloji) — sembol/modül özetleri + tek en iyi/en kötü işlem | `scratch_multi_symbol_account_simulation.py` |
| `multi_symbol_account_report_data.json` | Yukarıdakinin rapor/artifact özeti (top10/bottom10 sembol, histogram) | aynı |

**Not:** `multi_symbol_account_results.json` breakeven-stop'suz eski
metodolojiyle üretildi (2026-09-01, breakeven-stop'tan önce). %50
breakeven ile 95 sembol ölçeğinde yeniden üretilmedi — GOLD'daki büyük
iyileşme (yukarıda) diğer 94 sembolde de benzer yönde olabilir ama
DOĞRULANMADI, varsayılmamalı.

Tam işlem-bazlı arşiv (230.068 gerçek işlem, grafik pencereli, breakeven
%50 dahil güncel metodolojiyle) `trade_archive/{SEMBOL}.json` altında —
618MB olduğu için git'e değil, sadece yerel diske kaydedildi.

## holdout_validation/ — Rigorous Walk-Forward/Holdout Sonucu (EN GÜVENİLİR BULGU)

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `holdout_validation_results.json` | GOLD/BTCUSD/EURGBP için train/val/walk-forward/holdout metrikleri + block-bootstrap %95 CI + rejim kırılımı -- `backtest/final_holdout.py`'nin projenin ZATEN VAR OLAN rigorous altyapısı kullanılarak üretildi | `scratch_holdout_validation_run.py` |

**Bu, tüm `results/` içindeki DİĞER dosyalardan NİTELİKSEL OLARAK
FARKLI** -- diğerleri basit scratch-script simülasyonu, bu ise
projenin en sıkı doğrulama standardı (chronological split + walk-
forward + tek-atımlık kutsal holdout + block-bootstrap güven aralığı).
Sonuç: 3/3 sembolde TRAIN'de bile negatif expectancy, holdout'ta "FAILED
TO GENERALIZE", CI tamamen negatif. Ayrıntılı kök neden analizi (iki
ayrı same-bar iyimserliği) için `../README.md` ve
`../NOA_KONSEPTI_KAYNAK_ANALIZI.md`.

## confluence_and_filters/ — Ek Filtre / Confluence Ablation Testleri

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `confluence_study_results.json` | **NEGATİF SONUÇ**: 2-3-4 modülün aynı anda aynı yönde/bölgede sinyal vermesi ("confluence") kaliteyi artırmıyor — confluence=1/2 baseline'dan kötü, confluence=3'ün iyi görünmesi n=73 ile istatistiksel gürültü | `scratch_confluence_study.py` |
| `scratch_compare_overall.json` | Dört modülün genel (tüm semboller) karşılaştırması | modül birleşik rapor çalışması |
| `scratch_trendline_per_symbol_r2.json` | Trendline'ın sembol bazlı R² / tutarlılık analizi | Trendline kalibrasyon çalışması |

**Katman/Alan filtresi de negatif sonuç verdi** (K1 en KÖTÜ bucket
çıktı, NONE en iyisi) — bu dosya `results/`'a henüz kopyalanmadı, ham
sonuçlar commit `cd44e90` civarında üretildi; anlatı
`NOA_KONSEPTI_KAYNAK_ANALIZI.md`'de "Katman'ın V1 sinyallerine pratik
etkisi" bölümünde.

## Kök seviye

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `master_report_data.json` | 4 modülün (FVG/iFVG/OB/Trendline) birleşik lider tablosu | `scratch_master_report_aggregate.py` |
| `leaderboard_data.json` | Modül bazlı sembol liderlik sıralaması | aynı |
| `winrate_presentation_data.json` | Tüm sembollerin win rate dağılımı (sembol eleme turlarının dayanağı) | sembol eleme çalışması |

---

## Üç ana ampirik bulgu (hepsi burada belgeleniyor)

1. **Ek filtreler işe yaramadı** — OB'nin ICT filtreleri (`order_block/ob_filters_study_results.json`),
   Katman/Alan filtresi, ve çoklu-modül confluence
   (`confluence_and_filters/confluence_study_results.json`) üçü de
   ayrı ayrı test edildi, üçü de baseline'ı İYİLEŞTİRMEDİ. Mevcut basit
   V1 sinyalleri zaten sağlıklı; üstüne eklenen koşullar sadece
   örneklemi daraltıyor.
2. **Breakeven-stop (%50 eşik) net bir iyileştirme** —
   `breakeven/` altındaki üç aşamalı tarama + `account_simulation/`
   altındaki GOLD $10k karşılaştırması ile doğrulandı: kâr ve
   drawdown'da belirgin iyileşme, "düşen win rate" görünümü breakeven
   işlemlerin paydaya girmesinden kaynaklanan bir artefakt.
3. **Sembol seçimi kritik** — `winrate_presentation_data.json` ve
   `strategy/config.py:KEPT_SYMBOLS` tarihçesi, 101 sembollük evrenin
   yapısal olarak çok farklı performans gösterdiğini kanıtlıyor; şu an
   test kapsamı GOLD/BTCUSD/EURGBP'ye daraltılmış durumda.
4. **(EN ÖNEMLİSİ) Yukarıdaki 1-3'ün dayandığı TÜM ölçümler, rigorous
   walk-forward/holdout'tan geçirildiğinde muhtemelen gerçek olandan
   iyimser** — `holdout_validation/` bölümüne bak. İki ayrı same-bar
   iyimserliği (OB'de dolum, tüm modüllerde TP kabulü) bulundu ve
   ölçüldü; düzeltilmiş metodolojiyle 3/3 sembolde in-sample bile
   negatif expectancy çıktı. 1-3'ün YÖNÜ (hangi filtre/eşik diğerinden
   iyi) muhtemelen hâlâ geçerli (aynı iyimserlik hem baseline'ı hem
   varyantı etkiliyor, göreceli sıralamayı daha az bozuyor olabilir --
   ama bu VARSAYIM, test edilmedi), ama MUTLAK sayılar (PF, win rate,
   $ kâr) güvenilir değil.
