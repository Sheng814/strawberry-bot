import os
import certifi
from flask import Flask, request, abort
from openai import OpenAI
import requests
import base64
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent,
    TextMessage,
    ImageMessage,
    TextSendMessage
)

# =========================
# 1. 填入你的API金鑰
# =========================

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
CWA_API_KEY = os.getenv("CWA_API_KEY", "").strip()

# =========================
# 2. 初始化
# =========================

app = Flask(__name__)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_API_KEY)

# 用來記住使用者目前選到哪個功能
user_state = {}


# =========================
# 3. GPT 文字回覆
# =========================

def ask_gpt(system_prompt, user_message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content

    except Exception as e:
        print("OpenAI text error:", e)
        return "目前系統回覆發生錯誤，請稍後再試。"


# =========================
# 4. GPT 圖片分析
# =========================

def ask_gpt_with_image(image_bytes):
    try:
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
你是草莓病蟲害識別與防治建議助手。
請根據使用者上傳的草莓葉片、果實或植株照片進行初步分析。

請用繁體中文回答，格式如下：

【初步判斷】
說明可能的病害或蟲害類型。

【觀察依據】
說明你從照片中看到哪些特徵，例如斑點、變色、萎凋、霉層、蟲害痕跡等。

【處理建議】
提供農民可以先採取的處理方式。

【注意事項】
提醒這只是 AI 初步判斷，若情況嚴重，應請教農業改良場、農會或專業人員。
"""
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "請分析這張草莓照片是否可能有病蟲害，並提供防治建議。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.4
        )

        return response.choices[0].message.content

    except Exception as e:
        print("OpenAI image error:", e)
        return "圖片分析失敗，請確認照片清楚，或稍後再試。"


# =========================
# 5. 中央氣象署 API
# =========================

def normalize_location_name(name):
    """
    把使用者輸入的縣市名稱統一整理
    例如：台中 → 臺中市、台北市 → 臺北市
    """

    name = name.strip()
    name = name.replace("台", "臺")

    city_map = {
        "臺北": "臺北市",
        "臺北市": "臺北市",
        "新北": "新北市",
        "新北市": "新北市",
        "桃園": "桃園市",
        "桃園市": "桃園市",
        "臺中": "臺中市",
        "臺中市": "臺中市",
        "臺南": "臺南市",
        "臺南市": "臺南市",
        "高雄": "高雄市",
        "高雄市": "高雄市",

        "基隆": "基隆市",
        "基隆市": "基隆市",
        "新竹": "新竹縣",   # 若只輸入新竹，先預設新竹縣
        "新竹縣": "新竹縣",
        "新竹市": "新竹市",
        "苗栗": "苗栗縣",
        "苗栗縣": "苗栗縣",
        "彰化": "彰化縣",
        "彰化縣": "彰化縣",
        "南投": "南投縣",
        "南投縣": "南投縣",
        "雲林": "雲林縣",
        "雲林縣": "雲林縣",
        "嘉義": "嘉義縣",   # 若只輸入嘉義，先預設嘉義縣
        "嘉義縣": "嘉義縣",
        "嘉義市": "嘉義市",
        "屏東": "屏東縣",
        "屏東縣": "屏東縣",
        "宜蘭": "宜蘭縣",
        "宜蘭縣": "宜蘭縣",
        "花蓮": "花蓮縣",
        "花蓮縣": "花蓮縣",
        "臺東": "臺東縣",
        "臺東縣": "臺東縣",
        "澎湖": "澎湖縣",
        "澎湖縣": "澎湖縣",
        "金門": "金門縣",
        "金門縣": "金門縣",
        "連江": "連江縣",
        "連江縣": "連江縣",
    }

    return city_map.get(name, name)


def get_weather_forecast(location_name):
    """
    使用中央氣象署 F-C0032-001：一般天氣預報-今明36小時天氣預報
    """

    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"

    params = {
        "Authorization": CWA_API_KEY
    }

    try:
        print("=== CWA DEBUG START ===")
        print("Input location:", location_name)
        print("CWA_API_KEY exists:", bool(CWA_API_KEY))
        print("CWA_API_KEY length:", len(CWA_API_KEY) if CWA_API_KEY else 0)

        response = requests.get(
            url,
            params=params,
            timeout=10,
            verify=False
        )

        print("CWA status code:", response.status_code)
        print("CWA response first 500:", response.text[:500])

        data = response.json()

        if "records" not in data:
            print("CWA response has no records.")
            return None

        if "location" not in data["records"]:
            print("CWA records has no location.")
            return None

        target_name = normalize_location_name(location_name)
        print("Target name:", target_name)

        locations = data["records"]["location"]

        matched_location = None

        for loc in locations:
            api_location_name = loc["locationName"]

            if api_location_name == target_name:
                matched_location = loc
                break

        if matched_location is None:
            available_names = [loc["locationName"] for loc in locations]

            return (
                "查不到這個地區的天氣資料。\n\n"
                "請輸入台灣縣市名稱，例如：\n"
                "臺北市、新北市、桃園市、臺中市、臺南市、高雄市、彰化縣、苗栗縣\n\n"
                f"目前可查詢的縣市有：\n{', '.join(available_names)}"
            )

        result = f"地區：{matched_location['locationName']}\n"

        weather_elements = matched_location["weatherElement"]

        for element in weather_elements:
            name = element["elementName"]
            result += f"\n【{name}】\n"

            for time_item in element["time"]:
                start_time = time_item["startTime"]
                end_time = time_item["endTime"]
                parameter = time_item["parameter"]["parameterName"]

                result += f"{start_time} ~ {end_time}：{parameter}\n"

        print("=== CWA DEBUG SUCCESS ===")
        return result

    except Exception as e:
        print("=== CWA DEBUG ERROR ===")
        print("CWA API error:", e)
        print("CWA_API_KEY exists:", bool(CWA_API_KEY))
        print("CWA_API_KEY length:", len(CWA_API_KEY) if CWA_API_KEY else 0)
        return None


def analyze_weather_for_strawberry(location_name):
    weather_text = get_weather_forecast(location_name)

    if weather_text is None:
        return (
            "天氣資料讀取失敗，可能是系統暫時異常，請稍後再試。"
        )

    if weather_text.startswith("查不到這個地區"):
        return weather_text

    system_prompt = """
你是草莓極端氣候預警助手。
請根據中央氣象署的天氣預報資料，判斷對草莓種植可能造成的風險。

請用繁體中文回答，格式如下：

【天氣摘要】
簡短整理未來天氣。

【草莓風險判斷】
分析是否可能有低溫、豪雨、高溫、濕度過高、病害風險等。

【農民建議】
提供實際可執行的管理建議，例如排水、覆蓋、通風、減少澆水、注意灰黴病等。

【提醒】
說明此為根據公開天氣資料與 AI 的初步建議。
"""

    user_message = f"""
使用者所在地區：{location_name}

中央氣象署天氣資料如下：
{weather_text}

請分析這些天氣對草莓種植的影響。
"""

    return ask_gpt(system_prompt, user_message)


# =========================
# 6. 一般六功能 Prompt
# =========================

def get_prompt(option):
    if option == "B":
        return """
你是草莓精準灌溉與施肥建議助手。
請用繁體中文回覆，內容包含：
1. 詢問草莓目前生長階段
2. 詢問天氣、土壤濕度、是否下雨
3. 提供一般性灌溉建議
4. 提供一般性施肥建議
5. 提醒避免過度澆水與過量施肥
"""

    elif option == "C":
        return """
你是草莓生長預測與產量分析助手。
請用繁體中文回覆，內容包含：
1. 詢問草莓生長階段
2. 詢問種植面積、植株數量、品種
3. 說明可根據生長資料與環境資料推估生長狀態
4. 說明產量受溫度、光照、水分、授粉、病蟲害影響
5. 提醒目前是 AI 初步推估
"""

    elif option == "D":
        return """
你是草莓市場價格與銷售建議助手。
請用繁體中文回覆，內容包含：
1. 詢問品種、品質等級、預計採收量
2. 詢問銷售地區與通路
3. 提供一般性銷售建議
4. 提醒若要即時價格需串接市場價格資料來源
"""

    elif option == "F":
        return """
你是草莓農場主智慧管理手冊助手。
請用繁體中文回覆，內容包含：
1. 請使用者輸入草莓品種、面積、種植日期、生長階段
2. 說明可以協助建立管理紀錄
3. 建議記錄澆水、施肥、病蟲害、採收量、天氣狀況
4. 提供個人化管理建議
"""

    return None


# =========================
# 7. Webhook 接收區
# =========================

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    print("Request body:", body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. 請檢查 Channel Secret 是否正確。")
        abort(400)
    except Exception as e:
        print("Webhook error:", e)
        abort(500)

    return "OK"


# =========================
# 8. 處理文字訊息
# =========================

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    original_text = event.message.text.strip()
    user_text = original_text.upper()

    # =========================
    # A. 病蟲害識別：等待圖片
    # =========================
    if user_text == "A":
        user_state[user_id] = "WAITING_IMAGE"
        reply_text = (
            "你已選擇：A. 病蟲害識別功能\n\n"
            "請直接上傳一張草莓葉片、果實或植株的照片。\n"
            "我會協助你初步判斷可能的病蟲害，並提供防治建議。"
        )

    # =========================
    # B. 灌溉與施肥：等待使用者輸入環境資料
    # =========================
    elif user_text == "B":
        user_state[user_id] = "WAITING_B_INFO"
        reply_text = (
            "你已選擇：B. 精準灌溉與施肥建議\n\n"
            "請輸入以下資料，我會幫你分析：\n"
            "1. 草莓目前生長階段，例如定植期、開花期、結果期、採收期\n"
            "2. 最近天氣，例如晴天、下雨、低溫、高溫\n"
            "3. 土壤狀況，例如偏乾、潮濕、積水\n"
            "4. 最近是否有施肥\n\n"
            "範例：\n"
            "開花期，最近有下雨，土壤偏濕，三天前有施肥。"
        )

    # =========================
    # C. 生長預測與產量分析
    # =========================
    elif user_text == "C":
        user_state[user_id] = "WAITING_C_INFO"
        reply_text = (
            "你已選擇：C. 生長預測與產量分析\n\n"
            "請輸入以下資料，我會幫你初步分析：\n"
            "1. 草莓品種\n"
            "2. 種植面積或植株數量\n"
            "3. 目前生長階段\n"
            "4. 開花、結果或葉片生長狀況\n"
            "5. 最近是否有病蟲害或天氣異常\n\n"
            "範例：\n"
            "品種是豐香，種植100株，目前結果期，開花正常，最近沒有明顯病蟲害。"
        )

    # =========================
    # D. 市場價格與銷售建議
    # =========================
    elif user_text == "D":
        user_state[user_id] = "WAITING_D_INFO"
        reply_text = (
            "你已選擇：D. 市場價格與銷售建議\n\n"
            "請輸入以下資料，我會幫你提供銷售建議：\n"
            "1. 草莓品種\n"
            "2. 預計採收量\n"
            "3. 品質等級，例如大果、中果、小果\n"
            "4. 銷售方式，例如批發、直銷、電商、觀光果園\n"
            "5. 銷售地區\n\n"
            "範例：\n"
            "品種是香水草莓，預計採收50公斤，大果，想在彰化做直銷。"
        )

    # =========================
    # E. 極端氣候預警：等待縣市
    # =========================
    elif user_text == "E":
        user_state[user_id] = "WAITING_LOCATION"
        reply_text = (
            "你已選擇：E. 極端氣候預警系統\n\n"
            "請輸入你的農場所在地縣市，例如：\n"
            "彰化縣、臺中市、苗栗縣、臺北市、高雄市"
        )

    # =========================
    # F. 農場管理手冊
    # =========================
    elif user_text == "F":
        user_state[user_id] = "WAITING_F_INFO"
        reply_text = (
            "你已選擇：F. 農場主智慧管理手冊\n\n"
            "請輸入你的農場基本資料，我會幫你整理成管理建議：\n"
            "1. 草莓品種\n"
            "2. 種植面積\n"
            "3. 種植日期\n"
            "4. 目前生長階段\n"
            "5. 最近澆水、施肥、病蟲害、採收狀況\n\n"
            "範例：\n"
            "品種是豐香，面積0.2公頃，11月定植，目前開花期，每兩天澆水一次，最近葉片有些黃化。"
        )

    # =========================
    # B 後續資料分析
    # =========================
    elif user_state.get(user_id) == "WAITING_B_INFO":
        system_prompt = """
你是草莓精準灌溉與施肥建議助手。
請根據使用者提供的草莓生長階段、天氣、土壤與施肥狀況，提供具體建議。

請用繁體中文回答，格式如下：

【目前狀況判斷】
整理使用者提供的資訊。

【灌溉建議】
說明是否需要澆水、是否要減少澆水、是否要注意排水。

【施肥建議】
說明是否適合施肥、應注意氮肥、磷鉀肥或避免過量施肥。

【注意事項】
提醒可能風險，例如積水、根腐、肥傷、灰黴病等。
"""
        reply_text = ask_gpt(system_prompt, original_text)
        user_state[user_id] = None

    # =========================
    # C 後續資料分析
    # =========================
    elif user_state.get(user_id) == "WAITING_C_INFO":
        system_prompt = """
你是草莓生長預測與產量分析助手。
請根據使用者提供的品種、植株數量、面積、生長階段、開花結果狀況與病蟲害狀況，進行初步分析。

請用繁體中文回答，格式如下：

【生長狀態判斷】
判斷目前草莓生長是否正常。

【產量影響因素】
分析可能影響產量的因素。

【初步產量建議】
可以用保守、普通、良好三種等級描述，不要假裝能精準預測。

【管理建議】
提供提升生長與產量的做法。
"""
        reply_text = ask_gpt(system_prompt, original_text)
        user_state[user_id] = None

    # =========================
    # D 後續資料分析
    # =========================
    elif user_state.get(user_id) == "WAITING_D_INFO":
        system_prompt = """
你是草莓市場價格與銷售建議助手。
請根據使用者提供的草莓品種、採收量、品質等級、銷售方式與地區，提供銷售策略。

請用繁體中文回答，格式如下：

【銷售條件整理】
整理使用者提供的資訊。

【建議銷售方式】
分析適合批發、直銷、電商或觀光果園。

【提高收益建議】
提供分級、包裝、品牌、社群行銷或預購建議。

【注意事項】
提醒若要即時市場價格，仍需要串接農產品市場價格資料。
"""
        reply_text = ask_gpt(system_prompt, original_text)
        user_state[user_id] = None

    # =========================
    # E 後續縣市查詢
    # =========================
    elif user_state.get(user_id) == "WAITING_LOCATION":
        location_name = original_text
        reply_text = analyze_weather_for_strawberry(location_name)
        user_state[user_id] = None

    # =========================
    # F 後續資料分析
    # =========================
    elif user_state.get(user_id) == "WAITING_F_INFO":
        system_prompt = """
你是草莓農場主智慧管理手冊助手。
請根據使用者提供的農場資料，整理成農場管理紀錄，並提供個人化管理建議。

請用繁體中文回答，格式如下：

【農場紀錄整理】
條列整理使用者提供的農場資料。

【目前管理狀態】
判斷目前管理上可能的優點與風險。

【建議追蹤項目】
列出之後應該持續記錄的資料，例如澆水、施肥、病蟲害、採收量、天氣。

【個人化建議】
提供下一步管理建議。
"""
        reply_text = ask_gpt(system_prompt, original_text)
        user_state[user_id] = None

    # =========================
    # 其他文字
    # =========================
    else:
        reply_text = (
            "請從下方選單選擇功能：\n\n"
            "A. 病蟲害識別\n"
            "B. 精準灌溉與施肥建議\n"
            "C. 生長預測與產量分析\n"
            "D. 市場價格與銷售建議\n"
            "E. 極端氣候預警\n"
            "F. 農場主智慧管理手冊"
        )

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


# =========================
# 9. 處理圖片訊息
# =========================

@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id

    if user_state.get(user_id) != "WAITING_IMAGE":
        reply_text = (
            "我收到圖片了。\n\n"
            "如果你要使用病蟲害識別功能，請先點選下方選單的：\n"
            "A. 病蟲害識別\n\n"
            "再上傳草莓葉片或果實照片。"
        )

    else:
        try:
            message_content = line_bot_api.get_message_content(event.message.id)
            image_bytes = b"".join(message_content.iter_content())

            reply_text = ask_gpt_with_image(image_bytes)
            user_state[user_id] = None

        except Exception as e:
            print("LINE image error:", e)
            reply_text = "圖片讀取失敗，請重新上傳一次清楚的照片。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


# =========================
# 10. 啟動 Flask
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)