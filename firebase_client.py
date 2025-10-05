# firebase_client.py
# ไฟล์นี้ทำหน้าที่ติดต่อกับ Firebase เท่านั้น
# เป็นเหมือน "บุรุษไปรษณีย์" ที่รับส่งข้อมูลระหว่างโปรแกรมของเรากับ Server
# ทำให้ส่วนอื่นๆ ของโปรแกรมไม่ต้องกังวลเรื่องการเชื่อมต่อที่ซับซ้อน

import json
import threading
import time
import requests
import random
import string
from typing import Optional, Callable, List

try:
    # sseclient-py เป็น library ที่ช่วยให้รับข้อมูลแบบ Real-time (Streaming) ได้ดีขึ้น
    from sseclient import SSEClient  # type: ignore
except ImportError:
    SSEClient = None # ถ้าไม่มี จะใช้วิธีดึงข้อมูลซ้ำๆ (Polling) แทน

class FirebaseRTClient:
    """
    คลาสสำหรับจัดการการเชื่อมต่อกับ Firebase Authentication และ Realtime Database
    """
    # แปลข้อความ Error จาก Firebase เป็นภาษาไทยให้เข้าใจง่าย
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
        self.id_token = None # Token ที่ใช้ยืนยันตัวตนในการเข้าถึงข้อมูล
        self.refresh_token = None # Token ที่ใช้ขอ id_token ใหม่เมื่อหมดอายุ
        self.local_uid = None # User ID ของผู้ใช้ที่กำลัง login
        self._stop_stream = False

    def _post_json(self, url: str, payload: dict) -> dict:
        """ฟังก์ชันช่วยสำหรับส่งข้อมูลแบบ POST และจัดการ Error"""
        try:
            r = requests.post(url, json=payload, timeout=30)
            r.raise_for_status() # ถ้ามี Error (เช่น 404, 500) จะโยน Exception
            return r.json()
        except requests.HTTPError as e:
            # พยายามแปล Error เป็นภาษาไทย
            msg = ""
            try:
                j = r.json()
                msg = j.get("error", {}).get("message", "")
            except Exception: pass
            human_readable_error = self.ERROR_MAP.get(msg, msg or str(e))
            raise ValueError(human_readable_error)

    # --- Authentication (การยืนยันตัวตน) ---
    def sign_in_email(self, email: str, password: str):
        """เข้าสู่ระบบด้วย Email/Password"""
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token, self.refresh_token, self.local_uid = d["idToken"], d["refreshToken"], d["localId"]
        return d

    def sign_up_email(self, email: str, password: str):
        """สมัครสมาชิกใหม่ด้วย Email/Password"""
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token, self.refresh_token, self.local_uid = d["idToken"], d["refreshToken"], d["localId"]
        return d

    def refresh_id_token(self):
        """ขอ Token ใหม่โดยอัตโนมัติเมื่อใกล้หมดอายุ"""
        if not self.refresh_token: return
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"
        r = requests.post(url, data={"grant_type":"refresh_token", "refresh_token":self.refresh_token})
        r.raise_for_status()
        d = r.json()
        self.id_token, self.refresh_token, self.local_uid = d["id_token"], d["refresh_token"], d["user_id"]

    def start_auto_refresh(self, every_sec=50*60):
        """เริ่มการต่ออายุ Token อัตโนมัติใน Background"""
        def loop():
            while True:
                time.sleep(every_sec)
                try: self.refresh_id_token()
                except Exception: pass
        threading.Thread(target=loop, daemon=True).start()

    # --- Database Operations (การจัดการข้อมูล) ---
    def _auth(self):
        """สร้าง header สำหรับยืนยันตัวตน"""
        if not self.id_token: raise RuntimeError("Not authenticated")
        return {"auth": self.id_token}

    def get(self, path:str):
        url=f"{self.rtdb_url}/{path}.json"
        r=requests.get(url, params=self._auth(), timeout=30)
        r.raise_for_status()
        return r.json()

    def put(self, path:str, obj):
        url=f"{self.rtdb_url}/{path}.json"
        r=requests.put(url, params=self._auth(), json=obj, timeout=30)
        r.raise_for_status()
        return r.json()

    def patch(self, path:str, obj):
        url=f"{self.rtdb_url}/{path}.json"
        r=requests.patch(url, params=self._auth(), json=obj, timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path:str, obj):
        url=f"{self.rtdb_url}/{path}.json"
        r=requests.post(url, params=self._auth(), json=obj, timeout=30)
        r.raise_for_status()
        return r.json()

    def delete(self, path:str):
        url=f"{self.rtdb_url}/{path}.json"
        r=requests.delete(url, params=self._auth(), timeout=30)
        r.raise_for_status()
        return r.json()

    # --- Username / Profile Helpers ---
    @staticmethod
    def _norm_uname(u: str) -> str:
        """จัดรูปแบบ username ให้ถูกต้อง (ตัวเล็ก, ไม่มีอักขระพิเศษ)"""
        u = (u or "").strip().lower()
        if not u: raise ValueError("username ว่างไม่ได้")
        for bad in ['.', '#', '$', '[', ']', '/']:
            if bad in u: raise ValueError(f"username มีอักขระต้องห้าม: {bad}")
        return u

    def reserve_username(self, username: str):
        """จอง username ในระบบ"""
        return self.put(f"usernames/{self._norm_uname(username)}", self.local_uid)

    def uid_from_username(self, username: str) -> Optional[str]:
        """ค้นหา UID จาก username"""
        try: return self.get(f"usernames/{self._norm_uname(username)}")
        except requests.HTTPError: return None

    def save_profile(self, username: str, display_name: str):
        """บันทึกข้อมูลโปรไฟล์สาธารณะ"""
        data = {"username": self._norm_uname(username),
                "displayName": display_name or username,
                "updatedAt": int(time.time())}
        return self.put(f"public_profiles/{self.local_uid}", data)

    def get_profile(self, uid: str) -> Optional[dict]:
        """ดึงข้อมูลโปรไฟล์จาก UID"""
        try: return self.get(f"public_profiles/{uid}")
        except requests.HTTPError: return None

    # --- Room Helpers ---
    @staticmethod
    def gen_room_id() -> str:
        """สร้างรหัสห้องแบบสุ่ม"""
        alpha = string.ascii_uppercase + string.digits
        return "R-" + "".join(random.choice(alpha) for _ in range(7))

    def create_room(self) -> str:
        """สร้างห้องใหม่และกำหนดค่าเริ่มต้น"""
        room_id = self.gen_room_id()
        now = int(time.time())
        # สร้างโครงสร้างห้อง
        self.put(f"rooms/{room_id}", {
            "ownerUid": self.local_uid,
            "createdAt": now,
            "members": { self.local_uid: {"role": "owner", "invitedBy": self.local_uid, "joinedAt": now} },
        })
        # เพิ่มห้องนี้ในรายชื่อห้องของผู้ใช้
        self.patch(f"rooms_by_user/{self.local_uid}", { room_id: True })
        
        # สร้างบิลเริ่มต้น (ว่างๆ) และ small_wins เริ่มต้น (ว่างๆ)
        initial_bill_data = {"people": [self.local_uid], "updatedAt": time.time()} # ใส่ owner ไว้ในบิลเลย
        self.put(f"bills/{room_id}", initial_bill_data)
        self.put(f"small_wins/{room_id}", {})
        return room_id

    def add_member(self, room_id: str, target_uid: str):
        """เชิญสมาชิกใหม่เข้าห้อง"""
        now = int(time.time())
        self.patch(f"rooms/{room_id}/members/{target_uid}",
                   {"role": "member", "invitedBy": self.local_uid, "joinedAt": now})
        self.patch(f"rooms_by_user/{target_uid}", { room_id: True })

    def list_my_rooms(self) -> List[str]:
        """ดึงรายชื่อห้องทั้งหมดที่เราเป็นสมาชิก"""
        mapping = self.get(f"rooms_by_user/{self.local_uid}") or {}
        return sorted(list(mapping.keys()))

    def get_room_owner(self, room_id: str) -> Optional[str]:
        """หา UID ของเจ้าของห้อง"""
        try:
            return self.get(f"rooms/{room_id}/ownerUid")
        except requests.HTTPError:
            return None

    # --- Real-time Streaming ---
    def stream(self, path: str, on_event: Callable):
        """เริ่มฟังการเปลี่ยนแปลงข้อมูลแบบ real-time"""
        if not self.id_token: raise RuntimeError("Not authenticated")
        url = f"{self.rtdb_url}/{path}.json"; self._stop_stream = False

        def run_sse():
            """วิธีที่ 1: ใช้ SSE (Server-Sent Events) - ดีที่สุด"""
            while not self._stop_stream:
                try:
                    msgs = SSEClient(url, params={"auth": self.id_token})
                    for msg in msgs:
                        if self._stop_stream: break
                        if msg.event in ("put", "patch"):
                            try: on_event(json.loads(msg.data))
                            except (json.JSONDecodeError, TypeError): pass
                except Exception:
                    time.sleep(2) # รอสักครู่แล้วลองเชื่อมต่อใหม่

        def run_poll():
            """วิธีที่ 2: ใช้ Polling (สำรอง) - ดึงข้อมูลซ้ำๆ ทุก 3 วินาที"""
            last_json = None
            while not self._stop_stream:
                try:
                    data = self.get(path) # ใช้ self.get ที่มี timeout และ error handling
                    current_json = json.dumps(data, sort_keys=True)
                    if data is not None and current_json != last_json:
                        on_event({"path": "/", "data": data})
                        last_json = current_json
                except Exception: pass
                time.sleep(3)

        # เลือกวิธี stream ที่เหมาะสม (SSE ถ้ามี, ไม่งั้นใช้ Polling)
        threading.Thread(target=(run_sse if SSEClient else run_poll), daemon=True).start()

    def stop_stream(self):
        """หยุดการฟังข้อมูล"""
        self._stop_stream = True

