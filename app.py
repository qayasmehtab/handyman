"""
Handyman / کاریگر — Complete Demo App (Streamlit)
-------------------------------------------------
Features:
1. Multi-language (English, Urdu, Sindhi) with dynamic UI & Chat greetings.
2. SQLite Database for Users, Bookings, Ratings & Password Reset.
3. Persistent Login Session (Stays logged in across refreshes).
4. Forgot Password / OTP Flow for recovery.
5. Interactive Map & Messenger Chat.
"""

import time
import random
import os
import base64
import sqlite3
import hashlib
from datetime import datetime
import streamlit as st
import folium
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Handyman | کاریگر",
    page_icon="🛠️",
    layout="centered",
)

def get_logo_base64():
    if os.path.exists("logo.png"):
        with open("logo.png", "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

LOGO_B64 = get_logo_base64()

# ---------------------------------------------------------------------------
# DATABASE SETUP (SQLite)
# ---------------------------------------------------------------------------
DB_PATH = "handyman.db"

def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            service TEXT NOT NULL,
            address TEXT NOT NULL,
            worker_name TEXT,
            visit_charge REAL DEFAULT 500,
            status TEXT DEFAULT 'Pending',
            rating INTEGER DEFAULT 0,
            review TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def register_user(phone, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    if cur.fetchone():
        conn.close()
        return False, "exists"
    cur.execute(
        "INSERT INTO users (phone, password_hash) VALUES (?, ?)",
        (phone, hash_password(password)),
    )
    conn.commit()
    conn.close()
    return True, "ok"

def verify_user(phone, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE phone = ?", (phone,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return False, "no_user"
    if row[0] == hash_password(password):
        return True, "ok"
    return False, "wrong_pw"

def update_user_password(phone, new_password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password_hash = ? WHERE phone = ?", (hash_password(new_password), phone))
    conn.commit()
    conn.close()

def save_booking(phone, service, address, worker_name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (phone, service, address, worker_name, status) VALUES (?, ?, ?, ?, ?)",
        (phone, service, address, worker_name, "Accepted"),
    )
    booking_id = cur.lastrowid
    conn.commit()
    conn.close()
    return booking_id

def update_booking_rating(booking_id, rating, review):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE bookings SET rating = ?, review = ?, status = 'Completed' WHERE id = ?",
        (rating, review, booking_id),
    )
    conn.commit()
    conn.close()

def get_user_bookings(phone):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, service, address, worker_name, status, rating, review, created_at FROM bookings WHERE phone = ? ORDER BY id DESC", (phone,))
    rows = cur.fetchall()
    conn.close()
    return rows

init_db()

# ---------------------------------------------------------------------------
# GLOBAL STYLE
# ---------------------------------------------------------------------------
APP_STYLE = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
div[data-testid="stToolbar"] {visibility: hidden;}
div[data-testid="stDecoration"] {visibility: hidden;}
div[data-testid="stStatusWidget"] {visibility: hidden;}

html, body, .stApp {
    background: linear-gradient(160deg, #0A3A73 0%, #063260 22%, #F0E9D2 55%, #FCFBE8 100%) !important;
    background-attachment: fixed !important;
}

.block-container {
    max-width: 440px;
    margin: 0 auto;
    padding-top: 1.4rem;
    padding-bottom: 3rem;
    padding-left: 1.4rem;
    padding-right: 1.4rem;
    background: #FFFFFF;
    border-radius: 28px;
    box-shadow: 0 12px 45px rgba(6, 50, 96, 0.30);
    margin-top: 18px;
    margin-bottom: 18px;
    border-top: 6px solid #E7752F;
}

h1, h2, h3 { color: #063260 !important; }

.stButton > button {
    border-radius: 14px;
    font-weight: 700;
    height: 3em;
    border: 2px solid #F0E9D2;
    background: linear-gradient(180deg, #FCFBE8 0%, #F0E9D2 100%);
    color: #063260;
    transition: 0.15s ease-in-out;
}
.stButton > button:hover {
    border-color: #E7752F;
    background: linear-gradient(180deg, #FCE3D1 0%, #F7C9A3 100%);
    color: #B34E12;
}

.stButton > button[kind="primary"] {
    background: linear-gradient(180deg, #F08A3E 0%, #E7752F 100%);
    border: none;
    color: #FFFFFF;
    box-shadow: 0 6px 16px rgba(231, 117, 47, 0.40);
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(180deg, #E7752F 0%, #C85E1F 100%);
    color: #FFFFFF;
}

.stTextInput > div > div > input {
    border-radius: 12px;
    border: 2px solid #F0E9D2;
    background: #FCFBE8;
}
</style>
"""
st.markdown(APP_STYLE, unsafe_allow_html=True)

BAHRIA_TOWN_KARACHI = {"lat": 24.8607, "lng": 67.0011}

# ---------------------------------------------------------------------------
# TRANSLATIONS
# ---------------------------------------------------------------------------
T = {
    "en": {
        "choose_language": "Choose Language",
        "continue": "Continue",
        "login_title": "Login / Register",
        "password": "Password",
        "login_btn": "Login",
        "phone_label": "Mobile Number",
        "phone_placeholder": "03XXXXXXXXX",
        "mode_login": "Login",
        "mode_register": "Create Account",
        "register_btn": "🚀 Create Account",
        "err_no_user": "No account found with this number. Please register.",
        "err_wrong_pw": "Incorrect password. Please try again.",
        "err_phone_exists": "This number is already registered.",
        "err_phone_invalid": "Please enter a valid mobile number.",
        "reg_success": "🎉 Account created successfully! Please login.",
        "forgot_pw": "🔑 Forgot Password / OTP Recovery",
        "send_otp": "Send OTP Code",
        "otp_sent": "📲 OTP Code sent to your mobile: **{otp}** (Demo)",
        "enter_otp": "Enter 4-Digit OTP",
        "new_password": "New Password",
        "reset_pw_btn": "Reset Password",
        "pw_reset_success": "🎉 Password updated successfully! Please login.",
        "err_wrong_otp": "Invalid OTP code. Please try again.",
        "current_location": "Current Location",
        "loc_use_current": "📍 My Current Location",
        "loc_use_other": "🏠 Other Address",
        "loc_address_placeholder": "Enter full address...",
        "loc_apply": "✅ Apply Location",
        "loc_applied": "Location set to: {addr}",
        "maintenance_repair": "Maintenance & Repair",
        "select_service": "Select a Service",
        "plumber": "Plumber",
        "electrician": "Electrician",
        "ac_repairing": "AC Repairing",
        "solar_system": "Solar System",
        "gardening": "Gardening",
        "cleaning": "Cleaning",
        "painter": "Painter",
        "back": "Back",
        "logout": "Logout",
        "find_handyman": "Find Handyman",
        "searching": "Searching nearby handymen...",
        "visit_charge_label": "🧾 Visiting Charges: Rs. 500",
        "visit_note": "Pay only visiting charges now. Repair cost will be decided on-site.",
        "visit_warranty": "✅ Warranty: Free repair if same issue occurs again.",
        "notif_title": "🔔 New Response!",
        "notif_body": "{name} ({service}) accepted your request and is on the way.",
        "accept": "Accept",
        "decline": "Decline",
        "worker_enroute": "Worker is on the way",
        "eta": "ETA",
        "min": "min",
        "simulate_move": "Simulate Location Update",
        "arrived": "🎉 Worker has arrived at your location!",
        "call": "📞 Audio Call",
        "message": "💬 Message",
        "call_screen_title": "Calling...",
        "mute": "Mute",
        "end_call": "End Call",
        "chat_title": "Chat with",
        "type_message": "Type a message...",
        "send": "Send",
        "history_title": "📋 Booking History & Rating",
        "rate_worker": "⭐ Rate Worker",
        "submit_rating": "Submit Feedback",
        "app_tagline": "Book trusted handymen near you",
    },
    "ur": {
        "choose_language": "زبان منتخب کریں",
        "continue": "جاری رکھیں",
        "login_title": "لاگ ان / اکاؤنٹ",
        "password": "پاس ورڈ",
        "login_btn": "لاگ ان کریں",
        "phone_label": "موبائل نمبر",
        "phone_placeholder": "03XXXXXXXXX",
        "mode_login": "لاگ ان",
        "mode_register": "اکاؤنٹ بنائیں",
        "register_btn": "🚀 اکاؤنٹ بنائیں",
        "err_no_user": "اس نمبر سے اکاؤنٹ نہیں ملا۔ براہ کرم رجسٹر کریں۔",
        "err_wrong_pw": "پاس ورڈ غلط ہے۔ دوبارہ کوشش کریں۔",
        "err_phone_exists": "یہ نمبر پہلے سے رجسٹرڈ ہے۔",
        "err_phone_invalid": "درست موبائل نمبر درج کریں۔",
        "reg_success": "🎉 اکاؤنٹ بن گیا! اب لاگ ان کریں۔",
        "forgot_pw": "🔑 پاس ورڈ بھول گئے / او ٹی پی ریکوری",
        "send_otp": "او ٹی پی کوڈ بھیجیں",
        "otp_sent": "📲 او ٹی پی کوڈ آپ کے نمبر پر بھیج دیا گیا ہے: **{otp}** (ڈیمو)",
        "enter_otp": "4 ہندسوں کا او ٹی پی درج کریں",
        "new_password": "نیا پاس ورڈ",
        "reset_pw_btn": "پاس ورڈ ری سیٹ کریں",
        "pw_reset_success": "🎉 پاس ورڈ کامیابی سے تبدیل ہو گیا! اب لاگ ان کریں۔",
        "err_wrong_otp": "او ٹی پی غلط ہے۔ دوبارہ کوشش کریں۔",
        "current_location": "موجودہ مقام",
        "loc_use_current": "📍 میری موجودہ لوکیشن",
        "loc_use_other": "🏠 دوسرا پتہ",
        "loc_address_placeholder": "مکمل پتہ درج کریں...",
        "loc_apply": "✅ لوکیشن اپلائی کریں",
        "loc_applied": "لوکیشن سیٹ ہو گئی: {addr}",
        "maintenance_repair": "مینٹیننس اینڈ ریپیئر",
        "select_service": "سروس منتخب کریں",
        "plumber": "پلمبر",
        "electrician": "الیکٹریشن",
        "ac_repairing": "اے سی ریپیئرنگ",
        "solar_system": "سولر سسٹم",
        "gardening": "گارڈننگ",
        "cleaning": "صفائی",
        "painter": "پینٹر",
        "back": "واپس",
        "logout": "لاگ آؤٹ",
        "find_handyman": "کاریگر تلاش کریں",
        "searching": "قریبی کاریگر تلاش کیے جا رہے ہیں...",
        "visit_charge_label": "🧾 وزٹنگ چارجز: روپے 500",
        "visit_note": "ابھی صرف وزٹنگ چارجز ادا کریں۔ کام دیکھنے کے بعد قیمت طے ہوگی۔",
        "visit_warranty": "✅ گارنٹی: اگر دوبارہ مسئلہ آیا تو مرمت مفت ہوگی۔",
        "notif_title": "🔔 نیا جواب!",
        "notif_body": "{name} ({service}) نے آپ کی درخواست قبول کر لی ہے اور راستے میں ہے۔",
        "accept": "قبول کریں",
        "decline": "مسترد کریں",
        "worker_enroute": "کاریگر راستے میں ہے",
        "eta": "متوقع وقت",
        "min": "منٹ",
        "simulate_move": "لوکیشن اپڈیٹ سمولیٹ کریں",
        "arrived": "🎉 کاریگر آپ کے مقام پر پہنچ گیا ہے!",
        "call": "📞 آڈیو کال",
        "message": "💬 پیغام",
        "call_screen_title": "کال کی جا رہی ہے...",
        "mute": "خاموش",
        "end_call": "کال ختم کریں",
        "chat_title": "چیٹ",
        "type_message": "پیغام لکھیں...",
        "send": "بھیجیں",
        "history_title": "📋 بکنگ ہسٹری اور ریٹنگ",
        "rate_worker": "⭐ کاریگر کو ریٹنگ دیں",
        "submit_rating": "فیڈ بیک جمع کریں",
        "app_tagline": "اپنے قریب قابلِ اعتماد کاریگر بک کریں",
    },
    "sd": {
        "choose_language": "ٻولي چونڊيو",
        "continue": "جاري رکو",
        "login_title": "لاگ ان / اڪائونٽ",
        "password": "پاسورڊ",
        "login_btn": "لاگ ان ڪريو",
        "phone_label": "موبائل نمبر",
        "phone_placeholder": "03XXXXXXXXX",
        "mode_login": "لاگ ان",
        "mode_register": "اڪائونٽ ٺاهيو",
        "register_btn": "🚀 اڪائونٽ ٺاهيو",
        "err_no_user": "هن نمبر سان اڪائونٽ نه مليو. رجسٽر ڪريو.",
        "err_wrong_pw": "پاسورڊ غلط آهي. ٻيهر ڪوشش ڪريو.",
        "err_phone_exists": "هي نمبر اڳ ۾ رجسٽرڊ آهي.",
        "err_phone_invalid": "صحيح موبائل نمبر داخل ڪريو.",
        "reg_success": "🎉 اڪائونٽ ٺهي ويو! هاڻي لاگ ان ڪريو.",
        "forgot_pw": "🔑 پاسورڊ وسري ويو / او ٽي پي ریکوري",
        "send_otp": "او ٽي پي موڪليو",
        "otp_sent": "📲 او ٽي پي ڪوڊ اوهان جي نمبر تي موڪليو ويو آهي: **{otp}** (ڊيمو)",
        "enter_otp": "4 انگن جو او ٽي پي داخل ڪريو",
        "new_password": "نئون پاسورڊ",
        "reset_pw_btn": "پاسورڊ ري سيٽ ڪريو",
        "pw_reset_success": "🎉 پاسورڊ تبديل ٿي ويو! هاڻي لاگ ان ڪريو.",
        "err_wrong_otp": "او ٽي پي غلط آهي. ٻيهر ڪوشش ڪريو.",
        "current_location": "موجوده مقام",
        "loc_use_current": "📍 منهنجي موجوده لوڪيشن",
        "loc_use_other": "🏠 ٻيو پتو",
        "loc_address_placeholder": "مڪمل پتو داخل ڪريو...",
        "loc_apply": "✅ لوڪيشن اپلائي ڪريو",
        "loc_applied": "لوڪيشن سيٽ ٿي وئي: {addr}",
        "maintenance_repair": "مينٽيننس ۽ مرمت",
        "select_service": "سروس چونڊيو",
        "plumber": "پلمبر",
        "electrician": "اليڪٽريشن",
        "ac_repairing": "اي سي رپيئرنگ",
        "solar_system": "سولر سسٽم",
        "gardening": "گارڊننگ",
        "cleaning": "صفائي",
        "painter": "پينٽر",
        "back": "پوئتي",
        "logout": "لاگ آئوٽ",
        "find_handyman": "ڪاريگر ڳوليو",
        "searching": "ويجهڙا ڪاريگر ڳوليا پيا وڃن...",
        "visit_charge_label": "🧾 وزٽنگ چارجز: 500 روپيا",
        "visit_note": "هاڻي رڳو وزٽنگ چارجز ڏيو. ڪم ڏسڻ کان پوءِ قيمت طئي ٿيندي.",
        "visit_warranty": "✅ گارنٽي: جيڪڏهن ساڳيو مسئلو ٻيهر ٿيو ته مرمت مفت هوندي.",
        "notif_title": "🔔 نئون جواب!",
        "notif_body": "{name} ({service}) اوهان جي درخواست قبول ڪئي آهي ۽ رستي ۾ آهي.",
        "accept": "قبول ڪريو",
        "decline": "رد ڪريو",
        "worker_enroute": "ڪاريگر رستي ۾ آهي",
        "eta": "لڳ ڀڳ وقت",
        "min": "منٽ",
        "simulate_move": "لوڪيشن اپڊيٽ سمليٽ ڪريو",
        "arrived": "🎉 ڪاريگر اوهان جي مقام تي پهچي ويو آهي!",
        "call": "📞 آڊيو ڪال",
        "message": "💬 پيغام",
        "call_screen_title": "ڪال ڪئي پئي وڃي...",
        "mute": "خاموش",
        "end_call": "ڪال بند ڪريو",
        "chat_title": "چيٽ",
        "type_message": "پيغام لکو...",
        "send": "موڪليو",
        "history_title": "📋 بکنگ هسٽري ۽ ريٽنگ",
        "rate_worker": "⭐ ڪاريگر کي ريٽنگ ڏيو",
        "submit_rating": "فيڊبيڪ موڪليو",
        "app_tagline": "پنهنجي ويجهو ڀروسي وارا ڪاريگر بڪ ڪريو",
    },
}

AUTO_RESPONSES = {
    "en": ["Hello! I am on my way.", "Almost there, please wait for 5 minutes.", "I have arrived at your location.", "How can I help you today?"],
    "ur": ["السلام علیکم! میں راستے میں ہوں۔", "تقریباً پہنچ رہا ہوں، بس 5 منٹ انتظار کریں۔", "میں آپ کی لوکیشن پر پہنچ گیا ہوں۔", "میں آپ کی کیا مدد کر سکتا ہوں؟"],
    "sd": ["اسلام عليڪم! مان رستي ۾ آهيان.", "بس پهچڻ وارو آهيان، 5 منٽ انتظار ڪريو.", "مان اوهان جي لوڪيشن تي پهچي ويو آهيان.", "مان اوهان جي ڇا مدد ڪري سگهان ٿو؟"]
}

SERVICE_ICONS = {
    "plumber": "🔧",
    "electrician": "💡",
    "ac_repairing": "❄️",
    "solar_system": "☀️",
    "gardening": "🌱",
    "cleaning": "🧹",
    "painter": "🎨",
}

SERVICE_LABELS = {
    "plumber": "Plumber",
    "electrician": "Electrician",
    "ac_repairing": "AC Repairing",
    "solar_system": "Solar System",
    "gardening": "Gardening",
    "cleaning": "Cleaning",
    "painter": "Painter",
}

DEMO_WORKERS = [
    {"name": "Ali Ahmed", "rating": 4.8},
    {"name": "Bilal Khan", "rating": 4.6},
    {"name": "Sana Malik", "rating": 4.9},
    {"name": "Usman Tariq", "rating": 4.7},
]

# ---------------------------------------------------------------------------
# SESSION STATE INIT (Persistent Session Handling)
# ---------------------------------------------------------------------------
defaults = {
    "lang": "en",
    "logged_in": False,
    "page": "login",
    "category": None,
    "booking_state": None,
    "worker": None,
    "worker_step": 0,
    "current_booking_id": None,
    "chat_messages": [],
    "loc_mode": "current",
    "loc_address": "Karachi",
    "loc_custom_input": "",
    "user_phone": "",
    "auth_mode": "login", # login, register, forgot
    "reset_otp": None,
    "reset_phone": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

def tr(key):
    lang = st.session_state.lang or "en"
    return T[lang][key]

def get_time_greeting():
    lang = st.session_state.lang or "en"
    hour = datetime.now().hour
    if lang == "ur":
        if 5 <= hour < 12: return "☀️ صبح بخیر!"
        elif 12 <= hour < 17: return "🌤️ دوپہر بخیر!"
        elif 17 <= hour < 21: return "🌇 شام بخیر!"
        else: return "🌙 شب بخیر!"
    elif lang == "sd":
        if 5 <= hour < 12: return "☀️ صبح جو سلام!"
        elif 12 <= hour < 17: return "🌤️ منجھند جو سلام!"
        elif 17 <= hour < 21: return "🌇 شام جو سلام!"
        else: return "🌙 رات جو سلام!"
    else:
        if 5 <= hour < 12: return "☀️ Good Morning!"
        elif 12 <= hour < 17: return "🌤️ Good Afternoon!"
        elif 17 <= hour < 21: return "🌇 Good Evening!"
        else: return "🌙 Good Night!"

def app_title():
    if LOGO_B64:
        logo_html = f"<img src='data:image/png;base64,{LOGO_B64}' style='width:140px;'/>"
    else:
        logo_html = "<div style='font-size:12px; font-weight:700; color:#E7752F; text-transform:uppercase;'>Trusted Home Services</div>"
    st.markdown(
        f"""
        <div style='text-align:center; line-height:1.15; padding-bottom:6px;'>
            <div style='display:flex; justify-content:center;'>{logo_html}</div>
            <div style='font-size:30px; font-weight:800; color:#063260;'>Handyman</div>
            <div dir='rtl' lang='ur' style='font-size:22px; font-weight:700; color:#E7752F;'>کاریگر</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# PAGES
# ---------------------------------------------------------------------------
def page_login():
    app_title()
    st.write("")

    lc1, lc2, lc3 = st.columns(3)
    with lc1:
        if st.button("English", use_container_width=True, type="primary" if st.session_state.lang == "en" else "secondary", key="lang_en"):
            st.session_state.lang = "en"
            st.rerun()
    with lc2:
        if st.button("اردو", use_container_width=True, type="primary" if st.session_state.lang == "ur" else "secondary", key="lang_ur"):
            st.session_state.lang = "ur"
            st.rerun()
    with lc3:
        if st.button("سنڌي", use_container_width=True, type="primary" if st.session_state.lang == "sd" else "secondary", key="lang_sd"):
            st.session_state.lang = "sd"
            st.rerun()

    st.write("")
    st.subheader(tr("login_title"))

    m1, m2 = st.columns(2)
    with m1:
        if st.button(tr("mode_login"), use_container_width=True, type="primary" if st.session_state.auth_mode == "login" else "secondary", key="mode_login_btn"):
            st.session_state.auth_mode = "login"
            st.rerun()
    with m2:
        if st.button(tr("mode_register"), use_container_width=True, type="primary" if st.session_state.auth_mode == "register" else "secondary", key="mode_reg_btn"):
            st.session_state.auth_mode = "register"
            st.rerun()

    st.write("")

    def valid_phone(p):
        p = p.strip()
        return p.isdigit() and 10 <= len(p) <= 12

    if st.session_state.auth_mode == "forgot":
        st.markdown(f"**{tr('forgot_pw')}**")
        f_phone = st.text_input(tr("phone_label"), placeholder=tr("phone_placeholder"), key="forgot_phone_input")
        
        if st.session_state.reset_otp is None:
            if st.button(tr("send_otp"), use_container_width=True, type="primary", key="action_send_otp"):
                if not valid_phone(f_phone):
                    st.error(tr("err_phone_invalid"))
                else:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute("SELECT id FROM users WHERE phone = ?", (f_phone.strip(),))
                    row = cur.fetchone()
                    conn.close()
                    if not row:
                        st.error(tr("err_no_user"))
                    else:
                        otp_code = str(random.randint(1000, 9999))
                        st.session_state.reset_otp = otp_code
                        st.session_state.reset_phone = f_phone.strip()
                        st.rerun()
        else:
            st.info(tr("otp_sent").format(otp=st.session_state.reset_otp))
            entered_otp = st.text_input(tr("enter_otp"), max_chars=4, key="forgot_otp_input")
            new_pw = st.text_input(tr("new_password"), type="password", key="forgot_new_pw")
            
            if st.button(tr("reset_pw_btn"), use_container_width=True, type="primary", key="action_reset_pw"):
                if entered_otp.strip() == st.session_state.reset_otp:
                    if len(new_pw.strip()) < 4:
                        st.error(tr("err_wrong_pw"))
                    else:
                        update_user_password(st.session_state.reset_phone, new_pw.strip())
                        st.success(tr("pw_reset_success"))
                        st.session_state.reset_otp = None
                        st.session_state.reset_phone = None
                        st.session_state.auth_mode = "login"
                        st.rerun()
                else:
                    st.error(tr("err_wrong_otp"))

        if st.button("⬅ " + tr("back"), use_container_width=True, key="back_to_login_btn"):
            st.session_state.auth_mode = "login"
            st.session_state.reset_otp = None
            st.rerun()

    else:
        phone = st.text_input(tr("phone_label"), placeholder=tr("phone_placeholder"), key="login_phone_input")
        password = st.text_input(tr("password"), type="password", key="login_pass_input")

        if st.session_state.auth_mode == "login":
            if st.button(tr("login_btn"), use_container_width=True, type="primary", key="action_login_btn"):
                if not valid_phone(phone):
                    st.error(tr("err_phone_invalid"))
                elif not password.strip():
                    st.error(tr("err_wrong_pw"))
                else:
                    ok, reason = verify_user(phone.strip(), password)
                    if ok:
                        st.session_state.logged_in = True
                        st.session_state.user_phone = phone.strip()
                        st.session_state.page = "home"
                        st.rerun()
                    elif reason == "no_user":
                        st.error(tr("err_no_user"))
                    else:
                        st.error(tr("err_wrong_pw"))

            st.write("")
            if st.button(tr("forgot_pw"), use_container_width=True, key="goto_forgot_btn"):
                st.session_state.auth_mode = "forgot"
                st.rerun()

        else: # register
            if st.button(tr("register_btn"), use_container_width=True, type="primary", key="action_register_btn"):
                if not valid_phone(phone):
                    st.error(tr("err_phone_invalid"))
                elif len(password.strip()) < 4:
                    st.error(tr("err_wrong_pw"))
                else:
                    ok, reason = register_user(phone.strip(), password)
                    if ok:
                        st.success(tr("reg_success"))
                        st.session_state.auth_mode = "login"
                        st.rerun()
                    else:
                        st.error(tr("err_phone_exists"))

def page_home():
    top = st.columns([4, 1])
    with top[0]:
        app_title()
    with top[1]:
        if st.button("🌐", key="home_lang_toggle"):
            st.session_state.page = "login"
            st.rerun()

    st.write("")
    st.markdown(
        f"""
        <div style='background:linear-gradient(135deg,#F0E9D2 0%,#FCFBE8 100%);
                    border:1.5px solid #E7752F; border-radius:14px; padding:10px 16px;
                    text-align:center; font-weight:700; font-size:14px; color:#063260;
                    margin-bottom:12px;'>
            {get_time_greeting()}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(tr("app_tagline"))
    st.write("---")

    st.markdown(f"**📍 {tr('current_location')}**")
    loc_choice = st.radio(
        "loc_mode_picker",
        options=["current", "other"],
        format_func=lambda o: tr("loc_use_current") if o == "current" else tr("loc_use_other"),
        index=0 if st.session_state.loc_mode == "current" else 1,
        label_visibility="collapsed",
        horizontal=True,
    )

    if loc_choice == "other":
        custom_addr = st.text_input(
            tr("loc_address_placeholder"),
            value=st.session_state.loc_custom_input,
            label_visibility="collapsed",
            placeholder=tr("loc_address_placeholder"),
            key="home_custom_address"
        )
        st.session_state.loc_custom_input = custom_addr
    else:
        custom_addr = None

    if st.button(tr("loc_apply"), use_container_width=True, key="home_apply_loc"):
        st.session_state.loc_mode = loc_choice
        if loc_choice == "other" and custom_addr and custom_addr.strip():
            st.session_state.loc_address = custom_addr.strip()
        elif loc_choice == "current":
            st.session_state.loc_address = "Karachi"
        st.rerun()

    st.success(tr("loc_applied").format(addr=st.session_state.loc_address))
    st.write("---")

    if st.button("🛠️  " + tr("maintenance_repair"), use_container_width=True, type="primary", key="home_maint_btn"):
        st.session_state.page = "category"
        st.rerun()

    st.write("")
    if st.button("📋  " + tr("history_title"), use_container_width=True, key="home_history_btn"):
        st.session_state.page = "history"
        st.rerun()

    st.write("")
    if st.button(tr("logout"), use_container_width=True, key="home_logout_btn"):
        for k, v in defaults.items():
            st.session_state[k] = v
        st.rerun()

def page_category():
    app_title()
    st.write("")
    st.subheader(tr("select_service"))

    services = ["plumber", "electrician", "ac_repairing", "solar_system", "gardening", "cleaning", "painter"]
    cols = st.columns(2)
    for i, s in enumerate(services):
        with cols[i % 2]:
            if st.button(f"{SERVICE_ICONS[s]}  {SERVICE_LABELS[s]}", use_container_width=True, key=f"svc_btn_{s}"):
                st.session_state.category = s
                st.session_state.booking_state = None
                st.session_state.page = "booking"
                st.rerun()

    st.write("")
    if st.button("⬅ " + tr("back"), use_container_width=True, key="cat_back_btn"):
        st.session_state.page = "home"
        st.rerun()

def draw_map(worker_lat=None, worker_lng=None):
    m = folium.Map(
        location=[BAHRIA_TOWN_KARACHI["lat"], BAHRIA_TOWN_KARACHI["lng"]],
        zoom_start=11,
        tiles="OpenStreetMap",
    )
    folium.Marker(
        [BAHRIA_TOWN_KARACHI["lat"], BAHRIA_TOWN_KARACHI["lng"]],
        tooltip="You",
        icon=folium.Icon(color="blue", icon="home"),
    ).add_to(m)

    if worker_lat is not None:
        folium.Marker(
            [worker_lat, worker_lng],
            tooltip=st.session_state.worker["name"] if st.session_state.worker else "Worker",
            icon=folium.Icon(color="green", icon="wrench", prefix="fa"),
        ).add_to(m)
        folium.PolyLine(
            [[worker_lat, worker_lng], [BAHRIA_TOWN_KARACHI["lat"], BAHRIA_TOWN_KARACHI["lng"]]],
            color="green",
            weight=3,
            dash_array="6",
        ).add_to(m)

    st_folium(m, height=300, width=None, returned_objects=[])

def page_booking():
    app_title()
    st.write("")
    if st.session_state.category:
        cat = st.session_state.category
        st.subheader(f"{SERVICE_ICONS[cat]}  {SERVICE_LABELS[cat]}")

    state = st.session_state.booking_state
    st.markdown(f"<div style='font-size:13px; color:#5A4A2A; margin-bottom:8px;'>📍 <b>{st.session_state.loc_address}</b></div>", unsafe_allow_html=True)

    if state is None:
        st.markdown(
            f"""
            <div style='background:#FCFBE8; border:2px solid #F0E9D2; border-radius:14px; padding:12px 16px; margin-bottom:12px;'>
                <div style='font-weight:800; color:#063260; font-size:15px;'>{tr('visit_charge_label')}</div>
                <div style='font-size:13px; color:#5A4A2A; margin-top:4px;'>{tr('visit_note')}</div>
                <div style='font-size:13px; color:#2E7D32; margin-top:6px; font-weight:600;'>{tr('visit_warranty')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        draw_map()
        st.write("")
        if st.button("🔍  " + tr("find_handyman"), use_container_width=True, type="primary", key="booking_find_btn"):
            st.session_state.booking_state = "searching"
            st.rerun()

    elif state == "searching":
        with st.spinner(tr("searching")):
            time.sleep(1.5)
        st.session_state.worker = random.choice(DEMO_WORKERS)
        st.session_state.booking_state = "notified"
        st.session_state.worker_step = 0
        st.rerun()

    elif state == "notified":
        worker = st.session_state.worker
        cat_label = SERVICE_LABELS[st.session_state.category]
        st.info(f"**{tr('notif_title')}**\n\n" + tr("notif_body").format(name=worker["name"], service=cat_label))
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ " + tr("accept"), use_container_width=True, type="primary", key="booking_accept_btn"):
                st.session_state.booking_state = "accepted"
                st.session_state.worker_step = 0
                booking_id = save_booking(
                    st.session_state.user_phone,
                    cat_label,
                    st.session_state.loc_address,
                    worker["name"],
                )
                st.session_state.current_booking_id = booking_id
                st.rerun()
        with c2:
            if st.button("❌ " + tr("decline"), use_container_width=True, key="booking_decline_btn"):
                st.session_state.booking_state = None
                st.session_state.worker = None
                st.rerun()

    elif state in ("accepted", "arrived"):
        worker = st.session_state.worker
        step = st.session_state.worker_step
        lat_offsets = [0.05, 0.03, 0.01, 0.0]
        lng_offsets = [0.05, 0.03, 0.01, 0.0]
        curr_lat = BAHRIA_TOWN_KARACHI["lat"] + lat_offsets[min(step, 3)]
        curr_lng = BAHRIA_TOWN_KARACHI["lng"] + lng_offsets[min(step, 3)]

        st.success(f"👷 **{worker['name']}** — ⭐ {worker['rating']}")
        if step < 3:
            st.info(f"🚗 {tr('worker_enroute')} ({tr('eta')}: {(3 - step) * 5} {tr('min')})")
            draw_map(curr_lat, curr_lng)
            if st.button(tr("simulate_move"), use_container_width=True, type="primary", key="booking_sim_move_btn"):
                st.session_state.worker_step += 1
                if st.session_state.worker_step >= 3:
                    st.session_state.booking_state = "arrived"
                st.rerun()
        else:
            st.balloons()
            st.success(tr("arrived"))
            draw_map(BAHRIA_TOWN_KARACHI["lat"], BAHRIA_TOWN_KARACHI["lng"])

        st.write("")
        col_call, col_chat = st.columns(2)
        with col_call:
            if st.button(tr("call"), use_container_width=True, key="booking_call_btn"):
                st.session_state.page = "call"
                st.rerun()
        with col_chat:
            if st.button(tr("message"), use_container_width=True, key="booking_chat_btn"):
                st.session_state.page = "chat"
                st.rerun()

        st.write("")
        if st.button("⬅ " + tr("back"), use_container_width=True, key="booking_back_btn"):
            st.session_state.page = "category"
            st.rerun()

def page_chat():
    app_title()
    worker = st.session_state.worker
    st.subheader(f"{tr('chat_title')} {worker['name'] if worker else 'Worker'}")

    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.chat_messages:
            if msg["sender"] == "user":
                st.markdown(f"<div style='text-align:right; color:#063260; background:#F0E9D2; padding:8px; border-radius:10px; margin:4px 0;'><b>You:</b> {msg['text']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='text-align:left; color:#E7752F; background:#FCFBE8; padding:8px; border-radius:10px; margin:4px 0;'><b>{worker['name']}:</b> {msg['text']}</div>", unsafe_allow_html=True)

    with st.form("chat_form", clear_on_submit=True):
        txt = st.text_input(tr("type_message"), label_visibility="collapsed", key="chat_input_box")
        submitted = st.form_submit_button(tr("send"))
        if submitted and txt.strip():
            st.session_state.chat_messages.append({"sender": "user", "text": txt.strip()})
            lang = st.session_state.lang
            bot_reply = random.choice(AUTO_RESPONSES.get(lang, AUTO_RESPONSES["en"]))
            st.session_state.chat_messages.append({"sender": "worker", "text": bot_reply})
            st.rerun()

    st.write("")
    if st.button("⬅ " + tr("back"), use_container_width=True, key="chat_back_btn"):
        st.session_state.page = "booking"
        st.rerun()

def page_call():
    app_title()
    st.subheader(tr("call_screen_title"))
    worker = st.session_state.worker
    st.markdown(f"### 📞 {worker['name'] if worker else 'Worker'}")
    st.write("Connecting audio call...")

    c1, c2 = st.columns(2)
    with c1:
        st.button(tr("mute"), use_container_width=True, key="call_mute_btn")
    with c2:
        if st.button(tr("end_call"), use_container_width=True, type="primary", key="call_end_btn"):
            st.session_state.page = "booking"
            st.rerun()

def page_history():
    app_title()
    st.subheader(tr("history_title"))
    
    rows = get_user_bookings(st.session_state.user_phone)
    if not rows:
        st.info("No bookings found yet.")
    else:
        for r in rows:
            b_id, s_name, addr, w_name, status, rating, review, c_at = r
            with st.expander(f"🛠️ {s_name.upper()} — {w_name} ({status})"):
                st.write(f"**Address:** {addr}")
                st.write(f"**Date:** {c_at}")
                if rating > 0:
                    st.write(f"**Rating:** {'⭐' * rating}")
                    if review:
                        st.write(f"**Review:** {review}")
                else:
                    st.markdown(f"**{tr('rate_worker')}**")
                    with st.form(f"rate_form_{b_id}"):
                        stars = st.slider("Rating", 1, 5, 5, key=f"star_{b_id}")
                        rev_text = st.text_input("Review Comment", key=f"rev_{b_id}")
                        submitted = st.form_submit_button(tr("submit_rating"))
                        if submitted:
                            update_booking_rating(b_id, stars, rev_text)
                            st.success("Thank you for your feedback!")
                            st.rerun()

    st.write("")
    if st.button("⬅ " + tr("back"), use_container_width=True, key="history_back_btn"):
        st.session_state.page = "home"
        st.rerun()

# ---------------------------------------------------------------------------
# ROUTER (Persistent Check)
# ---------------------------------------------------------------------------
if not st.session_state.logged_in:
    page_login()
else:
    page = st.session_state.page
    if page == "home" or page == "login":
        page_home()
    elif page == "category":
        page_category()
    elif page == "booking":
        page_booking()
    elif page == "chat":
        page_chat()
    elif page == "call":
        page_call()
    elif page == "history":
        page_history()
    else:
        page_home()