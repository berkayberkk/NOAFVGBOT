//+------------------------------------------------------------------+
//|                                     TradeBot_NOA_V2_Viewer.mq5  |
//|                 Copyright 2026, NOAFVGBOT Research Team          |
//|                   NOAFVGBOT V2 — MT5 Visual Replay Viewer        |
//+------------------------------------------------------------------+
#property copyright "NOAFVGBOT Research Team"
#property link      "https://github.com/noafvgbot"
#property version   "2.99"
#property description "MT5 Visual Replay EA for NOAFVGBOT V2 Research TradePassports."
#property description "Minimal Single-Object Visibility Test Edition."

//--- Inputs
input string   InpCsvFileName           = "v2_mt5_replay.csv"; // Replay CSV Filename
input string   InpResearchSymbol        = "XAUUSD";           // Research Symbol
input string   InpBrokerSymbol          = "GOLD";             // Broker Symbol

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("[V2VIEWER_TEST] OnInit started");
   long chart_id = ChartID();
   Print("[V2VIEWER_TEST] ChartID=", chart_id);
   Print("[V2VIEWER_TEST] Symbol=", _Symbol);
   Print("[V2VIEWER_TEST] Period=", EnumToString((ENUM_TIMEFRAMES)_Period));

   double p = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(p <= 0) p = 1800.0;
   datetime now = TimeCurrent();

   // 1. Create OBJ_HLINE
   string hline_name = "V2_VISIBILITY_TEST_HLINE";
   ResetLastError();
   bool res_hline = ObjectCreate(0, hline_name, OBJ_HLINE, 0, 0, p);
   int err_hline = GetLastError();

   if(res_hline)
   {
      ObjectSetInteger(0, hline_name, OBJPROP_COLOR, clrMagenta);
      ObjectSetInteger(0, hline_name, OBJPROP_WIDTH, 4);
      ObjectSetInteger(0, hline_name, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, hline_name, OBJPROP_BACK, false);
      ObjectSetInteger(0, hline_name, OBJPROP_HIDDEN, false);
      ObjectSetInteger(0, hline_name, OBJPROP_SELECTABLE, true);
      ObjectSetInteger(0, hline_name, OBJPROP_SELECTED, false);
      ObjectSetInteger(0, hline_name, OBJPROP_TIMEFRAMES, OBJ_ALL_PERIODS);
   }

   int find_hline = ObjectFind(0, hline_name);
   double stored_price_hline = (find_hline >= 0) ? ObjectGetDouble(0, hline_name, OBJPROP_PRICE) : 0.0;

   Print("[V2VIEWER_TEST] HLINE ObjectCreate res=", res_hline, " err=", err_hline, " ObjectFind=", find_hline, " price=", stored_price_hline, " ObjectsTotal=", ObjectsTotal(0));

   // 2. Create OBJ_TEXT
   string text_name = "V2_VISIBILITY_TEST_TEXT";
   ResetLastError();
   bool res_text = ObjectCreate(0, text_name, OBJ_TEXT, 0, now, p);
   int err_text = GetLastError();

   if(res_text)
   {
      ObjectSetString(0, text_name, OBJPROP_TEXT, "V2 OBJECT TEST");
      ObjectSetInteger(0, text_name, OBJPROP_COLOR, clrYellow);
      ObjectSetInteger(0, text_name, OBJPROP_FONTSIZE, 16);
      ObjectSetInteger(0, text_name, OBJPROP_BACK, false);
      ObjectSetInteger(0, text_name, OBJPROP_HIDDEN, false);
      ObjectSetInteger(0, text_name, OBJPROP_SELECTABLE, true);
      ObjectSetInteger(0, text_name, OBJPROP_SELECTED, false);
      ObjectSetInteger(0, text_name, OBJPROP_TIMEFRAMES, OBJ_ALL_PERIODS);
   }

   int find_text = ObjectFind(0, text_name);

   Print("[V2VIEWER_TEST] TEXT ObjectCreate res=", res_text, " err=", err_text, " ObjectFind=", find_text, " ObjectsTotal=", ObjectsTotal(0));

   ChartRedraw(0);

   Comment("NOAFVGBOT V2 — MINIMAL SINGLE-OBJECT VISIBILITY TEST\n" +
           "--------------------------------------------------------\n" +
           "ChartID: " + IntegerToString(chart_id) + "\n" +
           "HLINE Find: " + IntegerToString(find_hline) + " | Price: " + DoubleToString(stored_price_hline, 2) + "\n" +
           "TEXT Find: " + IntegerToString(find_text) + "\n" +
           "ObjectsTotal(0): " + IntegerToString(ObjectsTotal(0)) + "\n" +
           "--------------------------------------------------------\n" +
           "PHYSICAL ZERO TRADING EXECUTION");

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, "V2_VISIBILITY_TEST_");
   Comment("");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Minimal isolated visibility test mode
}
//+------------------------------------------------------------------+
