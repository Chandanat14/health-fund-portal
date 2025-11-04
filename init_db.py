import sqlite3
from werkzeug.security import generate_password_hash

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
        private_key TEXT,  -- Added to store hospital private key
        password_hash TEXT,
        total_claims INTEGER DEFAULT 0,
        approved_claims INTEGER DEFAULT 0,
        rejected_claims INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS claims (
        claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
        blockchain_claim_id INTEGER,  -- Added to store blockchain claim_id
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
        submission_date TEXT
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
    conn.commit()
    conn.close()