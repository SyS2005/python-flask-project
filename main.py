from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, emit
import random
from string import ascii_uppercase
from datetime import datetime
import json

app = Flask(__name__)
app.config["SECRET_KEY"] = "your_secret_key"
socketio = SocketIO(app)

# Список для збереження користувачів і кімнат
users = {}
rooms = {}

# Функція для створення унікального коду кімнати
def generate_unique_code(length):
    while True:
        code = "".join(random.choices(ascii_uppercase, k=length))
        if code not in rooms:
            return code

def load_users():
    try:
        with open("users.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

# Збереження даних у файл users.json
def save_users(users):
    with open("users.json", "w") as file:
        json.dump(users, file)

# Перевірка правильності логіну
def check_user(username, password):
    users = load_users()
    return users.get(username) == password

# Головна сторінка авторизації
@app.route("/", methods=["GET", "POST"])
def home():
    users = load_users()  

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        action = request.form.get("action")

        if not username or not password:
            return render_template("home.html", error="Будь ласка, введіть ім'я та пароль.", username=username)

        if action == "register":
            if username in users:
                return render_template("home.html", error="Користувач із таким ім'ям уже існує.", username=username)
            users[username] = password  
            save_users(users)  
            return render_template("home.html", error="Реєстрація успішна! Увійдіть у систему.", username=username)

        elif action == "login":
            if not check_user(username, password):
                return render_template("home.html", error="Неправильне ім'я користувача або пароль.", username=username)

            session["username"] = username
            return redirect(url_for("dashboard"))

    return render_template("home.html")

# Панель керування кімнатами
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "username" not in session:
        return redirect(url_for("home"))

    username = session["username"]  # Отримуємо ім'я користувача з сесії

    if request.method == "POST":
        if "create" in request.form:
            # Створення нової кімнати
            code = generate_unique_code(6)
            rooms[code] = {
                            "owner": username, 
                            "members": [username],
                            "messages": [], 
                            "visible_to": [username]
                            }
            session["room"] = code
            return redirect(url_for("room"))
        elif "join" in request.form:
            code = request.form.get("code")
            if code in rooms:
                if username not in rooms[code]["visible_to"]:
                    rooms[code]["visible_to"].append(username)  # Додаємо користувача до видимості кімнати
                session["room"] = code
                return redirect(url_for("room"))
            else:
                return render_template("dashboard.html", username=username, error="Кімнати з таким кодом не існує.", rooms=rooms)
    # Фільтруємо кімнати, які видимі користувачу
    user_rooms = {code: room for code, room in rooms.items() if username in room["visible_to"]}
    return render_template("dashboard.html", username=username, rooms=user_rooms)

# Кімната для чату
@app.route("/room", methods=["GET", "POST"])
def room():
    if "room" not in session:
        return redirect(url_for("dashboard"))
    
    code = session["room"]
    if code not in rooms:
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        room_code = request.form.get("room_code")
        if room_code in rooms:
            session["room"] = room_code
            return redirect(url_for("room"))
        else:
            return render_template("room.html", error="Кімната з таким кодом не існує.", code=code, messages=rooms[code]["messages"])
    
    messages = rooms[code]["messages"]
    return render_template("room.html", code=code, messages=messages)

@app.route("/logout", methods=["POST"])
def logout():
    if "room" not in session:
        return redirect(url_for("dashboard"))

    room = session["room"]
    username = session["username"]

    if room in rooms:
        if username in rooms[room]["members"]:
            rooms[room]["members"].remove(username)  # Видаляємо користувача з кімнати

            leave_message = {
                "name": "Система",
                "message": f"{username} залишив кімнату.",
                "time": datetime.now().strftime("%H:%M:%S"),
            }
            socketio.emit("message", leave_message, to=room)
            session.pop("room", None)  # Видаляємо інформацію про кімнату з сесії
        else:
            return redirect(url_for("dashboard"))  # Користувач вже не є в кімнаті, перенаправляємо назад

    return redirect(url_for("dashboard"))

@app.route("/logout_full", methods=["POST"])
def logout_full():
    session.pop("username", None)  # Видаляє ім'я користувача з сесії
    session.pop("room", None)  # Видаляє інформацію про кімнату з сесії
    return redirect(url_for("home"))

@app.route("/join_room_from_list", methods=["POST"])
def join_room_from_list():
    if "username" not in session:
        return redirect(url_for("home"))

    code = request.form.get("code")  # Отримуємо код кімнати з форми
    if code in rooms:
        session["room"] = code  # Зберігаємо код кімнати в сесії
        return redirect(url_for("room"))  # Перенаправляємо в кімнату
    else:
        return render_template("dashboard.html", username=session["username"], rooms=rooms, error="Кімната не знайдена.")

@app.route("/delete_room", methods=["POST"])
def delete_room():
    if "username" not in session:
        return redirect(url_for("home"))

    code = request.form.get("code")  # Отримуємо код кімнати з форми
    username = session["username"]

    if code in rooms:
        if rooms[code]["owner"] == username:  # Перевірка, чи є користувач власником кімнати
            del rooms[code]  # Видаляємо кімнату зі списку
            return redirect(url_for("dashboard"))
        else:
            return render_template("dashboard.html", username=username, rooms=rooms, error="Тільки власник кімнати може її видалити.")
    else:
        return render_template("dashboard.html", username=username, rooms=rooms, error="Кімната не знайдена.")

@socketio.on("message")
def handle_message(data):
    room = session.get("room")
    if room in rooms:
        content = {
            "name": session.get("username"),
            "message": data["data"],
            "time": datetime.now().strftime("%H:%M:%S"),
        }
        rooms[room]["messages"].append(content)
        socketio.emit("message", content, to=room)

@socketio.on("join")
def join():
    room = session.get("room")
    if room in rooms:
        join_room(room)
        username = session.get("username")
        rooms[room]["members"].append(username)
        join_message = {
            "name": "Система",
            "message": f"{username} приєднався до кімнати!",
            "time": datetime.now().strftime("%H:%M:%S"),
        }
        rooms[room]["messages"].append(join_message)
        socketio.emit("message", join_message, to=room)

@socketio.on("disconnect")
def handle_disconnect():
    room = session.get("room")
    username = session.get("username")

    if not room or room not in rooms:
        return

    # Зменшуємо кількість учасників
    rooms[room]["members"].remove(username)

    # Сповіщаємо учасників кімнати
    leave_message = {
        "name": "Система",
        "message": f"{username} залишив кімнату.",
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    socketio.emit("message", leave_message, to=room)

    print(f"{username} залишив кімнату {room}")

if __name__ == "__main__":
    socketio.run(app, debug=True)
