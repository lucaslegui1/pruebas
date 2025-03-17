import asyncio
import base64
import json
import operator
import os
import platform
import sys
import threading
import requests
import queue
import subprocess
import time
from datetime import datetime, timedelta

import customtkinter as ctk
from tkinter import messagebox
from tkinter import PhotoImage

# Importaciones de Selenium y undetected_chromedriver
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException, InvalidSessionIdException
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc

# -------------------------------
# CONFIGURACIÓN PERSISTENTE (JSON)
# -------------------------------
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "MIN_PAYOUT": 80,
    "TAKE_PROFIT": 100,
    "STOP_LOSS": 50,
    "MAX_SIMULTANEOUS_TRADES": 2,  # Máximo de operaciones en la sesión
    "TAKE_PROFIT_ENABLED": True,
    "STOP_LOSS_ENABLED": True
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
__version__ = "2.1.1"

def version_tuple(v):
    return tuple(map(int, v.split(".")))

def check_for_updates():
    UPDATE_URL = "https://flixertrade.online/update/version.json"
    try:
        r = requests.get(UPDATE_URL, timeout=5)
        if r.status_code == 200:
            data = r.json()
            remote_version = data.get("version")
            download_url = data.get("download_url")
            if remote_version and download_url and version_tuple(remote_version) > version_tuple(__version__):
                log(f"Nueva versión: {remote_version}. Actualizando, espere...")
                update_response = requests.get(download_url, timeout=10)
                if update_response.status_code == 200:
                    if not getattr(sys, 'frozen', False):
                        with open(sys.argv[0], "wb") as f:
                            f.write(update_response.content)
                        log("Actualización aplicada. Reiniciando...")
                        sys.exit(0)
                    else:
                        current_exe = sys.executable
                        temp_exe = current_exe + ".new"
                        update_script = "update_script.bat"
                        with open(temp_exe, "wb") as f:
                            f.write(update_response.content)
                        log("Descargado. Creando script...")
                        with open(update_script, "w") as f:
                            f.write(f"""@echo off
taskkill /F /IM {os.path.basename(current_exe)} >nul 2>&1
timeout /t 5 >nul
move /Y "{temp_exe}" "{current_exe}" >nul 2>&1
start "" "{current_exe}"
del "%~f0"
""".strip())
                        log("Cerrando para actualizar...")
                        time.sleep(1)
                        subprocess.Popen(update_script, shell=True)
                        sys.exit(0)
                else:
                    log("Error al descargar actualización.")
                    raise Exception("Actualización fallida.")
        else:
            log("No se pudo comprobar actualización.")
            raise Exception("No se pudo comprobar actualización.")
    except Exception as e:
        log(f"Fallo en actualización: {e}")
        raise e

def apply_update():
    try:
        log("Ejecutando nueva versión...")
        os.startfile("FlixerBOT_v2.1.exe")
        sys.exit(0)
    except Exception as e:
        log(f"Error al iniciar la nueva versión: {e}")

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
TRADING_ALLOWED = True
CURRENT_ASSET = None
FAVORITES_REANIMATED = False
NUMBERS = {'0': '11', '1': '7', '2': '8', '3': '9', '4': '4', '5': '5', '6': '6', '7': '1', '8': '2', '9': '3'}
INITIAL_DEPOSIT = None

trade_total = 0  # Recuento total de operaciones
limit_logged = False  # Para evitar mensajes repetitivos

# Variable para almacenar el timestamp del último cierre de vela (para actualizar favoritos)
LAST_FAVORITES_UPDATE = 0

# -------------------------------
# NUEVAS ESTRATEGIAS AGRUPADAS POR ESCENARIO
# -------------------------------
STRATEGY_GROUPS = {
    "Expiración 4/5 minutos": {
         "Tendencia Fuerte": {
              "FAST_MA": 5,
              "SLOW_MA": 15,
              "RSI_PERIOD": 10,
              "USE_RSI": True,
              "USE_MACD": True,
         },
         "Mercado Lateral": {
              "FAST_MA": 3,
              "SLOW_MA": 8,
              "RSI_PERIOD": 14,
              "USE_RSI": True,
              "USE_MACD": False,
         },
         "Mercado Lento": {
              "FAST_MA": 8,
              "SLOW_MA": 20,
              "RSI_PERIOD": 14,
              "USE_RSI": True,
         },
         "Mercado Volátil": {
              "FAST_MA": 3,
              "SLOW_MA": 8,
              "RSI_PERIOD": 14,
              "USE_RSI": True,
              "USE_BOLLINGER": True,
              "USE_ATR": True,
              "ATR_PERIOD": 14,
              "BOLLINGER_PERIOD": 20,
              "BOLLINGER_K": 2,
         },
    },
    "Expiración 1/2 minutos": {
         "Breakout Rápido": {
              "FAST_MA": 2,
              "SLOW_MA": 5,
              "RSI_PERIOD": 10,
              "USE_RSI": False,
              "USE_MACD": True,
         },
         "Reversión Instantánea": {
              "FAST_MA": 3,
              "SLOW_MA": 7,
              "RSI_PERIOD": 12,
              "USE_RSI": True,
              "USE_MACD": False,
              "USE_BOLLINGER": True,
         },
         "Momentum Corto": {
              "USE_MACD": True,
         },
         "Scalping Volátil": {
              "USE_ATR": True,
              "ATR_PERIOD": 10,
              "USE_BOLLINGER": True,
              "BOLLINGER_PERIOD": 15,
              "BOLLINGER_K": 2,
         },
    }
}

active_strategy = None  # Estrategia activa seleccionada

# -------------------------------
# (Se han eliminado todas las referencias a Martingale)
# -------------------------------

# -------------------------------
# COLA PARA LOGS
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
# FUNCIONES PARA LIMPIAR OPERACIONES
# -------------------------------
def limpiar_operaciones():
    global ACTIONS
    for asset in list(ACTIONS.keys()):
        if ACTIONS[asset] + timedelta(seconds=PERIOD * 2) < datetime.now():
            del ACTIONS[asset]

# -------------------------------
# FUNCIONES DEL DRIVER Y LICENCIA
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

def get_authorized_uids():
    try:
        response = requests.get("https://flixertrade.online/update/authorized_uids.json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("authorized_uids", [])
    except Exception as e:
        log("Error al obtener UIDs autorizados:", e)
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
            log("Licencia válida. UID:", uid)
        else:
            LICENSE_VALID = False
            log("Licencia NO válida. UID:", uid)
            log("Redirigiendo a la pasarela de registro...")
            driver.get("https://flixertrade.online/registro.html")
            while True:
                await asyncio.sleep(60)
    except Exception as e:
        log("Error en validación de licencia:", e)
        driver.get("https://flixertrade.online/registro.html")
        while True:
            await asyncio.sleep(60)

# -------------------------------
# INTERFAZ CON CUSTOMTKINTER
# -------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class FlixerBotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FlixerBot_v2 (2.1.3) - Dashboard")
        self.geometry("1200x800")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.login_confirmed = False
        self.bot_started = False

        self.notebook = ctk.CTkTabview(self, width=1180, height=760)
        self.notebook.pack(padx=10, pady=10)
        self.notebook.add("Login")
        self.notebook.add("Trading")
        self.notebook.add("Logs")

        self.create_login_tab()
        self.create_trading_tab()
        self.create_logs_tab()

    def create_login_tab(self):
        frame = self.notebook.tab("Login")
        label = ctk.CTkLabel(frame, text="Bienvenido a FlixerBot (2.1.3)", font=("Segoe UI", 24, "bold"))
        label.pack(pady=20)
        self.login_instr = ctk.CTkLabel(frame, text="Inicia sesión en Pocket Option en el navegador abierto.", font=("Segoe UI", 16))
        self.login_instr.pack(pady=10)
        self.btn_confirm = ctk.CTkButton(frame, text="He iniciado sesión", command=self.confirm_login, width=200)
        self.btn_confirm.pack(pady=20)
        self.label_account_info = ctk.CTkLabel(frame, text="", font=("Segoe UI", 14))
        self.label_account_info.pack(pady=10)

    def confirm_login(self):
        self.login_confirmed = True
        self.btn_confirm.destroy()
        self.login_instr.configure(text="Sesión iniciada")
        self.update_account_info()
        messagebox.showinfo("Login", "Sesión iniciada. Los datos de tu cuenta se mostrarán en esta pestaña.")
        self.notebook.set("Trading")

    def update_account_info(self):
        saldo = f"{INITIAL_DEPOSIT}" if INITIAL_DEPOSIT is not None else "No disponible"
        licencia = "Válida" if LICENSE_VALID else "No válida"
        tp = f"{SETTINGS.get('TAKE_PROFIT')}" if SETTINGS.get('TAKE_PROFIT_ENABLED', False) else "N/A"
        sl = f"{SETTINGS.get('STOP_LOSS')}" if SETTINGS.get('STOP_LOSS_ENABLED', False) else "N/A"
        info = f"Saldo Inicial: {saldo} | Licencia: {licencia} | TP: {tp} | SL: {sl}"
        self.label_account_info.configure(text=info)
        self.after(5000, self.update_account_info)

    def create_trading_tab(self):
        frame = self.notebook.tab("Trading")
        # --- CONTROL DE TRADING (siempre visible en la parte superior) ---
        control_frame = ctk.CTkFrame(frame)
        control_frame.pack(pady=10, anchor="n", fill="x")
        self.trading_info = ctk.CTkLabel(control_frame, text="Trading no iniciado.", font=("Segoe UI", 16))
        self.trading_info.pack(side="left", padx=10)
        self.trade_total_label = ctk.CTkLabel(control_frame, text="Total operaciones: 0", font=("Segoe UI", 16))
        self.trade_total_label.pack(side="left", padx=10)
        self.btn_start_trading = ctk.CTkButton(control_frame, text="Iniciar Trading", command=self.start_trading, width=150)
        self.btn_start_trading.pack(side="left", padx=10)
        self.btn_restart_trading = ctk.CTkButton(control_frame, text="Reiniciar Trading", command=self.restart_trading, width=150)
        self.btn_restart_trading.pack(side="left", padx=10)

        # --- CONTENEDOR DE CONFIGURACIÓN EN DOS COLUMNAS ---
        config_frame = ctk.CTkFrame(frame)
        config_frame.pack(pady=10, fill="x")
        # Columna Izquierda: Parámetros Generales
        general_frame = ctk.CTkFrame(config_frame)
        general_frame.grid(row=0, column=0, padx=10, pady=10, sticky="n")
        ctk.CTkLabel(general_frame, text="Parámetros Generales", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=5)
        ctk.CTkLabel(general_frame, text="Pago Mínimo (%)", font=("Segoe UI", 16)).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.min_payout_var = ctk.StringVar(value=str(SETTINGS.get("MIN_PAYOUT", 80)))
        ctk.CTkEntry(general_frame, textvariable=self.min_payout_var, width=100).grid(row=1, column=1, padx=10, pady=5, sticky="w")
        ctk.CTkLabel(general_frame, text="Take Profit ($)", font=("Segoe UI", 16)).grid(row=2, column=0, padx=10, pady=5, sticky="e")
        self.take_profit_var = ctk.StringVar(value=str(SETTINGS.get("TAKE_PROFIT", 100)))
        ctk.CTkEntry(general_frame, textvariable=self.take_profit_var, width=100).grid(row=2, column=1, padx=10, pady=5, sticky="w")
        ctk.CTkLabel(general_frame, text="Stop Loss ($)", font=("Segoe UI", 16)).grid(row=3, column=0, padx=10, pady=5, sticky="e")
        self.stop_loss_var = ctk.StringVar(value=str(SETTINGS.get("STOP_LOSS", 50)))
        ctk.CTkEntry(general_frame, textvariable=self.stop_loss_var, width=100).grid(row=3, column=1, padx=10, pady=5, sticky="w")
        ctk.CTkLabel(general_frame, text="Max operaciones en esta sesion", font=("Segoe UI", 16)).grid(row=4, column=0, padx=10, pady=5, sticky="e")
        self.max_trades_var = ctk.StringVar(value=str(SETTINGS.get("MAX_SIMULTANEOUS_TRADES", 2)))
        ctk.CTkEntry(general_frame, textvariable=self.max_trades_var, width=100).grid(row=4, column=1, padx=10, pady=5, sticky="w")
        # Casilleros para habilitar/deshabilitar TP y SL
        self.tp_enabled_var = ctk.BooleanVar(value=SETTINGS.get("TAKE_PROFIT_ENABLED", True))
        self.sl_enabled_var = ctk.BooleanVar(value=SETTINGS.get("STOP_LOSS_ENABLED", True))
        ctk.CTkCheckBox(general_frame, text="Habilitar Take Profit", variable=self.tp_enabled_var).grid(row=5, column=0, columnspan=2, pady=5)
        ctk.CTkCheckBox(general_frame, text="Habilitar Stop Loss", variable=self.sl_enabled_var).grid(row=6, column=0, columnspan=2, pady=5)
        
        # Columna Derecha: Opciones de Estrategia Avanzada
        adv_container = ctk.CTkFrame(config_frame)
        adv_container.grid(row=0, column=1, padx=10, pady=10, sticky="n")
        # Opción siempre visible: Invertir Confirmaciones
        self.invert_confirm_var = ctk.BooleanVar(value=False)
        self.invert_confirm_checkbox = ctk.CTkCheckBox(adv_container, text="Invertir Confirmaciones", variable=self.invert_confirm_var, command=self.update_invert_confirm)
        self.invert_confirm_checkbox.pack(pady=5, anchor="w")
        # Modo Avanzado: Checkbutton para activar opciones avanzadas
        self.advanced_mode_var = ctk.BooleanVar(value=False)
        self.advanced_mode_checkbox = ctk.CTkCheckBox(adv_container, text="Modo Avanzado", variable=self.advanced_mode_var, command=self.toggle_advanced_mode)
        self.advanced_mode_checkbox.pack(pady=5, anchor="w")
        # Contenedor scrollable para opciones avanzadas (altura 400 px, ancho 400 px)
        self.advanced_options_frame = ctk.CTkScrollableFrame(adv_container, width=400, height=400)
        self.advanced_options_frame.pack(pady=5, fill="both", expand=True)
        self.create_advanced_options_widgets()
        # Por defecto, ocultar las opciones avanzadas
        self.advanced_options_frame.pack_forget()

        # --- SECCIÓN DE ESTRATEGIAS ---
        strat_frame = ctk.CTkFrame(frame)
        strat_frame.pack(pady=10, fill="x")
        ctk.CTkLabel(strat_frame, text="Selecciona Estrategia", font=("Segoe UI", 18, "bold")).pack(pady=5)
        for group_name, strategies in STRATEGY_GROUPS.items():
            group_label = ctk.CTkLabel(strat_frame, text=group_name, font=("Segoe UI", 16, "bold"))
            group_label.pack(anchor="w", padx=10, pady=5)
            group_buttons_frame = ctk.CTkFrame(strat_frame)
            group_buttons_frame.pack(padx=10, pady=5, fill="x")
            for strat_name, strat_params in strategies.items():
                btn = ctk.CTkButton(group_buttons_frame, text=strat_name, width=150,
                                    command=lambda n=strat_name, p=strat_params: self.set_strategy(n, p))
                btn.pack(side="left", padx=5, pady=5)
        self.selected_strategy_label = ctk.CTkLabel(strat_frame, text="Ninguna estrategia seleccionada", font=("Segoe UI", 16))
        self.selected_strategy_label.pack(pady=5)

        self.update_trade_counts()

    def update_invert_confirm(self):
        global active_strategy
        if active_strategy is not None:
            active_strategy["vice_versa"] = self.invert_confirm_var.get()

    def create_advanced_options_widgets(self):
        self.adv_vars = {}
        row = 0
        # RSI
        self.adv_vars["USE_RSI"] = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.advanced_options_frame, text="Activar RSI", variable=self.adv_vars["USE_RSI"]).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.adv_vars["RSI_PERIOD"] = ctk.StringVar(value="14")
        ctk.CTkLabel(self.advanced_options_frame, text="Periodo:").grid(row=row, column=1, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["RSI_PERIOD"], width=60).grid(row=row, column=2, padx=5, pady=5)
        row += 1
        self.adv_vars["RSI_LOWER"] = ctk.StringVar(value="30")
        ctk.CTkLabel(self.advanced_options_frame, text="Límite Inferior:").grid(row=row, column=1, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["RSI_LOWER"], width=60).grid(row=row, column=2, padx=5, pady=5)
        self.adv_vars["RSI_UPPER"] = ctk.StringVar(value="70")
        ctk.CTkLabel(self.advanced_options_frame, text="Límite Superior:").grid(row=row, column=3, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["RSI_UPPER"], width=60).grid(row=row, column=4, padx=5, pady=5)
        row += 1
        # MACD
        self.adv_vars["USE_MACD"] = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.advanced_options_frame, text="Activar MACD", variable=self.adv_vars["USE_MACD"]).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.adv_vars["MACD_FAST"] = ctk.StringVar(value="12")
        ctk.CTkLabel(self.advanced_options_frame, text="Rápida:").grid(row=row, column=1, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["MACD_FAST"], width=60).grid(row=row, column=2, padx=5, pady=5)
        self.adv_vars["MACD_SLOW"] = ctk.StringVar(value="26")
        ctk.CTkLabel(self.advanced_options_frame, text="Lenta:").grid(row=row, column=3, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["MACD_SLOW"], width=60).grid(row=row, column=4, padx=5, pady=5)
        row += 1
        self.adv_vars["MACD_SIGNAL"] = ctk.StringVar(value="9")
        ctk.CTkLabel(self.advanced_options_frame, text="Señal:").grid(row=row, column=1, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["MACD_SIGNAL"], width=60).grid(row=row, column=2, padx=5, pady=5)
        row += 1
        # Bollinger
        self.adv_vars["USE_BOLLINGER"] = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.advanced_options_frame, text="Activar Bollinger", variable=self.adv_vars["USE_BOLLINGER"]).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.adv_vars["BOLLINGER_PERIOD"] = ctk.StringVar(value="20")
        ctk.CTkLabel(self.advanced_options_frame, text="Periodo:").grid(row=row, column=1, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["BOLLINGER_PERIOD"], width=60).grid(row=row, column=2, padx=5, pady=5)
        self.adv_vars["BOLLINGER_K"] = ctk.StringVar(value="2")
        ctk.CTkLabel(self.advanced_options_frame, text="K:").grid(row=row, column=3, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["BOLLINGER_K"], width=60).grid(row=row, column=4, padx=5, pady=5)
        row += 1
        # ATR
        self.adv_vars["USE_ATR"] = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.advanced_options_frame, text="Activar ATR", variable=self.adv_vars["USE_ATR"]).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.adv_vars["ATR_PERIOD"] = ctk.StringVar(value="14")
        ctk.CTkLabel(self.advanced_options_frame, text="Periodo:").grid(row=row, column=1, padx=5, pady=5, sticky="e")
        ctk.CTkEntry(self.advanced_options_frame, textvariable=self.adv_vars["ATR_PERIOD"], width=60).grid(row=row, column=2, padx=5, pady=5)
        row += 1

    def toggle_advanced_mode(self):
        if self.advanced_mode_var.get():
            self.advanced_options_frame.pack(pady=5, fill="both", expand=True)
        else:
            self.advanced_options_frame.pack_forget()
        self.apply_advanced_options()

    def apply_advanced_options(self):
        global active_strategy
        if active_strategy is None:
            return
        active_strategy["USE_RSI"] = self.adv_vars["USE_RSI"].get()
        try:
            active_strategy["RSI_PERIOD"] = int(self.adv_vars["RSI_PERIOD"].get())
            active_strategy["RSI_LOWER"] = int(self.adv_vars["RSI_LOWER"].get())
            active_strategy["RSI_UPPER"] = int(self.adv_vars["RSI_UPPER"].get())
        except ValueError:
            log("Error en la configuración del RSI. Verifique los valores numéricos.")
        active_strategy["USE_MACD"] = self.adv_vars["USE_MACD"].get()
        try:
            active_strategy["MACD_FAST"] = int(self.adv_vars["MACD_FAST"].get())
            active_strategy["MACD_SLOW"] = int(self.adv_vars["MACD_SLOW"].get())
            active_strategy["MACD_SIGNAL"] = int(self.adv_vars["MACD_SIGNAL"].get())
        except ValueError:
            log("Error en la configuración del MACD. Verifique los valores numéricos.")
        active_strategy["USE_BOLLINGER"] = self.adv_vars["USE_BOLLINGER"].get()
        try:
            active_strategy["BOLLINGER_PERIOD"] = int(self.adv_vars["BOLLINGER_PERIOD"].get())
            active_strategy["BOLLINGER_K"] = float(self.adv_vars["BOLLINGER_K"].get())
        except ValueError:
            log("Error en la configuración de Bollinger. Verifique los valores numéricos.")
        active_strategy["USE_ATR"] = self.adv_vars["USE_ATR"].get()
        try:
            active_strategy["ATR_PERIOD"] = int(self.adv_vars["ATR_PERIOD"].get())
        except ValueError:
            log("Error en la configuración del ATR. Verifique el valor numérico.")

    def set_strategy(self, strategy_name, strategy_params):
        global active_strategy
        active_strategy = strategy_params.copy()
        if self.advanced_mode_var.get():
            self.apply_advanced_options()
        self.selected_strategy_label.configure(text=f"Estrategia seleccionada: {strategy_name}")
        log(f"Estrategia '{strategy_name}' seleccionada.")

    def save_tp_sl_settings(self):
        SETTINGS["TAKE_PROFIT_ENABLED"] = self.tp_enabled_var.get()
        SETTINGS["STOP_LOSS_ENABLED"] = self.sl_enabled_var.get()

    def start_trading(self):
        self.save_tp_sl_settings()
        self.bot_started = True
        self.trading_info.configure(text="Trading iniciado.")
        self.notebook.set("Logs")

    def restart_trading(self):
        global CANDLES, ACTIONS, TRADING_ALLOWED, trade_total
        CANDLES = {}
        ACTIONS = {}
        TRADING_ALLOWED = True
        trade_total = 0
        self.bot_started = True
        self.trading_info.configure(text="Trading reiniciado. Consultando operaciones...")
        log("Operativa reiniciada por el usuario.")

    def update_trade_counts(self):
        global trade_total
        self.trade_total_label.configure(text=f"Total operaciones: {trade_total}")
        self.after(3000, self.update_trade_counts)

    def create_logs_tab(self):
        frame = self.notebook.tab("Logs")
        label = ctk.CTkLabel(frame, text="Logs del Bot (2.1.3)", font=("Segoe UI", 24, "bold"))
        label.pack(pady=10)
        self.text_logs = ctk.CTkTextbox(frame, width=1100, height=600, state="disabled", font=("Segoe UI", 12))
        self.text_logs.pack(padx=10, pady=10)
        self.after(1000, self.update_logs)

    def update_logs(self):
        try:
            while True:
                msg = log_queue.get_nowait()
                self.text_logs.configure(state="normal")
                self.text_logs.insert("end", msg + "\n")
                self.text_logs.see("end")
                self.text_logs.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(1000, self.update_logs)

    def on_closing(self):
        if messagebox.askokcancel("Salir", "¿Desea salir?"):
            self.destroy()

# -------------------------------
# FUNCIONES DEL BOT (Indicadores, estrategias y trading)
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

def atr(candles, period):
    trs = []
    for i in range(1, len(candles)):
        current = candles[i]
        prev = candles[i-1]
        high = current[3]
        low = current[4]
        prev_close = prev[2]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period

async def moving_averages_cross(candles, sstrategy=None):
    fast_ma = sstrategy.get("FAST_MA", 3) if sstrategy else 3
    slow_ma = sstrategy.get("SLOW_MA", 8) if sstrategy else 8
    if fast_ma == 0 or slow_ma == 0 or fast_ma >= slow_ma:
        log("Parámetros de medias móviles incorrectos.")
        return None
    prices = [c[2] for c in candles]
    fast_ma_value = sum(prices[-fast_ma:]) / fast_ma
    slow_ma_value = sum(prices[-slow_ma:]) / slow_ma
    return "call" if fast_ma_value > slow_ma_value else "put"

async def calculate_last_wma(prices, period):
    if len(prices) < period:
        raise ValueError("Datos insuficientes para WMA.")
    weights = list(range(1, period + 1))
    weighted_prices = [prices[i] * weights[i] for i in range(-period, 0)]
    return sum(weighted_prices) / sum(weights)

async def calculate_last_ema(prices, period, multiplier):
    if len(prices) < period:
        raise ValueError("Datos insuficientes para EMA.")
    sma = sum(prices[:period]) / period
    ema = sma
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

async def get_rsi(candles, sstrategy=None):
    period = sstrategy.get("RSI_PERIOD", 14) if sstrategy else 14
    prices = [c[2] for c in candles]
    if len(prices) < period + 1:
        log("⚠️ Advertencia: No hay suficientes datos para calcular el RSI.")
        return None
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
    if avg_loss == 0:
        return [100]
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return [rsi]

async def rsi_strategy(candles, action, sstrategy=None):
    rsi = await get_rsi(candles, sstrategy)
    if rsi is None:
        return None
    rsi_lower = sstrategy.get("RSI_LOWER", 30) if sstrategy else 30
    rsi_upper = sstrategy.get("RSI_UPPER", 70) if sstrategy else 70
    if action == "call" and rsi[-1] < rsi_lower:
        return "call"
    elif action == "put" and rsi[-1] > rsi_upper:
        return "put"
    return None

async def combined_strategy(candles, sstrategy=None):
    strategy = active_strategy if active_strategy is not None else {}
    base_signal = await moving_averages_cross(candles, sstrategy=strategy)
    if not base_signal:
        return None
    if strategy.get("USE_RSI", False) or SETTINGS.get("USE_RSI", True):
        rsi_sig = await rsi_strategy(candles, base_signal, sstrategy=strategy)
        if not rsi_sig:
            return None
    prices = [c[2] for c in candles]
    if strategy.get("USE_MACD", False) or SETTINGS.get("USE_MACD", False):
        macd_line, signal_line = calculate_macd(prices,
                                                 strategy.get("MACD_FAST", 12),
                                                 strategy.get("MACD_SLOW", 26),
                                                 strategy.get("MACD_SIGNAL", 9))
        if not macd_line or not signal_line:
            return None
        if base_signal == "call" and macd_line[-1] <= signal_line[-1]:
            return None
        if base_signal == "put" and macd_line[-1] >= signal_line[-1]:
            return None
    if strategy.get("USE_BOLLINGER", False) or SETTINGS.get("USE_BOLLINGER", False):
        middle, upper, lower = bollinger_bands(prices,
                                               strategy.get("BOLLINGER_PERIOD", 20),
                                               strategy.get("BOLLINGER_K", 2))
        if middle is None:
            return None
        if base_signal == "call" and prices[-1] > upper:
            return None
        if base_signal == "put" and prices[-1] < lower:
            return None
    if strategy.get("USE_ATR", False) or SETTINGS.get("USE_ATR", False):
        atr_value = atr(candles, strategy.get("ATR_PERIOD", 14))
        if atr_value is not None and atr_value < 0.1:
            log("ATR demasiado bajo, evitando operación.")
            return None
    return base_signal

async def check_strategies(candles, sstrategy=None):
    strategy = active_strategy if active_strategy is not None else {}
    signal = await combined_strategy(candles, sstrategy=strategy)
    if signal:
        return signal, "Señal generada con estrategia activa."
    return None, "No se generó señal con la estrategia activa."

async def get_price_action(candles, action):
    if action == "call":
        if candles[-1][2] > candles[-3][2]:
            return action
    elif action == "put":
        if candles[-1][2] < candles[-3][2]:
            return action
    return None

async def switch_to_asset(driver, asset):
    global CURRENT_ASSET
    asset_items = driver.find_elements(By.CLASS_NAME, "assets-favorites-item")
    for item in asset_items:
        if item.get_attribute("data-id") != asset:
            continue
        while True:
            await asyncio.sleep(0.1)
            if "assets-favorites-item--active" in item.get_attribute("class"):
                CURRENT_ASSET = asset
                return True
            try:
                item.click()
            except Exception:
                log(f"Asset {asset} fuera de alcance.")
                return False
    if asset == CURRENT_ASSET:
        return True
    return False

async def check_payout(driver, asset):
    try:
        payout_text = driver.find_element(By.CLASS_NAME, "value__val-start").text
        payout_val = int(payout_text[1:-1])
        if payout_val >= SETTINGS["MIN_PAYOUT"]:
            return True
        else:
            log(f"Payout {payout_text[1:]} no permitido para {asset}")
            ACTIONS[asset] = datetime.now() + timedelta(minutes=1)
            return False
    except Exception as e:
        log("Error en check_payout:", e)
        return False

async def check_trades():
    global TRADING_ALLOWED
    return True

async def create_order(driver, action, asset, sstrategy=None):
    max_trades = int(SETTINGS.get("MAX_SIMULTANEOUS_TRADES", 2))
    if len(ACTIONS) >= max_trades:
        global limit_logged
        if not limit_logged:
            log("Límite de operaciones alcanzado.")
            limit_logged = True
        return False
    else:
        limit_logged = False
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
            log(f"Máximo de operaciones alcanzado. Adquiere licencia: {LICENSE_BUY_URL}")
            driver.get(LICENSE_BUY_URL)
            return False
        vice_versa = sstrategy.get("vice_versa", False) if sstrategy else SETTINGS.get("VICE_VERSA", False)
        if vice_versa:
            action = "call" if action == "put" else "put"
        driver.find_element(By.CLASS_NAME, f"btn-{action}").click()
        ACTIONS[asset] = datetime.now()
        global trade_total
        trade_total += 1
        log(f"{action.capitalize()} en {asset}")
    except Exception as e:
        log("No se pudo crear la orden:", e)
        return False
    return True

async def get_candles_yfinance(email, asset, timeframe):
    response = requests.get(CANDLES_URL, params={"asset": asset, "email": email})
    if response.status_code != 200:
        raise Exception(response.json()["error"])
    candles = [["", "", c] for c in response.json()[asset]]
    return candles

async def backtest(email, timeframe="1m"):
    assets = requests.get(ASSETS_URL, params={"email": email})
    if assets.status_code != 200:
        log(assets.json()["error"])
        return
    PROFITS = []
    for asset in assets.json()["assets"]:
        await asyncio.sleep(0.7)
        try:
            candles = await get_candles_yfinance(email, asset, timeframe=timeframe)
        except:
            log(f"Backtest en {asset} ({timeframe}): Sin candles.")
            continue
        if not candles:
            log(f"Backtest en {asset} ({timeframe}): Sin candles.")
            continue
        size = max(SETTINGS.get("SLOW_MA", 8), SETTINGS.get("RSI_PERIOD", 14)) + 11
        actions = {}
        for i in range(size, len(candles) + 1):
            candles_part = candles[i-size:i]
            action, _ = await check_strategies(candles_part, sstrategy=active_strategy)
            if action:
                actions[i] = action
        per = int(len(candles) / len(actions)) if actions else 0
        log(f"Backtest en {asset} ({timeframe}): 1 orden cada {per} candles.")
        for estimation in [1, 2, 3]:
            wins = 0
            draws = 0
            for i, action in actions.items():
                try:
                    if candles[i][2] == candles[i+estimation][2]:
                        draws += 1
                    if action == "call" and candles[i][2] < candles[i+estimation][2]:
                        wins += 1
                    elif action == "put" and candles[i][2] > candles[i+estimation][2]:
                        wins += 1
                except IndexError:
                    pass
            try:
                profit = wins * 100 // (len(actions) - draws) if (len(actions) - draws) > 0 else 0
                PROFITS.append(profit)
                log(f"Estimación {estimation} candles: Beneficio {profit}%")
            except ZeroDivisionError:
                log("Sin operaciones.")
                continue
    log(f"Beneficio promedio backtest: {sum(PROFITS) // len(PROFITS) if PROFITS else 0}%")
    log("Backtest finalizado, iniciando trading...")

OPEN_ORDERS = {}

async def check_indicators(driver):
    limpiar_operaciones()
    strategy = active_strategy if active_strategy is not None else {}
    for asset, candles in CANDLES.items():
        if asset in OPEN_ORDERS and candles:
            order_time = OPEN_ORDERS[asset].timestamp()
            if candles[-1][0] < order_time + PERIOD:
                continue
            else:
                del OPEN_ORDERS[asset]
        action, reason = await check_strategies(candles, sstrategy=strategy)
        if not action:
            continue
        order_created = await create_order(driver, action, asset, sstrategy=strategy)
        if order_created:
            OPEN_ORDERS[asset] = datetime.now()
            log(f"Orden {action} en {asset} tomada: {reason}")
            await asyncio.sleep(1)
            return

async def check_deposit(driver):
    global INITIAL_DEPOSIT, TRADING_ALLOWED
    try:
        deposit_elem = driver.find_element(By.CSS_SELECTOR,
            "body > div.wrapper > div.wrapper__top > header > div.right-block.js-right-block > div.right-block__item.js-drop-down-modal-open > div > div.balance-info-block__data > div.balance-info-block__balance > span")
        deposit_text = deposit_elem.text.replace(",", "").strip()
        if "*" in deposit_text:
            log("Saldo enmascarado recibido:", deposit_text)
            return
        deposit = float(deposit_text)
    except Exception as e:
        log("Error al leer saldo:", e)
        return
    if INITIAL_DEPOSIT is None:
        INITIAL_DEPOSIT = deposit
        log(f"Depósito inicial: {INITIAL_DEPOSIT}")
        await asyncio.sleep(1)
        return
    if SETTINGS.get("TAKE_PROFIT_ENABLED", False):
        if deposit > INITIAL_DEPOSIT + SETTINGS.get("TAKE_PROFIT", 100):
            log(f"Take profit alcanzado. Inicial: {INITIAL_DEPOSIT}, actual: {deposit}")
            TRADING_ALLOWED = False
    if SETTINGS.get("STOP_LOSS_ENABLED", False):
        if deposit < INITIAL_DEPOSIT - SETTINGS.get("STOP_LOSS", 50):
            log(f"Stop loss alcanzado. Inicial: {INITIAL_DEPOSIT}, actual: {deposit}")
            TRADING_ALLOWED = False

async def websocket_log(driver):
    global PERIOD, CANDLES, ACTIONS, FAVORITES_REANIMATED, LAST_FAVORITES_UPDATE
    try:
        logs = driver.get_log("performance")
    except InvalidSessionIdException:
        log("Sesión Chrome cerrada. Saliendo de websocket_log.")
        raise
    for wsData in logs:
        try:
            message = json.loads(wsData["message"])["message"]
        except Exception:
            continue
        response = message.get("params", {}).get("response", {})
        if response.get("opcode", 0) == 2:
            try:
                payload_str = base64.b64decode(response["payloadData"]).decode("utf-8")
                data = json.loads(payload_str)
            except Exception:
                continue
            if "history" in data:
                asset_name = data["asset"]
                if asset_name not in CANDLES:
                    CANDLES[asset_name] = []
                if PERIOD != data["period"]:
                    PERIOD = data["period"]
                    CANDLES = {}
                    ACTIONS = {}
                    FAVORITES_REANIMATED = False
                    LAST_FAVORITES_UPDATE = 0
                candles = list(reversed(data["candles"]))
                for tstamp, value in data["history"]:
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
                # Actualiza favoritos solo al cerrar la vela actual
                latest_candle_time = max(c[0] for c in candles) if candles else 0
                if latest_candle_time > LAST_FAVORITES_UPDATE:
                    LAST_FAVORITES_UPDATE = latest_candle_time
                    await reanimate_favorites(driver)
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

async def reanimate_favorites(driver):
    global FAVORITES_REANIMATED, CURRENT_ASSET
    asset_items = driver.find_elements(By.CLASS_NAME, "assets-favorites-item")
    for item in asset_items:
        try:
            item.click()
            log(f"Actualizando favorito: {item.get_attribute('data-id')}")
        except Exception:
            log(f"Asset {item.get_attribute('data-id')} fuera de alcance.")
            continue
    FAVORITES_REANIMATED = True

async def set_amount_icon(driver):
    amount_style = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control-buttons__wrapper > div > a")
    try:
        amount_style.find_element(By.CLASS_NAME, "currency-icon--usd")
    except NoSuchElementException:
        amount_style.click()

async def set_estimation_icon(driver):
    time_style = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control-buttons__wrapper > div > a > div > div > svg")
    if "exp-mode-2.svg" in time_style.get_attribute("data-src"):
        time_style.click()

async def get_estimation(driver):
    estimation = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control__value.value.value--several-items")
    est = datetime.strptime(estimation.text, "%H:%M:%S")
    return (est.hour * 3600) + (est.minute * 60) + est.second

async def main():
    driver = await get_driver()
    driver.get(URL)
    await asyncio.sleep(5)
    log("Chrome abierto; por favor inicia sesión en Pocket Option.")
    while not app.login_confirmed and not app.tk.call("wm", "state", app._w) == "withdrawn":
        await asyncio.sleep(1)
    log("Validando licencia y consultando saldo...")
    await validate_license(driver)
    await check_deposit(driver)
    while not app.bot_started:
        await asyncio.sleep(1)
    log("Trading iniciado. Ejecutando operaciones...")
    while True:
        try:
            limpiar_operaciones()
            if not TRADING_ALLOWED:
                await asyncio.sleep(1)
                continue
            await websocket_log(driver)
            await check_indicators(driver)
            await check_deposit(driver)
            await asyncio.sleep(1)
        except InvalidSessionIdException:
            log("Sesión Chrome cerrada. Saliendo del ciclo principal.")
            break
        except Exception as e:
            log("Excepción en ciclo principal:", e)
            await asyncio.sleep(1)

if __name__ == "__main__":
    load_settings()
    app = FlixerBotApp()
    bot_thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
    bot_thread.start()
    app.mainloop()
