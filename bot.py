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

# gemini-3.5-flash-lite установлена первой для экономии квот (защита от 429),
# gemini-3.8-flash используется как резервная
MODELS_QUEUE = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]


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


def clean_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def get_entry_text(entry):
    if getattr(entry, "content", None):
        return clean_html(entry.content[0].value)
    return clean_html(getattr(entry, "summary", getattr(entry, "description", "")))


def generate_summary(title, text):
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY не задан")
        return None

    prompt = (
        "Ты — профессиональный аналитик энергетического рынка. "
        "Проанализируй новость и подготовь развернутую, содержательную выжимку на русском языке.\n\n"
        "Требования к оформлению:\n"
        "1. Используй только HTML-теги <b> и <i>. Markdown (*, **, #) использовать строго запрещено.\n"
        "2. Обязательно сохраняй все важные цифры, суммы в $, мощности, названия регуляторов и компаний.\n\n"
        "Формат:\n\n"
        "📌 <b>В чём суть:</b>\n"
        "(Развернутый абзац на 3-4 предложения с описанием контекста, причин и масштаба проблемы)\n\n"
        "📊 <b>Ключевые детали и цифры:</b>\n"
        "• <b>...</b>: подробное описание важного факта или метрики с цифрами\n"
        "• <b>...</b>: еще один ключевой аспект\n"
        "• <b>...</b>: позиции сторон, решения регуляторов или контракты\n"
        "• <b>...</b>: технические или финансовые нюансы\n"
        "• <b>...</b>: влияние на потребителей или инфраструктуру\n\n"
        "⚖️ <b>Конфликт интересов и позиции:</b>\n"
        "(Кратко о том, кто и почему спорит — регуляторы, бигтех, потребители, энергокомпании)\n\n"
        "💡 <b>Итог и последствия:</b>\n"
        "(Что это означает в долгосрочной перспективе для рынка и счетов за энергию)\n\n"
        f"Заголовок: {title}\n"
        f"Текст статьи:\n{text[:14000]}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": GEMINI_API_KEY}

    for model in MODELS_QUEUE:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        for attempt in range(2):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=35)
                if r.status_code == 200:
                    data = r.json()
                    try:
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    except (KeyError, IndexError):
                        print(f"⚠️ Текст не найден в ответе {model}: {data}")
                        break

                print(f"⚠️ Gemini [{model}][{r.status_code}]: {r.text[:200]}")
                if r.status_code in (429, 500, 503):
                    time.sleep(3)
                    continue
                break
            except Exception as e:
                print(f"❌ Ошибка соединения с {model}: {e}")
                time.sleep(2)

    return None


def send_telegram_message(title, summary):
    text = f"<b>{html.escape(title)}</b>\n\n{summary}"

    # Контроль лимита сообщения Telegram (4096 символов)
    if len(text) > 4000:
        text = text[:3950] + "..."

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}

    r = requests.post(url, json=payload)
    if not r.ok:
        print(f"Telegram [{r.status_code}]: {r.text}")
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
            print("⚠️ Выжимка не получена от ИИ, отправляю исходный текст")
            summary = text[:400] + ("..." if len(text) > 400 else "")

        if send_telegram_message(title, summary):
            history.add(link)
        else:
            print(f"Не удалось отправить: {link}")

        # Пауза между запросами для предотвращения исчерпания минутных квот API
        time.sleep(5)

    save_history(history)


if __name__ == "__main__":
    main()
