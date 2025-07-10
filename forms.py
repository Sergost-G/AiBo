from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, FloatField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange

class LoginForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    remember = BooleanField('Запомнить меня')
    submit = SubmitField('Войти')

class RegisterForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[
        DataRequired(),
        Length(min=4, max=20)
    ])
    email = StringField('Email', validators=[
        DataRequired(),
        Email()
    ])
    password = PasswordField('Пароль', validators=[
        DataRequired(),
        Length(min=6, max=30)
    ])
    confirm_password = PasswordField('Подтвердите пароль', validators=[
        DataRequired(),
        EqualTo('password')
    ])
    submit = SubmitField('Зарегистрироваться')

class ResetPasswordForm(FlaskForm):
    email = StringField('Email', validators=[
        DataRequired(),
        Email()
    ])
    submit = SubmitField('Сбросить пароль')

class SettingsForm(FlaskForm):
    notification_threshold = FloatField(
        'Порог уведомлений (%)',
        validators=[DataRequired(), NumberRange(min=0.1, max=10.0)],
        render_kw={"step": "0.1"}
    )
    preferred_exchanges = StringField(
        'Предпочитаемые биржи',
        validators=[DataRequired()],
        description='Перечислите биржи через запятую'
    )
    submit = SubmitField('Сохранить настройки')