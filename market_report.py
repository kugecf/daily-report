import requests
import pandas as pd
import json, csv, os, traceback, time
from datetime import datetime, timezone, timedelta

# ========== 配置 ==========
SEND_KEY = os.environ.get("SERVER_CHAN_KEY")
ALERT_FILE = "alerts.json"
LOG_FILE = "market_log.csv"
MULTPL_CACHE = "multpl_cache.json"

# ========== 工具函数 ==========
def safe_float(val):
    try: return float(str(val).replace(",", "").strip())
    except: return None

def get_percentile(series, value):
    try: return round((series < value).mean() * 100, 1)
    except: return None

# ========== 数据源 1：Yahoo Finance v8 API ==========
def yahoo_ohlcv(ticker, period="10y"):
    """
    返回 dict: close, day_high, hist_high, date (最新交易日), error
    """
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        js = r.json()
        result = js["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        df = pd.DataFrame({
            "open": quote["open"], "high": quote["high"],
            "low": quote["low"], "close": quote["close"]
        }, index=pd.to_datetime(timestamps, unit="s"))
        df = df.dropna()
        if df.empty:
            raise ValueError("空数据")
        last = df.iloc[-1]
        hist_high = df["high"].max()
        return {
            "close": round(last["close"], 2),
            "day_high": round(last["high"], 2),
            "hist_high": round(hist_high, 2),
            "date": df.index[-1].strftime("%Y-%m-%d"),
            "error": None
        }
    except Exception as e:
        return {"close": None, "day_high": None, "hist_high": None, "date": None, "error": str(e)}

# ========== 数据源 2：Stooq (免费，稳定) ==========
def stooq_quote(symbol):
    """
    返回 dict: close, date, error
    支持美股格式如 spy, qqq, ^vix
    """
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&e=csv"
    try:
        r = requests.get(url, timeout=10)
        lines = r.text.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("无数据")
        # 解析第二行
        vals = lines[1].split(",")
        close = safe_float(vals[4])
        date = vals[1]  # YYYY-MM-DD
        return {"close": round(close,2) if close else None, "date": date, "error": None}
    except Exception as e:
        return {"close": None, "date": None, "error": str(e)}

# ========== 数据源 3：CoinGecko (BTC) ==========
def coingecko_btc(days="1825"):
    """
    返回 latest_price, hist_high, hist_series (收盘价序列)
    """
    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days={days}"
    headers = {"User-Agent": "Mozilla/5.0"}
    for _ in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 429:
                time.sleep(60)
                continue
            prices = [p[1] for p in r.json().get("prices", [])]
            if not prices: raise ValueError("空数据")
            ser = pd.Series(prices)
            return {
                "price": round(ser.iloc[-1], 2),
                "hist_high": round(ser.max(), 2),
                "series": ser,
                "error": None
            }
        except Exception as e:
            time.sleep(5)
    return {"price": None, "hist_high": None, "series": None, "error": "CoinGecko失败"}

# ========== 数据源 4：Binance (BTC实时价) ==========
def binance_btc_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10)
        price = float(r.json()["price"])
        return {"price": round(price, 2), "error": None}
    except Exception as e:
        return {"price": None, "error": str(e)}

# ========== 估值数据：multpl (PE / CAPE) ==========
def get_multpl_data():
    """返回 {'PE':{'val':...,'pct':...}, 'CAPE':{...}}"""
    headers = {"User-Agent": "Mozilla/5.0"}
    res = {"PE": {"val": "获取失败", "pct": None}, "CAPE": {"val": "获取失败", "pct": None}}
    urls = {
        "PE": "https://www.multpl.com/s-p-500-pe-ratio/table/by-month",
        "CAPE": "https://www.multpl.com/shiller-pe/table/by-month"
    }
    for key, url in urls.items():
        for attempt in range(3):
            try:
                tables = pd.read_html(url)
                if tables and tables[0].shape[1] >= 2:
                    vals = pd.to_numeric(tables[0].iloc[:,1].astype(str).str.replace(",",""), errors='coerce').dropna()
                    if not vals.empty:
                        latest = round(vals.iloc[0], 2)
                        res[key]["val"] = latest
                        res[key]["pct"] = get_percentile(vals, latest)
                        break
            except Exception as e:
                print(f"[{key}] multpl attempt {attempt+1}: {e}")
                time.sleep(3)
    # 缓存
    if res["PE"]["val"]=="获取失败" and res["CAPE"]["val"]=="获取失败":
        if os.path.exists(MULTPL_CACHE):
            with open(MULTPL_CACHE) as f:
                res = json.load(f)
    else:
        with open(MULTPL_CACHE, "w") as f:
            json.dump(res, f)
    return res

# ========== 推送与存储 ==========
def send_wechat(content, title="每日市场交叉验证"):
    if not SEND_KEY: return
    try:
        requests.post(f"https://sctapi.ftqq.com/{SEND_KEY}.send",
                      data={"title": title, "desp": content}, timeout=10)
    except Exception as e:
        print("推送失败:", e)

def load_alerts():
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE) as f: return json.load(f)
    return {}

def save_alerts(d):
    with open(ALERT_FILE, "w") as f: json.dump(d, f)

def save_log(date_str, data):
    fields = ["date",
              "SPY_y_close","SPY_s_close","SPY_hist_high",
              "QQQ_y_close","QQQ_s_close","QQQ_hist_high",
              "BTC_cg_price","BTC_bn_price","BTC_hist_high",
              "VIX_y_close","VIX_s_close"]
    row = {"date": date_str}
    # SPY
    row["SPY_y_close"] = data["SPY"]["Yahoo"]["close"]
    row["SPY_s_close"] = data["SPY"]["Stooq"]["close"]
    row["SPY_hist_high"] = data["SPY"]["Yahoo"]["hist_high"]
    row["QQQ_y_close"] = data["QQQ"]["Yahoo"]["close"]
    row["QQQ_s_close"] = data["QQQ"]["Stooq"]["close"]
    row["QQQ_hist_high"] = data["QQQ"]["Yahoo"]["hist_high"]
    row["BTC_cg_price"] = data["BTC"]["CoinGecko"]["price"]
    row["BTC_bn_price"] = data["BTC"]["Binance"]["price"]
    row["BTC_hist_high"] = data["BTC"]["CoinGecko"]["hist_high"]
    row["VIX_y_close"] = data["VIX"]["Yahoo"]["close"]
    row["VIX_s_close"] = data["VIX"]["Stooq"]["close"]
    write_header = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header: w.writeheader()
        w.writerow(row)

# ========== 主程序 ==========
if __name__ == "__main__":
    try:
        # 北京时间
        today_str = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=8))).strftime("%Y/%m/%d")

        # ---------- 采集数据 ----------
        data = {}

        # SPY / QQQ: Yahoo + Stooq
        for tkr, stooq_sym in [("SPY","spy"), ("QQQ","qqq")]:
            y = yahoo_ohlcv(tkr)
            s = stooq_quote(stooq_sym)
            data[tkr] = {"Yahoo": y, "Stooq": s}

        # BTC: CoinGecko + Binance
        cg = coingecko_btc("1825")
        bn = binance_btc_price()
        data["BTC"] = {"CoinGecko": cg, "Binance": bn}

        # VIX: Yahoo + Stooq
        y_vix = yahoo_ohlcv("^VIX", "5y")
        s_vix = stooq_quote("^vix")
        data["VIX"] = {"Yahoo": y_vix, "Stooq": s_vix}

        # PE/CAPE
        pe_data = get_multpl_data()

        # ---------- 生成交叉对比报告 ----------
        msg = f"**{today_str} 市场数据 · 多源交叉验证**\n"
        msg += f"（美股数据日期为前一交易日）\n\n"

        # SPY / QQQ 表格
        for name in ["SPY", "QQQ"]:
            y = data[name]["Yahoo"]
            s = data[name]["Stooq"]
            y_close = y["close"] if y["close"] else "--"
            s_close = s["close"] if s["close"] else "--"
            day_high = y["day_high"] if y["day_high"] else "--"
            hist_high = y["hist_high"] if y["hist_high"] else "--"
            ratio = round(y["close"]/y["hist_high"]*100, 1) if (y["close"] and y["hist_high"]) else "--"
            msg += f"**{name}**\n"
            msg += f"• 收盘价：Yahoo {y_close}  |  Stooq {s_close}  (日期:{y.get('date','?')})\n"
            msg += f"• 当日最高：{day_high}（仅 Yahoo）\n"
            msg += f"• 历史最高（High）：{hist_high}  →  当前/最高 {ratio}%\n\n"

        # BTC
        cg = data["BTC"]["CoinGecko"]
        bn = data["BTC"]["Binance"]
        msg += "**BTC**\n"
        msg += f"• CoinGecko: {cg['price'] or '--'}  |  Binance: {bn['price'] or '--'}\n"
        msg += f"• 历史最高（CoinGecko收盘价序列）：{cg['hist_high'] or '--'}\n\n"

        # VIX
        yv = data["VIX"]["Yahoo"]
        sv = data["VIX"]["Stooq"]
        msg += "**VIX**\n"
        msg += f"• Yahoo: {yv['close'] or '--'}  |  Stooq: {sv['close'] or '--'}  (日期:{yv.get('date','?')})\n\n"

        # PE / CAPE
        msg += "**估值指标 (multpl.com)**\n"
        pe = pe_data["PE"]
        cape = pe_data["CAPE"]
        msg += f"• PE: {pe['val']}  分位({pe['pct']}%)\n" if pe["val"]!="获取失败" else "• PE: 获取失败\n"
        msg += f"• CAPE: {cape['val']}  分位({cape['pct']}%)\n" if cape["val"]!="获取失败" else "• CAPE: 获取失败\n"

        # 差异警示
        warnings = []
        for name in ["SPY", "QQQ"]:
            y = data[name]["Yahoo"]["close"]
            s = data[name]["Stooq"]["close"]
            if y and s and abs(y-s) > 0.5:
                warnings.append(f"{name}收盘价差异 {y-s:.2f}")
        if warnings:
            msg += "\n⚠️ 数据源差异：\n" + "\n".join(warnings) + "\n"

        # 数据源链接
        msg += (
            "\n━━━━━━━━━━\n"
            "📎 数据源（点击核实）\n"
            "• Yahoo SPY：https://finance.yahoo.com/quote/SPY\n"
            "• Stooq SPY：https://stooq.com/q/?s=spy\n"
            "• CoinGecko BTC：https://www.coingecko.com/en/coins/bitcoin\n"
            "• Binance BTC：https://www.binance.com/en/trade/BTC_USDT\n"
            "• Multpl PE：https://www.multpl.com/s-p-500-pe-ratio\n"
            "• Multpl CAPE：https://www.multpl.com/shiller-pe"
        )

        # 比率提醒（沿用逻辑，使用Yahoo历史最高）
        alerts = load_alerts()
        alert_msg = ""
        for key in ["SPY", "QQQ"]:
            y = data[key]["Yahoo"]
            if y["close"] and y["hist_high"]:
                ratio = round(y["close"]/y["hist_high"]*100, 1)
                last_alert = alerts.get(key, 105)
                if ratio <= last_alert - 5:
                    alert_msg += f"⚠️ {key} 当前/历史最高 {ratio}%（跌破{last_alert-5}%）\n"
                    alerts[key] = ratio
        # BTC 可用 CoinGecko 价格与历史最高
        cg = data["BTC"]["CoinGecko"]
        if cg["price"] and cg["hist_high"]:
            btc_ratio = round(cg["price"]/cg["hist_high"]*100, 1)
            last_btc = alerts.get("BTC", 105)
            if btc_ratio <= last_btc - 5:
                alert_msg += f"⚠️ BTC 当前/历史最高 {btc_ratio}%（跌破{last_btc-5}%）\n"
                alerts["BTC"] = btc_ratio
        save_alerts(alerts)
        if alert_msg:
            send_wechat(alert_msg, title="价格比率提醒")

        send_wechat(msg)
        save_log(today_str, data)
        print("✅ 完成")
    except Exception as e:
        print("❌ 全局异常:", e)
        traceback.print_exc()
