# app_ui.py
# ส่วนของหน้าตาโปรแกรม (Frontend) ทั้งหมด

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, font
from typing import Dict, Optional, Callable
from datetime import datetime, timedelta
import time
import threading

from bill_engine import Bill, Item
from firebase_client import FirebaseRTClient
from ui_components import RoomPickerDialog

class LoginFrame(ttk.Frame):
    """หน้าจอสำหรับ Login หรือสมัครสมาชิก"""
    def __init__(self, master, on_success: Callable[[FirebaseRTClient], None]):
        super().__init__(master)
        self.on_success = on_success
        self.grid(sticky="nsew", padx=24, pady=24)
        master.title("เข้าสู่ระบบ • Bill Split App"); master.geometry("420x320")
        master.columnconfigure(0, weight=1); master.rowconfigure(0, weight=1)

        style = ttk.Style(master)
        style.theme_use('clam')
        style.configure('TFrame', background="#FFB1B4")                # พื้นหลัง Frame สีชมพู
        style.configure('TLabel', background="#FFB1B4", foreground='#222')   # Label ตัวอักษรดำ พื้นชมพู
        style.configure('TButton', background="#FFE1E2", foreground='#222', font=('Segoe UI', 11, 'bold'))
        style.map('TButton', background=[('active', "#D0D0D0"), ('!active', "#FFFFFF")])
        frm = ttk.Frame(self); frm.pack(expand=True, fill="both")
        ttk.Label(frm, text="เข้าสู่ระบบ", font=("Segoe UI", 14, "bold")).pack(pady=(0,10))

        self.has_account = tk.BooleanVar(value=True)
        r1 = ttk.Frame(frm); r1.pack(fill="x")
        ttk.Radiobutton(r1, text="ฉันมีบัญชีแล้ว (Login)", variable=self.has_account, value=True, command=self._update_ui).pack(side="left")
        ttk.Radiobutton(r1, text="สมัครใหม่ (Sign up)", variable=self.has_account, value=False, command=self._update_ui).pack(side="left", padx=10)

        ttk.Label(frm, text="อีเมล").pack(anchor="w", pady=(10,2))
        self.email_entry = ttk.Entry(frm); self.email_entry.pack(fill="x")
        self.pwd_var = tk.StringVar(); self.cpwd_var = tk.StringVar()
        pw_block = ttk.Frame(frm); pw_block.pack(fill="x", pady=(8,0))
        ttk.Label(pw_block, text="รหัสผ่าน").pack(anchor="w")
        row = ttk.Frame(pw_block); row.pack(fill="x")
        self.pwd_entry = ttk.Entry(row, show="*", textvariable=self.pwd_var)
        self.pwd_entry.pack(side="left", fill="x", expand=True)
        self.show_pw_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="แสดง", variable=self.show_pw_var, command=self._toggle_password_visibility).pack(side="left", padx=8)
        self.cpw_frame = ttk.Frame(pw_block)
        ttk.Label(self.cpw_frame, text="ยืนยันรหัสผ่าน").pack(anchor="w", pady=(8,2))
        self.cpwd_entry = ttk.Entry(self.cpw_frame, show="*", textvariable=self.cpwd_var)
        self.cpwd_entry.pack(fill="x")
        self.action_button = ttk.Button(frm, text="เข้าสู่ระบบ", command=self.attempt_auth)
        self.action_button.pack(pady=16)
        self.status_label = ttk.Label(frm, text="", foreground="#666"); self.status_label.pack()

        for w in (self.email_entry, self.pwd_entry, self.cpwd_entry):
            w.bind("<Return>", lambda *_: self.attempt_auth())
        self._update_ui()

    def _update_ui(self):
        """อัปเดต UI ตามโหมด Login/Sign up"""
        is_login = self.has_account.get()
        self.cpw_frame.pack_forget() if is_login else self.cpw_frame.pack(fill="x")
        self.action_button.config(text="เข้าสู่ระบบ" if is_login else "สมัครสมาชิก")
            
    def _toggle_password_visibility(self):
        """สลับการแสดง/ซ่อนรหัสผ่าน"""
        self.pwd_entry.config(show="" if self.show_pw_var.get() else "*")

    def attempt_auth(self):
        """พยายาม Login หรือ Sign up"""
        email = self.email_entry.get().strip(); pwd = self.pwd_var.get().strip()
        if not email or not pwd:
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกอีเมลและรหัสผ่าน"); return
        if not self.has_account.get():
            cpwd = self.cpwd_var.get().strip()
            if len(pwd) < 6: messagebox.showwarning("รหัสผ่านสั้นไป", "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร"); return
            if pwd != cpwd: messagebox.showwarning("รหัสผ่านไม่ตรงกัน", "รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน"); return
        
        api_key = self.winfo_toplevel().FIREBASE_API_KEY
        rtdb_url = self.winfo_toplevel().FIREBASE_RTDB_URL
        if not api_key or not rtdb_url:
            messagebox.showerror("Config Error", "กรุณาตั้งค่า Firebase API Key และ RTDB URL ในไฟล์ main.py"); return
        
        fb = FirebaseRTClient(api_key, rtdb_url)
        try:
            self.status_label.config(text="กำลังเชื่อมต่อ..."); self.update_idletasks()
            fb.sign_in_email(email, pwd) if self.has_account.get() else fb.sign_up_email(email, pwd)
        except Exception as e:
            messagebox.showerror("เกิดข้อผิดพลาด", f"{e}"); self.status_label.config(text=""); return
        fb.start_auto_refresh()

        prof = fb.get_profile(fb.local_uid)
        if not prof or not prof.get("username"):
            while True:
                uname = simpledialog.askstring("ตั้ง Username", "ตั้ง Username สำหรับใช้ในแอป (ห้ามซ้ำ, ห้ามใช้อักขระพิเศษ .#$[]/)", parent=self)
                if not uname: return
                dname = simpledialog.askstring("ชื่อที่แสดง", "ชื่อที่จะให้แสดงในแอป (ถ้าว่างจะใช้ Username แทน)", parent=self) or uname
                try:
                    fb.reserve_username(uname); fb.save_profile(uname, dname); break
                except Exception as e:
                    messagebox.showerror("Username ไม่พร้อมใช้งาน", f"ไม่สามารถใช้ Username นี้ได้: {e}\nกรุณาลองใหม่อีกครั้ง")

        self.status_label.config(text="สำเร็จ! กำลังเปิดแอปพลิเคชัน…")
        self.after(100, lambda: self.on_success(fb))

class BillSplitApp(ttk.Frame):
    """หน้าต่างหลักของโปรแกรม"""
    def __init__(self, master, fb: FirebaseRTClient):
        super().__init__(master)
        self.fb = fb; self.bill = Bill(); self.room_id: Optional[str] = None
        self._local_change = False; self._last_remote_ua: Optional[float] = None
        self.name_cache: Dict[str, str] = {}; self.label2uid: Dict[str, str] = {}
        self.small_wins_data: Optional[Dict] = None

        master.title("หารค่าอาหาร & เป้าหมายเล็กๆ • Tkinter + Firebase"); master.geometry("1120x700")
        self.pack(fill=tk.BOTH, expand=True)

        default_font = font.nametofont("TkDefaultFont")
        self.completed_font = font.Font(family=default_font.cget("family"), size=default_font.cget("size"), overstrike=True)
        self._build_layout()
        self.after(200, self.open_room_picker)

    def _build_layout(self):
        """สร้าง Layout หลักของโปรแกรม"""
        top_bar = ttk.Frame(self); top_bar.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Label(top_bar, text="สถานะ:", font=("Segoe UI", 10)).pack(side="left")
        self.status_label = ttk.Label(top_bar, text="ยังไม่ได้เลือกห้อง", font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side="left", padx=(4, 12))
        ttk.Button(top_bar, text="เลือก/สร้างห้อง", command=self.open_room_picker).pack(side="left")
        ttk.Button(top_bar, text="เชิญเพื่อนเข้าห้อง", command=self.invite_member).pack(side="left", padx=4)
        ttk.Button(top_bar, text="คัดลอกรหัสห้อง", command=self.copy_room_id).pack(side="left")

        self.notebook = ttk.Notebook(self); self.notebook.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        bill_tab = ttk.Frame(self.notebook); self.notebook.add(bill_tab, text="💰 หารบิล")
        sw_tab = ttk.Frame(self.notebook); self.notebook.add(sw_tab, text="🏆 เป้าหมายเล็กๆ (Small Wins)")
        self._build_bill_tab(bill_tab)
        self._build_small_wins_tab(sw_tab)

    def _build_bill_tab(self, parent):
        """สร้าง Layout ของ Tab หารบิล"""
        parent.columnconfigure(1, weight=1); parent.rowconfigure(0, weight=1)
        left = ttk.Frame(parent); left.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)
        
        ttk.Label(left, text="รายชื่อเพื่อน (ที่ใช้งานอยู่)", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.person_entry = ttk.Entry(left, width=22); self.person_entry.grid(row=1, column=0, sticky="ew")
        ttk.Button(left, text="เพิ่ม (UID/username)", command=self.add_person).grid(row=1, column=1, padx=5)
        self.people_list = tk.Listbox(left, height=5, exportselection=False); self.people_list.grid(row=2, column=0, columnspan=2, sticky="we", pady=5)
        ttk.Button(left, text="เคลียร์ยอดและนำออก", command=self.remove_person).grid(row=3, column=0, columnspan=2, sticky="we")

        ttk.Label(left, text="Service/VAT/Tip", font=("Segoe UI", 11, "bold")).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10,5))
        frm_cfg = ttk.Frame(left); frm_cfg.grid(row=5, column=0, columnspan=2, sticky="we")
        self.service_var=tk.StringVar(value="0"); self.vat_var=tk.StringVar(value="0"); self.tip_var=tk.StringVar(value="0")
        ttk.Label(frm_cfg, text="Service %").grid(row=0, column=0, sticky="w"); ttk.Entry(frm_cfg, textvariable=self.service_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Label(frm_cfg, text="VAT %").grid(row=1, column=0, sticky="w"); ttk.Entry(frm_cfg, textvariable=self.vat_var, width=10).grid(row=1, column=1, padx=5)
        ttk.Label(frm_cfg, text="Tip (บาท)").grid(row=2, column=0, sticky="w"); ttk.Entry(frm_cfg, textvariable=self.tip_var, width=10).grid(row=2, column=1, padx=5)
        ttk.Button(left, text="อัปเดตค่าใช้จ่าย", command=self.update_config).grid(row=6, column=0, columnspan=2, sticky="we", pady=5)

        ttk.Label(left, text="เพิ่มรายการอาหาร", font=("Segoe UI", 11, "bold")).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10,5))
        frm_item = ttk.Frame(left); frm_item.grid(row=8, column=0, columnspan=2, sticky="we")
        ttk.Label(frm_item, text="ชื่อเมนู").grid(row=0, column=0, sticky="w"); self.item_name = ttk.Entry(frm_item, width=22); self.item_name.grid(row=0, column=1, sticky="we", pady=1)
        ttk.Label(frm_item, text="ราคา").grid(row=1, column=0, sticky="w"); self.item_price = ttk.Entry(frm_item, width=22); self.item_price.grid(row=1, column=1, sticky="we", pady=1)
        ttk.Label(frm_item, text="คนจ่าย").grid(row=2, column=0, sticky="w"); self.payer_combo = ttk.Combobox(frm_item, values=[], state="readonly", width=20); self.payer_combo.grid(row=2, column=1, sticky="we", pady=1)
        ttk.Label(frm_item, text="คนกิน").grid(row=3, column=0, sticky="nw"); self.participants_list = tk.Listbox(frm_item, selectmode=tk.MULTIPLE, height=4, exportselection=False); self.participants_list.grid(row=3, column=1, sticky="we", pady=1)
        self.all_var=tk.BooleanVar(value=False); ttk.Checkbutton(frm_item, text="ทุกคน", variable=self.all_var, command=self.toggle_all_participants).grid(row=4, column=1, sticky="w")
        self.use_weights=tk.BooleanVar(value=False); ttk.Checkbutton(frm_item, text="หารไม่เท่ากัน (weights)", variable=self.use_weights).grid(row=5, column=1, sticky="w", pady=(4,0))
        btns = ttk.Frame(left); btns.grid(row=9, column=0, columnspan=2, sticky="we", pady=6)
        ttk.Button(btns, text="เพิ่มรายการ", command=self.add_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="ลบรายการที่เลือก", command=self.remove_selected_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        ttk.Label(left, text="เพิ่มรายการโอนเงิน", font=("Segoe UI", 11, "bold")).grid(row=10, column=0, columnspan=2, sticky="w", pady=(10,5))
        frm_tf = ttk.Frame(left); frm_tf.grid(row=11, column=0, columnspan=2, sticky="we")
        ttk.Label(frm_tf, text="จาก:").grid(row=0, column=0, sticky="w"); self.tf_from = ttk.Combobox(frm_tf, values=[], state="readonly", width=20); self.tf_from.grid(row=0, column=1, sticky="we", pady=1)
        ttk.Label(frm_tf, text="ถึง:").grid(row=1, column=0, sticky="w"); self.tf_to = ttk.Combobox(frm_tf, values=[], state="readonly", width=20); self.tf_to.grid(row=1, column=1, sticky="we", pady=1)
        ttk.Label(frm_tf, text="จำนวน:").grid(row=2, column=0, sticky="w"); self.tf_amount = ttk.Entry(frm_tf, width=22); self.tf_amount.grid(row=2, column=1, sticky="we", pady=1)
        ttk.Button(left, text="เพิ่มรายการโอน", command=self.add_transfer).grid(row=12, column=0, columnspan=2, sticky="we", pady=5)
        
        right = ttk.Frame(parent); right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right.rowconfigure(1, weight=3); right.rowconfigure(3, weight=1); right.rowconfigure(6, weight=2); right.columnconfigure(0, weight=1)
        ttk.Label(right, text="รายการทั้งหมด", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.table_cols = ("idx","name","price","payer","count","participants")
        self.table = ttk.Treeview(right, columns=self.table_cols, show="headings", height=10, selectmode="browse")
        heads = {"idx":"#","name":"เมนู","price":"ราคา","payer":"คนจ่าย","count":"คนกิน","participants":"รายชื่อ"}
        widths={"idx":40,"name":200,"price":90,"payer":110,"count":60,"participants":350}
        for k in self.table_cols: self.table.heading(k, text=heads[k]); self.table.column(k, width=widths[k], anchor="w")
        for col in ("idx", "price", "count"): self.table.column(col, anchor="e")
        self.table.grid(row=1, column=0, sticky="nsew"); scr = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.table.yview); self.table.configure(yscrollcommand=scr.set); scr.grid(row=1, column=1, sticky="ns")
        
        ttk.Label(right, text="รายการโอนเงินระหว่างบุคคล (คืนเงิน/จ่ายล่วงหน้า)", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10,0))
        self.tf_cols = ("idx", "from", "to", "amount")
        self.tf_table = ttk.Treeview(right, columns=self.tf_cols, show="headings", height=3, selectmode="browse")
        tf_heads = {"idx":"#", "from":"จาก", "to":"ถึง", "amount":"จำนวนเงิน (บาท)"}
        for k in self.tf_cols: self.tf_table.heading(k, text=tf_heads[k]); self.tf_table.column(k, anchor="w")
        self.tf_table.column("idx", anchor="e", width=40); self.tf_table.column("amount", anchor="e", width=150)
        self.tf_table.grid(row=3, column=0, sticky="nsew"); scr_tf = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.tf_table.yview); self.tf_table.configure(yscrollcommand=scr_tf.set); scr_tf.grid(row=3, column=1, sticky="ns")
        
        ttk.Button(right, text="ลบรายการโอนที่เลือก", command=self.remove_selected_transfer).grid(row=4, column=0, columnspan=2, sticky="e", pady=5)
        ttk.Label(right, text="สรุปผล", font=("Segoe UI", 11, "bold")).grid(row=5, column=0, columnspan=2, sticky="w")
        self.output = tk.Text(right, height=10, font=("Consolas", 9)); self.output.grid(row=6, column=0, columnspan=2, sticky="nsew")
        
    def _build_small_wins_tab(self, parent):
        """สร้าง Layout ของ Tab Small Wins"""
        parent.columnconfigure(0, weight=1); parent.rowconfigure(1, weight=1)
        add_frame = ttk.LabelFrame(parent, text="ตั้งเป้าหมายใหม่ของฉัน", padding=10)
        add_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        add_frame.columnconfigure(0, weight=1)
        ttk.Label(add_frame, text="เป้าหมาย:").grid(row=0, column=0, sticky="w")
        self.sw_goal_text = ttk.Entry(add_frame); self.sw_goal_text.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        ttk.Label(add_frame, text="ทำให้สำเร็จใน (วัน):").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.sw_deadline_days = ttk.Entry(add_frame, width=10); self.sw_deadline_days.grid(row=1, column=1, sticky="w", padx=(10, 5))
        ttk.Button(add_frame, text="ตั้งเป้าหมาย", command=self.add_small_win).grid(row=1, column=2)
        
        main_frame = ttk.Frame(parent); main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=0)
        main_frame.rowconfigure(0, weight=1); main_frame.columnconfigure(0, weight=1)
        self.sw_cols = ("status", "goal", "owner", "deadline", "nudges", "goal_id", "owner_uid")
        self.sw_table = ttk.Treeview(main_frame, columns=self.sw_cols, show="headings", selectmode="browse")
        heads = {"status": "สถานะ", "goal":"เป้าหมาย (Goal)", "owner":"เจ้าของ", "deadline":"เดดไลน์", "nudges":"สะกิด"}
        widths= {"status": 80, "goal":450, "owner":150, "deadline":150, "nudges":80}
        for col, head in heads.items(): self.sw_table.heading(col, text=head); self.sw_table.column(col, width=widths[col], anchor="w")
        for col in ("nudges", "status"): self.sw_table.column(col, anchor="center")
        for col in ("goal_id", "owner_uid"): self.sw_table.column(col, width=0, stretch=False)
        self.sw_table.grid(row=0, column=0, sticky="nsew")
        sw_scr = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.sw_table.yview); self.sw_table.configure(yscrollcommand=sw_scr.set); sw_scr.grid(row=0, column=1, sticky="ns")
        self.sw_table.bind("<<TreeviewSelect>>", self.on_goal_select)
        self.sw_table.tag_configure("completed", foreground="gray", font=self.completed_font)

        action_frame = ttk.Frame(parent); action_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        self.sw_nudge_btn = ttk.Button(action_frame, text="👉 สะกิดเพื่อน (Nudge)", command=self.nudge_selected_goal, state="disabled"); self.sw_nudge_btn.pack(side="left")
        self.sw_complete_btn = ttk.Button(action_frame, text="✅ ทำสำเร็จแล้ว", command=self.complete_selected_goal, state="disabled"); self.sw_complete_btn.pack(side="left", padx=10)
        self.sw_delete_btn = ttk.Button(action_frame, text="🗑️ ลบเป้าหมาย", command=self.delete_selected_goal, state="disabled"); self.sw_delete_btn.pack(side="left", padx=10)

    def open_room_picker(self):
        """เปิด Pop-up สำหรับเลือก/สร้างห้อง"""
        RoomPickerDialog(self, self.fb, on_pick=self._pick_room, on_create=self._create_room)

    def _pick_room(self, room_id: str):
        """Callback เมื่อผู้ใช้เลือกห้อง"""
        if not room_id: return
        try:
            self.room_id = room_id
            owner = self.fb.get_room_owner(room_id); role = "Owner" if owner == self.fb.local_uid else "Member"
            my_username = self._label_for(self.fb.local_uid)
            self.status_label.config(text=f"'{my_username}' เป็น {role} ในห้อง: {room_id}")
            self.bind_room(room_id)
        except Exception as e: messagebox.showerror("ผิดพลาด", f"ไม่สามารถเข้าห้องได้:\n{e}")

    def _create_room(self) -> str:
        """Callback เมื่อผู้ใช้สร้างห้องใหม่"""
        try:
            rid = self.fb.create_room(); self._pick_room(rid); return rid
        except Exception as e: messagebox.showerror("สร้างห้องไม่ได้", str(e)); return ""

    def copy_room_id(self):
        if not self.room_id: messagebox.showinfo("ยังไม่มีห้อง", "โปรดเลือกหรือสร้างห้องก่อน"); return
        self.clipboard_clear(); self.clipboard_append(self.room_id)
        messagebox.showinfo("คัดลอกแล้ว", f"คัดลอกรหัสห้อง {self.room_id} แล้ว")

    def bind_room(self, room_id: str):
        """เริ่มเชื่อมต่อและฟังข้อมูลของห้องที่เลือก"""
        threading.Thread(target=self._fetch_and_cache_member_profiles, daemon=True).start()

        def on_bill_event(_ev):
            if self._local_change: return
            try:
                full_data = self.fb.get(f"bills/{room_id}")
                if not isinstance(full_data, dict): return
                ua = full_data.get("updatedAt")
                if ua is not None and ua == self._last_remote_ua: return
                self._last_remote_ua = ua; self.bill = Bill.from_dict(full_data)
                self.after(0, self._render_all_from_bill)
            except Exception: pass

        def on_sw_event(ev):
            if self._local_change: return
            try:
                new_data = self.fb.get(f"small_wins/{self.room_id}") or {}
                self._check_for_nudge(new_data)
                self.small_wins_data = new_data
                self.after(0, lambda: self._render_small_wins(new_data))
            except Exception: pass

        try:
            self.fb.stream(f"bills/{room_id}", on_bill_event); self.fb.stream(f"small_wins/{room_id}", on_sw_event)
            initial_bill_data = self.fb.get(f"bills/{room_id}")
            if initial_bill_data: self.bill = Bill.from_dict(initial_bill_data)
            self.small_wins_data = self.fb.get(f"small_wins/{room_id}")
            self._render_all_from_bill(); self._render_small_wins(self.small_wins_data)
        except Exception as e: messagebox.showerror("ผิดพลาด", f"ไม่สามารถเชื่อมต่อกับห้องได้:\n{e}")

    def invite_member(self):
        """เชิญเพื่อนเข้าห้อง"""
        if not self.room_id: messagebox.showwarning("ยังไม่ได้เลือกห้อง","โปรดเลือกหรือสร้างห้องก่อน"); return
        owner = self.fb.get_room_owner(self.room_id)
        if owner != self.fb.local_uid: messagebox.showwarning("เฉพาะเจ้าของห้อง", "คุณไม่ใช่เจ้าของห้องนี้"); return
        key = simpledialog.askstring("เชิญเพื่อน", "กรอก username หรือ UID ของเพื่อน:", parent=self)
        if not key: return
        try:
            target_uid = self.fb.uid_from_username(key) if len(key) < 28 else key
            if not target_uid: messagebox.showerror("ไม่พบ", f"ไม่พบผู้ใช้: {key}"); return
            self.fb.add_member(self.room_id, target_uid); self.bill.add_person(target_uid)
            self._push_bill(); self._render_all_from_bill()
            messagebox.showinfo("สำเร็จ", f"เชิญ '{self._label_for(target_uid)}' เข้าห้องแล้ว")
        except Exception as e: messagebox.showerror("เชิญไม่ได้", str(e))

    def _fetch_and_cache_member_profiles(self):
        """โหลดโปรไฟล์สมาชิกมาเก็บใน Cache"""
        if not self.room_id: return
        try:
            members = self.fb.get(f"rooms/{self.room_id}/members") or {}
            for uid in members.keys(): self._label_for(uid)
            # ดึงโปรไฟล์ของคนที่เคยอยู่ในบิลแต่ตอนนี้ออกไปแล้วด้วย
            all_uids_in_bill = set()
            bill_data = self.fb.get(f"bills/{self.room_id}")
            if bill_data:
                for item in bill_data.get("items", []):
                    all_uids_in_bill.add(item.get("payer"))
                    all_uids_in_bill.update(item.get("participants", []))
                for transfer in bill_data.get("transfers", []):
                    all_uids_in_bill.add(transfer.get("from"))
                    all_uids_in_bill.add(transfer.get("to"))
            
            for uid in all_uids_in_bill:
                if uid: self._label_for(uid)

            self.after(0, self._rerender_all_ui)
        except Exception: pass

    def _label_for(self, uid: str) -> str:
        """แปลง UID เป็นชื่อที่แสดงผล"""
        if not uid: return "N/A"
        if uid in self.name_cache: return self.name_cache[uid]
        label = uid[:6] + "..."
        try:
            prof = self.fb.get_profile(uid)
            if prof: label = prof.get("username") or prof.get("displayName") or label
        except Exception: pass
        self.name_cache[uid] = label; self.label2uid[label] = uid
        return label

    def _push_bill(self):
        """ส่งข้อมูล Bill ปัจจุบันไปบันทึกที่ Firebase"""
        if not self.room_id: return
        try:
            self._local_change = True
            data = self.bill.to_dict(); data["lastEditBy"] = self.fb.local_uid
            self.fb.put(f"bills/{self.room_id}", data)
            self._last_remote_ua = data["updatedAt"]
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))

    def _rerender_all_ui(self):
        """สั่งให้ UI ทุกส่วนอัปเดตข้อมูล"""
        self._render_all_from_bill()
        self._render_small_wins(self.small_wins_data)

    def _render_all_from_bill(self):
        """อัปเดต UI ทุกส่วนที่เกี่ยวกับบิล"""
        self.service_var.set(f"{self.bill.service_pct:g}"); self.vat_var.set(f"{self.bill.vat_pct:g}"); self.tip_var.set(f"{self.bill.tip:g}")
        people_labels = sorted([self._label_for(uid) for uid in self.bill.people.keys()])
        self.payer_combo["values"] = people_labels; self.tf_from["values"] = people_labels; self.tf_to["values"] = people_labels
        if not self.payer_combo.get() and people_labels: self.payer_combo.set(people_labels[0])
        self.participants_list.delete(0, tk.END); self.people_list.delete(0, tk.END)
        for label in people_labels: self.participants_list.insert(tk.END, label); self.people_list.insert(tk.END, label)
        self._rebuild_table(); self._rebuild_transfers_table(); self.refresh_summary()

    def _rebuild_table(self):
        """สร้างตารางรายการอาหารใหม่"""
        self.table.delete(*self.table.get_children())
        for i, it in enumerate(self.bill.items):
            row=(i+1, it.name, f"{it.price:,.2f}", self._label_for(it.payer), len(it.participants), ", ".join(self._label_for(u) for u in it.participants))
            self.table.insert("", tk.END, values=row)

    def _rebuild_transfers_table(self):
        """สร้างตารางรายการโอนเงินใหม่"""
        self.tf_table.delete(*self.tf_table.get_children())
        for i, t in enumerate(self.bill.transfers):
            row = (i + 1, self._label_for(t['from']), self._label_for(t['to']), f"{t['amount']:,.2f}")
            self.tf_table.insert("", "end", values=row)

    def toggle_all_participants(self):
        """เลือก/ไม่เลือกเพื่อนทั้งหมดในช่อง 'คนกิน'"""
        select_op = self.participants_list.select_set if self.all_var.get() else self.participants_list.select_clear
        select_op(0, tk.END)

    def refresh_summary(self):
        """คำนวณและแสดงผลสรุป"""
        try:
            # ดึงรายชื่อทั้งหมดที่เคยมีส่วนร่วมในบิล เพื่อให้แสดงผลครบทุกคนแม้จะถูกนำออกไปแล้ว
            all_uids_in_bill = set()
            for item in self.bill.items:
                all_uids_in_bill.add(item.payer)
                all_uids_in_bill.update(item.participants)
            for transfer in self.bill.transfers:
                all_uids_in_bill.add(transfer['from'])
                all_uids_in_bill.add(transfer['to'])
            all_uids_in_bill.update(self.bill.people.keys()) # รวมคนที่ยัง active อยู่
            
            subtotal, svc, vat, total = self.bill._totals()
            should = self.bill.summary_costs(); paid = self.bill.paid_map()
            net = self.bill.net_balance(); txs = self.bill.settle_transactions()
            raw_debts = self.bill.calculate_raw_debts()
        except Exception as e:
            self.output.delete(1.0, tk.END); self.output.insert(tk.END, f"Error:\n{e}"); return
        
        money = lambda x: f"{x:,.2f} บาท"
        lines = ["สรุปร้าน/บิล", f"  Subtotal: {money(subtotal)}", f"  Service {self.bill.service_pct:g}%: {money(svc)}",
                 f"  VAT {self.bill.vat_pct:g}%: {money(vat)}", f"  Tip: {money(self.bill.tip)}", f"  Total: {money(total)}",
                 "\nควรจ่าย (ยอดรวม)", *[f"  - {self._label_for(uid)}: {money(should.get(uid,0.0))}" for uid in sorted(list(all_uids_in_bill), key=self._label_for) if uid],
                 "\nจ่ายไปแล้ว", *[f"  - {self._label_for(uid)}: {money(paid.get(uid,0.0))}" for uid in sorted(list(all_uids_in_bill), key=self._label_for) if uid],
                 "\nดุลสุทธิ (บวก=ได้คืน, ลบ=ต้องจ่ายเพิ่ม) *รวมรายการโอนแล้ว*", *[f"  - {self._label_for(uid)}: {money(net.get(uid,0.0))}" for uid in sorted(list(all_uids_in_bill), key=self._label_for) if uid],
                 "\nรายละเอียดการค้างจ่าย (ใครออกเงินให้ใครก่อน)"]
        
        if not raw_debts: lines.append("  ไม่มีการค้างจ่ายระหว่างเพื่อน")
        else:
            for payer_uid, debtor_map in sorted(raw_debts.items(), key=lambda x: self._label_for(x[0])):
                for debtor_uid, debt_info in sorted(debtor_map.items(), key=lambda x: self._label_for(x[0])):
                    if debt_info['total'] > 0.01:
                        lines.append(f"  - {self._label_for(debtor_uid)} ค้างจ่าย {self._label_for(payer_uid)}: {money(debt_info['total'])}")
                        items_str = ", ".join(debt_info['items']); lines.append(f"    (จาก: {items_str[:57] + '...' if len(items_str) > 60 else items_str})")
        
        lines.append("\nข้อเสนอแนะการโอนเงิน (ยอดสุทธิ)")
        if not txs: lines.append("  เคลียร์แล้ว 🎉")
        else: lines.extend([f"  - {self._label_for(t['from'])} → {self._label_for(t['to'])}: {money(t['amount'])}" for t in txs])
        
        self.output.delete(1.0, tk.END); self.output.insert(tk.END, "\n".join(lines))

    def add_person(self):
        key = self.person_entry.get().strip()
        if not key: return
        try:
            uid = self.fb.uid_from_username(key) if len(key) < 28 else key
            if not uid: messagebox.showerror("ไม่พบ", f"ไม่พบผู้ใช้: {key}"); return
            self.bill.add_person(uid); self._label_for(uid); self.person_entry.delete(0,tk.END)
            self._push_bill(); self._rerender_all_ui()
        except Exception as e: messagebox.showerror("ผิดพลาด", str(e))

    def remove_person(self):
        sel = self.people_list.curselection()
        if not sel: 
            messagebox.showinfo("แนะนำ", "เลือกชื่อเพื่อนที่ต้องการเคลียร์ยอดและนำออกจากลิสต์ที่ใช้งานอยู่")
            return
        uid = self.label2uid.get(self.people_list.get(sel[0]))
        if not uid: return
        try:
            self.bill.remove_person(uid)
            self._push_bill()
            self._rerender_all_ui()
            messagebox.showinfo("สำเร็จ", f"'{self._label_for(uid)}' ถูกเคลียร์ยอดและนำออกจากรายชื่อที่ใช้งานอยู่แล้ว")
        except Exception as e: messagebox.showerror("ลบไม่ได้", str(e))

    def update_config(self):
        try:
            f = lambda s: float((s or "0").strip())
            self.bill.service_pct = f(self.service_var.get()); self.bill.vat_pct = f(self.vat_var.get()); self.bill.tip = f(self.tip_var.get())
            self._push_bill(); self.refresh_summary()
        except Exception as e: messagebox.showerror("ผิดพลาด", str(e))

    def add_item(self):
        name = self.item_name.get().strip(); price_raw = self.item_price.get().strip()
        payer_label = self.payer_combo.get().strip()
        sel_labels = [self.participants_list.get(i) for i in self.participants_list.curselection()]
        parts_uids = [self.label2uid[label] for label in sel_labels if label in self.label2uid]
        if not all([name, price_raw, payer_label, parts_uids]): messagebox.showwarning("ข้อมูลไม่ครบ","กรุณากรอกข้อมูลให้ครบ"); return
        payer_uid = self.label2uid.get(payer_label)
        if not payer_uid: return
        try: price = float(price_raw)
        except: messagebox.showerror("ผิดพลาด","ราคาไม่ถูกต้อง"); return
        weights = None
        if self.use_weights.get():
            weights = {}
            for uid in parts_uids:
                w = simpledialog.askstring("Weight", f"ใส่ Weight ของ '{self._label_for(uid)}' (>0):", parent=self)
                if w is None: return
                try: v=float(w); assert v > 0; weights[uid] = v
                except: messagebox.showwarning("ผิดพลาด","กรุณาใส่ Weight เป็นตัวเลขที่มากกว่า 0"); return
        try:
            self.bill.add_item(Item(name=name, price=price, payer=payer_uid, participants=parts_uids, weights=weights))
            self.item_name.delete(0,tk.END); self.item_price.delete(0,tk.END)
            self._push_bill(); self._rerender_all_ui()
        except Exception as e: messagebox.showerror("ผิดพลาด", str(e))

    def remove_selected_item(self):
        sel = self.table.selection()
        if not sel: return
        try:
            idx1 = int(self.table.item(sel[0], "values")[0])
            self.bill.remove_item_at(idx1 - 1); self._push_bill(); self._rerender_all_ui()
        except (ValueError, IndexError): return

    def add_transfer(self):
        """เพิ่มรายการโอนเงิน"""
        from_label = self.tf_from.get(); to_label = self.tf_to.get(); amount_raw = self.tf_amount.get().strip()
        if not from_label or not to_label or not amount_raw: messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณาเลือกผู้โอน, ผู้รับ, และจำนวนเงิน"); return
        from_uid = self.label2uid.get(from_label); to_uid = self.label2uid.get(to_label)
        if not from_uid or not to_uid: messagebox.showerror("ผิดพลาด", "ไม่พบ UID ของผู้ใช้"); return
        try:
            amount = float(amount_raw)
            self.bill.add_transfer(from_uid, to_uid, amount); self.tf_amount.delete(0, tk.END)
            self._push_bill(); self._rerender_all_ui()
        except Exception as e: messagebox.showerror("ผิดพลาด", str(e))

    def remove_selected_transfer(self):
        """ลบรายการโอนที่เลือก"""
        sel = self.tf_table.selection()
        if not sel: return
        try:
            idx1 = int(self.tf_table.item(sel[0], "values")[0])
            self.bill.remove_transfer_at(idx1 - 1); self._push_bill(); self._rerender_all_ui()
        except (ValueError, IndexError): return

    def _render_small_wins(self, goals_data: Optional[Dict]):
        """วาดตาราง Small Wins ใหม่"""
        self.sw_table.delete(*self.sw_table.get_children())
        if not goals_data or not isinstance(goals_data, dict): return
        sorted_goals = sorted(goals_data.items(), key=lambda item: item[1].get('createdAt', 0), reverse=True)
        for goal_id, goal in sorted_goals:
            owner_uid = goal.get("ownerUid", "N/A")
            deadline_ts = goal.get("deadline", 0)
            is_completed = goal.get("isCompleted", False)
            status_text = "✅ สำเร็จ" if is_completed else "⏳ กำลังทำ"
            tags = ("completed",) if is_completed else ()
            row = (status_text, goal.get("goalText", ""), self._label_for(owner_uid), 
                   datetime.fromtimestamp(deadline_ts).strftime('%d %b %Y') if deadline_ts > 0 else "N/A",
                   len(goal.get("nudges", {})), goal_id, owner_uid)
            self.sw_table.insert("", "end", values=row, tags=tags)
        self.on_goal_select(None)

    def _check_for_nudge(self, new_data: dict):
        """ตรวจสอบว่าเป้าหมายของเราถูกสะกิดหรือไม่"""
        if not self.small_wins_data or not isinstance(self.small_wins_data, dict): return
        for goal_id, new_goal in new_data.items():
            if (goal_id in self.small_wins_data and new_goal.get("ownerUid") == self.fb.local_uid):
                old_nudges = self.small_wins_data[goal_id].get("nudges", {}) or {}
                new_nudges = new_goal.get("nudges", {}) or {}
                new_nudger_uids = set(new_nudges.keys()) - set(old_nudges.keys())
                if new_nudger_uids:
                    nudger_name = self._label_for(list(new_nudger_uids)[0])
                    goal_text = new_goal.get('goalText', '')
                    self.after(0, lambda n=nudger_name, g=goal_text: messagebox.showinfo("มีคนสะกิดคุณ!", f"คุณ '{n}' สะกิดเป้าหมาย:\n'{g}'"))
            
    def _push_sw_and_rerender(self, method: str, path: str, payload: Optional[dict] = None):
        """[FIX] Helper function: ส่งข้อมูลไป Firebase และสั่ง re-render ทันที"""
        try:
            self._local_change = True
            fb_method = getattr(self.fb, method)
            if payload is not None: fb_method(path, payload)
            else: fb_method(path)
            self.small_wins_data = self.fb.get(f"small_wins/{self.room_id}") or {}
            self._render_small_wins(self.small_wins_data)
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"การอัปเดตข้อมูลล้มเหลว: {e}")
        finally:
            self.after(300, lambda: setattr(self, "_local_change", False))

    def add_small_win(self):
        """เพิ่มเป้าหมายใหม่"""
        goal_text = self.sw_goal_text.get().strip(); days_str = self.sw_deadline_days.get().strip()
        if not self.room_id or not goal_text or not days_str: messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกเป้าหมายและจำนวนวัน"); return
        try: days = int(days_str); assert days > 0
        except: messagebox.showwarning("ผิดพลาด", "กรุณาใส่จำนวนวันเป็นตัวเลขที่มากกว่า 0"); return
        deadline_ts = int((datetime.now() + timedelta(days=days)).timestamp())
        payload = {"goalText": goal_text, "ownerUid": self.fb.local_uid, "createdAt": int(time.time()), "deadline": deadline_ts, "isCompleted": False}
        self._push_sw_and_rerender('post', f"small_wins/{self.room_id}", payload)
        self.sw_goal_text.delete(0, tk.END); self.sw_deadline_days.delete(0, tk.END)

    def on_goal_select(self, event):
        """อัปเดตสถานะปุ่มต่างๆ เมื่อเลือกเป้าหมาย"""
        sel = self.sw_table.selection()
        if not sel:
            for btn in (self.sw_nudge_btn, self.sw_delete_btn, self.sw_complete_btn): btn.config(state="disabled")
            return
        item = self.sw_table.item(sel[0]); values = item['values']; tags = item['tags']
        if not values: return
        owner_uid = values[self.sw_cols.index("owner_uid")]; is_my_goal = (owner_uid == self.fb.local_uid); is_completed = "completed" in tags
        self.sw_delete_btn.config(state="normal" if is_my_goal else "disabled")
        self.sw_nudge_btn.config(state="disabled" if is_my_goal or is_completed else "normal")
        self.sw_complete_btn.config(state="disabled" if not is_my_goal or is_completed else "normal")

    def get_selected_goal_id(self) -> Optional[str]:
        """ดึง ID ของเป้าหมายที่ถูกเลือก"""
        sel = self.sw_table.selection()
        return self.sw_table.item(sel[0])['values'][self.sw_cols.index("goal_id")] if sel else None
        
    def nudge_selected_goal(self):
        """ส่ง 'สะกิด' ไปยังเป้าหมาย"""
        goal_id = self.get_selected_goal_id()
        if not self.room_id or not goal_id: return
        path = f"small_wins/{self.room_id}/{goal_id}/nudges/{self.fb.local_uid}"
        self._push_sw_and_rerender('put', path, int(time.time()))
            
    def delete_selected_goal(self):
        """ลบเป้าหมาย"""
        goal_id = self.get_selected_goal_id()
        if not self.room_id or not goal_id or not messagebox.askyesno("ยืนยัน", "แน่ใจว่าจะลบเป้าหมายนี้?"): return
        path = f"small_wins/{self.room_id}/{goal_id}"
        self._push_sw_and_rerender('delete', path)

    def complete_selected_goal(self):
        """อัปเดตสถานะเป้าหมายเป็น 'สำเร็จ'"""
        goal_id = self.get_selected_goal_id()
        if not self.room_id or not goal_id: return
        path = f"small_wins/{self.room_id}/{goal_id}"
        payload = {"isCompleted": True, "completedAt": int(time.time())}
        self._push_sw_and_rerender('patch', path, payload)

