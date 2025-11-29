import os
import shutil
import json
import logging
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import instaloader
import pandas as pd
from datetime import datetime

# --- Configuration ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
FRONTEND_DIST_DIR = os.path.join("frontend", "dist")

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- State ---
login_sessions = {}

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

def get_session_file_path(username: str) -> str:
    return os.path.join(DATA_DIR, f"{username}.xlsx")

def clean_duplicates(target_user_id: int, exclude_filename: str = None):
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

# --- API Endpoints ---

@app.post("/api/login")
def login(request: LoginRequest):
    username = request.username
    password = request.password

    L = instaloader.Instaloader(
        user_agent="Instagram 269.0.0.18.75 Android (31/12; 320dpi; 720x1280; Xiaomi; Redmi Note 4; mido; qcom; en_US; 314077874)"
    )

    try:
        L.login(username, password)
        login_sessions[username] = {'loader': L, 'password': password}
        return {"status": "success", "message": "Login successful", "requires_2fa": False}

    except instaloader.TwoFactorAuthRequiredException:
        login_sessions[username] = {'loader': L, 'password': password}
        return {"status": "pending", "message": "2FA Required", "requires_2fa": True}

    except instaloader.BadCredentialsException:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    except instaloader.ConnectionException as e:
         raise HTTPException(status_code=503, detail=f"Connection error: {str(e)}")

    except Exception as e:
        logger.exception(f"Login error for {username}")
        # Improve error message for known issues
        if "challenge_required" in str(e):
             raise HTTPException(status_code=403, detail="Instagram requires verification (Challenge). Please try logging in on the app first.")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/2fa")
def two_factor(request: TwoFactorRequest):
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
def save_data(request: SaveDataRequest):
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
def list_files():
    files = []
    for f in os.listdir(DATA_DIR):
        if f.endswith(".xlsx"):
            path = os.path.join(DATA_DIR, f)
            try:
                stat = os.stat(path)
                files.append({
                    "filename": f,
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat()
                })
            except Exception:
                pass
    return files

@app.get("/api/download/{filename}")
def download_file(filename: str):
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        return FileResponse(filepath, filename=filename)
    raise HTTPException(status_code=404, detail="File not found")

@app.delete("/api/delete/{filename}")
def delete_file(filename: str):
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/api/rename")
def rename_file(request: RenameRequest):
    old_path = os.path.join(DATA_DIR, request.old_filename)
    new_path = os.path.join(DATA_DIR, request.new_filename)

    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail="File not found")
    if os.path.exists(new_path):
        raise HTTPException(status_code=400, detail="Filename already exists")

    os.rename(old_path, new_path)
    return {"status": "success"}

@app.post("/api/edit")
def edit_file(request: EditDataRequest):
    filepath = os.path.join(DATA_DIR, request.filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        df = pd.read_excel(filepath)

        # Update columns
        if "Gmail" in df.columns:
            df["Gmail"] = request.gmail
        if "Gmail Password" in df.columns:
            df["Gmail Password"] = request.gmail_password

        df.to_excel(filepath, index=False)
        return {"status": "success", "message": "File updated"}
    except Exception as e:
        logger.error(f"Error editing file: {e}")
        raise HTTPException(status_code=500, detail="Failed to update file")

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files allowed")

    content = await file.read()
    temp_path = os.path.join(DATA_DIR, file.filename)

    with open(temp_path, "wb") as f:
        f.write(content)

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
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=400, detail=f"Invalid file: {str(e)}")

# --- Serve Frontend ---
# Mount static files. Ensure this is last so API routes take precedence.
if os.path.exists(FRONTEND_DIST_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="static")
else:
    logger.warning("Frontend build not found. Run 'npm run build' in frontend directory.")
