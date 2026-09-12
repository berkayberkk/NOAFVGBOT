# Görsel İnceleme Paneli (Faz A/B) — Gözlem Notları

**Tarih:** 2026-09-11
**Durum:** Bunların HİÇBİRİ resmi olarak test edilmemiştir — hepsi gözlem/hipotez.
Hiçbiri config.py'ye yazılmadı, holdout kullanılmadı. Karar ve resmi Deney
önceliklendirmesi kullanıcıya aittir.

## Yöntem

Faz A'da kurulan `webapp/visual_review.py:build_review()` (gerçek
`strategy/` tespit motoru + `strategy/signal_engine.py:generate_signals` +
`backtest/engine.py:run_backtest` — ayrı/paralel bir mantık yok) çağrılarak
GOLD ve BTCUSD için M30/train+val sinyalleri üretildi. Tarayıcı eklentisi
bu oturumda bağlı olmadığı için panelin canvas'ı yerine
`scratch_phase_b_render.py` ile aynı veriden matplotlib PNG montajları
üretilip (`phase_b_charts/*.png`, 20 dosya) gözle incelendi. Her montaj
havuzdan (limit=500, en güncel sinyaller) ilk 16 kazanan/kaybeden/geçersiz
örneği gösterir — köşedeki "havuzda N" değeri toplam örneklem büyüklüğünü
verir. Panelin kendisi (canvas) henüz gerçek bir tarayıcıda AÇILIP TEYİT
EDİLMEDİ — bu ayrı bir doğrulama adımı olarak kalıyor.

**Bilinen sınırlama:** Panel Trendline'ın diyagonal çizgisini çizmiyor
(sadece yatay entry/SL/TP çizgileri) — bu yüzden "dokunuş açısı" gibi
geometrik sorular bu turda GÖZLEMLENEMEDİ.

## 1. Trendline (GOLD 16 kazanan+16 kaybeden / havuz 66+134; BTCUSD 16+16 / havuz 67+133)

- **Dokunuş açısı:** gözlemlenemedi (yukarıdaki sınırlama).
- **Önceki fiyat davranışı (GOLD):** kaybedenlerin en az 9/16'sında dokunuştan
  önceki ~40-80 barda net bir yön yok, dar bantta gidip geliyor (idx=107434,
  106698, 106507, 106480, 106050, 105004, 104997). Kazananların çoğunda
  (≥10/16) dokunuş öncesi net, tek yönlü bir bacak var (idx=109499, 107718,
  106701, 104311).
- **BTCUSD'de daha keskin versiyon:** kaybeden 16'nın 11'i dar/düşük
  volatiliteli bir konsolidasyonun TAM ORTASINDA tetikleniyor. Özellikle
  idx=102865/102862/102856 — aynı ~4 saat içinde, aynı fiyat bölgesinde,
  3 ayrı BUY sinyali, üçü de kaybetti (aynı çizginin art arda testi gibi
  görünüyor — olası "çoklu-dokunuş kümeleme" sorunu, iFVG'nin chop-cluster
  filtresine benzer bir mekanizma Trendline'da yok).
- **Seans saati:** kazanan/kaybeden gruplar arasında gözle görülür bir
  saat-dağılımı farkı YOK.
- **Hipotez (test edilmemiş):** "Dokunuş öncesi son 40-80 barda net bir
  yönlü hareketin YOKLUĞU (dar bant/konsolidasyon), kaybetme olasılığını
  artırıyor olabilir." Ayrıca "kısa sürede (birkaç saat içinde) aynı
  çizgiye yapılan tekrarlanan dokunuşlar" ayrı bir aday filtre konusu
  olabilir.

## 2. Order Block (GOLD 16+16 / havuz 43+130; BTCUSD 16+16 / havuz 20+149)

- **En net bulgu.** GOLD'da (dönem boyunca baskın rejim YUKARI): 16
  kaybedenin ≥13'ü SELL — güçlü, kesintisiz bir yükseliş trendinin İÇİNDE,
  trende karşı (fade) sinyaller (idx=109758, 109604, 109603, 109509,
  109468, 109334, 109333, 109286, 109228 ve devamı). 16 kazananın TAMAMI
  BUY, trendle aynı yönde.
- BTCUSD'de (dönem boyunca baskın rejim AŞAĞI, Şub-2025): TERS yönde ama
  AYNI mekanizma — 16 kaybedenin 13'ü BUY (trende karşı), 16 kazananın
  13'ü SELL (trendle aynı yönde).
- **Hipotez (test edilmemiş, güçlü destekli):** "OB modülünün zayıflığı
  (baseline ort. -0.0412R, en kötü modül), sinyalin kendi geçerlilik
  kalitesinden çok, dönemin baskın rejimine KARŞI açılan (fade)
  sinyallerin sistematik kaybından kaynaklanıyor." Bu invalid_reason
  eksikliğiyle ilgili bir "kör nokta" değil — mevcut kurallar
  (strong_move_ratio/engulfing/swept_liquidity vb.) zaten trend yönünü
  hiç hesaba katmıyor, katması gerekebilir.
- invalid_reason kavramı OB'de yok (koddan doğrulandı, `strategy/order_block.py`
  hiçbir tespiti eleyen bir `valid` alanı taşımıyor) — "gerçek OB değil
  ama invalid_reason'sız" sorusuna doğrudan cevap: mevcut kod hiçbir OB'yi
  elemiyor, bu yüzden filtre kör noktası aramak yerine YÖN/REJİM filtresi
  eksikliği daha belirgin bir aday.

## 3. FVG (GOLD 12 kazanan+7 kaybeden / havuz aynı) ve iFVG (GOLD 44+100)

- **Örneklem uyarısı:** FVG kaybeden grup sadece 7 örnek — düşük güvenilirlik,
  temkinli okunmalı (kullanıcının n<5 eşiğinin hemen üzerinde ama 15-20
  hedefinin altında).
- FVG: GOLD'da 12 kazananın TAMAMI BUY, 7 kaybedenin TAMAMI SELL — OB'de
  görülenle BİREBİR aynı rejim-hizalı/karşıtı ayrımı.
- iFVG: 100 kaybedenden incelenen 16'nın 15'i yine SELL (trende karşı),
  sadece 1 BUY — aynı örüntü.
- **invalid_reason kalite kontrolü:** FVG'de "hacim teyidi yok", "dengesiz
  FVG (orantısız büyük)", "mesafe kuralı dışında" etiketli 16 örnek tek tek
  incelendi — etiketlerle görünüm arasında bariz bir tutarsızlık
  bulunmadı, gerçek/sınırda gap formasyonları gibi duruyorlar. iFVG'de
  "chop-cluster" etiketli 16 örnek de öncesinde gerçekten zikzak/kararsız
  fiyat gösteriyor — filtre mantıklı görünüyor, bariz bir kör nokta
  gözlenmedi.

## Genel örüntü (4 modülde de tekrarlanan, en güçlü bulgu)

Tek bir modüle özgü değil: **GOLD'da SELL sinyalleri, BTCUSD'de BUY
sinyalleri — yani "dönemin baskın rejimine karşı" sinyaller 4 modülde de
(Trendline/OB/FVG/iFVG) sistematik olarak kaybediyor.** Bu, #004b/#004c/
#007'de sayısal olarak zaten doğrulanmış rejim-etkisiyle birebir örtüşüyor
(bkz. `NOA_RESEARCH_LEDGER.md`), ama bu turda ilk kez OB/FVG/iFVG
seviyesinde de GÖZLE bu kadar net görüldü. Not: bu gözlem GOLD/BTCUSD'nin
BU train+val döneminin kendi baskın trendine göre yapıldı — başka
sembollerde/dönemlerde yön değişebilir, mekanizma (rejime-karşı zayıflık)
aynı kalabilir.

## Kaynak dosyalar

- `phase_b_charts/*.png` (20 montaj dosyası, her biri 12-16 sinyal)
- `scratch_phase_b_render.py` (render script, `webapp/visual_review.py`'yi
  doğrudan çağırır)
- `webapp/visual_review.py`, `/visual-review` paneli (Faz A, canlı/talep
  üzerine kullanılabilir, henüz gerçek tarayıcıda teyit edilmedi)

## Sonraki adım için not

Kullanıcı bu gözlemlerden hangisinin resmi bir Deney (train/val/holdout +
ayna testi disipliniyle) olarak test edileceğine karar verecek. En güçlü
aday: "rejime-karşı sinyal filtresi" — ama #004c zaten BASİT bir rejim
filtresini (trend.py) TEK BAŞINA test edip REJECT etmişti. Buradaki
gözlem daha çok "OB/FVG/iFVG modülüne ÖZEL, modül bazında rejim uyumu"
şeklinde farklılaşıyor olabilir — #004c'nin sonucuyla çelişmediğinden
emin olmak için dikkatli tasarlanmalı.
