# NOAFVGBOT Research Ledger

Bu dosya, 2026-09-07'de başlatılan kapsamlı "Research & Testing Lab"
çalışmasının (kullanıcının 52 bölümlük araştırma talimatı) HER deneyini
kaydeder -- başarılı/başarısız fark etmez. Amaç: kaç parametre/filtre/
zaman-dilimi/SL/TP/entry/exit denendiğini takip etmek (bölüm 31/50),
overfitting riskini görünür kılmak, ve OOS/holdout sonuçlarının SADECE
BİR KEZ kullanıldığından emin olmak.

Format (bölüm 31):
```
Experiment #NNN
Hypothesis:
Dataset / IS / Validation / OOS:
Parameters:
Result:
Decision: ACCEPT / REJECT / INFORMATIONAL (karar gerektirmeyen, sadece ölçüm)
```

Anlatım/gerekçe için ayrıca bkz. `NOA_KONSEPTI_KAYNAK_ANALIZI.md` (proje
genelindeki TÜM kalibrasyon tarihçesi, bu ledger'dan ÖNCEKİ dönemi de
kapsıyor -- bu ledger SADECE 2026-09-07'den itibaren başlayan "Research
Lab" çalışmasına özel).

---

## Experiment #001 -- Kutsal Holdout v2: bugünkü resmi config'in İLK KEZ tam testi

**Hypothesis:** projenin kendi en sıkı doğrulama altyapısı
(`backtest/final_holdout.py`/`validation.py`/`regime.py`), bugünkü resmi
stratejiyi (SL tampon 15/15/30/5, breakeven %50 fvg/ifvg/ob, shallow-edge
giriş, hacim teyidi, 2026-09-07 market-emri fill düzeltmesi) HİÇ görmedi
(`results/README.md` en kritik açık madde olarak işaretliyor, en son
2026-09-02'de ESKİ config ile çalıştırılmıştı). Bu, o boşluğu kapatan
İLK çalışma.

**Dataset:** KEPT_SYMBOLS (GOLD/BTCUSD/EURGBP), M30, tüm mevcut kanonik
geçmiş (GOLD: 2014-06-13 .. 2026-08-26, 137.317 mum).

**IS/Validation/WFA/OOS:** `split_chronological` %60/%20/%20 (train/val/
test) + val içi walk-forward pencereleri + son %20'nin TAMAMI tek-atımlık
kutsal holdout.

**Parametreler:** DEĞİŞTİRİLMEDİ -- `strategy/config.py`'nin BUGÜNKÜ
(2026-09-07) tüm resmi varsayılanları, sadece `spread` sembole göre
temsili değerle set edildi (GOLD=0.25, BTCUSD=20.0, EURGBP=0.00020, aynı
2026-09-02 çalışmasındaki gibi).

**Sonuç (3/3 sembol tamamlandı):**

| Sembol | TRAIN exp/pf/win | VAL exp/pf/win | WFA-OOS exp/pf/win | HOLDOUT exp/pf/win/maxDD | Sınıflandırma | 95% CI |
|---|---|---|---|---|---|---|
| GOLD | -0.0182 / 0.97 / 24.1% | -0.0646 / 0.89 / 23.2% | -0.0490 / 0.91 / 23.5% | **+0.0827** / 1.15 / 28.3% / 89.08R | VALIDATED MODERATE | [+0.0237, +0.1447] |
| BTCUSD | -0.1079 / 0.82 / 22.5% | -0.0456 / 0.92 / 23.8% | -0.0928 / 0.84 / 22.4% | **-0.0817** / 0.86 / 22.5% / 288.67R | **FAILED TO GENERALIZE** | [-0.1360, -0.0235] |
| EURGBP | -0.0803 / 0.86 / 22.0% | -0.2033 / 0.66 / 17.9% | -0.1791 / 0.71 / 19.3% | **-0.2375** / 0.62 / 17.9% / 1096.50R | **FAILED TO GENERALIZE** | [-0.2778, -0.1995] |

**Değerlendirme:** bu, tüm oturumun en önemli bulgusu.

1. **Tarihin ilk %80'i (train+val+walk-forward), 3/3 sembolde İSTİSNASIZ
   negatif expectancy** (win rate %17.9-24.1 arası) -- bugünkü resmi
   strateji, kendi geçmiş verisinin büyük çoğunluğunda zarar ediyor.
   Bu, "IS'te iyi ama OOS'ta kötü" (klasik overfit) paterninin bile
   ALTINDA -- IS (train) zaten kötü.
2. **BTCUSD ve EURGBP kutsal holdout'ta da FAILED TO GENERALIZE** --
   CI'ları TAMAMEN negatif (BTCUSD üst sınırı bile -0.0235R, EURGBP'de
   -0.1995R). EURGBP özellikle ağır: PF=0.62, win=%17.9,
   **maxDD=1096.50R** -- pratik olarak felaket seviyesinde.
3. **Sadece GOLD holdout'ta pozitif** (+0.0827R, CI tamamen pozitif,
   istatistiksel olarak "anlamlı") -- ama `maxDD=89.08R` holdout'un
   kendi içinde bile ağır, ve bu tek pozitif sonuç 3 sembolün SADECE
   1'i, ve stratejinin KENDİ train/val/walk-forward'ında (aynı sembol,
   GOLD) da negatif olduğu unutulmamalı.
4. Aday 6/7/8 (SL tamponu genişletme) kararlarının kendi mini train/
   val/holdout'ları (`scratch_sl_buffer_holdout_check.py` vb., SADECE
   SL parametresi ekseninde, kendi içinde metodolojik olarak sağlam)
   pozitif çıkmıştı -- ama stratejinin BÜTÜNÜ, projenin BAĞIMSIZ kutsal
   holdout'undan geçirildiğinde 2/3 sembolde açıkça başarısız. Bu,
   parça-parça (SL ekseni, breakeven ekseni, entry-depth ekseni...)
   holdout doğrulamasının, BÜTÜNSEL doğrulamanın yerini TUTMADIĞININ
   somut kanıtı -- bölüm 32'nin ("OOS kilidi") ve section 10'un
   ("robust expectancy > win rate") tam da uyardığı senaryo.

**KUTSAL KURAL uygulandı:** bu sonuca göre HİÇBİR parametre bu oturumda
değiştirilmedi/önerilmedi -- sadece ölçüldü ve raporlandı.

**Decision:** INFORMATIONAL / **KIRMIZI BAYRAK**. Sonraki araştırma
fazları (loss taxonomy, MAE/MFE, session/regime kırılımları) bu ışıkta
yürütülecek -- özellikle BTCUSD/EURGBP için "neden çalışmıyor" sorusu,
GOLD için "neden bu kadar kırılgan (89R maxDD)" sorusu önceliklendirilecek.
Canlı işlem hazırlığı (bölüm 48, S14) şu an için AÇIKÇA HAYIR.

**Kaynak script:** `scratch_holdout_validation_run_v2_current_config.py`,
çıktı `holdout_validation_results_v2_current_config.json`.

## Experiment #002 -- Kutsal Holdout v2, 101/101 evren + STRATEGY/EXECUTION ikili doğrulama metodolojisi

**Hypothesis:** Deney #001'in 3-sembollük pilotu (GOLD/BTCUSD/EURGBP) yeterli
değil -- kullanıcının açık talebiyle `_ALL_101_SYMBOLS`'in TAMAMI (frozen
universe, `results/holdout_v2_101/UNIVERSE_FROZEN.json`, 2026-09-07'de
sonuçlar bilinmeden donduruldu) aynı metodolojiyle test ediliyor.

**Metodoloji düzeltmesi (kullanıcı talebi, uygulandı):** STRATEGY VALIDITY
(PASS/FAIL/UNCERTAIN -- sadece CI/expectancy/n'e bakar) ve EXECUTION
VALIDITY (VALID/UNCERTAIN/INVALID -- sadece maliyet gerçekçiliğine bakar)
artık İKİ BAĞIMSIZ EKSEN (`research_dual_validity.py`). Hiçbir sembolde
gerçek broker spread/commission/slippage kalibre değil, tick-level veri
yok -- GOLD/BTCUSD/EURGBP dahi "temsili tahmin" (UNCERTAIN), gerçek
"VALID" hiçbir sembolde yok. Her sembol için test partisyonunda 4-seviyeli
(zero/low/median/high, ATR-orantılı) **SENTETİK** spread-duyarlılık
taraması + MAE/MFE özeti + tam provenance (universe/data/strategy/
parametre/run-id/timestamp) ekleniyor.

**Doğrulama (kritik):** GOLD/BTCUSD/EURGBP + ilk 15 küçük-sembol için bu
yeni alanlar SONRADAN eklendi (`scratch_augment_dual_validity.py` +
`scratch_backfill_mae_mfe_provenance.py`) -- train/val/walk-forward/
holdout/bootstrap sayılarının DEĞİŞMEDİĞİ SHA-256 hash karşılaştırmasıyla
doğrulandı (18/18 sembol, mismatch YOK).

**Durum (bu ledger girişinin yazıldığı an):** 19/101 tamamlandı (18 gerçek
+ pilot 3'ü içeriyor), 82 sembol kaldı, arka planda checkpoint'li/
kesintiye dayanıklı çalışıyor (`scratch_holdout_v2_101_universe.py`,
PID değişken -- `holdout_v2_101_pid_v4.txt`). Tahmini toplam süre: ~9-12
saat (sembol başına ~2-9 dakika, veri boyutuna bağlı).

**KUTSAL KURAL:** bu asamada hicbir parametre degistirilmedi/onerilmedi.

**Decision:** INFORMATIONAL / DEVAM EDİYOR -- 101/101 tamamlanınca GLOBAL
FORENSIC SUMMARY üretilecek (`scratch_aggregate_101_summary.py`).

---

## SONUÇ (101/101 TAMAMLANDI, 2026-09-07)

8/8 bütünlük kontrolü GEÇTİ (`scratch_pre_report_integrity_checks.py`):
coverage 101/101, precomputed metrikler değişmedi, evren budanmadı,
parametre hash'i TÜM run boyunca tek (`8c6ab463e4bef9b2`), provenance
eksiksiz.

**Global dağılım:** STRATEGY PASS=4 (%4), UNCERTAIN=25 (%25), FAIL=71
(%71), NOT_TESTED=1 (EURNOK, data insufficient, 649 mum). EXECUTION:
INVALID=97, UNCERTAIN=3 (GOLD/BTCUSD/EURGBP), VALID=0/101. Expectancy
dağılımı: ortalama -0.040R, medyan -0.044R, p25=-0.086R, p75=+0.008R --
**%71 negatif, %29 pozitif**. Hiçbir market family (Metals/FX_Majors/
FX_Crosses/FX_Exotics/Indices/Crypto/Energy) ortalamada pozitif değil
(Metals +0.016R ortalama en iyisi ama SADECE 4 sembol, GOLD'un tek başına
sürüklediği bir artefakt).

**EN ÖNEMLİ BULGU -- 4 PASS sembolün (GOLD, UK100, USDTRY, EURTRY)
TAMAMI AYNI mekanizmadan geçiyor:** her birinde LONG expectancy güçlü
pozitif (GOLD +0.776R/win%48.6/PF3.20, USDTRY +1.179R/win%57.1/PF4.84,
EURTRY +0.947R/win%50.0/PF3.99, UK100 +0.608R/win%44.7/PF2.62) ve SHORT
expectancy KATASTROFİK negatif (win rate %9.5-15.3, PF 0.28-0.49,
maxDD 458-891R). Karşılaştırma icin FAIL sembollerde (EURGBP/BTCUSD) bu
asimetri YOK -- iki yön de benzer kötü. USDJPY'de AYNI asimetri var
(long pozitif/short negatif) ama SHORT islem sayisi fazla oldugu icin
toplam yine negatif -- yani mekanizma DOGRULANDI: **PASS, sinyal
kalitesinden degil, holdout penceresinin (kabaca 2024-2026) o sembolde
tesadufen guclu tek yonlu trend olmasindan geliyor.** Bu, stratejinin
FVG/OB/Trendline mantığının gerçek bir çift-yönlü edge taşımadığının,
sadece "trend yönünde kalırsan kazanırsın" seviyesinde bir trend-takip
artefaktı olduğunun güçlü kanıtı.

**Ana karar sorusunun cevabı:** NOAFVGBOT NE evrensel bir edge taşıyor
NE DE belirli bir market ailesine özgü uzmanlaşmış bir strateji --
"PASS" olan her sembol, o sembolün holdout penceresinde tesadüfen güçlü
tek yönlü trend içinde olmasıyla açıklanıyor (bkz. yukarıdaki LONG/SHORT
asimetrisi). Enstrüman TİPİ (metal, endeks, EM kur, kripto) ile PASS/FAIL
arasında tutarlı bir ilişki YOK.

**GOLD özel not:** rank 4/100 (persentil %97), ama concentration analizi
(top-5 işlem çıkarılınca expectancy 0.0827→0.0776, sadece %6 düşüş)
GOLD'un birkaç şanslı işleme bağlı OLMADIĞINI gösteriyor -- ancak yıl/
çeyrek kırılımı (2025-Q1 +0.377R → 2025-Q4 -0.157R → 2026-Q3 -0.147R)
ve volatilite kırılımı (LOW ATR +0.176R vs HIGH ATR -0.044R, maxDD'nin
neredeyse tamamı HIGH-volatilite bucket'ından) ile birlikte
LONG/SHORT asimetrisi, GOLD'un "edge"inin rejime (2024-2026 boğa
piyasası) sıkı bağımlı olduğunu gösteriyor. Raporlanan 89.08R maxDD,
LONG tarafının kazançlarıyla SHORT tarafının 822R'lik kendi maxDD'sini
MASKELEDIĞİ için düşük görünüyor -- gerçek yapısal risk (SHORT sinyalleri
yön değiştirmeden ateşlemeye devam ederse) çok daha yüksek. Farklı zaman
dilimlerinde (H1/H2/H4/D1/W1) tutarlılık HENÜZ TEST EDİLMEDİ (bu çalışma
SADECE M30).

**KUTSAL KURAL uygulandı:** bu bulgulara göre hiçbir parametre
değiştirilmedi/önerilmedi.

**Decision:** INFORMATIONAL / **KIRMIZI BAYRAK (genişletilmiş)**. Kaynak:
`results/holdout_v2_101/GLOBAL_FORENSIC_SUMMARY.json`, tüm 101 sembol
detayı `results/holdout_v2_101/{SYMBOL}.json`.

## Experiment #003 -- 101x6 MTF genişlemesi (H1/H2/H4/D1/W1) + W1 yapısal kısıt bulgusu

**Hypothesis:** Deney #002'nin (M30, 101/101) tek zaman dilimiyle sınırlı
olduğu, kullanıcının 101x6=606 symbol-timeframe matrisi hedefiyle
genişletildi. M30 baseline DONDURULDU, DEĞİŞTİRİLMEDİ (hash doğrulandı,
`78e7d018...`, run öncesi/sonrası aynı).

**Sonuç -- kapsama:**

| TF | Kullanılabilir (ok) | Insufficient/Not-tested | Not |
|---|--:|--:|---|
| M30 | 100 | 1 (EURNOK) | Deney #002, dondurulmuş baseline |
| H1 | 100 | 1 (EURNOK) | Sağlıklı |
| H2 | 98 | 3 | Sağlıklı |
| H4 | 95 | 6 | Sağlıklı |
| D1 | 59 | 42 | Azalmış ama kullanılabilir örneklem |
| **W1** | **0** | **101** | **YAPISAL KISIT (aşağıda)** |

**KRİTİK TEKNİK BULGU -- W1 hiçbir sembolde test edilemedi:**
`research/v2/data/resampler.py` (projenin kendi çekirdek modülü, bu
oturumda değiştirilmedi) her hedef mum için KESİNTİSİZ %100 dolu M1
penceresi şartı koşuyor. W1 için bu 10.080 dakikanın TAMAMI demek --
ama her enstrüman (BTCUSD dahil) haftada en az bir piyasa-kapanış/veri
boşluğu içeriyor, bu yüzden HİÇBİR haftalık pencere HİÇBİR sembolde tam
olamıyor. Doğrulama: GOLD'da 869/869 aday hafta penceresinin TAMAMI
"incomplete". Modülün kendi docstring'i zaten sadece M3/M5/M15/M30 için
doğrulandığını belirtiyor -- H1/H2/H4'ün sağlıklı çıkması (küçük pencere
= kayıp az), D1'in azalmış-ama-kullanılabilir olması (orta pencere),
W1'in tamamen imkansız olması (büyük pencere = kayıp %100) aynı kök
nedenin farklı şiddetleri.

**Kullanıcı kararı (2026-09-08):** W1, 101/101 sembolde açık teknik
gerekçeyle `NOT_TESTED` olarak kapatıldı (kod/resampler DEĞİŞTİRİLMEDİ).
606 hedefi **505'e** (M30+H1+H2+H4+D1) revize edildi. Alternatif
seçenekler (gap-tolerant yeni resampler yazmak, D1'i yeniden değerlendirmek)
kullanıcıya sunuldu, kullanıcı en muhafazakar/değişiklik-gerektirmeyen
seçeneği tercih etti.

**KUTSAL KURAL uygulandı:** hiçbir strateji parametresi değişmedi. Bu,
bir VERİ PİPELİNE kısıtı -- strateji performansıyla ilgisi yok.

**Decision:** INFORMATIONAL. Kapsam: 505/505 (101x5, W1 hariç) hedeflendi,
her hücrede en az bir kayıt (ok/insufficient/not_tested) mevcut -- hiçbir
sembol sessizce atlanmadı. Sonraki adım: H1/H2/H4/D1 için GLOBAL FORENSIC
SUMMARY + MTF confluence/conflict analizi (M30 dahil 5 zaman dilimi
üzerinden).

### Ek bulgu -- Timeframe arttıkça expectancy monoton olarak kötüleşiyor

| TF | Ortalama exp | Medyan exp | %Pozitif | PASS sembolleri |
|---|--:|--:|--:|---|
| M30 | -0.0399R | -0.0440R | %29.0 | EURTRY, GOLD, UK100, USDTRY (4) |
| H1 | -0.0692R | -0.0741R | %14.0 | AUDNZD, EURTRY, GOLD, USDTRY (4) |
| H2 | -0.0966R | -0.1020R | %15.3 | EURTRY, USDTRY (2) |
| H4 | -0.1331R | -0.1495R | %20.0 | EURTRY, USDTRY (2) |
| D1 | -0.2245R | -0.3679R | %28.8 | **YOK (0)** |

**Monoton kötüleşme deseni** (M30→H1→H2→H4→D1: -0.040 → -0.069 → -0.097
→ -0.133 → -0.225R ortalama) çok net. GOLD, H2'den itibaren PASS
listesinden düşüyor -- sadece TRY çiftleri (USDTRY/EURTRY, muhtemelen
uzun vadeli devalüasyon trendi) H4'e kadar dayanıyor, D1'de onlar da
başarısız. **Dikkat:** D1 örneklemi resampler kısıtı yüzünden ciddi
daraldı (59/101, ~42 sembol NOT_TESTED) -- bu sonucun bir kısmı azalmış/
olası-önyargılı örneklemden kaynaklanıyor olabilir, tek başına "D1 kesin
çalışmıyor" kanıtı olarak okunmamalı, ama yön (kötüleşme) M30→H4 arası
(tam örneklemli) zaten çok net.

**Yorum:** Bu, önceki bulguyla (PASS sembollerin LONG/SHORT asimetrisi,
rejim-tailwind artefaktı) tutarlı -- daha yüksek zaman diliminde FVG/OB/
Trendline formasyonları seyrekleşiyor, işlemler cok uzun suruyor, ve
belirli bir donemsel trend tailwind'inden faydalanma sansı azalıyor.
Kaynak: `results/holdout_v2_101/MTF_TIMEFRAME_SUMMARY.json`.
