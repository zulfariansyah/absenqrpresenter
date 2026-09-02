import sqlite3
import random
import string
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seminar.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn

from werkzeug.security import generate_password_hash, check_password_hash

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS presentations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            judul TEXT NOT NULL,
            ruangan TEXT DEFAULT '-',
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qr_code TEXT UNIQUE NOT NULL,
            nim_nip TEXT NOT NULL,
            nama_lengkap TEXT NOT NULL,
            no_hp TEXT DEFAULT '',
            institusi TEXT NOT NULL,
            pekerjaan TEXT NOT NULL,
            presentation_id INTEGER,
            judul_presentasi TEXT DEFAULT '',
            ruangan TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pendaftar',
            created_at TEXT NOT NULL,
            attended_at TEXT,
            FOREIGN KEY (presentation_id) REFERENCES presentations(id) ON DELETE SET NULL
        )
    """)
    
    # Migrasi otomatis jika kolom belum ada pada participants
    cursor.execute("PRAGMA table_info(participants)")
    columns = [col['name'] for col in cursor.fetchall()]
    if 'no_hp' not in columns:
        cursor.execute("ALTER TABLE participants ADD COLUMN no_hp TEXT DEFAULT ''")
    if 'presentation_id' not in columns:
        cursor.execute("ALTER TABLE participants ADD COLUMN presentation_id INTEGER DEFAULT NULL")
    if 'judul_presentasi' not in columns:
        cursor.execute("ALTER TABLE participants ADD COLUMN judul_presentasi TEXT DEFAULT ''")
    if 'ruangan' not in columns:
        cursor.execute("ALTER TABLE participants ADD COLUMN ruangan TEXT DEFAULT ''")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nama TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL,
            last_login TEXT
        )
    """)
    # Set default event settings if not exist
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('event_name', 'Seminar & Konferensi Presenter 2026')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('event_logo', '')")
    
    # Inisialisasi 5 User Admin Bawaan
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    default_hash = generate_password_hash('admin123', method='pbkdf2:sha256')
    
    default_admins = [
        ('admin', default_hash, 'Super Admin', 'superadmin', now_str),
        ('petugas1', default_hash, 'Petugas Absensi 1', 'admin', now_str),
        ('petugas2', default_hash, 'Petugas Absensi 2', 'admin', now_str),
        ('petugas3', default_hash, 'Petugas Absensi 3', 'admin', now_str),
        ('petugas4', default_hash, 'Petugas Absensi 4', 'admin', now_str),
    ]
    
    for u, h, n, r, c in default_admins:
        cursor.execute("""
            INSERT OR IGNORE INTO admins (username, password_hash, nama, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (u, h, n, r, c))
    
    conn.commit()
    conn.close()

def verify_admin(username, password):
    """Memverifikasi username dan password admin, mengembalikan objek admin jika valid"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admins WHERE username = ?", (username.strip(),))
    admin = cursor.fetchone()
    conn.close()
    
    if not admin:
        return None
        
    try:
        if check_password_hash(admin['password_hash'], password):
            return dict(admin)
    except Exception:
        pass
            
    return None

def update_admin_last_login(admin_id):
    """Memperbarui timestamp login terakhir admin"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE admins SET last_login = ? WHERE id = ?", (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), admin_id
    ))
    conn.commit()
    conn.close()

def get_all_admins():
    """Mengambil daftar seluruh user admin"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, nama, role, created_at, last_login FROM admins ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_admin_by_id(admin_id):
    """Mengambil data admin berdasarkan ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, nama, role, created_at, last_login FROM admins WHERE id = ?", (admin_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_admin_password(admin_id, new_password):
    """Mengatur/mengubah password admin tertentu (fitur Super Admin & ganti password sendiri)"""
    if not new_password or not new_password.strip():
        return False
    hash_val = generate_password_hash(new_password.strip(), method='pbkdf2:sha256')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE admins SET password_hash = ? WHERE id = ?", (hash_val, admin_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def update_admin_profile(admin_id, nama, username=None, role=None):
    """Memperbarui informasi profil admin"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if nama and nama.strip():
        updates.append("nama = ?")
        params.append(nama.strip())
    if username and username.strip():
        updates.append("username = ?")
        params.append(username.strip())
    if role and role in ['superadmin', 'admin']:
        updates.append("role = ?")
        params.append(role)
        
    if not updates:
        conn.close()
        return False
        
    params.append(admin_id)
    query = f"UPDATE admins SET {', '.join(updates)} WHERE id = ?"
    try:
        cursor.execute(query, params)
        conn.commit()
        affected = cursor.rowcount > 0
    except sqlite3.IntegrityError:
        affected = False
    finally:
        conn.close()
    return affected

def create_admin(username, password, nama, role='admin'):
    """Membuat user admin baru"""
    hash_val = generate_password_hash(password.strip(), method='pbkdf2:sha256')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO admins (username, password_hash, nama, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username.strip(), hash_val, nama.strip(), role, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return get_admin_by_id(new_id)
    except sqlite3.IntegrityError:
        conn.close()
        return None

def delete_admin(admin_id):
    """Menghapus user admin (Super Admin tidak boleh menghapus akun dirinya sendiri)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def get_setting(key, default=''):
    """Mengambil nilai setting berdasarkan key"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    """Menyimpan atau memperbarui nilai setting"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()
    conn.close()

def get_all_settings():
    """Mengambil seluruh data settings dalam bentuk dictionary"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    settings = {row['key']: row['value'] for row in rows}
    if 'event_name' not in settings:
        settings['event_name'] = 'Seminar Nasional Teknologi & Inovasi 2026'
    if 'event_logo' not in settings:
        settings['event_logo'] = ''
    return settings

# ======================= PRESENTATION TITLES (JUDUL & RUANGAN) =======================

def get_all_presentations(search=None, ruangan=None):
    """Mengambil seluruh data judul presentasi beserta status klaim presenter"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            p.id, 
            p.judul, 
            p.ruangan, 
            p.created_at,
            pt.id AS participant_id,
            pt.nama_lengkap AS presenter_name,
            pt.nim_nip AS presenter_nim,
            pt.status AS participant_status,
            pt.qr_code AS presenter_qr,
            CASE WHEN pt.id IS NOT NULL THEN 1 ELSE 0 END AS is_taken
        FROM presentations p
        LEFT JOIN participants pt ON pt.presentation_id = p.id
        WHERE 1=1
    """
    params = []
    
    if ruangan and ruangan != 'Semua':
        query += " AND p.ruangan = ?"
        params.append(ruangan)
        
    if search:
        search_pattern = f"%{search.strip()}%"
        query += " AND (p.judul LIKE ? OR p.ruangan LIKE ? OR pt.nama_lengkap LIKE ? OR pt.nim_nip LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])
        
    query += " ORDER BY p.id ASC"
    
    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_available_presentations():
    """Mengambil daftar judul presentasi untuk dropdown formulir pendaftaran publik"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            p.id, 
            p.judul, 
            p.ruangan, 
            pt.nama_lengkap AS presenter_name,
            pt.qr_code AS presenter_qr,
            CASE WHEN pt.id IS NOT NULL THEN 1 ELSE 0 END AS is_taken
        FROM presentations p
        LEFT JOIN participants pt ON pt.presentation_id = p.id
        ORDER BY p.id ASC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_presentation_by_id(presentation_id):
    """Mengambil detail 1 judul presentasi berdasarkan ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            p.*, 
            pt.id AS participant_id,
            pt.nama_lengkap AS presenter_name,
            pt.nim_nip AS presenter_nim,
            CASE WHEN pt.id IS NOT NULL THEN 1 ELSE 0 END AS is_taken
        FROM presentations p
        LEFT JOIN participants pt ON pt.presentation_id = p.id
        WHERE p.id = ?
    """, (presentation_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_distinct_ruangan():
    """Mengambil daftar seluruh ruangan unik yang terdaftar"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT ruangan FROM presentations WHERE ruangan IS NOT NULL AND ruangan != '' ORDER BY ruangan ASC")
    rows = [r['ruangan'] for r in cursor.fetchall()]
    conn.close()
    return rows

def add_presentation(judul, ruangan='-'):
    """Menambahkan judul presentasi baru"""
    cleaned_judul = judul.strip()
    cleaned_ruangan = (ruangan or '-').strip()
    if not cleaned_judul:
        return None
        
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO presentations (judul, ruangan, created_at)
        VALUES (?, ?, ?)
    """, (cleaned_judul, cleaned_ruangan, created_at))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return get_presentation_by_id(new_id)

def update_presentation(presentation_id, judul, ruangan='-'):
    """Memperbarui judul presentasi dan ruangan, serta sinkronisasi data peserta yang memilihnya"""
    cleaned_judul = judul.strip()
    cleaned_ruangan = (ruangan or '-').strip()
    if not cleaned_judul:
        return False
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE presentations
        SET judul = ?, ruangan = ?
        WHERE id = ?
    """, (cleaned_judul, cleaned_ruangan, presentation_id))
    affected = cursor.rowcount > 0
    
    # Sinkronisasi ke data participants jika ada yang terkait
    if affected:
        cursor.execute("""
            UPDATE participants
            SET judul_presentasi = ?, ruangan = ?
            WHERE presentation_id = ?
        """, (cleaned_judul, cleaned_ruangan, presentation_id))
        
    conn.commit()
    conn.close()
    return affected

def delete_presentation(presentation_id):
    """Menghapus 1 judul presentasi dan melepaskan relasi dari peserta terkait"""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Lepaskan relasi dari peserta (set NULL agar data peserta tidak hilang)
    cursor.execute("""
        UPDATE participants
        SET presentation_id = NULL
        WHERE presentation_id = ?
    """, (presentation_id,))
    
    cursor.execute("DELETE FROM presentations WHERE id = ?", (presentation_id,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def delete_all_presentations():
    """Menghapus seluruh judul presentasi"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE participants SET presentation_id = NULL")
    cursor.execute("DELETE FROM presentations")
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected

def delete_presentations_bulk(presentation_ids):
    """Menghapus banyak judul presentasi sekaligus berdasarkan daftar ID"""
    if not presentation_ids:
        return 0
    valid_ids = [int(i) for i in presentation_ids if str(i).isdigit() or isinstance(i, int)]
    if not valid_ids:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join(['?'] * len(valid_ids))
    cursor.execute(f"UPDATE participants SET presentation_id = NULL WHERE presentation_id IN ({placeholders})", valid_ids)
    cursor.execute(f"DELETE FROM presentations WHERE id IN ({placeholders})", valid_ids)
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected

def get_presentation_stats():
    """Mengambil statistik ketersediaan judul presentasi"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM presentations")
    total = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(DISTINCT p.id) 
        FROM presentations p
        INNER JOIN participants pt ON pt.presentation_id = p.id
    """)
    taken = cursor.fetchone()[0]
    
    conn.close()
    available = max(0, total - taken)
    return {
        "total_judul": total,
        "judul_terisi": taken,
        "judul_tersedia": available
    }

def generate_unique_qr_code():
    """Menghasilkan 10 karakter alfanumerik acak kapital yang unik"""
    chars = string.ascii_uppercase + string.digits
    conn = get_db_connection()
    cursor = conn.cursor()
    while True:
        code = "".join(random.choices(chars, k=10))
        cursor.execute("SELECT id FROM participants WHERE qr_code = ?", (code,))
        if cursor.fetchone() is None:
            conn.close()
            return code

def register_participant(nim_nip, nama_lengkap, no_hp, institusi, pekerjaan, presentation_id=None):
    """
    Mendaftarkan presenter baru dengan status default 'pendaftar'.
    Jika presentation_id disertakan, dilakukan validasi bahwa judul tersebut masih tersedia.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    judul_presentasi = ''
    ruangan = '-'
    
    if presentation_id:
        # Cek apakah judul ada di tabel presentations
        cursor.execute("SELECT * FROM presentations WHERE id = ?", (presentation_id,))
        pres = cursor.fetchone()
        if not pres:
            conn.close()
            raise ValueError("Judul presentasi yang dipilih tidak ditemukan dalam database!")
            
        # Cek apakah judul sudah diambil presenter lain (1 judul = 1 presenter)
        cursor.execute("SELECT id, nama_lengkap FROM participants WHERE presentation_id = ?", (presentation_id,))
        already_taken = cursor.fetchone()
        if already_taken:
            conn.close()
            raise ValueError(f"Judul presentasi ini sudah dipilih oleh presenter lain ({already_taken['nama_lengkap']})!")
            
        judul_presentasi = pres['judul']
        ruangan = pres['ruangan'] or '-'
        
    qr_code = generate_unique_qr_code()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO participants (qr_code, nim_nip, nama_lengkap, no_hp, institusi, pekerjaan, presentation_id, judul_presentasi, ruangan, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendaftar', ?)
    """, (qr_code, nim_nip.strip(), nama_lengkap.strip(), (no_hp or '').strip(), institusi.strip(), pekerjaan.strip(), presentation_id, judul_presentasi, ruangan, created_at))
    conn.commit()
    inserted_id = cursor.lastrowid
    
    cursor.execute("SELECT * FROM participants WHERE id = ?", (inserted_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)

def upsert_participant_from_csv(qr_code, nim_nip, nama_lengkap, no_hp='', institusi='-', pekerjaan='Lainnya', judul_presentasi='', ruangan='-', presentation_id=None, status='pendaftar', created_at=None, attended_at=None, overwrite=True):
    """
    Menyimpan atau memperbarui data peserta dari file CSV backup (pendaftar & peserta).
    Jika data sudah ada (berdasarkan qr_code atau nim_nip):
    - Jika overwrite=True: data diperbarui.
    - Jika overwrite=False: data dilewati (skip).
    """
    if not qr_code or len(qr_code.strip()) < 5:
        qr_code = generate_unique_qr_code()
    else:
        qr_code = qr_code.strip().upper()
        
    cleaned_nim = nim_nip.strip()
    cleaned_nama = nama_lengkap.strip()
    cleaned_hp = (no_hp or '').strip()
    cleaned_inst = institusi.strip()
    cleaned_job = pekerjaan.strip() if pekerjaan else 'Lainnya'
    cleaned_judul = (judul_presentasi or '').strip()
    cleaned_ruangan = (ruangan or '-').strip()
    
    status_lower = (status or 'pendaftar').strip().lower()
    final_status = 'peserta' if ('peserta' in status_lower or 'hadir' in status_lower) and 'belum' not in status_lower else 'pendaftar'
    
    final_created_at = created_at.strip() if created_at and created_at.strip() != '-' else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    final_attended_at = None
    if final_status == 'peserta':
        if attended_at and attended_at.strip() != '-':
            final_attended_at = attended_at.strip()
        else:
            final_attended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Jika judul_presentasi ada tapi presentation_id kosong, coba cari id-nya
    if cleaned_judul and not presentation_id:
        cursor.execute("SELECT id FROM presentations WHERE LOWER(judul) = LOWER(?)", (cleaned_judul,))
        pres_row = cursor.fetchone()
        if pres_row:
            presentation_id = pres_row['id']
    
    cursor.execute("SELECT id FROM participants WHERE qr_code = ? OR nim_nip = ?", (qr_code, cleaned_nim))
    existing = cursor.fetchone()
    
    if existing:
        if overwrite:
            cursor.execute("""
                UPDATE participants 
                SET qr_code = ?, nim_nip = ?, nama_lengkap = ?, no_hp = ?, institusi = ?, pekerjaan = ?, presentation_id = ?, judul_presentasi = ?, ruangan = ?, status = ?, created_at = ?, attended_at = ?
                WHERE id = ?
            """, (qr_code, cleaned_nim, cleaned_nama, cleaned_hp, cleaned_inst, cleaned_job, presentation_id, cleaned_judul, cleaned_ruangan, final_status, final_created_at, final_attended_at, existing['id']))
            conn.commit()
            conn.close()
            return 'updated'
        else:
            conn.close()
            return 'skipped'
    else:
        cursor.execute("""
            INSERT INTO participants (qr_code, nim_nip, nama_lengkap, no_hp, institusi, pekerjaan, presentation_id, judul_presentasi, ruangan, status, created_at, attended_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (qr_code, cleaned_nim, cleaned_nama, cleaned_hp, cleaned_inst, cleaned_job, presentation_id, cleaned_judul, cleaned_ruangan, final_status, final_created_at, final_attended_at))
        conn.commit()
        conn.close()
        return 'inserted'

def get_participant_by_nim(nim_nip):
    """Mencari data peserta berdasarkan NIM/NIP untuk deteksi duplikasi pendaftaran"""
    if not nim_nip:
        return None
    cleaned = nim_nip.strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM participants WHERE nim_nip = ?", (cleaned,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_participant_by_qr(qr_code):
    """Mencari data peserta berdasarkan QR Code"""
    if not qr_code:
        return None
    code_cleaned = qr_code.strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM participants WHERE UPPER(qr_code) = ?", (code_cleaned,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_participant_by_id(participant_id):
    """Mencari data peserta berdasarkan ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM participants WHERE id = ?", (participant_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def mark_attendance(qr_code):
    """
    Memproses pemindaian QR Code.
    Mengubah status 'pendaftar' menjadi 'peserta' dan mencatat waktu hadir.
    """
    participant = get_participant_by_qr(qr_code)
    if not participant:
        return {
            "success": False,
            "code": "NOT_FOUND",
            "message": f"QR Code '{qr_code}' tidak ditemukan dalam database pendaftar."
        }
    
    if participant["status"] == "peserta":
        return {
            "success": False,
            "code": "ALREADY_ATTENDED",
            "message": f"Peserta '{participant['nama_lengkap']}' sudah melakukan absensi sebelumnya pada {participant['attended_at']}.",
            "data": participant
        }
    
    attended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE participants
        SET status = 'peserta', attended_at = ?
        WHERE id = ?
    """, (attended_at, participant["id"]))
    conn.commit()
    
    cursor.execute("SELECT * FROM participants WHERE id = ?", (participant["id"],))
    updated_row = dict(cursor.fetchone())
    conn.close()
    
    return {
        "success": True,
        "code": "SUCCESS",
        "message": f"Absensi berhasil! Status '{updated_row['nama_lengkap']}' kini resmi menjadi Peserta.",
        "data": updated_row
    }

def toggle_status(participant_id):
    """Mengubah status pendaftar <-> peserta secara manual dari tabel admin"""
    participant = get_participant_by_id(participant_id)
    if not participant:
        return None
    
    new_status = "peserta" if participant["status"] == "pendaftar" else "pendaftar"
    attended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if new_status == "peserta" else None
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE participants
        SET status = ?, attended_at = ?
        WHERE id = ?
    """, (new_status, attended_at, participant_id))
    conn.commit()
    
    cursor.execute("SELECT * FROM participants WHERE id = ?", (participant_id,))
    updated = dict(cursor.fetchone())
    conn.close()
    return updated

def delete_participant(participant_id):
    """Menghapus data pendaftar/peserta"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM participants WHERE id = ?", (participant_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def delete_participants_bulk(participant_ids):
    """Menghapus banyak data pendaftar/peserta sekaligus berdasarkan daftar ID"""
    if not participant_ids:
        return 0
    valid_ids = [int(i) for i in participant_ids if str(i).isdigit() or isinstance(i, int)]
    if not valid_ids:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join(['?'] * len(valid_ids))
    cursor.execute(f"DELETE FROM participants WHERE id IN ({placeholders})", valid_ids)
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected

def get_participants(status=None, search=None, pekerjaan=None, ruangan=None):
    """
    Mengambil data peserta dengan filter status ('pendaftar'/'peserta'),
    kata kunci pencarian (NIM/NIP, Nama, Institusi, Judul, Ruangan, QR), jenis pekerjaan, dan ruangan.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM participants WHERE 1=1"
    params = []
    
    if status in ['pendaftar', 'peserta']:
        query += " AND status = ?"
        params.append(status)
        
    if pekerjaan and pekerjaan != 'Semua':
        query += " AND pekerjaan = ?"
        params.append(pekerjaan)

    if ruangan and ruangan != 'Semua':
        query += " AND ruangan = ?"
        params.append(ruangan)
        
    if search:
        search_pattern = f"%{search.strip()}%"
        query += " AND (nim_nip LIKE ? OR nama_lengkap LIKE ? OR no_hp LIKE ? OR institusi LIKE ? OR qr_code LIKE ? OR judul_presentasi LIKE ? OR ruangan LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])
        
    if status == 'peserta':
        query += " ORDER BY attended_at DESC, id DESC"
    else:
        query += " ORDER BY created_at DESC, id DESC"
        
    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_stats():
    """Mengambil ringkasan statistik kehadiran seminar & judul presentasi"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM participants")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM participants WHERE status = 'pendaftar'")
    pendaftar_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM participants WHERE status = 'peserta'")
    peserta_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM presentations")
    total_judul = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT presentation_id) FROM participants WHERE presentation_id IS NOT NULL")
    judul_terisi = cursor.fetchone()[0]
    
    conn.close()
    
    attendance_rate = round((peserta_count / total * 100), 1) if total > 0 else 0
    judul_tersedia = max(0, total_judul - judul_terisi)
    
    return {
        "total": total,
        "pendaftar": pendaftar_count,
        "peserta": peserta_count,
        "attendance_rate": attendance_rate,
        "total_judul": total_judul,
        "judul_terisi": judul_terisi,
        "judul_tersedia": judul_tersedia
    }
