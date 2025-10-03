# ----------------------------------------------------------------------------------
# Small Wins: Collaborative Goal Tracker
#
# Description:
# โปรแกรมเดสก์ท็อปที่สร้างด้วย Python, Tkinter และ Firebase เพื่อช่วยให้คุณและเพื่อนๆ
# บรรลุเป้าหมายเล็กๆ น้อยๆ ไปด้วยกัน ติดตามความคืบหน้า ส่งการแจ้งเตือน
# และเฉลิมฉลองความสำเร็จในสภาพแวดล้อมการทำงานร่วมกันแบบเรียลไทม์
#
# Features:
# ✔ Real-time data synchronization using Firebase Realtime Database.
# ✔ User authentication (Sign up / Login).
# ✔ Create collaborative "Win Rooms" to share goals with friends.
# ✔ Add, track, and complete "Small Wins" (goals).
# ✔ Assign tasks to specific friends.
# ✔ Nudge/remind friends to complete their tasks.
# ✔ Visually appealing and user-friendly interface.
# ----------------------------------------------------------------------------------

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
import json
import threading
import time
import requests

# --- Configuration ---
# To use this application, you need to create a project on the Firebase console.
# 1. Go to https://console.firebase.google.com/
# 2. Create a new project.
# 3. In your project, go to "Authentication" -> "Sign-in method" and enable "Email/Password".
# 4. Go to "Realtime Database", create a database, and check the "Rules".
#    For initial development, you can set the rules to be public:
#    {
#      "rules": {
#        ".read": "auth != null",
#        ".write": "auth != null"
#      }
#    }
#    **WARNING**: These are insecure rules. For production, secure your data properly.
# 5. Find your Web API Key and Database URL in your project settings.
FIREBASE_API_KEY = "AIzaSyCw9sLe1AaSi_TVHhTNVEwXGaJLw3DoDA0"  # Replace with your Firebase Web API Key
FIREBASE_RTDB_URL = "https://smallwin-f475a-default-rtdb.asia-southeast1.firebasedatabase.app"  # Replace with your Firebase Realtime Database URL (e.g., https://your-project-id.firebaseio.com/)

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
# FIREBASE CLIENT: Handles communication with Firebase
# ===============================================
class FirebaseRTClient:
    def __init__(self, api_key: str, rtdb_url: str):
        self.api_key = api_key
        self.rtdb_url = rtdb_url.rstrip("/")
        self.id_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.local_uid: Optional[str] = None
        self._stop_stream_event = threading.Event()
        self._stream_thread: Optional[threading.Thread] = None

    def _make_request(self, method, url, **kwargs):
        """Helper for making authenticated requests."""
        if 'params' not in kwargs:
            kwargs['params'] = {}
        if self.id_token:
            kwargs['params']['auth'] = self.id_token
        try:
            response = requests.request(method, url, **kwargs, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Firebase request failed: {e}")
            raise

    # --- Authentication ---
    def sign_in(self, email, password):
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
                    data = self.get(path)
                    current_hash = hash(json.dumps(data, sort_keys=True))
                    if data and current_hash != last_data_hash:
                        last_data_hash = current_hash
                        callback(data)
                except Exception as e:
                    print(f"Polling error: {e}")
                time.sleep(2) # Poll every 2 seconds

        self._stream_thread = threading.Thread(target=runner, daemon=True)
        self._stream_thread.start()

    def stop_streaming(self):
        self._stop_stream_event.set()

# ===============================================
# MAIN APPLICATION (UI): The Tkinter interface
# ===============================================
class SmallWinsApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("Small Wins - Collaborative Goal Tracker")
        self.master.geometry("900x650")

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
        # --- Main Layout ---
        self.main_notebook = ttk.Notebook(self)
        self.login_frame = ttk.Frame(self.main_notebook, padding="20")
        self.app_frame = ttk.Frame(self.main_notebook, padding="10")
        
        self.main_notebook.add(self.login_frame, text="Login")
        self.main_notebook.add(self.app_frame, text="App")
        self.main_notebook.pack(expand=True, fill="both")
        
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
        # --- Login/Signup Widgets ---
        login_container = ttk.LabelFrame(self.login_frame, text="Login or Sign Up")
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
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Login", command=self.handle_login).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Sign Up", command=self.handle_signup).pack(side="left", padx=5)
        
    def _create_app_widgets(self):
        # --- App Layout ---
        # Left Panel: Room Info & Members
        left_panel = ttk.Frame(self.app_frame, width=250)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        right_panel = ttk.Frame(self.app_frame)
        right_panel.pack(side="right", fill="both", expand=True)

        # --- Left Panel Widgets ---
        self.room_info_frame = ttk.LabelFrame(left_panel, text="Room Info")
        self.room_info_frame.pack(fill="x", pady=(0, 10))
        self.room_name_label = ttk.Label(self.room_info_frame, text="ห้อง: N/A", font=("Segoe UI", 10, "bold"))
        self.room_name_label.pack(pady=5)
        ttk.Button(self.room_info_frame, text="ออกจากห้อง", command=self.leave_room).pack(fill="x", padx=5, pady=5)

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
        ttk.Button(invite_frame, text="Invite", command=self.invite_member).pack(side="right", padx=(5,0))

        # --- Right Panel Widgets ---
        # Goal Entry
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
>>>>>>> 2a106603506b8521e792f796a64e5c252d7d572a
        
        action_frame = ttk.Frame(right_panel)
        action_frame.pack(fill="x", pady=5)
        ttk.Button(action_frame, text="Toggle Complete", command=self.toggle_win_status).pack(side="left")
        ttk.Button(action_frame, text="Assign to...", command=self.assign_win).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Nudge!", command=self.nudge_user).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Delete", command=self.delete_win).pack(side="right")

    # --- Firebase & Logic Handlers ---
    def handle_login(self):
        email = self.email_entry.get()
        password = self.password_entry.get()
        if not email or not password:
            messagebox.showerror("Error", "Email and password are required.")
            return
            
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        
        try:
            self.fb.sign_in(email, password)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("Login Failed", f"Could not log in: {e}")
            
    def handle_signup(self):
        email = self.email_entry.get()
        password = self.password_entry.get()
        if not email or not password:
            messagebox.showerror("Error", "Email and password are required.")
            return

        username = simpledialog.askstring("Sign Up", "Choose a unique username:", parent=self)
        if not username: return
        displayName = simpledialog.askstring("Sign Up", "Enter your display name:", parent=self) or username
        
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
            
        try:
            self.fb.sign_up(email, password)
            self.fb.create_profile(self.fb.local_uid, username, displayName)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("สมัครไม่สำเร็จ", f"ไม่สามารถสร้างบัญชีได้: {e}")
            
    def post_auth_setup(self):
        uid = self.fb.local_uid
        profile = self.fb.get_profile(uid)
        if not profile:
             messagebox.showerror("Error", "Could not load user profile.")
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
            self.fb.start_streaming(f"rooms/{self.room_id}", self.on_room_update)
            self._show_app_view()
            self.update_ui_from_room_data()
            
        except Exception as e:
            messagebox.showerror("Room Error", f"Failed to join or create room: {e}")

    def on_room_update(self, data):
        """Callback for when Firebase data changes."""
        if self._local_update_flag:
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
        
        room_path = f"small_wins_rooms/{self.room_id}"
        
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
        
        self.room_name_label.config(text=f"Room: {self.current_room.name}")
        
        self.members_list.delete(0, tk.END)
        for uid in self.current_room.members.keys():
            display_name = self.get_display_name(uid)
            is_current = " (คุณ)" if uid == self.fb.local_uid else ""
            self.members_list.insert(tk.END, f"{display_name}{is_current}")

        # Update wins tree
        self.wins_tree.delete(*self.wins_tree.get_children())
        sorted_wins = sorted(self.current_room.wins.values(), key=lambda w: w.createdAt)
        
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
        return uid[:8] # Fallback to partial UID

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
        self.update_ui_from_room_data() # Optimistic UI update

    def _get_selected_win(self) -> Optional[SmallWin]:
        selected_iid = self.wins_tree.focus()
        if not selected_iid:
            messagebox.showinfo("Info", "Please select a 'win' from the list first.")
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
            messagebox.showinfo("Nudge", "This win is already complete!")
            return
            
        if win.assignedTo:
            assignee_name = self.get_display_name(win.assignedTo)
            messagebox.showinfo("Nudge!", f"A friendly (but imaginary) nudge has been sent to {assignee_name} for the task: '{win.title}'!")
        else:
            messagebox.showinfo("Nudge", "This win is unassigned. Assign it to someone to nudge them.")

    def leave_room(self):
        if messagebox.askyesno("Confirm", "Are you sure you want to leave this room?"):
            self.fb.stop_streaming()
            self.room_id = None
            self.current_room = None
            self.user_cache.clear()
            self.wins_tree.delete(*self.wins_tree.get_children())
            self.members_list.delete(0, tk.END)
            self._show_login_view()
            
    def on_closing(self):
        """Clean up when app is closing."""
        if self.fb:
            self.fb.stop_stream()
        self.master.destroy()

# ===============================================
# APPLICATION STARTUP
# ===============================================
def main():
    if "YOUR_FIREBASE" in FIREBASE_API_KEY or "YOUR_FIREBASE" in FIREBASE_RTDB_URL:
        messagebox.showerror("Configuration Needed",
                             "Please replace 'YOUR_FIREBASE_WEB_API_KEY' and "
                             "'YOUR_FIREBASE_DATABASE_URL' in the Python script "
                             "with your actual Firebase project credentials.")
        return

    root = tk.Tk()
    
    # Apply a modern theme if available
    try:
        # For Windows, 'vista' is a good, clean choice. 'clam' or 'alt' for others.
        style = ttk.Style(root)
        available_themes = style.theme_names()
        if 'vista' in available_themes:
            style.theme_use('vista')
        elif 'clam' in available_themes:
            style.theme_use('clam')
    except Exception:
        pass # Default theme is fine

    app = SmallWinsApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()