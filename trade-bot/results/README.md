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
| `fvg_entry_depth_study_results.json` | Giriş derinliği taraması (0.0=sığ kenar .. 1.0=derin kenar), DÜZELTİLMİŞ motor — sığ kenar (0.0) 3 sembolde de tutarlı en iyi, **BENİMSENDİ** | `scratch_fvg_entry_depth_study.py` |

**Resmi parametreler** (`strategy/config.py`, 2026-09-03 itibarıyla): R=1.5,
SL tamponu=gap×**15.0** (eski 1.0'dan güncellendi, bkz. `sl_buffer/`),
giriş=gap'in sığ/yakın kenarı (eski davranış: derin kenar), hacim teyidi
ELEME şartı (son 20 mumun ortalamasının 1.5 katı), H4 devre dışı.

## ifvg/ — Inverse FVG

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `ifvg_tp_sl_study_results.json` | 101 sembol × 6 zaman dilimi R-katı taraması (kırılım+retest+reddiye tanımıyla) | `scratch_ifvg_tp_sl_study.py` |
| `ifvg_top_trades_data.json` | Her sembolün en karlı iFVG işlemi + grafik penceresi (görselleştirme galerisi verisi) | `scratch_ifvg_top_trades.py` |
| `ifvg_vs_fvg_report_data.json` | iFVG'nin FVG'ye göre kalite karşılaştırması | erken keşif |

**Resmi parametreler:** R=1.5, SL tamponu=gap×**15.0** (eski 1.0'dan
güncellendi 2026-09-03, bkz. `sl_buffer/ifvg_sl_buffer_holdout_check_results.json`
ve `NOA_KONSEPTI_KAYNAK_ANALIZI.md` "Aday 7"), H4 devre dışı.

## order_block/ — Order Block

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `ob_tp_sl_study_results.json` | 101 sembol × 6 zaman dilimi R-katı taraması (düzeltilmiş tanım: son zıt mum) | `scratch_ob_tp_sl_study.py` |
| `ob_tp_sl_report_data.json` | Rapor/artifact özeti | `scratch_ob_tp_sl_study.py` |
| `ob_top_trades_data.json` | Her sembolün en karlı OB işlemi + grafik penceresi | `scratch_ob_top_trades.py` |
| `ob_filters_study_results.json` | **NEGATİF SONUÇ**: engulfing/likidite-süpürmesi/HTF-premium-discount filtrelerinin hiçbiri kabul edilmedi — hepsi baseline'dan kötü çıktı (2026-09-02) | `scratch_ob_filters_study.py` |
| `ob_entry_depth_study_results.json` | Giriş derinliği taraması (0.0=sığ kenar .. 1.0=derin kenar/eski govde ortası=0.5), DÜZELTİLMİŞ motor — sığ kenar (0.0) 3 sembolde de tutarlı en iyi, **BENİMSENDİ** | `scratch_ob_entry_depth_study.py` |

**Resmi parametreler:** R=3.0, SL tamponu=gövde×**30.0** (eski 3.0'dan
güncellendi, bkz. `sl_buffer/`), giriş=gövdenin sığ/yakın kenarı (eski
davranış: gövde ortası), W1 devre dışı.

## trendline/ — Trendline (diyagonal destek/direnç)

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `trendline_tp_sl_study_results.json` | 95 sembol × 6 zaman dilimi R-katı taraması (bounce + kırılım+retest) | `scratch_trendline_tp_sl_study.py` |
| `trendline_tp_sl_report_data.json` | Rapor/artifact özeti | `scratch_trendline_tp_sl_study.py` |
| `trendline_examples_data.json` | 8 gerçek GOLD örneği (ilk görsel doğrulama) | erken keşif |
| `trendline_top10_examples_data.json` | 10 örneklik galeri (TP/SL araştırmasından sonra) | `scratch_trendline_top10_examples.py` |
| `trendline_top20_examples_data.json` | 20 örneklik galeri (kırılım+retest eklendikten sonra) | `scratch_trendline_top20_examples.py` |

**Resmi parametreler:** R=2.0, SL tamponu=dokunuş barı ATR'sinin×**5.0**
(eski 0.5'ten güncellendi 2026-09-03, bkz. `sl_buffer/trendline_sl_buffer_holdout_check_results.json`
ve `NOA_KONSEPTI_KAYNAK_ANALIZI.md` "Aday 8"), H4 devre dışı.

**⚠️ NOT (2026-09-03):** yukarıdaki "en yüksek beklentili/en tutarlı
modül" karakterizasyonu, DÜZELTİLMEMİŞ (same-bar-iyimser) eski
metodolojiye dayanıyordu -- bkz. dosyanın en üstündeki "KRİTİK BULGU"
banner'ı. `sl_buffer/trendline_sl_buffer_holdout_check_results.json`
Trendline'ı İLK KEZ düzeltilmiş motor + gerçek holdout ile test etti:
resmi (sl=0.5) konfigürasyon 3 sembolde de negatif expectancy verdi
(GOLD -0.21R, BTCUSD -0.39R, EURGBP -0.94R holdout'ta) -- yani Trendline
de diğer üç modül gibi düzeltmeden önce iyimser görünüyormuş.

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
| `corrected_account_simulation_results.json` | **DÜZELTİLMİŞ MOTORLA** GOLD/BTCUSD/EURGBP $10k hesap simülasyonu (gerçekçi temsili spread, aynı-bar hataları yok) — 3/3 hesap pratikte sıfırlandı (GOLD $32, BTCUSD/EURGBP $0). Bu, win-rate araştırması ÖNCESİ orijinal sonuç | `scratch_corrected_account_simulation.py` |
| `corrected_account_simulation_results_v3_slbuffer.json` | FVG/OB SL tamponu genişletme (Aday 6) sonrası checkpoint — GOLD ilk kez sabit-$'da pozitif (+%7,9) | aynı script, Aday 6 sonrası |
| `corrected_account_simulation_results_v4_ifvg_slbuffer.json` | + iFVG SL tamponu (Aday 7) sonrası checkpoint — GOLD +%15,8 | aynı script, Aday 7 sonrası |
| `corrected_account_simulation_results_v5_all4_slbuffer.json` | **EN GÜNCEL** — + Trendline SL tamponu (Aday 8) sonrası, DÖRT modülün TÜMÜ güncellenmiş halde — GOLD +%19,2, 3 hesabın TOPLAMI $30.046,33 (**+$46,33 net, İLK KEZ pozitif**) | aynı script, Aday 8 sonrası |
| `corrected_multi_symbol_results_95.json` | **DÜZELTİLMİŞ MOTORLA** 95 sembolün TAMAMI, ama **spread=0** (diğer 92 sembol için gerçekçi spread tahmini yok) — 85/95 sabit-$ modelde pozitif. Aday listesi, kanıt DEĞİL (bkz. aşağıdaki not) | `scratch_corrected_multi_symbol_simulation.py` |

**Not (2026-09-02/03):** `multi_symbol_account_results.json` (eski,
breakeven-stop'suz) ve şimdi de `corrected_multi_symbol_results_95.json`
(yeni, düzeltilmiş motor ama spread=0) ikisi de KEPT_SYMBOLS
daraltmasının kendisinin hatalı/eksik metodolojiye dayandığını
gösteriyor -- düzeltilmiş motorla GOLD/BTCUSD/EURGBP gerçek spread'le
kaybettiriyor, ama AYNI motor spread=0 ile 95 sembolün %89'unu pozitif
gösteriyor. Sonuç: sembol seçiminin gerçek spread verisiyle YENİDEN
yapılması gerekiyor -- ne eski ne de bu yeni tarama, gerçek spread
olmadan güvenilir bir sembol listesi vermiyor.

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

## sl_buffer/ — SL Tamponu Yeniden Kalibrasyonu (2026-09-03, HOLDOUT ile doğrulandı)

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `sl_buffer_recalibration_results.json` | İlk tarama: FVG sl=0.25-3.0, OB sl=0.5-5.0 — win rate VE expectancy birlikte monoton iyileşiyor, üst uçta plato yok | `scratch_sl_buffer_recalibration_study.py` |
| `sl_buffer_recalibration_extended_results.json` | Genişletilmiş tarama: FVG sl=3.0-30.0, OB sl=5.0-50.0 — GOLD'da expectancy pozitife döndü, EURGBP'de sembol-özgü doygunluk noktası bulundu | `scratch_sl_buffer_recalibration_extended_study.py` |
| `sl_buffer_holdout_check_results.json` | **EN SIKI DOĞRULAMA (FVG/OB)**: her sembol kendi içinde kronolojik %60/%20/%20 bölündü, aday sl=15.0(fvg)/30.0(ob) SADECE train+val'da seçildi, HİÇ BAKILMAMIŞ test'te BİR KEZ çalıştırıldı — 6/6 sembol×modülde expectancy iyileşti (GOLD'da 2/2 pozitife döndü) | `scratch_sl_buffer_holdout_check.py` |
| `ifvg_sl_buffer_holdout_check_results.json` | **EN SIKI DOĞRULAMA (iFVG)**: aynı disiplin, aday sl=15.0 — 3/3 sembolde expectancy iyileşti (GOLD pozitife döndü) | `scratch_ifvg_sl_buffer_holdout_check.py` |
| `trendline_sl_buffer_holdout_check_results.json` | **EN SIKI DOĞRULAMA (Trendline)**: aynı disiplin, aday sl=5.0 — 3/3 sembolde expectancy iyileşti (BTCUSD pozitife döndü, GOLD'da iyileşme küçük) | `scratch_trendline_sl_buffer_holdout_check.py` |

**Karar: BENİMSENDİ.** `MODULE_SL_BUFFER_RATIO`: fvg 1.0→15.0, ob
3.0→30.0, ifvg 1.0→15.0, trendline 0.5→5.0. Bu, `results/` içindeki
DİĞER tüm dosyalardan (aşağıdaki "Kritik bulgu" banner'ının uyardığı
basit scratch-simülasyonlarından) farklı olarak, GERÇEK train/val/test
ayrımı + tek-atımlık holdout ile doğrulandı — `holdout_validation/` ile
aynı sıkılıkta. Ayrıntı: `NOA_KONSEPTI_KAYNAK_ANALIZI.md` "Aday 6/7/8"
bölümleri.

## trade_gallery/ — Tek Tek İşlem İnceleme Galerisi (görsel geri bildirim için)

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `GOLD_all_modules.json` | GOLD'da bugünkü resmi parametrelerle (Aday 1-8 dahil) tek-pozisyon modelinde GERÇEKTEN alınan 92 işlemin tamamı (SADECE M30) -- her biri kaynak yapısıyla (FVG/OB/iFVG bölgesi ya da Trendline slope/intercept'i) birlikte, mum penceresi dahil | `scratch_gold_trade_gallery.py` |
| `GOLD_mtf_summary.json` | GOLD, M30+H1 BİRLEŞİK tek-pozisyon $10k hesap simülasyonu özeti -- equity eğrisi, modül/zaman dilimi kırılımı, SL/breakeven kök neden (MFE) dağılımı | `scratch_gold_mtf_account_simulation.py` |
| `GOLD_mtf_trades.json` | Yukarıdakinin 55 işleminin tamamı, `mfe_pct`/`failure_reason`/`timeframe` alanları eklenmiş galeri formatında | aynı script |

**⚠️ Beklenmedik bulgu:** H1'i M30 ile AYNI tek-pozisyon hesaba eklemek
sonucu İYİLEŞTİRMEDİ, KÖTÜLEŞTİRDİ -- M30 tek başına $11.922 (+%19,2)
kazandırırken, M30+H1 birleşik sadece $10.188 (+%1,9) kazandırdı, çünkü
H1 hem kendi başına zayıf (win %10,0) hem de uzun pozisyon süresiyle
M30'un daha iyi fırsatlarını engelliyor (24.954 aday sinyalin %99,8'i
çakışma yüzünden atlandı). `MODULE_DISABLED_TIMEFRAMES`'e HENÜZ bir
değişiklik yapılmadı -- bu tek sembol/tek çalışma, KEPT_SYMBOLS
genelinde doğrulanmadan resmi karar değil. Ayrıntı:
`NOA_KONSEPTI_KAYNAK_ANALIZI.md` "GOLD işlem galerisi + çoklu-zaman-dilimi" bölümü.

`scratch_corrected_account_simulation.py::simulate_account` ile BİREBİR
aynı tek-pozisyon seçim mantığını kullanır (92/16.589 aday sinyalden
gerçekten alınanlar) -- yani buradaki işlemler, o checkpoint'in GOLD
satırındaki modül dağılımıyla (FVG n=25 win%40, iFVG n=25 win%36, OB
n=40 win%25, Trendline n=2 win%0) birebir eşleşir. Genişletilmiş SL/TP
tamponu bazı işlemleri çok uzun sürede (bazen binlerce bar) çözdüğü
için, pencere GİRİŞ dolumuna göre kuruluyor ve çıkış çok uzaktaysa ayrı,
kompakt bir "çıkış yakın çekimi" penceresi ekleniyor (`skipped_bars`
alanıyla aradaki atlanan bar sayısı not ediliyor) -- tüm geçmişi
saklamak dosyayı 19.8MB'den 564KB'a indirdi.

## confluence_and_filters/ — Ek Filtre / Confluence Ablation Testleri

| Dosya | İçerik | Kaynak script |
|---|---|---|
| `confluence_study_results.json` | **NEGATİF SONUÇ**: 2-3-4 modülün aynı anda aynı yönde/bölgede sinyal vermesi ("confluence") kaliteyi artırmıyor — confluence=1/2 baseline'dan kötü, confluence=3'ün iyi görünmesi n=73 ile istatistiksel gürültü | `scratch_confluence_study.py` |
| `winrate_filters_study_results.json` | Killzone + hacim teyidi ablation (DÜZELTİLMİŞ motor, iki ayrı temelde koşuldu) — killzone işe yaramadı, hacim teyidi FVG'de tutarlı iyileşme gösterdi, **BENİMSENDİ** (sadece FVG, eleme şartı olarak) | `scratch_winrate_filters_study.py` |
| `r_multiple_recalibration_results.json` | R-katı yeniden kalibrasyonu (0.5-5.0), YENİ giriş kuralıyla — expectancy'de ihmal edilebilir kazanç ama win rate sistematik düşüyor, **BENİMSENMEDİ** | `scratch_r_multiple_recalibration_study.py` |
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
