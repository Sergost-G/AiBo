from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, session, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from database import db, User, Subscription
from forms import LoginForm, RegisterForm, ResetPasswordForm, SettingsForm
from datetime import datetime, timedelta
import os
import json
import csv
import subprocess
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///arbitrage.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Инициализация расширений
db.init_app(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Конфигурация Telegram
TELEGRAM_BOT_TOKEN = "7789215856:AAG9UcYWz2UycD-Ah9iHHZC0TOU8e0tKn3E"
TELEGRAM_PAYMENT_PROVIDER_TOKEN = "your-payment-provider-token"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('web_app.log'),
        logging.StreamHandler()
    ]
)
@app.before_request
def check_csrf():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        csrf.protect()

# Команда для инициализации БД
@app.cli.command("init-db")
def init_db():
    """Инициализирует базу данных."""
    with app.app_context():
        db.create_all()
    print("База данных инициализирована.")

# Команда для создания администратора
@app.cli.command("create-admin")
def create_admin():
    """Создает администратора"""
    username = input("Введите имя пользователя: ")
    email = input("Введите email: ")
    password = input("Введите пароль: ")
    
    with app.app_context():
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            print("Пользователь с таким именем или email уже существует")
            return
        
        admin = User(
            username=username,
            email=email,
            is_admin=True
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"Администратор {username} успешно создан!")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_arbitrage_data():
    """Получает данные из файла для веб-интерфейса"""
    try:
        with open('arbitrage_data.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Ошибка чтения данных: {e}")
        return {
            "last_update": "N/A",
            "total_pairs": 0,
            "profitable_pairs": 0,
            "top_opportunities": []
        }

# ----------- Маршруты аутентификации -----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            return redirect(url_for('dashboard'))
        else:
            flash('Неверное имя пользователя или пароль', 'danger')
    return render_template('auth/login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegisterForm()
    if form.validate_on_submit():
        # Проверяем, существует ли пользователь
        existing_user = User.query.filter(
            (User.username == form.username.data) | 
            (User.email == form.email.data)
        ).first()
        
        if existing_user:
            flash('Пользователь с таким именем или email уже существует', 'danger')
            return render_template('auth/register.html', form=form)
            
        user = User(
            username=form.username.data,
            email=form.email.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ----------- Основные маршруты -----------
@app.route('/')
@login_required
def dashboard():
    if not current_user.has_active_subscription():
        return redirect(url_for('subscribe'))
    
    data = get_arbitrage_data()
    return render_template('dashboard.html', data=data, current_year=datetime.now().year)

@app.route('/data')
@login_required
def data():
    if not current_user.has_active_subscription():
        return jsonify({"error": "Требуется подписка"}), 403
    return jsonify(get_arbitrage_data())

@app.route('/subscribe')
@login_required
def subscribe():
    if current_user.has_active_subscription():
        return redirect(url_for('dashboard'))
    return render_template('subscribe.html', bot_token=TELEGRAM_BOT_TOKEN)

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user, current_year=datetime.now().year)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = SettingsForm()
    
    if form.validate_on_submit():
        # Обновляем настройки пользователя
        current_user.notification_threshold = form.notification_threshold.data
        current_user.preferred_exchanges = form.preferred_exchanges.data
        db.session.commit()
        flash('Настройки успешно обновлены', 'success')
        return redirect(url_for('settings'))
    
    # Заполняем форму текущими значениями
    form.notification_threshold.data = current_user.notification_threshold or 2.0
    form.preferred_exchanges.data = current_user.preferred_exchanges or "Bybit,Gate,MEXC,Huobi,BingX,Bitget,OKX"
    
    return render_template('settings.html', form=form, current_year=datetime.now().year)

@app.route('/history')
@login_required
def history_page():
    """Показывает историю арбитражных сделок"""
    try:
        # Получаем список всех файлов истории
        history_files = sorted(
            [f for f in os.listdir() if f.startswith('arbitrage_log_') and f.endswith('.csv')],
            reverse=True
        )
        
        # Если файлов нет, возвращаем пустую страницу
        if not history_files:
            return render_template('history.html', history=[], files=[], current_year=datetime.now().year)
        
        # Загружаем последний файл по умолчанию
        filename = history_files[0]
        history_data = []
        
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Преобразуем числовые значения
                try:
                    row['buy_price'] = float(row.get('buy_price', 0))
                    row['sell_price'] = float(row.get('sell_price', 0))
                except (ValueError, TypeError):
                    row['buy_price'] = 0
                    row['sell_price'] = 0
                history_data.append(row)
        
        return render_template(
            'history.html', 
            history=history_data, 
            files=history_files,
            selected_file=filename,
            current_year=datetime.now().year
        )
    except Exception as e:
        logging.error(f"Ошибка чтения истории: {e}")
        flash('Ошибка при загрузке истории', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/history/download')
@login_required
def download_history():
    """Скачивает файл истории"""
    filename = request.args.get('file', f"arbitrage_log_{datetime.now().strftime('%Y%m%d')}.csv")
    
    try:
        if os.path.exists(filename):
            response = make_response(open(filename, 'rb').read())
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            return response
        else:
            flash('Файл истории не найден', 'danger')
            return redirect(url_for('history_page'))
    except Exception as e:
        logging.error(f"Ошибка скачивания истории: {e}")
        flash('Ошибка при скачивании файла', 'danger')
        return redirect(url_for('history_page'))

@app.route('/pair/<symbol>')
@login_required
def pair_details(symbol):
    data = get_arbitrage_data()
    pair_info = None
    
    # Ищем информацию о паре в данных
    for opp in data.get('top_opportunities', []):
        if opp['symbol'] == symbol:
            pair_info = opp
            break
    
    if not pair_info:
        flash('Информация о паре не найдена', 'danger')
        return redirect(url_for('dashboard'))
    
    # Дополнительная информация
    price_history = [
        {'time': '10:00', 'price': pair_info['buy_price'] * 0.98},
        {'time': '10:05', 'price': pair_info['buy_price'] * 0.99},
        {'time': '10:10', 'price': pair_info['buy_price']},
        {'time': '10:15', 'price': pair_info['buy_price'] * 1.01},
        {'time': '10:20', 'price': pair_info['buy_price'] * 1.02},
    ]
    
    exchange_comparison = [
        {'exchange': 'Binance', 'price': pair_info['buy_price'] * 1.03},
        {'exchange': 'KuCoin', 'price': pair_info['buy_price'] * 1.01},
        {'exchange': pair_info['buy_exchange'], 'price': pair_info['buy_price']},
        {'exchange': pair_info['sell_exchange'], 'price': pair_info['sell_price']},
        {'exchange': 'Huobi', 'price': pair_info['sell_price'] * 0.99},
    ]
    
    return render_template(
        'pair_details.html',
        pair=pair_info,
        price_history=price_history,
        exchange_comparison=exchange_comparison,
        current_year=datetime.now().year
    )

# ----------- API для оплаты -----------
@app.route('/create_subscription', methods=['POST'])
@login_required
def create_subscription():
    plan = request.json.get('plan')  # daily, weekly, monthly
    
    # Определяем продолжительность подписки
    if plan == 'daily':
        days = 1
        amount = 100  # 100 рублей
    elif plan == 'weekly':
        days = 7
        amount = 500
    elif plan == 'monthly':
        days = 30
        amount = 1500
    else:
        return jsonify({"error": "Неверный план"}), 400
    
    # Создаем подписку
    end_date = datetime.utcnow() + timedelta(days=days)
    
    if current_user.subscription:
        subscription = current_user.subscription
        subscription.start_date = datetime.utcnow()
        subscription.end_date = end_date
        subscription.plan = plan
    else:
        subscription = Subscription(
            user_id=current_user.id,
            start_date=datetime.utcnow(),
            end_date=end_date,
            plan=plan
        )
        db.session.add(subscription)
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Подписка оформлена!",
        "end_date": end_date.strftime("%Y-%m-%d")
    })

# ----------- Админ-панель -----------
# Переменная для хранения процесса бота
bot_process = None

def is_bot_running():
    """Проверяет, работает ли бот"""
    try:
        # Проверяем наличие файла с данными
        if not os.path.exists('arbitrage_data.json'):
            return False
            
        with open('arbitrage_data.json', 'r') as f:
            data = json.load(f)
            if data.get("last_update", "N/A") == "N/A":
                return False
                
            last_update = datetime.strptime(data["last_update"], "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - last_update).total_seconds() < 300
    except:
        return False

@app.route('/admin')
@login_required
def admin_panel():
    # Проверяем, является ли пользователь администратором
    if not current_user.is_admin:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    subscriptions = Subscription.query.all()
    bot_status = "Работает" if is_bot_running() else "Остановлен"
    
    # Передаем текущее время как 'now'
    return render_template(
    'admin.html', 
    users=users, 
    subscriptions=subscriptions,
    bot_status=bot_status,
    data=get_arbitrage_data(),
    current_year=datetime.now().year,
    datetime=datetime  # Передаем модуль datetime в шаблон
)

@app.route('/admin/update_subscription', methods=['POST'])
@login_required
def update_subscription():
    if not current_user.is_admin:
        return jsonify({"error": "Доступ запрещен"}), 403
    
    user_id = request.form.get('user_id')
    plan = request.form.get('plan')
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404
    
    # Определяем продолжительность подписки
    if plan == 'daily':
        days = 1
    elif plan == 'weekly':
        days = 7
    elif plan == 'monthly':
        days = 30
    else:
        return jsonify({"error": "Неверный план"}), 400
    
    end_date = datetime.utcnow() + timedelta(days=days)
    
    if user.subscription:
        subscription = user.subscription
        subscription.start_date = datetime.utcnow()
        subscription.end_date = end_date
        subscription.plan = plan
    else:
        subscription = Subscription(
            user_id=user.id,
            start_date=datetime.utcnow(),
            end_date=end_date,
            plan=plan
        )
        db.session.add(subscription)
    
    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"Подписка для {user.username} обновлена",
        "end_date": end_date.strftime("%Y-%m-%d")
    })

@app.route('/admin/start_bot')
@login_required
def start_bot():
    if not current_user.is_admin:
        return jsonify({"error": "Доступ запрещен"}), 403
    
    global bot_process
    
    if bot_process and bot_process.poll() is None:
        return jsonify({
            "success": False,
            "error": "Бот уже запущен"
        })
    
    try:
        # Запускаем бота в отдельном процессе
        bot_process = subprocess.Popen(['python', 'bot.py'])
        return jsonify({
            "success": True,
            "message": "Бот успешно запущен"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })

@app.route('/admin/stop_bot')
@login_required
def stop_bot():
    if not current_user.is_admin:
        return jsonify({"error": "Доступ запрещен"}), 403
    
    global bot_process
    
    if bot_process and bot_process.poll() is None:
        try:
            # Останавливаем бота
            bot_process.terminate()
            bot_process.wait(timeout=10)
            return jsonify({
                "success": True,
                "message": "Бот успешно остановлен"
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            })
    else:
        return jsonify({
            "success": False,
            "error": "Бот не запущен"
        })

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')