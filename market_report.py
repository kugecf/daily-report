import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import os, json, csv, traceback, time

SEND_KEY = os.environ.get("SERVER_CHAN_KEY")
ALERT_FILE = "alerts.json"
LOG_FILE = "market_log.csv"

def safe_float(s):
    try:
        return float(str(s).replace(",", "").strip())
    except:
        return None

def get_percentile(series, value):
    try:
        return round((series < value).mean() * 100, 1)
    except:
        return None

# ====== 1. Yahoo v8 API（稳定绕过限流） ======
def yahoo_ohlcv(ticker, period="10y"):
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.raise_for_status()
        js = r.json()["chart"]["result"][0]
        ts = js["timestamp"]
        q = js["indicators"]["quote"][0]
        df = pd.DataFrame({"high": q["high"], "close": q["close"]}, index=pd.to_datetime(ts, unit="s")).dropna()
        if df.empty: raise ValueError("empty")
        last = df.iloc[-1]
        return {"close": round(last["close"],2), "day_high": round(last["high"],2),
                "hist_high": round(df["high"].max(),2), "date": df.index[-1].strftime("%Y-%m-%d"), "error": None}
    except Exception as e:
        return {"close": None, "day_high": None, "hist_high": None, "date": None, "error": str(e)}

# ====== 2. BTC 免费稳定源：Coinlore（无限制） ======
def coinlore_btc():
    try:
        r = requests.get("https://api.coinlore.net/api/ticker/?id=90", timeout=10)
        data = r.json()
        if data:
            price = float(data[0]["price_usd"])
            return {"price": round(price, 2), "error": None}
    except Exception as e:
        return {"price": None, "error": str(e)}
    return {"price": None, "error": "No data"}

def coingecko_btc_historical():
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1825"
    for _ in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if r.status_code == 429:
                time.sleep(60)
                continue
            prices = [p[1] for p in r.json().get("prices", [])]
            if prices:
                ser = pd.Series(prices)
                return {"hist_high": round(ser.max(), 2), "error": None}
        except:
            time.sleep(5)
    return {"hist_high": None, "error": "Failed"}

# ====== 3. multpl PE/CAPE（直连 by-month 稳定页） ======
def fetch_multpl_table(url, label):
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt in range(3):
        try:
            tables = pd.read_html(url)
            if tables and tables[0].shape[1] >= 2:
                vals = pd.to_numeric(tables[0].iloc[:,1].astype(str).str.replace(",",""), errors='coerce').dropna()
                if not vals.empty:
                    latest = round(vals.iloc[0], 2)
                    pct = get_percentile(vals, latest)
                    print(f"[{label}] 最新={latest}, 分位={pct}%")
                    return latest, pct, vals
        except Exception as e:
            print(f"[{label}] 失败 {attempt+1}: {e}")
            time.sleep(3)
    return "获取失败", None, None

# ====== 推送与存储 ======
def send_wechat(content, title="每日市场交叉验证"):
    if not SEND_KEY: return
    requests.post(f"https://sctapi.ftqq.com/{SEND_KEY}.send", data={"title": title, "desp": content}, timeout=10)

def load_alerts():
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE) as f: return json.load(f)
    return {}

def save_alerts(d):
    with open(ALERT_FILE, "w") as f: json.dump(d, f)

if __name__ == "__main__":
    try:
        today_str = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d")
        
        # 1. 获取数据
        spy = yahoo_ohlcv("SPY")
        qqq = yahoo_ohlcv("QQQ")
        vix = yahoo_ohlcv("^VIX", "5y")
        btc_now = coinlore_btc()
        btc_hist = coingecko_btc_historical()
        pe_val, pe_pct, _ = fetch_multpl_table("https://www.multpl.com/s-p-500-pe-ratio/table/by-month", "PE")
        cape_val, cape_pct, _ = fetch_multpl_table("https://www.multpl.com/shiller-pe/table/by-month", "CAPE")

        # 2. 构建报告
        msg = f"**{today_str} 市场数据 · 多源交叉验证**\n（美股数据日期为前一交易日）\n\n"
        
        msg += f"**SPY**\n• 收盘价：Yahoo {spy['close']} (日期:{spy.get('date','?')})\n"
        msg += f"• 日内最高：{spy['day_high']}（仅 Yahoo）\n"
        msg += f"• 历史最高（Yahoo口径）：{spy['hist_high']}\n\n"

        msg += f"**QQQ**\n• 收盘价：Yahoo {qqq['close']} (日期:{qqq.get('date','?')})\n"
        msg += f"• 日内最高：{qqq['day_high']}（仅 Yahoo）\n"
        msg += f"• 历史最高（Yahoo口径）：{qqq['hist_high']}\n\n"

        msg += f"**BTC**\n• Coinlore实时价: {btc_now['price'] or '--'}\n"
        msg += f"• 历史最高（CoinGecko收盘序列）：{btc_hist['hist_high'] or '--'}\n\n"

        msg += f"**VIX**\n• Yahoo: {vix['close']} (日期:{vix.get('date','?')})\n\n"

        msg += "**估值指标 (multpl.com)**\n"
        msg += f"• PE: {pe_val} 分位({pe_pct}%)\n" if pe_val != "获取失败" else "• PE: 获取失败\n"
        msg += f"• CAPE: {cape_val} 分位({cape_pct}%)\n" if cape_val != "获取失败" else "• CAPE: 获取失败\n"

        # 数据源核实链接
        msg += (
            "\n━━━━━━━━━━\n"
            "📎 数据源 (点击核实)\n"
            "━━━━━━━━━━\n"
            "• Yahoo SPY: https://finance.yahoo.com/quote/SPY\n"
            "• Yahoo QQQ: https://finance.yahoo.com/quote/QQQ\n"
            "• Coinlore BTC: https://www.coinlore.com/coin/bitcoin\n"
            "• CoinGecko BTC History: https://www.coingecko.com/en/coins/bitcoin/historical_data\n"
            "• multpl PE: https://www.multpl.com/s-p-500-pe-ratio/table/by-month\n"
            "• multpl CAPE: https://www.multpl.com/shiller-pe/table/by-month"
        )

        send_wechat(msg)
        print("✅ 报告生成完成")
        
    except Exception as e:
        print("❌ 全局异常:", e)
        traceback.print_exc()
