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
from tkinter import ttk, messagebox
import queue
import threading
import requests
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException, InvalidSessionIdException
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
import shutil
import subprocess
import time

# -------------------------------
# CONFIGURACIÓN PERSISTENTE (JSON)
# -------------------------------
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "FAST_MA": 3,
    "FAST_MA_TYPE": "SMA",
    "SLOW_MA": 8,
    "SLOW_MA_TYPE": "SMA",
    "MIN_PAYOUT": 80,
    "VICE_VERSA": False,
    "MARTINGALE_ENABLED": False,
    "MARTINGALE_LIST": [1, 2, 4, 8],
    "RSI_ENABLED": True,
    "RSI_PERIOD": 14,
    "RSI_UPPER": 70,
    "RSI_CALL_SIGN": ">",
    "TAKE_PROFIT_ENABLED": False,
    "TAKE_PROFIT": 100,
    "STOP_LOSS_ENABLED": False,
    "STOP_LOSS": 50,
    "USE_SERVER_STRATEGIES": False,
    "COMBINED_STRATEGY_ENABLED": False,
    "USE_RSI": True,
    "USE_MACD": False,
    "USE_BOLLINGER": False
}
SETTINGS = {}

def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            loaded = json.load(f)
        SETTINGS = DEFAULT_SETTINGS.copy()
        SETTINGS.update(loaded)
    else:
        SETTINGS = DEFAULT_SETTINGS.copy()
        save_settings(**SETTINGS)

def save_settings(**kwargs):
    global SETTINGS
    SETTINGS.update(kwargs)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(SETTINGS, f, indent=4)

# -------------------------------
# VERSION Y AUTO-ACTUALIZACIÓN
# -------------------------------
__version__ = "2.0.9"

def version_tuple(v):
    return tuple(map(int, (v.split("."))))

def check_for_updates():
    UPDATE_URL = "https://flixertrade.online/update/version.json"
    try:
        r = requests.get(UPDATE_URL, timeout=5)
        if r.status_code == 200:
            data = r.json()
            remote_version = data.get("version")
            download_url = data.get("download_url")
            if remote_version and download_url and version_tuple(remote_version) > version_tuple(__version__):
                log(f"Nueva versión disponible: {remote_version}. Iniciando actualización...")
                update_response = requests.get(download_url, timeout=10)
                if update_response.status_code == 200:
                    if not getattr(sys, 'frozen', False):
                        with open(sys.argv[0], "wb") as f:
                            f.write(update_response.content)
                        log("Actualización aplicada. Reinicia el bot para usar la nueva versión.")
                        sys.exit(0)
                    else:
                        current_exe = sys.executable
                        temp_exe = current_exe + ".new"
                        update_script = "update_script.bat"
                        with open(temp_exe, "wb") as f:
                            f.write(update_response.content)
                        log("Actualización descargada. Creando script de actualización...")
                        with open(update_script, "w") as f:
                            f.write(f"""@echo off
taskkill /F /IM {os.path.basename(current_exe)} >nul 2>&1
timeout /t 5 >nul
move /Y "{temp_exe}" "{current_exe}" >nul 2>&1
start "" "{current_exe}"
del "%~f0"
""".strip())
                        log("Cerrando bot para completar la actualización...")
                        time.sleep(1)
                        subprocess.Popen(update_script, shell=True)
                        sys.exit(0)
                else:
                    log("Error al descargar la actualización.")
                    raise Exception("Actualización fallida. Bot desactivado.")
        else:
            log("No se pudo comprobar la actualización.")
            raise Exception("No se pudo comprobar la actualización. Bot desactivado.")
    except Exception as e:
        log(f"Fallo en la comprobación de actualización: {e}")
        raise e

# -------------------------------
# VARIABLES GLOBALES Y CONFIGURACIÓN DEL BOT
# -------------------------------
ops = { '>': operator.gt, '<': operator.lt }
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
MARTINGALE_LIST = []
MARTINGALE_LAST_ACTION_ENDS_AT = datetime.now()
MARTINGALE_AMOUNT_SET = False
MARTINGALE_INITIAL = True
FIRST_TRADE_DONE = False  # NUEVA VARIABLE PARA EVITAR USAR OPERACIÓN HISTÓRICA EN LA PRIMERA ORDEN
MARTINGALE_MAP = {True: 'normal', False: 'disabled'}
NUMBERS = {'0': '11', '1': '7', '2': '8', '3': '9', '4': '4', '5': '5', '6': '6', '7': '1', '8': '2', '9': '3'}
INITIAL_DEPOSIT = None

# -------------------------------
# COLA PARA LOGS (GUI TIEMPO REAL)
# -------------------------------
log_queue = queue.Queue()
def log(*args):
    message = datetime.now().strftime('%Y-%m-%d %H:%M:%S') + " " + " ".join(map(str, args))
    print(message)
    try:
        with open("bot.log", "a") as f:
            f.write(message + "\n")
    except Exception:
        pass
    log_queue.put(message)

# -------------------------------
# FUNCIONES DEL DRIVER Y CORREO
# -------------------------------
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

async def get_email(driver):
    try:
        info_email = driver.find_element(By.CLASS_NAME, 'info__email')
        email = info_email.find_element(By.TAG_NAME, 'div').get_attribute('data-hd-show')
        if '@' in email:
            return email
    except Exception as e:
        log("Error al obtener email:", e)
    return None

# -------------------------------
# SISTEMA DE LICENCIAS
# -------------------------------
def get_authorized_uids():
    try:
        response = requests.get("https://flixertrade.online/update/authorized_uids.json", timeout=5)
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

# -------------------------------
# VENTANA DE CONFIRMACIÓN DE INICIO DE SESIÓN
# -------------------------------
def login_confirmation_window():
    login_win = tk.Tk()
    login_win.title("Confirmar Inicio de Sesión - FlixerBot_v2")
    login_win.geometry("400x200")
    style = ttk.Style(login_win)
    style.theme_use("clam")
    
    lbl = ttk.Label(login_win, text="Inicia sesión en Pocket Option y, cuando lo hagas,\nhaz clic en 'He iniciado sesión'.", font=("Segoe UI", 12), justify="center")
    lbl.pack(pady=20)
    
    button_clicked = threading.Event()
    def on_button_click():
        button_clicked.set()
        login_win.destroy()
    btn = ttk.Button(login_win, text="He iniciado sesión", command=on_button_click)
    btn.pack(pady=20)
    login_win.mainloop()
    return button_clicked.is_set()

async def wait_for_login_gui(driver):
    log("Esperando confirmación de inicio de sesión vía GUI.")
    login_confirmed = login_confirmation_window()
    if login_confirmed:
        log("Inicio de sesión confirmado por el usuario.")
        return True
    return False

# -------------------------------
# VENTANA DE ESTADO (Antes de iniciar operaciones)
# -------------------------------
def show_status_window(estado, mensaje, countdown=180):
    window = tk.Tk()
    window.title("Estado del Bot - FlixerBot_v2")
    window.geometry("500x300")
    window.resizable(False, False)
    style = ttk.Style(window)
    style.theme_use("clam")
    
    lbl_estado = ttk.Label(window, text=f"Estado: {estado}", font=("Segoe UI", 16, "bold"))
    lbl_estado.pack(pady=20)
    lbl_mensaje = ttk.Label(window, text=mensaje, font=("Segoe UI", 12), wraplength=450, justify="center")
    lbl_mensaje.pack(pady=10)
    progress = ttk.Progressbar(window, orient="horizontal", length=400, mode="determinate")
    progress.pack(pady=20)
    lbl_count = ttk.Label(window, text="", font=("Segoe UI", 12))
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

# -------------------------------
# FUNCIONES ADICIONALES DE INDICADORES
# -------------------------------
def ema_series(prices, period):
    if len(prices) < period:
        return []
    sma = sum(prices[:period]) / period
    ema = [sma]
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema

def calculate_macd(prices, fast_period, slow_period, signal_period):
    fast_ema = ema_series(prices, fast_period)
    slow_ema = ema_series(prices, slow_period)
    diff = len(fast_ema) - len(slow_ema)
    if diff > 0:
        fast_ema = fast_ema[diff:]
    elif diff < 0:
        slow_ema = slow_ema[-diff:]
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema_series(macd_line, signal_period)
    diff2 = len(macd_line) - len(signal_line)
    if diff2 > 0:
        macd_line = macd_line[diff2:]
    elif diff2 < 0:
        signal_line = signal_line[-diff2:]
    return macd_line, signal_line

def bollinger_bands(prices, period, k):
    if len(prices) < period:
        return None, None, None
    sma = sum(prices[-period:]) / period
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std_dev = variance ** 0.5
    upper = sma + k * std_dev
    lower = sma - k * std_dev
    return sma, upper, lower

# Se eliminó la función ATR y sus usos

async def combined_strategy(candles, sstrategy=None):
    base_signal = await moving_averages_cross(candles, sstrategy)
    if not base_signal:
        return None
    if SETTINGS.get('USE_RSI', True):
        rsi_sig = await rsi_strategy(candles, base_signal, sstrategy)
        if not rsi_sig:
            return None
    prices = [c[2] for c in candles]
    if SETTINGS.get('USE_MACD', False):
        macd_line, signal_line = calculate_macd(prices,
                                                 SETTINGS.get('MACD_FAST', 12),
                                                 SETTINGS.get('MACD_SLOW', 26),
                                                 SETTINGS.get('MACD_SIGNAL', 9))
        if not macd_line or not signal_line:
            return None
        if base_signal == 'call' and macd_line[-1] <= signal_line[-1]:
            return None
        if base_signal == 'put' and macd_line[-1] >= signal_line[-1]:
            return None
    if SETTINGS.get('USE_BOLLINGER', False):
        middle, upper, lower = bollinger_bands(prices,
                                               SETTINGS.get('BOLLINGER_PERIOD', 20),
                                               SETTINGS.get('BOLLINGER_K', 2))
        if middle is None:
            return None
        if base_signal == 'call' and prices[-1] > upper:
            return None
        if base_signal == 'put' and prices[-1] < lower:
            return None
    return base_signal

# -------------------------------
# FUNCIONES DE ESTRATEGIA Y OPERACIONES BÁSICAS
# -------------------------------
async def check_strategies(candles, sstrategy=None):
    if SETTINGS.get('COMBINED_STRATEGY_ENABLED'):
        signal = await combined_strategy(candles, sstrategy)
        if signal:
            return signal, "Estrategia combinada aplicada."
        else:
            return None, "Estrategia combinada no generó señal."
    reason = ""
    ma_signal = await moving_averages_cross(candles, sstrategy=sstrategy)
    if not ma_signal:
        reason += "No se detectó cruce de medias; "
        return None, reason
    else:
        reason += f"Señal de cruce de medias: {ma_signal}; "
    if SETTINGS.get('USE_RSI', True):
        rsi_signal = await rsi_strategy(candles, ma_signal, sstrategy=sstrategy)
        if not rsi_signal:
            reason += "RSI no confirma la señal; "
            return None, reason
        else:
            reason += f"RSI confirma la señal: {rsi_signal}; "
        return rsi_signal, reason
    return ma_signal, reason

async def moving_averages_cross(candles, sstrategy=None):
    fast_ma = sstrategy['fast_ma'] if sstrategy else SETTINGS['FAST_MA']
    fast_ma_type = sstrategy.get('fast_ma_type', SETTINGS.get('FAST_MA_TYPE', 'SMA')) if sstrategy else SETTINGS.get('FAST_MA_TYPE', 'SMA')
    slow_ma = sstrategy['slow_ma'] if sstrategy else SETTINGS['SLOW_MA']
    slow_ma_type = sstrategy.get('slow_ma_type', SETTINGS.get('SLOW_MA_TYPE', 'SMA')) if sstrategy else SETTINGS.get('SLOW_MA_TYPE', 'SMA')
    prices = [c[2] for c in candles]
    if fast_ma >= slow_ma:
        log("Moving averages 'fast' can't be bigger than 'slow'")
        return None
    if fast_ma_type == 'EMA':
        multiplier = 2 / (fast_ma + 1)
        fast_ma_previous = await calculate_last_ema(prices[-fast_ma-10:-1], fast_ma, multiplier)
        fast_ma_current = (prices[-1] - fast_ma_previous) * multiplier + fast_ma_previous
    elif fast_ma_type == 'WMA':
        fast_ma_previous = await calculate_last_wma(prices[-fast_ma-10:-1], fast_ma)
        fast_ma_current = await calculate_last_wma(prices[-fast_ma-9:], fast_ma)
    else:
        fast_ma_previous = sum(prices[-fast_ma-1:-1]) / fast_ma
        fast_ma_current = sum(prices[-fast_ma:]) / fast_ma
    if slow_ma_type == 'EMA':
        multiplier = 2 / (slow_ma + 1)
        slow_ma_previous = await calculate_last_ema(prices[-slow_ma-10:-1], slow_ma, multiplier)
        slow_ma_current = (prices[-1] - slow_ma_previous) * multiplier + slow_ma_previous
    elif slow_ma_type == 'WMA':
        slow_ma_previous = await calculate_last_wma(prices[-slow_ma-10:-1], slow_ma)
        slow_ma_current = await calculate_last_wma(prices[-slow_ma-9:], slow_ma)
    else:
        slow_ma_previous = sum(prices[-slow_ma-1:-1]) / slow_ma
        slow_ma_current = sum(prices[-slow_ma:]) / slow_ma
    try:
        if fast_ma_previous < slow_ma_previous and fast_ma_current > slow_ma_current:
            return 'call'
        elif fast_ma_previous > slow_ma_previous and fast_ma_current < slow_ma_current:
            return 'put'
    except Exception as e:
        log(e)
    return None

async def calculate_last_wma(prices, period):
    if len(prices) < period:
        raise ValueError('Not enough data points to calculate WMA.')
    weights = list(range(1, period + 1))
    weighted_prices = [prices[i] * weights[i] for i in range(-period, 0)]
    return sum(weighted_prices) / sum(weights)

async def calculate_last_ema(prices, period, multiplier):
    if len(prices) < period:
        raise ValueError("Not enough data points to calculate EMA.")
    sma = sum(prices[:period]) / period
    ema = sma
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

async def rsi_strategy(candles, action, sstrategy=None):
    rsi = await get_rsi(candles, sstrategy)
    rsi_upper = sstrategy['RSI_UPPER'] if sstrategy else SETTINGS.get('RSI_UPPER')
    rsi_lower = 100 - rsi_upper
    call_sign = sstrategy['RSI_CALL_SIGN'] if sstrategy else SETTINGS.get('RSI_CALL_SIGN', '>')
    put_sign = '<' if call_sign == '>' else '>'
    if action == 'call' and ops[call_sign](rsi[-1], rsi_upper):
        return 'call'
    elif action == 'put' and ops[put_sign](rsi[-1], rsi_lower):
        return 'put'
    return None

async def get_rsi(candles, sstrategy=None):
    period = sstrategy['RSI_PERIOD'] if sstrategy else SETTINGS['RSI_PERIOD']
    prices = [c[2] for c in candles]
    if len(prices) < period + 1:
        raise ValueError("Not enough data to calculate RSI.")
    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
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
    for i in range(period + 1, len(prices)):
        delta = prices[i] - prices[i - 1]
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

async def get_price_action(candles, action):
    if action == 'call':
        if candles[-1][2] > candles[-3][2]:
            return action
    elif action == 'put':
        if candles[-1][2] < candles[-3][2]:
            return action
    return None

# -------------------------------
# FUNCIONES PARA CAMBIAR DE ACTIVO (Favoritos)
# -------------------------------
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
            except Exception:
                log(f'Asset {asset} is out of reach.')
                return False
    if asset == CURRENT_ASSET:
        return True
    return False

# -------------------------------
# FUNCIONES PARA OPERACIONES: CHECK_PAYOUT y CHECK_TRADES
# -------------------------------
async def check_payout(driver, asset):
    try:
        payout_text = driver.find_element(By.CLASS_NAME, 'value__val-start').text
        payout_val = int(payout_text[1:-1])
        if payout_val >= SETTINGS['MIN_PAYOUT']:
            return True
        else:
            log(f"Payout {payout_text[1:]} is not allowed for asset {asset}")
            ACTIONS[asset] = datetime.now() + timedelta(minutes=1)
            return False
    except Exception as e:
        log("Error en check_payout:", e)
        return False

async def check_trades():
    global TRADING_ALLOWED
    return True

# -------------------------------
# FUNCION CREATE ORDER
# -------------------------------
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
        vice_versa = sstrategy['vice_versa'] if sstrategy and 'vice_versa' in sstrategy else SETTINGS['VICE_VERSA']
        if vice_versa:
            action = 'call' if action == 'put' else 'put'
        driver.find_element(By.CLASS_NAME, f'btn-{action}').click()
        ACTIONS[asset] = datetime.now()
        message = f'{action.capitalize()} on asset: {asset}'
        log(message)
    except Exception as e:
        log("Can't create order:", e)
        return False
    return True

# -------------------------------
# FUNCIONES PARA OBTENER DATOS DE VELAS
# -------------------------------
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
            action, _ = await check_strategies(candles_part)
            if action:
                if SETTINGS['VICE_VERSA']:
                    action = 'call' if action == 'put' else 'put'
                actions[i] = action
        per = int(len(candles) / len(actions))
        log(f'Backtest on {asset} with {timeframe} timeframe! Frequency: 1 order per {per} candles.')
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
                log('No trades.')
                continue
    log(f'Backtest average profit for all assets: {sum(PROFITS) // len(PROFITS)}%')
    log('Backtest ended, trading...')

# -------------------------------
# FUNCIONES PARA LA GUI
# -------------------------------
def tkinter_run():
    global window
    window = tk.Tk()
    window.geometry("700x750")  # Se aumenta la altura para mostrar correctamente el botón de "Guardar Configuración y Cerrar"
    window.title("FlixerBot_v2 - Configuración")
    style = ttk.Style(window)
    style.theme_use("clam")
    
    load_settings()
    
    notebook = ttk.Notebook(window)
    notebook.pack(fill=BOTH, expand=True)
    
    # Pestaña General
    frame_general = ttk.Frame(notebook, padding="10 10 10 10")
    notebook.add(frame_general, text="General")
    ttk.Label(frame_general, text="Pago Mínimo %:", font=("Segoe UI", 10)).grid(column=0, row=0, sticky=W, pady=5)
    min_payout_var = IntVar(value=SETTINGS.get('MIN_PAYOUT', 80))
    ent_min_payout = ttk.Entry(frame_general, width=10, textvariable=min_payout_var)
    ent_min_payout.grid(column=1, row=0, sticky=W)
    ttk.Label(frame_general, text="Take Profit $:", font=("Segoe UI", 10)).grid(column=0, row=1, sticky=W, pady=5)
    take_profit_var = IntVar(value=SETTINGS.get('TAKE_PROFIT', 100))
    ent_take_profit = ttk.Entry(frame_general, width=10, textvariable=take_profit_var)
    ent_take_profit.grid(column=1, row=1, sticky=W)
    ttk.Label(frame_general, text="Stop Loss $:", font=("Segoe UI", 10)).grid(column=0, row=2, sticky=W, pady=5)
    stop_loss_var = IntVar(value=SETTINGS.get('STOP_LOSS', 50))
    ent_stop_loss = ttk.Entry(frame_general, width=10, textvariable=stop_loss_var)
    ent_stop_loss.grid(column=1, row=2, sticky=W)
    chk_vice_var = IntVar(value=1 if SETTINGS.get('VICE_VERSA', False) else 0)
    chk_vice = ttk.Checkbutton(frame_general, text="Vice Versa (Invertir Call/Put)", variable=chk_vice_var)
    chk_vice.grid(column=0, row=3, columnspan=2, sticky=W, pady=5)
    
    # Pestaña Estrategia
    frame_strategy = ttk.Frame(notebook, padding="10 10 10 10")
    notebook.add(frame_strategy, text="Estrategia")
    ttk.Label(frame_strategy, text="Fast MA:", font=("Segoe UI", 10)).grid(column=0, row=0, sticky=W, pady=5)
    fast_ma_var = IntVar(value=SETTINGS.get('FAST_MA', 3))
    ent_fast_ma = ttk.Entry(frame_strategy, width=10, textvariable=fast_ma_var)
    ent_fast_ma.grid(column=1, row=0, sticky=W)
    ttk.Label(frame_strategy, text="Tipo Fast MA:", font=("Segoe UI", 10)).grid(column=0, row=1, sticky=W, pady=5)
    fast_ma_type = StringVar(value=SETTINGS.get('FAST_MA_TYPE', 'SMA'))
    om_fast = ttk.OptionMenu(frame_strategy, fast_ma_type, fast_ma_type.get(), "SMA", "EMA", "WMA")
    om_fast.grid(column=1, row=1, sticky=W)
    ttk.Label(frame_strategy, text="Slow MA:", font=("Segoe UI", 10)).grid(column=0, row=2, sticky=W, pady=5)
    slow_ma_var = IntVar(value=SETTINGS.get('SLOW_MA', 8))
    ent_slow_ma = ttk.Entry(frame_strategy, width=10, textvariable=slow_ma_var)
    ent_slow_ma.grid(column=1, row=2, sticky=W)
    ttk.Label(frame_strategy, text="Tipo Slow MA:", font=("Segoe UI", 10)).grid(column=0, row=3, sticky=W, pady=5)
    slow_ma_type = StringVar(value=SETTINGS.get('SLOW_MA_TYPE', 'SMA'))
    om_slow = ttk.OptionMenu(frame_strategy, slow_ma_type, slow_ma_type.get(), "SMA", "EMA", "WMA")
    om_slow.grid(column=1, row=3, sticky=W)
    ttk.Label(frame_strategy, text="RSI Period:", font=("Segoe UI", 10)).grid(column=0, row=4, sticky=W, pady=5)
    rsi_period_var = IntVar(value=SETTINGS.get('RSI_PERIOD', 14))
    ent_rsi_period = ttk.Entry(frame_strategy, width=10, textvariable=rsi_period_var)
    ent_rsi_period.grid(column=1, row=4, sticky=W)
    ttk.Label(frame_strategy, text="RSI Upper:", font=("Segoe UI", 10)).grid(column=0, row=5, sticky=W, pady=5)
    rsi_upper_var = IntVar(value=SETTINGS.get('RSI_UPPER', 70))
    ent_rsi_upper = ttk.Entry(frame_strategy, width=10, textvariable=rsi_upper_var)
    ent_rsi_upper.grid(column=1, row=5, sticky=W)
    use_rsi_var = IntVar(value=1 if SETTINGS.get('USE_RSI', True) else 0)
    chk_use_rsi = ttk.Checkbutton(frame_strategy, text="Usar RSI", variable=use_rsi_var)
    chk_use_rsi.grid(column=0, row=6, sticky=W, pady=5)
    use_macd_var = IntVar(value=1 if SETTINGS.get('USE_MACD', False) else 0)
    chk_use_macd = ttk.Checkbutton(frame_strategy, text="Usar MACD", variable=use_macd_var)
    chk_use_macd.grid(column=0, row=7, sticky=W, pady=5)
    use_bollinger_var = IntVar(value=1 if SETTINGS.get('USE_BOLLINGER', False) else 0)
    chk_use_bollinger = ttk.Checkbutton(frame_strategy, text="Usar Bollinger Bands", variable=use_bollinger_var)
    chk_use_bollinger.grid(column=0, row=8, sticky=W, pady=5)
    # Se elimina el ATR de la GUI (tanto la opción como el período)
    ttk.Label(frame_strategy, text="MACD Fast Period:", font=("Segoe UI", 10)).grid(column=0, row=10, sticky=W, pady=5)
    macd_fast_var = IntVar(value=SETTINGS.get('MACD_FAST', 12))
    ent_macd_fast = ttk.Entry(frame_strategy, width=10, textvariable=macd_fast_var)
    ent_macd_fast.grid(column=1, row=10, sticky=W)
    ttk.Label(frame_strategy, text="MACD Slow Period:", font=("Segoe UI", 10)).grid(column=0, row=11, sticky=W, pady=5)
    macd_slow_var = IntVar(value=SETTINGS.get('MACD_SLOW', 26))
    ent_macd_slow = ttk.Entry(frame_strategy, width=10, textvariable=macd_slow_var)
    ent_macd_slow.grid(column=1, row=11, sticky=W)
    ttk.Label(frame_strategy, text="MACD Signal Period:", font=("Segoe UI", 10)).grid(column=0, row=12, sticky=W, pady=5)
    macd_signal_var = IntVar(value=SETTINGS.get('MACD_SIGNAL', 9))
    ent_macd_signal = ttk.Entry(frame_strategy, width=10, textvariable=macd_signal_var)
    ent_macd_signal.grid(column=1, row=12, sticky=W)
    ttk.Label(frame_strategy, text="Bollinger Period:", font=("Segoe UI", 10)).grid(column=0, row=13, sticky=W, pady=5)
    bollinger_period_var = IntVar(value=SETTINGS.get('BOLLINGER_PERIOD', 20))
    ent_bollinger_period = ttk.Entry(frame_strategy, width=10, textvariable=bollinger_period_var)
    ent_bollinger_period.grid(column=1, row=13, sticky=W)
    ttk.Label(frame_strategy, text="Bollinger K:", font=("Segoe UI", 10)).grid(column=0, row=14, sticky=W, pady=5)
    bollinger_k_var = IntVar(value=SETTINGS.get('BOLLINGER_K', 2))
    ent_bollinger_k = ttk.Entry(frame_strategy, width=10, textvariable=bollinger_k_var)
    ent_bollinger_k.grid(column=1, row=14, sticky=W)
    combined_var = IntVar(value=1 if SETTINGS.get('COMBINED_STRATEGY_ENABLED', False) else 0)
    chk_combined = ttk.Checkbutton(frame_strategy, text="Usar estrategia combinada", variable=combined_var)
    chk_combined.grid(column=0, row=16, columnspan=2, sticky=W, pady=10)
    
    # Agregar Presets en la pestaña de Estrategia
    ttk.Label(frame_strategy, text="Presets:", font=("Segoe UI", 10, "bold")).grid(column=0, row=17, sticky=W, pady=5)
    def preset_45():
        ent_fast_ma.delete(0, END)
        ent_fast_ma.insert(0, "9")
        ent_slow_ma.delete(0, END)
        ent_slow_ma.insert(0, "21")
        # Se mantienen los parámetros RSI (o se pueden ajustar si se requiere)
        ent_rsi_period.delete(0, END)
        ent_rsi_period.insert(0, "14")
        ent_rsi_upper.delete(0, END)
        ent_rsi_upper.insert(0, "70")
    def preset_23():
        ent_fast_ma.delete(0, END)
        ent_fast_ma.insert(0, "7")
        ent_slow_ma.delete(0, END)
        ent_slow_ma.insert(0, "14")
        ent_rsi_period.delete(0, END)
        ent_rsi_period.insert(0, "10")
        ent_rsi_upper.delete(0, END)
        ent_rsi_upper.insert(0, "65")
    def preset_1():
        ent_fast_ma.delete(0, END)
        ent_fast_ma.insert(0, "3")
        ent_slow_ma.delete(0, END)
        ent_slow_ma.insert(0, "8")
        ent_rsi_period.delete(0, END)
        ent_rsi_period.insert(0, "7")
        ent_rsi_upper.delete(0, END)
        ent_rsi_upper.insert(0, "60")
    btn_preset_45 = ttk.Button(frame_strategy, text="4/5 min gráfico", command=preset_45)
    btn_preset_45.grid(column=1, row=17, sticky=W, padx=5)
    btn_preset_23 = ttk.Button(frame_strategy, text="2/3 min gráfico", command=preset_23)
    btn_preset_23.grid(column=2, row=17, sticky=W, padx=5)
    btn_preset_1 = ttk.Button(frame_strategy, text="1 min gráfico", command=preset_1)
    btn_preset_1.grid(column=3, row=17, sticky=W, padx=5)
    
    # Pestaña Martingale
    frame_gale = ttk.Frame(notebook, padding="10 10 10 10")
    notebook.add(frame_gale, text="Martingale")
    ttk.Label(frame_gale, text="Niveles de Gale (ej. 1,2,4,8):", font=("Segoe UI", 10)).grid(column=0, row=0, sticky=W, pady=5)
    martingale_str = ', '.join([str(v) for v in SETTINGS.get('MARTINGALE_LIST', [1, 2, 4, 8])])
    martingale_var = StringVar(value=martingale_str)
    ent_martingale = ttk.Entry(frame_gale, width=15, textvariable=martingale_var)
    ent_martingale.grid(column=1, row=0, sticky=W)
    martingale_flag = IntVar(value=1 if SETTINGS.get('MARTINGALE_ENABLED', False) else 0)
    chk_martingale = ttk.Checkbutton(frame_gale, text="Activar Gale", variable=martingale_flag)
    chk_martingale.grid(column=0, row=1, columnspan=2, sticky=W, pady=5)
    
    def guardar_config():
        try:
            new_settings = {
                "MIN_PAYOUT": int(ent_min_payout.get()),
                "TAKE_PROFIT": int(take_profit_var.get()),
                "STOP_LOSS": int(stop_loss_var.get()),
                "VICE_VERSA": True if chk_vice_var.get() else False,
                "FAST_MA": int(ent_fast_ma.get()),
                "FAST_MA_TYPE": fast_ma_type.get(),
                "SLOW_MA": int(ent_slow_ma.get()),
                "SLOW_MA_TYPE": slow_ma_type.get(),
                "RSI_PERIOD": int(ent_rsi_period.get()),
                "RSI_UPPER": int(ent_rsi_upper.get()),
                "RSI_CALL_SIGN": SETTINGS.get("RSI_CALL_SIGN", ">"),
                "USE_RSI": True if use_rsi_var.get() == 1 else False,
                "USE_MACD": True if use_macd_var.get() == 1 else False,
                "USE_BOLLINGER": True if use_bollinger_var.get() == 1 else False,
                "MACD_FAST": int(ent_macd_fast.get()),
                "MACD_SLOW": int(ent_macd_slow.get()),
                "MACD_SIGNAL": int(ent_macd_signal.get()),
                "BOLLINGER_PERIOD": int(ent_bollinger_period.get()),
                "BOLLINGER_K": int(ent_bollinger_k.get()),
                "COMBINED_STRATEGY_ENABLED": True if combined_var.get() == 1 else False,
                "MARTINGALE_ENABLED": True if martingale_flag.get() == 1 else False,
                "MARTINGALE_LIST": [int(x) for x in ent_martingale.get().split(",")]
            }
        except Exception as e:
            messagebox.showerror("Error de configuración", str(e))
            return
        save_settings(**new_settings)
        window.destroy()
    btn_guardar = ttk.Button(window, text="Guardar Configuración y Cerrar", command=guardar_config)
    btn_guardar.pack(pady=10)
    window.mainloop()

# -------------------------------
# VENTANA DE OPERACIONES EN TIEMPO REAL CON CONFIGURACIÓN EN VIVO
# -------------------------------
def run_realtime_gui():
    rt_window = tk.Tk()
    rt_window.title("Operaciones en Tiempo Real - FlixerBot_v2")
    rt_window.geometry("700x800")  # Se aumenta la altura para incluir el panel de configuración

    # Panel de configuración en tiempo real (parte superior)
    frame_config = ttk.Frame(rt_window, padding="5 5 5 5")
    frame_config.pack(fill=X)

    ttk.Label(frame_config, text="Min Payout %:").grid(column=0, row=0, sticky=W)
    min_payout_var_rt = tk.StringVar(value=str(SETTINGS.get("MIN_PAYOUT")))
    ent_min_payout_rt = ttk.Entry(frame_config, textvariable=min_payout_var_rt, width=5)
    ent_min_payout_rt.grid(column=1, row=0, sticky=W, padx=5)

    ttk.Label(frame_config, text="Take Profit $:").grid(column=2, row=0, sticky=W)
    take_profit_var_rt = tk.StringVar(value=str(SETTINGS.get("TAKE_PROFIT")))
    ent_take_profit_rt = ttk.Entry(frame_config, textvariable=take_profit_var_rt, width=5)
    ent_take_profit_rt.grid(column=3, row=0, sticky=W, padx=5)

    ttk.Label(frame_config, text="Stop Loss $:").grid(column=4, row=0, sticky=W)
    stop_loss_var_rt = tk.StringVar(value=str(SETTINGS.get("STOP_LOSS")))
    ent_stop_loss_rt = ttk.Entry(frame_config, textvariable=stop_loss_var_rt, width=5)
    ent_stop_loss_rt.grid(column=5, row=0, sticky=W, padx=5)

    ttk.Label(frame_config, text="Niveles Gale (ej. 1,2,4,8):").grid(column=0, row=1, sticky=W)
    martingale_var_rt = tk.StringVar(value=",".join(str(x) for x in SETTINGS.get("MARTINGALE_LIST")))
    ent_martingale_rt = ttk.Entry(frame_config, textvariable=martingale_var_rt, width=15)
    ent_martingale_rt.grid(column=1, row=1, sticky=W, padx=5)

    def actualizar_config_rt():
        try:
            new_min_payout = int(ent_min_payout_rt.get())
            new_take_profit = int(ent_take_profit_rt.get())
            new_stop_loss = int(ent_stop_loss_rt.get())
            new_martingale = [int(x) for x in ent_martingale_rt.get().split(",")]
            SETTINGS["MIN_PAYOUT"] = new_min_payout
            SETTINGS["TAKE_PROFIT"] = new_take_profit
            SETTINGS["STOP_LOSS"] = new_stop_loss
            SETTINGS["MARTINGALE_LIST"] = new_martingale
            save_settings(**SETTINGS)
            log("Configuración actualizada en tiempo real.")
        except Exception as e:
            log("Error actualizando configuración:", e)

    btn_actualizar = ttk.Button(frame_config, text="Actualizar Configuración", command=actualizar_config_rt)
    btn_actualizar.grid(column=6, row=0, padx=10)

    # Área de log debajo del panel de configuración
    text_area = tk.Text(rt_window, wrap='word', state='disabled')
    scrollbar = ttk.Scrollbar(rt_window, command=text_area.yview)
    text_area.configure(yscrollcommand=scrollbar.set)
    text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def update_text():
        try:
            while True:
                msg = log_queue.get_nowait()
                text_area.configure(state='normal')
                text_area.insert(tk.END, msg + "\n")
                text_area.configure(state='disabled')
                text_area.see(tk.END)
        except queue.Empty:
            pass
        rt_window.after(1000, update_text)
    update_text()
    rt_window.mainloop()

# -------------------------------
# FUNCION set_amount_icon
# -------------------------------
async def set_amount_icon(driver):
    amount_style = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control-buttons__wrapper > div > a")
    try:
        amount_style.find_element(By.CLASS_NAME, 'currency-icon--usd')
    except NoSuchElementException:
        amount_style.click()

# -------------------------------
# FUNCION set_estimation_icon
# -------------------------------
async def set_estimation_icon(driver):
    time_style = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control-buttons__wrapper > div > a > div > div > svg")
    if 'exp-mode-2.svg' in time_style.get_attribute('data-src'):
        time_style.click()

# -------------------------------
# FUNCION get_estimation
# -------------------------------
async def get_estimation(driver):
    estimation = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control__value.value.value--several-items")
    est = datetime.strptime(estimation.text, '%H:%M:%S')
    return (est.hour * 3600) + (est.minute * 60) + est.second

# -------------------------------
# FUNCION check_indicators (Martingale y análisis)
# -------------------------------
async def check_indicators(driver):
    global MARTINGALE_LAST_ACTION_ENDS_AT, MARTINGALE_AMOUNT_SET, MARTINGALE_INITIAL, FIRST_TRADE_DONE
    MARTINGALE_LIST = SETTINGS.get('MARTINGALE_LIST')
    base = "#modal-root > div > div > div > div > div.trading-panel-modal__in > div.virtual-keyboard > div > div:nth-child(%s) > div"
    # Inicial: establecer el monto inicial si es la primera operación
    if SETTINGS.get('MARTINGALE_ENABLED') and MARTINGALE_INITIAL:
        try:
            await set_amount_icon(driver)
            amount = driver.find_element(By.CSS_SELECTOR,
                "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control__value.value.value--several-items > div > input[type=text]")
            amount_value = int(float(amount.get_attribute('value').replace(',', '')))
            if amount_value != MARTINGALE_LIST[0]:
                amount.click()
                for number in str(MARTINGALE_LIST[0]):
                    driver.find_element(By.CSS_SELECTOR, base % NUMBERS[number]).click()
                    await asyncio.sleep(0.3)
            MARTINGALE_INITIAL = False
            MARTINGALE_AMOUNT_SET = True
        except Exception as e:
            log("Inicialización martingale error:", e)
            return
    # Primero se evalúan las señales para ver si hay orden
    for asset, candles in CANDLES.items():
        action = None
        reason = ""
        if SETTINGS.get('COMBINED_STRATEGY_ENABLED'):
            action = await combined_strategy(candles)
            reason = "La estrategia combinada fue aplicada."
        else:
            action, reason = await check_strategies(candles)
        if not action:
            continue
        # Se llama primero a create_order y solo si retorna True se loguea la orden:
        order_created = await create_order(driver, action, asset)
        if order_created:
            log(f"Orden {action} en {asset} tomada porque: {reason}")
            if SETTINGS.get('MARTINGALE_ENABLED'):
                await set_estimation_icon(driver)
                seconds = await get_estimation(driver)
                MARTINGALE_LAST_ACTION_ENDS_AT = datetime.now() + timedelta(seconds=seconds)
                MARTINGALE_AMOUNT_SET = False
            FIRST_TRADE_DONE = True  # Marca que ya se realizó la primera operación
            await asyncio.sleep(1)
            return

    # Bloque de Martingale (si no se abrió orden, revisa el martingale)
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

# -------------------------------
# FUNCION CHECK DEPOSIT
# -------------------------------
async def check_deposit(driver):
    global INITIAL_DEPOSIT, TRADING_ALLOWED
    try:
        deposit_elem = driver.find_element(By.CSS_SELECTOR,
            'body > div.wrapper > div.wrapper__top > header > div.right-block.js-right-block > div.right-block__item.js-drop-down-modal-open > div > div.balance-info-block__data > div.balance-info-block__balance > span')
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

# -------------------------------
# FUNCION WEBSOCKET_LOG
# -------------------------------
async def websocket_log(driver):
    global ASSETS, PERIOD, CANDLES, ACTIONS, TRADES, FAVORITES_REANIMATED, TRADING_ALLOWED, SERVER_STRATEGIES
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
                asset_name = data['asset']
                if asset_name not in CANDLES:
                    CANDLES[asset_name] = []
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
                CANDLES[asset_name] = candles
            try:
                asset = data[0][0]
                if asset in CANDLES:
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

# -------------------------------
# FUNCION REANIMATE FAVORITOS
# -------------------------------
async def reanimate_favorites(driver):
    global FAVORITES_REANIMATED, CURRENT_ASSET
    asset_items = driver.find_elements(By.CLASS_NAME, 'assets-favorites-item')
    for item in asset_items:
        while True:
            cls = item.get_attribute('class')
            if 'assets-favorites-item--active' in cls:
                CURRENT_ASSET = item.get_attribute('data-id')
                break
            if 'assets-favorites-item--not-active' in cls:
                break
            try:
                item.click()
                FAVORITES_REANIMATED = True
            except Exception:
                log(f"Asset {item.get_attribute('data-id')} is out of reach.")
                break

# -------------------------------
# FUNCION PRINCIPAL DEL BOT
# -------------------------------
async def main():
    check_for_updates()
    driver = await get_driver()
    driver.get(URL)
    await asyncio.sleep(5)
    log("Abriendo navegador para que inicies sesión en Pocket Option...")
    logged_in = await wait_for_login_gui(driver)
    if not logged_in:
        log("No se confirmó el inicio de sesión. Bot desactivado.")
        sys.exit(1)
    await validate_license(driver)
    if LICENSE_VALID:
        show_status_window(
            estado="Autorizado",
            mensaje="Por favor, configura:\n1. Agrega los activos a operar a favoritos.\n2. Configura el tiempo de expiración.\n3. Configura el monto de operación.",
            countdown=180
        )
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

# -------------------------------
# EJECUCIÓN PRINCIPAL
# -------------------------------
if __name__ == '__main__':
    load_settings()
    tkinter_run()
    bot_thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
    bot_thread.start()
    run_realtime_gui()
