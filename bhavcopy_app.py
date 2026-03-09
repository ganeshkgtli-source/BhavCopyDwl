import requests
import zipfile
import io
import os
import datetime
import time
import tkinter as tk
from tkinter import messagebox
from tkcalendar import DateEntry

BASE_FOLDER = "bhavcopy"


 # Utility Functions
 
def is_weekend(date_obj):
    return date_obj.weekday() >= 5


def build_bse_url(date_obj):
    """
    Before 2024  -> EQDDMMYY_CSV.ZIP
    2024+        -> EQ_ISINCODE_DDMMYY_T0.CSV
    """
    date_str = date_obj.strftime("%d%m%y")

    if date_obj.year >= 2024:
        return f"https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{date_str}_T0.CSV"

    return f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{date_str}_CSV.ZIP"


def download_bhavcopy(date_obj):
    if is_weekend(date_obj):
        print(f"Skipping weekend: {date_obj}")
        return

    # Prevent future date download
    if date_obj >= datetime.date.today():
        print("Bhavcopy for today is not available yet.")
        return

    year = date_obj.strftime("%Y")
    year_folder = os.path.join(BASE_FOLDER, year)
    os.makedirs(year_folder, exist_ok=True)

    url = build_bse_url(date_obj)

    try:
        print(f"Downloading: {url}")

        with requests.Session() as session:
            session.headers.update({
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.bseindia.com/"
            })

            # Visit homepage first (important)
            session.get("https://www.bseindia.com/")

            response = session.get(url, timeout=20)

                                                                                                                                                                                                        

        if response.status_code != 200:
            print("File not available")
            return

        # Check ZIP signature
        if not response.content.startswith(b'PK'):
            print("Invalid file received (probably blocked)")
            return

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            for file in z.namelist():
                file_path = os.path.join(year_folder, file)

                if os.path.exists(file_path):
                    print(f"Already exists: {file}")
                    continue

                z.extract(file, year_folder)
                print(f"Extracted: {file}")

        time.sleep(1)  # Prevent rate limiting

    except Exception as e:
        print("Error:", e)


 # Button Actions
# ----------------------------- 

def download_selected_date():
    selected_date = cal.get_date()

    if is_weekend(selected_date):
        messagebox.showwarning("Weekend", "Selected date is a weekend!")
        return

    download_bhavcopy(selected_date)
    messagebox.showinfo("Done", "Download completed!")


def download_all_data():
    start_date = datetime.date(2015, 1, 1)
    today = datetime.date.today()

    current_date = start_date

    while current_date < today:
        if not is_weekend(current_date):
            download_bhavcopy(current_date)

        current_date += datetime.timedelta(days=1)

    messagebox.showinfo("Completed", "All available data downloaded!")


 # GUI Setup
 
root = tk.Tk()
root.title("BSE Bhavcopy Downloader")
root.geometry("400x250")

label = tk.Label(root, text="Select Date", font=("Arial", 12))
label.pack(pady=10)

cal = DateEntry(
    root,
    width=15,
    background="darkblue",
    foreground="white",
    borderwidth=2,
    date_pattern="dd-mm-yyyy"
)
cal.pack(pady=5)

btn_download = tk.Button(
    root,
    text="Download Selected Date",
    command=download_selected_date,
    width=25
)
btn_download.pack(pady=10)

btn_download_all = tk.Button(
    root,
    text="Download All Data Till Now",
    command=download_all_data,
    width=25
)
btn_download_all.pack(pady=10)

root.mainloop()