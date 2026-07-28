import os
import base64
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import jwt

# --- SQLAlchemy Imports ---
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, func
from sqlalchemy.orm import sessionmaker, declarative_base

app = FastAPI(title="Checkpoint PWA System")

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SECRET_KEY = "SUPER_SECRET_CHECKPOINT_KEY_CHANGE_ME"
ALGORITHM = "HS256"

# --- Supabase PostgreSQL Connection ---
# ดึงค่าจาก Environment Variable บน Render (หากมี) หรือ fallback ใช้ Connection String โดยตรง
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.wcngqpcicnxvfakinkku:tRPeILhiSbFWmIff@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
)

# สร้าง SQLAlchemy Engine และ Session
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Database Models (PostgreSQL Table Models) ---
class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True, index=True)
    password = Column(String, nullable=False)
    name = Column(String, nullable=False)

class Equipment(Base):
    __tablename__ = "equipments"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    image = Column(Text, nullable=True, default="")

class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String)
    eq_id = Column(String)
    action = Column(String)
    details = Column(Text)
    username = Column(String)

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)

# สร้างตารางบน Supabase อัตโนมัติ (หากยังไม่มี) และลงข้อมูลเริ่มต้น
def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Check and insert default settings
        if not db.query(Setting).filter(Setting.key == "admin_pin").first():
            db.add(Setting(key="admin_pin", value="9999"))
        
        # Check and insert default users
        if not db.query(User).filter(User.username == "admin").first():
            db.add(User(username="admin", password="1234", name="Admin User"))
            
        # Check and insert default equipments
        if not db.query(Equipment).filter(Equipment.id == "EQ-101").first():
            db.add(Equipment(id="EQ-101", name="ตู้เชื่อม Portable", status="AVAILABLE", image=""))
        if not db.query(Equipment).filter(Equipment.id == "EQ-102").first():
            db.add(Equipment(id="EQ-102", name="สว่านไร้สาย", status="AVAILABLE", image=""))
            
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error initializing DB: {e}")
    finally:
        db.close()

# เรียกใช้งาน init_db() ตอนเริ่มระบบ
init_db()

# --- Helper Functions ---
def generate_qrcode_svg(text: str) -> str:
    """สร้าง QR Code URL สำหรับแสดงผล"""
    return f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={text}"

def get_admin_pin():
    db = SessionLocal()
    try:
        setting = db.query(Setting).filter(Setting.key == "admin_pin").first()
        return setting.value if setting else "9999"
    finally:
        db.close()

def add_db_log(eq_id: str, action: str, details: str, username: str = "system"):
    db = SessionLocal()
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = Log(
            timestamp=now_str,
            eq_id=eq_id,
            action=action,
            details=details,
            username=username
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error adding log: {e}")
    finally:
        db.close()

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
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == data.username, User.password == data.password).first()
        if not user:
            return {"success": False, "message": "Username หรือ Password ไม่ถูกต้อง"}

        token = create_access_token({"sub": user.username, "name": user.name})
        return {"success": True, "token": token, "username": user.username, "name": user.name}
    finally:
        db.close()

class RegisterModel(BaseModel):
    username: str
    password: str
    name: str

@app.post("/api/register")
async def register_user(data: RegisterModel):
    db = SessionLocal()
    try:
        existing_user = db.query(User).filter(User.username == data.username).first()
        if existing_user:
            return {"success": False, "message": "Username นี้มีในระบบอยู่แล้ว"}

        new_user = User(username=data.username, password=data.password, name=data.name)
        db.add(new_user)
        db.commit()
        
        add_db_log("USER", "REGISTER", f"ลงทะเบียนผู้ใช้งานใหม่: {data.name}", data.username)
        return {"success": True, "message": "สมัครสมาชิกสำเร็จ!"}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": "เกิดข้อผิดพลาดในการลงทะเบียน"}
    finally:
        db.close()

class ChangeUsernameModel(BaseModel):
    token: str
    new_username: str
    password_confirm: str

@app.post("/api/change_username")
async def change_username(data: ChangeUsernameModel):
    current_user = verify_token(data.token)
    if not current_user:
        return {"success": False, "message": "Session หมดอายุ กรุณาล็อกอินใหม่"}

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == current_user).first()
        if not user or user.password != data.password_confirm:
            return {"success": False, "message": "รหัสผ่านยืนยันไม่ถูกต้อง!"}

        check_dup = db.query(User).filter(User.username == data.new_username).first()
        if check_dup:
            return {"success": False, "message": "Username ใหม่นี้ซ้ำกับในระบบ"}

        user.username = data.new_username
        db.commit()

        add_db_log("USER", "CHANGE_USERNAME", f"เปลี่ยนชื่อผู้ใช้จาก '{current_user}' เป็น '{data.new_username}'", data.new_username)
        new_token = create_access_token({"sub": data.new_username, "name": user.name})
        return {"success": True, "message": "เปลี่ยน Username สำเร็จ!", "new_token": new_token, "new_username": data.new_username}
    except Exception:
        db.rollback()
        return {"success": False, "message": "ไม่สามารถเปลี่ยน Username ได้"}
    finally:
        db.close()

class ChangePasswordModel(BaseModel):
    token: str
    old_password: str
    new_password: str

@app.post("/api/change_password")
async def change_password(data: ChangePasswordModel):
    current_user = verify_token(data.token)
    if not current_user:
        return {"success": False, "message": "Session หมดอายุ กรุณาล็อกอินใหม่"}

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == current_user).first()
        if not user or user.password != data.old_password:
            return {"success": False, "message": "รหัสผ่านเดิมไม่ถูกต้อง!"}

        user.password = data.new_password
        db.commit()

        add_db_log("USER", "CHANGE_PASSWORD", "เปลี่ยนรหัสผ่านเข้าใช้งานสำเร็จ", current_user)
        return {"success": True, "message": "เปลี่ยนรหัสผ่านสำเร็จ!"}
    except Exception:
        db.rollback()
        return {"success": False, "message": "ไม่สามารถเปลี่ยนรหัสผ่านได้"}
    finally:
        db.close()

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

    db = SessionLocal()
    try:
        eq = db.query(Equipment).filter(Equipment.id == req.eq_id).first()
        if not eq:
            return {"success": False, "message": "ไม่พบอุปกรณ์นี้"}
        if eq.status == "BORROWED":
            return {"success": False, "message": "อุปกรณ์นี้ถูกยืมไปแล้ว"}

        eq.status = "BORROWED"
        db.commit()

        add_db_log(req.eq_id, "CHECKOUT", f"ยืมใส่รถทะเบียน: {req.plate_number} (คนขับ: {req.driver_name or 'ไม่ระบุ'})", username)
        return {"success": True, "message": f"ยืมอุปกรณ์ {req.eq_id} สำเร็จ"}
    except Exception:
        db.rollback()
        return {"success": False, "message": "เกิดข้อผิดพลาดในการยืมอุปกรณ์"}
    finally:
        db.close()

class CheckinModel(BaseModel):
    token: str
    eq_id: str

@app.post("/api/checkin")
async def checkin(req: CheckinModel):
    username = verify_token(req.token)
    if not username: return {"success": False, "message": "Session หมดอายุ"}

    db = SessionLocal()
    try:
        eq = db.query(Equipment).filter(Equipment.id == req.eq_id).first()
        if eq:
            eq.status = "AVAILABLE"
            db.commit()

        add_db_log(req.eq_id, "CHECKIN", "คืนอุปกรณ์เรียบร้อย", username)
        return {"success": True, "message": f"คืนอุปกรณ์ {req.eq_id} เรียบร้อย"}
    except Exception:
        db.rollback()
        return {"success": False, "message": "เกิดข้อผิดพลาดในการคืนอุปกรณ์"}
    finally:
        db.close()

# API ดึง Dashboard + เจน QR Code
@app.get("/api/dashboard_data")
async def get_dashboard_data(year: Optional[str] = None, month: Optional[str] = None, day: Optional[str] = None):
    db = SessionLocal()
    try:
        eqs = db.query(Equipment).all()
        query = db.query(Log)

        # กรองข้อมูล Log ตาม ปี/เดือน/วัน (รองรับรูปแบบ String "YYYY-MM-DD HH:MM:SS")
        if year and year != "ALL":
            query = query.filter(Log.timestamp.like(f"{year}-%"))
        if month and month != "ALL":
            month_str = f"{int(month):02d}"
            query = query.filter(Log.timestamp.like(f"%-{month_str}-%"))
        if day and day != "ALL":
            day_str = f"{int(day):02d}"
            query = query.filter(Log.timestamp.like(f"%-{day_str} %"))

        logs = query.order_by(Log.id.desc()).limit(200).all()

        equipments_data = []
        for e in eqs:
            qr_src = generate_qrcode_svg(e.id)
            equipments_data.append({
                "id": e.id,
                "name": e.name,
                "status": e.status,
                "image": e.image or "",
                "qrcode": qr_src
            })

        return {
            "equipments": equipments_data,
            "logs": [{"timestamp": l.timestamp, "eq_id": l.eq_id, "action": l.action, "details": l.details, "username": l.username} for l in logs]
        }
    finally:
        db.close()

@app.post("/api/equipment/delete")
async def delete_equipment(eq_id: str = Form(...), pin: str = Form(...), token: str = Form(...)):
    username = verify_token(token)
    if not username: return {"success": False, "message": "Session หมดอายุ"}
    if pin != get_admin_pin():
        return {"success": False, "message": "รหัสผ่าน Admin PIN ไม่ถูกต้อง!"}

    db = SessionLocal()
    try:
        eq = db.query(Equipment).filter(Equipment.id == eq_id).first()
        if eq:
            db.delete(eq)
            db.commit()

        add_db_log(eq_id, "DELETE", "ลบรายการอุปกรณ์ออกจากระบบ", username)
        return {"success": True, "message": f"ลบอุปกรณ์ {eq_id} เรียบร้อยแล้ว"}
    except Exception:
        db.rollback()
        return {"success": False, "message": "เกิดข้อผิดพลาดในการลบอุปกรณ์"}
    finally:
        db.close()

@app.post("/api/equipment/edit")
async def edit_equipment(eq_id: str = Form(...), name: str = Form(...), pin: str = Form(...), token: str = Form(...)):
    username = verify_token(token)
    if not username: return {"success": False, "message": "Session หมดอายุ"}
    if pin != get_admin_pin():
        return {"success": False, "message": "รหัสผ่าน Admin PIN ไม่ถูกต้อง!"}

    db = SessionLocal()
    try:
        eq = db.query(Equipment).filter(Equipment.id == eq_id).first()
        if eq:
            eq.name = name
            db.commit()

        add_db_log(eq_id, "EDIT", f"แก้ไขชื่ออุปกรณ์เป็น: {name}", username)
        return {"success": True, "message": f"แก้ไขข้อมูล {eq_id} เรียบร้อยแล้ว"}
    except Exception:
        db.rollback()
        return {"success": False, "message": "เกิดข้อผิดพลาดในการแก้ไขข้อมูล"}
    finally:
        db.close()

@app.post("/api/register_equipment")
async def register_equipment(eq_id: str = Form(...), name: str = Form(...), admin_pin: str = Form(...)):
    if admin_pin != get_admin_pin():
        return JSONResponse(status_code=403, content={"success": False, "message": "PIN Admin ไม่ถูกต้อง"})

    db = SessionLocal()
    try:
        eq = db.query(Equipment).filter(Equipment.id == eq_id).first()
        if eq:
            eq.name = name
            eq.status = "AVAILABLE"
        else:
            eq = Equipment(id=eq_id, name=name, status="AVAILABLE", image="")
            db.add(eq)
        
        db.commit()

        add_db_log(eq_id, "REGISTER", f"เพิ่มอุปกรณ์ใหม่: {name}", "admin")
        return {"success": True, "message": f"ลงทะเบียน {eq_id} สำเร็จ"}
    except Exception:
        db.rollback()
        return {"success": False, "message": "เกิดข้อผิดพลาดในการลงทะเบียนอุปกรณ์"}
    finally:
        db.close()

@app.post("/api/change_admin_pin")
async def change_admin_pin(old_pin: str = Form(...), new_pin: str = Form(...)):
    if old_pin != get_admin_pin():
        return {"success": False, "message": "รหัส PIN เดิมไม่ถูกต้อง"}

    db = SessionLocal()
    try:
        setting = db.query(Setting).filter(Setting.key == "admin_pin").first()
        if setting:
            setting.value = new_pin
        else:
            setting = Setting(key="admin_pin", value=new_pin)
            db.add(setting)
        
        db.commit()

        add_db_log("SYSTEM", "CHANGE_ADMIN_PIN", "เปลี่ยนรหัสผ่าน Admin Action PIN สำเร็จ", "admin")
        return {"success": True, "message": "เปลี่ยน Admin PIN สำเร็จ!"}
    except Exception:
        db.rollback()
        return {"success": False, "message": "ไม่สามารถเปลี่ยน Admin PIN ได้"}
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
