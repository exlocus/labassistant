import logging
from scipy import constants
import numpy as np
import matplotlib.pyplot as plt
import os
import math
import asyncio
import aiohttp
import sqlite3
from datetime import datetime
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters.state import State, StatesGroup, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command
from aiogram import F

logging.basicConfig(level=logging.INFO)

API_TOKEN = "8160270004:AAHpWYhTBpOQ7MGbr5s4z9fk8mm-_l-ZrLU"

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher()

user_feedback_index = {}
user_data = {}

class Form(StatesGroup):
    waiting_for_conversion_input = State()
    waiting_for_spectrum_analysis_input = State()
    waiting_for_wavelength_input = State()
    waiting_for_fluence_calculation_average_power_input = State()
    waiting_for_fluence_calculation_repetition_rate_input = State()
    waiting_for_fluence_calculation_spot_diameter_input = State()
    waiting_for_feedback_type_default_accept = State()
    waiting_for_feedback_type_anon_accept = State()
    waiting_for_feedback_confirmation = State()
    waiting_for_feedback_anon_confirmation = State()
    waiting_for_mass_mail_message_input = State()
    waiting_for_mass_mail_photo_input = State()

def db_start():
    conn = sqlite3.connect('feedback.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS feedback (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      username TEXT,
                      message TEXT,
                      is_anonymous INTEGER,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def save_feedback(user_id, username, message, is_anonymous):
    conn = sqlite3.connect('feedback.db')
    cursor = conn.cursor()
    created_at = datetime.now()
    cursor.execute("INSERT INTO feedback (user_id, username, message, is_anonymous, created_at) VALUES (?, ?, ?, ?, ?)", 
                   (user_id, username, message, is_anonymous, created_at))
    conn.commit()
    conn.close()

def delete_feedback(feedback_id):
    """Удаляет отзыв из базы данных по ID."""
    conn = sqlite3.connect("feedback.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
    conn.commit()
    conn.close()

def load_all_feedback():
    """Загружает все отзывы из базы данных."""
    conn = sqlite3.connect("feedback.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, username, message, is_anonymous, created_at FROM feedback")
    feedbacks = cursor.fetchall()
    conn.close()

    feedback_list = [
        {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "message": row[3],
            "is_anonymous": row[4],
            "created_at": row[5]
        }
        for row in feedbacks
    ]
    return feedback_list

async def download_file(bot, file_id):
    """Функция для загрузки файла по его file_id с использованием aiohttp"""
    file_info = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as response:
            if response.status == 200:
                return await response.read()
            else:
                raise Exception(f"Не удалось загрузить файл: {response.status}")

async def delete_previous_message(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass

async def calculate_conversion(user_input: str, message: Message):
    try:
        user_id = message.from_user.id
        user_info = user_data.get(user_id, {})
        value_type = user_info.get("value_type_for_conversion")
        value = float(user_input)
        buttons = [
            [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)

        if value_type == "frequency":
            frequency_hz = value * 1e12
            wavelength_nm = (constants.c / frequency_hz) * 1e9
            energy_eV = (constants.h * frequency_hz) / constants.e
            await message.answer(f"🌊 Длина волны: {wavelength_nm:.2f} нм\n⚡ Энергия фотона: {energy_eV:.2f} эВ", reply_markup=keyboard)
        elif value_type == "wavelength":
            wavelength_m = value * 1e-9
            frequency = constants.c / wavelength_m
            frequency_tHz = frequency * 1e-12
            energy_eV = (constants.h * frequency) / constants.e
            await message.answer(f"🔄 Частота: {frequency_tHz:.2f} ТГц\n⚡ Энергия фотона: {energy_eV:.2f} эВ", reply_markup=keyboard)
        elif value_type == "energy":
            energy_J = value * constants.e
            frequency = energy_J / constants.h
            wavelength_nm = (constants.c / frequency) * 1e9
            frequency_tHz = frequency * 1e-12
            await message.answer(f"🔄 Частота: {frequency_tHz:.2f} ТГц\n🌊 Длина волны: {wavelength_nm:.2f} нм", reply_markup=keyboard)
        else:
            await message.answer("Неизвестный ввод. Пожалуйста, попробуйте снова.")
        del user_data[user_id]
    except ValueError:
        await message.answer("🚫 Пожалуйста, введите числовое значение.")
    except ZeroDivisionError:
        await message.answer("🚫 Пожалуйста, введите числовое значение (кроме нуля).")
async def analyze_spectrum(file_data, message: Message):
    try:
        data = np.loadtxt(file_data)
        wavelengths = data[:, 0]
        intensities = data[:, 1]

        peak_index = np.argmax(intensities)
        peak_wavelength = wavelengths[peak_index]
        peak_intensity = intensities[peak_index]

        half_max = peak_intensity / 2

        left_half_max_index = np.where(intensities[:peak_index] <= half_max)[0][-1]
        left_half_max_wavelength = wavelengths[left_half_max_index]

        right_half_max_index = np.where(intensities[peak_index:] <= half_max)[0][0] + peak_index
        right_half_max_wavelength = wavelengths[right_half_max_index]

        fwhm = right_half_max_wavelength - left_half_max_wavelength

        plt.figure(figsize=(10, 6))
        plt.plot(wavelengths, intensities, label='Спектр', color='b')
        plt.axhline(half_max, color='grey', linestyle='--', label='Половина максимума')
        plt.plot(peak_wavelength, peak_intensity, 'ro', label=f'Пик при {peak_wavelength:.2f} нм')
        plt.plot([left_half_max_wavelength, right_half_max_wavelength], [half_max, half_max], 'go-', label=f'Полуширина = {fwhm:.2f} нм')

        plt.xlabel('Длина волны (нм)')
        plt.ylabel('Интенсивность (а.е.)')
        plt.title('Спектр с пиком и полушириной')
        plt.legend()
        plt.grid(True)
        plt.savefig("spectrum_analysis.png")

        buttons = [
            [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        current_directory = os.getcwd()
        input_file = FSInputFile(os.path.join(current_directory, "spectrum_analysis.png"))
        await message.answer_photo(input_file, caption=f"Резонансный пик: {peak_wavelength:.2f} нм\nШирина на полувысоте: {fwhm:.2f} нм", reply_markup=keyboard)
    except Exception as e:
        await message.answer(f"Произошла ошибка при обработке спектра. Пожалуйста, убедитесь, что файл корректный.")

async def fluence_calculation(message: Message):
    user_id = message.from_user.id
    diameter_mm = float(message.text)
    diameter_cm = diameter_mm / 10
    area_cm2 = math.pi * (diameter_cm / 2) ** 2
    user_data[user_id]["spot_area"] = area_cm2
    user_data[user_id]["step"] = "calculate"

    power = user_data[user_id]["average_power"]
    rate = user_data[user_id]["repetition_rate"]
    area = user_data[user_id]["spot_area"]
    fluence = power / (rate * area)
    
    buttons = [
        [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(f"Флюенс лазерной системы составляет: {fluence:.3e} Дж/см²", reply_markup=keyboard)
    del user_data[user_id]

@dp.message(Command("start"))
async def start_handler(message: Message, user_id2: int = None):
    """Обработчик команды /start."""
    user_id = message.from_user.id
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

    text = (
        "👋 Привет! Я — ваш научный ассистент 🔬.\n"
        "Вот что я могу предложить:\n\n"
        "1. 🔄 Перевод частоты/энергии в длину волны\n"
        "2. 📏 Информация о диапазоне длин волн\n"
        "3. 📊 Анализ спектра\n"
        "4. 🔥 Вычисление флюенса\n"
        "5. 📝 Оставить отзыв\n\n"
        "Выберите нужную опцию ниже, чтобы начать работу!"
    )

    buttons = [
        [types.InlineKeyboardButton(text="Калькулятор 🧮", callback_data="calc")],
        [types.InlineKeyboardButton(text="Оставить отзыв 📝", callback_data="feedback")]
    ]

    if user_id2 == 1094169323 and user_id2 != None:
        buttons.append([types.InlineKeyboardButton(text="Админ панель ⚙️", callback_data="admin_panel")])
    elif message.from_user.id == 1094169323:
        buttons.append([types.InlineKeyboardButton(text="Админ панель ⚙️", callback_data="admin_panel")])

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery):
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    await start_handler(callback.message, user_id)

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: types.CallbackQuery):
    """Обработчик админ панели."""
    await delete_previous_message(callback.message)
    admin_text = (
        "🛠️ Добро пожаловать в админ панель!\n"
        "Выберите опцию:"
    )

    admin_buttons = [
        [types.InlineKeyboardButton(text="Посмотреть отзывы 📋", callback_data="view_feedback")],
        [types.InlineKeyboardButton(text="Массовая рассылка 📢", callback_data="mass_mail")],
        [types.InlineKeyboardButton(text="Назад ↩", callback_data="back_to_start")]
    ]
    admin_keyboard = types.InlineKeyboardMarkup(inline_keyboard=admin_buttons)
    await callback.message.answer(admin_text, reply_markup=admin_keyboard)
    await callback.answer()

@dp.callback_query(F.data == "view_feedback")
async def view_feedback_handler(callback: types.CallbackQuery):
    """Обработчик для просмотра отзывов."""
    user_id = callback.from_user.id
    feedback_list = load_all_feedback()
    if not feedback_list:
        await delete_previous_message(callback.message)
        buttons = [
            [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer("Нет новых отзывов для просмотра. 📭", reply_markup=keyboard)
        return

    user_feedback_index[user_id] = 0
    await show_feedback(callback.message, feedback_list, user_id)

async def show_feedback(message, feedback_list, user_id):
    """Функция для отображения текущего отзыва с кнопками управления."""
    await delete_previous_message(message)
    current_index = user_feedback_index.get(user_id, 0)
    feedback = feedback_list[current_index]

    feedback_message = (
        f"Отзыв от {feedback['username'] or 'Аноним'} (id{feedback['user_id'] or "'скрыт'"}):\n\n"
        f"Написан {feedback['created_at']}\n"
        f"Тип отзыва: {'Анонимный 👤' if feedback['is_anonymous'] else 'Обычный 😀'}\n\n"
        f"Текст отзыва:\n{feedback['message']}\n\n"
        f"Отзыв {current_index + 1} из {len(feedback_list)}"
    )

    buttons = [
        [
            types.InlineKeyboardButton(text="◀", callback_data="prev_feedback"),
            types.InlineKeyboardButton(text="✅ Просмотрено", callback_data="mark_as_read"),
            types.InlineKeyboardButton(text="▶", callback_data="next_feedback")
        ]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(feedback_message, reply_markup=keyboard)

@dp.callback_query(F.data == "next_feedback")
async def next_feedback_handler(callback: types.CallbackQuery):
    """Показать следующий отзыв."""
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    feedback_list = load_all_feedback()
    if not feedback_list:
        await callback.answer("Нет отзывов для отображения.")
        return

    user_feedback_index[user_id] = (user_feedback_index[user_id] + 1) % len(feedback_list)
    await show_feedback(callback.message, feedback_list, user_id)

@dp.callback_query(F.data == "prev_feedback")
async def prev_feedback_handler(callback: types.CallbackQuery):
    """Показать предыдущий отзыв."""
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    feedback_list = load_all_feedback()
    if not feedback_list:
        await callback.answer("Нет отзывов для отображения.")
        return

    user_feedback_index[user_id] = (user_feedback_index[user_id] - 1) % len(feedback_list)
    await show_feedback(callback.message, feedback_list, user_id)

@dp.callback_query(F.data == "mark_as_read")
async def mark_as_read_handler(callback: types.CallbackQuery):
    """Пометить отзыв как прочитанный и удалить его из базы."""
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    feedback_list = load_all_feedback()
    if not feedback_list:
        await callback.answer("Нет отзывов для отображения.")
        return

    current_index = user_feedback_index.get(user_id, 0)
    feedback = feedback_list[current_index]

    delete_feedback(feedback['id'])

    await callback.message.answer("Отзыв помечен как просмотренный и удален. ✅")

    feedback_list = load_all_feedback()
    if not feedback_list:
        buttons = [
            [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer("Все отзывы просмотрены! 📭", reply_markup=keyboard)
        user_feedback_index.pop(user_id, None)
    else:
        user_feedback_index[user_id] = current_index % len(feedback_list)
        await show_feedback(callback.message, feedback_list, user_id)

@dp.callback_query(F.data == "mass_mail")
async def start_mass_mail(callback: types.CallbackQuery, state: FSMContext):
    """Запускает процесс массовой рассылки."""
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_mass_mail_message_input)
    await callback.message.answer("🔢 Введите текст сообщения для массовой рассылки:")
    await callback.answer()

@dp.message(StateFilter(Form.waiting_for_mass_mail_message_input))
async def process_message(message: types.Message, state: FSMContext):
    """Сохраняет текст сообщения и запрашивает подтверждение."""
    message_text = message.text
    user_id = message.from_user.id

    user_data[user_id] = {"message_text": message_text}

    confirmation_message = (
        f"🔔 Вы собираетесь отправить следующее массовое сообщение:\n\n"
        f"{message_text}\n\n"
        "Вы уверены, что хотите продолжить? 🤔"
    )

    buttons = [
        [types.InlineKeyboardButton(text="Да 👍", callback_data="confirm_mass_mail")],
        [types.InlineKeyboardButton(text="Нет, изменить ✏️", callback_data="edit_mass_mail")],
        [types.InlineKeyboardButton(text="Отмена ❌", callback_data="cancel_mass_mail")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(confirmation_message, reply_markup=keyboard)

@dp.callback_query(F.data == "confirm_mass_mail")
async def proceed_with_mass_mail(callback: types.CallbackQuery, state: FSMContext):
    """Переходит к ожиданию загрузки фото для массовой рассылки."""
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_mass_mail_photo_input)
    await callback.answer()

    buttons = [
        [types.InlineKeyboardButton(text="Пропустить ⏩", callback_data="skip_photo")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer('📸 Прикрепите фотографию (или нажмите "Пропустить ⏩" для отправки без фото):', reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "edit_mass_mail")
async def edit_mass_mail(callback: types.CallbackQuery, state: FSMContext):
    """Позволяет администратору изменить текст сообщения для массовой рассылки."""
    await delete_previous_message(callback.message)
    await callback.message.answer("🔄 Пожалуйста, введите новый текст сообщения для массовой рассылки:")
    await state.set_state(Form.waiting_for_mass_mail_message_input)

@dp.callback_query(F.data == "cancel_mass_mail")
async def cancel_mass_mail(callback: types.CallbackQuery, state: FSMContext):
    """Отменяет массовую рассылку."""
    await delete_previous_message(callback.message)
    buttons = [
        [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Массовая рассылка отменена. ❌", reply_markup=keyboard)
    await state.clear()

@dp.message(StateFilter(Form.waiting_for_mass_mail_photo_input))
async def process_photo(message: types.Message, state: FSMContext):
    """Сохраняет фото и отправляет массовое сообщение."""
    user_id = message.from_user.id

    message_text = user_data.get(user_id, {}).get("message_text")
    photo = message.photo[-1].file_id

    await send_mass_mail(message, message_text, photo)
    await state.clear()
    buttons = [
        [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("📢 Рассылка завершена.", reply_markup=keyboard)

@dp.callback_query(F.data == "skip_photo")
async def skip_photo(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает отправку фото."""
    user_id = callback.from_user.id

    message_text = user_data.get(user_id, {}).get("message_text")

    await send_mass_mail(callback.message, message_text)
    await state.clear()
    buttons = [
        [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("📢 Рассылка завершена.", reply_markup=keyboard)

async def send_mass_mail(message: Message, message_text: str, photo: str = None):
    """Функция для отправки массового сообщения."""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')

    for row in cursor.fetchall():
        user_id = row[0]
        try:
            if photo:
                await bot.send_photo(user_id, photo, caption=message_text)
            else:
                await bot.send_message(user_id, message_text)
        except Exception as e:
            print(e)

    conn.close()

@dp.callback_query(F.data == "calc")
async def select_calc_method(callback: types.CallbackQuery):
    await delete_previous_message(callback.message)
    buttons = [
        [types.InlineKeyboardButton(text="Перевод частоты/энергии 🌈", callback_data="convert")],
        [types.InlineKeyboardButton(text="Диапазон длин волн 📏", callback_data="wavelength_info")],
        [types.InlineKeyboardButton(text="Анализ спектра 📊", callback_data="spectrum_analysis")],
        [types.InlineKeyboardButton(text="Вычисление флюенса 🔥", callback_data="fluence_calc")],
        [types.InlineKeyboardButton(text="Назад ↩", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выберите опцию:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "convert")
async def handle_conversion(callback: types.CallbackQuery):
    await delete_previous_message(callback.message)
    buttons = [
        [types.InlineKeyboardButton(text="Частота (ТГц) 🔄", callback_data="input_frequency")],
        [types.InlineKeyboardButton(text="Длина волны (нм) 🌊", callback_data="input_wavelength")],
        [types.InlineKeyboardButton(text="Энергия (Эв) ⚡", callback_data="input_energy")],
        [types.InlineKeyboardButton(text="Назад ↩", callback_data="calc")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выберите параметр для ввода:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "input_frequency")
async def input_frequency(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_conversion_input)
    user_id = callback.from_user.id
    user_data[user_id] = {"value_type_for_conversion": "frequency"}
    await callback.message.answer("🔢 Введите частоту (Гц):")
    await callback.answer()

@dp.callback_query(F.data == "input_wavelength")
async def input_wavelength(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_conversion_input)
    user_id = callback.from_user.id
    user_data[user_id] = {"value_type_for_conversion": "wavelength"}
    await callback.message.answer("🔢 Введите длину волны (нм):")
    await callback.answer()

@dp.callback_query(F.data == "input_energy")
async def input_energy(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_conversion_input)
    user_id = callback.from_user.id
    user_data[user_id] = {"value_type_for_conversion": "energy"}
    await callback.message.answer("🔢 Введите энергию (Дж):")
    await callback.answer()

@dp.message(StateFilter(Form.waiting_for_conversion_input))
async def process_user_input_conversion(message: Message):
    user_input = message.text
    await calculate_conversion(user_input, message)

@dp.callback_query(F.data == "spectrum_analysis")
async def handle_spectrum_analysis(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_spectrum_analysis_input)
    await callback.message.answer("📤 Пожалуйста, отправьте файл спектра в формате .txt (две колонки: длина волны и интенсивность).")
    await callback.answer()

@dp.message(StateFilter(Form.waiting_for_spectrum_analysis_input))
async def process_user_input_spectrum_analysis(message: Message):
    try:
        file_id = message.document.file_id
        file_data = await download_file(bot, file_id)
        if file_data:
            with open("spectrum.txt", "wb") as f:
                f.write(file_data)

            await analyze_spectrum("spectrum.txt", message)
        else:
            await message.answer("🚫 Не удалось загрузить файл. Попробуйте снова.")
    except AttributeError:
        await message.answer("🚫 Похоже вы отправили не файл. Попробуйте снова.")

@dp.callback_query(F.data == "wavelength_info")
async def handle_wavelength_info(callback: types.CallbackQuery):
    await delete_previous_message(callback.message)
    text = (
        "📏 Информация о диапазонах длин волн:\n\n"
        "- Ультрафиолет (UV): 100–400 нм\n"
        "- Видимый свет: 400–700 нм\n"
        "  - Фиолетовый: 400–450 нм\n"
        "  - Синий: 450–495 нм\n"
        "  - Зеленый: 495–570 нм\n"
        "  - Желтый: 570–590 нм\n"
        "  - Оранжевый: 590–620 нм\n"
        "  - Красный: 620–700 нм\n"
        "- Инфракрасный (IR): 700 нм и выше\n\n"
        "Вы можете ввести конкретную длину волны, и я помогу определить её диапазон."
    )

    buttons = [
        [types.InlineKeyboardButton(text="🔍 Определить диапазон длины волны", callback_data="ask_wavelength")],
        [types.InlineKeyboardButton(text="Назад ↩", callback_data="calc")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    current_directory = os.getcwd()
    input_file = FSInputFile(os.path.join(current_directory, "wavelength.png"))
    await callback.message.answer_photo(photo=input_file, caption=text, reply_markup=keyboard)

    await callback.answer()

@dp.callback_query(F.data == "ask_wavelength")
async def ask_wavelength_range(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_wavelength_input)
    await callback.message.answer("🔢 Введите длину волны (в нм), и я скажу, к какому диапазону она относится.")
    await callback.answer()

@dp.message(StateFilter(Form.waiting_for_wavelength_input))
async def process_wavelength_input(message: Message):
    try:
        wavelength = float(message.text)
        wavelength_ranges = {
            "ultraviolet": {
                "name": "Ультрафиолет (UV)",
                "range": (100, 400),
                "description": "Диапазон от 100 до 400 нм, не видим человеческому глазу."
            },
            "visible": {
                "name": "Видимый свет",
                "range": (400, 700),
                "description": (
                    "Диапазон от 400 до 700 нм.\n"
                    "- Фиолетовый: 400–450 нм\n"
                    "- Синий: 450–495 нм\n"
                    "- Зеленый: 495–570 нм\n"
                    "- Желтый: 570–590 нм\n"
                    "- Оранжевый: 590–620 нм\n"
                    "- Красный: 620–700 нм"
                )
            },
            "infrared": {
                "name": "Инфракрасный (IR)",
                "range": (700, 1000),
                "description": "Диапазон от 700 нм и выше, не видим человеческому глазу."
            }
        }

        response = "Результаты по введённой длине волны:\n"
        for key, info in wavelength_ranges.items():
            min_wl, max_wl = info["range"]
            if min_wl <= wavelength <= max_wl:
                response += f"🟢 Длина волны {wavelength} нм соответствует диапазону: {info['name']}.\n{info['description']}\n"
                break
        else:
            response = f"🚫 Длина волны {wavelength} нм находится вне известных диапазонов."

        buttons = [
            [types.InlineKeyboardButton(text="Назад ↩", callback_data="wavelength_info")]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(response, reply_markup=keyboard)
    except ValueError:
        await message.answer("🚫 Пожалуйста, введите числовое значение длины волны в нанометрах (нм).")

@dp.callback_query(F.data == "fluence_calc")
async def handle_fluence_calculation(callback: types.CallbackQuery, state: FSMContext):
    """Начало процесса вычисления флюенса."""
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_fluence_calculation_average_power_input)
    await callback.message.answer("🔢 Введите среднюю мощность лазера (Вт):")
    await callback.answer()

@dp.message(StateFilter(Form.waiting_for_fluence_calculation_average_power_input))
async def process_average_power(message: Message, state):
    """Обработка средней мощности лазера."""
    try:
        average_power = float(message.text)
        if average_power == 0:
            await message.answer("🚫 Значение мощности недолжно быть 0.")
            return

        user_data[message.from_user.id] = {"average_power": average_power}
        await state.set_state(Form.waiting_for_fluence_calculation_repetition_rate_input)
        await message.answer("🔢 Введите частоту импульсов лазера (Гц):")
    except ValueError:
        await message.answer("🚫 Пожалуйста, введите числовое значение для мощности.")

@dp.message(StateFilter(Form.waiting_for_fluence_calculation_repetition_rate_input))
async def process_repetition_rate(message: Message, state):
    """Обработка частоты импульсов лазера."""
    try:
        repetition_rate = float(message.text)
        if repetition_rate == 0:
            await message.answer("🚫 Значение частоты недолжно быть 0.")
            return

        user_data[message.from_user.id]["repetition_rate"] = repetition_rate
        await state.set_state(Form.waiting_for_fluence_calculation_spot_diameter_input)
        await message.answer("🔢 Введите диаметр пятна на поверхности (см):")
    except ValueError:
        await message.answer("🚫 Пожалуйста, введите числовое значение для частоты.")

@dp.message(StateFilter(Form.waiting_for_fluence_calculation_spot_diameter_input))
async def process_spot_diameter(message: Message, state):
    """Обработка диаметра пятна лазера и расчет флюенса."""
    try:
        spot_diameter = float(message.text)
        if spot_diameter == 0:
            await message.answer("🚫 Значение диаметра недолжно 0.")
            return
        
        await fluence_calculation(message)
        await state.clear()
    except ValueError:
        await message.answer("🚫 Пожалуйста, введите числовое значение для диаметра.")

@dp.callback_query(F.data == "feedback")
async def handle_feedback(callback: types.CallbackQuery):
    await delete_previous_message(callback.message)

    text = (
        "Выберите тип отзыва:\n\n"
        "1. Анонимный 👤: ваш отзыв будет отправлен без указания вашего ID и тега пользователя. "
        "Вы можете делиться своим мнением, не раскрывая свою личность.\n\n"
        "2. Обычный 😀: ваш отзыв будет отправлен с указанием вашего ID и тега пользователя. "
        "В случае необходимости автор может связаться с вами и уточнить детали вашего отзыва. "
        "Что вам понравилось и что бы вы хотели улучшить — вы сможете описать это более подробно."
    )
    
    buttons = [
        [types.InlineKeyboardButton(text="Анонимный 👤", callback_data="feedback_type_anon")],
        [types.InlineKeyboardButton(text="Обычный 😀", callback_data="feedback_type_default")],
        [types.InlineKeyboardButton(text="Назад ↩", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "feedback_type_default")
async def handle_feedback_type_default(callback: types.CallbackQuery, state: FSMContext):
    """Начало процесса отправки обычного отзыва."""
    user_id = callback.from_user.id
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_feedback_type_default_accept)
    await callback.message.answer("🔢 Напишите ваш отзыв:")
    await callback.answer()
    user_data[user_id] = {}

@dp.message(StateFilter(Form.waiting_for_feedback_type_default_accept))
async def feedback_type_default_step2(message: types.Message, state: FSMContext):
    feedback_text = message.text
    user_id = message.from_user.id
    username = message.from_user.username

    user_data[user_id]["feedback_text"] = feedback_text

    confirmation_message = (
        f"Отзыв от @{username} (id{user_id}):\n\n"
        f"Написан {datetime.now()}\n"
        'Тип отзыва: "Обычный 😀"\n\n'
        "Текст отзыва:\n"
        f"{feedback_text}\n\n"
        "Вы уверены, что хотите отправить этот отзыв? 🤔"
    )

    buttons = [
        [types.InlineKeyboardButton(text="Да 👍", callback_data="confirm_feedback")],
        [types.InlineKeyboardButton(text="Нет, изменить ✏️", callback_data="edit_feedback")],
        [types.InlineKeyboardButton(text="Отмена ❌", callback_data="cancel_feedback")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(confirmation_message, reply_markup=keyboard)
    await state.set_state(Form.waiting_for_feedback_confirmation)

@dp.callback_query(F.data == "edit_feedback")
async def edit_feedback(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    await callback.message.answer("🔄 Вы можете изменить свой отзыв. Напишите его заново:")
    await state.set_state(Form.waiting_for_feedback_type_default_accept)

@dp.callback_query(F.data == "confirm_feedback")
async def confirm_feedback(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    username = callback.from_user.username

    feedback_text = user_data[user_id].get("feedback_text")
    is_anonymous = 0

    save_feedback(user_id, username, feedback_text, is_anonymous)
    buttons = [
        [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("🤗 Спасибо за ваш отзыв!\n\n📝 Ваш отзыв был успешно отправлен и будет рассмотрен в ближайшее время. Мы ценим ваше мнение! 🙏", reply_markup=keyboard)
    await state.clear()
    user_data.pop(user_id, None)

@dp.callback_query(F.data == "feedback_type_anon")
async def feedback_type_anon(callback: types.CallbackQuery, state: FSMContext):
    """Начало процесса отправки анонимного отзыва."""
    user_id = callback.from_user.id
    await delete_previous_message(callback.message)
    await state.set_state(Form.waiting_for_feedback_type_anon_accept)
    await callback.message.answer("🔢 Напишите ваш анонимный отзыв:")
    await callback.answer()
    user_data[user_id] = {}

@dp.message(StateFilter(Form.waiting_for_feedback_type_anon_accept))
async def feedback_type_anon_step2(message: types.Message, state: FSMContext):
    feedback_text = message.text
    user_id = message.from_user.id

    user_data[user_id]["feedback_text"] = feedback_text

    confirmation_message = (
        f"Отзыв от Аноним (id'скрыт'):\n\n"
        f"Написан {datetime.now()}\n"
        'Тип отзыва: "Анонимный 👤"\n\n'
        "Текст отзыва:\n"
        f"{feedback_text}\n\n"
        "Вы уверены, что хотите отправить этот отзыв? 🤔"
    )

    buttons = [
        [types.InlineKeyboardButton(text="Да 👍", callback_data="confirm_feedback_anon")],
        [types.InlineKeyboardButton(text="Нет, изменить ✏️", callback_data="edit_feedback_anon")],
        [types.InlineKeyboardButton(text="Отмена ❌", callback_data="cancel_feedback")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(confirmation_message, reply_markup=keyboard)
    await state.set_state(Form.waiting_for_feedback_anon_confirmation)

@dp.callback_query(F.data == "edit_feedback_anon")
async def edit_feedback_anon(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    await callback.message.answer("🔄 Вы можете изменить свой отзыв. Напишите его заново:")
    await state.set_state(Form.waiting_for_feedback_type_anon_accept)

@dp.callback_query(F.data == "confirm_feedback_anon")
async def confirm_feedback_anon(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    feedback_text = user_data[user_id].get("feedback_text")
    is_anonymous = 1

    save_feedback(None, None, feedback_text, is_anonymous)
    buttons = [
        [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("🤗 Спасибо за ваш отзыв!\n\n📝 Ваш отзыв был успешно отправлен и будет рассмотрен в ближайшее время. Мы ценим ваше мнение! 🙏", reply_markup=keyboard)
    await state.clear()
    user_data.pop(user_id, None)

@dp.callback_query(F.data == "cancel_feedback")
async def cancel_feedback_anon(callback: types.CallbackQuery, state: FSMContext):
    await delete_previous_message(callback.message)
    user_id = callback.from_user.id
    buttons = [
        [types.InlineKeyboardButton(text="🏠 В начало", callback_data="back_to_start")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Отправка отзыва отменена. ❌", reply_markup=keyboard)
    await state.clear()
    user_data.pop(user_id, None)

async def main():
    """Основная функция для запуска бота."""
    await dp.start_polling(bot)

db_start()

if __name__ == "__main__":
    asyncio.run(main())
