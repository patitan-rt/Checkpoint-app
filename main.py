import os
import io
import base64
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
import qrcode

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_session'

# --- DATABASE SETUP ---
DB_NAME = 'inventory_system.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    pin TEXT DEFAULT '9999'
                )''')
    
    # Items Table
    c.execute('''CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT,
                    qr_code_base64 TEXT
                )''')

    # Transactions Table (Borrow / Return)
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT,
                    user_name TEXT,
                    action TEXT, -- 'CHECKOUT' or 'CHECKIN'
                    license_plate TEXT,
                    driver_name TEXT,
                    timestamp TEXT
                )''')

    # System Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operator TEXT,
                    action_detail TEXT,
                    timestamp TEXT
                )''')

    # Seed Default Admin User if not exists
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, pin) VALUES (?, ?, ?)", ('admin', 'admin123', '9999'))

    conn.commit()
    conn.close()

init_db()

# --- HELPER FUNCTIONS ---
def generate_qr_base64(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def log_system_action(operator, action_detail):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO system_logs (operator, action_detail, timestamp) VALUES (?, ?, ?)", 
              (operator, action_detail, now))
    conn.commit()
    conn.close()

# --- HTML TEMPLATE WITH EMBEDDED CSS & JS ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Equipment & QR Management System</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 10px; color: #c9d1d9; }
        .form-control, .form-select { background-color: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus, .form-select:focus { background-color: #161b22; color: #58a6ff; border-color: #58a6ff; box-shadow: none; }
        .btn-custom-primary { background-color: #238636; color: #fff; border: none; }
        .btn-custom-primary:hover { background-color: #2ea043; color: #fff; }
        .btn-custom-secondary { background-color: #21262d; color: #c9d1d9; border: 1px solid #30363d; }
        .btn-custom-secondary:hover { background-color: #30363d; color: #58a6ff; }
        .table-dark-custom { color: #c9d1d9; border-color: #30363d; }
        .table-dark-custom th { background-color: #21262d; border-color: #30363d; }
        .table-dark-custom td { border-color: #30363d; }
        .nav-tabs .nav-link { color: #8b949e; border: none; }
        .nav-tabs .nav-link.active { background-color: #161b22; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
        
        /* Print Label Styles */
        @media print {
            body * { visibility: hidden; }
            #printable-area, #printable-area * { visibility: visible; }
            #printable-area { position: absolute; left: 0; top: 0; width: 100%; }
            .no-print { display: none !important; }
        }
        .qr-sticker {
            width: 250px;
            padding: 15px;
            border: 2px dashed #000;
            background: #fff;
            color: #000;
            text-align: center;
            margin: auto;
            border-radius: 8px;
        }
    </style>
</head>
<body class="p-3 p-md-4">
<div class="container-fluid max-width-1200">

    <!-- Header Navigation -->
    <div class="d-flex justify-content-between align-items-center mb-4 pb-2 border-bottom border-secondary">
        <h2>🛠️ Equipment Borrow & Return System</h2>
        <div>
            <span class="me-3 text-info">👤 {{ session['username'] }}</span>
            <button class="btn btn-sm btn-outline-danger" onclick="logout()">Logout</button>
        </div>
    </div>

    <!-- Navigation Tabs -->
    <ul class="nav nav-tabs mb-4" id="mainTabs" role="tablist">
        <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#scan-tab">📸 QR Scanner & Actions</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#items-tab" onclick="loadItems()">📦 Items & Print QR</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#logs-tab" onclick="loadLogs()">📜 Logs & Filter</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#settings-tab">⚙️ Settings</button></li>
    </ul>

    <div class="tab-content">
        <!-- TAB 1: SCANNER & BORROW/RETURN -->
        <div class="tab-pane fade show active" id="scan-tab">
            <div class="row g-4">
                <div class="col-md-6">
                    <div class="card p-3 h-100">
                        <h5>📸 QR Code Scanner</h5>
                        <div id="reader" style="width: 100%; border-radius: 8px; overflow: hidden; background: #000;"></div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card p-3 h-100">
                        <h5>📝 Transaction Info</h5>
                        <form id="checkoutForm">
                            <div class="mb-3">
                                <label class="form-label">Item ID (Scanned/Manual)</label>
                                <input type="text" id="scan_item_id" class="form-control" placeholder="Scan or Enter ID" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Borrower Name (ชื่อผู้ยืม)</label>
                                <input type="text" id="borrower_name" class="form-control" placeholder="John Doe" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">License Plate (ทะเบียนรถ)</label>
                                <input type="text" id="license_plate" class="form-control" placeholder="1กข-9999" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Driver Name (ชื่อคนขับ)</label>
                                <input type="text" id="driver_name" class="form-control" placeholder="Driver Name" required>
                            </div>
                            <div class="d-flex gap-2">
                                <button type="button" class="btn btn-custom-primary flex-fill" onclick="processAction('CHECKOUT')">📥 ยืมสินค้า (Checkout)</button>
                                <button type="button" class="btn btn-warning flex-fill" onclick="processAction('CHECKIN')">📤 คืนสินค้า (Checkin)</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>

        <!-- TAB 2: ITEMS & QR PRINT -->
        <div class="tab-pane fade" id="items-tab">
            <div class="card p-3 mb-4">
                <h5>➕ Add New Item</h5>
                <form id="addItemForm" class="row g-3">
                    <div class="col-md-3"><input type="text" id="new_id" class="form-control" placeholder="Item ID (e.g. ITM-001)" required></div>
                    <div class="col-md-4"><input type="text" id="new_name" class="form-control" placeholder="Item Name" required></div>
                    <div class="col-md-3"><input type="text" id="new_cat" class="form-control" placeholder="Category"></div>
                    <div class="col-md-2"><button type="submit" class="btn btn-custom-primary w-100">Save Item</button></div>
                </form>
            </div>
            
            <div class="card p-3">
                <h5>📦 Item List & Generate Label</h5>
                <div class="row g-3" id="itemsGrid">
                    <!-- Dynamic Items Cards Loaded via JS -->
                </div>
            </div>
        </div>

        <!-- TAB 3: LOGS & FILTERS -->
        <div class="tab-pane fade" id="logs-tab">
            <div class="card p-3 mb-4">
                <div class="row g-3 align-items-center">
                    <div class="col-md-3">
                        <label class="form-label">Filter Year</label>
                        <select id="filterYear" class="form-select" onchange="loadLogs()"><option value="">All Years</option></select>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label">Filter Month</label>
                        <select id="filterMonth" class="form-select" onchange="loadLogs()"><option value="">All Months</option></select>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label">Filter Day</label>
                        <select id="filterDay" class="form-select" onchange="loadLogs()"><option value="">All Days</option></select>
                    </div>
                </div>
            </div>

            <div class="card p-3 mb-4">
                <h5>📋 Borrow / Return Logs</h5>
                <div class="table-responsive">
                    <table class="table table-dark-custom align-middle">
                        <thead>
                            <tr>
                                <th>Timestamp</th><th>Action</th><th>Item ID</th><th>Borrower</th><th>License Plate</th><th>Driver</th>
                            </tr>
                        </thead>
                        <tbody id="logsTableBody"></tbody>
                    </table>
                </div>
            </div>

            <div class="card p-3">
                <h5>⚙️ Operator / System Logs</h5>
                <div class="table-responsive">
                    <table class="table table-dark-custom align-middle">
                        <thead>
                            <tr><th>Timestamp</th><th>Operator</th><th>Action Details</th></tr>
                        </thead>
                        <tbody id="sysLogsTableBody"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 4: SETTINGS -->
        <div class="tab-pane fade" id="settings-tab">
            <div class="row g-4">
                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>👤 Account Settings</h5>
                        <div class="mb-3">
                            <label class="form-label">New Username</label>
                            <input type="text" id="up_user" class="form-control" value="{{ session['username'] }}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">New Password</label>
                            <input type="password" id="up_pass" class="form-control" placeholder="Leave blank to keep current">
                        </div>
                        <button class="btn btn-custom-primary" onclick="updateProfile()">Update Profile</button>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>🔒 Security Admin PIN</h5>
                        <div class="mb-3">
                            <label class="form-label">Current / New Action PIN</label>
                            <input type="password" id="up_pin" class="form-control" placeholder="Default: 9999">
                        </div>
                        <button class="btn btn-warning" onclick="updatePin()">Update PIN</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- PRINT QR CODE MODAL -->
<div class="modal fade" id="printModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content bg-dark text-light border-secondary">
            <div class="modal-header border-secondary">
                <h5 class="modal-title">🖨️ Print QR Label</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body text-center" id="printable-area">
                <div class="qr-sticker">
                    <h5 id="p_name" class="fw-bold mb-1" style="font-size: 16px;">Item Name</h5>
                    <p id="p_id" class="text-muted mb-2" style="font-size: 12px;">ID: ITM-0000</p>
                    <img id="p_qr" src="" style="width: 150px; height: 150px;" alt="QR Code">
                    <p id="p_cat" class="mt-2 mb-0 fw-semibold" style="font-size: 11px; text-transform: uppercase;">Category</p>
                </div>
            </div>
            <div class="modal-footer border-secondary">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                <button type="button" class="btn btn-custom-primary" onclick="window.print()">🖨️ Print Sticker</button>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
    let html5QrcodeScanner;

    document.addEventListener("DOMContentLoaded", function() {
        // Init Scanner
        html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: 250 });
        html5QrcodeScanner.render(onScanSuccess);

        // Date Filter Options Initialization
        const ySel = document.getElementById('filterYear');
        const currentYear = new Date().getFullYear();
        for(let i=currentYear; i>=currentYear-5; i--) ySel.innerHTML += `<option value="${i}">${i}</option>`;
        
        const mSel = document.getElementById('filterMonth');
        for(let i=1; i<=12; i++) mSel.innerHTML += `<option value="${String(i).padStart(2,'0')}">Month ${i}</option>`;

        const dSel = document.getElementById('filterDay');
        for(let i=1; i<=31; i++) dSel.innerHTML += `<option value="${String(i).padStart(2,'0')}">Day ${i}</option>`;
    });

    function onScanSuccess(decodedText) {
        document.getElementById('scan_item_id').value = decodedText;
    }

    // CHECKOUT / CHECKIN ACTION
    function processAction(actionType) {
        const payload = {
            item_id: document.getElementById('scan_item_id').value,
            user_name: document.getElementById('borrower_name').value,
            license_plate: document.getElementById('license_plate').value,
            driver_name: document.getElementById('driver_name').value,
            action: actionType
        };

        if(!payload.item_id || !payload.user_name || !payload.license_plate) {
            alert('Please fill out all required fields!');
            return;
        }

        fetch('/api/transaction', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            if(data.success) {
                alert(`SUCCESS: ${actionType} completed!`);
                document.getElementById('checkoutForm').reset();
            } else {
                alert(`ERROR: ${data.message}`);
            }
        });
    }

    // LOAD ITEMS
    function loadItems() {
        fetch('/api/items')
        .then(res => res.json())
        .then(items => {
            const grid = document.getElementById('itemsGrid');
            grid.innerHTML = items.map(item => `
                <div class="col-md-3">
                    <div class="card p-3 text-center h-100">
                        <img src="data:image/png;base64,${item.qr_code_base64}" class="img-fluid mx-auto mb-2" style="max-width: 120px;">
                        <h6 class="mb-1">${item.name}</h6>
                        <small class="text-muted d-block mb-2">ID: ${item.id} | Cat: ${item.category || '-'}</small>
                        <button class="btn btn-sm btn-custom-secondary mt-auto" onclick="openPrintModal('${item.id}', '${item.name}', '${item.category}', '${item.qr_code_base64}')">
                            🖨️ Print Label
                        </button>
                    </div>
                </div>
            `).join('');
        });
    }

    // PRINT MODAL SETUP
    function openPrintModal(id, name, cat, qrBase64) {
        document.getElementById('p_id').innerText = `ID: ${id}`;
        document.getElementById('p_name').innerText = name;
        document.getElementById('p_cat').innerText = cat || 'GENERAL';
        document.getElementById('p_qr').src = `data:image/png;base64,${qrBase64}`;
        new bootstrap.Modal(document.getElementById('printModal')).show();
    }

    // ADD ITEM
    document.getElementById('addItemForm').addEventListener('submit', function(e) {
        e.preventDefault();
        const payload = {
            id: document.getElementById('new_id').value,
            name: document.getElementById('new_name').value,
            category: document.getElementById('new_cat').value
        };
        fetch('/api/items', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            if(data.success) {
                this.reset();
                loadItems();
            } else {
                alert(data.message);
            }
        });
    });

    // LOAD LOGS
    function loadLogs() {
        const y = document.getElementById('filterYear').value;
        const m = document.getElementById('filterMonth').value;
        const d = document.getElementById('filterDay').value;

        fetch(`/api/logs?year=${y}&month=${m}&day=${d}`)
        .then(res => res.json())
        .then(data => {
            document.getElementById('logsTableBody').innerHTML = data.transactions.map(t => `
                <tr>
                    <td>${t.timestamp}</td>
                    <td><span class="badge ${t.action==='CHECKOUT'?'bg-danger':'bg-success'}">${t.action}</span></td>
                    <td>${t.item_id}</td>
                    <td>${t.user_name}</td>
                    <td>${t.license_plate}</td>
                    <td>${t.driver_name}</td>
                </tr>
            `).join('');

            document.getElementById('sysLogsTableBody').innerHTML = data.system_logs.map(s => `
                <tr>
                    <td>${s.timestamp}</td>
                    <td>${s.operator}</td>
                    <td>${s.action_detail}</td>
                </tr>
            `).join('');
        });
    }

    // PROFILE & SECURITY UPDATES
    function updateProfile() {
        fetch('/api/user/update-profile', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                username: document.getElementById('up_user').value,
                password: document.getElementById('up_pass').value
            })
        }).then(res => res.json()).then(data => alert(data.message));
    }

    function updatePin() {
        fetch('/api/user/update-pin', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ pin: document.getElementById('up_pin').value })
        }).then(res => res.json()).then(data => alert(data.message));
    }

    function logout() {
        window.location.href = '/logout';
    }
</script>
</body>
</html>
"""

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>Login - Inventory System</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #0d1117; color: #c9d1d9; display: flex; align-items: center; justify-content: center; height: 100vh; }
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 10px; width: 350px; }
        .form-control { background-color: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
    </style>
</head>
<body>
<div class="card p-4">
    <h4 class="text-center mb-4">🔐 System Login</h4>
    {% if error %} <div class="alert alert-danger p-2">{{ error }}</div> {% endif %}
    <form method="POST">
        <div class="mb-3">
            <label class="form-label">Username</label>
            <input type="text" name="username" class="form-control" required>
        </div>
        <div class="mb-3">
            <label class="form-label">Password</label>
            <input type="password" name="password" class="form-control" required>
        </div>
        <button type="submit" class="btn btn-success w-100">Login</button>
    </form>
</div>
</body>
</html>
"""

# --- ROUTES & API ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form['username']
        pwd = request.form['password']
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (uname, pwd))
        user = c.fetchone()
        conn.close()
        if user:
            session['username'] = uname
            log_system_action(uname, "User logged in.")
            return redirect(url_for('index'))
        return render_template_string(LOGIN_TEMPLATE, error="Invalid credentials!")
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    if 'username' in session:
        log_system_action(session['username'], "User logged out.")
        session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/items', methods=['GET', 'POST'])
def handle_items():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if request.method == 'POST':
        data = request.json
        qr_b64 = generate_qr_base64(data['id'])
        try:
            c.execute("INSERT INTO items (id, name, category, qr_code_base64) VALUES (?, ?, ?, ?)",
                      (data['id'], data['name'], data.get('category', ''), qr_b64))
            conn.commit()
            log_system_action(session['username'], f"Created Item ID: {data['id']}")
            conn.close()
            return jsonify({'success': True})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'success': False, 'message': 'Item ID already exists!'})

    c.execute("SELECT id, name, category, qr_code_base64 FROM items")
    rows = c.fetchall()
    conn.close()
    return jsonify([{'id': r[0], 'name': r[1], 'category': r[2], 'qr_code_base64': r[3]} for r in rows])

@app.route('/api/transaction', methods=['POST'])
def transaction():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    item_id = data['item_id']
    user_name = data['user_name']
    license_plate = data['license_plate']
    driver_name = data['driver_name']
    action = data['action'] # CHECKOUT or CHECKIN

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # CHECK LICENSE PLATE CONSTRAINT (ห้ามยืมข้ามทะเบียนรถ)
    if action == 'CHECKOUT':
        c.execute("""SELECT license_plate FROM transactions 
                     WHERE user_name = ? 
                     ORDER BY id DESC LIMIT 1""", (user_name,))
        last_trans = c.fetchone()
        
        # Verify active unreturned items
        c.execute("""SELECT action FROM transactions 
                     WHERE user_name = ? AND item_id = ? 
                     ORDER BY id DESC LIMIT 1""", (user_name, item_id))
        item_status = c.fetchone()

        if last_trans and last_trans[0] != license_plate:
            # Check if user has unreturned items on the old license plate
            c.execute("""SELECT item_id FROM transactions WHERE user_name = ? AND license_plate = ?""", 
                      (user_name, last_trans[0]))
            all_user_items = c.fetchall()
            
            unreturned = False
            for item in set(all_user_items):
                c.execute("""SELECT action FROM transactions WHERE user_name = ? AND item_id = ? ORDER BY id DESC LIMIT 1""", 
                          (user_name, item[0]))
                st = c.fetchone()
                if st and st[0] == 'CHECKOUT':
                    unreturned = True
                    break

            if unreturned:
                conn.close()
                return jsonify({
                    'success': False, 
                    'message': f"ผู้ยืม '{user_name}' ยังยืมของค้างอยู่ที่ทะเบียน '{last_trans[0]}' กรุณาคืนของทั้งหมดก่อนยืมไปกับทะเบียนอื่น!"
                })

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""INSERT INTO transactions (item_id, user_name, action, license_plate, driver_name, timestamp) 
                 VALUES (?, ?, ?, ?, ?, ?)""", 
              (item_id, user_name, action, license_plate, driver_name, now))
    conn.commit()
    conn.close()

    log_system_action(session['username'], f"Processed {action} for Item '{item_id}' by '{user_name}' (Plate: {license_plate})")
    return jsonify({'success': True})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    y = request.args.get('year', '')
    m = request.args.get('month', '')
    d = request.args.get('day', '')

    query = "SELECT timestamp, action, item_id, user_name, license_plate, driver_name FROM transactions WHERE 1=1"
    params = []

    if y:
        query += " AND strftime('%Y', timestamp) = ?"
        params.append(y)
    if m:
        query += " AND strftime('%m', timestamp) = ?"
        params.append(m)
    if d:
        query += " AND strftime('%d', timestamp) = ?"
        params.append(d)

    query += " ORDER BY id DESC LIMIT 100"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    t_rows = c.fetchall()

    c.execute("SELECT timestamp, operator, action_detail FROM system_logs ORDER BY id DESC LIMIT 100")
    s_rows = c.fetchall()
    conn.close()

    return jsonify({
        'transactions': [{'timestamp': r[0], 'action': r[1], 'item_id': r[2], 'user_name': r[3], 'license_plate': r[4], 'driver_name': r[5]} for r in t_rows],
        'system_logs': [{'timestamp': r[0], 'operator': r[1], 'action_detail': r[2]} for r in s_rows]
    })

@app.route('/api/user/update-profile', methods=['POST'])
def update_profile():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    new_u = data.get('username')
    new_p = data.get('password')
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if new_p:
        c.execute("UPDATE users SET username = ?, password = ? WHERE username = ?", (new_u, new_p, session['username']))
    else:
        c.execute("UPDATE users SET username = ? WHERE username = ?", (new_u, session['username']))
    conn.commit()
    conn.close()

    log_system_action(session['username'], f"Updated profile/username to '{new_u}'")
    session['username'] = new_u
    return jsonify({'message': 'Profile updated successfully!'})

@app.route('/api/user/update-pin', methods=['POST'])
def update_pin():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    new_pin = data.get('pin')
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET pin = ? WHERE username = ?", (new_pin, session['username']))
    conn.commit()
    conn.close()

    log_system_action(session['username'], "Updated Security Admin PIN")
    return jsonify({'message': 'PIN updated successfully!'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
