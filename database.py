import os
import re
from datetime import timedelta
import psycopg2
from config import DATABASE_URL, ADMIN_IDS, get_ist_now

# लोकल इन-मेमोरी बैकअप (यदि नेटवर्क कभी भी अनरीचेबल हो तो बॉट न रुके)
MEMORY_USERS = {}
MEMORY_DAF = {}
MEMORY_ARCHIVE = {}

def get_clean_db_url():
    url = DATABASE_URL
    if not url:
        return ""
    # Render IPv4 नेटवर्क एरर को कोड लेवल पर ही फिक्स करना
    if "db." in url and ".supabase.co" in url and ":5432" in url:
        # 5432 IPv6 होता है, इसे IPv4 कम्पैटिबल पूलर पोर्ट पर कोड से ही ऑटो-रूट करना
        url = url.replace(":5432", ":6543")
    return url

def get_db_connection():
    clean_url = get_clean_db_url()
    if not clean_url:
        raise Exception("DATABASE_URL अनुपलब्ध है।")
    conn = psycopg2.connect(clean_url, connect_timeout=4)
    conn.autocommit = True
    return conn

def init_db():
    try:
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
    except Exception as e:
        print(f"DB Online Init Notice (Safe Mode Active): {e}")

try:
    init_db()
except Exception:
    pass

def register_user(user_id, username, first_name):
    MEMORY_USERS[user_id] = {
        "user_id": user_id,
        "username": username or "",
        "first_name": first_name or "",
        "is_vip": MEMORY_USERS.get(user_id, {}).get("is_vip", 0),
        "vip_expiry": MEMORY_USERS.get(user_id, {}).get("vip_expiry", None),
        "joined_at": get_ist_now()
    }
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
    except Exception:
        pass

def is_authorized(user_id):
    if user_id in ADMIN_IDS:
        return True
    
    # पहले मेमोरी कैश चेक करें
    mem = MEMORY_USERS.get(user_id)
    if mem and mem.get("is_vip") == 1:
        exp = mem.get("vip_expiry")
        if exp is None or get_ist_now() <= exp:
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
                if get_ist_now() <= row[1].astimezone(get_ist_now().tzinfo):
                    return True
            else:
                return True
    except Exception:
        pass
    return False

def add_vip_user(target_uid: int, days: int):
    expiry_time = get_ist_now() + timedelta(days=days)
    
    # 1. तुरंत इन-मेमोरी अपडेट
    if target_uid not in MEMORY_USERS:
        MEMORY_USERS[target_uid] = {"user_id": target_uid, "username": "", "first_name": f"User_{target_uid}"}
    MEMORY_USERS[target_uid]["is_vip"] = 1
    MEMORY_USERS[target_uid]["vip_expiry"] = expiry_time

    # 2. डेटाबेस में स्थायी अपडेट (बिना किसी टाइप एरर के)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, is_vip, vip_expiry, joined_at)
        VALUES (%s, 1, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET 
            is_vip = 1, 
            vip_expiry = %s;
    """, (target_uid, expiry_time, expiry_time))
    c.close()
    conn.close()

def remove_vip_user(target_uid: int):
    if target_uid in MEMORY_USERS:
        MEMORY_USERS[target_uid]["is_vip"] = 0
        MEMORY_USERS[target_uid]["vip_expiry"] = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = %s", (target_uid,))
        c.close()
        conn.close()
    except Exception:
        pass

def get_user_daf(user_id):
    if user_id in MEMORY_DAF:
        d = MEMORY_DAF[user_id]
        return (d["name"], d["home_state"], d["college_name"], d["graduation_status"], d["optional_subject"], d["attempt_number"])
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT name, home_state, college_name, graduation_status, optional_subject, attempt_number FROM user_daf WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        if row:
            MEMORY_DAF[user_id] = {
                "name": row[0], "home_state": row[1], "college_name": row[2],
                "graduation_status": row[3], "optional_subject": row[4], "attempt_number": row[5]
            }
        return row
    except Exception:
        return None

def save_user_daf(user_id, name, home_state, college, status, opt_sub, attempt):
    MEMORY_DAF[user_id] = {
        "name": name, "home_state": home_state, "college_name": college,
        "graduation_status": status, "optional_subject": opt_sub, "attempt_number": attempt
    }
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
    except Exception:
        pass

def get_user_full_info(user_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, is_vip, vip_expiry, joined_at FROM users WHERE user_id = %s", (user_id,))
        user_row = c.fetchone()
        c.execute("SELECT name, home_state, college_name, graduation_status, optional_subject, attempt_number, updated_at FROM user_daf WHERE user_id = %s", (user_id,))
        daf_row = c.fetchone()
        c.close()
        conn.close()
        if user_row:
            return user_row, daf_row
    except Exception:
        pass

    if user_id in MEMORY_USERS:
        u = MEMORY_USERS[user_id]
        u_row = (u["user_id"], u["username"], u["first_name"], u["is_vip"], u["vip_expiry"], u["joined_at"])
        d_row = None
        if user_id in MEMORY_DAF:
            d = MEMORY_DAF[user_id]
            d_row = (d["name"], d["home_state"], d["college_name"], d["graduation_status"], d["optional_subject"], d["attempt_number"], get_ist_now())
        return u_row, d_row
    return None, None

def save_to_archive(period, topic, html_content, ref_date=None):
    d_val = ref_date if ref_date else get_ist_now().date()
    MEMORY_ARCHIVE[str(d_val)] = (topic, html_content)
    try:
        conn = get_db_connection()
        c = conn.cursor()
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
    except Exception:
        pass

def get_archive_by_date(date_str):
    if str(date_str) in MEMORY_ARCHIVE:
        return MEMORY_ARCHIVE[str(date_str)]
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
    ids = set(MEMORY_USERS.keys())
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        rows = c.fetchall()
        c.close()
        conn.close()
        ids.update([r[0] for r in rows])
    except Exception:
        pass
    return list(ids)

def get_all_users_detailed():
    dict_users = {}
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, is_vip, vip_expiry FROM users ORDER BY joined_at DESC")
        rows = c.fetchall()
        c.close()
        conn.close()
        for r in rows:
            dict_users[r[0]] = r
    except Exception:
        pass

    for uid, u in MEMORY_USERS.items():
        if uid not in dict_users:
            dict_users[uid] = (uid, u.get("username", ""), u.get("first_name", ""), u.get("is_vip", 0), u.get("vip_expiry", None))
    return list(dict_users.values())
