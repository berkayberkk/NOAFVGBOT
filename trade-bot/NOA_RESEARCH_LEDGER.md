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

---

## FAZ 2 BAŞLADI (2026-09-08) -- Kapsam daraltıldı: SADECE FVG/iFVG/OrderBlock/Trendline

Proje sahibi kararı: `zone.py` (N/O Alan/Katman konsepti) ve
`NOA_KONSEPTI_KAYNAK_ANALIZI.md`'deki kişisel konsept artık hiçbir
yeni araştırmada kullanılmıyor/referans alınmıyor (dosya silinmedi,
tarihsel kayıt olarak duruyor). Hedef: Deney #001-#003'te bulunan
LONG/SHORT asimetrisinin (4 PASS sembolün TAMAMINDA aynı desen) KÖK
NEDENİNİ bulmak.

## Experiment #004a -- TEŞHİS: asimetri hangi modülden geliyor?

**Hypothesis:** LONG/SHORT asimetrisi belirli bir modüle (örn. sadece
OB veya sadece FVG) özgü olabilir.

**Dataset:** 4 PASS sembol (GOLD/UK100/USDTRY/EURTRY), kutsal holdout
partisyonu (Deney #002'de ZATEN tüketilmiş/sabit sonucun modül×yön
kırılımına ayrıştırılması -- yeni bir holdout bakışı DEĞİL, deterministik
yeniden-türetme, hiçbir yeni karar bu veriye göre verilmedi).

**Sonuç:** **4 modülün TAMAMI (FVG/iFVG/OB/Trendline), 4 sembolün
TAMAMINDA aynı yönde asimetrik** -- BUY win rate %34-71, SELL win rate
sadece %7-26 (tek istisna: USDTRY Trendline_sell, n=41 küçük örneklem,
win %66 -- gürültü olarak değerlendiriliyor). Asimetri TEK bir modüle
özgü değil, TÜM modüllerde aynı büyüklükte.

**Decision:** INFORMATIONAL. Bu, asimetrinin modül-spesifik bir tanım
kusurundan değil, PAYLAŞILAN bir nedenden (rejim/dönem etkisi ya da
ortak kod yolu) geldiğine işaret ediyor -- Deney #004b bunu ayırt ediyor.

**Kaynak:** `scratch_exp004_diagnosis_module_direction.py`,
`scratch_exp004a_module_direction_breakdown.json`.

## Experiment #004b -- TEŞHİS: yapısal kod kusuru mu, rejim etkisi mi? (Ayna testi)

**Hypothesis:** Eğer modüllerin bullish/bearish tespit mantığı TAM
SİMETRİKSE, fiyat serisi dikey aynalandığında (yükselen trend düşen
olur, bullish mum bearish mum olur, TÜM ATR/gap/govde büyüklükleri
MUTLAK değer olarak korunur) orijinal LONG performansı ≈ aynalı SHORT
performansı, orijinal SHORT ≈ aynalı LONG olmalı. Eşitlik bozulursa
(aynalı dünyada da LONG hâlâ iyiyse) kodda bullish'i kayıran yapısal
bir asimetri vardır.

**Dataset:** 6 sembol (4 PASS + kontrol için 2 FAIL: BTCUSD/EURGBP),
SADECE train+val (%80) -- holdout HİÇ KULLANILMADI (kutsal kural,
muhafazakar uygulama).

**Sonuç -- 6/6 sembolde NEREDEYSE TAM SİMETRİ:**

| Sembol | Orijinal LONG exp | Aynalı SHORT exp | Orijinal SHORT exp | Aynalı LONG exp |
|---|--:|--:|--:|--:|
| GOLD | +0.1448 | +0.1447 | -0.1938 | -0.1946 |
| UK100 | -0.0330 | -0.0352 | -0.0750 | -0.0732 |
| USDTRY | +0.5360 | +0.5360 | -0.3382 | -0.3381 |
| EURTRY | +0.6767 | +0.6775 | -0.3422 | -0.3425 |
| BTCUSD | +0.0792 | +0.0779 | -0.2090 | -0.2089 |
| EURGBP | -0.1269 | -0.1291 | -0.0928 | -0.0938 |

İşlem sayıları da neredeyse birebir yer değiştiriyor (örn. GOLD orijinal
LONG n=6444 ↔ aynalı SHORT n=6442). **KESİN SONUÇ: modüllerin (FVG/iFVG/
OB/Trendline) bullish/bearish tespit kodunda YAPISAL BİR ASİMETRİ YOK.**
LONG/SHORT performans farkı %100 veri/rejime bağlı -- "hangi yön kazanır"
sorusu, fiyat serisinin kendi trendine göre belirleniyor, koda göre değil.

**Decision:** REJECT (yapısal kod kusuru hipotezi). Kök neden REJİM/DÖNEM
etkisi olarak doğrulandı -- Adım 2'ye (rejim filtresi hipotezi) geçiliyor.

**Kaynak:** `scratch_exp004b_mirror_symmetry_test.py`,
`scratch_exp004b_mirror_symmetry_results.json`.

## Experiment #004c -- HİPOTEZ TEST: rejim filtresi (trend.py, NOA'sız) asimetriyi düzeltiyor mu?

**Hypothesis:** trend.py'nin rejim filtresi (BUY sadece trend UP'ta, SELL
sadece trend DOWN'da) LONG/SHORT asimetrisini düzeltip genel expectancy'yi
iyileştirir.

**Dataset:** 101 sembolün TAMAMI (Deney #002/003 frozen universe, SADECE
4 eski PASS sembolde test etmek seçim yanlılığı olurdu) -- SADECE train+val
(%80), holdout HİÇ KULLANILMADI.

**Metodoloji notu:** sinyaller BİR KEZ üretildi, backtest BİR KEZ çalıştı
(run_backtest sinyaller arasında bağımsız) -- rejim filtresi POST-HOC
(işlem seçimi olarak) uygulandı, bu matematiksel olarak ayrı bir
backtest çalıştırmakla özdeş sonuç verir, sadece 2x maliyeti önler.

**Sonuç (100/101 değerlendirilebilir, EURNOK insufficient):**

| | Baseline | Rejim-filtreli |
|---|--:|--:|
| Ortalama expectancy | -0.0158R | -0.0172R |
| Medyan expectancy | -0.0175R | -0.0183R |
| İyileşen sembol | -- | 52/100 (%52) |
| Kötüleşen sembol | -- | 48/100 (%48) |
| Ortalama işlem tutma oranı | -- | %29.6 |

4 eski PASS sembol: GOLD delta=+0.0128, USDTRY delta=+0.0119, EURTRY
delta=+0.0089 (hafif iyileşme), **UK100 delta=-0.0155 (kötüleşme)**.

**Değerlendirme:** filtre işlem sayısının ~%70'ini feda ediyor ama
ortalama/medyan expectancy'de ANLAMLI bir iyileşme YOK (aksine hafif
kötü) -- iyileşen/kötüleşen sembol oranı (%52/%48) pratik olarak yazı-
tura. Bazı sembollerde "pozitif expectancy oranı" (%27->%34) artıyor
gibi görünse de bu, kullanıcının kendi tanımladığı **"Win Rate Tuzağı"**
paterni (bölüm 23/43) -- küçülen örneklemde gürültüyle şişen bir görünüm,
gerçek/sistemik bir düzeltme değil.

**KUTSAL KURAL:** holdout'a dokunulmadı, hiçbir parametre config.py'ye
yazılmadı.

**Decision:** REJECT (rejim filtresi hipotezi, basit haliyle). LONG/SHORT
asimetrisi rejim etkisi olduğu doğrulanmıştı (Deney #004b) ama trend.py'nin
BASİT (HH/HL+EMA yön uyumu) filtresi bunu SİSTEMATİK olarak
DÜZELTEMİYOR -- muhtemelen trend tespitinin kendisi de gecikmeli/gürültülü
olduğu için "rejime uygun" sayılan barların bir kısmı zaten rejim
DÖNÜŞÜNÜN yakınında oluyor. Adım 3'e (confluence + rejim filtresi birlikte)
geçiliyor, ama beklenti düşük tutulmalı.

**Kaynak:** `scratch_exp004c_regime_filter_test.py`,
`results/exp004c_regime_filter/*.json` (101 dosya).

## Experiment #004d -- HİPOTEZ TEST: konfluens (birden fazla modülün aynı yönde/yakında sinyal vermesi), rejim filtresiYLE BİRLİKTE, asimetriyi/expectancy'yi düzeltiyor mu?

**Hypothesis:** #004c rejim filtresini TEK BAŞINA test etti (REJECT). Bu
deney, konfluens (±10 bar içinde farklı bir modülden aynı yönde sinyal)
ile rejim filtresini BİRLİKTE test ediyor, 4 varyant (BASELINE/REGIME_ONLY/
CONFLUENCE_ONLY/CONFLUENCE_AND_REGIME) tek bir sinyal/backtest geçişinden
post-hoc çıkarılarak.

**Dataset:** 101 sembolün TAMAMI, SADECE train+val (%80), holdout HİÇ
KULLANILMADI.

**Sonuç (100/101 değerlendirilebilir, EURNOK insufficient):**

| | Baseline | Regime Only | Confluence Only | Confluence+Regime |
|---|--:|--:|--:|--:|
| Ortalama expectancy | -0.0158R | -0.0172R | +0.0036R | -0.0014R |
| Medyan expectancy | -0.0175R | -0.0183R | +0.0042R | +0.0013R |
| Toplam işlem sayısı | 1,117,205 | 328,219 | 669,929 | 202,162 |
| İşlem tutma oranı | %100 | %29.38 | %59.96 | %18.10 |

**Baseline vs CONFLUENCE_AND_REGIME:** İyileşen 69/100, Kötüleşen 31/100.
Ortalama delta +0.0144R, medyan delta +0.0219R.

**4 eski PASS sembol (baseline -> confluence+regime):**

| Sembol | Baseline | Regime Only | Confluence Only | Confluence+Regime | Delta |
|---|--:|--:|--:|--:|--:|
| GOLD | -0.0310 | -0.0182 | -0.0311 | -0.0094 | +0.0216 |
| UK100 | -0.0553 | -0.0708 | -0.0483 | -0.1171 | -0.0618 |
| USDTRY | +0.0991 | +0.1110 | +0.1225 | +0.1269 | +0.0278 |
| EURTRY | +0.1837 | +0.1926 | +0.1802 | +0.1619 | -0.0218 |

**Win Rate Tuzağı (CONFLUENCE_AND_REGIME):** 7/100 sembol (EURDKK, EURTRY,
EURUSD, HK50, NETH25, PLATINUM, XLMUSD) -- win rate baseline'dan yüksek
ama expectancy sabit/kötü.

**Değerlendirme:** CONFLUENCE_AND_REGIME ortalama/medyan expectancy'yi
baseline'a göre iyileştiriyor (medyan negatiften pozitife dönüyor) ve
sembollerin çoğunluğunda (%69) iyileşme var -- ama (1) toplam ortalama
HÂLÂ negatif, (2) işlem hacminin %82'si feda ediliyor, (3) 4 eski PASS
semboldeen ikisi (UK100 belirgin şekilde, EURTRY hafif) KÖTÜLEŞİYOR.
Rejim filtresinin katkısı (#004c ile tutarlı olarak) burada da net
değil -- CONFLUENCE_ONLY tek başına (regime olmadan) daha güçlü ve daha
az örneklem-maliyetli görünüyor (bkz. Experiment #006, ayrı doğrulandı).

**KUTSAL KURAL:** holdout'a dokunulmadı, hiçbir parametre config.py'ye
yazılmadı.

**Decision:** REJECT (confluence+regime BİRLİKTE hipotezi, canlıya alma
ölçütüyle). Net iyileşme var ama toplamda hâlâ negatif, işlem hacmi
çok büyük oranda feda ediliyor, ve 4 kanonik semboldeen UK100 belirgin
kötüleşiyor. Rejim bileşeni katkı sağlamıyor gibi görünüyor --
konfluensin KENDİ BAŞINA etkisi Experiment #006'da ayrı test edildi.

**Kaynak:** `scratch_exp004d_confluence_regime_test.py`,
`results/exp004d_confluence_regime/*.json` (101 dosya).

## Experiment #005 -- HİPOTEZ TEST: sabit R-katı TP yerine Destek/Direnç tabanlı TP, expectancy'yi artırıyor mu? (4 modül AYRI AYRI)

**Hypothesis:** Sinyal yönünde en yakın S/R seviyesi TP adayı olarak
denenir (uygun seviye yoksa mevcut sabit R-katına fallback, sinyal
ASLA iptal edilmez). 4 modül (FVG/iFVG/OB/Trendline) kendi mevcut
sabit-R TP baseline'ına karşı AYRI AYRI karşılaştırıldı.

**Dataset:** 101 sembolün TAMAMI, SADECE train+val (%80), holdout HİÇ
KULLANILMADI.

**Sonuç (100/101 değerlendirilebilir; trendline'da ayrıca 1 sembol
no_events -> 99/100):**

| Modül | Baseline exp (ort.) | SR-TP exp (ort.) | Baseline exp (medyan) | SR-TP exp (medyan) | İyileşen/Kötüleşen | İşlem tutma | Win Rate Tuzağı |
|---|--:|--:|--:|--:|--:|--:|--:|
| FVG | +0.0028 | -0.0049 | +0.0039 | -0.0050 | 41/59 | %100.92 | 59/100 |
| iFVG | +0.0077 | -0.0116 | +0.0078 | -0.0115 | 24/76 | %100.47 | 76/100 |
| OB | -0.0412 | -0.0316 | -0.0414 | -0.0309 | 53/47 | %103.24 | 47/100 |
| Trendline | +0.0944 | +0.0487 | +0.0879 | +0.0570 | 29/70 | %100.13 | 70/99 |

Her 4 modülde de "kötüleşen" sembol sayısı ile "Win Rate Tuzağı" sayısı
BİREBİR EŞİT (FVG 59=59, iFVG 76=76, OB 47=47, Trendline 70=70) --
kötüleşen sembollerin TAMAMI aynı zamanda win rate artışı + expectancy
sabit/düşüş paterni gösteriyor.

**TP mesafesi analizi (R cinsinden, backtest'siz, tüm sinyaller havuzlanmış):**

| Modül | Sabit R (baseline) | Fiilen kullanılan TP mesafesi (ort.) | Oran | S/R TP bulunma oranı | Fallback oranı |
|---|--:|--:|--:|--:|--:|
| FVG | 1.5000 | 0.0771 | 0.0514x (~19x daha yakın) | %98.1 | %1.9 |
| iFVG | 1.5000 | 0.0905 | 0.0603x (~17x daha yakın) | %99.4 | %0.6 |
| OB | 3.0000 | 0.2174 | 0.0725x (~14x daha yakın) | %98.9 | %1.1 |
| Trendline | 2.0000 | 0.1263 | 0.0631x (~16x daha yakın) | %99.6 | %0.4 |

**Değerlendirme:** S/R tabanlı TP, sinyallerin ezici çoğunluğunda
(%98.1-99.6) fallback'e DÜŞMEDEN kullanılıyor, ve fiilen kullanılan TP
mesafesi sabit R-katından 14-19 KAT DAHA YAKIN. Bu, gözlemlenen win-rate
artışı + expectancy sabit/düşüş paternini (Win Rate Tuzağı, her modülde
kötüleşen sembol sayısıyla birebir örtüşüyor) MEKANİZMA OLARAK sayısal
şekilde doğruluyor -- TP çok yakın geldiği için işlemler daha sık kazanıyor
ama kazanç/R çok küçüldüğü için net expectancy iyileşmiyor (3 modülde
açıkça kötüleşiyor, OB'de marjinal/ihmal edilebilir).

**KUTSAL KURAL:** sonuç ne çıkarsa çıksın config.py'ye HİÇBİR YAZMA
YAPILMADI -- bu SADECE ölçüm.

**Decision:** REJECT (S/R tabanlı TP hipotezi, 4 modülün TAMAMINDA).
FVG/iFVG/Trendline'da net kötüleşme, OB'de istatistiksel olarak
ihmal edilebilir/karışık (53/47 iyileşen/kötüleşen, ort. delta
+0.0097R ama medyan delta sadece +0.0030R). TP mesafesi analizi kök
nedeni (S/R TP'nin sabit R'den 14-19x daha yakın gelmesi) kesin olarak
tespit etti.

**Kaynak:** `scratch_exp005_sr_based_tp_test.py`,
`results/exp005_sr_tp/*.json` (101 dosya).

## Experiment #006 -- DOĞRULAMA: Confluence-only (rejimsiz) etkisi, #004d'nin CONFLUENCE_ONLY varyantı üzerinden AYRI test edildi

**Hypothesis:** #004d'de CONFLUENCE_ONLY (rejimsiz) varyantı baseline'a
göre pozitif ortalama/medyan expectancy gösterdi -- bu, eski metodolojiyle
(zone-overlap tanımı, KEPT_SYMBOLS, 3-4 sembol) yapılmış önceki
"confluence faydasız" bulgusuyla ÇELİŞİYOR. Bu deney, #004d'nin ZATEN
ÜRETİLMİŞ CONFLUENCE_ONLY verisini (yeniden hesaplama YAPILMADI) baseline
karşısında TAM 101 sembollük tabloyla, aykırı-değer ve Win Rate Tuzağı
kontrolleriyle doğruluyor.

**Dataset:** #004d ile AYNI (101 sembol, train+val, holdout HİÇ
KULLANILMADI) -- veri kaynağı `results/exp004d_confluence_regime/*.json`,
yeniden backtest ÇALIŞTIRILMADI.

**Sonuç (100/101 değerlendirilebilir):**

| | Baseline | Confluence Only |
|---|--:|--:|
| Ortalama expectancy | -0.0158R | +0.0036R |
| Medyan expectancy | -0.0175R | +0.0042R |
| Toplam işlem sayısı | 1,117,205 | 669,929 |
| İşlem tutma oranı | %100 | %59.96 |
| Pozitif-expectancy sembol sayısı | 27/100 | 56/100 |

**İyileşen/Kötüleşen:** 88/100 iyileşen, 12/100 kötüleşen, 0 eşit.
Ortalama delta +0.0194R, medyan delta +0.0176R.

**Aykırı-değer kontrolü (top-5 sembol çıkarılınca):** ortalama delta
+0.0194R -> +0.0168R, ortalama confluence-only expectancy +0.0036R ->
+0.0039R (neredeyse değişmiyor) -- **sonuç geniş tabanlı, birkaç
aykırı sembole bağlı DEĞİL**. Top-5: SA40 (+0.0816), EURDKK (+0.0733),
GERTECH30 (+0.0691), GBPNOK (+0.0581), GBPSEK (+0.0548).

**USDTRY/EURTRY özel kontrolü:** USDTRY delta=+0.0234 (100 sembol
içinde 37. sırada, orta seviye). **EURTRY delta=-0.0035 (94. sırada --
KÖTÜLEŞEN sembollerden biri)**. Pozitif ortalama bu iki sembole
bağlı DEĞİL.

**Win Rate Tuzağı (confluence-only):** 6/100 sembol (EURCHF, EURTRY,
GBPAUD, GERMID50, GOLD, TAIWAN) -- #004d'nin confluence+regime'deki
7/100'üne yakın, benzer küçük oran.

**Ek not -- Trendline modülünün diğer 3 modülden ayrışması (Exp #005
baseline verisi, S/R-TP'siz, sabit R-katıyla):**

| Modül | R-katı | Sembol başı ort. sinyal | Ort. win rate | Ort. expectancy | Ort. profit factor | Ort. işlem tutma (bar) |
|---|--:|--:|--:|--:|--:|--:|
| FVG | 1.5 | 1,588 | 0.2982 | +0.0028 | 1.0105 | 781.6 |
| iFVG | 1.5 | 2,710 | 0.3018 | +0.0077 | 1.0189 | 428.7 |
| OB | 3.0 | 6,442 | 0.2156 | -0.0412 | 0.9342 | 1872.9 |
| Trendline | 2.0 | 436 | 0.3595 | +0.0944 | 1.1636 | 143.0 |

Trendline diğer 3 modülden 4-15 kat daha az sinyal üretiyor, en yüksek
win rate ve tek PF>1.1 olan modül, ve çok daha kısa ortalama tutma
süresi gösteriyor -- en seyrek/seçici sinyal kaynağı.

**KUTSAL KURAL:** holdout'a dokunulmadı, hiçbir parametre config.py'ye
yazılmadı -- bu SADECE ölçüm, canlıya alma kararı verilmedi.

**Decision:** ACCEPT (hipotez olarak -- confluence-only'nin train+val'de
net, geniş tabanlı, aykırı-değere bağlı olmayan pozitif etkisi
doğrulandı). Eski "confluence faydasız" bulgusuyla çelişki, eski
metodolojinin (zone-overlap tanımı, dar KEPT_SYMBOLS örneklemi) farklı
ölçüm biçiminden kaynaklanıyor olabilir -- bu deney yeni/basit index-
yakınlığı tanımıyla ve TAM 101 sembol evreniyle ölçüldü. Canlıya
alma/config değişikliği kararı KULLANICIYA bırakılıyor.

**Kaynak:** `results/exp004d_confluence_regime/*.json` (101 dosya,
CONFLUENCE_ONLY alanı) -- ayrı bir script/backtest çalıştırılmadı.

## Experiment #007 -- Trendline-only izolasyonu + ayna testi (regime-artifact kontrolü)

**Hypothesis/Şüphe:** Exp #005'in baseline tablosunda Trendline tek başına
(+0.0944R ort.) Confluence-only'nin (#006, +0.0036R) sonucundan çok daha
güçlü -- #006'nın pozitif bulgusu aslında Trendline'ın kombinasyonlara
dahil olmasından mı kaynaklanıyor? Ayrıca Trendline'ın kendisi #004b'deki
gibi bir rejim-artefaktı mı, yoksa gerçek/rejim-bağımsız bir edge mi?

**KUTSAL KURAL:** SADECE train+val (%80), holdout HİÇ KULLANILMADI --
tüm adımlarda. Hiçbir parametre config.py'ye yazılmadı.

### ADIM 1 -- Trendline-only, 101 sembol, sabit R-katı (S/R-TP DEĞİL), tam baseline tablosu

(Kaynak: `results/exp005_sr_tp/*.json`'daki `trendline.baseline_fixed_r`
alanı -- yeniden hesaplama YAPILMADI.)

**Sonuç (99/101 değerlendirilebilir; EURNOK insufficient, USFANG no_events):**

| Metrik | Değer |
|---|--:|
| Ortalama expectancy | +0.0944R |
| Medyan expectancy | +0.0879R |
| Ortalama win rate | 0.3595 |
| Ortalama profit factor | 1.1636 |
| Pozitif-expectancy sembol oranı | 80/99 (%80.8) |
| PF>1 sembol oranı | 80/99 (%80.8) |
| Win Rate Tuzağı (win_rate>0.50 AND expectancy<=0) | 0/99 |
| Ortalama sinyal/sembol | 436.2 |
| Ortalama işlem tutma süresi | 143.0 bar |

En kötü 5: BTCUSD (-0.1108), GOLD (-0.0903), USDHUF (-0.0797), MATICUSD
(-0.0706), CHFSGD (-0.0641). En iyi 5: FRA40 (+0.3058), US500 (+0.3075),
IT40 (+0.3204), USDHKD (+0.4132), GERTECH30 (+0.7731, n=12 -- küçük
örneklem).

4 eski PASS sembol Trendline-only'de KARIŞIK: UK100 (+0.0395) ve USDTRY
(+0.0285) pozitif, ama **GOLD (-0.0903) ve EURTRY (-0.0259) negatif** --
geniş tabanlı agregat pozitif olsa da, bu 4 sembolün tamamında tutarlı
DEĞİL.

### ADIM 2 -- Ayna testi (#004b metodolojisi, AYNI 6 sembol: GOLD/UK100/USDTRY/EURTRY/BTCUSD/EURGBP), SADECE Trendline

| Sembol | Orijinal LONG exp | Aynalı SHORT exp | \|delta\| | Orijinal SHORT exp | Aynalı LONG exp | \|delta\| | Yön değişti mi? |
|---|--:|--:|--:|--:|--:|--:|:--:|
| GOLD | -0.0139 | -0.0179 | 0.0040 | -0.1717 | -0.1962 | 0.0245 | EVET |
| UK100 | +0.0361 | -0.0167 | 0.0528 | +0.0426 | +0.0934 | 0.0508 | EVET |
| USDTRY | +0.2720 | +0.2720 | 0.0000 | -0.1210 | -0.1141 | 0.0069 | EVET |
| EURTRY | +0.1369 | +0.1764 | 0.0395 | -0.1361 | -0.1411 | 0.0050 | EVET |
| BTCUSD | -0.1955 | -0.2244 | 0.0289 | -0.0252 | -0.0246 | 0.0006 | EVET |
| EURGBP | +0.2040 | +0.1022 | 0.1018 | -0.0970 | -0.1329 | 0.0359 | EVET |

**Simetri:** orijinal-LONG/aynalı-SHORT ve orijinal-SHORT/aynalı-LONG
çiftleri 6/6 sembolde YAKIN (ort. mutlak fark ≈0.029R, USDTRY'de neredeyse
BİREBİR: 0.2720=0.2720) -- Trendline'ın bullish/bearish (ASCENDING/
DESCENDING) tespit kodunda YAPISAL bir asimetri YOK, #004b'nin diğer 4
modül için bulduğu sonuçla TUTARLI.

**"Hangi yön kazanıyor" testi:** 6/6 sembolde, aynalama sonrası kazanan
yön DEĞİŞTİ (ör. USDTRY orijinalde LONG kazanıyor +0.272, aynalı dünyada
SHORT kazanıyor +0.272 -- birebir yer değiştirdi; GOLD orijinalde LONG
"daha az kötü", aynalı dünyada SHORT "daha az kötü" oldu). Bu, #004b'nin
regime-etkisi imzasıyla BİREBİR aynı -- kod tarafsız, ama LONG/SHORT
performansı sembolün o dönemdeki rejimine/trendine bağlı.

### ADIM 3 -- Değerlendirme

Trendline ayna testini GEÇTİ (kod tarafsız) AMA yön-değişimi testi de
6/6 sembolde REJİM ETKİSİNİ doğruladı -- yani Trendline, GOLD/UK100/
USDTRY/EURTRY'nin bütün sistemde gösterdiği rejim-bağımlılığın AYNISINI,
kendi izole halinde de gösteriyor. **Trendline "temiz/rejim-bağımsız bir
edge" DEĞİL** -- diğer 3 modül gibi rejime bağımlı, sadece (ADIM 1'in
gösterdiği gibi) daha seyrek/seçici sinyal ürettiği için agregat halde
daha az gürültülü ve daha geniş tabanlı pozitif görünüyor (bkz. #006
ek notu: 4-15x daha az sinyal, en yüksek win rate, tek PF>1.1 modül).

### ADIM 4 -- Confluence-only sonucu Trendline'a mı bağlı? (101/101 TAMAMLANDI)

`scratch_exp007_confluence_trendline_split.py` -- #004d/#006 ile AYNI
sinyal/backtest geçişi, ama her confluence işlemi "Trendline dahil mi"
etiketiyle iki alt kümeye (confluence_with_trendline /
confluence_without_trendline) ayrıldı.

**Sonuç (100/101 değerlendirilebilir):**

| | Baseline | Confluence (tümü, #006) | ...Trendline DAHİL | ...Trendline HARİÇ |
|---|--:|--:|--:|--:|
| Ortalama expectancy | -0.0158R | +0.0036R | **+0.0417R** | **-0.0011R** |
| Medyan expectancy | -0.0175R | +0.0042R | +0.0372R | -0.0018R |
| Toplam işlem | 1,117,205 | 669,929 | 72,340 (%10.8) | 597,589 (%89.2) |

WITH_TL > WITHOUT_TL (sembol bazında): 69/99 sembol, WITHOUT_TL daha iyi:
30/99. Ortalama delta (WITH_TL - WITHOUT_TL) = +0.0423R, medyan +0.0402R.

**4 eski PASS sembol (WITH_TL vs WITHOUT_TL):**

| Sembol | Baseline | Confl (tümü) | WITH_TL (n) | WITHOUT_TL (n) |
|---|--:|--:|--:|--:|
| GOLD | -0.0310 | -0.0311 | -0.0960 (n=935) | -0.0234 (n=7847) |
| UK100 | -0.0553 | -0.0483 | +0.0665 (n=609) | -0.0628 (n=4812) |
| USDTRY | +0.0991 | +0.1225 | +0.1285 (n=424) | +0.1221 (n=7400) |
| EURTRY | +0.1837 | +0.1802 | +0.2300 (n=508) | +0.1770 (n=7837) |

**Değerlendirme:** #006'nın "confluence işe yarıyor" sonucu, ağırlıklı
ortalama olarak DOĞRU ama YANILTICI -- popülasyonun sadece %10.8'ini
oluşturan Trendline-dahil kombinasyonlar güçlü pozitif (+0.0417R),
popülasyonun %89.2'sini oluşturan Trendline-HARİÇ (yani FVG/iFVG/OB
arası) kombinasyonlar ise pratikte SIFIRA yakın/hafif negatif
(-0.0011R ort., -0.0018R medyan) -- yani FVG/iFVG/OB arasındaki
konfluensin KENDİ BAŞINA gerçek bir edge'i YOK, #006'nın toplam pozitif
görünümü neredeyse tamamen Trendline'ın katılımından geliyor. UK100'de
bu en çarpıcı biçimde görülüyor (WITHOUT_TL -0.0628, WITH_TL +0.0665 --
tam ters işaret). GOLD ise İSTİSNA: orada Trendline'ın katıldığı
kombinasyonlar baseline'dan da kötü (-0.0960) -- #007'nin Adım 1-3'ünde
zaten gösterildiği gibi Trendline GOLD'da (bu train+val döneminde)
zayıf/rejime-ters düşüyor olabilir.

**KUTSAL KURAL:** holdout'a dokunulmadı, config.py'ye hiçbir yazma
yapılmadı.

**Decision:** #006'nın CONFLUENCE_ONLY bulgusu için INFORMATIONAL DÜZELTME
-- ham "confluence pozitif" sonucu Trendline-kaynaklı bir karışım
etkisi (Simpson's paradox benzeri); FVG/iFVG/OB arası konfluensin kendi
başına REJECT edilmesi gerekir (~sıfır ort., %89 örneklem), asıl ilgi
Trendline'ın (zaten #007 Adım 1-3'te rejim-bağımlı bulunan) katılımında
yoğunlaşıyor.

**Kaynak:** `scratch_exp007_trendline_mirror_test.py`,
`scratch_exp007_trendline_mirror_results.json`,
`scratch_exp007_confluence_trendline_split.py`,
`results/exp007_confluence_trendline_split/*.json` (101 dosya).
