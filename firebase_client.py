# firebase_client.py
# ติดต่อกับ Firebase (Authentication และ Realtime Database)

import json
import threading
import time
import requests
import random
import string
from typing import Optional, Callable, List

try:
    from sseclient import SSEClient  # type: ignore
except ImportError:
    SSEClient = None

class FirebaseRTClient:
    """จัดการการเชื่อมต่อ Firebase Auth และ Realtime Database"""
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
        """ฟังก์ชันช่วยสำหรับส่ง POST request และจัดการ Error"""
        try:
            r = requests.post(url, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            msg = ""
            try:
                j = r.json()
                msg = j.get("error", {}).get("message", "")
            except Exception: pass
            human_readable_error = self.ERROR_MAP.get(msg, msg or str(e))
            raise ValueError(human_readable_error)

    def sign_in_email(self, email: str, password: str):
        """เข้าสู่ระบบด้วย Email/Password"""
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token, self.refresh_token, self.local_uid = d["idToken"], d["refreshToken"], d["localId"]
        return d

    def sign_up_email(self, email: str, password: str):
        """สมัครสมาชิกใหม่"""
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.api_key}"
        d = self._post_json(url, {"email": email, "password": password, "returnSecureToken": True})
        self.id_token, self.refresh_token, self.local_uid = d["idToken"], d["refreshToken"], d["localId"]
        return d

    def refresh_id_token(self):
        """ขอ Token ใหม่เมื่อใกล้หมดอายุ"""
        if not self.refresh_token: return
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"
        r = requests.post(url, data={"grant_type":"refresh_token", "refresh_token":self.refresh_token})
        r.raise_for_status()
        d = r.json()
        self.id_token, self.refresh_token, self.local_uid = d["id_token"], d["refresh_token"], d["user_id"]

    def start_auto_refresh(self, every_sec=50*60):
        """เริ่มการต่ออายุ Token อัตโนมัติ"""
        def loop():
            while True:
                time.sleep(every_sec)
                try: self.refresh_id_token()
                except Exception: pass
        threading.Thread(target=loop, daemon=True).start()

    def _auth(self):
        """สร้าง header สำหรับยืนยันตัวตน"""
        if not self.id_token: raise RuntimeError("Not authenticated")
        return {"auth": self.id_token}

    def _request_with_retry(self, method: str, path: str, **kwargs):
        """ส่ง Request พร้อมระบบ Retry เมื่อเจอ Error 401 Unauthorized"""
        url = f"{self.rtdb_url}/{path}.json"
        try:
            params = kwargs.pop('params', {})
            params.update(self._auth())
            r = requests.request(method, url, params=params, timeout=30, **kwargs)
            r.raise_for_status()
            return r.json() if r.content else None
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                try:
                    self.refresh_id_token()
                    params = kwargs.pop('params', {})
                    params.update(self._auth())
                    r_retry = requests.request(method, url, params=params, timeout=30, **kwargs)
                    r_retry.raise_for_status()
                    return r_retry.json() if r_retry.content else None
                except Exception as retry_e:
                    raise ValueError("การยืนยันตัวตนล้มเหลว กรุณาลองเข้าสู่ระบบใหม่อีกครั้ง") from retry_e
            raise e

    def get(self, path:str):
        return self._request_with_retry("get", path)
    def put(self, path:str, obj):
        return self._request_with_retry("put", path, json=obj)
    def patch(self, path:str, obj):
        return self._request_with_retry("patch", path, json=obj)
    def post(self, path:str, obj):
        return self._request_with_retry("post", path, json=obj)
    def delete(self, path:str):
        return self._request_with_retry("delete", path)

    @staticmethod
    def _norm_uname(u: str) -> str:
        """จัดรูปแบบ username ให้ถูกต้อง"""
        u = (u or "").strip().lower()
        if not u: raise ValueError("username ว่างไม่ได้")
        for bad in ['.', '#', '$', '[', ']', '/']:
            if bad in u: raise ValueError(f"username มีอักขระต้องห้าม: {bad}")
        return u

    def reserve_username(self, username: str):
        """จอง username"""
        return self.put(f"usernames/{self._norm_uname(username)}", self.local_uid)

    def uid_from_username(self, username: str) -> Optional[str]:
        """ค้นหา UID จาก username"""
        try: return self.get(f"usernames/{self._norm_uname(username)}")
        except requests.HTTPError: return None

    def save_profile(self, username: str, display_name: str):
        """บันทึกข้อมูลโปรไฟล์"""
        data = {"username": self._norm_uname(username),
                "displayName": display_name or username,
                "updatedAt": int(time.time())}
        return self.put(f"public_profiles/{self.local_uid}", data)

    def get_profile(self, uid: str) -> Optional[dict]:
        """ดึงข้อมูลโปรไฟล์จาก UID"""
        try: return self.get(f"public_profiles/{uid}")
        except requests.HTTPError: return None

    @staticmethod
    def gen_room_id() -> str:
        """สร้างรหัสห้องแบบสุ่ม"""
        alpha = string.ascii_uppercase + string.digits
        return "R-" + "".join(random.choice(alpha) for _ in range(7))

    def create_room(self) -> str:
        """สร้างห้องใหม่"""
        room_id = self.gen_room_id()
        now = int(time.time())
        self.put(f"rooms/{room_id}", {
            "ownerUid": self.local_uid,
            "createdAt": now,
            "members": { self.local_uid: {"role": "owner", "invitedBy": self.local_uid, "joinedAt": now} },
        })
        self.patch(f"rooms_by_user/{self.local_uid}", { room_id: True })
        initial_bill_data = {"people": [self.local_uid], "updatedAt": time.time()}
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
        """ดึงรายชื่อห้องทั้งหมดของเรา"""
        mapping = self.get(f"rooms_by_user/{self.local_uid}") or {}
        return sorted(list(mapping.keys()))

    def get_room_owner(self, room_id: str) -> Optional[str]:
        """หา UID ของเจ้าของห้อง"""
        try:
            return self.get(f"rooms/{room_id}/ownerUid")
        except requests.HTTPError:
            return None

    def stream(self, path: str, on_event: Callable):
        """เริ่มฟังการเปลี่ยนแปลงข้อมูลแบบ real-time"""
        if not self.id_token: raise RuntimeError("Not authenticated")
        url = f"{self.rtdb_url}/{path}.json"; self._stop_stream = False

        def run_sse():
            while not self._stop_stream:
                try:
                    current_token = self.id_token
                    if not current_token: time.sleep(2); continue
                    msgs = SSEClient(url, params={"auth": current_token})
                    for msg in msgs:
                        if self._stop_stream: break
                        if msg.event in ("put", "patch"):
                            try: on_event(json.loads(msg.data))
                            except (json.JSONDecodeError, TypeError): pass
                except requests.HTTPError as e:
                    if e.response.status_code == 401:
                        try: self.refresh_id_token()
                        except Exception: time.sleep(5)
                    else: time.sleep(5)
                except Exception: time.sleep(2)

        def run_poll():
            last_json = None
            while not self._stop_stream:
                try:
                    data = self.get(path) 
                    current_json = json.dumps(data, sort_keys=True)
                    if data is not None and current_json != last_json:
                        on_event({"path": "/", "data": data})
                        last_json = current_json
                except Exception: pass
                time.sleep(3)

        threading.Thread(target=(run_sse if SSEClient else run_poll), daemon=True).start()

    def stop_stream(self):
        """หยุดการฟังข้อมูล"""
        self._stop_stream = True

