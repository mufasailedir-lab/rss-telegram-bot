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

# Очередь моделей Gemini: основная быстрая и резервная флагманская
MODELS_QUEUE = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]

# Словарь сопоставления категорий из URL с русскими хештегами
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

# Шаблоны для отсева разговорных подкастов
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
    trimmed = list(history)[-300:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def clean_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"The post .*? appeared first on .*?(\.|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Sign up for (our )?newsletter.*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


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
        "Ты — выпускающий редактор русскоязычного Telegram-канала об энергетике. "
        "Сделай адаптированную, ёмкую выжимку новости.\n\n"
        "Главные ограничения:\n"
        "1. Язык: строго русский.\n"
        "2. Общий объём: 80–120 слов.\n"
        "3. Разметка: используй ТОЛЬКО HTML-теги <b>, <i> и <blockquote>. "
        "Markdown (*, **, #) строго запрещен.\n"
        "4. Всегда сохраняй ключевые цифры ($, %, объёмы, мощности), компании и регуляторов.\n"
        "5. Блок деталей ОБЯЗАТЕЛЬНО оберни в теги <blockquote>...</blockquote>.\n\n"
        "Формат:\n\n"
        "📰 <b>(Ёмкий заголовок на русском без кавычек)</b>\n\n"
        "⚡ <b>Главное:</b> 1–2 коротких предложения сути инфоповода.\n\n"
        "<blockquote>"
        "• <b>...</b>: короткий факт с цифрами\n"
        "• <b>...</b>: короткий факт с цифрами\n"
        "• <b>...</b>: короткий факт с цифрами (если есть)"
        "</blockquote>\n\n"
        "💡 <b>Контекст:</b> 1 предложение о влиянии на рынок (добавляй только если есть последствия).\n\n"
        f"Заголовок оригинала: {title}\n"
        f"Текст статьи:\n{text[:3500]}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 500,
            "temperature": 0.2
        }
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY}

    for model in MODELS_QUEUE:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        for attempt in range(2):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=30)
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


def send_telegram_rich_message(message_text, article_url):
    if len(message_text) > 4000:
        message_text = message_text[:3950] + "..."

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML",
        # Настройка богатого медиа-превью из статьи
        "link_preview_options": {
            "is_disabled": False,
            "url": article_url,
            "prefer_large_media": True,
            "show_above_text": True
        },
        # Инлайн-кнопка для четкой нижней границы публикации
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "Читать первоисточник ↗", "url": article_url}]
            ]
        }
    }

    r = requests.post(url, json=payload, timeout=25)
    if not r.ok:
        print(f"Telegram [{r.status_code}]: {r.text}")
        # Запасной вариант отправки с удалением HTML-тегов при ошибке парсинга
        payload.pop("parse_mode", None)
        payload["text"] = re.sub(r"<[^>]+>", "", message_text)
        r = requests.post(url, json=payload, timeout=25)
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

        # 1. Отсев подкастов и видео
        if is_podcast(link):
            print(f"⏭ Пропуск подкаста: {title}")
            history.add(link)
            continue

        # 2. Отсев пустых или слишком коротких записей
        if len(text) < 250:
            print(f"⏭ Пропуск: короткий текст ({len(text)} симв.): {title}")
            history.add(link)
            continue

        print(f"Обработка новости: {title}")
        summary = generate_summary(title, text)

        # 3. Если ИИ временно недоступен — пропуск до следующего запуска
        if not summary:
            print("⚠️ Выжимка не получена от ИИ, пропускаю")
            continue

        # 4. Формирование поста: карточка выжимки + хештег
        tag = get_tag_from_url(link)
        message_text = f"{summary}\n\n{tag}"

        # 5. Отправка через Rich Message (превью статьи над текстом + кнопка-разделитель)
        if send_telegram_rich_message(message_text, link):
            history.add(link)
            print("✅ Пост опубликован успешно")
        else:
            print(f"❌ Не удалось отправить: {link}")

        time.sleep(5)

    save_history(history)


if __name__ == "__main__":
    main()
