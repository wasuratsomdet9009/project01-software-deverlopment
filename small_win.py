# ----------------------------------------------------------------------------------
# Small Wins: Collaborative Goal Tracker
#
# Description:
# โปรแกรมเดสก์ท็อปที่สร้างด้วย Python, Tkinter และ Firebase เพื่อช่วยให้คุณและเพื่อนๆ
# บรรลุเป้าหมายเล็กๆ น้อยๆ ไปด้วยกัน ติดตามความคืบหน้า ส่งการแจ้งเตือน
# และเฉลิมฉลองความสำเร็จในสภาพแวดล้อมการทำงานร่วมกันแบบเรียลไทม์
#
# Features:
# ✔ ซิงโครไนซ์ข้อมูลแบบเรียลไทม์โดยใช้ Firebase Realtime Database
# ✔ การยืนยันตัวตนผู้ใช้ (สมัคร / เข้าสู่ระบบ)
# ✔ สร้าง "ห้องเป้าหมาย" เพื่อแชร์เป้าหมายกับเพื่อน
# ✔ เพิ่ม ติดตาม และทำ "เป้าหมาย" ให้สำเร็จ
# ✔ มอบหมายงานให้เพื่อนที่ระบุได้
# ✔ "สะกิด" หรือเตือนเพื่อนให้ทำงานให้เสร็จ
# ✔ หน้าตาโปรแกรมสวยงามและใช้งานง่าย
# ✔ บันทึกและแสดงเวลาที่สร้าง เวลาที่สำเร็จ และระยะเวลาที่ใช้สำหรับแต่ละเป้าหมาย
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

# --- Configuration ---
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"

# ===============================================
# DATA MODELS
# ===============================================
@dataclass
class SmallWin:
    id: str = field(default_factory=lambda: f"win_{int(time.time() * 1000)}")
    title: str = ""
    description: str = ""
    completed: bool = False
    assignedTo: Optional[str] = None
    createdBy: Optional[str] = None
    createdAt: float = field(default_factory=time.time)
    completedAt: Optional[float] = None
    priority: str = "medium"
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
    members: Dict[str, bool] = field(default_factory=dict)
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
# FIREBASE CLIENT
# ===============================================
class FirebaseRTClient:
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

    def __init__(self, api_key: str, rtdb_url: str):
        self.api_key = api_key
        self.rtdb_url = rtdb_url.rstrip("/")
        self.id_token = None
        self.refresh_token = None
        self.local_uid = None
        self._stop_stream = False
        self._stream_thread = None

    def _post_json(self, url: str, payload: dict) -> dict:
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

    def _auth(self):
        if not self.id_token:
            raise RuntimeError("Not authenticated")
        return {"auth": self.id_token}

    def get(self, path: str):
        url = f"{self.rtdb_url}/{path}.json"
        r = requests.get(url, params=self._auth(), timeout=30)
        r.raise_for_status()
        return r.json()

    def put(self, path: str, obj):
        url = f"{self.rtdb_url}/{path}.json"
        r = requests.put(url, params=self._auth(), json=obj, timeout=30)
        r.raise_for_status()
        return r.json()

    def patch(self, path: str, obj):
        url = f"{self.rtdb_url}/{path}.json"
        r = requests.patch(url, params=self._auth(), json=obj, timeout=30)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _norm_uname(u: str) -> str:
        u = (u or "").strip().lower()
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
        except requests.HTTPError:
            return None

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

    def start_streaming(self, path: str, on_event: Callable):
        if not self.id_token:
            raise RuntimeError("Not authenticated")
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
                    try:
                        self.refresh_id_token()
                    except:
                        pass
                time.sleep(3)

        self._stream_thread = threading.Thread(target=poll_loop, daemon=True)
        self._stream_thread.start()

    def stop_streaming(self):
        self._stop_stream = True
        if self._stream_thread:
            self._stream_thread.join(timeout=1)

# ===============================================
# MAIN APPLICATION
# ===============================================
class SmallWinsApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("เครื่องมือติดตามเป้าหมาย")
        self.master.geometry("1200x700")

        self.fb: Optional[FirebaseRTClient] = None
        self.room_id: Optional[str] = None
        self.current_room: Optional[WinRoom] = None
        self.user_cache: Dict[str, str] = {}
        self._local_change = False
        self._last_remote_ua = None

        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._create_widgets()
        
        self.login_frame.pack(expand=True, fill="both")
        self.master.title("เข้าสู่ระบบ - Small Wins")
        
    def _create_widgets(self):
        self.login_frame = ttk.Frame(self, padding="20")
        self.room_selection_frame = ttk.Frame(self, padding="20")
        self.app_frame = ttk.Frame(self, padding="10")
        
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
        login_container = ttk.LabelFrame(self.login_frame, text="เข้าสู่ระบบ หรือ สมัครสมาชิก")
        login_container.pack(expand=True)
        
        ttk.Label(login_container, text="อีเมล:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.email_entry = ttk.Entry(login_container, width=30)
        self.email_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(login_container, text="รหัสผ่าน:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.password_entry = ttk.Entry(login_container, show="*", width=30)
        self.password_entry.grid(row=1, column=1, padx=5, pady=5)
        
        btn_frame = ttk.Frame(login_container)
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
        
        right_panel = ttk.Frame(self.app_frame)
        right_panel.pack(side="right", fill="both", expand=True)

        self.room_info_frame = ttk.LabelFrame(left_panel, text="ข้อมูลห้อง")
        self.room_info_frame.pack(fill="x", pady=(0, 10))
        self.room_name_label = ttk.Label(self.room_info_frame, text="ห้อง: N/A", font=("Segoe UI", 10, "bold"))
        self.room_name_label.pack(pady=5)
        ttk.Button(self.room_info_frame, text="ออกจากห้อง", command=self.leave_room).pack(fill="x", padx=5, pady=5)

        self.members_frame = ttk.LabelFrame(left_panel, text="สมาชิก")
        self.members_frame.pack(fill="both", expand=True)
        self.members_list = tk.Listbox(self.members_frame, height=10)
        self.members_list.pack(fill="both", expand=True, padx=5, pady=5)
        
        invite_frame = ttk.Frame(left_panel)
        invite_frame.pack(fill="x", pady=5)
        ttk.Label(invite_frame, text="เชิญเพื่อน:").pack(anchor="w")
        self.invite_entry = ttk.Entry(invite_frame)
        self.invite_entry.pack(side="left", expand=True, fill="x")
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
        self.wins_tree.column("created", width=140, anchor="center")
        self.wins_tree.column("completed_time", width=140, anchor="center")
        self.wins_tree.column("duration", width=100, anchor="e")
        
        self.wins_tree.pack(fill="both", expand=True)
        self.wins_tree.tag_configure('completed', foreground='gray')
        
        action_frame = ttk.Frame(right_panel)
        action_frame.pack(fill="x", pady=5)
        ttk.Button(action_frame, text="สลับสถานะ", command=self.toggle_win_status).pack(side="left")
        ttk.Button(action_frame, text="มอบหมายให้...", command=self.assign_win).pack(side="left", padx=5)
        ttk.Button(action_frame, text="สะกิด", command=self.nudge_user).pack(side="left", padx=5)
        ttk.Button(action_frame, text="ลบ", command=self.delete_win).pack(side="right")

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
        if not email:
            return
            
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        
        try:
            self.fb.sign_in_email(email, password)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("เข้าระบบไม่สำเร็จ", f"ไม่สามารถเข้าระบบได้: {e}")
            
    def handle_signup(self):
        email, password = self._validate_inputs()
        if not email:
            return

        username = simpledialog.askstring("สมัครสมาชิก", "เลือก username ที่ไม่ซ้ำ:", parent=self)
        if not username:
            return
        displayName = simpledialog.askstring("สมัครสมาชิก", "ใส่ชื่อที่ต้องการให้แสดง:", parent=self) or username
        
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
            
        try:
            self.fb.sign_up_email(email, password)
            self.fb.reserve_username(username)
            self.fb.save_profile(username, displayName)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("สมัครไม่สำเร็จ", f"ไม่สามารถสร้างบัญชีได้: {e}")
            
    def post_auth_setup(self):
        uid = self.fb.local_uid
        profile = self.fb.get_profile(uid)

        if not profile:
            username = simpledialog.askstring("สร้างโปรไฟล์", "เลือก username ที่ไม่ซ้ำสำหรับบัญชีของคุณ:", parent=self)
            if not username:
                return
            displayName = simpledialog.askstring("สร้างโปรไฟล์", "ใส่ชื่อที่ต้องการให้แสดง:", parent=self) or username
            try:
                self.fb.reserve_username(username)
                self.fb.save_profile(username, displayName)
                profile = self.fb.get_profile(uid)
            except Exception as e:
                messagebox.showerror("สร้างโปรไฟล์ไม่สำเร็จ", f"ไม่สามารถสร้างโปรไฟล์ได้: {e}")
                return

        if not profile:
            messagebox.showerror("ผิดพลาด", "ไม่สามารถโหลดหรือสร้างโปรไฟล์ได้ กรุณาเริ่มใหม่")
            return

        display_name = profile.get("displayName") or profile.get("username") or uid[:8]
        self.user_cache[uid] = display_name
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

            if room_data:
                self.current_room = WinRoom.from_dict(room_data)
                if self.fb.local_uid not in self.current_room.members:
                    self.current_room.members[self.fb.local_uid] = True
            else:
                self.current_room = WinRoom(name=self.room_id)
                self.current_room.members[self.fb.local_uid] = True
            
            self._save_room_to_firebase()
            self.fb.start_streaming(room_path, self.on_room_update)
            self._switch_to_app_view()
            self.update_ui_from_room_data()
            
        except Exception as e:
            messagebox.showerror("เข้าห้องไม่สำเร็จ", f"ไม่สามารถเข้าห้องได้: {e}")

    def on_room_update(self, data):
        if self._local_change:
            return
        try:
            if data and isinstance(data, dict):
                new_room = WinRoom.from_dict(data)
                self.current_room = new_room
                self.after(0, self.update_ui_from_room_data)
        except Exception as e:
            print(f"Error updating room: {e}")
            
    def handle_logout(self):
        if self.fb:
            self.fb.stop_streaming()
        self.fb = None
        self.room_id = None
        self.current_room = None
        self.user_cache.clear()
        self.password_entry.delete(0, tk.END)
        self._switch_to_login_view()

    def _save_room_to_firebase(self):
        if not (self.fb and self.current_room and self.room_id):
            return
        
        room_path = f"small_wins_rooms/{self.room_id}"
        
        def save():
            try:
                self._local_change = True
                self.fb.put(room_path, self.current_room.to_dict())
                time.sleep(1)
            finally:
                self.after(300, lambda: setattr(self, "_local_change", False))

        threading.Thread(target=save, daemon=True).start()

    def update_ui_from_room_data(self):
        if not self.current_room:
            return
        
        self.room_name_label.config(text=f"ห้อง: {self.current_room.name}")
        
        self.members_list.delete(0, tk.END)
        for uid in self.current_room.members.keys():
            display_name = self.get_display_name(uid)
            is_current = " (คุณ)" if uid == self.fb.local_uid else ""
            self.members_list.insert(tk.END, f"{display_name}{is_current}")

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
        if not uid:
            return "N/A"
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

    def add_win(self):
        if not self.current_room:
            messagebox.showwarning("คำเตือน", "กรุณาเข้าร่วมห้องก่อน")
            return
            
        title = self.win_entry.get().strip()
        
        if not title:
            messagebox.showwarning("คำเตือน", "กรุณากรอกชื่อเป้าหมาย")
            return
        
        new_win = SmallWin(
            title=title,
            createdBy=self.fb.local_uid,
            assignedTo=self.fb.local_uid
        )
        
        self.current_room.wins[new_win.id] = new_win
        self.win_entry.delete(0, tk.END)
        
        self._save_room_to_firebase()
        self.update_ui_from_room_data()

    def _get_selected_win(self) -> Optional[SmallWin]:
        selected_iid = self.wins_tree.focus()
        if not selected_iid:
            messagebox.showinfo("แจ้งเตือน", "กรุณาเลือกเป้าหมายจากรายการก่อน")
            return None
        
        return self.current_room.wins.get(selected_iid)

    def toggle_win_status(self):
        win = self._get_selected_win()
        if not win:
            return
        
        win.completed = not win.completed
        win.completedAt = time.time() if win.completed else None
        
        self._save_room_to_firebase()
        self.update_ui_from_room_data()

    def delete_win(self):
        win = self._get_selected_win()
        if not win:
            return
        
        if messagebox.askyesno("ยืนยัน", f"คุณแน่ใจหรือไม่ว่าต้องการลบ '{win.title}'?"):
            del self.current_room.wins[win.id]
            self._save_room_to_firebase()
            self.update_ui_from_room_data()

    def assign_win(self):
        win = self._get_selected_win()
        if not win:
            return

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
        if not username_to_invite:
            return
        
        try:
            uid_to_add = self.fb.uid_from_username(username_to_invite)
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
        win = self._get_selected_win()
        if not win:
            return
            
        if win.completed:
            messagebox.showinfo("สะกิด", "เป้าหมายนี้สำเร็จแล้ว!")
            return
            
        if win.assignedTo:
            assignee_name = self.get_display_name(win.assignedTo)
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

    def on_closing(self):
        if self.fb:
            self.fb.stop_streaming()
        self.master.destroy()

# ===============================================
# APPLICATION STARTUP
# ===============================================
def main():
    root = tk.Tk()
    
    try:
        style = ttk.Style(root)
        available_themes = style.theme_names()
        if 'vista' in available_themes:
            style.theme_use('vista')
        elif 'clam' in available_themes:
            style.theme_use('clam')
    except Exception:
        pass

    app = SmallWinsApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()