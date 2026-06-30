import sqlite3
import hashlib
import os
import json
import requests
import time
from functools import wraps
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, g, flash, get_flashed_messages, send_from_directory
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your-super-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DATABASE = 'project.db'

# -------------------- Database --------------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        c = db.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            can_view_progress INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            estimated_hours INTEGER NOT NULL,
            status INTEGER DEFAULT 0,
            order_index INTEGER,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS task_visibility (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            visible INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            UNIQUE(user_id, task_id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS gallery_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            image_filename TEXT NOT NULL,
            description TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS public_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        db.commit()

        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                  ('api_key', '010fc89b-8f88-4d84-8e3a-37cbb4d95fb9'))
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                  ('api_url', 'https://aki.io/openai/v1'))
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                  ('model', 'gpt-3.5-turbo'))

        c.execute("SELECT * FROM users WHERE username = 'H'")
        if not c.fetchone():
            c.execute("INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, ?)",
                      ('H', hashlib.sha256('2026'.encode()).hexdigest(), 'manager', 1))
            db.commit()

        c.execute("SELECT COUNT(*) FROM projects")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO projects (name, description, status) VALUES (?, ?, ?)",
                      ('مخزن ۲۰۰ مترمکعبی آب', 'پروژه ساخت مخزن بتنی ۲۰۰ مترمکعبی جهت ذخیره آب شرب', 'active'))
            project_id = c.lastrowid
            tasks_data = [
                ('مطالعات ژئوتکنیک و نمونه‌برداری خاک (GEO)', 24),
                ('آزمایشات مکانیک خاک (برش مستقیم، تحکیم، تراکم)', 24),
                ('طراحی اولیه سازه مخزن (SAP2000 و ETABS)', 40),
                ('تحلیل و طراحی جزئیات آرماتورگذاری', 32),
                ('تهیه نقشه‌های اجرایی و شیت‌بندی (AutoCAD)', 40),
                ('اخذ مجوزهای شهرداری و سازمان محیط زیست', 20),
                ('تهیه و خرید میلگرد AIII (سایزهای مختلف)', 20),
                ('تهیه سیمان پرتلند تیپ ۲ و سنگدانه‌ها (شن و ماسه)', 20),
                ('تهیه قالب‌های فلزی و چوبی (پانل‌های مدولار)', 16),
                ('تهیه لوله‌های فولادی و اتصالات (جوشی و فلنج)', 16),
                ('تهیه عایق رطوبتی (قیر، ایزوگام، نوار آب‌بند و درزگیر)', 16),
                ('تهیه پمپ، شیرآلات و تجهیزات مکانیکی (شناور و پیزومتر)', 16),
                ('نصب و برپایی کارگاه و انبارهای موقت', 32),
                ('پی‌کنی و گودبرداری با بیل مکانیکی (کوماتسو PC200)', 40),
                ('تسطیح و کوبیدن بستر با غلتک ویبره‌ای ۱۰ تنی', 24),
                ('اجرای لایه‌های شن و ماسه زیر فونداسیون (با تراکم)', 24),
                ('قالب‌بندی فونداسیون با قالب‌های فلزی (پانل‌های ۱×۲ متر)', 32),
                ('برش، خم و جوش آرماتورهای فونداسیون (دستگاه جوش برق)', 40),
                ('بتن‌ریزی فونداسیون با بتن C30 (تراک میکسر ۹ مترمکعب)', 40),
                ('عمل‌آوری بتن فونداسیون (مرطوب‌سازی با عایق و پلاستیک)', 24),
                ('قالب‌بندی دیواره‌های مخزن (ارتفاع ۵ متر، قالب‌های مدولار)', 48),
                ('آرماتوربندی دیواره‌ها (دو لایه، فاصله‌دهنده‌های پلاستیکی)', 64),
                ('بتن‌ریزی دیواره‌ها با پمپ بتن (شوتینگ و ویبره)', 48),
                ('ویبره زدن و تراکم بتن دیواره‌ها (ویبره داخلی با فرکانس بالا)', 16),
                ('قالب‌بندی سقف (دال بتنی با قالب‌های تیرچه و بلوک)', 32),
                ('آرماتوربندی سقف (میلگردهای حرارتی و اصلی با وصله)', 32),
                ('بتن‌ریزی سقف با بتن C25 (پمپ بتن)', 24),
                ('عمل‌آوری سقف و دیوارها (پوشش پلاستیکی و مرطوب‌سازی مداوم)', 32),
                ('باز کردن قالب‌ها پس از کسب مقاومت (۷ روزه)', 16),
                ('اجرای عایق رطوبتی دیواره‌ها (دو لایه قیرگونی با گونی و قیر مذاب)', 32),
                ('اجرای عایق رطوبتی کف (نوارهای آب‌بند و قیر مذاب با گونی)', 24),
                ('اجرای عایق رطوبتی سقف (ایزوگام با لایه محافظ و شن)', 24),
                ('نصب لوله‌های ورود و خروج آب (فلنج‌دار با جوشکاری آرگون)', 24),
                ('نصب شیرآلات و دریچه‌های دسترسی (شیر شناور و float valve)', 16),
                ('نصب سیستم هوادهی و تهویه (لوله‌های هواکش و کاپ گرد)', 12),
                ('نصب سیستم اندازه‌گیری سطح آب (لوله‌های پیزومتر و سنسور اولتراسونیک)', 12),
                ('تست اولیه آب‌بندی (پر کردن تدریجی تا ۵۰% و کنترل نشتی به مدت ۲۴ ساعت)', 40),
                ('تست نهایی آب‌بندی (پر کردن کامل تا لبه و کنترل نشتی به مدت ۷۲ ساعت)', 60),
                ('رفع نشتی‌های احتمالی (تزریق دوغاب سیمان با پمپ تزریق)', 24),
                ('اجرای پوشش محافظ داخلی (ملات ماسه سیمان با افزودنی آب‌بند و پلیمر)', 24),
                ('خاکریزی اطراف مخزن و کوبیدن با غلتک ویبره‌ای در لایه‌های ۲۰ سانتی', 32),
                ('کف‌سازی و محوطه‌سازی اطراف مخزن (شن‌ریزی، جدول‌گذاری و آسفالت)', 24),
                ('نصب نرده‌های محافظ و دسترسی (فنس و درب فلزی)', 16),
                ('رنگ‌آمیزی و پوشش نهایی سازه (ضد خوردگی و زیباسازی)', 16),
                ('نصب تابلوهای هشدار و اطلاعاتی (علائم ایمنی و مشخصات مخزن)', 8),
                ('آزمایش‌های کیفی بتن (مکعب‌های ۷ و ۲۸ روزه)', 16),
                ('تهیه مستندات اجرایی و نقشه‌های as-built', 24),
                ('آماده‌سازی برای تحویل به کارفرما (نظافت و رفع نواقص)', 16),
                ('جلسه تحویل نهایی با کارفرما و ارائه مستندات', 16),
                ('بستن قرارداد بهره‌برداری و انتقال دانش فنی', 16)
            ]
            total = sum(h for _, h in tasks_data)
            if total < 1440:
                diff = 1440 - total
                last_title, last_hours = tasks_data[-1]
                tasks_data[-1] = (last_title, last_hours + diff)
            for idx, (title, hours) in enumerate(tasks_data, start=1):
                c.execute("INSERT INTO tasks (project_id, title, estimated_hours, order_index) VALUES (?, ?, ?, ?)",
                          (project_id, title, hours, idx))
            db.commit()
init_db()

# -------------------- Helpers --------------------
def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if role:
                user = get_db().execute("SELECT role FROM users WHERE id = ?", (session['user_id'],)).fetchone()
                if not user or user['role'] != role:
                    return "Unauthorized", 403
            return f(*args, **kwargs)
        return decorated
    return decorator

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def call_ai_api(user_message, api_key, api_url, model):
    system_prompt = (
        ""
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7
    }
    try:
        response = requests.post(api_url + "/chat/completions", headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return None
    except Exception:
        return None

# -------------------- Routes --------------------
@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/login')
def login():
    return render_template_string(LOGIN_HTML)

@app.route('/login', methods=['POST'])
def do_login():
    username = request.form.get('username')
    password = request.form.get('password')
    if not username or not password:
        flash('لطفاً نام کاربری و رمز عبور را وارد کنید')
        return redirect(url_for('login'))
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user and user['password'] == hashlib.sha256(password.encode()).hexdigest() and user['is_active'] == 1:
        session['user_id'] = user['id']
        session['role'] = user['role']
        return redirect(url_for('manager_dashboard' if user['role'] == 'manager' else 'viewer_dashboard'))
    flash('نام کاربری یا رمز عبور اشتباه است')
    return redirect(url_for('login'))

@app.route('/manager-login')
def manager_login():
    return render_template_string(MANAGER_LOGIN_HTML)

@app.route('/manager-login', methods=['POST'])
def do_manager_login():
    username = request.form.get('username')
    password = request.form.get('password')
    if username == 'H' and password == '2026':
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = 'H' AND password = ?",
                          (hashlib.sha256('2026'.encode()).hexdigest(),)).fetchone()
        if user and user['is_active']:
            session['user_id'] = user['id']
            session['role'] = 'manager'
            return redirect(url_for('manager_dashboard'))
    flash('اطلاعات ورود منیجر صحیح نیست')
    return redirect(url_for('manager_login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/send-public-message', methods=['POST'])
def send_public_message():
    name = request.form.get('name')
    message = request.form.get('message')
    if not name or not message:
        flash('لطفاً نام و پیام خود را وارد کنید')
        return redirect(url_for('index'))
    db = get_db()
    db.execute("INSERT INTO public_messages (name, message) VALUES (?, ?)", (name, message))
    db.commit()
    flash('✅ پیام شما با موفقیت ارسال شد. با تشکر از شما!')
    return redirect(url_for('index'))

# ---------- Manager Dashboard ----------
@app.route('/manager/dashboard')
@login_required('manager')
def manager_dashboard():
    db = get_db()
    projects = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    viewers = db.execute("SELECT * FROM users WHERE role = 'viewer' AND is_active = 1").fetchall()
    messages = db.execute("SELECT m.*, u.username FROM messages m JOIN users u ON m.user_id = u.id WHERE m.is_deleted = 0 ORDER BY m.timestamp DESC").fetchall()
    public_msgs = db.execute("SELECT * FROM public_messages ORDER BY created_at DESC").fetchall()
    api_key = db.execute("SELECT value FROM settings WHERE key='api_key'").fetchone()
    api_url = db.execute("SELECT value FROM settings WHERE key='api_url'").fetchone()
    model = db.execute("SELECT value FROM settings WHERE key='model'").fetchone()
    return render_template_string(MANAGER_DASHBOARD_HTML,
                                  projects=projects,
                                  viewers=viewers,
                                  messages=messages,
                                  public_msgs=public_msgs,
                                  api_key=api_key['value'] if api_key else '',
                                  api_url=api_url['value'] if api_url else '',
                                  model=model['value'] if model else '')

@app.route('/manager/project/create', methods=['POST'])
@login_required('manager')
def create_project():
    name = request.form.get('name')
    description = request.form.get('description')
    if not name:
        flash('نام پروژه الزامی است')
        return redirect(url_for('manager_dashboard'))
    db = get_db()
    db.execute("INSERT INTO projects (name, description) VALUES (?, ?)", (name, description))
    db.commit()
    flash('پروژه جدید ایجاد شد')
    return redirect(url_for('manager_dashboard'))

@app.route('/manager/project/<int:project_id>/delete', methods=['POST'])
@login_required('manager')
def delete_project(project_id):
    db = get_db()
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    flash('پروژه حذف شد')
    return redirect(url_for('manager_dashboard'))

@app.route('/manager/project/<int:project_id>/tasks')
@login_required('manager')
def project_tasks(project_id):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        flash('پروژه یافت نشد')
        return redirect(url_for('manager_dashboard'))
    tasks = db.execute("SELECT * FROM tasks WHERE project_id = ? ORDER BY order_index", (project_id,)).fetchall()
    total_hours = sum(t['estimated_hours'] for t in tasks)
    done_hours = sum(t['estimated_hours'] for t in tasks if t['status'] == 2)
    progress = int((done_hours / total_hours) * 100) if total_hours > 0 else 0
    return render_template_string(PROJECT_TASKS_HTML, project=project, tasks=tasks, progress=progress)

@app.route('/manager/project/<int:project_id>/task/add', methods=['POST'])
@login_required('manager')
def add_task(project_id):
    title = request.form.get('title')
    hours = request.form.get('hours', type=int)
    if not title or not hours:
        flash('عنوان و ساعت الزامی است')
        return redirect(url_for('project_tasks', project_id=project_id))
    db = get_db()
    max_order = db.execute("SELECT ifnull(MAX(order_index), 0) FROM tasks WHERE project_id = ?", (project_id,)).fetchone()[0]
    db.execute("INSERT INTO tasks (project_id, title, estimated_hours, order_index) VALUES (?, ?, ?, ?)",
               (project_id, title, hours, max_order+1))
    db.commit()
    flash('مرحله جدید اضافه شد')
    return redirect(url_for('project_tasks', project_id=project_id))

@app.route('/manager/task/<int:task_id>/status', methods=['POST'])
@login_required('manager')
def update_task_status(task_id):
    status = request.form.get('status')
    db = get_db()
    task = db.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        flash('مرحله یافت نشد')
        return redirect(url_for('manager_dashboard'))
    db.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    db.commit()
    if status == '2':
        flash('🎉 آفرین! این مرحله با موفقیت انجام شد.')
    return redirect(url_for('project_tasks', project_id=task['project_id']))

@app.route('/manager/task/<int:task_id>/edit', methods=['POST'])
@login_required('manager')
def edit_task_title(task_id):
    new_title = request.form.get('title')
    if new_title:
        db = get_db()
        task = db.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task:
            db.execute("UPDATE tasks SET title = ? WHERE id = ?", (new_title, task_id))
            db.commit()
    return redirect(url_for('project_tasks', project_id=task['project_id']))

@app.route('/manager/task/<int:task_id>/delete', methods=['POST'])
@login_required('manager')
def delete_task(task_id):
    db = get_db()
    task = db.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task:
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
    return redirect(url_for('project_tasks', project_id=task['project_id']))

# ---------- Gallery Management ----------
@app.route('/manager/project/<int:project_id>/gallery')
@login_required('manager')
def project_gallery(project_id):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        flash('پروژه یافت نشد')
        return redirect(url_for('manager_dashboard'))
    images = db.execute("SELECT * FROM gallery_images WHERE project_id = ? ORDER BY uploaded_at DESC", (project_id,)).fetchall()
    return render_template_string(PROJECT_GALLERY_HTML, project=project, images=images)

@app.route('/manager/project/<int:project_id>/gallery/upload', methods=['POST'])
@login_required('manager')
def upload_gallery_image(project_id):
    if 'image' not in request.files:
        flash('فایلی انتخاب نشده')
        return redirect(url_for('project_gallery', project_id=project_id))
    file = request.files['image']
    if file.filename == '':
        flash('فایلی انتخاب نشده')
        return redirect(url_for('project_gallery', project_id=project_id))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        name, ext = os.path.splitext(filename)
        filename = f"{name}_{int(time.time())}{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        description = request.form.get('description', '')
        db = get_db()
        db.execute("INSERT INTO gallery_images (project_id, image_filename, description) VALUES (?, ?, ?)",
                   (project_id, filename, description))
        db.commit()
        flash('تصویر با موفقیت آپلود شد')
    else:
        flash('فرمت فایل مجاز نیست')
    return redirect(url_for('project_gallery', project_id=project_id))

@app.route('/manager/gallery/<int:image_id>/delete', methods=['POST'])
@login_required('manager')
def delete_gallery_image(image_id):
    db = get_db()
    image = db.execute("SELECT project_id, image_filename FROM gallery_images WHERE id = ?", (image_id,)).fetchone()
    if image:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], image['image_filename'])
        if os.path.exists(filepath):
            os.remove(filepath)
        db.execute("DELETE FROM gallery_images WHERE id = ?", (image_id,))
        db.commit()
    return redirect(url_for('project_gallery', project_id=image['project_id']))

@app.route('/manager/public-message/<int:msg_id>/delete', methods=['POST'])
@login_required('manager')
def delete_public_message(msg_id):
    db = get_db()
    db.execute("DELETE FROM public_messages WHERE id = ?", (msg_id,))
    db.commit()
    flash('پیام حذف شد')
    return redirect(url_for('manager_dashboard'))

# ---------- Public Gallery ----------
@app.route('/gallery')
def public_gallery():
    db = get_db()
    # فقط پروژه‌هایی که حداقل یک عکس دارند نمایش داده می‌شوند
    projects = db.execute("""
        SELECT DISTINCT p.* FROM projects p 
        INNER JOIN gallery_images gi ON p.id = gi.project_id 
        ORDER BY p.created_at DESC
    """).fetchall()
    
    project_images = {}
    for p in projects:
        imgs = db.execute("SELECT * FROM gallery_images WHERE project_id = ? ORDER BY uploaded_at DESC", (p['id'],)).fetchall()
        project_images[p['id']] = imgs
    return render_template_string(PUBLIC_GALLERY_HTML, projects=projects, project_images=project_images)

# ---------- Viewer Dashboard ----------
@app.route('/viewer/dashboard')
@login_required('viewer')
def viewer_dashboard():
    db = get_db()
    user_id = session['user_id']
    projects = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    can_view_progress = user['can_view_progress'] == 1
    project_data = []
    for p in projects:
        tasks = db.execute("SELECT * FROM tasks WHERE project_id = ? ORDER BY order_index", (p['id'],)).fetchall()
        visible_task_ids = db.execute(
            "SELECT task_id FROM task_visibility WHERE user_id = ? AND visible = 1",
            (user_id,)
        ).fetchall()
        visible_set = {row['task_id'] for row in visible_task_ids}
        task_list = []
        for t in tasks:
            t_dict = dict(t)
            t_dict['visible'] = t['id'] in visible_set
            task_list.append(t_dict)
        total_hours = sum(t['estimated_hours'] for t in tasks)
        done_hours = sum(t['estimated_hours'] for t in tasks if t['status'] == 2)
        progress = int((done_hours / total_hours) * 100) if total_hours > 0 else 0
        project_data.append({
            'project': p,
            'tasks': task_list,
            'progress': progress
        })
    messages = db.execute("SELECT * FROM messages WHERE user_id = ? AND is_deleted = 0 ORDER BY timestamp DESC", (user_id,)).fetchall()
    return render_template_string(VIEWER_DASHBOARD_HTML,
                                  projects=project_data,
                                  can_view_progress=can_view_progress,
                                  messages=messages)

@app.route('/viewer/send-message', methods=['POST'])
@login_required('viewer')
def send_message():
    message = request.form.get('message')
    if message:
        db = get_db()
        db.execute("INSERT INTO messages (user_id, message) VALUES (?, ?)", (session['user_id'], message))
        db.commit()
    return redirect(url_for('viewer_dashboard'))

# ---------- Manager: Viewer Management ----------
@app.route('/manager/create-viewer', methods=['POST'])
@login_required('manager')
def create_viewer():
    username = request.form.get('username')
    password = request.form.get('password')
    if not username or not password:
        flash('نام کاربری و رمز عبور الزامی است')
        return redirect(url_for('manager_dashboard'))
    db = get_db()
    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        flash('این نام کاربری قبلاً ثبت شده است')
        return redirect(url_for('manager_dashboard'))
    hashed = hashlib.sha256(password.encode()).hexdigest()
    db.execute("INSERT INTO users (username, password, role, created_by, is_active) VALUES (?, ?, 'viewer', ?, 1)",
               (username, hashed, session['user_id']))
    db.commit()
    flash('اکانت بازدید کننده ایجاد شد')
    return redirect(url_for('manager_dashboard'))

@app.route('/manager/viewer/<int:user_id>/toggle-active', methods=['POST'])
@login_required('manager')
def toggle_viewer_active(user_id):
    db = get_db()
    user = db.execute("SELECT is_active FROM users WHERE id = ? AND role = 'viewer'", (user_id,)).fetchone()
    if user:
        db.execute("UPDATE users SET is_active = ? WHERE id = ?", (0 if user['is_active'] else 1, user_id))
        db.commit()
    return redirect(url_for('manager_dashboard'))

@app.route('/manager/viewer/<int:user_id>/delete', methods=['POST'])
@login_required('manager')
def delete_viewer(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ? AND role = 'viewer'", (user_id,))
    db.commit()
    return redirect(url_for('manager_dashboard'))

@app.route('/manager/viewer/<int:user_id>/permissions', methods=['GET', 'POST'])
@login_required('manager')
def viewer_permissions(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ? AND role = 'viewer'", (user_id,)).fetchone()
    if not user:
        return "کاربر یافت نشد", 404
    if request.method == 'POST':
        task_ids = request.form.getlist('task_visible')
        db.execute("DELETE FROM task_visibility WHERE user_id = ?", (user_id,))
        for tid in task_ids:
            db.execute("INSERT INTO task_visibility (user_id, task_id, visible) VALUES (?, ?, 1)", (user_id, tid))
        can_view_progress = 1 if request.form.get('can_view_progress') else 0
        db.execute("UPDATE users SET can_view_progress = ? WHERE id = ?", (can_view_progress, user_id))
        db.commit()
        flash('تنظیمات دسترسی به‌روز شد')
        return redirect(url_for('manager_dashboard'))
    tasks = db.execute("SELECT t.*, p.name as project_name FROM tasks t JOIN projects p ON t.project_id = p.id ORDER BY p.name, t.order_index").fetchall()
    visible_tasks = db.execute("SELECT task_id FROM task_visibility WHERE user_id = ? AND visible = 1", (user_id,)).fetchall()
    visible_task_ids = [row['task_id'] for row in visible_tasks]
    return render_template_string(PERMISSIONS_HTML, user=user, tasks=tasks, visible_task_ids=visible_task_ids)

@app.route('/manager/message/<int:msg_id>/delete', methods=['POST'])
@login_required('manager')
def delete_message(msg_id):
    db = get_db()
    db.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (msg_id,))
    db.commit()
    return redirect(url_for('manager_dashboard'))

# ---------- Manager: AI Settings ----------
@app.route('/manager/ai-settings', methods=['POST'])
@login_required('manager')
def update_ai_settings():
    api_key = request.form.get('api_key')
    api_url = request.form.get('api_url')
    model = request.form.get('model')
    db = get_db()
    if api_key:
        db.execute("UPDATE settings SET value = ? WHERE key = 'api_key'", (api_key,))
    if api_url:
        db.execute("UPDATE settings SET value = ? WHERE key = 'api_url'", (api_url,))
    if model:
        db.execute("UPDATE settings SET value = ? WHERE key = 'model'", (model,))
    db.commit()
    flash('تنظیمات هوش مصنوعی به‌روز شد')
    return redirect(url_for('manager_dashboard'))

@app.route('/manager/ai-test', methods=['POST'])
@login_required('manager')
def test_ai():
    db = get_db()
    api_key = db.execute("SELECT value FROM settings WHERE key='api_key'").fetchone()
    api_url = db.execute("SELECT value FROM settings WHERE key='api_url'").fetchone()
    model = db.execute("SELECT value FROM settings WHERE key='model'").fetchone()
    if not api_key or not api_url or not model:
        return "تنظیمات کامل نیست", 400
    test_message = "سلام، یک پیام تست از پنل مدیریت ارسال می‌شود. لطفاً پاسخ دهید."
    try:
        response = call_ai_api(test_message, api_key['value'], api_url['value'], model['value'])
        return response if response else "پاسخی دریافت نشد"
    except Exception as e:
        return f"خطا در ارتباط با هوش مصنوعی: {str(e)}", 500

# ---------- AI Chat API ----------
@app.route('/api/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    if not user_message:
        return {"error": "پیام خالی است"}, 400
    db = get_db()
    api_key = db.execute("SELECT value FROM settings WHERE key='api_key'").fetchone()
    api_url = db.execute("SELECT value FROM settings WHERE key='api_url'").fetchone()
    model = db.execute("SELECT value FROM settings WHERE key='model'").fetchone()
    if not api_key or not api_url or not model:
        return {"error": "هوش مصنوعی فعلاً از دسترس خارج است"}, 503
    response = call_ai_api(user_message, api_key['value'], api_url['value'], model['value'])
    if response is None:
        return {"error": "هوش مصنوعی فعلاً از دسترس خارج است"}, 503
    return {"response": response}

# ---------- Serve uploaded images ----------
@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ==================== HTML TEMPLATES ====================
BASE_CANVAS = '''
<canvas id="particleCanvas"></canvas>
<style>
    canvas#particleCanvas {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: -1;
        pointer-events: none;
        background: radial-gradient(ellipse at center, #0a0b1a 0%, #05060f 100%);
    }
</style>
<script>
    (function() {
        const canvas = document.getElementById('particleCanvas');
        const ctx = canvas.getContext('2d');
        let width, height;
        let particles = [];
        let mouse = { x: null, y: null };

        function resize() {
            width = canvas.width = window.innerWidth;
            height = canvas.height = window.innerHeight;
        }
        window.addEventListener('resize', resize);
        resize();

        class Particle {
            constructor() {
                this.x = Math.random() * width;
                this.y = Math.random() * height;
                this.size = Math.random() * 2 + 0.5;
                this.speedX = (Math.random() - 0.5) * 0.4;
                this.speedY = (Math.random() - 0.5) * 0.4;
            }
            update() {
                this.x += this.speedX;
                this.y += this.speedY;
                if (this.x < 0 || this.x > width) this.speedX *= -1;
                if (this.y < 0 || this.y > height) this.speedY *= -1;
                if (mouse.x !== null) {
                    const dx = mouse.x - this.x;
                    const dy = mouse.y - this.y;
                    const dist = Math.sqrt(dx*dx + dy*dy);
                    const maxDist = 150;
                    if (dist < maxDist) {
                        const force = (1 - dist/maxDist) * 0.02;
                        this.x += dx * force;
                        this.y += dy * force;
                    }
                }
            }
            draw() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(255,215,0,0.4)';
                ctx.fill();
            }
        }

        function initParticles(count) {
            particles = [];
            for (let i = 0; i < count; i++) {
                particles.push(new Particle());
            }
        }
        initParticles(150);

        function drawLines() {
            for (let i = 0; i < particles.length; i++) {
                for (let j = i+1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const dist = Math.sqrt(dx*dx + dy*dy);
                    if (dist < 120) {
                        ctx.beginPath();
                        ctx.strokeStyle = `rgba(255,215,0,${0.15 * (1 - dist/120)})`;
                        ctx.lineWidth = 0.5;
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.stroke();
                    }
                }
            }
        }

        function animate() {
            ctx.clearRect(0, 0, width, height);
            particles.forEach(p => { p.update(); p.draw(); });
            drawLines();
            requestAnimationFrame(animate);
        }
        animate();

        document.addEventListener('mousemove', function(e) {
            mouse.x = e.clientX;
            mouse.y = e.clientY;
        });
        document.addEventListener('mouseleave', function() {
            mouse.x = null;
            mouse.y = null;
        });
    })();
</script>
'''

INDEX_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>شرکت آب و سازه</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: transparent;
            color: #e0e0f0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            direction: rtl;
            overflow-x: hidden;
        }
        .hero {
            position: relative;
            z-index: 1;
            text-align: center;
            padding: 60px 20px;
            max-width: 900px;
            width: 100%;
        }
        .hero h1 {
            font-size: 64px;
            font-weight: 800;
            background: linear-gradient(135deg, #ffd700, #f0b800);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 16px;
            animation: fadeUp 1s ease-out;
        }
        .hero p {
            font-size: 20px;
            color: rgba(255,255,255,0.6);
            margin-bottom: 32px;
            line-height: 1.8;
        }
        .hero .btn-group {
            display: flex;
            gap: 16px;
            justify-content: center;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }
        .hero .btn {
            padding: 16px 32px;
            border-radius: 30px;
            text-decoration: none;
            font-weight: 700;
            transition: all 0.3s;
            font-size: 16px;
            border: none;
            cursor: pointer;
        }
        .btn-primary {
            background: linear-gradient(135deg, #ffd700, #f0b800);
            color: #0b0c1a;
            box-shadow: 0 8px 24px rgba(255,215,0,0.3);
        }
        .btn-primary:hover {
            transform: translateY(-4px);
            box-shadow: 0 16px 40px rgba(255,215,0,0.4);
        }
        .btn-outline {
            background: transparent;
            border: 2px solid rgba(255,215,0,0.3);
            color: #ffd700;
        }
        .btn-outline:hover {
            background: rgba(255,215,0,0.1);
            border-color: #ffd700;
        }
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 24px;
            margin-top: 40px;
            width: 100%;
            max-width: 800px;
        }
        .feature {
            background: rgba(255,255,255,0.04);
            border-radius: 24px;
            padding: 24px;
            border: 1px solid rgba(255,255,255,0.06);
            backdrop-filter: blur(8px);
            transition: 0.3s;
        }
        .feature:hover {
            border-color: rgba(255,215,0,0.2);
            transform: translateY(-4px);
        }
        .feature i {
            font-size: 32px;
            color: #ffd700;
            margin-bottom: 12px;
        }
        .feature h3 {
            font-size: 18px;
            margin-bottom: 6px;
        }
        .feature p {
            font-size: 14px;
            color: rgba(255,255,255,0.5);
        }
        .toggle-section {
            width: 100%;
            max-width: 600px;
            margin: 30px auto 0;
        }
        .toggle-btn {
            width: 100%;
            padding: 18px;
            border: 2px solid rgba(255,215,0,0.3);
            border-radius: 30px;
            background: rgba(255,255,255,0.04);
            color: #ffd700;
            font-size: 18px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
            backdrop-filter: blur(8px);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }
        .toggle-btn:hover {
            background: rgba(255,215,0,0.1);
            border-color: #ffd700;
            transform: translateY(-2px);
        }
        .toggle-content {
            display: none;
            background: rgba(255,255,255,0.04);
            border-radius: 32px;
            padding: 36px;
            border: 1px solid rgba(255,255,255,0.06);
            backdrop-filter: blur(8px);
            margin-top: 16px;
        }
        .toggle-content.active {
            display: block;
            animation: slideDown 0.4s ease-out;
        }
        @keyframes slideDown {
            from { opacity:0; transform: translateY(-20px); }
            to { opacity:1; transform: translateY(0); }
        }
        .toggle-content input,
        .toggle-content textarea {
            width: 100%;
            padding: 14px 20px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 16px;
            outline: none;
            font-family: inherit;
            transition: 0.3s;
            margin-bottom: 16px;
        }
        .toggle-content input:focus,
        .toggle-content textarea:focus {
            border-color: #ffd700;
            box-shadow: 0 0 0 4px rgba(255,215,0,0.1);
            background: rgba(0,0,0,0.5);
        }
        .toggle-content textarea {
            min-height: 120px;
            resize: vertical;
        }
        .toggle-content input::placeholder,
        .toggle-content textarea::placeholder {
            color: rgba(255,255,255,0.3);
        }
        .toggle-content button {
            width: 100%;
            padding: 16px;
            border: none;
            border-radius: 24px;
            background: linear-gradient(135deg, #ffd700, #f0b800);
            color: #0b0c1a;
            font-size: 18px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .toggle-content button:hover {
            transform: scale(1.02);
            box-shadow: 0 8px 24px rgba(255,215,0,0.3);
        }
        @keyframes fadeUp {
            from { opacity:0; transform: translateY(30px); }
            to { opacity:1; transform: translateY(0); }
        }
        @media (max-width: 600px) {
            .hero h1 { font-size: 36px; }
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="hero">
        <h1>🏗️ شرکت آب و سازه مهدیشهر</h1>
        <p>لَا حَوْلَ وَ لَا قُوَّةَ إِلَّا بِاللَّهِ الْعَلِیِّ الْعَظِیمِ</p>
        <div class="btn-group">
            <a href="{{ url_for('login') }}" class="btn btn-primary">ورود به پنل</a>
            <a href="{{ url_for('public_gallery') }}" class="btn btn-outline">گالری پروژه‌ها</a>
        </div>
        <div class="features">
            <div class="feature">
                <i class="fas fas fa-map-marker-alt"></i>
                <h3>آدرس</h3>
                <p> مهدیشهر، خیابان امام خمینی، جنب بانک ملی، مجتمع کاج، طبقه سوم، واحد 12</p>
            </div>
            <div class="feature">
                <i class="fas fa-images"></i>
                <h3>گالری تصاویر</h3>
                <p>مشاهده روند اجرای پروژه‌ها</p>
            </div>
            <div class="feature">
                <i class="fas fa-phone"></i>
                <h3>تماس با ما</h3>
                <p>02333621395</p>
            </div>
        </div>

        <!-- فرم ارسال پیام عمومی با دکمه -->
        <div class="toggle-section">
            <button class="toggle-btn" onclick="toggleForm()">
                <i class="fas fa-paper-plane"></i> درخواست همکاری با ما
            </button>
            <div class="toggle-content" id="messageForm">
                <form method="POST" action="{{ url_for('send_public_message') }}">
                    <input type="text" name="name" placeholder="نام و نام خانوادگی" required>
                    <textarea name="message" placeholder="متن پیام شما..." required></textarea>
                    <button type="submit"><i class="fas fa-send"></i> ارسال پیام</button>
                </form>
            </div>
        </div>
    </div>

    <!-- AI Chat Widget -->
    <div id="chatWidget" style="position:fixed; bottom:24px; left:24px; z-index:1000;">
        <button id="chatToggle" style="background:#ffd700; border:none; border-radius:50%; width:60px; height:60px; font-size:28px; color:#0b0c1a; box-shadow:0 8px 24px rgba(255,215,0,0.4); cursor:pointer; transition:0.3s;">
            <i class="fas fa-comment-dots"></i>
        </button>
        <div id="chatBox" style="display:none; position:absolute; bottom:80px; left:0; width:340px; max-height:400px; background:rgba(20,20,40,0.95); backdrop-filter:blur(16px); border-radius:24px; border:1px solid rgba(255,215,0,0.15); padding:16px; box-shadow:0 16px 48px rgba(0,0,0,0.6);">
            <div id="chatMessages" style="max-height:280px; overflow-y:auto; margin-bottom:12px; direction:rtl;"></div>
            <div style="display:flex; gap:8px;">
                <input id="chatInput" type="text" placeholder="پیام خود را بنویسید..." style="flex:1; background:rgba(0,0,0,0.4); border:1px solid rgba(255,255,255,0.1); border-radius:20px; padding:10px 16px; color:#fff; outline:none; font-family:inherit;">
                <button id="chatSend" style="background:#ffd700; border:none; border-radius:20px; padding:10px 18px; color:#0b0c1a; font-weight:700; cursor:pointer;">ارسال</button>
            </div>
        </div>
    </div>
    <script>
        function toggleForm() {
            const form = document.getElementById('messageForm');
            form.classList.toggle('active');
        }
        const toggle = document.getElementById('chatToggle');
        const box = document.getElementById('chatBox');
        const input = document.getElementById('chatInput');
        const send = document.getElementById('chatSend');
        const messages = document.getElementById('chatMessages');
        let isOpen = false;
        toggle.addEventListener('click', () => {
            isOpen = !isOpen;
            box.style.display = isOpen ? 'block' : 'none';
            if (isOpen) messages.scrollTop = messages.scrollHeight;
        });
        function addMessage(text, sender) {
            const div = document.createElement('div');
            div.style.cssText = `padding:8px 12px; margin:4px 0; border-radius:12px; background:${sender === 'user' ? 'rgba(255,215,0,0.1)' : 'rgba(255,255,255,0.05)'}; border-right:3px solid ${sender === 'user' ? '#ffd700' : '#888'}; word-wrap:break-word;`;
            div.textContent = text;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }
        async function sendMessage() {
            const msg = input.value.trim();
            if (!msg) return;
            addMessage(msg, 'user');
            input.value = '';
            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg})
                });
                const data = await res.json();
                if (data.error) {
                    addMessage('⚠️ ' + data.error, 'bot');
                } else {
                    addMessage(data.response, 'bot');
                }
            } catch (e) {
                addMessage('⚠️ خطا در ارتباط با سرور', 'bot');
            }
        }
        send.addEventListener('click', sendMessage);
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });
    </script>
</body>
</html>
'''

LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ورود | شرکت آب و سازه</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: transparent;
            direction: rtl;
            overflow: hidden;
        }
        .login-card {
            position: relative;
            z-index: 1;
            background: rgba(255,255,255,0.04);
            backdrop-filter: blur(24px);
            border-radius: 48px;
            padding: 56px 48px;
            width: 100%;
            max-width: 440px;
            border: 1px solid rgba(255,215,0,0.12);
            box-shadow: 0 40px 80px rgba(0,0,0,0.6);
            animation: slideUp 0.8s ease-out;
        }
        @keyframes slideUp {
            from { opacity:0; transform: translateY(40px) scale(0.96); }
            to { opacity:1; transform: translateY(0) scale(1); }
        }
        .login-card:hover { border-color: rgba(255,215,0,0.3); transform: translateY(-6px); transition: all 0.3s; }
        .logo {
            text-align: center;
            margin-bottom: 40px;
        }
        .logo h1 {
            font-size: 34px;
            font-weight: 800;
            background: linear-gradient(135deg, #ffd700, #f0b800);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .logo p {
            color: rgba(255,255,255,0.5);
            font-size: 14px;
            margin-top: 8px;
        }
        .form-group { margin-bottom: 24px; }
        .form-group label {
            display: block;
            color: rgba(255,255,255,0.7);
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .form-group input {
            width: 100%;
            padding: 16px 20px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 16px;
            transition: all 0.3s;
            outline: none;
            font-family: inherit;
        }
        .form-group input:focus {
            border-color: #ffd700;
            box-shadow: 0 0 0 4px rgba(255,215,0,0.15);
            background: rgba(0,0,0,0.5);
        }
        .btn-login {
            width: 100%;
            padding: 18px;
            border: none;
            border-radius: 24px;
            background: linear-gradient(135deg, #ffd700, #f0b800);
            color: #0b0c1a;
            font-size: 18px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .btn-login:hover {
            transform: scale(1.02);
            box-shadow: 0 16px 40px rgba(255,215,0,0.3);
        }
        .footer-links {
            margin-top: 28px;
            text-align: center;
        }
        .footer-links a {
            color: rgba(255,255,255,0.4);
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
        }
        .footer-links a:hover { color: #ffd700; }
        .flash-messages { margin-bottom: 24px; }
        .flash {
            padding: 14px 20px;
            border-radius: 16px;
            background: rgba(255,0,0,0.1);
            border-right: 4px solid #ff6b6b;
            color: #ff6b6b;
            font-size: 14px;
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="login-card">
        <div class="logo">
            <h1>🏗️ آب و سازه</h1>
            <p>سامانه مدیریت پروژه</p>
        </div>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="flash-messages">
                    {% for msg in messages %}
                        <div class="flash">{{ msg }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}
        <form method="POST" action="{{ url_for('do_login') }}">
            <div class="form-group">
                <label><i class="fas fa-user"></i> نام کاربری</label>
                <input type="text" name="username" placeholder="نام کاربری" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-lock"></i> رمز عبور</label>
                <input type="password" name="password" placeholder="••••••••" required>
            </div>
            <button type="submit" class="btn-login"><i class="fas fa-sign-in-alt"></i> ورود</button>
        </form>
        <div class="footer-links">
            <a href="{{ url_for('manager_login') }}"><i class="fas fa-crown"></i> ورود منیجر</a>
            <a href="{{ url_for('index') }}" style="margin-right:16px;"><i class="fas fa-home"></i> صفحه اصلی</a>
        </div>
    </div>
</body>
</html>
'''

MANAGER_LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ورود منیجر | آب و سازه</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: transparent;
            direction: rtl;
            overflow: hidden;
        }
        .login-card {
            background: rgba(255,255,255,0.04);
            backdrop-filter: blur(24px);
            border-radius: 48px;
            padding: 56px 48px;
            width: 100%;
            max-width: 440px;
            border: 1px solid rgba(255,215,0,0.2);
            box-shadow: 0 40px 80px rgba(0,0,0,0.6);
            animation: slideUp 0.8s ease-out;
            z-index: 1;
        }
        @keyframes slideUp {
            from { opacity:0; transform: translateY(40px) scale(0.96); }
            to { opacity:1; transform: translateY(0) scale(1); }
        }
        .login-card h2 {
            color: #ffd700;
            text-align: center;
            font-weight: 700;
            font-size: 28px;
            margin-bottom: 32px;
        }
        .form-group { margin-bottom: 24px; }
        .form-group label {
            display: block;
            color: rgba(255,255,255,0.7);
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .form-group input {
            width: 100%;
            padding: 16px 20px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 16px;
            transition: all 0.3s;
            outline: none;
            font-family: inherit;
        }
        .form-group input:focus {
            border-color: #ffd700;
            box-shadow: 0 0 0 4px rgba(255,215,0,0.15);
        }
        .btn-login {
            width: 100%;
            padding: 18px;
            border: none;
            border-radius: 24px;
            background: linear-gradient(135deg, #ffd700, #f0b800);
            color: #0b0c1a;
            font-size: 18px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .btn-login:hover {
            transform: scale(1.02);
            box-shadow: 0 16px 40px rgba(255,215,0,0.3);
        }
        .flash-messages { margin-bottom: 24px; }
        .flash {
            padding: 14px 20px;
            border-radius: 16px;
            background: rgba(255,0,0,0.1);
            border-right: 4px solid #ff6b6b;
            color: #ff6b6b;
            font-size: 14px;
        }
        .back-link {
            display: block;
            text-align: center;
            margin-top: 24px;
            color: rgba(255,255,255,0.4);
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
            transition: color 0.3s;
        }
        .back-link:hover { color: #ffd700; }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="login-card">
        <h2><i class="fas fa-crown"></i> ورود منیجر</h2>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="flash-messages">
                    {% for msg in messages %}
                        <div class="flash">{{ msg }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}
        <form method="POST" action="{{ url_for('do_manager_login') }}">
            <div class="form-group">
                <label><i class="fas fa-user-tie"></i> نام کاربری</label>
                <input type="text" name="username" placeholder="نام کاربری منیجر" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-key"></i> رمز عبور</label>
                <input type="password" name="password" placeholder="••••••••" required>
            </div>
            <button type="submit" class="btn-login"><i class="fas fa-sign-in-alt"></i> ورود</button>
        </form>
        <a href="{{ url_for('login') }}" class="back-link"><i class="fas fa-arrow-right"></i> بازگشت به صفحه ورود</a>
    </div>
</body>
</html>
'''

MANAGER_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>پنل مدیریت | آب و سازه</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: transparent;
            color: #e0e0f0;
            padding: 24px;
            direction: rtl;
            min-height: 100vh;
        }
        .container { max-width: 1440px; margin: 0 auto; position: relative; z-index: 1; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 32px;
            background: rgba(255,255,255,0.04);
            border-radius: 32px;
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 32px;
            flex-wrap: wrap;
            gap: 16px;
        }
        .header h1 {
            font-size: 26px;
            font-weight: 700;
            background: linear-gradient(135deg, #ffd700, #f0b800);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header .user-info { display: flex; align-items: center; gap: 16px; }
        .header .user-info a {
            color: #ffd700;
            text-decoration: none;
            background: rgba(255,215,0,0.08);
            padding: 10px 22px;
            border-radius: 30px;
            border: 1px solid rgba(255,215,0,0.1);
            font-weight: 600;
            transition: all 0.3s;
            font-size: 14px;
        }
        .header .user-info a:hover { background: rgba(255,215,0,0.15); transform: translateY(-2px); }
        .grid-2 {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 28px;
            margin-bottom: 32px;
        }
        .card {
            background: rgba(255,255,255,0.03);
            border-radius: 32px;
            padding: 28px;
            border: 1px solid rgba(255,255,255,0.05);
            backdrop-filter: blur(8px);
            transition: all 0.3s;
        }
        .card:hover { border-color: rgba(255,215,0,0.12); box-shadow: 0 8px 32px rgba(0,0,0,0.3); transform: translateY(-2px); }
        .card h2 {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            color: #ffd700;
            display: flex;
            align-items: center;
            gap: 10px;
            border-bottom: 1px solid rgba(255,215,0,0.08);
            padding-bottom: 12px;
        }
        .project-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        .project-item .actions { display: flex; gap: 8px; flex-wrap: wrap; }
        .project-item .actions a, .project-item .actions form button {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 4px 14px;
            color: #ccc;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.3s;
            text-decoration: none;
            font-family: inherit;
        }
        .project-item .actions a:hover, .project-item .actions form button:hover {
            background: rgba(255,215,0,0.12);
            color: #ffd700;
        }
        .project-item .actions .danger:hover { background: rgba(255,0,0,0.15); color: #ff6b6b; border-color: #ff6b6b; }
        .create-project {
            display: flex;
            gap: 12px;
            margin-top: 16px;
            flex-wrap: wrap;
        }
        .create-project input, .create-project textarea {
            flex: 1;
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 20px;
            padding: 12px 18px;
            color: #fff;
            font-size: 14px;
            font-family: inherit;
            transition: 0.3s;
        }
        .create-project input:focus, .create-project textarea:focus {
            border-color: #ffd700;
            outline: none;
            box-shadow: 0 0 0 3px rgba(255,215,0,0.1);
        }
        .create-project button {
            background: #ffd700;
            border: none;
            border-radius: 20px;
            padding: 12px 28px;
            color: #0b0c1a;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .create-project button:hover { transform: scale(1.02); box-shadow: 0 8px 24px rgba(255,215,0,0.3); }
        .viewer-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        .viewer-item .actions { display: flex; gap: 8px; flex-wrap: wrap; }
        .viewer-item .actions form { display: inline; }
        .viewer-item .actions button, .viewer-item .actions a {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 4px 14px;
            color: #ccc;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.3s;
            text-decoration: none;
            font-family: inherit;
        }
        .viewer-item .actions button:hover, .viewer-item .actions a:hover {
            background: rgba(255,215,0,0.12);
            color: #ffd700;
        }
        .viewer-item .actions .danger:hover { background: rgba(255,0,0,0.15); color: #ff6b6b; border-color: #ff6b6b; }
        .create-viewer {
            display: flex;
            gap: 12px;
            margin-top: 16px;
            flex-wrap: wrap;
        }
        .create-viewer input {
            flex: 1;
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 20px;
            padding: 12px 18px;
            color: #fff;
            font-size: 14px;
            font-family: inherit;
            transition: 0.3s;
        }
        .create-viewer input:focus {
            border-color: #ffd700;
            outline: none;
            box-shadow: 0 0 0 3px rgba(255,215,0,0.1);
        }
        .create-viewer button {
            background: #ffd700;
            border: none;
            border-radius: 20px;
            padding: 12px 28px;
            color: #0b0c1a;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .create-viewer button:hover { transform: scale(1.02); box-shadow: 0 8px 24px rgba(255,215,0,0.3); }
        .msg-item {
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
        }
        .msg-item .msg-text { flex: 1; }
        .msg-item .msg-meta { color: rgba(255,255,255,0.3); font-size: 12px; white-space: nowrap; }
        .msg-item .msg-actions button {
            background: none;
            border: none;
            color: #ff6b6b;
            cursor: pointer;
            font-size: 16px;
            transition: 0.3s;
        }
        .msg-item .msg-actions button:hover { transform: scale(1.1); }
        .flash-messages { margin-bottom: 20px; }
        .flash {
            padding: 14px 20px;
            border-radius: 20px;
            background: rgba(255,215,0,0.06);
            border-right: 4px solid #ffd700;
            color: #f0e6d0;
            margin-bottom: 8px;
            font-weight: 500;
            animation: fadeIn 0.4s;
        }
        .flash.success { background: rgba(0,255,0,0.05); border-right-color: #69db7c; color: #69db7c; }
        .ai-settings {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 12px;
        }
        .ai-settings input {
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 10px 16px;
            color: #fff;
            font-size: 13px;
            font-family: inherit;
            transition: 0.3s;
        }
        .ai-settings input:focus {
            border-color: #ffd700;
            outline: none;
            box-shadow: 0 0 0 3px rgba(255,215,0,0.1);
        }
        .ai-settings button {
            background: #ffd700;
            border: none;
            border-radius: 16px;
            padding: 10px 20px;
            color: #0b0c1a;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
            font-size: 13px;
        }
        .ai-settings button:hover { transform: scale(1.02); box-shadow: 0 4px 16px rgba(255,215,0,0.3); }
        @media (max-width: 900px) {
            .grid-2 { grid-template-columns: 1fr; }
            .header { flex-direction: column; align-items: stretch; }
            .ai-settings { grid-template-columns: 1fr; }
        }
        @keyframes fadeIn {
            from { opacity:0; transform: translateX(-10px); }
            to { opacity:1; transform: translateX(0); }
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-hard-hat"></i> پنل مدیریت <small style="font-size:16px; font-weight:400; color:rgba(255,255,255,0.4); -webkit-text-fill-color:rgba(255,255,255,0.4);">مهندس حسین ملک احمدی</small></h1>
            <div class="user-info">
                <span style="color:rgba(255,255,255,0.4);"><i class="fas fa-user-cog"></i> خوش آمدید</span>
                <a href="{{ url_for('logout') }}"><i class="fas fa-sign-out-alt"></i> خروج</a>
            </div>
        </div>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="flash-messages">
                    {% for msg in messages %}
                        <div class="flash {% if 'تبریک' in msg %}success{% endif %}">{{ msg }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}

        <div class="grid-2">
            <div class="card">
                <h2><i class="fas fa-project-diagram"></i> پروژه‌ها</h2>
                <div class="create-project">
                    <form method="POST" action="{{ url_for('create_project') }}" style="display:flex; gap:12px; width:100%; flex-wrap:wrap;">
                        <input type="text" name="name" placeholder="نام پروژه" required style="flex:2; min-width:150px;">
                        <input type="text" name="description" placeholder="توضیحات" style="flex:3; min-width:150px;">
                        <button type="submit"><i class="fas fa-plus-circle"></i> ایجاد</button>
                    </form>
                </div>
                <div style="margin-top:16px;">
                    {% for project in projects %}
                    <div class="project-item">
                        <span><i class="fas fa-folder" style="color:#ffd700;"></i> {{ project.name }}</span>
                        <div class="actions">
                            <a href="{{ url_for('project_tasks', project_id=project.id) }}"><i class="fas fa-tasks"></i> مراحل</a>
                            <a href="{{ url_for('project_gallery', project_id=project.id) }}"><i class="fas fa-images"></i> گالری</a>
                            <form method="POST" action="{{ url_for('delete_project', project_id=project.id) }}" onsubmit="return confirm('پروژه حذف شود؟')">
                                <button type="submit" class="danger"><i class="fas fa-trash-alt"></i></button>
                            </form>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>

            <div class="card">
                <h2><i class="fas fa-users"></i> بازدیدکنندگان</h2>
                <div class="create-viewer">
                    <form method="POST" action="{{ url_for('create_viewer') }}" style="display:flex; gap:12px; width:100%; flex-wrap:wrap;">
                        <input type="text" name="username" placeholder="نام کاربری جدید" required>
                        <input type="text" name="password" placeholder="رمز عبور" required>
                        <button type="submit"><i class="fas fa-plus-circle"></i> ایجاد</button>
                    </form>
                </div>
                <div style="margin-top:16px;">
                    {% for viewer in viewers %}
                    <div class="viewer-item">
                        <span><i class="fas fa-user-circle" style="color:#ffd700;"></i> {{ viewer.username }}</span>
                        <div class="actions">
                            <a href="{{ url_for('viewer_permissions', user_id=viewer.id) }}"><i class="fas fa-key"></i> دسترسی</a>
                            <form method="POST" action="{{ url_for('toggle_viewer_active', user_id=viewer.id) }}">
                                <button type="submit">{% if viewer.is_active %}<i class="fas fa-lock-open"></i> غیرفعال{% else %}<i class="fas fa-lock"></i> فعال{% endif %}</button>
                            </form>
                            <form method="POST" action="{{ url_for('delete_viewer', user_id=viewer.id) }}" onsubmit="return confirm('حذف شود؟')">
                                <button type="submit" class="danger"><i class="fas fa-trash-alt"></i></button>
                            </form>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <div class="grid-2">
            <div class="card">
                <h2><i class="fas fa-comments"></i> پیام‌های بازدیدکنندگان</h2>
                {% for msg in messages %}
                <div class="msg-item">
                    <div class="msg-text"><strong style="color:#ffd700;">{{ msg.username }}</strong>: {{ msg.message }}</div>
                    <div class="msg-meta">{{ msg.timestamp[:16] }}</div>
                    <div class="msg-actions">
                        <form method="POST" action="{{ url_for('delete_message', msg_id=msg.id) }}">
                            <button type="submit"><i class="fas fa-trash-alt"></i></button>
                        </form>
                    </div>
                </div>
                {% else %}
                <div style="color:rgba(255,255,255,0.3);">پیامی وجود ندارد</div>
                {% endfor %}
            </div>

            <div class="card">
                <h2><i class="fas fa-envelope" style="color:#69db7c;"></i> پیام‌های عمومی</h2>
                {% for msg in public_msgs %}
                <div class="msg-item">
                    <div class="msg-text">
                        <strong style="color:#ffd700;">{{ msg.name }}</strong>: {{ msg.message }}
                    </div>
                    <div class="msg-meta">{{ msg.created_at[:16] }}</div>
                    <div class="msg-actions">
                        <form method="POST" action="{{ url_for('delete_public_message', msg_id=msg.id) }}">
                            <button type="submit"><i class="fas fa-trash-alt"></i></button>
                        </form>
                    </div>
                </div>
                {% else %}
                <div style="color:rgba(255,255,255,0.3);">هیچ پیامی دریافت نشده است</div>
                {% endfor %}
            </div>
        </div>

        <div class="card">
            <h2><i class="fas fa-robot"></i> تنظیمات هوش مصنوعی</h2>
            <form method="POST" action="{{ url_for('update_ai_settings') }}">
                <div class="ai-settings">
                    <input type="text" name="api_key" value="{{ api_key }}" placeholder="API Key">
                    <input type="text" name="api_url" value="{{ api_url }}" placeholder="API URL">
                    <input type="text" name="model" value="{{ model }}" placeholder="مدل (مثلاً gpt-3.5-turbo)">
                    <button type="submit"><i class="fas fa-save"></i> ذخیره</button>
                </div>
            </form>
            <form method="POST" action="{{ url_for('test_ai') }}" style="margin-top:12px;">
                <button type="submit" style="background:rgba(255,215,0,0.1); border:1px solid rgba(255,215,0,0.2); border-radius:16px; padding:8px 20px; color:#ffd700; cursor:pointer; font-family:inherit; font-weight:600; transition:0.3s;">تست ارتباط با هوش مصنوعی</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

PROJECT_TASKS_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>مراحل پروژه | {{ project.name }}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: transparent;
            color: #e0e0f0;
            padding: 24px;
            direction: rtl;
            min-height: 100vh;
        }
        .container { max-width: 1000px; margin: 0 auto; position: relative; z-index: 1; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 32px;
            background: rgba(255,255,255,0.04);
            border-radius: 32px;
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 32px;
            flex-wrap: wrap;
            gap: 16px;
        }
        .header h1 {
            font-size: 26px;
            font-weight: 700;
            color: #ffd700;
        }
        .header a {
            color: #ffd700;
            text-decoration: none;
            background: rgba(255,215,0,0.08);
            padding: 10px 22px;
            border-radius: 30px;
            border: 1px solid rgba(255,215,0,0.1);
            font-weight: 600;
            transition: all 0.3s;
        }
        .header a:hover { background: rgba(255,215,0,0.15); transform: translateY(-2px); }
        .card {
            background: rgba(255,255,255,0.03);
            border-radius: 32px;
            padding: 28px;
            border: 1px solid rgba(255,255,255,0.05);
            backdrop-filter: blur(8px);
            margin-bottom: 24px;
        }
        .card h2 {
            font-size: 20px;
            font-weight: 600;
            color: #ffd700;
            border-bottom: 1px solid rgba(255,215,0,0.08);
            padding-bottom: 12px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .task-item {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 14px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            flex-wrap: wrap;
        }
        .task-item:last-child { border-bottom: none; }
        .task-title { flex: 1; min-width: 140px; }
        .task-title .edit-form { display: flex; gap: 8px; align-items: center; }
        .task-title .edit-form input {
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 6px 14px;
            color: #fff;
            font-size: 14px;
            width: 180px;
            font-family: inherit;
            transition: 0.3s;
        }
        .task-title .edit-form input:focus { border-color: #ffd700; outline: none; box-shadow: 0 0 0 3px rgba(255,215,0,0.1); }
        .task-title .edit-form button { background: none; border: none; color: #ffd700; cursor: pointer; font-size: 16px; transition: 0.3s; }
        .task-title .edit-form button:hover { transform: scale(1.1); }
        .task-time { color: rgba(255,255,255,0.5); font-size: 13px; font-weight: 500; min-width: 80px; }
        .task-status select {
            background: rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 20px;
            padding: 6px 14px;
            color: #fff;
            font-size: 13px;
            cursor: pointer;
            font-family: inherit;
            transition: 0.3s;
        }
        .task-status select:focus { border-color: #ffd700; outline: none; }
        .task-status select option { background: #1a1a2e; }
        .task-delete form button {
            background: none;
            border: none;
            color: #ff6b6b;
            cursor: pointer;
            font-size: 16px;
            transition: 0.3s;
        }
        .task-delete form button:hover { transform: scale(1.1); }
        .progress-bar {
            width: 100%;
            height: 8px;
            background: rgba(255,255,255,0.06);
            border-radius: 20px;
            overflow: hidden;
            margin-top: 12px;
            box-shadow: inset 0 1px 3px rgba(0,0,0,0.3);
        }
        .progress-bar .fill {
            height: 100%;
            background: linear-gradient(90deg, #ffd700, #f0b800);
            border-radius: 20px;
            transition: width 0.8s cubic-bezier(0.34,1.56,0.64,1);
            box-shadow: 0 0 20px rgba(255,215,0,0.2);
        }
        .add-task {
            display: flex;
            gap: 12px;
            margin-top: 16px;
            flex-wrap: wrap;
        }
        .add-task input {
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 20px;
            padding: 12px 18px;
            color: #fff;
            font-size: 14px;
            font-family: inherit;
            transition: 0.3s;
        }
        .add-task input:focus { border-color: #ffd700; outline: none; box-shadow: 0 0 0 3px rgba(255,215,0,0.1); }
        .add-task button {
            background: #ffd700;
            border: none;
            border-radius: 20px;
            padding: 12px 28px;
            color: #0b0c1a;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .add-task button:hover { transform: scale(1.02); box-shadow: 0 8px 24px rgba(255,215,0,0.3); }
        .flash-messages { margin-bottom: 20px; }
        .flash {
            padding: 14px 20px;
            border-radius: 20px;
            background: rgba(255,215,0,0.06);
            border-right: 4px solid #ffd700;
            color: #f0e6d0;
            margin-bottom: 8px;
            font-weight: 500;
            animation: fadeIn 0.4s;
        }
        .flash.success { background: rgba(0,255,0,0.05); border-right-color: #69db7c; color: #69db7c; }
        @media (max-width: 600px) {
            .header { flex-direction: column; align-items: stretch; }
            .task-item { flex-direction: column; align-items: stretch; }
        }
        @keyframes fadeIn {
            from { opacity:0; transform: translateX(-10px); }
            to { opacity:1; transform: translateX(0); }
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-tasks"></i> {{ project.name }}</h1>
            <a href="{{ url_for('manager_dashboard') }}"><i class="fas fa-arrow-right"></i> بازگشت</a>
        </div>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="flash-messages">
                    {% for msg in messages %}
                        <div class="flash {% if 'تبریک' in msg %}success{% endif %}">{{ msg }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}

        <div class="card">
            <h2><i class="fas fa-list"></i> مراحل پروژه</h2>
            <div style="margin-bottom:16px;">
                <div class="progress-bar"><div class="fill" style="width:{{ progress }}%;"></div></div>
                <div style="margin-top:8px; color:rgba(255,255,255,0.4);">پیشرفت: {{ progress }}%</div>
            </div>
            {% for task in tasks %}
            <div class="task-item">
                <div class="task-title">
                    <form method="POST" action="{{ url_for('edit_task_title', task_id=task.id) }}" class="edit-form">
                        <input type="text" name="title" value="{{ task.title }}" required>
                        <button type="submit"><i class="fas fa-edit"></i></button>
                    </form>
                </div>
                <div class="task-time">
                    {% set days = task.estimated_hours // 24 %}
                    {% set hours = task.estimated_hours % 24 %}
                    {% if days > 0 %}{{ days }} روز{% endif %}
                    {% if hours > 0 %}{% if days > 0 %} و {% endif %}{{ hours }} ساعت{% endif %}
                    {% if days == 0 and hours == 0 %}۰ ساعت{% endif %}
                </div>
                <div class="task-status">
                    <form method="POST" action="{{ url_for('update_task_status', task_id=task.id) }}">
                        <select name="status" onchange="this.form.submit()">
                            <option value="0" {% if task.status == 0 %}selected{% endif %}>انجام نشده</option>
                            <option value="1" {% if task.status == 1 %}selected{% endif %}>در حال انجام</option>
                            <option value="2" {% if task.status == 2 %}selected{% endif %}>انجام شد</option>
                        </select>
                    </form>
                </div>
                <div class="task-delete">
                    <form method="POST" action="{{ url_for('delete_task', task_id=task.id) }}" onsubmit="return confirm('مرحله حذف شود؟')">
                        <button type="submit"><i class="fas fa-trash-alt"></i></button>
                    </form>
                </div>
            </div>
            {% endfor %}

            <div class="add-task">
                <form method="POST" action="{{ url_for('add_task', project_id=project.id) }}" style="display:flex; gap:12px; width:100%; flex-wrap:wrap;">
                    <input type="text" name="title" placeholder="عنوان مرحله جدید" required style="flex:2; min-width:150px;">
                    <input type="number" name="hours" placeholder="ساعت" required style="flex:1; min-width:80px;">
                    <button type="submit"><i class="fas fa-plus-circle"></i> افزودن</button>
                </form>
            </div>
        </div>
    </div>
</body>
</html>
'''

PROJECT_GALLERY_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>گالری | {{ project.name }}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: transparent;
            color: #e0e0f0;
            padding: 24px;
            direction: rtl;
            min-height: 100vh;
        }
        .container { max-width: 1100px; margin: 0 auto; position: relative; z-index: 1; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 32px;
            background: rgba(255,255,255,0.04);
            border-radius: 32px;
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 32px;
            flex-wrap: wrap;
            gap: 16px;
        }
        .header h1 { font-size: 26px; font-weight: 700; color: #ffd700; }
        .header a {
            color: #ffd700;
            text-decoration: none;
            background: rgba(255,215,0,0.08);
            padding: 10px 22px;
            border-radius: 30px;
            border: 1px solid rgba(255,215,0,0.1);
            font-weight: 600;
            transition: all 0.3s;
        }
        .header a:hover { background: rgba(255,215,0,0.15); transform: translateY(-2px); }
        .card {
            background: rgba(255,255,255,0.03);
            border-radius: 32px;
            padding: 28px;
            border: 1px solid rgba(255,255,255,0.05);
            backdrop-filter: blur(8px);
            margin-bottom: 24px;
        }
        .card h2 {
            font-size: 20px;
            font-weight: 600;
            color: #ffd700;
            border-bottom: 1px solid rgba(255,215,0,0.08);
            padding-bottom: 12px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .upload-form {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            align-items: center;
        }
        .upload-form input[type="file"] {
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 20px;
            padding: 10px 16px;
            color: #fff;
            font-size: 14px;
            font-family: inherit;
        }
        .upload-form input[type="text"] {
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 20px;
            padding: 10px 16px;
            color: #fff;
            font-size: 14px;
            font-family: inherit;
            flex: 1;
            min-width: 150px;
        }
        .upload-form button {
            background: #ffd700;
            border: none;
            border-radius: 20px;
            padding: 10px 28px;
            color: #0b0c1a;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .upload-form button:hover { transform: scale(1.02); box-shadow: 0 8px 24px rgba(255,215,0,0.3); }
        .gallery-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 24px;
            margin-top: 16px;
        }
        .gallery-item {
            background: rgba(255,255,255,0.04);
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.06);
            transition: 0.3s;
            position: relative;
        }
        .gallery-item:hover { transform: translateY(-4px); border-color: rgba(255,215,0,0.2); }
        .gallery-item img {
            width: 100%;
            height: 240px;
            object-fit: cover;
            display: block;
        }
        .gallery-item .info {
            padding: 12px 16px;
        }
        .gallery-item .info .desc {
            font-size: 14px;
            color: rgba(255,255,255,0.7);
            margin-bottom: 6px;
        }
        .gallery-item .info .meta {
            font-size: 12px;
            color: rgba(255,255,255,0.3);
        }
        .gallery-item .delete-btn {
            position: absolute;
            top: 8px;
            left: 8px;
            background: rgba(0,0,0,0.6);
            border: none;
            border-radius: 50%;
            width: 32px;
            height: 32px;
            color: #ff6b6b;
            cursor: pointer;
            transition: 0.3s;
            font-size: 14px;
        }
        .gallery-item .delete-btn:hover { background: rgba(255,0,0,0.3); transform: scale(1.1); }
        .flash-messages { margin-bottom: 20px; }
        .flash {
            padding: 14px 20px;
            border-radius: 20px;
            background: rgba(255,215,0,0.06);
            border-right: 4px solid #ffd700;
            color: #f0e6d0;
            margin-bottom: 8px;
            font-weight: 500;
            animation: fadeIn 0.4s;
        }
        @media (max-width: 600px) {
            .header { flex-direction: column; align-items: stretch; }
            .upload-form { flex-direction: column; }
            .upload-form input[type="file"], .upload-form input[type="text"], .upload-form button { width: 100%; }
            .gallery-grid { grid-template-columns: 1fr; }
        }
        @keyframes fadeIn {
            from { opacity:0; transform: translateX(-10px); }
            to { opacity:1; transform: translateX(0); }
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-images"></i> گالری {{ project.name }}</h1>
            <a href="{{ url_for('manager_dashboard') }}"><i class="fas fa-arrow-right"></i> بازگشت</a>
        </div>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="flash-messages">
                    {% for msg in messages %}
                        <div class="flash">{{ msg }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}

        <div class="card">
            <h2><i class="fas fa-upload"></i> آپلود تصویر</h2>
            <form method="POST" action="{{ url_for('upload_gallery_image', project_id=project.id) }}" enctype="multipart/form-data" class="upload-form">
                <input type="file" name="image" accept="image/*" required>
                <input type="text" name="description" placeholder="توضیحات (اختیاری)">
                <button type="submit"><i class="fas fa-cloud-upload-alt"></i> آپلود</button>
            </form>
        </div>

        <div class="card">
            <h2><i class="fas fa-photo-video"></i> تصاویر</h2>
            <div class="gallery-grid">
                {% for img in images %}
                <div class="gallery-item">
                    <img src="{{ url_for('uploaded_file', filename=img.image_filename) }}" alt="{{ img.description }}">
                    <div class="info">
                        <div class="desc">{{ img.description or 'بدون توضیح' }}</div>
                        <div class="meta">{{ img.uploaded_at[:16] }}</div>
                    </div>
                    <form method="POST" action="{{ url_for('delete_gallery_image', image_id=img.id) }}" onsubmit="return confirm('تصویر حذف شود؟')">
                        <button type="submit" class="delete-btn"><i class="fas fa-trash-alt"></i></button>
                    </form>
                </div>
                {% else %}
                <div style="color:rgba(255,255,255,0.3); grid-column:1/-1; text-align:center; padding:40px 0;">هیچ تصویری آپلود نشده است</div>
                {% endfor %}
            </div>
        </div>
    </div>
</body>
</html>
'''

PUBLIC_GALLERY_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>گالری پروژه‌ها | آب و سازه</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: transparent;
            color: #e0e0f0;
            padding: 24px;
            direction: rtl;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; position: relative; z-index: 1; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 32px;
            background: rgba(255,255,255,0.04);
            border-radius: 32px;
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 32px;
            flex-wrap: wrap;
            gap: 16px;
        }
        .header h1 {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, #ffd700, #f0b800);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header a {
            color: #ffd700;
            text-decoration: none;
            background: rgba(255,215,0,0.08);
            padding: 10px 22px;
            border-radius: 30px;
            border: 1px solid rgba(255,215,0,0.1);
            font-weight: 600;
            transition: all 0.3s;
        }
        .header a:hover { background: rgba(255,215,0,0.15); transform: translateY(-2px); }
        .project-section {
            background: rgba(255,255,255,0.03);
            border-radius: 32px;
            padding: 28px;
            border: 1px solid rgba(255,255,255,0.05);
            backdrop-filter: blur(8px);
            margin-bottom: 32px;
        }
        .project-section h2 {
            font-size: 24px;
            font-weight: 700;
            color: #ffd700;
            margin-bottom: 8px;
        }
        .project-section .desc {
            color: rgba(255,255,255,0.5);
            margin-bottom: 16px;
            font-size: 15px;
        }
        .gallery-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 24px;
        }
        .gallery-item {
            background: rgba(255,255,255,0.04);
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.06);
            transition: 0.3s;
            cursor: default;
            user-select: none;
            -webkit-user-select: none;
        }
        .gallery-item:hover { transform: translateY(-4px); border-color: rgba(255,215,0,0.2); }
        .gallery-item img {
            width: 100%;
            height: 240px;
            object-fit: cover;
            display: block;
            pointer-events: none;
            -webkit-user-drag: none;
        }
        .gallery-item .info { padding: 12px 16px; }
        .gallery-item .info .desc {
            font-size: 14px;
            color: rgba(255,255,255,0.7);
            margin-bottom: 6px;
        }
        .gallery-item .info .meta {
            font-size: 12px;
            color: rgba(255,255,255,0.3);
        }
        .no-images {
            color: rgba(255,255,255,0.3);
            text-align: center;
            padding: 40px 0;
            grid-column: 1/-1;
        }
        .back-home {
            display: inline-block;
            margin-top: 16px;
            color: rgba(255,255,255,0.4);
            text-decoration: none;
            font-weight: 600;
            transition: 0.3s;
        }
        .back-home:hover { color: #ffd700; }
        .watermark {
            position: fixed;
            bottom: 16px;
            left: 16px;
            font-size: 12px;
            color: rgba(255,215,0,0.06);
            pointer-events: none;
            z-index: 9999;
            font-weight: 600;
            user-select: none;
        }
        @media (max-width: 600px) {
            .header { flex-direction: column; align-items: stretch; }
            .gallery-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-images"></i> گالری پروژه‌ها</h1>
            <a href="{{ url_for('index') }}"><i class="fas fa-home"></i> صفحه اصلی</a>
        </div>

        {% if projects %}
            {% for project in projects %}
            <div class="project-section">
                <h2>{{ project.name }}</h2>
                <div class="desc">{{ project.description or '' }}</div>
                <div class="gallery-grid">
                    {% set imgs = project_images[project.id] %}
                    {% if imgs %}
                        {% for img in imgs %}
                        <div class="gallery-item">
                            <img src="{{ url_for('uploaded_file', filename=img.image_filename) }}" alt="{{ img.description }}" draggable="false">
                            <div class="info">
                                <div class="desc">{{ img.description or 'بدون توضیح' }}</div>
                                <div class="meta">{{ img.uploaded_at[:16] }}</div>
                            </div>
                        </div>
                        {% endfor %}
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div style="text-align:center; padding:60px 20px; background:rgba(255,255,255,0.03); border-radius:32px; border:1px solid rgba(255,255,255,0.05);">
                <i class="fas fa-image" style="font-size:48px; color:rgba(255,215,0,0.2);"></i>
                <h3 style="color:rgba(255,255,255,0.4); margin-top:16px;">هیچ پروژه‌ای با تصویر وجود ندارد</h3>
                <p style="color:rgba(255,255,255,0.2); margin-top:8px;">به زودی تصاویر پروژه‌ها در اینجا قرار می‌گیرند</p>
            </div>
        {% endif %}

        <div class="watermark">🔒 محافظت شده</div>
    </div>
    <script>
        document.querySelectorAll('.gallery-item img').forEach(img => {
            img.addEventListener('contextmenu', e => e.preventDefault());
        });
        document.addEventListener('dragstart', e => e.preventDefault());
        document.addEventListener('copy', e => e.preventDefault());
    </script>
</body>
</html>
'''

VIEWER_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>پنل بازدیدکننده | آب و سازه</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: transparent;
            color: #e0e0f0;
            padding: 24px;
            direction: rtl;
            min-height: 100vh;
        }
        .container { max-width: 900px; margin: 0 auto; position: relative; z-index: 1; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 28px;
            background: rgba(255,255,255,0.03);
            border-radius: 32px;
            border: 1px solid rgba(255,255,255,0.05);
            margin-bottom: 32px;
            flex-wrap: wrap;
            gap: 12px;
            backdrop-filter: blur(8px);
        }
        .header h1 { font-size: 24px; font-weight: 700; color: #ffd700; }
        .header .logout {
            color: #ffd700;
            text-decoration: none;
            background: rgba(255,215,0,0.08);
            padding: 10px 22px;
            border-radius: 30px;
            border: 1px solid rgba(255,215,0,0.1);
            font-weight: 600;
            transition: all 0.3s;
        }
        .header .logout:hover { background: rgba(255,215,0,0.15); transform: translateY(-2px); }
        .card {
            background: rgba(255,255,255,0.03);
            border-radius: 32px;
            padding: 28px;
            border: 1px solid rgba(255,255,255,0.05);
            margin-bottom: 24px;
            backdrop-filter: blur(8px);
            transition: 0.3s;
        }
        .card:hover { border-color: rgba(255,215,0,0.1); }
        .card h2 {
            font-size: 20px;
            font-weight: 600;
            color: #ffd700;
            border-bottom: 1px solid rgba(255,215,0,0.08);
            padding-bottom: 12px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .task-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        .task-item:last-child { border-bottom: none; }
        .task-item.blurred {
            filter: blur(4px);
            pointer-events: none;
            opacity: 0.6;
        }
        .task-item .lock-icon { color: #ffd700; margin-left: 8px; font-size: 14px; }
        .task-status { font-weight: 600; }
        .status-done { color: #69db7c; }
        .status-progress { color: #ffd93d; }
        .status-notstarted { color: #ff6b6b; }
        .project-progress {
            margin: 12px 0;
        }
        .progress-bar {
            width: 100%;
            height: 8px;
            background: rgba(255,255,255,0.06);
            border-radius: 20px;
            overflow: hidden;
            box-shadow: inset 0 1px 3px rgba(0,0,0,0.3);
        }
        .progress-bar .fill {
            height: 100%;
            background: linear-gradient(90deg, #ffd700, #f0b800);
            border-radius: 20px;
            transition: width 0.8s;
            box-shadow: 0 0 20px rgba(255,215,0,0.15);
        }
        .chat-box {
            max-height: 300px;
            overflow-y: auto;
            margin-bottom: 16px;
            background: rgba(0,0,0,0.2);
            border-radius: 20px;
            padding: 16px;
        }
        .chat-msg {
            padding: 10px 16px;
            margin-bottom: 8px;
            background: rgba(255,255,255,0.04);
            border-radius: 16px;
            border-right: 3px solid #ffd700;
            animation: slideIn 0.3s ease-out;
        }
        @keyframes slideIn {
            from { opacity:0; transform: translateX(-10px); }
            to { opacity:1; transform: translateX(0); }
        }
        .chat-msg .time { color: rgba(255,255,255,0.3); font-size: 11px; }
        .chat-form {
            display: flex;
            gap: 12px;
        }
        .chat-form input {
            flex: 1;
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 30px;
            padding: 14px 20px;
            color: #fff;
            font-size: 14px;
            outline: none;
            font-family: inherit;
            transition: 0.3s;
        }
        .chat-form input:focus { border-color: #ffd700; box-shadow: 0 0 0 3px rgba(255,215,0,0.1); }
        .chat-form button {
            background: #ffd700;
            border: none;
            border-radius: 30px;
            padding: 14px 28px;
            color: #0b0c1a;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
        }
        .chat-form button:hover { transform: scale(1.02); box-shadow: 0 8px 24px rgba(255,215,0,0.3); }
        .watermark {
            position: fixed;
            bottom: 16px;
            left: 16px;
            font-size: 12px;
            color: rgba(255,215,0,0.06);
            pointer-events: none;
            z-index: 9999;
            font-weight: 600;
            user-select: none;
        }
        .no-perm { color: rgba(255,255,255,0.3); font-style: italic; }
        .flash-messages { margin-bottom: 16px; }
        .flash {
            padding: 12px 18px;
            border-radius: 16px;
            background: rgba(255,215,0,0.06);
            border-right: 4px solid #ffd700;
            color: #f0e6d0;
            margin-bottom: 6px;
            animation: fadeIn 0.4s;
        }
        @keyframes fadeIn {
            from { opacity:0; transform: translateX(-10px); }
            to { opacity:1; transform: translateX(0); }
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-eye"></i> پنل بازدیدکننده</h1>
            <a href="{{ url_for('logout') }}" class="logout"><i class="fas fa-sign-out-alt"></i> خروج</a>
        </div>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="flash-messages">
                    {% for msg in messages %}
                        <div class="flash">{{ msg }}</div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}

        {% for pdata in projects %}
        <div class="card">
            <h2><i class="fas fa-folder"></i> {{ pdata.project.name }}</h2>
            {% if can_view_progress %}
            <div class="project-progress">
                <div class="progress-bar"><div class="fill" style="width:{{ pdata.progress }}%;"></div></div>
                <div style="margin-top:4px; color:rgba(255,255,255,0.4); font-size:14px;">پیشرفت: {{ pdata.progress }}%</div>
            </div>
            {% endif %}
            {% for task in pdata.tasks %}
                {% if task.visible %}
                <div class="task-item">
                    <span>{{ task.title }}</span>
                    <span class="task-status
                        {% if task.status == 2 %}status-done
                        {% elif task.status == 1 %}status-progress
                        {% else %}status-notstarted{% endif %}">
                        {% if task.status == 2 %}<i class="fas fa-check-circle"></i> انجام شد
                        {% elif task.status == 1 %}<i class="fas fa-spinner fa-spin"></i> در حال انجام
                        {% else %}<i class="fas fa-clock"></i> انجام نشده{% endif %}
                    </span>
                </div>
                {% else %}
                <div class="task-item blurred">
                    <span><i class="fas fa-lock lock-icon"></i> {{ task.title }}</span>
                    <span class="task-status status-notstarted"><i class="fas fa-ban"></i> بدون دسترسی</span>
                </div>
                {% endif %}
            {% else %}
                <div class="no-perm">هیچ مرحله‌ای تعریف نشده</div>
            {% endfor %}
        </div>
        {% endfor %}

        <div class="card">
            <h2><i class="fas fa-comment-dots"></i> گفتگو با منیجر</h2>
            <div class="chat-box" id="chatBox">
                {% for msg in messages %}
                <div class="chat-msg">
                    <div>{{ msg.message }}</div>
                    <div class="time">{{ msg.timestamp[:16] }}</div>
                </div>
                {% else %}
                <div class="no-perm">هنوز پیامی ارسال نشده است</div>
                {% endfor %}
            </div>
            <form method="POST" action="{{ url_for('send_message') }}" class="chat-form">
                <input type="text" name="message" placeholder="پیام خود را بنویسید..." required>
                <button type="submit"><i class="fas fa-paper-plane"></i> ارسال</button>
            </form>
        </div>

        <div class="watermark">🔒 محافظت شده</div>
    </div>

    <script>
        document.addEventListener('contextmenu', e => e.preventDefault());
        document.addEventListener('selectstart', e => e.preventDefault());
        document.querySelectorAll('.gallery-item img').forEach(img => {
            img.addEventListener('contextmenu', e => e.preventDefault());
        });
        document.addEventListener('dragstart', e => e.preventDefault());
        const chatBox = document.getElementById('chatBox');
        if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
    </script>
</body>
</html>
'''

PERMISSIONS_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>دسترسی‌ها | {{ user.username }}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: transparent;
            color: #e0e0f0;
            padding: 30px;
            direction: rtl;
            min-height: 100vh;
        }
        .container {
            max-width: 700px;
            margin: 0 auto;
            background: rgba(255,255,255,0.03);
            border-radius: 32px;
            padding: 36px;
            border: 1px solid rgba(255,255,255,0.05);
            backdrop-filter: blur(8px);
            position: relative;
            z-index: 1;
        }
        h2 {
            color: #ffd700;
            font-weight: 600;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .task-check {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        .task-check input[type="checkbox"] {
            width: 22px;
            height: 22px;
            accent-color: #ffd700;
            cursor: pointer;
            transition: 0.2s;
        }
        .task-check input[type="checkbox"]:hover { transform: scale(1.1); }
        .task-check label { flex: 1; font-weight: 400; }
        .task-check .project-name { color: rgba(255,255,255,0.3); font-size: 12px; margin-right: 8px; }
        .btn-save {
            background: #ffd700;
            border: none;
            border-radius: 20px;
            padding: 14px 36px;
            color: #0b0c1a;
            font-weight: 700;
            cursor: pointer;
            margin-top: 24px;
            transition: all 0.3s;
            font-family: inherit;
            font-size: 16px;
        }
        .btn-save:hover { transform: scale(1.02); box-shadow: 0 8px 24px rgba(255,215,0,0.3); }
        .back-link {
            display: inline-block;
            margin-top: 20px;
            color: rgba(255,255,255,0.4);
            text-decoration: none;
            font-weight: 600;
            transition: color 0.3s;
        }
        .back-link:hover { color: #ffd700; }
        .progress-check {
            margin-top: 16px;
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .progress-check input[type="checkbox"] {
            width: 22px;
            height: 22px;
            accent-color: #ffd700;
            cursor: pointer;
        }
    </style>
</head>
<body>
    ''' + BASE_CANVAS + '''
    <div class="container">
        <h2><i class="fas fa-key" style="color:#ffd700;"></i> تنظیم دسترسی‌ها برای {{ user.username }}</h2>
        <form method="POST">
            {% for task in tasks %}
            <div class="task-check">
                <input type="checkbox" name="task_visible" value="{{ task.id }}"
                       {% if task.id in visible_task_ids %}checked{% endif %}>
                <label>{{ task.title }} <span class="project-name">({{ task.project_name }})</span></label>
            </div>
            {% endfor %}
            <div class="progress-check">
                <input type="checkbox" name="can_view_progress" value="1"
                       {% if user.can_view_progress %}checked{% endif %}>
                <label>مشاهده درصد پیشرفت کلی پروژه‌ها</label>
            </div>
            <button type="submit" class="btn-save"><i class="fas fa-save"></i> ذخیره دسترسی‌ها</button>
        </form>
        <a href="{{ url_for('manager_dashboard') }}" class="back-link"><i class="fas fa-arrow-right"></i> بازگشت به پنل مدیریت</a>
    </div>
</body>
</html>
'''

# -------------------- Run --------------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)