# main.py
# ไฟล์สำหรับเริ่มต้นการทำงานของโปรแกรม
# วิธีรัน: python main.py

import tkinter as tk
from tkinter import ttk

from app_ui import LoginFrame, BillSplitApp
from firebase_client import FirebaseRTClient

# =====================
#  Firebase Config
# =====================
FIREBASE_API_KEY = "AIzaSyAL3zittLydgTBzslUwFY_gtxpBv_lSIuA"
FIREBAS_RTDB_URL = "https://software-project01-default-rtdb.firebaseio.com/"


def main():
    """ฟังก์ชันหลักในการสร้างและรันโปรแกรม"""
    root = tk.Tk()
    root.FIREBASE_API_KEY = FIREBASE_API_KEY
    root.FIREBASE_RTDB_URL = FIREBAS_RTDB_URL

    try:
        style = ttk.Style(root)
        if "azure" in style.theme_names():
            style.theme_use("azure")
            style.configure("TNotebook.Tab", padding=[10, 5], font=("Segoe UI", 10))
            style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    def open_app(fb_client: FirebaseRTClient):
        """เปลี่ยนจากหน้า Login ไปยังหน้าแอปหลัก"""
        for widget in root.winfo_children():
            widget.destroy()
        BillSplitApp(root, fb_client)

    LoginFrame(root, on_success=open_app)
    root.mainloop()

if __name__ == "__main__":
    main()

