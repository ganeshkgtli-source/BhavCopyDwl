import requests
import zipfile
import io
import datetime
import sqlite3
import os
import pandas as pd

from flask import Flask, render_template, request, jsonify, Response, redirect

app = Flask(__name__)

DOWNLOAD_BASE = "Downloaded"
DB_NAME = "bhavcopy_files.db"

DOWNLOAD_STATE = {}

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx",
})

session.get("https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx")


 
# URL BUILDER
 
def build_bse_url(date_obj):

    change_date = datetime.date(2024, 7, 8)

    if date_obj < change_date:

        date_str = date_obj.strftime("%d%m%y")

        return "ZIP", f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{date_str}_CSV.ZIP"

    else:

        date_str = date_obj.strftime("%Y%m%d")

        return "CSV", f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date_str}_F_0000.CSV"


 
# DATABASE
 
def init_db():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bhavcopy_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT UNIQUE,
            trade_date TEXT,
            year INTEGER,
            month TEXT,
            file_data BLOB,
            is_deleted INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS download_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT UNIQUE,
        trade_date TEXT,
        week_day TEXT,
        status TEXT,
        download_time TEXT
    )
    """)
    conn.commit()
    conn.close()


def save_file_to_db(file_name, file_bytes, date_obj):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO bhavcopy_files
            (file_name, trade_date, year, month, file_data)
            VALUES (?, ?, ?, ?, ?)
        """, (
            file_name,
            str(date_obj),
            date_obj.year,
            date_obj.strftime("%b").upper(),
            file_bytes
        ))

        conn.commit()

    except sqlite3.IntegrityError:
        pass

    conn.close()


def save_log(file_name, trade_date, week_day, status):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO download_logs
    (file_name, trade_date, week_day, status, download_time)
    VALUES (?,?,?,?,?)
    ON CONFLICT(file_name)
    DO UPDATE SET
        trade_date=excluded.trade_date,
        week_day=excluded.week_day,
        status=excluded.status,
        download_time=excluded.download_time
    """, (file_name, trade_date, week_day, status, now))

    conn.commit()
    conn.close()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO download_logs (file_name,status,download_time)
        VALUES (?,?,?)
        ON CONFLICT(file_name)
        DO UPDATE SET
            status=excluded.status,
            download_time=excluded.download_time
    """, (file_name, status, now))

    conn.commit()
    conn.close()
def delete_log(file_name):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM download_logs WHERE file_name=?",
        (file_name,)
    )

    conn.commit()
    conn.close()
# PROCESS OLD FORMAT
 
def process_csv_before_2024(file_bytes):

    df = pd.read_csv(io.BytesIO(file_bytes))

    df = df.rename(columns={
        "SC_CODE": "SECURITY_ID",
        "SC_NAME": "SYMBOL",
        "SC_GROUP": "SERIES",
        "SC_TYPE": "TYPE",
    })

    df = df[df["SERIES"].str.startswith(("A", "B"), na=False)]

    df["TYPE"] = df["TYPE"].apply(
        lambda x: "EQUITY" if str(x).upper() == "Q" else x
    )

    cols_to_remove = ["PREVCLOSE", "NET_TURNOV", "TDCLOINDI"]

    df = df.drop(columns=[c for c in cols_to_remove if c in df.columns])

    df = df[
        [
            "SECURITY_ID",
            "SYMBOL",
            "SERIES",
            "TYPE",
            "OPEN",
            "HIGH",
            "LOW",
            "CLOSE",
            "NO_TRADES",
            "NO_OF_SHRS"
        ]
    ]

    output = io.StringIO()
    df.to_csv(output, index=False)

    return output.getvalue().encode()


 
# PROCESS NEW FORMAT
 
def process_bhavcopy_after_2024(file_bytes):

    df = pd.read_csv(io.BytesIO(file_bytes))

    df = df.rename(columns={
        "TradDt": "DATE",
        "FinInstrmId": "SECURITY_ID",
        "TckrSymb": "SYMBOL",
        "SctySrs": "SERIES",
        "OpnPric": "OPEN",
        "HghPric": "HIGH",
        "LwPric": "LOW",
        "ClsPric": "CLOSE",
        "TtlNbOfTxsExctd": "NO_OF_TRADE",
        "TtlTradgVol": "NO_OF_SHRS"
    })

    df = df[df["SERIES"].str.startswith(("A", "B"), na=False)]

    df["TYPE"] = "EQUITY"

    cols_to_remove = [
        "BizDt","Sgmt","Src","FinInstrmTp","ISIN",
        "XpryDt","FininstrmActlXpryDt","FinInstrmNm",
        "LastPric","PrvsClsgPric","SttlmPric",
        "OpnIntrst","ChngInOpnIntrst",
        "TtlTrfVal","SsnId","NewBrdLotQty",
        "Rmks","Rsvd1","Rsvd2","Rsvd3","Rsvd4"
    ]

    df = df.drop(columns=[c for c in cols_to_remove if c in df.columns])

    df = df[
        [
            "DATE",
            "SECURITY_ID",
            "SYMBOL",
            "SERIES",
            "TYPE",
            "OPEN",
            "HIGH",
            "LOW",
            "CLOSE",
            "NO_OF_TRADE",
            "NO_OF_SHRS"
        ]
    ]

    output = io.StringIO()
    df.to_csv(output, index=False)

    return output.getvalue().encode()


 
# DOWNLOAD LOGIC
def download_bhavcopy(date_obj):

    day_name = date_obj.strftime("%A")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT 1 FROM bhavcopy_files WHERE trade_date = ?",
        (str(date_obj),)
    )

    if cursor.fetchone():
        conn.close()
        return f"Already exists in DB: {date_obj} ({day_name})"

    conn.close()

    file_type, url = build_bse_url(date_obj)

    try:

        print("Downloading:", url)

        response = session.get(url, timeout=(3,30))

        if response.status_code != 200:

            file_name = f"EQ{date_obj.strftime('%d%m%y')}.CSV"
            save_log(
    file_name,
    str(date_obj),
    day_name,
    "Not Available"
)

            return f"File not available: {date_obj} ({day_name})"


         
        # OLD ZIP FORMAT
         

        if file_type == "ZIP":

            with zipfile.ZipFile(io.BytesIO(response.content)) as z:

                for file in z.namelist():

                    raw_bytes = z.read(file)

                    processed = process_csv_before_2024(raw_bytes)

                    save_file_to_db(
                        file,
                        processed,
                        date_obj
                    )

                    save_log(
    file,
    str(date_obj),
    day_name,
    "Downloaded"
)

            return f"Downloaded (ZIP): {date_obj} ({day_name})"


         
        # NEW CSV FORMAT
         

        else:

            file_name = f"EQ{date_obj.strftime('%d%m%y')}.CSV"

            processed = process_bhavcopy_after_2024(response.content)

            save_file_to_db(
                file_name,
                processed,
                date_obj
            )

            save_log(
    file_name,
    str(date_obj),
    day_name,
    "Downloaded"
)

            return f"Downloaded: {date_obj} ({day_name})"


    except Exception as e:

        file_name = f"EQ{date_obj.strftime('%d%m%y')}.CSV"
        save_log(
    file_name,
    str(date_obj),
    day_name,
    "Error"
)

        return f"Error {date_obj}: {e}"

 
# YEAR DOWNLOAD
 
def download_year_data(year):

    start_date = datetime.date(year, 1, 1)
    end_date = datetime.date(year, 12, 31)

    current = start_date

    while current <= end_date:

        result = download_bhavcopy(current)

        print(result)

        current += datetime.timedelta(days=1)

    return f"Completed year {year}"


def download_all_data():
    start_year = 2017
    current_year = datetime.date.today().year
    for year in range(start_year, current_year + 1):
        download_year_data(year)
    return "Download started..."

# ROUTES
 
@app.route("/", methods=["GET", "POST"])
def index():

    message = ""

    if request.method == "POST":

        if "download_date" in request.form:

            date_str = request.form.get("date")

            date_obj = datetime.datetime.strptime(
                date_str,
                "%Y-%m-%d"
            ).date()

            message = download_bhavcopy(date_obj)

        elif "download_year" in request.form:

            year = int(request.form.get("year"))

            message = download_year_data(year)
        # Download all data
        elif "download_all" in request.form:

            message = download_all_data()

    return render_template("index.html", message=message)


 
# DOWNLOAD FILES FROM DB
 
@app.route("/download-selected", methods=["POST"])
def download_selected():

    selected_ids = request.form.getlist("file_ids")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    saved_count = 0

    for file_id in selected_ids:

        cursor.execute("""
            SELECT file_name, year, month, file_data
            FROM bhavcopy_files
            WHERE id=?
        """, (file_id,))

        row = cursor.fetchone()

        if row:

            file_name, year, month, file_data = row

            save_folder = os.path.join(
                DOWNLOAD_BASE,
                str(year),
                month
            )

            os.makedirs(save_folder, exist_ok=True)

            file_path = os.path.join(save_folder, file_name)

            with open(file_path, "wb") as f:
                f.write(file_data)

            saved_count += 1

    conn.close()

    return jsonify({
        "success": f"{saved_count} files downloaded"
    })


 
# DELETE FILES
 
@app.route("/delete-selected", methods=["POST"])
def delete_selected():

    selected_ids = request.form.getlist("file_ids")

    if not selected_ids:
        return jsonify({"error": "No files selected"}), 400

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    deleted_count = 0

    for file_id in selected_ids:

        cursor.execute("""
            SELECT file_name, year, month
            FROM bhavcopy_files
            WHERE id = ?
        """, (file_id,))

        row = cursor.fetchone()

        if row:
            file_name, year, month = row

            cursor.execute("DELETE FROM bhavcopy_files WHERE id = ?", (file_id,))
            deleted_count += 1

            cursor.execute(
    "DELETE FROM download_logs WHERE file_name=?",
    (file_name,)
)

            # Delete from Downloaded folder
            downloaded_path = os.path.join(DOWNLOAD_BASE, str(year), month, file_name)
            if os.path.exists(downloaded_path):
                os.remove(downloaded_path)

    conn.commit()
    conn.close()

    return jsonify({
        "message": f"{deleted_count} file(s) deleted"
    })


@app.route("/delete-temp", methods=["POST"])
def delete_temp():

    selected_ids = request.form.getlist("file_ids")

    if not selected_ids:
        return jsonify({"error":"No files selected"}),400

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for file_id in selected_ids:

        cursor.execute(
            "UPDATE bhavcopy_files SET is_deleted=1 WHERE id=?",
            (file_id,)
        )

    conn.commit()
    conn.close()

    return jsonify({"message":"Files moved to temporary delete"})

@app.route("/stream-all-logs")
def stream_all_logs():

    key = "all"

    if key not in DOWNLOAD_STATE:
        DOWNLOAD_STATE[key] = {
            "running": False,
            "logs": []
        }

    def generate():

        state = DOWNLOAD_STATE[key]

        # If already running → send existing logs
        if state["running"]:
            for log in state["logs"]:
                yield f"data: {log}\n\n"
            return

        state["running"] = True
        state["logs"].clear()

        start_year = 2017
        current_year = datetime.date.today().year

        for year in range(start_year, current_year + 1):

            log = f"Starting download for {year}"
            state["logs"].append(log)
            yield f"data: {log}\n\n"

            start_date = datetime.date(year, 1, 1)
            if  year==current_year:
                end_date = datetime.date.today()
            else:
                end_date = datetime.date(year, 12, 31)

            current = start_date

            while current <= end_date:

                log = f"Downloading: {current}"
                state["logs"].append(log)
                yield f"data: {log}\n\n"

                result = download_bhavcopy(current)

                state["logs"].append(result)
                yield f"data: {result}\n\n"

                current += datetime.timedelta(days=1)

            log = f"Completed year {year}"
            state["logs"].append(log)
            yield f"data: {log}\n\n"

        finish = "Completed all years"
        state["logs"].append(finish)
        yield f"data: {finish}\n\n"

        state["running"] = False

    return Response(generate(), mimetype="text/event-stream")
 
@app.route("/logs-all")
def logs_all():
    return render_template("logs_all.html")

def get_temp_deleted_files():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, file_name, trade_date, year, month
        FROM bhavcopy_files
        WHERE is_deleted = 1
        ORDER BY trade_date DESC
    """)

    files = cursor.fetchall()

    conn.close()

    return files


 


@app.route("/trash")
def view_trash():

    files = get_temp_deleted_files()

    return render_template("trash.html", files=files)
 


@app.route("/stream-logs/<int:year>")
def stream_logs(year):

    if year not in DOWNLOAD_STATE:
        DOWNLOAD_STATE[year] = {
            "running": False,
            "logs": []
        }

    def generate():

        state = DOWNLOAD_STATE[year]

        # If already running → send existing logs only
        if state["running"]:
            for log in state["logs"]:
                yield f"data: {log}\n\n"
            return

        state["running"] = True
        state["logs"].clear()

        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)

        current = start_date

        while current <= end_date:

            log = f"Downloading: {current}"
            state["logs"].append(log)
            yield f"data: {log}\n\n"

            result = download_bhavcopy(current)

            state["logs"].append(result)
            yield f"data: {result}\n\n"

            current += datetime.timedelta(days=1)

        finish = f"Completed year {year}"
        state["logs"].append(finish)
        yield f"data: {finish}\n\n"

        state["running"] = False

    return Response(generate(), mimetype="text/event-stream")

@app.route("/files")
def view_files():

    selected_year = request.args.get("year")
    selected_month = request.args.get("month")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    query = """
        SELECT id, file_name, trade_date, year, month
        FROM bhavcopy_files
        WHERE is_deleted = 0
    """

    params = []

    if selected_year:
        query += " AND year = ?"
        params.append(selected_year)

    if selected_month:
        query += " AND month = ?"
        params.append(selected_month)

    query += " ORDER BY trade_date DESC"

    cursor.execute(query, params)
    files = cursor.fetchall()

    # dropdown filters
    cursor.execute("SELECT DISTINCT year FROM bhavcopy_files ORDER BY year DESC")
    years = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT month FROM bhavcopy_files ORDER BY month")
    months = [row[0] for row in cursor.fetchall()]

    conn.close()

    return render_template(
        "files.html",
        files=files,
        years=years,
        months=months,
        selected_year=selected_year,
        selected_month=selected_month
    )

@app.route("/logs/<int:year>")
def logs_page(year):
    return render_template("logs.html", year=year)


@app.route("/logs")
def logs_redirect():

    # find running download
    for year, state in DOWNLOAD_STATE.items():
        if state["running"]:
            return redirect(f"/logs/{year}")

    # if none running → show latest log if exists
    if DOWNLOAD_STATE:
        last_year = list(DOWNLOAD_STATE.keys())[-1]
        return redirect(f"/logs/{last_year}")

    return "No logs available"
 
@app.route("/log-dashboard")
def log_dashboard():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT file_name, trade_date, week_day, status, download_time
        FROM download_logs
        ORDER BY trade_date DESC
    """)

    logs = cursor.fetchall()

    conn.close()

    return render_template("log_dashboard.html", logs=logs)
# RUN
 
if __name__ == "__main__":

    init_db()

    app.run(debug=True)