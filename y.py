
import sqlite3

def migrate_db():
    conn = sqlite3.connect('health_fund.db')
    conn.execute('PRAGMA journal_mode=WAL')
    c = conn.cursor()
    
    # Add reject_reason and submission_date to claims
    c.execute("PRAGMA table_info(claims)")
    columns = [col[1] for col in c.fetchall()]
    if 'reject_reason' not in columns:
        c.execute("ALTER TABLE claims ADD COLUMN reject_reason TEXT")
    if 'submission_date' not in columns:
        c.execute("ALTER TABLE claims ADD COLUMN submission_date TEXT")
        c.execute("UPDATE claims SET submission_date = '2025-01-01' WHERE submission_date IS NULL")
    
    # Create new socio_economic table
    c.execute('''CREATE TABLE IF NOT EXISTS socio_economic_new (
        aadhar_number TEXT PRIMARY KEY,
        name TEXT,
        address TEXT,
        date_of_birth TEXT,
        annual_income REAL,
        blood_group TEXT,
        spouse_name TEXT,
        spouse_aadhar_number TEXT,
        spouse_date_of_birth TEXT,
        spouse_blood_group TEXT,
        children_count INTEGER,
        children_details TEXT,
        photo_path TEXT
    )''')
    
    # Migrate data from old socio_economic table
    c.execute("PRAGMA table_info(socio_economic)")
    old_columns = [col[1] for col in c.fetchall()]
    if old_columns:
        c.execute("INSERT INTO socio_economic_new (aadhar_number, name, date_of_birth, annual_income, photo_path) SELECT aadhar_number, name, date_of_birth, annual_income, photo_path FROM socio_economic")
        c.execute("DROP TABLE socio_economic")
        c.execute("ALTER TABLE socio_economic_new RENAME TO socio_economic")
    
    # Clean photo_path to remove 'uploads\' or 'uploads/'
    c.execute("UPDATE socio_economic SET photo_path = REPLACE(REPLACE(photo_path, 'uploads\\', ''), 'uploads/', '') WHERE photo_path IS NOT NULL")
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate_db()