import os
import json
import requests
import feedparser

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

def generate_summary(title, description):
    """Генерация структурированной выжимки через Gemini API."""
    if not GEMINI_API_KEY:
        print("❌ Ошибка: Переменная GEMINI_API_KEY отсутствует!")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = (
        f"Проанализируй новость и сделай структурированную выжимку на русском языке.\n"
        f"Используй следующий формат:\n\n"
        f"📌 <b>Главное:</b> (1-2 предложения с сутью новости)\n\n"
        f"🔑 <b>Ключевые детали:</b>\n"
        f"• (деталь 1)\n"
        f"• (деталь 2)\n"
        f"• (деталь 3)\n\n"
        f"💡 <b>Итог:</b> (1 короткий вывод)\n\n"
        f"Новость для анализа:\n"
        f"Заголовок: {title}\n"
        f"Текст новости: {description}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code == 200:
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            print(f"❌ Ошибка Gemini API [{response.status_code}]: {response.text}")
    except Exception as e:
        print(f"❌ Исключение при запросе к Gemini API: {e}")
    
    return None

def send_telegram_message(title, link, summary=None):
    if summary:
        text = f"<b>{title}</b>\n\n{summary}\n\n🔗 <a href='{link}'>Читать полностью</a>"
    else:
        text = f"<b>{title}</b>\n\n🔗 <a href='{link}'>Читать полностью</a>"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    response = requests.post(url, json=payload)
    return response.ok

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
        description = getattr(entry, 'summary', getattr(entry, 'description', ''))

        print(f"Обработка новости: {title}")
        summary = generate_summary(title, description)
        
        if send_telegram_message(title, link, summary):
            history.add(link)
        else:
            print(f"Не удалось отправить: {link}")

    save_history(history)

if __name__ == "__main__":
    main()
