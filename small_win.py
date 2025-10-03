# ----------------------------------------------------------------------------------
<<<<<<< HEAD
# Small Wins: Collaborative Goal Tracker (Updated for shared Firebase)
=======
# Small Wins: Collaborative Goal Tracker (เวอร์ชันภาษาไทย)
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
#
# Description:
# โปรแกรมเดสก์ท็อปที่สร้างด้วย Python, Tkinter และ Firebase เพื่อช่วยให้คุณและเพื่อนๆ
# บรรลุเป้าหมายเล็กๆ น้อยๆ ไปด้วยกัน ติดตามความคืบหน้า ส่งการแจ้งเตือน
# และเฉลิมฉลองความสำเร็จในสภาพแวดล้อมการทำงานร่วมกันแบบเรียลไทม์
#
# Features:
<<<<<<< HEAD
# ✔ Real-time data synchronization using Firebase Realtime Database.
# ✔ User authentication (Sign up / Login) - shared with bill splitting app.
# ✔ Create collaborative "Win Rooms" to share goals with friends.
# ✔ Add, track, and complete "Small Wins" (goals).
# ✔ Assign tasks to specific friends.
# ✔ Nudge/remind friends to complete their tasks.
# ✔ Visually appealing and user-friendly interface.
=======
# ✔ ซิงโครไนซ์ข้อมูลแบบเรียลไทม์โดยใช้ Firebase Realtime Database
# ✔ การยืนยันตัวตนผู้ใช้ (สมัคร / เข้าสู่ระบบ)
# ✔ สร้าง "ห้องเป้าหมาย" เพื่อแชร์เป้าหมายกับเพื่อน
# ✔ เพิ่ม ติดตาม และทำ "เป้าหมาย" ให้สำเร็จ
# ✔ มอบหมายงานให้เพื่อนที่ระบุได้
# ✔ "สะกิด" หรือเตือนเพื่อนให้ทำงานให้เสร็จ
# ✔ หน้าตาโปรแกรมสวยงามและใช้งานง่าย
# ✔ บันทึกและแสดงเวลาที่สร้าง เวลาที่สำเร็จ และระยะเวลาที่ใช้สำหรับแต่ละเป้าหมาย
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
# ----------------------------------------------------------------------------------

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
import json
import threading
import time
import requests
import re

<<<<<<< HEAD
try:
    from sseclient import SSEClient  # type: ignore
except Exception:
    SSEClient = None  # fallback to polling

# =====================
# Firebase Config — ใช้ฐานข้อมูลเดียวกันกับ Bill Splitting
# =====================
=======
# --- Configuration ---
# Updated to match the bill splitting app's Firebase project
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"

# ===============================================
# DATA MODELS: Representing the application's data
# ===============================================
@dataclass
class SmallWin:
    id: str = field(default_factory=lambda: f"win_{int(time.time() * 1000)}")
    title: str = ""
    description: str = ""
    completed: bool = False
    assignedTo: Optional[str] = None  # User UID
    createdBy: Optional[str] = None   # User UID who created this win
    createdAt: float = field(default_factory=time.time)
    completedAt: Optional[float] = None
    priority: str = "medium"  # low, medium, high
    tags: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "completed": self.completed,
            "assignedTo": self.assignedTo,
            "createdBy": self.createdBy,
            "createdAt": self.createdAt,
            "completedAt": self.completedAt,
            "priority": self.priority,
            "tags": self.tags
        }

    @classmethod
    def from_dict(cls, data: dict):
        win = cls()
        win.id = data.get("id", win.id)
        win.title = data.get("title", "")
        win.description = data.get("description", "")
        win.completed = data.get("completed", False)
        win.assignedTo = data.get("assignedTo")
        win.createdBy = data.get("createdBy")
        win.createdAt = data.get("createdAt", time.time())
        win.completedAt = data.get("completedAt")
        win.priority = data.get("priority", "medium")
        win.tags = data.get("tags", [])
        return win

@dataclass
class WinRoom:
    name: str
    description: str = ""
    members: Dict[str, bool] = field(default_factory=dict)  # {uid: True}
    wins: Dict[str, SmallWin] = field(default_factory=dict)
    createdBy: Optional[str] = None
    updatedAt: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "members": self.members,
            "wins": {win_id: win.to_dict() for win_id, win in self.wins.items()},
            "createdBy": self.createdBy,
            "updatedAt": time.time()
        }

    @classmethod
    def from_dict(cls, data: dict):
        room = cls(name=data.get("name", "Unnamed Room"))
        room.description = data.get("description", "")
        room.members = data.get("members", {})
        room.wins = {win_id: SmallWin.from_dict(win_data) for win_id, win_data in data.get("wins", {}).items()}
        room.createdBy = data.get("createdBy")
        room.updatedAt = data.get("updatedAt", time.time())
        return room

# ===============================================
<<<<<<< HEAD
# FIREBASE CLIENT: Handles communication with Firebase (shared structure)
=======
# FIREBASE CLIENT: Handles communication with Firebase (Upgraded Version)
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
# ===============================================
class FirebaseRTClient:
    def __init__(self, api_key: str, rtdb_url: str):
        self.api_key = api_key
        self.rtdb_url = rtdb_url.rstrip("/")
        self.id_token = None
        self.refresh_token = None
        self.local_uid = None
        self._stop_stream = False
        self._stream_thread = None

<<<<<<< HEAD
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

    def delete(self, path: str):
        url = f"{self.rtdb_url}/{path}.json"
        res = requests.delete(url, params=self._auth_params(), timeout=30)
        res.raise_for_status()
        return res.json()

    # ---------- Username/Profile helpers (shared with bill app) ----------
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
        return self.put(f"usernames/{uname}", self.local_uid)

    def uid_from_username(self, username: str) -> Optional[str]:
        uname = self._norm_uname(username)
        try:
            return self.get(f"usernames/{uname}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                raise RuntimeError("ไม่มีสิทธิ์อ่าน /usernames")
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

    # ---------- Streaming ----------
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
=======
    # ---------- Auth (with better error translation) ----------
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
        """Makes a POST request and translates Firebase errors into readable messages."""
        r = requests.post(url, json=payload)
        try:
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            msg = ""
            try:
                j = r.json()
                raw = j.get("error", {}).get("message", "")
                msg = raw.split(" : ")[0].strip()
            except Exception:
                pass
            human_readable_error = self.ERROR_MAP.get(msg, msg or str(e))
            raise ValueError(human_readable_error)

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

    # REST Database Operations
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

    # Username / Profile Helpers
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

    def get_profile(self, uid: str) -> Optional[UserProfile]:
        try:
            data = self.get(f"public_profiles/{uid}")
            if data:
                return UserProfile(uid=uid, username=data.get('username'), displayName=data.get('displayName'))
        except requests.HTTPError:
            return None
        return None

    # Streaming
    def start_streaming(self, path: str, on_event: Callable):
        if not self.id_token: raise RuntimeError("Not authenticated")
        url = f"{self.rtdb_url}/{path}.json"
        self._stop_stream = False

        def poll_loop():
            last_hash = None
            while not self._stop_stream:
                try:
                    data = requests.get(url, params=self._auth(), timeout=30).json()
                    if data is not None:
                        current_hash = hash(json.dumps(data, sort_keys=True))
                        if last_hash != current_hash:
                            on_event(data)
                            last_hash = current_hash
                except:
                    try: self.refresh_id_token()
                    except: pass
                time.sleep(3)
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a

<<<<<<< Updated upstream
=======
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

>>>>>>> Stashed changes
        self._stream_thread = threading.Thread(target=runner, daemon=True)
        self._stream_thread.start()

<<<<<<< HEAD
    def stop_stream(self):
        self._stop_stream = True
=======
    def stop_streaming(self): 
        self._stop_stream = True
        if self._stream_thread:
            self._stream_thread.join(timeout=1)
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a

# ===============================================
# MAIN APPLICATION (UI): The Tkinter interface
# ===============================================
class SmallWinsApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
<<<<<<< HEAD
        self.master.title("Small Wins - Collaborative Goal Tracker")
        self.master.geometry("1000x700")
=======
        self.master.title("เครื่องมือติดตามเป้าหมาย")
        self.master.geometry("1200x700")
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a

        # --- State Management ---
        self.fb: Optional[FirebaseRTClient] = None
        self.room_id: Optional[str] = None
        self.current_room: Optional[WinRoom] = None
        self.user_cache: Dict[str, str] = {} # uid -> displayName
        self._local_change = False
        self._last_remote_ua = None

        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._create_widgets()
        
        self.login_frame.pack(expand=True, fill="both")
        self.master.title("เข้าสู่ระบบ - Small Wins")
        
    def _create_widgets(self):
<<<<<<< HEAD
        # --- Main Layout ---
        self.main_notebook = ttk.Notebook(self)
        self.login_frame = ttk.Frame(self.main_notebook, padding="20")
        self.app_frame = ttk.Frame(self.main_notebook, padding="10")
        
        self.main_notebook.add(self.login_frame, text="Login")
        self.main_notebook.add(self.app_frame, text="Small Wins")
        self.main_notebook.pack(expand=True, fill="both")
=======
        # --- Main Layout Frames ---
        self.login_frame = ttk.Frame(self, padding="20")
        self.room_selection_frame = ttk.Frame(self, padding="20")
        self.app_frame = ttk.Frame(self, padding="10")
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        self._create_login_widgets()
        self._create_room_selection_widgets()
        self._create_app_widgets()

    def _switch_to_app_view(self):
        self.room_selection_frame.pack_forget()
        self.app_frame.pack(expand=True, fill="both")
        self.master.title(f"ห้อง: {self.room_id} - Small Wins")

    def _switch_to_login_view(self):
        self.room_selection_frame.pack_forget()
        self.app_frame.pack_forget()
        self.login_frame.pack(expand=True, fill="both")
        self.master.title("เข้าสู่ระบบ - Small Wins")

    def _switch_to_room_selection_view(self):
        self.login_frame.pack_forget()
        self.app_frame.pack_forget()
        self.room_selection_frame.pack(expand=True, fill="both")
        self.master.title("เลือกห้อง - Small Wins")

    def _create_login_widgets(self):
<<<<<<< HEAD
        # --- Login/Signup Widgets ---
        login_container = ttk.LabelFrame(self.login_frame, text="เข้าสู่ระบบ Small Wins")
        login_container.pack(expand=True, fill='both')
        
        # Status label
        self.status_label = ttk.Label(login_container, text="กรุณาเข้าสู่ระบบเพื่อใช้งาน", 
                                     font=("Segoe UI", 10))
        self.status_label.pack(pady=10)
        
        # Email
        ttk.Label(login_container, text="อีเมล:").pack(anchor='w', padx=20)
        self.email_entry = ttk.Entry(login_container, width=40)
        self.email_entry.pack(pady=5, padx=20)
=======
        login_container = ttk.LabelFrame(self.login_frame, text="เข้าสู่ระบบ หรือ สมัครสมาชิก")
        login_container.pack(expand=True)
        
        ttk.Label(login_container, text="อีเมล:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.email_entry = ttk.Entry(login_container, width=30)
        self.email_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(login_container, text="รหัสผ่าน:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.password_entry = ttk.Entry(login_container, show="*", width=30)
        self.password_entry.grid(row=1, column=1, padx=5, pady=5)
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        # Password
        ttk.Label(login_container, text="รหัสผ่าน:").pack(anchor='w', padx=20)
        self.password_entry = ttk.Entry(login_container, show="*", width=40)
        self.password_entry.pack(pady=5, padx=20)
        
        # Buttons
        btn_frame = ttk.Frame(login_container)
<<<<<<< HEAD
        btn_frame.pack(pady=20)
        ttk.Button(btn_frame, text="เข้าสู่ระบบ", command=self.handle_login).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="สมัครสมาชิก", command=self.handle_signup).pack(side="left", padx=10)
        
        # Instructions
        instructions = ttk.Label(login_container, 
                               text="หมายเหตุ: ใช้บัญชีเดียวกันกับแอปแบ่งค่าอาหาร\nถ้ายังไม่มีบัญชี กรุณาสมัครสมาชิกใหม่",
                               font=("Segoe UI", 9), foreground="gray")
        instructions.pack(pady=10)
        
    def _create_app_widgets(self):
        # --- App Layout ---
        # Left Panel: Room Info & Members
        left_panel = ttk.Frame(self.app_frame, width=280)
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)
=======
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="เข้าสู่ระบบ", command=self.handle_login).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="สมัครสมาชิก", command=self.handle_signup).pack(side="left", padx=5)

    def _create_room_selection_widgets(self):
        container = ttk.LabelFrame(self.room_selection_frame, text="เข้าร่วม หรือ สร้างห้อง")
        container.pack(expand=True)

        join_frame = ttk.Frame(container, padding=10)
        join_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(join_frame, text="รหัสห้อง:").pack(side="left", padx=(0, 5))
        self.join_room_entry = ttk.Entry(join_frame, width=25)
        self.join_room_entry.pack(side="left", expand=True, fill="x")
        ttk.Button(join_frame, text="เข้าร่วมห้อง", command=self.handle_join_room).pack(side="left", padx=(5, 0))

        ttk.Separator(container, orient="horizontal").pack(fill='x', pady=10, padx=20)

        create_frame = ttk.Frame(container, padding=10)
        create_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(create_frame, text="ยังไม่มีห้อง?").pack(side="left")
        ttk.Button(create_frame, text="สร้างห้องใหม่", command=self.handle_create_room).pack(side="left", padx=5)

        logout_button = ttk.Button(self.room_selection_frame, text="ออกจากระบบ", command=self.handle_logout)
        logout_button.pack(side="bottom", pady=20)
        
    def _create_app_widgets(self):
        left_panel = ttk.Frame(self.app_frame, width=250)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        right_panel = ttk.Frame(self.app_frame)
        right_panel.pack(side="right", fill="both", expand=True)

<<<<<<< HEAD
        # --- Left Panel Widgets ---
<<<<<<< Updated upstream
        self.room_info_frame = ttk.LabelFrame(left_panel, text="Room Info")
        self.room_info_frame.pack(fill="x", pady=(0, 10))
        self.room_name_label = ttk.Label(self.room_info_frame, text="ห้อง: N/A", font=("Segoe UI", 10, "bold"))
        self.room_name_label.pack(pady=5)
        ttk.Button(self.room_info_frame, text="ออกจากห้อง", command=self.leave_room).pack(fill="x", padx=5, pady=5)

=======
        # User info
        user_frame = ttk.LabelFrame(left_panel, text="ผู้ใช้งานปัจจุบัน")
        user_frame.pack(fill="x", pady=(0, 10))
        self.user_info_label = ttk.Label(user_frame, text="กำลังโหลด...", font=("Segoe UI", 9))
        self.user_info_label.pack(pady=8)

        # Room controls
        room_control_frame = ttk.LabelFrame(left_panel, text="ควบคุมห้อง")
        room_control_frame.pack(fill="x", pady=(0, 10))
=======
        self.room_info_frame = ttk.LabelFrame(left_panel, text="ข้อมูลห้อง")
        self.room_info_frame.pack(fill="x", pady=(0, 10))
        self.room_name_label = ttk.Label(self.room_info_frame, text="ห้อง: N/A", font=("Segoe UI", 10, "bold"))
        self.room_name_label.pack(pady=5)
        ttk.Button(self.room_info_frame, text="ออกจากห้อง", command=self.leave_room).pack(fill="x", padx=5, pady=5)

>>>>>>> Stashed changes
        self.members_frame = ttk.LabelFrame(left_panel, text="สมาชิก")
        self.members_frame.pack(fill="both", expand=True)
        self.members_list = tk.Listbox(self.members_frame, height=10)
        self.members_list.pack(fill="both", expand=True, padx=5, pady=5)
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        ttk.Button(room_control_frame, text="สร้าง/เข้าร่วมห้องใหม่", 
                  command=self.join_or_create_room, width=25).pack(pady=5)
        ttk.Button(room_control_frame, text="ออกจากห้อง", 
                  command=self.leave_room, width=25).pack(pady=2)

        # Room info
        self.room_info_frame = ttk.LabelFrame(left_panel, text="ข้อมูลห้อง")
        self.room_info_frame.pack(fill="x", pady=(0, 10))
        self.room_name_label = ttk.Label(self.room_info_frame, text="ยังไม่ได้เข้าห้อง", 
                                        font=("Segoe UI", 9, "bold"))
        self.room_name_label.pack(pady=5)
        self.room_desc_label = ttk.Label(self.room_info_frame, text="", 
                                        font=("Segoe UI", 8), foreground="gray")
        self.room_desc_label.pack(pady=(0, 5))

        # Members
        self.members_frame = ttk.LabelFrame(left_panel, text="สมาชิกในห้อง")
        self.members_frame.pack(fill="both", expand=True)
        
        self.members_list = tk.Listbox(self.members_frame, height=8)
        members_scroll = ttk.Scrollbar(self.members_frame, orient="vertical", command=self.members_list.yview)
        self.members_list.configure(yscrollcommand=members_scroll.set)
        self.members_list.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        members_scroll.pack(side="right", fill="y", padx=(0, 5), pady=5)
        
        # Invite controls
        invite_frame = ttk.Frame(left_panel)
        invite_frame.pack(fill="x", pady=5)
        ttk.Label(invite_frame, text="เชิญเพื่อน:", font=("Segoe UI", 8)).pack(anchor="w")
        invite_entry_frame = ttk.Frame(invite_frame)
        invite_entry_frame.pack(fill="x")
        self.invite_entry = ttk.Entry(invite_entry_frame, font=("Segoe UI", 8))
        self.invite_entry.pack(side="left", expand=True, fill="x")
<<<<<<< HEAD
        ttk.Button(invite_entry_frame, text="เชิญ", command=self.invite_member, width=8).pack(side="right", padx=(5,0))

        # --- Right Panel Widgets ---
        # Header
        header_frame = ttk.Frame(right_panel)
        header_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(header_frame, text="Small Wins - เป้าหมายร่วมกัน", 
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        
        # Filters and controls
        filter_frame = ttk.Frame(right_panel)
        filter_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(filter_frame, text="ดู:", font=("Segoe UI", 9)).pack(side="left")
        self.filter_var = tk.StringVar(value="all")
        filter_opts = [("ทั้งหมด", "all"), ("ยังไม่เสร็จ", "pending"), ("เสร็จแล้ว", "completed"), ("ของฉัน", "mine")]
        for text, value in filter_opts:
            ttk.Radiobutton(filter_frame, text=text, variable=self.filter_var, value=value,
                           command=self.apply_filter).pack(side="left", padx=5)

        # Goal Entry Form
        entry_frame = ttk.LabelFrame(right_panel, text="เพิ่มเป้าหมายใหม่")
        entry_frame.pack(fill="x", pady=(0, 10))
<<<<<<< Updated upstream
        ttk.Label(entry_frame, text="เป้าหมายใหม่:").pack(side="left")
        self.win_entry = ttk.Entry(entry_frame)
        self.win_entry.pack(side="left", expand=True, fill="x", padx=5)
        ttk.Button(entry_frame, text="เพิ่มเป้าหมาย", command=self.add_win).pack(side="right")
        
        cols = ("status", "title", "assigned", "created", "completed_time", "duration")
        self.wins_tree = ttk.Treeview(right_panel, columns=cols, show="headings", selectmode="browse")
        self.wins_tree.heading("status", text="สถานะ")
        self.wins_tree.heading("title", text="เป้าหมาย")
        self.wins_tree.heading("assigned", text="ผู้รับผิดชอบ")
        self.wins_tree.heading("created", text="วันที่สร้าง")
        self.wins_tree.heading("completed_time", text="วันที่สำเร็จ")
        self.wins_tree.heading("duration", text="ระยะเวลา")
        
        self.wins_tree.column("status", width=80, anchor="center")
        self.wins_tree.column("title", width=250)
        self.wins_tree.column("assigned", width=120)
=======
        
        # Title
        title_frame = ttk.Frame(entry_frame)
        title_frame.pack(fill="x", padx=5, pady=3)
        ttk.Label(title_frame, text="เป้าหมาย:", width=12).pack(side="left")
        self.win_title_entry = ttk.Entry(title_frame)
        self.win_title_entry.pack(side="left", expand=True, fill="x", padx=5)
        
        # Description
        desc_frame = ttk.Frame(entry_frame)
        desc_frame.pack(fill="x", padx=5, pady=3)
        ttk.Label(desc_frame, text="รายละเอียด:", width=12).pack(side="left")
        self.win_desc_entry = ttk.Entry(desc_frame)
        self.win_desc_entry.pack(side="left", expand=True, fill="x", padx=5)
        
        # Priority and Add button
        control_frame = ttk.Frame(entry_frame)
        control_frame.pack(fill="x", padx=5, pady=5)
        ttk.Label(control_frame, text="ความสำคัญ:", width=12).pack(side="left")
        self.priority_var = tk.StringVar(value="medium")
        priority_combo = ttk.Combobox(control_frame, textvariable=self.priority_var, 
                                     values=["low", "medium", "high"], state="readonly", width=10)
        priority_combo.pack(side="left", padx=5)
        ttk.Button(control_frame, text="เพิ่มเป้าหมาย", command=self.add_win).pack(side="right")
        
        # Goals List (Treeview)
        tree_frame = ttk.Frame(right_panel)
        tree_frame.pack(fill="both", expand=True)
        
        cols = ("status", "priority", "title", "assigned", "created")
        self.wins_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        
        # Configure columns
        self.wins_tree.heading("status", text="สถานะ")
        self.wins_tree.heading("priority", text="ระดับ")
        self.wins_tree.heading("title", text="เป้าหมาย")
        self.wins_tree.heading("assigned", text="มอบหมายให้")
        self.wins_tree.heading("created", text="สร้างโดย")
        
        self.wins_tree.column("status", width=80, anchor="center")
        self.wins_tree.column("priority", width=60, anchor="center")
        self.wins_tree.column("title", width=250)
        self.wins_tree.column("assigned", width=120)
        self.wins_tree.column("created", width=120)
        
        # Scrollbars for tree
        tree_scroll_v = ttk.Scrollbar(tree_frame, orient="vertical", command=self.wins_tree.yview)
        tree_scroll_h = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.wins_tree.xview)
        self.wins_tree.configure(yscrollcommand=tree_scroll_v.set, xscrollcommand=tree_scroll_h.set)
        
        self.wins_tree.pack(side="left", fill="both", expand=True)
        tree_scroll_v.pack(side="right", fill="y")
        tree_scroll_h.pack(side="bottom", fill="x")
        
        # Styling for different priorities and completion status
        self.wins_tree.tag_configure('completed', foreground='gray', font=("Segoe UI", 9, "overstrike"))
        self.wins_tree.tag_configure('high', background='#ffebee')
        self.wins_tree.tag_configure('medium', background='#fff8e1')
        self.wins_tree.tag_configure('low', background='#e8f5e8')
=======
        ttk.Button(invite_frame, text="เชิญ", command=self.invite_member).pack(side="right", padx=(5,0))

        entry_frame = ttk.Frame(right_panel)
        entry_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(entry_frame, text="เป้าหมายใหม่:").pack(side="left")
        self.win_entry = ttk.Entry(entry_frame)
        self.win_entry.pack(side="left", expand=True, fill="x", padx=5)
        ttk.Button(entry_frame, text="เพิ่มเป้าหมาย", command=self.add_win).pack(side="right")
        
        cols = ("status", "title", "assigned", "created", "completed_time", "duration")
        self.wins_tree = ttk.Treeview(right_panel, columns=cols, show="headings", selectmode="browse")
        self.wins_tree.heading("status", text="สถานะ")
        self.wins_tree.heading("title", text="เป้าหมาย")
        self.wins_tree.heading("assigned", text="ผู้รับผิดชอบ")
        self.wins_tree.heading("created", text="วันที่สร้าง")
        self.wins_tree.heading("completed_time", text="วันที่สำเร็จ")
        self.wins_tree.heading("duration", text="ระยะเวลา")
        
        self.wins_tree.column("status", width=80, anchor="center")
        self.wins_tree.column("title", width=250)
        self.wins_tree.column("assigned", width=120)
>>>>>>> Stashed changes
        self.wins_tree.column("created", width=140, anchor="center")
        self.wins_tree.column("completed_time", width=140, anchor="center")
        self.wins_tree.column("duration", width=100, anchor="e")
        
        self.wins_tree.pack(fill="both", expand=True)
        
        self.wins_tree.tag_configure('completed', foreground='gray')
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        action_frame = ttk.Frame(right_panel)
<<<<<<< HEAD
        action_frame.pack(fill="x", pady=10)
        
        left_actions = ttk.Frame(action_frame)
        left_actions.pack(side="left")
        ttk.Button(left_actions, text="เสร็จแล้ว/ยกเลิก", command=self.toggle_win_status).pack(side="left", padx=2)
        ttk.Button(left_actions, text="มอบหมายให้...", command=self.assign_win).pack(side="left", padx=2)
        ttk.Button(left_actions, text="แก้ไข", command=self.edit_win).pack(side="left", padx=2)
        
        right_actions = ttk.Frame(action_frame)
        right_actions.pack(side="right")
        ttk.Button(right_actions, text="เตือนเพื่อน", command=self.nudge_user).pack(side="left", padx=2)
        ttk.Button(right_actions, text="ลบ", command=self.delete_win).pack(side="left", padx=2)

        # Bind double click to view details
        self.wins_tree.bind("<Double-1>", self.show_win_details)

    # --- Helper methods ---
    def get_display_name(self, uid: str) -> str:
        """Get cached display name for UID."""
        if not uid: 
            return "ไม่ระบุ"
        if uid in self.user_cache:
            return self.user_cache[uid]
        if self.fb:
            profile = self.fb.get_profile(uid)
            if profile and isinstance(profile, dict):
                name = profile.get("displayName") or profile.get("username") or uid[:8]
                self.user_cache[uid] = name
                return name
        self.user_cache[uid] = uid[:8]
        return uid[:8]

    # --- Firebase & Logic Handlers ---
    def handle_login(self):
        email = self.email_entry.get().strip()
        password = self.password_entry.get().strip()
        if not email or not password:
            messagebox.showerror("ข้อผิดพลาด", "กรุณากรอกอีเมลและรหัสผ่าน")
            return
=======
        action_frame.pack(fill="x", pady=5)
        ttk.Button(action_frame, text="สลับสถานะ", command=self.toggle_win_status).pack(side="left")
        ttk.Button(action_frame, text="มอบหมายให้...", command=self.assign_win).pack(side="left", padx=5)
        ttk.Button(action_frame, text="สะกิด", command=self.nudge_user).pack(side="left", padx=5)
        ttk.Button(action_frame, text="ลบ", command=self.delete_win).pack(side="right")

    # --- Time Formatting Helpers ---
    def _format_timestamp(self, ts: Optional[float]) -> str:
        if not ts:
            return "-"
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))

    def _format_duration(self, seconds: Optional[float]) -> str:
        if seconds is None or seconds < 0:
            return "-"
        seconds = int(seconds)
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            parts.append(f"{secs}s")
        return " ".join(parts)

    # --- Firebase & Logic Handlers ---
    def _validate_inputs(self):
        email = self.email_entry.get().strip()
        password = self.password_entry.get()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            messagebox.showwarning("ข้อมูลผิดพลาด", "รูปแบบอีเมลไม่ถูกต้อง")
            return None, None
        if not password:
            messagebox.showwarning("ข้อมูลผิดพลาด", "กรุณากรอกรหัสผ่าน")
            return None, None
        return email, password

    def handle_login(self):
        email, password = self._validate_inputs()
        if not email: return
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
            
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        
        try:
<<<<<<< HEAD
            self.status_label.config(text="กำลังเข้าสู่ระบบ...")
            self.fb.sign_in_email(email, password)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("เข้าสู่ระบบไม่สำเร็จ", f"ไม่สามารถเข้าสู่ระบบได้: {e}")
            self.status_label.config(text="เข้าสู่ระบบไม่สำเร็จ")
            
    def handle_signup(self):
        email = self.email_entry.get().strip()
        password = self.password_entry.get().strip()
        if not email or not password:
            messagebox.showerror("ข้อผิดพลาด", "กรุณากรอกอีเมลและรหัสผ่าน")
            return

        username = simpledialog.askstring("สมัครสมาชิก", "เลือก username (ใช้ a-z, 0-9, _, - เท่านั้น):", parent=self)
        if not username: return
        displayName = simpledialog.askstring("สมัครสมาชิก", "ชื่อที่แสดง (หรือเว้นว่างเพื่อใช้ username):", parent=self) or username
=======
            self.fb.sign_in_email(email, password)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("เข้าระบบไม่สำเร็จ", f"ไม่สามารถเข้าระบบได้: {e}")
            
    def handle_signup(self):
        email, password = self._validate_inputs()
        if not email: return

        username = simpledialog.askstring("สมัครสมาชิก", "เลือก username ที่ไม่ซ้ำ:", parent=self)
        if not username: return
        displayName = simpledialog.askstring("สมัครสมาชิก", "ใส่ชื่อที่ต้องการให้แสดง:", parent=self) or username
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
            
        try:
<<<<<<< HEAD
            self.status_label.config(text="กำลังสมัครสมาชิก...")
            self.fb.sign_up_email(email, password)
            self.fb.reserve_username(username)
            self.fb.save_profile(username, displayName)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("สมัครสมาชิกไม่สำเร็จ", f"ไม่สามารถสมัครสมาชิกได้: {e}")
            self.status_label.config(text="สมัครสมาชิกไม่สำเร็จ")
            
    def post_auth_setup(self):
        """Setup after successful authentication."""
        try:
            uid = self.fb.local_uid
            profile = self.fb.get_profile(uid)
            
            if not profile:
                messagebox.showerror("ข้อผิดพลาด", "ไม่พบข้อมูลโปรไฟล์ผู้ใช้")
                return
                
            username = profile.get("username", "ไม่ระบุ")
            display_name = profile.get("displayName", username)
            
            self.user_cache[uid] = display_name
            self.user_info_label.config(text=f"สวัสดี {display_name}!")
            
            # Start token refresh
            self.fb.start_auto_refresh()
            
            # Show app view
            self._show_app_view()
            
            # Ask for room to join
            self.after(500, self.prompt_for_room)
            
        except Exception as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถโหลดข้อมูลผู้ใช้: {e}")

    def prompt_for_room(self):
        """Ask user which room to join or create."""
        room_id = simpledialog.askstring("เข้าร่วมห้อง", 
                                        "กรอก Room ID เพื่อเข้าร่วมหรือสร้างใหม่:", 
                                        parent=self)
        if room_id:
            self.join_room(room_id.strip())

    def join_room(self, room_id: str):
        """Join or create a room."""
        self.room_id = room_id
        
        try:
            # Try to load existing room
            room_data = self.fb.get(f"win_rooms/{self.room_id}")
            
            if room_data and isinstance(room_data, dict):
                # Room exists
                self.current_room = WinRoom.from_dict(room_data)
                # Add current user to members if not already there
                if self.fb.local_uid not in self.current_room.members:
                    self.current_room.members[self.fb.local_uid] = True
                    self._save_room_to_firebase()
            else:
                # Create new room
                room_name = simpledialog.askstring("สร้างห้องใหม่", 
                                                  f"ตั้งชื่อห้อง '{room_id}':", 
                                                  initialvalue=room_id, 
                                                  parent=self)
                if not room_name:
                    return
                    
                room_desc = simpledialog.askstring("รายละเอียดห้อง", 
                                                  "รายละเอียดห้อง (เว้นว่างได้):", 
                                                  parent=self) or ""
                
                self.current_room = WinRoom(name=room_name, description=room_desc)
                self.current_room.members[self.fb.local_uid] = True
                self.current_room.createdBy = self.fb.local_uid
                self._save_room_to_firebase()
            
            # Mark as room member in the rooms collection
            try:
                self.fb.patch(f"rooms/{self.room_id}/members/{self.fb.local_uid}", 
                             {"joinedAt": int(time.time())})
            except Exception:
                pass  # Non-critical if this fails
            
            # Start streaming updates
            self._start_room_streaming()
=======
            self.fb.sign_up_email(email, password)
            self.fb.create_profile(self.fb.local_uid, username, displayName)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("สมัครไม่สำเร็จ", f"ไม่สามารถสร้างบัญชีได้: {e}")
            
    def post_auth_setup(self):
        uid = self.fb.local_uid
        profile = self.fb.get_profile(uid)

        if not profile:
            username = simpledialog.askstring("สร้างโปรไฟล์", "เลือก username ที่ไม่ซ้ำสำหรับบัญชีของคุณ:", parent=self)
            if not username: return 
            displayName = simpledialog.askstring("สร้างโปรไฟล์", "ใส่ชื่อที่ต้องการให้แสดง:", parent=self) or username
            try:
                self.fb.create_profile(uid, username, displayName)
                profile = self.fb.get_profile(uid)
            except Exception as e:
                messagebox.showerror("สร้างโปรไฟล์ไม่สำเร็จ", f"ไม่สามารถสร้างโปรไฟล์ได้: {e}")
                return

        if not profile:
            messagebox.showerror("ผิดพลาด", "ไม่สามารถโหลดหรือสร้างโปรไฟล์ได้ กรุณาเริ่มใหม่")
            return

        self.current_user = profile
        self.user_cache[uid] = profile.displayName
        self.fb.start_auto_refresh()
        self._switch_to_room_selection_view()

    def handle_join_room(self):
        room_id = self.join_room_entry.get().strip()
        if not room_id:
            messagebox.showwarning("ต้องการข้อมูล", "กรุณากรอกรหัสห้องเพื่อเข้าร่วม")
            return
        self._enter_room_flow(room_id, is_new=False)

    def handle_create_room(self):
        room_id = simpledialog.askstring("สร้างห้อง", "กรอกรหัสห้องใหม่ที่ไม่ซ้ำ:", parent=self)
        if not room_id:
            return
        self._enter_room_flow(room_id.strip(), is_new=True)

    def _enter_room_flow(self, room_id, is_new):
        self.room_id = room_id
        room_path = f"small_wins_rooms/{self.room_id}"
        try:
            room_data = self.fb.get(room_path)

            if is_new and room_data:
                messagebox.showerror("ผิดพลาด", f"รหัสห้อง '{self.room_id}' มีอยู่แล้ว กรุณาเลือกชื่ออื่น")
                return

            if not is_new and not room_data:
                messagebox.showerror("ผิดพลาด", f"ไม่พบรหัสห้อง '{self.room_id}'")
                return

            if room_data: # Joining existing room
                self.current_room = WinRoom.from_dict(room_data)
                if self.current_user.uid not in self.current_room.members:
                    self.current_room.members[self.current_user.uid] = True
            else: # Creating new room
                self.current_room = WinRoom(name=self.room_id)
                self.current_room.members[self.current_user.uid] = True
            
            self._save_room_to_firebase()
            self.fb.start_streaming(room_path, self.on_room_update)
            self._switch_to_app_view()
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
            self.update_ui_from_room_data()
            
        except Exception as e:
<<<<<<< HEAD
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถเข้าร่วมห้อง: {e}")
=======
            messagebox.showerror("เข้าห้องไม่สำเร็จ", f"ไม่สามารถเข้าห้องได้: {e}")
            
    def handle_logout(self):
        if self.fb:
            self.fb.stop_streaming()
        # Reset state
        self.fb.id_token = None
        self.fb.refresh_token = None
        self.fb.local_uid = None
        self.current_user = None
        self.room_id = None
        self.current_room = None
        self.user_cache.clear()
        # Clear UI
        self.password_entry.delete(0, tk.END)
        self._switch_to_login_view()
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a

    def join_or_create_room(self):
        """Button handler to join/create room."""
        if self.fb and self.fb.local_uid:
            self.prompt_for_room()
        else:
            messagebox.showerror("ข้อผิดพลาด", "กรุณาเข้าสู่ระบบก่อน")

    def _start_room_streaming(self):
        """Start listening for room updates."""
        if not (self.fb and self.room_id):
            return
            
        def on_event(_ev):
            if self._local_change: 
                return
            try:
                full_data = self.fb.get(f"win_rooms/{self.room_id}")
                if not isinstance(full_data, dict): 
                    return
                ua = full_data.get("updatedAt")
                if ua is not None and ua == self._last_remote_ua:
                    return
                new_room = WinRoom.from_dict(full_data)
                self._last_remote_ua = ua
                self.current_room = new_room
                self.after(0, self.update_ui_from_room_data)
            except Exception as e:
                print(f"Stream error: {e}")

        try:
            self.fb.stream(f"win_rooms/{self.room_id}", on_event)
        except Exception as e:
            print(f"Failed to start streaming: {e}")

    def _save_room_to_firebase(self):
        """Save current room state to Firebase."""
        if not (self.fb and self.current_room and self.room_id):
            return
<<<<<<< HEAD
            
        def save():
            try:
                self._local_change = True
                data = self.current_room.to_dict()
                data["lastEditBy"] = self.fb.local_uid
                self.fb.put(f"win_rooms/{self.room_id}", data)
                self._last_remote_ua = data["updatedAt"]
=======
        
        room_path = f"small_wins_rooms/{self.room_id}"
<<<<<<< Updated upstream
        
        room_path = f"small_wins_rooms/{self.room_id}"
=======
>>>>>>> Stashed changes
        
        def save():
            try:
                self._local_update_flag = True
                self.fb.put(room_path, self.current_room.to_dict())
                time.sleep(1) # Wait a moment for the update to settle
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
            finally:
                self.after(300, lambda: setattr(self, "_local_change", False))

        threading.Thread(target=save, daemon=True).start()

    def update_ui_from_room_data(self):
<<<<<<< HEAD
        """Update UI elements based on current room data."""
        if not self.current_room:
            return
            
        # Update room info
        self.room_name_label.config(text=f"ห้อง: {self.current_room.name}")
        self.room_desc_label.config(text=self.current_room.description or "ไม่มีรายละเอียด")
=======
        if not self.current_room: return
        
        self.room_name_label.config(text=f"ห้อง: {self.current_room.name}")
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        self.members_list.delete(0, tk.END)
        for uid in self.current_room.members.keys():
            display_name = self.get_display_name(uid)
            is_current = " (คุณ)" if uid == self.fb.local_uid else ""
            self.members_list.insert(tk.END, f"{display_name}{is_current}")

<<<<<<< HEAD
        # Update wins tree
        self.apply_filter()

    def apply_filter(self):
        """Apply current filter to wins tree."""
        if not self.current_room:
            return
            
        self.wins_tree.delete(*self.wins_tree.get_children())
        filter_type = self.filter_var.get()
        
        # Get filtered wins
        filtered_wins = []
        for win in self.current_room.wins.values():
            if filter_type == "all":
                filtered_wins.append(win)
            elif filter_type == "pending" and not win.completed:
                filtered_wins.append(win)
            elif filter_type == "completed" and win.completed:
                filtered_wins.append(win)
            elif filter_type == "mine" and (win.createdBy == self.fb.local_uid or win.assignedTo == self.fb.local_uid):
                filtered_wins.append(win)
        
        # Sort by creation time (newest first)
        filtered_wins.sort(key=lambda w: w.createdAt, reverse=True)
        
        # Populate tree
        for win in filtered_wins:
            status = "✅ เสร็จ" if win.completed else "⏳ รอ"
            priority_display = {"low": "🔵", "medium": "🟡", "high": "🔴"}[win.priority]
            assigned_name = self.get_display_name(win.assignedTo) if win.assignedTo else "ไม่ระบุ"
            created_name = self.get_display_name(win.createdBy) if win.createdBy else "ไม่ระบุ"
            
            # Determine tags for styling
            tags = []
            if win.completed:
                tags.append('completed')
            else:
                tags.append(win.priority)
            
            self.wins_tree.insert("", tk.END, iid=win.id, 
                                 values=(status, priority_display, win.title, assigned_name, created_name), 
                                 tags=tuple(tags))
=======
        self.wins_tree.delete(*self.wins_tree.get_children())
        sorted_wins = sorted(self.current_room.wins.values(), key=lambda w: (w.completed, w.createdAt))
        
        for win in sorted_wins:
            status = "✅ สำเร็จ" if win.completed else "⏳ รอทำ"
            assigned_name = self.get_display_name(win.assignedTo) if win.assignedTo else "ไม่ได้มอบหมาย"
            tags = ('completed',) if win.completed else ()

            created_str = self._format_timestamp(win.createdAt)
            completed_str = self._format_timestamp(win.completedAt)
            duration_str = "-"
            if win.completed and win.completedAt and win.createdAt:
                duration_seconds = win.completedAt - win.createdAt
                duration_str = self._format_duration(duration_seconds)

            self.wins_tree.insert("", tk.END, iid=win.id, 
                                  values=(status, win.title, assigned_name, created_str, completed_str, duration_str), 
                                  tags=tags)
            
    def get_display_name(self, uid: str) -> str:
        """Cached lookup for user display names."""
        if not uid: return "N/A"
        if uid in self.user_cache:
            return self.user_cache[uid]
        if self.fb:
            profile = self.fb.get_profile(uid)
            if profile:
                self.user_cache[uid] = profile.displayName
                return profile.displayName
        return uid[:8]
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a

    def add_win(self):
        """Add a new win/goal."""
        if not self.current_room:
            messagebox.showwarning("คำเตือน", "กรุณาเข้าร่วมห้องก่อน")
            return
            
        title = self.win_title_entry.get().strip()
        description = self.win_desc_entry.get().strip()
        
        if not title:
            messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อเป้าหมาย")
            return
        
        new_win = SmallWin(
            title=title,
            description=description,
            priority=self.priority_var.get(),
            createdBy=self.fb.local_uid,
            assignedTo=self.fb.local_uid  # Default assign to self
        )
        
        self.current_room.wins[new_win.id] = new_win
        
        # Clear form
        self.win_title_entry.delete(0, tk.END)
        self.win_desc_entry.delete(0, tk.END)
        self.priority_var.set("medium")
        
        self._save_room_to_firebase()
<<<<<<< HEAD

    def _get_selected_win(self) -> Optional[SmallWin]:
        """Get currently selected win from tree."""
        selected_items = self.wins_tree.selection()
        if not selected_items:
=======
        self.update_ui_from_room_data()

    def _get_selected_win(self) -> Optional[SmallWin]:
        selected_iid = self.wins_tree.focus()
        if not selected_iid:
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
            messagebox.showinfo("แจ้งเตือน", "กรุณาเลือกเป้าหมายจากรายการก่อน")
            return None
        
        win_id = selected_items[0]
        return self.current_room.wins.get(win_id)

    def toggle_win_status(self):
        """Toggle completion status of selected win."""
        win = self._get_selected_win()
        if not win: 
            return
        
        win.completed = not win.completed
        win.completedAt = time.time() if win.completed else None
        
        self._save_room_to_firebase()
<<<<<<< HEAD
=======
        self.update_ui_from_room_data()

    def delete_win(self):
        win = self._get_selected_win()
        if not win: return
        
        if messagebox.askyesno("ยืนยัน", f"คุณแน่ใจหรือไม่ว่าต้องการลบ '{win.title}'?"):
            del self.current_room.wins[win.id]
            self._save_room_to_firebase()
            self.update_ui_from_room_data()
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a

    def assign_win(self):
        """Assign selected win to a member."""
        win = self._get_selected_win()
        if not win: 
            return

<<<<<<< HEAD
        # Create list of members
        members = []
        member_map = {}
        for uid in self.current_room.members.keys():
            display_name = self.get_display_name(uid)
            members.append(display_name)
            member_map[display_name] = uid

        if not members:
            messagebox.showwarning("คำเตือน", "ไม่มีสมาชิกในห้อง")
            return

        # Simple assignment dialog
        member_name = simpledialog.askstring("มอบหมายงาน", 
                                           f"มอบหมาย '{win.title}' ให้:\n" + "\n".join(f"- {m}" for m in members) + 
                                           "\n\nกรอกชื่อสมาชิก:", 
                                           parent=self)
        
        if member_name and member_name in member_map:
            win.assignedTo = member_map[member_name]
            self._save_room_to_firebase()
        elif member_name:
            messagebox.showerror("ข้อผิดพลาด", "ไม่พบสมาชิกที่ระบุ")

    def edit_win(self):
        """Edit selected win."""
=======
        members_map = {self.get_display_name(uid): uid for uid in self.current_room.members}
        
        assign_to_name = simpledialog.askstring("มอบหมายงาน", "กรอกชื่อที่แสดงของสมาชิกที่จะมอบหมายงานให้:", parent=self)
        if assign_to_name and assign_to_name in members_map:
            win.assignedTo = members_map[assign_to_name]
            self._save_room_to_firebase()
            self.update_ui_from_room_data()
        elif assign_to_name:
            messagebox.showerror("ผิดพลาด", "ไม่พบสมาชิกคนดังกล่าว")
    
    def invite_member(self):
        username_to_invite = self.invite_entry.get().strip()
        if not username_to_invite: return
        
        try:
            uid_to_add = self.fb.get_uid_from_username(username_to_invite)
            if uid_to_add:
                if uid_to_add in self.current_room.members:
                    messagebox.showinfo("แจ้งเตือน", f"{username_to_invite} อยู่ในห้องนี้แล้ว")
                else:
                    self.current_room.members[uid_to_add] = True
                    self._save_room_to_firebase()
                    self.update_ui_from_room_data()
                    self.invite_entry.delete(0, tk.END)
            else:
                messagebox.showerror("ผิดพลาด", f"ไม่พบ username '{username_to_invite}'")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถเชิญสมาชิกได้: {e}")
            
    def nudge_user(self):
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        win = self._get_selected_win()
        if not win: 
            return
            
        # Simple edit dialog
        new_title = simpledialog.askstring("แก้ไขเป้าหมาย", "ชื่อใหม่:", 
                                          initialvalue=win.title, parent=self)
        if new_title:
            win.title = new_title.strip()
            
        new_desc = simpledialog.askstring("แก้ไขรายละเอียด", "รายละเอียดใหม่:", 
                                         initialvalue=win.description, parent=self)
        if new_desc is not None:  # Allow empty string
            win.description = new_desc.strip()
            
        self._save_room_to_firebase()

    def delete_win(self):
        """Delete selected win."""
        win = self._get_selected_win()
        if not win: 
            return
        
        if messagebox.askyesno("ยืนยันการลบ", f"ต้องการลบ '{win.title}' หรือไม่?"):
            del self.current_room.wins[win.id]
            self._save_room_to_firebase()

    def nudge_user(self):
        """Send a friendly nudge to assigned user."""
        win = self._get_selected_win()
        if not win: 
            return

        if win.completed:
<<<<<<< HEAD
            messagebox.showinfo("แจ้งเตือน", "เป้าหมายนี้เสร็จแล้ว!")
=======
            messagebox.showinfo("สะกิด", "เป้าหมายนี้สำเร็จแล้ว!")
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
            return
            
        if win.assignedTo:
            assignee_name = self.get_display_name(win.assignedTo)
<<<<<<< HEAD
            if win.assignedTo == self.fb.local_uid:
                messagebox.showinfo("เตือนตัวเอง", f"อย่าลืมทำ '{win.title}' นะ!")
            else:
                messagebox.showinfo("เตือนเพื่อน", 
                                  f"ส่งการเตือนเป้าหมาย '{win.title}' ให้ {assignee_name} แล้ว!\n(ในอนาคตจะมีระบบแจ้งเตือนจริง)")
        else:
            messagebox.showinfo("แจ้งเตือน", "เป้าหมายนี้ยังไม่ได้มอบหมายให้ใคร")

    def invite_member(self):
        """Invite a member to the room by username."""
        if not self.current_room:
            messagebox.showwarning("คำเตือน", "กรุณาเข้าร่วมห้องก่อน")
            return
            
        username_to_invite = self.invite_entry.get().strip()
        if not username_to_invite:
            messagebox.showwarning("คำเตือน", "กรุณากรอก username ที่ต้องการเชิญ")
            return
        
        try:
            uid_to_add = self.fb.uid_from_username(username_to_invite)
            if uid_to_add:
                if uid_to_add in self.current_room.members:
                    messagebox.showinfo("แจ้งเตือน", f"{username_to_invite} อยู่ในห้องแล้ว")
                else:
                    self.current_room.members[uid_to_add] = True
                    self._save_room_to_firebase()
                    self.invite_entry.delete(0, tk.END)
                    messagebox.showinfo("สำเร็จ", f"เชิญ {username_to_invite} เข้าห้องแล้ว!")
            else:
                messagebox.showerror("ข้อผิดพลาด", f"ไม่พบ username '{username_to_invite}'")
        except Exception as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถเชิญสมาชิก: {e}")

    def show_win_details(self, event):
        """Show detailed information about selected win."""
        win = self._get_selected_win()
        if not win:
            return
            
        created_by = self.get_display_name(win.createdBy) if win.createdBy else "ไม่ระบุ"
        assigned_to = self.get_display_name(win.assignedTo) if win.assignedTo else "ไม่ระบุ"
        created_time = time.strftime("%d/%m/%Y %H:%M", time.localtime(win.createdAt))
        completed_time = ""
        if win.completedAt:
            completed_time = time.strftime("%d/%m/%Y %H:%M", time.localtime(win.completedAt))
        
        status_text = "เสร็จสิ้น" if win.completed else "กำลังดำเนินการ"
        priority_text = {"low": "ต่ำ", "medium": "ปานกลาง", "high": "สูง"}[win.priority]
        
        details = f"""เป้าหมาย: {win.title}

รายละเอียด: {win.description or "ไม่มี"}

สถานะ: {status_text}
ระดับความสำคัญ: {priority_text}

สร้างโดย: {created_by}
มอบหมายให้: {assigned_to}
วันที่สร้าง: {created_time}"""
        
        if completed_time:
            details += f"\nวันที่เสร็จ: {completed_time}"
            
        messagebox.showinfo("รายละเอียดเป้าหมาย", details)

    def leave_room(self):
        """Leave current room and return to room selection."""
        if not self.current_room:
            messagebox.showinfo("แจ้งเตือน", "ยังไม่ได้เข้าร่วมห้องใด")
            return
            
        if messagebox.askyesno("ยืนยัน", f"ต้องการออกจากห้อง '{self.current_room.name}' หรือไม่?"):
            # Stop streaming
            if self.fb:
                self.fb.stop_stream()
            
            # Clear room data
            self.room_id = None
            self.current_room = None
            self.user_cache.clear()
            
            # Clear UI
            self.wins_tree.delete(*self.wins_tree.get_children())
            self.members_list.delete(0, tk.END)
<<<<<<< Updated upstream
            self._show_login_view()
            
=======
            self.room_name_label.config(text="ยังไม่ได้เข้าห้อง")
            self.room_desc_label.config(text="")
            self.invite_entry.delete(0, tk.END)
=======
            messagebox.showinfo("สะกิด!", f"ได้ส่งการสะกิด (ในจินตนาการ) ไปให้ {assignee_name} สำหรับงาน '{win.title}' เรียบร้อยแล้ว!")
        else:
            messagebox.showinfo("สะกิด", "เป้าหมายนี้ยังไม่ได้มอบหมายให้ใคร กรุณามอบหมายก่อน")

    def leave_room(self):
        if messagebox.askyesno("ยืนยัน", "คุณแน่ใจหรือไม่ว่าต้องการออกจากห้องนี้?"):
            self.fb.stop_streaming()
            self.room_id = None
            self.current_room = None
            self.wins_tree.delete(*self.wins_tree.get_children())
            self.members_list.delete(0, tk.END)
            self._switch_to_room_selection_view()
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
            
            # Prompt for new room
            self.after(1000, self.prompt_for_room)

>>>>>>> Stashed changes
    def on_closing(self):
        """Clean up when app is closing."""
        if self.fb:
            self.fb.stop_stream()
        self.master.destroy()

# ===============================================
# APPLICATION STARTUP
# ===============================================
def main():
<<<<<<< HEAD
    if not FIREBASE_API_KEY or "YOUR_FIREBASE" in FIREBASE_API_KEY:
        messagebox.showerror("ตั้งค่าไม่สมบูรณ์",
                             "กรุณาตั้งค่า FIREBASE_API_KEY และ FIREBASE_RTDB_URL ให้ถูกต้อง")
        return

    root = tk.Tk()
    
    # Apply modern theme if available
=======
    root = tk.Tk()
    
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
    try:
        style = ttk.Style(root)
        available_themes = style.theme_names()
        if 'vista' in available_themes:
            style.theme_use('vista')
        elif 'clam' in available_themes:
            style.theme_use('clam')
    except Exception:
<<<<<<< HEAD
        pass  # Use default theme
=======
        pass
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a

    app = SmallWinsApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()