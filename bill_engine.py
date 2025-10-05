# bill_engine.py
# จัดการข้อมูลและกฎเกณฑ์ต่างๆ ของการหารบิล

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict
import time

@dataclass
class Person:
    """เก็บข้อมูลของคน (ใช้ UID)"""
    name: str

@dataclass
class Item:
    """เก็บข้อมูลของรายการอาหาร"""
    name: str
    price: float
    payer: str
    participants: List[str]
    weights: Optional[Dict[str, float]] = None

@dataclass
class Bill:
    """จัดการข้อมูลทั้งหมดของบิลและคำนวณผลลัพธ์"""
    people: Dict[str, Person] = field(default_factory=dict)
    items: List[Item] = field(default_factory=list)
    transfers: List[Dict] = field(default_factory=list)
    service_pct: float = 0.0
    vat_pct: float = 0.0
    tip: float = 0.0

    def add_person(self, uid: str):
        """เพิ่มคนเข้าบิล"""
        uid = uid.strip()
        if not uid: raise ValueError("UID ว่างไม่ได้")
        if uid in self.people: return
        self.people[uid] = Person(name=uid)

    def remove_person(self, uid: str):
        """
        ลบคนออกจากรายชื่อ "ที่ใช้งานอยู่" ได้ก็ต่อเมื่อเคลียร์ยอดเงินทั้งหมดแล้ว (ดุลสุทธิเป็น 0)
        การลบจะทำให้ไม่สามารถเลือกคนนี้ในรายการอาหารหรือรายการโอนเงินใหม่ๆ ได้อีก
        แต่ประวัติเดิมของคนนี้จะยังคงอยู่ในการคำนวณ
        """
        if uid in self.people:
            balance = self.net_balance().get(uid, 0.0)
            # ใช้ค่าเผื่อเล็กน้อย (0.01) สำหรับความคลาดเคลื่อนของ floating point
            if abs(balance) > 0.01:
                raise ValueError(f"ลบไม่ได้: ยังมียอดค้างชำระ/ต้องได้รับเงินคืนอยู่ {balance:,.2f} บาท\nกรุณาเพิ่มรายการโอนเงินเพื่อเคลียร์ยอดให้เป็นศูนย์ก่อน")
            
            # ถ้าเคลียร์แล้ว ก็ลบออกจากรายชื่อที่ active อยู่
            del self.people[uid]

    def add_item(self, item: Item):
        """เพิ่มรายการอาหาร"""
        if item.payer not in self.people: raise ValueError(f"ไม่พบผู้จ่าย (UID): {item.payer}")
        for p in item.participants:
            if p not in self.people: raise ValueError(f"ไม่พบผู้ร่วมกิน (UID): {p}")
        if item.price <= 0: raise ValueError("ราคา item ต้อง > 0")
        if item.weights:
            w = {k: float(v) for k, v in item.weights.items() if k in item.participants}
            if not w: raise ValueError("weights ว่าง/ไม่ตรงกับผู้ร่วมกิน")
            if any(v <= 0 for v in w.values()): raise ValueError("ทุก weight ต้อง > 0")
            item.weights = w
        self.items.append(item)

    def remove_item_at(self, idx: int):
        """ลบรายการอาหารตามลำดับ"""
        if 0 <= idx < len(self.items): self.items.pop(idx)

    def add_transfer(self, from_uid: str, to_uid: str, amount: float):
        """เพิ่มรายการโอนเงินระหว่างบุคคล"""
        if from_uid not in self.people: raise ValueError(f"ไม่พบผู้โอน (UID): {from_uid}")
        if to_uid not in self.people: raise ValueError(f"ไม่พบผู้รับ (UID): {to_uid}")
        if amount <= 0: raise ValueError("จำนวนเงินต้อง > 0")
        if from_uid == to_uid: raise ValueError("ผู้โอนและผู้รับต้องเป็นคนละคน")
        self.transfers.append({"from": from_uid, "to": to_uid, "amount": amount})

    def remove_transfer_at(self, idx: int):
        """ลบรายการโอนเงินตามลำดับ"""
        if 0 <= idx < len(self.transfers): self.transfers.pop(idx)

    def _totals(self):
        """คำนวณยอดรวมต่างๆ"""
        subtotal = sum(i.price for i in self.items)
        svc = subtotal * (self.service_pct / 100.0)
        vat = (subtotal + svc) * (self.vat_pct / 100.0)
        total = subtotal + svc + vat + self.tip
        return subtotal, svc, vat, total

    def _get_total_scale_factor(self) -> float:
        """คำนวณสัดส่วนค่าใช้จ่ายทั้งหมดเทียบกับยอดรวมค่าอาหาร"""
        subtotal = sum(i.price for i in self.items)
        if subtotal <= 0: return 1.0
        _, _, _, total = self._totals()
        return total / subtotal

    def summary_costs(self) -> Dict[str, float]:
        """สรุปว่าแต่ละคน 'ควรจะ' จ่ายเงินเท่าไหร่"""
        all_uids = set(self.people.keys())
        for item in self.items: all_uids.add(item.payer); all_uids.update(item.participants)
        for t in self.transfers: all_uids.add(t['from']); all_uids.add(t['to'])

        if not self.items: return {uid: 0.0 for uid in all_uids}
        subtotal = sum(i.price for i in self.items)
        if subtotal == 0: return {uid: 0.0 for uid in all_uids}
        
        raw = defaultdict(float)
        for it in self.items:
            if it.weights:
                totw = sum(it.weights.get(p, 0) for p in it.participants)
                if totw == 0: continue
                for p in it.participants:
                    if p in it.weights: raw[p] += it.price * (it.weights[p] / totw)
            else:
                if not it.participants: continue
                each = it.price / len(it.participants)
                for p in it.participants: raw[p] += each
        
        scale = self._get_total_scale_factor()
        return {p: raw.get(p, 0.0) * scale for p in all_uids}

    def paid_map(self) -> Dict[str, float]:
        """สรุปว่าแต่ละคน 'จ่ายไปแล้ว' เท่าไหร่"""
        all_uids = set(self.people.keys())
        for item in self.items: all_uids.add(item.payer); all_uids.update(item.participants)
        for t in self.transfers: all_uids.add(t['from']); all_uids.add(t['to'])
        
        paid = defaultdict(float)
        for it in self.items: paid[it.payer] += it.price
        
        subtotal, svc, vat, _ = self._totals()
        extra = svc + vat + self.tip
        if subtotal > 0 and extra > 0:
            for uid in paid: paid[uid] += extra * (paid[uid] / subtotal)
        
        return {uid: paid.get(uid, 0.0) for uid in all_uids}

    def net_balance(self) -> Dict[str, float]:
        """คำนวณดุลสุทธิ (ใครต้องจ่ายเพิ่ม, ใครต้องได้เงินคืน)"""
        should = self.summary_costs()
        paid = self.paid_map()
        
        all_uids = set(should.keys()) | set(paid.keys())
        net = {uid: paid.get(uid, 0.0) - should.get(uid, 0.0) for uid in all_uids}
        
        for t in self.transfers:
            net[t['from']] -= t['amount']
            net[t['to']] += t['amount']
        
        net_rounded = {uid: round(val, 2) for uid, val in net.items()}
        drift = round(sum(net_rounded.values()), 2)
        if drift != 0 and net_rounded:
            # หา key แรกที่ไม่ใช่ 0 เพื่อปรับแก้ค่า drift
            key_to_adjust = next((uid for uid, val in net_rounded.items() if val != 0), None)
            if key_to_adjust:
                net_rounded[key_to_adjust] = round(net_rounded[key_to_adjust] - drift, 2)
        return net_rounded

    def settle_transactions(self) -> List[Dict[str, float]]:
        """คำนวณรายการโอนเงินเพื่อเคลียร์บิล (แบบสรุป)"""
        net = self.net_balance()
        creditors = [[uid, amount] for uid, amount in net.items() if amount > 0.01]
        debtors = [[uid, -amount] for uid, amount in net.items() if amount < -0.01]
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)
        i = j = 0; transactions = []
        while i < len(debtors) and j < len(creditors):
            d_name, d_amount = debtors[i]; c_name, c_amount = creditors[j]
            pay_amount = round(min(d_amount, c_amount), 2)
            if pay_amount > 0:
                transactions.append({"from": d_name, "to": c_name, "amount": pay_amount})
                d_amount = round(d_amount - pay_amount, 2); c_amount = round(c_amount - pay_amount, 2)
            debtors[i][1] = d_amount; creditors[j][1] = c_amount
            if d_amount < 0.01: i += 1
            if c_amount < 0.01: j += 1
        return transactions
    
    def calculate_raw_debts(self) -> Dict[str, Dict[str, Dict]]:
        """คำนวณหนี้สินอย่างละเอียดว่าใครค้างใครจากรายการไหนบ้าง"""
        scale = self._get_total_scale_factor()
        debts = defaultdict(lambda: defaultdict(lambda: {'total': 0.0, 'items': []}))
        for item in self.items:
            item_cost_scaled = item.price * scale; payer = item.payer; shares = {}
            if item.weights:
                total_weight = sum(item.weights.get(p, 0) for p in item.participants)
                if total_weight > 0:
                    for p in item.participants: shares[p] = item_cost_scaled * (item.weights.get(p, 0) / total_weight)
            else:
                if item.participants:
                    each_share = item_cost_scaled / len(item.participants)
                    for p in item.participants: shares[p] = each_share
            for participant, amount in shares.items():
                if participant != payer:
                    debts[payer][participant]['total'] += amount
                    debts[payer][participant]['items'].append(item.name)
        return debts

    def to_dict(self):
        """แปลงข้อมูล Bill เป็น Dictionary เพื่อส่งไป Firebase"""
        return {
            "people": list(self.people.keys()),
            "items": [{"name":it.name, "price":it.price, "payer":it.payer,
                       "participants":it.participants, "weights":it.weights} for it in self.items],
            "transfers": self.transfers,
            "service_pct": self.service_pct, "vat_pct": self.vat_pct, "tip": self.tip,
            "updatedAt": time.time(),
        }

    @classmethod
    def from_dict(cls, data: dict):
        """สร้าง Object Bill จาก Dictionary ของ Firebase"""
        b = cls()
        for uid in data.get("people", []): b.add_person(uid)
        b.service_pct = float(data.get("service_pct", 0))
        b.vat_pct     = float(data.get("vat_pct", 0))
        b.tip         = float(data.get("tip", 0))
        b.transfers   = data.get("transfers", [])
        for it in data.get("items", []):
            try:
                b.add_item(Item(name=it["name"], price=float(it["price"]),
                                payer=it["payer"], participants=list(it["participants"]),
                                weights=it.get("weights")))
            except (ValueError, KeyError): continue
        return b

