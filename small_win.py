# ----------------------------------------------------------------------------------
# Small Wins: Collaborative Goal Tracker
#
# Description:
# A desktop application built with Python, Tkinter, and Firebase to help you and
# your friends achieve small, incremental goals together. Track progress, send
# reminders, and celebrate successes in a collaborative, real-time environment.
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
import re

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
# Updated to match the bill splitting app's Firebase project
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"  # From split_bill_all_in_one.py
FIREBASE_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/" # From split_bill_all_in_one.py

# ===============================================
# DATA MODELS: Representing the application's data
# ===============================================
@dataclass
class UserProfile:
    uid: str
    username: str
    displayName: str

@dataclass
class SmallWin:
    id: str = field(default_factory=lambda: f"win_{int(time.time() * 1000)}")
    title: str = ""
    completed: bool = False
    assignedTo: Optional[str] = None  # User UID
    createdAt: float = field(default_factory=time.time)
    completedAt: Optional[float] = None

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "completed": self.completed,
            "assignedTo": self.assignedTo, "createdAt": self.createdAt,
            "completedAt": self.completedAt
        }

    @classmethod
    def from_dict(cls, data: dict):
        win = cls()
        win.id = data.get("id")
        win.title = data.get("title")
        win.completed = data.get("completed", False)
        win.assignedTo = data.get("assignedTo")
        win.createdAt = data.get("createdAt")
        win.completedAt = data.get("completedAt")
        return win

@dataclass
class WinRoom:
    name: str
    members: Dict[str, bool] = field(default_factory=dict)  # {uid: True}
    wins: Dict[str, SmallWin] = field(default_factory=dict)
    updatedAt: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "name": self.name,
            "members": self.members,
            "wins": {win_id: win.to_dict() for win_id, win in self.wins.items()},
            "updatedAt": time.time()
        }

    @classmethod
    def from_dict(cls, data: dict):
        room = cls(name=data.get("name", "Unnamed Room"))
        room.members = data.get("members", {})
        room.wins = {win_id: SmallWin.from_dict(win_data) for win_id, win_data in data.get("wins", {}).items()}
        room.updatedAt = data.get("updatedAt", time.time())
        return room

# ===============================================
# FIREBASE CLIENT: Handles communication with Firebase (Upgraded Version)
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

        self._stream_thread = threading.Thread(target=poll_loop, daemon=True)
        self._stream_thread.start()

    def stop_streaming(self): 
        self._stop_stream = True
        if self._stream_thread:
            self._stream_thread.join(timeout=1)

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
        self.current_user: Optional[UserProfile] = None
        self.room_id: Optional[str] = None
        self.current_room: Optional[WinRoom] = None
        self.user_cache: Dict[str, str] = {} # uid -> displayName
        self._local_update_flag = False

        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._create_widgets()
        
        # Start with the login view
        self.login_frame.pack(expand=True, fill="both")
        self.master.title("Login - Small Wins")
        
    def _create_widgets(self):
        # --- Main Layout Frames ---
        self.login_frame = ttk.Frame(self, padding="20")
        self.room_selection_frame = ttk.Frame(self, padding="20")
        self.app_frame = ttk.Frame(self, padding="10")
        
        self._create_login_widgets()
        self._create_room_selection_widgets()
        self._create_app_widgets()

    def _switch_to_app_view(self):
        self.room_selection_frame.pack_forget()
        self.app_frame.pack(expand=True, fill="both")
        self.master.title(f"Room: {self.room_id} - Small Wins")

    def _switch_to_login_view(self):
        self.room_selection_frame.pack_forget()
        self.app_frame.pack_forget()
        self.login_frame.pack(expand=True, fill="both")
        self.master.title("Login - Small Wins")

    def _switch_to_room_selection_view(self):
        self.login_frame.pack_forget()
        self.app_frame.pack_forget()
        self.room_selection_frame.pack(expand=True, fill="both")
        self.master.title("Select Room - Small Wins")

    def _create_login_widgets(self):
        # --- Login/Signup Widgets ---
        login_container = ttk.LabelFrame(self.login_frame, text="Login or Sign Up")
        login_container.pack(expand=True)
        
        ttk.Label(login_container, text="Email:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.email_entry = ttk.Entry(login_container, width=30)
        self.email_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(login_container, text="Password:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.password_entry = ttk.Entry(login_container, show="*", width=30)
        self.password_entry.grid(row=1, column=1, padx=5, pady=5)
        
        btn_frame = ttk.Frame(login_container)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Login", command=self.handle_login).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Sign Up", command=self.handle_signup).pack(side="left", padx=5)

    def _create_room_selection_widgets(self):
        container = ttk.LabelFrame(self.room_selection_frame, text="Join or Create a Room")
        container.pack(expand=True)

        # Join Room Section
        join_frame = ttk.Frame(container, padding=10)
        join_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(join_frame, text="Room ID:").pack(side="left", padx=(0, 5))
        self.join_room_entry = ttk.Entry(join_frame, width=25)
        self.join_room_entry.pack(side="left", expand=True, fill="x")
        ttk.Button(join_frame, text="Join Room", command=self.handle_join_room).pack(side="left", padx=(5, 0))

        ttk.Separator(container, orient="horizontal").pack(fill='x', pady=10, padx=20)

        # Create Room Section
        create_frame = ttk.Frame(container, padding=10)
        create_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(create_frame, text="Don't have a room?").pack(side="left")
        ttk.Button(create_frame, text="Create a New Room", command=self.handle_create_room).pack(side="left", padx=5)

        # Logout Button at the bottom of the main frame
        logout_button = ttk.Button(self.room_selection_frame, text="Logout", command=self.handle_logout)
        logout_button.pack(side="bottom", pady=20)
        
    def _create_app_widgets(self):
        # --- App Layout ---
        # Left Panel: Room Info & Members
        left_panel = ttk.Frame(self.app_frame, width=250)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        
        # Right Panel: Goals (Wins)
        right_panel = ttk.Frame(self.app_frame)
        right_panel.pack(side="right", fill="both", expand=True)

        # --- Left Panel Widgets ---
        self.room_info_frame = ttk.LabelFrame(left_panel, text="Room Info")
        self.room_info_frame.pack(fill="x", pady=(0, 10))
        self.room_name_label = ttk.Label(self.room_info_frame, text="Room: N/A", font=("Segoe UI", 10, "bold"))
        self.room_name_label.pack(pady=5)
        ttk.Button(self.room_info_frame, text="Leave Room", command=self.leave_room).pack(fill="x", padx=5, pady=5)

        self.members_frame = ttk.LabelFrame(left_panel, text="Members")
        self.members_frame.pack(fill="both", expand=True)
        self.members_list = tk.Listbox(self.members_frame, height=10)
        self.members_list.pack(fill="both", expand=True, padx=5, pady=5)
        
        invite_frame = ttk.Frame(left_panel)
        invite_frame.pack(fill="x", pady=5)
        self.invite_entry = ttk.Entry(invite_frame)
        self.invite_entry.pack(side="left", expand=True, fill="x")
        ttk.Button(invite_frame, text="Invite", command=self.invite_member).pack(side="right", padx=(5,0))

        # --- Right Panel Widgets ---
        # Goal Entry
        entry_frame = ttk.Frame(right_panel)
        entry_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(entry_frame, text="New Win:").pack(side="left")
        self.win_entry = ttk.Entry(entry_frame)
        self.win_entry.pack(side="left", expand=True, fill="x", padx=5)
        ttk.Button(entry_frame, text="Add Win", command=self.add_win).pack(side="right")
        
        # Goals List (Treeview)
        cols = ("status", "title", "assigned")
        self.wins_tree = ttk.Treeview(right_panel, columns=cols, show="headings", selectmode="browse")
        self.wins_tree.heading("status", text="Status")
        self.wins_tree.heading("title", text="Goal / Win")
        self.wins_tree.heading("assigned", text="Assigned To")
        self.wins_tree.column("status", width=80, anchor="center")
        self.wins_tree.column("title", width=300)
        self.wins_tree.column("assigned", width=120)
        self.wins_tree.pack(fill="both", expand=True)
        
        # Styling for completed items
        self.wins_tree.tag_configure('completed', foreground='gray')
        
        # Action buttons for selected goal
        action_frame = ttk.Frame(right_panel)
        action_frame.pack(fill="x", pady=5)
        ttk.Button(action_frame, text="Toggle Complete", command=self.toggle_win_status).pack(side="left")
        ttk.Button(action_frame, text="Assign to...", command=self.assign_win).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Nudge!", command=self.nudge_user).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Delete", command=self.delete_win).pack(side="right")

    # --- Firebase & Logic Handlers ---
    def _validate_inputs(self):
        email = self.email_entry.get().strip()
        password = self.password_entry.get()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            messagebox.showwarning("Input Error", "รูปแบบอีเมลไม่ถูกต้อง")
            return None, None
        if not password:
            messagebox.showwarning("Input Error", "กรุณากรอกรหัสผ่าน")
            return None, None
        return email, password

    def handle_login(self):
        email, password = self._validate_inputs()
        if not email: return
            
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
        
        try:
            self.fb.sign_in_email(email, password)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("Login Failed", f"Could not log in: {e}")
            
    def handle_signup(self):
        email, password = self._validate_inputs()
        if not email: return

        username = simpledialog.askstring("Sign Up", "Choose a unique username:", parent=self)
        if not username: return
        displayName = simpledialog.askstring("Sign Up", "Enter your display name:", parent=self) or username
        
        if not self.fb:
            self.fb = FirebaseRTClient(FIREBASE_API_KEY, FIREBASE_RTDB_URL)
            
        try:
            self.fb.sign_up_email(email, password)
            self.fb.create_profile(self.fb.local_uid, username, displayName)
            self.post_auth_setup()
        except Exception as e:
            messagebox.showerror("Sign Up Failed", f"Could not create account: {e}")
            
    def post_auth_setup(self):
        uid = self.fb.local_uid
        profile = self.fb.get_profile(uid)

        if not profile:
            username = simpledialog.askstring("Create Profile", "Choose a unique username for your account:", parent=self)
            if not username: return 
            displayName = simpledialog.askstring("Create Profile", "Enter your display name:", parent=self) or username
            try:
                self.fb.create_profile(uid, username, displayName)
                profile = self.fb.get_profile(uid)
            except Exception as e:
                messagebox.showerror("Profile Error", f"Could not create your profile: {e}")
                return

        if not profile:
            messagebox.showerror("Error", "Could not load or create user profile. Please restart.")
            return

        self.current_user = profile
        self.user_cache[uid] = profile.displayName
        self.fb.start_auto_refresh()
        self._switch_to_room_selection_view()

    def handle_join_room(self):
        room_id = self.join_room_entry.get().strip()
        if not room_id:
            messagebox.showwarning("Input Needed", "Please enter a Room ID to join.")
            return
        self._enter_room_flow(room_id, is_new=False)

    def handle_create_room(self):
        room_id = simpledialog.askstring("Create Room", "Enter a new, unique Room ID:", parent=self)
        if not room_id:
            return
        self._enter_room_flow(room_id.strip(), is_new=True)

    def _enter_room_flow(self, room_id, is_new):
        self.room_id = room_id
        room_path = f"small_wins_rooms/{self.room_id}"
        try:
            room_data = self.fb.get(room_path)

            if is_new and room_data:
                messagebox.showerror("Error", f"Room ID '{self.room_id}' already exists. Please choose another one.")
                return

            if not is_new and not room_data:
                messagebox.showerror("Error", f"Room ID '{self.room_id}' not found.")
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
            self.update_ui_from_room_data()
        except Exception as e:
            messagebox.showerror("Room Error", f"Failed to enter room: {e}")
            
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

    def on_room_update(self, data):
        """Callback for when Firebase data changes."""
        if self._local_update_flag:
            return
        if data:
            self.current_room = WinRoom.from_dict(data)
            self.after(0, self.update_ui_from_room_data)

    def _save_room_to_firebase(self):
        """Saves the current room state to Firebase and sets a flag to ignore the echo."""
        if not self.fb or not self.current_room or not self.room_id:
            return
        
        room_path = f"small_wins_rooms/{self.room_id}"
        
        def save():
            try:
                self._local_update_flag = True
                self.fb.put(room_path, self.current_room.to_dict())
                time.sleep(1) # Wait a moment for the update to settle
            finally:
                self._local_update_flag = False

        threading.Thread(target=save, daemon=True).start()

    def update_ui_from_room_data(self):
        if not self.current_room: return
        
        self.room_name_label.config(text=f"Room: {self.current_room.name}")
        
        # Update members list
        self.members_list.delete(0, tk.END)
        for uid in self.current_room.members.keys():
            display_name = self.get_display_name(uid)
            self.members_list.insert(tk.END, display_name)

        # Update wins tree
        self.wins_tree.delete(*self.wins_tree.get_children())
        sorted_wins = sorted(self.current_room.wins.values(), key=lambda w: w.createdAt)
        
        for win in sorted_wins:
            status = "✅ Done" if win.completed else "⏳ To Do"
            assigned_name = self.get_display_name(win.assignedTo) if win.assignedTo else "Unassigned"
            tags = ('completed',) if win.completed else ()
            self.wins_tree.insert("", tk.END, iid=win.id, values=(status, win.title, assigned_name), tags=tags)
            
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
        title = self.win_entry.get().strip()
        if not title: return
        
        new_win = SmallWin(title=title, assignedTo=self.current_user.uid)
        self.current_room.wins[new_win.id] = new_win
        
        self.win_entry.delete(0, tk.END)
        self._save_room_to_firebase()
        self.update_ui_from_room_data() # Optimistic UI update

    def _get_selected_win(self) -> Optional[SmallWin]:
        selected_iid = self.wins_tree.focus()
        if not selected_iid:
            messagebox.showinfo("Info", "Please select a 'win' from the list first.")
            return None
        return self.current_room.wins.get(selected_iid)

    def toggle_win_status(self):
        win = self._get_selected_win()
        if not win: return
        
        win.completed = not win.completed
        win.completedAt = time.time() if win.completed else None
        
        self._save_room_to_firebase()
        self.update_ui_from_room_data()

    def delete_win(self):
        win = self._get_selected_win()
        if not win: return
        
        if messagebox.askyesno("Confirm", f"Are you sure you want to delete '{win.title}'?"):
            del self.current_room.wins[win.id]
            self._save_room_to_firebase()
            self.update_ui_from_room_data()

    def assign_win(self):
        win = self._get_selected_win()
        if not win: return

        members_map = {self.get_display_name(uid): uid for uid in self.current_room.members}
        member_names = list(members_map.keys())

        # Simple dialog to choose member
        assign_to_name = simpledialog.askstring("Assign Win", "Enter the display name of the member to assign this to:", parent=self)
        if assign_to_name and assign_to_name in members_map:
            win.assignedTo = members_map[assign_to_name]
            self._save_room_to_firebase()
            self.update_ui_from_room_data()
        elif assign_to_name:
            messagebox.showerror("Error", "Member not found.")
    
    def invite_member(self):
        username_to_invite = self.invite_entry.get().strip()
        if not username_to_invite: return
        
        try:
            uid_to_add = self.fb.get_uid_from_username(username_to_invite)
            if uid_to_add:
                if uid_to_add in self.current_room.members:
                    messagebox.showinfo("Info", f"{username_to_invite} is already in the room.")
                else:
                    self.current_room.members[uid_to_add] = True
                    self._save_room_to_firebase()
                    self.update_ui_from_room_data()
                    self.invite_entry.delete(0, tk.END)
            else:
                messagebox.showerror("Error", f"Username '{username_to_invite}' not found.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not invite member: {e}")
            
    def nudge_user(self):
        win = self._get_selected_win()
        if not win: return

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
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        else:
            style.theme_use('clam')
    except Exception:
        pass # Default theme is fine

    app = SmallWinsApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()

