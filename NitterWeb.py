import cloudscraper
import requests
import time
import re
import os
from datetime import datetime
from deep_translator import GoogleTranslator
import threading
import telebot
import feedparser
from google import genai
from bs4 import BeautifulSoup
from flask import Flask
from datetime import timedelta

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN") or ""
CHAT_ID = os.getenv("CHAT_ID") or ""
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or ""

bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-2.5-flash" 

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- LOG ---
def log(msg, level="INFO"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}")

# --- DATA ---
rss_news_store = []
sent_links = set()
MAX_NEWS = 5000
CLEAR_COUNT = 1000

# --- HELPERS ---
def translate(text):
    try:
        return GoogleTranslator(source='auto', target='te').translate(text)
    except:
        return text

def clean_html_tags(text):
    if not text: return ""
    return text.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")

def send_long_message(chat_id, text):
    """HTML ముక్కల వల్ల ఎర్రర్ రాకుండా జాగ్రత్తగా పంపుతుంది"""
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        try:
            bot.send_message(chat_id, chunk, parse_mode='HTML', disable_web_page_preview=True)
        except Exception as e:
            # HTML ట్యాగ్ కట్ అయితే ప్లెయిన్ టెక్స్ట్ గా పంపుతుంది
            log(f"⚠️ HTML Parse Error, sending as plain text: {e}", "WARNING")
            clean_chunk = re.sub('<[^>]+>', '', chunk)
            bot.send_message(chat_id, clean_chunk)

def manage_memory():
    global rss_news_store
    if len(rss_news_store) > MAX_NEWS:
        rss_news_store = rss_news_store[CLEAR_COUNT:]
        log(f"✅ Memory cleaned.")

# =========================
# 🟢 NORMAL RSS
# =========================
RSS_FEEDS = {
    "CNBC": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/latest.xml",
    "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
}

def fetch_normal_rss():
    log("🌍 NORMAL RSS STARTED...")
    while True:
        for name, url in RSS_FEEDS.items():
            try:
                res = requests.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Accept": "application/rss+xml, application/xml;q=0.9,*/*;q=0.8"
                    },
                    timeout=15
                )

                feed = feedparser.parse(res.content)

                if not feed.entries:
                    log(f"⚠️ No entries from {name}")
                    continue

                # --- ఇక్కడ నుండి మార్పు మొదలవుతుంది ---
                for entry in feed.entries[:10]:
                    link = entry.get("link", "")
                    if not link or link in sent_links:
                        continue

                    sent_links.add(link)

                    title = clean_html_tags(entry.get("title", ""))
                    summary_raw = entry.get("summary") or entry.get("description") or ""

                    clean_desc = re.sub('<[^>]+>', '', summary_raw).replace("\n", " ").strip()
                    clean_desc = clean_html_tags(clean_desc)

                    tel_title = translate(title)
                    tel_desc = translate(clean_desc[:800])

                    g_trans_url = f"https://translate.google.com/translate?sl=en&tl=te&u={link}"

                    # image_47f0db.png ఫార్మాట్ కోసం మెసేజ్ స్ట్రక్చర్
                    msg = (
                        f'<a href="{link}">&#8203;</a>'  # ఇది ప్రివ్యూ ఇమేజ్ తెస్తుంది
                        f"📌 <b>{tel_title}</b>\n\n"
                        f"🇬🇧 <b>English Title:</b>\n{title}\n\n"
                        f"🇮🇳 <b>తెలుగు సమ్మరీ:</b>\n{tel_desc}\n\n"
                        f"🌐 <b>{name}</b>\n"
                        f"🔗 <a href='{g_trans_url}'>Read More in Telugu</a> | "
                        f"<a href='{link}'>English Original</a>"
                    )

                    news_entry = {
                        "time": datetime.now(),
                        "type": "NORMAL",
                        "source": name,
                        "title": tel_title,
                        "desc": tel_desc,
                        "link": link,
                        "full_text": title + " " + clean_desc
                    }
                    rss_news_store.append(news_entry)
                    manage_memory()

                    try:
                        # disable_web_page_preview=False వల్ల రెండో ఇమేజ్ లాగా బాక్స్ వస్తుంది
                        bot.send_message(CHAT_ID, msg, parse_mode='HTML', disable_web_page_preview=False)
                    except Exception as e:
                        log(f"❌ Telegram send error: {e}", "ERROR")

                    time.sleep(1)
                # --- ఇక్కడితో మార్పు ముగుస్తుంది ---

            except Exception as e:
                log(f"❌ RSS Error {name}: {e}", "ERROR")

        time.sleep(120)

# =========================
# 🔵 X RSS (With Translate Link)
# =========================
X_RSS_FEEDS = {
    "NDTV Profit (X)": "https://nitter.net/NDTVProfitIndia/rss",
    "ET NOW (X)": "https://nitter.net/ETNOWlive/rss",
    "Redbox X": "https://nitter.net/REDBOXINDIA/rss"
}

def get_image_url(entry):
    try:
        if hasattr(entry, 'media_content') and entry.media_content:
            return entry.media_content[0]['url']
        soup = BeautifulSoup(str(entry.get('summary', '')), 'html.parser')
        img = soup.find('img')
        return img['src'] if img and img.get('src') else None
    except: return None

def clean_x_text(text):
    junk = [r'http\S+', r'www\.\S+', r'@\w+', r'#\w+', r'⤵️', r'\|']
    for p in junk:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    return clean_html_tags(re.sub(r'\s+', ' ', text).strip())

def fetch_x_rss():
    log("🐦 X RSS STARTED...")
    scraper = cloudscraper.create_scraper()
    while True:
        for name, url in X_RSS_FEEDS.items():
            try:
                res = scraper.get(url, timeout=20)
                if res.status_code != 200: continue
                feed = feedparser.parse(res.content)

                # --- ఇక్కడ నుండి మార్పు మొదలవుతుంది ---
                for entry in feed.entries[:5]:
                    link = entry.get("link", "")
                    if not link or link in sent_links: continue
                    sent_links.add(link)

                    title = clean_x_text(entry.get("title", ""))
                    tel_title = translate(title)
                    g_trans_url = f"https://translate.google.com/translate?sl=en&tl=te&u={link}"

                    # టెలిగ్రామ్ మెసేజ్ ఫార్మాట్
                    msg = (
                        f"🚀 <b>{name} Update</b>\n\n"
                        f"📌 <b>{tel_title}</b>\n\n"
                        f"🇬🇧 {title}\n\n"
                        f"🔗 <a href='{g_trans_url}'>Read More in Telugu</a> | "
                        f"<a href='{link}'>English Original</a>"
                    )

                    # డేటా స్టోరేజ్ (దీనివల్లే /redbox మరియు /xrss కమాండ్స్ పనిచేస్తాయి)
                    news_entry = {
                        "time": datetime.now(),
                        "type": "X",
                        "source": name, # ఇందులో 'Redbox X' లేదా 'NDTV Profit (X)' అని సేవ్ అవుతుంది
                        "title": tel_title,
                        "link": link
                    }
                    rss_news_store.append(news_entry)
                    manage_memory()

                    # ఫోటో ఉంటే ఫోటోతో, లేదంటే నార్మల్ మెసేజ్ పంపడం
                    image_url = get_image_url(entry)
                    try:
                        if image_url:
                            bot.send_photo(CHAT_ID, image_url, caption=msg[:1024], parse_mode='HTML')
                        else:
                            bot.send_message(CHAT_ID, msg, parse_mode='HTML', disable_web_page_preview=False)
                    except:
                        bot.send_message(CHAT_ID, msg, parse_mode='HTML', disable_web_page_preview=False)

                    time.sleep(2)
                # --- ఇక్కడితో మార్పు ముగుస్తుంది ---

            except Exception as e:
                log(f"❌ X RSS Error {name}: {e}", "ERROR")
        time.sleep(120)

# =========================
# 🤖 AI SUMMARY
# =========================
@bot.message_handler(commands=['summary'])
def summary(message):
    if not rss_news_store:
        bot.reply_to(message, "❌ వార్తలు లేవు")
        return

    bot.send_message(CHAT_ID, "🔍 AI విశ్లేషణ జరుగుతోంది (Normal RSS మాత్రమే)...")
    
    # మార్పు: కేవలం 'NORMAL' టైప్ వార్తలను మాత్రమే తీసుకుంటున్నాము
    normal_news = [n['full_text'] for n in rss_news_store if isinstance(n, dict) and n.get('type') == "NORMAL"]
    
    if not normal_news:
        bot.reply_to(message, "⚠️ విశ్లేషించడానికి Normal RSS వార్తలు ఏమీ లేవు.")
        return

    rss_data = "\n".join(normal_news[-100:]) # చివరి 100 నార్మల్ వార్తలు
    prompt = f"Analyze these news items in 4 sections: Corporate, National, Global, and Outlook. Output in Telugu:\n{rss_data}"

    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        final_text = clean_html_tags(response.text).replace("**", "")
        send_long_message(
    CHAT_ID,
    f"📊 <b>AI విశ్లేషణ (Normal RSS)</b>\n\n{final_text}"
)
        log("✅ Summary sent (Filtered)")
    except Exception as e:
        log(f"❌ AI Error: {e}", "ERROR")
        
# =========================
# 📋 LIST SPECIAL 
# =========================
@bot.message_handler(commands=['list'])
def list_news(message):
    # మార్పు: కేవలం 'NORMAL' వార్తలను మాత్రమే ఫిల్టర్ చేస్తున్నాము
    only_normal = [n for n in rss_news_store if isinstance(n, dict) and n.get('type') == "NORMAL"]

    if not only_normal:
        bot.reply_to(message, "❌ ప్రస్తుతం ఏ Normal RSS వార్తలు లేవు.")
        return

    args = message.text.split()
    try:
        page = int(args[1]) if len(args) > 1 else 1
    except:
        page = 1

    per_page = 30
    total_news = len(only_normal)
    total_pages = (total_news + per_page - 1) // per_page

    reversed_store = list(reversed(only_normal))
    start = (page - 1) * per_page
    page_news = reversed_store[start:start + per_page]

    response = f"📋 ఇటీవలి వార్తలు (Normal RSS) - పేజీ {page}/{total_pages}\n"
    response += f"📊 మొత్తం వార్తలు: {total_news}\n\n"

    for i, news in enumerate(page_news, start + 1):
        # news['title'] ని వాడుతున్నాము
        safe_news = news['title'].replace("*", "").replace("_", "").replace("`", "")
        short_news = (safe_news[:120] + "...") if len(safe_news) > 120 else safe_news
        response += f"{i}. {short_news}\n\n"

    response += f"📌 తదుపరి పేజీ: /list {page + 1}\n"
    send_long_message(CHAT_ID, response)

# =========================
# 📋 NORMAL RSS TIME BASED GET (Smart Time)
# =========================
@bot.message_handler(commands=['get'])
def get_normal_rss_by_time(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ సమయం చెప్పండి. ఉదా: `/get 11` (ఉదయం 11 తర్వాత వార్తల కోసం) లేదా `/get 22` (నిన్నటి రాత్రి 10 తర్వాత వార్తల కోసం)")
        return

    try:
        hour = int(args[1])
        if not (0 <= hour <= 23):
            bot.reply_to(message, "❌ సమయం 0 నుండి 23 మధ్యలో ఉండాలి.")
            return

        now = datetime.now()
        target_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        
        # Smart Logic: యూజర్ అడిగిన గంట ప్రస్తుత గంట కంటే ఎక్కువ ఉంటే అది నిన్నటి సమయంగా మారుస్తుంది
        if hour > now.hour:
            target_time = target_time - timedelta(days=1)

        # కేవలం 'NORMAL' టైప్ వార్తలను మాత్రమే ఫిల్టర్ చేయడం
        filtered_news = [
            n for n in rss_news_store 
            if isinstance(n, dict) and n.get('type') == "NORMAL" and n.get('time') >= target_time
        ]

        if not filtered_news:
            bot.reply_to(message, f"⚠️ {target_time.strftime('%d-%m %H:%M')} తర్వాత ఎటువంటి Normal RSS వార్తలు లేవు.")
            return

        report = f"🕒 <b>Normal RSS వార్తలు ({target_time.strftime('%d %b, %H:%M')} నుండి):</b>\n"
        report += f"📊 మొత్తం వార్తలు: {len(filtered_news)}\n\n"
        
        for i, n in enumerate(filtered_news, 1):
            t = n['time'].strftime('%H:%M')
            report += f"{i}. [{t}] <b>{n['title']}</b>\n"
            report += f"🌐 {n['source']} | <a href='{n['link']}'>లింక్</a>\n\n"

        send_long_message(CHAT_ID, report)

    except Exception as e:
        log(f"Error in get_normal: {e}", "ERROR")
        bot.reply_to(message, "❌ సమయం సరిగ్గా ఇవ్వండి (0-23 లోపు సంఖ్య).")
        
# =========================
# 🚩 REDBOX TIME BASED GET (Smart Time)
# =========================
@bot.message_handler(commands=['getred'])
def get_redbox_by_time(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ సమయం చెప్పండి. ఉదా: `/getred 22` (రాత్రి 10 గంటల తర్వాత వార్తల కోసం)")
        return

    try:
        hour = int(args[1])
        if not (0 <= hour <= 23):
            bot.reply_to(message, "❌ సమయం 0 నుండి 23 మధ్యలో ఉండాలి.")
            return

        now = datetime.now()
        target_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        
        # ఒకవేళ యూజర్ అడిగిన సమయం ప్రస్తుత సమయం కంటే ఎక్కువ ఉంటే (ఉదా: ఉదయం 6 కి అడిగితే 22 అనేది నిన్నటిది)
        if hour > now.hour:
            target_time = target_time - timedelta(days=1)

        # Redbox వార్తలను మాత్రమే ఫిల్టర్ చేయడం
        filtered_news = [
            n for n in rss_news_store 
            if isinstance(n, dict) and n.get('source') == "Redbox X" and n.get('time') >= target_time
        ]

        if not filtered_news:
            bot.reply_to(message, f"⚠️ {target_time.strftime('%d-%m %H:%M')} తర్వాత ఎటువంటి Redbox వార్తలు లేవు.")
            return

        report = f"🚩 <b>Redbox వార్తలు ({target_time.strftime('%d %b, %H:%M')} నుండి):</b>\n"
        report += f"📊 మొత్తం: {len(filtered_news)}\n\n"
        
        for i, n in enumerate(filtered_news, 1):
            t = n['time'].strftime('%H:%M')
            report += f"{i}. [{t}] <b>{n['title']}</b>\n🔗 <a href='{n['link']}'>Link</a>\n\n"

        send_long_message(message.chat.id, report)

    except Exception as e:
        log(f"Error in getred: {e}", "ERROR")
        bot.reply_to(message, "❌ ఏదో తప్పు జరిగింది. మళ్ళీ ప్రయత్నించండి.")

# =========================
# 🐦 X RSS TIME BASED GET (Smart Time)
# =========================
@bot.message_handler(commands=['getx'])
def get_xrss_by_time(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ సమయం చెప్పండి. ఉదా: `/getx 10` (ఉదయం 10 తర్వాత వార్తల కోసం)")
        return

    try:
        hour = int(args[1])
        if not (0 <= hour <= 23):
            bot.reply_to(message, "❌ సమయం 0 నుండి 23 మధ్యలో ఉండాలి.")
            return

        now = datetime.now()
        target_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        
        if hour > now.hour:
            target_time = target_time - timedelta(days=1)

        # Redbox కాకుండా మిగిలిన X వార్తలను ఫిల్టర్ చేయడం
        filtered_news = [
            n for n in rss_news_store 
            if isinstance(n, dict) and n.get('type') == "X" and n.get('source') != "Redbox X" and n.get('time') >= target_time
        ]

        if not filtered_news:
            bot.reply_to(message, f"⚠️ {target_time.strftime('%d-%m %H:%M')} తర్వాత ఎటువంటి X RSS వార్తలు లేవు.")
            return

        report = f"🐦 <b>X RSS వార్తలు ({target_time.strftime('%d %b, %H:%M')} నుండి):</b>\n"
        report += f"📊 మొత్తం: {len(filtered_news)}\n\n"
        
        for i, n in enumerate(filtered_news, 1):
            t = n['time'].strftime('%H:%M')
            report += f"{i}. [{t}] <b>{n['title']}</b>\n🌐 {n['source']} | <a href='{n['link']}'>Link</a>\n\n"

        send_long_message(message.chat.id, report)

    except Exception as e:
        log(f"Error in getx: {e}", "ERROR")
        bot.reply_to(message, "❌ ఏదో తప్పు జరిగింది.")
        
# =========================
# 📊 SMART AI SUMMARY (Time Based & Important News)
# =========================
@bot.message_handler(commands=['summarytime'])
def smart_summary(message):
    args = message.text.split()
    
    # డిఫాల్ట్‌గా ఉదయం 6 గంటల నుండి వార్తలు తీసుకుంటుంది, ఒకవేళ టైమ్ ఇస్తే ఆ టైమ్ నుండి తీసుకుంటుంది
    try:
        hour = int(args[1]) if len(args) > 1 else 6 
        if not (0 <= hour <= 23): hour = 6
    except:
        hour = 6

    now = datetime.now()
    target_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    
    # Smart Time Logic (నిన్నటి సమయం అయితే)
    if hour > now.hour:
        target_time = target_time - timedelta(days=1)

    if not rss_news_store:
        bot.reply_to(message, "❌ విశ్లేషించడానికి వార్తలు ఏమీ లేవు.")
        return

    # కేవలం మీరు అడిగిన సమయం తర్వాత వచ్చిన వార్తలను మాత్రమే ఫిల్టర్ చేయడం
    filtered_news = [
        f"Source: {n['source']} | Title: {n['full_text'] if 'full_text' in n else n['title']}" 
        for n in rss_news_store 
        if isinstance(n, dict) and n.get('time') >= target_time
    ]

    if not filtered_news:
        bot.reply_to(message, f"⚠️ {hour}:00 తర్వాత ఎటువంటి వార్తలు లేవు.")
        return

    bot.send_message(message.chat.id, f"🔍 {target_time.strftime('%H:%M')} నుండి వచ్చిన ముఖ్యమైన వార్తలను AI విశ్లేషిస్తోంది...")

    # AI కి ఇచ్చే ఇన్‌స్ట్రక్షన్ (Prompt)
    rss_data = "\n".join(filtered_news[-150:]) # చివరి 150 వార్తలు (AI లిమిట్ కోసం)
    prompt = (
        f"You are a financial news expert. Analyze the following news items from {target_time.strftime('%H:%M')} onwards. "
        "Filter and extract only the MOST IMPORTANT and MARKET-MOVING news. "
        "Categorize them into: 1. Corporate (Stocks), 2. Economy/Policy, 3. Global Markets. "
        "Provide a concise summary in Telugu for each category. Use bullet points. "
        f"\nNews Data:\n{rss_data}"
    )

    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        final_text = clean_html_tags(response.text).replace("**", "")
        
        report_header = f"📊 <b>Smart AI Analysis (Important News Only)</b>\n"
        report_header += f"⏰ సమయం: {target_time.strftime('%d %b, %H:%M')} నుండి ఇప్పటివరకు\n"
        report_header += f"📰 విశ్లేషించిన వార్తలు: {len(filtered_news)}\n"
        report_header += "--------------------------------------\n\n"

        send_long_message(message.chat.id, report_header + final_text)
        log("✅ Time-based summary sent")
    except Exception as e:
        log(f"❌ AI Error: {e}", "ERROR")
        bot.reply_to(message, "⚠️ AI విశ్లేషణలో లోపం జరిగింది.")

# మెయిన్ బ్లాక్ ఎప్పుడూ లైన్ మొదట్లో (ఎడమ అంచున) ఉండాలి
if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    threading.Thread(target=fetch_normal_rss, daemon=True).start()
    threading.Thread(target=fetch_x_rss, daemon=True).start()
    log("🚀 BOT STARTED")
    bot.infinity_polling()
