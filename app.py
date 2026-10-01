from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = 'cok_gizli_anahtar_pdks_2026'
db_path = os.path.join(BASE_DIR, 'pdks_pro.db')

def init_db():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS personeller (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    ad_soyad TEXT, 
                    maas REAL, 
                    mesai_baslangic TEXT, 
                    mesai_bitis TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS kayitlar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    personel_id INTEGER, 
                    islem_tipi TEXT, 
                    tarih_saat TEXT, 
                    mesai_saati REAL, 
                    mesai_ucreti REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS yoneticiler (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    kullanici_adi TEXT UNIQUE, 
                    sifre TEXT)''')
    c.execute("INSERT OR IGNORE INTO yoneticiler (kullanici_adi, sifre) VALUES ('admin', '123456')")
    c.execute("DELETE FROM kayitlar WHERE mesai_saati < 0 OR mesai_ucreti < 0")
    conn.commit()
    conn.close()

@app.route('/')
def index():
    if not session.get('logged_in'): 
        return render_template('index.html')
    
    aranan = request.args.get('arama', '').strip()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Gelişmiş Sorgu: Giriş ve Çıkışları gün bazında yan yana birleştirir
    query = """
        SELECT 
            SUBSTR(k_giris.tarih_saat, 1, 10) AS tarih,
            p.ad_soyad,
            SUBSTR(k_giris.tarih_saat, 12, 8) AS giris_saati,
            SUBSTR(k_cikis.tarih_saat, 12, 8) AS cikis_saati,
            COALESCE(ROUND((STRFTIME('%s', k_cikis.tarih_saat) - STRFTIME('%s', k_giris.tarih_saat)) / 3600.0, 2), 0) AS toplam_calisma,
            COALESCE(k_cikis.mesai_saati, 0) AS fazla_mesai,
            COALESCE(k_cikis.mesai_ucreti, 0) AS mesai_kazanci,
            k_cikis.id AS cikis_id,
            k_giris.id AS giris_id
        FROM kayitlar k_giris
        JOIN personeller p ON k_giris.personel_id = p.id
        LEFT JOIN kayitlar k_cikis ON k_cikis.personel_id = p.id 
            AND k_cikis.islem_tipi = 'Çıkış' 
            AND SUBSTR(k_cikis.tarih_saat, 1, 10) = SUBSTR(k_giris.tarih_saat, 1, 10)
            AND k_cikis.tarih_saat > k_giris.tarih_saat
        WHERE k_giris.islem_tipi = 'Giriş'
    """
    
    if aranan:
        query += " AND p.ad_soyad LIKE ? ORDER BY tarih DESC, giris_saati DESC"
        c.execute(query, ('%' + aranan + '%',))
    else:
        query += " ORDER BY tarih DESC, giris_saati DESC"
        c.execute(query)
        
    kayitlar = c.fetchall()
    
    c.execute("SELECT id, ad_soyad FROM personeller")
    personeller = c.fetchall()
    conn.close()
    
    return render_template('index.html', kayitlar=kayitlar, personeller=personeller, aranan_kelime=aranan)

@app.route('/personel_ekle', methods=['POST'])
def personel_ekle():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    ad_soyad = request.form.get('personel_adi')
    maas = request.form.get('maas')
    baslangic = request.form.get('mesai_baslangic')
    bitis = request.form.get('mesai_bitis')
    if ad_soyad and maas and baslangic and bitis:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("INSERT INTO personeller (ad_soyad, maas, mesai_baslangic, mesai_bitis) VALUES (?, ?, ?, ?)",
                  (ad_soyad, float(maas), baslangic, bitis))
        conn.commit()
        conn.close()
        flash("Yeni personel başarıyla sisteme kaydedildi.")
    return redirect(url_for('index'))

@app.route('/islem', methods=['POST'])
def islem():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    p_id = request.form.get('personel_id')
    tip = request.form.get('islem_tipi')
    tarih_obj = datetime.now()
    tarih_str = tarih_obj.strftime("%Y-%m-%d %H:%M:%S")

    if not p_id or not tip:
        flash("Lütfen personel ve işlem tipi seçin!")
        return redirect(url_for('index'))

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT maas, mesai_baslangic, mesai_bitis FROM personeller WHERE id=?", (p_id,))
    p = c.fetchone()
    
    if not p:
        conn.close()
        return redirect(url_for('index'))
        
    maas, mesai_baslangic_str, mesai_bitis_str = float(p[0]), p[1], p[2]
    mesai_s, mesai_u = 0.0, 0.0
    
    if tip == 'Çıkış':
        c.execute("SELECT tarih_saat FROM kayitlar WHERE personel_id = ? AND islem_tipi = 'Giriş' ORDER BY tarih_saat DESC LIMIT 1", (p_id,))
        son_giris = c.fetchone()
        if son_giris:
            giris_tarih = datetime.strptime(son_giris[0], "%Y-%m-%d %H:%M:%S")
            toplam_saat = (tarih_obj - giris_tarih).total_seconds() / 3600
            normal_saat = (datetime.strptime(mesai_bitis_str, "%H:%M") - datetime.strptime(mesai_baslangic_str, "%H:%M")).total_seconds() / 3600
            if toplam_saat > normal_saat:
                mesai_s = round(toplam_saat - normal_saat, 2)
                mesai_u = round(mesai_s * (maas / 225) * 1.5, 2)

    c.execute("INSERT INTO kayitlar (personel_id, islem_tipi, tarih_saat, mesai_saati, mesai_ucreti) VALUES (?, ?, ?, ?, ?)", 
              (p_id, tip, tarih_str, mesai_s, mesai_u))
    conn.commit()
    conn.close()
    flash(f"{tip} hareketi kaydedildi.")
    return redirect(url_for('index'))

@app.route('/kayit_sil/<int:g_id>/<int:c_id>')
def kayit_sil(g_id, c_id):
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM kayitlar WHERE id = ?", (g_id,))
    if c_id and c_id != 0:
        c.execute("DELETE FROM kayitlar WHERE id = ?", (c_id,))
    conn.commit()
    conn.close()
    flash("Seçilen günkü hareket kayıtları silindi.")
    return redirect(url_for('index'))

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('kullanici_adi') == 'admin' and request.form.get('sifre') == '123456':
        session['logged_in'] = True
    else:
        flash("Hatalı giriş!")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
