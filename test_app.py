import unittest
import json
import os
import database
from app import app

class SeminarAttendanceSystemTestCase(unittest.TestCase):
    def setUp(self):
        # Gunakan database sementara untuk pengujian
        self.test_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_seminar.db")
        database.DB_PATH = self.test_db
        database.init_db()
        self.app = app.test_client()
        self.app.testing = True
        import app as app_module
        app_module.registration_history.clear()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def login_admin(self, username='admin', password='admin123'):
        return self.app.post('/api/login', json={'username': username, 'password': password})

    def test_01_qr_code_generation(self):
        """Uji bahwa kode QR adalah 10 karakter alfanumerik kapital"""
        code = database.generate_unique_qr_code()
        self.assertEqual(len(code), 10)
        self.assertTrue(code.isalnum())
        self.assertEqual(code, code.upper())

    def test_02_registration(self):
        """Uji pendaftaran peserta baru masuk ke status 'pendaftar'"""
        res = self.app.post('/api/register', json={
            'nim_nip': '2110511001',
            'nama_lengkap': 'Ahmad Fauzi',
            'no_hp': '081234567890',
            'institusi': 'Universitas Indonesia',
            'pekerjaan': 'Mahasiswa'
        })
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        p = data['data']
        self.assertEqual(p['status'], 'pendaftar')
        self.assertEqual(len(p['qr_code']), 10)
        self.assertEqual(p['nama_lengkap'], 'Ahmad Fauzi')
        self.assertEqual(p['no_hp'], '081234567890')
        self.assertIsNone(p['attended_at'])

    def test_03_auth_protection_and_login(self):
        """Uji proteksi route console/admin dan proses login/logout"""
        # Tanpa login -> akses /admin diarahkan ke /console (status 302)
        res_admin = self.app.get('/admin')
        self.assertEqual(res_admin.status_code, 302)

        # Tanpa login -> akses /console menampilkan form login (status 200)
        res_console = self.app.get('/console')
        self.assertEqual(res_console.status_code, 200)
        self.assertTrue('Masuk ke Console' in res_console.data.decode('utf-8'))

        # Tanpa login -> akses API dilindungi status 401
        res_api = self.app.get('/api/participants')
        self.assertEqual(res_api.status_code, 401)

        # Login salah
        bad_login = self.app.post('/api/login', json={'username': 'admin', 'password': 'wrongpassword'})
        self.assertEqual(bad_login.status_code, 401)

        # Login benar
        good_login = self.login_admin()
        self.assertEqual(good_login.status_code, 200)
        self.assertTrue(json.loads(good_login.data)['success'])

        # Sekarang akses /console menampilkan Dashboard Console Admin
        auth_console = self.app.get('/console')
        self.assertEqual(auth_console.status_code, 200)
        self.assertTrue('Console Absensi Presenter' in auth_console.data.decode('utf-8'))

        # Logout
        self.app.post('/api/logout')
        res_after = self.app.get('/api/participants')
        self.assertEqual(res_after.status_code, 401)

    def test_04_scan_attendance(self):
        """Uji pemindaian QR code mengubah status dari 'pendaftar' menjadi 'peserta'"""
        self.login_admin()

        # 1. Daftar dulu
        reg_res = self.app.post('/api/register', json={
            'nim_nip': '198701012015041001',
            'nama_lengkap': 'Prof. Dr. Rina Wijaya',
            'no_hp': '081299998888',
            'institusi': 'ITB',
            'pekerjaan': 'Dosen'
        })
        p = json.loads(reg_res.data)['data']
        qr_code = p['qr_code']

        # 2. Scan pertama kali -> Berhasil Hadir
        scan_res = self.app.post('/api/scan', json={'qr_code': qr_code})
        scan_data = json.loads(scan_res.data)
        self.assertTrue(scan_data['success'])
        self.assertEqual(scan_data['code'], 'SUCCESS')
        self.assertEqual(scan_data['data']['status'], 'peserta')

        # 3. Scan kedua kali -> Sudah Hadir
        again_res = self.app.post('/api/scan', json={'qr_code': qr_code})
        again_data = json.loads(again_res.data)
        self.assertFalse(again_data['success'])
        self.assertEqual(again_data['code'], 'ALREADY_ATTENDED')

        # 4. Scan QR code yang tidak ada -> NOT_FOUND
        invalid_scan = self.app.post('/api/scan', json={'qr_code': 'INVALID123'})
        invalid_data = json.loads(invalid_scan.data)
        self.assertFalse(invalid_data['success'])
        self.assertEqual(invalid_data['code'], 'NOT_FOUND')

    def test_05_participants_information_menus(self):
        """Uji menu informasi peserta memisahkan Pendaftar (belum hadir) dan Peserta (sudah hadir)"""
        self.login_admin()

        # Daftarkan 2 orang
        p1 = json.loads(self.app.post('/api/register', json={
            'nim_nip': '111', 'nama_lengkap': 'Peserta 1 (Belum Hadir)', 'no_hp': '08120000001', 'institusi': 'Inst A', 'pekerjaan': 'Mahasiswa'
        }).data)['data']

        p2 = json.loads(self.app.post('/api/register', json={
            'nim_nip': '222', 'nama_lengkap': 'Peserta 2 (Akan Scan Hadir)', 'no_hp': '08120000002', 'institusi': 'Inst B', 'pekerjaan': 'Praktisi'
        }).data)['data']

        # Scan p2 agar hadir
        self.app.post('/api/scan', json={'qr_code': p2['qr_code']})

        # Cek daftar 'pendaftar' (harus hanya berisi p1)
        res_pendaftar = self.app.get('/api/participants?status=pendaftar')
        pendaftar_list = json.loads(res_pendaftar.data)['data']
        self.assertEqual(len(pendaftar_list), 1)
        self.assertEqual(pendaftar_list[0]['id'], p1['id'])

        # Cek daftar 'peserta' (harus hanya berisi p2)
        res_peserta = self.app.get('/api/participants?status=peserta')
        peserta_list = json.loads(res_peserta.data)['data']
        self.assertEqual(len(peserta_list), 1)
        self.assertEqual(peserta_list[0]['id'], p2['id'])

        # Cek stats
        stats_res = self.app.get('/api/stats')
        stats = json.loads(stats_res.data)['stats']
        self.assertEqual(stats['total'], 2)
        self.assertEqual(stats['pendaftar'], 1)
        self.assertEqual(stats['peserta'], 1)
        self.assertEqual(stats['attendance_rate'], 50.0)

    def test_06_qr_image_and_export(self):
        """Uji download gambar QR dan export CSV"""
        self.login_admin()

        p = json.loads(self.app.post('/api/register', json={
            'nim_nip': '333', 'nama_lengkap': 'Budi', 'no_hp': '081233333333', 'institusi': 'UGM', 'pekerjaan': 'Lainnya'
        }).data)['data']

        # QR Image (Public)
        qr_img_res = self.app.get(f'/api/qr/{p["qr_code"]}.png')
        self.assertEqual(qr_img_res.status_code, 200)
        self.assertEqual(qr_img_res.mimetype, 'image/png')

        # CSV Export (Admin only)
        csv_res = self.app.get('/api/export-csv')
        self.assertEqual(csv_res.status_code, 200)
        self.assertTrue('text/csv' in csv_res.mimetype)
        self.assertTrue('Budi' in csv_res.data.decode('utf-8'))

    def test_07_event_settings(self):
        """Uji pengelolaan nama acara dan logo"""
        self.login_admin()

        # Update event name
        update_res = self.app.post('/api/settings', data={'event_name': 'Workshop AI Vision 2026'})
        self.assertEqual(update_res.status_code, 200)
        new_settings = json.loads(update_res.data)['settings']
        self.assertEqual(new_settings['event_name'], 'Workshop AI Vision 2026')

        # Reset logo
        reset_res = self.app.post('/api/settings/reset-logo')
        self.assertEqual(reset_res.status_code, 200)
        self.assertEqual(json.loads(reset_res.data)['settings']['event_logo'], '')

    def test_08_superadmin_user_management(self):
        """Uji 5 user default, Super Admin mereset password admin lain, dan pembatasan hak akses"""
        # 1. Login sebagai Super Admin
        self.login_admin('admin', 'admin123')

        # 2. Super Admin mengambil daftar seluruh user admin (harus ada minimal 5 user)
        res_users = self.app.get('/api/admin/users')
        self.assertEqual(res_users.status_code, 200)
        users = json.loads(res_users.data)['data']
        self.assertGreaterEqual(len(users), 5)
        
        usernames = [u['username'] for u in users]
        self.assertIn('admin', usernames)
        self.assertIn('petugas1', usernames)
        self.assertIn('petugas2', usernames)
        self.assertIn('petugas3', usernames)
        self.assertIn('petugas4', usernames)

        # Temukan ID petugas1
        petugas1 = next(u for u in users if u['username'] == 'petugas1')

        # 3. Super Admin mereset password petugas1 menjadi 'rahasiaBaru789'
        reset_res = self.app.post(f'/api/admin/users/{petugas1["id"]}/reset-password', json={
            'new_password': 'rahasiaBaru789'
        })
        self.assertEqual(reset_res.status_code, 200)

        # 4. Logout Super Admin
        self.app.post('/api/logout')

        # 5. Petugas1 login dengan password lama (harus gagal)
        old_login = self.login_admin('petugas1', 'admin123')
        self.assertEqual(old_login.status_code, 401)

        # 6. Petugas1 login dengan password baru (harus sukses)
        new_login = self.login_admin('petugas1', 'rahasiaBaru789')
        self.assertEqual(new_login.status_code, 200)
        user_info = json.loads(new_login.data)['user']
        self.assertEqual(user_info['role'], 'admin')

        # 7. Petugas1 (admin biasa) mencoba mengakses endpoint Super Admin (harus 403 Forbidden)
        forbidden_res = self.app.get('/api/admin/users')
        self.assertEqual(forbidden_res.status_code, 403)

    def test_09_xss_and_anti_spam_security(self):
        """Uji perlindungan XSS, Deteksi Duplikasi NIM, Anti-Bot Honeypot, dan Rate Limiting"""
        import app as app_module
        app_module.registration_history.clear()

        # 1. Uji XSS Sanitization: Input tag skrip berbahaya harus di-escape
        xss_res = self.app.post('/api/register', json={
            'nim_nip': '9990001',
            'nama_lengkap': '<script>alert("hacked")</script>Budi',
            'no_hp': '081234567890',
            'institusi': '<img src=x onerror=alert(1)>ITB',
            'pekerjaan': 'Mahasiswa'
        })
        self.assertEqual(xss_res.status_code, 200)
        data = json.loads(xss_res.data)['data']
        # Pastikan tag HTML berbahaya diubah menjadi HTML entity aman
        self.assertNotIn('<script>', data['nama_lengkap'])
        self.assertIn('&lt;script&gt;', data['nama_lengkap'])
        self.assertNotIn('<img', data['institusi'])
        self.assertIn('&lt;img', data['institusi'])

        # 2. Uji Deteksi Duplikasi NIM/NIP
        dup_res = self.app.post('/api/register', json={
            'nim_nip': '9990001',
            'nama_lengkap': 'Budi Duplikat',
            'no_hp': '081234567890',
            'institusi': 'ITB',
            'pekerjaan': 'Mahasiswa'
        })
        self.assertEqual(dup_res.status_code, 400)
        dup_data = json.loads(dup_res.data)
        self.assertEqual(dup_data['code'], 'DUPLICATE_NIM')

        # 3. Uji Anti-Bot Honeypot: Jika field bot terisi, request ditolak
        bot_res = self.app.post('/api/register', json={
            'nim_nip': '9990002',
            'nama_lengkap': 'Spam Bot',
            'no_hp': '081234567890',
            'institusi': 'Spam Corp',
            'pekerjaan': 'Mahasiswa',
            'website_url': 'http://spam-link.com'
        })
        self.assertEqual(bot_res.status_code, 400)

        # 4. Uji Rate Limiting: Maksimal 5 pendaftaran per IP, pendaftaran ke-6 harus kena 429
        app_module.registration_history.clear()
        
        # Kirim 5 pendaftaran sukses
        for i in range(1, 6):
            r = self.app.post('/api/register', json={
                'nim_nip': f'888000{i}',
                'nama_lengkap': f'Peserta {i}',
                'no_hp': f'0812000000{i}',
                'institusi': 'Kampus',
                'pekerjaan': 'Mahasiswa'
            })
            self.assertEqual(r.status_code, 200)

        # Pendaftaran ke-6 (melebihi limit 5 per menit)
        rate_limit_res = self.app.post('/api/register', json={
            'nim_nip': '8880099',
            'nama_lengkap': 'Peserta Terblokir',
            'no_hp': '08120000099',
            'institusi': 'Kampus',
            'pekerjaan': 'Mahasiswa'
        })
        self.assertEqual(rate_limit_res.status_code, 429)

    def test_10_csv_import_restore(self):
        """Uji impor data dari file CSV backup (pendaftar dan peserta)"""
        self.login_admin()

        csv_content = """No,Kode QR,NIM / NIP,Nama Lengkap,No. HP / WA,Institusi,Pekerjaan,Status,Waktu Pendaftaran,Waktu Hadir
1,IMPQR00001,1122334455,Budi Handoko,081234567891,Universitas Gadjah Mada,Mahasiswa,Pendaftar (Belum Hadir),2026-09-01 08:00:00,-
2,IMPQR00002,1122334466,Dr. Siti Rahma,081234567892,Institut Teknologi Bandung,Dosen,Peserta (Hadir),2026-09-01 08:15:00,2026-09-01 09:30:00
3,IMPQR00003,1122334477,Hendro Prakoso,081234567893,PT Inovasi Digital,Praktisi,Peserta (Hadir),2026-09-01 08:30:00,2026-09-01 09:45:00
"""
        # 1. Kirim file CSV via POST /api/import-csv
        import io
        data = {
            'file': (io.BytesIO(csv_content.encode('utf-8')), 'backup_seminar.csv'),
            'overwrite': 'true'
        }
        res = self.app.post('/api/import-csv', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        res_json = json.loads(res.data)
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['summary']['total'], 3)
        self.assertEqual(res_json['summary']['inserted'], 3)

        # 2. Verifikasi data tersimpan di database beserta no_hp
        p1 = database.get_participant_by_qr('IMPQR00001')
        self.assertIsNotNone(p1)
        self.assertEqual(p1['nama_lengkap'], 'Budi Handoko')
        self.assertEqual(p1['no_hp'], '081234567891')
        self.assertEqual(p1['status'], 'pendaftar')
        self.assertIsNone(p1['attended_at'])

        p2 = database.get_participant_by_qr('IMPQR00002')
        self.assertIsNotNone(p2)
        self.assertEqual(p2['nama_lengkap'], 'Dr. Siti Rahma')
        self.assertEqual(p2['no_hp'], '081234567892')
        self.assertEqual(p2['status'], 'peserta')
        self.assertEqual(p2['attended_at'], '2026-09-01 09:30:00')

        # 3. Uji update data via import dengan overwrite=true
        updated_csv = """No,Kode QR,NIM / NIP,Nama Lengkap,No. HP / WA,Institusi,Pekerjaan,Status,Waktu Pendaftaran,Waktu Hadir
1,IMPQR00001,1122334455,Budi Handoko M.Kom,081234567899,Universitas Gadjah Mada,Dosen,Peserta (Hadir),2026-09-01 08:00:00,2026-09-01 10:00:00
"""
        data2 = {
            'file': (io.BytesIO(updated_csv.encode('utf-8')), 'backup_update.csv'),
            'overwrite': 'true'
        }
        res2 = self.app.post('/api/import-csv', data=data2, content_type='multipart/form-data')
        self.assertEqual(res2.status_code, 200)
        res_json2 = json.loads(res2.data)
        self.assertEqual(res_json2['summary']['updated'], 1)

        p1_updated = database.get_participant_by_qr('IMPQR00001')
        self.assertEqual(p1_updated['nama_lengkap'], 'Budi Handoko M.Kom')
        self.assertEqual(p1_updated['no_hp'], '081234567899')
        self.assertEqual(p1_updated['status'], 'peserta')

    def test_11_no_hp_support_and_search(self):
        """Uji fungsionalitas kolom no_hp pada registrasi, pencarian, dan export CSV"""
        self.login_admin()

        # 1. Daftarkan 2 peserta dengan nomor HP berbeda
        r1 = self.app.post('/api/register', json={
            'nim_nip': '7770001',
            'nama_lengkap': 'Doni Prasetya',
            'no_hp': '085711223344',
            'institusi': 'Undip',
            'pekerjaan': 'Mahasiswa'
        })
        self.assertEqual(r1.status_code, 200)

        r2 = self.app.post('/api/register', json={
            'nim_nip': '7770002',
            'nama_lengkap': 'Fitri Handayani',
            'no_hp': '087855667788',
            'institusi': 'Unair',
            'pekerjaan': 'Dosen'
        })
        self.assertEqual(r2.status_code, 200)

        # 2. Cari berdasarkan nomor HP
        search_res = self.app.get('/api/participants?search=085711223344')
        self.assertEqual(search_res.status_code, 200)
        search_data = json.loads(search_res.data)
        self.assertEqual(len(search_data['data']), 1)
        self.assertEqual(search_data['data'][0]['nama_lengkap'], 'Doni Prasetya')
        self.assertEqual(search_data['data'][0]['no_hp'], '085711223344')

        # 3. Export CSV dan periksa kolom No. HP / WA di header dan baris
        exp_res = self.app.get('/api/export-csv')
        self.assertEqual(exp_res.status_code, 200)
        csv_text = exp_res.data.decode('utf-8')
        self.assertIn('No. HP / WA', csv_text)
        self.assertIn('085711223344', csv_text)
        self.assertIn('087855667788', csv_text)

    def test_12_proxy_prefix_support(self):
        """Uji fungsionalitas subpath prefix /absen dan header proxy"""
        # Request dengan header X-Forwarded-Prefix dari reverse proxy Nginx
        headers = {
            'X-Forwarded-Prefix': '/absen',
            'X-Forwarded-Proto': 'https',
            'Host': 'ppid.ft.unmul.ac.id'
        }

        # 1. Halaman utama harus menyertakan window.BASE_URL = "/absen"
        res = self.app.get('/', headers=headers)
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('window.BASE_URL = "/absen"', html)
        self.assertIn('href="/absen/"', html)

        # 2. Redirect tanpa login ke /admin harus mengarahkan ke /absen/console
        res_admin = self.app.get('/admin', headers=headers)
        self.assertEqual(res_admin.status_code, 302)
        self.assertIn('/absen/console', res_admin.location)

        # 3. Endpoint network-info harus mengenali prefix publik
        res_net = self.app.get('/api/network-info', headers=headers)
        self.assertEqual(res_net.status_code, 200)
        net_data = json.loads(res_net.data)
        self.assertEqual(net_data['prefix'], '/absen')
        self.assertIn('/absen', net_data['register_url_lan'])

    def test_13_presentation_crud_and_public_api(self):
        """Uji manajemen judul presentasi (CRUD Admin) dan endpoint publik dropdown"""
        self.login_admin()

        # 1. Tambah judul presentasi manual
        add_res = self.app.post('/api/admin/presentations', json={
            'judul': 'Penerapan Transformer untuk Analisis Sentimen',
            'ruangan': 'Ruang 101'
        })
        self.assertEqual(add_res.status_code, 200)
        pres_id = json.loads(add_res.data)['data']['id']

        # 2. Ambil list admin
        list_res = self.app.get('/api/admin/presentations')
        self.assertEqual(list_res.status_code, 200)
        list_data = json.loads(list_res.data)
        self.assertEqual(len(list_data['data']), 1)
        self.assertEqual(list_data['data'][0]['judul'], 'Penerapan Transformer untuk Analisis Sentimen')
        self.assertEqual(list_data['data'][0]['ruangan'], 'Ruang 101')
        self.assertFalse(list_data['data'][0]['is_taken'])

        # 3. Ambil list publik (untuk dropdown registrasi)
        pub_res = self.app.get('/api/presentations/public')
        self.assertEqual(pub_res.status_code, 200)
        pub_data = json.loads(pub_res.data)['data']
        self.assertEqual(len(pub_data), 1)
        self.assertEqual(pub_data[0]['id'], pres_id)
        self.assertFalse(pub_data[0]['is_taken'])

        # 4. Edit judul & ruangan
        edit_res = self.app.post(f'/api/admin/presentations/{pres_id}', json={
            'judul': 'Penerapan LLM & Transformer untuk Sentimen',
            'ruangan': 'Ruang A-1'
        })
        self.assertEqual(edit_res.status_code, 200)
        updated_pres = database.get_presentation_by_id(pres_id)
        self.assertEqual(updated_pres['judul'], 'Penerapan LLM & Transformer untuk Sentimen')
        self.assertEqual(updated_pres['ruangan'], 'Ruang A-1')

        # 5. Hapus judul
        del_res = self.app.delete(f'/api/admin/presentations/{pres_id}')
        self.assertEqual(del_res.status_code, 200)
        self.assertIsNone(database.get_presentation_by_id(pres_id))

    def test_14_presentation_csv_import_and_template(self):
        """Uji download template TSV (Tab Delimited) judul dan bulk import judul dari TSV / CSV"""
        self.login_admin()

        # 1. Download/Redirect template TSV Google Sheets
        tpl_res = self.app.get('/api/admin/presentations/template-csv')
        self.assertEqual(tpl_res.status_code, 302)
        self.assertIn('docs.google.com/spreadsheets', tpl_res.location)

        # 2. Impor judul dari file TSV (Tab Delimited)
        import io
        tsv_content = "Judul Presentasi\tRuangan\nAnalisis Big Data untuk Smart City\tRuang Alpha\nKeamanan Jaringan IoT Berbasis Blockchain\tRuang Beta\nOptimasi Algoritma Genetika pada Robotika\tRuang Gamma\n"
        data = {
            'file': (io.BytesIO(tsv_content.encode('utf-8')), 'daftar_judul.tsv')
        }
        imp_res = self.app.post('/api/admin/presentations/import-csv', data=data, content_type='multipart/form-data')
        self.assertEqual(imp_res.status_code, 200)
        imp_data = json.loads(imp_res.data)
        self.assertTrue(imp_data['success'])
        self.assertEqual(imp_data['summary']['inserted'], 3)

        # Verifikasi judul masuk ke database
        all_pres = database.get_all_presentations()
        self.assertEqual(len(all_pres), 3)

    def test_15_single_presenter_claim_restriction(self):
        """Uji aturan 1 judul hanya 1 presenter (mencegah judul ganda/double-booking)"""
        # 1. Buat 1 judul
        pres = database.add_presentation('Sistem Deteksi Penyakit Tanaman', 'Ruang Botani')
        pres_id = pres['id']

        # 2. Presenter 1 mendaftar memilih judul tersebut -> Sukses
        r1 = self.app.post('/api/register', json={
            'presentation_id': pres_id,
            'nim_nip': '12345001',
            'nama_lengkap': 'Presenter Pertama',
            'no_hp': '0811111111',
            'institusi': 'IPB',
            'pekerjaan': 'Dosen'
        })
        self.assertEqual(r1.status_code, 200)
        d1 = json.loads(r1.data)['data']
        self.assertEqual(d1['judul_presentasi'], 'Sistem Deteksi Penyakit Tanaman')
        self.assertEqual(d1['ruangan'], 'Ruang Botani')

        # 3. Presenter 2 mencoba mendaftar dengan judul yang SAMA -> Gagal (400)
        r2 = self.app.post('/api/register', json={
            'presentation_id': pres_id,
            'nim_nip': '12345002',
            'nama_lengkap': 'Presenter Kedua',
            'no_hp': '0822222222',
            'institusi': 'ITB',
            'pekerjaan': 'Mahasiswa'
        })
        self.assertEqual(r2.status_code, 400)
        r2_data = json.loads(r2.data)
        self.assertFalse(r2_data['success'])
        self.assertIn('sudah dipilih', r2_data['message'])

        # 4. Cek API publik: status judul harus is_taken: true dengan presenter_name: 'Presenter Pertama'
        pub_res = self.app.get('/api/presentations/public')
        pub_items = json.loads(pub_res.data)['data']
        target_pres = next(p for p in pub_items if p['id'] == pres_id)
        self.assertTrue(target_pres['is_taken'])
        self.assertEqual(target_pres['presenter_name'], 'Presenter Pertama')

    def test_16_participant_export_and_import_with_presentation(self):
        """Uji ekspor & impor peserta yang menyertakan Judul Presentasi dan Ruangan"""
        self.login_admin()

        # Buat judul dan daftarkan presenter
        pres = database.add_presentation('AI dalam Medis', 'Ruang 301')
        self.app.post('/api/register', json={
            'presentation_id': pres['id'],
            'nim_nip': '555001',
            'nama_lengkap': 'dr. Maya Sari',
            'no_hp': '0812555001',
            'institusi': 'RS Medika',
            'pekerjaan': 'Praktisi'
        })

        # 1. Export CSV harus memiliki header Judul Presentasi dan Ruangan
        exp_res = self.app.get('/api/export-csv')
        self.assertEqual(exp_res.status_code, 200)
        csv_text = exp_res.data.decode('utf-8')
        self.assertIn('Judul Presentasi', csv_text)
        self.assertIn('Ruangan', csv_text)
        self.assertIn('AI dalam Medis', csv_text)
        self.assertIn('Ruang 301', csv_text)

        # 2. Impor CSV dengan kolom Judul Presentasi dan Ruangan
        import io
        import_csv = """No,Kode QR,NIM / NIP,Nama Lengkap,Judul Presentasi,Ruangan,No. HP / WA,Institusi,Pekerjaan,Status,Waktu Pendaftaran,Waktu Hadir
1,IMPPRES001,666001,Dr. Hendra Gunawan,Cyber Security Framework,Ruang Lab A,0812666001,Universitas Brawijaya,Dosen,Peserta (Hadir),2026-09-01 08:00:00,2026-09-01 09:00:00
"""
        data = {
            'file': (io.BytesIO(import_csv.encode('utf-8')), 'presenters.csv'),
            'overwrite': 'true'
        }
        res_imp = self.app.post('/api/import-csv', data=data, content_type='multipart/form-data')
        self.assertEqual(res_imp.status_code, 200)
        
        # Verifikasi data presenter tersimpan
        p = database.get_participant_by_qr('IMPPRES001')
        self.assertIsNotNone(p)
        self.assertEqual(p['nama_lengkap'], 'Dr. Hendra Gunawan')
        self.assertEqual(p['judul_presentasi'], 'Cyber Security Framework')
        self.assertEqual(p['ruangan'], 'Ruang Lab A')
        self.assertEqual(p['status'], 'peserta')

    def test_17_distinct_ruangan_and_filtering(self):
        """Uji endpoint distinct ruangan dan filter peserta berdasarkan ruangan"""
        self.login_admin()

        database.add_presentation('Judul 1', 'Ruang Alpha')
        database.add_presentation('Judul 2', 'Ruang Beta')
        database.add_presentation('Judul 3', 'Ruang Alpha')

        rooms = database.get_distinct_ruangan()
        self.assertEqual(sorted(rooms), ['Ruang Alpha', 'Ruang Beta'])

    def test_18_presentation_bulk_delete(self):
        """Uji endpoint bulk delete judul presentasi (hapus banyak judul sekaligus via checkbox)"""
        self.login_admin()

        p1 = database.add_presentation('Judul Hapus 1', 'Ruang A')
        p2 = database.add_presentation('Judul Hapus 2', 'Ruang B')
        p3 = database.add_presentation('Judul Simpan 3', 'Ruang C')

        # Hapus p1 dan p2 sekaligus
        del_res = self.app.post('/api/admin/presentations/bulk-delete', json={
            'ids': [p1['id'], p2['id']]
        })
        self.assertEqual(del_res.status_code, 200)
        del_json = json.loads(del_res.data)
        self.assertTrue(del_json['success'])
        self.assertEqual(del_json['count'], 2)

        # Verifikasi di database
        self.assertIsNone(database.get_presentation_by_id(p1['id']))
        self.assertIsNone(database.get_presentation_by_id(p2['id']))
        self.assertIsNotNone(database.get_presentation_by_id(p3['id']))

    def test_19_participant_bulk_delete(self):
        """Uji endpoint bulk delete data presenter/peserta (hapus banyak data sekaligus via checkbox)"""
        self.login_admin()

        # Daftarkan 3 presenter
        pres1 = database.add_presentation('Paper 1', 'Ruang 1')
        pres2 = database.add_presentation('Paper 2', 'Ruang 2')
        pres3 = database.add_presentation('Paper 3', 'Ruang 3')

        r1 = self.app.post('/api/register', json={
            'presentation_id': pres1['id'],
            'nim_nip': '99001',
            'nama_lengkap': 'Presenter 1',
            'no_hp': '081299001',
            'institusi': 'Kampus 1',
            'pekerjaan': 'Mahasiswa'
        })
        r2 = self.app.post('/api/register', json={
            'presentation_id': pres2['id'],
            'nim_nip': '99002',
            'nama_lengkap': 'Presenter 2',
            'no_hp': '081299002',
            'institusi': 'Kampus 2',
            'pekerjaan': 'Dosen'
        })
        r3 = self.app.post('/api/register', json={
            'presentation_id': pres3['id'],
            'nim_nip': '99003',
            'nama_lengkap': 'Presenter 3',
            'no_hp': '081299003',
            'institusi': 'Kampus 3',
            'pekerjaan': 'Praktisi'
        })

        id1 = json.loads(r1.data)['data']['id']
        id2 = json.loads(r2.data)['data']['id']
        id3 = json.loads(r3.data)['data']['id']

        # Hapus id1 dan id2 secara bersamaan
        bulk_res = self.app.post('/api/participants/bulk-delete', json={
            'ids': [id1, id2]
        })
        self.assertEqual(bulk_res.status_code, 200)
        bulk_json = json.loads(bulk_res.data)
        self.assertTrue(bulk_json['success'])
        self.assertEqual(bulk_json['count'], 2)

        # Verifikasi peserta 1 dan 2 terhapus, peserta 3 masih ada
        self.assertIsNone(database.get_participant_by_nim('99001'))
        self.assertIsNone(database.get_participant_by_nim('99002'))
        self.assertIsNotNone(database.get_participant_by_nim('99003'))

        # Verifikasi judul 1 dan 2 kembali tersedia
        pres1_after = database.get_presentation_by_id(pres1['id'])
        self.assertFalse(pres1_after['is_taken'])

if __name__ == '__main__':
    unittest.main()

