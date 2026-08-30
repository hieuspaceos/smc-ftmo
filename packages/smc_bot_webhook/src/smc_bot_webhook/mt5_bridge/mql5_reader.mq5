//+------------------------------------------------------------------+
//|                                              mql5_reader.mq5   |
//|                  Phase 06: SMC_EXECUTION_V1 outbox reader           |
//|                                                                   |
//|  Polls <outbox>/pending/*.json every PollSeconds.                  |
//|  Validates schema + expiry + symbol + duplicate + demo account.     |
//|  Places OrderSend with magic number + comment.                      |
//|  Writes ACK JSON to <outbox>/done/<sid>.json with ticket + price.   |
//|                                                                   |
//|  NOTE: This file is REFERENCE. Compile in MetaEditor, attach to an  |
//|  EURUSD M15 chart, configure OutboxPath input to point at the       |
//|  shared folder (SMB / Syncthing / local mount).                     |
//+------------------------------------------------------------------+
#property copyright "SMC FTMO Bot"
#property version   "0.1.0"
#property description "SMC_EXECUTION_V1 outbox reader for Phase 06 file bridge"

#include <Trade\Trade.mqh>
#include <Files\File.mqh>
#include <JSON\JSON.mqh>

input string  OutboxPath    = "C:\\SMCBridge";   // shared folder visible to bot host
input int     PollSeconds   = 5;
input double  DefaultLot    = 0.01;             // test lot (FTMO Phase 1 min)
input double  MaxLot        = 0.05;             // hard cap regardless of risk_pct
input long    MagicEURUSD   = 990001;           // per-symbol magic (FTMO EA identifier)

// Persistent record of processed signal_ids (avoid duplicate execution
// on EA restart). Stored in <MQL5>\Files\SMC_processed.csv.
input string  ProcessedFile = "SMC_processed.csv";

// --- helpers --------------------------------------------------------

bool IsAlreadyProcessed(const string &sid)
{
   int fh = FileOpen(ProcessedFile, FILE_READ | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return false;
   while(!FileIsEnding(fh))
     {
      string line = FileReadString(fh);
      if(StringFind(line, sid) >= 0)
        {
         FileClose(fh);
         return true;
        }
     }
   FileClose(fh);
   return false;
}

void MarkProcessed(const string &sid)
{
   int fh = FileOpen(ProcessedFile, FILE_WRITE | FILE_READ | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   FileSeek(fh, 0, SEEK_END);
   FileWriteString(fh, sid + "\n");
   FileClose(fh);
}

bool IsExpired(const string &iso)
{
   datetime exp = StringToTime(StringSubstr(iso, 0, 19));
   return (TimeCurrent() > exp);
}

bool ValidateJSON(const string &sid, CJSONValue &jv, string &err)
{
   if(jv["schema"].ToString() != "SMC_EXECUTION_V1")
     { err = "schema mismatch"; return false; }
   if(jv["signal_id"].ToString() != sid)
     { err = "signal_id mismatch"; return false; }
   if(jv["symbol"].ToString() != "EURUSD")
     { err = "symbol not in allowlist (EURUSD only P0)"; return false; }
   if(IsExpired(jv["expires_at"].ToString()))
     { err = "expired"; return false; }
   return true;
}

bool IsDemoAccount()
{
   return ((ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE)
           == ACCOUNT_TRADE_MODE_DEMO);
}

void WriteACK(const string &sid, ulong ticket, double fillPrice,
              const string &status, const string &note)
{
   string ackPath = OutboxPath + "\\done\\" + sid + ".json";
   string body = StringFormat(
      "{\n"
      "  \"schema\": \"SMC_ACK_V1\",\n"
      "  \"signal_id\": \"%s\",\n"
      "  \"ticket\": %I64u,\n"
      "  \"fill_price\": %.5f,\n"
      "  \"status\": \"%s\",\n"
      "  \"note\": \"%s\",\n"
      "  \"ts\": \"%s\"\n"
      "}\n",
      sid, ticket, fillPrice, status, note,
      TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS));
   int fh = FileOpen(ackPath, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("SMC ACK write failed: %s (err=%d)\n", ackPath, GetLastError());
      return;
     }
   FileWriteString(fh, body);
   FileClose(fh);
   PrintFormat("SMC ACK written: %s\n", ackPath);
}

void WriteFailed(const string &sid, const string &err)
{
   string path = OutboxPath + "\\failed\\" + sid + ".json";
   string body = StringFormat(
      "{\"schema\": \"SMC_ACK_V1\", \"signal_id\": \"%s\", \"status\": \"failed\", \"note\": \"%s\", \"ts\": \"%s\"}\n",
      sid, err, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS));
   int fh = FileOpen(path, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return;
   FileWriteString(fh, body);
   FileClose(fh);
}

// --- main EA loop ----------------------------------------------------

int OnInit()
{
   PrintFormat("SMC mql5_reader v0.1.0 init — outbox=%s poll=%ds lot=%.2f magic=%I64d demo=%s\n",
              OutboxPath, PollSeconds, DefaultLot, MagicEURUSD, IsDemoAccount() ? "YES" : "NO");
   if(!IsDemoAccount())
     {
      PrintFormat("ERROR: account is NOT demo. Refusing to run.\n");
      return INIT_FAILED;
     }
   return INIT_SUCCEEDED;
}

void OnTick()
{
   // Poll every N seconds (last-poll timestamp via global).
   static datetime lastPoll = 0;
   if(TimeCurrent() - lastPoll < PollSeconds) return;
   lastPoll = TimeCurrent();

   string mask = OutboxPath + "\\pending\\*.json";
   string files[];
   int n = FileFind(mask, files);
   for(int i = 0; i < n; i++)
     {
      string path = files[i];
      int dot = StringFind(path, ".", StringReverse(path, StringLen(path) - 10));
      string sid = (dot > 0) ? StringSubstr(path, StringLen(OutboxPath) + 9, dot - StringLen(OutboxPath) - 9) : path;
      // Skip non-`.json` files (the `.tmp` part of atomic write is invisible).
      int slashPos = StringFind(sid, ".");
      string base = (slashPos > 0) ? StringSubstr(sid, 0, slashPos) : sid;

      if(IsAlreadyProcessed(base))
        {
         PrintFormat("SMC skip duplicate signal_id=%s\n", base);
         continue;
        }

      string body = FileReadString(path);
      if(StringLen(body) == 0) continue;

      CJSONValue jv;
      if(!JSONParse(body, jv))
        {
         PrintFormat("SMC JSON parse failed for %s\n", path);
         WriteFailed(base, "json_parse_error");
         continue;
        }
      string err = "";
      if(!ValidateJSON(base, jv, err))
        {
         PrintFormat("SMC validation failed for %s: %s\n", base, err);
         WriteFailed(base, err);
         continue;
        }

      // Volume: cap to MaxLot, floor to DefaultLot (FTMO min).
      double vol = jv["risk_pct"].ToDouble() * 100.0; // risk_pct (0.0055) *100 = 0.55 lots
      if(vol < DefaultLot) vol = DefaultLot;
      if(vol > MaxLot)      vol = MaxLot;

      string symbol = jv["symbol"].ToString();
      double entry  = jv["entry"].ToDouble();
      double sl     = jv["sl"].ToDouble();
      // TP: take the first TP level for simplicity.
      CJSONValue tpArr = jv["tp"];
      double tp = (tpArr.IsArray() && tpArr.Size() > 0) ? tpArr[0].ToDouble() : 0;

      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action    = (jv["side"].ToString() == "long") ? TRADE_ACTION_DEAL : TRADE_ACTION_SELL;
      req.symbol    = symbol;
      req.volume    = vol;
      req.type      = ORDER_TYPE_MARKET;
      req.sl        = sl;
      req.tp        = tp;
      req.price     = SymbolInfoDouble(symbol, SYMBOL_ASK);
      req.deviation = 10;
      req.magic     = MagicEURUSD;
      req.comment   = "SMC:" + base;
      req.type_filling = ORDER_FILLING_FOK;

      if(!OrderSend(req, res))
        {
         PrintFormat("SMC OrderSend failed for %s: retcode=%d comment=%s\n",
                     base, res.retcode, res.comment);
         WriteFailed(base, "order_send_failed:" + IntegerToString(res.retcode));
         continue;
        }
      ulong ticket = res.order;
      double fillPrice = res.price;
      PrintFormat("SMC ORDER PLACED signal_id=%s ticket=%I64u price=%.5f vol=%.2f\n",
                  base, ticket, fillPrice, vol);
      WriteACK(base, ticket, fillPrice, "acked", "OrderSend ok");
      MarkProcessed(base);
     }
}

void OnDeinit(const int reason) { Print("SMC mql5_reader deinit\n"); }
//+------------------------------------------------------------------+