# split_bill_all_in_one_login_separated.py

# ------------------------------------------------------------
# ✓ หน้า Login แยกจากหน้าใช้งาน
# ✓ Firebase Auth (Email/Password) + Username + Public profile
# ✓ ห้องถูกสร้างด้วยเลขสุ่มโดยระบบ (owner เท่านั้นเชิญสมาชิก)
# ✓ รายชื่อห้อง: แสดงเฉพาะห้องที่ user เป็นสมาชิก
# ✓ Room Picker แบบป๊อปอัพ (สร้าง/เลือกห้องด้วยปุ่ม)
# ✓ RTDB streaming (SSE) + polling สำรอง
# ✓ เก็บ payer/participants เป็น UID แต่แสดงเป็น username
# ✓ เพิ่มฟีเจอร์ Small Wins (เป้าหมายเล็กๆ)
# ------------------------------------------------------------

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json, threading, time, requests, random, string
from datetime import datetime, timedelta

try:
    from sseclient import SSEClient  # type: ignore
except Exception:
    SSEClient = None  # ถ้าไม่มีจะใช้ polling

# =====================
# Firebase Config
# =====================
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"

# =====================
# Bill Engine (ใช้ UID)
# =====================
@dataclass
class Person:
    name: str  # UID

@dataclass
class Item:
    name: str
    price: float
    payer: str              # UID
    participants: List[str] # [UID]
    weights: Optional[Dict[str, float]] = None  # {UID: weight}

@dataclass
class Bill:
    people: Dict[str, Person] = field(default_factory=dict)
    items: List[Item] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    def add_person(self, uid: str):
        uid = uid.strip()
        if not uid: raise ValueError("UID ว่างไม่ได้")
        if uid in self.people: return
        self.people[uid] = Person(name=uid)

    def remove_person(self, uid: str):
        if uid in self.people:
            for it in self.items:
                if it.payer == uid or uid in it.participants:
                    raise ValueError("ลบไม่ได้: มีรายการที่เกี่ยวข้องกับคนนี้")
            del self.people[uid]

    def add_item(self, item: Item):
        if item.payer not in self.people: raise ValueError(f"ไม่พบผู้จ่าย (UID): {item.payer}")
        for p in item.participants:
            if p not in self.people: raise ValueError(f"ไม่พบผู้ร่วมกิน (UID): {p}")
        if item.price <= 0: raise ValueError("ราคา item ต้อง > 0")
        if item.weights:
            w = {k: float(v) for k, v in item.weights.items() if k in item.participants}
            if not w: raise ValueError("weights ว่าง/ไม่ตรงกับผู้ร่วมกิน")
            if any(v <= 0 for v in w.values()): raise ValueError("ทุก weight ต้อง > 0")
            item.weights = w
        self.items.append(item)

    def remove_item_at(self, idx: int):
        if 0 <= idx < len(self.items): self.items.pop(idx)

    def _totals(self):
        subtotal = sum(i.price for i in self.items)
        svc = subtotal * (self.service_pct / 100.0)
        vat = (subtotal + svc) * (self.vat_pct / 100.0)
        total = subtotal + svc + vat + self.tip
        return subtotal, svc, vat, total

    def summary_costs(self) -> Dict[str, float]:
        if not self.items: return {uid: 0.0 for uid in self.people}
        subtotal, svc, vat, total = self._totals()
        if subtotal == 0: return {uid: 0.0 for uid in self.people}
        raw = defaultdict(float)
        for it in self.items:
            if it.weights:
                totw = sum(it.weights[p] for p in it.participants)
                for p in it.participants:
                    raw[p] += it.price * (it.weights[p] / totw)
            else:
                each = it.price / len(it.participants)
                for p in it.participants: raw[p] += each
        scale = total / subtotal
        return {p: raw.get(p, 0.0) * scale for p in self.people}

    def paid_map(self) -> Dict[str, float]:
        paid = defaultdict(float)
        for it in self.items:
            paid[it.payer] += it.price
        subtotal, svc, vat, total = self._totals()
        extra = svc + vat + self.tip
        if subtotal > 0 and extra > 0:
            for uid in paid:
                paid[uid] += extra * (paid[uid] / subtotal)
        for uid in self.people:
            paid[uid] = paid.get(uid, 0.0)
        return dict(paid)

    def net_balance(self) -> Dict[str, float]:
        should = self.summary_costs()
        paid = self.paid_map()
        net = {uid: round(paid.get(uid,0.0)-should.get(uid,0.0), 2) for uid in self.people}
        drift = round(sum(net.values()), 2)
        if drift != 0 and net:
            first = next(iter(net))
            net[first] = round(net[first] - drift, 2)
        return net

    def settle_transactions(self) -> List[Dict[str, float]]:
        net = self.net_balance()
        cr = [[u,a] for u,a in net.items() if a>0]
        db = [[u,-a] for u,a in net.items() if a<0]
        cr.sort(key=lambda x:x[1], reverse=True)
        db.sort(key=lambda x:x[1], reverse=True)
        i=j=0; tx=[]
        while i<len(db) and j<len(cr):
            dname, damt = db[i]; cname, camt = cr[j]
            pay = round(min(damt,camt),2)
            if pay>0:
                tx.append({"from": dname, "to": cname, "amount": pay})
                damt = round(damt-pay,2); camt = round(camt-pay,2)
            db[i][1]=damt; cr[j][1]=camt
            if damt==0: i+=1
            if camt==0: j+=1
        return tx

    def to_dict(self):
        return {
            "people": list(self.people.keys()),
            "items": [{"name":it.name,"price":it.price,"payer":it.payer,
                       "participants":it.participants,"weights":it.weights} for it in self.items],
            "service_pct": self.service_pct, "vat_pct": self.vat_pct, "tip": self.tip,
            "updatedAt": time.time(),
        }

    @classmethod
    def from_dict(cls, data: dict):
        b = cls()
        for uid in data.get("people", []): b.add_person(uid)
        b.service_pct = float(data.get("service_pct", 0))
        b.vat_pct     = float(data.get("vat_pct", 0))
        b.tip         = float(data.get("tip", 0))
        for it in data.get("items", []):
            b.add_item(Item(name=it["name"], price=float(it["price"]),
                            payer=it["payer"], participants=list(it["participants"]),
                            weights=it.get("weights")))
        return b

# =====================
# Firebase REST Client (+ Room helpers)
# =====================
class FirebaseRTClient:
    ERROR_MAP = {
        "EMAIL_NOT_FOUND": "ไม่พบบัญชีอีเมลนี้",
        "INVALID_PASSWORD": "รหัสผ่านไม่ถูกต้อง",
        "USER_DISABLED": "บัญชีถูกปิดใช้งาน",
        "EMAIL_EXISTS": "อีเมลนี้ถูกใช้งานแล้ว",
        "INVALID_EMAIL": "รูปแบบอีเมลไม่ถูกต้อง",
        "OPERATION_NOT_ALLOWED": "ยังไม่เปิดใช้งาน Email/Password ใน Firebase Auth",
        "WEAK_PASSWORD : Password should be at least 6 characters": "รหัสผ่านต้องยาวอย่างน้อย 6 ตัว",
        "MISSING_PASSWORD": "กรุณากรอกรหัสผ่าน",
    }

    def __init__(self, api_key: str, rtdb_url: str):
        self.api_key = api_key
        self.rtdb_url = rtdb_url.rstrip("/")
        self.id_token = None
        self.refresh_token = None
        self.local_uid = None
        self._stop_stream = False

    def _post_json(self, url: str, payload: dict) -> dict:
        r = requests.post(url, json=payload)
        try:
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            msg = ""
            try:
                j = r.json(); msg = j.get("error", {}).get("message", "")
            except Exception: pass
            human = self.ERROR_MAP.get(msg, msg or str(e))
            raise ValueError(human)

    # Auth
    def sign_in_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token, self.refresh_token, self.local_uid = d["idToken"], d["refreshToken"], d["localId"]; return d

    def sign_up_email(self, email: str, password: str):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token, self.refresh_token, self.local_uid = d["idToken"], d["refreshToken"], d["localId"]; return d

    # Token refresh
    def refresh_id_token(self):
        if not self.refresh_token: return
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"
        r = requests.post(url, data={"grant_type":"refresh_token","refresh_token":self.refresh_token})
        r.raise_for_status(); d = r.json()
        self.id_token, self.refresh_token, self.local_uid = d["id_token"], d["refresh_token"], d["user_id"]

    def start_auto_refresh(self, every_sec=50*60):
        def loop():
            while True:
                time.sleep(every_sec)
                try: self.refresh_id_token()
                except: pass
        threading.Thread(target=loop, daemon=True).start()

    # REST base
    def _auth(self):
        if not self.id_token: raise RuntimeError("Not authenticated")
        return {"auth": self.id_token}
    def get(self, path:str):
        url=f"{self.rtdb_url}/{path}.json"; r=requests.get(url, params=self._auth(), timeout=30); r.raise_for_status(); return r.json()
    def put(self, path:str, obj):
        url=f"{self.rtdb_url}/{path}.json"; r=requests.put(url, params=self._auth(), json=obj, timeout=30); r.raise_for_status(); return r.json()
    def patch(self, path:str, obj):
        url=f"{self.rtdb_url}/{path}.json"; r=requests.patch(url, params=self._auth(), json=obj, timeout=30); r.raise_for_status(); return r.json()
    def post(self, path:str, obj):
        url=f"{self.rtdb_url}/{path}.json"; r=requests.post(url, params=self._auth(), json=obj, timeout=30); r.raise_for_status(); return r.json()
    def delete(self, path:str):
        url=f"{self.rtdb_url}/{path}.json"; r=requests.delete(url, params=self._auth(), timeout=30); r.raise_for_status(); return r.json()

    # ---------- Username / Profile ----------
    @staticmethod
    def _norm_uname(u: str) -> str:
        u = (u or "").strip().lower()
        if not u: raise ValueError("username ว่างไม่ได้")
        for bad in ['.', '#', '$', '[', ']', '/']:
            if bad in u: raise ValueError("username มีอักขระต้องห้าม: . # $ [ ] /")
        return u
    def reserve_username(self, username: str):
        return self.put(f"usernames/{self._norm_uname(username)}", self.local_uid)
    def uid_from_username(self, username: str) -> Optional[str]:
        try: return self.get(f"usernames/{self._norm_uname(username)}")
        except requests.HTTPError: return None
    def save_profile(self, username: str, display_name: str):
        data = {"username": self._norm_uname(username),
                "displayName": display_name or username,
                "updatedAt": int(time.time())}
        return self.put(f"public_profiles/{self.local_uid}", data)
    def get_profile(self, uid: str) -> Optional[dict]:
        try: return self.get(f"public_profiles/{uid}")
        except requests.HTTPError: return None

    # ---------- Rooms (secure by membership) ----------
    @staticmethod
    def gen_room_id() -> str:
        alpha = string.ascii_uppercase + string.digits
        return "R-" + "".join(random.choice(alpha) for _ in range(7))

    def create_room(self) -> str:
        room_id = self.gen_room_id()
        now = int(time.time())
        self.put(f"rooms/{room_id}", {
            "ownerUid": self.local_uid,
            "createdAt": now,
            "members": { self.local_uid: {"role": "owner", "invitedBy": self.local_uid, "joinedAt": now} },
        })
        self.patch(f"rooms_by_user/{self.local_uid}", { room_id: True })
        
        # สร้างบิล (ครั้งแรก) พร้อมกับเพิ่ม owner เข้าไปในรายชื่อ people
        initial_bill = Bill()
        initial_bill.add_person(self.local_uid)
        self.put(f"bills/{room_id}", initial_bill.to_dict())

        # สร้าง small_wins ว่าง (ครั้งแรก)
        self.put(f"small_wins/{room_id}", {})
        return room_id

    def add_member(self, room_id: str, target_uid: str, invited_by: Optional[str] = None):
        now = int(time.time())
        self.patch(f"rooms/{room_id}/members/{target_uid}",
                   {"role": "member", "invitedBy": invited_by or self.local_uid, "joinedAt": now})
        self.patch(f"rooms_by_user/{target_uid}", { room_id: True })

    def list_my_rooms(self) -> List[str]:
        mapping = self.get(f"rooms_by_user/{self.local_uid}") or {}
        return sorted(list(mapping.keys()))

    def is_member(self, room_id: str, uid: Optional[str] = None) -> bool:
        uid = uid or self.local_uid
        m = self.get(f"rooms/{room_id}/members/{uid}")
        return bool(m)

    def get_room_owner(self, room_id: str) -> Optional[str]:
        r = self.get(f"rooms/{room_id}/ownerUid")
        return r if isinstance(r, str) else None

    # Streaming
    def stream(self, path: str, on_event: Callable):
        if not self.id_token: raise RuntimeError("Not authenticated")
        url = f"{self.rtdb_url}/{path}.json"; self._stop_stream = False

        def run_sse():
            while not self._stop_stream:
                try:
                    msgs = SSEClient(url, params={"auth": self.id_token})
                    for msg in msgs:
                        if self._stop_stream: break
                        if msg.event in ("put","patch"):
                            try:
                                data = json.loads(msg.data); on_event(data)
                            except: pass
                except:
                    try: self.refresh_id_token()
                    except: pass
                    time.sleep(2)

        def run_poll():
            last=None
            while not self._stop_stream:
                try:
                    data = requests.get(url, params={"auth": self.id_token}, timeout=30).json()
                    if data is not None and data != last:
                        on_event({"path": "/", "data": data}); last = data
                except:
                    try: self.refresh_id_token()
                    except: pass
                time.sleep(3)

        threading.Thread(target=(run_sse if SSEClient else run_poll), daemon=True).start()

    def stop_stream(self): self._stop_stream = True


# =====================
# Room Picker Dialog
# =====================
class RoomPickerDialog(tk.Toplevel):
    """หน้าต่างเลือกห้องจาก rooms_by_user/<uid> พร้อมปุ่มสร้าง/เข้า/คัดลอก"""
    def __init__(self, master, fb: 'FirebaseRTClient', on_pick: Callable[[str], None], on_create: Callable[[], str]):
        super().__init__(master)
        self.fb = fb
        self.on_pick = on_pick
        self.on_create = on_create

        self.title("เลือกห้องของฉัน")
        self.geometry("420x420")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        wrap = ttk.Frame(self); wrap.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(wrap, text="ห้องของฉัน", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        self.listbox = tk.Listbox(wrap, height=12, exportselection=False)
        self.listbox.pack(fill="both", expand=True, pady=(6, 8))

        btns = ttk.Frame(wrap); btns.pack(fill="x")
        ttk.Button(btns, text="รีเฟรช", command=self.refresh).pack(side="left")
        ttk.Button(btns, text="สร้างห้องใหม่", command=self._create).pack(side="left", padx=6)
        ttk.Button(btns, text="เข้าห้อง", command=self._enter).pack(side="left", padx=6)
        ttk.Button(btns, text="คัดลอกรหัส", command=self._copy).pack(side="right")

        self.refresh()

    def refresh(self):
        self.listbox.delete(0, tk.END)
        try:
            rooms = self.fb.list_my_rooms()
            for rid in rooms:
                owner = self.fb.get_room_owner(rid)
                me = self.fb.local_uid
                role = "owner" if owner == me else "member"
                self.listbox.insert(tk.END, f"{rid}   ({role})")
        except Exception:
            pass

    def _selected_room(self) -> Optional[str]:
        sel = self.listbox.curselection()
        if not sel: return None
        text = self.listbox.get(sel[0])
        return text.split()[0]

    def _enter(self):
        rid = self._selected_room()
        if not rid:
            messagebox.showinfo("เลือกห้อง", "กรุณาเลือกห้องก่อน"); return
        self.on_pick(rid)
        self.destroy()

    def _copy(self):
        rid = self._selected_room()
        if not rid:
            messagebox.showinfo("คัดลอก", "กรุณาเลือกห้องก่อน"); return
        self.clipboard_clear(); self.clipboard_append(rid)
        messagebox.showinfo("คัดลอกแล้ว", f"คัดลอก {rid} แล้ว")

    def _create(self):
        rid = self.on_create()
        if rid:
            messagebox.showinfo("สร้างห้องแล้ว", f"เลขห้อง: {rid}\n(เชิญเพื่อนด้วยปุ่ม \"เชิญเพื่อนเข้าห้อง\")")
            self.refresh()


# =====================
# Login Frame
# =====================
class LoginFrame(ttk.Frame):
    def __init__(self, master, on_success: Callable[[FirebaseRTClient], None]):
        super().__init__(master)
        self.on_success = on_success
        self.grid(sticky="nsew", padx=24, pady=24)
        master.title("เข้าสู่ระบบ • Bill Split"); master.geometry("420x320")
        master.columnconfigure(0, weight=1); master.rowconfigure(0, weight=1)

        frm = ttk.Frame(self); frm.pack(expand=True, fill="both")
        ttk.Label(frm, text="เข้าสู่ระบบ", font=("Segoe UI", 14, "bold")).pack(pady=(0,10))

        self.has_account = tk.BooleanVar(value=True)
        r1 = ttk.Frame(frm); r1.pack(fill="x")
        ttk.Radiobutton(r1, text="ฉันมีบัญชีแล้ว (Login)", variable=self.has_account, value=True,
                        command=lambda: self._toggle(True)).pack(side="left")
        ttk.Radiobutton(r1, text="สมัครใหม่ (Sign up)", variable=self.has_account, value=False,
                        command=lambda: self._toggle(False)).pack(side="left", padx=10)

        ttk.Label(frm, text="อีเมล").pack(anchor="w", pady=(10,2))
        self.email = ttk.Entry(frm); self.email.pack(fill="x")

        # password & confirm
        self.pwd_var = tk.StringVar(); self.cpwd_var = tk.StringVar()

        pw_block = ttk.Frame(frm); pw_block.pack(fill="x", pady=(8,0))
        ttk.Label(pw_block, text="รหัสผ่าน").pack(anchor="w")
        row = ttk.Frame(pw_block); row.pack(fill="x")
        self.pwd = ttk.Entry(row, show="*", textvariable=self.pwd_var)
        self.pwd.pack(side="left", fill="x", expand=True)
        self.show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="แสดง", variable=self.show_pw,
                        command=lambda: self.pwd.config(show="" if self.show_pw.get() else "*")).pack(side="left", padx=8)

        self.cpw_frame = ttk.Frame(pw_block)
        ttk.Label(self.cpw_frame, text="ยืนยันรหัสผ่าน").pack(anchor="w", pady=(8,2))
        row2 = ttk.Frame(self.cpw_frame); row2.pack(fill="x")
        self.cpwd = ttk.Entry(row2, show="*", textvariable=self.cpwd_var); self.cpwd.pack(side="left", fill="x", expand=True)
        self.show_cpw = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="แสดง", variable=self.show_cpw,
                        command=lambda: self.cpwd.config(show="" if self.show_cpw.get() else "*")).pack(side="left", padx=8)
        self.cpw_frame.pack_forget()

        ttk.Button(frm, text="ดำเนินการ", command=self.attempt_auth).pack(pady=16)
        for w in (self.email, self.pwd, self.cpwd): w.bind("<Return>", lambda *_: self.attempt_auth())
        self.status = ttk.Label(frm, text="", foreground="#666"); self.status.pack()

    def _toggle(self, is_login: bool):
        if is_login:
            self.cpw_frame.pack_forget(); self.cpwd_var.set(""); self.show_cpw.set(False); self.cpwd.config(show="*")
        else:
            self.cpw_frame.pack(fill="x")

    def attempt_auth(self):
        if not FIREBASE_API_KEY or not FIREBASE_RTDB_URL:
            messagebox.showwarning("Config","กรุณาตั้งค่า FIREBASE_API_KEY / FIREBASE_RTDB_URL"); return
        email = (self.email.get() or "").strip()
        pwd   = (self.pwd_var.get() or "").strip()
        if not email or not pwd:
            messagebox.showwarning("เตือน", "กรอกอีเมลและรหัสผ่าน"); return
        if not self.has_account.get():
            cpwd = (self.cpwd_var.get() or "").strip()
            if len(pwd)<6: messagebox.showwarning("เตือน","รหัสผ่านอย่างน้อย 6 ตัว"); return
            if pwd!=cpwd: messagebox.showwarning("เตือน","รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน"); return

        fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        try:
            fb.sign_in_email(email,pwd) if self.has_account.get() else fb.sign_up_email(email,pwd)
        except Exception as e:
            messagebox.showerror("Firebase", f"{e}"); return
        fb.start_auto_refresh()

        # Ensure username
        prof = fb.get_profile(fb.local_uid) or {}
        if not prof or not prof.get("username"):
            while True:
                uname = simpledialog.askstring("ตั้ง Username","username (ห้ามซ้ำ):", parent=self)
                if not uname: return
                dname = simpledialog.askstring("ชื่อแสดง","ชื่อที่จะแสดง (ว่าง=ใช้ username):", parent=self) or uname
                try:
                    fb.reserve_username(uname); fb.save_profile(uname, dname); break
                except Exception as e:
                    messagebox.showerror("Username", f"ใช้ไม่ได้: {e}\nลองใหม่อีกครั้ง")

        self.status.config(text="สำเร็จ! กำลังเข้าแอพ…")
        self.after(100, lambda: self.on_success(fb))


# =====================
# Main App
# =====================
class BillSplitApp(ttk.Frame):
    def __init__(self, master, fb: FirebaseRTClient):
        super().__init__(master)
        self.fb = fb
        self.bill = Bill()
        self.room_id: Optional[str] = None
        self._local_change = False
        self._last_remote_ua = None
        self.name_cache: Dict[str,str] = {}
        self.people_uids: List[str] = []
        self.label2uid: Dict[str,str] = {}

        master.title("หารค่าอาหาร & เป้าหมายเล็กๆ • Tkinter + Firebase")
        master.geometry("1120x700")
        self.pack(fill=tk.BOTH, expand=True)
        self._build_layout()

        # เปิดตัวเลือกห้องแบบป๊อปอัพ
        self.after(200, self.open_room_picker)

    # ---------- UI ----------
    def _build_layout(self):
        # Top bar for room controls
        top_bar = ttk.Frame(self)
        top_bar.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(top_bar, text="Cloud (Firebase)", font=("Segoe UI", 11, "bold")).pack(side="left", anchor="w")
        self.cloud_lbl = ttk.Label(top_bar, text=f"UID: {self.fb.local_uid[:6]}…")
        self.cloud_lbl.pack(side="left", anchor="w", padx=(6, 12))
        ttk.Button(top_bar, text="เปลี่ยนห้อง", command=self.open_room_picker).pack(side="left")
        ttk.Button(top_bar, text="เชิญเพื่อนเข้าห้อง", command=self.invite_member).pack(side="left", padx=4)
        ttk.Button(top_bar, text="คัดลอกรหัสห้อง", command=self.copy_room_id).pack(side="left")
        ttk.Button(top_bar, text="ออกห้อง", command=self.leave_room).pack(side="left", padx=4)

        # Main content area with Tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        bill_tab = ttk.Frame(self.notebook); self.notebook.add(bill_tab, text="💰 หารบิล")
        sw_tab = ttk.Frame(self.notebook); self.notebook.add(sw_tab, text="🏆 เป้าหมายเล็กๆ (Small Wins)")
        
        self._build_bill_tab(bill_tab)
        self._build_small_wins_tab(sw_tab)

    def _build_bill_tab(self, parent):
        parent.columnconfigure(0, weight=0); parent.columnconfigure(1, weight=1); parent.rowconfigure(0, weight=1)
        left = ttk.Frame(parent); left.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)
        right= ttk.Frame(parent); right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right.rowconfigure(1, weight=1); right.columnconfigure(0, weight=1)

        ttk.Label(left, text="รายชื่อเพื่อน (UID)", font=("Segoe UI", 11, "bold")).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10,0))
        self.person_entry = ttk.Entry(left, width=22); self.person_entry.grid(row=4, column=0, sticky="w")
        ttk.Button(left, text="เพิ่ม (UID/username)", command=self.add_person).grid(row=4, column=1, padx=5)
        self.people_list = tk.Listbox(left, height=8, exportselection=False)
        self.people_list.grid(row=5, column=0, columnspan=3, sticky="we", pady=5)
        ttk.Button(left, text="ลบที่เลือก", command=self.remove_person).grid(row=6, column=0, columnspan=3, sticky="we")

        ttk.Label(left, text="Service/VAT/Tip", font=("Segoe UI", 11, "bold")).grid(row=7, column=0, columnspan=3, sticky="w")
        frm_cfg = ttk.Frame(left); frm_cfg.grid(row=8, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_cfg, text="Service %").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_cfg, text="VAT %").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_cfg, text="Tip (บาท)").grid(row=2, column=0, sticky="w")
        self.service_var = tk.StringVar(value="0"); self.vat_var = tk.StringVar(value="0"); self.tip_var = tk.StringVar(value="0")
        ttk.Entry(frm_cfg, textvariable=self.service_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.vat_var, width=10).grid(row=1, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.tip_var, width=10).grid(row=2, column=1, padx=5)
        ttk.Button(left, text="อัปเดตค่า", command=self.update_config).grid(row=9, column=0, columnspan=3, sticky="we", pady=5)

        ttk.Label(left, text="เพิ่มรายการอาหาร", font=("Segoe UI", 11, "bold")).grid(row=10, column=0, columnspan=3, sticky="w", pady=(10,0))
        frm_item = ttk.Frame(left); frm_item.grid(row=11, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_item, text="ชื่อเมนู").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_item, text="ราคา").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้จ่ายก่อน").grid(row=2, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้ร่วมกิน").grid(row=3, column=0, sticky="nw")
        self.item_name = ttk.Entry(frm_item, width=22); self.item_price = ttk.Entry(frm_item, width=22)
        self.payer_combo = ttk.Combobox(frm_item, values=[], state="readonly", width=20)
        self.participants_list = tk.Listbox(frm_item, selectmode=tk.MULTIPLE, height=6, exportselection=False)
        self.all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_item, text="ทุกคน", variable=self.all_var, command=self.toggle_all_participants).grid(row=4, column=1, sticky="w")
        self.item_name.grid(row=0, column=1, sticky="we", pady=1); self.item_price.grid(row=1, column=1, sticky="we", pady=1)
        self.payer_combo.grid(row=2, column=1, sticky="we", pady=1); self.participants_list.grid(row=3, column=1, sticky="we", pady=1)
        self.use_weights = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_item, text="หารไม่เท่ากัน (weights)", variable=self.use_weights).grid(row=5, column=1, sticky="w", pady=(4,0))

        btns = ttk.Frame(left); btns.grid(row=12, column=0, columnspan=3, sticky="we", pady=6)
        ttk.Button(btns, text="เพิ่มรายการ", command=self.add_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="ลบรายการที่เลือก", command=self.remove_selected_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        ttk.Label(right, text="รายการทั้งหมด", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.table_cols = ("idx","name","price","payer","count","participants","mode","per_head","weights")
        self.table = ttk.Treeview(right, columns=self.table_cols, show="headings", height=14, selectmode="browse")
        heads = {"idx":"#","name":"เมนู","price":"ราคา (บาท)","payer":"ผู้จ่าย","count":"คนร่วม",
                 "participants":"รายชื่อผู้ร่วมกิน","mode":"โหมดหาร","per_head":"ต่อหัว/เมนู (บาท)","weights":"น้ำหนัก"}
        widths={"idx":40,"name":200,"price":110,"payer":110,"count":65,"participants":300,"mode":90,"per_head":130,"weights":160}
        anchors={"idx":"e","name":"w","price":"e","payer":"w","count":"e","participants":"w","mode":"center","per_head":"e","weights":"w"}
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

        ttk.Label(right, text="สรุปผล", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w", pady=(10,0))
        self.output = tk.Text(right, height=12); self.output.grid(row=3, column=0, sticky="nsew")

    def _build_small_wins_tab(self, parent):
        parent.columnconfigure(0, weight=1); parent.rowconfigure(1, weight=1)

        # --- Top frame for creating new goals ---
        add_frame = ttk.LabelFrame(parent, text="ตั้งเป้าหมายใหม่ของฉัน", padding=10)
        add_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        add_frame.columnconfigure(0, weight=1)

        ttk.Label(add_frame, text="เป้าหมาย:").grid(row=0, column=0, sticky="w")
        self.sw_goal_text = ttk.Entry(add_frame)
        self.sw_goal_text.grid(row=1, column=0, sticky="ew", pady=(0, 5))

        ttk.Label(add_frame, text="ทำให้สำเร็จใน (วัน):").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.sw_deadline_days = ttk.Entry(add_frame, width=10)
        self.sw_deadline_days.grid(row=1, column=1, sticky="w", padx=(10, 5))

        ttk.Button(add_frame, text="ตั้งเป้าหมาย", command=self.add_small_win).grid(row=1, column=2)

        # --- Main frame for displaying goals ---
        main_frame = ttk.Frame(parent)
        main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=0)
        main_frame.rowconfigure(0, weight=1); main_frame.columnconfigure(0, weight=1)

        self.sw_cols = ("goal", "owner", "deadline", "nudges", "goal_id", "owner_uid")
        self.sw_table = ttk.Treeview(main_frame, columns=self.sw_cols, show="headings", selectmode="browse")
        
        heads = {"goal":"เป้าหมาย (Goal)", "owner":"เจ้าของ", "deadline":"เดดไลน์", "nudges":"จำนวนสะกิด"}
        widths= {"goal":500, "owner":150, "deadline":150, "nudges":100}
        
        for col, head in heads.items():
            self.sw_table.heading(col, text=head)
            self.sw_table.column(col, width=widths[col], stretch=True)

        # Hide internal data columns
        self.sw_table.column("goal_id", width=0, stretch=False)
        self.sw_table.column("owner_uid", width=0, stretch=False)

        self.sw_table.grid(row=0, column=0, sticky="nsew")
        sw_scr = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.sw_table.yview)
        self.sw_table.configure(yscrollcommand=sw_scr.set)
        sw_scr.grid(row=0, column=1, sticky="ns")
        
        self.sw_table.bind("<<TreeviewSelect>>", self.on_goal_select)

        # --- Bottom frame for actions ---
        action_frame = ttk.Frame(parent)
        action_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        
        self.sw_nudge_btn = ttk.Button(action_frame, text="สะกิดเพื่อน (Nudge)", command=self.nudge_selected_goal, state="disabled")
        self.sw_nudge_btn.pack(side="left")
        
        self.sw_delete_btn = ttk.Button(action_frame, text="ลบเป้าหมายของฉัน", command=self.delete_selected_goal, state="disabled")
        self.sw_delete_btn.pack(side="left", padx=10)


    # ---------- Room choosing ----------
    def open_room_picker(self):
        """เปิดป๊อปอัพเลือกห้อง: สร้าง/เข้าห้อง ด้วยการกดปุ่ม"""
        RoomPickerDialog(self, self.fb, on_pick=self._pick_room, on_create=self._create_room)

    def _pick_room(self, room_id: str):
        if not room_id: return
        try:
            if not self.fb.is_member(room_id):
                messagebox.showerror("สิทธิ์ไม่พอ", "คุณไม่ได้เป็นสมาชิกห้องนี้"); return
            self.room_id = room_id
            owner = self.fb.get_room_owner(room_id)
            role = "owner" if owner == self.fb.local_uid else "member"
            self.cloud_lbl.config(text=f"สถานะ: {role} • Room: {room_id}")
            self.bind_room(room_id)
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def _create_room(self) -> str:
        try:
            rid = self.fb.create_room()
            self.room_id = rid
            self.cloud_lbl.config(text=f"สถานะ: owner • Room: {rid}")
            self.bind_room(rid)
            return rid
        except Exception as e:
            messagebox.showerror("สร้างห้องไม่ได้", str(e))
            return ""

    def copy_room_id(self):
        if not self.room_id:
            messagebox.showinfo("ยังไม่มีห้อง", "โปรดเลือก/สร้างห้องก่อน"); return
        self.clipboard_clear(); self.clipboard_append(self.room_id)
        messagebox.showinfo("คัดลอกแล้ว", f"คัดลอก {self.room_id} แล้ว")

    def leave_room(self):
        if not self.room_id:
            messagebox.showinfo("ยังไม่มีห้อง", "ยังไม่ได้อยู่ในห้อง"); return
        if not messagebox.askyesno("ออกห้อง", "แน่ใจว่าจะออกจากห้องนี้?"):
            return
        try:
            self.room_id = None
            self.bill = Bill()
            self._render_all_from_bill()
            self._render_small_wins(None)
            self.cloud_lbl.config(text=f"UID: {self.fb.local_uid[:6]}… (ยังไม่อยู่ในห้อง)")
        except Exception:
            pass

    def bind_room(self, room_id: str):
        # Bind Bills data
        try:
            if not self.fb.is_member(room_id):
                messagebox.showerror("สิทธิ์ไม่พอ","คุณไม่ได้เป็นสมาชิกห้องนี้"); return
            data = self.fb.get(f"bills/{room_id}")
            if data:
                self.bill = Bill.from_dict(data); self._render_all_from_bill()
                if isinstance(data, dict): self._last_remote_ua = data.get("updatedAt")
        except Exception as e:
            messagebox.showerror("Firebase", f"โหลดข้อมูลบิลไม่สำเร็จ: {e}")

        def on_bill_event(_ev):
            if self._local_change: return
            try:
                full = self.fb.get(f"bills/{room_id}")
                if not isinstance(full, dict): return
                ua = full.get("updatedAt")
                if ua is not None and ua == self._last_remote_ua: return
                new_bill = Bill.from_dict(full)
            except Exception:
                return
            def apply():
                self._last_remote_ua = ua; self.bill = new_bill; self._render_all_from_bill()
            self.after(0, apply)

        # Bind Small Wins data
        def on_sw_event(ev):
            if self._local_change: return
            try:
                full_sw_data = self.fb.get(f"small_wins/{self.room_id}")
            except Exception:
                return
            
            self.after(0, lambda: self._render_small_wins(full_sw_data))

        try:
            self.fb.stream(f"bills/{room_id}", on_bill_event)
            self.fb.stream(f"small_wins/{room_id}", on_sw_event)
            # Initial load for small wins
            sw_data = self.fb.get(f"small_wins/{room_id}")
            self._render_small_wins(sw_data)
        except Exception as e:
            print(f"Error starting stream: {e}")


    # ---------- Room Invite (owner only) ----------
    def invite_member(self):
        if not self.room_id:
            messagebox.showwarning("ยังไม่ได้เลือกห้อง","โปรดเลือก/สร้างห้องก่อน"); return
        owner = self.fb.get_room_owner(self.room_id)
        if owner != self.fb.local_uid:
            messagebox.showwarning("เฉพาะเจ้าของห้อง", "คุณไม่ใช่เจ้าของห้องนี้"); return

        key = simpledialog.askstring("เชิญเพื่อน", "กรอก username หรือ UID:", parent=self)
        if not key: return

        # แปลง username -> UID ถ้าจำเป็น
        target_uid = None
        if len(key) < 28:  # น่าจะเป็น username
            target_uid = self.fb.uid_from_username(key)
            if not target_uid:
                messagebox.showerror("ไม่พบ", f"ไม่พบ username: {key}"); return
        else:
            target_uid = key

        try:
            self.fb.add_member(self.room_id, target_uid, invited_by=self.fb.local_uid)
            messagebox.showinfo("สำเร็จ", f"เชิญเข้าห้องแล้ว: {target_uid[:6]}…")
        except Exception as e:
            messagebox.showerror("เชิญไม่ได้", str(e))

    # ---------- Helpers ----------
    def _label_for(self, uid: str) -> str:
        if uid in self.name_cache: return self.name_cache[uid]
        label = uid[:6]
        try:
            prof = self.fb.get_profile(uid)
            if prof: label = prof.get("username") or prof.get("displayName") or label
        except Exception:
            pass
        self.name_cache[uid] = label
        return label

    # ---------- Bill Splitting Logic ----------
    def _refresh_people_widgets(self):
        self.people_uids = list(self.bill.people.keys())
        labels=[]; self.label2uid={}
        for uid in self.people_uids:
            lab = self._label_for(uid); labels.append(lab); self.label2uid[lab]=uid
        self.payer_combo["values"] = labels
        self.participants_list.delete(0, tk.END)
        for uid in self.people_uids: self.participants_list.insert(tk.END, self._label_for(uid))
        self.people_list.delete(0, tk.END)
        for uid in self.people_uids: self.people_list.insert(tk.END, f"{self._label_for(uid)}  ({uid[:6]}…)")

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
        scale = self._compute_scale(); shares={}
        if not it.participants: return shares
        if it.weights:
            totw = sum(it.weights[p] for p in it.participants)
            for p in it.participants: shares[self._label_for(p)] = (it.price*scale)*(it.weights[p]/totw)
        else:
            each = (it.price*scale)/len(it.participants)
            for p in it.participants: shares[self._label_for(p)] = each
        return shares

    def _add_item_to_table(self, idx0: int, it: Item):
        row=(idx0+1, it.name, f"{it.price:,.2f}", self._label_for(it.payer),
             len(it.participants), ", ".join(self._label_for(u) for u in it.participants),
             "น้ำหนัก" if it.weights else "เท่ากัน", f"{self._per_head_for_item(it):,.2f}", self._format_weights(it))
        tag = "odd" if (idx0%2==0) else "even"
        pid = self.table.insert("", tk.END, values=row, tags=(tag,))
        for lab, money in self._item_shares(it).items():
            self.table.insert(pid, tk.END, values=("", f"• {lab}", "", "", "", "", "", f"{money:,.2f}", ""), tags=("child",))

    def _rebuild_table(self):
        self.table.delete(*self.table.get_children())
        for i, it in enumerate(self.bill.items): self._add_item_to_table(i, it)

    def _apply_zebra(self):
        roots = self.table.get_children("")
        for i, rid in enumerate(roots):
            self.table.item(rid, tags=("odd" if (i%2==0) else "even",))

    def _sort_by(self, col: str, reverse: Optional[bool]=None):
        col_index = self.table_cols.index(col)
        parents = list(self.table.get_children(""))
        def key_of(rid):
            v = self.table.item(rid,"values")[col_index]
            if col in {"idx","price","count","per_head"}:
                try: return float(str(v).replace(",",""))
                except: return 0.0
            return str(v).lower()
        if reverse is None: reverse = getattr(self,"_sort_rev_"+col, False)
        parents.sort(key=key_of, reverse=reverse); setattr(self,"_sort_rev_"+col, not reverse)
        for pos, rid in enumerate(parents): self.table.move(rid,"",pos)
        self._apply_zebra()

    def _push_bill(self):
        if not self.room_id: return
        try:
            self._local_change = True
            data = self.bill.to_dict(); data["lastEditBy"] = self.fb.local_uid
            self.fb.put(f"bills/{self.room_id}", data); self._last_remote_ua = data["updatedAt"]
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))

    def _render_config_vars(self):
        """อัปเดตค่าในช่องกรอก Service/VAT/Tip จากข้อมูล Bill ปัจจุบัน"""
        self.service_var.set(f"{self.bill.service_pct:g}")
        self.vat_var.set(f"{self.bill.vat_pct:g}")
        self.tip_var.set(f"{self.bill.tip:g}")

    def _render_all_from_bill(self):
        """แก้ไขให้ render ทุกส่วนของ UI ที่เกี่ยวกับบิล"""
        self._render_config_vars()
        self._refresh_people_widgets()
        self._rebuild_table()
        self.refresh_summary()

    def add_person(self):
        key = self.person_entry.get().strip()
        if not key: messagebox.showwarning("เตือน","กรอก UID หรือ username"); return
        uid = None
        try: uid = self.fb.uid_from_username(key) if len(key)<28 else key
        except: uid=None
        if not uid:
            messagebox.showerror("ไม่พบ", f"ไม่พบ username: {key} หรือ UID สั้นเกินไป"); return
        try:
            self.bill.add_person(uid); self.person_entry.delete(0,tk.END)
            self.name_cache[uid] = self._label_for(uid)
            self._render_all_from_bill(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_person(self):
        sel = self.people_list.curselection()
        if not sel: messagebox.showinfo("แจ้ง","เลือกเพื่อนก่อน"); return
        uid = self.people_uids[sel[0]]
        try:
            self.bill.remove_person(uid); self._render_all_from_bill(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ลบไม่ได้", str(e))

    def update_config(self):
        def f(s): s=(s or "0").strip(); return float(s) if s else 0.0
        try:
            self.bill.service_pct = f(self.service_var.get())
            self.bill.vat_pct     = f(self.vat_var.get())
            self.bill.tip         = f(self.tip_var.get())
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
            messagebox.showwarning("เตือน","กรอกข้อมูลให้ครบ"); return
        payer_uid = self.label2uid.get(payer_label, payer_label)
        try: price = float(price_raw)
        except: messagebox.showerror("ผิดพลาด","ราคาไม่ถูกต้อง"); return

        weights = None
        if self.use_weights.get():
            weights={}
            for uid in parts:
                while True:
                    w = simpledialog.askstring("weight", f"weight ของ {self._label_for(uid)} (>0):", parent=self)
                    if w is None: return
                    try:
                        v=float(w)
                        if v<=0: raise ValueError
                        weights[uid]=v; break
                    except: messagebox.showwarning("เตือน","ใส่ตัวเลข > 0")
        try:
            self.bill.add_item(Item(name=name, price=price, payer=payer_uid, participants=parts, weights=weights))
            self.item_name.delete(0,tk.END); self.item_price.delete(0,tk.END); self.use_weights.set(False)
            self._rebuild_table(); self.refresh_summary(); self._push_bill()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"เกิดข้อผิดพลาด: {e}")

    def remove_selected_item(self):
        sel = self.table.selection()
        if not sel: messagebox.showinfo("แจ้ง","เลือกรายการก่อน"); return
        rid = sel[0]; parent = self.table.parent(rid) or rid
        vals = self.table.item(parent,"values")
        try: idx1 = int(vals[0])
        except: messagebox.showerror("ผิดพลาด","ไม่พบดัชนีรายการ"); return
        self.bill.remove_item_at(idx1-1); self._rebuild_table(); self.refresh_summary(); self._push_bill()

    def refresh_summary(self):
        self.output.delete("1.0", tk.END)
        if not self.bill.people:
            return

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

    # ---------- Small Wins Logic ----------
    def _render_small_wins(self, goals_data: Optional[Dict]):
        self.sw_table.delete(*self.sw_table.get_children())
        if not goals_data or not isinstance(goals_data, dict):
            return
            
        sorted_goals = sorted(goals_data.items(), key=lambda item: item[1].get('createdAt', 0), reverse=True)

        for goal_id, goal in sorted_goals:
            owner_uid = goal.get("ownerUid", "N/A")
            owner_name = self._label_for(owner_uid)
            
            deadline_ts = goal.get("deadline", 0)
            deadline_str = datetime.fromtimestamp(deadline_ts).strftime('%Y-%m-%d %H:%M') if deadline_ts > 0 else "N/A"
            
            nudges = goal.get("nudges", {})
            nudge_count = len(nudges) if isinstance(nudges, dict) else 0

            row_values = (
                goal.get("goalText", ""),
                owner_name,
                deadline_str,
                nudge_count,
                goal_id,
                owner_uid
            )
            self.sw_table.insert("", "end", values=row_values)
        
        self.on_goal_select(None)

    def add_small_win(self):
        if not self.room_id:
            messagebox.showwarning("เตือน", "กรุณาเลือกห้องก่อน"); return

        goal_text = self.sw_goal_text.get().strip()
        if not goal_text:
            messagebox.showwarning("เตือน", "กรุณาใส่ข้อความเป้าหมาย"); return

        try:
            days = int(self.sw_deadline_days.get().strip())
            if days <= 0: raise ValueError
        except (ValueError, TypeError):
            messagebox.showwarning("เตือน", "กรุณาใส่จำนวนวันเป็นตัวเลขที่มากกว่า 0"); return

        deadline_dt = datetime.now() + timedelta(days=days)
        deadline_ts = int(deadline_dt.timestamp())

        payload = {
            "goalText": goal_text,
            "ownerUid": self.fb.local_uid,
            "createdAt": int(time.time()),
            "deadline": deadline_ts,
            "nudges": {}
        }
        try:
            self._local_change = True
            self.fb.post(f"small_wins/{self.room_id}", payload)
            self.sw_goal_text.delete(0, tk.END)
            self.sw_deadline_days.delete(0, tk.END)
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถสร้างเป้าหมายได้: {e}")
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))

    def on_goal_select(self, event):
        sel = self.sw_table.selection()
        if not sel:
            self.sw_nudge_btn.config(state="disabled")
            self.sw_delete_btn.config(state="disabled")
            return

        item = self.sw_table.item(sel[0])
        values = item['values']
        if not values: return

        owner_uid_idx = self.sw_cols.index("owner_uid")
        owner_uid = values[owner_uid_idx]

        is_my_goal = (owner_uid == self.fb.local_uid)
        
        self.sw_delete_btn.config(state="normal" if is_my_goal else "disabled")
        self.sw_nudge_btn.config(state="disabled" if is_my_goal else "normal")

    def get_selected_goal_info(self) -> Optional[Dict]:
        sel = self.sw_table.selection()
        if not sel: return None
        
        item = self.sw_table.item(sel[0])
        values = item['values']
        if not values: return None
        
        goal_id_idx = self.sw_cols.index("goal_id")
        owner_uid_idx = self.sw_cols.index("owner_uid")

        return {
            "id": values[goal_id_idx],
            "owner_uid": values[owner_uid_idx]
        }
        
    def nudge_selected_goal(self):
        if not self.room_id: return
        info = self.get_selected_goal_info()
        if not info:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกเป้าหมายที่จะสะกิด"); return
        
        goal_id = info["id"]
        path = f"small_wins/{self.room_id}/{goal_id}/nudges/{self.fb.local_uid}"
        try:
            self._local_change = True
            self.fb.put(path, int(time.time()))
            messagebox.showinfo("สำเร็จ", "ส่งสะกิดให้เพื่อนแล้ว!")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถสะกิดได้: {e}")
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))
            
    def delete_selected_goal(self):
        if not self.room_id: return
        info = self.get_selected_goal_info()
        if not info:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกเป้าหมายที่จะลบ"); return
        
        if not messagebox.askyesno("ยืนยัน", "แน่ใจว่าจะลบเป้าหมายนี้?"):
            return
            
        goal_id = info["id"]
        path = f"small_wins/{self.room_id}/{goal_id}"
        try:
            self._local_change = True
            self.fb.delete(path)
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถลบได้: {e}")
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))


# =====================
# App bootstrap
# =====================
def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "azure" in style.theme_names():
            style.theme_use("azure")
            style.configure("TNotebook.Tab", padding=[10, 5], font=("Segoe UI", 10))
            style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    def open_app(fb: FirebaseRTClient):
        for w in list(root.children.values()):
            try: w.destroy()
            except: pass
        BillSplitApp(root, fb)

    LoginFrame(root, on_success=open_app)
    root.mainloop()


# =====================
# Main
# =====================
if __name__ == "__main__":
    main()