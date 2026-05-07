import gspread
from oauth2client.service_account import ServiceAccountCredentials
import yfinance as yf
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import json
import html
import time
import pandas as pd
import twstock
twstock.__update_codes()

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

# --- 1. 設定 Google Sheets 權限 ---
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("股市自動化追蹤").sheet1 

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
            
            # 初始化數據
            price = "N/A"
            ma5 = "N/A"
            ma30 = "N/A"
            force_status = "觀察中"

            # 抓取歷史資料 (至少要 40 天才能計算 30MA)
            tk = yf.Ticker(ticker_yf)
            hist = tk.history(period="40d")
            
            if not hist.empty and len(hist) >= 30:
                # 1. 取得最新股價
                price = hist['Close'].iloc[-1]
                
                # 2. 計算均線
                ma5 = hist['Close'].rolling(window=5).mean().iloc[-1]
                ma30 = hist['Close'].rolling(window=30).mean().iloc[-1]
                
                # 3. 判斷主力動向 (邏輯：成交量與漲跌幅模擬)
                last_vol = hist['Volume'].iloc[-1]
                avg_vol = hist['Volume'].tail(5).mean() # 5日均量
                pct_change = ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                
                if pct_change > 2 and last_vol > avg_vol * 1.5:
                    force_status = "🔥 大買"
                elif pct_change > 0:
                    force_status = "📈 小買"
                elif pct_change < -2 and last_vol > avg_vol * 1.5:
                    force_status = "💀 大賣"
                elif pct_change < 0:
                    force_status = "📉 小賣"
                else:
                    force_status = "↔️ 盤整"

            # 格式化數值
            fmt_price = round(float(price), 2) if isinstance(price, (int, float)) else "N/A"
            fmt_ma5 = round(float(ma5), 2) if isinstance(ma5, (int, float)) else "N/A"
            fmt_ma30 = round(float(ma30), 2) if isinstance(ma30, (int, float)) else "N/A"

            # 欄位順序：公司名稱, 最新價, 5MA, 30MA, 主力動向, 更新時間
            all_data.append([name, fmt_price, fmt_ma5, fmt_ma30, force_status, now])
            print(f"✅ {name}({code}): 價{fmt_price} | 5MA:{fmt_ma5} | 動向:{force_status}")
            
            time.sleep(0.5)

        except Exception as e:
            all_data.append([name, "N/A", "N/A", "N/A", "出錯", now])
            print(f"❌ 處理 {code} 出錯: {e}")

    # 一次性寫入 B2 之後的欄位
    if all_data:
        sheet.update('B2', all_data)
        print("🎉 表格已更新包含均線與主力動向！")

except Exception as e:
    print(f"🔥 嚴重錯誤: {e}")