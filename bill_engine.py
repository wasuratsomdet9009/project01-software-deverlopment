# bill_engine.py
# ไฟล์นี้เปรียบเสมือน "สมอง" ของโปรแกรม
# ทำหน้าที่จัดการข้อมูลและกฎเกณฑ์ต่างๆ ของการหารบิลโดยเฉพาะ
# ไม่มียุ่งเกี่ยวกับหน้าตาโปรแกรม (UI) เลย ทำให้สามารถนำไปใช้กับโปรแกรมแบบอื่นๆ ได้
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict
import time

# --- Data Classes: โครงสร้างข้อมูลหลัก ---

@dataclass
class Person:
    """
    เก็บข้อมูลของคนคนหนึ่ง (ใช้ UID เป็นตัวระบุ)
    """
    name: str  # UID

@dataclass
class Item:
    """
    เก็บข้อมูลของรายการอาหารแต่ละอย่าง
    """
    name: str
    price: float
    payer: str              # UID ของคนจ่าย
    participants: List[str] # รายชื่อ UID ของคนร่วมกิน
    weights: Optional[Dict[str, float]] = None  # ถ้าหารไม่เท่ากัน จะเก็บน้ำหนักของแต่ละคน {UID: weight}

@dataclass
class Bill:
    """
    คลาสหลักที่รวบรวมข้อมูลทั้งหมดของบิล
    ทั้งรายชื่อคน, รายการอาหาร, และค่าใช้จ่ายอื่นๆ
    พร้อมฟังก์ชันสำหรับคำนวณผลลัพธ์
    """
    people: Dict[str, Person] = field(default_factory=dict)
    items: List[Item] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    def add_person(self, uid: str):
        """เพิ่มคนเข้าบิลด้วย UID"""
        uid = uid.strip()
        if not uid: raise ValueError("UID ว่างไม่ได้")
        if uid in self.people: return # ถ้ามีอยู่แล้วก็ไม่ต้องทำอะไร
        self.people[uid] = Person(name=uid)

    def remove_person(self, uid: str):
        """ลบคนออกจากบิล"""
        if uid in self.people:
            # เช็คก่อนว่าคนนี้ยังติดรายการอาหารอยู่ไหม
            for it in self.items:
                if it.payer == uid or uid in it.participants:
                    raise ValueError("ลบไม่ได้: มีรายการที่เกี่ยวข้องกับคนนี้")
            del self.people[uid]

    def add_item(self, item: Item):
        """เพิ่มรายการอาหาร"""
        # ตรวจสอบข้อมูลพื้นฐาน
        if item.payer not in self.people: raise ValueError(f"ไม่พบผู้จ่าย (UID): {item.payer}")
        for p in item.participants:
            if p not in self.people: raise ValueError(f"ไม่พบผู้ร่วมกิน (UID): {p}")
        if item.price <= 0: raise ValueError("ราคา item ต้อง > 0")
        
        # ตรวจสอบเรื่อง weights (ถ้ามี)
        if item.weights:
            w = {k: float(v) for k, v in item.weights.items() if k in item.participants}
            if not w: raise ValueError("weights ว่าง/ไม่ตรงกับผู้ร่วมกิน")
            if any(v <= 0 for v in w.values()): raise ValueError("ทุก weight ต้อง > 0")
            item.weights = w
        self.items.append(item)

    def remove_item_at(self, idx: int):
        """ลบรายการอาหารตามลำดับที่"""
        if 0 <= idx < len(self.items): self.items.pop(idx)

    def _totals(self):
        """คำนวณยอดรวมต่างๆ (เป็นฟังก์ชันภายใน)"""
        subtotal = sum(i.price for i in self.items)
        svc = subtotal * (self.service_pct / 100.0)
        vat = (subtotal + svc) * (self.vat_pct / 100.0)
        total = subtotal + svc + vat + self.tip
        return subtotal, svc, vat, total

    def summary_costs(self) -> Dict[str, float]:
        """สรุปว่าแต่ละคน 'ควรจะ' จ่ายเงินเท่าไหร่"""
        if not self.items: return {uid: 0.0 for uid in self.people}
        subtotal, svc, vat, total = self._totals()
        if subtotal == 0: return {uid: 0.0 for uid in self.people}

        # คำนวณยอดดิบของแต่ละคนจากรายการอาหาร
        raw = defaultdict(float)
        for it in self.items:
            if it.weights: # กรณีหารไม่เท่ากัน
                totw = sum(it.weights[p] for p in it.participants if p in it.weights)
                if totw == 0: continue
                for p in it.participants:
                    if p in it.weights:
                        raw[p] += it.price * (it.weights[p] / totw)
            else: # กรณีหารเท่ากัน
                if not it.participants: continue
                each = it.price / len(it.participants)
                for p in it.participants: raw[p] += each
        
        # นำยอดดิบมาบวก Service, VAT, Tip ตามสัดส่วน
        scale = total / subtotal if subtotal > 0 else 1.0
        return {p: raw.get(p, 0.0) * scale for p in self.people}

    def paid_map(self) -> Dict[str, float]:
        """สรุปว่าแต่ละคน 'จ่ายไปแล้ว' เท่าไหร่"""
        paid = defaultdict(float)
        # 1. รวมยอดที่จ่ายค่าอาหารไปก่อน
        for it in self.items:
            paid[it.payer] += it.price
        
        # 2. คิด Service, VAT, Tip เพิ่มให้คนที่จ่ายไปก่อน ตามสัดส่วนที่จ่าย
        subtotal, svc, vat, total = self._totals()
        extra = svc + vat + self.tip
        if subtotal > 0 and extra > 0:
            for uid in paid:
                paid[uid] += extra * (paid[uid] / subtotal)
        
        # ทำให้แน่ใจว่าทุกคนมีข้อมูลใน map
        for uid in self.people:
            paid[uid] = paid.get(uid, 0.0)
        return dict(paid)

    def net_balance(self) -> Dict[str, float]:
        """คำนวณดุลสุทธิ (ใครต้องจ่ายเพิ่ม, ใครต้องได้เงินคืน)"""
        should = self.summary_costs()
        paid = self.paid_map()
        net = {uid: round(paid.get(uid,0.0)-should.get(uid,0.0), 2) for uid in self.people}
        
        # ปรับค่าทศนิยมเล็กน้อยเพื่อให้ยอดรวมเป็น 0 พอดี
        drift = round(sum(net.values()), 2)
        if drift != 0 and net:
            first = next(iter(net))
            net[first] = round(net[first] - drift, 2)
        return net

    def settle_transactions(self) -> List[Dict[str, float]]:
        """คำนวณรายการโอนเงินเพื่อเคลียร์บิล"""
        net = self.net_balance()
        creditors = [[uid, amount] for uid, amount in net.items() if amount > 0] # คนที่ต้องได้เงินคืน
        debtors = [[uid, -amount] for uid, amount in net.items() if amount < 0] # คนที่ต้องจ่าย
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)
        
        i = j = 0
        transactions = []
        while i < len(debtors) and j < len(creditors):
            d_name, d_amount = debtors[i]
            c_name, c_amount = creditors[j]
            
            pay_amount = round(min(d_amount, c_amount), 2)
            if pay_amount > 0:
                transactions.append({"from": d_name, "to": c_name, "amount": pay_amount})
                d_amount = round(d_amount - pay_amount, 2)
                c_amount = round(c_amount - pay_amount, 2)
            
            debtors[i][1] = d_amount
            creditors[j][1] = c_amount
            
            if d_amount == 0: i += 1
            if c_amount == 0: j += 1
            
        return transactions

    def to_dict(self):
        """แปลงข้อมูล Bill ทั้งหมดเป็น Dictionary เพื่อส่งไป Firebase"""
        return {
            "people": list(self.people.keys()),
            "items": [{"name":it.name, "price":it.price, "payer":it.payer,
                       "participants":it.participants, "weights":it.weights} for it in self.items],
            "service_pct": self.service_pct,
            "vat_pct": self.vat_pct,
            "tip": self.tip,
            "updatedAt": time.time(), # ใส่เวลาที่อัปเดตล่าสุด
        }

    @classmethod
    def from_dict(cls, data: dict):
        """สร้าง Object Bill จาก Dictionary ที่ได้จาก Firebase"""
        b = cls()
        for uid in data.get("people", []): b.add_person(uid)
        b.service_pct = float(data.get("service_pct", 0))
        b.vat_pct     = float(data.get("vat_pct", 0))
        b.tip         = float(data.get("tip", 0))
        for it in data.get("items", []):
            try:
                b.add_item(Item(name=it["name"], price=float(it["price"]),
                                payer=it["payer"], participants=list(it["participants"]),
                                weights=it.get("weights")))
            except (ValueError, KeyError):
                # ถ้าเจอข้อมูลรายการอาหารที่ไม่ถูกต้องใน DB ให้ข้ามไป
                continue
        return b
