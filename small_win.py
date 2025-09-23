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
from typing import List, Dict, Optional
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
# FIREBASE CLIENT: Handles communication with Firebase
# ===============================================
class FirebaseRTClient:
    """A client for Firebase Authentication and Realtime Database."""
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
        payload = {"email": email, "password": password, "returnSecureToken": True}
        data = self._make_request('POST', url, json=payload)
        self._store_auth_credentials(data)
        return data

    def sign_up(self, email, password):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        data = self._make_request('POST', url, json=payload)
        self._store_auth_credentials(data)
        return data

    def _store_auth_credentials(self, data: dict):
        self.id_token = data.get("idToken")
        self.refresh_token = data.get("refreshToken")
        self.local_uid = data.get("localId")

    # --- Database Operations ---
    def get(self, path: str):
        return self._make_request('GET', f"{self.rtdb_url}/{path}.json")

    def put(self, path: str, data: dict):
        return self._make_request('PUT', f"{self.rtdb_url}/{path}.json", json=data)
        
    def patch(self, path: str, data: dict):
        return self._make_request('PATCH', f"{self.rtdb_url}/{path}.json", json=data)

    # --- User Profile Helpers ---
    def get_profile(self, uid: str) -> Optional[UserProfile]:
        try:
            data = self.get(f"profiles/{uid}")
            if data:
                return UserProfile(uid=uid, username=data.get('username'), displayName=data.get('displayName'))
        except requests.exceptions.HTTPError:
            return None
        return None

    def create_profile(self, uid: str, username: str, displayName: str):
        # Reserve username to prevent duplicates
        self.put(f"usernames/{username.lower()}", uid)
        # Store profile
        profile_data = {"username": username, "displayName": displayName}
        self.put(f"profiles/{uid}", profile_data)

    def get_uid_from_username(self, username: str) -> Optional[str]:
        try:
            return self.get(f"usernames/{username.lower()}")
        except requests.exceptions.HTTPError:
            return None

    # --- Real-time Streaming (Polling Fallback) ---
    def start_streaming(self, path: str, callback):
        self.stop_streaming() # Ensure no old stream is running
        self._stop_stream_event.clear()
        
        def poll_loop():
            last_data_hash = None
            while not self._stop_stream_event.is_set():
                try:
                    data = self.get(path)
                    current_hash = hash(json.dumps(data, sort_keys=True))
                    if data and current_hash != last_data_hash:
                        last_data_hash = current_hash
                        callback(data)
                except Exception as e:
                    print(f"Polling error: {e}")
                time.sleep(2) # Poll every 2 seconds

        self._stream_thread = threading.Thread(target=poll_loop, daemon=True)
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
        self.current_user: Optional[UserProfile] = None
        self.room_id: Optional[str] = None
        self.current_room: Optional[WinRoom] = None
        self.user_cache: Dict[str, str] = {} # uid -> displayName
        self._local_update_flag = False

        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._create_widgets()
        self._show_login_view()
        
    def _create_widgets(self):
        # --- Main Layout ---
        self.main_notebook = ttk.Notebook(self)
        self.login_frame = ttk.Frame(self.main_notebook, padding="20")
        self.app_frame = ttk.Frame(self.main_notebook, padding="10")
        
        self.main_notebook.add(self.login_frame, text="Login")
        self.main_notebook.add(self.app_frame, text="App")
        self.main_notebook.pack(expand=True, fill="both")
        
        self._create_login_widgets()
        self._create_app_widgets()
        
    def _show_login_view(self):
        self.main_notebook.select(self.login_frame)
        self.master.title("Login - Small Wins")

    def _show_app_view(self):
        self.main_notebook.select(self.app_frame)
        self.master.title(f"Room: {self.room_id} - Small Wins")

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
            messagebox.showerror("Sign Up Failed", f"Could not create account: {e}")
            
    def post_auth_setup(self):
        uid = self.fb.local_uid
        profile = self.fb.get_profile(uid)
        if not profile:
             messagebox.showerror("Error", "Could not load user profile.")
             return
        self.current_user = profile
        self.user_cache[uid] = profile.displayName

        self.join_or_create_room()

    def join_or_create_room(self):
        room_id = simpledialog.askstring("Join Room", "Enter a Room ID to join or create:", parent=self)
        if not room_id: return
        self.room_id = room_id.strip()

        try:
            room_data = self.fb.get(f"rooms/{self.room_id}")
            if room_data: # Room exists
                self.current_room = WinRoom.from_dict(room_data)
                # Add current user to members if not already there
                if self.current_user.uid not in self.current_room.members:
                    self.current_room.members[self.current_user.uid] = True
            else: # Create new room
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
        if data:
            self.current_room = WinRoom.from_dict(data)
            self.after(0, self.update_ui_from_room_data)

    def _save_room_to_firebase(self):
        """Saves the current room state to Firebase and sets a flag to ignore the echo."""
        if not self.fb or not self.current_room or not self.room_id:
            return
        
        def save():
            try:
                self._local_update_flag = True
                self.fb.put(f"rooms/{self.room_id}", self.current_room.to_dict())
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
            self.user_cache.clear()
            self.wins_tree.delete(*self.wins_tree.get_children())
            self.members_list.delete(0, tk.END)
            self._show_login_view()
            
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

