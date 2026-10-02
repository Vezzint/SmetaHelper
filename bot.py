import asyncio
import os
import json
import tempfile
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from groq import Groq
from fpdf import FPDF

# =============================================
# ВСТАВЬ СВОИ КЛЮЧИ СЮДА (в кавычках)
# =============================================
BOT_TOKEN = "ВСТАВЬ_ТОКЕН_БОТА_СЮДА"
GROQ_API_KEY = "ВСТАВЬ_GROQ_КЛЮЧ_СЮДА"
# =============================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = Groq(api_key=GROQ_API_KEY)


# ---------- Команда /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👷 Привет! Я бот-сметчик.\n\n"
        "Просто отправь мне голосовое сообщение с описанием работ, "
        "и я за 10 секунд сделаю красивую PDF-смету для клиента.\n\n"
        "📌 Пример голосового:\n"
        "«Клиент Сергей, квартира на Ленина. Шпаклёвка стен 50 квадратов, "
        "поклейка обоев, ламинат в двух комнатах 30 квадратов. "
        "Материалы заказчика. Срок — неделя.»"
    )


# ---------- Обработка голосовых сообщений ----------
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    await message.answer("⏳ Обрабатываю, подожди ~10 секунд...")

    # 1. Скачиваем голосовой файл
    file = await bot.get_file(message.voice.file_id)
    tmp_audio = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    await bot.download_file(file.file_path, tmp_audio.name)
    audio_path = tmp_audio.name
    tmp_audio.close()

    try:
        # 2. Распознаём голос в текст (Whisper)
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(audio_path, audio_file.read()),
                model="whisper-large-v3-turbo",
                language="ru"
            )
        text = transcription.text

        # 3. Превращаем текст в структурированную смету (Llama)
        prompt = f"""Ты — помощник строителя. Из голосового сообщения мастера извлеки данные для сметы.
Верни ТОЛЬКО JSON, без пояснений, без markdown, без кавычек вокруг JSON.

Формат:
{{
  "client": "имя клиента или адрес объекта",
  "items": [
    {{"name": "название работы", "quantity": "число", "unit": "ед. измерения", "price": "цена за ед.", "total": "сумма"}}
  ],
  "materials_note": "примечание по материалам",
  "deadline": "сроки",
  "total_sum": "общая сумма числом"
}}

Если какие-то данные не указаны — поставь "—".
Если цены не названы — поставь примерные рыночные цены в рублях.

Голосовое сообщение мастера:
{text}"""

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        raw = response.choices[0].message.content.strip()

        # Чистим ответ от возможных ```json ... ```
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            raw = "\n".join(lines)

        data = json.loads(raw)

        # 4. Генерируем PDF
        pdf_path = generate_pdf(data)

        # 5. Отправляем PDF пользователю
        await message.answer_document(
            types.FSInputFile(pdf_path, filename="smeta.pdf"),
            caption="✅ Смета готова! Можешь переслать клиенту."
        )
        os.unlink(pdf_path)

    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)


# ---------- Генерация PDF ----------
def generate_pdf(data):
    pdf = FPDF()
    pdf.add_page()

    # Подключаем шрифт с поддержкой русского языка
    pdf.add_font("DejaVu", "", "DejaVuSans.ttf")

    # Заголовок
    pdf.set_font("DejaVu", size=18)
    pdf.cell(0, 15, "KOMMERCHESKOE PREDLOZHENIE", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)

    # Информация
    pdf.set_font("DejaVu", size=11)
    pdf.cell(0, 8, f"Klient: {data.get('client', '-')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Sroki: {data.get('deadline', '-')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Materialy: {data.get('materials_note', '-')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Таблица — заголовки
    pdf.set_font("DejaVu", size=10)
    headers = ["Rabota", "Kol-vo", "Ed.", "Tsena", "Itogo"]
    widths = [65, 25, 20, 35, 35]

    for i, h in enumerate(headers):
        pdf.cell(widths[i], 8, h, border=1, align="C")
    pdf.ln()

    # Таблица — строки
    for item in data.get("items", []):
        pdf.cell(widths[0], 8, str(item.get("name", ""))[:30], border=1)
        pdf.cell(widths[1], 8, str(item.get("quantity", "")), border=1, align="C")
        pdf.cell(widths[2], 8, str(item.get("unit", "")), border=1, align="C")
        pdf.cell(widths[3], 8, str(item.get("price", "")), border=1, align="R")
        pdf.cell(widths[4], 8, str(item.get("total", "")), border=1, align="R")
        pdf.ln()

    # Итого
    pdf.ln(5)
    pdf.set_font("DejaVu", size=14)
    pdf.cell(0, 10, f"ITOGO: {data.get('total_sum', '-')} rub.", new_x="LMARGIN", new_y="NEXT", align="R")

    # Сохраняем
    path = tempfile.mktemp(suffix=".pdf")
    pdf.output(path)
    return path


# ---------- Запуск бота ----------
async def main():
    print("Bot zapushchen!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
