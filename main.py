import json
import os
import telebot
from telebot.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from groq import Groq
from dotenv import load_dotenv
from scorer import run_scoring

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    raise ValueError("Ошибка: не найдены TELEGRAM_TOKEN или GROQ_API_KEY в файле .env")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)

BACKLOG_FILE = "backlog.json"
SCORED_FILE = "scored_backlog.json"
CONTEXT_FILE = "context.md"

user_drafts = {}

EXTRACT_PROMPT = """
Ты опытный Product Manager. Твоя задача — оцифровать идею фичи для методики RICE, опираясь на контекст продукта.

Правила диалога:
1. Если пользователь дал ОЧЕНЬ мало информации (непонятен масштаб охвата Reach, сложность Effort или реальная польза Impact) И флаг force_evaluate = false, задай 1-2 коротких вопроса.
   Верни JSON с двумя ключами:
   - "status": "need_info"
   - "question": "Твой короткий вопрос пользователю"

2. Если деталей достаточно ИЛИ пользователь уже ответил на вопрос ИЛИ флаг force_evaluate = true — оцени фичу и верни JSON с ключами:
   - "status": "ready"
   - "title": "краткое название фичи на русском"
   - "stack_required": строго "F", "B" или "BaF"
   - "reach": целое число (не больше MAU из контекста)
   - "impact": 0.25, 0.5, 1.0, 2.0 или 3.0
   - "confidence": число от 0.1 до 1.0 (если данных мало, ставь 0.5 или ниже)
   - "effort": целое число >= 1 (в человеко-неделях)

Верни ТОЛЬКО валидный JSON без лишнего текста.
"""

PM_ANALYZE_PROMPT = """
Ты Senior Product Manager. Тебе передан отсортированный по методике RICE бэклог спринта в формате JSON.
Проведи краткий, структурированный и практичный анализ на русском языке.

Правила оформления (СТРОГО для Telegram HTML):
- НЕ используй Markdown-таблицы, решетки, двойные звездочки и HTML-сущности вроде &nbsp; или <br>.
- Для жирного текста используй тег <b>текст</b>, для курсива — <i>текст</i>.
- Оформляй пункты аккуратными списками с эмодзи и обычными пробелами.

Содержание анализа:
1. 🏆 <b>Quick Wins (топ-2 фичи):</b> выдели задачи с лучшим соотношением ценности и затрат и объясни, почему их стоит брать первыми.
2. ⚖️ <b>Баланс стека (F, B, BaF):</b> проверь, нет ли перекоса и бутылочного горлышка для фронтенда, бэкенда или QA.
3. ⚠️ <b>Риски и гипотезы:</b> укажи на фичи с низким Confidence (< 0.6) или большим Effort, которые требуют проверки.
4. 🚀 <b>Итоговые рекомендации:</b> 2–3 конкретных шага на спринт.
"""

def load_json(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_context():
    if not os.path.exists(CONTEXT_FILE):
        return "Контекст продукта не задан."
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def finalize_and_save_feature(chat_id, feature_data, reply_to_msg_id=None):
    backlog = load_json(BACKLOG_FILE)
    new_id = max([item.get("id", 0) for item in backlog], default=0) + 1

    new_entry = {
        "id": new_id,
        "title": feature_data.get("title", "Без названия"),
        "stack_required": feature_data.get("stack_required", "BaF"),
        "reach": int(feature_data.get("reach", 100)),
        "impact": float(feature_data.get("impact", 1.0)),
        "confidence": float(feature_data.get("confidence", 0.5)),
        "effort": max(1, int(feature_data.get("effort", 1)))
    }

    backlog.append(new_entry)
    save_json(BACKLOG_FILE, backlog)
    user_drafts.pop(chat_id, None)

    reply_text = (
        f"✅ <b>Фича #{new_id} добавлена в бэклог!</b>\n\n"
        f"📌 <b>Название:</b> {new_entry['title']}\n"
        f"🛠 <b>Стек:</b> {new_entry['stack_required']}\n"
        f"👥 <b>Охват:</b> {new_entry['reach']}\n"
        f"💥 <b>Влияние:</b> {new_entry['impact']}\n"
        f"🎯 <b>Уверенность:</b> {new_entry['confidence']}\n"
        f"⏳ <b>Усилия:</b> {new_entry['effort']}"
    )
    bot.send_message(chat_id, reply_text, parse_mode="HTML", reply_to_message_id=reply_to_msg_id)

def process_feature_with_llm(chat_id, combined_text, force_evaluate=False, reply_to_msg_id=None):
    bot.send_chat_action(chat_id, 'typing')
    product_context = load_context()

    system_msg = (
        f"{EXTRACT_PROMPT}\n\n"
        f"=== ВВОДНЫЕ О ПРОДУКТЕ И КОМАНДЕ ===\n{product_context}\n\n"
        f"Текущий флаг force_evaluate = {str(force_evaluate).lower()}."
    )

    chat_completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": combined_text}
        ],
        model="openai/gpt-oss-20b",
        temperature=0.2,
        response_format={"type": "json_object"}
    )

    ai_response = chat_completion.choices[0].message.content
    result = json.loads(ai_response)

    if result.get("status") == "need_info" and not force_evaluate:
        user_drafts[chat_id] = {"history": combined_text, "asked": True}

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("⏩ Оценить как есть", callback_data="skip_clarify"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_feature")
        )

        question_text = f"🤔 <b>Нужно небольшое уточнение:</b>\n\n{result.get('question')}"
        bot.send_message(
            chat_id,
            question_text,
            parse_mode="HTML",
            reply_markup=markup,
            reply_to_message_id=reply_to_msg_id
        )
    else:
        finalize_and_save_feature(chat_id, result, reply_to_msg_id=reply_to_msg_id)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_drafts.pop(message.chat.id, None)
    text = (
        "Привет! Я AI-помощник для RICE-скоринга бэклога.\n\n"
        "📝 <b>Просто напиши идею фичи</b> — если деталей мало, я задам 1–2 уточняющих вопроса (их можно пропустить).\n"
        "📊 /score — запустить валидацию, расчет RICE и сортировку.\n"
        "🧠 /analyze — получить аналитику от AI Product Manager по итогам скоринга."
    )
    bot.reply_to(message, text, parse_mode="HTML")

@bot.message_handler(commands=['score'])
def handle_score(message):
    user_drafts.pop(message.chat.id, None)
    valid_projects, errors = run_scoring(BACKLOG_FILE, SCORED_FILE)

    if not valid_projects and errors:
        bot.reply_to(message, "⚠️ Не удалось провести скоринг:\n" + "\n".join(errors))
        return

    lines = ["🏆 <b>Приоритезированный бэклог (RICE):</b>\n"]
    for idx, h in enumerate(valid_projects, 1):
        lines.append(
            f"{idx}. <b>[{h['stack_required']}] {h['title']}</b>\n"
            f"   RICE: <code>{h['rice_score']}</code> (R:{h['reach']} | I:{h['impact']} | C:{h['confidence']} | E:{h['effort']})"
        )

    if errors:
        lines.append("\n⚠️ <b>Пропущены с ошибками:</b>\n" + "\n".join(errors))

    lines.append("\n👉 Нажми /analyze, чтобы получить мнение AI-продакта.")
    bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

@bot.message_handler(commands=['analyze'])
def handle_analyze(message):
    user_drafts.pop(message.chat.id, None)
    scored_data = load_json(SCORED_FILE)
    if not scored_data:
        bot.reply_to(message, "Сначала выполни расчет бэклога командой /score.")
        return

    bot.send_chat_action(message.chat.id, 'typing')

    try:
        product_context = load_context()
        full_analyze_prompt = (
            f"{PM_ANALYZE_PROMPT}\n\n"
            f"=== ВВОДНЫЕ О ПРОДУКТЕ И КОМАНДЕ ===\n{product_context}\n\n"
            f"Обязательно учитывай размер аудитории, длительность спринта и состав команды "
            f"при оценке реалистичности плана и узких мест."
        )

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": full_analyze_prompt},
                {"role": "user", "content": json.dumps(scored_data, ensure_ascii=False)}
            ],
            model="openai/gpt-oss-120b",
            temperature=0.4
        )
        analysis = chat_completion.choices[0].message.content.replace("&nbsp;", " ")
        try:
            bot.reply_to(message, f"🧠 <b>Анализ от AI Product Manager:</b>\n\n{analysis}", parse_mode="HTML")
        except Exception:
            bot.reply_to(message, f"🧠 Анализ от AI Product Manager:\n\n{analysis}")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при анализе: {e}")

@bot.callback_query_handler(func=lambda call: call.data in ["skip_clarify", "cancel_feature"])
def handle_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    if call.data == "cancel_feature":
        user_drafts.pop(chat_id, None)
        bot.edit_message_text(
            "❌ Добавление фичи отменено.",
            chat_id=chat_id,
            message_id=call.message.message_id
        )
        return

    if call.data == "skip_clarify":
        draft = user_drafts.get(chat_id)
        if not draft:
            bot.edit_message_text(
                "⚠️ Черновик устарел. Отправьте идею фичи заново.",
                chat_id=chat_id,
                message_id=call.message.message_id
            )
            return

        bot.edit_message_text(
            "⏩ Оцениваю фичу на основе имеющихся данных...",
            chat_id=chat_id,
            message_id=call.message.message_id
        )
        try:
            process_feature_with_llm(chat_id, draft["history"], force_evaluate=True)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка при оценке: {e}")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id

    try:
        if chat_id in user_drafts:
            draft = user_drafts[chat_id]
            combined_text = (
                f"Изначальная идея фичи: {draft['history']}\n"
                f"Уточнение от пользователя: {message.text}"
            )
            process_feature_with_llm(chat_id, combined_text, force_evaluate=True, reply_to_msg_id=message.message_id)
        else:
            process_feature_with_llm(chat_id, message.text, force_evaluate=False, reply_to_msg_id=message.message_id)

    except Exception as e:
        user_drafts.pop(chat_id, None)
        bot.reply_to(message, f"❌ Произошла ошибка при обработке: {e}")

bot.set_my_commands([
    BotCommand("start", "ℹ️ Инструкция по работе"),
    BotCommand("score", "📊 Посчитать RICE и отсортировать"),
    BotCommand("analyze", "🧠 Анализ от AI Product Manager"),
])

bot.infinity_polling()


