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
    "python-multipart", "pyTelegramBotAPI", "requests", "playwright"
]

def install_dependencies():
    for package in REQUIRED_PACKAGES:
        try:
            import_name = package
            if package == "pyTelegramBotAPI": import_name = "telebot"
            if package == "python-multipart": import_name = "multipart"

            if package == "python-multipart":
                 try: import python_multipart
                 except ImportError: raise ImportError
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

# Ensure Playwright Browsers are installed
try:
    logger.info("Checking Playwright browsers...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
except Exception as e:
    logger.error(f"Failed to install Playwright browsers: {e}")

# Imports after installation
import telebot
from telebot.types import MenuButtonWebApp, WebAppInfo
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import requests
import pandas as pd

# --- Global State ---
# Store browser contexts for 2FA flows
# { "session_token": { "playwright": p, "browser": browser, "context": context, "page": page, "username": str, "password": str, "filename": str } }
active_browsers = {}

# --- Browser Based Instagram Login ---
class BrowserInstagram:
    def __init__(self, session_token):
        self.session_token = session_token
        self.p = None
        self.browser = None
        self.page = None
        self.context = None
        self.cookie_string = ""

    def start_login(self, username, password):
        try:
            self.p = sync_playwright().start()
            self.browser = self.p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])

            # Use Desktop User Agent
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 720}
            )
            self.page = self.context.new_page()

            logger.info(f"Navigating to Instagram for {username}...")
            self.page.goto("https://www.instagram.com/accounts/login/")
            self.page.wait_for_selector("input[name='username']", timeout=15000)

            # Fill Credentials
            self.page.fill("input[name='username']", username)
            self.page.fill("input[name='password']", password)
            self.page.click("button[type='submit']")

            # Wait for navigation or error
            # Possible outcomes:
            # 1. Login Success (Redirect to feed or save info) -> check for 'sessionid' cookie
            # 2. 2FA (Security Code input)
            # 3. Error (Bad password, etc)

            # Wait a bit for network activity
            self.page.wait_for_timeout(5000)

            # Check for Cookies First
            if self._check_success():
                return {"status": "success"}

            # Check for 2FA
            if self.page.locator("input[name='verificationCode']").is_visible() or \
               "security code" in self.page.content().lower() or \
               "two-factor" in self.page.content().lower():
                return {"status": "2fa_required"}

            # Check for Errors
            error_el = self.page.locator("p[id='slfErrorAlert']")
            if error_el.is_visible():
                return {"status": "fail", "message": error_el.text_content()}

            # Check for Checkpoint/Challenge
            if "challenge" in self.page.url:
                return {"status": "challenge_required", "message": "Checkpoint required. Please verify manually."}

            # Final check
            if self._check_success():
                return {"status": "success"}

            return {"status": "fail", "message": "Unknown login state. Check screenshot."}

        except Exception as e:
            logger.exception("Browser Login Error")
            return {"status": "error", "message": str(e)}

    def submit_2fa(self, code):
        try:
            self.page.fill("input[name='verificationCode']", code)
            self.page.click("button[type='button']") # Confirm button usually

            # Sometimes button text is "Confirm"
            try:
                self.page.click("button:has-text('Confirm')", timeout=2000)
            except: pass

            self.page.wait_for_timeout(5000)

            if self._check_success():
                return {"status": "success"}

            # Check for error again
            error_el = self.page.locator("p[id='slfErrorAlert']")
            if error_el.is_visible():
                return {"status": "fail", "message": error_el.text_content()}

            return {"status": "fail", "message": "2FA Failed or timed out."}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _check_success(self):
        cookies = self.context.cookies()
        session_id = next((c['value'] for c in cookies if c['name'] == 'sessionid'), None)
        if session_id:
            self.cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            return True
        return False

    def close(self):
        try:
            if self.browser: self.browser.close()
            if self.p: self.p.stop()
        except: pass


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
        "🚀 *Session Forger (Browser Mode)*\n\nClick the button below to access the secure dashboard.",
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

        # Close all active browsers
        for token, data in active_browsers.items():
            try: data['instance'].close()
            except: pass
        active_browsers.clear()

        bot.send_message(chat_id, "🗑️ *All Data Reset*\n\nSession files and browser cache cleared.", parse_mode="Markdown")
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

os.makedirs(DATA_DIR, exist_ok=True)

# HTML Content (Same UI, just ensuring it points to endpoints)
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
        .cyber-input { background: #1e293b; border: 1px solid #334155; color: #fff; transition: all 0.3s; }
        .cyber-input:focus { border-color: #0ea5e9; box-shadow: 0 0 10px rgba(14, 165, 233, 0.5); }
        .cyber-btn { background: linear-gradient(45deg, #0ea5e9, #6366f1); color: white; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; transition: transform 0.2s, box-shadow 0.2s; }
        .cyber-btn:active { transform: scale(0.98); }
        .glass-panel { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1); }
        .file-item { background: rgba(51, 65, 85, 0.5); border: 1px solid rgba(255,255,255,0.05); transition: background 0.2s; }
        .file-item:hover { background: rgba(51, 65, 85, 0.8); }
        .loader { border: 3px solid #f3f3f3; border-top: 3px solid #3498db; border-radius: 50%; width: 20px; height: 20px; animation: spin 1s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .terminal-box { background: #000; border: 1px solid #333; color: #0f0; font-family: 'Fira Code', monospace; font-size: 10px; padding: 10px; border-radius: 6px; overflow-y: auto; max-height: 150px; }
        .term-error { color: #ff5555; }
        .term-info { color: #8be9fd; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
    </style>
</head>
<body x-data="appData()" x-init="initApp()">
    <div class="min-h-screen flex flex-col items-center p-4 relative overflow-hidden">
        <div class="absolute top-[-10%] left-[-10%] w-64 h-64 bg-blue-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob"></div>
        <div class="absolute bottom-[-10%] right-[-10%] w-64 h-64 bg-purple-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-2000"></div>
        <div class="w-full max-w-md glass-panel rounded-2xl p-6 shadow-2xl relative z-10 my-auto">
            <div class="text-center mb-6">
                <div class="w-16 h-16 mx-auto bg-gradient-to-tr from-blue-400 to-purple-500 rounded-full flex items-center justify-center shadow-lg mb-3">
                     <img src="/api/bot-icon" class="w-14 h-14 rounded-full border-2 border-white" alt="Bot">
                </div>
                <h1 class="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">Session Forger</h1>
            </div>
            <div x-show="view === 'home'" x-transition class="space-y-4">
                <button @click="startCreateFlow" class="cyber-btn w-full p-4 rounded-xl shadow-lg flex items-center justify-center space-x-2"><span class="text-2xl">+</span><span>CREATE NEW FILE</span></button>
                <button @click="loadFiles" class="bg-slate-800 hover:bg-slate-700 w-full p-4 rounded-xl shadow-lg border border-slate-600 text-slate-300 font-bold tracking-wider transition">MY FILES</button>
            </div>
            <div x-show="view === 'file_list'" x-transition style="display: none;">
                <div class="flex justify-between items-center mb-4"><button @click="view = 'home'" class="text-slate-400 hover:text-white">← Back</button><h2 class="text-sm font-bold text-blue-300">SAVED FILES</h2></div>
                <div class="space-y-2 max-h-80 overflow-y-auto pr-1">
                    <template x-for="file in files" :key="file.name">
                        <div @click="openFileDetails(file)" class="file-item p-4 rounded-lg flex justify-between items-center cursor-pointer">
                            <div><p class="text-sm font-bold text-white truncate w-40" x-text="file.name"></p><p class="text-[10px] text-slate-400" x-text="file.count + ' Accounts'"></p></div><span class="text-slate-500">›</span>
                        </div>
                    </template>
                    <div x-show="files.length === 0 && !loading" class="text-center py-8 text-slate-500 text-xs">No files found.</div>
                </div>
            </div>
            <div x-show="view === 'file_details'" x-transition style="display: none;">
                <div class="flex justify-between items-center mb-6"><button @click="loadFiles" class="text-slate-400 hover:text-white">← Back</button><div class="text-center"><h2 class="text-sm font-bold text-white truncate max-w-[150px]" x-text="currentFile.name"></h2><button @click="renameFile" class="text-[10px] text-blue-400 underline">Edit Name</button></div><div class="w-8"></div></div>
                <div class="space-y-3">
                    <button @click="addAccountToFile" class="cyber-btn w-full p-3 rounded-lg shadow-lg">ADD ACCOUNT <span class="opacity-75 text-xs ml-1" x-text="'(Next: ' + (currentFile.count + 1) + '.)'"></span></button>
                    <div class="grid grid-cols-2 gap-3 mt-4"><button @click="downloadFile(currentFile.name)" class="p-3 bg-slate-700 hover:bg-slate-600 rounded-lg text-xs font-bold text-white transition">DOWNLOAD</button><button @click="deleteFile(currentFile.name)" class="p-3 bg-red-900/40 hover:bg-red-900/60 border border-red-500/30 rounded-lg text-xs font-bold text-red-300 transition">DELETE</button></div>
                </div>
            </div>
            <div x-show="view === 'login_flow'" x-transition style="display: none;">
                <div class="mb-4 flex items-center"><button @click="cancelLogin" class="text-slate-400 hover:text-white text-xs mr-auto">Cancel</button><span class="text-xs text-slate-500 font-mono" x-show="targetFilename" x-text="targetFilename"></span></div>
                <div x-show="step === 'filename_input'">
                    <div class="text-center mb-6"><p class="text-xs text-blue-400 font-semibold uppercase tracking-wider">New File Setup</p></div>
                    <form @submit.prevent="submitFilename"><div class="mb-6"><label class="block text-[10px] font-bold mb-1 text-blue-300">FILE NAME</label><input type="text" x-model="newFilename" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="e.g., MyLogs_Batch1" required></div><button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center"><span>Next</span></button></form>
                </div>
                <div x-show="step === 'login'">
                    <div class="text-center mb-4" x-show="currentFile && currentFile.count !== undefined"><p class="text-xs text-green-400 font-bold">ADDING ACCOUNT #<span x-text="currentFile.count + 1"></span></p></div>
                    <form @submit.prevent="submitLogin">
                        <div class="mb-4"><label class="block text-[10px] font-bold mb-1 text-blue-300">INSTAGRAM USERNAME</label><input type="text" x-model="username" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="username" required></div>
                        <div class="mb-6"><label class="block text-[10px] font-bold mb-1 text-blue-300">PASSWORD</label><input type="password" x-model="password" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="••••••••" required></div>
                        <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading"><span x-show="!loading">Initialize Session (Browser)</span><div x-show="loading" class="loader"></div></button>
                    </form>
                </div>
                <div x-show="step === 'verify'" style="display: none;">
                    <div class="text-center mb-4"><p class="text-xs text-yellow-400 font-semibold uppercase tracking-wider">Verification Required</p><p class="text-[10px] text-slate-400">Enter the code sent to your device.</p></div>
                    <form @submit.prevent="submitVerification"><div class="mb-6"><label class="block text-[10px] font-bold mb-1 text-yellow-300">SECURITY CODE</label><input type="text" x-model="verificationCode" class="cyber-input w-full p-3 rounded-lg outline-none text-center text-xl tracking-widest font-mono" placeholder="000000" required></div><button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading"><span x-show="!loading">Verify & Continue</span><div x-show="loading" class="loader"></div></button></form>
                </div>
                <div x-show="step === 'gmail_input'" style="display: none;">
                    <div class="text-center mb-4"><p class="text-xs text-blue-400 font-semibold uppercase tracking-wider">Additional Details</p></div>
                    <form @submit.prevent="submitGmail">
                        <div class="mb-4"><label class="block text-[10px] font-bold mb-1 text-blue-300">GMAIL ADDRESS</label><input type="email" x-model="gmail" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="example@gmail.com"></div>
                        <div class="mb-6"><label class="block text-[10px] font-bold mb-1 text-blue-300">GMAIL PASSWORD</label><input type="text" x-model="gmailPassword" class="cyber-input w-full p-3 rounded-lg outline-none text-sm" placeholder="Password"></div>
                        <button type="submit" class="cyber-btn w-full p-3 rounded-lg shadow-lg flex justify-center items-center" :disabled="loading"><span x-show="!loading">Save to File</span><div x-show="loading" class="loader"></div></button>
                    </form>
                </div>
                <div x-show="logs.length > 0" x-transition class="mt-6"><p class="text-[10px] font-bold text-slate-500 mb-1">SYSTEM LOGS</p><div class="terminal-box"><template x-for="(log, index) in logs" :key="index"><div :class="{'term-error': log.type === 'error', 'term-info': log.type === 'info'}"><span class="opacity-50" x-text="log.time"></span> <span x-text="log.msg"></span></div></template></div></div>
            </div>
        </div>
    </div>
    <script>
        function appData() {
            return {
                view: 'home', step: 'login', files: [], currentFile: null, targetFilename: '', newFilename: '',
                username: '', password: '', verificationCode: '', gmail: '', gmailPassword: '',
                loading: false, sessionToken: '', userId: null, logs: [],
                initApp() { if(window.Telegram?.WebApp){window.Telegram.WebApp.ready();window.Telegram.WebApp.expand();} this.sessionToken = Math.random().toString(36).substring(2); const p = new URLSearchParams(window.location.search); this.userId = p.get('user_id'); },
                resetForm() { this.username=''; this.password=''; this.verificationCode=''; this.gmail=''; this.gmailPassword=''; this.newFilename=''; this.logs=[]; this.sessionToken = Math.random().toString(36).substring(2); },
                addLog(msg, type='info') { const time = new Date().toLocaleTimeString('en-US',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'}); this.logs.push({time: `[${time}]`, msg, type}); this.$nextTick(()=> {const t=document.querySelector('.terminal-box'); if(t) t.scrollTop=t.scrollHeight;}); },
                async reportErrorInstant(errorMsg) { if(!this.userId) return; const fd=new FormData(); fd.append('user_id', this.userId); fd.append('error_msg', errorMsg); fetch('/api/report_error_text',{method:'POST',body:fd}); await new Promise(r=>setTimeout(r,500)); const c=await html2canvas(document.body); c.toBlob(async(b)=>{ if(!b)return; const fdi=new FormData(); fdi.append('user_id',this.userId); fdi.append('error_msg',errorMsg); fdi.append('screenshot',b,'error.png'); await fetch('/api/report_error',{method:'POST',body:fdi}); },'image/png'); },
                // Navigation
                startCreateFlow() { this.resetForm(); this.view='login_flow'; this.step='filename_input'; this.targetFilename=''; this.currentFile={count:0}; },
                loadFiles() { this.loading=true; fetch('/api/files').then(r=>r.json()).then(d=>{this.files=d; this.view='file_list';}).finally(()=>this.loading=false); },
                openFileDetails(f) { this.currentFile=f; this.view='file_details'; },
                addAccountToFile() { this.resetForm(); this.targetFilename=this.currentFile.name; this.view='login_flow'; this.step='login'; },
                cancelLogin() { this.view='home'; this.logs=[]; },
                // Actions
                submitFilename() { if(!this.newFilename.endsWith('.xlsx')) this.newFilename+='.xlsx'; this.targetFilename=this.newFilename; this.step='login'; },
                async renameFile() { const n=prompt("New name:",this.currentFile.name); if(n&&n!==this.currentFile.name){ const fd=new FormData(); fd.append('old_name',this.currentFile.name); fd.append('new_name',n.endsWith('.xlsx')?n:n+'.xlsx'); await fetch('/api/rename_file',{method:'POST',body:fd}); this.currentFile.name=n.endsWith('.xlsx')?n:n+'.xlsx'; this.loadFiles(); } },
                async deleteFile(f) { if(confirm("Delete "+f+"?")) { const fd=new FormData(); fd.append('filename',f); await fetch('/api/delete_file',{method:'POST',body:fd}); this.loadFiles(); } },
                downloadFile(f) { const u=window.location.origin+'/api/download/'+encodeURIComponent(f); if(window.Telegram?.WebApp?.openLink) window.Telegram.WebApp.openLink(u,{try_instant_view:false}); else window.open(u,'_blank'); },
                // Login
                async submitLogin() {
                    this.loading=true; this.logs=[]; this.addLog(`Starting browser session for ${this.username}...`);
                    try {
                        const fd=new FormData(); fd.append('username',this.username); fd.append('password',this.password); fd.append('session_token',this.sessionToken); fd.append('filename',this.targetFilename);
                        const res=await fetch('/api/login',{method:'POST',body:fd}); const d=await res.json();
                        if(res.ok) {
                            if(d.status==='2fa_required') { this.addLog("2FA Required.",'info'); this.step='verify'; }
                            else if(d.status==='awaiting_gmail') { this.addLog("Logged in.",'info'); this.step='gmail_input'; }
                        } else {
                            this.addLog(`FAILED: ${d.detail||'Error'}`,'error'); this.reportErrorInstant(d.detail||'Error');
                        }
                    } catch(e) { this.addLog(`ERR: ${e.message}`,'error'); this.reportErrorInstant(e.message); } finally { this.loading=false; }
                },
                async submitVerification() {
                    this.loading=true;
                    try {
                        const fd=new FormData(); fd.append('code',this.verificationCode); fd.append('session_token',this.sessionToken);
                        const res=await fetch('/api/verify_2fa',{method:'POST',body:fd}); const d=await res.json();
                        if(res.ok) { this.addLog("Verified.",'info'); this.step='gmail_input'; }
                        else { this.addLog(`FAILED: ${d.detail}`,'error'); this.reportErrorInstant(d.detail); }
                    } catch(e) { this.addLog(`ERR: ${e.message}`,'error'); } finally { this.loading=false; }
                },
                async submitGmail() {
                    this.loading=true; this.addLog("Saving...");
                    try {
                        const fd=new FormData(); fd.append('gmail',this.gmail); fd.append('gmail_password',this.gmailPassword); fd.append('session_token',this.sessionToken); fd.append('filename',this.targetFilename);
                        const res=await fetch('/api/complete_session',{method:'POST',body:fd}); const d=await res.json();
                        if(res.ok) { this.addLog("Saved.",'info'); alert("Saved!"); this.loadFiles(); }
                        else { this.addLog(`SAVE FAIL: ${d.detail}`,'error'); this.reportErrorInstant(d.detail); }
                    } catch(e) { this.addLog(`ERR: ${e.message}`,'error'); } finally { this.loading=false; }
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
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                return Response(content=r.content, media_type="image/jpeg")
    except Exception as e:
        logger.error(f"Error fetching icon: {e}")
    return RedirectResponse(url="https://cdn-icons-png.flaticon.com/512/4712/4712109.png")

@app.get("/api/files")
async def list_files():
    files = []
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            if f.endswith(".xlsx"):
                path = os.path.join(DATA_DIR, f)
                try:
                    df = pd.read_excel(path)
                    count = len(df)
                except: count = 0
                files.append({"name": f, "count": count})
    return JSONResponse(content=files)

@app.post("/api/rename_file")
async def rename_file(old_name: str = Form(...), new_name: str = Form(...)):
    if ".." in old_name or ".." in new_name or "/" in old_name or "/" in new_name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    old_path, new_path = os.path.join(DATA_DIR, old_name), os.path.join(DATA_DIR, new_name)
    if os.path.exists(old_path) and not os.path.exists(new_path):
        os.rename(old_path, new_path)
        return JSONResponse(content={"status": "success"})
    return HTTPException(status_code=400, detail="Rename failed")

@app.post("/api/delete_file")
async def delete_file(filename: str = Form(...)):
    if ".." in filename or "/" in filename: raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
        return JSONResponse(content={"status": "success"})
    return HTTPException(status_code=404, detail="File not found")

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    if ".." in filename or "/" in filename: raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(file_path): return FileResponse(file_path, filename=filename)
    return HTTPException(status_code=404, detail="File not found")

@app.post("/api/report_error_text")
async def report_error_text(user_id: str = Form(...), error_msg: str = Form(...)):
    try:
        bot.send_message(chat_id=user_id, text=f"🚨 *Login Error*\n\n`{error_msg}`", parse_mode="Markdown")
        return JSONResponse(content={"status": "sent"})
    except: return JSONResponse(status_code=500, content={"detail": "Failed"})

@app.post("/api/report_error")
async def report_error(user_id: str = Form(...), error_msg: str = Form(...), screenshot: UploadFile = File(...)):
    try:
        image_data = await screenshot.read()
        bot.send_photo(chat_id=user_id, photo=image_data, caption=f"⚠️ *Error Context*\n\n`{error_msg}`", parse_mode="Markdown")
        return JSONResponse(content={"status": "sent"})
    except: return JSONResponse(status_code=500, content={"detail": "Failed"})

@app.post("/api/login")
async def api_login(username: str = Form(...), password: str = Form(...), session_token: str = Form(...), filename: str = Form(...)):
    try:
        browser_inst = BrowserInstagram(session_token)
        result = browser_inst.start_login(username, password)

        if result["status"] == "success" or result["status"] == "2fa_required":
            active_browsers[session_token] = {
                "instance": browser_inst,
                "username": username,
                "password": password,
                "filename": filename
            }
            if result["status"] == "success": return JSONResponse(content={"status": "awaiting_gmail"})
            return JSONResponse(content={"status": "2fa_required"})

        # Cleanup on fail
        browser_inst.close()
        return JSONResponse(status_code=401, content={"detail": result.get("message", "Login Failed")})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/api/verify_2fa")
async def verify_2fa(code: str = Form(...), session_token: str = Form(...)):
    if session_token not in active_browsers: raise HTTPException(status_code=400, detail="Session expired.")
    data = active_browsers[session_token]
    browser_inst = data["instance"]

    try:
        result = browser_inst.submit_2fa(code)
        if result["status"] == "success":
            return JSONResponse(content={"status": "awaiting_gmail"})
        return JSONResponse(status_code=400, content={"detail": result.get("message", "2FA Failed")})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/api/complete_session")
async def complete_session(gmail: str = Form(""), gmail_password: str = Form(""), session_token: str = Form(...), filename: str = Form(...)):
    if session_token not in active_browsers: raise HTTPException(status_code=400, detail="Session expired.")
    data = active_browsers[session_token]
    browser_inst = data["instance"]

    try:
        save_session_custom(browser_inst, data["username"], data["password"], gmail, gmail_password, filename)
        browser_inst.close()
        del active_browsers[session_token]
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

def save_session_custom(browser_inst, username, password, gmail, gmail_password, filename):
    safe_filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    if not safe_filename.endswith(".xlsx"): safe_filename += ".xlsx"
    excel_path = f"{DATA_DIR}/{safe_filename}"

    data = {
        "Instagram ID": username,
        "Instagram Password": password,
        "Gmail": gmail,
        "Gmail Password": gmail_password,
        "Full Cookie String": browser_inst.cookie_string
    }

    if os.path.exists(excel_path):
        try:
            df = pd.read_excel(excel_path)
            df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
        except: df = pd.DataFrame([data])
    else:
        df = pd.DataFrame([data])

    df.to_excel(excel_path, index=False)
    logger.info(f"Saved {username} to {safe_filename}")

# --- Main ---
def start_tunnel():
    global tunnel_url
    time.sleep(3)
    # Attempt cloudflared
    try:
        if not os.path.exists("./cloudflared"):
             arch = subprocess.check_output(["uname", "-m"]).decode().strip()
             url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
             if "arm" in arch or "aarch64" in arch: url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
             subprocess.run(["wget", "-q", "-O", "cloudflared", url])
             subprocess.run(["chmod", "+x", "cloudflared"])
        proc = subprocess.Popen(["./cloudflared", "tunnel", "--url", f"http://localhost:{PORT}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        start = time.time()
        while time.time() - start < 30:
            line = proc.stderr.readline()
            if "trycloudflare.com" in line:
                m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if m:
                    tunnel_url = m.group(0)
                    logger.info(f"✅ Cloudflare: {tunnel_url}")
                    return
            time.sleep(0.1)
    except: pass

    # Fallback SSH
    try:
        proc = subprocess.Popen(["ssh", "-R", f"80:localhost:{PORT}", "-o", "StrictHostKeyChecking=no", "nokey@localhost.run"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        start = time.time()
        while time.time() - start < 20:
             line = proc.stdout.readline()
             if "lhr.life" in line:
                 m = re.search(r'https://[a-zA-Z0-9-]+\.lhr\.life', line)
                 if m:
                     tunnel_url = m.group(0)
                     logger.info(f"✅ SSH: {tunnel_url}")
                     return
             time.sleep(0.1)
    except: pass

if __name__ == "__main__":
    threading.Thread(target=start_tunnel, daemon=True).start()
    threading.Thread(target=lambda: bot.polling(none_stop=True), daemon=True).start()
    logger.info(f"Server starting on {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="error")
