# ui_components.py
# เก็บส่วนประกอบของ UI ที่นำกลับมาใช้ซ้ำได้ เช่น Pop-up

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from firebase_client import FirebaseRTClient

class RoomPickerDialog(tk.Toplevel):
    """หน้าต่าง Pop-up สำหรับเลือก/สร้างห้อง"""
    def __init__(self, master, fb: 'FirebaseRTClient', on_pick: Callable[[str], None], on_create: Callable[[], str]):
        super().__init__(master)
        self.fb = fb
        self.on_pick = on_pick
        self.on_create = on_create

        self.title("เลือกหรือสร้างห้อง")
        self.geometry("420x420")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(wrap, text="ห้องของฉัน", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.listbox = tk.Listbox(wrap, height=12, exportselection=False, font=("Segoe UI", 10))
        self.listbox.pack(fill="both", expand=True, pady=(6, 8))
        self.listbox.bind("<Double-1>", lambda e: self._enter())

        btns = ttk.Frame(wrap)
        btns.pack(fill="x")
        ttk.Button(btns, text="รีเฟรช", command=self.refresh).pack(side="left")
        ttk.Button(btns, text="สร้างห้องใหม่", command=self._create).pack(side="left", padx=6)
        ttk.Button(btns, text="เข้าห้อง", command=self._enter).pack(side="left", padx=6)
        ttk.Button(btns, text="คัดลอกรหัส", command=self._copy).pack(side="right")
        self.refresh()

    def refresh(self):
        """โหลดรายชื่อห้องมาแสดงใหม่"""
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
        """ดึงรหัสห้องที่ถูกเลือก"""
        sel = self.listbox.curselection()
        if not sel: return None
        return self.listbox.get(sel[0]).split()[0]

    def _enter(self):
        """จัดการเมื่อกด 'เข้าห้อง'"""
        rid = self._selected_room()
        if not rid:
            messagebox.showinfo("เลือกห้อง", "กรุณาเลือกห้องก่อน", parent=self)
            return
        self.on_pick(rid)
        self.destroy()

    def _copy(self):
        """จัดการเมื่อกด 'คัดลอกรหัส'"""
        rid = self._selected_room()
        if not rid:
            messagebox.showinfo("คัดลอก", "กรุณาเลือกห้องก่อน", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(rid)
        messagebox.showinfo("คัดลอกแล้ว", f"คัดลอกรหัสห้อง {rid} แล้ว", parent=self)

    def _create(self):
        """จัดการเมื่อกด 'สร้างห้องใหม่'"""
        rid = self.on_create()
        if rid:
            messagebox.showinfo("สร้างห้องแล้ว", f"สร้างห้องใหม่สำเร็จ!\nเลขห้อง: {rid}\n(ใช้ปุ่ม 'เชิญเพื่อน' เพื่อเพิ่มสมาชิก)", parent=self)
            self.refresh()

