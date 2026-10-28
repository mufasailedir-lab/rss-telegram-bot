import os
import json
import requests
import feedparser
import html
import re
import time
from urllib.parse import urlparse

RSS_URL = "https://energynewsbeat.co/feed/"
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "posted_links.json"

# Сначала быстрая gemini-3.5-flash-lite для экономии квот, затем резервная gemini-3.8-flash
MODELS_QUEUE = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]

# Словарь сопоставления разделов сайта с русскими хештегами
CATEGORY_TAGS = {
    "crude-oil": "#нефть",
    "crude-oil-news": "#нефть",
    "natural-gas": "#газ",
    "diesel": "#дизель #топливо",
    "jet-fuel": "#авиакеросин #топливо",
    "downstream": "#переработка",
    "electrical-generation": "#электроэнергия",
    "data-center": "#датацентры #электроэнергия",
    "ai": "#ИИ #энергетика",
    "earnings": "#отчетность",
    "weekly-rig-count": "#бурение",
    "electric-vehicles": "#электромобили",
    "net-zero": "#зеленая_энергетика",
    "big-oil-companies": "#нефтяные_гиганты",
    "international-news": "#мировые_новости",
}

# Ключевые слова в URL подкастов и аудио-шоу для исключения
PODCAST_PATTERNS = [
    "conversations-in-energy-with-stu-turley",
    "energy-transition-podcast",
]


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
    # Храним только последние 300 ссылок, чтобы файл не разрастался
    trimmed = list(history)[-300:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def clean_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def get_entry_text(entry):
    if getattr(entry, "content", None):
        return clean_html(entry.content[0].value)
    return clean_html(getattr(entry, "summary", getattr(entry, "description", "")))


def get_tag_from_url(url):
    try:
        path_segments = [seg for seg in urlparse(url).path.split("/") if seg]
        if path_segments:
            category = path_segments[0].lower()
            return CATEGORY_TAGS.get(category, "#энергетика")
    except Exception:
        pass
    return "#энергетика"


def is_podcast(url):
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in PODCAST_PATTERNS)


def generate_summary(title, text):
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY не задан")
        return None

    prompt = (
        "Ты — редактор русскоязычного новостного Telegram-канала об энергетике. "
        "Переведи заголовок и подготовь лаконичную, легко читаемую выжимку статьи.\n\n"
        "Требования:\n"
        "1. Весь текст (включая заголовок) должен быть СТРОГО на грамотном русском языке.\n"
        "2. Используй только HTML-теги <b> и <i>. Любой Markdown (*, **, #) строго запрещён.\n"
        "3. Текст должен читаться за 20 секунд: пиши ёмко, без канцеляризмов и длинных вводных конструкций.\n"
        "4. Обязательно сохраняй ключевые цифры ($, %, ГВт, баррели), компании и регуляторов.\n"
        "5. Каждый пункт в деталях — строго одно короткое предложение.\n\n"
        "Формат строго следующий:\n\n"
        "📰 <b>(Ёмкий заголовок новости на русском языке)</b>\n\n"
        "⚡ <b>Главное:</b> 1-2 коротких предложения о сути инфоповода.\n\n"
        "📊 <b>В деталях:</b>\n"
        "• <b>Ключевой факт:</b> пояснение с цифрами\n"
        "• <b>Ключевой факт:</b> пояснение с цифрами\n"
        "• <b>Ключевой факт:</b> пояснение с цифрами\n\n"
        "🎯 <b>Почему это важно:</b> 1 предложение о влиянии на рынок, отрасль или цены.\n\n"
        f"Оригинальный заголовок: {title}\n"
        f"Текст статьи:\n{text[:10000]}"
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


def send_telegram_message(message_text):
    if len(message_text) > 4000:
        message_text = message_text[:3950] + "..."

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message_text, "parse_mode": "HTML"}

    r = requests.post(url, json=payload)
    if not r.ok:
        print(f"Telegram [{r.status_code}]: {r.text}")
        payload.pop("parse_mode")
        payload["text"] = re.sub(r"<[^>]+>", "", message_text)
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

        # 1. Отсев подкастов и видео без вызова нейросети
        if is_podcast(link):
            print(f"⏭ Пропуск подкаста: {title}")
            history.add(link)
            continue

        print(f"Обработка новости: {title}")
        summary = generate_summary(title, text)

        # 2. Если нейросеть недоступна, не публикуем сырой английский текст —
        # пропускаем, чтобы повторить попытку в следующий запуск
        if not summary:
            print("⚠️ Выжимка не получена от ИИ, пропускаю до следующего запуска")
            continue

        # 3. Извлечение рубрики из URL и добавление хештегов
        tag = get_tag_from_url(link)
        message_text = f"{summary}\n\n{tag}"

        if send_telegram_message(message_text):
            history.add(link)
        else:
            print(f"Не удалось отправить: {link}")

        # Пауза между запросами для предотвращения исчерпания минутных квот API
        time.sleep(5)

    save_history(history)


if __name__ == "__main__":
    main()
