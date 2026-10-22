import os
import json
import requests
import feedparser

RSS_URL = "https://energynewsbeat.co/feed/"
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
HISTORY_FILE = "posted_links.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Ошибка при чтении истории: {e}")
            return set()
    return set()

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history), f, ensure_ascii=False, indent=2)

def send_telegram_message(title, link):
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
        print("Ошибка: Переменные BOT_TOKEN или CHAT_ID не заданы.")
        return

    history = load_history()
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("Лента пуста или недоступна.")
        return

    # Фильтруем новые записи (обрабатываем от старых к новым)
    new_entries = [entry for entry in reversed(feed.entries) if entry.link not in history]

    if not new_entries:
        print("Новых новостей нет.")
        return

    for entry in new_entries:
        print(f"Отправка новости: {entry.title}")
        if send_telegram_message(entry.title, entry.link):
            history.add(entry.link)
        else:
            print(f"Не удалось отправить: {entry.link}")

    save_history(history)

if __name__ == "__main__":
    main()