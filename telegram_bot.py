import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CallbackContext
)
from database import db, User, Subscription
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "7789215856:AAG9UcYWz2UycD-Ah9iHHZC0TOU8e0tKn3E")

async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    await update.message.reply_html(
        rf"Привет {user.mention_html()}! Я бот для управления подпиской на Arbitrage Bot.",
        reply_markup=main_menu_keyboard()
    )

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("Моя подписка", callback_data='subscription')],
        [InlineKeyboardButton("Купить подписку", callback_data='buy_subscription')],
        [InlineKeyboardButton("Помощь", callback_data='help')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == 'subscription':
        await show_subscription(query)
    elif query.data == 'buy_subscription':
        await show_subscription_plans(query)
    elif query.data.startswith('plan_'):
        plan = query.data.split('_')[1]
        await process_subscription_payment(query, plan)
    elif query.data == 'help':
        await show_help(query)

async def show_subscription(query):
    user_id = query.from_user.id
    with db.session() as session:
        user = session.query(User).filter_by(telegram_id=str(user_id)).first()
        if user:
            if user.has_active_subscription():
                sub = user.subscription
                days_left = sub.remaining_days()
                message = (
                    f"✅ Ваша подписка активна!\n"
                    f"📅 Тип: {sub.plan}\n"
                    f"⏳ Действует до: {sub.end_date.strftime('%d.%m.%Y')}\n"
                    f"⏱ Осталось дней: {days_left}"
                )
            else:
                message = "❌ У вас нет активной подписки.\nНажмите 'Купить подписку' для доступа к сервису."
        else:
            message = "🔐 Вы не привязали свой аккаунт.\nПожалуйста, войдите на сайт и привяжите Telegram в профиле."

    await query.edit_message_text(
        text=message,
        reply_markup=main_menu_keyboard()
    )

async def show_subscription_plans(query):
    keyboard = [
        [InlineKeyboardButton("Дневная - 100₽", callback_data='plan_daily')],
        [InlineKeyboardButton("Недельная - 500₽", callback_data='plan_weekly')],
        [InlineKeyboardButton("Месячная - 1500₽", callback_data='plan_monthly')],
        [InlineKeyboardButton("Назад", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="Выберите тарифный план:",
        reply_markup=reply_markup
    )

async def process_subscription_payment(query, plan):
    prices = {
        'daily': 100,
        'weekly': 500,
        'monthly': 1500
    }
    
    await query.edit_message_text(
        text=f"Для оплаты подписки ({plan}) на сумму {prices[plan]}₽ перейдите по ссылке:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Оплатить", url=f"https://t.me/your_payment_bot?start={plan}_{query.from_user.id}")],
            [InlineKeyboardButton("Назад", callback_data='buy_subscription')]
        ])
    )

async def show_help(query):
    help_text = (
        "🤖 Arbitrage Bot - система мониторинга арбитражных возможностей\n\n"
        "Основные команды:\n"
        "/start - начать работу с ботом\n"
        "/subscribe - управление подпиской\n"
        "/help - показать это сообщение\n\n"
        "Для связи с поддержкой: @your_support"
    )
    await query.edit_message_text(
        text=help_text,
        reply_markup=main_menu_keyboard()
    )

async def link_account(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    code = context.args[0] if context.args else None
    
    if code:
        with db.session() as session:
            user = session.query(User).filter_by(telegram_link_code=code).first()
            if user:
                user.telegram_id = str(user_id)
                session.commit()
                await update.message.reply_text("✅ Ваш Telegram аккаунт успешно привязан!")
            else:
                await update.message.reply_text("❌ Неверный код привязки. Пожалуйста, проверьте код и попробуйте снова.")
    else:
        await update.message.reply_text("Пожалуйста, укажите код привязки после команды, например: /link ABC123")

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("link", link_account))
    application.add_handler(CallbackQueryHandler(button))
    
    application.run_polling()

if __name__ == '__main__':
    main()