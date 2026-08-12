import os
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

USERS_FILE = 'data/users.json'
EQUIPMENT_FILE = 'data/equipment.json'
CONFIG_FILE = 'data/config.json'
LOGS_FILE = 'data/logs.json'
VEHICLES_FILE = 'data/vehicles.json'

os.makedirs('data', exist_ok=True)

def load_json(filepath, default):
    if not os.path.exists(filepath):
        save_json(filepath, default)
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_current_user(token):
    users = load_json(USERS_FILE, {})
    for u, data in users.items():
        if data.get('token') == token:
            return u
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    
    users = load_json(USERS_FILE, {})
    if username in users and check_password_hash(users[username]['password_hash'], password):
        token = str(uuid.uuid4())
        users[username]['token'] = token
        save_json(USERS_FILE, users)
        return jsonify({"success": True, "token": token, "username": username})
    
    return jsonify({"success": False, "message": "Username หรือ Password ไม่ถูกต้อง"}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"success": False, "message": "กรุณากรอกข้อมูลให้ครบถ้วน"}), 400
        
    users = load_json(USERS_FILE, {})
    if username in users:
        return jsonify({"success": False, "message": "Username นี้มีผู้ใช้งานแล้ว"}), 400
        
    users[username] = {
        "password_hash": generate_password_hash(password),
        "token": ""
    }
    save_json(USERS_FILE, users)
    return jsonify({"success": True, "message": "สมัครสมาชิกเรียบร้อยแล้ว"})

# --- ขนส่ง ---
@app.route('/api/register_vehicle', methods=['POST'])
def register_vehicle():
    data = request.json or {}
    plate = (data.get('plate_number') or '').strip()
    driver = (data.get('driver_name') or '').strip()
    
    if not plate or not driver:
        return jsonify({"success": False, "message": "กรุณากรอกทะเบียนรถและชื่อคนขับ"}), 400
        
    vehicles = load_json(VEHICLES_FILE, [])
    for v in vehicles:
        if v['plate_number'] == plate:
            return jsonify({"success": False, "message": "ทะเบียนรถนี้ลงทะเบียนไว้แล้ว"}), 400
            
    vehicles.append({
        "id": str(uuid.uuid4()),
        "plate_number": plate,
        "driver_name": driver,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    save_json(VEHICLES_FILE, vehicles)
    return jsonify({"success": True, "message": "ลงทะเบียนรถเรียบร้อยแล้ว"})

@app.route('/api/delete_vehicle', methods=['POST'])
def delete_vehicle():
    data = request.json or {}
    v_id = data.get('vehicle_id')
    vehicles = load_json(VEHICLES_FILE, [])
    vehicles = [v for v in vehicles if v['id'] != v_id]
    save_json(VEHICLES_FILE, vehicles)
    return jsonify({"success": True, "message": "ลบข้อมูลขนส่งเรียบร้อยแล้ว"})

# --- สินค้าและการยืม/คืน ---
@app.route('/api/register_equipment', methods=['POST'])
def register_equipment():
    admin_pin = request.form.get('admin_pin')
    eq_id = request.form.get('eq_id')
    name = request.form.get('name')
    
    config = load_json(CONFIG_FILE, {"admin_pin": "1234"})
    if admin_pin != config.get('admin_pin'):
        return jsonify({"success": False, "message": "Admin PIN ไม่ถูกต้อง"}), 403
        
    equipments = load_json(EQUIPMENT_FILE, {})
    if eq_id in equipments:
        return jsonify({"success": False, "message": "รหัสสินค้านี้มีในระบบแล้ว"}), 400
        
    equipments[eq_id] = {
        "id": eq_id,
        "name": name,
        "status": "AVAILABLE",
        "borrowed_by": None,
        "borrowed_at": None,
        "plate_number": None,
        "driver_name": None
    }
    save_json(EQUIPMENT_FILE, equipments)
    return jsonify({"success": True, "message": "เพิ่มสินค้าใหม่เรียบร้อยแล้ว"})

@app.route('/api/delete_equipment', methods=['POST'])
def delete_equipment():
    data = request.json or {}
    admin_pin = data.get('admin_pin')
    eq_id = data.get('eq_id')
    
    config = load_json(CONFIG_FILE, {"admin_pin": "1234"})
    if admin_pin != config.get('admin_pin'):
        return jsonify({"success": False, "message": "Admin PIN ไม่ถูกต้อง"}), 403
        
    equipments = load_json(EQUIPMENT_FILE, {})
    if eq_id not in equipments:
        return jsonify({"success": False, "message": "ไม่พบสินค้านี้ในระบบ"}), 404
        
    if equipments[eq_id].get('status') == 'BORROWED':
        return jsonify({"success": False, "message": "ไม่สามารถลบได้ เนื่องจากสินค้านี้กำลังถูกยืมอยู่"}), 400
        
    del equipments[eq_id]
    save_json(EQUIPMENT_FILE, equipments)
    return jsonify({"success": True, "message": "ลบสินค้าออกจากระบบเรียบร้อยแล้ว"})

@app.route('/api/checkout', methods=['POST'])
def checkout():
    data = request.json or {}
    token = data.get('token')
    eq_id = data.get('eq_id')
    vehicle_id = data.get('vehicle_id')
    
    username = get_current_user(token)
    if not username:
        return jsonify({"success": False, "message": "ไม่ได้เข้าสู่ระบบ"}), 401
        
    equipments = load_json(EQUIPMENT_FILE, {})
    vehicles = load_json(VEHICLES_FILE, [])
    
    target_vehicle = next((v for v in vehicles if v['id'] == vehicle_id), None)
    if not target_vehicle:
        return jsonify({"success": False, "message": "กรุณาเลือกรถขนส่งที่ลงทะเบียนไว้"}), 400
        
    plate = target_vehicle['plate_number']
    driver = target_vehicle['driver_name']
    
    if eq_id not in equipments:
        return jsonify({"success": False, "message": "ไม่พบรหัสสินค้านี้ในระบบ"}), 404
        
    item = equipments[eq_id]
    
    # บล็อกไม่ให้ยืมซ้ำ
    if item['status'] == 'BORROWED':
        return jsonify({"success": False, "message": f"สินค้านี้ ({eq_id}) ถูกยืมไปแล้ว ไม่สามารถสแกนยืมซ้ำได้! ต้องสแกนคืนก่อน"}), 400

    # ตรวจสอบคนขับคนเดิมยืมต่างทะเบียน
    for eq_key, eq_val in equipments.items():
        if eq_val.get('status') == 'BORROWED':
            existing_driver = (eq_val.get('driver_name') or '').strip()
            existing_plate = (eq_val.get('plate_number') or '').strip()

            if existing_driver and existing_driver == driver and existing_plate != plate:
                return jsonify({
                    "success": False,
                    "message": f"คุณ{driver} มีรายการยืมค้างอยู่กับทะเบียน {existing_plate} กรุณาคืนของก่อน"
                }), 400
        
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    item['status'] = 'BORROWED'
    item['borrowed_by'] = username
    item['borrowed_at'] = now_str
    item['plate_number'] = plate
    item['driver_name'] = driver
    save_json(EQUIPMENT_FILE, equipments)
    
    logs = load_json(LOGS_FILE, [])
    log_entry = {
        "log_id": str(uuid.uuid4()),
        "eq_id": eq_id,
        "eq_name": item['name'],
        "borrowed_by": username,
        "borrowed_at": now_str,
        "returned_at": None,
        "returned_by": None,
        "plate_number": plate,
        "driver_name": driver,
        "status": "BORROWED"
    }
    logs.insert(0, log_entry)
    save_json(LOGS_FILE, logs)
    
    return jsonify({"success": True, "message": f"สแกนยืมสำเร็จ: {item['name']} ({eq_id})"})

@app.route('/api/checkin', methods=['POST'])
def checkin():
    data = request.json or {}
    token = data.get('token')
    eq_id = data.get('eq_id')
    log_id = data.get('log_id')
    
    username = get_current_user(token)
    if not username:
        return jsonify({"success": False, "message": "ไม่ได้เข้าสู่ระบบ"}), 401
        
    equipments = load_json(EQUIPMENT_FILE, {})
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs = load_json(LOGS_FILE, [])
    
    target_log = None
    if log_id:
        target_log = next((l for l in logs if l['log_id'] == log_id), None)
    elif eq_id:
        target_log = next((l for l in logs if l['eq_id'] == eq_id and l['status'] == 'BORROWED'), None)

    if not target_log:
        return jsonify({"success": False, "message": "ไม่พบรายการยืมค้างอยู่ของสินค้านี้"}), 404

    target_log['returned_at'] = now_str
    target_log['returned_by'] = username
    target_log['status'] = 'RETURNED'
    save_json(LOGS_FILE, logs)
    
    if target_log['eq_id'] in equipments:
        item = equipments[target_log['eq_id']]
        item['status'] = 'AVAILABLE'
        item['borrowed_by'] = None
        item['borrowed_at'] = None
        item['plate_number'] = None
        item['driver_name'] = None
        save_json(EQUIPMENT_FILE, equipments)
        
    return jsonify({"success": True, "message": f"สแกนคืนสินค้า {target_log['eq_name']} เรียบร้อยแล้ว"})

@app.route('/api/dashboard_data', methods=['GET'])
def dashboard_data():
    equipments = load_json(EQUIPMENT_FILE, {})
    logs = load_json(LOGS_FILE, [])
    vehicles = load_json(VEHICLES_FILE, [])
    return jsonify({
        "equipments": list(equipments.values()),
        "logs": logs,
        "vehicles": vehicles
    })

@app.route('/api/change_username', methods=['POST'])
def change_username():
    data = request.json or {}
    token = data.get('token')
    new_username = data.get('new_username')
    password_confirm = data.get('password_confirm')
    
    current_user = get_current_user(token)
    if not current_user:
        return jsonify({"success": False, "message": "สิทธิ์การเข้าใช้งานไม่ถูกต้อง"}), 401
        
    users = load_json(USERS_FILE, {})
    if not check_password_hash(users[current_user]['password_hash'], password_confirm):
        return jsonify({"success": False, "message": "รหัสผ่านไม่ถูกต้อง"}), 400
        
    users[new_username] = users.pop(current_user)
    new_token = str(uuid.uuid4())
    users[new_username]['token'] = new_token
    save_json(USERS_FILE, users)
    
    return jsonify({"success": True, "message": "เปลี่ยน ชื่อผู้ใช้ สำเร็จแล้ว", "new_token": new_token, "new_username": new_username})

@app.route('/api/change_password', methods=['POST'])
def change_password():
    data = request.json or {}
    token = data.get('token')
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    current_user = get_current_user(token)
    if not current_user:
        return jsonify({"success": False, "message": "สิทธิ์การเข้าใช้งานไม่ถูกต้อง"}), 401
        
    users = load_json(USERS_FILE, {})
    if not check_password_hash(users[current_user]['password_hash'], old_password):
        return jsonify({"success": False, "message": "รหัสผ่านเดิมไม่ถูกต้อง"}), 400
        
    users[current_user]['password_hash'] = generate_password_hash(new_password)
    save_json(USERS_FILE, users)
    return jsonify({"success": True, "message": "เปลี่ยน รหัสผ่าน สำเร็จแล้ว"})

@app.route('/api/change_admin_pin', methods=['POST'])
def change_admin_pin():
    old_pin = request.form.get('old_pin')
    new_pin = request.form.get('new_pin')
    
    config = load_json(CONFIG_FILE, {"admin_pin": "1234"})
    if old_pin != config.get('admin_pin'):
        return jsonify({"success": False, "message": "Admin PIN เดิมไม่ถูกต้อง"}), 403
        
    config['admin_pin'] = new_pin
    save_json(CONFIG_FILE, config)
    return jsonify({"success": True, "message": "อัปเดต Admin PIN เรียบร้อยแล้ว"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
