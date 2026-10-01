from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
import psycopg2
import hashlib
from datetime import datetime, timedelta, timezone
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = 'cok_gizli_anahtar_pdks_2026'

DATABASE_URL = os.environ.get('DATABASE_URL')
TR_TZ = timezone(timedelta(hours=3))

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS personeller (
                    id SERIAL PRIMARY KEY, ad_soyad TEXT UNIQUE, maas REAL, 
                    mesai_baslangic TEXT, mesai_bitis TEXT, aktif_mi INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS kayitlar (
                    id SERIAL PRIMARY KEY, personel_id INTEGER, islem_tipi TEXT, 
                    tarih_saat TEXT, mesai_saati REAL, mesai_ucreti REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS yoneticiler (
                    id SERIAL PRIMARY KEY, kullanici_adi TEXT UNIQUE, sifre TEXT)''')
    admin_sifre_hash = hashlib.sha256("123456".encode('utf-8')).hexdigest()
    c.execute("INSERT INTO yoneticiler (kullanici_adi, sifre) VALUES ('admin', %s) ON CONFLICT (kullanici_adi) DO NOTHING", (admin_sifre_hash,))
    conn.commit()
    c.close()
    conn.close()

def format_ad_soyad(ham_isim):
    parcalar = ham_isim.strip().split()
    if len(parcalar) < 2: return None
    soyad = parcalar[-1].upper()
    adlar = [p.capitalize() for p in parcalar[:-1]]
    return " ".join(adlar) + " " + soyad

def get_hareket_verileri(secili_ay, aranan="", goster_pasif="0"):
    conn = get_db_connection()
    c = conn.cursor()
    query = """
        SELECT 
            SUBSTR(k_giris.tarih_saat, 1, 10), p.ad_soyad, SUBSTR(k_giris.tarih_saat, 12, 8), SUBSTR(k_cikis.tarih_saat, 12, 8),
            ROUND((EXTRACT(EPOCH FROM TO_TIMESTAMP(k_cikis.tarih_saat, 'YYYY-MM-DD HH24:MI:SS')) - EXTRACT(EPOCH FROM TO_TIMESTAMP(k_giris.tarih_saat, 'YYYY-MM-DD HH24:MI:SS'))) / 3600.0, 2),
            COALESCE(k_cikis.mesai_saati, 0.0), COALESCE(k_cikis.mesai_ucreti, 0.0), k_giris.id, COALESCE(k_cikis.id, 0), p.aktif_mi
        FROM kayitlar k_giris
        JOIN personeller p ON k_giris.personel_id = p.id
        LEFT JOIN kayitlar k_cikis ON k_cikis.personel_id = k_giris.personel_id 
            AND k_cikis.islem_tipi = 'Çıkış' AND SUBSTR(k_cikis.tarih_saat, 1, 10) = SUBSTR(k_giris.tarih_saat, 1, 10) AND k_cikis.tarih_saat >= k_giris.tarih_saat
        WHERE k_giris.islem_tipi = 'Giriş' AND SUBSTR(k_giris.tarih_saat, 1, 7) = %s
    """
    params = [secili_ay]
    if goster_pasif != "1": query += " AND p.aktif_mi = 1"
    if aranan: query += " AND p.ad_soyad LIKE %s"; params.append('%' + aranan + '%')
    query += " ORDER BY k_giris.tarih_saat DESC"
    c.execute(query, params)
    veriler = c.fetchall()
    c.close()
    conn.close()
    return veriler

def get_bordro_verileri(secili_ay, goster_pasif="0"):
    conn = get_db_connection()
    c = conn.cursor()
    query = """
        SELECT p.id, p.ad_soyad, p.maas,
            SUM(CASE WHEN k.islem_tipi = 'Çıkış' THEN k.mesai_saati ELSE 0 END),
            SUM(CASE WHEN k.islem_tipi = 'Çıkış' THEN k.mesai_ucreti ELSE 0 END), 0.0, p.aktif_mi
        FROM personeller p
        LEFT JOIN kayitlar k ON p.id = k.personel_id AND SUBSTR(k.tarih_saat, 1, 7) = %s
    """
    if goster_pasif == "1": query += " WHERE p.aktif_mi = 1 OR (p.aktif_mi = 0 AND k.id IS NOT NULL)"
    else: query += " WHERE p.aktif_mi = 1"
    query += " GROUP BY p.id, p.ad_soyad, p.maas, p.aktif_mi"
    c.execute(query, (secili_ay,))
    bordro_kayitlar = c.fetchall()
    c.close()
    conn.close()
    hesaplanan = []
    for s in bordro_kayitlar:
        t_m = round(s[3] if s[3] else 0.0, 2)
        t_k = round(s[4] if s[4] else 0.0, 2)
        hesaplanan.append((s[0], s[1], s[2], t_m, t_k, round(s[2] + t_k, 2), s[6]))
    return hesaplanan

@app.route('/')
def index():
    is_admin, is_user = session.get('logged_in'), session.get('user_logged_in')
    if not is_admin and not is_user:
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT id, ad_soyad FROM personeller WHERE aktif_mi = 1 ORDER BY ad_soyad ASC")
        personeller = c.fetchall(); c.close(); conn.close()
        return render_template('index.html', personeller=personeller)
    secili_ay = request.args.get('ay_filtre', datetime.now(TR_TZ).strftime("%Y-%m"))
    goster_pasif = request.args.get('goster_pasif', '0')
    aranan = session.get('user_name', '') if is_user else request.args.get('arama', '').strip()
    if is_user: goster_pasif = "1"
    kayitlar = get_hareket_verileri(secili_ay, aranan, goster_pasif)
    bordro = get_bordro_verileri(secili_ay, goster_pasif)
    conn = get_db_connection(); c = conn.cursor()
    c.execute("SELECT id, ad_soyad FROM personeller WHERE aktif_mi = 1 ORDER BY ad_soyad ASC")
    personeller = c.fetchall(); c.close(); conn.close()
    return render_template('index.html', kayitlar=kayitlar, bordro=bordro, personeller=personeller, aranan_kelime=aranan, secili_ay=secili_ay, goster_pasif=goster_pasif)

@app.route('/excel_hareket')
def excel_hareket():
    if not session.get('logged_in') and not session.get('user_logged_in'): return redirect(url_for('index'))
    secili_ay = request.args.get('ay_filtre', datetime.now(TR_TZ).strftime("%Y-%m"))
    goster_pasif = request.args.get('goster_pasif', '0')
    aranan = session.get('user_name', '') if session.get('user_logged_in') else request.args.get('arama', '').strip()
    veriler = get_hareket_verileri(secili_ay, aranan, goster_pasif)
    csv = ["Tarih;Personel Adi;Giris Saati;Cikis Saati;Toplam Calisma;Fazla Mesai;Mesai Kazanci"]
    for v in veriler: csv.append(f"{v[0]};{v[1]};{v[2]};{v[3] if v[3] else '--:--'};{v[4] if v[4] else '0.0'};{v[5]};{v[6]}")
    return Response("\uFEFF" + "\n".join(csv), mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=Hareket_{secili_ay}.csv"})

@app.route('/excel_bordro')
def excel_bordro():
    if not session.get('logged_in'): return redirect(url_for('index'))
    secili_ay = request.args.get('ay_filtre', datetime.now(TR_TZ).strftime("%Y-%m"))
    goster_pasif = request.args.get('goster_pasif', '0')
    veriler = get_bordro_verileri(secili_ay, goster_pasif)
    csv = ["Personel Adi;Sabit Brut Maas;Aylik Toplam Fazla Mesai;Toplam Mesai Kazanci;Net Tutar;Durum"]
    for v in veriler: csv.append(f"{v[1]};{v[2]};{v[3]};{v[4]};{v[5]};{'Aktif' if v[6]==1 else 'Ayrilmis'}")
    return Response("\uFEFF" + "\n".join(csv), mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=Bordro_{secili_ay}.csv"})

@app.route('/personel_ekle', methods=['POST'])
def personel_ekle():
    if not session.get('logged_in'): return redirect(url_for('index'))
    ad_soyad = format_ad_soyad(request.form.get('personel_adi'))
    maas, bas, bit = request.form.get('maas'), request.form.get('mesai_baslangic'), request.form.get('mesai_bitis')
    if not ad_soyad: flash("Hata: Ad Soyad birlikte girilmelidir!"); return redirect(url_for('index'))
    conn = get_db_connection(); c = conn.cursor()
    c.execute("SELECT id FROM personeller WHERE ad_soyad = %s AND aktif_mi = 1", (ad_soyad,))
    if c.fetchone(): flash("Hata: Personel zaten mevcut!")
    else: c.execute("INSERT INTO personeller (ad_soyad, maas, mesai_baslangic, mesai_bitis, aktif_mi) VALUES (%s, %s, %s, %s, 1)", (ad_soyad, float(maas), bas, bit)); conn.commit()
    c.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/personel_sil/<int:p_id>')
def personel_sil(p_id):
    if not session.get('logged_in'): return redirect(url_for('index'))
    conn = get_db_connection(); c = conn.cursor()
    c.execute("UPDATE personeller SET aktif_mi = 0 WHERE id = %s", (p_id,)); conn.commit(); c.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/islem', methods=['POST'])
def islem():
    if not session.get('logged_in'): return redirect(url_for('index'))
    p_id, tip, harici = request.form.get('personel_id'), request.form.get('islem_tipi'), request.form.get('harici_tarih_saat')
    t_obj = datetime.strptime(harici, "%Y-%m-%dT%H:%M") if harici and harici.strip() else datetime.now(TR_TZ).replace(tzinfo=None)
    t_str = t_obj.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection(); c = conn.cursor()
    c.execute("SELECT maas, mesai_baslangic, mesai_bitis FROM personeller WHERE id=%s", (p_id,))
    p = c.fetchone()
    if p:
        maas, m_bas, m_bit = float(p[0]), p[1], p[2]; m_s, m_u = 0.0, 0.0
        if tip == 'Çıkış':
            c.execute("SELECT tarih_saat FROM kayitlar WHERE personel_id = %s AND islem_tipi = 'Giriş' AND tarih_saat <= %s ORDER BY tarih_saat DESC LIMIT 1", (p_id, t_str))
            son_g = c.fetchone()
            if son_g:
                top_s = (t_obj - datetime.strptime(son_g[0], "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
                norm_s = (datetime.strptime(m_bit, "%H:%M") - datetime.strptime(m_bas, "%H:%M")).total_seconds() / 3600
                if top_s > norm_s: m_s = round(top_s - norm_s, 2); m_u = round(m_s * (maas / 225) * 1.5, 2)
        c.execute("INSERT INTO kayitlar (personel_id, islem_tipi, tarih_saat, mesai_saati, mesai_ucreti) VALUES (%s, %s, %s, %s, %s)", (p_id, tip, t_str, m_s, m_u)); conn.commit()
    c.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/kayit_sil/<int:g_id>/<int:c_id>')
def kayit_sil(g_id, c_id):
    if not session.get('logged_in'): return redirect(url_for('index'))
    conn = get_db_connection(); c = conn.cursor()
    c.execute("DELETE FROM kayitlar WHERE id = %s", (g_id,))
    if c_id and c_id != 0: c.execute("DELETE FROM kayitlar WHERE id = %s", (c_id,))
    conn.commit(); c.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/login', methods=['POST'])
def login():
    tip = request.form.get('login_tipi')
    if tip == 'admin':
        hash_s = hashlib.sha256(request.form.get('sifre').encode('utf-8')).hexdigest()
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT * FROM yoneticiler WHERE kullanici_adi=%s AND sifre=%s", (request.form.get('kullanici_adi'), hash_s))
        if c.fetchone(): 
            session['logged_in'] = True
        else: 
            flash("Hatalı admin girişi!")
        c.close(); conn.close()
    elif tip == 'personel' and request.form.get('user_personel_id'):
        p_id = request.form.get('user_personel_id')
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT ad_soyad FROM personeller WHERE id=%s", (p_id,))
        p = c.fetchone(); c.close(); conn.close()
        if p: 
            session['user_logged_in'] = True; session['user_id'] = p_id; session['user_name'] = p[0]
    return redirect(url_for('index'))

@app.route('/admin_sifre_degis', methods=['POST'])
def admin_sifre_degis():
    if not session.get('logged_in'): return redirect(url_for('index'))
    e_hash = hashlib.sha256(request.form.get('eski_sifre').encode('utf-8')).hexdigest()
    y_hash = hashlib.sha256(request.form.get('yeni_sifre').encode('utf-8')).hexdigest()
    conn = get_db_connection(); c = conn.cursor()
    c.execute("SELECT * FROM yoneticiler WHERE kullanici_adi = 'admin' AND sifre = %s", (e_hash,))
    if c.fetchone(): 
        c.execute("UPDATE yoneticiler SET sifre = %s WHERE kullanici_adi = 'admin'", (y_hash,)); conn.commit(); flash("Şifre güncellendi.")
    else: 
        flash("Mevcut şifre yanlış!")
    c.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/logout')
def logout(): 
    session.clear(); 
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
