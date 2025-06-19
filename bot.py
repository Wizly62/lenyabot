import os
import telebot
from telebot import types
import sqlite3
from datetime import datetime
import threading
import logging
import time
from functools import lru_cache

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('psychology_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = '7396024719:AAG8nWMTOMvbyJCorRLfdaTkyoBufjPwsv0'
bot = telebot.TeleBot(BOT_TOKEN)

# База данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('psychology.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.init_db()

    def init_db(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                                user_id INTEGER PRIMARY KEY,
                                username TEXT,
                                first_name TEXT,
                                last_name TEXT,
                                register_date TEXT)''')

        self.cursor.execute('''CREATE TABLE IF NOT EXISTS test_results (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER,
                                test_name TEXT,
                                score INTEGER,
                                result TEXT,
                                interpretation TEXT,
                                test_date TEXT)''')

        self.conn.commit()

    def add_user(self, user):
        self.cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, register_date)
                               VALUES (?, ?, ?, ?, ?)''',
                            (user.id, user.username, user.first_name, user.last_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        self.conn.commit()

    def get_user(self, user_id):
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()

    def save_result(self, user_id, test_name, score, result, interpretation):
        self.cursor.execute('''INSERT INTO test_results (user_id, test_name, score, result, interpretation, test_date)
                               VALUES (?, ?, ?, ?, ?, ?)''',
                            (user_id, test_name, score, result, interpretation, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        self.conn.commit()

    def get_results(self, user_id):
        self.cursor.execute('''SELECT test_name, result, interpretation, test_date FROM test_results
                               WHERE user_id = ? ORDER BY test_date DESC''', (user_id,))
        return self.cursor.fetchall()

db = Database()

# Пользовательский кэш
user_tests = {}

# Тесты
TESTS = {
    "Темперамент": {
        "description": "Определите свой тип темперамента по Айзенку.",
        "questions": [
            "Вы часто находитесь в хорошем настроении?",
            "Вы легко знакомитесь с людьми?",
            "Вы предпочитаете действовать быстро, чем долго раздумывать?",
            "Вы любите быть в центре внимания?",
            "Вы быстро восстанавливаетесь после неудачи?"
        ],
        "scoring": {
            (0, 5): ("Меланхолик", "Склонны к самоанализу, чувствительны, замкнуты."),
            (6, 10): ("Флегматик", "Спокойны, уравновешенны, рассудительны."),
            (11, 15): ("Сангвиник", "Общительны, живо реагируют на происходящее."),
            (16, 25): ("Холерик", "Импульсивны, энергичны, быстро возбуждаются.")
        }
    },
    "Депрессия (Бек)": {
        "description": "Определение признаков депрессии.",
        "questions": [
            "Вы часто чувствуете грусть или подавленность?",
            "У вас сниженный интерес к повседневной деятельности?",
            "Вы чувствуете усталость без видимой причины?",
            "Вы часто испытываете чувство вины или никчёмности?",
            "Вы испытываете трудности с концентрацией внимания?"
        ],
        "scoring": {
            (0, 5): ("Нет депрессии", "Всё в порядке, вы в эмоциональном балансе."),
            (6, 10): ("Лёгкая депрессия", "Рекомендуется следить за состоянием, возможно стоит проконсультироваться."),
            (11, 15): ("Умеренная депрессия", "Следует обратиться за профессиональной помощью."),
            (16, 25): ("Тяжёлая депрессия", "Необходима консультация психотерапевта или врача.")
        }
    },
    "Мотивация": {
        "description": "Определите уровень вашей внутренней мотивации.",
        "questions": [
            "Вы ставите цели и следуете им?",
            "Вы продолжаете действовать, даже когда становится трудно?",
            "Вы верите в успех своего дела?",
            "Вы получаете удовольствие от процесса работы?",
            "Вы легко находите причины двигаться вперёд?"
        ],
        "scoring": {
            (0, 5): ("Низкая мотивация", "Возможно, вы устали или перегружены."),
            (6, 10): ("Средняя мотивация", "Вы справляетесь, но нуждаетесь в дополнительных источниках вдохновения."),
            (11, 15): ("Высокая мотивация", "Вы настроены на успех и готовы преодолевать трудности."),
            (16, 25): ("Очень высокая мотивация", "Вы мотивированы и заряжаете этим других.")
        }
    },
    "Стрессоустойчивость": {
        "description": "Проверьте, как вы справляетесь со стрессом.",
        "questions": [
            "Вы сохраняете спокойствие в кризисных ситуациях?",
            "Вы умеете расслабляться после трудного дня?",
            "Вы редко теряете самообладание?",
            "Вы не склонны к панике в экстренных ситуациях?",
            "Вы умеете быстро восстанавливаться после стресса?"
        ],
        "scoring": {
            (0, 5): ("Низкая устойчивость к стрессу", "Следует развивать навыки релаксации."),
            (6, 10): ("Средняя устойчивость", "Вы справляетесь, но иногда стресс берёт верх."),
            (11, 15): ("Хорошая устойчивость", "Вы умеете держать себя в руках."),
            (16, 25): ("Отличная устойчивость", "Вы — пример стрессоустойчивости!")
        }
    },
    "Самооценка": {
        "description": "Оцените уровень вашей самооценки.",
        "questions": [
            "Вы довольны собой и своими достижениями?",
            "Вы чувствуете себя достойным уважения?",
            "Вы принимаете себя таким, какой вы есть?",
            "Вы уверены в своих силах?",
            "Вы не сравниваете себя с другими постоянно?"
        ],
        "scoring": {
            (0, 5): ("Низкая самооценка", "Рекомендуется работа над уверенностью в себе."),
            (6, 10): ("Средняя самооценка", "Вы достаточно уверены, но есть пространство для роста."),
            (11, 15): ("Высокая самооценка", "Вы уверены и принимаете себя."),
            (16, 25): ("Завышенная самооценка", "Оценивайте себя трезво и честно.")
        }
    }
}

# Обработчики
@bot.message_handler(commands=['start'])
def handle_start(message):
    db.add_user(message.from_user)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🧠 Пройти тест", "👤 Мой профиль")
    bot.send_message(message.chat.id, "Добро пожаловать! Выберите действие:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🧠 Пройти тест")
def handle_tests(message):
    markup = types.InlineKeyboardMarkup()
    for name in TESTS:
        markup.add(types.InlineKeyboardButton(name, callback_data=f"test_{name}"))
    bot.send_message(message.chat.id, "Выберите тест:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('test_'))
def start_test(call):
    test_name = call.data[5:]
    user_tests[call.from_user.id] = {
        'name': test_name,
        'current': 0,
        'answers': []
    }
    send_question(call.from_user.id, call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('ans_'))
def handle_answer(call):
    answer = int(call.data[4:])
    user_id = call.from_user.id
    user_tests[user_id]['answers'].append(answer)
    user_tests[user_id]['current'] += 1
    send_question(user_id, call.message.chat.id)

def send_question(user_id, chat_id):
    test = user_tests[user_id]
    test_data = TESTS[test['name']]

    if test['current'] >= len(test_data['questions']):
        finish_test(user_id, chat_id)
        return

    question = test_data['questions'][test['current']]
    markup = types.InlineKeyboardMarkup()
    for i, label in enumerate(["Никогда", "Редко", "Иногда", "Часто", "Всегда"], 1):
        markup.add(types.InlineKeyboardButton(label, callback_data=f"ans_{i}"))

    bot.send_message(chat_id, f"{question}", reply_markup=markup)

def finish_test(user_id, chat_id):
    test = user_tests[user_id]
    total = sum(test['answers'])
    scoring = TESTS[test['name']]['scoring']
    for rng, (result, interp) in scoring.items():
        if rng[0] <= total <= rng[1]:
            db.save_result(user_id, test['name'], total, result, interp)
            bot.send_message(chat_id, f"\U0001F4CA Результат теста: <b>{test['name']}</b>\n\n<b>{result}</b>\n{interp}", parse_mode='HTML')
            break
    del user_tests[user_id]

@bot.message_handler(func=lambda m: m.text == "👤 Мой профиль")
def profile(message):
    user = db.get_user(message.from_user.id)
    results = db.get_results(message.from_user.id)
    text = f"<b>Профиль:</b>\nИмя: {user['first_name']}\nЮзернейм: @{user['username']}\n\n<b>Результаты тестов:</b>\n"
    for res in results:
        text += f"\n<b>{res['test_name']}</b> — {res['result']}\n{res['interpretation']}\nДата: {res['test_date']}\n"
    bot.send_message(message.chat.id, text, parse_mode='HTML')

# Запуск
if __name__ == '__main__':
    while True:
        try:
            logger.info("Бот запущен")
            bot.polling(none_stop=True)
        except Exception as e:
            logger.error(f"Ошибка polling: {e}")
            time.sleep(5)
