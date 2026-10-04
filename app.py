import os
import re
import pandas as pd
from flask import Flask, render_template_string, request, redirect, url_for, session
from datetime import date, datetime
import sqlite3
import io

app = Flask(__name__)
app.secret_key = 'logistics_secret_key_2026'
DB_NAME = 'logistics.db'

# 辅助函数：智能清洗和提取单元格文本（精准保留 "NAN" 和 "NA" 作为合法司机名或字符串）
def clean_val(val, default=''):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip()
    if s == '' or s.lower() == 'none':
        return default
    return s

# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    ''')
    
    # 运单与 Invoice 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no TEXT,
            tracking_no TEXT,
            customer TEXT,
            amount REAL,
            status TEXT,
            delivery_date TEXT,
            pod_status TEXT,
            check_in_time TEXT,
            pod_remark TEXT,
            assigned_driver TEXT,
            posted_date TEXT,
            posted_by TEXT,
            undelivery_reason TEXT,
            redelivery_count INTEGER DEFAULT 0
        )
    ''')
    
    # 补送历史记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS redelivery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no TEXT,
            tracking_no TEXT,
            customer TEXT,
            original_driver TEXT,
            redelivery_time TEXT,
            operator TEXT,
            reason TEXT
        )
    ''')

    # Packing List 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS packing_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_no TEXT,
            cargo_name TEXT,
            driver TEXT,
            inv_no TEXT,
            pl_date TEXT
        )
    ''')
    
    # 插入默认管理员账号
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, role) VALUES ('admin', 'admin123', 'admin')")
        cursor.execute("INSERT INTO users (username, password, role) VALUES ('BALA', '123', 'driver')")
        cursor.execute("INSERT INTO users (username, password, role) VALUES ('NAN', '123', 'driver')")
        cursor.execute("INSERT INTO users (username, password, role) VALUES ('NA', '123', 'driver')")
    
    conn.commit()
    conn.close()

init_db()

TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>罗厘货运代理与车队管理系统</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    {% if not session.get('user') %}
    <div class="container mt-5" style="max-width: 400px;">
        <div class="card shadow p-4">
            <h3 class="text-center mb-4">🚚 货代系统登录</h3>
            {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
            <form method="POST" action="/login">
                <div class="mb-3">
                    <label>用户名</label>
                    <input type="text" name="username" class="form-control" required>
                </div>
                <div class="mb-3">
                    <label>密码</label>
                    <input type="password" name="password" class="form-control" required>
                </div>
                <button type="submit" class="btn btn-primary w-100">登录</button>
            </form>
        </div>
    </div>
    {% else %}
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 bg-dark text-white min-vh-100 p-3">
                <h4>🚚 车队管理系统</h4>
                <hr>
                <p class="small text-warning">当前用户: {{ session.get('user') }} ({{ session.get('role') }})</p>
                <hr>
                {% if session.get('role') == 'admin' %}
                    <a href="/invoices" class="btn btn-dark w-100 text-start mb-2">📥 Invoice 管理与导入</a>
                    <a href="/check_invoices" class="btn btn-dark w-100 text-start mb-2">✅ Check Invoice & Post</a>
                    <a href="/redelivery_history" class="btn btn-dark w-100 text-start mb-2">🔄 补送历史记录</a>
                    <a href="/invoices_done" class="btn btn-dark w-100 text-start mb-2">📁 Invoice Done (归档)</a>
                    <a href="/packing" class="btn btn-dark w-100 text-start mb-2">📋 Packing List 管理</a>
                    {% if session.get('user') == 'admin' %}
                        <a href="/drivers_manage" class="btn btn-outline-info w-100 text-start mb-2">👥 司机账号管理</a>
                        <a href="/admins_manage" class="btn btn-outline-warning w-100 text-start mb-2">🛡️ 管理员账号管理</a>
                    {% endif %}
                {% else %}
                    <a href="/driver_portal" class="btn btn-dark w-100 text-start mb-2">📱 司机打卡端</a>
                {% endif %}
                <hr>
                <a href="/logout" class="btn btn-outline-danger w-100 btn-sm">退出登录</a>
            </div>

            <div class="col-md-10 p-4">
                {% block content %}{% endblock %}
            </div>
        </div>
    </div>
    {% endif %}
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

@app.route('/')
def index():
    if not session.get('user'):
        return render_template_string(TEMPLATE)
    if session.get('role') == 'admin':
        return redirect(url_for('check_invoices'))
    else:
        return redirect(url_for('driver_portal'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username=? AND password=?", (username, password))
    user = cursor.fetchone()
    conn.close()
    if user:
        session['user'] = username
        session['role'] = user[0]
        return redirect(url_for('index'))
    else:
        return render_template_string(TEMPLATE, error="用户名或密码错误！")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- Invoice 管理与导入模块 ---
@app.route('/invoices', methods=['GET', 'POST'])
def invoices():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        action_type = request.form.get('action_type')
        if action_type == 'assign_driver':
            inv_id = request.form.get('inv_id')
            new_driver = request.form.get('assigned_driver')
            if inv_id:
                cursor.execute("UPDATE invoices SET assigned_driver=? WHERE id=?", (new_driver, inv_id))
                conn.commit()
        elif action_type == 'manual_add':
            inv_no = request.form.get('inv_no', '').strip()
            customer = request.form.get('customer', '').strip()
            tracking_no = request.form.get('tracking_no', 'LOG-DEFAULT').strip()
            amount = request.form.get('amount', 0.0)
            delivery_date = request.form.get('delivery_date', date.today().strftime('%Y-%m-%d'))
            driver = request.form.get('driver', '').strip()
            if inv_no:
                cursor.execute("""
                    INSERT INTO invoices (inv_no, tracking_no, customer, amount, status, delivery_date, pod_status, assigned_driver)
                    VALUES (?, ?, ?, ?, '未送达', ?, '未上传', ?)
                """, (inv_no, tracking_no, customer, amount, delivery_date, driver))
                conn.commit()
        elif action_type == 'batch_delete':
            selected_invs = request.form.getlist('selected_inv')
            for i_id in selected_invs:
                cursor.execute("DELETE FROM invoices WHERE id=?", (i_id,))
            conn.commit()

    date_filter = request.args.get('date', '')
    inv_filter = request.args.get('inv', '')
    
    query = "SELECT id, inv_no, tracking_no, customer, amount, status, delivery_date, assigned_driver, redelivery_count FROM invoices WHERE status != '已POST'"
    params = []
    if date_filter:
        query += " AND delivery_date = ?"
        params.append(date_filter)
    if inv_filter:
        query += " AND inv_no LIKE ?"
        params.append(f"%{inv_filter}%")
        
    cursor.execute(query, params)
    inv_list = cursor.fetchall()
    
    cursor.execute("SELECT username FROM users WHERE role='driver'")
    driver_list = [d[0] for d in cursor.fetchall()]
    conn.close()

    today_str = date.today().strftime('%Y-%m-%d')

    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>📥 Invoice 集中管理与智能导入</h2>
    <hr>
    <form method="GET" class="row g-3 mb-4 bg-white p-3 shadow-sm rounded">
        <div class="col-md-4"><label class="form-label">按日期筛选</label><input type="date" name="date" class="form-control" value="'''+date_filter+'''"></div>
        <div class="col-md-4"><label class="form-label">按 Invoice 编号筛选</label><input type="text" name="inv" class="form-control" placeholder="输入 INV 编号" value="'''+inv_filter+'''"></div>
        <div class="col-md-4 d-flex align-items-end"><button type="submit" class="btn btn-primary w-100 me-2">🔍 筛选</button><a href="/invoices" class="btn btn-secondary w-100">🔄 重置</a></div>
    </form>
    
    <div class="mb-3 d-flex justify-content-between">
        <div>
            <button class="btn btn-primary me-2" data-bs-toggle="modal" data-bs-target="#manualAddModal">➕ 手动添加 Invoice</button>
            <a href="/import_invoice_page" class="btn btn-success">📥 智能导入 Invoice (Excel/CSV)</a>
        </div>
        <button type="button" class="btn btn-danger" onclick="batchDelete()">🗑️ 批量删除勾选项</button>
    </div>
    
    <form method="POST" id="batchForm">
        <input type="hidden" name="action_type" id="actionType" value="batch_delete">
        <table class="table table-hover bg-white shadow-sm rounded align-middle">
            <thead class="table-dark">
                <tr>
                    <th width="40"><input type="checkbox" onclick="selectAll(this)"></th>
                    <th>Invoice 编号</th><th>运单号</th><th>客户名称</th><th>日期</th><th>指派司机</th><th>金额 (RM)</th><th>状态</th><th>操作</th>
                </tr>
            </thead>
            <tbody>
                {% for row in inv_list %}
                <tr>
                    <td><input type="checkbox" name="selected_inv" value="{{ row[0] }}"></td>
                    <td><b>{{ row[1] }}</b></td>
                    <td>{{ row[2] }}</td>
                    <td>{{ row[3] }}</td>
                    <td><small class="text-muted">{{ row[6] or '-' }}</small></td>
                    <td>
                        <form method="POST" class="d-inline">
                            <input type="hidden" name="action_type" value="assign_driver">
                            <input type="hidden" name="inv_id" value="{{ row[0] }}">
                            <select name="assigned_driver" class="form-select form-select-sm" onchange="this.form.submit()">
                                <option value="">-- 未指派 --</option>
                                {% for d in driver_list %}
                                <option value="{{ d }}" {% if row[7] == d %}selected{% endif %}>{{ d }}</option>
                                {% endfor %}
                            </select>
                        </form>
                    </td>
                    <td>{{ row[4] }}</td>
                    <td>
                        {% if row[5] == 'Undelivery' %}<span class="badge bg-danger">❌ 未送达</span>
                        {% elif row[5] == '已打卡' %}<span class="badge bg-success">✅ 已打卡</span>
                        {% else %}<span class="badge bg-warning text-dark">{{ row[5] }}</span>{% endif %}
                    </td>
                    <td><a href="/delete_invoice/{{ row[0] }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('确定删除该 Invoice 吗？')">删除</a></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </form>

    <!-- 手动添加 Invoice 模态框 -->
    <div class="modal fade" id="manualAddModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <form method="POST">
                    <input type="hidden" name="action_type" value="manual_add">
                    <div class="modal-header bg-primary text-white">
                        <h5 class="modal-title">➕ 手动添加新 Invoice</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3"><label class="form-label"><b>Invoice 编号 (Doc No)</b></label><input type="text" name="inv_no" class="form-control" placeholder="例如: INV-8899" required></div>
                        <div class="mb-3"><label class="form-label"><b>客户名称 (Debtor Name)</b></label><input type="text" name="customer" class="form-control" placeholder="例如: ABC Trading"></div>
                        <div class="mb-3"><label class="form-label">运单号 (Tracking No)</label><input type="text" name="tracking_no" class="form-control" placeholder="默认 LOG-DEFAULT" value="LOG-DEFAULT"></div>
                        <div class="mb-3"><label class="form-label">日期</label><input type="date" name="delivery_date" class="form-control" value="''' + today_str + '''"></div>
                        <div class="mb-3"><label class="form-label">金额 (RM)</label><input type="number" step="0.01" name="amount" class="form-control" value="0.0"></div>
                        <div class="mb-3">
                            <label class="form-label">分配司机</label>
                            <select name="driver" class="form-select">
                                <option value="">-- 暂不分配 --</option>
                                {% for d in driver_list %}<option value="{{ d }}">{{ d }}</option>{% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                        <button type="submit" class="btn btn-primary">保存添加</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script>
    function selectAll(source){
        let checkboxes = document.getElementsByName('selected_inv');
        for(let cb of checkboxes) cb.checked = source.checked;
    }
    function batchDelete() {
        let checkboxes = document.getElementsByName('selected_inv');
        let count = 0;
        for(let cb of checkboxes) if(cb.checked) count++;
        if(count === 0) { alert('请先勾选要删除的 Invoice 项！'); return; }
        if(confirm('确定要批量删除选中的 ' + count + ' 项吗？')) {
            document.getElementById('batchForm').submit();
        }
    }
    </script>
    ''')
    return render_template_string(html, inv_list=inv_list, driver_list=driver_list)

@app.route('/import_invoice_page', methods=['GET', 'POST'])
def import_invoice_page():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    msg, error_msg = "", ""
    today_str = date.today().strftime('%Y-%m-%d')
    if request.method == 'POST':
        if 'excel_file' in request.files and request.files['excel_file'].filename != '':
            file = request.files['excel_file']
            try:
                file_bytes = file.read()
                filename_lower = file.filename.lower()
                
                # keep_default_na=False 保证 NAN 和 NA 不会被自动解析为 Python 的 NaN
                if filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls'):
                    df = pd.read_excel(io.BytesIO(file_bytes), keep_default_na=False)
                else:
                    df = pd.read_csv(io.BytesIO(file_bytes), keep_default_na=False)
                
                if df is None or len(df.columns) == 0: raise ValueError("文件为空或无法解析！")
                
                df.columns = df.columns.astype(str).str.strip()
                
                # 建立智能匹配映射 (Doc No -> Invoice, Debtor Name -> Customer)
                inv_col, cust_col, track_col, amount_col, date_col, driver_col = None, None, None, None, None, None
                for col in df.columns:
                    c_lower = col.lower().replace('.', '').replace('_', ' ').strip()
                    if not inv_col and any(k in c_lower for k in ['doc no', 'invoice', 'inv no', 'inv', 'docno']):
                        inv_col = col
                    elif not cust_col and any(k in c_lower for k in ['debtor name', 'customer', 'debtor', 'client']):
                        cust_col = col
                    elif not track_col and any(k in c_lower for k in ['tracking', 'order no', 'waybill', '运单']):
                        track_col = col
                    elif not amount_col and any(k in c_lower for k in ['amount', 'total', 'net amount', '金额']):
                        amount_col = col
                    elif not date_col and any(k in c_lower for k in ['date', '日期']):
                        date_col = col
                    elif not driver_col and any(k in c_lower for k in ['driver', '司机']):
                        driver_col = col

                # 如果无法精确识别，兜底默认前两列
                if not inv_col and len(df.columns) > 0: inv_col = df.columns[0]
                if not cust_col and len(df.columns) > 1: cust_col = df.columns[1]

                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                count = 0
                
                for _, row in df.iterrows():
                    inv_no = clean_val(row.get(inv_col))
                    if not inv_no: continue
                    
                    customer = clean_val(row.get(cust_col), '未知客户')
                    tracking_no = clean_val(row.get(track_col), 'LOG-DEFAULT')
                    
                    raw_amount = clean_val(row.get(amount_col), '0')
                    try: amount = float(re.sub(r'[^\d.]', '', raw_amount))
                    except: amount = 0.0
                    
                    delivery_date = clean_val(row.get(date_col), today_str).split(' ')[0]
                    if not delivery_date: delivery_date = today_str
                    
                    driver = clean_val(row.get(driver_col), '')

                    cursor.execute("""
                        INSERT INTO invoices (inv_no, tracking_no, customer, amount, status, delivery_date, pod_status, assigned_driver) 
                        VALUES (?, ?, ?, ?, '未送达', ?, '未上传', ?)
                    """, (inv_no, tracking_no, customer, amount, delivery_date, driver))
                    count += 1
                    
                conn.commit()
                conn.close()
                msg = f"成功智能导入了 {count} 条 Invoice 记录！"
            except Exception as e: error_msg = f"文件导入识别失败: {str(e)}"
            
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>📥 智能导入 Invoice (Excel / CSV)</h2>
    <hr>
    {% if msg %}<div class="alert alert-success">{{ msg }}</div>{% endif %}
    {% if error_msg %}<div class="alert alert-danger">{{ error_msg }}</div>{% endif %}
    <div class="card shadow-sm p-4 bg-white" style="max-width: 600px;">
        <form method="POST" enctype="multipart/form-data">
            <div class="mb-3">
                <label class="form-label"><b>选择文件 (支持任意 Excel / CSV)</b></label>
                <input type="file" name="excel_file" class="form-control" accept=".csv, .xlsx, .xls" required>
            </div>
            <div class="alert alert-info small mb-3">
                💡 系统会自动匹配列名：<br>
                • <b>Doc No / Invoice</b> 自动识别为 Invoice 编号<br>
                • <b>Debtor Name / Customer</b> 自动识别为客户名称<br>
                • 若无日期列，将自动填充当前系统日期 ({{ today_str }})
            </div>
            <button type="submit" class="btn btn-success w-100">🚀 开始自动解析并导入</button>
        </form>
    </div>
    <div class="mt-3"><a href="/invoices" class="btn btn-secondary">⬅️ 返回 Invoice 列表</a></div>
    ''')
    return render_template_string(html, msg=msg, error_msg=error_msg, today_str=today_str)

# --- Packing List 智能导入与管理 ---
@app.route('/packing')
def packing():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    today_str = date.today().strftime('%Y-%m-%d')
    date_filter = request.args.get('date', '')
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    query = "SELECT id, tracking_no, cargo_name, driver, inv_no, pl_date FROM packing_lists WHERE 1=1"
    params = []
    if date_filter:
        query += " AND pl_date = ?"
        params.append(date_filter)
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    pl_list = cursor.fetchall()
    conn.close()
    
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>📋 Packing List 管理中心</h2>
    <hr>
    <form method="GET" class="row g-3 mb-4 bg-white p-3 shadow-sm rounded">
        <div class="col-md-6"><label class="form-label"><b>按 Packing List 日期筛选</b></label><input type="date" name="date" class="form-control" value="''' + date_filter + '''"></div>
        <div class="col-md-6 d-flex align-items-end"><button type="submit" class="btn btn-primary w-100 me-2">🔍 查找</button><a href="/packing" class="btn btn-secondary w-100">📅 显示全部</a></div>
    </form>
    <div class="mb-3 d-flex justify-content-between">
        <div><a href="/packing_add_page" class="btn btn-primary me-2">➕ 手动创建 Packing List</a></div>
        <a href="/import_packing_page" class="btn btn-success">📥 智能导入 Packing List (Excel)</a>
    </div>
    <table class="table table-bordered bg-white shadow-sm align-middle">
        <thead class="table-dark">
            <tr><th>日期</th><th>运单号 (Tracking No)</th><th>货物名称</th><th>司机名</th><th>关联 Invoice</th><th>操作</th></tr>
        </thead>
        <tbody>
            {% for row in pl_list %}
            <tr>
                <td>{{ row[5] }}</td><td><b>{{ row[1] }}</b></td><td>{{ row[2] }}</td>
                <td><span class="badge bg-primary fs-6">{{ row[3] }}</span></td>
                <td><b>{{ row[4] }}</b></td>
                <td>
                    <a href="/packing_edit_page/{{ row[0] }}" class="btn btn-sm btn-outline-primary me-1">编辑</a>
                    <a href="/delete_packing/{{ row[0] }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('确定删除吗？')">删除</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    ''')
    return render_template_string(html, pl_list=pl_list, date_filter=date_filter)

@app.route('/import_packing_page', methods=['GET', 'POST'])
def import_packing_page():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    msg, error_msg = "", ""
    today_str = date.today().strftime('%Y-%m-%d')
    if request.method == 'POST':
        if 'pl_file' in request.files and request.files['pl_file'].filename != '':
            file = request.files['pl_file']
            pl_date = request.form.get('pl_date', today_str)
            try:
                file_bytes = file.read()
                filename_lower = file.filename.lower()
                
                # keep_default_na=False 保证 NAN 和 NA 不会被 Pandas 转为 NaN
                if filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls'):
                    df = pd.read_excel(io.BytesIO(file_bytes), keep_default_na=False)
                else:
                    df = pd.read_csv(io.BytesIO(file_bytes), keep_default_na=False)

                if df is None or len(df.columns) == 0: raise ValueError("文件格式无法读取！")
                df.columns = df.columns.astype(str).str.strip()

                # 智能字段映射 (doc, no -> tracking_no, Transfer To -> inv_no)
                track_col, inv_col, driver_col, cargo_col = None, None, None, None
                for col in df.columns:
                    c_lower = col.lower().replace('.', '').replace('_', ' ').strip()
                    if not track_col and any(k in c_lower for k in ['doc no', 'doc, no', 'tracking', 'order no', '运单']):
                        track_col = col
                    elif not inv_col and any(k in c_lower for k in ['transfer to', 'invoice', 'inv', 'doc no']):
                        if col != track_col: inv_col = col
                    elif not driver_col and any(k in c_lower for k in ['driver', '司机', 'driver name']):
                        driver_col = col
                    elif not cargo_col and any(k in c_lower for k in ['cargo', 'description', '货物']):
                        cargo_col = col

                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                imported_count = 0

                for _, row in df.iterrows():
                    tracking_no = clean_val(row.get(track_col))
                    if not tracking_no: continue

                    linked_inv = clean_val(row.get(inv_col), '无关联Invoice')
                    driver_name = clean_val(row.get(driver_col), '未指定司机') # 准确支持 NAN 和 NA
                    cargo_name = clean_val(row.get(cargo_col), 'General Cargo')

                    cursor.execute("""
                        INSERT INTO packing_lists (tracking_no, cargo_name, driver, inv_no, pl_date) 
                        VALUES (?, ?, ?, ?, ?)
                    """, (tracking_no, cargo_name, driver_name, linked_inv, pl_date))

                    # 自动把同名 Invoice 的司机进行绑定更新
                    if linked_inv and linked_inv != '无关联Invoice':
                        for inv in linked_inv.split(','):
                            clean_i = inv.strip()
                            if clean_i:
                                cursor.execute("UPDATE invoices SET assigned_driver=? WHERE inv_no=?", (driver_name, clean_i))

                    imported_count += 1

                conn.commit()
                conn.close()
                msg = f"成功智能导入 {imported_count} 条 Packing List 记录！自动识别驱动与 Invoice 联动完毕。"
            except Exception as e: error_msg = f"解析导入失败: {str(e)}"
            
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>📥 智能导入 Packing List (任意 Excel)</h2>
    <hr>
    {% if msg %}<div class="alert alert-success">{{ msg }}</div>{% endif %}
    {% if error_msg %}<div class="alert alert-danger">{{ error_msg }}</div>{% endif %}
    <div class="card shadow-sm p-4 bg-white" style="max-width: 650px;">
        <form method="POST" enctype="multipart/form-data">
            <div class="mb-3"><label class="form-label"><b>选择 Packing List 文件 (Excel / CSV)</b></label><input type="file" name="pl_file" class="form-control" accept=".csv, .xlsx, .xls" required></div>
            <div class="mb-3"><label class="form-label"><b>Packing List 日期</b></label><input type="date" name="pl_date" class="form-control" value="''' + today_str + '''" required></div>
            <div class="alert alert-info small mb-3">
                💡 <b>智能识别规则：</b><br>
                • <b>doc, no / doc. no</b> 自动识别为运单号<br>
                • <b>Transfer To</b> 自动识别为关联 Invoice<br>
                • <b>Driver</b> 自动识别司机姓名 (支持 NAN、NA 司机名识别)
            </div>
            <div class="d-flex justify-content-between">
                <a href="/packing" class="btn btn-secondary">返回列表</a>
                <button type="submit" class="btn btn-success">🚀 智能读取并导入</button>
            </div>
        </form>
    </div>
    ''')
    return render_template_string(html, msg=msg, error_msg=error_msg, today_str=today_str)

@app.route('/packing_add_page', methods=['GET', 'POST'])
def packing_add_page():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        tracking_no = request.form['tracking_no']
        cargo_name = request.form['cargo_name']
        driver = request.form['driver']
        pl_date = request.form['pl_date']
        selected_invoices = request.form.getlist('selected_invoices')
        inv_str = ", ".join(selected_invoices) if selected_invoices else "无关联Invoice"
        
        cursor.execute("INSERT INTO packing_lists (tracking_no, cargo_name, driver, inv_no, pl_date) VALUES (?, ?, ?, ?, ?)", (tracking_no, cargo_name, driver, inv_str, pl_date))
        
        if selected_invoices:
            for inv_no in selected_invoices:
                cursor.execute("UPDATE invoices SET assigned_driver=? WHERE inv_no=?", (driver, inv_no))
                
        conn.commit()
        conn.close()
        return redirect(url_for('packing'))
        
    cursor.execute("SELECT username FROM users WHERE role='driver'")
    drivers = cursor.fetchall()
    
    # 获取已经打包过的所有 Invoice 集合
    cursor.execute("SELECT inv_no FROM packing_lists")
    pl_rows = cursor.fetchall()
    packed_inv_nos = set()
    for row in pl_rows:
        if row[0]:
            for inv in row[0].split(','):
                clean_i = inv.strip()
                if clean_i and clean_i != '无关联Invoice':
                    packed_inv_nos.add(clean_i)

    # 查出未 POST 的账单
    cursor.execute("SELECT id, inv_no, customer, status FROM invoices WHERE status != '已POST'")
    raw_invoices = cursor.fetchall()
    
    # 彻底实现：已打包的 Invoice 不在选择列表中显示（未送达需要重新打包的除外）
    invoices = []
    for inv in raw_invoices:
        inv_number = inv[1].strip()
        is_packed = inv_number in packed_inv_nos
        is_undelivery = inv[3] in ['Undelivery', '未送达']
        
        if not is_packed or is_undelivery:
            invoices.append(inv)

    conn.close()
    today_str = date.today().strftime('%Y-%m-%d')
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>➕ 手动创建 Packing List</h2>
    <hr>
    <div class="card shadow-sm p-4 bg-white" style="max-width: 800px;">
        <form method="POST">
            <div class="mb-3"><label class="form-label"><b>Packing List 日期</b></label><input type="date" name="pl_date" class="form-control" value="''' + today_str + '''" required></div>
            <div class="mb-3"><label class="form-label">运单号 (Tracking No)</label><input type="text" name="tracking_no" class="form-control" placeholder="例如: LOG-003" required></div>
            <div class="mb-3"><label class="form-label">货物名称 (Cargo Name)</label><input type="text" name="cargo_name" class="form-control" placeholder="例如: General Cargo" required></div>
            <div class="mb-3">
                <label class="form-label">执行运送的司机 (Driver)</label>
                <select name="driver" class="form-select" required>
                    <option value="">-- 请选择司机 --</option>
                    {% for d in drivers %}<option value="{{ d[0] }}">{{ d[0] }}</option>{% endfor %}
                </select>
            </div>
            <div class="mb-4">
                <label class="form-label"><b>勾选要绑定的 Invoice (已打包的 Invoice 已被智能隐藏)</b></label>
                <div class="border p-3 rounded bg-light" style="max-height: 220px; overflow-y: auto;">
                    {% if not invoices %}
                        <p class="text-muted mb-0">暂无未打包的 Invoice 供勾选。</p>
                    {% endif %}
                    {% for inv in invoices %}
                    <div class="form-check mb-1">
                        <input class="form-check-input" type="checkbox" name="selected_invoices" value="{{ inv[1] }}" id="inv_{{ inv[0] }}">
                        <label class="form-check-label" for="inv_{{ inv[0] }}">
                            <b>{{ inv[1] }}</b> (客户: {{ inv[2] }})
                            {% if inv[3] == 'Undelivery' %}<span class="badge bg-danger ms-2">❌ 未送达 (重新打包)</span>{% endif %}
                        </label>
                    </div>
                    {% endfor %}
                </div>
            </div>
            <div class="d-flex justify-content-between">
                <a href="/packing" class="btn btn-secondary">返回列表</a>
                <button type="submit" class="btn btn-primary">保存创建 Packing List</button>
            </div>
        </form>
    </div>
    ''')
    return render_template_string(html, drivers=drivers, invoices=invoices, today_str=today_str)

@app.route('/packing_edit_page/<int:pl_id>', methods=['GET', 'POST'])
def packing_edit_page(pl_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        tracking_no = request.form['tracking_no']
        cargo_name = request.form['cargo_name']
        driver = request.form['driver']
        pl_date = request.form['pl_date']
        selected_invoices = request.form.getlist('selected_invoices')
        inv_str = ", ".join(selected_invoices) if selected_invoices else "无关联Invoice"
        
        cursor.execute("UPDATE packing_lists SET tracking_no=?, cargo_name=?, driver=?, inv_no=?, pl_date=? WHERE id=?", (tracking_no, cargo_name, driver, inv_str, pl_date, pl_id))
        if selected_invoices:
            for inv_no in selected_invoices:
                cursor.execute("UPDATE invoices SET assigned_driver=? WHERE inv_no=?", (driver, inv_no))
        conn.commit()
        conn.close()
        return redirect(url_for('packing'))
        
    cursor.execute("SELECT id, tracking_no, cargo_name, driver, inv_no, pl_date FROM packing_lists WHERE id=?", (pl_id,))
    pl = cursor.fetchone()
    
    cursor.execute("SELECT username FROM users WHERE role='driver'")
    drivers = cursor.fetchall()
    
    current_invs = [i.strip() for i in pl[4].split(',')] if pl[4] else []
    
    cursor.execute("SELECT inv_no FROM packing_lists WHERE id != ?", (pl_id,))
    other_pl_rows = cursor.fetchall()
    other_packed_inv_nos = set()
    for row in other_pl_rows:
        if row[0]:
            for inv in row[0].split(','):
                clean_i = inv.strip()
                if clean_i and clean_i != '无关联Invoice':
                    other_packed_inv_nos.add(clean_i)

    cursor.execute("SELECT id, inv_no, customer, status FROM invoices WHERE status != '已POST'")
    raw_invoices = cursor.fetchall()
    
    invoices = []
    for inv in raw_invoices:
        inv_number = inv[1].strip()
        is_in_current = inv_number in current_invs
        is_other_packed = inv_number in other_packed_inv_nos
        is_undelivery = inv[3] in ['Undelivery', '未送达']
        if is_in_current or not is_other_packed or is_undelivery:
            invoices.append(inv)

    conn.close()
    
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>✏️ 修改 Packing List</h2>
    <hr>
    <div class="card shadow-sm p-4 bg-white" style="max-width: 800px;">
        <form method="POST">
            <div class="mb-3"><label class="form-label"><b>Packing List 日期</b></label><input type="date" name="pl_date" class="form-control" value="'''+str(pl[5])+'''" required></div>
            <div class="mb-3"><label class="form-label">运单号 (Tracking No)</label><input type="text" name="tracking_no" class="form-control" value="'''+pl[1]+'''" required></div>
            <div class="mb-3"><label class="form-label">货物名称 (Cargo Name)</label><input type="text" name="cargo_name" class="form-control" value="'''+pl[2]+'''" required></div>
            <div class="mb-3">
                <label class="form-label">运送司机 (Driver)</label>
                <select name="driver" class="form-select" required>
                    {% for d in drivers %}<option value="{{ d[0] }}" {% if d[0] == pl[3] %}selected{% endif %}>{{ d[0] }}</option>{% endfor %}
                </select>
            </div>
            <div class="mb-4">
                <label class="form-label"><b>勾选/修改绑定的 Invoice</b></label>
                <div class="border p-3 rounded bg-light" style="max-height: 220px; overflow-y: auto;">
                    {% for inv in invoices %}
                    <div class="form-check mb-1">
                        <input class="form-check-input" type="checkbox" name="selected_invoices" value="{{ inv[1] }}" id="inv_{{ inv[0] }}" {% if inv[1] in current_invs %}checked{% endif %}>
                        <label class="form-check-label" for="inv_{{ inv[0] }}"><b>{{ inv[1] }}</b> (客户: {{ inv[2] }})</label>
                    </div>
                    {% endfor %}
                </div>
            </div>
            <div class="d-flex justify-content-between">
                <a href="/packing" class="btn btn-secondary">返回列表</a>
                <button type="submit" class="btn btn-primary">保存修改</button>
            </div>
        </form>
    </div>
    ''')
    return render_template_string(html, pl=pl, drivers=drivers, invoices=invoices, current_invs=current_invs)

@app.route('/delete_packing/<int:pl_id>')
def delete_packing(pl_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM packing_lists WHERE id=?", (pl_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('packing'))

# --- Check Invoice 模块 (添加日期显示) ---
@app.route('/check_invoices', methods=['GET', 'POST'])
def check_invoices():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        selected = request.form.getlist('selected_inv')
        if selected:
            current_date = date.today().strftime('%Y-%m-%d')
            current_admin = session.get('user', 'admin')
            for i in selected:
                cursor.execute("UPDATE invoices SET status='已POST', posted_date=?, posted_by=? WHERE id=?", (current_date, current_admin, i))
            conn.commit()

    cursor.execute("SELECT inv_no FROM packing_lists")
    pl_rows = cursor.fetchall()
    valid_inv_nos = set()
    for row in pl_rows:
        if row[0]:
            for inv in row[0].split(','):
                clean_i = inv.strip()
                if clean_i and clean_i != '无关联Invoice': valid_inv_nos.add(clean_i)

    date_filter = request.args.get('date', '')
    driver_filter = request.args.get('driver', '')
    
    query = "SELECT id, inv_no, tracking_no, customer, amount, delivery_date, assigned_driver, status, check_in_time, undelivery_reason, redelivery_count FROM invoices WHERE status != '已POST'"
    params = []
    if date_filter:
        query += " AND delivery_date = ?"
        params.append(date_filter)
    if driver_filter:
        query += " AND assigned_driver LIKE ?"
        params.append(f"%{driver_filter}%")
        
    cursor.execute(query, params)
    all_unposted = cursor.fetchall()
    conn.close()
    
    check_list = [row for row in all_unposted if row[1].strip() in valid_inv_nos]

    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>✅ Check Invoice 与 Post Stock 审核</h2>
    <hr>
    <form method="GET" class="row g-3 mb-4 bg-white p-3 shadow-sm rounded">
        <div class="col-md-4"><label class="form-label">按送货日期筛选</label><input type="date" name="date" class="form-control" value="'''+date_filter+'''"></div>
        <div class="col-md-4"><label class="form-label">按运送司机筛选</label><input type="text" name="driver" class="form-control" placeholder="输入司机姓名" value="'''+driver_filter+'''"></div>
        <div class="col-md-4 d-flex align-items-end"><button type="submit" class="btn btn-primary w-100 me-2">🔍 筛选</button><a href="/check_invoices" class="btn btn-secondary w-100">🔄 重置</a></div>
    </form>
    
    <form method="POST">
        <div class="mb-3"><button type="submit" class="btn btn-danger">📦 勾选并执行 Post Stock (归档)</button></div>
        <table class="table table-hover bg-white shadow-sm rounded align-middle">
            <thead class="table-dark">
                <tr><th width="40"><input type="checkbox" onclick="selectAll(this)"></th><th>Invoice 编号</th><th>日期</th><th>运单号</th><th>客户名称</th><th>司机</th><th>金额 (RM)</th><th>打卡状态 / 原因</th><th>补送状态</th><th>操作</th></tr>
            </thead>
            <tbody>
                {% for row in check_list %}
                <tr>
                    <td><input type="checkbox" name="selected_inv" value="{{ row[0] }}"></td>
                    <td><b>{{ row[1] }}</b></td>
                    <td><small class="text-muted">{{ row[5] or '-' }}</small></td>
                    <td>{{ row[2] }}</td><td>{{ row[3] }}</td>
                    <td><span class="badge bg-info text-dark">{{ row[6] or '未分配' }}</span></td>
                    <td>{{ row[4] }}</td>
                    <td>
                        {% if row[7] == '已打卡' %}<span class="badge bg-success">✅ 已打卡 ({{ row[8] }})</span>
                        {% elif row[7] == 'Undelivery' %}<span class="badge bg-danger">❌ 未送达</span><br><small class="text-danger">{{ row[9] or '' }}</small>
                        {% else %}<span class="badge bg-secondary">⏳ 待司机打卡</span>{% endif %}
                    </td>
                    <td>
                        {% if row[10] and row[10] > 0 %}<span class="badge bg-warning text-dark">补送 {{ row[10] }} 次</span>
                        {% else %}<span class="text-muted small">正常</span>{% endif %}
                    </td>
                    <td>
                        <button type="button" class="btn btn-sm btn-outline-warning text-dark border" data-bs-toggle="modal" data-bs-target="#redeliveryModal_{{ row[0] }}">🔄 补送</button>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </form>

    {% for row in check_list %}
    <div class="modal fade" id="redeliveryModal_{{ row[0] }}" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <form method="POST" action="/redeliver_invoice/{{ row[0] }}">
                    <div class="modal-header bg-warning text-dark">
                        <h5 class="modal-title">🔄 确认安排补送: {{ row[1] }}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3"><label class="form-label"><b>客户名称</b></label><input type="text" class="form-control" value="{{ row[3] }}" disabled></div>
                        <div class="mb-3"><label class="form-label"><b>填写补送原因说明</b></label><textarea name="redelivery_reason" class="form-control" rows="3" required></textarea></div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                        <button type="submit" class="btn btn-warning">提交补送并重置状态</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    {% endfor %}
    <script>function selectAll(source){checkboxes=document.getElementsByName('selected_inv');for(let cb of checkboxes)cb.checked=source.checked;}</script>
    ''')
    return render_template_string(html, check_list=check_list)

@app.route('/redeliver_invoice/<int:inv_id>', methods=['POST'])
def redeliver_invoice(inv_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    redelivery_reason = request.form.get('redelivery_reason', '管理员申请重新派送').strip()
    operator = session.get('user', 'admin')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT inv_no, tracking_no, customer, assigned_driver, redelivery_count FROM invoices WHERE id=?", (inv_id,))
    inv_data = cursor.fetchone()
    
    if inv_data:
        inv_no, tracking_no, customer, driver, current_count = inv_data
        new_count = (current_count or 0) + 1
        cursor.execute("INSERT INTO redelivery_logs (inv_no, tracking_no, customer, original_driver, redelivery_time, operator, reason) VALUES (?, ?, ?, ?, ?, ?, ?)", (inv_no, tracking_no, customer, driver, timestamp, operator, redelivery_reason))
        cursor.execute("UPDATE invoices SET status='未送达', check_in_time=NULL, undelivery_reason=NULL, pod_remark=NULL, redelivery_count=? WHERE id=?", (new_count, inv_id))
        conn.commit()
    conn.close()
    return redirect(url_for('check_invoices'))

# --- Invoice Done 归档中心 (新增搜索 Invoice 与月份筛选) ---
@app.route('/invoices_done', methods=['GET', 'POST'])
def invoices_done():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        selected = request.form.getlist('selected_inv')
        if selected:
            for i in selected:
                cursor.execute("UPDATE invoices SET status='已打卡', posted_date=NULL, posted_by=NULL WHERE id=?", (i,))
            conn.commit()

    date_filter = request.args.get('date', '')
    month_filter = request.args.get('month', '')
    inv_filter = request.args.get('inv', '')
    
    query = "SELECT id, inv_no, tracking_no, customer, amount, delivery_date, posted_date, posted_by FROM invoices WHERE status='已POST'"
    params = []
    
    if date_filter:
        query += " AND delivery_date = ?"
        params.append(date_filter)
    if month_filter:
        query += " AND strftime('%Y-%m', delivery_date) = ?"
        params.append(month_filter)
    if inv_filter:
        query += " AND inv_no LIKE ?"
        params.append(f"%{inv_filter}%")
        
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    done_list = cursor.fetchall()
    conn.close()
    
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>📁 Invoice Done (已 Post 归档历史)</h2>
    <hr>
    <!-- 增加按 Invoice 搜索与按月份筛选表单 -->
    <form method="GET" class="row g-3 mb-4 bg-white p-3 shadow-sm rounded">
        <div class="col-md-3">
            <label class="form-label">🔍 搜索 Invoice 编号</label>
            <input type="text" name="inv" class="form-control" placeholder="输入 INV 编号" value="'''+inv_filter+'''">
        </div>
        <div class="col-md-3">
            <label class="form-label">🗓️ 按月份筛选</label>
            <input type="month" name="month" class="form-control" value="'''+month_filter+'''">
        </div>
        <div class="col-md-3">
            <label class="form-label">📅 按精准日期筛选</label>
            <input type="date" name="date" class="form-control" value="'''+date_filter+'''">
        </div>
        <div class="col-md-3 d-flex align-items-end">
            <button type="submit" class="btn btn-primary w-100 me-2">🔍 筛选</button>
            <a href="/invoices_done" class="btn btn-secondary w-100">🔄 重置</a>
        </div>
    </form>
    
    <form method="POST">
        <div class="mb-3">
            <button type="submit" class="btn btn-outline-warning text-dark bg-white border" onclick="return confirm('确定要 Unpost 选中账单吗？')">🔄 批量 Unpost 选中账单</button>
        </div>
        <table class="table table-striped bg-white shadow-sm rounded align-middle">
            <thead class="table-secondary">
                <tr>
                    <th width="40"><input type="checkbox" onclick="selectAll(this)"></th>
                    <th>Invoice 编号</th><th>运单号</th><th>客户名称</th><th>金额 (RM)</th><th>送货日期</th><th>Post 日期</th><th>Post 账号</th><th>状态</th><th>操作</th>
                </tr>
            </thead>
            <tbody>
                {% for row in done_list %}
                <tr>
                    <td><input type="checkbox" name="selected_inv" value="{{ row[0] }}"></td>
                    <td><b>{{ row[1] }}</b></td><td>{{ row[2] }}</td><td>{{ row[3] }}</td><td>{{ row[4] }}</td>
                    <td>{{ row[5] }}</td><td><span class="text-primary">{{ row[6] or '-' }}</span></td>
                    <td><span class="badge bg-dark">{{ row[7] or '系统管理员' }}</span></td>
                    <td><span class="badge bg-success">已POST归档</span></td>
                    <td><a href="/unpost_invoice/{{ row[0] }}" class="btn btn-sm btn-outline-warning" onclick="return confirm('确定要 Unpost 吗？')">🔄 Unpost</a></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </form>
    <script>function selectAll(source){checkboxes=document.getElementsByName('selected_inv');for(let cb of checkboxes)cb.checked=source.checked;}</script>
    ''')
    return render_template_string(html, done_list=done_list)

@app.route('/unpost_invoice/<int:inv_id>')
def unpost_invoice(inv_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE invoices SET status='已打卡', posted_date=NULL, posted_by=NULL WHERE id=?", (inv_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('invoices_done'))

@app.route('/delete_invoice/<int:inv_id>')
def delete_invoice(inv_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM invoices WHERE id=?", (inv_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('invoices'))

# --- 补送历史与账号管理模块 ---
@app.route('/redelivery_history')
def redelivery_history():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    inv_filter = request.args.get('inv', '')
    query = "SELECT id, inv_no, tracking_no, customer, original_driver, redelivery_time, operator, reason FROM redelivery_logs WHERE 1=1"
    params = []
    if inv_filter:
        query += " AND inv_no LIKE ?"
        params.append(f"%{inv_filter}%")
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    logs = cursor.fetchall()
    conn.close()
    
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>🔄 补送历史记录 (Redelivery Logs)</h2>
    <hr>
    <form method="GET" class="row g-3 mb-4 bg-white p-3 shadow-sm rounded">
        <div class="col-md-6"><label class="form-label">按 Invoice 编号查询补送记录</label><input type="text" name="inv" class="form-control" placeholder="输入 Invoice 编号" value="'''+inv_filter+'''"></div>
        <div class="col-md-6 d-flex align-items-end"><button type="submit" class="btn btn-primary w-100 me-2">🔍 查找</button><a href="/redelivery_history" class="btn btn-secondary w-100">🔄 重置</a></div>
    </form>
    <table class="table table-hover bg-white shadow-sm rounded align-middle">
        <thead class="table-dark">
            <tr><th>序号ID</th><th>Invoice 编号</th><th>运单号</th><th>客户名称</th><th>原指派司机</th><th>补送时间</th><th>操作员</th><th>补送原因说明</th></tr>
        </thead>
        <tbody>
            {% for log in logs %}
            <tr>
                <td>{{ log[0] }}</td><td><b>{{ log[1] }}</b></td><td>{{ log[2] }}</td><td>{{ log[3] }}</td>
                <td><span class="badge bg-info text-dark">{{ log[4] or '无' }}</span></td>
                <td>{{ log[5] }}</td><td><span class="badge bg-dark">{{ log[6] }}</span></td>
                <td><span class="text-danger">{{ log[7] }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    ''')
    return render_template_string(html, logs=logs)

@app.route('/drivers_manage', methods=['GET', 'POST'])
def drivers_manage():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    msg, error_msg = "", ""
    if request.method == 'POST':
        new_driver = request.form.get('username', '').strip()
        new_pass = request.form.get('password', '').strip()
        if new_driver and new_pass:
            try:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'driver')", (new_driver, new_pass))
                conn.commit()
                conn.close()
                msg = f"成功添加司机: {new_driver}"
            except Exception as e: error_msg = f"添加失败: {str(e)}"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE role='driver'")
    driver_list = cursor.fetchall()
    conn.close()
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>👥 司机账号与权限管理</h2>
    <hr>
    {% if msg %}<div class="alert alert-success">{{ msg }}</div>{% endif %}
    {% if error_msg %}<div class="alert alert-danger">{{ error_msg }}</div>{% endif %}
    <div class="row">
        <div class="col-md-5 mb-4">
            <div class="card shadow-sm p-4 bg-white">
                <h4 class="text-success mb-3">➕ 添加新司机账号</h4>
                <form method="POST">
                    <div class="mb-3"><label class="form-label">司机姓名 / 用户名</label><input type="text" name="username" class="form-control" placeholder="例如: BALA" required></div>
                    <div class="mb-3"><label class="form-label">登录密码</label><input type="text" name="password" class="form-control" placeholder="例如: 123" required></div>
                    <button type="submit" class="btn btn-success w-100">确认添加司机</button>
                </form>
            </div>
        </div>
        <div class="col-md-7">
            <div class="card shadow-sm p-4 bg-white">
                <h4 class="mb-3">📋 现有车队司机列表</h4>
                <table class="table table-hover">
                    <thead class="table-dark"><tr><th>司机姓名</th><th width="120">操作</th></tr></thead>
                    <tbody>
                        {% for d in driver_list %}
                        <tr><td><b>{{ d[1] }}</b></td><td><a href="/delete_user/{{ d[0] }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('确定删除该司机吗？')">删除</a></td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    ''')
    return render_template_string(html, driver_list=driver_list, msg=msg, error_msg=error_msg)

@app.route('/admins_manage', methods=['GET', 'POST'])
def admins_manage():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    msg, error_msg = "", ""
    if request.method == 'POST':
        new_admin = request.form.get('username', '').strip()
        new_pass = request.form.get('password', '').strip()
        if new_admin and new_pass:
            try:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'admin')", (new_admin, new_pass))
                conn.commit()
                conn.close()
                msg = f"成功添加管理员: {new_admin}"
            except Exception as e: error_msg = f"添加失败: {str(e)}"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE role='admin'")
    admin_list = cursor.fetchall()
    conn.close()
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>🛡️ 管理员账号管理</h2>
    <hr>
    {% if msg %}<div class="alert alert-success">{{ msg }}</div>{% endif %}
    {% if error_msg %}<div class="alert alert-danger">{{ error_msg }}</div>{% endif %}
    <div class="row">
        <div class="col-md-5 mb-4">
            <div class="card shadow-sm p-4 bg-white">
                <h4 class="text-primary mb-3">➕ 添加新管理员</h4>
                <form method="POST">
                    <div class="mb-3"><label class="form-label">管理员账号</label><input type="text" name="username" class="form-control" required></div>
                    <div class="mb-3"><label class="form-label">密码</label><input type="text" name="password" class="form-control" required></div>
                    <button type="submit" class="btn btn-primary w-100">确认添加管理员</button>
                </form>
            </div>
        </div>
        <div class="col-md-7">
            <div class="card shadow-sm p-4 bg-white">
                <h4 class="mb-3">📋 管理员列表</h4>
                <table class="table table-hover">
                    <thead class="table-secondary"><tr><th>管理员账号</th><th width="120">操作</th></tr></thead>
                    <tbody>
                        {% for a in admin_list %}
                        <tr>
                            <td><b>{{ a[1] }}</b></td>
                            <td>{% if a[1] != 'admin' %}<a href="/delete_user/{{ a[0] }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('确定删除吗？')">删除</a>{% else %}<span class="text-muted small">超级管理员</span>{% endif %}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    ''')
    return render_template_string(html, admin_list=admin_list, msg=msg, error_msg=error_msg)

@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username, role FROM users WHERE id=?", (user_id,))
    target = cursor.fetchone()
    if target and target[0] != 'admin':
        cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    conn.close()
    if target and target[1] == 'admin': return redirect(url_for('admins_manage'))
    return redirect(url_for('drivers_manage'))

# --- 司机打卡端 ---
@app.route('/driver_portal')
def driver_portal():
    if session.get('role') != 'driver': return redirect(url_for('index'))
    driver_name = session['user'].strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT inv_no FROM packing_lists")
    pl_rows = cursor.fetchall()
    valid_inv_nos = set()
    for row in pl_rows:
        if row[0]:
            for inv in row[0].split(','):
                clean_i = inv.strip()
                if clean_i and clean_i != '无关联Invoice': valid_inv_nos.add(clean_i)
                    
    cursor.execute("""
        SELECT id, inv_no, tracking_no, customer, amount, status, delivery_date, check_in_time, pod_remark, undelivery_reason 
        FROM invoices 
        WHERE LOWER(TRIM(assigned_driver)) = LOWER(?) 
        AND status != '已POST'
    """, (driver_name,))
    all_driver_invoices = cursor.fetchall()
    conn.close()
    
    invoice_details = [inv for inv in all_driver_invoices if inv[1].strip() in valid_inv_nos]
    
    html = TEMPLATE.replace('{% block content %}{% endblock %}', '''
    <h2>📱 司机专属打卡系统</h2>
    <hr>
    <p class="text-muted">欢迎，司机 <b>{{ session.get('user') }}</b>！以下是管理员安排的送货任务：</p>
    {% if not invoice_details %}<div class="alert alert-warning">目前暂无指派给您的 Packing List 任务。</div>{% endif %}

    <div class="row">
        {% for inv in invoice_details %}
        <div class="col-md-12 mb-3">
            <div class="card border-{% if inv[5] == '已打卡' %}success{% elif inv[5] == 'Undelivery' %}danger{% else %}warning{% endif %} shadow-sm">
                <div class="card-body d-flex justify-content-between align-items-center">
                    <div>
                        <h5 class="card-title text-dark"><b>Invoice 编号: {{ inv[1] }}</b> <span class="badge bg-secondary small">运单: {{ inv[2] }}</span></h5>
                        <p class="card-text mb-1 small text-muted">客户名称: {{ inv[3] }} | 金额: RM {{ inv[4] }} | 日期: {{ inv[6] }}</p>
                        {% if inv[5] == '已打卡' %}<span class="badge bg-success">✅ 已打卡 (时间: {{ inv[7] or '记录正常' }})</span>
                        {% elif inv[5] == 'Undelivery' %}<span class="badge bg-danger">❌ 未送达</span><p class="small text-danger mt-1 mb-0">原因: {{ inv[9] or '无说明' }}</p>
                        {% else %}<span class="badge bg-warning text-dark">⏳ 待打卡</span>{% endif %}
                    </div>
                    <div>
                        <button class="btn {% if inv[5] == 'Undelivery' %}btn-outline-danger{% else %}btn-success{% endif %} btn-sm" data-bs-toggle="modal" data-bs-target="#checkInModal_{{ inv[0] }}">
                            {% if inv[5] == 'Undelivery' or inv[5] == '已打卡' %}修改打卡状态{% else %}📷 独立打卡{% endif %}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div class="modal fade" id="checkInModal_{{ inv[0] }}" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <form method="POST" action="/submit_invoice_checkin/{{ inv[0] }}">
                        <div class="modal-header bg-dark text-white">
                            <h5 class="modal-title">📌 打卡确认: {{ inv[1] }}</h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="mb-3"><label class="form-label"><b>客户名称</b></label><input type="text" class="form-control" value="{{ inv[3] }}" disabled></div>
                            <div class="mb-3">
                                <label class="form-label"><b>打卡结果</b></label>
                                <select name="checkin_type" id="checkin_type_{{ inv[0] }}" class="form-select" onchange="toggleUndelivery({{ inv[0] }})" required>
                                    <option value="normal" {% if inv[5] != 'Undelivery' %}selected{% endif %}>✅ 正常送达 (Delivered)</option>
                                    <option value="undelivery" {% if inv[5] == 'Undelivery' %}selected{% endif %}>❌ 未送达 (Undelivery)</option>
                                </select>
                            </div>
                            <div id="normal_section_{{ inv[0] }}">
                                <div class="mb-3"><label class="form-label">送货备注</label><textarea name="pod_remark" class="form-control" rows="2">{{ inv[8] or '' }}</textarea></div>
                            </div>
                            <div id="undelivery_section_{{ inv[0] }}" style="display: none;">
                                <div class="mb-3">
                                    <label class="form-label text-danger"><b>未送达原因说明</b></label>
                                    <textarea name="undelivery_reason" class="form-control" rows="2">{{ inv[9] or '' }}</textarea>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                            <button type="submit" class="btn btn-primary">✅ 提交打卡结果</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
        <script>
        function toggleUndelivery(id) {
            var selectVal = document.getElementById('checkin_type_' + id).value;
            document.getElementById('normal_section_' + id).style.display = (selectVal === 'undelivery') ? 'none' : 'block';
            document.getElementById('undelivery_section_' + id).style.display = (selectVal === 'undelivery') ? 'block' : 'none';
        }
        window.addEventListener('DOMContentLoaded', () => { toggleUndelivery({{ inv[0] }}); });
        </script>
        {% endfor %}
    </div>
    ''')
    return render_template_string(html, invoice_details=invoice_details)

@app.route('/submit_invoice_checkin/<int:inv_id>', methods=['POST'])
def submit_invoice_checkin(inv_id):
    if session.get('role') != 'driver': return redirect(url_for('index'))
    checkin_type = request.form.get('checkin_type', 'normal')
    check_time = date.today().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if checkin_type == 'undelivery':
        undelivery_reason = request.form.get('undelivery_reason', '未说明原因').strip()
        cursor.execute("UPDATE invoices SET status='Undelivery', check_in_time=?, undelivery_reason=? WHERE id=?", (check_time, undelivery_reason, inv_id))
    else:
        pod_remark = request.form.get('pod_remark', '').strip()
        cursor.execute("UPDATE invoices SET status='已打卡', check_in_time=?, pod_remark=?, undelivery_reason=NULL WHERE id=?", (check_time, pod_remark, inv_id))
    conn.commit()
    conn.close()
    return redirect(url_for('driver_portal'))

if __name__ == '__main__':
    print("系统启动成功！请在浏览器打开: http://127.0.0.1:5000")
    app.run(host='0.0.0.0', debug=True, port=5000)