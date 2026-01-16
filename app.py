from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import hashlib
import random
from langdetect import detect, LangDetectException

app = Flask(__name__)
CORS(app)

# 百度翻译配置（用户提供）
BAIDU_Fanyi_APPID = "20251201002510175"
BAIDU_Fanyi_SECRET_KEY = "RmDJVRf3wvqOcJ_gKPqE"

# -------------------------- 1. 国家-语境映射 --------------------------
CULTURE_CONTEXT_MAP = {
    "中国": "高语境", 
    "日本": "高语境", 
    "韩国": "高语境",
    "美国": "低语境", 
    "德国": "低语境", 
    "加拿大": "低语境"
}

# -------------------------- 2. 语言-国家映射（自动检测用） --------------------------
LANG_TO_CULTURE = {
    "zh": "中国",
    "ja": "日本",
    "ko": "韩国",
    "en": "美国",
    "de": "德国"
}

# -------------------------- 3. 文化语义重写模板 --------------------------
SEMANTIC_REWRITE_TEMPLATES = [
    # 高语境反讽 → 低语境直接批评
    (
        "高语境反讽",
        (["你真厉害", "你好聪明", "真棒", "amazing"], ["迟到", "忘记", "搞不定", "想不明白", "late"]),
        lambda text: text.replace("真厉害", "太离谱了")
                        .replace("好聪明", "怎么回事")
                        .replace("真棒", "太不负责任了")
                        .replace("amazing", "太离谱了")
    ),
    # 高语境委婉拒绝 → 低语境明确拒绝
    (
        "高语境委婉拒绝",
        (["还不错", "挺好的"], ["再改改", "不太适合", "考虑下"]),
        lambda text: text.replace("还不错", "这个方案不合适").replace("挺好的", "我不能接受")
    ),
    # 冒犯性内容 → 拒绝处理
    (
        "严重文化冒犯",
        (["你们国家", "你们民族", "your country"], ["差", "垃圾", "low", "不行"]),
        lambda text: "【系统拦截】该内容涉及国家/民族冒犯，不符合跨文化交流规范"
    )
]

# -------------------------- 4. 语义检测+重写 --------------------------
def detect_and_rewrite_semantic(text, speaker_context):
    for semantic_type, (trigger1, trigger2), rewrite_func in SEMANTIC_REWRITE_TEMPLATES:
        if speaker_context == "高语境" and any(w in text for w in trigger1) and any(w in text for w in trigger2):
            return (semantic_type, rewrite_func(text))
        if any(w in text for w in trigger1) and any(w in text for w in trigger2):
            return (semantic_type, rewrite_func(text))
    return ("正面表达", text)

# -------------------------- 5. 修复翻译函数（添加headers+确保参数正确） --------------------------
def translate_adapted_text(text, src_lang, target_lang):
    # 百度翻译语言代码映射（严格匹配百度API要求）
    lang_map = {
        "zh": "zh",    # 中文
        "en": "en",    # 英语
        "de": "de",    # 德语
        "ja": "jp",    # 日语
        "ko": "kor"    # 韩语
    }
    # 获取正确的百度API语言码
    src = lang_map.get(src_lang, "auto")  # 自动识别源语言（兜底）
    target = lang_map.get(target_lang, "zh")
    salt = random.randint(32768, 65536)
    # 生成签名（注意编码）
    sign_str = f"{BAIDU_Fanyi_APPID}{text}{salt}{BAIDU_Fanyi_SECRET_KEY}"
    sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    try:
        url = "https://fanyi-api.baidu.com/api/trans/vip/translate"
        params = {
            "q": text,
            "from": src,
            "to": target,
            "appid": BAIDU_Fanyi_APPID,
            "salt": salt,
            "sign": sign
        }
        # 添加请求头避免被拦截
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()  # 主动抛出HTTP错误
        result = response.json()
        # 处理百度翻译返回结果
        if "trans_result" in result:
            return result["trans_result"][0]["dst"]
        else:
            return f"翻译失败：{result.get('error_msg', '未知错误')}"
    except Exception as e:
        return f"翻译失败：{str(e)}"

# -------------------------- 6. 跨文化建议 --------------------------
def get_culture_suggestion(context_type, semantic_type):
    if semantic_type == "严重文化冒犯":
        return "请避免使用涉及国家/民族的负面表述，跨文化交流应保持尊重和平等。"
    if context_type == "高语境":
        return "高语境交流建议：用委婉表达传递态度，避免直接批评；若对方是低语境文化，建议适当明确语义。"
    else:
        return "低语境交流建议：直接明确表达观点，避免过度迂回；若对方是高语境文化，建议增加委婉语气。"

# -------------------------- 7. 核心接口（返回自动检测后的说话人国家） --------------------------
@app.route('/culture_semantic_adapt', methods=['POST'])
def culture_semantic_adapt():
    data = request.get_json()
    text = data.get("text", "").strip()
    speaker_culture = data.get("speaker_culture", "中国")
    target_lang = data.get("target_lang", "en")

    # 1. 处理自动检测说话人国家
    detected_culture = speaker_culture  # 记录最终的说话人国家
    if speaker_culture == "auto":
        try:
            src_lang = detect(text)
            detected_culture = LANG_TO_CULTURE.get(src_lang, "中国")
        except LangDetectException:
            detected_culture = "中国"
        speaker_culture = detected_culture

    # 2. 获取说话人语境
    context_type = CULTURE_CONTEXT_MAP.get(speaker_culture, "未知语境")
    # 3. 语义检测+重写
    semantic_type, rewritten_text = detect_and_rewrite_semantic(text, context_type)
    # 4. 自动识别输入语言（用于翻译）
    try:
        src_lang = detect(text)
    except LangDetectException:
        src_lang = "auto"
    # 5. 翻译重写后的文本
    translated_text = translate_adapted_text(rewritten_text, src_lang, target_lang) if "系统拦截" not in rewritten_text else "——"
    # 6. 生成文化建议
    culture_suggest = get_culture_suggestion(context_type, semantic_type)

    return jsonify({
        "detected_speaker_culture": detected_culture,  # 返回自动检测后的国家
        "context_type": context_type,
        "semantic_type": semantic_type,
        "rewritten_text": rewritten_text,
        "translated_text": translated_text,
        "culture_suggest": culture_suggest,
        "code": 200
    })


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)