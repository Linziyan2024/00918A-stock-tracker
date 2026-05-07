import gspread
from oauth2client.service_account import ServiceAccountCredentials
import yfinance as yf
from datetime import datetime
import twstock
import requests
from bs4 import BeautifulSoup
import json
import html
import time
import pandas as pd
import os

# 強制更新 twstock 代碼資料庫 (GitHub 環境必備)
twstock.__update_codes()

# --- 1. 設定 Google Sheets 權限 ---
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# 這裡做了安全性檢查：
# 如果在 GitHub 跑，會去找解碼出來的 credentials.json
# 如果在你電腦跑，只要有這個檔案也能動
json_file = "credentials.json"

if not os.path.exists(json_file):
    raise FileNotFoundError(f"找不到金鑰檔案：{json_file}，請檢查 GitHub Secrets 設定。")

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
    client = gspread.authorize(creds)
    # 務必確認你的 Google Sheet 名字完全正確
    sheet = client.open("股市自動化追蹤").sheet1 
except Exception as e:
    print(f"Google Sheets 連線失敗: {e}")
    raise

# --- 2. 獲取成分股邏輯 (維持不變) ---
def get_00981A_holdings_fixed():
    url = "https://www.ezmoney.com.tw/ETF/Fund/Info?FundCode=49YTW"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        asset_div = soup.find('div', id='DataAsset')
        if asset_div and asset_div.has_attr('data-content'):
            raw_json = html.unescape(asset_div['data-content'])
            all_assets = json.loads(raw_json)
            stock_list = []
            for group in all_assets:
                if group.get('AssetName') == "股票" and group.get('Details'):
                    for detail in group['Details']:
                        code = detail.get('DetailCode')
                        if code:
                            stock_list.append(code.strip())
            return stock_list
    except:
        return []

# --- 3. 執行主程式 ---
try:
    print("正在獲取最新成分股與均線數據...")
    fetched_codes = get_00981A_holdings_fixed()
    if not fetched_codes:
        raise Exception("無法取得股票清單")

    # 更新 A 欄代號
    sheet.update('A2', [[s] for s in fetched_codes])

    all_data = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for code in fetched_codes:
        try:
            ticker_yf = f"{code}.TW"
            stock_info = twstock.codes.get(code)
            name = stock_info.name if stock_info else "未知"
            
            price, ma5, ma30, force_status = "N/A", "N/A", "N/A", "觀察中"

            tk = yf.Ticker(ticker_yf)
            hist = tk.history(period="40d")
            
            if not hist.empty and len(hist) >= 30:
                price = hist['Close'].iloc[-1]
                ma5 = hist['Close'].rolling(window=5).mean().iloc[-1]
                ma30 = hist['Close'].rolling(window=30).mean().iloc[-1]
                
                last_vol = hist['Volume'].iloc[-1]
                avg_vol = hist['Volume'].tail(5).mean()
                pct_change = ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                
                if pct_change > 2 and last_vol > avg_vol * 1.5: force_status = "🔥 大買"
                elif pct_change > 0: force_status = "📈 小買"
                elif pct_change < -2 and last_vol > avg_vol * 1.5: force_status = "💀 大賣"
                elif pct_change < 0: force_status = "📉 小賣"
                else: force_status = "↔️ 盤整"

            fmt_price = round(float(price), 2) if isinstance(price, (int, float)) else "N/A"
            fmt_ma5 = round(float(ma5), 2) if isinstance(ma5, (int, float)) else "N/A"
            fmt_ma30 = round(float(ma30), 2) if isinstance(ma30, (int, float)) else "N/A"

            all_data.append([name, fmt_price, fmt_ma5, fmt_ma30, force_status, now])
            print(f"✅ {name}({code}): {fmt_price} | {force_status}")
            time.sleep(0.5)

        except Exception as e:
            all_data.append([name, "N/A", "N/A", "N/A", "出錯", now])
            print(f"❌ 處理 {code} 出錯: {e}")

    if all_data:
        sheet.update('B2', all_data)
        print("🎉 全部更新完成！")

except Exception as e:
    print(f"🔥 嚴重錯誤: {e}")
