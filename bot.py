import time
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import json
import logging
import traceback
import random
import sys
import csv
import requests  # Добавлен импорт модуля requests

# Настройка логирования
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    
    file_handler = logging.FileHandler('arbitrage_bot.log', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

setup_logging()

# Настройки
REFRESH_RATE = 30
LIQUIDITY_THRESHOLD = 0
MIN_SPREAD_THRESHOLD = 1.0
MAX_SPREAD_THRESHOLD = 10.0
MAX_PAIRS_TO_SHOW = 20
MAX_CONCURRENT_REQUESTS = 50
MAX_TRACKED_PAIRS = 200
EXCHANGES = ["Bybit", "Gate", "MEXC", "Huobi", "BingX", "Bitget", "OKX"]
DEBUG_MODE = True

# Настройки Telegram
TELEGRAM_TOKEN = "7789215856:AAG9UcYWz2UycD-Ah9iHHZC0TOU8e0tKn3E"
TELEGRAM_CHAT_ID = "234735694"
NOTIFICATION_THRESHOLD = 2.0
NOTIFICATION_COOLDOWN = 300

# Черный список монет
BLACKLIST = [
    "XEMUSDT", "SNTUSDT", "WAVESUSDT", "USDCUSDT", "TUSDUSDT", 
    "BTTUSDT", "JSTUSDT", "PERLUSDT", "NEXOUSDT", "HOTUSDT"
]

# Комиссии бирж
COMMISSIONS = {
    "Bybit": 0.0004,
    "Gate": 0.0003,
    "MEXC": 0.0004,
    "Huobi": 0.0004,
    "BingX": 0.0004,
    "Bitget": 0.0004,
    "OKX": 0.0004,
}

# Кэш для уведомлений
notification_cache = {}
spread_history = {}
CONFIG_FILE = "bot_config.json"
ARBITRAGE_DATA_FILE = "arbitrage_data.json"  # Файл для веб-интерфейса

# Задержки между запросами
EXCHANGE_DELAYS = {
    "BingX": 3.0,
    "OKX": 0.5,
    "Huobi": 0.5,
    "Bitget": 0.5,
    "Others": 0.3
}

def normalize_symbol(symbol: str) -> str:
    symbol = symbol.upper().replace('-', '').replace('_', '')
    if not symbol.endswith('USDT'):
        symbol += 'USDT'
    return symbol

def is_blacklisted(symbol):
    symbol = normalize_symbol(symbol)
    return any(black_symbol == symbol for black_symbol in BLACKLIST)

def save_config():
    config = {
        "BLACKLIST": BLACKLIST,
        "NOTIFICATION_THRESHOLD": NOTIFICATION_THRESHOLD,
        "MIN_SPREAD_THRESHOLD": MIN_SPREAD_THRESHOLD,
        "MAX_SPREAD_THRESHOLD": MAX_SPREAD_THRESHOLD,
        "LIQUIDITY_THRESHOLD": LIQUIDITY_THRESHOLD
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

def load_config():
    global BLACKLIST, NOTIFICATION_THRESHOLD, MIN_SPREAD_THRESHOLD, MAX_SPREAD_THRESHOLD, LIQUIDITY_THRESHOLD
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                BLACKLIST = config.get("BLACKLIST", BLACKLIST)
                NOTIFICATION_THRESHOLD = config.get("NOTIFICATION_THRESHOLD", NOTIFICATION_THRESHOLD)
                MIN_SPREAD_THRESHOLD = config.get("MIN_SPREAD_THRESHOLD", MIN_SPREAD_THRESHOLD)
                MAX_SPREAD_THRESHOLD = config.get("MAX_SPREAD_THRESHOLD", MAX_SPREAD_THRESHOLD)
                LIQUIDITY_THRESHOLD = config.get("LIQUIDITY_THRESHOLD", LIQUIDITY_THRESHOLD)
    except Exception as e:
        logging.error(f"Ошибка загрузки конфигурации: {e}")

def save_arbitrage_data(data):
    """Сохраняет данные для веб-интерфейса"""
    try:
        with open(ARBITRAGE_DATA_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logging.error(f"Ошибка сохранения данных: {e}")

def log_to_csv(symbol, spread, prices, best_buy, best_sell):
    try:
        filename = f"arbitrage_log_{datetime.now().strftime('%Y%m%d')}.csv"
        file_exists = os.path.isfile(filename)
        
        with open(filename, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                headers = ["timestamp", "symbol", "spread", "buy_exchange", "buy_price", 
                          "sell_exchange", "sell_price", "profit_potential"]
                writer.writerow(headers)
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            buy_price = prices.get(best_buy, 0)
            sell_price = prices.get(best_sell, 0)
            profit_potential = (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
            
            row = [
                timestamp, 
                symbol, 
                f"{spread:.4f}%", 
                best_buy, 
                buy_price,
                best_sell,
                sell_price,
                f"{profit_potential:.4f}%"
            ]
            writer.writerow(row)
    except Exception as e:
        logging.error(f"Ошибка записи в CSV: {e}")

def calculate_arbitrage_opportunity(prices):
    if not prices or len(prices) < 2:
        return None
    
    try:
        buy_exchange = min(prices, key=prices.get)
        sell_exchange = max(prices, key=prices.get)
        
        buy_price = prices[buy_exchange]
        sell_price = prices[sell_exchange]
        
        net_buy_price = buy_price * (1 + COMMISSIONS.get(buy_exchange, 0.0004))
        net_sell_price = sell_price * (1 - COMMISSIONS.get(sell_exchange, 0.0004))
        
        if net_buy_price <= 0:
            return None
            
        spread = (net_sell_price - net_buy_price) / net_buy_price * 100
        profit_potential = (sell_price - buy_price) / buy_price * 100
        
        return {
            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,
            "spread": spread,
            "profit_potential": profit_potential,
            "net_profit": net_sell_price - net_buy_price
        }
    except Exception as e:
        logging.error(f"Ошибка расчета арбитража: {e}")
        return None

# Функции для получения символов с бирж
async def get_bybit_symbols(session):
    """Получаем пары с Bybit"""
    try:
        url = "https://api.bybit.com/v5/market/tickers"
        params = {'category': 'linear'}
        async with session.get(url, params=params, timeout=20) as response:
            data = await response.json()
            symbols = []
            if 'result' in data and 'list' in data['result']:
                for item in data['result']['list']:
                    if 'symbol' in item and item['symbol'].endswith('USDT'):
                        clean_symbol = normalize_symbol(item['symbol'])
                        symbols.append(clean_symbol)
            return symbols
    except Exception as e:
        logging.error(f"Bybit symbols error: {e}")
        return []

async def get_gate_symbols(session):
    """Получаем пары с Gate.io"""
    try:
        url = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
        async with session.get(url, timeout=20) as response:
            contracts = await response.json()
            symbols = []
            for c in contracts:
                if 'name' in c:
                    clean_symbol = normalize_symbol(c['name'].replace('_USDT', 'USDT'))
                    symbols.append(clean_symbol)
            return symbols
    except Exception as e:
        logging.error(f"Gate.io symbols error: {e}")
        return []

async def get_mexc_symbols(session):
    """Получаем пары с MEXC"""
    try:
        url = "https://contract.mexc.com/api/v1/contract/ticker"
        async with session.get(url, timeout=20) as response:
            data = await response.json()
            symbols = []
            if 'data' in data:
                for item in data['data']:
                    if 'symbol' in item:
                        clean_symbol = normalize_symbol(item['symbol'].replace('_', ''))
                        symbols.append(clean_symbol)
            return symbols
    except Exception as e:
        logging.error(f"MEXC symbols error: {e}")
        return []

async def get_huobi_symbols(session):
    """Получаем пары с Huobi"""
    try:
        url = "https://api.hbdm.com/linear-swap-api/v1/swap_contract_info"
        async with session.get(url, timeout=20) as response:
            # Проверяем content-type
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                # Альтернативный API
                url = "https://api.hbdm.com/linear-swap-api/v1/swap_price_range"
                async with session.get(url, timeout=20) as response2:
                    data = await response2.json()
                    symbols = []
                    for contract in data.get('data', []):
                        symbol = normalize_symbol(contract['contract_code'])
                        symbols.append(symbol)
                    return symbols
            
            data = await response.json()
            symbols = []
            for contract in data.get('data', []):
                symbol = normalize_symbol(contract['contract_code'])
                symbols.append(symbol)
            return symbols
    except Exception as e:
        logging.error(f"Huobi symbols error: {e}")
        return []

async def get_bingx_symbols(session):
    """Получаем пары с BingX"""
    try:
        url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
        async with session.get(url, timeout=20) as response:
            data = await response.json()
            symbols = []
            if 'data' in data:
                for contract in data['data']:
                    if 'symbol' in contract and contract['symbol'].endswith('-USDT'):
                        clean_symbol = normalize_symbol(contract['symbol'].replace('-', ''))
                        symbols.append(clean_symbol)
            return symbols
    except Exception as e:
        logging.error(f"BingX symbols error: {e}")
        return []

async def get_bitget_symbols(session):
    """Получаем пары с Bitget"""
    try:
        url = "https://api.bitget.com/api/swap/v3/market/contracts"
        async with session.get(url, timeout=20) as response:
            data = await response.json()
            symbols = []
            if 'data' in data:
                for contract in data['data']:
                    if contract.get('quoteCoin') == 'USDT' and 'symbol' in contract:
                        clean_symbol = normalize_symbol(contract['symbol'])
                        symbols.append(clean_symbol)
            return symbols
    except Exception as e:
        logging.error(f"Bitget symbols error: {e}")
        return []

async def get_okx_symbols(session):
    """Получаем пары с OKX"""
    try:
        url = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
        async with session.get(url, timeout=20) as response:
            data = await response.json()
            symbols = []
            if 'data' in data:
                for item in data['data']:
                    if (item.get('instType') == 'SWAP' and 
                        'instId' in item and 
                        '-USDT-SWAP' in item['instId']):
                        clean_symbol = normalize_symbol(item['instId'].replace('-USDT-SWAP', 'USDT'))
                        symbols.append(clean_symbol)
            return symbols
    except Exception as e:
        logging.error(f"OKX symbols error: {e}")
        return []

async def fetch_symbols():
    """Асинхронно получаем все пары с бирж"""
    try:
        connector = aiohttp.TCPConnector(limit_per_host=10)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                get_bybit_symbols(session),
                get_gate_symbols(session),
                get_mexc_symbols(session),
                get_huobi_symbols(session),
                get_bingx_symbols(session),
                get_bitget_symbols(session),
                get_okx_symbols(session)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except Exception as e:
        logging.error(f"Ошибка в fetch_symbols: {e}")
        return []

def find_common_symbols(symbol_lists):
    """Находим пары, доступные хотя бы на 2 биржах"""
    symbol_counter = {}
    for symbol_list in symbol_lists:
        if not isinstance(symbol_list, list):
            continue
        for symbol in symbol_list:
            symbol = normalize_symbol(symbol)
            symbol_counter[symbol] = symbol_counter.get(symbol, 0) + 1
    
    sorted_symbols = sorted(
        [s for s, count in symbol_counter.items() if count >= 2 and not is_blacklisted(s)],
        key=lambda s: symbol_counter[s], 
        reverse=True
    )
    return sorted_symbols[:MAX_TRACKED_PAIRS]

async def get_price(session, exchange: str, symbol: str) -> float:
    symbol = normalize_symbol(symbol)
    try:
        # Добавляем задержку
        delay = EXCHANGE_DELAYS.get(exchange, EXCHANGE_DELAYS["Others"])
        await asyncio.sleep(delay + random.uniform(0, 0.5))
        
        timeout = 15
        if exchange == "Bybit":
            url = "https://api.bybit.com/v5/market/tickers"
            params = {'category': 'linear', 'symbol': symbol}
            async with session.get(url, params=params, timeout=timeout) as response:
                if response.status != 200:
                    return 0.0
                data = await response.json()
                if 'result' in data and 'list' in data['result'] and len(data['result']['list']) > 0:
                    return float(data['result']['list'][0]['lastPrice'])
        
        elif exchange == "Gate":
            gate_symbol = symbol.replace('USDT', '_USDT')
            url = f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={gate_symbol}"
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return 0.0
                data = await response.json()
                if isinstance(data, list) and len(data) > 0 and 'last' in data[0]:
                    return float(data[0]['last'])
        
        elif exchange == "MEXC":
            mexc_symbol = symbol.replace('USDT', '_USDT')
            url = f"https://contract.mexc.com/api/v1/contract/ticker?symbol={mexc_symbol}"
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return 0.0
                data = await response.json()
                if 'data' in data and 'lastPrice' in data['data']:
                    return float(data['data']['lastPrice'])
        
        elif exchange == "Huobi":
            huobi_symbol = symbol.replace('USDT', '-USDT')
            url = f"https://api.hbdm.com/linear-swap-ex/market/detail/merged?contract_code={huobi_symbol}"
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return 0.0
                data = await response.json()
                if 'tick' in data and 'close' in data['tick']:
                    return float(data['tick']['close'])
                
        elif exchange == "BingX":
            bingx_symbol = symbol[:-4] + '-' + symbol[-4:]
            url = f"https://open-api.bingx.com/openApi/swap/v2/quote/ticker?contract={bingx_symbol}"
            
            # Повторные попытки для BingX
            for attempt in range(3):
                try:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 429:
                            wait_time = (attempt + 1) * 10  # 10, 20, 30 секунд
                            logging.warning(f"BingX: 429 для {symbol}, попытка {attempt+1}/3, жду {wait_time} сек.")
                            await asyncio.sleep(wait_time)
                            continue
                        if response.status != 200:
                            return 0.0
                        data = await response.json()
                        if 'data' in data and 'lastPrice' in data['data']:
                            return float(data['data']['lastPrice'])
                        return 0.0
                except Exception as e:
                    logging.debug(f"Ошибка BingX {symbol}: {e}")
                    await asyncio.sleep(5)
            return 0.0
                
        elif exchange == "Bitget":
            url = f"https://api.bitget.com/api/swap/v3/market/ticker?symbol={symbol}"
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return 0.0
                data = await response.json()
                if 'data' in data and data['data'] is not None and 'last' in data['data']:
                    return float(data['data']['last'])
                
        elif exchange == "OKX":
            okx_symbol = symbol.replace('USDT', '-USDT-SWAP')
            url = f"https://www.okx.com/api/v5/market/ticker?instId={okx_symbol}"
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return 0.0
                data = await response.json()
                if 'data' in data and isinstance(data['data'], list) and len(data['data']) > 0 and 'last' in data['data'][0]:
                    return float(data['data'][0]['last'])
        
        return 0.0
        
    except aiohttp.ClientError as e:
        logging.debug(f"Сетевая ошибка {exchange} для {symbol}: {str(e)}")
        return 0.0
    except Exception as e:
        logging.debug(f"Ошибка {exchange} для {symbol}: {str(e)}")
        return 0.0

async def process_symbol(session, symbol, semaphore):
    async with semaphore:
        try:
            prices = {}
            for exchange in EXCHANGES:
                try:
                    price = await get_price(session, exchange, symbol)
                    if price > 0:
                        prices[exchange] = price
                except Exception as e:
                    logging.debug(f"Ошибка {exchange} для {symbol}: {str(e)}")
            return symbol, prices
        except Exception as e:
            logging.error(f"Ошибка обработки символа {symbol}: {e}")
            return symbol, {}

def send_telegram_alert(message: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=15)
        return response.status_code == 200
    except Exception as e:
        logging.error(f"Ошибка отправки в Telegram: {e}")
        return False

async def main():
    global MAX_TRACKED_PAIRS
    load_config()
    logging.info("🚀 Запуск арбитражного бота (режим всех пар)")
    logging.info(f"⚡ Автообновление: каждые {REFRESH_RATE} сек.")
    logging.info(f"🔔 Уведомления при спреде > {NOTIFICATION_THRESHOLD}%")
    logging.info(f"🔍 Биржи: {', '.join(EXCHANGES)}")
    logging.info(f"🔢 Макс. отслеживаемых пар: {MAX_TRACKED_PAIRS}")
    
    try:
        # Первоначальный сбор пар
        logging.info("🔄 Получение списка торговых пар...")
        symbol_lists = await fetch_symbols()
        
        # Проверка результатов
        for i, result in enumerate(symbol_lists):
            if isinstance(result, Exception):
                logging.error(f"Ошибка при получении символов с биржи {EXCHANGES[i]}: {str(result)}")
            elif not isinstance(result, list):
                logging.warning(f"Биржа {EXCHANGES[i]} вернула не список: {type(result)}")
        
        all_symbols = find_common_symbols(symbol_lists)
        logging.info(f"🟢 Отслеживаем {len(all_symbols)} пар")
        
        last_symbol_update = datetime.now()
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        cycle_count = 0
        
        while True:
            cycle_start = time.time()
            cycle_count += 1
            logging.info(f"🔄 Цикл {cycle_count} начат")
            
            # Обновляем список пар каждые 30 минут
            if datetime.now() - last_symbol_update > timedelta(minutes=30):
                logging.info("🔄 Обновление списка пар...")
                symbol_lists = await fetch_symbols()
                all_symbols = find_common_symbols(symbol_lists)
                last_symbol_update = datetime.now()
                logging.info(f"🟢 Обновлено: {len(all_symbols)} пар")
            
            # Получение цен
            results = []
            connector = aiohttp.TCPConnector(limit_per_host=10)
            async with aiohttp.ClientSession(connector=connector) as session:
                tasks = [process_symbol(session, symbol, semaphore) for symbol in all_symbols]
                results = await asyncio.gather(*tasks)
            
            # Анализ результатов
            profitable_pairs = []
            web_data = {
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_pairs": len(all_symbols),
                "profitable_pairs": 0,
                "top_opportunities": []
            }
            
            for symbol, prices in results:
                if len(prices) < 2:
                    continue
                
                arb_data = calculate_arbitrage_opportunity(prices)
                if not arb_data:
                    continue
                    
                spread = arb_data["spread"]
                
                if MIN_SPREAD_THRESHOLD <= spread <= MAX_SPREAD_THRESHOLD:
                    profitable_pairs.append((symbol, prices, arb_data))
                    
                    # Отправка уведомлений
                    if spread >= NOTIFICATION_THRESHOLD:
                        last_notified = notification_cache.get(symbol, 0)
                        current_time = time.time()
                        if current_time - last_notified > NOTIFICATION_COOLDOWN:
                            message = (
                                f"🚨 Арбитраж: {symbol}\n"
                                f"📊 Спред: {spread:.2f}%\n"
                                f"💰 Купить на: {arb_data['buy_exchange']} - {prices[arb_data['buy_exchange']]:.6f}\n"
                                f"💰 Продать на: {arb_data['sell_exchange']} - {prices[arb_data['sell_exchange']]:.6f}"
                            )
                            if send_telegram_alert(message):
                                logging.info(f"📢 Уведомление для {symbol} (спред: {spread:.2f}%)")
                                notification_cache[symbol] = current_time
                                log_to_csv(symbol, spread, prices, 
                                          arb_data["buy_exchange"], 
                                          arb_data["sell_exchange"])
            
            # Сохранение данных для веб-интерфейса
            web_data["profitable_pairs"] = len(profitable_pairs)
            if profitable_pairs:
                profitable_pairs.sort(key=lambda x: x[2]["spread"], reverse=True)
                web_data["top_opportunities"] = [
                    {
                        "symbol": symbol,
                        "spread": f"{arb_data['spread']:.2f}%",
                        "buy_exchange": arb_data['buy_exchange'],
                        "sell_exchange": arb_data['sell_exchange'],
                        "buy_price": prices[arb_data['buy_exchange']],
                        "sell_price": prices[arb_data['sell_exchange']]
                    }
                    for symbol, prices, arb_data in profitable_pairs[:10]
                ]
            
            save_arbitrage_data(web_data)
            
            # Вывод результатов
            profitable_count = len(profitable_pairs)
            logging.info(f"🔍 Найдено выгодных пар: {profitable_count}")
            
            # Динамическая регулировка количества пар
            if profitable_count < 10:
                MAX_TRACKED_PAIRS = min(2500, MAX_TRACKED_PAIRS + 100)
                logging.info(f"🔼 Увеличиваем макс. пар до {MAX_TRACKED_PAIRS}")
            elif profitable_count > 30:
                MAX_TRACKED_PAIRS = max(100, MAX_TRACKED_PAIRS - 20)
                logging.info(f"🔽 Уменьшаем макс. пар до {MAX_TRACKED_PAIRS}")
            
            if profitable_pairs:
                for symbol, prices, arb_data in profitable_pairs[:MAX_PAIRS_TO_SHOW]:
                    logging.info(f"📈 {symbol}: спред {arb_data['spread']:.2f}%")
            
            # Время до следующего обновления
            processing_time = time.time() - cycle_start
            next_update = max(10, REFRESH_RATE - processing_time)
            logging.info(f"⏱ Обработка заняла {processing_time:.1f} сек., следующее обновление через {next_update:.1f} сек.")
            await asyncio.sleep(next_update)
            
    except KeyboardInterrupt:
        logging.info("🛑 Работа бота остановлена пользователем")
    except Exception as e:
        logging.error(f"🔥 Критическая ошибка: {e}")
        logging.error(traceback.format_exc())
    finally:
        save_config()
        logging.info("✅ Конфигурация сохранена")

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            logging.info("Бот завершил работу")
        else:
            logging.error(f"Ошибка запуска: {e}")
    except Exception as e:
        logging.error(f"Необработанная ошибка: {e}")