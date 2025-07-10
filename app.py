import os
import sqlite3
import requests
from flask import Flask, render_template, request, redirect, url_for, g, flash
from contextlib import closing
from datetime import datetime
from functools import lru_cache

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev_secret_key')

# Конфигурация
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'travelai.db')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY', 'e1d47d44ca85e82a2c63559ef9356751')
REST_COUNTRIES_URL = "https://restcountries.com/v3.1/all?fields=name,capital,flags,region,subregion,landlocked,languages,currencies,population,area"

# Функции для работы с базой данных
def get_db():
    """Устанавливает соединение с базой данных"""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

def init_db():
    """Инициализирует базу данных"""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_params TEXT NOT NULL,
                budget TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_name TEXT NOT NULL,
                capital TEXT,
                flag_url TEXT,
                weather_temp INTEGER,
                weather_desc TEXT,
                search_id INTEGER,
                notes TEXT,
                FOREIGN KEY (search_id) REFERENCES searches (id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_name TEXT NOT NULL,
                rating INTEGER,
                comment TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS travel_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_name TEXT NOT NULL,
                start_date DATE,
                end_date DATE,
                budget REAL,
                activities TEXT,
                status TEXT DEFAULT 'planned'
            )
        """)
        
        db.commit()

@app.teardown_appcontext
def close_db(error):
    """Закрывает соединение с БД при завершении"""
    if hasattr(g, 'db'):
        g.db.close()

# Инициализация базы данных при старте
if not os.path.exists(DATABASE):
    init_db()

# Функции работы с API
@lru_cache(maxsize=100)
def get_countries():
    """Получение списка стран с API"""
    try:
        response = requests.get(REST_COUNTRIES_URL, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе стран: {e}")
        return []

def get_weather(city_name):
    """Получение текущей погоды для города"""
    try:
        if not city_name:
            return None
            
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "temp": round(data["main"]["temp"]),
                "feels_like": round(data["main"]["feels_like"]),
                "humidity": data["main"]["humidity"],
                "wind": data["wind"]["speed"],
                "description": data["weather"][0]["description"].capitalize(),
                "icon": data["weather"][0]["icon"]
            }
        print(f"Ошибка погодного API: {response.status_code}")
    except Exception as e:
        print(f"Ошибка при запросе погоды: {e}")
    
    return {"temp": 25, "feels_like": 26, "humidity": 60, "wind": 3, 
            "description": "Солнечно", "icon": "01d"}

def get_upcoming_events(capital):
    """Получение ближайших событий в столице"""
    events = {
        "Paris": ["Фестиваль света (12-15 мая)", "День взятия Бастилии (14 июля)"],
        "Rome": ["Неделя моды (10-17 июня)", "Фестиваль мороженого (июль)"],
        "Berlin": ["Фестиваль пива (август)", "Рождественские ярмарки (декабрь)"],
        "Tokyo": ["Фестиваль сакуры (апрель)", "Фестиваль фейерверков (июль)"],
        "default": ["Фестиваль местной культуры", "Международный кинофестиваль"]
    }
    return events.get(capital, events["default"])[:2]

def get_travel_tips(country_name):
    """Получение советов для путешественников"""
    tips_db = {
        "France": ["Попробуйте круассаны в местных пекарнях", "Билеты в музеи лучше покупать онлайн"],
        "Italy": ["Остерегайтесь карманников в туристических местах", "Попробуйте джелато в маленьких кафе"],
        "Japan": ["Имейте при себе наличные - не везде принимают карты", "Соблюдайте очередь при входе в транспорт"],
        "default": ["Изучите местные обычаи перед поездкой", "Сохраните контакты экстренных служб"]
    }
    return tips_db.get(country_name, tips_db["default"])

# Функции работы с приложением
def save_search(search_params, budget):
    """Сохранение параметров поиска в БД"""
    try:
        db = get_db()
        
        # Проверяем соединение с БД
        if db is None:
            raise sqlite3.Error("Не удалось подключиться к базе данных")
            
        # Проверяем существование таблицы
        cursor = db.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='searches'
        """)
        if not cursor.fetchone():
            init_db()  # Пересоздаем таблицы если их нет
            
        # Вставляем данные
        cursor.execute(
            "INSERT INTO searches (search_params, budget) VALUES (?, ?)",
            (str(search_params), str(budget))  # Явное преобразование в строку
        )
        db.commit()
        
        # Проверяем, что запись добавлена
        if cursor.lastrowid is None:
            raise sqlite3.Error("Не удалось получить ID новой записи")
            
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        print(f"Ошибка SQLite при сохранении поиска: {e}")
        if 'db' in locals() and db:
            db.rollback()
        return None
    except Exception as e:
        print(f"Неожиданная ошибка при сохранении поиска: {e}")
        return None

def save_favorite(country, search_id, notes=None):
    """Сохранение избранного в БД"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            """INSERT INTO favorites 
            (country_name, capital, flag_url, weather_temp, weather_desc, search_id, notes) 
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (country['name'], country['capital'], country['flag'], 
             country['weather']['temp'], country['weather']['description'], search_id, notes)
        )
        db.commit()
        return True
    except sqlite3.Error as e:
        print(f"Ошибка при сохранении избранного: {e}")
        db.rollback()
        return False

def get_search_history(limit=10):
    """Получение истории поиска"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM searches ORDER BY timestamp DESC LIMIT ?",
            (limit,))
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Ошибка при получении истории поиска: {e}")
        return []

def save_feedback(country_name, rating, comment):
    """Сохранение отзыва о стране"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO feedback (country_name, rating, comment) VALUES (?, ?, ?)",
            (country_name, rating, comment)
        )
        db.commit()
        return True
    except sqlite3.Error as e:
        print(f"Ошибка при сохранении отзыва: {e}")
        db.rollback()
        return False

def get_country_ratings():
    """Получение средних рейтингов стран с обработкой NULL значений"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT 
                country_name, 
                COALESCE(AVG(rating), 0) as avg_rating, 
                COUNT(*) as reviews_count
            FROM feedback 
            GROUP BY country_name
        """)
        
        ratings = {}
        for row in cursor.fetchall():
            avg_rating = row['avg_rating']
            # Обеспечиваем, что avg_rating будет числом
            avg_rating = avg_rating if avg_rating is not None else 0
            ratings[row['country_name']] = {
                'rating': round(float(avg_rating), 1),  # Явное преобразование в float
                'reviews': row['reviews_count']
            }
        return ratings
        
    except sqlite3.Error as e:
        print(f"Ошибка при получении рейтингов стран: {e}")
        return {}

def estimate_budget_level(country_name):
    """Оценка уровня цен в стране"""
    cheap = ["Thailand", "Vietnam", "India", "Indonesia", "Mexico"]
    medium = ["Brazil", "Turkey", "Malaysia", "Greece", "Portugal"]
    
    if country_name in cheap:
        return 1
    elif country_name in medium:
        return 2
    return 3

def get_duration_advice(duration, country_name):
    """Советы по оптимальной длительности поездки"""
    short_trip = ["France", "Italy", "Spain", "Portugal"]
    long_trip = ["Australia", "New Zealand", "Canada", "Russia"]
    
    if duration == "weekend":
        return "Идеально для короткого визита" if country_name in short_trip else "Можно посмотреть основные достопримечательности"
    elif duration == "week":
        return "Оптимально для знакомства со страной"
    else:
        return "Отлично для глубокого изучения" if country_name in long_trip else "Хороший вариант для длительного пребывания"

def add_cost_estimation(country, duration, user_currency="USD"):
    """Примерная оценка стоимости поездки"""
    budget_level = estimate_budget_level(country["name"])
    duration_multiplier = 1 if duration == "weekend" else 3 if duration == "week" else 10
    
    base_cost = budget_level * 500 * duration_multiplier
    max_cost = base_cost * 1.5
    
    country["estimated_cost"] = f"{int(base_cost)}-{int(max_cost)} {user_currency}"
    country["duration_advice"] = get_duration_advice(duration, country["name"])
    country["budget_level"] = budget_level
    return country

def get_country_tags(country):
    """Генерация тегов для страны"""
    tags = []
    if country.get("weather", {}).get("temp", 0) > 25:
        tags.append("Жаркий климат")
    elif country.get("weather", {}).get("temp", 0) < 10:
        tags.append("Холодный климат")
    
    if country.get("landlocked"):
        tags.append("Не имеет выхода к морю")
    else:
        tags.append("Есть пляжи")
    
    if country.get("region") == "Europe":
        tags.append("Европа")
    elif country.get("region") == "Asia":
        tags.append("Азия")
    
    if country.get("languages"):
        if len(country["languages"]) > 1:
            tags.append("Многоязычная")
    
    ratings = get_country_ratings()
    if country["name"] in ratings and ratings[country["name"]]["reviews"] > 10:
        tags.append("Популярное направление")
    
    return tags[:5]

def get_backup_destinations(travel_type):
    """Запасные варианты если API не работает"""
    destinations = {
        "пляж": [
            {"name": "Мальдивы", "capital": "Мале", "flag": "https://flagcdn.com/w320/mv.png", "landlocked": False},
            {"name": "Тайланд", "capital": "Бангкок", "flag": "https://flagcdn.com/w320/th.png", "landlocked": False}
        ],
        "горы": [
            {"name": "Швейцария", "capital": "Берн", "flag": "https://flagcdn.com/w320/ch.png", "landlocked": True},
            {"name": "Непал", "capital": "Катманду", "flag": "https://flagcdn.com/w320/np.png", "landlocked": True}
        ],
        "город": [
            {"name": "Франция", "capital": "Париж", "flag": "https://flagcdn.com/w320/fr.png", "landlocked": False},
            {"name": "Япония", "capital": "Токио", "flag": "https://flagcdn.com/w320/jp.png", "landlocked": False}
        ],
        "природа": [
            {"name": "Коста-Рика", "capital": "Сан-Хосе", "flag": "https://flagcdn.com/w320/cr.png", "landlocked": False},
            {"name": "Новая Зеландия", "capital": "Веллингтон", "flag": "https://flagcdn.com/w320/nz.png", "landlocked": False}
        ]
    }
    return destinations.get(travel_type, [])

def get_favorites():
    """Получение избранных стран"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT f.id, f.country_name, f.capital, f.flag_url, f.weather_temp, 
                   f.weather_desc, f.notes, s.search_params, s.timestamp
            FROM favorites f
            JOIN searches s ON f.search_id = s.id
            ORDER BY s.timestamp DESC
        """)
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Ошибка при получении избранного: {e}")
        return []

def save_travel_plan(country_name, start_date, end_date, budget, activities):
    """Сохранение плана поездки"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO travel_plans 
            (country_name, start_date, end_date, budget, activities)
            VALUES (?, ?, ?, ?, ?)
        """, (country_name, start_date, end_date, budget, activities))
        db.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        print(f"Ошибка при сохранении плана поездки: {e}")
        db.rollback()
        return None

def get_travel_plans():
    """Получение планов поездок"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT id, country_name, start_date, end_date, budget, activities, status
            FROM travel_plans
            ORDER BY start_date DESC
        """)
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Ошибка при получении планов поездок: {e}")
        return []

# Маршруты Flask
@app.route("/")
def home():
    """Главная страница с формой поиска"""
    return render_template("index.html")

@app.route("/recommend", methods=["POST"])
def recommend():
    """Обработка формы и генерация рекомендаций"""
    travel_type = request.form.get("type")
    budget = request.form.get("budget", "1000")
    climate = request.form.get("climate", "any")
    language = request.form.get("language", "any")
    duration = request.form.get("duration", "week")
    currency = request.form.get("currency", "USD")
    
    search_params = f"{travel_type}|{budget}|{climate}|{language}|{duration}|{currency}"
    search_id = save_search(search_params, budget)
    
    if not search_id:
        flash("Ошибка при сохранении параметров поиска", "error")
        return redirect(url_for('home'))
    
    try:
        countries = get_countries()
        ratings = get_country_ratings()
        recommendations = []
        
        for country in countries[:50]:
            try:
                country_name = country.get("name", {}).get("common", "")
                capital = country.get("capital", [None])[0]
                
                if not country_name or not capital:
                    continue
                
                weather = get_weather(capital)
                
                if travel_type == "пляж" and (country.get("region") not in ["Africa", "Americas", "Asia", "Oceania"] or weather["temp"] < 20):
                    continue
                
                if climate != "any" and (
                    (climate == "warm" and weather["temp"] < 15) or
                    (climate == "cold" and weather["temp"] > 15) or
                    (climate == "tropical" and weather["temp"] < 25)
                ):
                    continue
                
                if language != "any":
                    langs = country.get("languages", {}).values()
                    if not any(lang.lower().startswith(language[:3]) for lang in langs):
                        continue
                
                country_data = {
                    "name": country_name,
                    "capital": capital,
                    "flag": country.get("flags", {}).get("png", ""),
                    "weather": weather,
                    "region": country.get("region", ""),
                    "landlocked": country.get("landlocked", False),
                    "languages": list(country.get("languages", {}).values()) if country.get("languages") else [],
                    "rating": ratings.get(country_name, {}).get("rating", 0),
                    "reviews": ratings.get(country_name, {}).get("reviews", 0),
                    "events": get_upcoming_events(capital),
                    "tips": get_travel_tips(country_name),
                    "population": country.get("population", 0),
                    "area": country.get("area", 0)
                }
                
                country_data = add_cost_estimation(country_data, duration, currency)
                country_data["tags"] = get_country_tags(country_data)
                
                recommendations.append(country_data)
            
            except Exception as e:
                print(f"Ошибка обработки страны {country_name}: {e}")
                continue
        
        if not recommendations and travel_type in ["пляж", "горы", "город", "природа"]:
            backup = get_backup_destinations(travel_type)
            recommendations = [{
                **dest, 
                "weather": {"temp": 28, "feels_like": 29, "humidity": 60, "wind": 3, "description": "Солнечно", "icon": "01d"}, 
                "budget_level": 2,
                "rating": 4.0,
                "reviews": 15,
                "events": get_upcoming_events(dest["capital"]),
                "estimated_cost": "1000-1500 USD",
                "duration_advice": get_duration_advice(duration, dest["name"]),
                "region": "Europe",
                "languages": ["Местный язык"],
                "tags": ["Популярное направление"],
                "tips": get_travel_tips(dest["name"]),
                "population": 1000000,
                "area": 100000
            } for dest in backup]
        
        recommendations.sort(key=lambda x: (
            -x["weather"]["temp"] if travel_type == "пляж" else 0,
            -x["rating"],
            x["budget_level"]
        ))
        
        if recommendations:
            save_favorite(recommendations[0], search_id)
        
        return render_template("results.html",
            recommendations=recommendations,
            travel_type=travel_type,
            budget=budget,
            climate=climate,
            language=language,
            duration=duration,
            currency=currency)
    
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        backup = get_backup_destinations(travel_type)
        return render_template("results.html",
            recommendations=[{
                **dest, 
                "weather": {"temp": 28, "feels_like": 29, "humidity": 60, "wind": 3, "description": "Солнечно", "icon": "01d"}, 
                "budget_level": 2,
                "rating": 4.0,
                "reviews": 15,
                "events": ["Фестиваль местной культуры"],
                "estimated_cost": "1000-1500 USD",
                "duration_advice": get_duration_advice(duration, dest["name"]),
                "region": "Europe",
                "languages": ["Местный язык"],
                "tags": ["Популярное направление"],
                "tips": ["Совет 1", "Совет 2"],
                "population": 1000000,
                "area": 100000
            } for dest in backup[:3]],
            travel_type=travel_type,
            budget=budget,
            climate=climate,
            language=language,
            duration=duration,
            currency=currency)

@app.route("/history")
def history():
    """Страница истории поиска"""
    searches = get_search_history()
    return render_template("history.html", searches=searches)

@app.route("/favorites")
def favorites():
    """Страница избранного"""
    favorites = get_favorites()
    return render_template("favorites.html", favorites=favorites)

@app.route("/save_note/<int:favorite_id>", methods=["POST"])
def save_note(favorite_id):
    """Сохранение заметки для избранного"""
    note = request.form.get("note")
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE favorites SET notes = ? WHERE id = ?",
            (note, favorite_id)
        )
        db.commit()
        flash('Заметка успешно сохранена', 'success')
    except sqlite3.Error as e:
        print(f"Ошибка при сохранении заметки: {e}")
        flash('Ошибка при сохранении заметки', 'error')
    
    return redirect(url_for('favorites'))

@app.route("/feedback", methods=["POST"])
def feedback():
    """Обработка отзыва о стране"""
    country_name = request.form.get("country_name")
    rating = request.form.get("rating")
    comment = request.form.get("comment", "")
    
    if save_feedback(country_name, rating, comment):
        flash('Спасибо за ваш отзыв!', 'success')
    else:
        flash('Ошибка при сохранении отзыва', 'error')
    
    return redirect(url_for('favorites'))

@app.route("/plans")
def travel_plans():
    """Страница планов поездок"""
    plans = get_travel_plans()
    return render_template("plans.html", plans=plans)

@app.route("/add_plan", methods=["POST"])
def add_plan():
    """Добавление нового плана поездки"""
    country_name = request.form.get("country_name")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    budget = request.form.get("budget")
    activities = request.form.get("activities", "")
    
    plan_id = save_travel_plan(country_name, start_date, end_date, budget, activities)
    
    if plan_id:
        flash('План поездки успешно добавлен', 'success')
    else:
        flash('Ошибка при сохранении плана поездки', 'error')
    
    return redirect(url_for('travel_plans'))

@app.route("/delete_plan/<int:plan_id>", methods=["POST"])
def delete_plan(plan_id):
    """Удаление плана поездки"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "DELETE FROM travel_plans WHERE id = ?",
            (plan_id,)
        )
        db.commit()
        flash('План поездки удален', 'success')
    except sqlite3.Error as e:
        print(f"Ошибка при удалении плана поездки: {e}")
        flash('Ошибка при удалении плана поездки', 'error')
    
    return redirect(url_for('travel_plans'))

@app.route("/country/<country_name>")
def country_detail(country_name):
    """Страница с подробной информацией о стране"""
    countries = get_countries()
    country = next((c for c in countries if c.get("name", {}).get("common") == country_name), None)
    
    if not country:
        flash('Страна не найдена', 'error')
        return redirect(url_for('home'))
    
    capital = country.get("capital", [None])[0]
    weather = get_weather(capital)
    ratings = get_country_ratings().get(country_name, {})
    
    country_data = {
        "name": country_name,
        "official_name": country.get("name", {}).get("official", country_name),
        "capital": capital,
        "flag": country.get("flags", {}).get("png", ""),
        "region": country.get("region", ""),
        "subregion": country.get("subregion", ""),
        "population": "{:,}".format(country.get("population", 0)),
        "area": "{:,}".format(country.get("area", 0)),
        "languages": list(country.get("languages", {}).values()) if country.get("languages") else [],
        "currencies": list(country.get("currencies", {}).keys()) if country.get("currencies") else [],
        "weather": weather,
        "rating": ratings.get("rating", 0),
        "reviews": ratings.get("reviews", 0),
        "events": get_upcoming_events(capital),
        "tips": get_travel_tips(country_name),
        "landlocked": country.get("landlocked", False)
    }
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT rating, comment, timestamp
        FROM feedback
        WHERE country_name = ?
        ORDER BY timestamp DESC
        LIMIT 5
    """, (country_name,))
    reviews = cursor.fetchall()
    
    return render_template("country.html", country=country_data, reviews=reviews)

if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        init_db()
    app.run(debug=True)