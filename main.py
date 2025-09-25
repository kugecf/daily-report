import yfinance as yf
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import os

# ====== Server酱 KEY，从 GitHub Secrets 获取 ======
SEND_KEY = os.environ.get("SERVER_CHAN_KEY")

def get_percentile(series, value):
    try:
        return round((series < value).mean() * 100, 1)
    except Exception:
        return None

def fetch_yahoo_data():
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
            pct = get_percentile(hist, hist.iloc[-1])
            data[name] = (price, pct)
        except Exception:
            data[name] = ("获取失败", None)
    return data

def fetch_multpl_data():
    results = {}
    urls = {
        "PE": "https://www.multpl.com/s-p-500-pe-ratio/table",
        "CAPE": "https://www.multpl.com/shiller-pe/table"
    }
    for key, url in urls.items():
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            table = soup.find("table", {"class":"datatable"})
            history = []
            if table:
                rows = table.find_all("tr")[1:]
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        try:
                            history.append(float(cols[1].text.strip().replace(",","")))
                        except:
                            continue
            if history:
                value = round(history[0],2)
                series = pd.Series(history)
                pct = get_percentile(series, value)
                results[key] = {"val": value, "pct": pct}
            else:
                results[key] = {"val": "获取失败", "pct": None}
        except Exception:
            results[key] = {"val": "获取失败", "pct": None}
    return results

def send_wechat(content):
    url = f"https://sctapi.ftqq.com/{SEND_KEY}.send"
    try:
        requests.post(url, data={
            "title": "每日市场数据",
            "desp": content
        }, timeout=10)
    except Exception:
        print("微信推送失败")

if __name__ == "__main__":
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d")
    data = fetch_yahoo_data()
    pe_data = fetch_multpl_data()

    msg = f"**{today} 最新美股与比特币价格：**\n\n"

    # 美股
    spy_price, spy_pct = data['SPY']
    qqq_price, qqq_pct = data['QQQ']
    msg += "📈 **美股指数**\n"
    msg += f"- SPY: {spy_price if isinstance(spy_price,str) else f'{spy_price:.2f}'}" + (f" （{spy_pct:.1f}%）" if spy_pct else "") + "\n"
    msg += f"- QQQ: {qqq_price if isinstance(qqq_price,str) else f'{qqq_price:.2f}'}" + (f" （{qqq_pct:.1f}%）" if qqq_pct else "") + "\n\n"

    # 比特币
    btc_price, btc_pct = data['BTC']
    msg += "💰 **比特币**\n"
    msg += f"- BTC: {btc_price if isinstance(btc_price,str) else f'{btc_price:.2f}'}" + (f" （{btc_pct:.1f}%）" if btc_pct else "") + "\n\n"

    # VIX
    vix_price, vix_pct = data['VIX']
    msg += "🌪 **波动率指数**\n"
    msg += f"- VIX: {vix_price if isinstance(vix_price,str) else f'{vix_price:.2f}'}" + (f" （{vix_pct:.1f}%）" if vix_pct else "") + "\n\n"

    # 估值指标
    pe_val, pe_pct = pe_data['PE']["val"], pe_data['PE']["pct"]
    cape_val, cape_pct = pe_data['CAPE']["val"], pe_data['CAPE']["pct"]
    msg += "📊 **估值指标**\n"
    msg += f"- S&P500 PE: {pe_val if isinstance(pe_val,str) else f'{pe_val:.2f}'}" + (f" （{pe_pct:.1f}%）" if pe_pct else "") + "\n"
    msg += f"- S&P500 CAPE: {cape_val if isinstance(cape_val,str) else f'{cape_val:.2f}'}" + (f" （{cape_pct:.1f}%）" if cape_pct else "") + "\n\n"

    # 数据来源
    msg += "📌 **数据来源**：https://www.multpl.com/"

    # 推送
    send_wechat(msg)
    print(msg)
