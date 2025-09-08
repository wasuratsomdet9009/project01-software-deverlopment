# split_bill_all_in_one.py
# ------------------------------------------------------------
# Logic คำนวณ + Tkinter UI + Firebase (Auth + RTDB Streaming/Polling)
# ✔ แชร์ข้อมูลเรียลไทม์ (SSE) + โพลลิ่งสำรอง
# ✔ กันลูปสะท้อน + เทียบ updatedAt + ต่ออายุโทเคน
# ✔ People/payer/participants เก็บเป็น UID จริง แสดงเป็น username
# ✔ ตารางละเอียดพร้อม sort และแถวลูกแจกแจงต่อคน
# ------------------------------------------------------------

from dataclasses import dataclass, field
from typing import List, Dict, Optional
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
# Firebase Config — ใส่ของโปรเจกต์คุณ
# =====================
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"

# =====================
# Core Logic (Bill Engine) — เก็บ UID เป็นคีย์
# =====================
@dataclass
class Person:
    name: str  # จะเก็บเป็น UID

@dataclass
class Item:
    name: str
    price: float
    payer: str                   # UID ผู้จ่ายก่อน
    participants: List[str]      # รายชื่อ UID ผู้ร่วมกิน
    weights: Optional[Dict[str, float]] = None  # key ต้องเป็น UID

@dataclass
class Bill:
    people: Dict[str, Person] = field(default_factory=dict)  # key = UID
    items: List[Item] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    # ---------- People ----------
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

    # ---------- Items ----------
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
                raise ValueError("weights ว่าง หรือไม่ตรงกับผู้ร่วมกิน (UID)")
            if any(v <= 0 for v in w.values()):
                raise ValueError("ทุก weight ต้อง > 0")
            item.weights = w
        self.items.append(item)

    def remove_item_at(self, idx: int):
        if 0 <= idx < len(self.items):
            self.items.pop(idx)

    # ---------- Calc ----------
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
            if damt == 0:
                i += 1
            if camt == 0:
                j += 1
        return txs

    # ---------- Serialize ----------
    def to_dict(self):
        return {
            "people": list(self.people.keys()),  # list of UIDs
            "items": [
                {
                    "name": it.name,
                    "price": it.price,
                    "payer": it.payer,                       # UID
                    "participants": it.participants,         # [UID]
                    "weights": it.weights,                   # {UID: w}
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
                name=it["name"], price=float(it["price"]), payer=it["payer"],
                participants=list(it["participants"]), weights=it.get("weights")
            ))
        return b

# =====================
# Firebase REST + Streaming client
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

    # ---------- Auth ----------
    def sign_in_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        res = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
        res.raise_for_status()
        data = res.json()
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.local_uid = data["localId"]
        return data

    def sign_up_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        res = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
        res.raise_for_status()
        data = res.json()
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.local_uid = data["localId"]
        return data

    # ---------- Token refresh ----------
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

    # ---------- RTDB REST ----------
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

    # ---------- Username/Profile helpers ----------
    def _norm_uname(self, username: str) -> str:
        u = (username or "").strip().lower()
        if not u:
            raise ValueError("username ว่างไม่ได้")
        for bad in ['.', '#', '$', '[', ']', '/']:
            if bad in u:
                raise ValueError("username มีอักขระต้องห้าม: . # $ [ ] /")
        return u

    def reserve_username(self, username: str):
        uname = self._norm_uname(username)
        # เขียนเป็นสตริง uid โดยใช้ PUT
        return self.put(f"usernames/{uname}", self.local_uid)

    def uid_from_username(self, username: str) -> Optional[str]:
        uname = self._norm_uname(username)
        try:
            return self.get(f"usernames/{uname}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                raise RuntimeError("ไม่มีสิทธิ์อ่าน /usernames — ตรวจ Rules Realtime Database")
            raise

    def save_profile(self, username: str, display_name: str):
        data = {
            "username": self._norm_uname(username),
            "displayName": display_name or username,
            "updatedAt": int(time.time())
        }
        return self.put(f"public_profiles/{self.local_uid}", data)

    def get_profile(self, uid: str) -> Optional[dict]:
        try:
            return self.get(f"public_profiles/{uid}")
        except requests.HTTPError:
            return None

    # ---------- Streaming (SSE or Polling) ----------
    def stream(self, path: str, on_event):
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
# Tkinter UI
# =====================
class BillSplitApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("หารค่าอาหารกับเพื่อน • Tkinter + Firebase")
        self.master.geometry("1120x680")
        self.pack(fill=tk.BOTH, expand=True)

        self.bill = Bill()
        self.fb: Optional[FirebaseRTClient] = None
        self.room_id: Optional[str] = None
        self._local_change = False
        self._last_remote_ua = None

        # แคช uid→username/displayName
        self.name_cache: Dict[str, str] = {}
        # mapping สำหรับคอมโบ/ลิสต์
        self.people_uids: List[str] = []    # ลำดับใน Listbox
        self.label2uid: Dict[str, str] = {} # Combobox label → UID

        self._build_layout()

    # ---------- UI Layout ----------
    def _build_layout(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)

        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Cloud
        ttk.Label(left, text="Cloud Sync (Firebase)", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(left, text="เชื่อม Firebase / Login", command=self.connect_firebase).grid(row=1, column=0, sticky="we")
        self.cloud_lbl = ttk.Label(left, text="สถานะ: offline")
        self.cloud_lbl.grid(row=1, column=1, columnspan=2, sticky="w", padx=6)

        # People
        ttk.Label(left, text="รายชื่อเพื่อน (เก็บเป็น UID)", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10,0))
        self.person_entry = ttk.Entry(left, width=22)
        self.person_entry.grid(row=3, column=0, sticky="w")
        ttk.Button(left, text="เพิ่ม (UID/username)", command=self.add_person).grid(row=3, column=1, padx=5)
        ttk.Button(left, text="ลบที่เลือก", command=self.remove_person).grid(row=3, column=2)
        self.people_list = tk.Listbox(left, height=8, exportselection=False)
        self.people_list.grid(row=4, column=0, columnspan=3, sticky="we", pady=5)

        # Config
        ttk.Label(left, text="ตั้งค่า Service/VAT/Tip", font=("Segoe UI", 11, "bold")).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10,0))
        frm_cfg = ttk.Frame(left); frm_cfg.grid(row=6, column=0, columnspan=3, sticky="we")
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

        # Item form
        ttk.Label(left, text="เพิ่มรายการอาหาร", font=("Segoe UI", 11, "bold")).grid(row=8, column=0, columnspan=3, sticky="w", pady=(10,0))
        frm_item = ttk.Frame(left); frm_item.grid(row=9, column=0, columnspan=3, sticky="we")
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

        btns = ttk.Frame(left); btns.grid(row=10, column=0, columnspan=3, sticky="we", pady=5)
        ttk.Button(btns, text="เพิ่มรายการ", command=self.add_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="ลบรายการที่เลือก", command=self.remove_selected_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # Table
        ttk.Label(right, text="รายการทั้งหมด", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.table_cols = ("idx", "name", "price", "payer", "count", "participants", "mode", "per_head", "weights")
        self.table = ttk.Treeview(right, columns=self.table_cols, show="headings", height=12, selectmode="browse")
        headings = {
            "idx": "#", "name": "เมนู", "price": "ราคา (บาท)", "payer": "ผู้จ่าย",
            "count": "คนร่วม", "participants": "รายชื่อผู้ร่วมกิน",
            "mode": "โหมดหาร", "per_head": "ต่อหัว/เมนู (บาท)", "weights": "น้ำหนัก"
        }
        widths = {"idx": 40, "name": 200, "price":110, "payer":110, "count":65,
                  "participants": 300, "mode":90, "per_head":130, "weights":160}
        anchors = {"idx":"e","name":"w","price":"e","payer":"w","count":"e",
                   "participants":"w","mode":"center","per_head":"e","weights":"w"}
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
        self.table.configure(yscrollcommand=scr.set); scr.grid(row=1, column=1, sticky="ns")

        # Summary
        ttk.Label(right, text="สรุปผล", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w", pady=(10,0))
        self.output = tk.Text(right, height=12); self.output.grid(row=3, column=0, sticky="nsew")
        btn_bottom = ttk.Frame(right); btn_bottom.grid(row=4, column=0, sticky="we", pady=6)
        ttk.Button(btn_bottom, text="คำนวณ/อัปเดตสรุป", command=self.refresh_summary).pack(side=tk.LEFT)
        ttk.Button(btn_bottom, text="คัดลอกสรุป", command=self.copy_summary).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="บันทึกบิล (JSON)", command=self.save_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="โหลดบิล (JSON)", command=self.load_bill_local).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="Export โอน (CSV)", command=self.export_transfers_csv).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_bottom, text="ล้างทั้งหมด", command=self.reset_all).pack(side=tk.LEFT, padx=6)

    # ---------- helper: UID → label ----------
    def _label_for(self, uid: str) -> str:
        if uid in self.name_cache:
            return self.name_cache[uid]
        label = uid[:6]  # default
        if self.fb:
            prof = self.fb.get_profile(uid)
            if prof and isinstance(prof, dict):
                label = prof.get("username") or prof.get("displayName") or label
        self.name_cache[uid] = label
        return label

    def _refresh_people_widgets(self):
        # payer combobox
        self.people_uids = list(self.bill.people.keys())
        labels = []
        self.label2uid = {}
        for uid in self.people_uids:
            lab = self._label_for(uid)
            labels.append(lab)
            self.label2uid[lab] = uid
        self.payer_combo["values"] = labels

        # participants listbox
        self.participants_list.delete(0, tk.END)
        for uid in self.people_uids:
            self.participants_list.insert(tk.END, self._label_for(uid))

        # left list
        self.people_list.delete(0, tk.END)
        for uid in self.people_uids:
            self.people_list.insert(tk.END, f"{self._label_for(uid)}  ({uid[:6]}…)")

    def toggle_all_participants(self):
        if self.all_var.get():
            self.participants_list.select_set(0, tk.END)
        else:
            self.participants_list.select_clear(0, tk.END)

    # ---------- table formatting ----------
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
        scale = self._compute_scale()
        shares = {}
        if not it.participants: return shares
        if it.weights:
            totw = sum(it.weights[p] for p in it.participants)
            for p in it.participants:
                shares[self._label_for(p)] = (it.price * scale) * (it.weights[p] / totw)
        else:
            each = (it.price * scale) / len(it.participants)
            for p in it.participants:
                shares[self._label_for(p)] = each
        return shares

    def _add_item_to_table(self, idx0: int, it: Item):
        rowvals = (
            idx0 + 1,
            it.name,
            f"{it.price:,.2f}",
            self._label_for(it.payer),
            len(it.participants),
            ", ".join(self._label_for(u) for u in it.participants),
            "น้ำหนัก" if it.weights else "เท่ากัน",
            f"{self._per_head_for_item(it):,.2f}",
            self._format_weights(it),
        )
        tag = "odd" if (idx0 % 2 == 0) else "even"
        parent_id = self.table.insert("", tk.END, values=rowvals, tags=(tag,))
        shares = self._item_shares(it)
        for lab, money in shares.items():
            cvals = ("", f"• {lab}", "", "", "", "", "", f"{money:,.2f}", "")
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
                try: return float(str(v).replace(",", "").replace("บาท", "").strip())
                except Exception: return 0.0
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
        if not FIREBASE_API_KEY or "YOUR_WEB_API_KEY" in FIREBASE_API_KEY:
            messagebox.showwarning("Config", "กรุณาตั้งค่า FIREBASE_API_KEY และ FIREBASE_RTDB_URL ในไฟล์ก่อน")
            return

        choice = messagebox.askquestion("เข้าสู่ระบบ", "มีบัญชีแล้วหรือไม่?\nYes = Login, No = Sign up")
        email = simpledialog.askstring("อีเมล", "อีเมล:", parent=self)
        if email is None: return
        pwd = simpledialog.askstring("รหัสผ่าน", "รหัสผ่าน:", parent=self, show="*")
        if pwd is None: return

        self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        try:
            if choice == "yes":
                self.fb.sign_in_email(email, pwd)
            else:
                self.fb.sign_up_email(email, pwd)
        except Exception as e:
            messagebox.showerror("Firebase", f"ล็อกอิน/สมัครไม่สำเร็จ: {e}")
            self.fb = None
            return

        self.fb.start_auto_refresh()

        # ensure profile + username
        prof = self.fb.get_profile(self.fb.local_uid) or {}
        if not prof or not prof.get("username"):
            while True:
                uname = simpledialog.askstring("ตั้ง Username", "username (ห้ามซ้ำ, ใช้ a-z0-9._- ได้):", parent=self)
                if not uname: return
                dname = simpledialog.askstring("ชื่อแสดง", "ชื่อที่จะแสดง (ว่าง=ใช้ username):", parent=self) or uname
                try:
                    self.fb.reserve_username(uname)
                    self.fb.save_profile(uname, dname)
                    break
                except Exception as e:
                    messagebox.showerror("Username", f"ใช้ไม่ได้: {e}\nลองใหม่")

        # refresh label cache of myself
        self.name_cache[self.fb.local_uid] = (self.fb.get_profile(self.fb.local_uid) or {}).get("username", "me")

        room = simpledialog.askstring("เข้าร่วมห้อง", "Room ID (เช่น classA-2025):", parent=self)
        if not room:
            messagebox.showwarning("แจ้ง", "ต้องใส่ Room ID")
            return
        self.room_id = room.strip()

        # mark member (ต้องผ่าน Rules)
        try:
            self.fb.patch(f"rooms/{self.room_id}/members/{self.fb.local_uid}", {"joinedAt": int(time.time())})
        except Exception as e:
            messagebox.showerror("Firebase", f"เข้าห้องไม่สำเร็จ: {e}")
            return

        # initial load
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
        self._refresh_people_widgets()
        self.service_var.set(str(self.bill.service_pct))
        self.vat_var.set(str(self.bill.vat_pct))
        self.tip_var.set(str(self.bill.tip))
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
            w = csv.writer(f); w.writerow(["from(UID)", "to(UID)", "amount"])
            for t in txs:
                w.writerow([t["from"], t["to"], f'{t["amount"]:.2f}'])
        messagebox.showinfo("CSV", f"ส่งออกแล้ว: {path}")

    # ---------- People / Items / Config Events ----------
    def add_person(self):
        key = self.person_entry.get().strip()
        if not key:
            messagebox.showwarning("เตือน", "กรุณากรอก UID หรือ username"); return

        uid = key
        # เดาว่าเป็น username ถ้าดูสั้นกว่ารหัส UID ปกติ (~28–36)
        if self.fb and len(key) < 28:
            try:
                found = self.fb.uid_from_username(key)
                if found: uid = found
                else:
                    messagebox.showerror("ไม่พบ", f"ไม่พบ username: {key}")
                    return
            except Exception as e:
                messagebox.showerror("Firebase", str(e)); return

        try:
            self.bill.add_person(uid)
            self.person_entry.delete(0, tk.END)
            # เติมแคชชื่อเพื่อแสดงสวย ๆ
            self.name_cache[uid] = self._label_for(uid)
            self._refresh_people_widgets()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_person(self):
        sel = self.people_list.curselection()
        if not sel:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกเพื่อนที่จะลบ"); return
        uid = self.people_uids[sel[0]]
        try:
            self.bill.remove_person(uid)
            self._refresh_people_widgets()
            self._push_bill()
        except Exception as e:
            messagebox.showerror("ลบไม่ได้", str(e))

    def update_config(self):
        def _to_float(s):
            s = (s or "0").strip(); return float(s) if s else 0.0
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
        return [self.people_uids[i] for i in sel]

    def add_item(self):
        name = self.item_name.get().strip()
        price_raw = self.item_price.get().strip()
        payer_label = self.payer_combo.get().strip()
        parts = self._get_selected_participants()

        if not name: messagebox.showwarning("เตือน", "กรุณากรอกชื่อเมนู"); return
        if not price_raw: messagebox.showwarning("เตือน", "กรุณากรอกราคา"); return
        if not payer_label: messagebox.showwarning("เตือน", "กรุณาเลือกผู้จ่ายก่อน"); return
        if not parts: messagebox.showwarning("เตือน", "กรุณาเลือกผู้ร่วมกิน"); return

        payer_uid = self.label2uid.get(payer_label, payer_label)
        try:
            price = float(price_raw)
        except Exception:
            messagebox.showerror("ผิดพลาด", "กรอกจำนวนเงินให้ถูกต้อง"); return

        weights = None
        if self.use_weights.get():
            weights = {}
            for uid in parts:
                while True:
                    w = simpledialog.askstring("น้ำหนักส่วนแบ่ง", f"weight ของ {self._label_for(uid)} (ตัวเลข > 0):", parent=self)
                    if w is None: return
                    try:
                        fv = float(w)
                        if fv <= 0: raise ValueError
                        weights[uid] = fv; break
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
        rid = sel[0]
        parent = self.table.parent(rid) or rid
        vals = self.table.item(parent, "values")
        try:
            idx1 = int(vals[0])
        except Exception:
            messagebox.showerror("ผิดพลาด", "ไม่พบดัชนีรายการ"); return
        self.bill.remove_item_at(idx1 - 1)
        self._rebuild_table(); self.refresh_summary(); self._push_bill()

    def reset_all(self):
        if messagebox.askyesno("ยืนยัน", "ล้างข้อมูลทั้งหมด?"):
            self.bill = Bill()
            self._render_all_from_bill()
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
            self.output.insert(tk.END, f"  - {self._label_for(uid)}: {money(should.get(uid, 0.0))}\n")

        self.output.insert(tk.END, "\nจ่ายไปแล้ว\n")
        for uid in self.bill.people:
            self.output.insert(tk.END, f"  - {self._label_for(uid)}: {money(paid.get(uid, 0.0))}\n")

        self.output.insert(tk.END, "\nดุลสุทธิ (บวก=ควรได้รับ, ลบ=ควรจ่าย)\n")
        for uid in self.bill.people:
            self.output.insert(tk.END, f"  - {self._label_for(uid)}: {money(net.get(uid, 0.0))}\n")

        self.output.insert(tk.END, "\nรายการชำระกัน (ลดจำนวนธุรกรรมแบบ greedy)\n")
        if not txs:
            self.output.insert(tk.END, "  เคลียร์แล้ว ไม่ต้องโอนกัน 🎉\n")
        else:
            for t in txs:
                self.output.insert(tk.END, f"  - {self._label_for(t['from'])} → {self._label_for(t['to'])}: {money(t['amount'])}\n")

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
