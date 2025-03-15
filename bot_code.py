import logging
import random
import sqlite3
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
AWAITING_PARTNER, AWAITING_MESSAGE, AWAITING_MESSAGE_TYPE = range(3)

# Создание базы данных и таблиц
def setup_database():
    conn = sqlite3.connect('couples_bot.db')
    cursor = conn.cursor()
    
    # Таблица для хранения пар пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS couples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user1_id, user2_id)
    )
    ''')
    
    # Таблица для хранения сообщений
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        couple_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        message_text TEXT NOT NULL,
        message_type TEXT NOT NULL,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (couple_id) REFERENCES couples (id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Функция для проверки существования пары
def check_couple(user_id, partner_id):
    conn = sqlite3.connect('couples_bot.db')
    cursor = conn.cursor()
    
    # Проверяем оба варианта (user1-user2 и user2-user1)
    cursor.execute('''
    SELECT id FROM couples 
    WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)
    ''', (user_id, partner_id, partner_id, user_id))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

# Функция для создания новой пары
def create_couple(user_id, partner_id):
    conn = sqlite3.connect('couples_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO couples (user1_id, user2_id)
    VALUES (?, ?)
    ''', (user_id, partner_id))
    
    couple_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return couple_id

# Функция для сохранения сообщения
def save_message(couple_id, sender_id, receiver_id, message_text, message_type):
    conn = sqlite3.connect('couples_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO messages (couple_id, sender_id, receiver_id, message_text, message_type)
    VALUES (?, ?, ?, ?, ?)
    ''', (couple_id, sender_id, receiver_id, message_text, message_type))
    
    conn.commit()
    conn.close()

# Функция для получения статистики сообщений
def get_message_stats(receiver_id):
    conn = sqlite3.connect('couples_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT message_type, COUNT(*) 
    FROM messages 
    WHERE receiver_id = ? 
    GROUP BY message_type
    ''', (receiver_id,))
    
    stats = cursor.fetchall()
    
    # Подсчет общего количества сообщений
    cursor.execute('''
    SELECT COUNT(*) 
    FROM messages 
    WHERE receiver_id = ?
    ''', (receiver_id,))
    
    total = cursor.fetchone()[0]
    conn.close()
    
    # Формируем словарь со статистикой
    result = {"total": total, "positive": 0, "negative": 0}
    for msg_type, count in stats:
        result[msg_type] = count
    
    return result

# Функция для получения случайного сообщения
def get_random_message(receiver_id):
    conn = sqlite3.connect('couples_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT message_text, message_type, sender_id 
    FROM messages 
    WHERE receiver_id = ? 
    ORDER BY RANDOM() 
    LIMIT 1
    ''', (receiver_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {"text": result[0], "type": result[1], "sender_id": result[2]}
    else:
        return None

# Список пар пользователя
def get_user_couples(user_id):
    conn = sqlite3.connect('couples_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT id, user1_id, user2_id 
    FROM couples 
    WHERE user1_id = ? OR user2_id = ?
    ''', (user_id, user_id))
    
    couples = cursor.fetchall()
    conn.close()
    
    result = []
    for couple in couples:  # Исправлено: добавлено "in couples"
        couple_id, user1, user2 = couple  # Распаковываем кортеж
        partner_id = user2 if user1 == user_id else user1
        result.append({"couple_id": couple_id, "partner_id": partner_id})
    
    return result


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Создать пару", callback_data="create_couple")],
        [InlineKeyboardButton("Мои пары", callback_data="my_couples")],
        [InlineKeyboardButton("Узнать свой ID", callback_data="get_my_id")]  # Новая кнопка
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Добро пожаловать! Этот бот позволяет создавать пары и обмениваться сообщениями.",
        reply_markup=reply_markup
    )


# Обработчик для создания пары
async def create_couple_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Отмена", callback_data="cancel_action")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text="Пожалуйста, введите ID пользователя, с которым хотите создать пару:",
        reply_markup=reply_markup
    )
    
    return AWAITING_PARTNER

# Обработчик для получения ID партнера
async def get_partner_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    try:
        partner_id = int(update.message.text)
        
        # Проверка на создание пары с самим собой
        if partner_id == user_id:
            await update.message.reply_text("Вы не можете создать пару с самим собой.")
            return ConversationHandler.END
        
        # Проверка на существующую пару
        couple_id = check_couple(user_id, partner_id)
        
        if couple_id:
            await update.message.reply_text(f"У вас уже есть пара с этим пользователем (ID пары: {couple_id}).")
        else:
            # Создаем новую пару
            couple_id = create_couple(user_id, partner_id)
            await update.message.reply_text(f"Пара успешно создана! ID пары: {couple_id}")
        
        # Предлагаем основное меню
        keyboard = [
            [InlineKeyboardButton("Создать пару", callback_data="create_couple")],
            [InlineKeyboardButton("Мои пары", callback_data="my_couples")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Что бы вы хотели сделать дальше?", reply_markup=reply_markup)
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректный ID пользователя (целое число).")
        return AWAITING_PARTNER

# Обработчик для отображения пар пользователя
async def show_user_couples(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    couples = get_user_couples(user_id)
    
    if not couples:
        await query.edit_message_text("У вас пока нет созданных пар.")
        return
    
    keyboard = []
    for couple in couples:
        keyboard.append([InlineKeyboardButton(f"Пара с ID: {couple['partner_id']}", 
                                           callback_data=f"select_couple_{couple['couple_id']}_{couple['partner_id']}")])
    
    keyboard.append([InlineKeyboardButton("Назад", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("Ваши пары:", reply_markup=reply_markup)

# Обработчик для выбора пары
async def select_couple(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    couple_id = int(data[2])
    partner_id = int(data[3])
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("Отправить сообщение", callback_data=f"send_message_{couple_id}_{partner_id}")],
        [InlineKeyboardButton("Посмотреть статистику", callback_data=f"view_stats_{couple_id}_{partner_id}")],
        [InlineKeyboardButton("Получить случайное сообщение", callback_data=f"get_random_{couple_id}_{partner_id}")],
        [InlineKeyboardButton("Назад к парам", callback_data="my_couples")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Пара с пользователем ID: {partner_id}\nВыберите действие:",
        reply_markup=reply_markup
    )

# Обработчик для отправки сообщения
async def send_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    couple_id = int(data[2])
    partner_id = int(data[3])
    
    # Сохраняем данные в контексте
    context.user_data["couple_id"] = couple_id
    context.user_data["partner_id"] = partner_id
    
    await query.edit_message_text("Введите текст сообщения:")
    
    return AWAITING_MESSAGE

# Обработчик для получения текста сообщения
async def get_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_text = update.message.text
    
    # Сохраняем текст сообщения в контексте
    context.user_data["message_text"] = message_text
    
    keyboard = [
        [
            InlineKeyboardButton("Позитивное", callback_data="message_type_positive"),
            InlineKeyboardButton("Негативное", callback_data="message_type_negative")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите тип сообщения:",
        reply_markup=reply_markup
    )
    
    return AWAITING_MESSAGE_TYPE

# Обработчик для выбора типа сообщения
async def select_message_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    message_type = query.data.split("_")[2]  # positive или negative
    couple_id = context.user_data["couple_id"]
    partner_id = context.user_data["partner_id"]
    message_text = context.user_data["message_text"]
    sender_id = update.effective_user.id
    
    # Сохраняем сообщение в базе данных
    save_message(couple_id, sender_id, partner_id, message_text, message_type)
    
    await query.edit_message_text(f"Сообщение успешно отправлено пользователю с ID: {partner_id}!")
    
    # Предлагаем основное меню
    keyboard = [
        [InlineKeyboardButton("Мои пары", callback_data="my_couples")],
        [InlineKeyboardButton("Главное меню", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Что бы вы хотели сделать дальше?", reply_markup=reply_markup)
    
    return ConversationHandler.END

# Обработчик для просмотра статистики
async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    stats = get_message_stats(user_id)
    
    await query.edit_message_text(
        f"Статистика полученных сообщений:\n"
        f"Всего: {stats['total']}\n"
        f"Позитивных: {stats['positive']}\n"
        f"Негативных: {stats['negative']}\n\n"
        "Используйте /start для возврата в главное меню."
    )

# Обработчик для получения случайного сообщения
async def get_random_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    message = get_random_message(user_id)
    
    if message:
        emoji = "🙂" if message["type"] == "positive" else "😞"
        await query.edit_message_text(
            f"{emoji} Случайное сообщение ({message['type']}):\n\n"
            f"{message['text']}\n\n"
            "Используйте /start для возврата в главное меню."
        )
    else:
        await query.edit_message_text(
            "У вас пока нет сообщений для прочтения.\n\n"
            "Используйте /start для возврата в главное меню."
        )

# Обработчик для возврата в главное меню
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Создать пару", callback_data="create_couple")],
        [InlineKeyboardButton("Мои пары", callback_data="my_couples")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "Главное меню:",
        reply_markup=reply_markup
    )

# Обработчик для отмены действий
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Действие отменено.")
    await start(update, context)  # Автоматически вызываем /start
    return ConversationHandler.END

async def cancel_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("Действие отменено.")
    return ConversationHandler.END

# Обработчики команды /id
async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(f"Ваш ID: {user_id}")

async def get_my_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Ваш ID: {user_id}",
        reply_markup=reply_markup
    )
    

# Основная функция для запуска бота
def main() -> None:
    # Инициализация базы данных
    setup_database()
    
    # Создание приложения и передача токена
    TOKEN = os.getenv("BOT_TOKEN")  # Получаем токен из переменной окружения
    application = Application.builder().token(TOKEN).build()
    
    # Создание ConversationHandler для управления состояниями
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_couple_handler, pattern="^create_couple$"),
            CallbackQueryHandler(send_message_handler, pattern="^send_message_"),
            CallbackQueryHandler(select_message_type, pattern="^message_type_")
        ],
        states={
            AWAITING_PARTNER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_id)],
            AWAITING_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_message_text)],
            AWAITING_MESSAGE_TYPE: [CallbackQueryHandler(select_message_type, pattern="^message_type_")]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(cancel_action_handler, pattern="^cancel_action$"))
    application.add_handler(CallbackQueryHandler(get_my_id_handler, pattern="^get_my_id$"))
    application.add_handler(CallbackQueryHandler(show_user_couples, pattern="^my_couples$"))
    application.add_handler(CallbackQueryHandler(select_couple, pattern="^select_couple_"))
    application.add_handler(CallbackQueryHandler(view_stats, pattern="^view_stats_"))
    application.add_handler(CallbackQueryHandler(get_random_message_handler, pattern="^get_random_"))
    application.add_handler(CallbackQueryHandler(back_to_main, pattern="^back_to_main$"))
    application.add_handler(CommandHandler("id", get_id))
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()