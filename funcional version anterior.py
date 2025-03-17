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
    "USE_BOLLINGER": False,
    "USE_ATR": False,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "BOLLINGER_PERIOD": 20,
    "BOLLINGER_K": 2,
    "ATR_PERIOD": 14
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
                log(f"Nueva versión disponible: {remote_version}. Actualizando... Por favor, espere mientras el bot se reinicia; este proceso puede tardar unos minutos.")
                update_response = requests.get(download_url, timeout=10)
                if update_response.status_code == 200:
                    if not getattr(sys, 'frozen', False):
                        with open(sys.argv[0], "wb") as f:
                            f.write(update_response.content)
                        log("Actualización aplicada. Reiniciando el bot para usar la nueva versión. Esta iniciara en un instante")
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

# ===============================
# NUEVO DISEÑO DE INTERFACES (SOLO VISUAL)
# ===============================
# Paleta de colores: fondo oscuro (#141414), textos claros (#EEEEEE) y acentos en naranja (#FF9800) y azul (#2196F3).

def apply_custom_style(root):
    style = ttk.Style(root)
    root.configure(bg="#141414")
    style.theme_use("clam")
    style.configure("TLabel", background="#141414", foreground="#EEEEEE", font=("Segoe UI", 12))
    style.configure("Header.TLabel", background="#141414", foreground="#FF9800", font=("Segoe UI", 16, "bold"))
    style.configure("TButton", background="#1E1E1E", foreground="#EEEEEE", font=("Segoe UI", 11), relief="flat")
    style.map("TButton", background=[("active", "#2196F3")], foreground=[("active", "#FFFFFF")])
    style.configure("TEntry", fieldbackground="#1E1E1E", foreground="#EEEEEE", font=("Segoe UI", 11))
    style.configure("TCheckbutton", background="#141414", foreground="#EEEEEE", font=("Segoe UI", 11))
    style.configure("TNotebook", background="#141414", foreground="#EEEEEE")
    style.configure("TFrame", background="#141414")
    return style

# Ventana de confirmación de inicio de sesión (síncrona, para continuar la ejecución)
def login_confirmation_window():
    root = tk.Tk()
    root.title("Inicia Sesión - FlixerBot_v2 (2.0.1)")
    root.geometry("450x250")
    try:
        root.iconbitmap("logo.ico")
    except Exception:
        pass
    apply_custom_style(root)
    
    frame = ttk.Frame(root, padding="30")
    frame.pack(expand=True, fill="both")
    
    lbl_title = ttk.Label(frame, text="Bienvenido a FlixerBot", style="Header.TLabel")
    lbl_title.pack(pady=(0,15))
    
    lbl_instr = ttk.Label(frame, text="Inicia sesión en Pocket Option y luego presiona el botón para confirmar.", justify="center")
    lbl_instr.pack(pady=(0,20))
    
    confirmed = threading.Event()
    def on_confirm():
        confirmed.set()
        root.destroy()
    btn_confirm = ttk.Button(frame, text="He iniciado sesión", command=on_confirm)
    btn_confirm.pack(pady=10)
    root.mainloop()
    return confirmed.is_set()

# Ventana de estado (diseño moderno)
def show_status_window(estado, mensaje, countdown=180):
    root = tk.Tk()
    root.title("Estado del Bot - FlixerBot_v2")
    root.geometry("550x350")
    root.resizable(False, False)
    try:
        root.iconbitmap("logo.ico")
    except Exception:
        pass
    apply_custom_style(root)
    
    frame = ttk.Frame(root, padding="30")
    frame.pack(expand=True, fill="both")
    
    lbl_estado = ttk.Label(frame, text=f"Estado: {estado}", style="Header.TLabel")
    lbl_estado.pack(pady=(0,20))
    
    lbl_mensaje = ttk.Label(frame, text=mensaje, wraplength=480, justify="center")
    lbl_mensaje.pack(pady=(0,20))
    
    progress = ttk.Progressbar(frame, orient="horizontal", length=400, mode="determinate")
    progress.pack(pady=10)
    lbl_timer = ttk.Label(frame, text="", font=("Segoe UI", 10))
    lbl_timer.pack(pady=(10,0))
    
    def update_progress(remaining):
        progress['maximum'] = countdown
        progress['value'] = countdown - remaining
        lbl_timer.config(text=f"Iniciando en {remaining} segundos")
        if remaining > 0:
            root.after(1000, update_progress, remaining - 1)
        else:
            root.destroy()
    update_progress(countdown)
    root.mainloop()

# NUEVA VENTANA DE CONFIGURACIÓN: Utilizamos grid para separar el contenido y el footer fijo.
def tkinter_run():
    global window
    window = tk.Tk()
    window.title("Configuración FlixerBot_v2")
    window.minsize(900, 700)
    try:
        window.iconbitmap("logo.ico")
    except Exception:
        pass
    apply_custom_style(window)
    
    # Configuramos la ventana con grid: dos filas (contenido y footer)
    window.rowconfigure(0, weight=1)
    window.rowconfigure(1, weight=0)
    window.columnconfigure(0, weight=1)
    
    # Área de contenido con Notebook (fila 0)
    notebook = ttk.Notebook(window)
    notebook.grid(row=0, column=0, sticky="nsew", padx=20, pady=(20,10))
    
    # Pestaña: Tutorial
    frame_tutorial = ttk.Frame(notebook, padding="20")
    notebook.add(frame_tutorial, text="Tutorial")
    tutorial_text = (
        "• Agrega los activos a favoritos en la plataforma.\n"
        "• Configura el tiempo de expiración y el monto de operación.\n"
        "• Si operas con varios activos, desactiva Martingale.\n"
        "• Prueba las estrategias en cuenta demo antes de operar en real.\n"
        "• El bot se actualizará automáticamente cuando sea necesario."
    )
    ttk.Label(frame_tutorial, text=tutorial_text, justify="left", wraplength=600).pack(pady=10)
    
    # Pestaña: General
    frame_general = ttk.Frame(notebook, padding="20")
    notebook.add(frame_general, text="General")
    ttk.Label(frame_general, text="Pago Mínimo (%):").grid(row=0, column=0, sticky="w", padx=10, pady=10)
    min_payout_var = tk.IntVar(value=SETTINGS.get('MIN_PAYOUT', 80))
    ttk.Entry(frame_general, textvariable=min_payout_var, width=8).grid(row=0, column=1, padx=10, pady=10)
    ttk.Label(frame_general, text="Take Profit ($):").grid(row=1, column=0, sticky="w", padx=10, pady=10)
    take_profit_var = tk.IntVar(value=SETTINGS.get('TAKE_PROFIT', 100))
    ttk.Entry(frame_general, textvariable=take_profit_var, width=8).grid(row=1, column=1, padx=10, pady=10)
    ttk.Label(frame_general, text="Stop Loss ($):").grid(row=2, column=0, sticky="w", padx=10, pady=10)
    stop_loss_var = tk.IntVar(value=SETTINGS.get('STOP_LOSS', 50))
    ttk.Entry(frame_general, textvariable=stop_loss_var, width=8).grid(row=2, column=1, padx=10, pady=10)
    chk_vice_var = tk.IntVar(value=1 if SETTINGS.get('VICE_VERSA', False) else 0)
    ttk.Checkbutton(frame_general, text="Vice Versa (Invertir Call/Put)", variable=chk_vice_var).grid(row=3, column=0, columnspan=2, padx=10, pady=10, sticky="w")
    
    # Pestaña: Estrategia – Dividida en dos columnas para mejor visibilidad
    frame_strategy = ttk.Frame(notebook, padding="20")
    notebook.add(frame_strategy, text="Estrategia")
    
    # Creamos dos frames internos para organizar la información en dos columnas
    left_frame = ttk.Frame(frame_strategy)
    left_frame.grid(row=0, column=0, sticky="nsew", padx=(0,20))
    right_frame = ttk.Frame(frame_strategy)
    right_frame.grid(row=0, column=1, sticky="nsew")
    
    # Configuramos que ambas columnas se expandan uniformemente
    frame_strategy.columnconfigure(0, weight=1)
    frame_strategy.columnconfigure(1, weight=1)
    
    # --- Izquierda (parámetros de medias y RSI) ---
    ttk.Label(left_frame, text="Fast MA:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
    fast_ma_var = tk.IntVar(value=SETTINGS.get('FAST_MA', 3))
    ttk.Entry(left_frame, textvariable=fast_ma_var, width=8).grid(row=0, column=1, padx=10, pady=5)
    
    ttk.Label(left_frame, text="Tipo Fast MA:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
    fast_ma_type = tk.StringVar(value=SETTINGS.get('FAST_MA_TYPE', 'SMA'))
    ttk.OptionMenu(left_frame, fast_ma_type, fast_ma_type.get(), "SMA", "EMA", "WMA").grid(row=1, column=1, padx=10, pady=5)
    
    ttk.Label(left_frame, text="Slow MA:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
    slow_ma_var = tk.IntVar(value=SETTINGS.get('SLOW_MA', 8))
    ttk.Entry(left_frame, textvariable=slow_ma_var, width=8).grid(row=2, column=1, padx=10, pady=5)
    
    ttk.Label(left_frame, text="Tipo Slow MA:").grid(row=3, column=0, sticky="w", padx=10, pady=5)
    slow_ma_type = tk.StringVar(value=SETTINGS.get('SLOW_MA_TYPE', 'SMA'))
    ttk.OptionMenu(left_frame, slow_ma_type, slow_ma_type.get(), "SMA", "EMA", "WMA").grid(row=3, column=1, padx=10, pady=5)
    
    ttk.Label(left_frame, text="RSI Period:").grid(row=4, column=0, sticky="w", padx=10, pady=5)
    rsi_period_var = tk.IntVar(value=SETTINGS.get('RSI_PERIOD', 14))
    ttk.Entry(left_frame, textvariable=rsi_period_var, width=8).grid(row=4, column=1, padx=10, pady=5)
    
    ttk.Label(left_frame, text="RSI Upper:").grid(row=5, column=0, sticky="w", padx=10, pady=5)
    rsi_upper_var = tk.IntVar(value=SETTINGS.get('RSI_UPPER', 70))
    ttk.Entry(left_frame, textvariable=rsi_upper_var, width=8).grid(row=5, column=1, padx=10, pady=5)
    
    use_rsi_var = tk.IntVar(value=1 if SETTINGS.get('USE_RSI', True) else 0)
    ttk.Checkbutton(left_frame, text="Usar RSI", variable=use_rsi_var).grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=5)
    
    # --- Derecha (parámetros de MACD, Bollinger y estrategia combinada) ---
    ttk.Label(right_frame, text="MACD Fast:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
    macd_fast_var = tk.IntVar(value=SETTINGS.get('MACD_FAST', 12))
    ttk.Entry(right_frame, textvariable=macd_fast_var, width=8).grid(row=0, column=1, padx=10, pady=5)
    
    ttk.Label(right_frame, text="MACD Slow:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
    macd_slow_var = tk.IntVar(value=SETTINGS.get('MACD_SLOW', 26))
    ttk.Entry(right_frame, textvariable=macd_slow_var, width=8).grid(row=1, column=1, padx=10, pady=5)
    
    ttk.Label(right_frame, text="MACD Signal:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
    macd_signal_var = tk.IntVar(value=SETTINGS.get('MACD_SIGNAL', 9))
    ttk.Entry(right_frame, textvariable=macd_signal_var, width=8).grid(row=2, column=1, padx=10, pady=5)
    
    ttk.Label(right_frame, text="Bollinger Period:").grid(row=3, column=0, sticky="w", padx=10, pady=5)
    bollinger_period_var = tk.IntVar(value=SETTINGS.get('BOLLINGER_PERIOD', 20))
    ttk.Entry(right_frame, textvariable=bollinger_period_var, width=8).grid(row=3, column=1, padx=10, pady=5)
    
    ttk.Label(right_frame, text="Bollinger K:").grid(row=4, column=0, sticky="w", padx=10, pady=5)
    bollinger_k_var = tk.IntVar(value=SETTINGS.get('BOLLINGER_K', 2))
    ttk.Entry(right_frame, textvariable=bollinger_k_var, width=8).grid(row=4, column=1, padx=10, pady=5)
    
    use_macd_var = tk.IntVar(value=1 if SETTINGS.get('USE_MACD', False) else 0)
    ttk.Checkbutton(right_frame, text="Usar MACD", variable=use_macd_var).grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=5)
    
    use_bollinger_var = tk.IntVar(value=1 if SETTINGS.get('USE_BOLLINGER', False) else 0)
    ttk.Checkbutton(right_frame, text="Usar Bollinger Bands", variable=use_bollinger_var).grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=5)
    
    combined_var = tk.IntVar(value=1 if SETTINGS.get('COMBINED_STRATEGY_ENABLED', False) else 0)
    ttk.Checkbutton(right_frame, text="Estrategia combinada", variable=combined_var).grid(row=7, column=0, columnspan=2, sticky="w", padx=10, pady=5)
    
    # Presets: Área para ajustes predefinidos debajo de las columnas
    preset_frame = ttk.Frame(frame_strategy, padding="10")
    preset_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(20,0))
    
    def preset_45():
        fast_ma_var.set(9)
        slow_ma_var.set(21)
        rsi_period_var.set(14)
        rsi_upper_var.set(70)
        
    def preset_23():
        fast_ma_var.set(7)
        slow_ma_var.set(14)
        rsi_period_var.set(10)
        rsi_upper_var.set(65)
        
    def preset_1():
        fast_ma_var.set(3)
        slow_ma_var.set(8)
        rsi_period_var.set(7)
        rsi_upper_var.set(60)
    
    btn_preset_45 = ttk.Button(preset_frame, text="4/5 min gráfico", command=preset_45)
    btn_preset_45.pack(side="left", padx=5)
    btn_preset_23 = ttk.Button(preset_frame, text="2/3 min gráfico", command=preset_23)
    btn_preset_23.pack(side="left", padx=5)
    btn_preset_1 = ttk.Button(preset_frame, text="1 min gráfico", command=preset_1)
    btn_preset_1.pack(side="left", padx=5)


    
    # Pestaña: Martingale
    frame_gale = ttk.Frame(notebook, padding="20")
    notebook.add(frame_gale, text="Martingale")
    ttk.Label(frame_gale, text="Niveles de Martingale (ej: 1,2,4,8):").grid(row=0, column=0, sticky="w", padx=10, pady=10)
    martingale_str = ', '.join([str(v) for v in SETTINGS.get('MARTINGALE_LIST', [1, 2, 4, 8])])
    martingale_var = tk.StringVar(value=martingale_str)
    ttk.Entry(frame_gale, textvariable=martingale_var, width=15).grid(row=0, column=1, padx=10, pady=10)
    martingale_flag = tk.IntVar(value=1 if SETTINGS.get('MARTINGALE_ENABLED', False) else 0)
    ttk.Checkbutton(frame_gale, text="Activar Martingale", variable=martingale_flag).grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="w")
    
    # Footer fijo (fila 1) con el botón "Guardar y Cerrar"
    footer_frame = ttk.Frame(window)
    footer_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=20)
    footer_frame.columnconfigure(0, weight=1)
    
    def guardar_config():
        try:
            new_settings = {
                "MIN_PAYOUT": int(min_payout_var.get()),
                "TAKE_PROFIT": int(take_profit_var.get()),
                "STOP_LOSS": int(stop_loss_var.get()),
                "VICE_VERSA": True if chk_vice_var.get() else False,
                "FAST_MA": int(fast_ma_var.get()),
                "FAST_MA_TYPE": fast_ma_type.get(),
                "SLOW_MA": int(slow_ma_var.get()),
                "SLOW_MA_TYPE": slow_ma_type.get(),
                "RSI_PERIOD": int(rsi_period_var.get()),
                "RSI_UPPER": int(rsi_upper_var.get()),
                "RSI_CALL_SIGN": SETTINGS.get("RSI_CALL_SIGN", ">"),
                "USE_RSI": True if use_rsi_var.get() == 1 else False,
                "USE_MACD": True if use_macd_var.get() == 1 else False,
                "USE_BOLLINGER": True if use_bollinger_var.get() == 1 else False,
                "MACD_FAST": int(macd_fast_var.get()),
                "MACD_SLOW": int(macd_slow_var.get()),
                "MACD_SIGNAL": int(macd_signal_var.get()),
                "BOLLINGER_PERIOD": int(bollinger_period_var.get()),
                "BOLLINGER_K": int(bollinger_k_var.get()),
                "COMBINED_STRATEGY_ENABLED": True if combined_var.get() == 1 else False,
                "MARTINGALE_ENABLED": True if martingale_flag.get() == 1 else False,
                "MARTINGALE_LIST": [int(x) for x in martingale_var.get().split(",")]
            }
        except Exception as e:
            messagebox.showerror("Error de configuración", str(e))
            return
        save_settings(**new_settings)
        window.destroy()
    
    btn_guardar = ttk.Button(footer_frame, text="Guardar y Cerrar", command=guardar_config)
    btn_guardar.grid(row=0, column=1, sticky="e")
    
    window.mainloop()

# Nueva ventana de operaciones en tiempo real (diseño moderno)
def run_realtime_gui():
    rt_window = tk.Tk()
    rt_window.title("Operaciones en Tiempo Real - FlixerBot_v2")
    rt_window.geometry("950x650")
    try:
        rt_window.iconbitmap("logo.ico")
    except Exception:
        pass
    apply_custom_style(rt_window)
    
    main_frame = ttk.Frame(rt_window)
    main_frame.pack(expand=True, fill="both", padx=20, pady=20)
    
    # Panel lateral para configuración en vivo
    side_frame = ttk.Frame(main_frame, width=250)
    side_frame.pack(side="left", fill="y", padx=(0,20))
    side_frame.pack_propagate(0)
    
    lbl_live = ttk.Label(side_frame, text="Configuración\nEn Vivo", style="Header.TLabel", anchor="center")
    lbl_live.pack(pady=(0,20))
    
    ttk.Label(side_frame, text="Min Payout %:").pack(anchor="w", padx=10, pady=5)
    min_payout_var_rt = tk.StringVar(value=str(SETTINGS.get("MIN_PAYOUT")))
    ttk.Entry(side_frame, textvariable=min_payout_var_rt, width=10).pack(anchor="w", padx=10)
    
    ttk.Label(side_frame, text="Take Profit $:").pack(anchor="w", padx=10, pady=5)
    take_profit_var_rt = tk.StringVar(value=str(SETTINGS.get("TAKE_PROFIT")))
    ttk.Entry(side_frame, textvariable=take_profit_var_rt, width=10).pack(anchor="w", padx=10)
    
    ttk.Label(side_frame, text="Stop Loss $:").pack(anchor="w", padx=10, pady=5)
    stop_loss_var_rt = tk.StringVar(value=str(SETTINGS.get("STOP_LOSS")))
    ttk.Entry(side_frame, textvariable=stop_loss_var_rt, width=10).pack(anchor="w", padx=10)
    
    ttk.Label(side_frame, text="Martingale:").pack(anchor="w", padx=10, pady=5)
    martingale_var_rt = tk.StringVar(value=",".join(str(x) for x in SETTINGS.get("MARTINGALE_LIST")))
    ttk.Entry(side_frame, textvariable=martingale_var_rt, width=15).pack(anchor="w", padx=10)
    
    def actualizar_config_rt():
        try:
            new_min_payout = int(min_payout_var_rt.get())
            new_take_profit = int(take_profit_var_rt.get())
            new_stop_loss = int(stop_loss_var_rt.get())
            new_martingale = [int(x) for x in martingale_var_rt.get().split(",")]
            SETTINGS["MIN_PAYOUT"] = new_min_payout
            SETTINGS["TAKE_PROFIT"] = new_take_profit
            SETTINGS["STOP_LOSS"] = new_stop_loss
            SETTINGS["MARTINGALE_LIST"] = new_martingale
            save_settings(**SETTINGS)
            log("Configuración actualizada en vivo.")
        except Exception as e:
            log("Error actualizando configuración en vivo:", e)
    
    ttk.Button(side_frame, text="Actualizar", command=actualizar_config_rt).pack(pady=15, padx=10)
    
    # Área de logs
    log_frame = ttk.Frame(main_frame)
    log_frame.pack(side="left", expand=True, fill="both")
    text_area = tk.Text(log_frame, wrap="word", state="disabled", font=("Segoe UI", 10), bg="#1E1E1E", fg="#EEEEEE")
    scrollbar = ttk.Scrollbar(log_frame, command=text_area.yview)
    text_area.configure(yscrollcommand=scrollbar.set)
    text_area.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    def update_text():
        try:
            while True:
                msg = log_queue.get_nowait()
                text_area.configure(state="normal")
                text_area.insert(tk.END, msg + "\n")
                text_area.configure(state="disabled")
                text_area.see(tk.END)
        except queue.Empty:
            pass
        rt_window.after(1000, update_text)
    update_text()
    rt_window.mainloop()

# ===============================
# (Las funciones lógicas del bot permanecen sin cambios)
# ===============================
# FUNCIONES ADICIONALES DE INDICADORES
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
    if SETTINGS.get('USE_ATR', False):
        atr_value = atr(candles, SETTINGS.get('ATR_PERIOD', 14))
        if atr_value is not None and atr_value < 0.1:
            log("ATR demasiado bajo, evitando operación.")
            return None
    return base_signal

async def check_strategies(candles, sstrategy=None):
    if SETTINGS.get('COMBINED_STRATEGY_ENABLED'):
        signal = await combined_strategy(candles, sstrategy)
        if signal:
            return signal, "Estrategia combinada fue aplicada."
        else:
            return None, "Estrategia combinada no generó señal."
    reason = ""
    ma_signal = await moving_averages_cross(candles, sstrategy=sstrategy)
    if not ma_signal:
        reason += "No se detectó cruce de medias; "
        return None, reason
    else:
        reason += f"Señal de cruce de medias y Patron: {ma_signal}; "
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
                    action = 'call' if action == 'put' else 'call'
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

OPEN_ORDERS = {}

async def check_indicators(driver):
    global MARTINGALE_LAST_ACTION_ENDS_AT, MARTINGALE_AMOUNT_SET, MARTINGALE_INITIAL, FIRST_TRADE_DONE, OPEN_ORDERS
    try:
        FIRST_TRADE_DONE
    except NameError:
        FIRST_TRADE_DONE = False
    try:
        OPEN_ORDERS
    except NameError:
        OPEN_ORDERS = {}

    MARTINGALE_LIST = SETTINGS.get('MARTINGALE_LIST')
    base = "#modal-root > div > div > div > div > div.trading-panel-modal__in > div.virtual-keyboard > div > div:nth-child(%s) > div"

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

    for asset, candles in CANDLES.items():
        if asset in OPEN_ORDERS and candles:
            last_timestamp = candles[-1][0]
            order_time = OPEN_ORDERS[asset].timestamp()
            if last_timestamp < (order_time + PERIOD):
                continue
            else:
                del OPEN_ORDERS[asset]
        action = None
        reason = ""
        if SETTINGS.get('COMBINED_STRATEGY_ENABLED'):
            try:
                action = await combined_strategy(candles)
                reason = "Estrategia combinada aplicada."
            except Exception as e:
                log("Error en estrategia combinada:", e)
                continue
        else:
            action, reason = await check_strategies(candles)
        if not action:
            continue
        order_created = await create_order(driver, action, asset)
        if order_created:
            OPEN_ORDERS[asset] = datetime.now()
            log(f"Orden {action} en {asset} tomada porque: {reason}")
            if SETTINGS.get('MARTINGALE_ENABLED'):
                await set_estimation_icon(driver)
                seconds = await get_estimation(driver)
                MARTINGALE_LAST_ACTION_ENDS_AT = datetime.now() + timedelta(seconds=seconds)
                MARTINGALE_AMOUNT_SET = False
            FIRST_TRADE_DONE = True
            await asyncio.sleep(1)
            return

    if SETTINGS.get('MARTINGALE_ENABLED') and not MARTINGALE_AMOUNT_SET:
        if datetime.now() < MARTINGALE_LAST_ACTION_ENDS_AT:
            return
        try:
            deposit = driver.find_element(By.CSS_SELECTOR,
                'body > div.wrapper > div.wrapper__top > header > div.right-block.js-right-block > div.right-block__item.js-drop-down-modal-open > div > div.balance-info-block__data > div.balance-info-block__balance > span')
        except Exception as e:
            log("Error al obtener el depósito:", e)
            return
        try:
            closed_tab = driver.find_element(By.CSS_SELECTOR,
                '#bar-chart > div > div > div.right-widget-container > div > div.widget-slot__header > div.divider > ul > li:nth-child(2) > a')
            closed_tab.click()
            await asyncio.sleep(2)
        except Exception as e:
            log("No se pudo abrir el historial de operaciones cerradas:", e)
        await set_amount_icon(driver)
        closed_trades = driver.find_elements(By.CLASS_NAME, 'deals-list__item')
        if not closed_trades:
            log("No se encontró el historial; verifique que esté desplegado manualmente.")
        else:
            last_split = closed_trades[0].text.split('\n')
            log("Datos de la última operación cerrada:", last_split)
            try:
                amount = driver.find_element(By.CSS_SELECTOR,
                    "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control__value.value.value--several-items > div > input[type=text]")
                amount_value = int(float(amount.get_attribute('value').replace(',', '')))
                result_win = last_split[4] if len(last_split) > 4 else "$0"
                result_draw = last_split[3] if len(last_split) > 3 else "$0"
                log("Result win:", result_win, "Result draw:", result_draw)
                if result_win not in ["$0", "$\u202f0"]:
                    if amount_value != MARTINGALE_LIST[0]:
                        log("Trade ganado. Reiniciando monto a:", MARTINGALE_LIST[0])
                        amount.click()
                        await asyncio.sleep(0.3)
                        for number in str(MARTINGALE_LIST[0]):
                            driver.find_element(By.CSS_SELECTOR, base % NUMBERS[number]).click()
                            await asyncio.sleep(0.3)
                elif result_draw not in ["$0", "$\u202f0"]:
                    log("Trade empatado. Manteniendo monto:", amount_value)
                else:
                    if amount_value in MARTINGALE_LIST:
                        idx = MARTINGALE_LIST.index(amount_value)
                        next_amount = MARTINGALE_LIST[idx+1] if idx+1 < len(MARTINGALE_LIST) else MARTINGALE_LIST[0]
                    else:
                        next_amount = MARTINGALE_LIST[0]
                    if amount_value != next_amount:
                        if next_amount > float(deposit.text.replace(',', '')):
                            log('Martingale no puede configurarse: depósito menor que el siguiente valor.')
                            return
                        log("Trade perdido. Aumentando monto de", amount_value, "a", next_amount)
                        amount.click()
                        await asyncio.sleep(0.3)
                        for number in str(next_amount):
                            driver.find_element(By.CSS_SELECTOR, base % NUMBERS[number]).click()
                            await asyncio.sleep(0.3)
                try:
                    closed_tab_parent = driver.find_element(By.CSS_SELECTOR,
                        '#bar-chart > div > div > div.right-widget-container > div > div.widget-slot__header > div.divider > ul > li:nth-child(2) > a').find_element(By.XPATH, '..')
                    closed_tab_parent.click()
                except Exception:
                    pass
            except Exception as e:
                log("Error en actualización martingale:", e)
        MARTINGALE_AMOUNT_SET = True

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

async def set_amount_icon(driver):
    amount_style = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--bet-amount > div.block__control.control > div.control-buttons__wrapper > div > a")
    try:
        amount_style.find_element(By.CLASS_NAME, 'currency-icon--usd')
    except NoSuchElementException:
        amount_style.click()

async def set_estimation_icon(driver):
    time_style = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control-buttons__wrapper > div > a > div > div > svg")
    if 'exp-mode-2.svg' in time_style.get_attribute('data-src'):
        time_style.click()

async def get_estimation(driver):
    estimation = driver.find_element(By.CSS_SELECTOR, 
        "#put-call-buttons-chart-1 > div > div.blocks-wrap > div.block.block--expiration-inputs > div.block__control.control > div.control__value.value.value--several-items")
    est = datetime.strptime(estimation.text, '%H:%M:%S')
    return (est.hour * 3600) + (est.minute * 60) + est.second

async def main():
    check_for_updates()
    driver = await get_driver()
    driver.get(URL)
    await asyncio.sleep(5)
    log("Abriendo navegador para que inicies sesión en Pocket Option...")
    logged_in = login_confirmation_window()
    if not logged_in:
        log("No se confirmó el inicio de sesión. Bot desactivado.")
        sys.exit(1)
    await validate_license(driver)
    if LICENSE_VALID:
        show_status_window(
            estado="Autorizado",
            mensaje="Configura:\n1. Activos a favoritos.\n2. Tiempo de expiración.\n3. Monto de operación.",
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

if __name__ == '__main__':
    load_settings()
    tkinter_run()
    bot_thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
    bot_thread.start()
    run_realtime_gui()
