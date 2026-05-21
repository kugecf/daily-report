import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
import os, json, traceback, time

SEND_KEY = os.environ.get("SERVER_CHAN_KEY")
ALERT_FILE = "alerts.json"

# ATH threshold levels: drop % from all-time high
DROP_THRESHOLDS = [10, 15, 20, 25]


def yahoo_ohlcv(ticker, period="max"):
    """Fetch OHLCV data from Yahoo Finance v8 API."""
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.raise_for_status()
        js = r.json()["chart"]["result"][0]
        ts = js["timestamp"]
        q = js["indicators"]["quote"][0]
        df = pd.DataFrame({"close": q["close"]}, index=pd.to_datetime(ts, unit="s")).dropna()
        if df.empty:
            raise ValueError("empty data")
        last_close = round(df["close"].iloc[-1], 2)
        ath = round(df["close"].max(), 2)
        pct_of_ath = round(last_close / ath * 100, 2)
        return {
            "close": last_close,
            "ath": ath,
            "pct_of_ath": pct_of_ath,
            "date": df.index[-1].strftime("%Y-%m-%d"),
            "error": None,
        }
    except Exception as e:
        return {"close": None, "ath": None, "pct_of_ath": None, "date": None, "error": str(e)}


def send_wechat(content, title="SPY/QQQ 浠锋牸棰勮"):
    """Send alert via Server Chan (WeChat push)."""
    if not SEND_KEY:
        print("鈿?SERVER_CHAN_KEY not set, skipping notification")
        return
    try:
        requests.post(
            f"https://sctapi.ftqq.com/{SEND_KEY}.send",
            data={"title": title, "desp": content},
            timeout=10,
        )
        print("鉁?Alert sent via Server Chan")
    except Exception as e:
        print(f"鉁?Failed to send alert: {e}")


def load_alerts():
    """Load persisted ATH and triggered threshold state."""
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE) as f:
            return json.load(f)
    return {}


def save_alerts(d):
    """Save ATH and triggered threshold state."""
    with open(ALERT_FILE, "w") as f:
        json.dump(d, f, indent=2)


def check_and_alert(ticker, data, state):
    """
    Check if price drops below any threshold not yet alerted.
    Returns True if an alert was sent.
    """
    if data["error"] or data["close"] is None:
        print(f"鈿?{ticker}: data error, skipping alert check")
        return False

    ticker_state = state.get(ticker, {"ath": data["ath"], "triggered": []})

    # Update ATH if new high is reached
    if data["ath"] > ticker_state.get("ath", 0):
        print(f"鈽?{ticker}: New ATH! {ticker_state.get('ath')} -> {data['ath']}")
        ticker_state["ath"] = data["ath"]
        # Reset ALL thresholds 鈥?new ATH means fresh cycle
        ticker_state["triggered"] = []

    # Calculate current drop % from ATH
    ath = ticker_state["ath"]
    if ath <= 0:
        return False
    drop_pct = round((1 - data["close"] / ath) * 100, 2)
    triggered = ticker_state.get("triggered", [])

    alerted = False
    for threshold in DROP_THRESHOLDS:
        if drop_pct >= threshold and threshold not in triggered:
            # New threshold crossed 鈥?send alert
            triggered.append(threshold)
            msg = (
                f"馃毃 {ticker} 浠锋牸棰勮\n\n"
                f"褰撳墠浠锋牸: ${data['close']}\n"
                f"鍘嗗彶鏈€楂?(ATH): ${ath}\n"
                f"浠嶢TH涓嬭穼: **{drop_pct}%**\n"
                f"瑙﹀彂闃堝€? {threshold}%\n"
                f"褰撳墠涓篈TH鐨? {data['pct_of_ath']}%\n"
                f"鏁版嵁鏃ユ湡: {data['date']}\n\n"
                f"鈿?娉ㄦ剰: 浠锋牸宸蹭粠鏈€楂樼偣涓嬭穼瓒呰繃 {threshold}%"
            )
            send_wechat(msg, f"馃毃 {ticker} 浠锋牸涓嬭穼 {threshold}% 棰勮")
            alerted = True
            print(f"馃毃 {ticker}: threshold {threshold}% triggered (drop={drop_pct}%)")

    # Update state
    ticker_state["triggered"] = sorted(triggered)
    state[ticker] = ticker_state
    save_alerts(state)

    if not alerted:
        print(f"鉁?{ticker}: drop={drop_pct}%, thresholds triggered={triggered}")
    return alerted


if __name__ == "__main__":
    try:
        print(f"=== Price Drop Monitor === {datetime.now().isoformat()}")

        # Load persisted state
        state = load_alerts()

        # Fetch SPY and QQQ data
        print("\nFetching SPY...")
        spy = yahoo_ohlcv("SPY")
        print(f"  close={spy['close']}, ATH={spy['ath']}, %ofATH={spy['pct_of_ath']}%")

        print("\nFetching QQQ...")
        qqq = yahoo_ohlcv("QQQ")
        print(f"  close={qqq['close']}, ATH={qqq['ath']}, %ofATH={qqq['pct_of_ath']}%")

        # Check alerts
        print("\nChecking alert thresholds...")
        check_and_alert("SPY", spy, state)
        check_and_alert("QQQ", qqq, state)

        print("\n鉁?Monitor check complete")

    except Exception as e:
        print(f"鉂?Global error: {e}")
        traceback.print_exc()
