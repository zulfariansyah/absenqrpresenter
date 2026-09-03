import os
import io
import csv
import re
import html
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_file, Response, session, redirect, url_for, send_from_directory
import qrcode
from qrcode.image.pil import PilImage

import database
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# Dukungan Reverse Proxy (Nginx subpath / header X-Forwarded-Prefix & Proto)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.config['SECRET_KEY'] = 'presenter-semnasretro-secret-key-2026'
app.config['SESSION_COOKIE_NAME'] = 'session_presenter_semnas'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Inisialisasi Database
database.init_db()

def normalize_media_url(url):
    """Menormalisasi URL static/media agar otomatis berawalan /absenpresenter"""
    if not url:
        return ''
    if url.startswith('http') or url.startswith('data:'):
        return url
    if not url.startswith('/absenpresenter'):
        if url.startswith('/static/'):
            return f"/absenpresenter{url}"
        return f"/absenpresenter/static/uploads/{url.lstrip('/')}"
    return url

@app.template_filter('linkify')
def linkify(text):
    """Mengubah link URL dalam teks menjadi hyperlink yang bisa diklik (new window)"""
    if not text:
        return ''
    escaped = html.escape(str(text))
    url_pattern = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')
    def replace_url(match):
        url = match.group(0)
        href = url if url.startswith(('http://', 'https://')) else f'http://{url}'
        return f'<a href="{href}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-800 underline font-semibold break-all inline-flex items-center gap-1">{url} <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline shrink-0"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></a>'
    linked = url_pattern.sub(replace_url, escaped)
    return linked.replace('\n', '<br>')

ACTIVE_PORT = 5001

def get_local_ip():
    """Mendeteksi IP Address lokal di jaringan LAN / Wi-Fi"""
    import socket
    import subprocess
    # Coba koneksi UDP standar
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.'):
                return ip
    except Exception:
        pass

    # Fallback macOS Wi-Fi / Ethernet interface (en0, en1, en2)
    for iface in ['en0', 'en1', 'en2', 'eth0', 'wlan0']:
        try:
            res = subprocess.run(['ipconfig', 'getifaddr', iface], capture_output=True, text=True, timeout=1)
            ip = res.stdout.strip()
            if ip and not ip.startswith('127.'):
                return ip
        except Exception:
            pass

    # Fallback hostname lookup
    try:
        host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        for ip in host_ips:
            if not ip.startswith('127.'):
                return ip
    except Exception:
        pass

    return '127.0.0.1'

def find_available_port(start_port=5001, max_tries=5):
    """Mencari port bebas secara otomatis jika port default sedang digunakan program lain"""
    import socket
    if os.environ.get('PORT'):
        return int(os.environ.get('PORT'))
    for p in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('0.0.0.0', p))
                return p
            except OSError:
                continue
    return start_port

def admin_required(f):
    """Decorator untuk membatasi akses khusus sesi admin yang valid"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in') and not session.get('presenter_admin_logged_in'):
            if request.path.startswith('/api/') or request.path.startswith('/apipresenter/') or request.path.startswith('/absenpresenter/api/'):
                return jsonify({'success': False, 'message': 'Akses ditolak. Silakan login terlebih dahulu.'}), 401
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    return decorated_function

def superadmin_required(f):
    """Decorator untuk membatasi akses khusus sesi Super Admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in') and not session.get('presenter_admin_logged_in'):
            return jsonify({'success': False, 'message': 'Akses ditolak. Silakan login terlebih dahulu.'}), 401
        if session.get('admin_role') != 'superadmin':
            return jsonify({'success': False, 'message': 'Akses ditolak. Fitur ini hanya untuk Super Admin.'}), 403
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_settings():
    """Menyediakan variabel global pengaturan acara, IP lokal, dan status login ke seluruh template"""
    global ACTIVE_PORT
    settings = database.get_all_settings()
    settings['event_logo'] = normalize_media_url(settings.get('event_logo', ''))
    settings['event_favicon'] = normalize_media_url(settings.get('event_favicon', ''))

    local_ip = get_local_ip()
    port = ACTIVE_PORT
    return {
        'event_settings': settings,
        'local_ip': local_ip,
        'server_port': port,
        'local_url': f"http://{local_ip}:{port}",
        'is_admin': session.get('admin_logged_in', False) or session.get('presenter_admin_logged_in', False),
        'admin_id': session.get('admin_id'),
        'admin_username': session.get('admin_username', 'admin'),
        'admin_name': session.get('admin_name', 'Super Admin'),
        'admin_role': session.get('admin_role', 'admin'),
        'is_superadmin': session.get('admin_role') == 'superadmin'
    }

@app.route('/absenpresenter/static/<path:filename>')
@app.route('/staticpresenter/<path:filename>')
def custom_static(filename):
    """Melayani file static jika diakses langsung dengan prefix /absenpresenter/static/"""
    return send_from_directory(os.path.join(app.root_path, 'static'), filename)

@app.route('/absenpresenter')
@app.route('/')
def index():
    """Halaman Pendaftaran Seminar (Publik Peserta)"""
    return render_template('register.html')

@app.route('/absenpresenter/admin')
@app.route('/adminpresenter')
@app.route('/admin')
def admin():
    """Halaman Dashboard Admin Presenter (menampilkan Form Login jika belum login, atau Dashboard jika sudah login)"""
    if not session.get('admin_logged_in') and not session.get('presenter_admin_logged_in'):
        return render_template('login.html')
    return render_template('admin.html')

@app.route('/login')
def login():
    """Redirect /login ke /admin"""
    return redirect(url_for('admin'))

@app.route('/absenpresenter/ticket/<qr_code>')
@app.route('/ticketpresenter/<qr_code>')
@app.route('/ticket/<qr_code>')
def ticket(qr_code):
    """Halaman E-Ticket Digital Peserta"""
    participant = database.get_participant_by_qr(qr_code)
    if not participant:
        return render_template('ticket.html', participant=None, error="Tiket QR Code tidak ditemukan.")
    return render_template('ticket.html', participant=participant, error=None)

def presenter_route(rule, **options):
    """Mendaftarkan route untuk path standar (/api/...), alias /apipresenter/..., dan subpath /absenpresenter/api/..."""
    def decorator(f):
        endpoint = options.pop('endpoint', None)
        orig_endpoint = endpoint or f.__name__
        app.add_url_rule(rule, orig_endpoint, f, **options)
        
        if rule.startswith('/api/'):
            sub_rule = rule[5:]
            app.add_url_rule(f'/apipresenter/{sub_rule}', orig_endpoint + '_alias_apipres', f, **options)
            app.add_url_rule(f'/absenpresenter/api/{sub_rule}', orig_endpoint + '_alias_absenpres', f, **options)
        elif rule.startswith('/api'):
            sub_rule = rule[4:]
            app.add_url_rule(f'/apipresenter{sub_rule}', orig_endpoint + '_alias_apipres', f, **options)
            app.add_url_rule(f'/absenpresenter/api{sub_rule}', orig_endpoint + '_alias_absenpres', f, **options)
        return f
    return decorator

# ======================= AUTH & API ENDPOINTS =======================

@presenter_route('/api/login', methods=['POST'])
def api_login():
    """Memverifikasi username & password admin"""
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'success': False, 'message': 'Username dan password wajib diisi!'}), 400

    admin_user = database.verify_admin(username, password)
    if admin_user:
        session['admin_logged_in'] = True
        session['admin_id'] = admin_user['id']
        session['admin_username'] = admin_user['username']
        session['admin_name'] = admin_user['nama']
        session['admin_role'] = admin_user['role']
        database.update_admin_last_login(admin_user['id'])
        return jsonify({
            'success': True,
            'message': f'Selamat datang, {admin_user["nama"]}!',
            'user': {
                'id': admin_user['id'],
                'username': admin_user['username'],
                'nama': admin_user['nama'],
                'role': admin_user['role']
            }
        })
    else:
        return jsonify({'success': False, 'message': 'Username atau password admin salah!'}), 401

@presenter_route('/api/logout', methods=['POST', 'GET'])
def api_logout():
    """Keluar dari sesi admin presenter"""
    session.clear()
    if request.method == 'GET':
        return redirect(url_for('admin'))
    return jsonify({'success': True, 'message': 'Logout berhasil.'})

@presenter_route('/api/admin/change-credentials', methods=['POST'])
@admin_required
def api_change_credentials():
    """Mengubah password akun admin yang sedang login"""
    data = request.get_json() or {}
    current_pass = data.get('current_password', '').strip()
    new_pass = data.get('new_password', '').strip()
    new_nama = data.get('nama', '').strip()

    admin_id = session.get('admin_id')
    current_user = database.get_admin_by_id(admin_id) if admin_id else None
    
    if not current_user:
        return jsonify({'success': False, 'message': 'User tidak ditemukan.'}), 404

    # Verifikasi password saat ini
    valid = database.verify_admin(current_user['username'], current_pass)
    if not valid:
        return jsonify({'success': False, 'message': 'Password saat ini salah!'}), 400

    if new_nama:
        database.update_admin_profile(admin_id, nama=new_nama)
        session['admin_name'] = new_nama

    if new_pass:
        database.update_admin_password(admin_id, new_pass)

    return jsonify({'success': True, 'message': 'Kredensial berhasil diperbarui!'})

# ======================= SUPER ADMIN MANAGEMENT ENDPOINTS =======================

@presenter_route('/api/admin/users', methods=['GET'])
@superadmin_required
def api_get_admins():
    """Mengambil daftar seluruh user admin (Khusus Super Admin)"""
    admins = database.get_all_admins()
    return jsonify({'success': True, 'data': admins})

@presenter_route('/api/admin/users', methods=['POST'])
@superadmin_required
def api_create_admin():
    """Membuat user admin baru (Khusus Super Admin)"""
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    nama = data.get('nama', '').strip()
    role = data.get('role', 'admin').strip()

    if not username or not password or not nama:
        return jsonify({'success': False, 'message': 'Username, nama, dan password wajib diisi!'}), 400

    new_admin = database.create_admin(username, password, nama, role)
    if not new_admin:
        return jsonify({'success': False, 'message': 'Username sudah digunakan, pilih username lain.'}), 400

    return jsonify({'success': True, 'message': f'Admin {nama} berhasil dibuat!', 'data': new_admin})

@presenter_route('/api/admin/users/<int:admin_id>/reset-password', methods=['POST'])
@superadmin_required
def api_reset_admin_password(admin_id):
    """Mengatur/Reset password admin manapun (Khusus Super Admin)"""
    data = request.get_json() or {}
    new_password = data.get('new_password', '').strip()

    if not new_password:
        return jsonify({'success': False, 'message': 'Password baru wajib diisi!'}), 400

    target_admin = database.get_admin_by_id(admin_id)
    if not target_admin:
        return jsonify({'success': False, 'message': 'User admin tidak ditemukan.'}), 404

    success = database.update_admin_password(admin_id, new_password)
    if success:
        return jsonify({'success': True, 'message': f'Password untuk {target_admin["nama"]} ({target_admin["username"]}) berhasil diperbarui!'})
    return jsonify({'success': False, 'message': 'Gagal memperbarui password.'}), 500

@presenter_route('/api/admin/users/<int:admin_id>/edit', methods=['POST'])
@superadmin_required
def api_edit_admin_profile(admin_id):
    """Mengubah nama, username, atau role admin (Khusus Super Admin)"""
    data = request.get_json() or {}
    nama = data.get('nama', '').strip()
    username = data.get('username', '').strip()
    role = data.get('role', '').strip()

    target_admin = database.get_admin_by_id(admin_id)
    if not target_admin:
        return jsonify({'success': False, 'message': 'User admin tidak ditemukan.'}), 404

    # Proteksi: Jangan hapus status superadmin jika diri sendiri sedang login
    if admin_id == session.get('admin_id') and role and role != 'superadmin':
        return jsonify({'success': False, 'message': 'Anda tidak dapat menurunkan role akun Anda sendiri.'}), 400

    success = database.update_admin_profile(admin_id, nama=nama, username=username, role=role if role else None)
    if success:
        return jsonify({'success': True, 'message': 'Data admin berhasil diperbarui!'})
    return jsonify({'success': False, 'message': 'Gagal memperbarui data admin (kemungkinan username sudah dipakai).'}), 400

@presenter_route('/api/admin/users/<int:admin_id>', methods=['DELETE'])
@superadmin_required
def api_delete_admin(admin_id):
    """Menghapus user admin (Khusus Super Admin)"""
    if admin_id == session.get('admin_id'):
        return jsonify({'success': False, 'message': 'Anda tidak dapat menghapus akun Anda sendiri!'}), 400

    target = database.get_admin_by_id(admin_id)
    if not target:
        return jsonify({'success': False, 'message': 'User tidak ditemukan.'}), 404

    database.delete_admin(admin_id)
    return jsonify({'success': True, 'message': f'Admin {target["nama"]} berhasil dihapus.'})

import html
import time

# In-Memory Rate Limiter untuk mencegah spam / flood pendaftaran
registration_history = {}

def is_rate_limited(ip_address, max_requests=5, window_seconds=60):
    """Mencegah spam pendaftaran dengan membatasi maksimal 5 pendaftaran per menit per IP"""
    now = time.time()
    timestamps = registration_history.get(ip_address, [])
    # Hapus timestamp yang sudah lebih dari window_seconds
    valid_timestamps = [t for t in timestamps if now - t < window_seconds]
    if len(valid_timestamps) >= max_requests:
        registration_history[ip_address] = valid_timestamps
        return True
    valid_timestamps.append(now)
    registration_history[ip_address] = valid_timestamps
    return False

@presenter_route('/api/presentations/public', methods=['GET'])
def api_presentations_public():
    """Mengambil daftar judul presentasi untuk form registrasi publik (dengan flag is_taken)"""
    items = database.get_available_presentations()
    return jsonify({'success': True, 'data': items})

@presenter_route('/api/register', methods=['POST'])
def api_register():
    """Menerima pendaftaran presenter baru dengan pemilihan judul presentasi & ruangan"""
    data = request.get_json() or {}
    
    # 1. Anti-Bot Honeypot: Jika field bot terisi, tolak langsung
    if data.get('website_url') or data.get('hp_secondary'):
        return jsonify({
            'success': False,
            'message': 'Permintaan pendaftaran ditolak oleh sistem keamanan.'
        }), 400

    # 2. Rate Limiting: Maksimal 5 registrasi per 60 detik per IP
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1')
    if is_rate_limited(client_ip, max_requests=5, window_seconds=60):
        return jsonify({
            'success': False,
            'message': 'Terlalu banyak permintaan pendaftaran. Mohon tunggu 1 menit sebelum mencoba lagi.'
        }), 429
    
    raw_nim = data.get('nim_nip', '').strip()
    raw_nama = data.get('nama_lengkap', '').strip()
    raw_no_hp = data.get('no_hp', '').strip()
    raw_institusi = data.get('institusi', '').strip()
    raw_pekerjaan = data.get('pekerjaan', '').strip()
    raw_pres_id = data.get('presentation_id')
    
    # 3. Validasi Keberadaan Input
    if not raw_nim or not raw_nama or not raw_no_hp or not raw_institusi or not raw_pekerjaan:
        return jsonify({
            'success': False,
            'message': 'Semua kolom formulir (No. Identitas, Nama Lengkap, No. HP / WhatsApp, Institusi, Pekerjaan) wajib diisi!'
        }), 400
        
    presentation_id = None
    all_db_presentations = database.get_all_presentations()
    if all_db_presentations:
        if not raw_pres_id:
            return jsonify({
                'success': False,
                'message': 'Silakan pilih Judul Presentasi yang akan Anda bawakan!'
            }), 400
        try:
            presentation_id = int(raw_pres_id)
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'message': 'Pilihan judul presentasi tidak valid!'
            }), 400
    else:
        if raw_pres_id:
            try:
                presentation_id = int(raw_pres_id)
            except (ValueError, TypeError):
                pass
        
    # 4. Validasi Panjang Karakter (Mencegah Buffer/Payload Abuse)
    if len(raw_nim) < 3 or len(raw_nim) > 30:
        return jsonify({
            'success': False,
            'message': 'No. Identitas (NIM/NIP/NIDN/NUPTK/KTP) harus berisi antara 3 hingga 30 karakter!'
        }), 400

    if len(raw_nama) < 2 or len(raw_nama) > 100:
        return jsonify({
            'success': False,
            'message': 'Nama Lengkap harus berisi antara 2 hingga 100 karakter!'
        }), 400

    if len(raw_no_hp) < 8 or len(raw_no_hp) > 20:
        return jsonify({
            'success': False,
            'message': 'Nomor HP / WhatsApp harus berisi antara 8 hingga 20 karakter!'
        }), 400

    if len(raw_institusi) < 2 or len(raw_institusi) > 120:
        return jsonify({
            'success': False,
            'message': 'Nama Institusi harus berisi antara 2 hingga 120 karakter!'
        }), 400
        
    valid_jobs = ['Mahasiswa S1', 'Mahasiswa S2', 'Mahasiswa', 'Dosen', 'Praktisi', 'Lainnya']
    if raw_pekerjaan not in valid_jobs:
        return jsonify({
            'success': False,
            'message': f'Pekerjaan harus salah satu dari: {", ".join(valid_jobs)}'
        }), 400

    # 5. XSS Sanitization: Escape karakter khusus HTML (<, >, &, ", ')
    nim_nip = html.escape(raw_nim)
    nama_lengkap = html.escape(raw_nama)
    no_hp = html.escape(raw_no_hp)
    institusi = html.escape(raw_institusi)
    pekerjaan = html.escape(raw_pekerjaan)

    # 6. Deteksi Duplikasi Nomor Identitas
    existing = database.get_participant_by_nim(nim_nip)
    if existing:
        return jsonify({
            'success': False,
            'code': 'DUPLICATE_NIM',
            'message': f'No. Identitas "{nim_nip}" sudah terdaftar atas nama {existing["nama_lengkap"]}. QR Code tiket sudah pernah dibuat sebelumnya.',
            'data': existing
        }), 400
        
    try:
        participant = database.register_participant(
            nim_nip=nim_nip,
            nama_lengkap=nama_lengkap,
            no_hp=no_hp,
            institusi=institusi,
            pekerjaan=pekerjaan,
            presentation_id=presentation_id
        )
        return jsonify({
            'success': True,
            'message': 'Pendaftaran presenter berhasil!',
            'data': participant
        })
    except ValueError as ve:
        return jsonify({
            'success': False,
            'message': str(ve)
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Gagal mendaftarkan presenter: {str(e)}'
        }), 500

@presenter_route('/api/scan', methods=['POST'])
@admin_required
def api_scan():
    """
    Menerima hasil scan QR code dari kamera admin.
    Memvalidasi dan mengubah status dari pendaftar menjadi peserta.
    """
    data = request.get_json() or {}
    qr_code = data.get('qr_code', '').strip()
    
    if not qr_code:
        return jsonify({
            'success': False,
            'code': 'EMPTY_CODE',
            'message': 'Kode QR tidak boleh kosong.'
        }), 400
        
    result = database.mark_attendance(qr_code)
    return jsonify(result)

@presenter_route('/api/participants', methods=['GET'])
@admin_required
def api_participants():
    """Mengambil data peserta berdasarkan status (pendaftar/peserta), pencarian, pekerjaan, dan ruangan"""
    status = request.args.get('status')
    search = request.args.get('search')
    pekerjaan = request.args.get('pekerjaan')
    ruangan = request.args.get('ruangan')
    
    rows = database.get_participants(status=status, search=search, pekerjaan=pekerjaan, ruangan=ruangan)
    return jsonify({
        'success': True,
        'count': len(rows),
        'data': rows
    })

@presenter_route('/api/stats', methods=['GET'])
@admin_required
def api_stats():
    """Mengambil data statistik jumlah pendaftar, peserta hadir, judul presentasi, dan persentase"""
    stats = database.get_stats()
    return jsonify({
        'success': True,
        'stats': stats
    })

@presenter_route('/api/participant/<int:participant_id>/toggle', methods=['POST'])
@admin_required
def api_toggle_status(participant_id):
    """Mengubah status pendaftar <-> peserta secara manual"""
    updated = database.toggle_status(participant_id)
    if not updated:
        return jsonify({'success': False, 'message': 'Peserta tidak ditemukan.'}), 404
        
    return jsonify({
        'success': True,
        'message': f'Status berhasil diubah menjadi {updated["status"].capitalize()}',
        'data': updated
    })

@presenter_route('/api/participant/<int:participant_id>', methods=['DELETE'])
@admin_required
def api_delete_participant(participant_id):
    """Menghapus data pendaftar/peserta"""
    deleted = database.delete_participant(participant_id)
    if not deleted:
        return jsonify({'success': False, 'message': 'Data tidak ditemukan atau gagal dihapus.'}), 404
        
    return jsonify({
        'success': True,
        'message': 'Data berhasil dihapus.'
    })

@presenter_route('/api/participants/bulk-delete', methods=['POST'])
@admin_required
def api_bulk_delete_participants():
    """Menghapus beberapa data presenter sekaligus berdasarkan daftar ID terpilih"""
    data = request.get_json() or {}
    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return jsonify({'success': False, 'message': 'Pilih minimal 1 data presenter untuk dihapus.'}), 400
    
    count = database.delete_participants_bulk(ids)
    return jsonify({
        'success': True,
        'message': f'{count} data presenter berhasil dihapus.',
        'count': count
    })

@presenter_route('/api/settings', methods=['GET'])
def api_get_settings():
    """Mengambil data pengaturan nama acara & logo saat ini"""
    settings = database.get_all_settings()
    settings['event_logo'] = normalize_media_url(settings.get('event_logo', ''))
    settings['event_favicon'] = normalize_media_url(settings.get('event_favicon', ''))
    return jsonify({
        'success': True,
        'settings': settings
    })

@presenter_route('/api/settings', methods=['POST'])
@admin_required
def api_update_settings():
    """Memperbarui nama acara, title tag, informasi tambahan, logo, dan favicon acara"""
    event_name = request.form.get('event_name', '').strip()
    if event_name:
        database.set_setting('event_name', event_name)

    title_register = request.form.get('title_register', '').strip()
    database.set_setting('title_register', title_register)

    title_admin = request.form.get('title_admin', '').strip()
    database.set_setting('title_admin', title_admin)

    event_info = request.form.get('event_info', '').strip()
    database.set_setting('event_info', event_info)

    # Periksa apakah ada file logo yang diunggah
    if 'event_logo' in request.files:
        file = request.files['event_logo']
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1].lower()
            allowed_extensions = ['.png', '.jpg', '.jpeg', '.svg', '.webp', '.ico']
            if ext not in allowed_extensions:
                return jsonify({
                    'success': False,
                    'message': 'Format logo tidak didukung! Gunakan PNG, JPG, JPEG, SVG, atau WEBP.'
                }), 400

            filename = f"event_logo_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            logo_url = f"/absenpresenter/static/uploads/{filename}"
            database.set_setting('event_logo', logo_url)

    # Periksa apakah ada file favicon yang diunggah
    if 'event_favicon' in request.files:
        file = request.files['event_favicon']
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1].lower()
            allowed_fav_exts = ['.ico', '.png', '.svg', '.jpg', '.jpeg', '.webp']
            if ext not in allowed_fav_exts:
                return jsonify({
                    'success': False,
                    'message': 'Format FavIcon tidak didukung! Gunakan ICO, PNG, SVG, JPG, atau WEBP.'
                }), 400

            filename = f"event_favicon_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            fav_url = f"/absenpresenter/static/uploads/{filename}"
            database.set_setting('event_favicon', fav_url)

    updated_settings = database.get_all_settings()
    updated_settings['event_logo'] = normalize_media_url(updated_settings.get('event_logo', ''))
    updated_settings['event_favicon'] = normalize_media_url(updated_settings.get('event_favicon', ''))

    return jsonify({
        'success': True,
        'message': 'Pengaturan acara berhasil disimpan!',
        'settings': updated_settings
    })

@presenter_route('/api/settings/reset-logo', methods=['POST'])
@admin_required
def api_reset_logo():
    """Mereset logo acara kembali ke logo default sistem"""
    database.set_setting('event_logo', '')
    updated_settings = database.get_all_settings()
    updated_settings['event_logo'] = normalize_media_url(updated_settings.get('event_logo', ''))
    updated_settings['event_favicon'] = normalize_media_url(updated_settings.get('event_favicon', ''))
    return jsonify({
        'success': True,
        'message': 'Logo acara berhasil direset ke default.',
        'settings': updated_settings
    })

@presenter_route('/api/settings/reset-favicon', methods=['POST'])
@admin_required
def api_reset_favicon():
    """Mereset favicon acara kembali ke default sistem"""
    database.set_setting('event_favicon', '')
    updated_settings = database.get_all_settings()
    updated_settings['event_logo'] = normalize_media_url(updated_settings.get('event_logo', ''))
    updated_settings['event_favicon'] = normalize_media_url(updated_settings.get('event_favicon', ''))
    return jsonify({
        'success': True,
        'message': 'FavIcon acara berhasil direset ke default.',
        'settings': updated_settings
    })

@presenter_route('/api/network-info')
def api_network_info():
    """Mengembalikan informasi IP jaringan lokal dan link akses"""
    port = int(os.environ.get('PORT', 5001))
    local_ip = get_local_ip()
    prefix = request.script_root.rstrip('/')
    base_lan = f"http://{local_ip}:{port}{prefix}"
    base_local = f"http://127.0.0.1:{port}{prefix}"
    public_base = request.host_url.rstrip('/') + prefix
    
    # Jika diakses lewat domain/proxy (ada script_root atau bukan localhost)
    is_behind_domain = bool(request.script_root or (request.host and not request.host.startswith('127.0.0.1') and not request.host.startswith('localhost') and not request.host.startswith('0.0.0.0')))
    
    return jsonify({
        'local_ip': local_ip,
        'port': port,
        'prefix': prefix,
        'register_url_local': base_local,
        'register_url_lan': public_base if is_behind_domain else base_lan,
        'admin_url_local': f"{base_local}/admin",
        'admin_url_lan': f"{public_base}/admin" if is_behind_domain else f"{base_lan}/admin",
    })

@presenter_route('/api/qr-url.png')
def api_qr_url():
    """Menghasilkan QR Code untuk URL (misal link registrasi lokal / server)"""
    url_data = request.args.get('data', '').strip()
    if not url_data:
        port = int(os.environ.get('PORT', 5001))
        local_ip = get_local_ip()
        prefix = request.script_root.rstrip('/')
        is_behind_domain = bool(request.script_root or (request.host and not request.host.startswith('127.0.0.1') and not request.host.startswith('localhost') and not request.host.startswith('0.0.0.0')))
        if is_behind_domain:
            url_data = request.host_url.rstrip('/') + prefix
        else:
            url_data = f"http://{local_ip}:{port}{prefix}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url_data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    return send_file(buffer, mimetype='image/png')

@presenter_route('/api/qr/<qr_code>.png')
def api_qr_image(qr_code):
    """Menghasilkan file gambar PNG QR Code secara dinamis"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(qr_code.strip().upper())
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#1e293b", back_color="#ffffff")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='image/png',
        as_attachment=False,
        download_name=f"qr_presenter_semnasretro_{qr_code.lower()}.png"
    )

# ======================= PRESENTATIONS (JUDUL & RUANGAN) ADMIN ENDPOINTS =======================

@presenter_route('/api/admin/presentations', methods=['GET'])
@admin_required
def api_get_presentations():
    """Mengambil seluruh data judul presentasi, daftar ruangan, dan statistik"""
    search = request.args.get('search')
    ruangan = request.args.get('ruangan')
    items = database.get_all_presentations(search=search, ruangan=ruangan)
    ruangan_list = database.get_distinct_ruangan()
    stats = database.get_presentation_stats()
    return jsonify({
        'success': True,
        'data': items,
        'ruangan_list': ruangan_list,
        'stats': stats
    })

@presenter_route('/api/admin/presentations', methods=['POST'])
@admin_required
def api_add_presentation():
    """Menambahkan judul presentasi baru secara manual"""
    data = request.get_json() or {}
    judul = data.get('judul', '').strip()
    ruangan = data.get('ruangan', '-').strip()
    if not judul:
        return jsonify({'success': False, 'message': 'Judul presentasi wajib diisi!'}), 400
        
    pres = database.add_presentation(judul, ruangan)
    return jsonify({
        'success': True,
        'message': 'Judul presentasi berhasil ditambahkan!',
        'data': pres
    })

@presenter_route('/api/admin/presentations/<int:pres_id>', methods=['PUT', 'POST'])
@admin_required
def api_update_presentation(pres_id):
    """Mengubah data judul presentasi dan ruangan"""
    data = request.get_json() or {}
    judul = data.get('judul', '').strip()
    ruangan = data.get('ruangan', '-').strip()
    if not judul:
        return jsonify({'success': False, 'message': 'Judul presentasi wajib diisi!'}), 400
        
    success = database.update_presentation(pres_id, judul, ruangan)
    if success:
        return jsonify({'success': True, 'message': 'Judul presentasi berhasil diperbarui!'})
    return jsonify({'success': False, 'message': 'Judul presentasi tidak ditemukan atau gagal diperbarui.'}), 404

@presenter_route('/api/admin/presentations/<int:pres_id>', methods=['DELETE'])
@admin_required
def api_delete_presentation(pres_id):
    """Menghapus 1 judul presentasi"""
    success = database.delete_presentation(pres_id)
    if success:
        return jsonify({'success': True, 'message': 'Judul presentasi berhasil dihapus.'})
    return jsonify({'success': False, 'message': 'Judul presentasi tidak ditemukan.'}), 404

@presenter_route('/api/admin/presentations/reset', methods=['POST'])
@admin_required
def api_reset_presentations():
    """Menghapus seluruh daftar judul presentasi"""
    count = database.delete_all_presentations()
    return jsonify({'success': True, 'message': f'Semua judul presentasi ({count} data) berhasil dihapus.'})

@presenter_route('/api/admin/presentations/bulk-delete', methods=['POST'])
@admin_required
def api_bulk_delete_presentations():
    """Menghapus beberapa judul presentasi sekaligus berdasarkan daftar ID terpilih"""
    data = request.get_json() or {}
    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return jsonify({'success': False, 'message': 'Pilih minimal 1 judul presentasi untuk dihapus.'}), 400
    
    count = database.delete_presentations_bulk(ids)
    return jsonify({
        'success': True,
        'message': f'{count} judul presentasi berhasil dihapus.',
        'count': count
    })

def detect_delimiter(sample_text):
    """Mendeteksi delimiter file (Tab \t, Titik Koma ;, atau Koma ,) secara otomatis"""
    if not sample_text:
        return '\t'
    tab_count = sample_text.count('\t')
    semi_count = sample_text.count(';')
    comma_count = sample_text.count(',')
    
    # Utamakan Tab jika terdapat karakter tab, atau ambil delimiter dengan frekuensi tertinggi
    counts = [('\t', tab_count), (';', semi_count), (',', comma_count)]
    counts.sort(key=lambda x: x[1], reverse=True)
    if counts[0][1] > 0:
        return counts[0][0]
    return '\t'

GOOGLE_SHEET_TEMPLATE_URL = "https://docs.google.com/spreadsheets/d/1EHrfQH0qMvrTPE1OOtHUb959HQfnVVj13unNSs25VJI/edit?usp=sharing"

@presenter_route('/api/admin/presentations/template-csv', methods=['GET'])
@admin_required
def api_presentation_template_csv():
    """Mengarahkan pengguna ke Google Sheets template resmi untuk diunduh sebagai TSV"""
    return redirect(GOOGLE_SHEET_TEMPLATE_URL, code=302)

@presenter_route('/api/admin/presentations/import-csv', methods=['POST'])
@admin_required
def api_import_presentations_csv():
    """Mengimpor daftar judul presentasi & ruangan dari file TSV / CSV (Tab Delimiter)"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'File CSV / TSV tidak ditemukan dalam permintaan.'}), 400
        
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'success': False, 'message': 'Silakan pilih file TSV / CSV yang ingin diimpor.'}), 400

    try:
        raw_bytes = file.read()
        text = None
        for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
            try:
                text = raw_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
                
        if text is None:
            return jsonify({'success': False, 'message': 'Format encoding file tidak didukung.'}), 400

        stream = io.StringIO(text)
        sample = text[:4096]
        delimiter = detect_delimiter(sample)
        csv_reader = csv.reader(stream, delimiter=delimiter)
        
        rows = []
        for line in csv_reader:
            if line and any(field.strip() for field in line):
                rows.append([f.strip() for f in line])
                
        if not rows:
            return jsonify({'success': False, 'message': 'File TSV / CSV kosong atau tidak memiliki baris data.'}), 400

        first_row = [c.lower().strip() for c in rows[0]]
        judul_idx = -1
        ruang_idx = -1
        
        # Cari indeks kolom berdasarkan nama header di baris pertama
        for idx, col in enumerate(first_row):
            if any(k in col for k in ['judul', 'title', 'paper', 'makalah', 'artikel', 'topik', 'topic', 'naskah', 'presentasi', 'presentation', 'tema']):
                if judul_idx == -1:
                    judul_idx = idx
            elif any(k in col for k in ['ruang', 'ruangan', 'room', 'lokasi', 'tempat', 'kelas', 'sesi', 'link', 'zoom', 'auditorium', 'hall', 'lab']):
                if ruang_idx == -1:
                    ruang_idx = idx

        # Jika header tidak terdeteksi via keyword, tentukan mapping default berdasarkan jumlah kolom:
        if judul_idx == -1:
            if len(first_row) >= 3 and ('no' in first_row[0] or first_row[0].isdigit() or '#' in first_row[0]):
                judul_idx = 1
                ruang_idx = 2
            elif len(first_row) >= 2:
                # Kolom 0 = judul, kolom 1 = ruangan
                judul_idx = 0
                ruang_idx = 1
            else:
                judul_idx = 0
                ruang_idx = -1

        # SELALU lewati baris pertama (header)
        data_rows = rows[1:] if len(rows) > 1 else []
        
        inserted_count = 0
        skipped_count = 0
        
        for row in data_rows:
            if not row or not any(field.strip() for field in row):
                continue
            
            judul = row[judul_idx].strip() if (judul_idx != -1 and judul_idx < len(row)) else ''
            ruangan = row[ruang_idx].strip() if (ruang_idx != -1 and ruang_idx < len(row)) else '-'
            
            # Pengaman tambahan: lewati jika baris berisi nama header duplikat
            if judul.lower() in ['judul', 'judul presentasi', 'judul paper', 'title', 'paper title', 'no', 'nomor']:
                continue

            if not judul:
                skipped_count += 1
                continue
                
            database.add_presentation(judul, ruangan or '-')
            inserted_count += 1
            
        return jsonify({
            'success': True,
            'message': f'Impor data judul selesai! {inserted_count} judul presentasi berhasil ditambahkan.',
            'summary': {
                'total': inserted_count + skipped_count,
                'inserted': inserted_count,
                'skipped': skipped_count
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Gagal memproses file TSV / CSV judul: {str(e)}'}), 500

@presenter_route('/api/export-csv')
@admin_required
def export_csv():
    """Mengekspor daftar pendaftar/peserta ke file CSV dengan format UTF-8 (kompatibel Excel)"""
    status_filter = request.args.get('status') # 'pendaftar', 'peserta', or all
    ruangan_filter = request.args.get('ruangan')
    rows = database.get_participants(status=status_filter, ruangan=ruangan_filter)
    
    output = io.StringIO()
    # BOM untuk Excel agar encoding UTF-8 terbaca dengan rapi di Windows/Mac
    output.write('\ufeff')
    writer = csv.writer(output)
    
    writer.writerow(['No', 'Kode QR', 'No. Identitas (NIM/NIP/NIDN/NUPTK)', 'Nama Lengkap', 'Judul Presentasi', 'Ruangan', 'No. HP / WA', 'Institusi', 'Pekerjaan', 'Status', 'Waktu Pendaftaran', 'Waktu Hadir'])
    
    for idx, row in enumerate(rows, start=1):
        status_label = 'Peserta (Hadir)' if row['status'] == 'peserta' else 'Pendaftar (Belum Hadir)'
        writer.writerow([
            idx,
            row['qr_code'],
            row['nim_nip'],
            row['nama_lengkap'],
            row.get('judul_presentasi') or '-',
            row.get('ruangan') or '-',
            row['no_hp'] or '-',
            row['institusi'],
            row['pekerjaan'],
            status_label,
            row['created_at'],
            row['attended_at'] or '-'
        ])
        
    filename = f"daftar_presenter_{status_filter or 'semua'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

@presenter_route('/api/import-csv', methods=['POST'])
@admin_required
def import_csv():
    """Mengimpor data pendaftar & peserta keseluruhan dari file CSV backup"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'File CSV tidak ditemukan dalam permintaan.'}), 400
        
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'success': False, 'message': 'Silakan pilih file CSV yang ingin diimpor.'}), 400
        
    overwrite = request.form.get('overwrite', 'true').lower() in ['true', '1', 'yes']

    try:
        raw_bytes = file.read()
        text = None
        for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
            try:
                text = raw_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
                
        if text is None:
            return jsonify({'success': False, 'message': 'Format encoding file tidak didukung.'}), 400

        stream = io.StringIO(text)
        sample = text[:4096]
        delimiter = detect_delimiter(sample)
        csv_reader = csv.reader(stream, delimiter=delimiter)
        
        rows = []
        for line in csv_reader:
            if line and any(field.strip() for field in line):
                rows.append([f.strip() for f in line])
                
        if not rows:
            return jsonify({'success': False, 'message': 'File CSV kosong atau tidak memiliki baris data.'}), 400

        first_row = [c.lower() for c in rows[0]]
        has_header = False
        header_map = {}
        
        known_headers = {
            'qr_code': ['kode qr', 'qr_code', 'qr', 'kode', 'qrcode'],
            'nim_nip': ['no. identitas (nim/nip/nidn/nuptk)', 'no. identitas', 'no identitas', 'nomor identitas', 'nim / nip', 'nim/nip', 'nim_nip', 'nim', 'nip', 'nidn', 'nuptk', 'nik', 'ktp', 'nomor induk'],
            'nama_lengkap': ['nama lengkap', 'nama_lengkap', 'nama', 'fullname', 'name'],
            'judul_presentasi': ['judul presentasi', 'judul paper', 'judul', 'title', 'paper title', 'topik', 'judul_presentasi'],
            'ruangan': ['ruangan', 'ruang', 'room', 'lokasi', 'tempat'],
            'no_hp': ['no. hp / wa', 'no hp / wa', 'no. hp', 'no hp', 'nomor hp', 'no telepon', 'telepon', 'whatsapp', 'no wa', 'phone', 'mobile', 'no_hp'],
            'institusi': ['institusi', 'instansi', 'universitas', 'kampus', 'perusahaan', 'institution'],
            'pekerjaan': ['pekerjaan', 'profesi', 'kategori', 'job', 'occupation'],
            'status': ['status', 'status kehadiran', 'kehadiran', 'attendance'],
            'created_at': ['waktu pendaftaran', 'created_at', 'tanggal daftar', 'waktu daftar', 'created'],
            'attended_at': ['waktu hadir', 'attended_at', 'waktu absen', 'waktu scan', 'attended']
        }
        
        for col_idx, col_name in enumerate(first_row):
            cleaned_col = col_name.strip().lower()
            for key, aliases in known_headers.items():
                if cleaned_col in aliases:
                    header_map[key] = col_idx
                    has_header = True
                    break

        data_rows = rows[1:] if has_header else rows
        
        if not data_rows:
            return jsonify({'success': False, 'message': 'Tidak ada baris data peserta dalam file CSV.'}), 400

        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        for row_num, row in enumerate(data_rows, start=2 if has_header else 1):
            if not row or not any(row):
                continue
                
            try:
                if has_header and 'nim_nip' in header_map and 'nama_lengkap' in header_map:
                    qr_code = row[header_map['qr_code']] if 'qr_code' in header_map and header_map['qr_code'] < len(row) else ''
                    nim_nip = row[header_map['nim_nip']] if header_map['nim_nip'] < len(row) else ''
                    nama_lengkap = row[header_map['nama_lengkap']] if header_map['nama_lengkap'] < len(row) else ''
                    judul_presentasi = row[header_map['judul_presentasi']] if 'judul_presentasi' in header_map and header_map['judul_presentasi'] < len(row) else ''
                    ruangan = row[header_map['ruangan']] if 'ruangan' in header_map and header_map['ruangan'] < len(row) else '-'
                    no_hp = row[header_map['no_hp']] if 'no_hp' in header_map and header_map['no_hp'] < len(row) else ''
                    institusi = row[header_map['institusi']] if 'institusi' in header_map and header_map['institusi'] < len(row) else '-'
                    pekerjaan = row[header_map['pekerjaan']] if 'pekerjaan' in header_map and header_map['pekerjaan'] < len(row) else 'Lainnya'
                    status = row[header_map['status']] if 'status' in header_map and header_map['status'] < len(row) else 'pendaftar'
                    created_at = row[header_map['created_at']] if 'created_at' in header_map and header_map['created_at'] < len(row) else None
                    attended_at = row[header_map['attended_at']] if 'attended_at' in header_map and header_map['attended_at'] < len(row) else None
                else:
                    if len(row) >= 12 and row[0].isdigit():
                        # [No, QR, NIM, Nama, Judul, Ruang, NoHP, Institusi, Pekerjaan, Status, WaktuDaftar, WaktuHadir]
                        qr_code = row[1]
                        nim_nip = row[2]
                        nama_lengkap = row[3]
                        judul_presentasi = row[4]
                        ruangan = row[5]
                        no_hp = row[6]
                        institusi = row[7]
                        pekerjaan = row[8]
                        status = row[9]
                        created_at = row[10]
                        attended_at = row[11]
                    elif len(row) >= 10 and row[0].isdigit():
                        # [No, QR, NIM, Nama, NoHP, Institusi, Pekerjaan, Status, WaktuDaftar, WaktuHadir]
                        qr_code = row[1]
                        nim_nip = row[2]
                        nama_lengkap = row[3]
                        judul_presentasi = ''
                        ruangan = '-'
                        no_hp = row[4]
                        institusi = row[5]
                        pekerjaan = row[6]
                        status = row[7]
                        created_at = row[8]
                        attended_at = row[9]
                    elif len(row) >= 4:
                        qr_code = ''
                        nim_nip = row[0]
                        nama_lengkap = row[1]
                        judul_presentasi = row[2] if len(row) > 4 else ''
                        ruangan = row[3] if len(row) > 5 else '-'
                        no_hp = row[4] if len(row) > 5 else ''
                        institusi = row[5] if len(row) > 6 else '-'
                        pekerjaan = 'Lainnya'
                        status = 'pendaftar'
                        created_at = None
                        attended_at = None
                    else:
                        error_count += 1
                        continue

                if not nim_nip or not nama_lengkap:
                    error_count += 1
                    continue
                    
                nim_nip = html.escape(nim_nip[:30])
                nama_lengkap = html.escape(nama_lengkap[:100])
                judul_presentasi = html.escape((judul_presentasi or '')[:255])
                ruangan = html.escape((ruangan or '-')[:50])
                no_hp = html.escape((no_hp or '')[:20])
                institusi = html.escape((institusi or '-')[:120])
                pekerjaan = html.escape((pekerjaan or 'Lainnya')[:50])

                res = database.upsert_participant_from_csv(
                    qr_code=qr_code,
                    nim_nip=nim_nip,
                    nama_lengkap=nama_lengkap,
                    no_hp=no_hp,
                    institusi=institusi,
                    pekerjaan=pekerjaan,
                    judul_presentasi=judul_presentasi,
                    ruangan=ruangan,
                    status=status,
                    created_at=created_at,
                    attended_at=attended_at,
                    overwrite=overwrite
                )
                
                if res == 'inserted':
                    inserted_count += 1
                elif res == 'updated':
                    updated_count += 1
                else:
                    skipped_count += 1
            except Exception:
                error_count += 1
                continue

        total_processed = inserted_count + updated_count + skipped_count
        msg = f"Impor data CSV selesai! {inserted_count} data baru ditambahkan, {updated_count} data diperbarui."
        if skipped_count > 0:
            msg += f" ({skipped_count} data dilewati)."
            
        return jsonify({
            'success': True,
            'message': msg,
            'summary': {
                'total': total_processed,
                'inserted': inserted_count,
                'updated': updated_count,
                'skipped': skipped_count,
                'errors': error_count
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Gagal memproses file CSV: {str(e)}'}), 500

if __name__ == '__main__':
    ACTIVE_PORT = int(os.environ.get('PORT', 5001))
    local_ip = get_local_ip()
    
    print("\n" + "="*65)
    print("🚀 SISTEM ABSEN PRESENTER AKTIF & TERKONEKSI (PORT 5001)")
    print("="*65)
    print(f"📍 Akses Publik (Pendaftar Presenter):")
    print(f"   • Form Pendaftaran : http://127.0.0.1:{ACTIVE_PORT}")
    print(f"   • Via Wi-Fi/HP     : http://{local_ip}:{ACTIVE_PORT}")
    print(f"\n🔐 Akses Khusus Admin Presenter:")
    print(f"   • Login Admin      : http://127.0.0.1:{ACTIVE_PORT}/admin")
    print(f"   • Via Wi-Fi/HP     : http://{local_ip}:{ACTIVE_PORT}/admin")
    print("="*65 + "\n")
    app.run(host='0.0.0.0', port=ACTIVE_PORT, debug=False)
