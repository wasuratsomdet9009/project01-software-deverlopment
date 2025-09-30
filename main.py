# split_bill_all_in_one_login_separated.py
# ------------------------------------------------------------
# ✓ แยกหน้าล็อกอิน (LoginFrame) ออกจากหน้าใช้งาน (BillSplitApp)
# ✓ Firebase Auth (Email/Password) + Username reservation + Public profile
# ✓ RTDB streaming (SSE) + polling สำรอง
# ✓ เก็บ payer/participants เป็น UID จริง แต่แสดงเป็น username
# ✓ แก้ตรวจ API key, ปรับ add_person ให้เดา username ➜ UID, ปุ่มออกจากระบบ
# ✓ แก้ฟอร์มรหัสผ่าน: ยืนยันอยู่ใต้รหัสผ่าน, toggle ซ่อน/แสดง, แก้ตัวแปร pack_forget
# ------------------------------------------------------------

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import json, threading, time, csv, requests, re

try:
    from sseclient import SSEClient  # type: ignore
except Exception:
    SSEClient = None  # ถ้าไม่มีจะใช้ polling

# =====================
# Firebase Config (แก้ให้เป็นของคุณ)
# =====================
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"

# =====================
# Bill Engine (เก็บ UID)
# =====================
@dataclass
class Person:
    name: str  # เก็บเป็น UID

@dataclass
class Item:
    name: str
    price: float
    payer: str                   # UID
    participants: List[str]      # [UID]
    weights: Optional[Dict[str, float]] = None  # {UID: weight}

@dataclass
class Bill:
    people: Dict[str, Person] = field(default_factory=dict)  # key = UID
    items: List[Item] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    # People
    def add_person(self, uid: str):
        uid = uid.strip()
        if not uid:
            raise ValueError("UID ว่างไม่ได้")
        if uid in self.people:
            return
        self.people[uid] = Person(name=uid)

    def remove_person(self, uid: str):
        if uid in self.people:
            for it in self.items:
                if it.payer == uid or uid in it.participants:
                    raise ValueError("ลบไม่ได้: มีรายการที่เกี่ยวข้องกับคนนี้")
            del self.people[uid]

    # Items
    def add_item(self, item: Item):
        if item.payer not in self.people:
            raise ValueError(f"ไม่พบผู้จ่ายเงิน (UID): {item.payer}")
        for p in item.participants:
            if p not in self.people:
                raise ValueError(f"ไม่พบผู้ร่วมกิน (UID): {p}")
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

    # Calc
    def _totals(self):
        subtotal = sum(i.price for i in self.items)
        service_fee = subtotal * (self.service_pct / 100.0)
        vat_fee = (subtotal + service_fee) * (self.vat_pct / 100.0)
        total = subtotal + service_fee + vat_fee + self.tip
        return subtotal, service_fee, vat_fee, total

    def summary_costs(self) -> Dict[str, float]:
        if not self.items:
            return {uid: 0.0 for uid in self.people}
        subtotal, service_fee, vat_fee, total = self._totals()
        if subtotal == 0:
            return {uid: 0.0 for uid in self.people}
        cost_share_raw = defaultdict(float)
        for it in self.items:
            if it.weights:
                total_w = sum(it.weights[p] for p in it.participants)
                for p in it.participants:
                    cost_share_raw[p] += it.price * (it.weights[p] / total_w)
            else:
                each = it.price / len(it.participants)
                for p in it.participants:
                    cost_share_raw[p] += each
        scale = total / subtotal
        return {p: cost_share_raw.get(p, 0.0) * scale for p in self.people}

    def paid_map(self) -> Dict[str, float]:
        paid = defaultdict(float)
        for it in self.items:
            paid[it.payer] += it.price
        subtotal, service_fee, vat_fee, total = self._totals()
        extra = service_fee + vat_fee + self.tip
        if subtotal > 0 and extra > 0:
            for uid in paid:
                paid[uid] += extra * (paid[uid] / subtotal)
        for uid in self.people:
            paid[uid] = paid.get(uid, 0.0)
        return dict(paid)

    def net_balance(self) -> Dict[str, float]:
        should_pay = self.summary_costs()
        already_paid = self.paid_map()
        net = {uid: round(already_paid.get(uid, 0.0) - should_pay.get(uid, 0.0), 2)
               for uid in self.people}
        drift = round(sum(net.values()), 2)
        if drift != 0 and net:
            first = next(iter(net))
            net[first] = round(net[first] - drift, 2)
        return net

    def settle_transactions(self) -> List[Dict[str, float]]:
        net = self.net_balance()
        creditors = [[uid, amt] for uid, amt in net.items() if amt > 0]
        debtors = [[uid, -amt] for uid, amt in net.items() if amt < 0]
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)
        i = j = 0
        txs = []
        while i < len(debtors) and j < len(creditors):
            dname, damt = debtors[i]
            cname, camt = creditors[j]
            pay = round(min(damt, camt), 2)
            if pay > 0:
                txs.append({"from": dname, "to": cname, "amount": pay})
                damt = round(damt - pay, 2)
                camt = round(camt - pay, 2)
            debtors[i][1] = damt
            creditors[j][1] = camt
            if damt == 0: i += 1
            if camt == 0: j += 1
        return txs

    # Serialize
    def to_dict(self):
        return {
            "people": list(self.people.keys()),
            "items": [
                {
                    "name": it.name,
                    "price": it.price,
                    "payer": it.payer,
                    "participants": it.participants,
                    "weights": it.weights,
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
                payer=it["payer"], participants=list(it["participants"]),
                weights=it.get("weights")
            ))
        return b

# =====================
# Firebase REST Client
# =====================
class FirebaseRTClient:
    def __init__(self, api_key: str, rtdb_url: str):
        self.api_key = api_key
        self.rtdb_url = rtdb_url.rstrip("/")
        self.id_token = None
        self.refresh_token = None
        self.local_uid = None
        self._stop_stream = False

    # ---------- Auth (ด้วยตัวแปล error) ----------
    ERROR_MAP = {
        "EMAIL_NOT_FOUND": "ไม่พบบัญชีอีเมลนี้",
        "INVALID_PASSWORD": "รหัสผ่านไม่ถูกต้อง",
        "USER_DISABLED": "บัญชีถูกปิดใช้งาน",
        "EMAIL_EXISTS": "อีเมลนี้ถูกใช้งานแล้ว",
        "INVALID_EMAIL": "รูปแบบอีเมลไม่ถูกต้อง",
        "OPERATION_NOT_ALLOWED": "โปรเจกต์ยังไม่เปิดใช้งาน Email/Password บน Firebase Auth",
        "MISSING_PASSWORD": "กรุณากรอกรหัสผ่าน",
        "WEAK_PASSWORD": "รหัสผ่านต้องยาวอย่างน้อย 6 ตัว",
    }

    def _post_json(self, url: str, payload: dict) -> dict:
        """ยิง POST แล้วแปลง error ของ Firebase เป็นข้อความอ่านง่าย"""
        r = requests.post(url, json=payload)
        try:
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            msg = ""
            try:
                j = r.json()
                raw = j.get("error", {}).get("message", "")
                # ตัดหน้าข้อความยาวๆ เหลือคีย์หลัก
                msg = raw.split(" : ")[0].strip()
            except Exception:
                pass
            human = self.ERROR_MAP.get(msg, msg or str(e))
            raise ValueError(human)

    def sign_in_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token = d["idToken"]
        self.refresh_token = d["refreshToken"]
        self.local_uid = d["localId"]
        return d

    def sign_up_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token = d["idToken"]
        self.refresh_token = d["refreshToken"]
        self.local_uid = d["localId"]
        return d

    # ---------- Token refresh ----------
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
                except:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    # REST
    def _auth(self):
        if not self.id_token: raise RuntimeError("Not authenticated")
        return {"auth": self.id_token}

    def get(self, path: str):
        url = f"{self.rtdb_url}/{path}.json"
        r = requests.get(url, params=self._auth(), timeout=30); r.raise_for_status(); return r.json()

    def put(self, path: str, obj):
        url = f"{self.rtdb_url}/{path}.json"
        r = requests.put(url, params=self._auth(), json=obj, timeout=30); r.raise_for_status(); return r.json()

    def patch(self, path: str, obj):
        url = f"{self.rtdb_url}/{path}.json"
        r = requests.patch(url, params=self._auth(), json=obj, timeout=30); r.raise_for_status(); return r.json()

    # username / profile
    @staticmethod
    def _norm_uname(u: str) -> str:
        u = (u or "").strip().lower()
        if not u: raise ValueError("username ว่างไม่ได้")
        for bad in ['.', '#', '$', '[', ']', '/']:
            if bad in u: raise ValueError("username มีอักขระต้องห้าม: . # $ [ ] /")
        return u

    def reserve_username(self, username: str):
        uname = self._norm_uname(username)
        return self.put(f"usernames/{uname}", self.local_uid)

    def uid_from_username(self, username: str) -> Optional[str]:
        uname = self._norm_uname(username)
        try: return self.get(f"usernames/{uname}")
        except requests.HTTPError: return None

    def save_profile(self, username: str, display_name: str):
        data = {"username": self._norm_uname(username),
                "displayName": display_name or username,
                "updatedAt": int(time.time())}
        return self.put(f"public_profiles/{self.local_uid}", data)

    def get_profile(self, uid: str) -> Optional[dict]:
        try: return self.get(f"public_profiles/{uid}")
        except requests.HTTPError: return None

    # Streaming
    def stream(self, path: str, on_event: Callable):
        if not self.id_token: raise RuntimeError("Not authenticated")
        url = f"{self.rtdb_url}/{path}.json"
        self._stop_stream = False

        def run_sse():
            while not self._stop_stream:
                try:
                    msgs = SSEClient(url, params={"auth": self.id_token})
                    for msg in msgs:
                        if self._stop_stream: break
                        if msg.event in ("put", "patch"):
                            try:
                                data = json.loads(msg.data); on_event(data)
                            except: pass
                except:
                    try: self.refresh_id_token()
                    except: pass
                    time.sleep(2)

        def run_poll():
            last = None
            while not self._stop_stream:
                try:
                    data = requests.get(url, params={"auth": self.id_token}, timeout=30).json()
                    if data is not None:
                        ua = data.get("updatedAt") if isinstance(data, dict) else None
                        if last != ua:
                            on_event({"path": "/", "data": data}); last = ua
                except:
                    try: self.refresh_id_token()
                    except: pass
                time.sleep(3)

        th = threading.Thread(target=(run_sse if SSEClient else run_poll), daemon=True)
        th.start()

    def stop_stream(self): self._stop_stream = True

# =====================
# Login Frame (หน้าแรก)
# =====================
class LoginFrame(ttk.Frame):
    def __init__(self, master, on_success: Callable[[FirebaseRTClient], None]):
        super().__init__(master)
        self.on_success = on_success
        self.grid(sticky="nsew", padx=24, pady=24)
        master.title("เข้าสู่ระบบ • Bill Split")
        master.geometry("420x340")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        frm = ttk.Frame(self)
        frm.pack(expand=True, fill="both")
        ttk.Label(frm, text="เข้าสู่ระบบ", font=("Segoe UI", 14, "bold")).pack(pady=(0, 10))

        self.has_account = tk.BooleanVar(value=True)
        row1 = ttk.Frame(frm); row1.pack(fill="x")
        ttk.Radiobutton(row1, text="ฉันมีบัญชีแล้ว (Login)", variable=self.has_account,
                        value=True, command=lambda: self._toggle_signup(True)).pack(side="left")
        ttk.Radiobutton(row1, text="ฉันยังไม่มีบัญชี (Sign up)", variable=self.has_account,
                        value=False, command=lambda: self._toggle_signup(False)).pack(side="left", padx=10)

        ttk.Label(frm, text="อีเมล").pack(anchor="w", pady=(10, 2))
        self.email = ttk.Entry(frm); self.email.pack(fill="x")

        # ใช้ StringVar ผูก password + confirm
        self.pwd_var = tk.StringVar()
        self.cpwd_var = tk.StringVar()

        # บล็อครหัสผ่าน + ปุ่มโชว์/ซ่อน
        pw_block = ttk.Frame(frm)
        pw_block.pack(fill="x", pady=(8, 0))

        ttk.Label(pw_block, text="รหัสผ่าน").pack(anchor="w")
        pw_row = ttk.Frame(pw_block); pw_row.pack(fill="x")
        self.pwd = ttk.Entry(pw_row, show="*", textvariable=self.pwd_var)
        self.pwd.pack(side="left", fill="x", expand=True)
        self.show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            pw_row, text="แสดง", variable=self.show_pw,
            command=lambda: self.pwd.config(show="" if self.show_pw.get() else "*")
        ).pack(side="left", padx=8)

        # แถว 'ยืนยันรหัสผ่าน' (ซ่อนถ้า login)
        self.cpwd_frame = ttk.Frame(pw_block)
        ttk.Label(self.cpwd_frame, text="ยืนยันรหัสผ่าน").pack(anchor="w", pady=(8, 2))
        cpw_row = ttk.Frame(self.cpwd_frame); cpw_row.pack(fill="x")
        self.cpwd = ttk.Entry(cpw_row, show="*", textvariable=self.cpwd_var)
        self.cpwd.pack(side="left", fill="x", expand=True)
        self.show_cpw = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cpw_row, text="แสดง", variable=self.show_cpw,
            command=lambda: self.cpwd.config(show="" if self.show_cpw.get() else "*")
        ).pack(side="left", padx=8)

        # เริ่มต้นเป็นโหมด Login → ซ่อนยืนยัน
        self.cpwd_frame.pack_forget()

        btn = ttk.Button(frm, text="ดำเนินการ", command=self.attempt_auth)
        btn.pack(pady=16)
        # กด Enter เพื่อยืนยัน
        for w in (self.email, self.pwd, self.cpwd):
            w.bind("<Return>", lambda *_: self.attempt_auth())

        self.status = ttk.Label(frm, text="", foreground="#666")
        self.status.pack()

    def _toggle_signup(self, is_login: bool):
        """สลับโหมด: ซ่อน/โชว์ช่องยืนยัน และล้างค่าเพื่อกันหลงเหลือ"""
        if is_login:
            self.cpwd_frame.pack_forget()
            self.cpwd_var.set("")
            self.show_cpw.set(False)
            self.cpwd.config(show="*")
        else:
            self.cpwd_frame.pack(fill="x")

    def _valid_email(self, s: str) -> bool:
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s.strip()))

    def attempt_auth(self):
        if not FIREBASE_API_KEY or not FIREBASE_RTDB_URL:
            messagebox.showwarning("Config", "กรุณาตั้งค่า FIREBASE_API_KEY / FIREBASE_RTDB_URL ก่อน")
            return

        email = (self.email.get() or "").strip()
        pwd = (self.pwd_var.get() or "").strip()

        if not self._valid_email(email):
            messagebox.showwarning("เตือน", "รูปแบบอีเมลไม่ถูกต้อง")
            return
        if not pwd:
            messagebox.showwarning("เตือน", "กรอกรหัสผ่าน")
            return

        # โหมดสมัคร: ตรวจความยาว + เทียบยืนยัน
        if not self.has_account.get():
            cpwd = (self.cpwd_var.get() or "").strip()
            if len(pwd) < 6:
                messagebox.showwarning("เตือน", "รหัสผ่านต้องอย่างน้อย 6 ตัวอักษร")
                return
            if pwd != cpwd:
                messagebox.showwarning("เตือน", "รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน")
                return

        fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        try:
            if self.has_account.get():
                fb.sign_in_email(email, pwd)
            else:
                fb.sign_up_email(email, pwd)
        except Exception as e:
            messagebox.showerror("Firebase", f"{e}")
            return

        fb.start_auto_refresh()

        # ensure username / profile
        prof = fb.get_profile(fb.local_uid) or {}
        if not prof or not prof.get("username"):
            while True:
                uname = simpledialog.askstring("ตั้ง Username", "username (ห้ามซ้ำ):", parent=self)
                if not uname:
                    return
                dname = simpledialog.askstring("ชื่อแสดง", "ชื่อที่จะแสดง (ว่าง=ใช้ username):", parent=self) or uname
                try:
                    fb.reserve_username(uname)
                    fb.save_profile(uname, dname)
                    break
                except Exception as e:
                    messagebox.showerror("Username", f"ใช้ไม่ได้: {e}\nลองใหม่อีกครั้ง")

        self.status.config(text="สำเร็จ! กำลังเข้าแอพ…")
        self.after(100, lambda: self.on_success(fb))

# =====================
# Main App (หน้าใช้งาน)
# =====================
class BillSplitApp(ttk.Frame):
    def __init__(self, master, fb: FirebaseRTClient):
        super().__init__(master)
        self.fb = fb
        self.bill = Bill()
        self.room_id: Optional[str] = None
        self._local_change = False
        self._last_remote_ua = None

        # ชื่อแสดง (cache)
        self.name_cache: Dict[str, str] = {}
        self.people_uids: List[str] = []
        self.label2uid: Dict[str, str] = {}

        master.title("หารค่าอาหารกับเพื่อน • Tkinter + Firebase")
        master.geometry("1120x700")
        self.pack(fill=tk.BOTH, expand=True)
        self._build_layout()

        # เลือกห้อง
        self.join_room_and_bind()

    # ---------- UI ----------
    def _build_layout(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self); left.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)
        right = ttk.Frame(self); right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right.rowconfigure(1, weight=1); right.columnconfigure(0, weight=1)

        # status
        ttk.Label(left, text="Cloud (Firebase)", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.cloud_lbl = ttk.Label(left, text=f"UID: {self.fb.local_uid[:6]}…")
        self.cloud_lbl.grid(row=1, column=0, sticky="w", pady=(0,4))
        ttk.Button(left, text="ออกจากระบบ", command=self.logout).grid(row=1, column=1, sticky="e", padx=(6,0))

        # People
        ttk.Label(left, text="รายชื่อเพื่อน (UID)", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10,0))
        self.person_entry = ttk.Entry(left, width=22); self.person_entry.grid(row=3, column=0, sticky="w")
        ttk.Button(left, text="เพิ่ม (UID/username)", command=self.add_person).grid(row=3, column=1, padx=5)
        self.people_list = tk.Listbox(left, height=8, exportselection=False)
        self.people_list.grid(row=4, column=0, columnspan=2, sticky="we", pady=5)
        ttk.Button(left, text="ลบที่เลือก", command=self.remove_person).grid(row=5, column=0, columnspan=2, sticky="we")

        # Config
        ttk.Label(left, text="Service/VAT/Tip", font=("Segoe UI", 11, "bold")).grid(row=6, column=0, columnspan=2, sticky="w")
        frm_cfg = ttk.Frame(left); frm_cfg.grid(row=7, column=0, columnspan=2, sticky="we")
        ttk.Label(frm_cfg, text="Service %").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_cfg, text="VAT %").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_cfg, text="Tip (บาท)").grid(row=2, column=0, sticky="w")
        self.service_var = tk.StringVar(value="0"); self.vat_var = tk.StringVar(value="0"); self.tip_var = tk.StringVar(value="0")
        ttk.Entry(frm_cfg, textvariable=self.service_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.vat_var, width=10).grid(row=1, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.tip_var, width=10).grid(row=2, column=1, padx=5)
        ttk.Button(left, text="อัปเดตค่า", command=self.update_config).grid(row=8, column=0, columnspan=2, sticky="we", pady=5)

        # Item form
        ttk.Label(left, text="เพิ่มรายการอาหาร", font=("Segoe UI", 11, "bold")).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10,0))
        frm_item = ttk.Frame(left); frm_item.grid(row=10, column=0, columnspan=2, sticky="we")
        ttk.Label(frm_item, text="ชื่อเมนู").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_item, text="ราคา").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้จ่ายก่อน").grid(row=2, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้ร่วมกิน").grid(row=3, column=0, sticky="nw")
        self.item_name = ttk.Entry(frm_item, width=22)
        self.item_price = ttk.Entry(frm_item, width=22)
        self.payer_combo = ttk.Combobox(frm_item, values=[], state="readonly", width=20)
        self.participants_list = tk.Listbox(frm_item, selectmode=tk.MULTIPLE, height=6, exportselection=False)
        self.all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_item, text="ทุกคน", variable=self.all_var, command=self.toggle_all_participants).grid(row=4, column=1, sticky="w")
        self.item_name.grid(row=0, column=1, sticky="we", pady=1)
        self.item_price.grid(row=1, column=1, sticky="we", pady=1)
        self.payer_combo.grid(row=2, column=1, sticky="we", pady=1)
        self.participants_list.grid(row=3, column=1, sticky="we", pady=1)
        self.use_weights = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_item, text="หารไม่เท่ากัน (weights)", variable=self.use_weights).grid(row=5, column=1, sticky="w", pady=(4,0))

        btns = ttk.Frame(left); btns.grid(row=11, column=0, columnspan=2, sticky="we", pady=6)
        ttk.Button(btns, text="เพิ่มรายการ", command=self.add_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="ลบรายการที่เลือก", command=self.remove_selected_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # Table
        ttk.Label(right, text="รายการทั้งหมด", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.table_cols = ("idx", "name", "price", "payer", "count", "participants", "mode", "per_head", "weights")
        self.table = ttk.Treeview(right, columns=self.table_cols, show="headings", height=14, selectmode="browse")
        heads = {"idx":"#", "name":"เมนู", "price":"ราคา (บาท)", "payer":"ผู้จ่าย", "count":"คนร่วม",
                 "participants":"รายชื่อผู้ร่วมกิน", "mode":"โหมดหาร", "per_head":"ต่อหัว/เมนู (บาท)", "weights":"น้ำหนัก"}
        widths = {"idx":40,"name":200,"price":110,"payer":110,"count":65,"participants":300,"mode":90,"per_head":130,"weights":160}
        anchors = {"idx":"e","name":"w","price":"e","payer":"w","count":"e","participants":"w","mode":"center","per_head":"e","weights":"w"}
        for k in self.table_cols:
            self.table.heading(k, text=heads[k], command=lambda c=k: self._sort_by(c))
            self.table.column(k, width=widths[k], anchor=anchors[k], stretch=False)
        try:
            self.table.tag_configure("odd", background="#fafafa")
            self.table.tag_configure("even", background="#f2f4f7")
            self.table.tag_configure("child", foreground="#555")
        except Exception: pass
        self.table.grid(row=1, column=0, sticky="nsew")
        scr = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scr.set); scr.grid(row=1, column=1, sticky="ns")

        # Summary
        ttk.Label(right, text="สรุปผล", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w", pady=(10,0))
        self.output = tk.Text(right, height=12); self.output.grid(row=3, column=0, sticky="nsew")
        btm = ttk.Frame(right); btm.grid(row=4, column=0, sticky="we", pady=6)
        ttk.Button(btm, text="คำนวณ/อัปเดตสรุป", command=self.refresh_summary).pack(side=tk.LEFT)
        ttk.Button(btm, text="คัดลอกสรุป", command=self.copy_summary).pack(side=tk.LEFT, padx=6)
        ttk.Button(btm, text="บันทึกบิล (JSON)", command=self.save_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btm, text="โหลดบิล (JSON)", command=self.load_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btm, text="Export โอน (CSV)", command=self.export_transfers_csv).pack(side=tk.LEFT, padx=6)
        ttk.Button(btm, text="ล้างทั้งหมด", command=self.reset_all).pack(side=tk.LEFT, padx=6)

    # ---------- ห้อง + สตรีม ----------
    def join_room_and_bind(self):
        room = simpledialog.askstring("เข้าร่วมห้อง", "Room ID (เช่น classA-2025):", parent=self)
        if not room:
            messagebox.showwarning("แจ้ง", "ต้องใส่ Room ID"); return
        self.room_id = room.strip()
        try:
            self.fb.patch(f"rooms/{self.room_id}/members/{self.fb.local_uid}", {"joinedAt": int(time.time())})
        except Exception as e:
            messagebox.showerror("Firebase", f"เข้าห้องไม่สำเร็จ: {e}"); return

        try:
            data = self.fb.get(f"bills/{self.room_id}")
            if data:
                self.bill = Bill.from_dict(data)
                self._render_all_from_bill()
                if isinstance(data, dict):
                    self._last_remote_ua = data.get("updatedAt")
        except Exception:
            pass

        def on_event(_ev):
            if self._local_change: return
            try:
                full = self.fb.get(f"bills/{self.room_id}")
                if not isinstance(full, dict): return
                ua = full.get("updatedAt")
                if ua is not None and ua == self._last_remote_ua:
                    return
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

    # ---------- helpers ----------
    def logout(self):
        if messagebox.askyesno("ยืนยัน", "ออกจากระบบและกลับหน้าเข้าสู่ระบบ?"):
            try: self.fb.stop_stream()
            except: pass
            root = self.master
            for w in list(root.children.values()):
                try: w.destroy()
                except: pass
            LoginFrame(root, on_success=lambda fb: ( [c.destroy() for c in list(root.children.values())], BillSplitApp(root, fb) ))

    def _label_for(self, uid: str) -> str:
        if uid in self.name_cache: return self.name_cache[uid]
        label = uid[:6]
        prof = self.fb.get_profile(uid)
        if prof: label = prof.get("username") or prof.get("displayName") or label
        self.name_cache[uid] = label
        return label

    def _refresh_people_widgets(self):
        self.people_uids = list(self.bill.people.keys())
        labels = []; self.label2uid = {}
        for uid in self.people_uids:
            lab = self._label_for(uid); labels.append(lab); self.label2uid[lab] = uid
        self.payer_combo["values"] = labels

        self.participants_list.delete(0, tk.END)
        for uid in self.people_uids:
            self.participants_list.insert(tk.END, self._label_for(uid))

        self.people_list.delete(0, tk.END)
        for uid in self.people_uids:
            self.people_list.insert(tk.END, f"{self._label_for(uid)}  ({uid[:6]}…)")

    def toggle_all_participants(self):
        if self.all_var.get(): self.participants_list.select_set(0, tk.END)
        else: self.participants_list.select_clear(0, tk.END)

    def _compute_scale(self) -> float:
        subtotal = sum(i.price for i in self.bill.items)
        if subtotal <= 0: return 1.0
        svc = subtotal * (self.bill.service_pct / 100.0)
        vat = (subtotal + svc) * (self.bill.vat_pct / 100.0)
        total = subtotal + svc + vat + self.bill.tip
        return total / subtotal

    def _format_weights(self, it: Item) -> str:
        if not it.weights: return "-"
        return ", ".join(f"{self._label_for(p)}={v:g}" for p, v in it.weights.items())

    def _per_head_for_item(self, it: Item) -> float:
        scale = self._compute_scale()
        if not it.participants: return 0.0
        if it.weights:
            totw = sum(it.weights[p] for p in it.participants)
            return it.price * scale / totw
        return (it.price * scale) / len(it.participants)

    def _item_shares(self, it: Item) -> Dict[str, float]:
        scale = self._compute_scale(); shares = {}
        if not it.participants: return shares
        if it.weights:
            totw = sum(it.weights[p] for p in it.participants)
            for p in it.participants:
                shares[self._label_for(p)] = (it.price * scale) * (it.weights[p] / totw)
        else:
            each = (it.price * scale) / len(it.participants)
            for p in it.participants: shares[self._label_for(p)] = each
        return shares

    def _add_item_to_table(self, idx0: int, it: Item):
        rowvals = (idx0+1, it.name, f"{it.price:,.2f}", self._label_for(it.payer),
                   len(it.participants), ", ".join(self._label_for(u) for u in it.participants),
                   "น้ำหนัก" if it.weights else "เท่ากัน", f"{self._per_head_for_item(it):,.2f}", self._format_weights(it))
        tag = "odd" if (idx0 % 2 == 0) else "even"
        parent_id = self.table.insert("", tk.END, values=rowvals, tags=(tag,))
        for lab, money in self._item_shares(it).items():
            self.table.insert(parent_id, tk.END, values=("", f"• {lab}", "", "", "", "", "", f"{money:,.2f}", ""), tags=("child",))

    def _rebuild_table(self):
        self.table.delete(*self.table.get_children())
        for i, it in enumerate(self.bill.items): self._add_item_to_table(i, it)

    def _apply_zebra(self):
        roots = self.table.get_children("")
        for i, rid in enumerate(roots):
            self.table.item(rid, tags=("odd" if (i % 2 == 0) else "even",))

    def _sort_by(self, col: str, reverse: Optional[bool] = None):
        col_index = self.table_cols.index(col)
        parents = list(self.table.get_children(""))
        def key_of(rid):
            v = self.table.item(rid, "values")[col_index]
            if col in {"idx","price","count","per_head"}:
                try: return float(str(v).replace(",", ""))
                except: return 0.0
            return str(v).lower()
        if reverse is None: reverse = getattr(self, "_sort_rev_"+col, False)
        parents.sort(key=key_of, reverse=reverse); setattr(self, "_sort_rev_"+col, not reverse)
        for pos, rid in enumerate(parents): self.table.move(rid, "", pos)
        self._apply_zebra()

    # ---------- Sync ----------
    def _push_bill(self):
        if not self.room_id: return
        try:
            self._local_change = True
            data = self.bill.to_dict(); data["lastEditBy"] = self.fb.local_uid
            self.fb.put(f"bills/{self.room_id}", data); self._last_remote_ua = data["updatedAt"]
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))

    def _render_all_from_bill(self):
        self._refresh_people_widgets(); self._rebuild_table(); self.refresh_summary()

    def _keep_synced(self):
        if self.room_id and not self._local_change:
            try:
                full = self.fb.get(f"bills/{self.room_id}")
                if isinstance(full, dict):
                    ua = full.get("updatedAt")
                    if ua is not None and ua != self._last_remote_ua:
                        self._last_remote_ua = ua; self.bill = Bill.from_dict(full); self._render_all_from_bill()
            except: pass
        self.after(3000, self._keep_synced)

    # ---------- Local Save/Load/Copy/Export ----------
    def copy_summary(self):
        txt = self.output.get("1.0", tk.END).strip()
        self.master.clipboard_clear(); self.master.clipboard_append(txt)
        messagebox.showinfo("ก็อปแล้ว", "คัดลอกสรุปแล้ว")

    def save_bill_local(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if not p: return
        with open(p, "w", encoding="utf-8") as f: json.dump(self.bill.to_dict(), f, ensure_ascii=False, indent=2)
        messagebox.showinfo("บันทึกแล้ว", p)

    def load_bill_local(self):
        p = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not p: return
        with open(p, "r", encoding="utf-8") as f: data = json.load(f)
        self.bill = Bill.from_dict(data); self._render_all_from_bill(); self._push_bill()

    def export_transfers_csv(self):
        txs = self.bill.settle_transactions()
        if not txs: messagebox.showinfo("CSV", "ไม่มีรายการโอน"); return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not p: return
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["from(UID)","to(UID)","amount"])
            for t in txs: w.writerow([t["from"], t["to"], f'{t["amount"]:.2f}'])
        messagebox.showinfo("CSV", p)

    # ---------- Events ----------
    def add_person(self):
        key = self.person_entry.get().strip()
        if not key:
            messagebox.showwarning("เตือน", "กรอก UID หรือ username")
            return

        # พยายามตีความเป็น username ก่อน
        uid = None
        try:
            uid = self.fb.uid_from_username(key)
        except Exception:
            uid = None

        if not uid:
            # ถ้าไม่เจอ username ให้ถือว่าเป็น UID (เช็คความยาวคร่าว ๆ ของ Firebase UID)
            if len(key) < 28:
                messagebox.showerror("ไม่พบ", f"ไม่พบ username: {key}\nหรือ UID สั้นเกินไป")
                return
            uid = key

        try:
            self.bill.add_person(uid)
            self.person_entry.delete(0, tk.END)
            self.name_cache[uid] = self._label_for(uid)
            self._refresh_people_widgets()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_person(self):
        sel = self.people_list.curselection()
        if not sel: messagebox.showinfo("แจ้ง", "เลือกเพื่อนก่อน"); return
        uid = self.people_uids[sel[0]]
        try:
            self.bill.remove_person(uid); self._refresh_people_widgets(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ลบไม่ได้", str(e))

    def update_config(self):
        def f(s): s=(s or "0").strip(); return float(s) if s else 0.0
        try:
            self.bill.service_pct = f(self.service_var.get())
            self.bill.vat_pct = f(self.vat_var.get())
            self.bill.tip = f(self.tip_var.get())
            self.refresh_summary(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def _get_selected_participants(self) -> List[str]:
        if self.all_var.get(): return list(self.bill.people.keys())
        sel = self.participants_list.curselection()
        return [self.people_uids[i] for i in sel]

    def add_item(self):
        name = self.item_name.get().strip()
        price_raw = self.item_price.get().strip()
        payer_label = self.payer_combo.get().strip()
        parts = self._get_selected_participants()
        if not name or not price_raw or not payer_label or not parts:
            messagebox.showwarning("เตือน", "กรอกข้อมูลให้ครบ"); return
        payer_uid = self.label2uid.get(payer_label, payer_label)
        try: price = float(price_raw)
        except: messagebox.showerror("ผิดพลาด", "ราคาไม่ถูกต้อง"); return

        weights = None
        if self.use_weights.get():
            weights = {}
            for uid in parts:
                while True:
                    w = simpledialog.askstring("weight", f"weight ของ {self._label_for(uid)} (>0):", parent=self)
                    if w is None: return
                    try:
                        v = float(w)
                        if v <= 0: raise ValueError
                        weights[uid] = v; break
                    except: messagebox.showwarning("เตือน","ใส่ตัวเลข > 0")
        try:
            self.bill.add_item(Item(name=name, price=price, payer=payer_uid, participants=parts, weights=weights))
            self.item_name.delete(0, tk.END); self.item_price.delete(0, tk.END); self.use_weights.set(False)
            self._rebuild_table(); self.refresh_summary(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_selected_item(self):
        sel = self.table.selection()
        if not sel: messagebox.showinfo("แจ้ง", "เลือกรายการก่อน"); return
        rid = sel[0]; parent = self.table.parent(rid) or rid
        vals = self.table.item(parent, "values")
        try: idx1 = int(vals[0])
        except: messagebox.showerror("ผิดพลาด","ไม่พบดัชนีรายการ"); return
        self.bill.remove_item_at(idx1-1); self._rebuild_table(); self.refresh_summary(); self._push_bill()

    def reset_all(self):
        if messagebox.askyesno("ยืนยัน", "ล้างข้อมูลทั้งหมด?"):
            self.bill = Bill(); self._render_all_from_bill(); self._push_bill()

    def refresh_summary(self):
        try:
            subtotal, svc, vat, total = self.bill._totals()
            should = self.bill.summary_costs(); paid = self.bill.paid_map()
            net = self.bill.net_balance(); txs = self.bill.settle_transactions()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e)); return
        money = lambda x: f"{x:,.2f} บาท"
        self.output.delete(1.0, tk.END)
        self.output.insert(tk.END, "สรุปร้าน/บิล\n")
        self.output.insert(tk.END, f"  Subtotal: {money(subtotal)}\n")
        self.output.insert(tk.END, f"  Service {self.bill.service_pct:.2f}%: {money(svc)}\n")
        self.output.insert(tk.END, f"  VAT {self.bill.vat_pct:.2f}%: {money(vat)}\n")
        self.output.insert(tk.END, f"  Tip: {money(self.bill.tip)}\n")
        self.output.insert(tk.END, f"  Total: {money(total)}\n\n")
        self.output.insert(tk.END, "ควรจ่าย\n")
        for uid in self.bill.people: self.output.insert(tk.END, f"  - {self._label_for(uid)}: {money(should.get(uid,0.0))}\n")
        self.output.insert(tk.END, "\nจ่ายไปแล้ว\n")
        for uid in self.bill.people: self.output.insert(tk.END, f"  - {self._label_for(uid)}: {money(paid.get(uid,0.0))}\n")
        self.output.insert(tk.END, "\nดุลสุทธิ\n")
        for uid in self.bill.people: self.output.insert(tk.END, f"  - {self._label_for(uid)}: {money(net.get(uid,0.0))}\n")
        self.output.insert(tk.END, "\nการโอนเคลียร์กัน\n")
        if not txs: self.output.insert(tk.END, "  เคลียร์แล้ว 🎉\n")
        else:
            for t in txs:
                self.output.insert(tk.END, f"  - {self._label_for(t['from'])} → {self._label_for(t['to'])}: {money(t['amount'])}\n")

# =====================
# App bootstrap
# =====================
def main():
    root = tk.Tk()
    try:
        root.call("source", "azure.tcl"); ttk.Style().theme_use("azure")
    except Exception:
        pass

    def open_app(fb: FirebaseRTClient):
        # ล้างหน้าล็อกอิน แล้วเปิดหน้าใช้งาน
        for w in list(root.children.values()):
            try:
                w.destroy()
            except:
                pass
        BillSplitApp(root, fb)

    LoginFrame(root, on_success=open_app)
    root.mainloop()

if __name__ == "__main__":
    main()
