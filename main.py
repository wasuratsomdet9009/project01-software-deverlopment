# split_bill_with_login.py
# ------------------------------------------------------------
# Tkinter 2 หน้า: Login (Sign in/Sign up) + Bill Split App
# Firebase: Email/Password Auth + Realtime Database (SSE/poll)
# ตารางละเอียดพร้อมแถวลูก, sort คอลัมน์, zebra
# ------------------------------------------------------------

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import json, threading, time, csv
import requests

try:
    from sseclient import SSEClient  # type: ignore
except Exception:
    SSEClient = None  # ไม่มีไลบรารี ก็จะใช้ polling แทน

# =====================
# Firebase Config — เปลี่ยนให้เป็นโปรเจกต์ของคุณ
# =====================
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"

# =====================
# Bill Engine (Logic)
# =====================
@dataclass
class Person:
    name: str

@dataclass
class Item:
    name: str
    price: float
    payer: str
    participants: List[str]
    weights: Optional[Dict[str, float]] = None

@dataclass
class Bill:
    people: Dict[str, Person] = field(default_factory=dict)
    items: List[Item] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    # People
    def add_person(self, name: str):
        name = name.strip()
        if not name:
            raise ValueError("ชื่อว่างไม่ได้")
        if name in self.people:
            return
        self.people[name] = Person(name=name)

    def remove_person(self, name: str):
        if name in self.people:
            for it in self.items:
                if it.payer == name or name in it.participants:
                    raise ValueError("ลบไม่ได้: มีรายการที่เกี่ยวข้องกับคนนี้")
            del self.people[name]

    # Items
    def add_item(self, item: Item):
        if item.payer not in self.people:
            raise ValueError(f"ไม่พบผู้จ่ายเงิน: {item.payer}")
        for p in item.participants:
            if p not in self.people:
                raise ValueError(f"ไม่พบผู้ร่วมกิน: {p}")
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
            return {name: 0.0 for name in self.people}
        subtotal, service_fee, vat_fee, total = self._totals()
        if subtotal == 0:
            return {name: 0.0 for name in self.people}
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
            for name in paid:
                paid[name] += extra * (paid[name] / subtotal)
        for name in self.people:
            paid[name] = paid.get(name, 0.0)
        return dict(paid)

    def net_balance(self) -> Dict[str, float]:
        should_pay = self.summary_costs()
        already_paid = self.paid_map()
        net = {name: round(already_paid.get(name, 0.0) - should_pay.get(name, 0.0), 2)
               for name in self.people}
        drift = round(sum(net.values()), 2)
        if drift != 0 and net:
            first = next(iter(net))
            net[first] = round(net[first] - drift, 2)
        return net

    def settle_transactions(self) -> List[Dict[str, float]]:
        net = self.net_balance()
        creditors = [[name, amt] for name, amt in net.items() if amt > 0]
        debtors = [[name, -amt] for name, amt in net.items() if amt < 0]
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
            if damt == 0:
                i += 1
            if camt == 0:
                j += 1
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
        for n in data.get("people", []):
            b.add_person(n)
        b.service_pct = float(data.get("service_pct", 0))
        b.vat_pct = float(data.get("vat_pct", 0))
        b.tip = float(data.get("tip", 0))
        for it in data.get("items", []):
            b.add_item(Item(
                name=it["name"], price=float(it["price"]), payer=it["payer"],
                participants=it["participants"], weights=it.get("weights")
            ))
        return b

# =====================
# Firebase REST + Streaming
# =====================
class FirebaseRTClient:
    def __init__(self, api_key: str, rtdb_url: str):
        self.api_key = api_key
        self.rtdb_url = rtdb_url.rstrip("/")
        self.id_token = None
        self.refresh_token = None
        self.local_uid = None
        self._stop_stream = False
        self._stream_thread = None

    def _post_json(self, url, payload):
        res = requests.post(url, json=payload)
        try:
            res.raise_for_status()
            return res.json()
        except requests.HTTPError as e:
            # ดึงข้อความ error ของ Firebase ออกมา
            try:
                err = res.json()
                raw = err.get("error", {}).get("message", "")
            except Exception:
                raw = res.text
            # โยนเป็น RuntimeError พร้อมข้อความสั้นที่เข้าใจง่าย
            raise RuntimeError(raw or str(e)) from None

    def sign_in_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        data = self._post_json(url, {
            "email": email, "password": password, "returnSecureToken": True
        })
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.local_uid = data["localId"]
        return data

    def sign_up_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        data = self._post_json(url, {
            "email": email, "password": password, "returnSecureToken": True
        })
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.local_uid = data["localId"]
        return data

    # Token refresh
    def refresh_id_token(self):
        if not self.refresh_token:
            return
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"
        res = requests.post(url, data={
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        })
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

    # RTDB REST
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

    def post(self, path: str, obj):
        url = f"{self.rtdb_url}/{path}.json"
        res = requests.post(url, params=self._auth_params(), json=obj, timeout=30)
        res.raise_for_status()
        return res.json()

    def delete(self, path: str):
        url = f"{self.rtdb_url}/{path}.json"
        res = requests.delete(url, params=self._auth_params(), timeout=30)
        res.raise_for_status()
        return res.json()

    # Streaming
    def stream(self, path: str, on_event: Callable):
        if not self.id_token:
            raise RuntimeError("Not authenticated")
        url = f"{self.rtdb_url}/{path}.json"
        self._stop_stream = False

        def run_sse():
            while not self._stop_stream:
                try:
                    messages = SSEClient(url, params={"auth": self.id_token})
                    for msg in messages:
                        if self._stop_stream:
                            break
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
            while not self._stop_stream:
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

        def runner():
            if SSEClient is None:
                run_poll()
            else:
                run_sse()

        self._stream_thread = threading.Thread(target=runner, daemon=True)
        self._stream_thread.start()

    def stop_stream(self):
        self._stop_stream = True

# =====================
# Login Page (Frame)
# =====================
class LoginPage(ttk.Frame):
    def __init__(self, master, on_auth_success: Callable[[FirebaseRTClient, str], None]):
        super().__init__(master)
        self.on_auth_success = on_auth_success
        self.fb: Optional[FirebaseRTClient] = None

        self.columnconfigure(0, weight=1)
        title = ttk.Label(self, text="เข้าสู่ระบบ • Firebase", font=("Segoe UI", 14, "bold"))
        title.grid(row=0, column=0, pady=(20, 10), sticky="n")

        frm = ttk.Frame(self)
        frm.grid(row=1, column=0, pady=10, padx=20, sticky="n")

        ttk.Label(frm, text="อีเมล").grid(row=0, column=0, sticky="w")
        ttk.Label(frm, text="รหัสผ่าน").grid(row=1, column=0, sticky="w")
        ttk.Label(frm, text="Room ID").grid(row=2, column=0, sticky="w")

        self.email_var = tk.StringVar()
        self.pwd_var = tk.StringVar()
        self.room_var = tk.StringVar()

        ttk.Entry(frm, textvariable=self.email_var, width=28).grid(row=0, column=1, pady=5, sticky="we")
        ttk.Entry(frm, textvariable=self.pwd_var, width=28, show="*").grid(row=1, column=1, pady=5, sticky="we")
        ttk.Entry(frm, textvariable=self.room_var, width=28).grid(row=2, column=1, pady=5, sticky="we")

        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, pady=10)
        ttk.Button(btns, text="เข้าสู่ระบบ", command=self.sign_in).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="สมัครผู้ใช้ใหม่", command=self.sign_up).pack(side=tk.LEFT, padx=6)

        self.status = ttk.Label(self, text="สถานะ: offline")
        self.status.grid(row=3, column=0, pady=(10, 20))

    def _do_auth(self, mode: str):
        email = self.email_var.get().strip()
        pwd = self.pwd_var.get().strip()
        room = self.room_var.get().strip()
        if not email or not pwd:
            messagebox.showwarning("แจ้ง", "กรอกอีเมลและรหัสผ่าน")
            return
        if not room:
            messagebox.showwarning("แจ้ง", "กรอก Room ID")
            return
        if not FIREBASE_API_KEY or "FIREBASE_API_KEY" in FIREBASE_API_KEY:
            messagebox.showwarning("Config", "กรุณาตั้งค่า FIREBASE_API_KEY/RTDB_URL ในไฟล์")
            return

        self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        try:
            if mode == "in":
                self.fb.sign_in_email(email, pwd)
            else:
                self.fb.sign_up_email(email, pwd)
        except Exception as e:
            msg = str(e)  # ข้อความดิบจาก Firebase เช่น EMAIL_NOT_FOUND, INVALID_PASSWORD
            # mapping แบบหยาบให้เข้าใจง่าย
            if "EMAIL_NOT_FOUND" in msg:
                thai = "ไม่พบบัญชีนี้ กรุณาใช้ปุ่ม 'สมัครผู้ใช้ใหม่' ก่อน"
            elif "INVALID_PASSWORD" in msg:
                thai = "รหัสผ่านไม่ถูกต้อง"
            elif "WEAK_PASSWORD" in msg:
                thai = "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร"
            elif "INVALID_EMAIL" in msg:
                thai = "รูปแบบอีเมลไม่ถูกต้อง"
            elif "MISSING_PASSWORD" in msg:
                thai = "กรุณากรอกรหัสผ่าน"
            elif "OPERATION_NOT_ALLOWED" in msg:
                thai = "ยังไม่ได้เปิด Email/Password ใน Firebase Console → Authentication"
            else:
                thai = f"ไม่สำเร็จ: {msg}"
            messagebox.showerror("Firebase", thai)
            self.fb = None
            return

        self.fb.start_auto_refresh()
        self.status.config(text=f"สถานะ: online (uid={self.fb.local_uid[:6]}…)")

        # ส่งต่อไปหน้า App
        self.on_auth_success(self.fb, room)

    def sign_in(self):
        self._do_auth("in")

    def sign_up(self):
        self._do_auth("up")

# =====================
# Main App (Frame)
# =====================
class BillSplitApp(ttk.Frame):
    def __init__(self, master, fb: FirebaseRTClient, room_id: str):
        super().__init__(master)
        self.master.title("หารค่าอาหารกับเพื่อน • Tkinter + Firebase")
        self.master.geometry("1120x680")

        self.bill = Bill()
        self.fb = fb
        self.room_id = room_id.strip()
        self._local_change = False
        self._last_remote_ua = None

        self._build_layout()
        self._connect_and_subscribe()
        self.after(3000, self._keep_synced)

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

        # Header cloud
        ttk.Label(left, text=f"Room: {self.room_id}", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        self.cloud_lbl = ttk.Label(left, text="สถานะ: connecting…")
        self.cloud_lbl.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # People
        ttk.Label(left, text="รายชื่อเพื่อน", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6,0))
        self.person_entry = ttk.Entry(left, width=20)
        self.person_entry.grid(row=3, column=0, sticky="w")
        ttk.Button(left, text="เพิ่ม", command=self.add_person).grid(row=3, column=1, padx=5)
        ttk.Button(left, text="ลบที่เลือก", command=self.remove_person).grid(row=3, column=2)
        self.people_list = tk.Listbox(left, height=8, exportselection=False)
        self.people_list.grid(row=4, column=0, columnspan=3, sticky="we", pady=5)

        # Config
        ttk.Label(left, text="ตั้งค่า Service/VAT/Tip", font=("Segoe UI", 11, "bold")).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8,0))
        frm_cfg = ttk.Frame(left)
        frm_cfg.grid(row=6, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_cfg, text="Service %").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_cfg, text="VAT %").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_cfg, text="Tip (บาท)").grid(row=2, column=0, sticky="w")
        self.service_var = tk.StringVar(value="0")
        self.vat_var = tk.StringVar(value="0")
        self.tip_var = tk.StringVar(value="0")
        ttk.Entry(frm_cfg, textvariable=self.service_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.vat_var, width=10).grid(row=1, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.tip_var, width=10).grid(row=2, column=1, padx=5)
        ttk.Button(left, text="อัปเดตค่า Config", command=self.update_config).grid(row=7, column=0, columnspan=3, sticky="we", pady=5)

        # Item Form
        ttk.Label(left, text="เพิ่มรายการอาหาร", font=("Segoe UI", 11, "bold")).grid(row=8, column=0, columnspan=3, sticky="w", pady=(8,0))
        frm_item = ttk.Frame(left)
        frm_item.grid(row=9, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_item, text="ชื่อเมนู").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_item, text="ราคา (บาท)").grid(row=1, column=0, sticky="w")
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
        btns = ttk.Frame(left)
        btns.grid(row=10, column=0, columnspan=3, sticky="we", pady=5)
        ttk.Button(btns, text="เพิ่มรายการ", command=self.add_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="ลบรายการที่เลือก", command=self.remove_selected_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # Items Table
        ttk.Label(right, text="รายการทั้งหมด", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.table_cols = ("idx", "name", "price", "payer", "count", "participants", "mode", "per_head", "weights")
        self.table = ttk.Treeview(right, columns=self.table_cols, show="headings", height=12, selectmode="browse")
        headings = {
            "idx": "#", "name": "เมนู", "price": "ราคา (บาท)", "payer": "ผู้จ่าย",
            "count": "คนร่วม", "participants": "รายชื่อผู้ร่วมกิน",
            "mode": "โหมดหาร", "per_head": "ต่อหัว/เมนู (บาท)", "weights": "น้ำหนัก"
        }
        widths = {"idx": 40, "name": 200, "price": 110, "payer": 110, "count": 65,
                  "participants": 300, "mode": 90, "per_head": 130, "weights": 160}
        anchors = {"idx": "e", "name": "w", "price": "e", "payer": "w", "count": "e",
                   "participants": "w", "mode": "center", "per_head": "e", "weights": "w"}
        for k in self.table_cols:
            self.table.heading(k, text=headings[k], command=lambda c=k: self._sort_by(c))
            self.table.column(k, width=widths[k], anchor=anchors[k], stretch=False)

        try:
            self.table.tag_configure("odd", background="#fafafa")
            self.table.tag_configure("even", background="#f2f4f7")
            self.table.tag_configure("child", foreground="#555555")
        except Exception:
            pass

        self.table.grid(row=1, column=0, sticky="nsew")
        scr = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scr.set)
        scr.grid(row=1, column=1, sticky="ns")

        # Summary
        ttk.Label(right, text="สรุปผล", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w", pady=(10,0))
        self.output = tk.Text(right, height=12)
        self.output.grid(row=3, column=0, sticky="nsew")
        btn_bottom = ttk.Frame(right)
        btn_bottom.grid(row=4, column=0, sticky="we", pady=6)
        ttk.Button(btn_bottom, text="คำนวณ/อัปเดตสรุป", command=self.refresh_summary).pack(side=tk.LEFT)
        ttk.Button(btn_bottom, text="คัดลอกสรุป", command=self.copy_summary).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="บันทึกบิล (JSON)", command=self.save_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="โหลดบิล (JSON)", command=self.load_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="Export โอน (CSV)", command=self.export_transfers_csv).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="ล้างทั้งหมด", command=self.reset_all).pack(side=tk.LEFT, padx=6)

    # ---------- Helper Methods ----------
    def _refresh_people_widgets(self):
        names = list(self.bill.people.keys())
        self.payer_combo["values"] = names
        self.participants_list.delete(0, tk.END)
        for n in names:
            self.participants_list.insert(tk.END, n)

    def toggle_all_participants(self):
        if self.all_var.get():
            if self.participants_list.size() > 0:
                self.participants_list.select_set(0, tk.END)
        else:
            self.participants_list.select_clear(0, tk.END)

    # ---------- Firebase wiring ----------
    def _connect_and_subscribe(self):
        try:
            self.fb.patch(f"rooms/{self.room_id}/members/{self.fb.local_uid}", {"joinedAt": int(time.time())})
            data = self.fb.get(f"bills/{self.room_id}")
            if data:
                self.bill = Bill.from_dict(data)
                self._render_all_from_bill()
                if isinstance(data, dict):
                    self._last_remote_ua = data.get("updatedAt")
        except Exception:
            pass

        def on_event(ev):
            if self._local_change:
                return
            try:
                full = self.fb.get(f"bills/{self.room_id}")
                if not isinstance(full, dict):
                    return
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

    def _push_bill(self):
        if not (self.fb and self.room_id):
            return
        try:
            self._local_change = True
            data = self.bill.to_dict()
            data["lastEditBy"] = self.fb.local_uid
            self.fb.put(f"bills/{self.room_id}", data)
            self._last_remote_ua = data["updatedAt"]
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))

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

    # ---------- Table helpers ----------
    def _compute_scale(self) -> float:
        subtotal = sum(i.price for i in self.bill.items)
        if subtotal <= 0:
            return 1.0
        svc = subtotal * (self.bill.service_pct / 100.0)
        vat = (subtotal + svc) * (self.bill.vat_pct / 100.0)
        total = subtotal + svc + vat + self.bill.tip
        return total / subtotal

    def _format_weights(self, it: Item) -> str:
        if not it.weights:
            return "-"
        return ", ".join(f"{p}={v:g}" for p, v in it.weights.items())

    def _per_head_for_item(self, it: Item) -> float:
        scale = self._compute_scale()
        if not it.participants:
            return 0.0
        if it.weights:
            totw = sum(it.weights[p] for p in it.participants)
            return it.price * scale / totw
        else:
            return (it.price * scale) / len(it.participants)

    def _item_shares(self, it: Item) -> Dict[str, float]:
        scale = self._compute_scale()
        shares = {}
        if not it.participants:
            return shares
        if it.weights:
            totw = sum(it.weights[p] for p in it.participants)
            for p in it.participants:
                shares[p] = (it.price * scale) * (it.weights[p] / totw)
        else:
            each = (it.price * scale) / len(it.participants)
            for p in it.participants:
                shares[p] = each
        return shares

    def _add_item_to_table(self, idx0: int, it: Item):
        rowvals = (
            idx0 + 1,
            it.name,
            f"{it.price:,.2f}",
            it.payer,
            len(it.participants),
            ", ".join(it.participants),
            "น้ำหนัก" if it.weights else "เท่ากัน",
            f"{self._per_head_for_item(it):,.2f}",
            self._format_weights(it),
        )
        tag = "odd" if (idx0 % 2 == 0) else "even"
        parent_id = self.table.insert("", tk.END, values=rowvals, tags=(tag,))
        shares = self._item_shares(it)
        for p in it.participants:
            cvals = ("", f"• {p}", "", "", "", "", "", f"{shares.get(p, 0.0):,.2f}", "")
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

    # ---------- Local Save/Load/Copy/Export ----------
    def copy_summary(self):
        text = self.output.get("1.0", tk.END).strip()
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
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
            messagebox.showinfo("CSV", "ไม่มีรายการโอน เคลียร์หมดแล้ว")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not path: return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["from", "to", "amount"])
            for t in txs:
                w.writerow([t["from"], t["to"], f'{t["amount"]:.2f}'])
        messagebox.showinfo("CSV", f"ส่งออกแล้ว: {path}")

    # ---------- People / Items / Config Events ----------
    def add_person(self):
        name = self.person_entry.get().strip()
        if not name:
            messagebox.showwarning("เตือน", "กรุณากรอกชื่อเพื่อน")
            return
        try:
            self.bill.add_person(name)
            self.person_entry.delete(0, tk.END)
            self.people_list.insert(tk.END, name)
            self._refresh_people_widgets()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_person(self):
        sel = self.people_list.curselection()
        if not sel:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกชื่อเพื่อนที่จะลบ")
            return
        name = self.people_list.get(sel[0])
        try:
            self.bill.remove_person(name)
            self.people_list.delete(sel[0])
            self._refresh_people_widgets()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ลบไม่ได้", str(e))

    def update_config(self):
        def _to_float(s):
            s = (s or "0").strip()
            return float(s) if s else 0.0
        try:
            self.bill.service_pct = _to_float(self.service_var.get())
            self.bill.vat_pct = _to_float(self.vat_var.get())
            self.bill.tip = _to_float(self.tip_var.get())
            messagebox.showinfo("สำเร็จ", "อัปเดตค่าบริการ/VAT/Tip แล้ว")
            self.refresh_summary()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def _get_selected_participants(self) -> List[str]:
        if self.all_var.get():
            return list(self.bill.people.keys())
        sel = self.participants_list.curselection()
        return [self.participants_list.get(i) for i in sel]

    def add_item(self):
        name = self.item_name.get().strip()
        price_raw = self.item_price.get().strip()
        payer = self.payer_combo.get().strip()
        parts = self._get_selected_participants()
        if not name:
            messagebox.showwarning("เตือน", "กรุณากรอกชื่อเมนู")
            return
        if not price_raw:
            messagebox.showwarning("เตือน", "กรุณากรอกราคา")
            return
        if not payer:
            messagebox.showwarning("เตือน", "กรุณาเลือกผู้จ่ายก่อน")
            return
        if not parts:
            messagebox.showwarning("เตือน", "กรุณาเลือกผู้ร่วมกิน")
            return
        try:
            price = float(price_raw)
        except Exception:
            messagebox.showerror("ผิดพลาด", "กรอกจำนวนเงินให้ถูกต้อง")
            return
        weights = None
        if self.use_weights.get():
            weights = {}
            for p in parts:
                while True:
                    w = simpledialog.askstring("น้ำหนักส่วนแบ่ง", f"weight ของ {p} (ตัวเลข > 0):", parent=self)
                    if w is None:
                        return
                    try:
                        fv = float(w)
                        if fv <= 0:
                            raise ValueError
                        weights[p] = fv
                        break
                    except Exception:
                        messagebox.showwarning("เตือน", "ใส่ตัวเลข > 0 นะ")
        try:
            self.bill.add_item(Item(name=name, price=price, payer=payer, participants=parts, weights=weights))
            self.item_name.delete(0, tk.END)
            self.item_price.delete(0, tk.END)
            self.use_weights.set(False)
            self.refresh_summary()
            self._rebuild_table()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_selected_item(self):
        sel = self.table.selection()
        if not sel:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกรายการที่จะลบ")
            return
        rid = sel[0]
        parent = self.table.parent(rid) or rid
        vals = self.table.item(parent, "values")
        try:
            idx1 = int(vals[0])
        except Exception:
            messagebox.showerror("ผิดพลาด", "ไม่พบดัชนีรายการ")
            return
        idx0 = idx1 - 1
        self.bill.remove_item_at(idx0)
        self._rebuild_table()
        self.refresh_summary()
        self._push_bill()

    # ---------- Render summary ----------
    def _render_all_from_bill(self):
        self.people_list.delete(0, tk.END)
        for n in self.bill.people:
            self.people_list.insert(tk.END, n)
        self._refresh_people_widgets()
        self.service_var.set(str(self.bill.service_pct))
        self.vat_var.set(str(self.bill.vat_pct))
        self.tip_var.set(str(self.bill.tip))
        self._rebuild_table()
        self.refresh_summary()

    def reset_all(self):
        if messagebox.askyesno("ยืนยัน", "ล้างข้อมูลทั้งหมด?"):
            self.bill = Bill()
            self.people_list.delete(0, tk.END)
            self.table.delete(*self.table.get_children())
            self.output.delete(1.0, tk.END)
            self._refresh_people_widgets()
            self.service_var.set("0")
            self.vat_var.set("0")
            self.tip_var.set("0")
            self.item_name.delete(0, tk.END)
            self.item_price.delete(0, tk.END)
            self.payer_combo.set("")
            self.participants_list.selection_clear(0, tk.END)
            self.all_var.set(False)
            self.use_weights.set(False)
            self._push_bill()

    def refresh_summary(self):
        try:
            subtotal, svc, vat, total = self.bill._totals()
            should = self.bill.summary_costs()
            paid = self.bill.paid_map()
            net = self.bill.net_balance()
            txs = self.bill.settle_transactions()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))
            return

        def money(x): return f"{x:,.2f} บาท"

        self.output.delete(1.0, tk.END)
        self.output.insert(tk.END, "สรุปร้าน/บิล\n")
        self.output.insert(tk.END, f"  Subtotal: {money(subtotal)}\n")
        self.output.insert(tk.END, f"  Service {self.bill.service_pct:.2f}%: {money(svc)}\n")
        self.output.insert(tk.END, f"  VAT {self.bill.vat_pct:.2f}%: {money(vat)}\n")
        self.output.insert(tk.END, f"  Tip: {money(self.bill.tip)}\n")
        self.output.insert(tk.END, f"  Total: {money(total)}\n\n")

        self.output.insert(tk.END, "ควรจ่าย (รวม service/VAT/ทิป ตามสัดส่วนการกิน)\n")
        for n in self.bill.people:
            self.output.insert(tk.END, f"  - {n}: {money(should.get(n, 0.0))}\n")
        self.output.insert(tk.END, "\nจ่ายไปแล้ว\n")
        for n in self.bill.people:
            self.output.insert(tk.END, f"  - {n}: {money(paid.get(n, 0.0))}\n")
        self.output.insert(tk.END, "\nดุลสุทธิ (บวก=ควรได้รับ, ลบ=ควรจ่าย)\n")
        for n in self.bill.people:
            self.output.insert(tk.END, f"  - {n}: {money(net.get(n, 0.0))}\n")
        self.output.insert(tk.END, "\nรายการชำระกัน (ลดจำนวนธุรกรรมแบบ greedy)\n")
        if not txs:
            self.output.insert(tk.END, "  เคลียร์แล้ว ไม่ต้องโอนกัน 🎉\n")
        else:
            for t in txs:
                self.output.insert(tk.END, f"  - {t['from']} → {t['to']}: {money(t['amount'])}\n")

# =====================
# App Controller (สลับหน้า)
# =====================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bill Split • Login + App")
        self.geometry("1120x680")
        # Theme (optional)
        try:
            self.call("source", "azure.tcl")
            ttk.Style().theme_use("azure")
        except Exception:
            pass

        self.current_frame: Optional[ttk.Frame] = None
        self.show_login()

    def show_login(self):
        if self.current_frame:
            self.current_frame.destroy()
        self.current_frame = LoginPage(self, self.on_auth_success)
        self.current_frame.pack(fill="both", expand=True, padx=10, pady=10)

    def on_auth_success(self, fb_client: FirebaseRTClient, room_id: str):
        if self.current_frame:
            self.current_frame.destroy()
        self.current_frame = BillSplitApp(self, fb_client, room_id)
        self.current_frame.pack(fill="both", expand=True)

# -------------------- main --------------------
def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
