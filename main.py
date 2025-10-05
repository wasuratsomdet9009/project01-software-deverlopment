# main.py
# ไฟล์สำหรับเริ่มต้นการทำงานของโปรแกรม
# ทำหน้าที่สร้างหน้าต่างหลัก และเลือกว่าจะแสดงหน้า Login หรือหน้าแอปพลิเคชัน
# วิธีรัน: python main.py

import tkinter as tk
from tkinter import ttk

# --- Import หน้าจอและ Client จากไฟล์ที่แยกไว้ ---
from app_ui import LoginFrame, BillSplitApp
from firebase_client import FirebaseRTClient

# =====================
#  Firebase Config
#  **สำคัญ!** กรุณากรอกข้อมูล Firebase ของคุณที่นี่
# =====================
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"  # <<-- ใส่ Web API Key ของคุณ
FIREBAS_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/" # <<-- ใส่ URL ของ Realtime Database ของคุณ


def main():
    """
    ฟังก์ชันหลักในการสร้างและรันโปรแกรม
    """
    root = tk.Tk()

    # --- ตั้งค่า Firebase Config ให้เข้าถึงได้จากทุกที่ในแอป ---
    root.FIREBASE_API_KEY = FIREBASE_API_KEY
    root.FIREBASE_RTDB_URL = FIREBAS_RTDB_URL

    # --- ตั้งค่า Theme ของโปรแกรมให้ดูทันสมัย (ถ้ามี) ---
    try:
        style = ttk.Style(root)
        # ลองใช้ theme 'azure' ถ้าติดตั้งไว้
        if "azure" in style.theme_names():
            style.theme_use("azure")
            style.configure("TNotebook.Tab", padding=[10, 5], font=("Segoe UI", 10))
            style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        # หรือใช้ 'clam' เป็นตัวเลือกสำรอง
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        # ถ้าไม่มี theme พิเศษ ก็ใช้ theme ปกติ
        pass

    def open_app(fb_client: FirebaseRTClient):
        """
        ฟังก์ชันสำหรับเปลี่ยนจากหน้า Login ไปยังหน้าแอปหลัก
        """
        # ล้าง widget ทั้งหมดในหน้าต่างหลัก (ลบหน้า Login ออก)
        for widget in root.winfo_children():
            widget.destroy()
        # สร้างและแสดงหน้าแอปหลัก
        BillSplitApp(root, fb_client)

    # เริ่มต้นโดยการแสดงหน้า Login
    # เมื่อ Login สำเร็จ LoginFrame จะเรียกฟังก์ชัน open_app
    LoginFrame(root, on_success=open_app)

    # เริ่มการทำงานของ Tkinter event loop
    root.mainloop()

# --- จุดเริ่มต้นของโปรแกรม ---
if __name__ == "__main__":
    main()
