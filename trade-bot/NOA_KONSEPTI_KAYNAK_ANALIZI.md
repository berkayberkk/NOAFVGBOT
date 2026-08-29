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
