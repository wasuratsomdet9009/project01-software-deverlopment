# ui_components.py
# ไฟล์นี้เก็บส่วนประกอบของ UI ที่สามารถนำกลับมาใช้ซ้ำได้
# ในที่นี้คือหน้าต่าง Pop-up สำหรับเลือกห้อง

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable

# Import แบบนี้เพื่อให้ Python รู้จัก Type 'FirebaseRTClient' ตอนเช็คโค้ด
# แต่ไม่ต้อง import จริงๆ ตอนโปรแกรมทำงาน (ป้องกัน circular import)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from firebase_client import FirebaseRTClient

class RoomPickerDialog(tk.Toplevel):
    """
    หน้าต่าง Pop-up สำหรับเลือกห้อง, สร้างห้อง, หรือคัดลอกรหัสห้อง
    """
    def __init__(self, master, fb: 'FirebaseRTClient', on_pick: Callable[[str], None], on_create: Callable[[], str]):
        super().__init__(master)
        self.fb = fb
        self.on_pick = on_pick # ฟังก์ชันที่จะถูกเรียกเมื่อผู้ใช้ 'เลือก' ห้อง
        self.on_create = on_create # ฟังก์ชันที่จะถูกเรียกเมื่อผู้ใช้ 'สร้าง' ห้อง

        self.title("เลือกหรือสร้างห้อง")
        self.geometry("420x420")
        self.resizable(False, False)
        self.transient(master) # ทำให้หน้าต่างนี้อยู่ข้างบนหน้าต่างหลักเสมอ
        self.grab_set() # ทำให้ผู้ใช้ต้องจัดการหน้าต่างนี้ให้เสร็จก่อนกลับไปหน้าต่างหลัก

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(wrap, text="ห้องของฉัน", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        self.listbox = tk.Listbox(wrap, height=12, exportselection=False, font=("Segoe UI", 10))
        self.listbox.pack(fill="both", expand=True, pady=(6, 8))
        self.listbox.bind("<Double-1>", lambda e: self._enter()) # ดับเบิ้ลคลิกเพื่อเข้าห้อง

        btns = ttk.Frame(wrap)
        btns.pack(fill="x")
        ttk.Button(btns, text="รีเฟรช", command=self.refresh).pack(side="left")
        ttk.Button(btns, text="สร้างห้องใหม่", command=self._create).pack(side="left", padx=6)
        ttk.Button(btns, text="เข้าห้อง", command=self._enter).pack(side="left", padx=6)
        ttk.Button(btns, text="คัดลอกรหัส", command=self._copy).pack(side="right")

        self.refresh() # โหลดรายชื่อห้องทันทีที่เปิด

    def refresh(self):
        """โหลดรายชื่อห้องจาก Firebase มาแสดงใหม่"""
        self.listbox.delete(0, tk.END)
        try:
            rooms = self.fb.list_my_rooms()
            for rid in rooms:
                owner = self.fb.get_room_owner(rid)
                me = self.fb.local_uid
                role = "owner" if owner == me else "member"
                self.listbox.insert(tk.END, f"{rid}   ({role})")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถโหลดรายชื่อห้องได้:\n{e}", parent=self)

    def _selected_room(self) -> Optional[str]:
        """ดึงรหัสห้องที่ถูกเลือกจาก Listbox"""
        sel = self.listbox.curselection()
        if not sel: return None
        text = self.listbox.get(sel[0])  # "R-XXXXXXX   (owner)"
        return text.split()[0]

    def _enter(self):
        """จัดการเมื่อกดปุ่ม 'เข้าห้อง'"""
        rid = self._selected_room()
        if not rid:
            messagebox.showinfo("เลือกห้อง", "กรุณาเลือกห้องก่อน", parent=self)
            return
        self.on_pick(rid)
        self.destroy() # ปิดหน้าต่าง Pop-up

    def _copy(self):
        """จัดการเมื่อกดปุ่ม 'คัดลอกรหัส'"""
        rid = self._selected_room()
        if not rid:
            messagebox.showinfo("คัดลอก", "กรุณาเลือกห้องก่อน", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(rid)
        messagebox.showinfo("คัดลอกแล้ว", f"คัดลอกรหัสห้อง {rid} แล้ว", parent=self)

    def _create(self):
        """จัดการเมื่อกดปุ่ม 'สร้างห้องใหม่'"""
        rid = self.on_create()
        if rid:
            messagebox.showinfo("สร้างห้องแล้ว", f"สร้างห้องใหม่สำเร็จ!\nเลขห้อง: {rid}\n(ใช้ปุ่ม 'เชิญเพื่อน' เพื่อเพิ่มสมาชิก)", parent=self)
            self.refresh()
