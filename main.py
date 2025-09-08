# split_bill_all_in_one.py
# ------------------------------------------------------------
# Logic คำนวณ + Tkinter UI + Firebase (Auth + RTDB Streaming/Polling)
# - Login/Signup แยกหน้าต่าง (สมัครพร้อมตั้ง username)
# - เก็บโปรไฟล์ /users/{uid}, mapping /usernames/{username} -> uid
# - People, payer, participants ใช้ UID 100% (แสดงเป็น username บน UI)
# - จัดการสมาชิกห้อง: เพิ่มด้วย UID หรือค้นจาก username
# - แชร์บิลแบบเรียลไทม์ (SSE) + โพลลิ่งสำรอง, กันลูปสะท้อน, auto refresh token
# - ตาราง Tree (พ่อ/ลูก) + sort หัวคอลัมน์ + zebra
# ------------------------------------------------------------

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Tuple
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import json, threading, time, csv
import requests

try:
    from sseclient import SSEClient  # type: ignore
except Exception:
    SSEClient = None

# ===== Firebase Config (แก้ให้ตรงโปรเจกต์คุณ) =====
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"

# ===================== Core Logic (Bill Engine) =====================
@dataclass
class Person:
    uid: str

@dataclass
class Item:
    name: str
    price: float
    payer: str                 # UID ของผู้จ่ายก่อน
    participants: List[str]    # รายชื่อ UID ของผู้ร่วมกิน
    weights: Optional[Dict[str, float]] = None  # key = UID

@dataclass
class Bill:
    people: Dict[str, Person] = field(default_factory=dict)  # key = UID
    items: List[Item] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    # ----- People (UID) -----
    def add_person(self, uid: str):
        uid = uid.strip()
        if not uid:
            raise ValueError("UID ว่างไม่ได้")
        if uid in self.people:
            return
        self.people[uid] = Person(uid=uid)

    def remove_person(self, uid: str):
        if uid in self.people:
            for it in self.items:
                if it.payer == uid or uid in it.participants:
                    raise ValueError("ลบไม่ได้: มีรายการที่เกี่ยวข้องกับคนนี้")
            del self.people[uid]

    # ----- Items -----
    def add_item(self, item: Item):
        if item.payer not in self.people:
            raise ValueError(f"ไม่พบผู้จ่าย (UID): {item.payer}")
        for u in item.participants:
            if u not in self.people:
                raise ValueError(f"ไม่พบผู้ร่วมกิน (UID): {u}")
        if item.price <= 0:
            raise ValueError("ราคา item ต้องมากกว่า 0")
        if item.weights:
            w = {k: float(v) for k, v in item.weights.items() if k in item.participants}
            if not w:
                raise ValueError("weights ว่าง หรือไม่ตรงกับผู้ร่วมกิน")
            if any(v <= 0 for v in w.values()):
                raise ValueError("ทุก weight ต้อง > 0")
            item.weights = w
        self.items.append(item)

    def remove_item_at(self, idx: int):
        if 0 <= idx < len(self.items):
            self.items.pop(idx)

    # ----- Calc -----
    def _totals(self):
        subtotal = sum(i.price for i in self.items)
        service_fee = subtotal * (self.service_pct / 100.0)
        vat_fee = (subtotal + service_fee) * (self.vat_pct / 100.0)
        total = subtotal + service_fee + vat_fee + self.tip
        return subtotal, service_fee, vat_fee, total

    def summary_costs(self) -> Dict[str, float]:
        if not self.items:
            return {uid: 0.0 for uid in self.people}
        subtotal, _, _, total = self._totals()
        if subtotal == 0:
            return {uid: 0.0 for uid in self.people}
        raw = defaultdict(float)
        for it in self.items:
            if it.weights:
                tw = sum(it.weights[u] for u in it.participants)
                for u in it.participants:
                    raw[u] += it.price * (it.weights[u] / tw)
            else:
                each = it.price / len(it.participants)
                for u in it.participants:
                    raw[u] += each
        scale = total / subtotal
        return {u: raw.get(u, 0.0) * scale for u in self.people}

    def paid_map(self) -> Dict[str, float]:
        paid = defaultdict(float)
        for it in self.items:
            paid[it.payer] += it.price
        subtotal, service_fee, vat_fee, _ = self._totals()
        extra = service_fee + vat_fee + self.tip
        if subtotal > 0 and extra > 0:
            for u in paid:
                paid[u] += extra * (paid[u] / subtotal)
        for u in self.people:
            paid[u] = paid.get(u, 0.0)
        return dict(paid)

    def net_balance(self) -> Dict[str, float]:
        should = self.summary_costs()
        paid = self.paid_map()
        net = {u: round(paid.get(u, 0.0) - should.get(u, 0.0), 2) for u in self.people}
        drift = round(sum(net.values()), 2)
        if drift != 0 and net:
            first = next(iter(net))
            net[first] = round(net[first] - drift, 2)
        return net

    def settle_transactions(self) -> List[Dict[str, float]]:
        net = self.net_balance()
        cr = [[u, a] for u, a in net.items() if a > 0]
        db = [[u, -a] for u, a in net.items() if a < 0]
        cr.sort(key=lambda x: x[1], reverse=True)
        db.sort(key=lambda x: x[1], reverse=True)
        i = j = 0
        txs = []
        while i < len(db) and j < len(cr):
            d, da = db[i]
            c, ca = cr[j]
            pay = round(min(da, ca), 2)
            if pay > 0:
                txs.append({"from": d, "to": c, "amount": pay})
                da = round(da - pay, 2)
                ca = round(ca - pay, 2)
            db[i][1] = da
            cr[j][1] = ca
            if da == 0: i += 1
            if ca == 0: j += 1
        return txs

    # ----- Serialize (เก็บ UID) -----
    def to_dict(self):
        return {
            "people": list(self.people.keys()),  # list ของ UID
            "items": [
                {
                    "name": it.name,
                    "price": it.price,
                    "payer": it.payer,                      # UID
                    "participants": it.participants,        # list UID
                    "weights": it.weights,                  # {UID: weight}
                } for it in self.items
            ],
            "service_pct": self.service_pct,
            "vat_pct": self.vat_pct,
            "tip": self.tip,
            "updatedAt": time.time(),
        }

    @classmethod
    def from_dict(cls, data: dict):
        b = cls()
        for uid in data.get("people", []):
            b.add_person(uid)
        b.service_pct = float(data.get("service_pct", 0))
        b.vat_pct = float(data.get("vat_pct", 0))
        b.tip = float(data.get("tip", 0))
        for it in data.get("items", []):
            b.add_item(Item(
                name=it["name"], price=float(it["price"]),
                payer=it["payer"], participants=it["participants"],
                weights=it.get("weights")
            ))
        return b

# ===================== Firebase REST + Streaming =====================
class FirebaseRTClient:
    def __init__(self, api_key: str, rtdb_url: str):
        self.api_key = api_key
        self.rtdb_url = rtdb_url.rstrip("/")
        self.id_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.local_uid: Optional[str] = None
        self._stop_stream = False

    def _post_json(self, url: str, payload: dict):
        res = requests.post(url, json=payload)
        try:
            res.raise_for_status()
            return res.json()
        except requests.HTTPError as e:
            try:
                msg = res.json().get("error", {}).get("message", "")
            except Exception:
                msg = res.text
            raise RuntimeError(msg or str(e)) from None

    # ----- Auth -----
    def sign_in_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        data = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.local_uid = data["localId"]
        return data

    def sign_up_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        data = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.local_uid = data["localId"]
        return data

    def update_display_name(self, display_name: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={self.api_key}"
        data = self._post_json(url, {"idToken": self.id_token, "displayName": display_name, "returnSecureToken": True})
        self.id_token = data.get("idToken", self.id_token)
        return data

    # ----- Token refresh -----
    def refresh_id_token(self):
        if not self.refresh_token:
            return
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"
        res = requests.post(url, data={"grant_type": "refresh_token", "refresh_token": self.refresh_token})
        res.raise_for_status()
        d = res.json()
        self.id_token = d["id_token"]
        self.refresh_token = d["refresh_token"]
        self.local_uid = d["user_id"]

    def start_auto_refresh(self, every_sec=50*60):
        def loop():
            while True:
                time.sleep(every_sec)
                try:
                    self.refresh_id_token()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    # ----- RTDB REST -----
    def _auth_params(self):
        if not self.id_token:
            raise RuntimeError("Not authenticated")
        return {"auth": self.id_token}

    def get(self, path: str):
        url = f"{self.rtdb_url}/{path}.json"
        res = requests.get(url, params=self._auth_params(), timeout=30)
        res.raise_for_status()
        return res.json()

    def put(self, path: str, obj):
        url = f"{self.rtdb_url}/{path}.json"
        res = requests.put(url, params=self._auth_params(), json=obj, timeout=30)
        res.raise_for_status()
        return res.json()

    def patch(self, path: str, obj):
        url = f"{self.rtdb_url}/{path}.json"
        res = requests.patch(url, params=self._auth_params(), json=obj, timeout=30)
        res.raise_for_status()
        return res.json()

    # ----- Profile & Username -----
    def get_username(self, uid: str) -> Optional[str]:
        prof = self.get(f"users/{uid}") or {}
        return (prof or {}).get("username")

    def lookup_uid_by_username(self, username: str) -> Optional[str]:
        return self.get(f"usernames/{username}")

    def claim_username(self, uid: str, email: str, username: str):
        username = username.strip()
        if not username:
            raise RuntimeError("ต้องระบุ username")
        taken = self.get(f"usernames/{username}")
        if taken:
            raise RuntimeError("username นี้ถูกใช้แล้ว")
        self.put(f"usernames/{username}", uid)
        self.patch(f"users/{uid}", {"username": username, "email": email, "createdAt": int(time.time())})

    # ----- Room members -----
    def add_member_to_room(self, room_id: str, uid: str):
        uname = self.get_username(uid) or uid
        return self.patch(f"rooms/{room_id}/members/{uid}", {"username": uname, "addedAt": int(time.time())})

    def list_members(self, room_id: str) -> List[Tuple[str, str]]:
        members = self.get(f"rooms/{room_id}/members") or {}
        out = []
        for uid, meta in (members or {}).items():
            uname = (meta or {}).get("username") or self.get_username(uid) or uid
            out.append((uid, uname))
        return out

    # ----- Streaming (SSE or Polling) -----
    def stream(self, path: str, on_event: Callable[[dict], None]):
        if not self.id_token:
            raise RuntimeError("Not authenticated")
        url = f"{self.rtdb_url}/{path}.json"

        def run_sse():
            while True:
                try:
                    messages = SSEClient(url, params={"auth": self.id_token})
                    for msg in messages:
                        if msg.event in ("put", "patch"):
                            try:
                                data = json.loads(msg.data)
                                on_event(data)
                            except Exception:
                                pass
                except Exception:
                    try: self.refresh_id_token()
                    except: pass
                    time.sleep(2)

        def run_poll():
            last = None
            while True:
                try:
                    data = requests.get(url, params={"auth": self.id_token}, timeout=30).json()
                    if data is not None:
                        ua = data.get("updatedAt") if isinstance(data, dict) else None
                        if last != ua:
                            on_event({"path": "/", "data": data})
                            last = ua
                except Exception:
                    try: self.refresh_id_token()
                    except: pass
                time.sleep(3)

        threading.Thread(target=(run_sse if SSEClient else run_poll), daemon=True).start()

# ===================== Login / Signup Window =====================
class LoginWindow(tk.Toplevel):
    def __init__(self, master, on_success: Callable[[FirebaseRTClient, str, str, str], None]):
        super().__init__(master)
        self.title("เข้าสู่ระบบ / สมัครผู้ใช้")
        self.resizable(False, False)
        self.on_success = on_success

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        self.var_mode = tk.StringVar(value="login")

        row = 0
        ttk.Label(frm, text="โหมด", font=("Segoe UI", 10, "bold")).grid(row=row, column=0, sticky="w")
        ttk.Radiobutton(frm, text="เข้าสู่ระบบ", variable=self.var_mode, value="login",
                        command=self._toggle_signup).grid(row=row, column=1, sticky="w")
        ttk.Radiobutton(frm, text="สมัครผู้ใช้ใหม่", variable=self.var_mode, value="signup",
                        command=self._toggle_signup).grid(row=row, column=2, sticky="w")
        row += 1

        ttk.Label(frm, text="อีเมล").grid(row=row, column=0, sticky="e", pady=4)
        self.e_email = ttk.Entry(frm, width=28)
        self.e_email.grid(row=row, column=1, columnspan=2, sticky="we", pady=4); row += 1

        ttk.Label(frm, text="รหัสผ่าน").grid(row=row, column=0, sticky="e", pady=4)
        self.e_pwd = ttk.Entry(frm, show="*", width=28)
        self.e_pwd.grid(row=row, column=1, columnspan=2, sticky="we", pady=4); row += 1

        ttk.Label(frm, text="username (สำหรับสมัคร)").grid(row=row, column=0, sticky="e", pady=4)
        self.e_uname = ttk.Entry(frm, width=28)
        self.e_uname.grid(row=row, column=1, columnspan=2, sticky="we", pady=4); row += 1

        ttk.Button(frm, text="ยืนยัน", command=self._submit).grid(row=row, column=1, sticky="we", pady=8)
        ttk.Button(frm, text="ยกเลิก", command=self.destroy).grid(row=row, column=2, sticky="we", pady=8)

        for c in range(3):
            frm.columnconfigure(c, weight=1)

        self._toggle_signup()

    def _toggle_signup(self):
        signup = self.var_mode.get() == "signup"
        self.e_uname.configure(state=("normal" if signup else "disabled"))

    def _submit(self):
        email = (self.e_email.get() or "").strip()
        pwd   = (self.e_pwd.get() or "").strip()
        uname = (self.e_uname.get() or "").strip()

        if not email or not pwd:
            messagebox.showwarning("แจ้ง", "กรอกอีเมลและรหัสผ่าน")
            return

        fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        try:
            if self.var_mode.get() == "signup":
                if not uname:
                    messagebox.showwarning("แจ้ง", "กรอก username")
                    return
                fb.sign_up_email(email, pwd)
                fb.claim_username(fb.local_uid, email, uname)
                try: fb.update_display_name(uname)
                except: pass
            else:
                fb.sign_in_email(email, pwd)
                uname = fb.get_username(fb.local_uid) or email.split("@")[0]
        except Exception as e:
            msg = str(e)
            if "EMAIL_NOT_FOUND" in msg:
                thai = "ไม่พบบัญชีนี้ เลือกโหมด 'สมัครผู้ใช้ใหม่'"
            elif "INVALID_PASSWORD" in msg:
                thai = "รหัสผ่านไม่ถูกต้อง"
            elif "WEAK_PASSWORD" in msg:
                thai = "รหัสผ่านต้องมีอย่างน้อย 6 ตัว"
            elif "OPERATION_NOT_ALLOWED" in msg:
                thai = "ยังไม่เปิด Email/Password ใน Firebase Console"
            elif "INVALID_EMAIL" in msg:
                thai = "รูปแบบอีเมลไม่ถูกต้อง"
            else:
                thai = msg
            messagebox.showerror("Firebase", thai)
            return

        self.on_success(fb, email, fb.local_uid, uname)
        self.destroy()

# ===================== Member Manager =====================
class MemberManager(tk.Toplevel):
    def __init__(self, master, fb: FirebaseRTClient, room_id: str):
        super().__init__(master)
        self.title("สมาชิกห้อง")
        self.resizable(False, False)
        self.fb = fb
        self.room_id = room_id

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=f"Room: {room_id}", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0,6))

        self.listbox = tk.Listbox(frm, width=54, height=10)
        self.listbox.grid(row=1, column=0, columnspan=3, sticky="we")

        ttk.Label(frm, text="เพิ่มโดย UID").grid(row=2, column=0, sticky="e", pady=4)
        self.e_uid = ttk.Entry(frm, width=28)
        self.e_uid.grid(row=2, column=1, sticky="we", pady=4)
        ttk.Button(frm, text="เพิ่ม", command=self.add_by_uid).grid(row=2, column=2, sticky="we", padx=4)

        ttk.Label(frm, text="เพิ่มโดย username").grid(row=3, column=0, sticky="e", pady=4)
        self.e_uname = ttk.Entry(frm, width=28)
        self.e_uname.grid(row=3, column=1, sticky="we", pady=4)
        ttk.Button(frm, text="ค้นหาและเพิ่ม", command=self.add_by_username).grid(row=3, column=2, sticky="we", padx=4)

        ttk.Button(frm, text="รีเฟรชรายการ", command=self.refresh).grid(row=4, column=2, sticky="we", pady=(6,0))

        for c in range(3):
            frm.columnconfigure(c, weight=1)

        self.refresh()

    def refresh(self):
        self.listbox.delete(0, tk.END)
        try:
            items = self.fb.list_members(self.room_id)
            for uid, uname in items:
                self.listbox.insert(tk.END, f"{uname}  ({uid})")
        except Exception as e:
            messagebox.showerror("Firebase", f"โหลดสมาชิกไม่สำเร็จ: {e}")

    def add_by_uid(self):
        uid = (self.e_uid.get() or "").strip()
        if not uid:
            return
        try:
            self.fb.add_member_to_room(self.room_id, uid)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Firebase", f"เพิ่มไม่สำเร็จ: {e}")

    def add_by_username(self):
        uname = (self.e_uname.get() or "").strip()
        if not uname:
            return
        try:
            uid = self.fb.lookup_uid_by_username(uname)
            if not uid:
                messagebox.showwarning("แจ้ง", "ไม่พบ username นี้")
                return
            self.fb.add_member_to_room(self.room_id, uid)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Firebase", f"เพิ่มไม่สำเร็จ: {e}")

# ===================== Tkinter UI (Main App) =====================
class BillSplitApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("หารค่าอาหารกับเพื่อน • Tkinter + Firebase (UID-based)")
        self.master.geometry("1140x700")
        self.pack(fill=tk.BOTH, expand=True)

        self.bill = Bill()
        self.fb: Optional[FirebaseRTClient] = None
        self.room_id: Optional[str] = None

        # cache แสดงผล
        self.uid_to_name: Dict[str, str] = {}  # UID -> username
        self._local_change = False
        self._last_remote_ua = None

        self._build_layout()

    # ---------- UI Layout ----------
    def _build_layout(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Left
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)

        # Right
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # --- Cloud ---
        ttk.Label(left, text="Cloud Sync (Firebase)", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(left, text="เชื่อม Firebase (Login/Signup)", command=self.connect_firebase).grid(row=1, column=0, sticky="we")
        ttk.Button(left, text="จัดการสมาชิกห้อง", command=self.open_members).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Button(left, text="ซิงค์คนจากห้อง → People", command=self.sync_people_from_room).grid(row=1, column=2, sticky="we")
        self.cloud_lbl = ttk.Label(left, text="สถานะ: offline")
        self.cloud_lbl.grid(row=2, column=0, columnspan=3, sticky="w", padx=2, pady=(2,8))

        # --- People ---
        ttk.Label(left, text="เพิ่มเพื่อนด้วย UID/username", font=("Segoe UI", 11, "bold")).grid(row=3, column=0, columnspan=3, sticky="w")
        self.person_entry = ttk.Entry(left, width=24)
        self.person_entry.grid(row=4, column=0, sticky="w")
        ttk.Button(left, text="เพิ่ม", command=self.add_person).grid(row=4, column=1, padx=5)
        ttk.Button(left, text="ลบที่เลือก", command=self.remove_person).grid(row=4, column=2)
        self.people_list = tk.Listbox(left, height=8, exportselection=False)
        self.people_list.grid(row=5, column=0, columnspan=3, sticky="we", pady=5)

        # --- Config ---
        ttk.Label(left, text="ตั้งค่า Service/VAT/Tip", font=("Segoe UI", 11, "bold")).grid(row=6, column=0, columnspan=3, sticky="w", pady=(8,0))
        frm_cfg = ttk.Frame(left); frm_cfg.grid(row=7, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_cfg, text="Service %").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_cfg, text="VAT %").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_cfg, text="Tip (บาท)").grid(row=2, column=0, sticky="w")
        self.service_var = tk.StringVar(value="0")
        self.vat_var = tk.StringVar(value="0")
        self.tip_var = tk.StringVar(value="0")
        ttk.Entry(frm_cfg, textvariable=self.service_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.vat_var, width=10).grid(row=1, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.tip_var, width=10).grid(row=2, column=1, padx=5)
        ttk.Button(left, text="อัปเดตค่า Config", command=self.update_config).grid(row=8, column=0, columnspan=3, sticky="we", pady=5)

        # --- Item Form ---
        ttk.Label(left, text="เพิ่มรายการอาหาร", font=("Segoe UI", 11, "bold")).grid(row=9, column=0, columnspan=3, sticky="w", pady=(10,0))
        frm_item = ttk.Frame(left); frm_item.grid(row=10, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_item, text="ชื่อเมนู").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_item, text="ราคา (บาท)").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้จ่ายก่อน").grid(row=2, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้ร่วมกิน").grid(row=3, column=0, sticky="nw")
        self.item_name = ttk.Entry(frm_item, width=22)
        self.item_price = ttk.Entry(frm_item, width=22)
        self.payer_combo = ttk.Combobox(frm_item, values=[], state="readonly", width=22)
        self.participants_list = tk.Listbox(frm_item, selectmode=tk.MULTIPLE, height=6, exportselection=False)
        self.all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_item, text="ทุกคน", variable=self.all_var, command=self.toggle_all_participants).grid(row=4, column=1, sticky="w")
        self.item_name.grid(row=0, column=1, sticky="we", pady=1)
        self.item_price.grid(row=1, column=1, sticky="we", pady=1)
        self.payer_combo.grid(row=2, column=1, sticky="we", pady=1)
        self.participants_list.grid(row=3, column=1, sticky="we", pady=1)
        self.use_weights = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_item, text="หารไม่เท่ากัน (weights)", variable=self.use_weights).grid(row=5, column=1, sticky="w", pady=(4,0))
        btns = ttk.Frame(left); btns.grid(row=11, column=0, columnspan=3, sticky="we", pady=6)
        ttk.Button(btns, text="เพิ่มรายการ", command=self.add_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="ลบรายการที่เลือก", command=self.remove_selected_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # --- Items Table ---
        ttk.Label(right, text="รายการทั้งหมด", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.table_cols = ("idx", "name", "price", "payer", "count", "participants", "mode", "per_head", "weights")
        self.table = ttk.Treeview(right, columns=self.table_cols, show="tree headings", height=14, selectmode="browse")
        self.table.column("#0", width=24, anchor="w", stretch=False); self.table.heading("#0", text="", anchor="w")
        heads = {"idx":"#", "name":"เมนู", "price":"ราคา (บาท)", "payer":"ผู้จ่าย",
                 "count":"คนร่วม", "participants":"รายชื่อผู้ร่วมกิน",
                 "mode":"โหมดหาร", "per_head":"ต่อหัว/เมนู (บาท)", "weights":"น้ำหนัก"}
        widths = {"idx":40,"name":220,"price":110,"payer":120,"count":65,"participants":320,"mode":90,"per_head":130,"weights":160}
        anchors = {"idx":"e","name":"w","price":"e","payer":"w","count":"e","participants":"w","mode":"center","per_head":"e","weights":"w"}
        for k in self.table_cols:
            self.table.heading(k, text=heads[k], command=lambda c=k: self._sort_by(c))
            self.table.column(k, width=widths[k], anchor=anchors[k], stretch=False)
        try:
            self.table.tag_configure("odd", background="#fafafa")
            self.table.tag_configure("even", background="#f2f4f7")
            self.table.tag_configure("child", foreground="#555")
        except Exception:
            pass
        self.table.grid(row=1, column=0, sticky="nsew")
        scr = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scr.set); scr.grid(row=1, column=1, sticky="ns")

        # --- Summary ---
        ttk.Label(right, text="สรุปผล", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w", pady=(10,0))
        self.output = tk.Text(right, height=12); self.output.grid(row=3, column=0, sticky="nsew")
        btn_bottom = ttk.Frame(right); btn_bottom.grid(row=4, column=0, sticky="we", pady=6)
        ttk.Button(btn_bottom, text="คำนวณ/อัปเดตสรุป", command=self.refresh_summary).pack(side=tk.LEFT)
        ttk.Button(btn_bottom, text="คัดลอกสรุป", command=self.copy_summary).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="บันทึกบิล (JSON)", command=self.save_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="โหลดบิล (JSON)", command=self.load_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="Export โอน (CSV)", command=self.export_transfers_csv).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="ล้างทั้งหมด", command=self.reset_all).pack(side=tk.LEFT, padx=6)

    # ---------- Display helpers (UID -> username label) ----------
    def _short_uid(self, uid: str) -> str:
        return uid[:6] if uid else "??????"

    def _fetch_name(self, uid: str) -> str:
        if uid in self.uid_to_name:
            return self.uid_to_name[uid]
        name = uid
        if self.fb:
            try:
                name = self.fb.get_username(uid) or uid
            except Exception:
                name = uid
        self.uid_to_name[uid] = name
        return name

    def _label(self, uid: str) -> str:
        # แสดง "username (uid6)" เพื่อกันชื่อซ้ำ
        uname = self._fetch_name(uid)
        return f"{uname} ({self._short_uid(uid)})"

    # ---------- Table helpers ----------
    def toggle_all_participants(self):
        if self.all_var.get():
            self.participants_list.select_set(0, tk.END)
        else:
            self.participants_list.select_clear(0, tk.END)

    def _compute_scale(self) -> float:
        subtotal = sum(i.price for i in self.bill.items)
        if subtotal <= 0: return 1.0
        svc = subtotal * (self.bill.service_pct / 100.0)
        vat = (subtotal + svc) * (self.bill.vat_pct / 100.0)
        total = subtotal + svc + vat + self.bill.tip
        return total / subtotal

    def _format_weights(self, it: Item) -> str:
        if not it.weights: return "-"
        return ", ".join(f"{self._label(u)}={v:g}" for u, v in it.weights.items())

    def _per_head_for_item(self, it: Item) -> float:
        scale = self._compute_scale()
        if not it.participants: return 0.0
        if it.weights:
            tw = sum(it.weights[u] for u in it.participants)
            return it.price * scale / tw
        return (it.price * scale) / len(it.participants)

    def _item_shares(self, it: Item) -> Dict[str, float]:
        scale = self._compute_scale()
        shares = {}
        if not it.participants: return shares
        if it.weights:
            tw = sum(it.weights[u] for u in it.participants)
            for u in it.participants:
                shares[u] = (it.price * scale) * (it.weights[u] / tw)
        else:
            each = (it.price * scale) / len(it.participants)
            for u in it.participants:
                shares[u] = each
        return shares

    def _add_item_to_table(self, idx0: int, it: Item):
        rowvals = (
            idx0 + 1,
            it.name,
            f"{it.price:,.2f}",
            self._label(it.payer),
            len(it.participants),
            ", ".join(self._label(u) for u in it.participants),
            "น้ำหนัก" if it.weights else "เท่ากัน",
            f"{self._per_head_for_item(it):,.2f}",
            self._format_weights(it),
        )
        tag = "odd" if (idx0 % 2 == 0) else "even"
        parent_id = self.table.insert("", tk.END, iid=f"item-{idx0}", values=rowvals, tags=(tag,))
        self.table.item(parent_id, open=True)
        shares = self._item_shares(it)
        for u in it.participants:
            cvals = ("", f"• {self._label(u)}", "", "", "", "", "", f"{shares.get(u, 0.0):,.2f}", "")
            self.table.insert(parent_id, tk.END, values=cvals, tags=("child",))

    def _rebuild_table(self):
        self.table.delete(*self.table.get_children())
        for i, it in enumerate(self.bill.items):
            self._add_item_to_table(i, it)

    def _apply_zebra(self):
        roots = self.table.get_children("")
        for i, rid in enumerate(roots):
            self.table.item(rid, tags=("odd" if (i % 2 == 0) else "even",))

    def _sort_by(self, col: str, reverse: Optional[bool] = None):
        col_index = self.table_cols.index(col)
        parents = list(self.table.get_children(""))

        def key_of(rid):
            vals = self.table.item(rid, "values")
            v = vals[col_index]
            num_cols = {"idx", "price", "count", "per_head"}
            if col in num_cols:
                try:
                    return float(str(v).replace(",", "").replace("บาท", "").strip())
                except Exception:
                    return 0.0
            return str(v).lower()

        if reverse is None:
            reverse = getattr(self, "_sort_rev_"+col, False)
        parents.sort(key=key_of, reverse=reverse)
        setattr(self, "_sort_rev_"+col, not reverse)
        for pos, rid in enumerate(parents):
            self.table.move(rid, "", pos)
        self._apply_zebra()

    # ---------- Cloud / Firebase ----------
    def connect_firebase(self):
        self.open_login()

    def open_login(self):
        def _after_login(fb: FirebaseRTClient, email: str, uid: str, username: str):
            self.fb = fb
            self.uid_to_name[uid] = username
            self.cloud_lbl.config(text=f"ล็อกอินเป็น {username} ({self._short_uid(uid)})")
            self.fb.start_auto_refresh()

            room = simpledialog.askstring("เข้าร่วมห้อง", "Room ID (เช่น classA-2025):", parent=self)
            if not room: return
            self.room_id = room.strip()
            try:
                self.fb.add_member_to_room(self.room_id, uid)
                data = self.fb.get(f"bills/{self.room_id}")
                if data:
                    self.bill = Bill.from_dict(data)
                    self._render_all_from_bill()
                    if isinstance(data, dict):
                        self._last_remote_ua = data.get("updatedAt")
            except Exception:
                pass
            self._start_stream()
        LoginWindow(self.master, _after_login)

    def _start_stream(self):
        if not (self.fb and self.room_id): return

        def on_event(_ev):
            if self._local_change: return
            try:
                full = self.fb.get(f"bills/{self.room_id}")
                if not isinstance(full, dict): return
                ua = full.get("updatedAt")
                if ua is not None and ua == self._last_remote_ua: return
                new_bill = Bill.from_dict(full)
            except Exception:
                return
            def apply():
                self._last_remote_ua = ua
                self.bill = new_bill
                self._render_all_from_bill()
            self.after(0, apply)

        try:
            self.fb.stream(f"bills/{self.room_id}", on_event)
            self.cloud_lbl.config(text=f"สถานะ: online (room {self.room_id})")
        except Exception:
            self.cloud_lbl.config(text=f"สถานะ: online (poll)")
        self.after(3000, self._keep_synced)

    def _push_bill(self):
        if not (self.fb and self.room_id): return
        try:
            self._local_change = True
            data = self.bill.to_dict()
            data["lastEditBy"] = self.fb.local_uid
            self.fb.put(f"bills/{self.room_id}", data)
            self._last_remote_ua = data["updatedAt"]
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))

    def _render_all_from_bill(self):
        # refresh label cache จากสมาชิกในห้อง (ถ้ามี)
        if self.fb and self.room_id:
            try:
                for uid, uname in self.fb.list_members(self.room_id):
                    self.uid_to_name[uid] = uname
            except Exception:
                pass

        # แสดงรายชื่อ people
        self.people_order = list(self.bill.people.keys())
        self.people_list.delete(0, tk.END)
        for uid in self.people_order:
            self.people_list.insert(tk.END, self._label(uid))

        # widgets เลือก payer/participants
        labels = [self._label(uid) for uid in self.people_order]
        self.payer_combo["values"] = labels
        self.participants_list.delete(0, tk.END)
        for lab in labels:
            self.participants_list.insert(tk.END, lab)

        # config
        self.service_var.set(str(self.bill.service_pct))
        self.vat_var.set(str(self.bill.vat_pct))
        self.tip_var.set(str(self.bill.tip))

        # ตาราง & สรุป
        self._rebuild_table()
        self.refresh_summary()

    def _keep_synced(self):
        if self.fb and self.room_id and not self._local_change:
            try:
                full = self.fb.get(f"bills/{self.room_id}")
                if isinstance(full, dict):
                    ua = full.get("updatedAt")
                    if ua is not None and ua != self._last_remote_ua:
                        self._last_remote_ua = ua
                        self.bill = Bill.from_dict(full)
                        self._render_all_from_bill()
            except Exception:
                pass
        self.after(3000, self._keep_synced)

    # ---------- Member ops ----------
    def open_members(self):
        if not (self.fb and self.room_id):
            messagebox.showinfo("แจ้ง", "กรุณาเชื่อม Firebase และเลือกห้องก่อน")
            return
        MemberManager(self.master, self.fb, self.room_id)

    def sync_people_from_room(self):
        if not (self.fb and self.room_id):
            messagebox.showinfo("แจ้ง", "กรุณาเชื่อม Firebase และเลือกห้องก่อน")
            return
        try:
            for uid, uname in self.fb.list_members(self.room_id):
                self.uid_to_name[uid] = uname
                try:
                    self.bill.add_person(uid)
                except Exception:
                    pass
            self._render_all_from_bill()
            messagebox.showinfo("สำเร็จ", "ซิงค์รายชื่อจากห้องแล้ว")
        except Exception as e:
            messagebox.showerror("Firebase", f"ซิงค์ไม่สำเร็จ: {e}")

    # ---------- Local Save/Load/Copy/Export ----------
    def copy_summary(self):
        text = self.output.get("1.0", tk.END).strip()
        self.master.clipboard_clear(); self.master.clipboard_append(text)
        messagebox.showinfo("ก็อปแล้ว", "คัดลอกสรุปไปคลิปบอร์ดเรียบร้อย")

    def save_bill_local(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.bill.to_dict(), f, ensure_ascii=False, indent=2)
        messagebox.showinfo("บันทึกแล้ว", f"บันทึกไฟล์: {path}")

    def load_bill_local(self):
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not path: return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.bill = Bill.from_dict(data)
        self._render_all_from_bill()
        self._push_bill()

    def export_transfers_csv(self):
        txs = self.bill.settle_transactions()
        if not txs:
            messagebox.showinfo("CSV", "ไม่มีรายการโอน เคลียร์หมดแล้ว"); return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not path: return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["from_uid","to_uid","amount"])
            for t in txs:
                w.writerow([t["from"], t["to"], f'{t["amount"]:.2f}'])
        messagebox.showinfo("CSV", f"ส่งออกแล้ว: {path}")

    # ---------- People / Items / Config Events ----------
    def _refresh_people_widgets(self):
        self._render_all_from_bill()

    def add_person(self):
        key = self.person_entry.get().strip()
        if not key:
            messagebox.showwarning("เตือน", "กรุณากรอก UID หรือ username")
            return
        uid = None
        # ถ้าเชื่อม Firebase ลองค้น username -> uid ก่อน
        if self.fb:
            try:
                uid = self.fb.lookup_uid_by_username(key)
            except Exception:
                uid = None
        uid = uid or key  # ถ้าไม่เจอ username ให้ถือว่าใส่ UID มาแล้ว
        try:
            self.bill.add_person(uid)
            # cache ชื่อ
            self.uid_to_name[uid] = self.fb.get_username(uid) if self.fb else self.uid_to_name.get(uid, uid)
            self.person_entry.delete(0, tk.END)
            self._render_all_from_bill()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_person(self):
        sel = self.people_list.curselection()
        if not sel:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกชื่อที่จะลบ"); return
        uid = self.people_order[sel[0]]
        try:
            self.bill.remove_person(uid)
            self._render_all_from_bill()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ลบไม่ได้", str(e))

    def update_config(self):
        def _to_float(s): s=(s or "0").strip(); return float(s) if s else 0.0
        try:
            self.bill.service_pct = _to_float(self.service_var.get())
            self.bill.vat_pct = _to_float(self.vat_var.get())
            self.bill.tip = _to_float(self.tip_var.get())
            messagebox.showinfo("สำเร็จ", "อัปเดตค่าบริการ/VAT/Tip แล้ว")
            self.refresh_summary(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def _get_selected_participants(self) -> List[str]:
        if self.all_var.get():
            return list(self.bill.people.keys())
        sel = self.participants_list.curselection()
        return [self.people_order[i] for i in sel]  # map index -> UID

    def add_item(self):
        name = self.item_name.get().strip()
        price_raw = self.item_price.get().strip()
        payer_label = self.payer_combo.get().strip()
        parts = self._get_selected_participants()
        if not name:
            messagebox.showwarning("เตือน", "กรุณากรอกชื่อเมนู"); return
        if not price_raw:
            messagebox.showwarning("เตือน", "กรุณากรอกราคา"); return
        if not payer_label:
            messagebox.showwarning("เตือน", "กรุณาเลือกผู้จ่ายก่อน"); return
        if not parts:
            messagebox.showwarning("เตือน", "กรุณาเลือกผู้ร่วมกิน"); return
        try:
            price = float(price_raw)
        except Exception:
            messagebox.showerror("ผิดพลาด", "กรอกจำนวนเงินให้ถูกต้อง"); return

        # หา UID ของ payer จาก label
        try:
            idx = self.payer_combo["values"].index(payer_label)
            payer_uid = self.people_order[idx]
        except Exception:
            messagebox.showerror("ผิดพลาด", "เลือกผู้จ่ายไม่ถูกต้อง"); return

        weights = None
        if self.use_weights.get():
            weights = {}
            for uid in parts:
                label = self._label(uid)
                while True:
                    w = simpledialog.askstring("น้ำหนักส่วนแบ่ง", f"weight ของ {label} (ตัวเลข > 0):", parent=self)
                    if w is None: return
                    try:
                        fv = float(w)
                        if fv <= 0: raise ValueError
                        weights[uid] = fv
                        break
                    except Exception:
                        messagebox.showwarning("เตือน", "ใส่ตัวเลข > 0 นะ")

        try:
            self.bill.add_item(Item(name=name, price=price, payer=payer_uid, participants=parts, weights=weights))
            self.item_name.delete(0, tk.END); self.item_price.delete(0, tk.END); self.use_weights.set(False)
            self._rebuild_table(); self.refresh_summary(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_selected_item(self):
        sel = self.table.selection()
        if not sel:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกรายการที่จะลบ"); return
        rid = sel[0]; parent = self.table.parent(rid) or rid
        if not parent.startswith("item-"):
            parent = rid
        try:
            idx0 = int(parent.split("-")[1])
        except Exception:
            messagebox.showerror("ผิดพลาด", "ไม่พบดัชนีรายการ"); return
        self.bill.remove_item_at(idx0)
        self._rebuild_table(); self.refresh_summary(); self._push_bill()

    def reset_all(self):
        if messagebox.askyesno("ยืนยัน", "ล้างข้อมูลทั้งหมด?"):
            self.bill = Bill()
            self.people_list.delete(0, tk.END)
            self.table.delete(*self.table.get_children())
            self.output.delete(1.0, tk.END)
            self.service_var.set("0"); self.vat_var.set("0"); self.tip_var.set("0")
            self.item_name.delete(0, tk.END); self.item_price.delete(0, tk.END)
            self.payer_combo.set(""); self.participants_list.selection_clear(0, tk.END)
            self.all_var.set(False); self.use_weights.set(False)
            self._push_bill()

    def refresh_summary(self):
        try:
            subtotal, svc, vat, total = self.bill._totals()
            should = self.bill.summary_costs()
            paid = self.bill.paid_map()
            net = self.bill.net_balance()
            txs = self.bill.settle_transactions()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e)); return

        def money(x): return f"{x:,.2f} บาท"

        self.output.delete(1.0, tk.END)
        self.output.insert(tk.END, "สรุปร้าน/บิล\n")
        self.output.insert(tk.END, f"  Subtotal: {money(subtotal)}\n")
        self.output.insert(tk.END, f"  Service {self.bill.service_pct:.2f}%: {money(svc)}\n")
        self.output.insert(tk.END, f"  VAT {self.bill.vat_pct:.2f}%: {money(vat)}\n")
        self.output.insert(tk.END, f"  Tip: {money(self.bill.tip)}\n")
        self.output.insert(tk.END, f"  Total: {money(total)}\n\n")

        self.output.insert(tk.END, "ควรจ่าย (รวม service/VAT/ทิป ตามสัดส่วนการกิน)\n")
        for uid in self.bill.people:
            self.output.insert(tk.END, f"  - {self._label(uid)}: {money(should.get(uid, 0.0))}\n")
        self.output.insert(tk.END, "\nจ่ายไปแล้ว\n")
        for uid in self.bill.people:
            self.output.insert(tk.END, f"  - {self._label(uid)}: {money(paid.get(uid, 0.0))}\n")
        self.output.insert(tk.END, "\nดุลสุทธิ (บวก=ควรได้รับ, ลบ=ควรจ่าย)\n")
        for uid in self.bill.people:
            self.output.insert(tk.END, f"  - {self._label(uid)}: {money(net.get(uid, 0.0))}\n")

        self.output.insert(tk.END, "\nรายการชำระกัน (ลดจำนวนธุรกรรมแบบ greedy)\n")
        if not txs:
            self.output.insert(tk.END, "  เคลียร์แล้ว ไม่ต้องโอนกัน 🎉\n")
        else:
            for t in txs:
                self.output.insert(tk.END, f"  - {self._label(t['from'])} → {self._label(t['to'])}: {money(t['amount'])}\n")

# -------------------- main --------------------
def main():
    root = tk.Tk()
    try:
        root.call("source", "azure.tcl")
        ttk.Style().theme_use("azure")
    except Exception:
        pass
    app = BillSplitApp(root)
    app.mainloop()

if __name__ == "__main__":
    main()
