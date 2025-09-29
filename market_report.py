import yfinance as yf
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import os
import json
import csv

# ====== Server酱 KEY，从 GitHub Secrets 获取 ======
SEND_KEY = os.environ.get("SERVER_CHAN_KEY")

# 保存提醒状态的文件
ALERT_FILE = "alerts.json"
# 保存市场日志的文件
LOG_FILE = "market_log.csv"


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
            price = round(hist.iloc[-1], 2)
            high = round(hist.max(), 2)
            ratio = round(price / high * 100, 1)  # 当前价格相对最高价比例 %
            pct = get_percentile(hist, hist.iloc[-1])
            data[name] = {"price": price, "high": high, "ratio": ratio, "pct": pct}
        except Exception:
            data[name] = {"price": "获取失败", "high": None, "ratio": None, "pct": None}
    return data


def fetch_multpl_data():
    """获取 S&P500 的 PE 和 CAPE 数据"""
    results = {}
    urls = {
        "PE": "https://www.multpl.com/s-p-500-pe-ratio/table",
        "CAPE": "https://www.multpl.com/shiller-pe/table"
    }
    for key, url in urls.items():
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            table = soup.find("table", {"class": "datatable"})
            history = []
            if table:
                rows = table.find_all("tr")[1:]
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        try:
                            history.append(float(cols[1].text.strip().replace(",", "")))
                        except:
                            continue
            if history:
                value = round(history[0], 2)
                series = pd.Series(history)
                pct = get_percentile(series, value)
                results[key] = {"val": value, "pct": pct}
            else:
                results[key] = {"val": "获取失败", "pct": None}
        except Exception:
            results[key] = {"val": "获取失败", "pct": None}
    return results


def send_wechat(content):
    """推送到微信（Server酱）"""
    if not SEND_KEY:
        print("未设置 SERVER_CHAN_KEY，跳过推送")
        return
    url = f"https://sctapi.ftqq.com/{SEND_KEY}.send"
    try:
        requests.post(url, data={
            "title": "每日市场数据",
            "desp": content
        }, timeout=10)
    except Exception:
        print("微信推送失败")


def load_alerts():
    """加载上次提醒状态"""
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE, "r") as f:
            return json.load(f)
    return {}


def save_alerts(alerts):
    """保存提醒状态"""
    with open(ALERT_FILE, "w") as f:
        json.dump(alerts, f)


def save_market_log(today, data):
    """保存每日市场数据到 CSV"""
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

    write_header = not os.path.exists(LOG_FILE)

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def format_pct(val):
    """格式化百分比，如果是 None 返回空字符串"""
    return f"（{val:.1f}%）" if val is not None else ""


if __name__ == "__main__":
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d")
    data = fetch_yahoo_data()
    pe_data = fetch_multpl_data()
    alerts = load_alerts()

    msg = f"**{today} 最新市场数据：**\n\n"

    # ===== 美股 =====
    msg += "📈 **美股指数**\n"
    for idx in ["SPY", "QQQ"]:
        price, high, ratio, pct = data[idx]["price"], data[idx]["high"], data[idx]["ratio"], data[idx]["pct"]
        msg += f"- {idx}: {price if isinstance(price, str) else f'{price:.2f}'} (最高 {high if high else '-'} , 当前/最高 {ratio if ratio else '-'}%)"
        msg += f" {format_pct(pct)}\n"

    # ===== BTC =====
    btc = data["BTC"]
    msg += "\n💰 **比特币**\n"
    msg += f"- BTC: {btc['price'] if isinstance(btc['price'], str) else f'{btc['price']:.2f}'} (最高 {btc['high'] if btc['high'] else '-'} , 当前/最高 {btc['ratio'] if btc['ratio'] else '-'}%)"
    msg += f" {format_pct(btc['pct'])}\n"

    # ===== VIX =====
    vix = data["VIX"]
    msg += "\n🌪 **波动率指数**\n"
    msg += f"- VIX: {vix['price'] if isinstance(vix['price'], str) else f'{vix['price']:.2f}'}\n"

    # ===== 估值指标 =====
    pe_val, pe_pct = pe_data['PE']["val"], pe_data['PE']["pct"]
    cape_val, cape_pct = pe_data['CAPE']["val"], pe_data['CAPE']["pct"]

    msg += "\n📊 **估值指标**\n"
    msg += f"- S&P500 PE: {pe_val} {format_pct(pe_pct)}\n"
    msg += f"- S&P500 CAPE: {cape_val} {format_pct(cape_pct)}\n\n"

    # ===== 检查提醒条件 =====
    alert_msg = ""
    for key in ["SPY", "QQQ", "BTC"]:
        ratio = data[key]["ratio"]
        if not ratio:
            continue
        last_alert = alerts.get(key, 100)  # 默认100%
        while ratio <= last_alert - 5:
            alert_msg += f"⚠️ {key} 当前/最高比值跌破 {last_alert-5}%（现 {ratio:.1f}%）\n"
            last_alert -= 5
        alerts[key] = last_alert

    save_alerts(alerts)

    if alert_msg:
        send_wechat("价格提醒：\n" + alert_msg)
        print("触发提醒：\n" + alert_msg)

    # ===== 正常每日数据推送 =====
    msg += "📌 **数据来源**：https://www.multpl.com/"
    send_wechat(msg)
    print(msg)

    # ===== 保存日志 =====
    save_market_log(today, data)
