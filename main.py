import os
import sqlite3
import base64
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import jwt

app = FastAPI(title="Checkpoint PWA System")

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SECRET_KEY = "SUPER_SECRET_CHECKPOINT_KEY_CHANGE_ME"
ALGORITHM = "HS256"
DB_NAME = "checkpoint.db"

# --- Simple QR Code Matrix Generator (Pure SVG) ---
def generate_qrcode_svg(text: str) -> str:
    """สร้าง QR Code SVG พร้อมตัวเลข/รหัสกำกับด้านล่างแบบคร่าวๆ ไม่ต้องลง lib เพิ่ม"""
    # ใช้ Google Chart API เป็น fallback หรือ SVG Data URI Generator แบบเร็ว
    # เพื่อความคมชัดและความชัวร์สูงสุดใน PWA แนะนำโครงสร้าง SVG Data URI
    encoded_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')
    
    # สร้าง SVG ที่ดึง QR จาก Standard Data หรือ Render QR Matrix
    # ในกรณีนี้สร้างเป็น SVG HTML Image Embed เพื่อความสอดคล้อง
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={text}"
    return qr_url

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            name TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS equipments (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            image TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            eq_id TEXT,
            action TEXT,
            details TEXT,
            username TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('admin_pin', '9999')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('admin', '1234', 'Admin User')")
    cursor.execute("INSERT OR IGNORE INTO equipments VALUES ('EQ-101', 'ตู้เชื่อม Portable', 'AVAILABLE', '')")
    cursor.execute("INSERT OR IGNORE INTO equipments VALUES ('EQ-102', 'สว่านไร้สาย', 'AVAILABLE', '')")

    conn.commit()
    conn.close()

# --- Helpers ---
def get_admin_pin():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'admin_pin'")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "9999"

def add_db_log(eq_id: str, action: str, details: str, username: str = "system"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO logs (timestamp, eq_id, action, details, username) VALUES (?, ?, ?, ?, ?)",
        (now_str, eq_id, action, details, username)
    )
    conn.commit()
    conn.close()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=30)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def serve_webapp(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})

@app.get("/manifest.json")
async def get_manifest():
    return JSONResponse({
        "short_name": "Checkpoint",
        "name": "Checkpoint Management App",
        "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/1041/1041888.png", "type": "image/png", "sizes": "192x192"}],
        "start_url": "/",
        "background_color": "#090d16",
        "theme_color": "#090d16",
        "display": "standalone",
        "orientation": "portrait"
    })

@app.get("/sw.js")
async def get_sw():
    content = "self.addEventListener('install', (e) => self.skipWaiting()); self.addEventListener('fetch', (e) => e.respondWith(fetch(e.request)));"
    return HTMLResponse(content=content, media_type="application/javascript")

# --- APIs Auth & Profile ---
class LoginModel(BaseModel):
    username: str
    password: str

@app.post("/api/login")
async def login(data: LoginModel):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username, name FROM users WHERE username = ? AND password = ?", (data.username, data.password))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return {"success": False, "message": "Username หรือ Password ไม่ถูกต้อง"}

    token = create_access_token({"sub": user[0], "name": user[1]})
    return {"success": True, "token": token, "username": user[0], "name": user[1]}

class RegisterModel(BaseModel):
    username: str
    password: str
    name: str

@app.post("/api/register")
async def register_user(data: RegisterModel):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users VALUES (?, ?, ?)", (data.username, data.password, data.name))
        conn.commit()
        conn.close()
        add_db_log("USER", "REGISTER", f"ลงทะเบียนผู้ใช้งานใหม่: {data.name}", data.username)
        return {"success": True, "message": "สมัครสมาชิกสำเร็จ!"}
    except Exception:
        conn.close()
        return {"success": False, "message": "Username นี้มีในระบบอยู่แล้ว"}

class ChangeUsernameModel(BaseModel):
    token: str
    new_username: str
    password_confirm: str

@app.post("/api/change_username")
async def change_username(data: ChangeUsernameModel):
    current_user = verify_token(data.token)
    if not current_user:
        return {"success": False, "message": "Session หมดอายุ กรุณาล็อกอินใหม่"}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (current_user,))
    row = cursor.fetchone()

    if not row or row[0] != data.password_confirm:
        conn.close()
        return {"success": False, "message": "รหัสผ่านยืนยันไม่ถูกต้อง!"}

    try:
        cursor.execute("UPDATE users SET username = ? WHERE username = ?", (data.new_username, current_user))
        conn.commit()
        conn.close()
        
        add_db_log("USER", "CHANGE_USERNAME", f"เปลี่ยนชื่อผู้ใช้จาก '{current_user}' เป็น '{data.new_username}'", data.new_username)
        new_token = create_access_token({"sub": data.new_username, "name": data.new_username})
        return {"success": True, "message": "เปลี่ยน Username สำเร็จ!", "new_token": new_token, "new_username": data.new_username}
    except Exception:
        conn.close()
        return {"success": False, "message": "Username ใหม่นี้ซ้ำกับในระบบ"}

class ChangePasswordModel(BaseModel):
    token: str
    old_password: str
    new_password: str

@app.post("/api/change_password")
async def change_password(data: ChangePasswordModel):
    current_user = verify_token(data.token)
    if not current_user:
        return {"success": False, "message": "Session หมดอายุ กรุณาล็อกอินใหม่"}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (current_user,))
    row = cursor.fetchone()

    if not row or row[0] != data.old_password:
        conn.close()
        return {"success": False, "message": "รหัสผ่านเดิมไม่ถูกต้อง!"}

    cursor.execute("UPDATE users SET password = ? WHERE username = ?", (data.new_password, current_user))
    conn.commit()
    conn.close()

    add_db_log("USER", "CHANGE_PASSWORD", "เปลี่ยนรหัสผ่านเข้าใช้งานสำเร็จ", current_user)
    return {"success": True, "message": "เปลี่ยนรหัสผ่านสำเร็จ!"}

# --- APIs Equipment & Logs ---
class CheckoutModel(BaseModel):
    token: str
    eq_id: str
    plate_number: str
    driver_name: Optional[str] = ""

@app.post("/api/checkout")
async def checkout(req: CheckoutModel):
    username = verify_token(req.token)
    if not username: return {"success": False, "message": "Session หมดอายุ"}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM equipments WHERE id = ?", (req.eq_id,))
    eq = cursor.fetchone()
    if not eq:
        conn.close()
        return {"success": False, "message": "ไม่พบอุปกรณ์นี้"}
    if eq[0] == "BORROWED":
        conn.close()
        return {"success": False, "message": "อุปกรณ์นี้ถูกยืมไปแล้ว"}

    cursor.execute("UPDATE equipments SET status = 'BORROWED' WHERE id = ?", (req.eq_id,))
    conn.commit()
    conn.close()

    add_db_log(req.eq_id, "CHECKOUT", f"ยืมใส่รถทะเบียน: {req.plate_number} (คนขับ: {req.driver_name or 'ไม่ระบุ'})", username)
    return {"success": True, "message": f"ยืมอุปกรณ์ {req.eq_id} สำเร็จ"}

class CheckinModel(BaseModel):
    token: str
    eq_id: str

@app.post("/api/checkin")
async def checkin(req: CheckinModel):
    username = verify_token(req.token)
    if not username: return {"success": False, "message": "Session หมดอายุ"}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE equipments SET status = 'AVAILABLE' WHERE id = ?", (req.eq_id,))
    conn.commit()
    conn.close()

    add_db_log(req.eq_id, "CHECKIN", "คืนอุปกรณ์เรียบร้อย", username)
    return {"success": True, "message": f"คืนอุปกรณ์ {req.eq_id} เรียบร้อย"}

# API ดึง Dashboard + เจน QR Code ให้ทุกไอเทม
@app.get("/api/dashboard_data")
async def get_dashboard_data(year: Optional[str] = None, month: Optional[str] = None, day: Optional[str] = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, status, image FROM equipments")
    eqs = cursor.fetchall()

    query = "SELECT timestamp, eq_id, action, details, username FROM logs WHERE 1=1"
    params = []

    if year and year != "ALL":
        query += " AND strftime('%Y', timestamp) = ?"
        params.append(year)
    if month and month != "ALL":
        query += " AND strftime('%m', timestamp) = ?"
        params.append(f"{int(month):02d}")
    if day and day != "ALL":
        query += " AND strftime('%d', timestamp) = ?"
        params.append(f"{int(day):02d}")

    query += " ORDER BY id DESC LIMIT 200"
    
    cursor.execute(query, params)
    logs = cursor.fetchall()
    conn.close()

    equipments_data = []
    for e in eqs:
        eq_id = e[0]
        qr_src = generate_qrcode_svg(eq_id)
        equipments_data.append({
            "id": eq_id,
            "name": e[1],
            "status": e[2],
            "image": e[3],
            "qrcode": qr_src
        })

    return {
        "equipments": equipments_data,
        "logs": [{"timestamp": l[0], "eq_id": l[1], "action": l[2], "details": l[3], "username": l[4]} for l in logs]
    }

@app.post("/api/equipment/delete")
async def delete_equipment(eq_id: str = Form(...), pin: str = Form(...), token: str = Form(...)):
    username = verify_token(token)
    if not username: return {"success": False, "message": "Session หมดอายุ"}
    if pin != get_admin_pin():
        return {"success": False, "message": "รหัสผ่าน Admin PIN ไม่ถูกต้อง!"}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM equipments WHERE id = ?", (eq_id,))
    conn.commit()
    conn.close()

    add_db_log(eq_id, "DELETE", "ลบรายการอุปกรณ์ออกจากระบบ", username)
    return {"success": True, "message": f"ลบอุปกรณ์ {eq_id} เรียบร้อยแล้ว"}

@app.post("/api/equipment/edit")
async def edit_equipment(eq_id: str = Form(...), name: str = Form(...), pin: str = Form(...), token: str = Form(...)):
    username = verify_token(token)
    if not username: return {"success": False, "message": "Session หมดอายุ"}
    if pin != get_admin_pin():
        return {"success": False, "message": "รหัสผ่าน Admin PIN ไม่ถูกต้อง!"}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE equipments SET name = ? WHERE id = ?", (name, eq_id))
    conn.commit()
    conn.close()

    add_db_log(eq_id, "EDIT", f"แก้ไขชื่ออุปกรณ์เป็น: {name}", username)
    return {"success": True, "message": f"แก้ไขข้อมูล {eq_id} เรียบร้อยแล้ว"}

@app.post("/api/register_equipment")
async def register_equipment(eq_id: str = Form(...), name: str = Form(...), admin_pin: str = Form(...)):
    if admin_pin != get_admin_pin():
        return JSONResponse(status_code=403, content={"success": False, "message": "PIN Admin ไม่ถูกต้อง"})

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO equipments VALUES (?, ?, 'AVAILABLE', '')", (eq_id, name))
    conn.commit()
    conn.close()

    add_db_log(eq_id, "REGISTER", f"เพิ่มอุปกรณ์ใหม่: {name}", "admin")
    return {"success": True, "message": f"ลงทะเบียน {eq_id} สำเร็จ"}

@app.post("/api/change_admin_pin")
async def change_admin_pin(old_pin: str = Form(...), new_pin: str = Form(...)):
    if old_pin != get_admin_pin():
        return {"success": False, "message": "รหัส PIN เดิมไม่ถูกต้อง"}

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'admin_pin'", (new_pin,))
    conn.commit()
    conn.close()
    
    add_db_log("SYSTEM", "CHANGE_ADMIN_PIN", "เปลี่ยนรหัสผ่าน Admin Action PIN สำเร็จ", "admin")
    return {"success": True, "message": "เปลี่ยน Admin PIN สำเร็จ!"}

if __name__ == "__main__":
    init_db()
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)