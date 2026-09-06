//+------------------------------------------------------------------+
//| TradeBot_NOA_Recal.mq5                                            |
//| FVG + iFVG + Order Block + Trendline -- 2026-09-03 yeniden         |
//| kalibre edilmis (DUZELTILMIS, causal/holdout ile dogrulanmis)      |
//| stratejinin MQL5 karsiligi. TradeBot_NOA.mq5 ve                   |
//| TradeBot_NOA_MultiSymbol.mq5'in YERINE gecer -- onlar 28 Agustos   |
//| 2026'daki lookahead/survivorship-bias bulgusundan ONCE yazildi ve  |
//| hala eski/gecersiz A+ (FVG+OB confluence) + trend filtresi +      |
//| Destek/Direnc TP mantigini calistiriyorlar (bkz. o dosyalarin      |
//| basindaki DEPRECATED notu).                                       |
//|                                                                    |
//| Kaynak-dogrusu (source of truth) HER ZAMAN Python tarafidir:       |
//|   strategy/fvg.py, strategy/ifvg.py, strategy/order_block.py,      |
//|   strategy/trendline.py, strategy/support_resistance.py,           |
//|   strategy/signal_engine.py, strategy/config.py,                   |
//|   backtest/engine.py (breakeven-stop mantigi).                     |
//| Asagidaki her fonksiyonun basinda hangi Python fonksiyonunun       |
//| birebir karsiligi oldugu belirtilmistir. Parametreler bilerek      |
//| SABIT/embedded degil input olarak birakildi (MetaTrader'da         |
//| gorunur/degistirilebilir olsun diye) ama VARSAYILANLAR             |
//| strategy/config.py ile birebir ayni.                               |
//|                                                                    |
//| MIMARI (kullanicinin onayladigi):                                  |
//| - Tek EA, sembol listesi CSV (varsayilan: KEPT_SYMBOLS = GOLD,     |
//|   BTCUSD, EURGBP).                                                 |
//| - Gercek bekleyen (pending) emir YOK -- EA sinyalleri kendi        |
//|   icinde bir "bekleyen aday" listesinde tutar, OnTimer ile (tick   |
//|   degil, cunku coklu-sembol EA'da OnTick sadece grafigin kendi     |
//|   sembolunde tetiklenir) periyodik olarak fiyat kontrol edilir,    |
//|   seviyeye dokununca ANINDA market emriyle SL/TP ekli pozisyon     |
//|   acilir. Backtest'in "suresiz bekleyen dolum" davranisina         |
//|   esdeger, broker tarafinda pending emir yigilmaz.                 |
//| - Butun sinyaller (FVG/iFVG/OB/Trendline) her sembol icin her yeni |
//|   bar kapanisinda YENIDEN hesaplanir; zaten uretilmis (signature'i |
//|   gorulmus) sinyaller tekrar eklenmez.                             |
//|                                                                    |
//| DOGRULAMA UYARISI: Bu dosya, cok sayida hassas nokta-bazli formul  |
//| (ATR/ortalama-hacim/ortalama-aralik causal serileri, Trendline'in  |
//| tek-gecisli durum makinesi, breakeven arm seviyesi) icerdigi icin  |
//| MUTLAKA (1) MetaEditor'de derlenip (2) Strategy Tester'da           |
//| LogSignalsOnly=true ile calistirilip URETILEN SINYALLERIN Python   |
//| tarafinin (scratch_dump_signals_for_ea_parity.py) urettigi         |
//| sinyallerle BIREBIR AYNI oldugu dogrulanmadan demo hesaba dahi     |
//| alinmamalidir.                                                     |
//+------------------------------------------------------------------+
#property copyright "N/O-A tabanli ozel strateji -- 2026-09-03 recal"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//--- Genel ayarlar
input string  TradedSymbolsCsv          = "GOLD,BTCUSD,EURGBP";  // strategy/config.py:KEPT_SYMBOLS
input ENUM_TIMEFRAMES TF                = PERIOD_M30;             // tum kalibrasyon M30'da yapildi
input double  RiskPercentPerTrade       = 1.0;
input double  MaxPortfolioRiskPercent   = 4.0;
input double  MaxLotCap                 = 5.0;
input int     MagicNumber               = 20260903;
input int     PollSecondsTimer          = 15;   // fiyat-dokunus/breakeven kontrolu icin poll periyodu
input int     LookbackBars              = 2000; // her yeni barda yeniden hesaplanan pencere
input bool    LogSignalsOnly            = false; // true: islem acmaz, uretilen adaylari dosyaya/loga yazar (parite testi icin)

//--- FVG parametreleri (strategy/fvg.py + strategy/config.py)
input int     ATR_Period                = 14;
input double  MinGapToATR               = 0.15;
input double  MaxGapToATR               = 2.5;
input double  MaxMiddleCandleRatio      = 3.0;
input int     VolumeConfirmPeriod       = 20;
input double  VolumeConfirmRatio        = 1.5;

//--- Order Block parametreleri (strategy/order_block.py)
input int     OB_AvgRangePeriod         = 14;
input double  OB_StrongMoveRatio        = 2.0;

//--- iFVG parametreleri (strategy/ifvg.py)
input int     ChopClusterBars           = 15;

//--- Trendline parametreleri (strategy/trendline.py + support_resistance.py)
input int     TL_SwingLookback          = 10;
input int     TL_MinTouches             = 3;
input double  TL_TouchToleranceATRRatio = 0.5;

//--- Modul basina R-kati / SL tamponu / breakeven (strategy/config.py, 2026-09-03 kalibrasyonu)
input double  R_FVG   = 1.5;
input double  R_IFVG  = 1.5;
input double  R_OB    = 3.0;
input double  R_TL    = 2.0;
input double  SLBUF_FVG  = 15.0;
input double  SLBUF_IFVG = 15.0;
input double  SLBUF_OB   = 30.0;
input double  SLBUF_TL   = 5.0;
input double  BREAKEVEN_TRIGGER_PCT = 0.5;   // sadece FVG/iFVG/OB icin (Trendline HARIC)

//--- Bekleyen/gorulmus sinyal listesi buyukluk tavanlari (pratik guvenlik, Python'da yok)
input int     MaxPendingPerSymbol = 300;
input int     MaxSeenSigPerSymbol = 3000;

//+------------------------------------------------------------------+
//| Veri yapilari                                                     |
//+------------------------------------------------------------------+
struct Candle
  {
   datetime time;
   double   open, high, low, close;
   long     tick_volume;
  };

struct FVGZoneM
  {
   int      startIdx, endIdx;
   double   top, bottom;      // top > bottom her zaman (strategy/fvg.py ile ayni kural)
   bool     bullish;
   bool     valid;
   bool     volumeConfirmed;
   datetime signalTime;       // end_index barinin zamani
  };

struct OBZoneM
  {
   int      impulseIndex;
   double   top, bottom;      // GOVDE sinirlari (fitil DAHIL DEGIL)
   bool     bullish;
   datetime signalTime;
  };

struct IFVGEventM
  {
   double   top, bottom;      // kaynak FVG'nin top/bottom'u
   bool     newDirBullish;
   int      brokenIndex;
   int      retestIndex;
   double   entry;            // (top+bottom)/2
   bool     chopCluster;
   datetime signalTime;
  };

struct TrendlineM
  {
   bool     bullish;          // true = ASCENDING (destek), false = DESCENDING (direnc)
   double   slope, intercept;
   int      validatedIndex;
   int      knownIndex;       // validatedIndex + swingLookback -- bundan ONCE hicbir olay islenmez
   bool     broken;
   int      brokenIndex;
  };

struct PendingSignal
  {
   string   module;    // "FVG","iFVG","OB","Trendline"
   bool     isBuy;
   double   entry, sl, tp;
   bool     breakevenEligible;
   datetime signalTime;
   string   sig;        // dedup imzasi
  };

struct SymbolRuntime
  {
   datetime       lastBarTime;
   PendingSignal  pending[];
   string         seenSig[];
  };

//--- Dahili durumlar (sembol basina, index symbols[] ile hizali)
string        symbols[];
SymbolRuntime runtimes[];

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);

   int n = StringSplit(TradedSymbolsCsv, ',', symbols);
   if(n <= 0)
     {
      Print("[CONFIG_ERROR] TradedSymbolsCsv bos veya parse edilemedi");
      return(INIT_FAILED);
     }

   ArrayResize(runtimes, n);
   for(int i = 0; i < n; i++)
     {
      StringTrimLeft(symbols[i]);
      StringTrimRight(symbols[i]);

      if(!SymbolSelect(symbols[i], true))
        {
         Print("[SYMBOL_SELECT_FAILED] ", symbols[i], " Market Watch'a eklenemedi");
         return(INIT_FAILED);
        }

      runtimes[i].lastBarTime = 0;
      ArrayResize(runtimes[i].pending, 0);
      ArrayResize(runtimes[i].seenSig, 0);
     }

   Print("[INIT_OK] ", n, " sembol icin TradeBot_NOA_Recal baslatildi: ", TradedSymbolsCsv,
         LogSignalsOnly ? " [LOG_ONLY MODU -- ISLEM ACILMAYACAK]" : "");
   EventSetTimer(PollSecondsTimer);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

//+------------------------------------------------------------------+
//| OnTimer -- her sembol icin: yeni bar varsa yeniden hesapla,        |
//| ardindan (her tick'te) bekleyen dolum + breakeven kontrolu         |
//+------------------------------------------------------------------+
void OnTimer()
  {
   for(int i = 0; i < ArraySize(symbols); i++)
     {
      datetime curBarTime = iTime(symbols[i], TF, 0);
      if(curBarTime != 0 && curBarTime != runtimes[i].lastBarTime)
        {
         runtimes[i].lastBarTime = curBarTime;
         EvaluateSymbol(i);
        }

      CheckPendingFills(i);
      MonitorBreakevenForSymbol(symbols[i]);
     }
  }

// EA hangi grafige eklendiyse o sembolun tick'lerinde de ayni kontrolu tetikler --
// coklu-sembol mantigi zaten OnTimer'da, bu sadece ek bir guvence katmani.
void OnTick()
  {
   OnTimer();
  }

//+------------------------------------------------------------------+
//| ORTAK CAUSAL SERILER                                              |
//+------------------------------------------------------------------+

// strategy/fvg.py:compute_atr_series -- basit (SMA) True Range ortalamasi,
// pencere BU BARI DA icerir (i-period+1..i dahil) -- Wilder/RMA DEGIL,
// MT5'in yerlesik iATR'i ile KARISTIRILMAMALI.
void ComputeATRSeries(const Candle &candles[], int period, double &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, n);
   double tr[];
   ArrayResize(tr, n);
   for(int i = 0; i < n; i++)
     {
      if(i == 0)
         tr[i] = candles[i].high - candles[i].low;
      else
        {
         double pc = candles[i - 1].close;
         double a = candles[i].high - candles[i].low;
         double b = MathAbs(candles[i].high - pc);
         double c = MathAbs(candles[i].low - pc);
         tr[i] = MathMax(a, MathMax(b, c));
        }

      out[i] = -1.0; // sentinel: henuz yeterli veri yok (Python'daki None karsiligi)
      if(i >= period - 1)
        {
         double sum = 0;
         for(int k = i - period + 1; k <= i; k++)
            sum += tr[k];
         out[i] = sum / period;
        }
     }
  }

// strategy/order_block.py:_average_range_series -- son `period` barin ortalama
// high-low araligi, KENDISI HARIC (causal, bardan ONCEKI period bar).
void ComputeAvgRangeSeries(const Candle &candles[], int period, double &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
     {
      out[i] = -1.0;
      if(i < period)
         continue;
      double sum = 0;
      for(int k = i - period; k < i; k++)
         sum += (candles[k].high - candles[k].low);
      out[i] = sum / period;
     }
  }

// strategy/fvg.py + order_block.py:_average_volume_series -- son `period` barin
// ortalama tick_volume'u, KENDISI HARIC.
void ComputeAvgVolumeSeries(const Candle &candles[], int period, double &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
     {
      out[i] = -1.0;
      if(i < period)
         continue;
      double sum = 0;
      for(int k = i - period; k < i; k++)
         sum += (double)candles[k].tick_volume;
      out[i] = sum / period;
     }
  }

// strategy/support_resistance.py:find_swing_points -- simetrik pencere (i-lb..i+lb).
// Buffer'in son `lb` bari icin swing durumu HENUZ BILINEMEZ (Python ile ayni --
// i >= n-lb icin hesaplanmiyor) -- bu, causal gecikmenin EA'da otomatik olusmasini
// saglar (canli veri zaten gelecege bakamaz).
void FindSwingPoints(const Candle &candles[], int lb, bool &highOut[], bool &lowOut[])
  {
   int n = ArraySize(candles);
   ArrayResize(highOut, n);
   ArrayResize(lowOut, n);
   ArrayInitialize(highOut, false);
   ArrayInitialize(lowOut, false);
   for(int i = lb; i < n - lb; i++)
     {
      bool isHigh = true, isLow = true;
      double hi = candles[i].high, lo = candles[i].low;
      for(int k = i - lb; k <= i + lb; k++)
        {
         if(candles[k].high > hi)
            isHigh = false;
         if(candles[k].low < lo)
            isLow = false;
        }
      highOut[i] = isHigh;
      lowOut[i] = isLow;
     }
  }

//+------------------------------------------------------------------+
//| FVG (strategy/fvg.py:detect_fvgs / _build_fvg / _apply_multi_fvg_rule)|
//+------------------------------------------------------------------+
void AddFVG(FVGZoneM &out[], int startIdx, int endIdx, double bottom, double top, bool bullish,
            double atr, double midRange, bool volConfirmed, datetime signalTime)
  {
   double gapSize = top - bottom;
   double gapToAtr = (atr > 0) ? gapSize / atr : 0;

   bool valid = true;
   if(!(gapToAtr >= MinGapToATR && gapToAtr <= MaxGapToATR))
      valid = false;

   if(valid && gapSize > 0 && midRange > gapSize * MaxMiddleCandleRatio)
      valid = false;

   int n = ArraySize(out);
   ArrayResize(out, n + 1);
   out[n].startIdx = startIdx;
   out[n].endIdx = endIdx;
   out[n].top = top;
   out[n].bottom = bottom;
   out[n].bullish = bullish;
   out[n].valid = valid;
   out[n].volumeConfirmed = volConfirmed;
   out[n].signalTime = signalTime;
  }

void ApplyMultiFVGRule(FVGZoneM &fvgs[])
  {
   int n = ArraySize(fvgs);
   for(int i = 0; i < n; i++)
     {
      if(!fvgs[i].valid)
         continue;
      for(int j = 0; j < n; j++)
        {
         if(i == j || !fvgs[j].valid || fvgs[i].bullish != fvgs[j].bullish)
            continue;
         bool closeBy = MathAbs(fvgs[i].startIdx - fvgs[j].startIdx) <= 3;
         double overlap = MathMin(fvgs[i].top, fvgs[j].top) - MathMax(fvgs[i].bottom, fvgs[j].bottom);
         if(closeBy && overlap > 0)
           {
            fvgs[i].valid = false;
            break;
           }
        }
     }
  }

void DetectFVGs(const Candle &candles[], const double &atrSeries[], const double &avgVolSeries[], FVGZoneM &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, 0);

   for(int i = 0; i < n - 2; i++)
     {
      double atr = atrSeries[i];
      if(atr <= 0)
         continue;

      double avgVolC2 = avgVolSeries[i + 1];
      bool volConfirmed = (avgVolC2 > 0) && ((double)candles[i + 1].tick_volume >= avgVolC2 * VolumeConfirmRatio);
      double midRange = candles[i + 1].high - candles[i + 1].low;

      if(candles[i + 2].low > candles[i].high)
         AddFVG(out, i, i + 2, candles[i].high, candles[i + 2].low, true, atr, midRange, volConfirmed, candles[i + 2].time);

      if(candles[i + 2].high < candles[i].low)
         AddFVG(out, i, i + 2, candles[i + 2].high, candles[i].low, false, atr, midRange, volConfirmed, candles[i + 2].time);
     }

   ApplyMultiFVGRule(out);
  }

//+------------------------------------------------------------------+
//| iFVG (strategy/ifvg.py:detect_confirmed_ifvgs)                    |
//+------------------------------------------------------------------+
void DetectIFVGs(const Candle &candles[], const FVGZoneM &fvgs[], IFVGEventM &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, 0);
   int nf = ArraySize(fvgs);

   for(int f = 0; f < nf; f++)
     {
      if(!fvgs[f].valid)
         continue;

      int brokenIndex = -1;
      bool newDirBull = false;
      for(int i = fvgs[f].endIdx + 1; i < n; i++)
        {
         if(fvgs[f].bullish && candles[i].close < fvgs[f].bottom) { brokenIndex = i; newDirBull = false; break; }
         if(!fvgs[f].bullish && candles[i].close > fvgs[f].top)   { brokenIndex = i; newDirBull = true;  break; }
        }
      if(brokenIndex == -1)
         continue;

      int retestIndex = -1;
      for(int j = brokenIndex + 1; j < n; j++)
        {
         bool touched, rejected;
         if(!newDirBull)
           {
            touched = candles[j].high >= fvgs[f].bottom;
            rejected = candles[j].close < fvgs[f].bottom;
           }
         else
           {
            touched = candles[j].low <= fvgs[f].top;
            rejected = candles[j].close > fvgs[f].top;
           }
         if(touched)
           {
            if(rejected)
               retestIndex = j;
            break;
           }
        }
      if(retestIndex == -1)
         continue;

      int m = ArraySize(out);
      ArrayResize(out, m + 1);
      out[m].top = fvgs[f].top;
      out[m].bottom = fvgs[f].bottom;
      out[m].newDirBullish = newDirBull;
      out[m].brokenIndex = brokenIndex;
      out[m].retestIndex = retestIndex;
      out[m].entry = (fvgs[f].top + fvgs[f].bottom) / 2.0;
      out[m].chopCluster = false;
      out[m].signalTime = candles[retestIndex].time;
     }

   // Chop-cluster filtresi (_mark_chop_clusters): causal -- sadece ONCEKI (brokenIndex
   // daha kucuk) ve zit yonlu, cakisan bolgeli event'ler isaretlenir.
   int ne = ArraySize(out);
   for(int e = 0; e < ne; e++)
     {
      for(int e2 = 0; e2 < ne; e2++)
        {
         if(out[e2].brokenIndex >= out[e].brokenIndex)
            continue;
         if(out[e].brokenIndex - out[e2].brokenIndex > ChopClusterBars)
            continue;
         double overlap = MathMin(out[e].top, out[e2].top) - MathMax(out[e].bottom, out[e2].bottom);
         if(overlap > 0 && out[e].newDirBullish != out[e2].newDirBullish)
           {
            out[e].chopCluster = true;
            break;
           }
        }
     }

   IFVGEventM filtered[];
   ArrayResize(filtered, 0);
   for(int e = 0; e < ne; e++)
      if(!out[e].chopCluster)
        {
         int m = ArraySize(filtered);
         ArrayResize(filtered, m + 1);
         filtered[m] = out[e];
        }
   ArrayResize(out, ArraySize(filtered));
   for(int e = 0; e < ArraySize(filtered); e++)
      out[e] = filtered[e];
  }

//+------------------------------------------------------------------+
//| Order Block (strategy/order_block.py:detect_order_blocks)         |
//| NOT: mitigated/volume_confirmed/engulfing/swept_liquidity/         |
//| htf_discount_aligned Python'da da sinyal ELEMEK icin KULLANILMIYOR |
//| -- bu port de kasitli olarak ayni davranisi tasiyor, hesaplamiyor. |
//+------------------------------------------------------------------+
void DetectOrderBlocks(const Candle &candles[], const double &avgRangeSeries[], OBZoneM &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, 0);

   for(int i = 0; i < n; i++)
     {
      double avgRange = avgRangeSeries[i];
      if(avgRange <= 0)
         continue;

      double candleRange = candles[i].high - candles[i].low;
      if(candleRange < avgRange * OB_StrongMoveRatio)
         continue;

      int impulseDir = 0; // 1=bullish, -1=bearish, 0=doji
      if(candles[i].close > candles[i].open)
         impulseDir = 1;
      else if(candles[i].close < candles[i].open)
         impulseDir = -1;
      if(impulseDir == 0)
         continue;

      int obIndex = -1;
      for(int j = i - 1; j >= 0; j--)
        {
         int d = 0;
         if(candles[j].close > candles[j].open)
            d = 1;
         else if(candles[j].close < candles[j].open)
            d = -1;
         if(d != 0 && d != impulseDir)
           {
            obIndex = j;
            break;
           }
         // d == impulseDir (ayni yon) veya d == 0 (doji) ise atla, geriye bakmaya devam
        }
      if(obIndex == -1)
         continue;

      double top = MathMax(candles[obIndex].open, candles[obIndex].close);
      double bottom = MathMin(candles[obIndex].open, candles[obIndex].close);

      int m = ArraySize(out);
      ArrayResize(out, m + 1);
      out[m].impulseIndex = i;
      out[m].top = top;
      out[m].bottom = bottom;
      out[m].bullish = (impulseDir == 1);
      out[m].signalTime = candles[i].time;
     }
  }

//+------------------------------------------------------------------+
//| Trendline (strategy/trendline.py:_detect_one_direction/detect_trendlines,|
//| detect_trendline_reversals + strategy/signal_engine.py'nin bounce/       |
//| reversal sinyal uretim mantigi)                                          |
//+------------------------------------------------------------------+
void FitLine(int i, double priceI, int j, double priceJ, double &slope, double &intercept)
  {
   slope = (priceJ - priceI) / (double)(j - i);
   intercept = priceI - slope * i;
  }

// strategy/trendline.py:_detect_one_direction -- tek gecisli durum makinesi, BIREBIR.
void DetectTrendlinesOneDirection(const Candle &candles[], const double &atrSeries[], const bool &pivotMarked[],
                                   bool useHighPrice, bool rising, TrendlineM &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, 0);

   int i = -1, j = -1;
   double slope = 0, intercept = 0;
   int touchCountSoFar = 0;
   bool hasCurLine = false;
   TrendlineM curLine = {}; // sifir-baslatildi -- hasCurLine=true olmadan asla okunmuyor, sadece derleyici uyarisini sessize alir

   for(int k = 0; k < n; k++)
     {
      if(j != -1)
        {
         double close = candles[k].close;
         double linePrice = slope * k + intercept;
         bool broke = rising ? (close < linePrice) : (close > linePrice);
         if(broke && k > j)
           {
            if(hasCurLine)
              {
               curLine.broken = true;
               curLine.brokenIndex = k;
               int m = ArraySize(out);
               ArrayResize(out, m + 1);
               out[m] = curLine;
              }
            i = -1; j = -1; touchCountSoFar = 0; hasCurLine = false;
           }
        }

      if(pivotMarked[k])
        {
         double priceK = useHighPrice ? candles[k].high : candles[k].low;
         if(i == -1)
           {
            i = k;
           }
         else if(j == -1)
           {
            double priceI = useHighPrice ? candles[i].high : candles[i].low;
            bool cond = rising ? (priceK > priceI) : (priceK < priceI);
            if(cond)
              {
               j = k;
               FitLine(i, priceI, j, priceK, slope, intercept);
               touchCountSoFar = 2;
              }
            else
               i = k; // yon uyumsuz -- yeni anchor olarak bu pivottan devam
           }
         else
           {
            double linePrice = slope * k + intercept;
            double tol = (atrSeries[k] > 0 ? atrSeries[k] : 0) * TL_TouchToleranceATRRatio;
            if(MathAbs(priceK - linePrice) <= tol)
              {
               touchCountSoFar++;
               // NOT: Python'daki Trendline.touch_count/anchor_indices burada
               // kasitli tutulmuyor -- signal_engine.py hicbir yerde bu alanlari
               // OKUMUYOR, sadece dogrulama anindaki touchCountSoFar>=TL_MinTouches
               // esigi (asagida) davranissal olarak onemli, o zaten korunuyor.
               if(!hasCurLine && touchCountSoFar >= TL_MinTouches)
                 {
                  hasCurLine = true;
                  curLine.bullish = rising;
                  curLine.slope = slope;
                  curLine.intercept = intercept;
                  curLine.validatedIndex = k;
                  curLine.knownIndex = k + TL_SwingLookback;
                  curLine.broken = false;
                  curLine.brokenIndex = -1;
                 }
              }
            else
              {
               bool better = rising ? (priceK > linePrice) : (priceK < linePrice);
               if(!hasCurLine && better)
                 {
                  j = k;
                  double priceI2 = useHighPrice ? candles[i].high : candles[i].low;
                  FitLine(i, priceI2, j, priceK, slope, intercept);
                  touchCountSoFar = 2;
                 }
              }
           }
        }
     }

   if(hasCurLine)
     {
      int m = ArraySize(out);
      ArrayResize(out, m + 1);
      out[m] = curLine;
     }
  }

void DetectTrendlines(const Candle &candles[], const double &atrSeries[], TrendlineM &out[])
  {
   bool pivotHigh[], pivotLow[];
   FindSwingPoints(candles, TL_SwingLookback, pivotHigh, pivotLow);

   TrendlineM asc[], desc[];
   DetectTrendlinesOneDirection(candles, atrSeries, pivotLow, false, true, asc);   // yukselen destek -- swing LOW ciftleri
   DetectTrendlinesOneDirection(candles, atrSeries, pivotHigh, true, false, desc); // dusen direnc -- swing HIGH ciftleri

   ArrayResize(out, 0);
   for(int a = 0; a < ArraySize(asc); a++) { int m = ArraySize(out); ArrayResize(out, m + 1); out[m] = asc[a]; }
   for(int d = 0; d < ArraySize(desc); d++) { int m = ArraySize(out); ArrayResize(out, m + 1); out[m] = desc[d]; }
  }

//+------------------------------------------------------------------+
//| SINYAL URETIMI (strategy/signal_engine.py:generate_signals birebir)|
//+------------------------------------------------------------------+
string MakeSignature(string module, datetime t, bool isBuy, double entry)
  {
   return module + "|" + IntegerToString((long)t) + "|" + (isBuy ? "B" : "S") + "|" + DoubleToString(entry, 6);
  }

bool SignatureSeen(const string &seenArr[], string sig)
  {
   int n = ArraySize(seenArr);
   for(int i = 0; i < n; i++)
      if(seenArr[i] == sig)
         return true;
   return false;
  }

void AddCandidate(int symIdx, string module, bool isBuy, double entry, double sl, double tp,
                   bool beEligible, datetime signalTime)
  {
   if(entry <= 0 || sl <= 0 || tp <= 0)
      return;
   if(!MathIsValidNumber(entry) || !MathIsValidNumber(sl) || !MathIsValidNumber(tp))
      return;

   string sig = MakeSignature(module, signalTime, isBuy, entry);
   if(SignatureSeen(runtimes[symIdx].seenSig, sig))
      return;

   int ns = ArraySize(runtimes[symIdx].seenSig);
   ArrayResize(runtimes[symIdx].seenSig, ns + 1);
   runtimes[symIdx].seenSig[ns] = sig;
   if(ns + 1 > MaxSeenSigPerSymbol)
      ArrayRemove(runtimes[symIdx].seenSig, 0, (ns + 1) - MaxSeenSigPerSymbol);

   PendingSignal p;
   p.module = module; p.isBuy = isBuy; p.entry = entry; p.sl = sl; p.tp = tp;
   p.breakevenEligible = beEligible; p.signalTime = signalTime; p.sig = sig;

   int np = ArraySize(runtimes[symIdx].pending);
   ArrayResize(runtimes[symIdx].pending, np + 1);
   runtimes[symIdx].pending[np] = p;
   if(np + 1 > MaxPendingPerSymbol)
      ArrayRemove(runtimes[symIdx].pending, 0, (np + 1) - MaxPendingPerSymbol);

   // Parite dogrulamasi icin: LogSignalsOnly modundaysa, UretilEN HER aday
   // (fiyata dokunmus olsun olmasin) ayri bir dosyaya yazilir --
   // scratch_dump_signals_for_ea_parity.py'nin JSON ciktisiyla TAM liste
   // olarak (sadece dolanlarla degil) diff'lenebilsin diye. CheckPendingFills'teki
   // LogSignalToFile ise SADECE fiyata dokunup "islem acilmis olurdu" sinyalleri
   // loglar -- ikisi birbirini tamamlayan, farkli amacli iki log.
   if(LogSignalsOnly)
      LogCandidateToFile(symbols[symIdx], p);
  }

void LogCandidateToFile(string symbol, PendingSignal &p)
  {
   int h = FileOpen("NOA_Recal_allsignals_" + symbol + ".csv", FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ';');
   if(h == INVALID_HANDLE)
      return;
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, p.module, p.isBuy ? "BUY" : "SELL", TimeToString(p.signalTime, TIME_DATE | TIME_SECONDS),
             DoubleToString(p.entry, 6), DoubleToString(p.sl, 6), DoubleToString(p.tp, 6));
   FileClose(h);
  }

void GenerateFVGSignals(int symIdx, const FVGZoneM &fvgs[])
  {
   for(int i = 0; i < ArraySize(fvgs); i++)
     {
      if(!fvgs[i].valid || !fvgs[i].volumeConfirmed)
         continue;
      bool isBull = fvgs[i].bullish;
      double entry = isBull ? fvgs[i].top : fvgs[i].bottom;
      double gapSize = fvgs[i].top - fvgs[i].bottom;
      double buffer = gapSize * SLBUF_FVG;
      double sl = isBull ? (fvgs[i].bottom - buffer) : (fvgs[i].top + buffer);
      double risk = MathAbs(entry - sl);
      if(risk <= 0)
         continue;
      double tp = isBull ? (entry + risk * R_FVG) : (entry - risk * R_FVG);
      AddCandidate(symIdx, "FVG", isBull, entry, sl, tp, true, fvgs[i].signalTime);
     }
  }

void GenerateIFVGSignals(int symIdx, const IFVGEventM &events[])
  {
   for(int i = 0; i < ArraySize(events); i++)
     {
      bool isBull = events[i].newDirBullish;
      double entry = events[i].entry;
      double gapSize = events[i].top - events[i].bottom;
      double buffer = gapSize * SLBUF_IFVG;
      double sl = isBull ? (events[i].bottom - buffer) : (events[i].top + buffer);
      double risk = MathAbs(entry - sl);
      if(risk <= 0)
         continue;
      double tp = isBull ? (entry + risk * R_IFVG) : (entry - risk * R_IFVG);
      AddCandidate(symIdx, "iFVG", isBull, entry, sl, tp, true, events[i].signalTime);
     }
  }

void GenerateOBSignals(int symIdx, const OBZoneM &obs[])
  {
   for(int i = 0; i < ArraySize(obs); i++)
     {
      bool isBull = obs[i].bullish;
      double entry = isBull ? obs[i].top : obs[i].bottom;
      double bodySize = obs[i].top - obs[i].bottom;
      double buffer = bodySize * SLBUF_OB;
      double sl = isBull ? (obs[i].bottom - buffer) : (obs[i].top + buffer);
      double risk = MathAbs(entry - sl);
      if(risk <= 0)
         continue;
      double tp = isBull ? (entry + risk * R_OB) : (entry - risk * R_OB);
      AddCandidate(symIdx, "OB", isBull, entry, sl, tp, true, obs[i].signalTime);
     }
  }

// strategy/signal_engine.py'nin Trendline blogu (siçrama + kirilim+retest), 230-245 arasi
// satirlar dahil -- reversal'da entry=retest barinin KAPANISI (cizgi fiyati DEGIL).
void GenerateTrendlineSignals(int symIdx, const Candle &candles[], const double &atrSeries[], const TrendlineM &lines[])
  {
   int n = ArraySize(candles);

   // --- Sicrama (bounce) ---
   for(int t = 0; t < ArraySize(lines); t++)
     {
      TrendlineM tl = lines[t];
      bool isBull = tl.bullish;
      int start = tl.knownIndex + 1;
      int end = tl.broken ? tl.brokenIndex : n;
      if(start < 0) start = 0;
      if(end > n) end = n;

      bool wasTouching = false;
      for(int k = start; k < end; k++)
        {
         double linePrice = tl.slope * k + tl.intercept;
         double tol = (atrSeries[k] > 0 ? atrSeries[k] : 0) * TL_TouchToleranceATRRatio;
         bool touched = isBull ? (candles[k].low <= linePrice + tol) : (candles[k].high >= linePrice - tol);

         if(touched && !wasTouching)
           {
            double touchPrice = isBull ? candles[k].low : candles[k].high;
            double buffer = (atrSeries[k] > 0 ? atrSeries[k] : 0) * SLBUF_TL;
            double entry = touchPrice;
            double sl = isBull ? (entry - buffer) : (entry + buffer);
            double risk = MathAbs(entry - sl);
            if(risk > 0)
              {
               double tp = isBull ? (entry + risk * R_TL) : (entry - risk * R_TL);
               AddCandidate(symIdx, "Trendline", isBull, entry, sl, tp, false, candles[k].time);
              }
           }
         wasTouching = touched;
        }
     }

   // --- Kirilim + retest (reversal) ---
   for(int t = 0; t < ArraySize(lines); t++)
     {
      TrendlineM tl = lines[t];
      if(!tl.broken)
         continue;
      bool isBullRev = !tl.bullish; // DESCENDING kirilip yukari -> bullish, ASCENDING kirilip asagi -> bearish
      int scanStart = MathMax(tl.brokenIndex, tl.knownIndex) + 1;

      for(int k = scanStart; k < n; k++)
        {
         double linePrice = tl.slope * k + tl.intercept;
         double tol = (atrSeries[k] > 0 ? atrSeries[k] : 0) * TL_TouchToleranceATRRatio;
         bool touched = isBullRev ? (candles[k].low <= linePrice + tol) : (candles[k].high >= linePrice - tol);
         if(!touched)
            continue;

         bool rejected = isBullRev ? (candles[k].close > linePrice) : (candles[k].close < linePrice);
         if(rejected)
           {
            double buffer = (atrSeries[k] > 0 ? atrSeries[k] : 0) * SLBUF_TL;
            double entry = candles[k].close;
            double sl = isBullRev ? (candles[k].low - buffer) : (candles[k].high + buffer);
            double risk = MathAbs(entry - sl);
            if(risk > 0)
              {
               double tp = isBullRev ? (entry + risk * R_TL) : (entry - risk * R_TL);
               AddCandidate(symIdx, "Trendline", isBullRev, entry, sl, tp, false, candles[k].time);
              }
           }
         break; // ilk temasta karar verildi -- reddetsin ya da etmesin, tarama biter
        }
     }
  }

//+------------------------------------------------------------------+
//| Sembol icin tam yeniden hesaplama (yeni bar kapanisinda cagrilir)  |
//+------------------------------------------------------------------+
void EvaluateSymbol(int symIdx)
  {
   string symbol = symbols[symIdx];
   int totalBars = iBars(symbol, TF);
   if(totalBars <= 1)
      return;

   int bars = MathMin(LookbackBars, totalBars - 1);
   int minRequired = MathMax(ATR_Period, MathMax(OB_AvgRangePeriod, MathMax(VolumeConfirmPeriod, TL_SwingLookback * 2 + TL_MinTouches))) + 10;
   if(bars < minRequired)
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   if(CopyRates(symbol, TF, 1, bars, rates) != bars)
     {
      Print("[BUFFER_ALIGNMENT_FAILED] CopyRates basarisiz/eksik: ", symbol);
      return;
     }

   Candle candles[];
   ArrayResize(candles, bars);
   for(int i = 0; i < bars; i++)
     {
      candles[i].time = rates[i].time;
      candles[i].open = rates[i].open;
      candles[i].high = rates[i].high;
      candles[i].low = rates[i].low;
      candles[i].close = rates[i].close;
      candles[i].tick_volume = rates[i].tick_volume;
     }

   double atrSeries[], avgRangeSeries[], avgVolSeries[];
   ComputeATRSeries(candles, ATR_Period, atrSeries);
   ComputeAvgRangeSeries(candles, OB_AvgRangePeriod, avgRangeSeries);
   ComputeAvgVolumeSeries(candles, VolumeConfirmPeriod, avgVolSeries);

   FVGZoneM fvgs[];
   DetectFVGs(candles, atrSeries, avgVolSeries, fvgs);
   GenerateFVGSignals(symIdx, fvgs);

   IFVGEventM ifvgs[];
   DetectIFVGs(candles, fvgs, ifvgs);
   GenerateIFVGSignals(symIdx, ifvgs);

   OBZoneM obs[];
   DetectOrderBlocks(candles, avgRangeSeries, obs);
   GenerateOBSignals(symIdx, obs);

   TrendlineM lines[];
   DetectTrendlines(candles, atrSeries, lines);
   GenerateTrendlineSignals(symIdx, candles, atrSeries, lines);

   if(LogSignalsOnly)
      Print("[EVAL] ", symbol, " bar=", TimeToString(candles[bars-1].time),
            " FVG=", ArraySize(fvgs), " iFVG=", ArraySize(ifvgs), " OB=", ArraySize(obs),
            " TL=", ArraySize(lines), " pending=", ArraySize(runtimes[symIdx].pending));

   WritePendingSnapshot(symIdx);
  }

//+------------------------------------------------------------------+
//| Web panel icin: su an bekleyen (henuz fiyata dokunmamis) tum       |
//| adaylarin GUNCEL anlik goruntusunu dosyaya yazar -- her cagride    |
//| BASTAN yazilir (append degil), boylece dosya her zaman "su an ne   |
//| bekleniyor" sorusuna cevap verir. webapp/app.py:/api/pending bunu  |
//| okur (2026-09-04 gecesi eklendi -- panelde "canli bekleyen         |
//| sinyaller" gorunumu icin).                                        |
//+------------------------------------------------------------------+
void WritePendingSnapshot(int symIdx)
  {
   string symbol = symbols[symIdx];
   int h = FileOpen("NOA_Recal_pending_" + symbol + ".csv", FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ';');
   if(h == INVALID_HANDLE)
      return;
   int n = ArraySize(runtimes[symIdx].pending);
   for(int i = 0; i < n; i++)
     {
      PendingSignal p = runtimes[symIdx].pending[i];
      FileWrite(h, p.module, p.isBuy ? "BUY" : "SELL", DoubleToString(p.entry, 6),
                DoubleToString(p.sl, 6), DoubleToString(p.tp, 6),
                TimeToString(p.signalTime, TIME_DATE | TIME_SECONDS));
     }
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| Bekleyen adaylardan fiyata dokunani market emriyle ac (ya da       |
//| LogSignalsOnly modundaysa sadece logla)                            |
//+------------------------------------------------------------------+
void CheckPendingFills(int symIdx)
  {
   string symbol = symbols[symIdx];
   if(CheckPositionConflict(symbol))
      return;

   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
      return;

   int n = ArraySize(runtimes[symIdx].pending);
   for(int p = 0; p < n; p++)
     {
      PendingSignal sgn = runtimes[symIdx].pending[p];
      bool touched = sgn.isBuy ? (ask <= sgn.entry) : (bid >= sgn.entry);
      if(!touched)
         continue;

      // GUVENLIK KONTROLU (2026-09-04, gercek Strategy Tester kosusunda bulundu):
      // sinyaller suresiz beklediginden ("backtest'in sinirsiz bekleyen dolum"
      // davranisiyla eslesir, bkz. plan), fiyat "touched" olana kadar SL seviyesini
      // de gecmis olabilir (gap/uzun bekleme). O durumda SL, guncel fiyata gore
      // artik YANLIS TARAFTA olur -- broker "Invalid stops" (10016) ile reddeder.
      // Bu, formul hatasi DEGIL, "cok gec kalinmis" bir sinyali fark edip atlama
      // kontrolu -- boyle bir sinyal zaten gercek hayatta da SL'i coktan yemis
      // sayilir, acilmamasi dogru davranis.
      bool priceStillValid = sgn.isBuy ? (ask > sgn.sl) : (bid < sgn.sl);
      if(!priceStillValid)
        {
         ArrayRemove(runtimes[symIdx].pending, p, 1);
         WritePendingSnapshot(symIdx);
         break;
        }

      if(LogSignalsOnly)
        {
         Print("[SIGNAL_TOUCHED] ", symbol, " ", sgn.module, " ", (sgn.isBuy ? "BUY" : "SELL"),
               " entry=", sgn.entry, " sl=", sgn.sl, " tp=", sgn.tp,
               " signalTime=", TimeToString(sgn.signalTime));
         LogSignalToFile(symbol, sgn);
        }
      else
        {
         TryOpenTrade(symbol, sgn.isBuy, sgn.entry, sgn.sl, sgn.tp, sgn.module);
        }

      ArrayRemove(runtimes[symIdx].pending, p, 1);
      WritePendingSnapshot(symIdx);
      break; // bir pollde en fazla bir islem
     }
  }

void LogSignalToFile(string symbol, PendingSignal &sgn)
  {
   int h = FileOpen("NOA_Recal_signals_" + symbol + ".csv", FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ';');
   if(h == INVALID_HANDLE)
      return;
   FileSeek(h, 0, SEEK_END);
   FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS), symbol, sgn.module,
             sgn.isBuy ? "BUY" : "SELL", DoubleToString(sgn.entry, 6), DoubleToString(sgn.sl, 6),
             DoubleToString(sgn.tp, 6), TimeToString(sgn.signalTime, TIME_DATE | TIME_SECONDS));
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| Breakeven-stop monitoru (backtest/engine.py satir 122-134, 244-248)|
//| Sadece FVG/iFVG/OB icin (Trendline HARIC, comment alaninda modul   |
//| ismi TryOpenTrade'in `reason` parametresiyle saklaniyor).          |
//+------------------------------------------------------------------+
void MonitorBreakevenForSymbol(string symbol)
  {
   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
      return;
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);

   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;

      string comment = PositionGetString(POSITION_COMMENT);
      bool eligible = (comment == "FVG" || comment == "iFVG" || comment == "OB");
      if(!eligible)
         continue;

      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double curSL = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(tp <= 0)
         continue;

      bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);

      bool alreadyArmed = isBuy ? (curSL >= openPrice - point) : (curSL <= openPrice + point);
      if(alreadyArmed)
         continue;

      double armLevel = isBuy
                         ? (openPrice + BREAKEVEN_TRIGGER_PCT * (tp - openPrice))
                         : (openPrice - BREAKEVEN_TRIGGER_PCT * (openPrice - tp));

      bool reached = isBuy ? (bid >= armLevel) : (ask <= armLevel);
      if(!reached)
         continue;

      // NOT (2026-09-04, gercek Strategy Tester kosusunda bulundu): "reached"
      // dogru olsa bile piyasa kapaliyken (hafta sonu vb.) PositionModify hep
      // "Market closed" (10018) ile reddedilir -- SL entry'ye tasinana kadar
      // HER tick'te sessizce yeniden denenir (zararsiz, piyasa acilinca
      // otomatik basarili olur), bu yuzden basarisizlikta LOGLANMIYOR --
      // aksi halde kapali piyasa boyunca binlerce tekrar eden satir birikirdi.
      trade.PositionModify(ticket, openPrice, tp);
     }
  }

//+------------------------------------------------------------------+
//| Sembole gore acik pozisyon kontrolu (TradeBot_NOA_MultiSymbol.mq5  |
//| ile birebir ayni, degistirilmeden yeniden kullanildi)              |
//+------------------------------------------------------------------+
bool CheckPositionConflict(const string symbol)
  {
   ENUM_ACCOUNT_MARGIN_MODE marginMode = (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   bool isHedging = (marginMode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);

   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
        {
         if(PositionGetString(POSITION_SYMBOL) == symbol)
           {
            long posMagic = PositionGetInteger(POSITION_MAGIC);
            if(posMagic == MagicNumber)
              {
               return true;
              }
            else if(!isHedging)
              {
               Print("[FOREIGN_POSITION_NETTING_CONFLICT] Trade skipped: Foreign position (Magic ", posMagic, ") exists on Netting/Exchange account for ", symbol);
               return true;
              }
           }
        }
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Portfoy risk tavani (TradeBot_NOA_MultiSymbol.mq5 ile birebir ayni)|
//+------------------------------------------------------------------+
double CalcOpenPortfolioRiskPercent()
  {
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(balance <= 0)
      return 0.0;

   double totalRiskAmount = 0.0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;

      string posSymbol = PositionGetString(POSITION_SYMBOL);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double slPrice   = PositionGetDouble(POSITION_SL);
      double volume    = PositionGetDouble(POSITION_VOLUME);
      if(slPrice <= 0)
         continue;

      double tickValue = SymbolInfoDouble(posSymbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize  = SymbolInfoDouble(posSymbol, SYMBOL_TRADE_TICK_SIZE);
      if(tickValue <= 0 || tickSize <= 0)
         continue;

      double slDistance = MathAbs(openPrice - slPrice);
      double riskAmount = (slDistance / tickSize) * tickValue * volume;
      totalRiskAmount += riskAmount;
     }

   return (totalRiskAmount / balance) * 100.0;
  }

//+------------------------------------------------------------------+
//| Pozisyon acma -- risk yuzdesine gore lot hesabi ve guvenlik        |
//| (TradeBot_NOA_MultiSymbol.mq5 ile birebir ayni, degistirilmedi)    |
//+------------------------------------------------------------------+
void TryOpenTrade(const string symbol, bool isBuy, double entry, double sl, double tp, string reason)
  {
   if(CheckPositionConflict(symbol))
     {
      Print("[EXISTING_EA_POSITION] Trade skipped: Open position exists for ", symbol);
      return;
     }

   if(!MathIsValidNumber(entry) || !MathIsValidNumber(sl) || !MathIsValidNumber(tp))
     {
      Print("[INVALID_SL] Trade skipped: NaN/invalid entry, SL, or TP prices for ", symbol);
      return;
     }

   if(isBuy && sl >= entry)
     {
      Print("[INVALID_SL] Trade skipped: BUY SL (", sl, ") >= Entry (", entry, ") for ", symbol);
      return;
     }
   if(!isBuy && sl <= entry)
     {
      Print("[INVALID_SL] Trade skipped: SELL SL (", sl, ") <= Entry (", entry, ") for ", symbol);
      return;
     }

   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   int stopsLevelPoints = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minStopDist = stopsLevelPoints * point;
   double slDistance = MathAbs(entry - sl);

   if(slDistance <= 0 || (minStopDist > 0 && slDistance < minStopDist))
     {
      Print("[STOP_LEVEL_TOO_CLOSE] Trade skipped: SL distance (", slDistance, ") < min stops level (", minStopDist, ") for ", symbol);
      return;
     }

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount = balance * (RiskPercentPerTrade / 100.0);
   double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);

   if(tickValue <= 0 || tickSize <= 0 || !MathIsValidNumber(riskAmount) || riskAmount <= 0)
     {
      Print("[INVALID_VOLUME] Trade skipped: Invalid balance or tick parameters for ", symbol);
      return;
     }

   double currentPortfolioRiskPct = CalcOpenPortfolioRiskPercent();
   if(currentPortfolioRiskPct + RiskPercentPerTrade > MaxPortfolioRiskPercent)
     {
      Print("[PORTFOLIO_RISK_CAP] Trade skipped for ", symbol, ": mevcut portfoy riski %",
            DoubleToString(currentPortfolioRiskPct, 2), " + yeni %", DoubleToString(RiskPercentPerTrade, 2),
            " > tavan %", DoubleToString(MaxPortfolioRiskPercent, 2));
      return;
     }

   double rawLots = riskAmount / (slDistance / tickSize * tickValue);
   if(!MathIsValidNumber(rawLots) || rawLots <= 0)
     {
      Print("[INVALID_VOLUME] Trade skipped: Invalid calculated raw lot size for ", symbol);
      return;
     }

   double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

   double lots = MathFloor(rawLots / lotStep) * lotStep;

   if(lots < minLot)
     {
      Print("[INVALID_VOLUME] Trade skipped: Calculated lot (", lots, ") below broker min lot (", minLot, ") for ", symbol);
      return;
     }

   double safeMaxLot = MathMin(maxLot, MaxLotCap);
   if(lots > safeMaxLot)
     {
      Print("[MAX_LOT_GUARD] Volume capped from ", lots, " to max lot limit ", safeMaxLot, " for ", symbol);
      lots = safeMaxLot;
     }

   double price = isBuy ? SymbolInfoDouble(symbol, SYMBOL_ASK) : SymbolInfoDouble(symbol, SYMBOL_BID);
   ENUM_ORDER_TYPE orderType = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double reqMargin = 0.0;

   if(!OrderCalcMargin(orderType, symbol, lots, price, reqMargin) || !MathIsValidNumber(reqMargin) || reqMargin <= 0)
     {
      Print("[MARGIN_CALC_FAILED] Trade skipped: Could not calculate required margin for ", symbol);
      return;
     }

   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(reqMargin > freeMargin)
     {
      Print("[INSUFFICIENT_MARGIN] Trade skipped: Required margin (", reqMargin, ") > free margin (", freeMargin, ") for ", symbol);
      return;
     }

   trade.SetTypeFillingBySymbol(symbol);
   bool res = isBuy ? trade.Buy(lots, symbol, price, sl, tp, reason)
                     : trade.Sell(lots, symbol, price, sl, tp, reason);

   if(!res)
      Print("[ORDER_SEND_FAILED] Trade failed for ", symbol, ": Code=", trade.ResultRetcode(), " - ", trade.ResultComment());
   else
      Print("[TRADE_OPENED] ", symbol, " ", reason, " ", (isBuy ? "BUY" : "SELL"), " lots=", lots,
            " entry~=", price, " sl=", sl, " tp=", tp);
  }
