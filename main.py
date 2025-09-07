# bill_split_tkinter_app.py
# GUI หารค่าอาหารด้วย Tkinter (ไฟล์เดียวจบ รันได้เลย)
# - รองรับเพิ่มเพื่อน
# - เพิ่มเมนูอาหาร กำหนดคนจ่าย/คนร่วมกิน
# - เลือกหารเท่ากันหรือกำหนดน้ำหนัก (weights) ได้
# - ตั้ง service %, VAT %, tip
# - สรุปยอด ใครควรจ่าย/จ่ายไปแล้ว/ดุลสุทธิ และรายการโอนเคลียร์กัน

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# =====================
# Core Logic (Bill Engine)
# =====================
@dataclass
class Person:
    name: str

@dataclass
class Item:
    name: str
    price: float
    payer: str                   # ชื่อคนที่จ่ายก่อน
    participants: List[str]      # รายชื่อคนที่ร่วมกิน/หาร
    weights: Optional[Dict[str, float]] = None  # ถ้าหารไม่เท่ากัน ให้ใส่น้ำหนัก เช่น {"A":2, "B":1}

@dataclass
class Bill:
    people: Dict[str, Person] = field(default_factory=dict)
    items: List[Item] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    def add_person(self, name: str):
        name = name.strip()
        if not name:
            raise ValueError("ชื่อว่างไม่ได้")
        self.people.setdefault(name, Person(name=name))

    def remove_person(self, name: str):
        if name in self.people:
            # ห้ามลบถ้ายังมี item ที่อ้างถึง
            for it in self.items:
                if it.payer == name or name in it.participants:
                    raise ValueError("ลบไม่ได้: มีรายการที่เกี่ยวข้องกับคนนี้")
            del self.people[name]

    def add_item(self, item: Item):
        if item.payer not in self.people:
            raise ValueError(f"ไม่พบผู้จ่ายเงิน: {item.payer}")
        for p in item.participants:
            if p not in self.people:
                raise ValueError(f"ไม่พบผู้ร่วมกิน: {p}")
        if item.price <= 0:
            raise ValueError("ราคา item ต้องมากกว่า 0")
        if item.weights:
            w = {k: float(v) for k, v in item.weights.items() if k in item.participants}
            if not w:
                raise ValueError("weights ว่าง หรือไม่ตรงกับผู้ร่วมกิน")
            if any(v <= 0 for v in w.values()):
                raise ValueError("ทุก weight ต้อง > 0")
            item.weights = w
        self.items.append(item)

    def remove_item_at(self, idx: int):
        if 0 <= idx < len(self.items):
            self.items.pop(idx)

    def summary_costs(self) -> Dict[str, float]:
        if not self.items:
            return {name: 0.0 for name in self.people}
        subtotal = sum(i.price for i in self.items)
        service_fee = subtotal * (self.service_pct / 100.0)
        vat_base = subtotal + service_fee
        vat_fee = vat_base * (self.vat_pct / 100.0)
        total = subtotal + service_fee + vat_fee + self.tip
        if subtotal == 0:
            return {name: 0.0 for name in self.people}
        cost_share_raw = defaultdict(float)
        for it in self.items:
            if it.weights:
                total_w = sum(it.weights[p] for p in it.participants)
                for p in it.participants:
                    cost_share_raw[p] += it.price * (it.weights[p] / total_w)
            else:
                each = it.price / len(it.participants)
                for p in it.participants:
                    cost_share_raw[p] += each
        scale = total / subtotal
        return {p: cost_share_raw.get(p, 0.0) * scale for p in self.people}

    def paid_map(self) -> Dict[str, float]:
        paid = defaultdict(float)
        for it in self.items:
            paid[it.payer] += it.price
        subtotal = sum(i.price for i in self.items)
        if subtotal > 0:
            service_fee = subtotal * (self.service_pct / 100.0)
            vat_base = subtotal + service_fee
            vat_fee = vat_base * (self.vat_pct / 100.0)
            extra = service_fee + vat_fee + self.tip
            for name in paid:
                paid[name] += extra * (paid[name] / subtotal)
        for name in self.people:
            paid[name] = paid.get(name, 0.0)
        return dict(paid)

    def net_balance(self) -> Dict[str, float]:
        should_pay = self.summary_costs()
        already_paid = self.paid_map()
        net = {name: round(already_paid.get(name, 0.0) - should_pay.get(name, 0.0), 2)
               for name in self.people}
        drift = round(sum(net.values()), 2)
        if drift != 0 and net:
            first = next(iter(net))
            net[first] = round(net[first] - drift, 2)
        return net

    def settle_transactions(self) -> List[Dict[str, float]]:
        net = self.net_balance()
        creditors = [[name, amt] for name, amt in net.items() if amt > 0]
        debtors = [[name, -amt] for name, amt in net.items() if amt < 0]
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)
        i = j = 0
        txs = []
        while i < len(debtors) and j < len(creditors):
            dname, damt = debtors[i]
            cname, camt = creditors[j]
            pay = round(min(damt, camt), 2)
            if pay > 0:
                txs.append({"from": dname, "to": cname, "amount": pay})
                damt = round(damt - pay, 2)
                camt = round(camt - pay, 2)
            debtors[i][1] = damt
            creditors[j][1] = camt
            if damt == 0:
                i += 1
            if camt == 0:
                j += 1
        return txs

# =====================
# Tkinter UI
# =====================
class BillSplitApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("หารค่าอาหารกับเพื่อน • Tkinter")
        self.master.geometry("1050x620")
        self.pack(fill=tk.BOTH, expand=True)

        self.bill = Bill()

        self._build_layout()

    # ---------- UI Layout ----------
    def _build_layout(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Left sidebar (People + Config + Item form)
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)

        # Right main (Items table + Output)
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # --- People Section ---
        ppl_lab = ttk.Label(left, text="รายชื่อเพื่อน", font=("Segoe UI", 11, "bold"))
        ppl_lab.grid(row=0, column=0, columnspan=3, sticky="w")

        self.person_entry = ttk.Entry(left, width=20)
        self.person_entry.grid(row=1, column=0, sticky="w")
        ttk.Button(left, text="เพิ่ม", command=self.add_person).grid(row=1, column=1, padx=5)
        ttk.Button(left, text="ลบที่เลือก", command=self.remove_person).grid(row=1, column=2)

        self.people_list = tk.Listbox(left, height=8, exportselection=False)
        self.people_list.grid(row=2, column=0, columnspan=3, sticky="we", pady=5)

        # --- Config Section ---
        cfg_lab = ttk.Label(left, text="ตั้งค่า Service/VAT/Tip", font=("Segoe UI", 11, "bold"))
        cfg_lab.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        frm_cfg = ttk.Frame(left)
        frm_cfg.grid(row=4, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_cfg, text="Service %").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_cfg, text="VAT %").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_cfg, text="Tip (บาท)").grid(row=2, column=0, sticky="w")

        self.service_var = tk.StringVar(value="0")
        self.vat_var = tk.StringVar(value="0")
        self.tip_var = tk.StringVar(value="0")

        ttk.Entry(frm_cfg, textvariable=self.service_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.vat_var, width=10).grid(row=1, column=1, padx=5)
        ttk.Entry(frm_cfg, textvariable=self.tip_var, width=10).grid(row=2, column=1, padx=5)

        ttk.Button(left, text="อัปเดตค่า Config", command=self.update_config).grid(row=5, column=0, columnspan=3, sticky="we", pady=5)

        # --- Item Form ---
        item_lab = ttk.Label(left, text="เพิ่มรายการอาหาร", font=("Segoe UI", 11, "bold"))
        item_lab.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))

        frm_item = ttk.Frame(left)
        frm_item.grid(row=7, column=0, columnspan=3, sticky="we")
        ttk.Label(frm_item, text="ชื่อเมนู").grid(row=0, column=0, sticky="w")
        ttk.Label(frm_item, text="ราคา (บาท)").grid(row=1, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้จ่ายก่อน").grid(row=2, column=0, sticky="w")
        ttk.Label(frm_item, text="ผู้ร่วมกิน").grid(row=3, column=0, sticky="nw")

        self.item_name = ttk.Entry(frm_item, width=22)
        self.item_price = ttk.Entry(frm_item, width=22)
        self.payer_combo = ttk.Combobox(frm_item, values=[], state="readonly", width=20)
        self.participants_list = tk.Listbox(frm_item, selectmode=tk.MULTIPLE, height=6, exportselection=False)
        self.all_var = tk.BooleanVar(value=False)
        self.all_chk = ttk.Checkbutton(frm_item, text="ทุกคน", variable=self.all_var, command=self.toggle_all_participants)

        self.item_name.grid(row=0, column=1, sticky="we", pady=1)
        self.item_price.grid(row=1, column=1, sticky="we", pady=1)
        self.payer_combo.grid(row=2, column=1, sticky="we", pady=1)
        self.participants_list.grid(row=3, column=1, sticky="we", pady=1)
        self.all_chk.grid(row=4, column=1, sticky="w")

        self.use_weights = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_item, text="หารไม่เท่ากัน (weights)", variable=self.use_weights).grid(row=5, column=1, sticky="w", pady=(4,0))

        btns = ttk.Frame(left)
        btns.grid(row=8, column=0, columnspan=3, sticky="we", pady=5)
        ttk.Button(btns, text="เพิ่มรายการ", command=self.add_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btns, text="ลบรายการที่เลือก", command=self.remove_selected_item).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # --- Items Table ---
        tbl_lab = ttk.Label(right, text="รายการทั้งหมด", font=("Segoe UI", 11, "bold"))
        tbl_lab.grid(row=0, column=0, sticky="w")

        self.table = ttk.Treeview(right, columns=("price", "payer", "participants", "weights"), show="headings", height=10)
        self.table.heading("price", text="ราคา")
        self.table.heading("payer", text="ผู้จ่าย")
        self.table.heading("participants", text="ผู้ร่วมกิน")
        self.table.heading("weights", text="weights?")
        self.table.column("price", width=80, anchor="e")
        self.table.column("payer", width=100)
        self.table.column("participants", width=300)
        self.table.column("weights", width=100, anchor="center")
        self.table.grid(row=1, column=0, sticky="nsew")

        scr = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scr.set)
        scr.grid(row=1, column=1, sticky="ns")

        # --- Summary ---
        sum_lab = ttk.Label(right, text="สรุปผล", font=("Segoe UI", 11, "bold"))
        sum_lab.grid(row=2, column=0, sticky="w", pady=(10,0))

        self.output = tk.Text(right, height=12)
        self.output.grid(row=3, column=0, sticky="nsew")

        btn_bottom = ttk.Frame(right)
        btn_bottom.grid(row=4, column=0, sticky="we", pady=6)
        ttk.Button(btn_bottom, text="คำนวณ/อัปเดตสรุป", command=self.refresh_summary).pack(side=tk.LEFT)
        ttk.Button(btn_bottom, text="ล้างทั้งหมด", command=self.reset_all).pack(side=tk.LEFT, padx=6)

    # ---------- Helper Methods ----------
    def _refresh_people_widgets(self):
        names = list(self.bill.people.keys())
        self.payer_combo["values"] = names
        self.participants_list.delete(0, tk.END)
        for n in names:
            self.participants_list.insert(tk.END, n)

    def toggle_all_participants(self):
        if self.all_var.get():
            self.participants_list.select_set(0, tk.END)
        else:
            self.participants_list.select_clear(0, tk.END)

    def add_person(self):
        name = self.person_entry.get().strip()
        if not name:
            messagebox.showwarning("เตือน", "กรุณากรอกชื่อเพื่อน")
            return
        try:
            self.bill.add_person(name)
            self.person_entry.delete(0, tk.END)
            self.people_list.insert(tk.END, name)
            self._refresh_people_widgets()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_person(self):
        sel = self.people_list.curselection()
        if not sel:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกชื่อเพื่อนที่จะลบ")
            return
        name = self.people_list.get(sel[0])
        try:
            self.bill.remove_person(name)
            self.people_list.delete(sel[0])
            self._refresh_people_widgets()
        except Exception as e:
            messagebox.showerror("ลบไม่ได้", str(e))

    def update_config(self):
        def _to_float(s):
            s = (s or "0").strip()
            return float(s) if s else 0.0
        try:
            self.bill.service_pct = _to_float(self.service_var.get())
            self.bill.vat_pct = _to_float(self.vat_var.get())
            self.bill.tip = _to_float(self.tip_var.get())
            messagebox.showinfo("สำเร็จ", "อัปเดตค่าบริการ/VAT/Tip แล้ว")
            self.refresh_summary()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def _get_selected_participants(self) -> List[str]:
        if self.all_var.get():
            return list(self.bill.people.keys())
        sel = self.participants_list.curselection()
        return [self.participants_list.get(i) for i in sel]

    def add_item(self):
        name = self.item_name.get().strip()
        price_raw = self.item_price.get().strip()
        payer = self.payer_combo.get().strip()
        parts = self._get_selected_participants()

        if not name:
            messagebox.showwarning("เตือน", "กรุณากรอกชื่อเมนู")
            return
        if not price_raw:
            messagebox.showwarning("เตือน", "กรุณากรอกราคา")
            return
        if not payer:
            messagebox.showwarning("เตือน", "กรุณาเลือกผู้จ่ายก่อน")
            return
        if not parts:
            messagebox.showwarning("เตือน", "กรุณาเลือกผู้ร่วมกิน")
            return
        try:
            price = float(price_raw)
        except:
            messagebox.showerror("ผิดพลาด", "กรอกจำนวนเงินให้ถูกต้อง")
            return

        weights = None
        if self.use_weights.get():
            weights = {}
            for p in parts:
                while True:
                    w = simpledialog.askstring("น้ำหนักส่วนแบ่ง", f"weight ของ {p} (ตัวเลข > 0):", parent=self)
                    if w is None:
                        # กดยกเลิก -> ยกเลิกการเพิ่มรายการ
                        return
                    try:
                        fv = float(w)
                        if fv <= 0:
                            raise ValueError
                        weights[p] = fv
                        break
                    except:
                        messagebox.showwarning("เตือน", "ใส่ตัวเลข > 0 นะ")

        try:
            self.bill.add_item(Item(name=name, price=price, payer=payer, participants=parts, weights=weights))
            # insert to table
            weights_flag = "Yes" if weights else "No"
            self.table.insert("", tk.END, values=(f"{price:,.2f}", payer, ", ".join(parts), weights_flag))
            # clear item form
            self.item_name.delete(0, tk.END)
            self.item_price.delete(0, tk.END)
            self.use_weights.set(False)
            self.refresh_summary()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))

    def remove_selected_item(self):
        sel = self.table.selection()
        if not sel:
            messagebox.showinfo("แจ้ง", "กรุณาเลือกรายการที่จะลบ")
            return
        idx = self.table.index(sel[0])
        self.bill.remove_item_at(idx)
        self.table.delete(sel[0])
        self.refresh_summary()

    def reset_all(self):
        if messagebox.askyesno("ยืนยัน", "ล้างข้อมูลทั้งหมด?"):
            self.bill = Bill()
            self.people_list.delete(0, tk.END)
            self.table.delete(*self.table.get_children())
            self.output.delete(1.0, tk.END)
            self._refresh_people_widgets()
            self.service_var.set("0")
            self.vat_var.set("0")
            self.tip_var.set("0")
            self.item_name.delete(0, tk.END)
            self.item_price.delete(0, tk.END)
            self.payer_combo.set("")
            self.participants_list.selection_clear(0, tk.END)
            self.all_var.set(False)
            self.use_weights.set(False)

    def refresh_summary(self):
        try:
            should = self.bill.summary_costs()
            paid = self.bill.paid_map()
            net = self.bill.net_balance()
            txs = self.bill.settle_transactions()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e))
            return

        def money(x):
            return f"{x:,.2f} บาท"

        self.output.delete(1.0, tk.END)
        names = list(self.bill.people.keys())
        subtotal = sum(i.price for i in self.bill.items)
        svc = subtotal * (self.bill.service_pct/100.0)
        vat = (subtotal + svc) * (self.bill.vat_pct/100.0)
        total = subtotal + svc + vat + self.bill.tip

        self.output.insert(tk.END, "สรุปร้าน/บิล\n")
        self.output.insert(tk.END, f"  Subtotal: {money(subtotal)}\n")
        self.output.insert(tk.END, f"  Service {self.bill.service_pct:.2f}%: {money(svc)}\n")
        self.output.insert(tk.END, f"  VAT {self.bill.vat_pct:.2f}%: {money(vat)}\n")
        self.output.insert(tk.END, f"  Tip: {money(self.bill.tip)}\n")
        self.output.insert(tk.END, f"  Total: {money(total)}\n\n")

        self.output.insert(tk.END, "ควรจ่าย (รวม service/VAT/ทิป ตามสัดส่วนการกิน)\n")
        for n in names:
            self.output.insert(tk.END, f"  - {n}: {money(should.get(n, 0.0))}\n")
        self.output.insert(tk.END, "\nจ่ายไปแล้ว\n")
        for n in names:
            self.output.insert(tk.END, f"  - {n}: {money(paid.get(n, 0.0))}\n")
        self.output.insert(tk.END, "\nดุลสุทธิ (บวก=ควรได้รับ, ลบ=ควรจ่าย)\n")
        for n in names:
            self.output.insert(tk.END, f"  - {n}: {money(net.get(n, 0.0))}\n")

        self.output.insert(tk.END, "\nรายการชำระกัน (ลดจำนวนธุรกรรมแบบ greedy)\n")
        if not txs:
            self.output.insert(tk.END, "  เคลียร์แล้ว ไม่ต้องโอนกัน 🎉\n")
        else:
            for t in txs:
                self.output.insert(tk.END, f"  - {t['from']} → {t['to']}: {money(t['amount'])}\n")


def main():
    root = tk.Tk()
    # เล็กน้อยให้ ttk ดูสบายตา
    try:
        root.call("source", "azure.tcl")  # ถ้ามีธีม azure
        ttk.Style().theme_use("azure")
    except Exception:
        pass
    app = BillSplitApp(root)
    app.mainloop()


if __name__ == "__main__":
    main()
