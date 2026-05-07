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

# 強制更新 twstock 資料庫
twstock.__update_codes()

# --- 1. Google Sheets 設定 ---
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
json_file = "credentials.json"

if not os.path.exists(json_file):
    raise FileNotFoundError("找不到 credentials.json，請檢查 GitHub Actions 解碼步驟。")

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
    client = gspread.authorize(creds)
    sheet = client.open("股市自動化追蹤").sheet1 
except Exception as e:
    print(f"連線失敗: {e}")
    raise

# --- 2. 爬取 00981A 成分股 ---
def get_holdings():
    url = "https://www.ezmoney.com.tw/ETF/Fund/Info?FundCode=49YTW"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'html.parser')
        asset_div = soup.find('div', id='DataAsset')
        if asset_div:
            all_assets = json.loads(html.unescape(asset_div['data-content']))
            return [d['DetailCode'].strip() for g in all_assets if g['AssetName'] == "股票" for d in g['Details']]
    except: return []
    return []

# --- 3. 執行抓取 ---
codes = get_holdings()
if codes:
    # 更新 A 欄 (使用最新的 gspread 語法避免 Warning)
    sheet.update(range_name='A2', values=[[c] for c in codes])
    
    all_data = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for code in codes:
        try:
            # 判斷上市 (.TW) 或上櫃 (.TWO)
            info = twstock.codes.get(code)
            name = info.name if info else "未知"
            suffix = ".TW" if info and info.market == "上市" else ".TWO"
            ticker_yf = f"{code}{suffix}"
            
            price, ma5, ma30, force = "N/A", "N/A", "N/A", "觀察中"
            
            tk = yf.Ticker(ticker_yf)
            hist = tk.history(period="40d")
            
            if not hist.empty:
                price = hist['Close'].iloc[-1]
                if len(hist) >= 5: ma5 = hist['Close'].tail(5).mean()
                if len(hist) >= 30: ma30 = hist['Close'].tail(30).mean()
                
                # 簡單力道判斷
                change = ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                vol_ratio = hist['Volume'].iloc[-1] / hist['Volume'].tail(5).mean() if not hist['Volume'].tail(5).mean() == 0 else 1
                
                if change > 1.5 and vol_ratio > 1.2: force = "🔥 大買"
                elif change > 0: force = "📈 小買"
                elif change < -1.5 and vol_ratio > 1.2: force = "💀 大賣"
                elif change < 0: force = "📉 小賣"
                else: force = "↔️ 盤整"

            all_data.append([
                name, 
                round(float(price), 2) if isinstance(price, (int, float)) else "N/A",
                round(float(ma5), 2) if isinstance(ma5, (int, float)) else "N/A",
                round(float(ma30), 2) if isinstance(ma30, (int, float)) else "N/A",
                force, 
                now
            ])
            print(f"✅ {name}({code}): {price}")
            time.sleep(0.2)
        except Exception as e:
            all_data.append([name, "N/A", "N/A", "N/A", "錯誤", now])
            print(f"❌ {code} 出錯: {e}")

    if all_data:
        # 更新 B2:G 範圍
        sheet.update(range_name='B2', values=all_data)
        print("🎉 全部更新成功！")
