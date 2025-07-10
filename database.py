from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)  # Критически важное поле
    telegram_id = db.Column(db.String(50))
    telegram_link_code = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notification_threshold = db.Column(db.Float, default=2.0)
    preferred_exchanges = db.Column(db.String(200), default="Bybit,Gate,MEXC,Huobi,BingX,Bitget,OKX")
    subscription = db.relationship('Subscription', backref='user', uselist=False)
    
    def set_password(self, password):
        self.password = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def has_active_subscription(self):
        return self.subscription and self.subscription.end_date > datetime.utcnow()
    
    def generate_telegram_code(self):
        self.telegram_link_code = secrets.token_hex(3).upper()
        return self.telegram_link_code

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime)
    plan = db.Column(db.String(50))
    payment_id = db.Column(db.String(100))
    payment_confirmed = db.Column(db.Boolean, default=False)

    def is_active(self):
        return self.end_date > datetime.utcnow()
    
    def remaining_days(self):
        return (self.end_date - datetime.utcnow()).days if self.end_date else 0