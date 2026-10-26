import os
import json
import requests
import feedparser
import html
import re
import time


RSS_URL = "https://energynewsbeat.co/feed/"
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "posted_links.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Ошибка чтения истории: {e}")
            return set()
    return set()

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history), f, ensure_ascii=False, indent=2)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def clean_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def get_entry_text(entry):
    # Сначала полный текст, если лента его отдаёт, иначе анонс
    if getattr(entry, "content", None):
        return clean_html(entry.content[0].value)
    return clean_html(getattr(entry, "summary", getattr(entry, "description", "")))


def generate_summary(title, text):
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY не задан")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    prompt = (
        "Проанализируй новость и сделай структурированную выжимку на русском языке.\n"
        "Формат (используй только теги <b>, другой разметки не надо):\n\n"
        "📌 <b>Главное:</b> (1-2 предложения)\n\n"
        "🔑 <b>Ключевые детали:</b>\n• ...\n• ...\n• ...\n\n"
        "💡 <b>Итог:</b> (1 короткий вывод)\n\n"
        f"Заголовок: {title}\n"
        f"Текст: {text[:8000]}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": GEMINI_API_KEY}

    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            print(f"❌ Gemini [{r.status_code}]: {r.text[:300]}")
            if r.status_code in (429, 500, 503):
                time.sleep(5 * (attempt + 1))
                continue
            return None  # 400/404 и т.п. повторять бессмысленно
        except Exception as e:
            print(f"❌ Ошибка запроса к Gemini: {e}")
            time.sleep(3)
    return None


def send_telegram_message(title, link, summary):
    text = f"<b>{html.escape(title)}</b>\n\n{summary}\n\n🔗 <a href='{link}'>Читать полностью</a>"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}

    r = requests.post(url, json=payload)
    if not r.ok:
        print(f"Telegram [{r.status_code}]: {r.text}")
        # если сломалась HTML-разметка от нейросети, шлём без неё
        payload.pop("parse_mode")
        payload["text"] = re.sub(r"<[^>]+>", "", text)
        r = requests.post(url, json=payload)
    return r.ok

def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("Ошибка: BOT_TOKEN или CHAT_ID не заданы.")
        return

    history = load_history()
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("Лента пуста или недоступна.")
        return

    new_entries = [entry for entry in reversed(feed.entries) if entry.link not in history]

    if not new_entries:
        print("Новых новостей нет.")
        return

    for entry in new_entries:
        title = entry.title
        link = entry.link
        text = get_entry_text(entry)
    
        print(f"Обработка новости: {title}")
        summary = generate_summary(title, text)
    
        if not summary:
            print("Выжимки нет, пропускаю — попробую в следующий запуск")
            continue
    
        if send_telegram_message(title, link, summary):
            history.add(link)
        else:
            print(f"Не удалось отправить: {link}")

    save_history(history)

if __name__ == "__main__":
    main()
