# Handyman | کارگر — Demo App

Ye ek **demo/prototype** hai jo Python (Streamlit) mein bana hai. Isay app store
pay publish karnay se pehle, iska maqsad flow aur design ko test/dikhana hai.

## Kya kya hai is demo mein
- 🌐 Language chooser: **English / اردو / سنڌي** (tick karke choose karain)
- 🔐 Login screen (demo — koi bhi username/password chal jaega)
- 🏠 Home screen: **Handyman** (upar) / **کارگر** (neechay)
- 🛠️ **Maintenance & Repair** button → sub-services:
  - Plumber, Electrician, AC Technician, Solar, Gardener, Cleaning
- 📍 Location: filhal fix — **Bahria Town, Karachi** (map ke saath)
- 🔔 Booking flow (ride-app jaisa):
  1. "Find Handyman" dabao
  2. System nearby worker dhoondta hai (simulate)
  3. Notification aati hai → **Accept / Decline**
  4. Accept karne par worker ki location map par automatic (simulate) move hoti hai
- 📞 Audio Call button (UI/mock — asal call abhi connect nahi hai)
- 💬 Chat/Messenger option (UI/mock — asal messaging backend abhi nahi hai)

## Kaise chalayen (run karein)

1. Python 3.9+ install hona chahiye.
2. Terminal mein is folder ke andar jaen:
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```
3. Browser mein automatically khul jaega (ya link terminal mein milega, usually
   `http://localhost:8501`).

## Aage kya add hoga (production ke liye)
- Real user authentication (Firebase Auth / Django / Supabase)
- Real-time GPS location (device se, Google Maps / Mapbox API)
- Real audio calling (Agora / Twilio / WebRTC)
- Real chat backend (Firebase Realtime DB / WebSocket)
- Real worker-matching backend + push notifications (Firebase Cloud Messaging)
- Payments integration (JazzCash / EasyPaisa / card)

## Note on Sindhi/Urdu translations
Sindhi aur Urdu translations best-effort demo strings hain. Production se pehle
kisi native speaker se review karwa lein.
