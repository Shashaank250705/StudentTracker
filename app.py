import datetime
from flask import Flask, request, render_template, jsonify, session, redirect, url_for, flash
import mysql.connector
from mysql.connector import Error, pooling

# --- CONFIGURATION ---
SITE_NAME = "SANJAYA"
ACTIVE_THRESHOLD = 120  # Seconds to consider a node 'Online'

app = Flask(__name__)
app.secret_key = 'sanjaya_divine_vision_key_2026' 

# --- DATABASE CONNECTION ---
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root', 
    'database': 'campus_tracking',
    'pool_name': 'sanjaya_pool',
    'pool_size': 10
}

try:
    db_pool = mysql.connector.pooling.MySQLConnectionPool(**db_config)
except Error as e:
    print(f"!!! Error creating DB pool: {e}")

def get_db_connection():
    return db_pool.get_connection()

def format_datetime(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "Never"

# --- LOGIN & DASHBOARD ROUTES ---

@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('admin_dashboard'))
    return render_template('login.html', site_name=SITE_NAME)

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('userid')
    password = request.form.get('password')
    role_selected = request.form.get('role')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = "SELECT * FROM users WHERE username = %s AND password = %s AND role = %s"
    cursor.execute(query, (username, password, role_selected))
    user = cursor.fetchone()
    conn.close()

    if user:
        session['logged_in'] = True
        session['username'] = user['username']
        session['role'] = user['role']
        # This will now store "W1" or "W1, W2, W3"
        session['parent_of'] = user.get('parent_of')
        return redirect(url_for('admin_dashboard'))
    
    flash("Invalid Login Credentials", "danger")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    search_id = request.args.get('search_id', '')
    return render_template('admin.html', site_name=SITE_NAME, role=session.get('role'), search_id=search_id)

# --- FINGERPRINT MANAGEMENT API ---

@app.route('/api/get_fingerprints')
def get_fingerprints():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM fingerprints ORDER BY room_name ASC")
        return jsonify(cursor.fetchall())
    finally:
        conn.close()

@app.route('/api/delete_fingerprint', methods=['POST'])
def delete_fingerprint():
    if session.get('role') != 'admin': return jsonify({"status": "fail"}), 403
    bssid = request.form.get('bssid')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM fingerprints WHERE bssid = %s", (bssid,))
        conn.commit()
        return jsonify({"status": "success"})
    finally:
        conn.close()

# --- STUDENT & USER MANAGEMENT API ---

@app.route('/api/list_students')
def list_students():
    if not session.get('logged_in'): return jsonify([]), 401
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT student_id FROM student_locations ORDER BY student_id ASC")
        students = [row[0] for row in cursor.fetchall()]
        return jsonify(students)
    finally:
        conn.close()

@app.route('/api/register_student', methods=['POST'])
def register_student():
    if session.get('role') != 'admin': return jsonify({"status": "error", "message": "Admin only"}), 403
    sid = request.form.get('student_id')
    if not sid: return jsonify({"status": "error", "message": "ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO student_locations (student_id, last_room, last_rssi, last_updated) VALUES (%s, 'New Student', 0, NOW())", (sid,))
        conn.commit()
        return jsonify({"status": "success"})
    except Error as e:
        return jsonify({"status": "error", "message": "Already exists or DB error"}), 400
    finally:
        conn.close()

@app.route('/api/create_user', methods=['POST'])
def create_user():
    if session.get('role') != 'admin': return jsonify({"status": "fail"}), 403
    uname = request.form.get('username')
    pword = request.form.get('password')
    role = request.form.get('role')
    # linked_sid will be a comma-separated string from the frontend for Mentors
    linked_sid = request.form.get('linked_sid')

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password, role, parent_of) VALUES (%s, %s, %s, %s)", 
                       (uname, pword, role, linked_sid if linked_sid else None))
        conn.commit()
        return jsonify({"status": "success"})
    except Error as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        conn.close()

@app.route('/api/delete_student', methods=['POST'])
def delete_student():
    if session.get('role') != 'admin': return jsonify({"status": "fail"}), 403
    sid = request.form.get('student_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM student_locations WHERE student_id = %s", (sid,))
        cursor.execute("DELETE FROM location_history WHERE student_id = %s", (sid,))
        conn.commit()
        return jsonify({"status": "success"})
    finally:
        conn.close()

# --- TRAINING MODE API ---

@app.route('/api/toggle_training', methods=['POST'])
def toggle_training():
    if session.get('role') != 'admin': return jsonify({"status": "fail"}), 403
    active = request.form.get('active') == 'true'
    room = request.form.get('room_name', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    if active: cursor.execute("DELETE FROM training_buffer")
    cursor.execute("UPDATE training_mode SET is_active = %s, target_room = %s WHERE id = 1", (active, room))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

# --- API FOR ESP8266 ---

@app.route('/update_location', methods=['POST'])
def update_location():
    conn = None
    try:
        student_id = request.form.get('student_id')
        live_bssid = request.form.get('bssid')
        live_ssid = request.form.get('ssid', 'Unknown SSID')
        live_rssi = int(request.form.get('rssi', -100))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM training_mode WHERE id = 1")
        training = cursor.fetchone()

        if training and training['is_active']:
            target_room = training['target_room']
            cursor.execute("""
                INSERT INTO training_buffer (bssid, ssid, room_name, rssi_sum, reading_count)
                VALUES (%s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE rssi_sum = rssi_sum + %s, reading_count = reading_count + 1, ssid = %s
            """, (live_bssid, live_ssid, target_room, live_rssi, live_rssi, live_ssid))
            
            cursor.execute("SELECT reading_count, rssi_sum FROM training_buffer WHERE bssid = %s", (live_bssid,))
            buffer = cursor.fetchone()

            if buffer and buffer['reading_count'] >= 10:
                final_avg = buffer['rssi_sum'] // 10
                cursor.execute("""
                    INSERT INTO fingerprints (bssid, ssid, room_name, avg_rssi)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE avg_rssi = %s, room_name = %s, ssid = %s
                """, (live_bssid, live_ssid, target_room, final_avg, final_avg, target_room, live_ssid))
                cursor.execute("DELETE FROM training_buffer WHERE bssid = %s", (live_bssid,))
                conn.commit()
                return jsonify({"status": "training_complete"}), 200
            conn.commit()
            return jsonify({"status": "training_in_progress"}), 200

        # Normal Tracking
        cursor.execute("SELECT room_name FROM fingerprints WHERE bssid = %s ORDER BY ABS(avg_rssi - %s) ASC LIMIT 1", (live_bssid, live_rssi))
        match = cursor.fetchone()
        detected_room = match['room_name'] if match else "Unknown Area"

        cursor.execute("INSERT INTO location_history (student_id, room_name) VALUES (%s, %s)", (student_id, detected_room))
        cursor.execute("""
            INSERT INTO student_locations (student_id, last_room, last_rssi, last_updated)
            VALUES (%s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE last_room = %s, last_rssi = %s, last_updated = NOW()
        """, (student_id, detected_room, live_rssi, detected_room, live_rssi))
        conn.commit()
        return jsonify({"status": "success", "room": detected_room}), 200
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn: conn.close()

# --- DASHBOARD UPDATES API (FIXED FOR MULTI-STUDENT) ---

@app.route('/api/get_updates')
def get_updates():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    search_id = request.args.get('search_id')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # "multi_live" will hold the list of students for Parents/Mentors
    data = {"students": [], "multi_live": [], "history": [], "training_progress": 0}
    now = datetime.datetime.now()

    try:
        # 1. Admin/General Table
        cursor.execute("SELECT * FROM student_locations ORDER BY last_updated DESC")
        for s in cursor.fetchall():
            s['is_active'] = 1 if (now - s['last_updated']).total_seconds() < ACTIVE_THRESHOLD else 0
            s['last_updated'] = format_datetime(s['last_updated'])
            data['students'].append(s)

        # 2. Focused Logic for Parent/Mentor/Search
        target_ids = []
        if search_id:
            target_ids = [search_id]
        elif session.get('parent_of'):
            # This handles "W1" (Parent) and "W1, W2, W3" (Mentor)
            target_ids = [x.strip() for x in session.get('parent_of').split(',') if x.strip()]

        if target_ids:
            # SQL "IN" clause to fetch all linked students at once
            format_strings = ','.join(['%s'] * len(target_ids))
            cursor.execute(f"SELECT * FROM student_locations WHERE student_id IN ({format_strings})", tuple(target_ids))
            
            lives = cursor.fetchall()
            for live in lives:
                live['is_active'] = 1 if (now - live['last_updated']).total_seconds() < ACTIVE_THRESHOLD else 0
                live['last_updated'] = format_datetime(live['last_updated'])
                data['multi_live'].append(live)

            # History for the first student in the list (to prevent UI clutter)
            cursor.execute("SELECT room_name, timestamp FROM location_history WHERE student_id = %s ORDER BY timestamp DESC LIMIT 10", (target_ids[0],))
            data['history'] = [{"room_name": h['room_name'], "timestamp": format_datetime(h['timestamp'])} for h in cursor.fetchall()]

        # 3. Training Progress
        cursor.execute("SELECT MAX(reading_count) as count FROM training_buffer")
        res = cursor.fetchone()
        if res and res['count']: data['training_progress'] = res['count']
        
    finally:
        conn.close()
    return jsonify(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)