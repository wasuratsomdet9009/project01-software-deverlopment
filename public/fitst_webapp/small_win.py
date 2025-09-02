import tkinter as tk
from tkinter import messagebox
import uuid

# ส่วนนี้เตรียมการสำหรับ Firebase ยังไม่เสร็จ

class SmallGoalApp:
    """
    คลาสหลักของโปรแกรม จัดการข้อมูลและตรรกะทั้งหมด
    """
    def __init__(self):
        self.goals = {}
        print("โปรแกรมตั้งเป้าหมาย")
        print("-" * 30)

    def create_gui(self, root):
        """
        ฟังก์ชันนี้ถูกเตรียมไว้เพื่อสร้างหน้าตาโปรแกรม (GUI) ด้วย Tkinter ในอนาคต
        """
        self.root = root
        self.root.title("Small Goal Setter")
        pass

    def add_goal(self, goal_name):
        """
        เพิ่มเป้าหมายใหม่เข้าไปในระบบ
        """
        if not goal_name or not goal_name.strip():
            print("ข้อผิดพลาด: ชื่อเป้าหมายไม่สามารถเว้นว่างได้")
            return

        goal_id = str(uuid.uuid4()) # สร้าง ID ที่ไม่ซ้ำกันสำหรับแต่ละเป้าหมาย
        new_goal = {
            'name': goal_name.strip(),
            'status': 'incomplete'
        }
        self.goals[goal_id] = new_goal
        print(f"เพิ่มเป้าหมายสำเร็จ: '{goal_name.strip()}'")

    def show_all_goals(self):
        """
        แสดงเป้าหมายทั้งหมดที่มีอยู่ในระบบ
        """
        print("\n--- เป้าหมายทั้งหมดของคุณ ---")
        if not self.goals:
            print("ยังไม่มีเป้าหมายใดๆ")
        else:
            for i, (goal_id, goal_data) in enumerate(self.goals.items(), 1):
                print(f"{i}. [{goal_data['status']}] {goal_data['name']}")
        print("--------------------------\n")

    def mark_goal_as_complete(self, goal_index):
        """
        เปลี่ยนสถานะเป้าหมายเป็น 'complete'
        """
        if goal_index < 1 or goal_index > len(self.goals):
            print("ข้อผิดพลาด: หมายเลขเป้าหมายไม่ถูกต้อง")
            return
        
        # แปลง index ให้เป็น key ของ dictionary
        target_id = list(self.goals.keys())[goal_index - 1]
        self.goals[target_id]['status'] = 'complete'
        print(f"เป้าหมาย '{self.goals[target_id]['name']}' สำเร็จแล้ว!")

    def save_data_to_firebase(self):
        """
        ฟังก์ชันจำลองการบันทึกข้อมูลไปยัง Firebase
        """
        print("\n[จำลองการทำงาน] กำลังบันทึกข้อมูลไปยัง Firebase...")
        if not self.goals:
            print("ไม่มีข้อมูลให้บันทึก")
            return
    
        print("ข้อมูลที่จะถูกส่ง:", self.goals)
        print("[จำลองการทำงาน] บันทึกสำเร็จ!")


def run_command_line_version():
    """
    ฟังก์ชันสำหรับทดสอบการทำงานของโปรแกรมผ่าน Command Line
    """
    app = SmallGoalApp()

    app.add_goal("  อ่านหนังสือ 1 บท  ")
    app.add_goal("เขียนโค้ด Python 30 นาที")
    app.add_goal("ออกกำลังกาย")
    
    app.show_all_goals()
    
    app.mark_goal_as_complete(2)
    
    app.show_all_goals()

    app.save_data_to_firebase()


if __name__ == "__main__":
    #เวอร์ชันนี้ รันได้แค่ Command Line
    run_command_line_version()
