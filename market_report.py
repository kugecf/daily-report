import yfinance as yf
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import os, json, csv, traceback, time

# ====== Server酱 KEY，从 GitHub Secrets 获取 ======
SEND_KEY = os.environ.get("SERVER_CHAN_KEY")

# 保存提醒状态的文件
ALERT_FILE = "alerts.json"
# 保存市场日志的文件
LOG_FILE = "market_log.csv"
# multpl 数据缓存
CACHE_FILE = "multpl_cache.json"


def get_percentile(series, value):
    try:
        return round((series < value).mean() * 100, 1)
    except Exception:
        return None


def fetch_yahoo_data():
    """获取 SPY / QQQ / BTC / VIX 历史价格、最新价格、最高价和比例"""
    data = {}
    tickers = {
        "SPY": ("SPY", "10y"),
        "QQQ": ("QQQ", "10y"),
        "BTC": ("BTC-USD", "5y"),
        "VIX": ("^VIX", "5y"),
    }
    for name, (ticker, period) in tickers.items():
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period=period)["Close"]
            if hist.empty:
                raise ValueError("empty data")
            price = round(hist.iloc[-1], 2)
            high = round(hist.max(), 2)
            ratio = round(price / high * 100, 1)
            pct = get_percentile(hist, price)
            data[name] = {"price": price, "high": high, "ratio": ratio, "pct": pct}
        except Exception as e:
            print(f"获取 {name} 数据失败：{e}")
            data[name] = {"price": "获取失败", "high": None, "ratio": None, "pct": None}
    return data


def fetch_multpl_data():
    """获取 S&P500 的 PE 和 CAPE 数据（带缓存和重试）"""
    urls = {
        "PE": "https://www.multpl.com/s-p-500-pe-ratio/table",
        "CAPE": "https://www.multpl.com/shiller-pe/table",
    }
    results = {}
    for key, url in urls.items():
        for attempt in range(3):
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                soup = BeautifulSoup(r.text, "html.parser")
                table = soup.find("table", {"class": "datatable"})
                values = []
                if table:
                    for row in table.find_all("tr")[1:]:
                        cols = row.find_all("td")
                        if len(cols) >= 2:
                            try:
                                values.append(float(cols[1].text.strip().replace(",", "")))
                            except:
                                continue
                if values:
                    value = round(values[0], 2)
                    series = pd.Series(values)
                    pct = get_percentile(series, value)
                    results[key] = {"val": value, "pct": pct}
                    break
            except Exception:
                print(f"{key} 抓取失败，重试 {attempt+1}/3")
                time.sleep(2)
        else:
            results[key] = {"val": "获取失败", "pct": None}

    # 若全部失败则读取缓存
    if all(v["val"] == "获取失败" for v in results.values()):
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                results = json.load(f)
                print("使用缓存 multpl 数据")
    else:
        with open(CACHE_FILE, "w") as f:
            json.dump(results, f)
    return results


def send_wechat(content, title="每日市场数据"):
    """推送到微信（Server酱）"""
    if not SEND_KEY:
        print("未设置 SERVER_CHAN_KEY，跳过推送")
        return
    url = f"https://sctapi.ftqq.com/{SEND_KEY}.send"
    try:
        r = requests.post(url, data={"title": title, "desp": content}, timeout=10)
        print("推送状态：", r.status_code, r.text[:200])
    except Exception as e:
        print("微信推送失败：", e)


def load_alerts():
    if os.path.exists(ALERT_FILE):
        try:
            with open(ALERT_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_alerts(alerts):
    try:
        with open(ALERT_FILE, "w") as f:
            json.dump(alerts, f)
    except Exception as e:
        print("保存 alerts 失败：", e)


def save_market_log(today, data):
    fields = ["date", "SPY_price", "SPY_high", "SPY_ratio",
              "QQQ_price", "QQQ_high", "QQQ_ratio",
              "BTC_price", "BTC_high", "BTC_ratio",
              "VIX_price"]
    row = {
        "date": today,
        "SPY_price": data["SPY"]["price"],
        "SPY_high": data["SPY"]["high"],
        "SPY_ratio": data["SPY"]["ratio"],
        "QQQ_price": data["QQQ"]["price"],
        "QQQ_high": data["QQQ"]["high"],
        "QQQ_ratio": data["QQQ"]["ratio"],
        "BTC_price": data["BTC"]["price"],
        "BTC_high": data["BTC"]["high"],
        "BTC_ratio": data["BTC"]["ratio"],
        "VIX_price": data["VIX"]["price"],
    }
    try:
        write_header = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print("写入日志失败：", e)


def format_pct(val):
    return f"（{val:.1f}%）" if val is not None else ""


if __name__ == "__main__":
    try:
        today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d")
        data = fetch_yahoo_data()
        pe_data = fetch_multpl_data()
        alerts = load_alerts()

        msg = f"**{today} 最新市场数据：**\n\n📈 **美股指数**\n"
        for idx in ["SPY", "QQQ"]:
            d = data[idx]
            msg += f"- {idx}: {d['price']} (最高 {d['high']}, 当前/最高 {d['ratio']}%) {format_pct(d['pct'])}\n"

        btc, vix = data["BTC"], data["VIX"]
        msg += f"\n💰 **比特币**\n- BTC: {btc['price']} (最高 {btc['high']}, 当前/最高 {btc['ratio']}%) {format_pct(btc['pct'])}\n"
        msg += f"\n🌪 **波动率指数**\n- VIX: {vix['price']}\n"

        msg += "\n📊 **估值指标**\n"
        msg += f"- S&P500 PE: {pe_data['PE']['val']} {format_pct(pe_data['PE']['pct'])}\n"
        msg += f"- S&P500 CAPE: {pe_data['CAPE']['val']} {format_pct(pe_data['CAPE']['pct'])}\n\n"

        # ---- 提醒逻辑修正 ----
        alert_msg = ""
        for key in ["SPY", "QQQ", "BTC"]:
            ratio = data[key]["ratio"]
            if ratio is None:
                continue
            last_alert = alerts.get(key, 105)
            if ratio <= last_alert - 5:
                alert_msg += f"⚠️ {key} 当前/最高比值跌破 {last_alert-5}%（现 {ratio:.1f}%）\n"
                alerts[key] = ratio

        save_alerts(alerts)
        if alert_msg:
            send_wechat(alert_msg, title="价格提醒")
            print("触发提醒：\n", alert_msg)

        msg += "📌 **数据来源**：Yahoo Finance / multpl.com"
        send_wechat(msg)
        save_market_log(today, data)
        print("✅ 报告生成完成")
    except Exception as e:
        print("❌ 程序异常：", e)
        print(traceback.format_exc())
