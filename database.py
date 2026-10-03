import psycopg2
from config import DATABASE_URL, ADMIN_IDS, get_ist_now

def get_db_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL एनवायरनमेंट में सेट नहीं है।")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_vip INT DEFAULT 0,
            vip_expiry TIMESTAMPTZ,
            joined_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS user_daf (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            name TEXT,
            home_state TEXT,
            college_name TEXT,
            graduation_status TEXT,
            optional_subject TEXT,
            attempt_number TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS daily_archive (
            id BIGSERIAL PRIMARY KEY,
            period_type TEXT,
            reference_date DATE UNIQUE,
            topic TEXT,
            html_content TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    c.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Database Init Error: {e}")

def register_user(user_id, username, first_name):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, username, first_name, joined_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET 
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name;
        """, (user_id, username or "", first_name or ""))
        c.close()
        conn.close()
    except Exception as e:
        print(f"Error registering user: {e}")

def is_authorized(user_id):
    if user_id in ADMIN_IDS:
        return True
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT is_vip, vip_expiry FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        if row and row[0] == 1:
            if row[1]:
                if get_ist_now() <= row[1].astimezone(row[1].tzinfo):
                    return True
            else:
                return True
    except Exception as e:
        print(f"Auth error: {e}")
    return False

def add_vip_user(target_uid: int, days: int):
    expiry = get_ist_now() + psycopg2.extensions.AsIs(f"INTERVAL '{days} days'")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, is_vip, vip_expiry, joined_at)
        VALUES (%s, 1, NOW() + (%s || ' days')::INTERVAL, NOW())
        ON CONFLICT (user_id) DO UPDATE SET 
            is_vip = 1, 
            vip_expiry = NOW() + (%s || ' days')::INTERVAL;
    """, (target_uid, str(days), str(days)))
    c.close()
    conn.close()

def remove_vip_user(target_uid: int):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = %s", (target_uid,))
    c.close()
    conn.close()

def get_user_daf(user_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT name, home_state, college_name, graduation_status, optional_subject, attempt_number FROM user_daf WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        return row
    except Exception:
        return None

def save_user_daf(user_id, name, home_state, college, status, opt_sub, attempt):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO user_daf (user_id, name, home_state, college_name, graduation_status, optional_subject, attempt_number, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                home_state = EXCLUDED.home_state,
                college_name = EXCLUDED.college_name,
                graduation_status = EXCLUDED.graduation_status,
                optional_subject = EXCLUDED.optional_subject,
                attempt_number = EXCLUDED.attempt_number,
                updated_at = NOW();
        """, (user_id, name, home_state, college, status, opt_sub, attempt))
        c.close()
        conn.close()
    except Exception as e:
        print(f"Error saving DAF: {e}")

def get_user_full_info(user_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, is_vip, vip_expiry, joined_at FROM users WHERE user_id = %s", (user_id,))
        user_row = c.fetchone()
        if not user_row:
            c.close()
            conn.close()
            return None, None
        c.execute("SELECT name, home_state, college_name, graduation_status, optional_subject, attempt_number, updated_at FROM user_daf WHERE user_id = %s", (user_id,))
        daf_row = c.fetchone()
        c.close()
        conn.close()
        return user_row, daf_row
    except Exception:
        return None, None

def save_to_archive(period, topic, html_content, ref_date=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        d_val = ref_date if ref_date else get_ist_now().date()
        c.execute("""
            INSERT INTO daily_archive (period_type, reference_date, topic, html_content, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (reference_date) DO UPDATE SET
                topic = EXCLUDED.topic,
                html_content = EXCLUDED.html_content,
                created_at = NOW();
        """, (period, d_val, topic, html_content))
        c.close()
        conn.close()
    except Exception as e:
        print(f"Error archiving: {e}")

def get_archive_by_date(date_str):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT topic, html_content FROM daily_archive WHERE reference_date = %s LIMIT 1", (date_str,))
        row = c.fetchone()
        c.close()
        conn.close()
        return row
    except Exception:
        return None

def get_all_user_ids():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        rows = c.fetchall()
        c.close()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def get_all_users_detailed():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, is_vip, vip_expiry FROM users ORDER BY joined_at DESC")
        rows = c.fetchall()
        c.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"Error getting detailed users: {e}")
        return []
