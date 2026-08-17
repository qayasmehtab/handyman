import time
import random
import secrets as pysecrets
import hashlib
from datetime import datetime, date, timedelta, timezone
import streamlit as st
import folium
from streamlit_folium import st_folium
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Handyman | کاریگر",
    page_icon="🛠️",
    layout="centered",
)

# ---------------------------------------------------------------------------
# DATABASE SETUP (Supabase — permanent, cloud, free tier)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------
def register_user(phone, password, role="customer", name="User", service_type="plumber",
                   cnic_number=None, cnic_expiry=None, cnic_front_url=None,
                   cnic_back_url=None, selfie_url=None):
    sb = get_supabase()
    existing = sb.table("users").select("id").eq("phone", phone).execute()
    if existing.data:
        return False, "exists"

    if role == "worker" and cnic_number:
        cnic_existing = sb.table("users").select("id").eq("cnic_number", cnic_number).execute()
        if cnic_existing.data:
            return False, "cnic_exists"

    payload = {
        "phone": phone,
        "password_hash": hash_password(password),
        "role": role,
        "name": name,
        "service_type": service_type,
    }
    if role == "worker":
        payload.update({
            "cnic_number": cnic_number,
            "cnic_expiry": str(cnic_expiry) if cnic_expiry else None,
            "cnic_front_url": cnic_front_url,
            "cnic_back_url": cnic_back_url,
            "selfie_url": selfie_url,
            "is_verified": True,
        })
    sb.table("users").insert(payload).execute()
    return True, "ok"


def upload_kyc_file(uploaded_file, phone, label):
    """Upload a KYC image to Supabase Storage and return its public URL."""
    sb = get_supabase()
    ext = uploaded_file.name.split(".")[-1].lower()
    path = f"{phone}/{label}.{ext}"
    file_bytes = uploaded_file.getvalue()
    sb.storage.from_("worker-kyc").upload(
        path, file_bytes,
        file_options={"content-type": uploaded_file.type, "upsert": "true"},
    )
    return sb.storage.from_("worker-kyc").get_public_url(path)


def verify_user(phone, password):
    sb = get_supabase()
    res = sb.table("users").select("password_hash, role, name, service_type").eq("phone", phone).execute()
    if not res.data:
        return False, "no_user", None, None, None
    row = res.data[0]
    if row["password_hash"] == hash_password(password):
        return True, "ok", row["role"], row["name"], row["service_type"]
    return False, "wrong_pw", None, None, None


def update_user_password(phone, new_password):
    sb = get_supabase()
    sb.table("users").update({"password_hash": hash_password(new_password)}).eq("phone", phone).execute()


# ---------------------------------------------------------------------------
# SESSION PERSISTENCE (stay logged in across reloads)
# ---------------------------------------------------------------------------
def create_session(phone):
    try:
        sb = get_supabase()
        token = pysecrets.token_hex(16)
        sb.table("sessions").insert({"token": token, "phone": phone}).execute()
        return token
    except Exception:
        return None


def get_session_phone(token):
    try:
        sb = get_supabase()
        res = sb.table("sessions").select("phone").eq("token", token).execute()
        if res.data:
            return res.data[0]["phone"]
    except Exception:
        pass
    return None


def delete_session(token):
    if not token:
        return
    try:
        sb = get_supabase()
        sb.table("sessions").delete().eq("token", token).execute()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# BOOKINGS / TICKETS
# ---------------------------------------------------------------------------
def find_available_worker(service_key, exclude_phones=None):
    sb = get_supabase()
    res = sb.table("users").select("phone,name").eq("role", "worker").eq(
        "service_type", service_key).eq("is_verified", True).execute()
    exclude_phones = exclude_phones or []
    candidates = [r for r in res.data if r["phone"] not in exclude_phones]
    if not candidates:
        return None
    return random.choice(candidates)


def compute_visit_charge(customer_phone, service_key):
    """First job for this service = Rs.500, every job after that = Rs.750."""
    sb = get_supabase()
    res = sb.table("bookings").select("id").eq("customer_phone", customer_phone).eq(
        "service_key", service_key).eq("is_warranty", False).eq("status", "Completed").execute()
    return 500 if len(res.data) == 0 else 750


def save_booking(phone, service_label, service_key, address, payment_method, issue_desc,
                  assigned_worker_phone, visit_charge, is_warranty=False, parent_booking_id=None):
    sb = get_supabase()
    res = sb.table("bookings").insert({
        "customer_phone": phone,
        "service": service_label,
        "service_key": service_key,
        "address": address,
        "worker_name": None,
        "assigned_worker_phone": assigned_worker_phone,
        "payment_method": payment_method,
        "status": "Requested",
        "issue_desc": issue_desc,
        "is_warranty": is_warranty,
        "parent_booking_id": parent_booking_id,
        "visit_charge": visit_charge,
        "declined_workers": "",
    }).execute()
    return res.data[0]["id"]


def get_booking(booking_id):
    sb = get_supabase()
    res = sb.table("bookings").select("*").eq("id", booking_id).execute()
    return res.data[0] if res.data else None


def accept_booking(booking_id, worker_name):
    sb = get_supabase()
    sb.table("bookings").update({"status": "Pending", "worker_name": worker_name}).eq("id", booking_id).execute()


def decline_and_reassign(booking_id, current_worker_phone, service_key, declined_str):
    sb = get_supabase()
    declined_list = [d for d in (declined_str or "").split(",") if d]
    declined_list.append(current_worker_phone)
    next_worker = find_available_worker(service_key, exclude_phones=declined_list)
    update = {"declined_workers": ",".join(declined_list)}
    if next_worker:
        update["assigned_worker_phone"] = next_worker["phone"]
    else:
        update["assigned_worker_phone"] = None
        update["status"] = "Unassigned"
    sb.table("bookings").update(update).eq("id", booking_id).execute()


def cancel_booking(booking_id):
    sb = get_supabase()
    sb.table("bookings").update({"status": "Cancelled"}).eq("id", booking_id).execute()


def complete_booking(booking_id, final_amount, job_notes):
    sb = get_supabase()
    ticket_until = (now_utc() + timedelta(days=3)).isoformat()
    sb.table("bookings").update({
        "status": "Completed",
        "final_amount": final_amount,
        "job_notes": job_notes,
        "ticket_open_until": ticket_until,
    }).eq("id", booking_id).execute()


def update_booking_rating(booking_id, rating, review):
    sb = get_supabase()
    sb.table("bookings").update({"rating": rating, "review": review}).eq("id", booking_id).execute()


def get_user_bookings(phone):
    sb = get_supabase()
    res = sb.table("bookings").select("*").eq("customer_phone", phone).order("id", desc=True).execute()
    return res.data


def get_worker_requests(worker_phone):
    sb = get_supabase()
    res = sb.table("bookings").select("*").eq("assigned_worker_phone", worker_phone).eq(
        "status", "Requested").order("id", desc=True).execute()
    return res.data


def get_worker_jobs(worker_phone):
    sb = get_supabase()
    res = sb.table("bookings").select("*").eq("assigned_worker_phone", worker_phone).order(
        "id", desc=True).execute()
    return [r for r in res.data if r["status"] in ("Pending", "Completed")]

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
# TRANSLATIONS (English, Urdu, Sindhi Only)
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
        "role_label": "Select Account Type",
        "role_customer": "Customer",
        "role_worker": "Worker / Provider",
        "name_label": "Full Name",
        "cnic_label": "CNIC Number",
        "cnic_placeholder": "42101-1234567-1",
        "cnic_expiry_label": "CNIC Expiry Date",
        "cnic_front_label": "📄 CNIC Front Photo",
        "cnic_back_label": "📄 CNIC Back Photo",
        "selfie_label": "🤳 Selfie holding your CNIC",
        "err_cnic_expired": "This CNIC is expired. Please use a valid CNIC.",
        "err_cnic_missing": "Please fill CNIC number and expiry date.",
        "err_cnic_exists": "This CNIC is already registered with another account.",
        "err_files_missing": "Please upload CNIC front, back, and a selfie holding your CNIC.",
        "uploading_kyc": "Uploading verification documents...",
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
        "visit_charge_dynamic": "🧾 Visiting Charges: Rs. {amount}",
        "visit_note": "Pay only visiting charges now. Repair cost will be decided on-site.",
        "visit_warranty": "✅ Warranty: Free repair if same issue occurs again within 3 days.",
        "payment_method": "💳 Payment Method",
        "pay_cash": "Cash on Delivery",
        "pay_jazzcash": "JazzCash Mobile Wallet",
        "pay_easypaisa": "EasyPaisa Mobile Wallet",
        "issue_desc_label": "Briefly describe the problem",
        "waiting_worker": "⏳ Waiting for a worker to accept your request...",
        "no_worker_available": "No worker is available right now. Please try again later.",
        "retry": "🔁 Try Again",
        "cancel_request": "❌ Cancel Request",
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
        "worker_dashboard": "👷 Worker Dashboard",
        "total_earnings": "💰 Total Earnings",
        "complete_job": "✅ Mark Completed",
        "rate_worker": "⭐ Rate Worker",
        "submit_rating": "Submit Feedback",
        "app_tagline": "Book trusted handymen near you",
        "tab_requests": "🔔 New Requests",
        "tab_active": "🛠️ My Jobs",
        "job_notes_label": "Job Details / Work Done",
        "final_amount_label": "Final Amount (Rs.)",
        "report_issue": "⚠️ Report Same Issue (Free under Warranty)",
        "warranty_active_note": "🛡️ This is a free warranty visit for a previous issue.",
        "ticket_valid_till": "🛡️ Warranty valid till: {date}",
        "role_badge_worker": "👷 Worker Account",
        "role_badge_customer": "🙋 Customer Account",
        "accept": "Accept",
        "decline": "Decline",
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
        "role_label": "اکاؤنٹ کی قسم منتخب کریں",
        "role_customer": "کسٹمر",
        "role_worker": "کاریگر / ورکر",
        "name_label": "پورا نام",
        "cnic_label": "شناختی کارڈ نمبر (CNIC)",
        "cnic_placeholder": "42101-1234567-1",
        "cnic_expiry_label": "شناختی کارڈ کی میعاد ختم ہونے کی تاریخ",
        "cnic_front_label": "📄 شناختی کارڈ کا اگلا حصہ",
        "cnic_back_label": "📄 شناختی کارڈ کا پچھلا حصہ",
        "selfie_label": "🤳 اپنا شناختی کارڈ پکڑ کر سیلفی",
        "err_cnic_expired": "یہ شناختی کارڈ کی میعاد ختم ہو چکی ہے۔ درست کارڈ استعمال کریں۔",
        "err_cnic_missing": "براہ کرم شناختی کارڈ نمبر اور تاریخ درج کریں۔",
        "err_cnic_exists": "یہ شناختی کارڈ پہلے ہی کسی اور اکاؤنٹ سے رجسٹرڈ ہے۔",
        "err_files_missing": "براہ کرم شناختی کارڈ کا اگلا، پچھلا حصہ اور سیلفی اپلوڈ کریں۔",
        "uploading_kyc": "تصدیقی دستاویزات اپلوڈ ہو رہی ہیں...",
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
        "visit_charge_dynamic": "🧾 وزٹنگ چارجز: روپے {amount}",
        "visit_note": "ابھی صرف وزٹنگ چارجز ادا کریں۔ کام دیکھنے کے بعد قیمت طے ہوگی۔",
        "visit_warranty": "✅ گارنٹی: اگر 3 دن کے اندر دوبارہ وہی مسئلہ آیا تو مرمت مفت ہوگی۔",
        "payment_method": "💳 ادائیگی کا طریقہ",
        "pay_cash": "کیش آن ڈلیوری",
        "pay_jazzcash": "جاز کیش موبائل والٹ",
        "pay_easypaisa": "ایزی پیسا موبائل والٹ",
        "issue_desc_label": "مسئلہ مختصراً بیان کریں",
        "waiting_worker": "⏳ کاریگر کے آپ کی درخواست قبول کرنے کا انتظار ہے...",
        "no_worker_available": "فی الحال کوئی کاریگر دستیاب نہیں۔ بعد میں کوشش کریں۔",
        "retry": "🔁 دوبارہ کوشش کریں",
        "cancel_request": "❌ درخواست منسوخ کریں",
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
        "worker_dashboard": "👷 ورکر ڈیش بورڈ",
        "total_earnings": "💰 کل آمدنی",
        "complete_job": "✅ کام مکمل ہو گیا",
        "rate_worker": "⭐ کاریگر کو ریٹنگ دیں",
        "submit_rating": "فیڈ بیک جمع کریں",
        "app_tagline": "اپنے قریب قابلِ اعتماد کاریگر بک کریں",
        "tab_requests": "🔔 نئی درخواستیں",
        "tab_active": "🛠️ میرے کام",
        "job_notes_label": "کام کی تفصیل",
        "final_amount_label": "حتمی رقم (روپے)",
        "report_issue": "⚠️ وہی مسئلہ دوبارہ رپورٹ کریں (گارنٹی کے تحت مفت)",
        "warranty_active_note": "🛡️ یہ پرانے مسئلے کے لیے مفت گارنٹی وزٹ ہے۔",
        "ticket_valid_till": "🛡️ گارنٹی کی میعاد: {date}",
        "role_badge_worker": "👷 ورکر اکاؤنٹ",
        "role_badge_customer": "🙋 کسٹمر اکاؤنٹ",
        "accept": "قبول کریں",
        "decline": "مسترد کریں",
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
        "role_label": "اڪائونٽ جي قسم چونڊيو",
        "role_customer": "ڪسٽمر",
        "role_worker": "ڪاريگر / ورڪر",
        "name_label": "پورو نالو",
        "cnic_label": "سڃاڻپي ڪارڊ نمبر (CNIC)",
        "cnic_placeholder": "42101-1234567-1",
        "cnic_expiry_label": "سڃاڻپي ڪارڊ جي ختم ٿيڻ جي تاريخ",
        "cnic_front_label": "📄 ڪارڊ جو اڳيون پاسو",
        "cnic_back_label": "📄 ڪارڊ جو پوئتين پاسو",
        "selfie_label": "🤳 ڪارڊ پڪڙي سيلفي",
        "err_cnic_expired": "هي ڪارڊ ختم ٿي چڪو آهي. صحيح ڪارڊ استعمال ڪريو.",
        "err_cnic_missing": "مهرباني ڪري ڪارڊ نمبر ۽ تاريخ داخل ڪريو.",
        "err_cnic_exists": "هي ڪارڊ اڳ ۾ ئي ٻي اڪائونٽ سان رجسٽرڊ آهي.",
        "err_files_missing": "مهرباني ڪري ڪارڊ جو اڳيون، پوئتين پاسو ۽ سيلفي اپلوڊ ڪريو.",
        "uploading_kyc": "دستاويز اپلوڊ ٿي رهيا آهن...",
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
        "visit_charge_dynamic": "🧾 وزٽنگ چارجز: روپيا {amount}",
        "visit_note": "هاڻي رڳو وزٽنگ چارجز ڏيو. ڪم ڏسڻ کان پوءِ قيمت طئي ٿيندي.",
        "visit_warranty": "✅ گارنٽي: جيڪڏهن 3 ڏينهن اندر ساڳيو مسئلو ٻيهر ٿيو ته مرمت مفت هوندي.",
        "payment_method": "💳 ادائگي جو طريقو",
        "pay_cash": "ڪيش آن ڊليوري",
        "pay_jazzcash": "جاز ڪيش موبائل والٽ",
        "pay_easypaisa": "ايزي پيسا موبائل والٽ",
        "issue_desc_label": "مسئلو مختصر بيان ڪريو",
        "waiting_worker": "⏳ ڪاريگر جي اوهان جي درخواست قبول ڪرڻ جو انتظار آهي...",
        "no_worker_available": "هن وقت ڪو به ڪاريگر موجود ناهي. بعد ۾ ڪوشش ڪريو.",
        "retry": "🔁 ٻيهر ڪوشش ڪريو",
        "cancel_request": "❌ درخواست رد ڪريو",
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
        "worker_dashboard": "👷 ورڪر ڊيش بورڊ",
        "total_earnings": "💰 ڪل آمدني",
        "complete_job": "✅ ڪم مڪمل ٿيو",
        "rate_worker": "⭐ ڪاريگر کي ريٽنگ ڏيو",
        "submit_rating": "فيڊبيڪ موڪليو",
        "app_tagline": "پنهنجي ويجهو ڀروسي وارا ڪاريگر بڪ ڪريو",
        "tab_requests": "🔔 نيون درخواستون",
        "tab_active": "🛠️ منهنجا ڪم",
        "job_notes_label": "ڪم جي تفصيل",
        "final_amount_label": "آخري رقم (روپيا)",
        "report_issue": "⚠️ ساڳيو مسئلو ٻيهر ٻڌايو (گارنٽي هيٺ مفت)",
        "warranty_active_note": "🛡️ هي پراڻي مسئلي لاءِ مفت گارنٽي وزٽ آهي.",
        "ticket_valid_till": "🛡️ گارنٽي جي ميعاد: {date}",
        "role_badge_worker": "👷 ورڪر اڪائونٽ",
        "role_badge_customer": "🙋 ڪسٽمر اڪائونٽ",
        "accept": "قبول ڪريو",
        "decline": "رد ڪريو",
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

# ---------------------------------------------------------------------------
# SESSION STATE INIT
# ---------------------------------------------------------------------------
defaults = {
    "lang": "en",
    "logged_in": False,
    "user_role": "customer",
    "user_name": "User",
    "page": "login",
    "category": None,
    "worker_step": 0,
    "tracked_booking_id": None,
    "current_booking_id": None,
    "chat_messages": [],
    "loc_mode": "current",
    "loc_address": "Karachi",
    "loc_custom_input": "",
    "user_phone": "",
    "auth_mode": "login",
    "reset_otp": None,
    "reset_phone": None,
    "payment_method": "Cash",
    "session_token": None,
    "warranty_claim": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Auto-login via URL token (keeps user logged in after closing/reopening app)
if not st.session_state.logged_in:
    _t = st.query_params.get("t")
    if _t:
        _phone = get_session_phone(_t)
        if _phone:
            sb = get_supabase()
            res = sb.table("users").select("role,name,service_type").eq("phone", _phone).execute()
            if res.data:
                st.session_state.logged_in = True
                st.session_state.user_phone = _phone
                st.session_state.user_role = res.data[0]["role"]
                st.session_state.user_name = res.data[0]["name"]
                st.session_state.session_token = _t
                if st.session_state.page == "login":
                    st.session_state.page = "home"


def tr(key):
    lang = st.session_state.lang or "en"
    return T[lang][key]


def do_logout():
    delete_session(st.session_state.get("session_token"))
    st.query_params.clear()
    for k, v in defaults.items():
        st.session_state[k] = v


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
    st.markdown(
        """
        <div style='text-align:center; line-height:1.15; padding-bottom:6px;'>
            <div style='font-size:32px; font-weight:800; color:#063260;'>Handyman</div>
            <div dir='rtl' lang='ur' style='font-size:24px; font-weight:700; color:#E7752F;'>کاریگر</div>
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
                    sb = get_supabase()
                    res = sb.table("users").select("id").eq("phone", f_phone.strip()).execute()
                    if not res.data:
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
                    ok, reason, role, name, s_type = verify_user(phone.strip(), password)
                    if ok:
                        st.session_state.logged_in = True
                        st.session_state.user_phone = phone.strip()
                        st.session_state.user_role = role
                        st.session_state.user_name = name
                        st.session_state.page = "home"
                        token = create_session(phone.strip())
                        if token:
                            st.session_state.session_token = token
                            st.query_params["t"] = token
                        st.rerun()
                    elif reason == "no_user":
                        st.error(tr("err_no_user"))
                    else:
                        st.error(tr("err_wrong_pw"))

            st.write("")
            if st.button(tr("forgot_pw"), use_container_width=True, key="goto_forgot_btn"):
                st.session_state.auth_mode = "forgot"
                st.rerun()

        else:
            name = st.text_input(tr("name_label"), placeholder="Ali Ahmed", key="reg_name_input")
            role_choice = st.selectbox(tr("role_label"), options=["customer", "worker"], format_func=lambda r: tr("role_customer") if r == "customer" else tr("role_worker"), key="reg_role_input")

            s_type = "plumber"
            cnic_number = None
            cnic_expiry = None
            cnic_front_file = None
            cnic_back_file = None
            selfie_file = None

            if role_choice == "worker":
                s_type = st.selectbox(tr("select_service"), options=list(SERVICE_LABELS.keys()), format_func=lambda s: SERVICE_LABELS[s], key="reg_service_input")

                st.write("---")
                st.markdown(f"**🪪 {tr('cnic_label')}**")
                cnic_number = st.text_input(tr("cnic_label"), placeholder=tr("cnic_placeholder"),
                                             key="reg_cnic_number", label_visibility="collapsed")
                cnic_expiry = st.date_input(tr("cnic_expiry_label"), min_value=date.today(),
                                             key="reg_cnic_expiry")
                cnic_front_file = st.file_uploader(tr("cnic_front_label"), type=["jpg", "jpeg", "png"], key="reg_cnic_front")
                cnic_back_file = st.file_uploader(tr("cnic_back_label"), type=["jpg", "jpeg", "png"], key="reg_cnic_back")
                selfie_file = st.file_uploader(tr("selfie_label"), type=["jpg", "jpeg", "png"], key="reg_selfie")

            if st.button(tr("register_btn"), use_container_width=True, type="primary", key="action_register_btn"):
                if not valid_phone(phone):
                    st.error(tr("err_phone_invalid"))
                elif not name.strip():
                    st.error("Please enter your name.")
                elif len(password.strip()) < 4:
                    st.error(tr("err_wrong_pw"))
                elif role_choice == "worker" and (not cnic_number or not cnic_number.strip()):
                    st.error(tr("err_cnic_missing"))
                elif role_choice == "worker" and cnic_expiry <= date.today():
                    st.error(tr("err_cnic_expired"))
                elif role_choice == "worker" and (cnic_front_file is None or cnic_back_file is None or selfie_file is None):
                    st.error(tr("err_files_missing"))
                else:
                    cnic_front_url = cnic_back_url = selfie_url = None
                    if role_choice == "worker":
                        with st.spinner(tr("uploading_kyc")):
                            cnic_front_url = upload_kyc_file(cnic_front_file, phone.strip(), "cnic_front")
                            cnic_back_url = upload_kyc_file(cnic_back_file, phone.strip(), "cnic_back")
                            selfie_url = upload_kyc_file(selfie_file, phone.strip(), "selfie")

                    ok, reason = register_user(
                        phone.strip(), password, role=role_choice, name=name.strip(), service_type=s_type,
                        cnic_number=cnic_number.strip() if cnic_number else None,
                        cnic_expiry=cnic_expiry if role_choice == "worker" else None,
                        cnic_front_url=cnic_front_url, cnic_back_url=cnic_back_url, selfie_url=selfie_url,
                    )
                    if ok:
                        st.success(tr("reg_success"))
                        st.session_state.auth_mode = "login"
                        st.rerun()
                    elif reason == "cnic_exists":
                        st.error(tr("err_cnic_exists"))
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

    if st.session_state.user_role == "worker":
        st.markdown(
            f"<div style='text-align:center; font-weight:700; color:#E7752F; margin-bottom:6px;'>{tr('role_badge_worker')}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div style='background:linear-gradient(135deg,#F0E9D2 0%,#FCFBE8 100%);
                        border:1.5px solid #E7752F; border-radius:14px; padding:10px 16px;
                        text-align:center; font-weight:700; font-size:14px; color:#063260;
                        margin-bottom:12px;'>
                {get_time_greeting()} — {st.session_state.user_name}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.subheader(tr("worker_dashboard"))

        tab_req, tab_jobs = st.tabs([tr("tab_requests"), tr("tab_active")])

        with tab_req:
            reqs = get_worker_requests(st.session_state.user_phone)
            if not reqs:
                st.info("No new requests right now. Pull to refresh / reopen the app to check again.")
            for r in reqs:
                warranty_tag = " 🛡️" if r.get("is_warranty") else ""
                with st.container(border=True):
                    st.markdown(f"**{r['service']}{warranty_tag}**")
                    st.write(f"📍 {r['address']}")
                    if r.get("issue_desc"):
                        st.write(f"📝 {r['issue_desc']}")
                    st.write(f"💰 Rs. {r['visit_charge']}" + (" (FREE — Warranty)" if r.get("is_warranty") else ""))
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ " + tr("accept"), use_container_width=True, type="primary", key=f"acc_{r['id']}"):
                            accept_booking(r["id"], st.session_state.user_name)
                            st.rerun()
                    with c2:
                        if st.button("❌ " + tr("decline"), use_container_width=True, key=f"dec_{r['id']}"):
                            decline_and_reassign(r["id"], st.session_state.user_phone, r["service_key"], r.get("declined_workers", ""))
                            st.rerun()

        with tab_jobs:
            jobs = get_worker_jobs(st.session_state.user_phone)
            total_earn = sum([(j.get("final_amount") or 0) for j in jobs if j["status"] == "Completed"])
            st.markdown(
                f"""
                <div style='background:#FCFBE8; border:2px solid #F0E9D2; border-radius:14px; padding:12px 16px; margin-bottom:12px; text-align:center;'>
                    <div style='font-size:14px; color:#5A4A2A;'>{tr('total_earnings')}</div>
                    <div style='font-size:24px; font-weight:800; color:#E7752F;'>Rs. {total_earn}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not jobs:
                st.info("No jobs yet.")
            for r in jobs:
                warranty_tag = " 🛡️" if r.get("is_warranty") else ""
                with st.expander(f"🛠️ {r['service']}{warranty_tag} — {r['address']} ({r['status']})"):
                    st.write(f"**Customer Phone:** {r['customer_phone']}")
                    st.write(f"**Payment Method:** {r['payment_method']}")
                    st.write(f"**Visiting Charges:** Rs. {r['visit_charge']}")
                    if r.get("issue_desc"):
                        st.write(f"**Issue:** {r['issue_desc']}")
                    st.write(f"**Date:** {r['created_at']}")

                    if r["status"] == "Pending":
                        job_notes = st.text_area(tr("job_notes_label"), key=f"notes_{r['id']}")
                        default_amt = 0.0 if r.get("is_warranty") else float(r.get("visit_charge") or 500)
                        final_amt = st.number_input(tr("final_amount_label"), min_value=0.0, value=default_amt, step=100.0, key=f"amt_{r['id']}")
                        if st.button(tr("complete_job"), use_container_width=True, type="primary", key=f"comp_{r['id']}"):
                            complete_booking(r["id"], final_amt, job_notes)
                            st.success(f"Job completed! Rs. {final_amt} recorded.")
                            st.rerun()
                    else:
                        st.write(f"**Final Bill:** Rs. {r.get('final_amount') or 0}")
                        if r.get("job_notes"):
                            st.write(f"**Notes:** {r['job_notes']}")
                        tu = parse_ts(r.get("ticket_open_until"))
                        if tu and tu > now_utc():
                            st.caption(tr("ticket_valid_till").format(date=tu.strftime("%d %b, %I:%M %p")))

        st.write("")
        if st.button(tr("logout"), use_container_width=True, key="worker_logout_btn"):
            do_logout()
            st.rerun()
        return

    # Customer Home
    st.markdown(
        f"<div style='text-align:center; font-weight:700; color:#E7752F; margin-bottom:6px;'>{tr('role_badge_customer')}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div style='background:linear-gradient(135deg,#F0E9D2 0%,#FCFBE8 100%);
                    border:1.5px solid #E7752F; border-radius:14px; padding:10px 16px;
                    text-align:center; font-weight:700; font-size:14px; color:#063260;
                    margin-bottom:12px;'>
            {get_time_greeting()} — {st.session_state.user_name}
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
    if st.button(tr("history_title"), use_container_width=True, key="home_history_btn"):
        st.session_state.page = "history"
        st.rerun()

    st.write("")
    if st.button(tr("logout"), use_container_width=True, key="customer_logout_btn"):
        do_logout()
        st.rerun()


def page_category():
    app_title()
    st.write("")
    if st.button("⬅ " + tr("back"), key="cat_back_btn"):
        st.session_state.page = "home"
        st.rerun()

    st.subheader(tr("select_service"))
    st.write("")

    cols = st.columns(2)
    services = list(SERVICE_LABELS.keys())
    for idx, s_key in enumerate(services):
        col = cols[idx % 2]
        with col:
            icon = SERVICE_ICONS.get(s_key, "🛠️")
            label = SERVICE_LABELS[s_key]
            if st.button(f"{icon} {label}", use_container_width=True, key=f"serv_btn_{s_key}"):
                st.session_state.category = s_key
                st.session_state.page = "booking"
                st.rerun()


def page_booking():
    app_title()
    st.write("")
    if st.button("⬅ " + tr("back"), key="booking_back_btn"):
        st.session_state.page = "category"
        st.session_state.warranty_claim = None
        st.rerun()

    s_key = st.session_state.category or "plumber"
    s_icon = SERVICE_ICONS.get(s_key, "🛠️")
    s_name = SERVICE_LABELS.get(s_key, "Service")

    st.subheader(f"{s_icon} {s_name}")

    claim = st.session_state.warranty_claim
    is_warranty = bool(claim and claim.get("service_key") == s_key)

    if is_warranty:
        st.warning(tr("warranty_active_note"))
        charge_preview = 0
    else:
        charge_preview = compute_visit_charge(st.session_state.user_phone, s_key)

    st.markdown(tr("visit_charge_dynamic").format(amount=charge_preview))
    st.info(tr("visit_note"))
    st.success(tr("visit_warranty"))

    issue_desc = st.text_area(tr("issue_desc_label"), key="booking_issue_desc")

    st.write("---")
    st.markdown(f"**{tr('payment_method')}**")
    pay_options = ["Cash", "JazzCash", "EasyPaisa"]
    pay_format = {
        "Cash": tr("pay_cash"),
        "JazzCash": tr("pay_jazzcash"),
        "EasyPaisa": tr("pay_easypaisa"),
    }
    st.session_state.payment_method = st.radio(
        "payment_method_radio",
        options=pay_options,
        format_func=lambda o: pay_format[o],
        label_visibility="collapsed",
    )

    st.write("")

    if st.button(tr("find_handyman"), use_container_width=True, type="primary", key="action_find_handyman"):
        with st.spinner(tr("searching")):
            time.sleep(0.8)

        assigned = None
        parent_id = None
        if is_warranty:
            parent_id = claim.get("parent_id")
            pref_phone = claim.get("worker_phone")
            if pref_phone:
                sb = get_supabase()
                w = sb.table("users").select("phone,name").eq("phone", pref_phone).eq("role", "worker").execute()
                if w.data:
                    assigned = w.data[0]

        if not assigned:
            assigned = find_available_worker(s_key)

        if not assigned:
            st.error(tr("no_worker_available"))
        else:
            visit_charge = 0 if is_warranty else charge_preview
            b_id = save_booking(
                phone=st.session_state.user_phone,
                service_label=s_name,
                service_key=s_key,
                address=st.session_state.loc_address,
                payment_method=st.session_state.payment_method,
                issue_desc=issue_desc,
                assigned_worker_phone=assigned["phone"],
                visit_charge=visit_charge,
                is_warranty=is_warranty,
                parent_booking_id=parent_id,
            )
            st.session_state.current_booking_id = b_id
            st.session_state.warranty_claim = None
            st.session_state.page = "active_booking"
            st.rerun()


def page_active_booking():
    app_title()
    st.write("")

    b = get_booking(st.session_state.current_booking_id)
    if not b:
        st.error("Booking not found.")
        if st.button("⬅ " + tr("back"), key="ab_notfound_back"):
            st.session_state.page = "home"
            st.rerun()
        return

    status = b["status"]

    if status == "Requested":
        st.info(tr("waiting_worker"))
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Refresh", use_container_width=True, key="ab_refresh"):
                st.rerun()
        with c2:
            if st.button(tr("cancel_request"), use_container_width=True, key="ab_cancel"):
                cancel_booking(b["id"])
                st.session_state.current_booking_id = None
                st.session_state.page = "home"
                st.rerun()
        return

    if status == "Unassigned":
        st.error(tr("no_worker_available"))
        if st.button(tr("retry"), use_container_width=True, key="ab_retry"):
            cancel_booking(b["id"])
            st.session_state.current_booking_id = None
            st.session_state.page = "booking"
            st.rerun()
        return

    if status in ("Completed", "Cancelled"):
        st.success("This job has finished. Check your booking history.")
        if st.button(tr("history_title"), use_container_width=True, key="ab_to_history"):
            st.session_state.current_booking_id = None
            st.session_state.page = "history"
            st.rerun()
        return

    # status == Pending -> worker accepted, show tracking screen
    if st.session_state.tracked_booking_id != b["id"]:
        st.session_state.worker_step = 0
        st.session_state.tracked_booking_id = b["id"]

    w_name = b.get("worker_name") or "Worker"
    s_name = b.get("service", "Service")

    st.markdown(
        f"""
        <div style='background:#FCFBE8; border:2px solid #F0E9D2; border-radius:16px; padding:14px 16px; margin-bottom:14px; text-align:center;'>
            <div style='font-size:18px; font-weight:800; color:#063260;'>{w_name}</div>
            <div style='font-size:14px; color:#E7752F; font-weight:600;'>{s_name}</div>
            <div style='font-size:13px; color:#5A4A2A; margin-top:4px;'>📍 {b['address']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    m = folium.Map(location=[BAHRIA_TOWN_KARACHI["lat"], BAHRIA_TOWN_KARACHI["lng"]], zoom_start=14, tiles="CartoDB positron")

    step = st.session_state.worker_step
    lat_offset = 0.012 - (step * 0.003) if step < 4 else 0.0
    lng_offset = 0.008 - (step * 0.002) if step < 4 else 0.0

    worker_lat = BAHRIA_TOWN_KARACHI["lat"] + lat_offset
    worker_lng = BAHRIA_TOWN_KARACHI["lng"] + lng_offset

    folium.Marker(
        [BAHRIA_TOWN_KARACHI["lat"], BAHRIA_TOWN_KARACHI["lng"]],
        popup="Customer Location",
        icon=folium.Icon(color="orange", icon="home", prefix="fa")
    ).add_to(m)

    folium.Marker(
        [worker_lat, worker_lng],
        popup=w_name,
        icon=folium.Icon(color="blue", icon="wrench", prefix="fa")
    ).add_to(m)

    st_folium(m, height=220, use_container_width=True)

    if step < 4:
        eta_mins = max(1, 15 - (step * 4))
        st.info(f"🚗 {tr('worker_enroute')} — {tr('eta')}: **{eta_mins} {tr('min')}**")
        if st.button(tr("simulate_move"), use_container_width=True, key="action_sim_move"):
            st.session_state.worker_step += 1
            st.rerun()
    else:
        st.success(tr("arrived"))

    st.write("")
    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button(tr("call"), use_container_width=True, key="action_call_btn"):
            st.session_state.page = "call_screen"
            st.rerun()
    with bc2:
        if st.button(tr("message"), use_container_width=True, key="action_chat_btn"):
            st.session_state.page = "chat_screen"
            st.rerun()

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔄 Refresh Status", use_container_width=True, key="ab_pending_refresh"):
            st.rerun()
    with c2:
        if st.button("⬅ " + tr("back"), use_container_width=True, key="active_to_home"):
            st.session_state.page = "home"
            st.rerun()


def page_call_screen():
    app_title()
    st.write("")
    b = get_booking(st.session_state.current_booking_id)
    w_name = (b.get("worker_name") if b else None) or "Worker"
    st.markdown(
        f"""
        <div style='text-align:center; padding:30px 0;'>
            <div style='font-size:24px; font-weight:800; color:#063260;'>{w_name}</div>
            <div style='font-size:15px; color:#E7752F; margin-top:6px;'>{tr('call_screen_title')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        if st.button(tr("mute"), use_container_width=True, key="call_mute"):
            st.toast("Call muted")
    with cc2:
        if st.button(tr("end_call"), use_container_width=True, type="primary", key="call_end"):
            st.session_state.page = "active_booking"
            st.rerun()


def page_chat_screen():
    app_title()
    b = get_booking(st.session_state.current_booking_id)
    w_name = (b.get("worker_name") if b else None) or "Worker"
    st.markdown(f"**💬 {tr('chat_title')} {w_name}**")
    st.write("---")

    chat_container = st.container(height=260)
    with chat_container:
        if not st.session_state.chat_messages:
            lang = st.session_state.lang or "en"
            intro = AUTO_RESPONSES.get(lang, AUTO_RESPONSES["en"])[0]
            st.session_state.chat_messages.append({"sender": "worker", "text": intro})

        for msg in st.session_state.chat_messages:
            if msg["sender"] == "user":
                st.markdown(f"<div style='text-align:right; margin:6px 0;'><span style='background:#E7752F; color:white; padding:8px 12px; border-radius:12px; font-size:14px;'>{msg['text']}</span></div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='text-align:left; margin:6px 0;'><span style='background:#F0E9D2; color:#063260; padding:8px 12px; border-radius:12px; font-size:14px;'>{msg['text']}</span></div>", unsafe_allow_html=True)

    user_msg = st.chat_input(tr("type_message"))
    if user_msg:
        st.session_state.chat_messages.append({"sender": "user", "text": user_msg})
        lang = st.session_state.lang or "en"
        bot_reply = random.choice(AUTO_RESPONSES.get(lang, AUTO_RESPONSES["en"]))
        st.session_state.chat_messages.append({"sender": "worker", "text": bot_reply})
        st.rerun()

    st.write("")
    if st.button("⬅ " + tr("back"), use_container_width=True, key="chat_back"):
        st.session_state.page = "active_booking"
        st.rerun()


def page_history():
    app_title()
    st.write("")
    if st.button("⬅ " + tr("back"), key="history_back"):
        st.session_state.page = "home"
        st.rerun()

    st.subheader(tr("history_title"))
    bookings = get_user_bookings(st.session_state.user_phone)

    if not bookings:
        st.info("No bookings found in history.")
        return

    for b in bookings:
        warranty_tag = " 🛡️" if b.get("is_warranty") else ""
        with st.expander(f"🛠️ {b['service']}{warranty_tag} — {b['status']} ({str(b['created_at'])[:10]})"):
            st.write(f"**Worker:** {b.get('worker_name') or 'Not yet assigned'}")
            st.write(f"**Address:** {b['address']}")
            st.write(f"**Payment Method:** {b['payment_method']}")
            if b.get("issue_desc"):
                st.write(f"**Issue:** {b['issue_desc']}")

            if b["status"] == "Completed":
                st.write(f"**Total Bill Amount:** Rs. {b.get('final_amount') or 0}")
                if b.get("job_notes"):
                    st.write(f"**Job Notes:** {b['job_notes']}")

                tu = parse_ts(b.get("ticket_open_until"))
                if tu and tu > now_utc():
                    st.caption(tr("ticket_valid_till").format(date=tu.strftime("%d %b, %I:%M %p")))
                    if st.button(tr("report_issue"), key=f"report_{b['id']}"):
                        st.session_state.category = b.get("service_key")
                        st.session_state.warranty_claim = {
                            "parent_id": b["id"],
                            "worker_phone": b.get("assigned_worker_phone"),
                            "service_key": b.get("service_key"),
                        }
                        st.session_state.page = "booking"
                        st.rerun()

                if b.get("rating"):
                    st.success(f"Rated: {'⭐' * b['rating']} — '{b.get('review','')}'")
                else:
                    st.write(f"**{tr('rate_worker')}**")
                    stars = st.slider("Rating", 1, 5, 5, key=f"rate_stars_{b['id']}")
                    rev_text = st.text_input("Review comment", placeholder="Great service!", key=f"rate_review_{b['id']}")
                    if st.button(tr("submit_rating"), key=f"submit_rate_{b['id']}"):
                        update_booking_rating(b["id"], stars, rev_text)
                        st.success("Thank you for your feedback!")
                        st.rerun()

# ---------------------------------------------------------------------------
# ROUTER
# ---------------------------------------------------------------------------
def main():
    page = st.session_state.page
    if not st.session_state.logged_in or page == "login":
        page_login()
    elif page == "home":
        page_home()
    elif page == "category":
        page_category()
    elif page == "booking":
        page_booking()
    elif page == "active_booking":
        page_active_booking()
    elif page == "call_screen":
        page_call_screen()
    elif page == "chat_screen":
        page_chat_screen()
    elif page == "history":
        page_history()
    else:
        page_home()

if __name__ == "__main__":
    main()
