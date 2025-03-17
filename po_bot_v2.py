import asyncio
import base64
import json
import operator
import os
import platform
import random
import sys
import uuid
from datetime import datetime, timedelta
from tkinter import *
import tkinter as tk
from tkinter import ttk

import requests
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException, InvalidSessionIdException
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc

# -----------------------------------------------------
# CONFIGURACIÓN Y VARIABLES GLOBALES
# -----------------------------------------------------
ops = {
    '>': operator.gt,
    '<': operator.lt,
}

URL = 'https://pocket2.click/cabinet/quick-high-low?utm_campaign=764482&utm_source=affiliate&utm_medium=sr&a=6SpfiwSUVHtSu3&ac=flixuy'
BASE_URL = 'https://policensor.com'
ASSETS_URL = f'{BASE_URL}/assets/'
CANDLES_URL = f'{BASE_URL}/close_candles/'
LIMIT_TRADES_URL = f'{BASE_URL}/limit_trades/'
SERVER_STRATEGIES_URL = f'{BASE_URL}/server_strategies/'
PRODUCT_ID = 'prod_RWzyaFqdRawZim'
LICENSE_BUY_URL = "https://u2.shortink.io/register?utm_campaign=764482&utm_source=affiliate&utm_medium=sr&a=6SpfiwSUVHtSu3&ac=flixuy"
PERIOD = 1

ASSETS = {}
CANDLES = {}
ACTIONS = {}
LICENSE_VALID = False
TRADES = 0
TRADING_ALLOWED = True
CURRENT_ASSET = None
FAVORITES_REANIMATED = False
SETTINGS = {}
MARTINGALE_LIST = []
MARTINGALE_LAST_ACTION_ENDS_AT = datetime.now()
MARTINGALE_AMOUNT_SET = False
MARTINGALE_INITIAL = True
MARTINGALE_MAP = {True: 'normal', False: 'disabled'}
NUMBERS = {
    '0': '11',
    '1': '7',
    '2': '8',
    '3': '9',
    '4': '4',
    '5': '5',
    '6': '6',
    '7': '1',
    '8': '2',
    '9': '3',
}
INITIAL_DEPOSIT = None
SETTINGS_PATH = 'settings.txt'
SERVER_STRATEGIES = {}

# -----------------------------------------------------
# FUNCIONES DE DRIVER, LOG Y UTILIDADES
# -----------------------------------------------------
async def get_driver():
    options = uc.ChromeOptions()
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-certificate-errors-spki-list')
    username = os.environ.get('USER', os.environ.get('USERNAME'))
    os_platform = platform.platform().lower()
    if 'macos' in os_platform:
        path_default = fr'/Users/{username}/Library/Application Support/Google/Chrome/Trading Bot Profile'
    elif 'windows' in os_platform:
        path_default = fr'C:\Users\{username}\AppData\Local\Google\Chrome\User Data\Trading Bot Profile'
    elif 'linux' in os_platform:
        path_default = '~/.config/google-chrome/Trading Bot Profile'
    else:
        path_default = ''
    options.add_argument(fr'--user-data-dir={path_default}')
    driver = uc.Chrome(options=options)
    return driver

def log(*args):
    print(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), *args)

async def get_email(driver):
    try:
        info_email = driver.find_element(By.CLASS_NAME, 'info__email')
        email = info_email.find_element(By.TAG_NAME, 'div').get_attribute('data-hd-show')
        if '@' in email:
            return email
    except Exception as e:
        log("Error al obtener email:", e)
    return None

# -----------------------------------------------------
# SISTEMA DE LICENCIAS BASADO EN UID (REFERIDOS)
# -----------------------------------------------------
def get_authorized_uids():
    try:
        response = requests.get("https://flixertrade.online/authorized_uids.json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("authorized_uids", [])
    except Exception as e:
        log("Error al obtener la lista de UIDs autorizados:", e)
    return []

async def validate_license(driver):
    global LICENSE_VALID
    try:
        uid_element = driver.find_element(By.CSS_SELECTOR, "div.js-hd[data-hd-show^='id']")
        uid_text = uid_element.get_attribute("data-hd-show")
        uid = uid_text.replace("id", "").strip()
        authorized_uids = get_authorized_uids()
        if uid in authorized_uids:
            LICENSE_VALID = True
            log("Licencia válida. UID autorizado:", uid)
        else:
            LICENSE_VALID = False
            log("Licencia NO válida. UID no autorizado:", uid)
            log("Redirigiendo a la pasarela de registro...")
            driver.get("https://flixertrade.online/registro.html")
            while True:
                await asyncio.sleep(60)
    except Exception as e:
        log("Error en la validación de licencia:", e)
        driver.get("https://flixertrade.online/registro.html")
        while True:
            await asyncio.sleep(60)

# -----------------------------------------------------
# INTERFAZ GRÁFICA DE ESTADO (GUI) PARA CONFIGURACIÓN
# -----------------------------------------------------
def show_status_window(estado, mensaje, countdown=180):
    window = tk.Tk()
    window.title("Estado del Bot - FlixerBot_v2")
    window.geometry("500x300")
    window.resizable(False, False)

    lbl_estado = tk.Label(window, text=f"Estado: {estado}", font=("Segoe UI", 16, "bold"))
    lbl_estado.pack(pady=20)

    lbl_mensaje = tk.Label(window, text=mensaje, font=("Segoe UI", 12), wraplength=450, justify="center")
    lbl_mensaje.pack(pady=10)

    progress = ttk.Progressbar(window, orient="horizontal", length=400, mode="determinate")
    progress.pack(pady=20)
    
    lbl_count = tk.Label(window, text="", font=("Segoe UI", 12))
    lbl_count.pack(pady=10)

    def update_progress(remaining):
        progress['maximum'] = countdown
        progress['value'] = countdown - remaining
        lbl_count.config(text=f"Iniciando en {remaining} seg")
        if remaining > 0:
            window.after(1000, update_progress, remaining - 1)
        else:
            window.destroy()

    update_progress(countdown)
    window.mainloop()

# -----------------------------------------------------
# FUNCIONES PARA ESPERAR INICIO DE SESIÓN Y CONFIGURAR
# -----------------------------------------------------
async def wait_for_login(driver, timeout=180):
    start_time = datetime.now()
    while (datetime.now() - start_time).seconds < timeout:
        try:
            uid_element = driver.find_element(By.CSS_SELECTOR, "div.js-hd[data-hd-show^='id']")
            if uid_element:
                return True
        except Exception:
            pass
        await asyncio.sleep(5)
    return False

async def configuration_countdown(duration=180):
    log("Por favor, configura: agrega activos a operar a favoritos, configura el tiempo de expiración y el monto de operación.")
    log("El bot iniciará operaciones en 3 minutos.")
    for remaining in range(duration, 0, -1):
        percent = ((duration - remaining) / duration) * 100
        bar_length = 20
        filled = int(percent / (100 / bar_length))
        bar = "[" + "#" * filled + " " * (bar_length - filled) + "]"
        print(f"\rIniciando en {remaining:3d} seg {bar} {percent:5.1f}%", end="")
        await asyncio.sleep(1)
    print("\nConfiguración completada, iniciando operaciones...")

# -----------------------------------------------------
# FUNCIONES DE ESTRATEGIA Y OPERACIONES (SIN CAMBIOS)
# -----------------------------------------------------
async def websocket_log(driver):
    global ASSETS, PERIOD, CANDLES, ACTIONS, TRADES, CURRENT_ASSET, FAVORITES_REANIMATED, TRADING_ALLOWED, SERVER_STRATEGIES
    try:
        logs = driver.get_log('performance')
    except InvalidSessionIdException:
        log("Chrome session is invalid (closed). Exiting websocket_log.")
        raise
    for wsData in logs:
        try:
            message = json.loads(wsData['message'])['message']
        except Exception:
            continue
        response = message.get('params', {}).get('response', {})
        if response.get('opcode', 0) == 2:
            try:
                payload_str = base64.b64decode(response['payloadData']).decode('utf-8')
                data = json.loads(payload_str)
            except Exception:
                continue
            if 'history' in data:
                if not CURRENT_ASSET:
                    CURRENT_ASSET = data['asset']
                if PERIOD != data['period']:
                    PERIOD = data['period']
                    CANDLES = {}
                    ACTIONS = {}
                    FAVORITES_REANIMATED = False
                candles = list(reversed(data['candles']))
                for tstamp, value in data['history']:
                    tstamp = int(float(tstamp))
                    candle = [tstamp, value, value, value, value]
                    if value > candle[3]:
                        candle[3] = value
                    if value < candle[4]:
                        candle[4] = value
                    if tstamp % PERIOD == 0:
                        if tstamp not in [c[0] for c in candles]:
                            candles.append([tstamp, value, value, value, value])
                CANDLES[data['asset']] = candles
            try:
                asset = data[0][0]
                candles = CANDLES[asset]
                current_value = data[0][2]
                candles[-1][2] = current_value
                if current_value > candles[-1][3]:
                    candles[-1][3] = current_value
                if current_value < candles[-1][4]:
                    candles[-1][4] = current_value
                tstamp = int(float(data[0][1]))
                if tstamp % PERIOD == 0:
                    if tstamp not in [c[0] for c in candles]:
                        candles.append([tstamp, current_value, current_value, current_value, current_value])
            except Exception:
                pass
    if not FAVORITES_REANIMATED:
        try:
            await reanimate_favorites(driver)
        except:
            pass

async def reanimate_favorites(driver):
    global CURRENT_ASSET, FAVORITES_REANIMATED
    asset_items = driver.find_elements(By.CLASS_NAME, 'assets-favorites-item')
    for item in asset_items:
        while True:
            if 'assets-favorites-item--active' in item.get_attribute('class'):
                CURRENT_ASSET = item.get_attribute('data-id')
                break
            if 'assets-favorites-item--not-active' in item.get_attribute('class'):
                break
            try:
                item.click()
                FAVORITES_REANIMATED = True
            except ElementNotInteractableException:
                log(f"Asset {item.get_attribute('data-id')} is out of reach.")
                break

async def switch_to_asset(driver, asset):
    global CURRENT_ASSET
    asset_items = driver.find_elements(By.CLASS_NAME, 'assets-favorites-item')
    for item in asset_items:
        if item.get_attribute('data-id') != asset:
            continue
        while True:
            await asyncio.sleep(0.1)
            if 'assets-favorites-item--active' in item.get_attribute('class'):
                CURRENT_ASSET = asset
                return True
            try:
                item.click()
            except:
                log(f'Asset {asset} is out of reach.')
                return False
    if asset == CURRENT_ASSET:
        return True

async def check_payout(driver, asset):
    global ACTIONS
    payout = driver.find_element(By.CLASS_NAME, 'value__val-start').text
    if int(payout[1:-1]) >= SETTINGS['MIN_PAYOUT']:
        return True
    log(f'Payout {payout[1:]} is not allowed for asset {asset}')
    ACTIONS[asset] = datetime.now() + timedelta(minutes=1)
    return False

async def check_trades():
    global TRADING_ALLOWED
    return True

async def create_order(driver, action, asset, sstrategy=None):
    global ACTIONS
    if ACTIONS.get(asset) and ACTIONS[asset] + timedelta(seconds=PERIOD * 2) > datetime.now():
        return False
    try:
        switch = await switch_to_asset(driver, asset)
        if not switch:
            return False
        ok_payout = await check_payout(driver, asset)
        if not ok_payout:
            return False
        trading_allowed = await check_trades()
        if not trading_allowed:
            requests.post(LIMIT_TRADES_URL)
            email = await get_email(driver)
            log(f'Max daily trades reached. Para continuar, adquiere una licencia: {LICENSE_BUY_URL}')
            driver.get(LICENSE_BUY_URL)
            return False
        vice_versa = sstrategy['vice_versa'] if sstrategy else SETTINGS['VICE_VERSA']
        if vice_versa:
            action = 'call' if action == 'put' else 'put'
        driver.find_element(by=By.CLASS_NAME, value=f'btn-{action}').click()
        ACTIONS[asset] = datetime.now()
        message = f'{action.capitalize()} on asset: {asset}'
        if sstrategy:
            message += f' made by server strategy with profit {sstrategy["profit"]}%'
        log(message)
    except Exception as e:
        log("Can't create order:", e)
        return False
    return True

async def calculate_last_wma(candles, period):
    if len(candles) < period:
        raise ValueError('Not enough data points to calculate WMA.')
    weights = list(range(1, period + 1))
    weighted_prices = [candles[i] * weights[i] for i in range(-period, 0)]
    return sum(weighted_prices) / sum(weights)

async def calculate_last_ema(candles, period, multiplier):
    if len(candles) < period:
        raise ValueError("Not enough data points to calculate EMA.")
    sma = sum(candles[:period]) / period
    ema = sma
    for price in candles[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

async def moving_averages_cross(candles, sstrategy=None):
    fast_ma = sstrategy['fast_ma'] if sstrategy else SETTINGS['FAST_MA']
    fast_ma_type = sstrategy['fast_ma_type'] if sstrategy else SETTINGS.get('FAST_MA_TYPE', 'SMA')
    slow_ma = sstrategy['slow_ma'] if sstrategy else SETTINGS['SLOW_MA']
    slow_ma_type = sstrategy['slow_ma_type'] if sstrategy else SETTINGS.get('SLOW_MA_TYPE', 'SMA')
    candles = [c[2] for c in candles]
    if fast_ma >= slow_ma:
        log("Moving averages 'fast' can't be bigger than 'slow'")
        return None
    if fast_ma_type == 'EMA':
        multiplier = 2 / (fast_ma + 1)
        fast_ma_previous = await calculate_last_ema(candles[-fast_ma-10:-1], fast_ma, multiplier)
        fast_ma_current = (candles[-1] - fast_ma_previous) * multiplier + fast_ma_previous
    elif fast_ma_type == 'WMA':
        fast_ma_previous = await calculate_last_wma(candles[-fast_ma-10:-1], fast_ma)
        fast_ma_current = await calculate_last_wma(candles[-fast_ma-9:], fast_ma)
    else:
        fast_ma_previous = sum(candles[-fast_ma-1:-1]) / fast_ma
        fast_ma_current = sum(candles[-fast_ma:]) / fast_ma
    if slow_ma_type == 'EMA':
        multiplier = 2 / (slow_ma + 1)
        slow_ma_previous = await calculate_last_ema(candles[-slow_ma-10:-1], slow_ma, multiplier)
        slow_ma_current = (candles[-1] - slow_ma_previous) * multiplier + slow_ma_previous
    elif slow_ma_type == 'WMA':
        slow_ma_previous = await calculate_last_wma(candles[-slow_ma-10:-1], slow_ma)
        slow_ma_current = await calculate_last_wma(candles[-slow_ma-9:], slow_ma)
    else:
        slow_ma_previous = sum(candles[-slow_ma-1:-1]) / slow_ma
        slow_ma_current = sum(candles[-slow_ma:]) / slow_ma
    try:
        if fast_ma_previous < slow_ma_previous and fast_ma_current > slow_ma_current:
            return 'call'
        elif fast_ma_previous > slow_ma_previous and fast_ma_current < slow_ma_current:
            return 'put'
    except Exception as e:
        log(e)
    return None

async def get_rsi(candles, sstrategy=None):
    period = sstrategy['rsi_period'] if sstrategy else SETTINGS['RSI_PERIOD']
    candles = [c[2] for c in candles]
    if len(candles) < period + 1:
        raise ValueError("Not enough data to calculate RSI.")
    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = candles[i] - candles[i - 1]
        if delta > 0:
            gains.append(delta)
        else:
            losses.append(abs(delta))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rsi_values = [None] * period
    if avg_loss == 0:
        rsi_values.append(100)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))
    for i in range(period + 1, len(candles)):
        delta = candles[i] - candles[i - 1]
        gain = max(delta, 0)
        loss = abs(min(delta, 0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        rsi_values.append(rsi)
    return rsi_values

def get_rsi_lower(rsi_upper):
    return 100 - rsi_upper

def get_rsi_put_sign(call_sign):
    return '<' if call_sign == '>' else '>'

async def rsi_strategy(candles, action, sstrategy=None):
    rsi = await get_rsi(candles)
    rsi_upper = sstrategy['rsi_upper'] if sstrategy else SETTINGS.get('RSI_UPPER')
    rsi_lower = get_rsi_lower(rsi_upper)
    call_sign = sstrategy['rsi_call_sign'] if sstrategy else SETTINGS.get('RSI_CALL_SIGN', '>')
    put_sign = get_rsi_put_sign(call_sign)
    if action == 'call' and ops[call_sign](rsi[-1], rsi_upper):
        return 'call'
    elif action == 'put' and ops[put_sign](rsi[-1], rsi_lower):
        return 'put'
    return None

async def get_price_action(candles, action):
    if action == 'call':
        if candles[-1][2] > candles[-3][2]:
            return action
    elif action == 'put':
        if candles[-1][2] < candles[-3][2]:
            return action
    return None

async def set_amount_icon(driver):
    amount_style = driver.find_element(By.CSS_SELECTOR, "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control-buttons__wrapper > div > a")
    try:
        amount_style.find_element(By.CLASS_NAME, 'currency-icon--usd')
    except NoSuchElementException:
        amount_style.click()

async def set_estimation_icon(driver):
    time_style = driver.find_element(By.CSS_SELECTOR, "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control-buttons__wrapper > div > a > div > div > svg")
    if 'exp-mode-2.svg' in time_style.get_attribute('data-src'):
        time_style.click()

async def get_estimation(driver):
    estimation = driver.find_element(By.CSS_SELECTOR, "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control__value.value.value--several-items")
    est = datetime.strptime(estimation.text, '%H:%M:%S')
    return (est.hour * 3600) + (est.minute * 60) + est.second

async def hand_delay():
    await asyncio.sleep(random.choice([0.2, 0.3, 0.4, 0.5, 0.6]))

async def check_indicators(driver):
    global MARTINGALE_LAST_ACTION_ENDS_AT, MARTINGALE_AMOUNT_SET, MARTINGALE_INITIAL
    MARTINGALE_LIST = SETTINGS.get('MARTINGALE_LIST')
    base = "#modal-root > div > div > div > div > div.trading-panel-modal__in > div.virtual-keyboard > div > div:nth-child(%s) > div"
    if SETTINGS.get('MARTINGALE_ENABLED') and MARTINGALE_INITIAL:
        try:
            await set_amount_icon(driver)
            amount = driver.find_element(By.CSS_SELECTOR, "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control__value.value.value--several-items > div > input[type=text]")
            amount_value = int(float(amount.get_attribute('value').replace(',', '')))
            if amount_value != MARTINGALE_LIST[0]:
                amount.click()
                for number in str(MARTINGALE_LIST[0]):
                    driver.find_element(By.CSS_SELECTOR, base % NUMBERS[number]).click()
                    await hand_delay()
            MARTINGALE_INITIAL = False
            MARTINGALE_AMOUNT_SET = True
        except:
            return
        return
    if SETTINGS.get('MARTINGALE_ENABLED') and MARTINGALE_LAST_ACTION_ENDS_AT + timedelta(seconds=4) > datetime.now():
        return
    if SETTINGS.get('MARTINGALE_ENABLED') and not MARTINGALE_AMOUNT_SET:
        try:
            deposit = driver.find_element(By.CSS_SELECTOR, 'body > div.wrapper > div.wrapper__top > header > div.right-block.js-right-block > div.right-block__item.js-drop-down-modal-open > div > div.balance-info-block__data > div.balance-info-block__balance > span')
        except Exception as e:
            log(e)
        try:
            closed_tab = driver.find_element(By.CSS_SELECTOR, '#bar-chart > div > div > div.right-widget-container > div > div.widget-slot__header > div.divider > ul > li:nth-child(2) > a')
            closed_tab_parent = closed_tab.find_element(By.XPATH, '..')
            if closed_tab_parent.get_attribute('class') == '':
                closed_tab_parent.click()
        except:
            pass
        await set_amount_icon(driver)
        closed_trades = driver.find_elements(By.CLASS_NAME, 'deals-list__item')
        if closed_trades:
            last_split = closed_trades[0].text.split('\n')
            try:
                amount = driver.find_element(By.CSS_SELECTOR, "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control__value.value.value--several-items > div > input[type=text]")
                amount_value = int(float(amount.get_attribute('value').replace(',', '')))
                if '$0' != last_split[4] and '$\u202f0' != last_split[4]:
                    if amount_value > MARTINGALE_LIST[0]:
                        amount.click()
                        await hand_delay()
                        for number in str(MARTINGALE_LIST[0]):
                            driver.find_element(By.CSS_SELECTOR, base % NUMBERS[number]).click()
                            await hand_delay()
                elif '$0' != last_split[3] and '$\u202f0' != last_split[3]:
                    pass
                else:
                    amount.click()
                    await asyncio.sleep(random.choice([0.6, 0.7, 0.8, 0.9, 1.0, 1.1]))
                    if amount_value in MARTINGALE_LIST and MARTINGALE_LIST.index(amount_value) + 1 < len(MARTINGALE_LIST):
                        next_amount = MARTINGALE_LIST[MARTINGALE_LIST.index(amount_value) + 1]
                        if next_amount > float(deposit.text.replace(',', '')):
                            log('Martingale cannot be set: deposit is less than next Martingale value.')
                            return
                        for number in str(next_amount):
                            driver.find_element(By.CSS_SELECTOR, base % NUMBERS[number]).click()
                            await hand_delay()
                    else:
                        for number in str(MARTINGALE_LIST[0]):
                            driver.find_element(By.CSS_SELECTOR, base % NUMBERS[number]).click()
                            await hand_delay()
                closed_tab_parent.click()
            except Exception as e:
                log(e)
        MARTINGALE_AMOUNT_SET = True
    action = None
    sstrategy = None
    for asset, candles in CANDLES.items():
        if SETTINGS.get('USE_SERVER_STRATEGIES') and asset in SERVER_STRATEGIES and len(SERVER_STRATEGIES[asset]) > 0 and PERIOD == 60:
            for sstrategy in SERVER_STRATEGIES[asset]:
                action = await check_strategies(candles, sstrategy=sstrategy)
                if action:
                    continue
        else:
            action = await check_strategies(candles, sstrategy=None)
        if not action:
            continue
        order_created = await create_order(driver, action, asset, sstrategy=sstrategy)
        if order_created:
            if SETTINGS.get('MARTINGALE_ENABLED'):
                await set_estimation_icon(driver)
                seconds = await get_estimation(driver)
                MARTINGALE_LAST_ACTION_ENDS_AT = datetime.now() + timedelta(seconds=seconds)
                MARTINGALE_AMOUNT_SET = False
            await asyncio.sleep(1)
            return

async def check_deposit(driver):
    global INITIAL_DEPOSIT, TRADING_ALLOWED
    try:
        deposit_elem = driver.find_element(By.CSS_SELECTOR, 'body > div.wrapper > div.wrapper__top > header > div.right-block.js-right-block > div.right-block__item.js-drop-down-modal-open > div > div.balance-info-block__data > div.balance-info-block__balance > span')
        deposit_text = deposit_elem.text.replace(',', '').strip()
        if '*' in deposit_text:
            log("Saldo enmascarado recibido:", deposit_text)
            return
        deposit = float(deposit_text)
    except Exception as e:
        log("No se pudo leer el saldo. Error:", e)
        return
    if INITIAL_DEPOSIT is None:
        INITIAL_DEPOSIT = deposit
        log(f'Initial deposit: {INITIAL_DEPOSIT}')
        await asyncio.sleep(1)
        return
    if SETTINGS.get('TAKE_PROFIT_ENABLED'):
        if deposit > INITIAL_DEPOSIT + SETTINGS.get('TAKE_PROFIT', 100):
            log(f'Take profit reached, trading stopped. Initial deposit: {INITIAL_DEPOSIT}, current deposit: {deposit}')
            TRADING_ALLOWED = False
    if SETTINGS.get('STOP_LOSS_ENABLED'):
        if deposit < INITIAL_DEPOSIT - SETTINGS.get('STOP_LOSS', 50):
            log(f'Stop loss reached, trading stopped. Initial deposit: {INITIAL_DEPOSIT}, current deposit: {deposit}')
            TRADING_ALLOWED = False

async def check_strategies(candles, sstrategy=None):
    action = await moving_averages_cross(candles, sstrategy=sstrategy)
    if not action:
        return
    rsi_enabled = True if sstrategy else SETTINGS.get('RSI_ENABLED')
    if rsi_enabled:
        action = await rsi_strategy(candles, action, sstrategy=sstrategy)
        if not action:
            return
    return action

async def get_candles_yfinance(email, asset, timeframe):
    response = requests.get(CANDLES_URL, params={'asset': asset, 'email': email})
    if response.status_code != 200:
        raise Exception(response.json()['error'])
    candles = [['', '', c] for c in response.json()[asset]]
    return candles

async def backtest(email, timeframe='1m'):
    assets = requests.get(ASSETS_URL, params={'email': email})
    if assets.status_code != 200:
        log(assets.json()['error'])
        return
    PROFITS = []
    for asset in assets.json()['assets']:
        await asyncio.sleep(0.7)
        try:
            candles = await get_candles_yfinance(email, asset, timeframe=timeframe)
        except:
            log(f'Backtest on {asset} with {timeframe} timeframe! No candles available, try later.')
            continue
        if not candles:
            log(f'Backtest on {asset} with {timeframe} timeframe! No candles available, try later.')
            continue
        size = max(SETTINGS['SLOW_MA'], SETTINGS['RSI_PERIOD']) + 11
        actions = {}
        for i in range(size, len(candles) + 1):
            candles_part = candles[i-size:i]
            action = await check_strategies(candles_part)
            if action:
                if SETTINGS['VICE_VERSA']:
                    action = 'call' if action == 'put' else 'put'
                actions[i] = action
        per = int(len(candles) / len(actions))
        log(f'Backtest on {asset} with {timeframe} timeframe! Frequency: 1 order per {per} candles. ')
        for estimation in [1, 2, 3]:
            wins = 0
            draws = 0
            for i, action in actions.items():
                try:
                    if candles[i][2] == candles[i+estimation][2]:
                        draws += 1
                    if action == 'call' and candles[i][2] < candles[i+estimation][2]:
                        wins += 1
                    elif action == 'put' and candles[i][2] > candles[i+estimation][2]:
                        wins += 1
                except IndexError:
                    pass
            try:
                profit = wins * 100 // (len(actions) - draws)
                PROFITS.append(profit)
                log(f'By estimation of {estimation} candles, profit is {profit}%')
            except ZeroDivisionError:
                log(f'No trades.')
                continue
    log(f'Backtest average profit for all assets: {sum(PROFITS) // len(PROFITS)}%')
    log('Backtest ended, trading...')

# -----------------------------------------------------
# FUNCIÓN PRINCIPAL CON ESPERA Y CONFIGURACIÓN
# -----------------------------------------------------
async def main():
    driver = await get_driver()
    driver.get(URL)
    await asyncio.sleep(5)
    log("Esperando hasta 3 minutos para que se inicie sesión en Pocket Option...")
    logged_in = await wait_for_login(driver, timeout=180)
    if not logged_in:
        log("No se ha iniciado sesión en 3 minutos. Redirigiendo a la pasarela de registro.")
        driver.get("https://flixertrade.online/registro.html")
        while True:
            await asyncio.sleep(60)
    await validate_license(driver)
    if LICENSE_VALID:
        # Muestra una ventana de estado en forma de aplicación (Tkinter) con barra de progreso para 3 minutos.
        show_status_window(
            estado="Autorizado",
            mensaje="Por favor, configura:\n1. Agrega los activos a operar a favoritos.\n2. Configura el tiempo de expiración.\n3. Configura el monto de operación.",
            countdown=180
        )
    else:
        # En caso de no tener licencia, validate_license ya redirige a la pasarela.
        pass
    while True:
        try:
            if not TRADING_ALLOWED:
                await asyncio.sleep(1)
                continue
            await websocket_log(driver)
            await check_indicators(driver)
            await check_deposit(driver)
            await asyncio.sleep(1)
        except InvalidSessionIdException:
            log("Chrome session closed. Exiting main loop.")
            break
        except Exception as e:
            log("Exception caught in main loop:", e)
            await asyncio.sleep(1)

# -----------------------------------------------------
# FUNCIONES DE WAIT Y OVERLAY (AHORA SOLO EN CONSOLA)
# -----------------------------------------------------
async def wait_for_login(driver, timeout=180):
    start_time = datetime.now()
    while (datetime.now() - start_time).seconds < timeout:
        try:
            uid_element = driver.find_element(By.CSS_SELECTOR, "div.js-hd[data-hd-show^='id']")
            if uid_element:
                return True
        except Exception:
            pass
        await asyncio.sleep(5)
    return False

# -----------------------------------------------------
# FUNCIONES DE SETTINGS Y TKINTER PARA CONFIGURAR EL BOT
# -----------------------------------------------------
def cleanup_martingale_list(value):
    value = value.replace(' ', '')
    value_list = value.split(',')
    value_list = [int(v) for v in value_list]
    if len(value_list) < 2 or value_list[0] < 1 or value_list[0] > 19999 or value_list[-1] > 20000:
        raise
    martingale_list = []
    for i, v in enumerate(value_list):
        if i == 0:
            martingale_list.append(v)
        elif i < len(value_list):
            if value_list[i-1] < value_list[i]:
                martingale_list.append(v)
            else:
                raise
    return martingale_list

def read_settings():
    global SETTINGS
    try:
        with open(SETTINGS_PATH, 'r') as settings_file:
            for line in settings_file.readlines():
                parts = line.replace('\n', '').split(':')
                setting = parts[0]
                setting_type = parts[1]
                split = setting.split('=')
                value = split[1]
                if setting_type == 'bool':
                    value = True if value == 'True' else False
                elif setting_type == 'int':
                    value = int(value)
                elif setting_type == 'str':
                    if split[0] == 'MARTINGALE_LIST':
                        value = cleanup_martingale_list(value)
                    else:
                        value = value
                SETTINGS[split[0]] = value
    except FileNotFoundError as e:
        log(f'Settings.txt not found, creating it. Error: {e}')

def save_settings(**kwargs):
    global SETTINGS
    with open(SETTINGS_PATH, 'w') as settings_file:
        for setting, value in kwargs.items():
            if setting == 'MARTINGALE_LIST':
                SETTINGS[setting] = cleanup_martingale_list(value)
            else:
                SETTINGS[setting] = value
            settings_file.write(f"{setting}={value}:{type(value).__name__}\n")

def tkinter_run():
    global window
    window = Tk()
    window.geometry('550x250')
    window.title('FlixerBot_v2')
    read_settings()

    def enable_rsi():
        for el in [ent_rsi_period, lbl_rsi_period, lbl_rsi_call, lbl_rsi_put, rsi_upper_drop, ent_rsi_upper]:
            el.config(state='normal' if chk_rsi_var.get() else 'disabled')

    def enable_take_profit():
        ent_take_profit.config(state='normal' if chk_take_prof.get() else 'disabled')

    def enable_stop_loss():
        ent_stop_loss.config(state='normal' if chk_stop_lo.get() else 'disabled')

    def set_rsi_lower_sign(*args):
        rsi_lower_sign.set('<' if rsi_upper_sign.get() == '>' else '>')

    def set_rsi_lower(*args):
        try:
            value = rsi_upper_val.get()
            if value > 99:
                raise
            rsi_lower_val.set(100 - int(value))
        except:
            pass

    radio_var = IntVar()
    radio_var.set(1)
    Label(window, text='Strategies').grid(column=0, row=0)
    Radiobutton(window, text='Moving Averages Crossing', variable=radio_var, value=1, justify='left', anchor='w').grid(
        column=0, row=3, sticky=W)

    lbl_fast_ma = Label(window, text='Fast', justify='left')
    lbl_fast_ma.grid(column=0, row=4, sticky=W)
    fast_ma_type = StringVar(window)
    fast_ma_type.set(SETTINGS.get('FAST_MA_TYPE', 'SMA'))
    fast_ma_drop = OptionMenu(window, fast_ma_type, 'SMA', 'EMA', 'WMA')
    fast_ma_drop.grid(column=0, row=4)
    fast_ma_val = IntVar(value=SETTINGS.get('FAST_MA', 3))
    ent_fast_ma = Entry(window, width=2, justify='right', textvariable=fast_ma_val)
    ent_fast_ma.grid(column=0, row=4, sticky=E)

    lbl_slow_ma = Label(window, text='Slow', justify='left')
    lbl_slow_ma.grid(column=0, row=5, sticky=W)
    slow_ma_type = StringVar(window)
    slow_ma_type.set(SETTINGS.get('SLOW_MA_TYPE', 'SMA'))
    slow_ma_drop = OptionMenu(window, slow_ma_type, 'SMA', 'EMA', 'WMA')
    slow_ma_drop.grid(column=0, row=5)
    slow_ma_val = IntVar(value=SETTINGS.get('SLOW_MA', 8))
    ent_slow_ma = Entry(window, width=2, justify='right', textvariable=slow_ma_val)
    ent_slow_ma.grid(column=0, row=5, sticky=E)

    chk_rsi_var = IntVar()
    chk_rsi = Checkbutton(window, text='RSI', variable=chk_rsi_var, justify='left', anchor='w', command=enable_rsi)
    if SETTINGS.get('RSI_ENABLED', False) is True:
        chk_rsi.select()
    chk_rsi.grid(column=0, row=6, sticky=W)
    rsi_period_val = IntVar(value=SETTINGS.get('RSI_PERIOD', 14))
    ent_rsi_period = Entry(window, width=2, justify='right', textvariable=rsi_period_val)
    ent_rsi_period.config(state='normal' if chk_rsi_var.get() else 'disabled')
    ent_rsi_period.grid(column=0, row=6, sticky=E)
    lbl_rsi_period = Label(window, text='period')
    lbl_rsi_period.config(state='normal' if chk_rsi_var.get() else 'disabled')
    lbl_rsi_period.grid(column=0, row=6)
    lbl_rsi_call = Label(window, text='Call if RSI', justify='left')
    lbl_rsi_call.config(state='normal' if chk_rsi_var.get() else 'disabled')
    lbl_rsi_call.grid(column=0, row=7, sticky=W)
    rsi_upper_sign = StringVar(window)
    rsi_upper_sign.set(SETTINGS.get('RSI_CALL_SIGN', '>'))
    rsi_upper_drop = OptionMenu(window, rsi_upper_sign, '>', '<')
    rsi_upper_drop.config(state='normal' if chk_rsi_var.get() else 'disabled', disabledforeground='black')
    rsi_upper_drop.grid(column=0, row=7)
    rsi_upper_sign.trace_add('write', set_rsi_lower_sign)
    rsi_upper_val = IntVar(value=SETTINGS.get('RSI_UPPER', 70))
    ent_rsi_upper = Entry(window, width=2, justify='right', textvariable=rsi_upper_val)
    ent_rsi_upper.config(state='normal' if chk_rsi_var.get() else 'disabled')
    ent_rsi_upper.grid(column=0, row=7, sticky=E)
    rsi_upper_val.trace_add('write', set_rsi_lower)
    lbl_rsi_put = Label(window, text='Put if RSI', justify='left')
    lbl_rsi_put.config(state='normal' if chk_rsi_var.get() else 'disabled')
    lbl_rsi_put.grid(column=0, row=8, sticky=W)
    rsi_lower_sign = StringVar(window)
    rsi_lower_sign.set(get_rsi_put_sign(SETTINGS.get('RSI_CALL_SIGN', '>')))
    rsi_lower_drop = OptionMenu(window, rsi_lower_sign, '>', '<')
    rsi_lower_drop.config(state='disabled', disabledforeground='black')
    rsi_lower_drop.grid(column=0, row=8)
    rsi_lower_val = IntVar(value=get_rsi_lower(int(SETTINGS.get('RSI_UPPER', 70))))
    ent_rsi_lower = Entry(window, width=2, justify='right', textvariable=rsi_lower_val, state='disabled')
    ent_rsi_lower.grid(column=0, row=8, sticky=E)

    Label(window, text='   ').grid(column=1, row=0)
    Label(window, text='Options').grid(column=2, row=0)
    Label(window, text='Min payout %', justify='left').grid(column=2, row=3, sticky=W)
    ent_min_payout = Entry(window, width=2, justify='right', textvariable=IntVar(value=SETTINGS.get('MIN_PAYOUT', 92)))
    ent_min_payout.grid(column=2, row=3, sticky=E)

    chk_take_prof = IntVar()
    chk_take_profit = Checkbutton(window, text='Take profit $', variable=chk_take_prof, justify='left', anchor='w', command=enable_take_profit)
    if SETTINGS.get('TAKE_PROFIT_ENABLED', False) is True:
        chk_take_profit.select()
    chk_take_profit.grid(column=2, row=4, sticky=W)
    take_profit_val = IntVar(value=SETTINGS.get('TAKE_PROFIT', 100))
    ent_take_profit = Entry(window, width=3, justify='right', textvariable=take_profit_val)
    ent_take_profit.config(state='normal' if chk_take_prof.get() else 'disabled')
    ent_take_profit.grid(column=2, row=4, sticky=E)

    chk_stop_lo = IntVar()
    chk_stop_loss = Checkbutton(window, text='Stop loss $', variable=chk_stop_lo, justify='left', anchor='w', command=enable_stop_loss)
    if SETTINGS.get('STOP_LOSS_ENABLED', False) is True:
        chk_stop_loss.select()
    chk_stop_loss.grid(column=2, row=5, sticky=W)
    stop_loss_val = IntVar(value=SETTINGS.get('STOP_LOSS', 50))
    ent_stop_loss = Entry(window, width=3, justify='right', textvariable=stop_loss_val)
    ent_stop_loss.config(state='normal' if chk_stop_lo.get() else 'disabled')
    ent_stop_loss.grid(column=2, row=5, sticky=E)

    chk_var = IntVar()
    chk_vice_versa = Checkbutton(window, text='Vice versa Call <-> Put', justify='left', variable=chk_var)
    if SETTINGS.get('VICE_VERSA', False) is True:
        chk_vice_versa.select()
    chk_vice_versa.grid(column=2, row=6, sticky=W)

    def enable_martingale():
        if chk_mar.get():
            ent_mar.config(state='normal')
        else:
            ent_mar.config(state='disabled')

    chk_back = IntVar()
    chk_backtest = Checkbutton(window, text='Backtesting', variable=chk_back, justify='left', anchor='w')
    if SETTINGS.get('BACKTEST', False) is True:
        chk_backtest.select()
    chk_backtest.grid(column=2, row=7, sticky=W)

    chk_serv = IntVar()
    chk_server = Checkbutton(window, text='Use server strategies', variable=chk_serv, justify='left', anchor='w')
    if SETTINGS.get('USE_SERVER_STRATEGIES', False) is True:
        chk_server.select()
    chk_server.grid(column=2, row=8, sticky=W)

    Label(window, text='   ').grid(column=3, row=0)
    Label(window, text='Martingale').grid(column=4, row=0)
    chk_mar = IntVar()
    chk_martingale = Checkbutton(window, text='Use Martingale list', justify='left', anchor='w', variable=chk_mar, command=enable_martingale)
    if SETTINGS.get('MARTINGALE_ENABLED', False) is True:
        chk_martingale.select()
    chk_martingale.grid(column=4, row=3, sticky=W)
    mar_value = ', '.join([str(v) for v in SETTINGS.get('MARTINGALE_LIST', [1, 3, 7, 15, 32, 67])])
    ent_mar = Entry(window, width=16, textvariable=StringVar(value=mar_value), state='normal' if SETTINGS.get('MARTINGALE_ENABLED') else 'disabled')
    ent_mar.grid(column=4, row=4)

    def validate_int(value, min_=1, max_=10000):
        if not value.isdigit():
            return False
        if int(value) < min_ or int(value) > max_:
            return False
        return True

    def validate_list(value):
        try:
            cleanup_martingale_list(value)
        except:
            return False
        return True

    def run():
        error_variable.set('')
        if not validate_int(ent_fast_ma.get(), 1, 99):
            error_variable.set('Fast MA: debe ser un número de 1 a 99')
            return
        if not validate_int(ent_slow_ma.get(), 1, 99):
            error_variable.set('Slow MA: debe ser un número de 1 a 99')
            return
        if int(ent_fast_ma.get()) > int(ent_slow_ma.get()):
            error_variable.set('Fast MA no puede ser mayor que Slow MA')
            return
        if not validate_int(ent_min_payout.get(), 20, 92):
            error_variable.set('Min Payout: debe ser un número de 20 a 92')
            return
        if chk_mar.get() and not validate_list(ent_mar.get()):
            error_variable.set('Martingale list: debe ser una lista separada por comas con números crecientes')
            return
        if chk_rsi_var.get() and not validate_int(ent_rsi_period.get(), 1, 20):
            error_variable.set('RSI period: debe ser un número de 1 a 20')
            return
        if chk_rsi_var.get() and not validate_int(ent_rsi_upper.get(), 1, 99):
            error_variable.set('RSI: debe ser un número de 1 a 99')
            return
        if chk_take_prof.get() and not validate_int(ent_take_profit.get(), 1, 20000):
            error_variable.set('Take profit: debe ser un número de 1 a 20000')
            return
        if chk_stop_lo.get() and not validate_int(ent_stop_loss.get(), 1, 20000):
            error_variable.set('Stop loss: debe ser un número de 1 a 20000')
            return
        save_settings(
            FAST_MA=int(ent_fast_ma.get()),
            FAST_MA_TYPE=fast_ma_type.get(),
            SLOW_MA=int(ent_slow_ma.get()),
            SLOW_MA_TYPE=slow_ma_type.get(),
            MIN_PAYOUT=int(ent_min_payout.get()),
            VICE_VERSA=True if chk_var.get() else False,
            MARTINGALE_ENABLED=True if chk_mar.get() else False,
            MARTINGALE_LIST=ent_mar.get() if chk_mar.get() else mar_value,
            RSI_ENABLED=True if chk_rsi_var.get() else False,
            RSI_PERIOD=rsi_period_val.get() if chk_rsi_var.get() else SETTINGS.get('RSI_PERIOD', 14),
            RSI_UPPER=rsi_upper_val.get() if chk_rsi_var.get() else SETTINGS.get('RSI_UPPER', 70),
            RSI_CALL_SIGN=rsi_upper_sign.get() if chk_rsi_var.get() else SETTINGS.get('RSI_CALL_SIGN', '>'),
            BACKTEST=True if chk_back.get() else False,
            TAKE_PROFIT_ENABLED=True if chk_take_prof.get() else False,
            TAKE_PROFIT=take_profit_val.get() if chk_take_prof.get() else SETTINGS.get('TAKE_PROFIT', 100),
            STOP_LOSS_ENABLED=True if chk_stop_lo.get() else False,
            STOP_LOSS=stop_loss_val.get() if chk_stop_lo.get() else SETTINGS.get('STOP_LOSS', 50),
            USE_SERVER_STRATEGIES=True if chk_serv.get() else False,
        )
        window.destroy()
        return

    def on_close():
        window.destroy()
        sys.exit()

    error_variable = StringVar()
    lbl_error = Label(window, textvariable=error_variable, justify='left', anchor='w', fg='#f00')
    lbl_error.grid(column=0, columnspan=4, row=19, sticky=W)
    btn = Button(window, text="¡FlixerBot, hazme rico!", command=run)
    btn.grid(column=0, row=20)
    window.protocol("WM_DELETE_WINDOW", on_close)
    window.mainloop()

if __name__ == '__main__':
    tkinter_run()
    read_settings()
    asyncio.run(main())
