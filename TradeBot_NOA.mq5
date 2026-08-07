//+------------------------------------------------------------------+
//| TradeBot_NOA.mq5                                                  |
//| FVG + Order Block + Destek/Direnc + Trend confluence stratejisi. |
//| Python tarafinda (strategy/ klasoru) kalibre edilen ayni kurallar |
//| burada MQL5 EA olarak uygulanmistir. Ilk versiyon - demo hesapta  |
//| gozlemleyip Python'daki gibi birlikte kalibre edecegiz.           |
//+------------------------------------------------------------------+
#property copyright "N/O-A tabanli ozel strateji"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//--- Genel ayarlar
input ENUM_TIMEFRAMES TF                = PERIOD_M30;
input double  RiskPercent               = 1.0;      // islem basi risk (% bakiye)
input double  MaxLotCap                 = 5.0;      // maksimum lot siniri (guvenlik kepi)
input int     MagicNumber               = 20260726;

//--- FVG parametreleri (Python: strategy/fvg.py ile birebir)
input int     ATR_Period                = 14;
input double  MinGapToATR               = 0.15;
input double  MaxGapToATR               = 2.5;
input double  MaxMiddleCandleRatio      = 3.0;

//--- Order Block parametreleri (Python: strategy/order_block.py)
input int     OB_AvgRangePeriod         = 14;
input double  OB_StrongMoveRatio        = 2.0;

//--- Destek/Direnc parametreleri (Python: strategy/support_resistance.py)
input int     SwingLookback             = 5;
input double  ToleranceATRRatio         = 0.5;
input int     MinLevelTouchCount        = 2;

//--- Trend parametreleri (Python: strategy/trend.py)
input int     EMA_Period                = 50;

//--- Dahili durumlar
int atrHandle, emaHandle;
datetime lastBarTime = 0;

//+------------------------------------------------------------------+
//| Yardimci: mum verisi tutan basit yapi (Python'daki dict'e karsilik)|
//+------------------------------------------------------------------+
struct Candle
  {
   datetime time;
   double   open, high, low, close;
  };

//+------------------------------------------------------------------+
//| FVG yapisi (Python: FVG dataclass)                                |
//+------------------------------------------------------------------+
struct FVGZone
  {
   int    startIdx, endIdx;
   double top, bottom;
   bool   bullish;
   bool   valid;
   bool   filled;
  };

//+------------------------------------------------------------------+
//| Order Block yapisi (Python: OrderBlock dataclass)                 |
//+------------------------------------------------------------------+
struct OBZone
  {
   int    idx;
   double top, bottom;
   bool   bullish;
   bool   mitigated;
  };

//+------------------------------------------------------------------+
//| Destek/Direnc seviyesi (Python: Level dataclass)                  |
//+------------------------------------------------------------------+
struct SRLevel
  {
   double price;
   bool   isResistance;
   int    touchCount;
   int    lastIdx;
  };

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   atrHandle = iATR(_Symbol, TF, ATR_Period);
   emaHandle = iMA(_Symbol, TF, EMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   trade.SetExpertMagicNumber(MagicNumber);
   if(atrHandle == INVALID_HANDLE || emaHandle == INVALID_HANDLE)
     {
      Print("Indikator handle olusturulamadi");
      return(INIT_FAILED);
     }
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| OnTick - sadece yeni mum acildiginda calisir (Python: her mumda   |
//| bir kez sinyal hesaplandigi mantigina esdeger)                    |
//+------------------------------------------------------------------+
void OnTick()
  {
   datetime curBarTime = iTime(_Symbol, TF, 0);
   if(curBarTime == lastBarTime)
      return;  // ayni mum icinde tekrar calismasin
   lastBarTime = curBarTime;

   EvaluateAndTrade();
  }

//+------------------------------------------------------------------+
//| Ana degerlendirme: veriyi cek, FVG/OB/SR/Trend hesapla, A+ ara     |
//+------------------------------------------------------------------+
void EvaluateAndTrade()
  {
   int lookback = 500;  // gecmise ne kadar bakilacagi (performans icin sinirli)
   int totalBars = iBars(_Symbol, TF);
   if(totalBars <= 1)
      return;

   int bars = MathMin(lookback, totalBars - 1);
   if(bars < ATR_Period + SwingLookback * 3)
      return;  // yeterli veri yok

   // 1. Bulk CopyRates for COMPLETED bars starting from shift 1
   MqlRates rates[];
   ArraySetAsSeries(rates, false);  // index 0 = oldest, index bars-1 = newest completed (shift 1)
   if(CopyRates(_Symbol, TF, 1, bars, rates) != bars)
     {
      Print("[BUFFER_ALIGNMENT_FAILED] CopyRates failed or incomplete for ", _Symbol);
      return;
     }

   // 2. Bulk CopyBuffer for ATR (shift 1, count bars)
   double atr[];
   ArraySetAsSeries(atr, false);
   if(CopyBuffer(atrHandle, 0, 1, bars, atr) != bars)
     {
      Print("[BUFFER_ALIGNMENT_FAILED] CopyBuffer ATR failed or incomplete for ", _Symbol);
      return;
     }

   // 3. Bulk CopyBuffer for EMA (shift 1, count bars)
   double ema[];
   ArraySetAsSeries(ema, false);
   if(CopyBuffer(emaHandle, 0, 1, bars, ema) != bars)
     {
      Print("[BUFFER_ALIGNMENT_FAILED] CopyBuffer EMA failed or incomplete for ", _Symbol);
      return;
     }

   // 4. Build Candle array from rates and verify timestamp synchronization & buffer values
   Candle candles[];
   ArrayResize(candles, bars);
   for(int i = 0; i < bars; i++)
     {
      candles[i].time  = rates[i].time;
      candles[i].open  = rates[i].open;
      candles[i].high  = rates[i].high;
      candles[i].low   = rates[i].low;
      candles[i].close = rates[i].close;

      if(!MathIsValidNumber(atr[i]) || atr[i] <= 0)
        {
         Print("[BUFFER_ALIGNMENT_FAILED] Invalid ATR value at index ", i);
         return;
        }
      if(!MathIsValidNumber(ema[i]))
        {
         Print("[BUFFER_ALIGNMENT_FAILED] Invalid EMA value at index ", i);
         return;
        }
     }

   //--- FVG tespiti
   FVGZone fvgs[];
   DetectFVGs(candles, atr, fvgs);

   //--- Order Block tespiti
   OBZone obs[];
   DetectOrderBlocks(candles, obs);

   //--- Destek/Direnc seviyeleri
   SRLevel levels[];
   BuildLevels(candles, atr, levels);

   //--- Trend (son tamamlanan mum icin)
   int lastIdx = bars - 1;
   bool trendUp, trendDown, trendStrong;
   DetectTrendAt(candles, lastIdx, ema, trendUp, trendDown, trendStrong);

   //--- A+ confluence ara: son mumda olusan gecerli FVG + gecerli OB cakisiyor mu
   for(int i = 0; i < ArraySize(fvgs); i++)
     {
      if(!fvgs[i].valid || fvgs[i].filled)
         continue;
      if(fvgs[i].endIdx < lastIdx - 2)
         continue;  // sadece guncel FVG'lere bak

      for(int j = 0; j < ArraySize(obs); j++)
        {
         if(obs[j].mitigated)
            continue;
         if(obs[j].bullish != fvgs[i].bullish)
            continue;
         if(!ZonesOverlap(fvgs[i].top, fvgs[i].bottom, obs[j].top, obs[j].bottom))
            continue;

         bool wantsUp = fvgs[i].bullish;
         if(wantsUp && trendDown)
            continue;   // tam ters trend - eleme
         if(!wantsUp && trendUp)
            continue;

         double entry = wantsUp ? MathMax(fvgs[i].bottom, obs[j].bottom) : MathMin(fvgs[i].top, obs[j].top);
         double sl    = wantsUp ? MathMin(fvgs[i].bottom, obs[j].bottom) : MathMax(fvgs[i].top, obs[j].top);

         double tp;
         if(!FindNearestLevel(levels, entry, wantsUp, lastIdx, tp))
            continue;  // uygun TP bulunamadi, Python'daki gibi bu sinyali atla

         TryOpenTrade(wantsUp, entry, sl, tp, "A+");
         return;  // bir barda tek islem yeterli
        }
     }
  }

//+------------------------------------------------------------------+
//| Iki bolgenin fiyat olarak cakisip cakismadigini kontrol eder      |
//+------------------------------------------------------------------+
bool ZonesOverlap(double top1, double bottom1, double top2, double bottom2)
  {
   return (MathMin(top1, top2) - MathMax(bottom1, bottom2)) > 0;
  }

//+------------------------------------------------------------------+
//| FVG tespiti (Python: strategy/fvg.py detect_fvgs birebir mantik)  |
//+------------------------------------------------------------------+
void DetectFVGs(const Candle &candles[], const double &atrByIdx[], FVGZone &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, 0);

   for(int i = 0; i < n - 2; i++)
     {
      double atr = atrByIdx[i];
      if(atr <= 0)
         continue;

      // Bullish FVG: 3. mumun alt fitili, 1. mumun ust fitilinin ustunde
      if(candles[i+2].low > candles[i].high)
         AddFVG(out, i, i+2, candles[i].high, candles[i+2].low, true, candles[i+1], atr);

      // Bearish FVG: 3. mumun ust fitili, 1. mumun alt fitilinin altinda
      if(candles[i+2].high < candles[i].low)
         AddFVG(out, i, i+2, candles[i+2].high, candles[i].low, false, candles[i+1], atr);
     }

   ApplyMultiFVGRule(out);
  }

void AddFVG(FVGZone &out[], int startIdx, int endIdx, double bottom, double top,
            bool bullish, const Candle &middle, double atr)
  {
   double gapSize = top - bottom;
   double gapToAtr = (atr > 0) ? gapSize / atr : 0;

   bool valid = true;
   if(!(gapToAtr >= MinGapToATR && gapToAtr <= MaxGapToATR))
      valid = false;

   if(valid)
     {
      double midRange = middle.high - middle.low;
      if(gapSize > 0 && midRange > gapSize * MaxMiddleCandleRatio)
         valid = false;
     }

   int n = ArraySize(out);
   ArrayResize(out, n + 1);
   out[n].startIdx = startIdx;
   out[n].endIdx   = endIdx;
   out[n].top      = top;
   out[n].bottom   = bottom;
   out[n].bullish  = bullish;
   out[n].valid    = valid;
   out[n].filled   = false;
  }

void ApplyMultiFVGRule(FVGZone &fvgs[])
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

//+------------------------------------------------------------------+
//| Order Block tespiti (Python: strategy/order_block.py birebir)     |
//+------------------------------------------------------------------+
void DetectOrderBlocks(const Candle &candles[], OBZone &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, 0);

   for(int i = 0; i < n; i++)
     {
      if(i < OB_AvgRangePeriod)
         continue;

      double sumRange = 0;
      for(int k = i - OB_AvgRangePeriod; k < i; k++)
         sumRange += (candles[k].high - candles[k].low);
      double avgRange = sumRange / OB_AvgRangePeriod;
      if(avgRange <= 0)
         continue;

      double candleRange = candles[i].high - candles[i].low;
      if(candleRange < avgRange * OB_StrongMoveRatio)
         continue;

      bool bullish = candles[i].close > candles[i].open;

      int m = ArraySize(out);
      ArrayResize(out, m + 1);
      out[m].idx       = i;
      out[m].top       = candles[i].high;
      out[m].bottom    = candles[i].low;
      out[m].bullish   = bullish;
      out[m].mitigated = false;

      // mitigasyon kontrolu: sonraki mumlardan biri bolgeyi tamamen gecip
      // ters yonde kapanis verdiyse gecersiz
      for(int j = i + 1; j < n; j++)
        {
         if(bullish && candles[j].close < out[m].bottom) { out[m].mitigated = true; break; }
         if(!bullish && candles[j].close > out[m].top)   { out[m].mitigated = true; break; }
        }
     }
  }

//+------------------------------------------------------------------+
//| Destek/Direnc seviyeleri (Python: strategy/support_resistance.py) |
//+------------------------------------------------------------------+
void BuildLevels(const Candle &candles[], const double &atrByIdx[], SRLevel &out[])
  {
   int n = ArraySize(candles);
   ArrayResize(out, 0);

   for(int i = SwingLookback; i < n - SwingLookback; i++)
     {
      bool isHigh = true, isLow = true;
      for(int k = i - SwingLookback; k <= i + SwingLookback; k++)
        {
         if(candles[k].high > candles[i].high) isHigh = false;
         if(candles[k].low  < candles[i].low)  isLow  = false;
        }

      double atr = atrByIdx[i];
      double tolerance = atr * ToleranceATRRatio;

      if(isHigh)
         ClusterLevel(out, candles[i].high, true, i, tolerance);
      if(isLow)
         ClusterLevel(out, candles[i].low, false, i, tolerance);
     }
  }

void ClusterLevel(SRLevel &levels[], double price, bool isResistance, int idx, double tolerance)
  {
   for(int i = 0; i < ArraySize(levels); i++)
     {
      if(levels[i].isResistance == isResistance && MathAbs(levels[i].price - price) <= tolerance)
        {
         levels[i].price = (levels[i].price * levels[i].touchCount + price) / (levels[i].touchCount + 1);
         levels[i].touchCount++;
         levels[i].lastIdx = idx;
         return;
        }
     }
   int n = ArraySize(levels);
   ArrayResize(levels, n + 1);
   levels[n].price = price;
   levels[n].isResistance = isResistance;
   levels[n].touchCount = 1;
   levels[n].lastIdx = idx;
  }

//+------------------------------------------------------------------+
//| TP: en yakin karsi yondeki guclu S/R seviyesi (Python: engine.py) |
//+------------------------------------------------------------------+
bool FindNearestLevel(const SRLevel &levels[], double entry, bool wantsUp, int signalIdx, double &result)
  {
   bool found = false;
   double bestDist = DBL_MAX;

   for(int i = 0; i < ArraySize(levels); i++)
     {
      if(levels[i].touchCount < MinLevelTouchCount) continue;
      if(levels[i].lastIdx > signalIdx) continue;  // ileri bakma yasak (Python ile ayni kural)

      if(wantsUp && levels[i].isResistance && levels[i].price > entry)
        {
         double dist = levels[i].price - entry;
         if(dist < bestDist) { bestDist = dist; result = levels[i].price; found = true; }
        }
      if(!wantsUp && !levels[i].isResistance && levels[i].price < entry)
        {
         double dist = entry - levels[i].price;
         if(dist < bestDist) { bestDist = dist; result = levels[i].price; found = true; }
        }
     }
   return found;
  }

//+------------------------------------------------------------------+
//| Trend tespiti (Python: strategy/trend.py mantiginin sadelestirmesi)|
//+------------------------------------------------------------------+
void DetectTrendAt(const Candle &candles[], int idx, const double &ema[], bool &up, bool &down, bool &strong)
  {
   up = false; down = false; strong = false;

   double highs[]; double lows[];
   ArrayResize(highs, 0); ArrayResize(lows, 0);

   for(int i = SwingLookback; i <= idx - SwingLookback; i++)
     {
      bool isHigh = true, isLow = true;
      for(int k = i - SwingLookback; k <= i + SwingLookback; k++)
        {
         if(k > idx) continue;
         if(candles[k].high > candles[i].high) isHigh = false;
         if(candles[k].low  < candles[i].low)  isLow  = false;
        }
      if(isHigh) { int n = ArraySize(highs); ArrayResize(highs, n+1); highs[n] = candles[i].high; }
      if(isLow)  { int n = ArraySize(lows);  ArrayResize(lows,  n+1); lows[n]  = candles[i].low;  }
     }

   int nh = ArraySize(highs), nl = ArraySize(lows);
   if(nh >= 2 && nl >= 2)
     {
      if(highs[nh-1] > highs[nh-2] && lows[nl-1] > lows[nl-2]) up = true;
      if(highs[nh-1] < highs[nh-2] && lows[nl-1] < lows[nl-2]) down = true;
     }

   if(idx >= 0 && idx < ArraySize(ema))
     {
      double emaVal = ema[idx];
      if(up && candles[idx].close > emaVal) strong = true;
      if(down && candles[idx].close < emaVal) strong = true;
     }
  }

//+------------------------------------------------------------------+
//| Sembol ve hesap tipine gore acik pozisyon kontrolu              |
//+------------------------------------------------------------------+
bool CheckPositionConflict()
  {
   ENUM_ACCOUNT_MARGIN_MODE marginMode = (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   bool isHedging = (marginMode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);

   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
        {
         if(PositionGetString(POSITION_SYMBOL) == _Symbol)
           {
            long posMagic = PositionGetInteger(POSITION_MAGIC);
            if(posMagic == MagicNumber)
              {
               Print("[EXISTING_EA_POSITION] Trade skipped: Open position exists for ", _Symbol, " with MagicNumber ", MagicNumber);
               return true;
              }
            else if(!isHedging)
              {
               Print("[FOREIGN_POSITION_NETTING_CONFLICT] Trade skipped: Foreign position (Magic ", posMagic, ") exists on Netting/Exchange account for ", _Symbol);
               return true;
              }
           }
        }
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Pozisyon acma - risk yuzdesine gore lot hesabi ve guvenlik       |
//+------------------------------------------------------------------+
void TryOpenTrade(bool isBuy, double entry, double sl, double tp, string reason)
  {
   if(CheckPositionConflict())
     {
      return;
     }

   if(!MathIsValidNumber(entry) || !MathIsValidNumber(sl) || !MathIsValidNumber(tp))
     {
      Print("[INVALID_SL] Trade skipped: NaN/invalid entry, SL, or TP prices");
      return;
     }

   if(isBuy && sl >= entry)
     {
      Print("[INVALID_SL] Trade skipped: BUY SL (", sl, ") >= Entry (", entry, ")");
      return;
     }
   if(!isBuy && sl <= entry)
     {
      Print("[INVALID_SL] Trade skipped: SELL SL (", sl, ") <= Entry (", entry, ")");
      return;
     }

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int stopsLevelPoints = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minStopDist = stopsLevelPoints * point;
   double slDistance = MathAbs(entry - sl);

   if(slDistance <= 0 || (minStopDist > 0 && slDistance < minStopDist))
     {
      Print("[STOP_LEVEL_TOO_CLOSE] Trade skipped: SL distance (", slDistance, ") < min stops level (", minStopDist, ")");
      return;
     }

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount = balance * (RiskPercent / 100.0);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);

   if(tickValue <= 0 || tickSize <= 0 || !MathIsValidNumber(riskAmount) || riskAmount <= 0)
     {
      Print("[INVALID_VOLUME] Trade skipped: Invalid balance or tick parameters");
      return;
     }

   double rawLots = riskAmount / (slDistance / tickSize * tickValue);
   if(!MathIsValidNumber(rawLots) || rawLots <= 0)
     {
      Print("[INVALID_VOLUME] Trade skipped: Invalid calculated raw lot size");
      return;
     }

   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   double lots = MathFloor(rawLots / lotStep) * lotStep;

   if(lots < minLot)
     {
      Print("[INVALID_VOLUME] Trade skipped: Calculated lot (", lots, ") below broker min lot (", minLot, ")");
      return;
     }

   double safeMaxLot = MathMin(maxLot, MaxLotCap);
   if(lots > safeMaxLot)
     {
      Print("[MAX_LOT_GUARD] Volume capped from ", lots, " to max lot limit ", safeMaxLot);
      lots = safeMaxLot;
     }

   double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   ENUM_ORDER_TYPE orderType = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double reqMargin = 0.0;

   if(!OrderCalcMargin(orderType, _Symbol, lots, price, reqMargin) || !MathIsValidNumber(reqMargin) || reqMargin <= 0)
     {
      Print("[MARGIN_CALC_FAILED] Trade skipped: Could not calculate required margin");
      return;
     }

   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(reqMargin > freeMargin)
     {
      Print("[INSUFFICIENT_MARGIN] Trade skipped: Required margin (", reqMargin, ") > free margin (", freeMargin, ")");
      return;
     }

   bool res = isBuy ? trade.Buy(lots, _Symbol, price, sl, tp, reason)
                    : trade.Sell(lots, _Symbol, price, sl, tp, reason);

   if(!res)
     {
      Print("[ORDER_SEND_FAILED] Trade failed: Code=", trade.ResultRetcode(), " - ", trade.ResultComment());
     }
  }
