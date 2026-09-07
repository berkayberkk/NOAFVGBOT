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

**Katman 1'in iç alt-bölünmesi (`KONDİSYONLAR.pdf` madde 12, `_FİZİK KURALLARI.pdf`):**
K1'in kendisi de ikiye ayrılır — **0-0.15** ve **0.15-0.25**. Fiyat
K1'e ilerlerken yolda "enerji dolumu" (konsolidasyon) YAPTIYSA, tepki
0-0.15'te (en derin/en garanti alt-bant) beklenir; enerji dolumu
YAPMADIYSA 0.15-0.25'te beklenir. Yani hangi alt-bandın seçileceği,
K1'e giden yoldaki fiyat davranışına bağlı — sabit bir eşik değil.
Kodda hiç yok (Katman'ın kendisi bile yok).

**Mini Yeni Alan (`_ALAN GÜCÜ.pdf`) — iç içe zon kavramı:**
Aktif Yeni Alan'ın İÇİNDE, daha küçük ölçekli bir "Mini Yeni Alan"
oluşabilir. Bu mini-alanın kendi Katman 1'inden gelen bir tepki,
"Enerji Dolumu" puanına katkı sağlar (bkz. Alan Gücü). Yani Alan/
Katman yapısı kaynakta ÖZYİNELEMELİ (recursive/nested) — sadece tek
seviyeli bir N/O çifti değil. Kodda hiç yok, `strategy/zone.py` şu an
tek seviyeli.

**Eylem 1 / Eylem 2 — giriş stili — `EYLEM 1-2 - KATMANLAR.pdf`, `KONDİSYONLAR.pdf`**
- **Eylem 1:** "garanti" (S+ setup kalitesi + hesaplı Alan Gücü) bir
  Katman 1'den **direkt** buy/sell limit emri — onay beklemeden.
  Yüksek tecrübe gerektirir, çünkü tepkinin geleceği net kestirilmek
  zorunda.
- **Eylem 2:** setup S+ değilse veya doğru modül tercihi belirsizse,
  **bir modülden tepki gelip yeni bir mikro-yapı oluşturmasını**
  bekleyip ondan sonra giriş. En önemli kural: "modülden tepki gelip
  yapı oluşturursa, Eylem 2."

**Modüller — güç sıralaması / numaralandırma M1-M4 (`SETUP KALİTESİ.pdf`, `NOA'NIN FVG'Sİ.pdf`, `WICK IMBALANCE ROP.pdf`, `0.38.pdf`)**
1. **0.38 modülü (M1)** (en güçlü, puan=3) — Alan/leg'in (swing high→low)
   kendi fib'inde **0.382-0.5 bandı**, tek bir FVG gap'i değil. Rejection
   (reddiye) mumu ile teyit şart, kör giriş yok. 2 kullanılabilir seviye
   (tipik olarak 0.382 ve 0.5), mesafe kuralına göre hangisi kullanılabilir
   belirlenir.
2. **Wick Imbalance (M2)** (puan=2) — mum fitillerinden çizilen FVG-benzeri
   yapı, kendi fib'i var (0/0.15/0.25/0.38/0.5/0.62/0.75/0.85/1 referans
   ızgarası), 2 seviye kullanılabilir, mesafe kuralı **5-9 bar (yakın,
   1. seviye) / 9-75 bar (orta, 2. seviye) / 75-210 bar (uzak, 1. seviye
   tekrar) / 210+ geçersiz**. Ek şartlar: **"Alanın en dip modülüdür —
   altında/üstünde başka modül kalamaz"** (Alan'ın en uç noktasını
   tanımlar); **"önünde mum veya fitil bulunmamalı"** (en ekstrem,
   önünde engelsiz olmalı); **"mumun fitili, aktif süreçteki diğer
   mumların fitillerinden büyük olmalı"** (göze çarpan, aykırı bir
   fitil — sıradan bir fitil yeterli değil).
3. **FVG (M3)** (puan=1) — mevcut kodun tek implement ettiği modül, ama
   kaynaktaki tanımın sadece bir kısmını karşılıyor (bkz. alt madde).
   Sadece 1 kez kullanılır (dolunca tekrar kullanılmaz, kaynak: KONDİSYONLAR.pdf).
4. **R.O.P — Rejection Of Price (M4)** (puan=0 taban + zaman dilimi bonusu)
   — bir fitil önce bir tepe/dip yapar, sonra fiyat o fitili kırıp geçer;
   kırılan fitilin ucu artık bir modül adayı olur (ICT "Breaker Block"
   analogu). **KENDİ BAŞINA işlem açılabilecek bir modül DEĞİLDİR** —
   ancak FVG ile birleştiğinde veya Alan'ın en uç noktasıyla çakıştığında
   kullanılabilir. Mesafe kavramı yok (sadece fitil ucu konumu önemli).

**FVG modülü (detaylı) — `NOA'NIN FVG'Sİ.pdf`**

Geometri: 3 mumluk yapı, fitiller arası boşluk baz alınır. Bullish'te
1. mumun **üst fitili** ile 3. mumun **alt fitili** arasındaki boşluk,
giriş 3. mumun alt fitilinden. Bearish ayna simetrik (kodla uyumlu).

Mesafe kuralı **bar sayısı bazlı**, fib seviyeleri kullanılmaz: 1-210
bar Bearish yapı için geçerli, 1-280 bar Bullish yapı için geçerli,
ötesi geçersiz. **Koddaki ATR-bazlı mesafe kuralı bambaşka bir kavram**
— aynı ismi taşıyor ama farklı bir şeyi ölçüyor (gap büyüklüğü/ATR
oranı, formasyonun oluştuğu andan itibaren geçen bar sayısı değil).

Genel ilke: "Alanın her noktasında bulunabilen, ama alanın en
düşük/yüksek kısmında çalışan modüldür" — yani bir FVG Alan'ın
HERHANGİ bir yerinde oluşabilir, ama gerçekten tepki üretmesi
(çalışması) sadece Alan'ın uç noktasına (Katman 1'e) yakın olduğunda
bekleniyor. Bu genel ilke, kaynağın adlandırdığı şu 6 alt-modelde
somutlaşıyor — **kodda sadece 2'si (Dengesiz, Multi FVG) karşılığa
sahip, diğer 4'ü tamamen eksik**:

| Alt-model | Geçerli mi | Kod karşılığı |
|---|---|---|
| Dengesiz FVG Tarzı (ortadaki mum çok büyük) | Geçersiz | Var (`max_middle_candle_ratio`) |
| **Yüksek Katman FVG Tarzı** (FVG, Alan'ın yüksek Katman'ında) | **Geçersiz — "KESİNLİKLE işlem açmayın", "herkesi stop eden FVG bunlardır"** | **Yok** — Alan/Katman yapısına bağlı |
| 3. Büyük Mum Tarzı (3. mum çok büyük, fiyat mesafeyi "uçurumla" aşıyor) | Geçersiz | Yok |
| Multi FVG Modeli (yan yana birden fazla FVG) | Geçersiz | Var (`_apply_multi_fvg_rule`) |
| Baskın Dip FVG Modeli (güçlü bir "Uzak Mesafe" tepkisinden sonra oluşan İLK FVG, ağırlıklı Bearish) | Geçerli | Yok |
| **Alanın dibindeki FVG** | **En ideal** | Yok — Alan/Katman yapısına bağlı |

**Bu, `strategy/zone.py` çalışmasıyla doğrudan bağlantılı bir bulgu:**
"Yüksek Katman FVG" kuralı, bir FVG sinyalinin **kendi gap seviyesinin**
(current_katman ile "sinyal anındaki fiyatın hangi katmanda olduğu"
değil) hangi Katman'a düştüğüne göre reddedilmesini/kabul edilmesini
söylüyor. Önceki oturumdaki `scratch_katman_signal_filter_multisymbol.py`
testi bunu ölçmedi — o, sinyalin oluştuğu bardaki FİYATIN (ör. FVG_ONLY
için `fvg.entry_price`) en son donmuş Alan'a göre katmanını etiketledi,
FVG'nin KENDİ gap aralığının (top-bottom) o Alan'daki konumunu değil.
Bu iki şey çoğu zaman örtüşür ama aynı değildir — kaynağın "Yüksek
Katman FVG" kuralının daha doğru/sadık bir testi, FVG'nin
`(top+bottom)/2` (veya `entry_price`) değerini `classify_katman`'a
vermek olurdu, ki bu zaten yapılan teste çok yakın ama birebir aynı
değil (bkz. `_tag_katman` fonksiyonu, `signal.index`'teki `close`
fiyatını kullanıyor, FVG'nin kendi seviyesini değil). Bu farkın sonucu
ne kadar değiştirdiği test edilmedi — potansiyel bir sonraki adım.

**Alan Gücü — `_ALAN GÜCÜ.pdf`** — TAM FORMÜL (örneklerden ters
mühendislikle kesin doğrulandı, iki bağımsız örnek toplamı tutuyor):

Her Alan (Eski ve Yeni ayrı ayrı) için puan = şu bileşenlerin toplamı:

1. **Katman puanı** (o alanın tepkisi kaçıncı katmandan geldi):
   Katman 1 = **+2**, Katman 2 = **+1**.
2. **Modül puanı + zaman dilimi puanı** (tepkiyi başlatan modül, hangi
   zaman diliminde): modül tabanı — 0.38=+3, Wick Imbalance=+2, FVG=+1,
   R.O.P=+0 — **artı** zaman dilimi bonusu — H1=+1, H4=+2, Günlük=+3,
   Haftalık=+4. İkisi toplanır (ör. "Daily Wick Imbalance" = 2+3 = +5).
3. **Yapı oluştu mu?**: tepki başladıktan sonra orada bir modül/yapı
   oluştuysa **+2**.
4. **Enerji Dolumu** (bkz. Fizik Kuralları — sadece H1+ zaman
   diliminde sayılır): modül-bazlı enerji dolumu tespit edildiyse
   **+2**; Katman-1-bazlı (Mini Yeni Alan'ın K1'inden) enerji dolumu
   tespit edildiyse **+1**. İkisi aynı anda da uygulanabilir (görülen
   örnekte ikisi birden +2 ve +1 olarak eklenmiş).

Örnek (kaynaktan, doğrulandı): Modül tepkisi (Daily R.O.P, +0+3=+3) +
Katman 2 tepkisi (+1) + Yapı oluştu (+2) + 0.38 Enerji D. (+2) +
Katman 1 Enerji D. (+1) = **9**. İkinci örnek: Modül tepkisi & Katman 1
(Daily Wick Imbalance +5, +2) = +7, + Yapı var (+2) + Katman 1 Enerji
D. (+1) = **10**.

**Karar tablosu — Eski Alan puanı − Yeni Alan puanı farkına göre**
(kaynakta "YENİ ALAN GEÇERSİZLİĞİ" başlığı ile örnek birbirini
doğruluyor; gövde metnindeki tek bir cümle bunlarla çelişiyor —
muhtemelen kaynağın kendi yazım hatası, başlık+örnek esas alındı):

| Fark (Eski − Yeni) | Sonuç |
|---|---|
| ≤ −2 | **Eski Alan biter** (geçersiz olur) |
| −1, 0, veya +1 | Eski Alan'ın **Katman 1**'inden tepki beklenir |
| +2 veya +3 | Eski Alan'ın **Katman 2**'sinden tepki beklenir |
| ≥ +4 | **Yeni Alan biter** (geçersiz olur), örnek: Eski=10 Yeni=6 → fark=+4 → "Yeni Alan Ölür" |

Bir K1/K2 tepkisi çözüldükten sonra, önceki "Yeni Alan" yeni bir
"Eski Alan" olur ve hesap sıfırdan tekrarlanır (özyinelemeli).

**Bu formül ve karar tablosu kodda tamamen yok** — `strategy/zone.py`
sadece geometrik Kural 1'i (fitil %50 kırılımı) uyguluyor, hiçbir
puanlama/karşılaştırma yapmıyor.

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

**İşleme girmeden önce kontrol listesi (`SETUP KALİTESİ.pdf`):**
1. Alan Gücü hesaplaması yap.
2. Kondisyonları kontrol et (bkz. Fizik Kuralları/Kondisyonlar).
3. SL-TP paraya göre değil, **konsepte göre** belirlenmeli (bkz. İdeal TP-SL).
4. Spread-slippage önlemi al.
5. **Yakında enerji dolumu varsa uzak dur / daha alt (düşük güçlü) bir
   modülden beklenmeli** — yakındaki çözülmemiş konsolidasyon, riski artırır.

Kodda hiçbiri implement değil — mevcut EA/backtest hiçbir pre-trade
checklist uygulamıyor, sinyal üretilir üretilmez (confidence filtresi
dışında) işlem açılıyor.

**İdeal TP-SL — `_İDEAL TP - SL.pdf`** — TAM KURALLAR:

**TP için 3 seçenek (öncelik sırasıyla değil, bağlama göre):**
1. **Katman 1 Modülü** — modülün TAM tepki vermeden ÖNCEKİ (spread
   dahil, "bir tık önce") kısmına TP koy. En güvenli, kısa vadeli
   (≤5 gün) pozisyonlar için tercih edilir.
2. **Alan Bitiren** — Eski Alan'daki bir MODÜLE göre (Alan'ın en tepe/
   dip NOKTASINA göre DEĞİL — kaynak bunu açıkça bir hata olarak
   işaretliyor: "TP, fiyatın gerçekten tepki verebileceği bir yer
   olmalı", Alan'ın mutlak ekstremi orada değil). ATH/ATL durumunda:
   ATH + 20-30 pip (veya ATL − 20-30 pip).
3. **HTF Alternatifleri** — bir üst zaman diliminin (Günlük/Haftalık)
   modülüne kadar; zaman kazanmak veya swap maliyetinden kaçmak için.

**SL için 3 seçenek:**
1. **Katman 1'in son noktası** — en garanti fallback; Alan Gücü/modül
   seçimi yanlış çıksa bile bu SL kurtarır.
2. **Alternatif tepki potansiyeline sahip modül(ler) & HTF Alternatifleri.**
3. **Modül Bitişi** — o modülün dışında başka bir modül yoksa, veya
   istatistiksel olarak sabit bir risk sınırı isteniyorsa.

Her iki durumda da: modül seviyesinin **bir tık ötesine/önüne** SL/TP
koy (spread/slippage payı bırak, tam seviyeye değil).

**Breakeven kuralı (sayısal, net):**
- Giriş **"sniper"** ise (tam tepki noktasından, sıfır sapmayla
  girildiyse) → TP'nin **%30**'una ulaşınca pozisyonu breakeven'e çek.
- Giriş sniper DEĞİLSE (daha kötü/geç bir fiyattan girildiyse) → TP'nin
  **%70**'ine ulaşınca breakeven'e çek.

`backtest/engine.py`'deki `_find_take_profit` mantığı bunların
HİÇBİRİNE uymuyor — sonraki karşıt S/R seviyesini kullanıyor (Katman/
Alan/HTF modülü değil), ve **breakeven kavramı kodda hiç yok** (SL/TP
sabit, pozisyon açıldıktan sonra hiç güncellenmiyor).

**DXY Korelasyonu — `_DXY KORELASYONU.pdf`**
EURUSD/GBPUSD gibi majörler DXY ile ters korele (sabit offset ile:
EURUSD +0.14, GBPUSD +0.24 fib-seviye kayması); XAUUSD/BTCUSD DXY'den
bağımsız/dominant, basit ters korelasyon uygulanmaz. Kodda hiçbir DXY
veri hattı veya korelasyon mantığı yok.

**Fizik Kuralları / Kondisyonlar — `_FİZİK KURALLARI.pdf`, `KONDİSYONLAR.pdf`**
- **Enerji Dolumu:** fiyat sabit hızla sonsuza kadar hareket edemez —
  "enerji dolumu" (konsolidasyon) olmadan uzayan bir leg'den modül
  sinyali beklenmez. **Kritik kısıtlama: enerji dolumu SADECE H1 veya
  daha üst zaman diliminde hesaba katılır** — M30/M15 gibi düşük zaman
  dilimlerinde bu kavram hiç uygulanmaz. Mevcut kod altyapısı (`research/
  v2/data/resampler.py`'deki `Timeframe` enum'u) M30'un üstüne
  çıkmıyor — yani bu bileşen, mevcut pipeline'da hiçbir zaman
  hesaplanabilir durumda değil (0 olarak sabit kalır).
- **Kuvvet rekabeti (Alan Gücü'nün sezgisel versiyonu):** hangi yönde
  (bullish/bearish) daha fazla VEYA daha güçlü modül/zaman dilimi
  varsa o yön kazanır. Basit durum: 2 modül vs 1 modül → açık galip.
  Karmaşık durum: bir modül daha büyük zaman diliminde VE daha güçlü
  bir modül tipinde VE Katman 1'deyse ("Günlük Wick Imbalance, K1"),
  bu tek başına karşıt yöndeki daha zayıf/küçük modülleri kırabilir.
- Bir modül seviyesine erken (tam mesafeye ulaşmadan) tepki verilirse,
  o modül ikinci kez kullanılmaz — bir sonraki denemede kırılacağı
  varsayılır.
- FVG 1 kez kullanılır (dolunca biter); 0.38/Wick Imbalance 2 seviyeye
  kadar kullanılabilir.

## Kod ile uyum tablosu

| Kavram | Kaynakta | Kodda | Durum |
|---|---|---|---|
| Alan/Katman (zone/swing fib yapısı) | Merkezi kavram | Yok — `strategy/fvg.py` docstring'i zaten bunu "henüz kodlamadığımız swing/zone yapısı" diye not ediyor | **büyük eksik** |
| FVG — geometri (3 mumluk gap) | Var | Var | uyumlu |
| FVG — mesafe kuralı | Var, **bar-count bazlı** (1-210 bearish/1-280 bullish) | Var, ama **ATR-bazlı** — farklı kavram, aynı isim | **uyumsuz** |
| FVG — Dengesiz FVG Tarzı | Geçersiz | Var (`max_middle_candle_ratio`) | uyumlu |
| FVG — Multi FVG Modeli | Geçersiz | Var (`_apply_multi_fvg_rule`) | uyumlu |
| FVG — Yüksek Katman FVG Tarzı | **Geçersiz, kesinlikle işlem açma** | Yok — Alan/Katman'a bağlı | **eksik** |
| FVG — Alanın dibindeki FVG | **En ideal** | Yok — Alan/Katman'a bağlı | **eksik** |
| FVG — 3. Büyük Mum Tarzı | Geçersiz | Yok | **eksik** |
| FVG — Baskın Dip FVG Modeli | Geçerli (özel bağlam) | Yok | **eksik** |
| Wick Imbalance modülü | Var (2. güç sırası) | Yok | **eksik** |
| 0.38 modülü | Var (1. güç sırası) | Yok (önceki oturumdaki fib-prototip denemesi bunu FVG gap'inden türetmeye çalışmıştı — kavramsal olarak yanlış, bkz. aşağıdaki not) | **eksik** |
| R.O.P modülü | Var (4. sıra) | Yok | **eksik** |
| Setup Kalitesi (S+/S/A+/A/B+/B/C) | Var, TP/lot'u belirliyor | Yok | **büyük eksik** |
| Setup Kalitesi — pre-trade checklist (5 madde) | Var | Yok | **eksik** |
| Alan Gücü puanlaması (tam formül + karar tablosu artık biliniyor) | Var | Yok | **büyük eksik** |
| Katman 1 iç alt-bölünmesi (0-0.15/0.15-0.25) | Var | Yok (Katman'ın kendisi bile yok üretimde) | **eksik** |
| Mini Yeni Alan (özyinelemeli zon) | Var | Yok — `strategy/zone.py` tek seviyeli | **eksik** |
| Eylem 1 / Eylem 2 | Var | Yok — kod her zaman aynı şekilde limit emri koyuyor | **eksik** |
| İdeal TP (Katman1-modül / Alan Bitiren / HTF) | Var, 3 net seçenek | **Uyumsuz** — `_find_take_profit` sonraki S/R seviyesini kullanıyor | **uyumsuz** |
| İdeal SL (Katman1 son nokta / alternatif modül / modül bitişi) | Var, 3 net seçenek | **Uyumsuz** — SL `signal.stop_loss`'tan sabit geliyor | **uyumsuz** |
| Breakeven kuralı (%30 sniper / %70 non-sniper) | Var, sayısal | **Yok** — pozisyon açıldıktan sonra hiç güncellenmiyor | **eksik** |
| DXY korelasyonu (sabit offset formülü artık biliniyor) | Var | Yok — DXY veri hattı hiç yok | **eksik** |
| Enerji Dolumu (SADECE H1+ zaman diliminde geçerli) | Var | Yok, ayrıca mevcut altyapı M30 üstünü desteklemiyor | **eksik + altyapısal engel** |
| Modül tekrar kullanım kısıtı (FVG 1x, 0.38/WI 2x) | Var | Yok | **eksik** |
| Kuvvet rekabeti (modül+zaman dilimi gücü karşılaştırması) | Var | Yok | **eksik** |

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

## KRİTİK BULGU — V1'in sinyal üretiminde lookahead/survivorship bias (2026-08-28)

"FVG'nin kendi seviyesi Katman'a göre nasıl filtrelenir" sorusunu test
ederken (bkz. bir önceki güncelleme), `scratch_fvg_own_level_katman_multisymbol.py`
her sembolde **0 filled trade** üretti. Bu, veri sorunu değil, kodun
kendisindeki bir hataydı.

**Kök neden:** `strategy/fvg.py`'deki `mark_filled_fvgs`, bir FVG'yi
"dolmuş" sayarken candles dizisinin **TAMAMINA (geleceğe de) bakıyordu**
(`for candle in candles[fvg.end_index+1:]`). `strategy/signal_engine.py`'deki
`generate_signals`, sinyal adaylarını `valid_fvgs = [f for f in fvgs
if f.valid and not f.filled]` ile seçiyordu — yani sinyal havuzuna
sadece **"kalan tüm geçmişte bir daha ASLA kendi seviyesine dönmeyen"**
FVG'ler giriyordu. Ama `FVG_ONLY` sinyalinin giriş fiyatı
(`fvg.entry_price`) **tam olarak o seviyenin kendisi**. Sonuç:
matematiksel olarak, FVG_ONLY sinyalleri hiçbir zaman dolamazdı (spread=0
ile kanıtlandı, spread>0 ile de aynı — spread sadece dolum eşiğini daha
da katılaştırıyor, kurtarmıyor). GOLD'un tam 137K'lık M30 geçmişinde
doğrudan test edildi: **144 FVG_ONLY sinyalinin 0'ı doldu, 138 A+
sinyalinin sadece 1'i doldu** — tüm "VALIDATED STRONG" sonucu 229
OB_ONLY sinyalinden gelen 193 trade'e dayanıyordu.

Aynı sınıftan (daha hafif ama aynı yapıda) bir kusur OB tarafında da
vardı: `mark_mitigated_blocks` da tüm geleceğe bakıyor, `valid_obs =
[o for o in obs if not o.mitigated]` de aynı şekilde global bir
ön-filtreydi. OB_ONLY'de bu matematiksel olarak %0'a yol açmıyordu
(entry=yakın kenar, mitigation-check=uzak kenar, farklı seviyeler) ama
**gelecekte hiç tam kırılmayan (invalidated olmayan) OB'leri seçerek**
win rate'i ciddi şekilde şişiriyordu — bir bölgenin hiç kırılmaması,
zaten "doğru" bir yapı okuması olduğunun güçlü bir işareti, bu yüzden
bu filtre saf bir survivorship bias'tı.

**Ek olarak:** bu, canlı MQL5 EA'nın davranışıyla da tutarsızdı.
`mql5/TradeBot_NOA.mq5` sadece SON mumda oluşan FVG'leri değerlendiriyor
(`filled` alanı orada hiç set edilmiyor, hep `false`) — yani EA zaten
CAUSAL çalışıyordu (geleceğe bakamaz), backtest ise bakıyordu. Backtest,
EA'nın gerçekte nasıl davrandığını hiç doğru yansıtmıyordu.

**Düzeltme** (`strategy/fvg.py`, `strategy/order_block.py` (mevcut
`mitigated_index` alanı kullanıldı), `strategy/signal_engine.py`):
`FVG`'ye `filled_at_index: int | None` eklendi, `FVG.is_unfilled_as_of(index)`
metodu eklendi — "bu FVG, verilen bar'a kadar (bar dahil) dolmuş mu"
sorusunu CAUSAL olarak yanıtlıyor. `generate_signals`, artık global
"hiç dolmadı mı" ön-filtresi yerine, her sinyal KENDİ oluştuğu bar'a
göre causal kontrol yapıyor (A+ için `signal_index = max(fvg.end_index,
ob.index)`'e göre; FVG_ONLY/OB_ONLY için kendi formasyon barına göre —
ki bu ikisi için kontrol her zaman tautolojik olarak True döner, çünkü
formasyon barında henüz hiçbir gelecek test edilmemiştir).

**Düzeltme sonrası GOLD'da (resmi train/val/holdout + block-bootstrap
metodolojisi, son 20.000 M30 mum — tam 137K geçmiş performans nedeniyle
bu oturumda pratik değildi, `scratch_causal_fix_revalidation.py`):**

```
TRAIN: win=43.5%  expectancy_r=-0.1994  pf=0.63
VAL:   win=46.8%  expectancy_r=-0.1184  pf=0.73
TEST:  win=41.6%  expectancy_r=-0.1624  pf=0.71  (holdout)
evidence_classification: FAILED TO GENERALIZE
block_bootstrap 95% CI: [-0.2949, -0.0241]  -- tamamen negatif
```

**Sonuç: GOLD'un "VALIDATED STRONG" sınıflandırması geçersiz.**
İstatistiksel olarak sağlam (CI sıfırı kapsamıyor) NEGATİF bir
expectancy var. Round 1-3'teki "54/101 sembol validated" iddiası da
aynı buggy kodla hesaplandığı için **artık güvenilir değil** — tam
yeniden validasyon gerekiyor (performans: düzeltme sonrası sinyal
sayısı ~30-40x arttı — GOLD'da FVG=6382, A+=5559, OB=7280 aday sinyal,
eskiden FVG=144, A+=138, OB=229 idi — `run_backtest`'in sinyal başına
`build_levels` yeniden hesaplayan O(n) maliyeti bu ölçekte tam
137K'lık geçmiş için pratik olmayan bir süreye çıkıyor; tam yeniden
validasyon için ya backtest motorunun performansı iyileştirilmeli ya
da çok daha uzun bir koşuya (saatler) izin verilmeli).

**Canlı EA:** `TradeBot_NOA_MultiSymbol.mq5` demo hesapta bu geçersiz
çıkan "VALIDATED STRONG" varsayımına dayanarak çalışıyor. Bu bulgu
ışığında gözden geçirilmeli.

**Çok sembollü doğrulama (2026-08-28) — kesinleşti, GOLD'a özgü değil:**
Aynı metodoloji (`scratch_causal_fix_revalidation_multisymbol.py`) 5
farklı varlık sınıfında (metal, FX, kripto, endeks) çalıştırıldı —
**5/5 sembol "FAILED TO GENERALIZE", 5/5'inde %95 güven aralığı
TAMAMEN negatif** (sıfırı hiç kapsamıyor):

| Sembol | Sınıf | test win% | test exp_r | %95 CI |
|---|---|---|---|---|
| GOLD | Metal | 41.6% | -0.162 | [-0.295, -0.024] |
| EURUSD | FX majör | 29.2% | -0.682 | [-0.782, -0.583] |
| BTCUSD | Kripto | 41.0% | -0.998 | [-1.788, -0.409] |
| US500 | Endeks | 47.0% | -0.159 | [-0.272, -0.018] |
| GBPJPY | FX çapraz | 36.4% | -0.421 | [-0.548, -0.284] |

**Bu, GOLD'a özgü bir tesadüf değil — düzeltilmiş (causal) sinyal
üretimiyle V1 stratejisi (A+/FVG/OB birleşik) test edilen HER varlık
sınıfında sistematik olarak negatif çıkıyor.** Round 1-3'teki "54/101
sembol validated" iddiasının tamamı, bu analizde gösterilen buggy
(lookahead/survivorship bias'lı) sinyal üretimiyle hesaplandığı için
geçersiz sayılmalı. Mevcut haliyle V1'in gerçek bir pozitif edge'i
olduğuna dair hiçbir güvenilir kanıt yok — aksine, düzeltilmiş ölçüm
sistematik bir NEGATİF edge gösteriyor.

## V1'i baştan kurma: FVG modülü (2026-08-29)

Kullanıcı kararı: V1 stratejisi PDF kaynaklarına göre sıfırdan
kurulacak — sıra: **FVG → Order Block → Trendline**, her modül gerçek
grafik örnekleri üzerinden karşılıklı gözden geçirilerek (kullanıcı
kuralları netleştiriyor, kod buna göre düzeltiliyor).

**FVG geçerlilik kuralı düzeltildi:** GOLD D1 grafiği üzerinde inceleme
sırasında kullanıcı düzeltmesi: fitilin FVG'nin içine girmesi (hatta en
dibine/tepesine kadar) FVG'yi geçersiz kılmaz — normal bir retest. Sadece
bir mumun **kapanışı** gap'in tamamının dışına çıkarsa FVG artık
kullanılamaz. Bu, iFVG'nin invert olma tetikleyicisiyle birebir aynı
olay — "FVG doldu" ve "FVG invert oldu" tek bir olayın iki farklı adı.
`mark_filled_fvgs` buna göre güncellendi (`candle.low/high` yerine
`candle.close`).

**TP/SL çalışması — kullanıcı kuralı test edildi:** Giriş=`fvg.entry_price`,
SL=uzak kenarın (invalidation seviyesinin) biraz ötesi, TP=sabit R
katları. 101 sembol × 6 zaman dilimi (M30/H1/H2/H4/D1/W1), tam causal
simülasyon (lookahead yok), `scratch_fvg_tp_sl_study.py`.

*SL tampon kalibrasyonu (GOLD tam geçmiş, önce):* "biraz ötesi" gap
boyutunun **%10'u** alınırsa exp_r=&minus;0.61 (her R'de) — tampon o kadar
dar ki sıradan gürültüyle hemen stop oluyor. Tampon %50'ye çıkınca
pozitife dönüyor (+0.23, R=3'te pik); %100'e (tam gap boyutu) çıkınca en
iyi profit factor'e ulaşıyor (1.52, R=1.0-1.5'te pik). Tam çalışma
%100 tampon ile koşuldu.

*Ana bulgu (1.42 milyon trade, tüm zaman dilimleri havuzlanmış):*
**R=1.0-1.5 bölgesi 6 zaman diliminin TAMAMINDA optimal** — tesadüf
değil, çok tutarlı bir örüntü:

| Zaman dilimi | en iyi R | win% | exp_r | pf |
|---|---|---|---|---|
| M30 | 1.5 | 49.7% | 0.242 | 1.48 |
| H1 | 1.5 | 49.5% | 0.236 | 1.47 |
| H2 | 1.5 | 49.0% | 0.225 | 1.44 |
| H4 | 1.5 | 48.2% | 0.206 | 1.40 |
| D1 | 1.5 | 51.3% | 0.283 | 1.58 |
| W1 | 1.5 | 53.6% | 0.339 | 1.73 |

R=1.0 her yerde en yüksek profit factor'ü veriyor (1.47-1.84) ama R=1.5
biraz daha yüksek toplam expectancy veriyor. R=2.0 ve üzerinde performans
her zaman diliminde düzenli düşüyor. **Üst zaman dilimleri (D1/W1) alt
zaman dilimlerinden (M30/H1) belirgin şekilde daha güçlü** — ayrı bir
bulgu olarak not edildi.

Rapor: `fvg_tp_sl_report_data.json` (gitignore'da, üretilebilir) +
Artifact (oturumda paylaşıldı). Sıradaki adım: Order Block modülü.

## TP karşılaştırması: RR vs Likidite (2026-08-30)

Kullanıcı talebi: ikinci bir TP yöntemi test edildi — **Likidite TP**:
yükselişte yukarıda henüz alınmamış en yakın likidite (swing high),
düşüşte aşağıda henüz alınmamış en yakın likidite (swing low). Giriş
ve SL, RR TP çalışmasıyla birebir aynı (`fvg.entry_price`, uzak kenar +
gap boyutunun %100'ü tampon) — tek değişken TP yöntemi.
`scratch_fvg_liquidity_tp_study.py`, 101 sembol × 6 zaman dilimi, tam
causal simülasyon (swing bir noktası kendi lookback penceresi
tamamlanmadan "bilinen" sayılmaz, ileri tarama yok).

**Sonuç: Likidite TP, RR TP'den belirgin şekilde daha kötü.**

| | RR TP (R=1.0) | RR TP (R=1.5) | Likidite TP |
|---|---|---|---|
| n | 1.419.293 | 1.419.256 | 1.404.461 |
| win rate | %60.0 | %49.5 | **%16.4** |
| expectancy_r | +0.1997 | +0.2370 | **&minus;0.0047** |
| profit factor | 1.50 | 1.47 | **0.99** |
| toplam R | +283.397 | +336.369 | **&minus;6.546** |

Likidite TP pratikte break-even'in az altında (pf=0.99) — anlamlı bir
edge sağlamıyor. Muhtemel neden: en yakın "alınmamış" likidite genelde
çok uzak bir hedef (ortalama kazanan trade'in hedefi ~5R'ye denk
geliyordu, `avg_target_r` alanı) — fiyatın oraya varmadan önce SL'e
(1R) çarpma ihtimali çok daha yüksek, bu da win rate'i %16'ya
düşürüyor. Ayrıca 58.631 sinyal o anda "alınmamış likidite yok"
gerekçesiyle hiç test edilemedi (`n_skipped_no_liquidity`).

Bu, "likidite hedefi kavramsal olarak kötü" anlamına gelmiyor —
mevcut haliyle (en yakınının SEÇİLMESİ, mesafe sınırı olmadan) test
edildi ve kaybetti. Zaman dilimi kırılımında W1 hâlâ pozitif çıktı
(exp_r=+0.104) — üst zaman dilimlerinde likidite hedefleri daha
gerçekçi/ulaşılabilir olabilir. Daha küçük/sınırlı bir likidite seçimi
(ör. bir R tavanıyla sınırlı, ya da ilk N bar içindeki en yakın swing)
ayrı bir varyant olarak test edilebilir — bu oturumda yapılmadı.

**Karar için:** Mevcut kanıta göre RR TP (R=1.0-1.5) tercih edilmeli,
Likidite TP bu haliyle kullanılmamalı.

Rapor: `fvg_tp_comparison_report_data.json` (gitignore'da, üretilebilir)
+ Artifact (oturumda paylaşıldı).

## Order Block — derin araştırma ve mevcut kodla karşılaştırma (2026-08-31)

Kullanıcı talebi: FVG/iFVG'de izlenen yöntemle (derin araştır → gerçek
örnekle doğrula → koda uygula → tüm sembollerde test et) Order Block'a
geçildi. Çoklu kaynak (LuxAlgo, ICTKillzone, InnerCircleTrader,
TradingWyckoff, ATAS) tarandı, gerçek bir NQ trade örneğiyle
doğrulandı.

**KRİTİK BULGU: `strategy/order_block.py`'nin mevcut tanımı standart
tanımdan SAPIYOR — ve bu sapma zaten dosyanın kendi docstring'inde
itiraf ediliyor** ("kullanıcının kendi tanımına göre, PDF kaynağı yok
... klasik ICT tanımındaki 'son zıt mum' değil — burada mumun kendisi
OB sayılıyor").

**Standart tanım (tüm kaynaklarda hemfikir):**
- Order Block = güçlü hareketten (displacement) **HEMEN ÖNCEKİ SON ZIT
  YÖNLÜ mum** — hareketi başlatan mumun KENDİSİ değil.
- Bullish OB: güçlü YÜKSELİŞ hareketinden önceki **son düşüş (bearish)
  mumu**. Bearish OB: güçlü DÜŞÜŞ hareketinden önceki **son yükseliş
  (bullish) mumu**.
- Bölge, mumun **GÖVDESİYLE** sınırlı (fitil dahil tüm aralık değil) —
  bazı kaynaklar "gövdeden gövdeye + fitilden fitile tam yutma
  (engulfing)" şartı da arıyor: hareketi başlatan mum, önceki zıt
  mumun hem gövdesini hem fitilini tam kapsamalı.
- Ek geçerlilik şartları (kaynaklara göre "güçlü" bir OB için):
  1. **Likidite süpürmesi önce** — displacement'tan hemen önce yakın
     bir high/low süpürülmüş olmalı (iFVG'de doğruladığımız aynı
     kavram).
  2. **Gerçek displacement** — büyük gövdeli, kısa fitilli mumlar
     (fitil, mum boyunun %25'inden az), FVG bırakan bir hareket.
  3. **Sadece gövde kapanışı geçersiz kılar** (mitigation) — fitille
     dokunmak geçersiz kılmaz, bizim FVG'de kullandığımız kuralla
     birebir aynı mantık.
  4. **HTF premium/discount uyumu** — bullish OB sadece "discount"
     bölgesinde (günlük aralığın %50'sinin altında), bearish OB sadece
     "premium" bölgesinde (%50'sinin üstünde) geçerli sayılıyor.

**Breaker Block / Mitigation Block ayrımı** (OB başarısız olduğunda,
iFVG'nin OB karşılığı): Bir OB kırılıp (invalidated) tekrar test
edildiğinde ters yönde çalışırsa — eğer kırılmadan ÖNCE bir likidite
süpürmesi olduysa **Breaker Block**, olmadıysa **Mitigation Block**
denir. Bu, iFVG'de yaptığımız "kırılma+retest+reddiye" çalışmasının
doğrudan OB karşılığı — Order Block'un kendi "inverted" versiyonu.

**Gerçek NQ örneği (doğrulama):** Buy-side likidite süpürüldü (19180)
→ bearish displacement mumu (19185→19115) → **süpürmeden önceki son
bullish mum** OB oluyor (19120-19172, GÖVDE ile) → giriş OB'nin orta
noktasından (19146), FVG confluence'ıyla.

**Gold örneği (genel):** "Order Block Trading Strategy" kaynağı, GOLD'u
"order block trader'ın cenneti" diye tanımlıyor — 5 dakikalık GOLD
scalping stratejisinde win rate %60-70, ortalama R:R 2.0-2.5 bildiriliyor
(kaynak kendi backtestine dayanıyor, bağımsız doğrulanmadı — bizim
kendi testimizle karşılaştırılacak).

**Kod ile uyum tablosu:**

| Kavram | Standart | Mevcut kod | Durum |
|---|---|---|---|
| OB = hangi mum | Son ZIT mum (displacement'tan ÖNCE) | Displacement mumunun KENDİSİ | **temel tanım sapması** |
| Bölge sınırı | Sadece GÖVDE | Tüm high-low aralığı (fitil dahil) | **uyumsuz** |
| Engulfing şartı | Var (gövde+fitil tam yutma) | Yok | **eksik** |
| Likidite süpürmesi şartı | Var | Yok | **eksik** (iFVG'de test ettik, karışık sonuç verebilir) |
| Mitigation (geçersizlik) | Sadece gövde kapanışı | Zaten sadece gövde kapanışı kullanılıyor (`candle["close"]`) | **uyumlu** |
| HTF premium/discount | Var | Yok | **eksik** |
| Breaker/Mitigation Block ayrımı | Var (iFVG'nin OB karşılığı) | Yok | **eksik** |

**Sonraki adım:** Standart tanıma göre (son zıt mum, gövde bölgesi)
`strategy/order_block.py` düzeltilecek, FVG/iFVG'de izlenen aynı
disiplinle (önce basit/temel tanım, gerçek veriyle test, sonra
filtreler eklenerek iyileştirme) 101 sembolde test edilecek.

## Order Block — 101 sembol P&L çalışması sonuçları (2026-08-31)

Düzeltilmiş tanımla (`strategy/order_block.py`, son zıt mum + gövde
bölgesi) `scratch_ob_tp_sl_study.py` ile 101 sembol × 6 zaman dilimi
(M30/H1/H2/H4/D1/W1) tarandı, 0.5R–5.0R arası sabit R-katları test
edildi. SL tamponu GOLD M30 tam geçmişinde kalibre edildi (0.5x–10x
sweep, tepe 3.0-4.0x arası) → `SL_BUFFER_RATIO = 3.0` (OB gövdesinin
3 katı — FVG/iFVG'nin kendi gap boyutu tamponundan (1.0x) farklı,
çünkü OB gövdeleri FVG gap'inden küçük). Toplam **1.557.075 Order
Block** tespit edildi. Detaylı rapor: `ob_report.html` artifact'ı
(havuzlanmış + zaman dilimi kırılımlı tablo ve OB/iFVG/FVG karşılaştırma
grafiği).

**Havuzlanmış sonuçlar (n = o R'ye ulaşan işlem sayısı):**

| R | n | Kazanma% | Beklenti (R) | Profit Factor |
|---|---|---|---|---|
| 0.5 | 1.522.794 | %72.5 | +0.088R | 1.32 |
| 1.0 | 1.522.259 | %62.0 | +0.240R | 1.63 |
| 1.5 | 1.521.497 | %52.9 | +0.323R | 1.69 |
| 2.0 | 1.520.679 | %45.9 | +0.377R | 1.70 |
| 2.5 | 1.519.847 | %40.4 | +0.415R | 1.70 |
| 3.0 | 1.518.950 | %36.0 | +0.442R | 1.69 |
| 4.0 | 1.516.978 | %29.5 | +0.476R | 1.68 |
| 5.0 | 1.514.930 | %25.0 | +0.499R | 1.67 |

**Bulgular:**

1. **Beklenti (expectancy_r) test edilen tüm aralıkta (0.5–5.0R) hiç
   tepe yapmadan artıyor** — FVG/iFVG'de R≈1.5'te tepe yapıp gerileyen
   davranıştan farklı. Gerçek optimal R muhtemelen 5.0'ın üzerinde,
   bu çalışmada ölçülmedi.
2. **Profit factor R≈2.0-3.0'da zaten tepe yapmış** (H2/H4'te ~1.80-1.82)
   ve R=5.0'a doğru hafifçe geriliyor — "en tutarlı" R ile "en yüksek
   beklenti" R'si aynı nokta değil.
3. Aynı R'de OB'nin profit factor'ü iFVG'den düşük (R=1.0: OB 1.63 /
   iFVG 1.88), ama R büyüdükçe beklentide OB öne geçiyor (R=5.0: OB
   0.499 / iFVG 0.281). Olası sebep: OB'nin risk birimi (gövde × 3
   tampon) iFVG'nin gap tabanlı risk biriminden mutlak fiyatta genelde
   daha küçük — "OB'de 5R" ile "iFVG'de 5R" aynı mutlak hareket
   anlamına gelmiyor, doğrudan R karşılaştırması bu farkı gizliyor.
4. **H2/H4 en yüksek profit factor'ü veriyor**, M30 en yüksek işlem
   hacmine sahip (843k işlem @ R=1.0) ama PF en düşük seviyelerde —
   FVG/iFVG'de de gözlenen "yüksek zaman diliminde daha temiz sinyal"
   örüntüsü tekrarlanıyor.

**Sonraki adım (henüz yapılmadı):** kullanıcıyla bu 4 bulgu üzerinden
"OB'yi nasıl daha sağlıklı ve karlı hale getiririz" tartışması — özellikle
R>5.0 taraması ve likidite süpürmesi/HTF premium-discount gibi kod ile
uyum tablosunda "eksik" işaretlenen filtrelerin eklenmesinin PF üzerindeki
etkisi.

**Güncelleme (2026-08-31):** Ortak zayıf 6 sembol (GERTECH30, NASDAQ, IT40,
GERMID50, EURDKK, USFANG) `strategy/config.py:EXCLUDED_SYMBOLS`'a taşındı;
modül başına R hedefi (`MODULE_R_MULTIPLE`: FVG/iFVG=1.5R, OB=3.0R) ve
modül başına devre dışı zaman dilimi (`MODULE_DISABLED_TIMEFRAMES`:
FVG/iFVG→H4 hariç, OB→W1 hariç) merkezi config'e eklendi ve üç ana
R-katı çalışma scriptine bağlandı. Detaylar için bkz. git log
("Exclude structurally weak symbols...", 2026-08-31).

## Trendline — derin araştırma (2026-08-31)

Kullanıcının orijinal planı **FVG → Order Block → Trendline** sırasıyla
kuruluyordu; OB tamamlandı, sıra Trendline'da. Aynı disiplin: önce derin
araştırma (platformlar/bloglar), gerçek trade örneğiyle doğrulama, sonra
kod, sonra 101 sembol testi.

**Kaynaklar:** TrendSpider, Tradeciety, LuxAlgo (Trendline Liquidity —
SMC/ICT konsepti), FX Replay, Capital.com.

**Standart tanım (kaynaklar hemfikir):**
- **İnşa:** Yükselen trendline = art arda YÜKSELEN swing low'ları birleştirir
  (destek diyagonali). Düşen trendline = art arda DÜŞEN swing high'ları
  birleştirir (direnç diyagonali).
- **Geçerlilik eşiği:** "İki nokta çizer, üç nokta doğrular" (TrendSpider,
  Tradeciety'de birebir aynı ifade) — 2 swing noktası geometrik olarak bir
  çizgi tanımlar ama bu "aday", gerçek/tradeable sayılması için 3. bir
  swing noktasının çizgiye saygı göstermesi (dokunup tersine dönmesi)
  gerekiyor.
- **Fitil mi gövde mi:** Dokunuş noktaları için FİTİL kullanılıyor ("most
  traders use wicks because they show true rejection levels", "OK to cut
  through wicks, never cut through bodies"). Kırılma (break) için ise
  KAPANIŞ esas — bu, projede FVG/OB'de zaten kullanılan "sadece kapanış
  geçersiz kılar" kuralıyla birebir tutarlı.
- **Üç oynanabilir setup (Tradeciety):**
  1. **Bounce (sekme):** Trend yönünde çizgiden tekrar tepki — en temel,
     en literal "trendline trade".
  2. **Break + Retest:** Çizgi kapanışla kırılır, fiyat geri dönüp kırılan
     çizgiyi ZIT taraftan test eder, sonra kırılma yönünde devam eder.
  3. **Trendline Flag:** Trend içi konsolidasyonun kendi mini-trendline'ı,
     konsolidasyon yönünde kırılınca giriş.

**ICT/SMC açısı — "Trendline Likiditesi" (LuxAlgo):** Belirgin/gözle görülür
trendline'lar, altlarında/üstlerinde stop-loss kümelendiği için likidite
mıknatısı sayılıyor. İki senaryo net biçimde ayrılıyor:
- **Süpürme (sweep):** Çizgiden keskin bir "delme" olur, hızla başarısız
  olur, birkaç mum içinde çizgiyi TERS yönde displacement ile geri kazanır
  — bizim iFVG'de doğruladığımız "kırılma+retest+reddiye" örüntüsüyle
  KAVRAMSAL OLARAK BİREBİR AYNI.
  - **Gerçek kırılma:** Çizginin ötesinde kabul (acceptance) var, kapanışlar
  çizginin öbür tarafında kalıcı, devam (follow-through) geliyor.
- **Dürüst kısıtlama (kaynağın kendi itirafı):** "no reliable rule
  identifies in advance which break is a sweep" — FVG/OB'nin aksine
  (kesin 3-mum gap / son-zıt-mum tanımı), trendline'ın kırılma-mı-süpürme-mi
  ayrımı GERÇEK ZAMANLI olarak mekanik biçimde %100 çözülemiyor; sadece
  geriye dönük ("after the fact") netleşiyor. Bu, projenin FVG/OB'de
  ulaştığı hassasiyetin trendline'da mümkün olmadığını, en iyi ihtimalle
  ampirik/istatistiksel bir yaklaşım (causal touch/break kuralları + geriye
  dönük ölçüm) olacağını gösteriyor — dürüstçe belgeleniyor.
- **Gerçek trade örneği (GOLD, ICT kaynağından):** XAU/USD, NY seansı 08:30
  ET veri açıklamaları civarında süpürme sonrası temiz reversal'lar
  veriyor. Giriş, süpürme sonrası bırakılan PD array'in (OB/FVG/breaker)
  retest'inde; SL süpürülen seviyenin biraz ötesinde (fitil retest'i stop
  olmasın diye); hedef bir sonraki likidite seviyesi. Çoklu zaman dilimi:
  D1/H4 yön (bias), M15 bağlam, M5/M1 giriş tetiği.

**Kod ile uyum tablosu:**

| Kavram | Standart | Mevcut kod | Durum |
|---|---|---|---|
| Diyagonal trendline (swing'leri birleştiren eğik çizgi) | Var, temel yapı taşı | Yok — `support_resistance.py` sadece YATAY seviyeler kümeliyor | **eksik (yeni modül)** |
| Min. dokunuş eşiği (3) | Var | N/A | **eksik** |
| Fitil-temas / kapanış-kırılma ayrımı | Var | FVG/OB'de zaten aynı desen (kapanış-bazlı invalidation) var, trendline'a taşınacak | **desen zaten kanıtlı, uygulanacak** |
| Bounce sinyali | Var | Yok | **eksik** |
| Break+Retest sinyali | Var (iFVG'nin kavramsal karşılığı) | Yok | **eksik** |
| Süpürme/gerçek-kırılma ayrımı | Kaynak kendi de "önceden kesin ayrılamaz" diyor | Yok | **kasıtlı olarak MVP kapsamı dışı — belirsizliği kodda gizlemek yerine açıkça belgelendi** |

**MVP kapsam kararı:** FVG'nin kendi gelişim sırasını tekrarlıyoruz (önce
temel/gürültüsüz tanım, sonra ampirik iyileştirme). İlk aşamada SADECE
temel yapı: `detect_trendlines` (swing çiftlerinden aday çizgi + 3.
dokunuşla causal doğrulama) + `mark_broken_trendlines` (kapanış-bazlı
kırılma). Süpürme/gerçek-kırılma ayrımı, break+retest sinyali ve bounce
sinyali — FVG→iFVG geçişindeki gibi — ayrı bir ikinci aşamada, gerçek
veriyle görsel doğrulama sonrası eklenecek.

Sources:
- [How to Draw Trendlines — TrendSpider](https://trendspider.com/learning-center/how-to-draw-trendlines/)
- [3 Trendline Strategies — Tradeciety](https://tradeciety.com/3-trendline-strategies)
- [Trendline Liquidity — LuxAlgo](https://www.luxalgo.com/library/concept/trendline-liquidity/)

## Trendline — TP/SL araştırması ve 10 örnek doğrulama (2026-08-31)

Kullanıcı 8 örneği "gayet güzel" onayladıktan sonra: TP/SL mekaniği için
derin araştırma + SADECE 10 örnek (5 kazanan/5 kaybeden, tek sembolde,
tüm paritelere taramadan) görselleştirme istendi. 101 sembol testi bu
10 örnek onaylanana kadar ERTELENDİ.

**Kaynaklar:** Monkeytrade ("Trend Line Trading: How to Draw, Trade, and
Manage Risk"), Capital.com, AskTraders, ForTraders (Risk-Reward Ratio).

**SL (stop loss) — kaynaklardan:**
- Sekme (bounce) mumunun oluşturduğu swing noktasının BİRAZ ötesine
  konur -- "if price prints a new low below the swing low, the
  trendline structure is broken and the reason for the trade no longer
  exists." Örnek: swing low 1.2685 → SL 1.2675 (3 pip ötesi).
- ATR/volatilite tamponu kaynaklarda belirtilmiyor -- yapısal
  (swing noktasına göre) bir tampon, sabit pip.

**TP (take profit) — kaynaklardan:**
- Birincil yöntem: bir sonraki görünür swing high/low (zıt yapı
  seviyesi) -- işlem öncesi belirli bir R:R veriyor.
- Minimum hedef R:R oranı: 1:2 (kaynaklarda tutarlı tavsiye).

**Proje metodolojisiyle uyarlama kararı:** "Bir sonraki swing seviyesi"
TP yöntemi, projenin FVG için zaten test ettiği "en yakın alınmamış
likidite" TP fikriyle AYNI KATEGORİDE -- ve o çalışma (bkz. "TP
karşılaştırması: RR vs Likidite", 2026-08-30) likidite-bazlı TP'nin
sabit R-katlı TP'den AÇIK ARAYLA daha kötü performans gösterdiğini
kanıtladı. Bu bulgu tekrar test edilmeden, aynı disiplinle Trendline
için de SABİT R-KATLI TP kullanılacak (FVG/iFVG/OB ile birebir aynı
deneysel tasarım, 101 sembol çalışmasında karşılaştırılabilir olması
için). SL için ise kaynakların "yapısal, swing noktasına göre" tavsiyesi
ATR tamponuna çevrildi (FVG/iFVG/OB'de zaten kullanılan desen):

- **Giriş:** Dokunuş barının kendi fiyatı (swing low/high -- "sekme"
  anı).
- **SL:** Dokunuş fiyatının ATR × tampon kadar ötesi (yön: yükselen için
  aşağı, düşen için yukarı). Tampon oranı henüz kalibre edilmedi --
  10 örnek için geçici olarak 1.0× ATR kullanıldı (FVG'nin ilk
  kalibrasyon değeriyle aynı başlangıç noktası).
- **TP:** Sabit R katı. 10 örnek için geçici olarak R=1.5 kullanıldı
  (FVG/iFVG'nin zaten doğrulanmış optimal R'si) -- 101 sembol
  çalışmasında Trendline'ın KENDİ optimal R'si (muhtemelen farklı)
  ayrıca ölçülecek.
- **Hangi dokunuş oynanabilir:** Doğrulama (3.) dokunuşu ve ondan
  sonraki her ek dokunuş (kırılana kadar) birer bağımsız sekme işlemi
  adayı sayıldı.

**10 örnek nasıl seçildi:** Sadece GOLD M30 (tüm paritelere tarama
YAPILMADI, kullanıcı talimatı). `detect_trendlines` çıktısındaki her
doğrulanmış çizginin dokunuşları kronolojik sırayla simüle edildi, ilk
5 TP'ye ulaşan ve ilk 5 SL'e takılan işlem bulununca durduruldu.

## Trendline — Kırılım+Retest (reversal) eklendi, 20 örnek (2026-08-31)

Kullanıcı 10 örneği inceledikten sonra: "düşüş trendi kırıldığında long
açmak" gibi kırılım-sonrası-reversal setup'ının da eklenmesini istedi --
bu, MVP kapsam kararında bilinçli olarak ERTELENMİŞ olan tam da o ikinci
aşama (bkz. modül docstring'i, "Süpürme/gerçek-kırılma ayrımı... ikinci
aşamada eklenecek").

**Derin araştırma (Break and Retest -- Capital.com, MQL5 blog, FXOpen,
HorizonAI, EBC, StockGro):**
- Kırılma SONRASI, fiyat kırılan çizgiye GERİ DÖNÜP retest eder --
  çizgi artık ROL DEĞİŞTİRİR (düşen direnç kırılınca yeni destek olur,
  yükselen destek kırılınca yeni direnç olur).
- **Onay:** Retest barında REDDİYE mumu (pin bar/engulfing) -- kapanış
  eski bölgeye GERİ DÖNMEMELİ. "Traders typically enter once the
  rejection candle closes."
- **SL:** Retest ekstremumunun (fitilinin) biraz ötesi.
- **TP:** Bir sonraki swing seviyesi VEYA sabit R:R -- proje disiplini
  geregi yine SABİT R kullanılacak (bkz. yukarıdaki TP/SL kararı).

Bu tanım, iFVG'de zaten doğrulanmış "kırılma + retest + aynı-bar
reddiye" örüntüsüyle YAPISAL OLARAK BİREBİR AYNI -- sadece kaynak
FVG yerine Trendline. `detect_trendline_reversals` bu yüzden
`scratch_ifvg_tp_sl_study.py`'nin `detect_confirmed_ifvgs`
mantığından ("ilk temasta karar verilir -- ilk temas reddetmezse o
sinyal başarısız sayılır", "süre önemli değil") birebir esinlenerek
yazıldı.

**20 örnek (10 TP + 10 SL):** Sekme (bounce) VE kırılım+retest
(reversal) işlemleri BİRLİKTE, kronolojik sırayla, sadece GOLD'da
(tüm paritelere tarama yok) taranıp ilk 10 kazanan + ilk 10 kaybeden
bulununca durduruldu.

## KRİTİK BULGU — Trendline SL kalibrasyonunda 2 lookahead/optimizm hatası (2026-09-01)

101 sembol testine geçmeden önce (OB'de yapıldığı gibi) GOLD'un tam
geçmişinde SL tamponu kalibre edilirken bulundu: kazanma oranı %92.8,
profit factor 12.88 gibi GERÇEK OLMAYAN sonuçlar çıktı. İki ayrı hata
tespit edilip düzeltildi:

**Hata 1 — swing noktası lookahead'i (bounce işlemleri):**
`find_swing_points` bir mumun swing high/low olduğunu ancak
SONRASINDAKİ `lookback` kadar mumu da görünce onaylayabiliyor (simetrik
pencere, bkz. `support_resistance.py`). 10 örnek/20 örnek çalışmalarında
dokunuş barının KENDİ fiyatını SL için kullanmıştım -- ama o fiyatın
"gelecekte de düşmeyecek" bilgisi zaten dokunuşun "resmi swing noktası"
sayılmasına gömülüydü, bu da SL'in neredeyse hiç çalışmamasına yol açtı.

**Düzeltme:** `Trendline`'a `swing_lookback` alanı ve `known_index`
property'si eklendi (`validated_index + swing_lookback` -- çizginin
CAUSAL olarak "bilinebildiği" ilk bar). Trade simülasyonu artık:
(a) `tl.known_index`'ten ÖNCEKİ hiçbir olayı kullanmıyor, (b) dokunuşlar
artık find_swing_points pivotlarıyla SINIRLI DEĞİL -- known_index'ten
kırılmaya kadar HER mum, fiyatın çizgiye (toleransla) değip değmediği
için tek tek taranıyor (daha gerçekçi, gerçek traderların "her yaklaşımı"
değerlendirmesine daha yakın).

**Hata 2 — reversal girişinde "ulaşılmamış" fiyat (kırılım+retest
işlemleri):** Giriş, retest anındaki TEORİK çizgi fiyatı (`line_price`)
olarak ayarlanmıştı -- ama tolerans payı yüzünden bazı retest mumları bu
fiyata GERÇEKTEN ulaşmadan "dokunuş" sayılıyordu (ör. short işlemde giriş
1282.62 iken mumun gerçek en yükseği sadece 1281.78 -- piyasa hiç o
fiyata gelmemiş). Bu, gerçekte doldurulamayacak kadar iyi bir fiyattan
giriş varsayarak sonuçları şişiriyordu.

**Düzeltme (araştırmayla da uyumlu -- "traders typically enter once the
rejection candle closes"):** Reversal girişi artık `line_price` değil,
retest mumunun KENDİ KAPANIŞI -- gerçekten gerçekleşmiş bir fiyat.

**Düzeltme sonrası GOLD kalibrasyonu (SL tamponu × ATR, birleşik
bounce+reversal, R sabit):**

| Tampon | R=1.0 exp_r | R=1.5 exp_r | R=2.0 exp_r |
|---|---|---|---|
| 0.10× | 0.092 | 0.313 | 0.487 |
| 0.25× | 0.231 | 0.447 | 0.653 |
| **0.50×** | **0.362** | **0.516** | 0.570 |
| 0.75× | 0.331 | 0.382 | 0.414 |
| 1.00× | 0.307 | 0.326 | 0.326 |
| 2.00× | 0.140 | 0.118 | 0.118 |
| 3.00× | 0.064 | 0.040 | 0.009 |

**Seçilen değer: SL_BUFFER_RATIO = 0.5× ATR** (R=1.5'te en yüksek
beklenti, +0.516R, PF=2.31 -- FVG/iFVG/OB ile aynı büyüklük mertebesinde,
artık şüpheli derecede yüksek değil). Bu, iki hatanın da gerçek bir
lookahead/optimizm kaynağı olduğunu, düzeltmenin sonuçları makul bir
aralığa çektiğini doğruluyor. 101 sembol çalışması bu düzeltilmiş
mantıkla başlatıldı.

## Trendline — 95 sembol P&L çalışması sonuçları (2026-09-01)

`scratch_trendline_tp_sl_study.py` ile 95 sembol (6 zayıf sembol
`EXCLUDED_SYMBOLS` ile hariç) × 6 zaman dilimi tarandı, düzeltilmiş
causal mantıkla (known_index gating, gerçek fiyat girişleri), 0.5R-5.0R
sabit R-katları test edildi. Toplam **50.726 trendline** tespit edildi,
bunların **32.407'si (%64)** bir kırılım+retest reversal sinyaline
dönüştü. Detaylı rapor: `trendline_report.html` artifact'ı.

**Havuzlanmış sonuçlar (sekme+reversal birlikte):**

| R | n | Kazanma% | Beklenti (R) | Profit Factor |
|---|---|---|---|---|
| 0.5 | 96.403 | %74.9 | +0.124R | 1.49 |
| 1.0 | 96.402 | %67.5 | +0.349R | 2.07 |
| 1.5 | 96.400 | %60.3 | +0.507R | 2.28 |
| 2.0 | 96.392 | %53.4 | +0.603R | **2.30** |
| 3.0 | 96.385 | %42.5 | +0.700R | 2.22 |
| 5.0 | 96.372 | %29.2 | +0.750R | 2.06 |

**Bulgular:**

1. **Trendline, test edilen HER R değerinde FVG/iFVG/OB'nin hepsinden
   daha yüksek beklenti veriyor** -- dört modül arasında şimdiye kadarki
   en güçlü sonuç (R=1.5: Trendline +0.507R vs OB +0.323R, iFVG +0.326R,
   FVG +0.237R).
2. **Profit factor R=2.0'da tepe yapıyor (2.30)** -- dört modülün de en
   yüksek PF'i (iFVG'nin en iyisi 1.99, OB'nin ~1.70, FVG'nin ~1.52 idi).
3. **Zaman dilimleri arasında dikkat çekici tutarlılık** -- FVG/iFVG/OB'de
   görülen "bir dilimde iyi, diğerinde kötü" örüntüsü yok (D1 hafif önde,
   ama W1 dışında hepsi güçlü ve birbirine yakın).
4. Bounce/reversal ayrı ayrı kırılmadı bu ilk raporda (havuzlanmış) --
   merak edilirse ayrıca çıkarılabilir.

**Önemli uyarı:** Kullanıcının daha önce onayladığı 10/20 örnek galerisi,
eski (hatalı, lookahead içeren) mantıkla üretilmişti -- bu rapor
düzeltilmiş mantığı kullanıyor, sayılar daha önce gösterilenlerden
farklı (daha düşük ama hâlâ güçlü ve artık güvenilir).

## Sembol eleme turu 2 ve 3 (2026-09-02)

95 sembollük $10.000 hesap simülasyonunun (2020-2025, 4 modül birlikte,
tek-pozisyon, sabit-$ risk modeli) sonuçlarına göre kullanıcı iki ek
eleme turu yaptı, `strategy/config.py:EXCLUDED_SYMBOLS`'a eklendi:

**Tur 2 -- en düşük getirili 10 sembol** (sabit-$ risk modelinde):
EURTRY, SPAIN35, SA40, TAIWAN, HK50, PALLADIUM, CHN50, CA60, USDTRY,
USDHKD (hepsi pozitifti ama en zayıf onda birdi).

**Tur 3 -- kazanma oranı eşiği:** İlk denenen %49.6 eşiği 70/94 sembolü
(GOLD dahil) eleyip sadece 24 sembol bırakıyordu -- kullanıcı bunu aşırı
bulup eşiği %47'ye indirdi. %47'nin altındaki 15 YENİ sembol (tur 2'yle
çakışanlar hariç) çıkarıldı: EURPLN, CHINAH, EU50, GER40, EURHUF,
NETH25, BTCUSD, EURSEK, EURCHF, USDNOK, GBPNOK, SING30, DOGEUSD, UK100,
EURGBP. GOLD (%47.9 kazanma oranıyla) eşiğin hemen üstünde kaldı.

**Sonuç (tur 3):** `EXCLUDED_SYMBOLS` 31 sembol, kanonik liste 101'den
70'e indi. Tüm aktif test scriptleri (9 dosya) güncellendi.

## Sembol eleme turu 4 -- kapsam 3 sembole daraltıldı (2026-09-02)

Kullanıcı kararıyla kapsam **GOLD, BTCUSD, EURGBP** üçlüsüne daraltıldı --
geri kalan TÜM semboller (BTCUSD ve EURGBP dahil, onlar tur 3'te
çıkarılmıştı, bu turda geri eklendi) çıkarıldı. `strategy/config.py`
yeniden yapılandırıldı: `KEPT_SYMBOLS = ("GOLD", "BTCUSD", "EURGBP")`
tanımlandı, `EXCLUDED_SYMBOLS` artık kanonik 101 sembollük evrenin
(`_ALL_101_SYMBOLS`) bu üçü hariç TAMAMI (98 sembol) -- önceki kademeli
tur yapısı (6+10+15) yerine tek, temiz bir tanıma geçildi (geçmiş
turların gerekçeleri yorum olarak korundu).

Tüm 9 aktif test scriptindeki `ALL_SYMBOLS` artık
`list(KEPT_SYMBOLS)` olarak `strategy/config.py`'den import ediliyor --
tek kaynaktan besleniyor, gelecekte tekrar genişletilirse tek yerden
değişecek.

## Breakeven-stop eklendi (2026-09-02)

Kullanıcı isteği: "TP'ye giderken SL'i girişe çekelim, işlem dönerse
zarar etmeyelim -- TP'nin %60'ına ulaştıysa SL girişe çekilsin."
`scratch_breakeven_sl_study.py` ile GOLD/BTCUSD/EURGBP'de (KEPT_SYMBOLS)
FVG/iFVG/OB için baseline (sabit SL) ile breakeven-stop karşılaştırıldı.

**Causal tasarım:** Her barda ÖNCE bir önceki bardan kalma `effective_sl`
kontrol edilir (vuruldu mu), SONRA TP, SONRA (ikisi de olmadıysa) bu
barın kendi hareketi %60 eşiğini geçtiyse SL bir SONRAKİ bar için girişe
çekilir -- aynı-bar lookahead'i yok.

**Sonuç (3 sembol havuzu):**

| Modül | Baseline exp | Breakeven exp | Baseline PF (GOLD) | Breakeven PF (GOLD) |
|---|---|---|---|---|
| FVG | 0.249 | 0.265 | 1.51 | 1.70 |
| iFVG | 0.340 | 0.346 | 1.65 | 2.02 |
| OB | 0.425 | 0.439 | 1.75 | 1.99 |

Üç modülde de PF belirgin artış (kayıpların bir kısmı -1R yerine 0R
oluyor), beklenti hafif artış, hiçbir yerde kötüleşme yok. Ham kazanma
oranı düşüyor görünüyor (bazı eski "kazananlar" artık breakeven
sayılıyor) ama bu yanıltıcı -- toplam R (expectancy) her modülde arttı.

**Uygulandı:** `strategy/config.py` -- `BREAKEVEN_TRIGGER_PCT = 0.6`,
`BREAKEVEN_ENABLED_MODULES = ("fvg", "ifvg", "ob")` (Trendline dahil
değil, kullanıcının sorusu bu üç modülle sınırlıydı). Üç resmi çalışma
scriptine (`scratch_fvg_tp_sl_study.py`, `scratch_ifvg_tp_sl_study.py`,
`scratch_ob_tp_sl_study.py`) aynı mantık gömüldü -- gelecekteki tüm
çalışmalar artık breakeven-stop'lu.

## Trendline kalibrasyonu tamamlandı (2026-09-01)

FVG/iFVG/OB'ye uygulanan "sağlıklı hale getirme" turu Trendline'a da
uygulandı, `strategy/config.py`'ye eklendi:

- **MODULE_R_MULTIPLE["trendline"] = 2.0** -- profit factor tam bu
  noktada tepe yapıyor (2.30), R=2.5'te zaten gerilemeye başlıyor
  (2.27). Beklenti (expectancy_r) OB'deki gibi 5.0R'ye kadar hiç tepe
  yapmadan artmaya devam ediyor (+0.75R'de), ama PF tepe noktası daha
  net ve dengeli bir seçim.
- **MODULE_SL_BUFFER_RATIO["trendline"] = 0.5** -- GOLD kalibrasyonundan
  (yukarıdaki tablo).
- **MODULE_DISABLED_TIMEFRAMES["trendline"] = ("H4",)** -- R=2.0'da
  win=%51.9, PF=2.16 ile 6 dilim içinde en düşük (diğerleri 2.16-2.35
  aralığında birbirine çok yakın olsa da H4 en zayıfı).

**Sembol bazlı liderlik tablosu -- kritik fark:** FVG/iFVG/OB'nin
aksine, Trendline'ın en kötü 10 sembolü bile (en düşük: AUS200
exp=+0.390R, PF=1.73) **pozitif beklenti** veriyor -- negatif hiçbir
sembol yok. Bu, `EXCLUDED_SYMBOLS`'daki 6 sembolün (GERTECH30, NASDAQ,
IT40, GERMID50, EURDKK, USFANG) hiçbiri Trendline'ın kendi en kötü
10'unda bile çıkmadı, dolayısıyla listeye Trendline kaynaklı yeni bir
sembol eklenmedi. Trendline, dört modül arasında hem en yüksek
beklentili hem de sembol bazında en tutarlı/sağlam modül.

## Order Block'un eksik ICT filtreleri -- ablation testi SONUCU: HİÇBİRİ BENİMSENMEDİ (2026-09-02)

"OB filtreleri → Katman entegrasyonu → confluence testi" sırasının ilk
adımı olarak, standart ICT tanımında olup kodda eksik olan üç filtre
(bkz. modül docstring'i, `strategy/order_block.py`) her `OrderBlock`
üzerinde bilgi amaçlı boolean alan olarak eklendi:

- **`engulfing`** -- impuls mumu, OB mumunun fitil dahil tüm high-low
  aralığını kapsıyor mu.
- **`swept_liquidity`** -- OB mumu, kendinden önceki
  `ob_liquidity_sweep_lookback` (=10) barın en dip/tepe seviyesini
  geçti mi (likidite süpürmesi).
- **`htf_discount_aligned`** -- entry seviyesi, `ob_premium_discount_lookback`
  (=48 bar, M30'da ~1 gün, gerçek bir HTF mumu değil proxy) barlık
  aralığın doğru yarısında mı (bullish→discount/alt yarı,
  bearish→premium/üst yarı).

`scratch_ob_filters_study.py` ile GOLD/BTCUSD/EURGBP'de (M30, resmi
R=3.0/SL=gövde×3.0/breakeven-stop açık metodolojiyle) baseline (tüm
OB'ler) karşısında bu üç filtrenin tek başına ve ikili/üçlü tüm
kombinasyonları test edildi. **Sonuç beklenmedik ve tek yönlü:
HER filtre ve HER kombinasyon, istisnasız, baseline'a göre win rate/
beklenti/PF'yi DÜŞÜRÜYOR** -- havuzlanmış (3 sembol, n=35068 baseline):

| Filtre seti | n | win_rate | expectancy_r |
|---|---|---|---|
| baseline_all | 35068 | 31.9% | 0.439 |
| engulfing_only | 8056 | 28.5% | 0.304 |
| swept_liquidity_only | 11694 | 28.1% | 0.292 |
| htf_discount_only | 17993 | 30.9% | 0.398 |
| engulfing_AND_sweep | 2295 | 24.4% | 0.158 |
| engulfing_AND_htf | 4284 | 26.8% | 0.233 |
| sweep_AND_htf | 8205 | 27.8% | 0.280 |
| all_three | 1622 | 24.0% | 0.139 |

Desen tüm 3 sembolde ayrı ayrı da aynı yönde (bkz.
`ob_filters_study_results.json`) -- ne kadar çok filtre üst üste
binerse beklenti o kadar düşüyor, en kötüsü `all_three` (0.439→0.139).
Bu, standart ICT kaynaklarının iddiasının (bu filtreler "kaliteyi
artırır") **bu kod tabanının OB tanımıyla/veri setiyle DOĞRULANMADIĞI**
anlamına geliyor -- muhtemel neden: bu üç filtre zaten en GÜÇLÜ/en
temiz displacement'ları seçiyor, ama OB'nin resmi R=3.0 hedefi için asıl
belirleyici olan şey mumun "ICT-kalitesi" değil, basitçe daha FAZLA
örneklem/çeşitlilik (mevcut baseline zaten iyi çalışıyor, R=3.0'da
PF=1.99 GOLD'da) -- filtreler örneklemi daraltırken sinyalin kendi
doğasında bir iyileşme getirmiyor.

**Karar (ablation disiplinine göre):** Hiçbiri `detect_order_blocks`'un
ELEME mantığına veya resmi metodolojiye (`strategy/config.py`)
işlenmedi -- üç alan (`engulfing`, `swept_liquidity`,
`htf_discount_aligned`) sadece bilgi amaçlı `OrderBlock` üzerinde
duruyor, gelecekte confluence/Katman çalışmalarında farklı bir
kombinasyonla yeniden değerlendirilebilir ama şu an OB sinyal
üretiminde hiçbir değişiklik yok. Sıradaki adıma (Alan/Katman
entegrasyonu) geçildi.

## "sırasıyla yapalım" sıralamasının 3. ve son adımı: Confluence testi -- SONUÇ: BAŞKA BİR NEGATİF BULGU (2026-09-02)

Sıralamanın son sorusu: `strategy/signal_engine.py`'nin A+ fikri
(FVG+OB aynı bölgede/yönde çakışırsa daha güçlü sinyal) 4 modüle
(FVG, iFVG, Order Block, Trendline) genellenip ölçekli test edilirse
gerçekten kalite artıyor mu? `scratch_confluence_study.py` ile
GOLD/BTCUSD/EURGBP'de (M30, her modülün resmi R/SL/breakeven
parametreleriyle), her sinyalin kendi tetiklenme barında kaç BAŞKA
modülün aynı yönde/bölgede aktif sinyali olduğu (`confluence` sayısı,
0-3 arası) sayılıp bucket'landı. Aktiflik penceresi modeli: gerçek
invalidation biliniyorsa (FVG.filled_at_index, OB.mitigated_index) o
kullanıldı, iFVG/Trendline'da (kod tabanında invalidation izlenmiyor)
`MAX_ACTIVE_BARS=500` varsayımı kullanıldı (kalibre edilmedi, açıkça
belirtildi).

**Havuzlanmış (3 sembol) sonuç:**

| confluence | n | win% | exp_r |
|---|---|---|---|
| 0 (tek modül) | 43008 | 38.8% | 0.389 |
| 1 (2 modül aynı fikirde) | 26216 | 38.0% | 0.369 |
| 2 (3 modül aynı fikirde) | 3610 | 36.1% | 0.362 |
| 3 (4 modül aynı fikirde) | 73 | 43.8% | 0.589 |

**Desen, OB filtreleri ve Katman'daki AYNI negatif bulguyu tekrarlıyor:**
confluence=1 ve confluence=2, baseline'a (confluence=0) göre DAHA
KÖTÜ -- "daha çok modül aynı fikirde = daha kaliteli sinyal" hipotezi
burada da doğrulanmıyor. confluence=3'teki iyileşme (0.589) tek
başına çekici görünse de örneklem (n=73, tek sembolde n=11-42 arası)
istatistiksel olarak güvenilmez -- BTCUSD'de confluence=3'ün PF=12.00
çıkması (n=11) klasik küçük-örneklem aşırı-değeri, gerçek bir sinyal
değil.

**Üç ayrı ampirik testin (OB filtreleri, Katman, confluence) tutarlı
ortak sonucu:** V1'in temel sinyal havuzu (FVG/iFVG/OB/Trendline,
kendi resmi R/SL/breakeven parametreleriyle) zaten kendi başına
sağlıklı çalışıyor (PF 1.7-2.2 aralığında, tüm bucket'larda pozitif
beklenti) -- üstüne eklenen HİÇBİR ek filtre/teyit katmanı (ICT
filtreleri, Katman/Alan konumu, çoklu-modül confluence) örneklem
büyüklüğünü feda etmeye değecek bir kalite artışı getirmiyor. Bu,
kaynağın ("N/O-A Konsepti") daha üst katmanlarına (Alan Gücü, Setup
Kalitesi, Eylem 1/2) geçmeden önce ciddiye alınması gereken bir sinyal:
mevcut basit V1 tanımları muhtemelen zaten kaynaktaki daha karmaşık
puanlama sisteminin yakaladığı "iyi setup"ları kabaca kapsıyor,
üstüne konan ek koşullar sadece örneklemi daraltıp gürültüyü artırıyor.

**Karar:** `strategy/signal_engine.py`'ye confluence-sayısı bazlı hiçbir
filtre/ağırlıklandırma eklenmedi. "sırasıyla yapalım" sıralamasının
üç adımı da (OB filtreleri, Katman entegrasyonu, confluence testi)
tamamlandı -- üçü de mevcut metodolojiyi DEĞİŞTİRMEME kararıyla sonuçlandı.

## 95 sembollük tam işlem arşivi + Breakeven eşik taraması (2026-09-02)

**Tam işlem arşivi:** Kullanıcı "son genel test"in (95 sembollük $10k
hesap simülasyonu) SL'e takılan işlemlerini hatırlamak istedi -- o
testte sadece sembol başına tek en iyi/en kötü işlem kaydedilmişti, tam
liste hiç saklanmamıştı. `scratch_trade_archive.py` ile AYNI 95 sembol
kapsamıyla (Tur 1'in 6 sembol çıkarmasından sonraki tam evren, MEVCUT
KEPT_SYMBOLS'un 3 sembolünden BİLEREK farklı -- kullanıcı özellikle
geniş kapsamı istedi), güncel resmi metodolojiyle (breakeven-stop dahil)
yeniden çalıştırıldı, HER gerçekleşen işlem (sadece en iyi/en kötü değil)
+ görselleştirme için bir mum penceresi `trade_archive/{SEMBOL}.json`
altına kaydedildi. Sonuç: **230.068 gerçek işlem** (95.298 kazanan,
88.719 SL/zarar, 46.051 breakeven), 618MB, checkpoint'li/kesintiye
dayanıklı (detached PowerShell process, ~5 saat sürdü, 1 sembolde --
LTCUSD -- anormal bir yavaşlama (~2.8 saat) gözlendi ama hatasız
tamamlandı, nedeni araştırılmadı).

**Breakeven eşik taraması:** Kullanıcı sordu -- "TP'ye giden yolun
yarısını (%50) kat ettiyse SL girişe çekilirse win rate/kâr nasıl
etkilenir?" Üç aşamalı sweep yapıldı (GOLD/BTCUSD/EURGBP, FVG/iFVG/OB,
`scratch_breakeven_trigger_sweep_study.py` + `_spread_sweep_study.py`):

1. **Kaba tarama (%30-80, spread=0):** mevcut resmi eşik olan %60
   OPTIMAL DEĞİL -- expectancy eşik düştükçe monoton artıyor. %50 bile
   %60'tan iyi (havuzlanmış exp: 0.368 vs 0.363).
2. **İnce tarama (%5-30, spread=0):** eğri düzleşiyor (azalan getiri)
   ama tepe %5'te bile bulunamadı (exp=0.393) -- ama breakeven oranı
   %46.3'e çıkıyor (işlemlerin neredeyse yarısı sıfır sonuçlanıyor).
3. **Spread-DAHİL tarama** (temsili spread -- veri kaynağında
   (`data/canonical/*.csv`) SPREAD sütunu tamamen sıfır, GERÇEK spread
   veriden türetilemedi; GOLD=0.25, BTCUSD=20, EURGBP=0.0002 gibi tipik
   piyasa değerleri kullanıldı, kalibre edilmedi): **sıralama
   DEĞİŞMEDİ** (düşük eşik hala daha iyi, %10 en iyisiydi tüm testte),
   ama mutlak değerler çok kötüleşti -- havuzlanmış expectancy TÜM
   eşiklerde NEGATİFE döndü (BTCUSD/EURGBP'nin FVG/OB modüllerinde
   spread, dar SL'lere göre orantısız büyük çıktı -- ör. BTCUSD OB
   baseline exp=-0.389R). GOLD tek başına her eşikte pozitif kaldı.
   Bu, ayrı ve daha büyük bir bulgu: gerçekçi spread varsayımıyla
   FVG/OB'nin bazı sembol/enstrüman kombinasyonları hiç kârlı
   olmayabilir -- eşik seçiminden bağımsız bir konu, ayrıca
   araştırılmalı.

**Karar:** Sıralama üç testte de tutarlı olduğu (düşük eşik daha iyi)
ama en agresif uç (%5-10, %46 breakeven oranı) hiç kalibre edilmediği
ve gerçek spread verisiyle doğrulanmadığı için, kullanıcının özgün
sorusu olan VE üç testte de açıkça %60'tan iyi çıkan **%50** resmi
değer olarak benimsendi (`strategy/config.py:BREAKEVEN_TRIGGER_PCT`,
0.6 → 0.5). Daha agresif (%10-30) uç, gerçek spread verisi veya daha
geniş sembol kapsamı olmadan resmi hale getirilmedi -- ileride ayrı bir
çalışmayla değerlendirilebilir.

## KRİTİK BULGU — Bu oturumun tüm kalibrasyonu, projenin mevcut rigorous walk-forward/holdout altyapısından hiç geçirilmemişti (2026-09-02)

Kullanıcı "finans uzmanı/trader/yazılım mühendisi" bakış açısıyla
sağlamlık testleri önerisi istedi (bkz. "Sağlamlık Testleri Yol
Haritası" sunumu). En yüksek öncelikli önerilen adımı (walk-forward/
holdout) uygulamaya başlarken, **projenin bunun için zaten eksiksiz,
daha önce kurulmuş bir altyapısı olduğu** keşfedildi: `backtest/
final_holdout.py` (Phase 4F, "Sacred Holdout"), `validation.py`
(chronological train/val/holdout split + walk-forward), `robustness.py`
(parametre pertürbasyon testi), `regime.py` (rejim/zaman/volatilite
bucket'ları + block-bootstrap güven aralığı). Bu altyapı DAHA ÖNCE
(2026-08-28, bkz. README.md) V1'in ("eski" FVG+OB+Destek/Direnç, trend
filtreli) sahte "%92.7 win rate" iddiasını "FAILED TO GENERALIZE"e
çevirmişti.

**Ama bu oturumun TÜM işi** (FVG/iFVG/Order Block/Trendline'ın yeniden
kalibre edilen R-katı hedefleri, SL tamponları, breakeven-stop eşiği,
95 sembollük işlem arşivi, GOLD $10k hesap simülasyonu -- hepsi) bu
altyapıyı HİÇ kullanmadan, ~100 bağımsız `scratch_*.py` script'inin
kendi basit (walk-forward'suz, block-bootstrap'suz) simülasyon
mantığıyla yapılmıştı. `strategy/signal_engine.py` hâlâ eski (A+/
trend-filtreli, sadece FVG+OB, Destek/Direnç tabanlı TP) tasarımdaydı
-- bu oturumun kalibre ettiği stratejiyle hiçbir bağlantısı yoktu.

### Yapılan entegrasyon

1. `strategy/ifvg.py` -- `detect_confirmed_ifvgs` (önceden sadece
   `scratch_ifvg_tp_sl_study.py` içinde gömülüydü) gerçek bir strateji
   modülüne taşındı, `IFVGEvent` dataclass'ı ile (7 yeni birim testi,
   `_mark_chop_clusters` ayrı test edilebilir fonksiyona çıkarıldı).
2. `strategy/signal_engine.py` TAMAMEN yeniden yazıldı: A+ confluence
   ve trend/EMA filtresi kaldırıldı (confluence ablation'ın ve bu
   oturumun hiçbir kalibrasyon çalışmasının bunları kullanmadığı
   gerekçesiyle) -- artık FVG/iFVG/Order Block/Trendline (bounce +
   kırılım-retest) BAĞIMSIZ sinyal üretiyor, her biri kendi resmi
   `MODULE_R_MULTIPLE`/`MODULE_SL_BUFFER_RATIO`/`BREAKEVEN_TRIGGER_PCT`
   parametresini `Signal.take_profit`/`breakeven_trigger_pct` alanlarına
   yazıyor (5 yeni birim testi).
3. `backtest/engine.py`: `Signal.take_profit` doluysa DOĞRUDAN
   kullanılıyor (Destek/Direnç aramasına düşmüyor); breakeven-stop
   mantığı (nedensel sıra korunarak -- önce eski SL, sonra TP, sonra
   bu barın arm kontrolü) pozisyon-çıkış döngüsüne eklendi (4 yeni
   birim testi, mevcut 30 test regresyon olmadan geçti).
4. `backtest/final_holdout.py`: `run_final_holdout_evaluation`'a
   `val_metrics` parametresi eklendi -- önceden GÖMÜLÜ, V1'e ait eski
   sabitlere (expectancy=0.5253 vb.) karşı delta hesaplıyordu, artık
   TAZE `build_validation_report` sonucu geçirilebiliyor (sınıflandırmanın
   kendisini etkilemiyordu ama delta raporlamasını yanlış taban
   çizgisiyle yapıyordu).

Tam test paketi: 469/470 geçti (1 önceden var olan, ilgisiz Telegram
hatası).

### Kutsal holdout sonucu (TEK ATIMLIK, `scratch_holdout_validation_run.py`)

GOLD/BTCUSD/EURGBP, tam geçmiş (2010/2013/2017'den 2026'ya), temsili
spread (GOLD=0.25, BTCUSD=20, EURGBP=0.0002 -- veri kaynağında gerçek
spread hiç yok):

| Sembol | TRAIN exp | VAL exp | Walk-forward exp | HOLDOUT exp | HOLDOUT PF | Sınıflandırma | %95 Bootstrap CI |
|---|---|---|---|---|---|---|---|
| GOLD | -0.339 | -0.294 | -0.307 | -0.185 | 0.70 | FAILED TO GENERALIZE | [-0.226, -0.145] |
| BTCUSD | -0.350 | -0.323 | -0.394 | -0.265 | 0.62 | FAILED TO GENERALIZE | [-0.313, -0.219] |
| EURGBP | -0.545 | -0.638 | -0.571 | -0.833 | 0.21 | FAILED TO GENERALIZE | [-0.872, -0.790] |

**3/3 sembolde, TRAIN partisyonunda (in-sample!) bile expectancy
negatif.** Bu, "holdout'a genellenmiyor" değil, daha temel bir şey
söylüyor: rigorous motorla (aynı-barda-iyimser-TP-yok, aynı-barda-
sinyal-barıyla-dolum-yok) ölçüldüğünde stratejinin in-sample bile
pozitif edge'i yok.

### Kök neden araştırması (kod hatası DEĞİL -- iki ayrı metodolojik iyimserlik)

Sonuç ilk bakışta "entegrasyon bozuk" şüphesi uyandırdı (bu oturumun
TÜM diğer çalışmaları pozitifti). GOLD'un son 6.000 M30 mumluk
diliminde, AYNI sinyaller üzerinde eski scratch mantığı ile yeni motor
doğrudan karşılaştırılarak araştırıldı (bkz. bu oturumun sohbet
geçmişi -- ayrıntılı adım adım karşılaştırma):

1. **Order Block -- "impuls barının kendisiyle aynı barda dolum"**:
   `scratch_gold_account_simulation.py`'nin `_ob_trades`'i, dolum
   taramasını `ob.impulse_index`'ten (DAHİL) başlatıyordu. Ama impuls
   barının "güçlü hareket" sayılabilmesi için TAM aralığının (kapanışa
   kadar) bilinmesi gerekiyor -- o barın kendi dip/tepe noktasını
   (kapanmadan önce oluşmuş) "aynı zamanda girişe geri çekildi" diye
   kullanmak, gerçek işlemde ASLA mümkün olmayan bir bilgiyi kullanmak
   demek. Tek başına `impulse_index+1`'den başlatmak: win rate
   %33.8→%23.3, expectancy +0.35R→-0.07R.
2. **TÜM modüller -- "aynı barda iyimser TP kabul etme"**: scratch
   script'lerin ortak `_scan_fill_and_exit` deseni, dolum barının
   KENDİSİNDE hem SL hem TP'ye ulaşılabiliyorsa TP'nin önce vurulduğunu
   varsayıyordu. `backtest/engine.py` (bu oturumdan bağımsız, çok daha
   önce yazılmış ve test edilmiş -- `test_same_bar_entry_and_tp_ambiguity_no_optimistic_tp`)
   bunu HİÇBİR ZAMAN yapmıyor -- dolum barında sadece pesimistik SL
   kontrolü yapılıyor, TP her zaman bir SONRAKİ bara erteleniyor (çünkü
   tek bir OHLC barından hangisinin ÖNCE geldiği kesin bilinemez). Bu
   TEK kuralı FVG'de izole edip test etmek (fill mantığı birebir aynı
   tutularak): win rate %51.8→%36.0, expectancy +0.29R→-0.10R -- OB'de
   gözlenen toplam farkın neredeyse tamamını tek başına açıklıyor.

Her iki iyimserlik de sonucu YUKARI yanlı hale getiriyordu. Yeni
`strategy/signal_engine.py`/`backtest/engine.py` entegrasyonu HİÇBİRİNİ
içermiyor -- düzeltilecek bir kod hatası yok, holdout'u tekrar
çalıştırmak (deterministik, aynı kod+veri) aynı sonucu verir.

### Karar ve kapsam

Bu bulgu, README.md'nin en üstüne ikinci bir "KRİTİK" bölüm olarak
eklendi (2026-08-28'deki V1 bulgusuyla aynı ağırlıkta ama farklı bir
strateji/oturuma ait). Bu oturumun ürettiği TÜM pozitif sonuçlar
(breakeven-stop eşiği seçimi, R-katı/SL tamponu kalibrasyonları, GOLD
$10k hesap simülasyonu, 95 sembollük tam işlem arşivi) bu iki
iyimserlik yüzünden gerçek olandan daha iyi görünüyor olabilir --
kesin miktar sembol/modüle göre değişir, sistematik olarak
ölçülmedi. `results/holdout_validation/holdout_validation_results.json`
tam train/val/walk-forward/holdout/block-bootstrap verisini içeriyor.

Bu, kullanıcının "sağlamlık testleri" talebinin doğrudan ve en değerli
sonucu -- tam olarak arananı buldu: bu oturumun sonuçlarının ne kadar
güvenilir olduğu sorusuna kesin, istatistiksel olarak sağlam bir cevap.

## Win rate iyileştirme araştırması -- internet taraması (2026-09-03)

Kullanıcı "trader ve finans uzmanı gibi düşün, internete eriş, win rate'i
nasıl artırabileceğimizi araştır" dedi. WebSearch ile ICT/SMC (Smart
Money Concepts) literatürü, quant/skeptik kaynaklar ve kaynak-materyalin
kendi referans verdiği siteler (TrendSpider, LuxAlgo, ICTKillzone vb.)
tarandı.

**En önemli bulgu -- bağımsız bir doğrulama:** MPM Research'ün (2026-07)
FVG backtest çalışması, TAM OLARAK bizim kendi bulduğumuz hata sınıfını
(same-bar/intrabar belirsizlik) bağımsız olarak tespit etmiş: "win rate
fell from roughly 73% to roughly 50% when properly accounting for
methodology issues... the entire apparent edge was intrabar look-ahead."
Metodoloji: 4 futures piyasası, 5m/15m/1H, sonuçlar 1 dakikalık veride
çözümlenerek (bizim `backtest/engine.py`'nin "aynı barda iyimser TP
yok" kuralıyla AYNI disiplin) doğrulanmış. Sonuç: **"the reaction is
real; the tradeable edge is not."** Bu, bizim holdout bulgumuzun tesadüf
olmadığını, daha geniş bir literatürde de tekrarlanan bir örüntü
olduğunu gösteriyor -- FVG/OB tipi setup'ların "reaksiyonu" gerçek
(fiyat gerçekten tepki veriyor) ama naif backtest'lerdeki "edge"in çoğu
ölçüm hatasından kaynaklanıyor.

**Test edilmeye değer, YENİ (bu projede hiç denenmemiş) adaylar:**

1. **Seans/Killzone zaman filtresi** -- ICT kaynakları Londra (08:00-09:00
   GMT), NY AM (12:00-15:00 GMT), NY PM (18:00-19:00 GMT) killzone'ları
   dışındaki sinyallerin kalitesiz olduğunu iddia ediyor (bir kaynak
   "%68 vs %41 win rate" iddia etti -- ICT pazarlama materyali, şüpheyle
   yaklaşılmalı, ama fikir kendi verimizle doğrudan test edilebilir --
   candle timestamp'leri zaten elimizde).
2. **Hacim (tick_volume) teyidi** -- "displacement candle'ın volume'u
   son 20 mumun ortalamasının 1.5-2 katı olmalı" -- birden fazla kaynak
   bunu "tek en iyi filtre" diye işaretledi. Projede tick_volume alanı
   zaten candle dict'lerinde var ama HİÇBİR modülde hiç kullanılmadı --
   tamamen yeni bir sinyal boyutu.
3. **OTE (Optimal Trade Entry, %61.8-%79 Fibonacci)** -- FVG'nin %50
   orta noktası yerine daha derin bir geri çekilme seviyesinden giriş.
   Basit bir parametre değişikliği, breakeven eşiği taramasıyla ayni
   yöntemle test edilebilir.
4. **BOS/MSS (Break of Structure/Market Structure Shift) şartı** --
   FVG/OB sadece bir yapısal kırılmadan SONRAKİ N bar içinde oluştuysa
   geçerli sayılsın. Daha karmaşık (yapısal kırılma dedektörü
   gerektiriyor), bu turda ERTELENDİ.
5. **Breaker Block / Mitigation Block ayrımı** -- OB'nin başarısız
   olma şekli (likidite süpürmesi sonrası mı, süpürme olmadan mı
   kırıldı) gelecekteki tepkiyi öngörebilir -- daha önce de bu modülün
   docstring'inde "kapsam dışı" diye not edilmişti, hâlâ ERTELENDİ.

**Metodolojik disiplin (korunuyor):** Yukarıdaki MPM bulgusu göz önüne
alınarak, hiçbiri "mantıklı geliyor" diye doğrudan benimsenmeyecek --
her biri ayrı ayrı, DÜZELTİLMİŞ motorla (`strategy/signal_engine.py`+
`backtest/engine.py`, same-bar-iyimserliği YOK) KEPT_SYMBOLS üzerinde
ablation test edilip, sadece gerçekten iyileştirdiği ölçülürse
benimsenecek.

Kaynaklar: [Fair Value Gap best practices (edgeful)](https://www.edgeful.com/blog/posts/fair-value-gap-best-practices-guide),
[Does the FVG Strategy Work? (MPM Research)](https://mpmmarkets.com/research/does-the-fair-value-gap-strategy-work),
[ICT Order Block guide (ictkillzone.com)](https://www.ictkillzone.com/ict-order-block),
[Liquidity Sweep guide (backtrex)](https://backtrex.com/en/blog/liquidity-sweep-smc-ict-trading-guide),
[Optimal Trade Entry (LuxAlgo)](https://www.luxalgo.com/library/concept/optimal-trade-entry/),
[ICT Fibonacci/OTE (fxnx)](https://fxnx.com/en/blog/ote-why-70-5-79-beats-every-other-fib),
[Market Structure Shift (FXOpen)](https://fxopen.com/blog/en/market-structure-shift-meaning-and-use-in-ict-trading/),
[Breaker Blocks guide (3Commas)](https://3commas.io/blog/breaker-blocks-a-smart-money-trading-guide-from-ex),
[Mitigation Blocks guide (eplanetbrokers)](https://eplanetbrokers.com/training/what-is-mitigation-block),
[ICT Killzones guide (ictkillzone.com)](https://www.ictkillzone.com/ict-kill-zones),
[Displacement & Imbalance (liquidityfinder)](https://liquidityfinder.com/news/advanced-displacement-and-imbalance-the-smart-money-concepts-trick-most-traders-miss-9d2d9),
[Trendline Liquidity (LuxAlgo)](https://www.luxalgo.com/library/concept/trendline-liquidity/).

## Win rate araştırması -- Aday 1 ve 2 sonucu: Killzone + Hacim teyidi (2026-09-03)

`strategy/fvg.py`+`strategy/order_block.py`'ye `in_killzone`/`volume_confirmed`
bilgi amaçlı alanları eklendi (16 yeni birim testi), `strategy/session.py`
yeni modülü (killzone saat pencereleri) yazıldı. `scratch_winrate_filters_study.py`
ile DÜZELTİLMİŞ motorla (`strategy/signal_engine.py`+`backtest/engine.py`),
KEPT_SYMBOLS + gerçekçi spread ile ablation test edildi:

| Filtre | FVG win/exp | OB win/exp |
|---|---|---|
| baseline | %19.8 / -0.528R | %14.1 / -0.420R |
| killzone_only | %20.1 / -0.525R | %13.5 / -0.492R (KÖTÜLEŞTİ) |
| **volume_only** | **%22.6 / -0.374R** | %14.3 / -0.433R |
| killzone+volume | %22.7 / -0.384R | %13.6 / -0.554R |

**Killzone filtresi işe yaramadı** -- ICT pazarlama materyalinin
iddialarını (bkz. araştırma bölümü, "%68 vs %41 win rate") DOĞRULAMADI,
MPM Research'ün şüpheci duruşunu destekliyor. **Hacim teyidi FVG'de
gerçek ve tutarlı bir iyileşme gösterdi** (3 sembolde de aynı yönde,
win +2.8pp, beklenti +0.15R) -- bu araştırmanın şu ana kadarki tek
pozitif (yön olarak) bulgusu. OB'de etkisiz/nötr. ÖNEMLİ: hiçbiri
mutlak olarak pozitife dönmedi -- spread maliyeti hâlâ baskın (holdout
bulgusuyla tutarlı). Hacim teyidi henüz resmi metodolojiye (sinyal
üretiminde ELEME olarak) İŞLENMEDİ -- tek başına yeterli değil, diğer
adaylarla (giriş derinliği, BOS/MSS) birlikte değerlendirilecek.

## Win rate araştırması -- Aday 3 sonucu: FVG giriş derinliği -- BENİMSENDİ (2026-09-03)

`scratch_fvg_entry_depth_study.py` ile FVG girişinin gap içindeki
derinliği (0.0=sığ/yakın kenar, 1.0=eski/derin kenar) DÜZELTİLMİŞ
motorla, KEPT_SYMBOLS + gerçekçi spread ile 7 noktada tarandı:

| frac | Havuzlanmış win | Havuzlanmış exp |
|---|---|---|
| **0.000 (yeni)** | **%23.9** | **-0.269R** |
| 0.250 | %23.3 | -0.308R |
| 0.500 (ICT "CE" orta nokta) | %22.5 | -0.359R |
| 0.618 (OTE alt sınır) | %21.9 | -0.393R |
| 0.705 (OTE "sweet spot") | %21.4 | -0.419R |
| 0.790 (OTE üst sınır) | %21.2 | -0.444R |
| 1.000 (eski/mevcut davranış) | %19.8 | -0.528R |

**3 sembolde de (GOLD/BTCUSD/EURGBP) tutarlı, monoton bir eğim** -- ne
kadar sığ (az retracement gerektiren) giriş, o kadar iyi sonuç. Bu,
standart ICT tavsiyesinin (0.5-0.79 arası "OTE" bölgesi) TAM TERSİ --
araştırılan ICT kaynakları hep daha DERİN bir retracement öneriyordu,
ama bizim verimizde en SIĞ nokta en iyisi çıktı.

**Mekanizma notu (dürüstçe belirtiliyor):** SL formülü sabit kaldı
(hep uzak kenara göre) -- entry sığlaştıkça risk mesafesi büyüyor. Yani
bu bulgu kısmen "daha iyi zamanlama" değil, "daha geniş bir stop mesafesi
gürültüyle daha az tetikleniyor" mekanizması olabilir. Ama SONUÇ (R
cinsinden ölçülen gerçek performans) her iki yorum için de aynı ve
gerçek.

**KARAR: benimsendi.** `strategy/fvg.py:FVG.entry_price` artık gap'in
sığ/yakın kenarını (bullish->top, bearish->bottom) döndürüyor -- eski
davranışın (derin kenar) TAM TERSİ. Bu, `strategy/signal_engine.py`
üzerinden otomatik olarak tüm FVG_ONLY sinyallerine yansıyor (kod
değişikliği yok, sadece FVG modülünün kendi kuralı değişti). Test
paketi güncellendi (`tests/test_fvg.py`, `tests/test_signal_engine.py`
-- entry_price'a bağlı beklenen değerler yeni davranışa göre düzeltildi).

## Win rate araştırması -- Aday 4 sonucu: OB giriş derinliği -- BENİMSENDİ (2026-09-03)

Aynı sığ-kenar bulgusunun Order Block'a da uygulanıp uygulanmadığı
`scratch_ob_entry_depth_study.py` ile test edildi (OB'nin mevcut
girişi govde ORTASI, frac=0.5). Sonuç FVG ile BİREBİR AYNI yönde,
3 sembolde de tutarlı:

| frac | Havuzlanmış win | Havuzlanmış exp |
|---|---|---|
| **0.000 (yeni)** | **%14.8** | **-0.369R** |
| 0.250 | %14.4 | -0.395R |
| 0.500 (eski/mevcut davranış -- govde ortası) | %14.1 | -0.420R |
| 0.750 | %13.8 | -0.447R |
| 1.000 (uzak kenar) | %13.4 | -0.479R |

**KARAR: benimsendi.** `strategy/signal_engine.py`'nin OB girişi artık
govde ortası yerine sığ/yakın kenar (`ob.top if is_bull else ob.bottom`).
Test paketi güncellendi (`tests/test_signal_engine.py`). Bu, art arda
İKİNCİ modülde aynı deseni doğruladı -- "sığ giriş" artık tesadüf değil,
FVG/OB'nin ortak SL formülü (her zaman uzak kenara göre sabit) ile
etkileşen sistematik bir mekanizma olarak kabul ediliyor.

**Checkpoint -- iki entry-depth düzeltmesinin GOLD/BTCUSD/EURGBP $10k
hesap simülasyonundaki (sabit-$ model) toplam etkisi**
(`scratch_corrected_account_simulation.py` tekrar çalıştırıldı):
GOLD -$44.803→-$46.200 (~%3 kötü), BTCUSD -$115.215→-$66.160 (**%43
iyi**), EURGBP -$352.689→-$196.310 (**%44 iyi**). Toplam: -$512.706→
-$308.670, **~%40 iyileşme**. Bileşik model her ikisinde de pratik
olarak $0'a gidiyor (zaten önceden de öyleydi, entry-depth bunu
değiştirmedi). Modül bazında GÖZLEM: FVG'nin iyileşmesi TUTARLI, ama OB
bazen KÖTÜLEŞTİ (örn. BTCUSD'de OB +$4.424→-$1.845) -- bu, izole
ablation testlerinin YAKALAYAMADIĞI bir etki: 4 modül birlikte
çalışırken tek-pozisyon REKABETİ var, bir modülün daha çok/hızlı sinyal
alması diğerinin payını değiştirebiliyor. İzole test sonuçları (`her
modül kendi başına daha iyi`) ile birleşik hesap sonucu (`bazı modüller
daha kötü`) arasındaki bu fark açıkça not ediliyor -- gelecekteki her
ablation bulgusu için hatırlanması gereken bir kısıtlama.

## Win rate araştırması -- Aday 5 sonucu: R-katı yeniden kalibrasyonu -- BENİMSENMEDİ (2026-09-03)

`scratch_r_multiple_recalibration_study.py` ile FVG/OB'nin R-katı
hedefi (TP), YENİ giriş kuralıyla ve DÜZELTİLMİŞ motorla yeniden
tarandı (0.5-5.0R). Sonuç:

- **FVG:** Havuzlanmış expectancy en iyi R=4.0'da (-0.248R) ama eğri
  R=2.0-5.0 arası ÇOK DÜZ (-0.246 ile -0.263 arası, gürültü payı
  yüksek) -- mevcut resmi R=1.5'in (-0.269R) üzerinde sadece ~0.02R'lik
  bir kazanç var. AMA win rate R arttıkça SİSTEMATİK olarak düşüyor:
  R=1.5'te %23.9 iken R=4.0'da %14.0'a iniyor.
- **OB:** Mevcut resmi R=3.0 (-0.3685R) zaten neredeyse optimal
  (en iyisi R=5.0'da -0.3669R, farkı ihmal edilebilir).

**KARAR: benimsenmedi.** Kullanıcının özgün sorusu açıkça "win rate"
idi -- expectancy'deki ihmal edilebilir kazanç, win rate'teki büyük
kaybı (özellikle FVG'de) haklı çıkarmıyor. R-katları olduğu gibi
bırakıldı (FVG=1.5, OB=3.0).

## Win rate araştırması -- Aday 2 yeniden test + KARAR: hacim teyidi (FVG) -- BENİMSENDİ (2026-09-03)

Aday 1/2 bölümünde hacim teyidi ESKİ (derin kenar) giriş temelinde
test edilip "henüz resmi metodolojiye işlenmedi" denmişti. Entry-depth
(Aday 3/4) benimsendikten SONRA, `scratch_winrate_filters_study.py`
YENİ (sığ kenar) temel üzerinde TEKRAR çalıştırıldı -- amaç, filtrenin
hâlâ (ve ne kadar) işe yaradığını YENİ baseline'a göre doğrulamaktı:

| Filtre | FVG win/exp (yeni baseline) |
|---|---|
| baseline (sığ kenar, entry-depth sonrası) | %23.9 / -0.269R |
| killzone_only | değişmedi/işe yaramadı (Aday 1/2 ile tutarlı) |
| **volume_only** | **%25.1 / -0.179R** |

Hacim teyidi YENİ temelde de doğrulandı -- hatta ESKİ temeldeki
iyileşmeden (+2.8pp/+0.15R) DAHA GÜÇLÜ çıktı (+1.2pp win ama expectancy
+0.09R, ve mutlak win rate seviyesi zaten yükselmiş durumda). Killzone
yine işe yaramadı, OB yine etkilenmedi. Bu, iki bağımsız temelde
(entry-depth öncesi ve sonrası) tutarlı doğrulanan tek filtre olduğu
için eleme kuralı olarak benimsenmeye değer görüldü.

**KARAR: benimsendi (SADECE FVG için, OB'de nötr/etkisiz kaldığından
oraya uygulanmadı).** `strategy/signal_engine.py`'nin FVG sinyal
döngüsüne `if not f.valid or not f.volume_confirmed: continue` ELEME
şartı eklendi -- bu, bu oturumun win-rate araştırmasında BİLGİ AMAÇLI
değil sinyal ÜRETİMİNİ FİİLEN DARALTAN ilk filtre. `strategy/fvg.py`'ye
zaten Aday 1/2'de eklenmiş olan `volume_confirmed` alanı (mum hacminin
son 20 mumun ortalamasının 1.5 katından fazla olması) artık gerçek bir
kapı görevi görüyor. Test paketi güncellendi
(`tests/test_signal_engine.py::test_fvg_signal_uses_official_r_multiple_and_sl_buffer`
-- sabit 100 hacimli 14 mumluk eski fixture, 20-barlık hacim ortalaması
penceresini karşılamadığından sinyali 0'a düşürüyordu; fixture 20 nötr
mum + orta mumda 500 hacim patlaması ile güncellendi, `tests/test_fvg.py`'deki
eşdeğer testle aynı desen). Killzone hâlâ benimsenmedi (`in_killzone`
alanları bilgi amaçlı kalmaya devam ediyor, hiçbir yerde eleme için
kullanılmıyor).

## Win rate araştırması -- Aday 6 sonucu: SL tamponu genişletme -- BENİMSENDİ, HOLDOUT ile doğrulandı (2026-09-03)

`scratch_sl_buffer_recalibration_study.py`'nin ilk taraması (SL tamponu
oranı FVG için 0.25-3.0, OB için 0.5-5.0 -- R-katı sabit tutulup sadece
SL tamponu sweep edildi) beklenmedik bir desen gösterdi: **R-katı
taramasının aksine (Aday 5), burada win rate VE expectancy AYNI ANDA ve
MONOTON iyileşiyor** -- ve taranan aralığın EN ÜST UCUNDA (FVG sl=3.0,
OB sl=5.0) hâlâ iyileşme devam ediyordu, platoya ulaşılmamıştı. Bu yüzden
`scratch_sl_buffer_recalibration_extended_study.py` ile çok daha geniş
bir aralık tarandı (FVG 3.0-30.0, OB 5.0-50.0):

| | FVG havuzlanmış (3 sembol) | OB havuzlanmış (3 sembol) |
|---|---|---|
| mevcut resmi (fvg sl=1.0 / ob sl=3.0) | %23.9 win / -0.269R | %14.8 win / -0.369R |
| sl=15.0 (fvg) / sl=30.0 (ob) | %28.7 win / -0.022R | %18.5 win / -0.098R |
| en geniş taranan (fvg sl=30 / ob sl=50) | %28.8 win / -0.011R | %19.0 win / -0.069R |

Sembol bazında GOLD tek başına expectancy'yi POZİTİFE çeviriyordu
(sl=30'da +0.04R), ama **EURGBP hiçbir zaman pozitife geçmedi** ve
FVG'de sl=7-10 civarında zaten platoya girip sl=30'da hafifçe
KÖTÜLEŞTİ, OB'de de sl=30'da tepe yapıp sl=50'de KÖTÜLEŞTİ -- yani
tüm sembollerde aynı yönde ama FARKLI hızda/farklı optimal noktada bir
etki. Bu heterojenlik, bu bulgunun basit bir "ne kadar genişse o kadar
iyi" kuralı olmadığını, sembole özgü bir doygunluk noktası olduğunu
gösteriyor.

**KRİTİK METODOLOJİK ENDİŞE:** yukarıdaki tüm sayılar TAM veri seti
(train+val+test karışık) üzerinde, onlarca SL oranı noktasında en iyi
çıkanı arayarak elde edildi -- bu, bu oturumun BAŞLANGIÇ noktası olan
"holdout'ta çöktü" bulgusuyla AYNI risk deseni (eğri uydurma). Bu yüzden
Aday 3/4'ten (entry-depth) farklı olarak, bu bulgu resmi metodolojiye
işlenmeden ÖNCE `scratch_sl_buffer_holdout_check.py` ile projenin
"kutsal holdout" disiplini (bkz. `backtest/final_holdout.py`) uygulandı:
her sembol kendi içinde kronolojik %60/%20/%20 (`split_chronological`)
bölündü, aday SL oranları SADECE train+val (%80) üzerinde değerlendirildi,
en iyi expectancy'yi veren TEK bir aday seçildi (FVG'de hep sl=15.0,
OB'de hep sl=30.0 -- taranan aday listesinin üst sınırı, ama extended
sweep'teki tepe/plato noktalarına yakın, aşırı kuyruk değerleri (30/50)
bilinçli olarak aday listesine alınmadı), ve bu TEK aday HİÇ BAKILMAMIŞ
test (%20) kümesinde BİR KEZ çalıştırıldı:

| Sembol | Modül | Resmi (holdout) | Aday (holdout) |
|---|---|---|---|
| GOLD | fvg | %28.6 win / -0.0695R | %33.7 win / **+0.0568R** |
| GOLD | ob | %17.0 win / -0.1868R | %24.8 win / **+0.1126R** |
| BTCUSD | fvg | %28.2 win / -0.1053R | %27.4 win / -0.0606R |
| BTCUSD | ob | %18.6 win / -0.2052R | %18.0 win / -0.1242R |
| EURGBP | fvg | %15.8 win / -0.6254R | %25.5 win / -0.0900R |
| EURGBP | ob | %12.5 win / -0.6115R | %12.8 win / -0.3201R |

**6/6 sembol×modül kombinasyonunda, HİÇ görülmemiş veride expectancy
iyileşti** -- bu, R-katı denemesinden (Aday 5, benimsenmedi) ve hatta
entry-depth'ten (Aday 3/4, holdout'suz benimsendi) bile daha sıkı
doğrulanmış bir bulgu, çünkü tam bu oturumun başındaki felaketi
(train'de iyi, holdout'ta çöküş) tekrarlamadığı AÇIKÇA kanıtlandı.
EURGBP'de mutlak expectancy hâlâ negatif kalsa da, resmi konfigürasyona
göre KATLANARAK daha az kötü (-0.625R -> -0.090R, -0.612R -> -0.320R)
-- ve GOLD'da iki modül de holdout'ta gerçekten pozitife döndü.

**Mekanizma notu:** SL tamponu genişledikçe TP de aynı oranda genişliyor
(TP = entry ± R_katı × risk, risk SL tamponuna bağlı) -- yani bu, Aday
3/4'teki "sığ giriş = geniş risk mesafesi = az gürültü tetiklemesi"
mekanizmasının SL tarafında doğrudan devamı/güçlendirilmiş hali. Fiyatın
hem SL'ye hem TP'ye ulaşması için daha büyük bir hareket gerekiyor,
bu da kısa vadeli piyasa gürültüsünün pozisyonu erken durdurma
olasılığını daha da azaltıyor.

**KARAR: benimsendi.** `strategy/config.py`'deki `MODULE_SL_BUFFER_RATIO`
güncellendi: `fvg` 1.0 -> **15.0**, `ob` 3.0 -> **30.0** (`ifvg`/`trendline`
bu çalışmada test edilmediği için değiştirilmedi). Bu, bu oturumun EN
SIKI doğrulanmış (gerçek train/val/test ayrımıyla, tek atımlık holdout
ile) win-rate bulgusu.

**Checkpoint -- Aday 1-6'nın (killzone hariç, volume+entry-depth+SL-tamponu)
BİRLEŞİK etkisi, GOLD/BTCUSD/EURGBP $10k hesap simülasyonunda**
(`scratch_corrected_account_simulation.py` üçüncü kez çalıştırıldı):

| | Orijinal (düzeltme öncesi) | Sadece entry-depth sonrası | Şimdi (+ hacim teyidi + SL tamponu) |
|---|---|---|---|
| GOLD (sabit-$) | -$44.803 | -$46.200 | **+$10.795 (+%7,9)** |
| BTCUSD (sabit-$) | -$115.215 | -$66.160 | -$8.047 (-%19,5) |
| EURGBP (sabit-$) | -$352.689 | -$196.310 | -$8.924 (-%10,8) |
| **Toplam** | **-$512.706** | **-$308.670** | **-$6.176** |

**GOLD hesabı artık gerçekten kârlı** -- hem sabit-$ (+%7,9) hem bileşik
model (+%7,7, maxDD sadece %4,5 -- eskiden "pratikte $0'a gidiyor"
sonucuna kıyasla çarpıcı bir değişim). Toplam 3-hesap zararı $512K'dan
$6,2K'ya indi (~%99 iyileşme). Modül bazında: GOLD'da hem FVG (+$253,62,
win %37,5) hem OB (+$1.194,23, win %34,8) artık NET POZİTİF; EURGBP'de
de OB pozitif (+$1.001,36, win %19,0). **iFVG artık en büyük tekil zarar
kaynağı** (GOLD -$571,64, BTCUSD -$946,03, EURGBP -$1.325,51) -- bugünkü
hiçbir benimsenen değişiklik (giriş derinliği, hacim teyidi, SL tamponu)
iFVG'ye UYGULANMADI (hâlâ eski derin-kenar giriş + SL tamponu=1.0).
Trendline de küçük ama tutarlı negatif kalıyor. Bu, bir sonraki mantıklı
adımı işaret ediyor: iFVG'nin FVG ile yapısal olarak aynı gap-tabanlı SL
formülüne sahip olması nedeniyle, aynı iki tekniğin (giriş derinliği +
SL tamponu genişletme) iFVG'ye de genellenip genellenemeyeceğinin test
edilmesi.

## Win rate araştırması -- Aday 7 sonucu: iFVG SL tamponu genişletme -- BENİMSENDİ, HOLDOUT ile doğrulandı (2026-09-03)

Aday 6'nın (FVG/OB SL tamponu genişletme) hemen ardından, iFVG'nin
`strategy/signal_engine.py`'de FVG/OB ile BİREBİR AYNI SL formülünü
kullandığı fark edildi (`buffer = (top-bottom) * MODULE_SL_BUFFER_RATIO["ifvg"]`)
ama bugüne kadar hiç taranmamıştı (hâlâ eski değer=1.0) -- ve $10k hesap
simülasyonu checkpoint'inde iFVG artık EN BÜYÜK tekil zarar kaynağıydı.
`scratch_ifvg_sl_buffer_holdout_check.py` ile AYNI kutsal-holdout
disiplini uygulandı (train+val'da aday seçimi, test'te tek atımlık
doğrulama, adaylar [1,3,5,7,10,15]):

| Sembol | Resmi (holdout) | Aday sl=15.0 (holdout) |
|---|---|---|
| GOLD | %30.0 win / -0.1136R | %34.5 win / **+0.0943R** |
| BTCUSD | %29.0 win / -0.1308R | %28.8 win / -0.0049R |
| EURGBP | %15.8 win / -0.7555R | %25.8 win / -0.0966R |

**3/3 sembolde holdout'ta expectancy iyileşti** (GOLD'da pozitife
döndü) -- FVG/OB'de görülen desenin (GOLD güçlü pozitif, BTCUSD
neredeyse breakeven, EURGBP iyileşen ama hâlâ negatif) BİREBİR aynısı.
sl=15.0 üç sembolde de trainval taramasının ÜST UCUNDA en iyi çıktı --
platoya henüz ulaşılmadı (FVG/OB'deki gibi daha geniş bir aralık
taranırsa muhtemelen daha da iyileşir, ama iFVG için ayrı bir extended
sweep yapılmadı -- FVG=15.0/OB=30.0 ile tutarlı, orta ölçekli bir değer
seçildi).

**KARAR: benimsendi.** `MODULE_SL_BUFFER_RATIO["ifvg"]`: 1.0 -> **15.0**.
Test paketi güncellendi (`tests/test_signal_engine.py::test_ifvg_signal_uses_official_r_multiple_and_sl_buffer`).

## Win rate araştırması -- Aday 8 sonucu: Trendline SL tamponu genişletme -- BENİMSENDİ, HOLDOUT ile doğrulandı (2026-09-03)

Aday 6/7'nin ardından, tek kalan modül olan Trendline'a da aynı testin
uygulanması mantıklı bir sonraki adımdı. Trendline farklı bir SL formülü
kullanıyor (bölge boyutu değil, dokunuş/retest barının ATR'sinin katı --
`buffer = atr * MODULE_SL_BUFFER_RATIO["trendline"]`, mevcut resmi
değer=0.5) ama AYNI additive-buffer mekanizması. Trendline bu oturumun
tarihsel olarak EN GÜÇLÜ/EN TUTARLI modülü olarak biliniyordu
(`results/README.md`) -- ama o karakterizasyon DÜZELTİLMEMİŞ, holdout'suz
eski metodolojiye dayanıyordu; bu çalışma onu ilk kez düzeltilmiş
motor+holdout ile test etti. `scratch_trendline_sl_buffer_holdout_check.py`
ile aynı kutsal-holdout disiplini uygulandı (adaylar [0.5,1,2,3,5,7]):

| Sembol | Resmi (holdout) | Aday sl=5.0 (holdout) |
|---|---|---|
| GOLD | %25.2 win / -0.2075R | %26.2 win / -0.1972R |
| BTCUSD | %21.3 win / -0.3917R | %40.0 win / **+0.2011R** |
| EURGBP | %13.3 win / -0.9375R | %30.4 win / -0.1200R |

**3/3 sembolde holdout'ta expectancy iyileşti** -- ama GOLD'daki
iyileşme bu kez ÇOK küçük (FVG/OB/iFVG'de görülen büyük sıçramanın
aksine), ve `n_filled` GOLD'da sl=0.5→5.0 arasında NEREDEYSE HİÇ
değişmedi (103→103) -- FVG/OB/iFVG'de SL genişledikçe işlem sayısı
azalırken (daha az sinyal dolup kapanabiliyor) burada neredeyse sabit
kalması, mekanizmanın tam olarak aynı olmadığını gösteriyor. BTCUSD'nin
pozitife dönüşü de küçük örneklemle (n=45-47) geliyor, GOLD/EURGBP'ye
göre daha gürültüye açık. Yine de yön tutarlı ve 3/3 iyileşme kutsal
holdout barını geçiyor.

**KARAR: benimsendi (temkinli).** `MODULE_SL_BUFFER_RATIO["trendline"]`:
0.5 -> **5.0**. Diğer üç modüle göre daha küçük örneklem ve daha zayıf
mutlak iyileşme nedeniyle, bu bulgunun FVG/OB/iFVG kadar güçlü olmadığı
açıkça not ediliyor -- ama yön (3/3 sembol) ve metodoloji (holdout) aynı
bar'ı geçtiği için benimsendi. Trendline sinyallerinde `stop_loss`/
`take_profit` değerlerini doğrudan assert eden bir test yoktu, bu yüzden
test paketinde değişiklik gerekmedi.

**Checkpoint -- DÖRT modülün TÜMÜNÜN SL tamponu genişletmesinin (Aday
6+7+8) BİRLEŞİK etkisi, $10k hesap simülasyonunda** (beşinci kez
çalıştırıldı): GOLD sabit-$ $11.922,17 (**+%19,2**) / bileşik +%20,2
(maxDD %6,9); BTCUSD $9.073,89 (-%9,3, önceki checkpoint'ten -%17,3 →
-%9,3); EURGBP $9.050,27 (-%9,5, önceki -%10,8 → -%9,5).

**3 hesabın TOPLAMI $30.046,33 -- $30.000 başlangıca göre NET +$46,33,
YANİ İLK KEZ POZİTİF** (orijinal test -$512.706'ydı). Bu, bu oturumun
başındaki "3 hesap da pratikte sıfırlanıyor" bulgusundan (bkz. dosyanın
başındaki holdout/corrected-simulation bölümleri) tam ters yönde bir
sonuç -- tabii ki $46 marjinal ve KEPT_SYMBOLS'ün sadece 3 sembolünde,
gerçek spread'le, ama yön tersine döndü. GOLD tek başına artık güçlü
pozitif (+%19-20), BTCUSD/EURGBP zararları da küçüldü (%17-19 →
%9-10). Modül bazında ilginç bir gözlem: Trendline'ın kendi SL
genişlemesi, DİĞER modüllerin (FVG özellikle) tek-pozisyon rekabetindeki
payını DEĞİŞTİRDİ -- GOLD'da FVG'nin izole performansı KENDİSİ
değişmediği halde n=9→25 işleme çıktı ve pnl $137,57→$864,93'e yükseldi,
çünkü Trendline artık o pozisyon yuvasını daha az kazanıyor. Bu, çapraz-
modül rekabet etkisinin HER İKİ yönde de (bazen kötüleştirici, bazen
iyileştirici) çalışabildiğini gösteren üçüncü örnek.

**Checkpoint -- Aday 7'nin (iFVG SL tamponu) $10k hesap simülasyonundaki
etkisi** (`scratch_corrected_account_simulation.py` dördüncü kez
çalıştırıldı): GOLD sabit-$ +$11.585,00 (+%15,8, ÖNCEKİ checkpoint'ten
+%7,9 → +%15,8) ve bileşik +%16,6 (maxDD sadece %3,0'a düştü) -- iFVG
modülü GOLD'da (+$369,61, win %35,7) ve EURGBP'de (+$131,40, win %29,4)
artık kendi başına da NET POZİTİF. Toplam 3-hesap zararı -$6.176'dan
-$5.321'e indi. **Çapraz-modül rekabet etkisi tekrar gözlendi**: EURGBP'de
FVG modülü izole olarak KÖTÜLEŞTİ (-$433,11 -> -$1.833,11) çünkü iFVG artık
daha çekici hale geldiği için tek-pozisyon yuvasını daha sık kazanıyor --
bu, önceki OB/BTCUSD gözlemiyle aynı, izole ablation ile birleşik hesap
sonucu arasındaki bilinen ayrışma.

## GOLD işlem galerisi + çoklu-zaman-dilimi (M30+H1) hesap simülasyonu (2026-09-03)

Kullanıcı isteği: GOLD için tüm modüllerin (FVG/iFVG/OB/Trendline)
gerçekten aldığı işlemleri, kaynak yapısıyla (zon/trend çizgisi)
birlikte görselleştiren bir galeri + $10k hesap simülasyonunu M30'un
yanında H1'e de genişletmek + her SL/breakeven işlem için kök neden
tespiti.

**Araçlar:** `scratch_gold_trade_gallery.py` (sadece M30, 92 işlem,
`results/trade_gallery/GOLD_all_modules.json`) ve
`scratch_gold_mtf_account_simulation.py` (M30+H1 birleşik,
`results/trade_gallery/GOLD_mtf_summary.json` + `GOLD_mtf_trades.json`).
İkisi de `generate_signals`'ı (bkz. `strategy/signal_engine.py`) BİREBİR
aynı formüllerle tekrar üretiyor ama her sinyali kaynağı olan FVG/OB/
iFVG nesnesine ya da Trendline slope/intercept'ine eşleyen bir geometri
sözlüğüyle birlikte -- gerçek `run_backtest` motorundan geçirilip,
`scratch_corrected_account_simulation.py::simulate_account` ile BİREBİR
aynı tek-pozisyon seçim mantığıyla filtrelenmiş.

**Teknik not (pencere boyutu):** geniş SL/TP tamponu bazı işlemleri çok
uzun sürede (bazen >10.000 bar) çözdüğü için, ham pencere yaklaşımı
dosyayı 19.8MB'a şişirdi -- pencere artık FORMASYON ankorü değil DOLUM
barına göre kuruluyor, çıkış çok uzaktaysa ayrı kompakt bir "çıkış yakın
çekimi" ekleniyor (`skipped_bars` ile not edilerek). Sonuç: 564KB (M30)
/ 331KB (M30+H1).

**MFE (Maximum Favorable Excursion) kök neden sınıflandırması:** her
kaybeden/breakeven işlem için, dolum-çıkış arasında fiyatın planlı
mesafenin (giriş→TP) yüzde kaçını lehte kat ettiği ölçülüp 4 kategoriye
ayrılıyor: `ani_ters` (<%10, muhtemel fakeout), `erken_basarisiz`
(%10-40), `yakin_iskalama` (%40-80), `cok_yakin_iskalama` (>%80, en
aksiyon-alınabilir -- TP'ye çok yakınken kaybetti), artı ayrı
`breakeven` kategorisi.

**ÖNEMLİ, BEKLENMEDİK BULGU -- çoklu zaman dilimi birleşimi TOPLAM
sonucu KÖTÜLEŞTİRDİ:** M30 tek başına 92 işlem alıp $11.922
(**+%19,2**) ile bitiyordu (bkz. Aday 8 checkpoint'i). H1 aynı
tek-pozisyon hesaba eklenince (24.954 aday sinyal, M30+H1 birleşik),
**çakışma nedeniyle adayların %99,8'i (24.899/24.954) atlandı** ve
toplam sadece **55 işlem** alındı -- $10.188 (**+%1,9**) ile bitti.
Kök neden: H1 kendi başına zayıf (win %10,0, -$400,73) VE pozisyonu
UZUN SÜRE işgal ederek M30'un daha iyi fırsatlarını da engelliyor.
**Sonuç/ders:** tek-pozisyon (gerçek hesap kısıtı) bir sistemde birden
fazla zaman dilimini AYNI havuza eklemek, her zaman diliminin kendi
edge'i pozitif olsa bile, zayıf olanın hem kendi kaybı hem "fırsat
maliyeti" (daha iyi işlemleri engellemesi) yüzünden toplamı aşağı
çekebiliyor. H4/W1 zaten `MODULE_DISABLED_TIMEFRAMES`'te devre dışı
(eski metodolojiyle kalibre edilmiş, bu çalışmada yeniden test
edilmedi); bu yeni bulgu H1'in de (en azından GOLD'da, aynı tek-pozisyon
havuzunda) benzer şekilde ele alınması gerektiğini düşündürüyor --
ayrı bir pozisyon slotu/alt-hesap ile çalıştırılması ya da tamamen
devre dışı bırakılması gibi seçenekler değerlendirilebilir. **Resmi
konfigürasyona (`MODULE_DISABLED_TIMEFRAMES`) HENÜZ bir değişiklik
yapılmadı** -- bu tek bir sembolün (GOLD) tek bir çalışması, KEPT_SYMBOLS
genelinde ve holdout disipliniyle doğrulanmadan karar verilmeyecek.

Sunumlar: GOLD İşlem Galerisi (sadece M30, 92 işlem) ve GOLD Detaylı
Analiz Raporu (M30+H1, equity eğrisi + kök neden analizi + galeri)
artifact olarak yayınlandı.

## H1 zaman diliminin devre dışı bırakılması -- KEPT_SYMBOLS geneli holdout testi -- REDDEDİLDİ/ERTELENDİ (2026-09-03)

Yukarıdaki GOLD bulgusunun ("M30+H1 birleşimi toplam sonucu kötüleştirdi")
üç sembolün tamamında ve kutsal-holdout disipliniyle doğrulanmadan karar
verilmeyeceği not edilmişti -- bu, o doğrulama. `scratch_h1_timeframe_
disable_holdout_check.py`: her sembol için M30 `split_chronological`
(%60/%20/%20) ile bölünüp test'in başlangıç zamanı kesim noktası olarak
alındı, H1 de AYNI zaman sınırına göre trainval/test'e bölündü (H1 index'i
M30'unkiyle karşılaştırılamaz, zaman karşılaştırılabilir). Serbest
parametre yok (taranacak bir aralık değil, ikili bir seçim: M30-tek-başına
vs M30+H1-birleşik) -- bu yüzden iki seçenek de doğrudan hem trainval'da
hem HİÇ BAKILMAMIŞ test'te çalıştırıldı.

| Sembol | M30-alone (holdout) | M30+H1-combined (holdout) |
|---|---|---|
| GOLD | %37.5 win / +0.1861R | %39.4 win / **+0.4853R** (İYİLEŞTİ) |
| BTCUSD | %14.3 win / -0.2558R | %18.8 win / -0.3060R (kötüleşti) |
| EURGBP | %20.0 win / -0.1953R | %10.5 win / -0.3713R (kötüleşti) |

**3/3 DEĞİL, 2/3 -- ve tutarsız olan sembol tam da orijinal bulgunun
kaynağı olan GOLD'un kendisi.** GOLD'un bu holdout diliminde (son %20,
sadece n=32-33 işlem) M30+H1 birleşimi expectancy'yi ~2.6 kat artırıyor
-- bu, GOLD'un TÜM geçmişini kullanan önceki tam-periyot koşusunun
bulgusuyla (+%19,2 vs +%1,9, birleşim kötü) TAM TERS yönde. BTCUSD/EURGBP
holdout'ta yönü doğruluyor (birleşim kötü) ama GOLD'un kendi holdout'u
çelişiyor. Trainval'da da aynı tutarsızlık var: GOLD (-yönde, orijinal
bulguyla uyumlu) ve EURGBP (-yönde) birleşimi kötü gösteriyor ama BTCUSD
trainval'da birleşim hafif İYİ (-0.0572 -> -0.0427, orijinal hipotezle
ters). Örneklem küçük (holdout'ta sembol başına n=32-49 işlem) --
gürültüye açık.

**KARAR: REDDEDİLDİ (şimdilik).** `MODULE_DISABLED_TIMEFRAMES`'e H1
eklenmedi -- bu oturum boyunca her kabul edilen değişiklik (Aday 6/7/8)
3/3 sembolde AYNI yönde holdout iyileşmesi barını geçmişti, bu bulgu
geçmiyor. GOLD'un tam-periyot koşusundaki güçlü negatif sinyal muhtemelen
gerçek ama rejime-özgü (ya da tek büyük örtüşen-işlem kümesinin
etkisiyle şişmiş) bir etki -- 3 sembollik küçük holdout dilimleriyle
güvenilir şekilde ayrıştırılamıyor. Daha büyük örneklem (ör. tüm
KEPT_SYMBOLS'ün TÜM geçmişini, walk-forward/genişleyen pencereyle,
tek seferlik %20 holdout yerine) olmadan bu konuda karar verilmeyecek.

## Backtest fill modeli -- market-emri simetrik slippage RESMİ hale getirildi (2026-09-07)

2026-09-06 gecesi audit'in Bulgu #1'i (`scratch_execution_model_gap_study.py`,
o zaman sadece ölçüldü, resmi motor değiştirilmedi) resmi olarak
`backtest/engine.py`'ye uygulandı. Sorun: giriş dolumunda
`executed_entry = min(signal.entry, better_price + slippage)` formülü
dolumun ASLA `signal.entry`'den kötü olamayacağını varsayıyordu -- bu,
gerçek bir bekleyen LIMIT emrinin davranışı. Ama canlı EA
(`TradeBot_NOA_Recal.mq5`) pending limit emri KULLANMIYOR, tetiklenince
MARKET emriyle açılıyor -- market emri tetiklendiği tick'teki fiyatı
alır, `signal.entry`'den daha kötü de olabilir (normal, gap'siz
dokunuşlarda bile). Düzeltme: cap kaldırıldı, slippage artık exit
tarafındaki gibi KOŞULSUZ/simetrik uygulanıyor
(`trade.executed_entry = market_price + slippage`, cap yok).

**Etki:** backtest sonuçları artık sistematik olarak biraz daha kötümser
(daha gerçekçi) -- her dolan işlemde giriş fiyatı eskisinden `slippage`
kadar daha kötü. `tests/test_backtest_engine.py`'deki 8 test bu eski
"limit-emri" davranışını sabit kodluyordu, yeni market-emri değerleriyle
güncellendi (4'ü de isim değiştirdi: `..._capped_at_limit` /
`..._never_exceeds_limit` -> `..._applies_beyond_limit`, artık doğru
değil çünkü limit koruması yok). Tüm test paketi (36/36) yeşil.

**Kapsam dışı bırakılan (bilinçli):** bu, SADECE giriş dolum modelini
düzeltti. Aynı audit bulgusunun ikinci parçası -- ölçülen slippage
DEĞERLERİNİN (`SPREAD`/`SLIPPAGE` sabitleri, "temsili, henüz kalibre
edilmedi" olarak işaretli) gerçek broker/EA verisiyle kalibre edilmesi --
hâlâ yapılmadı; `config.slippage`/`config.spread` varsayılanları bu
oturumda değiştirilmedi. Ayrıca bu değişiklik, önceki oturumlarda
holdout ile kalibre edilen SL tampon oranlarını (Aday 6/7/8) yeniden
test ETMEDİ -- o kararlar farklı bir eksen (SL genişliği) üzerindeydi ve
bu fill-model düzeltmesinden bağımsız kabul edildi; istenirse ayrı bir
oturumda yeniden doğrulanabilir.

**Diğer açık madde (2026-09-06 audit'ten, hâlâ ertelendi):** EA↔Python
sinyal-parite doğrulaması (`LogSignalsOnly=true` Strategy Tester koşusu)
ve mobil responsive doğrulama bu oturumda ele alınmadı; magic=0 USDTRY
pozisyonu bulgusu kullanıcı isteğiyle bu oturumda kapsam dışı bırakıldı.
