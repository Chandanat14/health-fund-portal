import os
import re
import json
import uuid
import qrcode
import sqlite3
import threading
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from web3 import Web3
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
import logging
from io import BytesIO
from werkzeug.utils import secure_filename
import pandas as pd
from pathlib import Path
import os
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import qrcode
from datetime import datetime
import sqlite3
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Custom Jinja2 filter for Indian number formatting
def format_number(value):
    try:
        value = int(value)
        return "{:,d}".format(value)
    except (ValueError, TypeError):
        return "0"

app = Flask(__name__)
app.jinja_env.filters['format_number'] = format_number
app.secret_key = '0b707d29e772f8012c5c0fd8c9260876c74b78cb1f3d367c'
app.config['UPLOAD_FOLDER'] = Path('static/uploads')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'pdf'}
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.permanent_session_lifetime = 3600  # Session persists for 1 hour

# Thread-local storage for SQLite connections
thread_local = threading.local()

# Blockchain setup
w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:7545'))
contract_address = '0x4Bd8C0Bfbc59AB77D900Cab75E3552Caf8b12C4F'
treasurer_address = '0x4628B62c99bCa0066C90D4bf9A59Db729d6C4410'
treasurer_private_key = '0x39c1f8421b4f0c8919f35ad6ca6da93f7b9662ad440e97a3c08741af5a59e32f'
contract_abi = [
    {
        "inputs": [],
        "stateMutability": "nonpayable",
        "type": "constructor"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "uint256", "name": "claimId", "type": "uint256"},
            {"indexed": True, "internalType": "address", "name": "hospital", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "ClaimSubmitted",
        "type": "event"
    },
    {
        "inputs": [],
        "name": "MAX_CLAIM_PER_USER",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
        "constant": True
    },
    {
        "inputs": [],
        "name": "claimCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
        "constant": True
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "claims",
        "outputs": [
            {"internalType": "uint256", "name": "id", "type": "uint256"},
            {"internalType": "address", "name": "hospital", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "enum FundAllocation.Status", "name": "status", "type": "uint8"},
            {"internalType": "address", "name": "approver", "type": "address"}
        ],
        "stateMutability": "view",
        "type": "function",
        "constant": True
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "isRegisteredHospital",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
        "constant": True
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "totalClaimed",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
        "constant": True
    },
    {
        "inputs": [],
        "name": "treasurer",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
        "constant": True
    },
    {
        "inputs": [{"internalType": "address", "name": "hospital", "type": "address"}],
        "name": "registerHospital",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "hospital", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "submitClaim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "claim_id", "type": "uint256"}],
        "name": "approveClaim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "claim_id", "type": "uint256"}],
        "name": "rejectClaim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]
contract = w3.eth.contract(address=contract_address, abi=contract_abi)

def validate_private_key(key):
    key = key[2:] if key.startswith('0x') else key
    if not re.match(r'^[0-9a-fA-F]{64}$', key):
        raise ValueError("Invalid private key: Must be a 64-character hexadecimal string")
    return '0x' + key

try:
    treasurer_private_key = validate_private_key(treasurer_private_key)
except ValueError as e:
    logger.error(f"Error: {e}")
    treasurer_private_key = None

def get_db():
    if not hasattr(thread_local, 'db'):
        conn = sqlite3.connect('health_fund.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        thread_local.db = conn
    return thread_local.db

def close_db():
    if hasattr(thread_local, 'db'):
        thread_local.db.close()
        del thread_local.db

def init_db():
    conn = sqlite3.connect('health_fund.db')
    conn.execute('PRAGMA journal_mode=WAL')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        hospital_id TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS socio_economic (
        aadhar_number TEXT PRIMARY KEY,
        name TEXT,
        address TEXT,
        date_of_birth TEXT,
        annual_income INTEGER,
        blood_group TEXT,
        spouse_name TEXT,
        spouse_aadhar_number TEXT,
        spouse_date_of_birth TEXT,
        spouse_blood_group TEXT,
        children_count INTEGER,
        children_details TEXT,
        photo_path TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS hospitals (
        hospital_id TEXT PRIMARY KEY,
        hospital_name TEXT NOT NULL,
        public_key TEXT,
        private_key TEXT,  -- Added new column
        password_hash TEXT,
        total_claims INTEGER DEFAULT 0,
        approved_claims INTEGER DEFAULT 0,
        rejected_claims INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS claims (
        claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
        hospital_id TEXT,
        patient_id TEXT,
        aadhar_number TEXT,
        operation_type TEXT,
        bill_pdf_path TEXT,
        amount_claimed INTEGER,
        place TEXT,
        status TEXT,
        treasurer_id INTEGER,
        reject_reason TEXT,
        submission_date TEXT,
        blockchain_claim_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS funds_allocation (
        allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        treasurer_id INTEGER,
        amount_allocated INTEGER,
        date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS news_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        type TEXT,
        date_added TEXT
    )''')
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ('admin', generate_password_hash('admin'), 'District Admin'))
    
    # Migration: Add private_key column if it doesn't exist
    try:
        c.execute("SELECT private_key FROM hospitals LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE hospitals ADD COLUMN private_key TEXT")
        logger.info("Added private_key column to hospitals table")
    
    # Migration: Add blockchain_claim_id column if it doesn't exist
    try:
        c.execute("SELECT blockchain_claim_id FROM claims LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE claims ADD COLUMN blockchain_claim_id INTEGER")
        logger.info("Added blockchain_claim_id column to claims table")
    
    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

logger = logging.getLogger(__name__)

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Table, TableStyle
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from pathlib import Path
import qrcode
from io import BytesIO
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def generate_certificate(
    claim_id, hospital_id, amount, patient_id,
    aadhar_number, operation_type, place,
    hospital_name, hospital_public_key
):
    # ------------------------------------------------------------------ #
    # 1. SETUP
    # ------------------------------------------------------------------ #
    output_dir = Path('static/uploads')
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_filename = f"certificate_{claim_id}.pdf"
    pdf_path = output_dir / pdf_filename

    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    width, height = letter                     # 612 × 792 pt
    margin = 0.75 * inch
    content_width = width - 2 * margin

    # ------------------------------------------------------------------ #
    # 2. COLOUR PALETTE – Using RGB tuples for compatibility
    # ------------------------------------------------------------------ #
    saffron      = colors.HexColor("#FF9933")
    india_green  = colors.HexColor("#138808")
    navy_blue    = colors.HexColor("#000080")
    bg_gray      = colors.HexColor("#F5F5F5")
    white        = colors.HexColor("#FFFFFF")
    black        = colors.HexColor("#000000")
    red          = colors.HexColor("#FF0000")
    light_grid   = colors.HexColor("#D3D3D3")
    medium_gray  = colors.HexColor("#808080")
    
    # RGB tuples for qrcode (doesn't accept HexColor)
    navy_blue_rgb = (0, 0, 0.5)
    white_rgb = (1, 1, 1)

    # ------------------------------------------------------------------ #
    # 3. BACKGROUND + DOUBLE BORDER
    # ------------------------------------------------------------------ #
    c.setFillColor(bg_gray)
    c.rect(0, 0, width, height, fill=1)

    c.setStrokeColor(navy_blue)
    c.setLineWidth(3)
    c.rect(margin/2, margin/2, width - margin, height - margin, fill=0)

    c.setLineWidth(1)
    c.setStrokeColor(saffron)
    c.rect(margin/2 + 5, margin/2 + 5, width - margin - 10, height - margin - 10, fill=0)

    # ------------------------------------------------------------------ #
    # 4. WATERMARK
    # ------------------------------------------------------------------ #
    c.saveState()
    c.setFont("Helvetica-Bold", 60)
    c.setFillColor(navy_blue)
    c.setFillAlpha(0.07)
    c.rotate(30)
    c.drawCentredString(width * 0.6, height * 0.3, "GOVT. OF INDIA")
    c.drawCentredString(width * 0.6, height * 0.6, "HEALTH FUND")
    c.restoreState()

    # ------------------------------------------------------------------ #
    # 5. HEADER – EMBLEM + TITLE
    # ------------------------------------------------------------------ #
    emblem_path = Path('static/indian_emblem.png')
    emblem_y = height - margin - 80
    emblem_x = width / 2 - 50

    if emblem_path.exists():
        c.drawImage(str(emblem_path), emblem_x, emblem_y,
                    width=100, height=100, preserveAspectRatio=True, mask='auto')
    else:
        c.setFont("Times-Bold", 14)
        c.setFillColor(red)
        c.drawCentredString(width / 2, emblem_y + 50, "[EMBLEM MISSING]")

    c.setFillColor(navy_blue)
    c.setFont("Times-Bold", 24)
    c.drawCentredString(width / 2, emblem_y - 25,
                        "HEALTH FUND ALLOCATION CERTIFICATE")

    c.setFont("Times-Italic", 12)
    c.setFillColor(india_green)
    c.drawCentredString(width / 2, emblem_y - 50,
                        "Ministry of Health & Family Welfare, Government of India")

    # ------------------------------------------------------------------ #
    # 6. DETAILS TABLE
    # ------------------------------------------------------------------ #
    start_y = emblem_y - 100
    col1_w = 3 * inch
    col2_w = content_width - col1_w

    data = [
        ["Claim ID",          f":  {claim_id}"],
        ["Hospital ID",       f":  {hospital_id}"],
        ["Hospital Name",     f":  {hospital_name}"],
        ["Patient ID",        f":  {patient_id}"],
        ["Aadhaar Number",    f":  {aadhar_number}"],
        ["Operation Type",    f":  {operation_type}"],
        ["Place of Treatment",f":  {place}"],
        ["Amount Approved",   f":  ₹{amount:,.2f}"],
        ["Date of Issue",     f":  {datetime.now().strftime('%d %B %Y')}"],
    ]

    table = Table(data, colWidths=[col1_w, col2_w])
    table.setStyle(TableStyle([
        # ---- label column ------------------------------------------------
        ('BACKGROUND', (0, 0), (0, -1), white),
        ('TEXTCOLOR',  (0, 0), (0, -1), navy_blue),
        ('FONTNAME',   (0, 0), (0, -1), 'Times-Bold'),
        ('FONTSIZE',   (0, 0), (0, -1), 11),
        ('ALIGN',      (0, 0), (0, -1), 'RIGHT'),
        ('VALIGN',     (0, 0), (-1,-1), 'MIDDLE'),

        # ---- value column ------------------------------------------------
        ('TEXTCOLOR',  (1, 0), (1, -1), black),
        ('FONTNAME',   (1, 0), (1, -1), 'Times-Roman'),
        ('FONTSIZE',   (1, 0), (1, -1), 11),
        ('ALIGN',      (1, 0), (1, -1), 'LEFT'),

        # ---- padding ----------------------------------------------------
        ('LEFTPADDING',   (0,0), (-1,-1), 12),
        ('RIGHTPADDING',  (0,0), (-1,-1), 12),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),

        # ---- borders ----------------------------------------------------
        ('GRID', (0,0), (-1,-1), 0.5, light_grid),
        ('BOX',  (0,0), (-1,-1), 1.5, navy_blue),

        # ---- highlight amount & date ------------------------------------
        ('LINEABOVE', (0,7), (-1,7), 1, saffron),
        ('LINEABOVE', (0,8), (-1,8), 1, india_green),
    ]))

    tw, th = table.wrapOn(c, content_width, height)
    table.drawOn(c, margin, start_y - th)

    # ------------------------------------------------------------------ #
    # 7. QR CODE (bottom-right)
    # ------------------------------------------------------------------ #
    qr = qrcode.QRCode(version=1, box_size=6, border=3)
    qr_data = (
        f"Claim ID: {claim_id}\n"
        f"Hospital: {hospital_name}\n"
        f"Public Key: {hospital_public_key[:40]}...\n"
        f"Amount: ₹{amount:,.2f}\n"
        f"Status: APPROVED\n"
        f"Verify at: healthfund.gov.in/verify"
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    # Use string color names instead of HexColor objects
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_io = BytesIO()
    qr_img.save(qr_io, 'PNG')
    qr_io.seek(0)

    qr_x = width - margin - 100
    qr_y = margin + 20
    c.drawImage(ImageReader(qr_io), qr_x, qr_y, width=90, height=90)

    c.setFont("Helvetica", 8)
    c.setFillColor(medium_gray)
    c.drawString(qr_x, qr_y - 10, "Scan to Verify Authenticity")

    # ------------------------------------------------------------------ #
    # 8. DIGITAL SEAL
    # ------------------------------------------------------------------ #
    seal_y = qr_y + 20
    c.setFont("Times-Italic", 10)
    c.setFillColor(navy_blue)
    c.drawCentredString(width / 2, seal_y + 30, "Digitally Signed")
    c.drawCentredString(width / 2, seal_y + 15, "Health Fund Authority")
    c.setStrokeColor(navy_blue)
    c.setLineWidth(0.5)
    c.line(width / 2 - 60, seal_y, width / 2 + 60, seal_y)

    # ------------------------------------------------------------------ #
    # 9. FOOTER
    # ------------------------------------------------------------------ #
    footer_y = margin / 2
    c.setFont("Times-Roman", 9)
    c.setFillColor(india_green)
    c.drawCentredString(width / 2, footer_y + 15, "Issued by National Health Fund Portal")
    c.setFillColor(navy_blue)
    c.drawCentredString(width / 2, footer_y,
                        "Government of India | healthfund.gov.in | Helpline: 1800-XXX-XXXX")

    # ------------------------------------------------------------------ #
    # 10. FINISH PDF + DB UPDATE
    # ------------------------------------------------------------------ #
    c.showPage()
    c.save()

    # ---- DB update (safe) ----
    conn = None
    try:
        conn = sqlite3.connect('health_fund.db')
        cur = conn.cursor()
        cur.execute(
            "UPDATE claims SET bill_pdf_path = ? WHERE claim_id = ?",
            (pdf_filename, claim_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"DB update failed for claim {claim_id}: {e}")
    finally:
        if conn:
            conn.close()

    logger.info(f"Certificate generated: {pdf_filename}")
    return str(pdf_path)



# Middleware to clear flash messages after rendering
@app.after_request
def clear_flash_messages(response):
    if request.endpoint in ['district_admin', 'socio_economic_admin', 'socio_economic_manage', 
                           'socio_economic_view', 'socio_economic_edit', 'upload_xlsx', 
                           'treasurer', 'treasurer_manage_claims', 'treasurer_claim_stats', 
                           'treasurer_hospital_stats', 'hospital_staff', 'hospital_claim_status', 
                           'hospital_change_password', 'login', 'logout', 'home']:
        if g.get('_flashes', None):
            session.pop('_flashes', None)
            logger.debug(f"Cleared flash messages for endpoint {request.endpoint}")
    return response

@app.route('/')
def home():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM news_facts WHERE type='News' ORDER BY date_added DESC")
    news = c.fetchall()
    c.execute("SELECT * FROM news_facts WHERE type='Fact' ORDER BY date_added DESC")
    facts = c.fetchall()
    c.execute("""
        SELECT h.hospital_name,
               COALESCE(COUNT(c.claim_id), 0) as total_claims,
               COALESCE(SUM(CASE WHEN c.status = 'Approved' THEN 1 ELSE 0 END), 0) as approved_claims,
               COALESCE(SUM(CASE WHEN c.status = 'Rejected' THEN 1 ELSE 0 END), 0) as rejected_claims
        FROM hospitals h
        LEFT JOIN claims c ON h.hospital_id = c.hospital_id
        GROUP BY h.hospital_id, h.hospital_name
    """)
    hospitals = c.fetchall()
    return render_template('home.html', news=news, facts=facts, hospitals=hospitals)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        if user and check_password_hash(user['password'], password):
            session.permanent = True
            session['user_id'] = user['user_id']
            session['role'] = user['role']
            session['hospital_id'] = user['hospital_id']
            logger.debug(f"User {username} logged in with role {user['role']}")
            if user['role'] == 'District Admin':
                return redirect(url_for('district_admin'))
            elif user['role'] == 'SocioEconomicAdmin':
                return redirect(url_for('socio_economic_admin'))
            elif user['role'] == 'Treasurer':
                return redirect(url_for('treasurer'))
            elif user['role'] == 'Hospital Staff':
                return redirect(url_for('hospital_staff'))
            else:
                logger.error(f"Invalid role for user {username}: {user['role']}")
                flash('Invalid role', 'error')
        else:
            logger.warning(f"Failed login attempt for username {username}")
            flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logger.debug(f"Logging out user_id {session.get('user_id')}")
    session.clear()
    flash('Logged out successfully', 'success')
    logger.debug("Displaying logout confirmation page")
    return render_template('logout.html')

@app.route('/district_admin', methods=['GET', 'POST'])
def district_admin():
    if 'role' not in session or session['role'] != 'District Admin':
        logger.warning(f"Unauthorized access to /district_admin by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as District Admin', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', '').strip()
        
        if not (username and password and role):
            logger.warning(f"Invalid form submission for user creation by user_id {session.get('user_id')}")
            flash('All fields are required', 'error')
        elif role not in ['SocioEconomicAdmin', 'Treasurer']:
            logger.warning(f"Invalid role {role} submitted by user_id {session.get('user_id')}")
            flash('Invalid role. Choose SocioEconomicAdmin or Treasurer.', 'error')
        elif len(password) < 8:
            logger.warning(f"Password too short for username {username} by user_id {session.get('user_id')}")
            flash('Password must be at least 8 characters long', 'error')
        elif not re.match(r'^[a-zA-Z0-9_]+$', username):
            logger.warning(f"Invalid username format {username} by user_id {session.get('user_id')}")
            flash('Username can only contain letters, numbers, and underscores', 'error')
        else:
            try:
                hashed_password = generate_password_hash(password)
                c.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                          (username, hashed_password, role))
                conn.commit()
                logger.info(f"User {username} with role {role} added by user_id {session.get('user_id')}")
                flash(f'{role} user {username} added successfully', 'success')
            except sqlite3.IntegrityError:
                logger.error(f"Username {username} already exists")
                flash('Username already exists', 'error')
    
    c.execute("SELECT username, role FROM users WHERE role IN ('SocioEconomicAdmin', 'Treasurer')")
    users = c.fetchall()
    return render_template('district_admin.html', users=users)

@app.route('/socio_economic_admin', methods=['GET', 'POST'])
def socio_economic_admin():
    if 'role' not in session or session['role'] != 'SocioEconomicAdmin':
        logger.warning(f"Unauthorized access to /socio_economic_admin by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as SocioEconomicAdmin', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        news_type = request.form.get('type', '').strip()
        
        if not title or not content or not news_type:
            logger.warning(f"Invalid form submission for news/fact by user_id {session.get('user_id')}")
            flash('All fields are required', 'error')
        else:
            date_added = datetime.now().strftime('%Y-%m-%d')
            try:
                c.execute('INSERT INTO news_facts (title, content, type, date_added) VALUES (?, ?, ?, ?)',
                          (title, content, news_type, date_added))
                conn.commit()
                logger.info(f"News/fact added by user_id {session.get('user_id')}: {title}")
                flash('News/Fact added successfully', 'success')
            except sqlite3.Error as e:
                logger.error(f"Error adding news/fact by user_id {session.get('user_id')}: {str(e)}")
                flash(f'Error adding news/fact: {str(e)}', 'error')
    
    return render_template('socio_economic_admin.html')

@app.route('/socio_economic_manage', methods=['GET', 'POST'])
def socio_economic_manage():
    if 'role' not in session or session['role'] != 'SocioEconomicAdmin':
        logger.warning(f"Unauthorized access to /socio_economic_manage by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as SocioEconomicAdmin', 'error')
        return redirect(url_for('login'))
    
    logger.debug(f"Accessing /socio_economic_manage with session: {session}")
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        try:
            aadhar_number = request.form.get('aadhar_number', '').strip()
            if not re.match(r'^\d{12}$', aadhar_number):
                raise ValueError("Aadhar number must be a 12-digit number")
            
            c.execute("SELECT aadhar_number FROM socio_economic WHERE aadhar_number = ?", (aadhar_number,))
            if c.fetchone():
                raise ValueError("Aadhar number already exists")
            
            name = request.form.get('name', '').strip()
            address = request.form.get('address', '').strip()
            date_of_birth = request.form.get('date_of_birth', '')
            annual_income = request.form.get('annual_income', '')
            blood_group = request.form.get('blood_group', '')
            spouse_name = request.form.get('spouse_name', '')
            spouse_aadhar_number = request.form.get('spouse_aadhar_number', '')
            spouse_date_of_birth = request.form.get('spouse_date_of_birth', '')
            spouse_blood_group = request.form.get('spouse_blood_group', '')
            children_count = request.form.get('children_count', '0')
            
            if not (name and address and date_of_birth and annual_income and blood_group):
                raise ValueError("Required fields are missing")
            
            annual_income = int(float(annual_income))
            children_count = int(float(children_count))
            
            if spouse_aadhar_number and not re.match(r'^\d{12}$', spouse_aadhar_number):
                raise ValueError("Spouse Aadhar number must be a 12-digit number")
            
            valid_blood_groups = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
            if blood_group not in valid_blood_groups:
                raise ValueError("Invalid blood group")
            if spouse_blood_group and spouse_blood_group not in valid_blood_groups:
                raise ValueError("Invalid spouse blood group")
            
            children_details = []
            for i in range(children_count):
                child_name = request.form.get(f'child_name_{i}', '')
                child_aadhar = request.form.get(f'child_aadhar_{i}', '')
                child_dob = request.form.get(f'child_dob_{i}', '')
                child_blood_group = request.form.get(f'child_blood_group_{i}', '')
                if not (child_name and child_aadhar and child_dob and child_blood_group):
                    raise ValueError(f"Missing details for child {i+1}")
                if not re.match(r'^\d{12}$', child_aadhar):
                    raise ValueError(f"Invalid Aadhar number for child {i+1}")
                if child_blood_group not in valid_blood_groups:
                    raise ValueError(f"Invalid blood group for child {i+1}")
                children_details.append({
                    'name': child_name,
                    'aadhar_number': child_aadhar,
                    'dob': child_dob,
                    'blood_group': child_blood_group
                })
            
            photo = request.files.get('photo')
            photo_path = None
            if photo and photo.filename and allowed_file(photo.filename):
                photo_filename = f"{aadhar_number}_{secure_filename(photo.filename)}"
                photo.save(app.config['UPLOAD_FOLDER'] / photo_filename)
                photo_path = photo_filename
            elif photo and photo.filename and not allowed_file(photo.filename):
                raise ValueError("Invalid photo format")
            
            c.execute('''INSERT INTO socio_economic (
                         aadhar_number, name, address, date_of_birth, annual_income,
                         blood_group, spouse_name, spouse_aadhar_number, spouse_date_of_birth,
                         spouse_blood_group, children_count, children_details, photo_path)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (aadhar_number, name, address, date_of_birth, annual_income,
                       blood_group, spouse_name, spouse_aadhar_number, spouse_date_of_birth,
                       spouse_blood_group, children_count, json.dumps(children_details),
                       photo_path))
            conn.commit()
            logger.info(f"Added socio-economic record for aadhar_number {aadhar_number} by user_id {session.get('user_id')}")
            flash('Person added successfully', 'success')
            return redirect(url_for('socio_economic_admin'))
        except Exception as e:
            logger.error(f"Error adding socio-economic data for aadhar_number {aadhar_number}: {str(e)}")
            flash(f'Error adding person: {str(e)}', 'error')
    
    return render_template('socio_economic_manage.html')

@app.route('/socio_economic_view')
def socio_economic_view():
    if 'role' not in session or session['role'] != 'SocioEconomicAdmin':
        logger.warning(f"Unauthorized access to /socio_economic_view by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as SocioEconomicAdmin', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT aadhar_number, name, annual_income, children_count, photo_path FROM socio_economic")
    people = c.fetchall()
    logger.debug(f"Fetched {len(people)} people from socio_economic")
    c.execute("SELECT claim_id, aadhar_number, status, reject_reason FROM claims")
    claims = c.fetchall()
    return render_template('socio_economic_view.html', people=people, claims=claims)

@app.route('/socio_economic_edit/<aadhar_number>', methods=['GET', 'POST'])
def socio_economic_edit(aadhar_number):
    if 'role' not in session or session['role'] != 'SocioEconomicAdmin':
        logger.warning(f"Unauthorized access to /socio_economic_edit by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as SocioEconomicAdmin', 'error')
        return redirect(url_for('login'))
    
    logger.debug(f"Accessing /socio_economic_edit for aadhar_number {aadhar_number} with session: {session}")
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        if request.form.get('delete') == 'true':
            try:
                c.execute("SELECT photo_path FROM socio_economic WHERE aadhar_number = ?", (aadhar_number,))
                person = c.fetchone()
                if person and person['photo_path']:
                    photo_path = app.config['UPLOAD_FOLDER'] / person['photo_path']
                    if photo_path.exists():
                        photo_path.unlink()
                c.execute("DELETE FROM socio_economic WHERE aadhar_number = ?", (aadhar_number,))
                conn.commit()
                logger.info(f"Deleted socio-economic record for aadhar_number {aadhar_number} by user_id {session.get('user_id')}")
                flash('Record deleted successfully', 'success')
                return redirect(url_for('socio_economic_view'))
            except sqlite3.Error as e:
                logger.error(f"Error deleting socio-economic record for aadhar_number {aadhar_number}: {str(e)}")
                flash(f'Error deleting record: {str(e)}', 'error')
                return redirect(url_for('socio_economic_edit', aadhar_number=aadhar_number))
        
        try:
            name = request.form.get('name', '').strip()
            address = request.form.get('address', '').strip()
            date_of_birth = request.form.get('date_of_birth', '')
            annual_income = request.form.get('annual_income', '')
            blood_group = request.form.get('blood_group', '')
            spouse_name = request.form.get('spouse_name', '')
            spouse_aadhar_number = request.form.get('spouse_aadhar_number', '')
            spouse_date_of_birth = request.form.get('spouse_date_of_birth', '')
            spouse_blood_group = request.form.get('spouse_blood_group', '')
            children_count = request.form.get('children_count', '0')
            
            if not (name and address and date_of_birth and annual_income and blood_group):
                raise ValueError("Required fields are missing")
            
            annual_income = int(float(annual_income))
            children_count = int(float(children_count))
            
            if spouse_aadhar_number and not re.match(r'^\d{12}$', spouse_aadhar_number):
                raise ValueError("Spouse Aadhar number must be a 12-digit number")
            
            valid_blood_groups = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
            if blood_group not in valid_blood_groups:
                raise ValueError("Invalid blood group")
            if spouse_blood_group and spouse_blood_group not in valid_blood_groups:
                raise ValueError("Invalid spouse blood group")
            
            children_details = []
            for i in range(children_count):
                child_name = request.form.get(f'child_name_{i}', '')
                child_aadhar = request.form.get(f'child_aadhar_{i}', '')
                child_dob = request.form.get(f'child_dob_{i}', '')
                child_blood_group = request.form.get(f'child_blood_group_{i}', '')
                if not (child_name and child_aadhar and child_dob and child_blood_group):
                    raise ValueError(f"Missing details for child {i+1}")
                if not re.match(r'^\d{12}$', child_aadhar):
                    raise ValueError(f"Invalid Aadhar number for child {i+1}")
                if child_blood_group not in valid_blood_groups:
                    raise ValueError(f"Invalid blood group for child {i+1}")
                children_details.append({
                    'name': child_name,
                    'aadhar_number': child_aadhar,
                    'dob': child_dob,
                    'blood_group': child_blood_group
                })
            
            photo = request.files.get('photo')
            photo_path = None
            if photo and photo.filename and allowed_file(photo.filename):
                photo_filename = f"{aadhar_number}_{secure_filename(photo.filename)}"
                photo_path = app.config['UPLOAD_FOLDER'] / photo_filename
                c.execute("SELECT photo_path FROM socio_economic WHERE aadhar_number = ?", (aadhar_number,))
                old_photo = c.fetchone()['photo_path']
                if old_photo:
                    old_photo_path = app.config['UPLOAD_FOLDER'] / old_photo
                    if old_photo_path.exists():
                        old_photo_path.unlink()
                photo.save(photo_path)
                photo_path = photo_filename
            elif photo and photo.filename and not allowed_file(photo.filename):
                raise ValueError("Invalid photo format")
            
            c.execute('''UPDATE socio_economic SET
                         name = ?, address = ?, date_of_birth = ?, annual_income = ?,
                         blood_group = ?, spouse_name = ?, spouse_aadhar_number = ?,
                         spouse_date_of_birth = ?, spouse_blood_group = ?,
                         children_count = ?, children_details = ?,
                         photo_path = COALESCE(?, photo_path)
                         WHERE aadhar_number = ?''',
                      (name, address, date_of_birth, annual_income, blood_group,
                       spouse_name, spouse_aadhar_number, spouse_date_of_birth,
                       spouse_blood_group, children_count, json.dumps(children_details),
                       photo_path, aadhar_number))
            conn.commit()
            logger.info(f"Updated socio-economic record for aadhar_number {aadhar_number} by user_id {session.get('user_id')}")
            flash('Record updated successfully', 'success')
            return redirect(url_for('socio_economic_view'))
        except Exception as e:
            logger.error(f"Error updating socio-economic data for aadhar_number {aadhar_number}: {str(e)}")
            flash(f'Error updating record: {str(e)}', 'error')
            return redirect(url_for('socio_economic_edit', aadhar_number=aadhar_number))
    
    c.execute("SELECT * FROM socio_economic WHERE aadhar_number = ?", (aadhar_number,))
    person = c.fetchone()
    if not person:
        logger.warning(f"Record not found for aadhar_number {aadhar_number}")
        flash('Record not found', 'error')
        return redirect(url_for('socio_economic_view'))
    
    person_dict = dict(person)
    person_dict['children_details'] = json.loads(person['children_details'] or '[]')
    return render_template('socio_economic_edit.html', person=person_dict)

@app.route('/upload_xlsx', methods=['POST'])
def upload_xlsx():
    if 'role' not in session or session['role'] != 'SocioEconomicAdmin':
        logger.warning(f"Unauthorized access to /upload_xlsx by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as SocioEconomicAdmin', 'error')
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    if 'file' not in request.files:
        logger.warning(f"No file uploaded in /upload_xlsx by user_id {session.get('user_id')}")
        flash('No file uploaded', 'error')
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file or not allowed_file(file.filename):
        logger.warning(f"Invalid file format: {file.filename if file else 'None'} by user_id {session.get('user_id')}")
        flash('Invalid file format', 'error')
        return jsonify({'success': False, 'error': 'Invalid file format'}), 400
    
    try:
        df = pd.read_excel(file, engine='openpyxl')
        conn = get_db()
        c = conn.cursor()
        success_count = 0
        error_count = 0
        
        for _, row in df.iterrows():
            aadhar_number = str(row.get('aadhar_number', '')).strip()
            if not re.match(r'^\d{12}$', aadhar_number):
                logger.warning(f"Skipping invalid Aadhar in XLSX: {aadhar_number}")
                error_count += 1
                continue
            
            c.execute("SELECT aadhar_number FROM socio_economic WHERE aadhar_number = ?", (aadhar_number,))
            if c.fetchone():
                logger.warning(f"Skipping duplicate Aadhar in XLSX: {aadhar_number}")
                error_count += 1
                continue
            
            children_details = row.get('children_details', '')
            try:
                children_data = json.loads(children_details) if children_details else []
                for child in children_data:
                    if not re.match(r'^\d{12}$', child.get('aadhar_number', '')):
                        logger.warning(f"Skipping invalid child Aadhar in XLSX: {child.get('aadhar_number')}")
                        error_count += 1
                        continue
            except json.JSONDecodeError:
                logger.warning(f"Skipping invalid children details JSON in XLSX: {children_details}")
                error_count += 1
                continue
            
            try:
                annual_income = int(float(row.get('annual_income', 0)))
                children_count = int(float(row.get('children_count', 0)))
                spouse_aadhar = str(row.get('spouse_aadhar_number', '')).strip()
                if spouse_aadhar and not re.match(r'^\d{12}$', spouse_aadhar):
                    logger.warning(f"Skipping invalid spouse Aadhar in XLSX: {spouse_aadhar}")
                    error_count += 1
                    continue
                
                valid_blood_groups = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
                blood_group = str(row.get('blood_group', '')).strip()
                spouse_blood_group = str(row.get('spouse_blood_group', '')).strip()
                if blood_group and blood_group not in valid_blood_groups:
                    logger.warning(f"Skipping invalid blood group in XLSX: {blood_group}")
                    error_count += 1
                    continue
                if spouse_blood_group and spouse_blood_group not in valid_blood_groups:
                    logger.warning(f"Skipping invalid spouse blood group in XLSX: {spouse_blood_group}")
                    error_count += 1
                    continue
                
                c.execute('''INSERT OR IGNORE INTO socio_economic (
                    aadhar_number, name, address, date_of_birth, annual_income, blood_group,
                    spouse_name, spouse_aadhar_number, spouse_date_of_birth, spouse_blood_group,
                    children_count, children_details, photo_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (aadhar_number, 
                     str(row.get('name', '')).strip(),
                     str(row.get('address', '')).strip(),
                     str(row.get('date_of_birth', '')),
                     annual_income,
                     blood_group,
                     str(row.get('spouse_name', '')).strip(),
                     spouse_aadhar,
                     str(row.get('spouse_date_of_birth', '')),
                     spouse_blood_group,
                     children_count,
                     json.dumps(children_data) if children_data else '[]',
                     None))
                success_count += 1
            except (ValueError, sqlite3.Error) as e:
                logger.warning(f"Error processing XLSX row for Aadhar {aadhar_number}: {str(e)}")
                error_count += 1
                continue
        
        conn.commit()
        logger.info(f"XLSX upload processed: {success_count} records added, {error_count} errors by user_id {session.get('user_id')}")
        flash(f'XLSX processed: {success_count} records added, {error_count} errors', 'success' if success_count > 0 else 'error')
        return jsonify({'success': True, 'message': f'{success_count} records added, {error_count} errors'}), 200
    except Exception as e:
        logger.error(f"Error processing XLSX upload by user_id {session.get('user_id')}: {str(e)}")
        flash(f'Error processing XLSX: {str(e)}', 'error')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/treasurer', methods=['GET', 'POST'])
def treasurer():
    if 'role' not in session or session['role'] != 'Treasurer':
        logger.warning(f"Unauthorized access to /treasurer by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as Treasurer', 'error')
        return redirect(url_for('login'))
    
    if not treasurer_private_key:
        flash('Blockchain configuration error: Invalid private key', 'error')
        return render_template('treasurer.html')
    
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        hospital_id = request.form.get('hospital_id', '').strip()
        hospital_name = request.form.get('hospital_name', '').strip()
        public_key = request.form.get('public_key', '').strip()
        private_key = request.form.get('private_key', '').strip()  # New field for hospital private key
        password = request.form.get('password', '')
        
        if not (hospital_id and hospital_name and public_key and private_key and password):
            flash('All fields are required', 'error')
            return render_template('treasurer.html')
        
        try:
            # Validate private key
            private_key = validate_private_key(private_key)
            c.execute('INSERT INTO hospitals (hospital_id, hospital_name, public_key, private_key, total_claims, approved_claims, rejected_claims) VALUES (?, ?, ?, ?, ?, ?, ?)',
                      (hospital_id, hospital_name, public_key, private_key, 0, 0, 0))
            c.execute('INSERT INTO users (username, password, role, hospital_id) VALUES (?, ?, ?, ?)',
                      (hospital_id, generate_password_hash(password), 'Hospital Staff', hospital_id))
            conn.commit()
            tx = contract.functions.registerHospital(public_key).build_transaction({
                'from': treasurer_address,
                'nonce': w3.eth.get_transaction_count(treasurer_address),
                'gas': 2000000,
                'gasPrice': w3.to_wei('20', 'gwei')
            })
            signed_tx = w3.eth.account.sign_transaction(tx, treasurer_private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            w3.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(f"Hospital {hospital_id} registered by user_id {session.get('user_id')}")
            flash('Hospital registered successfully', 'success')
        except Exception as e:
            if 'Only treasurer can call this function' in str(e):
                actual_treasurer = contract.functions.treasurer().call()
                flash(f'Error: Only the treasurer account ({actual_treasurer}) can register hospitals. Update treasurer_address in app.py.', 'error')
            else:
                logger.error(f"Error registering hospital {hospital_id}: {str(e)}")
                flash(f'Error registering hospital: {str(e)}', 'error')
    
    return render_template('treasurer.html')

@app.route('/treasurer_manage_claims', methods=['GET', 'POST'])
def treasurer_manage_claims():
    if 'role' not in session or session['role'] != 'Treasurer':
        logger.warning(f"Unauthorized access to /treasurer_manage_claims by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as Treasurer', 'error')
        return redirect(url_for('login'))
    
    if not treasurer_private_key:
        flash('Blockchain configuration error: Invalid private key', 'error')
        return render_template('treasurer_manage_claims.html', pending_claims=[])
    
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        try:
            claim_id = int(request.form.get('claim_id', 0))
            action = request.form.get('action', '')  # Expected: 'approve' or 'reject'
            reject_reason = request.form.get('reject_reason', '') if action == 'reject' else ''
            if not claim_id or action not in ['approve', 'reject']:
                raise ValueError("Invalid form submission")
        except (KeyError, ValueError) as e:
            logger.error(f"Form submission error for claim_id {request.form.get('claim_id', 'unknown')}: {str(e)}")
            flash('Invalid form submission', 'error')
            return redirect(url_for('treasurer_manage_claims'))
        
        c.execute("SELECT status, hospital_id, amount_claimed, patient_id, aadhar_number, operation_type, place, blockchain_claim_id FROM claims WHERE claim_id = ?", (claim_id,))
        claim = c.fetchone()
        if not claim:
            flash('Claim not found', 'error')
            return redirect(url_for('treasurer_manage_claims'))
        if claim['status'] != 'Pending':
            flash(f'Claim {claim_id} is already {claim["status"]}', 'error')
            return redirect(url_for('treasurer_manage_claims'))
        
        blockchain_claim_id = claim['blockchain_claim_id']
        if not blockchain_claim_id:
            flash('Blockchain claim ID not found', 'error')
            return redirect(url_for('treasurer_manage_claims'))
        
        try:
            claim_data = contract.functions.claims(blockchain_claim_id).call()
            blockchain_status = claim_data[3]  # Status is the 4th field
            status_map = {0: 'Pending', 1: 'Approved', 2: 'Rejected'}
            blockchain_status_str = status_map.get(blockchain_status, 'Unknown')
            
            if blockchain_status != 0:
                flash(f'Claim {claim_id} is already {blockchain_status_str} on blockchain', 'error')
                c.execute("UPDATE claims SET status = ? WHERE claim_id = ?", (blockchain_status_str, claim_id))
                if blockchain_status == 2:
                    c.execute("UPDATE claims SET reject_reason = 'Synchronized from blockchain' WHERE claim_id = ? AND reject_reason IS NULL", (claim_id,))
                conn.commit()
                return redirect(url_for('treasurer_manage_claims'))
        except Exception as e:
            logger.error(f"Error checking blockchain status for claim {claim_id} (blockchain ID {blockchain_claim_id}): {str(e)}")
            flash(f'Error checking blockchain status: {str(e)}', 'error')
            return redirect(url_for('treasurer_manage_claims'))
        
        try:
            hospital_id = claim['hospital_id']
            c.execute("SELECT hospital_name, public_key FROM hospitals WHERE hospital_id = ?", (hospital_id,))
            hospital = c.fetchone()
            if not hospital:
                flash('Hospital not found', 'error')
                return redirect(url_for('treasurer_manage_claims'))
            
            hospital_name = hospital['hospital_name']
            hospital_public_key = hospital['public_key']
            
            logger.debug(f"Attempting to {action} claim {claim_id} (blockchain ID {blockchain_claim_id}) on blockchain")
            
            if action == 'approve':
                tx = contract.functions.approveClaim(blockchain_claim_id).build_transaction({
                    'from': treasurer_address,
                    'nonce': w3.eth.get_transaction_count(treasurer_address),
                    'gas': 2000000,
                    'gasPrice': w3.to_wei('20', 'gwei')
                })
                signed_tx = w3.eth.account.sign_transaction(tx, treasurer_private_key)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                logger.debug(f"Approve transaction hash: {tx_hash.hex()}, status: {receipt['status']}")
                if receipt['status'] == 0:
                    raise Exception("Transaction failed")
                c.execute("UPDATE claims SET status = 'Approved', treasurer_id = ?, reject_reason = NULL WHERE claim_id = ?", 
                          (session['user_id'], claim_id))
                c.execute("UPDATE hospitals SET approved_claims = approved_claims + 1 WHERE hospital_id = ?", (hospital_id,))
                conn.commit()
                generate_certificate(
                    claim_id, hospital_id, claim['amount_claimed'], claim['patient_id'],
                    claim['aadhar_number'], claim['operation_type'], claim['place'], hospital_name, hospital_public_key
                )
                flash('Claim approved and certificate generated', 'success')
            elif action == 'reject':
                if not reject_reason:
                    flash('Reject reason is required', 'error')
                    return redirect(url_for('treasurer_manage_claims'))
                tx = contract.functions.rejectClaim(blockchain_claim_id).build_transaction({
                    'from': treasurer_address,
                    'nonce': w3.eth.get_transaction_count(treasurer_address),
                    'gas': 2000000,
                    'gasPrice': w3.to_wei('20', 'gwei')
                })
                signed_tx = w3.eth.account.sign_transaction(tx, treasurer_private_key)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                logger.debug(f"Reject transaction hash: {tx_hash.hex()}, status: {receipt['status']}")
                if receipt['status'] == 0:
                    raise Exception("Transaction failed")
                c.execute("UPDATE claims SET status = 'Rejected', treasurer_id = ?, reject_reason = ? WHERE claim_id = ?", 
                          (session['user_id'], reject_reason, claim_id))
                c.execute("UPDATE hospitals SET rejected_claims = rejected_claims + 1 WHERE hospital_id = ?", (hospital_id,))
                conn.commit()
                flash(f'Claim rejected: {reject_reason}', 'success')
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error processing claim {claim_id} (blockchain ID {blockchain_claim_id}): {error_str}")
            if 'Claim does not exist' in error_str:
                flash(f'Claim {claim_id} does not exist on blockchain', 'error')
            elif 'Claim already processed' in error_str:
                flash(f'Claim {claim_id} is already processed on blockchain', 'error')
                try:
                    claim_data = contract.functions.claims(blockchain_claim_id).call()
                    blockchain_status = claim_data[3]
                    status_map = {0: 'Pending', 1: 'Approved', 2: 'Rejected'}
                    blockchain_status_str = status_map.get(blockchain_status, 'Unknown')
                    c.execute("UPDATE claims SET status = ? WHERE claim_id = ?", (blockchain_status_str, claim_id))
                    if blockchain_status == 2:
                        c.execute("UPDATE claims SET reject_reason = 'Synchronized from blockchain' WHERE claim_id = ? AND reject_reason IS NULL", (claim_id,))
                    conn.commit()
                    flash(f'Claim status synchronized to {blockchain_status_str}', 'info')
                except Exception as sync_e:
                    logger.error(f"Error synchronizing claim {claim_id} status: {str(sync_e)}")
                    flash(f'Error synchronizing claim status: {str(sync_e)}', 'error')
            else:
                flash(f'Error processing claim: {error_str}', 'error')
    
    c.execute("SELECT * FROM claims WHERE status = 'Pending'")
    pending_claims = c.fetchall()
    logger.debug(f"Fetched {len(pending_claims)} pending claims")
    return render_template('treasurer_manage_claims.html', pending_claims=pending_claims)

@app.route('/treasurer_claim_stats')
def treasurer_claim_stats():
    if 'role' not in session or session['role'] != 'Treasurer':
        logger.warning(f"Unauthorized access to /treasurer_claim_stats by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as Treasurer', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT h.hospital_id, h.hospital_name, h.total_claims, h.approved_claims, h.rejected_claims,
               COALESCE(SUM(CASE WHEN c.status = 'Pending' THEN 1 ELSE 0 END), 0) as pending_claims,
               COALESCE(SUM(CASE WHEN c.status = 'Approved' THEN c.amount_claimed ELSE 0 END), 0) as total_approved_amount,
               COALESCE(SUM(c.amount_claimed), 0) as total_amount
        FROM hospitals h
        LEFT JOIN claims c ON h.hospital_id = c.hospital_id
        GROUP BY h.hospital_id, h.hospital_name, h.total_claims, h.approved_claims, h.rejected_claims
    """)
    hospital_stats = c.fetchall()
    
    c.execute("""
        SELECT COALESCE(COUNT(*), 0) as total,
               COALESCE(SUM(CASE WHEN c.status = 'Approved' THEN 1 ELSE 0 END), 0) as approved,
               COALESCE(SUM(CASE WHEN c.status = 'Rejected' THEN 1 ELSE 0 END), 0) as rejected,
               COALESCE(SUM(CASE WHEN c.status = 'Pending' THEN 1 ELSE 0 END), 0) as pending,
               COALESCE(SUM(CASE WHEN c.status = 'Approved' THEN c.amount_claimed ELSE 0 END), 0) as total_amount
        FROM claims c
    """)
    overall_stats = c.fetchone()
    
    return render_template('treasurer_claim_stats.html', hospital_stats=hospital_stats, overall_stats=overall_stats)

@app.route('/download_bill/<claim_id>')
def download_bill(claim_id):
    if 'role' not in session or session['role'] not in ['Treasurer', 'Hospital Staff']:
        logger.warning(f"Unauthorized access to /download_bill by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Unauthorized access', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bill_pdf_path, hospital_id FROM claims WHERE claim_id = ?", (claim_id,))
    claim = c.fetchone()
    if not claim or not claim['bill_pdf_path']:
        flash('Certificate PDF not found', 'error')
        return redirect(url_for('treasurer_manage_claims' if session['role'] == 'Treasurer' else 'hospital_claim_status'))
    
    # Restrict Hospital Staff to their own hospital's claims
    if session['role'] == 'Hospital Staff' and claim['hospital_id'] != session['hospital_id']:
        logger.warning(f"Hospital Staff user_id {session.get('user_id')} attempted to access claim {claim_id} from another hospital")
        flash('Unauthorized access to this claim', 'error')
        return redirect(url_for('hospital_claim_status'))
    
    pdf_path = app.config['UPLOAD_FOLDER'] / claim['bill_pdf_path']
    if not pdf_path.exists():
        flash('Certificate PDF file missing', 'error')
        return redirect(url_for('treasurer_manage_claims' if session['role'] == 'Treasurer' else 'hospital_claim_status'))
    
    return send_file(pdf_path, as_attachment=True, download_name=f"certificate_{claim_id}.pdf")

@app.route('/treasurer_hospital_stats')
def treasurer_hospital_stats():
    if 'role' not in session or session['role'] != 'Treasurer':
        logger.warning(f"Unauthorized access to /treasurer_hospital_stats by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as Treasurer', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT h.hospital_id, h.hospital_name,
               COUNT(c.claim_id) as total_claims,
               SUM(CASE WHEN c.status = 'Approved' THEN 1 ELSE 0 END) as approved_claims,
               SUM(CASE WHEN c.status = 'Pending' THEN 1 ELSE 0 END) as pending_claims,
               SUM(CASE WHEN c.status = 'Rejected' THEN 1 ELSE 0 END) as rejected_claims,
               SUM(c.amount_claimed) as total_amount
        FROM hospitals h
        LEFT JOIN claims c ON h.hospital_id = c.hospital_id
        GROUP BY h.hospital_id, h.hospital_name
    """)
    hospital_stats = c.fetchall()
    hospital_stats = [dict(row) for row in hospital_stats]
    return render_template('treasurer_hospital_stats.html', hospital_stats=hospital_stats)

@app.route('/hospital_staff', methods=['GET', 'POST'])
def hospital_staff():
    if 'role' not in session or session['role'] != 'Hospital Staff':
        logger.warning(f"Unauthorized access to /hospital_staff by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as Hospital Staff', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    hospital_id = session['hospital_id']
    
    if request.method == 'POST':
        patient_id = request.form.get('patient_id', '')
        aadhar_number = request.form.get('aadhar_number', '')
        operation_type = request.form.get('operation_type', '')
        try:
            amount = int(float(request.form.get('amount_claimed', 0)))
        except (ValueError, TypeError):
            flash('Amount claimed must be a valid number', 'error')
            return redirect(url_for('hospital_staff'))
        place = request.form.get('place', '')
        bill_pdf = request.files.get('bill_pdf')
        claim_id = request.form.get('claim_id')  # For re-upload
        
        if not (patient_id and aadhar_number and operation_type and amount and place and bill_pdf):
            flash('All fields are required', 'error')
            return redirect(url_for('hospital_staff'))
        
        c.execute("SELECT aadhar_number, spouse_aadhar_number FROM socio_economic WHERE aadhar_number = ? OR spouse_aadhar_number = ?", 
                  (aadhar_number, aadhar_number))
        person = c.fetchone()
        if not person:
            flash('Aadhaar number not found in socio-economic database', 'error')
            return redirect(url_for('hospital_staff'))
        
        family_aadhars = [person['aadhar_number'], person['spouse_aadhar_number']] if person['spouse_aadhar_number'] else [person['aadhar_number']]
        current_year = datetime.now().strftime('%Y')
        c.execute("SELECT SUM(amount_claimed) as total FROM claims WHERE (aadhar_number IN (?, ?) OR aadhar_number = ?) AND status = 'Approved' AND submission_date LIKE ?",
                  (person['aadhar_number'], person['spouse_aadhar_number'] or '', aadhar_number, f'{current_year}%'))
        total_claimed = c.fetchone()['total'] or 0
        if total_claimed + amount > 500000:
            flash(f'Claim exceeds family annual limit of 500000 (current total: {total_claimed})', 'error')
            return redirect(url_for('hospital_staff'))
        
        c.execute("SELECT public_key, private_key FROM hospitals WHERE hospital_id = ?", (hospital_id,))
        hospital = c.fetchone()
        if not hospital:
            flash('Hospital not registered', 'error')
            return redirect(url_for('hospital_staff'))
        hospital_public_key = hospital['public_key']
        hospital_private_key = hospital['private_key']
        
        if bill_pdf and allowed_file(bill_pdf.filename):
            pdf_filename = f"{uuid.uuid4()}.pdf"
            bill_pdf.save(app.config['UPLOAD_FOLDER'] / pdf_filename)
            submission_date = datetime.now().strftime('%Y-%m-%d')
            try:
                if claim_id:  # Re-upload for rejected claim
                    c.execute("SELECT bill_pdf_path, status, blockchain_claim_id FROM claims WHERE claim_id = ? AND hospital_id = ?",
                              (claim_id, hospital_id))
                    old_claim = c.fetchone()
                    if not old_claim:
                        flash('Invalid or unauthorized claim for re-upload', 'error')
                        return redirect(url_for('hospital_staff'))
                    if old_claim['status'] != 'Rejected':
                        flash(f'Claim {claim_id} is {old_claim["status"]}, cannot re-upload', 'error')
                        return redirect(url_for('hospital_staff'))
                    old_pdf_path = app.config['UPLOAD_FOLDER'] / old_claim['bill_pdf_path']
                    if old_pdf_path.exists():
                        old_pdf_path.unlink()
                    blockchain_claim_id = old_claim['blockchain_claim_id']
                    c.execute("UPDATE claims SET bill_pdf_path = ?, status = 'Pending', reject_reason = NULL, submission_date = ?, amount_claimed = ? WHERE claim_id = ?",
                              (pdf_filename, submission_date, amount, claim_id))
                    # Resubmit to blockchain
                    hospital_account = w3.eth.account.from_key(hospital_private_key)
                    tx = contract.functions.submitClaim(hospital_public_key, amount).build_transaction({
                        'from': hospital_account.address,
                        'nonce': w3.eth.get_transaction_count(hospital_account.address),
                        'gas': 2000000,
                        'gasPrice': w3.to_wei('20', 'gwei')
                    })
                    signed_tx = w3.eth.account.sign_transaction(tx, hospital_private_key)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                    if receipt['status'] == 0:
                        raise Exception("Transaction failed")
                    # Get new blockchain claim_id from event
                    for log in receipt['logs']:
                        if log['address'].lower() == contract_address.lower():
                            event = contract.events.ClaimSubmitted().process_log(log)
                            blockchain_claim_id = event['args']['claimId']
                            break
                    else:
                        raise Exception("ClaimSubmitted event not found")
                    c.execute("UPDATE claims SET blockchain_claim_id = ? WHERE claim_id = ?", (blockchain_claim_id, claim_id))
                    c.execute("UPDATE hospitals SET total_claims = total_claims + 1 WHERE hospital_id = ?", (hospital_id,))
                    conn.commit()
                    flash('Document re-uploaded and claim resubmitted successfully', 'success')
                else:  # New claim
                    c.execute('''INSERT INTO claims (hospital_id, patient_id, aadhar_number, operation_type, 
                        bill_pdf_path, amount_claimed, place, status, submission_date) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (hospital_id, patient_id, aadhar_number, operation_type, pdf_filename, amount, place, 'Pending', submission_date))
                    claim_id = c.lastrowid
                    hospital_account = w3.eth.account.from_key(hospital_private_key)
                    tx = contract.functions.submitClaim(hospital_public_key, amount).build_transaction({
                        'from': hospital_account.address,
                        'nonce': w3.eth.get_transaction_count(hospital_account.address),
                        'gas': 2000000,
                        'gasPrice': w3.to_wei('20', 'gwei')
                    })
                    signed_tx = w3.eth.account.sign_transaction(tx, hospital_private_key)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                    if receipt['status'] == 0:
                        raise Exception("Transaction failed")
                    # Get blockchain claim_id from event
                    blockchain_claim_id = None
                    for log in receipt['logs']:
                        if log['address'].lower() == contract_address.lower():
                            event = contract.events.ClaimSubmitted().process_log(log)
                            blockchain_claim_id = event['args']['claimId']
                            break
                    else:
                        raise Exception("ClaimSubmitted event not found")
                    c.execute("UPDATE claims SET blockchain_claim_id = ? WHERE claim_id = ?", (blockchain_claim_id, claim_id))
                    c.execute("UPDATE hospitals SET total_claims = total_claims + 1 WHERE hospital_id = ?", (hospital_id,))
                    conn.commit()
                    flash('Claim submitted successfully', 'success')
            except Exception as e:
                logger.error(f"Error submitting claim {claim_id or 'new'} to blockchain: {str(e)}")
                if not claim_id:  # Delete new claim if blockchain submission fails
                    c.execute("DELETE FROM claims WHERE claim_id = ?", (claim_id,))
                conn.commit()
                flash(f'Error submitting claim to blockchain: {str(e)}', 'error')
        else:
            flash('Invalid bill PDF format', 'error')
    
    c.execute("SELECT hospital_name FROM hospitals WHERE hospital_id = ?", (hospital_id,))
    hospital = c.fetchone()
    hospital_name = hospital['hospital_name'] if hospital else 'Unknown'
    return render_template('hospital_staff.html', hospital_name=hospital_name)

@app.route('/hospital_claim_status')
def hospital_claim_status():
    if 'role' not in session or session['role'] != 'Hospital Staff':
        logger.warning(f"Unauthorized access to /hospital_claim_status by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as Hospital Staff', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    hospital_id = session['hospital_id']
    c.execute("SELECT * FROM claims WHERE hospital_id = ? ORDER BY submission_date DESC", (hospital_id,))
    claims = c.fetchall()
    c.execute("SELECT hospital_name FROM hospitals WHERE hospital_id = ?", (hospital_id,))
    hospital = c.fetchone()
    hospital_name = hospital['hospital_name'] if hospital else 'Unknown'
    return render_template('hospital_claim_status.html', claims=claims, hospital_name=hospital_name)

@app.route('/hospital_change_password', methods=['GET', 'POST'])
def hospital_change_password():
    if 'role' not in session or session['role'] != 'Hospital Staff':
        logger.warning(f"Unauthorized access to /hospital_change_password by user_id {session.get('user_id')} with role {session.get('role')}")
        flash('Please log in as Hospital Staff', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    hospital_id = session['hospital_id']
    
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not (current_password and new_password and confirm_password):
            flash('All fields are required', 'error')
            return redirect(url_for('hospital_change_password'))
        
        if new_password != confirm_password:
            flash('New password and confirmation do not match', 'error')
            return redirect(url_for('hospital_change_password'))
        
        if len(new_password) < 8:
            flash('New password must be at least 8 characters long', 'error')
            return redirect(url_for('hospital_change_password'))
        
        c.execute("SELECT password FROM users WHERE username = ? AND role = 'Hospital Staff'", (hospital_id,))
        user = c.fetchone()
        if not user or not check_password_hash(user['password'], current_password):
            flash('Current password is incorrect', 'error')
            return redirect(url_for('hospital_change_password'))
        
        try:
            hashed_password = generate_password_hash(new_password)
            c.execute("UPDATE users SET password = ? WHERE username = ? AND role = 'Hospital Staff'",
                      (hashed_password, hospital_id))
            conn.commit()
            logger.info(f"Password changed for hospital_id {hospital_id} by user_id {session.get('user_id')}")
            flash('Password changed successfully', 'success')
            return redirect(url_for('hospital_staff'))
        except sqlite3.Error as e:
            logger.error(f"Error changing password for hospital_id {hospital_id}: {str(e)}")
            flash(f'Error changing password: {str(e)}', 'error')
    
    c.execute("SELECT hospital_name FROM hospitals WHERE hospital_id = ?", (hospital_id,))
    hospital = c.fetchone()
    hospital_name = hospital['hospital_name'] if hospital else 'Unknown'
    return render_template('hospital_change_password.html', hospital_name=hospital_name)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)