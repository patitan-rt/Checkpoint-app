from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import io
import json
import secrets
import qrcode
import base64
from datetime import datetime

app = Flask(__name__)

# Config File Paths
DATA_DIR = 'data'
EQUIPMENT_FILE = os.path.join(DATA_DIR, 'equipment.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.json')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def load_json(filepath, default):
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default, f, ensure_ascii=False, indent=4)
        return default
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return default

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Initial Configurations
load_json(EQUIPMENT_FILE, [])
load_json(USERS_FILE, [])
load_json(LOGS_FILE, [])
load_json(CONFIG_FILE, {"admin_pin": "9999"})

# Active User Sessions
tokens = {}

def generate_qr_base64(text):
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()

def add_log(username, eq_id, action, details):
    logs = load_json(LOGS_FILE, [])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs.insert(0, {
        "timestamp": now_str,
        "username": username,
        "eq_id": eq_id,
        "action": action, # 'CHECKOUT', 'CHECKIN', 'SYSTEM'
        "details": details
    })
    save_json(LOGS_FILE, logs)

def get_user_by_token(token):
    return tokens.get(token)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    users = load_json(USERS_FILE, [])
    
    user = next((u for u in users if u['username'] == username and u['password'] == password), None)
    if user:
        token = secrets.token_hex(16)
        tokens[token] = username
        return jsonify({'success': True, 'token': token, 'username': username})
    return jsonify({'success': False, 'message': 'Username หรือ Password ไม่ถูกต้อง'}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    u, p, n = data.get('username'), data.get('password'), data.get('name')
    users = load_json(USERS_FILE, [])
    if any(usr['username'] == u for usr in users):
        return jsonify({'success': False, 'message': 'Username นี้ถูกใช้ไปแล้ว'}), 400
    
    users.append({"username": u, "password": p, "name": n})
    save_json(USERS_FILE, users)
    return jsonify({'success': True, 'message': 'ลงทะเบียนสำเร็จ'})

@app.route('/api/change_username', methods=['POST'])
def change_username():
    data = request.get_json() or {}
    token = data.get('token')
    new_user = data.get('new_username')
    pass_confirm = data.get('password_confirm')
    
    old_user = get_user_by_token(token)
    if not old_user: return jsonify({'success': False, 'message': 'Session หมดอายุ'}), 401
    
    users = load_json(USERS_FILE, [])
    u_obj = next((u for u in users if u['username'] == old_user and u['password'] == pass_confirm), None)
    if not u_obj:
        return jsonify({'success': False, 'message': 'รหัสผ่านยืนยันไม่ถูกต้อง'}), 400
    
    if any(u['username'] == new_user for u in users if u['username'] != old_user):
        return jsonify({'success': False, 'message': 'Username ใหม่นี้มีผู้อื่นใช้แล้ว'}), 400

    u_obj['username'] = new_user
    save_json(USERS_FILE, users)
    
    new_token = secrets.token_hex(16)
    tokens[new_token] = new_user
    del tokens[token]
    
    add_log(new_user, "-", "SYSTEM", f"เปลี่ยน Username จาก {old_user} เป็น {new_user}")
    return jsonify({'success': True, 'message': 'เปลี่ยน Username สำเร็จ', 'new_token': new_token, 'new_username': new_user})

@app.route('/api/change_password', methods=['POST'])
def change_password():
    data = request.get_json() or {}
    token = data.get('token')
    old_p = data.get('old_password')
    new_p = data.get('new_password')
    
    username = get_user_by_token(token)
    if not username: return jsonify({'success': False, 'message': 'Session หมดอายุ'}), 401
    
    users = load_json(USERS_FILE, [])
    u_obj = next((u for u in users if u['username'] == username and u['password'] == old_p), None)
    if not u_obj:
        return jsonify({'success': False, 'message': 'รหัสผ่านเดิมไม่ถูกต้อง'}), 400

    u_obj['password'] = new_p
    save_json(USERS_FILE, users)
    add_log(username, "-", "SYSTEM", "เปลี่ยนรหัสผ่านผู้ใช้งาน")
    return jsonify({'success': True, 'message': 'เปลี่ยนรหัสผ่านเรียบร้อย'})

@app.route('/api/register_equipment', methods=['POST'])
def register_equipment():
    pin = request.form.get('admin_pin')
    config = load_json(CONFIG_FILE, {})
    if pin != config.get('admin_pin'):
        return jsonify({'success': False, 'message': 'Admin PIN ไม่ถูกต้อง'}), 403

    eq_id = request.form.get('eq_id')
    name = request.form.get('name')
    equipments = load_json(EQUIPMENT_FILE, [])
    
    if any(e['id'] == eq_id for e in equipments):
        return jsonify({'success': False, 'message': 'รหัสอุปกรณ์นี้มีอยู่ในระบบแล้ว'}), 400

    qr_b64 = generate_qr_base64(eq_id)
    equipments.append({"id": eq_id, "name": name, "status": "AVAILABLE", "qrcode": qr_b64})
    save_json(EQUIPMENT_FILE, equipments)
    
    return jsonify({'success': True, 'message': f'เพิ่มอุปกรณ์ {name} ({eq_id}) เรียบร้อยแล้ว'})

@app.route('/api/equipment/edit', methods=['POST'])
def edit_equipment():
    pin = request.form.get('pin')
    config = load_json(CONFIG_FILE, {})
    if pin != config.get('admin_pin'): return jsonify({'success': False, 'message': 'Admin PIN ไม่ถูกต้อง'}), 403

    eq_id = request.form.get('eq_id')
    new_name = request.form.get('name')
    equipments = load_json(EQUIPMENT_FILE, [])
    
    eq = next((e for e in equipments if e['id'] == eq_id), None)
    if not eq: return jsonify({'success': False, 'message': 'ไม่พบอุปกรณ์'}), 404
    
    eq['name'] = new_name
    save_json(EQUIPMENT_FILE, equipments)
    return jsonify({'success': True, 'message': 'แก้ไขข้อมูลอุปกรณ์เรียบร้อย'})

@app.route('/api/equipment/delete', methods=['POST'])
def delete_equipment():
    pin = request.form.get('pin')
    config = load_json(CONFIG_FILE, {})
    if pin != config.get('admin_pin'): return jsonify({'success': False, 'message': 'Admin PIN ไม่ถูกต้อง'}), 403

    eq_id = request.form.get('eq_id')
    equipments = load_json(EQUIPMENT_FILE, [])
    equipments = [e for e in equipments if e['id'] != eq_id]
    save_json(EQUIPMENT_FILE, equipments)
    return jsonify({'success': True, 'message': 'ลบอุปกรณ์เรียบร้อย'})

@app.route('/api/checkout', methods=['POST'])
def checkout():
    data = request.get_json() or {}
    token = data.get('token')
    eq_id = data.get('eq_id')
    plate = data.get('plate_number', '-').strip() or '-'
    driver = data.get('driver_name', '-').strip() or '-'

    username = get_user_by_token(token)
    if not username: return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    equipments = load_json(EQUIPMENT_FILE, [])
    eq = next((e for e in equipments if e['id'] == eq_id), None)
    if not eq: return jsonify({'success': False, 'message': 'ไม่พบรหัสอุปกรณ์ในระบบ'}), 404
    if eq['status'] == 'BORROWED': return jsonify({'success': False, 'message': 'อุปกรณ์นี้ถูกยืมไปแล้ว'}), 400

    # -------------------------------------------------------------
    # LOGIC CHECK: ตรวจสอบการยืมค้างของคนขับต่างทะเบียนรถ
    # -------------------------------------------------------------
    if driver != '-':
        logs = load_json(LOGS_FILE, [])
        active_borrows = {}
        # วนลูป Logs จากอดีตมาปัจจุบัน เพื่อหาสถานะยืมค้างล่าสุด
        for l in reversed(logs):
            if l.get('action') in ['CHECKOUT', 'CHECKIN']:
                det = l.get('details', '')
                if 'Plate:' in det and 'Driver:' in det:
                    p = det.split('Plate:')[1].split(',')[0].strip()
                    d = det.split('Driver:')[1].strip()
                    eid = l.get('eq_id')
                    if l['action'] == 'CHECKOUT':
                        active_borrows[eid] = {'driver': d, 'plate': p}
                    elif l['action'] == 'CHECKIN' and eid in active_borrows:
                        del active_borrows[eid]

        # ค้นหาว่าคนขับคนนี้มีรายการยืมค้างในระบบอยู่หรือไม่
        for e_id, info in active_borrows.items():
            if info['driver'] == driver and info['plate'] != plate:
                return jsonify({
                    'success': False,
                    'message': f"ไม่อนุญาต: คุณ {driver} มีรายการยืมอุปกรณ์ ({e_id}) ค้างอยู่ที่รถทะเบียน [{info['plate']}] โปรด คืนสินค้าเดิม ก่อนยืมด้วยรถทะเบียน [{plate}]"
                }), 400

    # บันทึกสถานะอุปกรณ์เป็น BORROWED
    eq['status'] = 'BORROWED'
    save_json(EQUIPMENT_FILE, equipments)

    # บันทึกรูปแบบมาตรฐาน
    add_log(username, eq_id, "CHECKOUT", f"Checkout | Plate: {plate}, Driver: {driver}")
    return jsonify({'success': True, 'message': f'ยืมอุปกรณ์ {eq_id} สำเร็จ'})

@app.route('/api/checkin', methods=['POST'])
def checkin():
    data = request.get_json() or {}
    token = data.get('token')
    eq_id = data.get('eq_id')

    username = get_user_by_token(token)
    if not username: return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    equipments = load_json(EQUIPMENT_FILE, [])
    eq = next((e for e in equipments if e['id'] == eq_id), None)
    if not eq: return jsonify({'success': False, 'message': 'ไม่พบรหัสอุปกรณ์ในระบบ'}), 404

    eq['status'] = 'AVAILABLE'
    save_json(EQUIPMENT_FILE, equipments)

    add_log(username, eq_id, "CHECKIN", "Checkin | คืนอุปกรณ์เรียบร้อยแล้ว")
    return jsonify({'success': True, 'message': f'คืนอุปกรณ์ {eq_id} สำเร็จ'})

@app.route('/api/change_admin_pin', methods=['POST'])
def change_admin_pin():
    old_pin = request.form.get('old_pin')
    new_pin = request.form.get('new_pin')
    config = load_json(CONFIG_FILE, {})
    if old_pin != config.get('admin_pin'):
        return jsonify({'success': False, 'message': 'PIN เดิมไม่ถูกต้อง'}), 403

    config['admin_pin'] = new_pin
    save_json(CONFIG_FILE, config)
    return jsonify({'success': True, 'message': 'เปลี่ยน Admin PIN สำเร็จ'})

@app.route('/api/dashboard_data', methods=['GET'])
def dashboard_data():
    year = request.args.get('year', 'ALL')
    month = request.args.get('month', 'ALL')
    day = request.args.get('day', 'ALL')

    equipments = load_json(EQUIPMENT_FILE, [])
    logs = load_json(LOGS_FILE, [])

    # Filter Logs ตามวันที่
    filtered_logs = []
    for l in logs:
        try:
            dt = datetime.strptime(l['timestamp'], "%Y-%m-%d %H:%M:%S")
            if year != 'ALL' and str(dt.year) != str(year): continue
            if month != 'ALL' and str(dt.month) != str(month): continue
            if day != 'ALL' and str(dt.day) != str(day): continue
            filtered_logs.append(l)
        except:
            filtered_logs.append(l)

    return jsonify({'equipments': equipments, 'logs': filtered_logs})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
