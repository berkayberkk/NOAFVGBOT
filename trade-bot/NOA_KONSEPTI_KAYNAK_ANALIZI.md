# N/O-A Konsepti — Kaynak PDF Analizi vs Mevcut Kod

Kaynak: `NOA BOT ARŞİV/` altındaki 11 PDF (berofesorr, "N/O-A Konsepti").
Bu dosya, o kaynak materyaldeki kural setini `strategy/`, `backtest/`,
`research/v2/` içindeki mevcut implementasyonla karşılaştırır.

**Ana bulgu:** Mevcut V1 stratejisi (FVG + Order Block + Destek/Direnç
confluence) kaynak materyalin sadece küçük ve basitleştirilmiş bir alt
kümesi. Kaynaktaki gerçek sistem çok daha büyük bir mimari: Alan/Katman
zon yapısı + 4 modüllü güç hiyerarşisi + Alan Gücü puanlaması + Setup
Kalitesi grade sistemi + Eylem 1/2 giriş stili + DXY korelasyonu. Bunların
hemen hepsi kodda yok.

## Kavram sözlüğü (kaynak → tanım)

**Alan (Zone) — `ALANLAR 26.pdf`, `_FİZİK KURALLARI.pdf`**
- **N (Yeni Alan):** aktif trend. Başladığı noktadan bittiği/aktif kaldığı
  noktaya kadar fibonacci çekilir.
- **O (Eski Alan):** aktif trendden bir önceki trend/leg. Aynı şekilde uç
  noktalarına fib çekilir.
- Şu an sadece 5 fib seviyesi kullanılıyor: 0, 0.25, 0.50, 0.75, 1
  (ileride genişletilecek, kaynak "0.38 modülü" gibi ek seviyeler için
  ayrı bir çizim kullanıyor, aynı fib değil).
- **Yeni alan onayı — 2 kural (OR):**
  - Kural 1: gelen ters trend, aktif alanın **0.50** seviyesini kırar
    (fitil bile yeterli, kapanış şartı yok).
  - Kural 2: fiyat bir **modülden** (FVG, Wick Imbalance, 0.38, R.O.P)
    tepki verir.
- Alan geniş yapıda çizilmeli — 2-3 mumluk dar alanlar geçersiz.
- Yükselen alanda en düşük nokta, düşen alanda en yüksek nokta (0-0.25
  aralığı) esas alınır.

**Katman (Layer) — Eski Alan'ın fib'i 4 katmana bölünür — `EYLEM 1-2 - KATMANLAR.pdf`**
| Katman | Aralık | İşlem | Reaksiyon | Fakeout |
|---|---|---|---|---|
| K1 | 0 – 0.25 | **alınmalı** | maksimum | minimum |
| K2 | 0.25 – 0.50 | alınabilir | ortalama | düşük |
| K3 | 0.50 – 0.75 | **alınmaz** (sadece Kural 1'in "%50 kırıldı mı" teyidi için izlenir) | düşük | ortalama |
| K4 | 0.75 – 1 | **alınmaz** | minimum | maksimum |

**Ana Kural:** Fiyat %90-95 oranında Eski Alan'ın **Katman 1**'inden
tepki verir.

**Eylem 1 / Eylem 2 — giriş stili — `EYLEM 1-2 - KATMANLAR.pdf`, `KONDİSYONLAR.pdf`**
- **Eylem 1:** "garanti" (S+ setup kalitesi + hesaplı Alan Gücü) bir
  Katman 1'den **direkt** buy/sell limit emri — onay beklemeden.
  Yüksek tecrübe gerektirir, çünkü tepkinin geleceği net kestirilmek
  zorunda.
- **Eylem 2:** setup S+ değilse veya doğru modül tercihi belirsizse,
  **bir modülden tepki gelip yeni bir mikro-yapı oluşturmasını**
  bekleyip ondan sonra giriş. En önemli kural: "modülden tepki gelip
  yapı oluşturursa, Eylem 2."

**Modüller — güç sıralaması (`SETUP KALİTESİ.pdf`, `NOA'NIN FVG'Sİ.pdf`, `WICK IMBALANCE ROP.pdf`, `0.38.pdf`)**
1. **0.38 modülü** (en güçlü, puan=3) — Alan/leg'in (swing high→low)
   kendi fib'inde **0.382-0.5 bandı**, tek bir FVG gap'i değil. Rejection
   (reddiye) mumu ile teyit şart, kör giriş yok. 2 kullanılabilir seviye.
2. **Wick Imbalance** (puan=2) — mum fitillerinden çizilen FVG-benzeri
   yapı, kendi fib'i var, 2 seviye kullanılabilir, mesafe kuralı 5-9 /
   9-75 / 75-210 bar aralıklı.
3. **FVG** (puan=1) — mevcut kodun tek implement ettiği modül. Kaynağa
   göre mesafe kuralı **bar sayısı bazlı** (1-210 bar bearish, 1-280 bar
   bullish yapı için geçerli, ötesi geçersiz) — koddaki ATR-bazlı mesafe
   kuralı farklı bir kavram, aynı adı taşıyor ama aynı şeyi ölçmüyor.
   Sadece 1 kez kullanılır (dolunca tekrar kullanılmaz).
4. **R.O.P (Rejection Of Price)** (puan=0 taban + zaman dilimi bonusu) —
   fitil ucu kırılım + retest, ICT "Breaker Block" analogu.

**Alan Gücü — `_ALAN GÜCÜ.pdf`**
Eski Alan puanı vs Yeni Alan puanı karşılaştırması: modül reaksiyon
puanı + katman puanı + yapı-oluşum bonusu + enerji-dolumu bonusu +
zaman dilimi bonusu toplanır, hangi alan daha yüksek puanlıysa o
"kazanır" ve beklenen reaksiyon ona göre belirlenir. Kodda hiç yok.

**Setup Kalitesi — `SETUP KALİTESİ.pdf`**
Modül puanı + Katman puanı + Zaman dilimi puanı (Haftalık=4, Günlük=3,
H4=2, H1=1) toplamı → grade:

| Puan | Grade | Aksiyon |
|---|---|---|
| 9 | S+ | Max TP + Yüksek Lot |
| 8 | S | Yüksek TP + Ortalama Lot |
| 7 | A+ | Katman1 TP + Ortalama Lot |
| 6 | A | Katman1 TP + Ortalama Lot |
| 5 | B+ | Minimum TP + Düşük Lot |
| 4 | B | Minimum TP + Düşük Lot |
| 0-3 | C | **İptal** |

Kodda karşılığı yok — `strategy/signal_engine.py`'deki `Confidence`
(muhtemelen LOW/MEDIUM/HIGH) çok daha basit bir kavram, bu puanlama
sistemine denk gelmiyor, TP/lot'u dinamik olarak buna göre ayarlamıyor.

**İdeal TP-SL — `_İDEAL TP - SL.pdf`**
TP, sabit R:R değil; Katman 1 modülü / "Alan Bitiren" nokta / HTF
alternatifleri bazlı belirleniyor. Giriş kesinliğine (sniper mı değil
mi) göre TP'nin %30-%70'ine gelince breakeven'e çekme kuralı var.
`backtest/engine.py`'deki `_find_take_profit` mantığı bu kaynak kuralla
karşılaştırılmadı — muhtemelen uyumsuz.

**DXY Korelasyonu — `_DXY KORELASYONU.pdf`**
EURUSD/GBPUSD gibi majörler DXY ile ters korele (sabit offset ile:
EURUSD +0.14, GBPUSD +0.24 fib-seviye kayması); XAUUSD/BTCUSD DXY'den
bağımsız/dominant, basit ters korelasyon uygulanmaz. Kodda hiçbir DXY
veri hattı veya korelasyon mantığı yok.

**Fizik Kuralları / Kondisyonlar — `_FİZİK KURALLARI.pdf`, `KONDİSYONLAR.pdf`**
- Enerji Dolumu: fiyat sabit hızla sonsuza kadar hareket edemez —
  "enerji dolumu" (konsolidasyon) olmadan uzayan bir leg'den modül
  sinyali beklenmez.
- Bir modül seviyesine erken (tam mesafeye ulaşmadan) tepki verilirse,
  o modül ikinci kez kullanılmaz — bir sonraki denemede kırılacağı
  varsayılır.
- FVG 1 kez kullanılır (dolunca biter); 0.38/Wick Imbalance 2 seviyeye
  kadar kullanılabilir.

## Kod ile uyum tablosu

| Kavram | Kaynakta | Kodda | Durum |
|---|---|---|---|
| Alan/Katman (zone/swing fib yapısı) | Merkezi kavram | Yok — `strategy/fvg.py` docstring'i zaten bunu "henüz kodlamadığımız swing/zone yapısı" diye not ediyor | **büyük eksik** |
| FVG modülü | Var, bar-count mesafe kuralı | Var, ama ATR-bazlı farklı mesafe kuralı | **uyumsuz** |
| Wick Imbalance modülü | Var (2. güç sırası) | Yok | **eksik** |
| 0.38 modülü | Var (1. güç sırası) | Yok (önceki oturumdaki fib-prototip denemesi bunu FVG gap'inden türetmeye çalışmıştı — kavramsal olarak yanlış, bkz. aşağıdaki not) | **eksik** |
| R.O.P modülü | Var (4. sıra) | Yok | **eksik** |
| Multi-FVG kuralı | Var | Var (`_apply_multi_fvg_rule`) | uyumlu |
| Setup Kalitesi (S+/S/A+/A/B+/B/C) | Var, TP/lot'u belirliyor | Yok | **büyük eksik** |
| Alan Gücü puanlaması | Var | Yok | **büyük eksik** |
| Eylem 1 / Eylem 2 | Var | Yok — kod her zaman aynı şekilde limit emri koyuyor | **eksik** |
| İdeal TP-SL (katman/alan bazlı + BE) | Var | Muhtemelen farklı (kontrol edilmedi) | **kontrol edilmeli** |
| DXY korelasyonu | Var | Yok | **eksik** |
| Enerji Dolumu / modül tekrar kullanım kısıtı | Var | Yok | **eksik** |

## Önceki fib-retracement prototipiyle bağlantı

Bu oturumun başında test edilen `scratch_fib_fvg_prototype.py` (FVG
gap'inin 0.382/0.5/0.618 seviyelerinden giriş), sonucu metodolojik
olarak geçersiz çıkmıştı (tautolojik %0 baseline + n<15 örneklem).
Şimdi kaynağı okuyunca ek bir sorun daha görülüyor: kaynaktaki "0.38
modülü" zaten FVG'nin 3 mumluk gap'inden değil, **Alan/leg (swing
high-low) yapısından** çekiliyor ve rejection mumu şartı var. Yani o
prototip, doğru ölçülse bile yanlış kavramı test ediyordu.

## Sonuç

Bu, V1'in üstüne küçük bir ekleme değil — ayrı bir strateji katmanı
(muhtemelen mevcut V1/V2'den bağımsız bir "V3" olarak ele alınmalı).
Kapsam: swing/zone dedektörü (Alan), katman sınıflandırıcı, 3 yeni modül
(0.38, Wick Imbalance, R.O.P), Alan Gücü puanlayıcı, Setup Kalitesi
grade motoru, Eylem 1/2 karar mantığı, DXY veri hattı + korelasyon
modülü. Hangi parçadan başlanacağı ayrı bir karar gerektiriyor.

## Güncelleme — Alan/Katman dedektörü implement edildi

`strategy/zone.py` yazıldı: N/O Area (Yeni/Eski Alan), 4 Katman
sınıflandırması, sadece **Kural 1** (aktif alanın 0.50 seviyesinin
fitille kırılması) ile zone geçişi. **Kural 2 bilinçli olarak kapsam
dışı bırakıldı** — kaynak hangi modülün/ne kadar teyidin sayılacağını
hiç netleştirmiyor, ve şu an kodda sadece FVG modülü var; Wick
Imbalance/0.38/R.O.P eklenince ayrı bir işte ele alınacak. 15 birim
testi + tam test paketi (439 test) regresyon olmadan geçiyor.

**Gerçek GOLD M30 verisiyle doğrulama sonucu** (`scratch_zone_katman_validation.py`,
son 35.000 mum): 157 çözülmüş alan geçişinin **%31.2'si Katman 1'den,
%68.8'i Katman 2'den** tepki veriyor; Katman 3/4'ten **hiç** tepki
gözlenmedi (%0/%0).

Bu son nokta önemli bir metodolojik bulgu: `first_reaction_katman`
metriği ("bir sonraki alanın nihai ucu hangi katmana düştü") **yapısal
olarak K3/K4'ü hiç gösteremez** — çünkü Kural 1'in kendisi zaten "0.50
kırıldı mı" (K2/K3 sınırı) şartına dayanıyor; ölçüm ancak bu kırılma
GERÇEKLEŞTİKTEN sonra başlıyor, bu da otomatik olarak K1/K2 tarafına
yanlı hale getiriyor. Yani bu, kaynağın "%90-95 Katman 1'den tepki
verir" iddiasının **temiz/doğrudan bir testi değil** — kısmen destekler
(K1+K2 = tepkilerin tamamı, "derin" tarafta), ama K1 tek başına
sadece %31 (iddia edilen %90-95'in çok altında). Bu farkın nedeni
(a) kaynağın muhtemelen H4/Günlük/Haftalık ölçekte kalibre edilmiş
olması (burada sadece M30 test edilebiliyor, `Timeframe` enum'u daha
yükseğe çıkmıyor), (b) Kural 2'nin eksik olması, (c) `zone_swing_lookback`/
`zone_min_size_atr_ratio` varsayılanlarının kalibre edilmemiş olması,
veya (d) metrik tanımının kendisinin kaynağın kastettiği "ilk temas
noktası" yerine "nihai geri çekilme derinliği"ni ölçmesi olabilir.
Sonraki adım için: metriği "ilk temas + tepki teyidi" şeklinde
yeniden tanımlamak, ya da daha yüksek zaman diliminde (mevcut kod
M30'un üstünü desteklemiyor) test etmek gerekir.

## Güncelleme — Katman'ın V1 sinyallerine pratik etkisi test edildi (çok sembollü)

Farklı bir soru: "Ana Kural" istatistiksel olarak doğrulanmasa bile,
Katman etiketi mevcut V1 (FVG+OB) sinyallerini filtrelemek için pratik
bir değer taşıyor mu? `scratch_katman_signal_filter_multisymbol.py`
ile test edildi: `generate_signals()`'ın ürettiği her sinyal, oluştuğu
bardaki fiyatın en son donmuş Eski Alan'ın hangi Katman'ında olduğuna
göre etiketlendi, 18 çeşitli sembolde (FX majör, endeks, kripto, metal/
enerji, her biri son 10.000 M30 mum) trade'ler aynı katman kovasında
birleştirildi (checkpoint'li, kesintiye dayanıklı çalıştırıldı).

**Sonuç (561 toplam filled trade, kovalar n=43-212 arası — artık
istatistiksel olarak anlamlı bir örneklem):**

| Grup | filled | win% | exp_r | pf |
|---|---|---|---|---|
| TÜMÜ (baseline) | 561 | 89.1% | 0.504 | 7.26 |
| K1 | 43 | **81.4%** | **0.168** | 2.23 |
| K2 | 65 | 90.8% | 0.511 | 8.07 |
| K3 | 109 | 88.1% | 0.486 | 6.71 |
| K4 | 132 | 88.6% | 0.487 | 6.68 |
| NONE (katman yok) | 212 | **91.0%** | **0.590** | 9.91 |

**Bu, kaynağın iddiasını doğrulamıyor — tersini gösteriyor.** K1
("işlem alınmalı, maksimum reaksiyon") kovalar arasında en KÖTÜ
performansı gösteriyor (en düşük win rate, expectancy, profit factor);
hiçbir katman bağlamı olmayan sinyaller (NONE) en İYİ performansı
gösteriyor. K2/K3/K4 birbirine yakın ve baseline'a benzer.

Olası açıklamalar (hiçbiri doğrulanmadı, sadece olasılıklar):
1. Bu implementasyon sadece Kural 1'i içeriyor, Kural 2 yok — gerçek
   Katman sınıflandırması eksik/yanlış olabilir.
2. `zone_swing_lookback`/`zone_min_size_atr_ratio` varsayılanları
   kalibre edilmedi.
3. Confound: Katman etiketi ile hangi SetupType'ın (A+/FVG_ONLY/
   OB_ONLY) ateşlendiği arasında kontrol edilmemiş bir korelasyon
   olabilir.
4. Kaynağın iddiası, yazarın kendi manuel trading deneyimine dayanıyor
   olabilir ve bu haliyle (V1 stratejisiyle, M30'da, mevcut Katman
   tanımıyla) istatistiksel olarak doğrulanmıyor olabilir.

**Sonuç:** Mevcut haliyle Katman etiketi, V1 stratejisine bir filtre
olarak eklenmemeli — veri bunu desteklemiyor. Alan Gücü / Setup
Kalitesi / Eylem 1-2 gibi bu temelin üzerine inşa edilecek katmanlara
geçmeden önce, ya Kural 2 + diğer modüller (0.38/Wick Imbalance/R.O.P)
tamamlanıp tüm sistem birlikte test edilmeli, ya da bu bulgunun
kaynağın iddiasını gerçekten çürüttüğü kabul edilip yön değiştirilmeli.
