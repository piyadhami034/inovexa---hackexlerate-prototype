"""
=============================================================================
Smart Campus Analytics - Web Application Backend (Phase 3)
=============================================================================
A Student Success Platform for college staff (Admin, Faculty).
Backend Stack: Python Flask + SQLite + pandas + Werkzeug

Core Features:
1. Session-based authentication with role authorization (Admin vs. Faculty).
2. Every route except /login rejects unauthenticated requests (HTTP 401 for APIs).
3. Role-based security: Only Admin may add or edit student records (HTTP 403 for Faculty).
4. Audit logging table: Records every add/edit action (who, when, what changed).
5. Comprehensive input validation: Range boundaries, required fields, duplicate UID protection.
6. Automatic score recalculation: Re-runs the scoring engine immediately upon data mutation.
7. Complete suite of RESTful JSON APIs:
   - Auth: login, logout, me
   - Batches: list, select, summary
   - Students: list (search & filter), details (all 7 data sources, reasons, contributions)
   - At-Risk & Segments: academic risk, placement risk, dual risk, cohort segments
   - Trends: score distributions, subject-wise attendance and marks, skills profiles
   - Data Quality: anomaly fixes report and summary counts
   - Data Management: Add student, Edit student, Audit log history
=============================================================================
"""

import os
import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import io
import csv
import numpy as np
import pandas as pd
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    Response,
    g
)
from werkzeug.security import check_password_hash

# Import the Phase 2 scoring and explainability engine
import scoring

# ---------------------------------------------------------------------------
# Flask Application Setup & Path Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "data" / "campus.db"

app.secret_key = os.environ.get("SECRET_KEY", "smart-campus-dev-secret-key-2026-phase3")
app.permanent_session_lifetime = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Database Helper & Connection Lifecycle
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    """
    Returns an active SQLite database connection for the current request.
    Uses sqlite3.Row factory so columns can be accessed by name like a dictionary.
    """
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        # Enable foreign key constraint enforcement
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    """Closes the SQLite connection when the request finishes."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_audit_table():
    """
    Ensures the 'audit_log' table exists in the database for tracking data modifications.
    Schema: (id, username, role, action, target_uid, details, timestamp)
    """
    if not DATABASE_PATH.exists():
        return

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            target_uid TEXT,
            details TEXT,
            timestamp TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Helper: Determine Request Type (HTML Browser vs JSON API)
# ---------------------------------------------------------------------------
def is_api_request() -> bool:
    """
    Returns True if the current request is intended for an API endpoint
    (starts with /api/ or has Content-Type / Accept as application/json).
    """
    if request.path.startswith("/api/"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


@app.before_request
def check_session_inactivity():
    """
    Enforces automatic logout after 15 minutes (900s) of inactivity.
    Redirects browser users to /login with notification;
    returns 401 Unauthorized for API requests.
    """
    if request.path.startswith("/static"):
        return

    if request.path in ("/login", "/logout", "/api/auth/login", "/api/auth/logout"):
        return

    if "user_id" in session:
        now = time.time()
        last_activity = session.get("last_activity")
        if last_activity and (now - last_activity > 900):
            session.clear()
            if is_api_request():
                return jsonify({
                    "success": False,
                    "error": "Your session has expired due to 15 minutes of inactivity. Please log in again."
                }), 401
            flash("Your session has expired due to 15 minutes of inactivity. Please log in again.", "info")
            return redirect(url_for("login"))

        session["last_activity"] = now


# ---------------------------------------------------------------------------
# Authentication & Authorization Decorators
# ---------------------------------------------------------------------------
def login_required(view_func):
    """
    Enforces authentication on protected routes.
    Rejects unauthenticated requests with:
      - HTTP 401 JSON error for API calls.
      - Redirect to /login for browser page visits.
    """
    @wraps(view_func)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if is_api_request():
                return jsonify({
                    "success": False,
                    "error": "Unauthorized: Please log in to access this resource."
                }), 401
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return decorated_function


def admin_required(view_func):
    """
    Enforces Administrator role access on sensitive operations (e.g. Add/Edit Student).
    Rejects non-admin users with:
      - HTTP 403 Forbidden for API calls.
      - Flash message and redirect for browser page visits.
    """
    @wraps(view_func)
    def decorated_function(*args, **kwargs):
        # First ensure user is logged in
        if "user_id" not in session:
            if is_api_request():
                return jsonify({
                    "success": False,
                    "error": "Unauthorized: Please log in first."
                }), 401
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))

        # Then verify user has Admin role
        if session.get("role") != "Admin":
            if is_api_request():
                return jsonify({
                    "success": False,
                    "error": "Forbidden: Only Admin staff are authorized to perform this operation."
                }), 403
            flash("Access denied: Admin privileges required.", "error")
            return redirect(url_for("select_batch"))

        return view_func(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# Input Validation Rules & Audit Logger
# ---------------------------------------------------------------------------
FIELD_RULES: Dict[str, Tuple[float, float, type, str]] = {
    # Column: (min_value, max_value, data_type, human_readable_description)
    "cgpa": (0.0, 10.0, float, "CGPA must be between 0.0 and 10.0"),
    "internal_avg": (0.0, 40.0, float, "Internal marks average must be between 0.0 and 40.0"),
    "exam_avg": (0.0, 60.0, float, "Exam marks average must be between 0.0 and 60.0"),
    "backlogs": (0, 20, int, "Backlogs must be an integer between 0 and 20"),
    "attendance_overall": (0.0, 100.0, float, "Overall attendance must be between 0% and 100%"),
    "attendance_avg_subject": (0.0, 100.0, float, "Subject attendance average must be between 0% and 100%"),
    "lms_login_freq": (0, 500, int, "LMS login frequency must be between 0 and 500 logins/month"),
    "lms_assignment_pct": (0.0, 100.0, float, "LMS assignment completion must be between 0% and 100%"),
    "lms_resources": (0, 500, int, "LMS resources downloaded must be between 0 and 500"),
    "lms_forum_posts": (0, 300, int, "LMS forum posts must be between 0 and 300"),
    "events_attended": (0, 50, int, "Events attended must be between 0 and 50"),
    "clubs_joined": (0, 15, int, "Clubs joined must be between 0 and 15"),
    "hackathons": (0, 30, int, "Hackathons participated must be between 0 and 30"),
    "certifications": (0, 30, int, "Certifications earned must be between 0 and 30"),
    "workshops": (0, 30, int, "Workshops attended must be between 0 and 30"),
    "aptitude_score": (0.0, 100.0, float, "Aptitude score must be between 0 and 100"),
    "coding_score": (0.0, 100.0, float, "Coding score must be between 0 and 100"),
    "mock_interview": (0.0, 100.0, float, "Mock interview score must be between 0 and 100"),
    "communication_score": (0.0, 100.0, float, "Communication score must be between 0 and 100"),
    "drives_attended": (0, 30, int, "Drives attended must be between 0 and 30"),
    "offers_received": (0, 10, int, "Offers received must be between 0 and 10"),
    "python_score": (0.0, 100.0, float, "Python score must be between 0 and 100"),
    "sql_score": (0.0, 100.0, float, "SQL score must be between 0 and 100"),
    "problem_solving": (0.0, 100.0, float, "Problem solving score must be between 0 and 100"),
    "skill_communication": (0.0, 100.0, float, "Skill communication score must be between 0 and 100"),
    "teamwork": (0.0, 100.0, float, "Teamwork score must be between 0 and 100"),
    "leadership": (0.0, 100.0, float, "Leadership score must be between 0 and 100"),
    "student_satisfaction": (1.0, 5.0, float, "Student satisfaction rating must be between 1.0 and 5.0"),
    "faculty_feedback": (1.0, 5.0, float, "Faculty feedback rating must be between 1.0 and 5.0"),
    "course_rating": (1.0, 5.0, float, "Course rating must be between 1.0 and 5.0"),
    "infrastructure_rating": (1.0, 5.0, float, "Infrastructure rating must be between 1.0 and 5.0"),
    "overall_experience": (1.0, 5.0, float, "Overall experience rating must be between 1.0 and 5.0"),
}


def validate_student_inputs(data: Dict[str, Any], is_new: bool = False) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Validates payload for student add/edit:
    1. Checks required fields (uid, name, batch_code for new records).
    2. Validates numerical bounds according to FIELD_RULES.
    3. Type-casts valid values to their proper float/int types.
    Returns: (is_valid, error_message, cleaned_data_dict)
    """
    cleaned: Dict[str, Any] = {}

    # Check required fields for new records
    if is_new:
        uid = str(data.get("uid", "")).strip().upper()
        if not uid:
            return False, "Student UID is required.", {}
        # Ensure UID is alphanumeric with standard symbols
        if not uid.replace("-", "").replace("_", "").isalnum():
            return False, "UID may only contain alphanumeric characters, hyphens, and underscores.", {}
        cleaned["uid"] = uid

        name = str(data.get("name", "")).strip()
        if not name or len(name) < 2:
            return False, "Student full name is required (minimum 2 characters).", {}
        cleaned["name"] = name

        batch_code = str(data.get("batch_code", "")).strip()
        if not batch_code:
            return False, "Batch code is required.", {}
        cleaned["batch_code"] = batch_code

    # Optional updates to name or batch_code during edit
    if not is_new:
        if "name" in data:
            name = str(data.get("name", "")).strip()
            if not name or len(name) < 2:
                return False, "Student name cannot be empty.", {}
            cleaned["name"] = name
        if "batch_code" in data:
            batch_code = str(data.get("batch_code", "")).strip()
            if not batch_code:
                return False, "Batch code cannot be empty.", {}
            cleaned["batch_code"] = batch_code

    # Validate all metric fields
    for field_name, (min_val, max_val, expected_type, err_msg) in FIELD_RULES.items():
        if field_name in data:
            raw_val = data[field_name]
            if raw_val is None or str(raw_val).strip() == "":
                # For new records, set default median if omitted; for edit, skip if blank
                if is_new:
                    default_mid = (min_val + max_val) / 2.0
                    cleaned[field_name] = expected_type(round(default_mid)) if expected_type is int else round(default_mid, 2)
                continue

            try:
                numeric_val = expected_type(raw_val)
            except (ValueError, TypeError):
                return False, f"Field '{field_name}' must be a valid number: {err_msg}", {}

            if numeric_val < min_val or numeric_val > max_val:
                return False, f"Field '{field_name}' value {numeric_val} is out of bounds: {err_msg}", {}

            cleaned[field_name] = numeric_val
        elif is_new:
            # Assign reasonable mid-range defaults for new students if not specified
            default_mid = (min_val + max_val) / 2.0
            cleaned[field_name] = expected_type(round(default_mid)) if expected_type is int else round(default_mid, 2)

    return True, None, cleaned


def log_audit_action(action: str, target_uid: str, details: Any):
    """
    Inserts an entry into the audit_log table.
    Captures: who performed it, their role, the timestamp, action type, target student UID, and changes.
    """
    try:
        username = session.get("username", "system")
        role = session.get("role", "Admin")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        details_json = json.dumps(details) if not isinstance(details, str) else details

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_log (username, role, action, target_uid, details, timestamp)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (username, role, action, target_uid, details_json, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Failed to write audit log: {e}")


def recalculate_cohort_scores():
    """
    Re-runs the Phase 2 scoring and explainability engine across the dataset,
    ensuring that Success Scores, Academic & Placement subscores, risk flags,
    rule-based segments, and explainability contributions are immediately refreshed.
    """
    try:
        scored_df, _ = scoring.load_and_score(DATABASE_PATH)
        scoring.update_database_scores(scored_df, DATABASE_PATH)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to recalculate scores: {e}")
        return False


def get_active_batch_code() -> str:
    """
    Retrieves the currently selected batch_code from session,
    falling back to the first available batch in the database.
    """
    if "batch_code" in session and session["batch_code"]:
        return session["batch_code"]
    db = get_db()
    first_batch = db.execute("SELECT batch_code FROM batches ORDER BY start_year DESC, batch_code ASC LIMIT 1").fetchone()
    if first_batch:
        return first_batch["batch_code"]
    return "CSE_2023_27"


# ---------------------------------------------------------------------------
# HTML Web Pages (Protected)
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Redirects to overview, batch selection, or login based on authentication and active cohort."""
    if "user_id" in session:
        if session.get("batch_code"):
            return redirect(url_for("overview"))
        return redirect(url_for("select_batch"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Login page (HTML form handler).
    Validates user credentials against hashed passwords stored in SQLite.
    """
    if request.method == "GET" and "user_id" in session:
        return redirect(url_for("select_batch"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please enter both username and password.", "error")
            return render_template("login.html")

        db = get_db()
        user = db.execute(
            "SELECT id, username, password_hash, role, full_name FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]
            session["last_activity"] = time.time()
            return redirect(url_for("select_batch"))
        else:
            flash("Invalid username or password. Please try again.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Logs the user out, clears session, and redirects to login."""
    is_inactive = (request.args.get("inactivity") == "1")
    session.clear()
    if is_inactive:
        flash("Your session has expired due to 15 minutes of inactivity. Please log in again.", "info")
    else:
        flash("You have been logged out successfully.", "info")
    return redirect(url_for("login"))


@app.route("/select-batch", methods=["GET", "POST"])
@login_required
def select_batch():
    """Displays batches grid and handles batch selection."""
    db = get_db()

    if request.method == "POST":
        batch_code = request.form.get("batch_code", "").strip()
        if batch_code:
            session["batch_code"] = batch_code
            return redirect(url_for("overview"))
        else:
            flash("Please select a valid batch.", "error")

    batches = db.execute("""
        SELECT 
            b.id,
            b.batch_code,
            b.batch_name,
            b.department,
            b.start_year,
            b.end_year,
            COUNT(s.uid) AS student_count,
            ROUND(AVG(s.success_score), 1) AS avg_score,
            ROUND(AVG(s.attendance_overall), 1) AS avg_att
        FROM batches b
        LEFT JOIN students s ON b.batch_code = s.batch_code
        GROUP BY b.batch_code, b.id, b.batch_name, b.department, b.start_year, b.end_year
        ORDER BY b.start_year DESC, b.batch_name ASC
    """).fetchall()

    return render_template("select_batch.html", batches=batches)


@app.route("/overview")
@login_required
def overview():
    """
    Overview Dashboard (Page 3 of Page Flow):
    Renders 4 Stat Cards, 3 Navigation Flow Cards, and the Students Requiring Attention Table.
    """
    batch_code = get_active_batch_code()
    session["batch_code"] = batch_code
    db = get_db()

    # Batch information
    batch_info = db.execute(
        "SELECT batch_code, batch_name, department, start_year, end_year FROM batches WHERE batch_code = ?",
        (batch_code,)
    ).fetchone()

    if not batch_info:
        flash(f"Batch '{batch_code}' not found.", "error")
        return redirect(url_for("select_batch"))

    # Summary KPI Aggregates
    summary_row = db.execute("""
        SELECT 
            COUNT(uid) AS total_students,
            ROUND(AVG(success_score), 1) AS class_average,
            ROUND(AVG(attendance_overall), 1) AS attendance_avg,
            SUM(CASE WHEN needs_attention = 1 THEN 1 ELSE 0 END) AS attention_count
        FROM students
        WHERE batch_code = ?;
    """, (batch_code,)).fetchone()

    # Query students requiring attention
    attention_rows = db.execute("""
        SELECT 
            uid,
            name,
            batch_code,
            success_score,
            cgpa,
            internal_avg,
            exam_avg,
            backlogs,
            attendance_overall,
            academic_subscore,
            placement_subscore,
            risk_level,
            needs_attention,
            segment
        FROM students
        WHERE batch_code = ? AND (needs_attention = 1 OR risk_level = 'High' OR success_score < 50.0)
        ORDER BY success_score ASC, attendance_overall ASC;
    """, (batch_code,)).fetchall()

    attention_list = []
    for s in attention_rows:
        parts = s["name"].split()
        initials = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()
        marks_pct = round(((s["internal_avg"] / 40.0) * 50.0) + ((s["exam_avg"] / 60.0) * 50.0), 1)
        att_pct = round(s["attendance_overall"], 1)

        if att_pct < 65.0 and marks_pct < 50.0:
            concern = "Multiple below threshold"
        elif att_pct < 65.0:
            concern = "Low attendance"
        elif s["backlogs"] >= 3:
            concern = "Multiple backlogs"
        elif marks_pct < 45.0 or s["cgpa"] < 5.5:
            concern = "Low marks"
        elif s["placement_subscore"] < 40.0:
            concern = "Placement risk"
        else:
            concern = "Academic concern"

        priority = "High" if (s["risk_level"] == "High" or marks_pct < 45.0 or att_pct < 60.0 or s["backlogs"] >= 3) else "Medium"

        attention_list.append({
            "uid": s["uid"],
            "name": s["name"],
            "initials": initials,
            "avg_marks": f"{marks_pct}%",
            "attendance": f"{att_pct}%",
            "raw_marks_pct": marks_pct,
            "raw_attendance_pct": att_pct,
            "primary_concern": concern,
            "priority": priority,
            "success_score": s["success_score"],
            "segment": s["segment"],
        })

    kpis = {
        "total_students": summary_row["total_students"] or 0,
        "avg_success_score": summary_row["class_average"] or 0.0,
        "class_average": summary_row["class_average"] or 0.0,
        "attendance_avg": summary_row["attendance_avg"] or 0.0,
        "attention_count": summary_row["attention_count"] or 0,
    }

    # Indicator weights for 'How is the score calculated?' modal
    scoring_weights = [
        {"name": "Examinations (End-Sem)", "weight": 15, "desc": "End-semester external examination scores (scaled from 60 marks)"},
        {"name": "Internal Assessments", "weight": 15, "desc": "Continuous internal assessment marks (scaled from 40 marks)"},
        {"name": "Attendance Tracking", "weight": 15, "desc": "Overall lecture and lab presence percentage across all subjects"},
        {"name": "LMS Engagement", "weight": 10, "desc": "Assignment completion rate, login frequency, downloads, forum activity"},
        {"name": "Placement Tests & Drives", "weight": 20, "desc": "Aptitude, coding tests, mock interviews, and drive attendance"},
        {"name": "Skills Assessment", "weight": 10, "desc": "Technical skills (Python, SQL, problem solving) & soft skills (leadership, teamwork)"},
        {"name": "Extracurricular Activities", "weight": 8, "desc": "Clubs, technical hackathons, workshops, and verified certifications"},
        {"name": "Campus Experience Feedback", "weight": 7, "desc": "Student satisfaction and faculty mentorship evaluations"},
    ]

    return render_template(
        "overview.html",
        batch=batch_info,
        kpis=kpis,
        attention_students=attention_list,
        scoring_weights=scoring_weights
    )


@app.route("/api/batch/attention-csv")
@login_required
def api_attention_csv():
    """
    Downloads a CSV file listing all students needing attention in the selected batch,
    strictly sorted with the lowest Success Score first.
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    db = get_db()

    rows = db.execute("""
        SELECT 
            uid, name, batch_code, success_score, cgpa, attendance_overall,
            internal_avg, exam_avg, backlogs, risk_level, segment,
            academic_subscore, placement_subscore
        FROM students
        WHERE batch_code = ? AND (needs_attention = 1 OR risk_level = 'High' OR success_score < 50.0)
        ORDER BY success_score ASC, attendance_overall ASC;
    """, (batch_code,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "UID", "Student Name", "Batch Code", "Success Score (0-100)", "CGPA",
        "Overall Attendance %", "Internal Avg (/40)", "Exam Avg (/60)",
        "Active Backlogs", "Academic Readiness", "Placement Readiness",
        "Risk Priority", "Cohort Segment", "Primary Concern"
    ])

    for r in rows:
        att = r["attendance_overall"] or 0.0
        marks_pct = round(((r["internal_avg"] / 40.0) * 50.0) + ((r["exam_avg"] / 60.0) * 50.0), 1)
        if att < 65.0 and marks_pct < 50.0:
            concern = "Multiple below threshold"
        elif att < 65.0:
            concern = "Low attendance"
        elif r["backlogs"] >= 3:
            concern = "Multiple backlogs"
        elif marks_pct < 45.0 or (r["cgpa"] and r["cgpa"] < 5.5):
            concern = "Low marks"
        elif r["placement_subscore"] and r["placement_subscore"] < 40.0:
            concern = "Placement risk"
        else:
            concern = "Academic concern"

        priority = "High" if (r["risk_level"] == "High" or marks_pct < 45.0 or att < 60.0 or r["backlogs"] >= 3) else "Medium"

        writer.writerow([
            r["uid"],
            r["name"],
            r["batch_code"],
            r["success_score"],
            r["cgpa"],
            att,
            r["internal_avg"],
            r["exam_avg"],
            r["backlogs"],
            r["academic_subscore"],
            r["placement_subscore"],
            priority,
            r["segment"],
            concern
        ])

    csv_content = output.getvalue()
    filename = f"attention_students_{batch_code}.csv"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "text/csv; charset=utf-8"
        }
    )


@app.route("/students-view")
@login_required
def students_view():
    """
    Students Directory View (Page 4 of Page Flow):
    Renders searchable, filterable table of all students in the batch with scores, risk flags, and segments.
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    session["batch_code"] = batch_code
    db = get_db()

    # Batch information
    batch_info = db.execute(
        "SELECT batch_code, batch_name, department, start_year, end_year FROM batches WHERE batch_code = ?",
        (batch_code,)
    ).fetchone()

    if not batch_info:
        flash(f"Batch '{batch_code}' not found.", "error")
        return redirect(url_for("select_batch"))

    # Filter parameters
    search = request.args.get("search", "").strip()
    risk_filter = request.args.get("risk", "all").strip().lower()
    segment_filter = request.args.get("segment", "all").strip()
    sort_by = request.args.get("sort_by", "success_score").strip()
    sort_order = request.args.get("sort_order", "desc").strip().lower()

    allowed_sort_cols = {
        "uid", "name", "cgpa", "attendance_overall", "success_score",
        "academic_subscore", "placement_subscore", "risk_level", "segment", "backlogs"
    }
    if sort_by not in allowed_sort_cols:
        sort_by = "success_score"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    # Distinct segments for dropdown filter
    segment_rows = db.execute(
        "SELECT DISTINCT segment FROM students WHERE batch_code = ? AND segment IS NOT NULL ORDER BY segment ASC;",
        (batch_code,)
    ).fetchall()
    available_segments = [r["segment"] for r in segment_rows if r["segment"]]

    # Build query
    query = """
        SELECT 
            s.uid, s.name, s.batch_code, s.cgpa, s.internal_avg, s.exam_avg,
            s.backlogs, s.attendance_overall, s.success_score, s.academic_subscore,
            s.placement_subscore, s.risk_level, s.needs_attention, s.risk_academic,
            s.risk_placement, s.risk_flag, s.segment
        FROM students s
        WHERE s.batch_code = ?
    """
    params: List[Any] = [batch_code]

    if search:
        query += " AND (s.uid LIKE ? OR s.name LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term])

    if risk_filter == "high":
        query += " AND s.risk_level = 'High'"
    elif risk_filter == "medium":
        query += " AND s.risk_level = 'Medium'"
    elif risk_filter == "low":
        query += " AND s.risk_level = 'Low'"
    elif risk_filter == "attention":
        query += " AND (s.needs_attention = 1 OR s.risk_level = 'High')"

    if segment_filter and segment_filter.lower() != "all":
        query += " AND s.segment = ?"
        params.append(segment_filter)

    query += f" ORDER BY s.{sort_by} {sort_order.upper()};"

    rows = db.execute(query, params).fetchall()

    students = []
    for r in rows:
        item = dict(r)
        parts = item["name"].split()
        item["initials"] = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()
        students.append(item)

    active_filters = {
        "search": search,
        "risk": risk_filter,
        "segment": segment_filter,
        "sort_by": sort_by,
        "sort_order": sort_order
    }

    return render_template(
        "students_list.html",
        batch=batch_info,
        students=students,
        active_filters=active_filters,
        available_segments=available_segments
    )


@app.route("/students-view/<uid>")
@login_required
def student_detail_view(uid: str):
    """
    Student Detail View (Page 5 of Page Flow):
    Renders complete student profile, all 7 data sources, Why Flagged panel, and score breakdown chart.
    """
    norm_uid = uid.strip().upper()
    db = get_db()

    student_row = db.execute("""
        SELECT s.*, b.batch_name, b.department, b.start_year, b.end_year
        FROM students s
        LEFT JOIN batches b ON s.batch_code = b.batch_code
        WHERE s.uid = ?;
    """, (norm_uid,)).fetchone()

    if not student_row:
        flash(f"Student with UID '{norm_uid}' not found.", "error")
        return redirect(url_for("students_view"))

    student = dict(student_row)

    # Detailed subject academic marks
    academic_subjects = db.execute("""
        SELECT subject, internal_marks, exam_marks,
               ROUND(internal_marks + exam_marks, 1) AS total_marks
        FROM academic_details
        WHERE uid = ?
        ORDER BY subject ASC;
    """, (norm_uid,)).fetchall()

    # Detailed subject attendance
    attendance_subjects = db.execute("""
        SELECT subject, attendance_pct
        FROM attendance_details
        WHERE uid = ?
        ORDER BY subject ASC;
    """, (norm_uid,)).fetchall()

    # Parse explainability reasons and actions
    try:
        top_reasons = json.loads(student.get("top_reasons") or "[]")
    except Exception:
        top_reasons = []

    try:
        top_actions = json.loads(student.get("top_actions") or "[]")
    except Exception:
        top_actions = []

    # Batch averages for indicator comparison
    batch_averages_row = db.execute("""
        SELECT 
            ROUND(AVG(cgpa), 2) AS avg_cgpa,
            ROUND(AVG((exam_avg / 60.0) * 100.0), 1) AS avg_examinations,
            ROUND(AVG((internal_avg / 40.0) * 100.0), 1) AS avg_internal,
            ROUND(AVG(attendance_overall), 1) AS avg_attendance,
            ROUND(AVG(lms_assignment_pct), 1) AS avg_lms,
            ROUND(AVG((aptitude_score + coding_score + mock_interview) / 3.0), 1) AS avg_placement,
            ROUND(AVG((python_score + sql_score + problem_solving + skill_communication + teamwork + leadership) / 6.0), 1) AS avg_skills,
            ROUND(AVG(student_satisfaction), 1) AS avg_feedback
        FROM students
        WHERE batch_code = ?;
    """, (student["batch_code"],)).fetchone()

    # Seven integrated data sources
    seven_sources = {
        "academic": {
            "title": "Academic Performance",
            "cgpa": student["cgpa"],
            "internal_avg": student["internal_avg"],
            "exam_avg": student["exam_avg"],
            "backlogs": student["backlogs"],
            "subjects": [dict(r) for r in academic_subjects],
        },
        "attendance": {
            "title": "Attendance Tracking",
            "overall_pct": student["attendance_overall"],
            "subject_avg_pct": student["attendance_avg_subject"],
            "subjects": [dict(r) for r in attendance_subjects],
        },
        "lms": {
            "title": "Learning Management System (LMS)",
            "login_frequency": student["lms_login_freq"],
            "assignment_completion_pct": student["lms_assignment_pct"],
            "resources_downloaded": student["lms_resources"],
            "forum_posts": student["lms_forum_posts"],
        },
        "engagement": {
            "title": "Extracurricular Engagement",
            "events_attended": student["events_attended"],
            "clubs_joined": student["clubs_joined"],
            "hackathons": student["hackathons"],
            "certifications": student["certifications"],
            "workshops": student["workshops"],
        },
        "placement": {
            "title": "Placement Readiness",
            "aptitude_score": student["aptitude_score"],
            "coding_score": student["coding_score"],
            "mock_interview": student["mock_interview"],
            "communication_score": student["communication_score"],
            "drives_attended": student["drives_attended"],
            "offers_received": student["offers_received"],
        },
        "skills": {
            "title": "Skills Assessment",
            "python_score": student["python_score"],
            "sql_score": student["sql_score"],
            "problem_solving": student["problem_solving"],
            "communication": student["skill_communication"],
            "teamwork": student["teamwork"],
            "leadership": student["leadership"],
        },
        "feedback": {
            "title": "Student & Faculty Feedback",
            "student_satisfaction": student["student_satisfaction"],
            "faculty_feedback": student["faculty_feedback"],
            "course_rating": student["course_rating"],
            "infrastructure_rating": student["infrastructure_rating"],
            "overall_experience": student["overall_experience"],
        }
    }

    # Normalized 8-indicator breakdown
    norm_exam = round((student["exam_avg"] / 60.0) * 100.0, 1)
    norm_internal = round((student["internal_avg"] / 40.0) * 100.0, 1)
    norm_att = round(student["attendance_overall"], 1)
    norm_lms = round(student["lms_assignment_pct"], 1)
    norm_place = round((student["aptitude_score"] + student["coding_score"] + student["mock_interview"]) / 3.0, 1)
    norm_skills = round((student["python_score"] + student["sql_score"] + student["problem_solving"] +
                         student["skill_communication"] + student["teamwork"] + student["leadership"]) / 6.0, 1)
    total_acts = (student["events_attended"] + student["clubs_joined"] + student["hackathons"] +
                  student["certifications"] + student["workshops"])
    norm_extra = round(min(100.0, (total_acts / 30.0) * 100.0), 1)
    fb_avg = ((student["student_satisfaction"] + student["faculty_feedback"] + student["course_rating"] +
               student["infrastructure_rating"] + student["overall_experience"]) / 5.0)
    norm_fb = round((fb_avg / 5.0) * 100.0, 1)

    indicators_breakdown = [
        {"name": "Examinations", "weight": 15, "value": norm_exam, "batch_avg": batch_averages_row["avg_examinations"] if batch_averages_row else 50.0},
        {"name": "Internal assessments", "weight": 15, "value": norm_internal, "batch_avg": batch_averages_row["avg_internal"] if batch_averages_row else 50.0},
        {"name": "Attendance", "weight": 15, "value": norm_att, "batch_avg": batch_averages_row["avg_attendance"] if batch_averages_row else 65.0},
        {"name": "LMS activity", "weight": 10, "value": norm_lms, "batch_avg": batch_averages_row["avg_lms"] if batch_averages_row else 50.0},
        {"name": "Placement participation & tests", "weight": 20, "value": norm_place, "batch_avg": batch_averages_row["avg_placement"] if batch_averages_row else 50.0},
        {"name": "Skills", "weight": 10, "value": norm_skills, "batch_avg": batch_averages_row["avg_skills"] if batch_averages_row else 50.0},
        {"name": "Extracurricular", "weight": 8, "value": norm_extra, "batch_avg": 45.0},
        {"name": "Feedback", "weight": 7, "value": norm_fb, "batch_avg": 60.0},
    ]

    parts = student["name"].split()
    initials = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    student_data = {
        "uid": student["uid"],
        "name": student["name"],
        "initials": initials,
        "batch_code": student["batch_code"],
        "batch_name": student.get("batch_name"),
        "department": student.get("department"),
        "success_score": student["success_score"],
        "academic_subscore": student["academic_subscore"],
        "placement_subscore": student["placement_subscore"],
        "risk_level": student["risk_level"],
        "needs_attention": student["needs_attention"],
        "risk_flag": student["risk_flag"],
        "segment": student["segment"],
        "top_reasons": top_reasons,
        "top_actions": top_actions,
        "indicators_breakdown": indicators_breakdown,
        "sources": seven_sources
    }

    return render_template("student_detail.html", student=student_data)


@app.route("/at-risk-view")
@login_required
def at_risk_view():
    """
    At-Risk & Segments View (Page 6 of Page Flow):
    Renders side-by-side Academic Risk and Placement Risk rosters,
    plus 6 behavioral cohort segment cards with interventions and a Chart.js segment size chart.
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    session["batch_code"] = batch_code
    db = get_db()

    # Batch information
    batch_info = db.execute(
        "SELECT batch_code, batch_name, department, start_year, end_year FROM batches WHERE batch_code = ?",
        (batch_code,)
    ).fetchone()

    if not batch_info:
        flash(f"Batch '{batch_code}' not found.", "error")
        return redirect(url_for("select_batch"))

    # Query all students in batch
    rows = db.execute("""
        SELECT 
            uid, name, batch_code, cgpa, internal_avg, exam_avg, backlogs,
            attendance_overall, aptitude_score, coding_score, mock_interview,
            success_score, academic_subscore, placement_subscore,
            risk_level, needs_attention, risk_academic, risk_placement, risk_flag,
            segment
        FROM students
        WHERE batch_code = ?
        ORDER BY success_score ASC;
    """, (batch_code,)).fetchall()

    academic_risk_students = []
    placement_risk_students = []

    # Pre-configure the 6 canonical cohort segments
    segments_config = [
        {
            "name": "High Performers",
            "icon": "🌟",
            "color": "#10b981",
            "bg_color": "rgba(16, 185, 129, 0.12)",
            "description": "Consistent high achievers excelling across academic grades, coding tests, and campus activities.",
            "intervention": "Nominate for honors projects, university research fellowships, and peer study tutoring leadership.",
            "students": []
        },
        {
            "name": "Strong Academics but Low Placement Readiness",
            "icon": "📘",
            "color": "#3b82f6",
            "bg_color": "rgba(59, 130, 246, 0.12)",
            "description": "Solid classroom grades (CGPA ≥ 6.0), but lagging in aptitude test speed, coding challenges, or mock interviews.",
            "intervention": "Enroll in targeted technical interview bootcamps, resume clinics, and weekly mock coding challenges.",
            "students": []
        },
        {
            "name": "Placement Ready but Weak Academics",
            "icon": "💻",
            "color": "#f59e0b",
            "bg_color": "rgba(245, 158, 11, 0.12)",
            "description": "Strong practical coding skills and interview confidence, but at academic risk due to low internals, exam marks, or backlogs.",
            "intervention": "Schedule remedial tutoring sessions, previous exam question reviews, and backlog clearing milestones.",
            "students": []
        },
        {
            "name": "Disengaged",
            "icon": "⚠️",
            "color": "#ef4444",
            "bg_color": "rgba(239, 68, 68, 0.12)",
            "description": "Critically low attendance (< 60%), neglected LMS activity, and multiple active backlogs indicating detachment.",
            "intervention": "Immediate 1-on-1 pastoral counseling, parent-mentor academic conference, and attendance warning notice.",
            "students": []
        },
        {
            "name": "Needs Overall Support",
            "icon": "🚨",
            "color": "#dc2626",
            "bg_color": "rgba(220, 38, 38, 0.12)",
            "description": "Facing comprehensive difficulties across both classroom academic assessments and placement readiness benchmarks.",
            "intervention": "Design an Individualized Student Support Plan (ISSP) pairing faculty remedial sessions with peer study buddies.",
            "students": []
        },
        {
            "name": "Steady",
            "icon": "⚖️",
            "color": "#64748b",
            "bg_color": "rgba(100, 116, 139, 0.12)",
            "description": "Stable cohort students comfortably meeting departmental benchmarks without acute deficits in either domain.",
            "intervention": "Provide regular semester milestone checkpoints and encourage participation in upcoming hackathons and clubs.",
            "students": []
        }
    ]

    segments_by_name = {s["name"]: s for s in segments_config}

    for r in rows:
        item = dict(r)
        parts = item["name"].split()
        item["initials"] = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

        # 1. Academic Risk List Evaluation
        if item["risk_academic"] == 1 or (item["academic_subscore"] and item["academic_subscore"] < 50.0):
            # Compute main diagnostic reason
            if item["attendance_overall"] < 65.0:
                acad_reason = f"Low attendance ({item['attendance_overall']}%)"
            elif item["backlogs"] >= 3:
                acad_reason = f"{item['backlogs']} active backlogs"
            elif item["exam_avg"] < 30.0:
                acad_reason = f"Low exam score ({item['exam_avg']}/60)"
            elif item["internal_avg"] < 20.0:
                acad_reason = f"Low internal marks ({item['internal_avg']}/40)"
            elif item["cgpa"] < 6.0:
                acad_reason = f"CGPA {item['cgpa']} below minimum threshold"
            else:
                acad_reason = f"Academic readiness deficit ({item['academic_subscore']}/100)"
            
            acad_item = dict(item)
            acad_item["main_reason"] = acad_reason
            academic_risk_students.append(acad_item)

        # 2. Placement Risk List Evaluation
        if item["risk_placement"] == 1 or (item["placement_subscore"] and item["placement_subscore"] < 50.0):
            # Compute main diagnostic reason
            if item["aptitude_score"] < 40.0:
                place_reason = f"Aptitude score ({item['aptitude_score']}/100)"
            elif item["coding_score"] < 40.0:
                place_reason = f"Coding score ({item['coding_score']}/100)"
            elif item["mock_interview"] < 40.0:
                place_reason = f"Mock interview ({item['mock_interview']}/100)"
            else:
                place_reason = f"Placement readiness deficit ({item['placement_subscore']}/100)"

            place_item = dict(item)
            place_item["main_reason"] = place_reason
            placement_risk_students.append(place_item)

        # 3. Categorize into Segments
        seg_name = item.get("segment") or "Steady"
        if seg_name in segments_by_name:
            segments_by_name[seg_name]["students"].append(item)
        else:
            segments_by_name["Steady"]["students"].append(item)

    # Calculate counts and chart data
    segment_chart_labels = []
    segment_chart_counts = []
    segment_chart_colors = []

    for s in segments_config:
        s["count"] = len(s["students"])
        segment_chart_labels.append(s["name"])
        segment_chart_counts.append(s["count"])
        segment_chart_colors.append(s["color"])

    return render_template(
        "at_risk.html",
        batch=batch_info,
        total_students=len(rows),
        academic_risk_students=academic_risk_students,
        placement_risk_students=placement_risk_students,
        segments=segments_config,
        segment_chart_labels=segment_chart_labels,
        segment_chart_counts=segment_chart_counts,
        segment_chart_colors=segment_chart_colors
    )


@app.route("/data-management-view")
@login_required
def data_management_view():
    """
    Data Management & Quality Control Dashboard (Page 7 of Page Flow):
    Provides:
      - Warning modal prompt before modifying records
      - View-only protection for Faculty staff
      - Editable students table with live search and edit modal
      - Add-student form with validation and automated score recalculation
      - Automated CSV ingestion and data cleaning pipeline
      - Data Quality Report displaying fixed anomalies
      - System Audit Log showing modification histories
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    session["batch_code"] = batch_code
    db = get_db()

    # Batch information
    batch_info = db.execute(
        "SELECT batch_code, batch_name, department, start_year, end_year FROM batches WHERE batch_code = ?",
        (batch_code,)
    ).fetchone()

    if not batch_info:
        flash(f"Batch '{batch_code}' not found.", "error")
        return redirect(url_for("select_batch"))

    # All batches for dropdown selector
    all_batches = db.execute(
        "SELECT batch_code, batch_name FROM batches ORDER BY start_year DESC, batch_code ASC"
    ).fetchall()

    # Query all students in active batch
    student_rows = db.execute("""
        SELECT 
            uid, name, batch_code, cgpa, internal_avg, exam_avg, backlogs,
            attendance_overall, lms_assignment_pct, aptitude_score, coding_score,
            mock_interview, success_score, academic_subscore, placement_subscore,
            risk_level, segment
        FROM students
        WHERE batch_code = ?
        ORDER BY uid ASC;
    """, (batch_code,)).fetchall()

    students = []
    for r in student_rows:
        item = dict(r)
        parts = item["name"].split()
        item["initials"] = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()
        students.append(item)

    # Fetch Data Quality Report entries
    dq_rows = db.execute("""
        SELECT id, issue_type, description, count, timestamp
        FROM data_quality_report
        ORDER BY id DESC;
    """).fetchall()

    dq_reports = [dict(r) for r in dq_rows]
    total_fixes = sum(r["count"] for r in dq_reports)

    # Breakdown by category
    dq_summary = {
        "total_fixes": total_fixes,
        "uid_fixes": sum(r["count"] for r in dq_reports if "UID" in r["issue_type"]),
        "dup_fixes": sum(r["count"] for r in dq_reports if "Duplicate" in r["issue_type"]),
        "missing_fixes": sum(r["count"] for r in dq_reports if "Missing" in r["issue_type"]),
        "clamp_fixes": sum(r["count"] for r in dq_reports if "Range" in r["issue_type"] or "Clamp" in r["issue_type"]),
    }

    # Fetch Recent Audit Logs
    audit_rows = db.execute("""
        SELECT id, username, role, action, target_uid, details, timestamp
        FROM audit_log
        ORDER BY id DESC
        LIMIT 60;
    """).fetchall()

    audit_logs = []
    for r in audit_rows:
        item = dict(r)
        try:
            item["details_parsed"] = json.loads(item["details"])
        except Exception:
            item["details_parsed"] = item["details"]
        audit_logs.append(item)

    is_admin = (session.get("role") == "Admin")
    user_role = session.get("role", "Faculty")
    confirmed = (request.args.get("confirmed", "0") == "1")

    return render_template(
        "data_management.html",
        batch=batch_info,
        batches=all_batches,
        students=students,
        data_quality_reports=dq_reports,
        data_quality_summary=dq_summary,
        audit_logs=audit_logs,
        is_admin=is_admin,
        user_role=user_role,
        confirmed=confirmed
    )


@app.route("/upload-csv", methods=["POST"])
@app.route("/api/upload-csv", methods=["POST"])
@login_required
def upload_csv():
    """
    POST /upload-csv or POST /api/upload-csv
    Ingests a student CSV file through the automated cleaning pipeline:
      1. UID normalization (removes whitespace, capitalizes)
      2. Duplicate dropping
      3. Missing value median imputation
      4. Numerical clamping to domain ranges
      5. Type enforcement
      6. Upsert into database
      7. Dynamic score recalculation
      8. Quality issue logging & audit logging
    Only Admin staff may commit modifications; Faculty requests are rejected with 403.
    """
    if session.get("role") != "Admin":
        if is_api_request():
            return jsonify({"success": False, "error": "Forbidden: Only Administrators may upload CSV data."}), 403
        flash("Access denied: Only Administrators can upload data files.", "error")
        return redirect(url_for("data_management_view"))

    file = request.files.get("csv_file") or request.files.get("file")
    if not file or not file.filename:
        if is_api_request():
            return jsonify({"success": False, "error": "Please select a valid CSV file to upload."}), 400
        flash("Please select a valid CSV file to upload.", "error")
        return redirect(url_for("data_management_view"))

    if not file.filename.lower().endswith(".csv"):
        if is_api_request():
            return jsonify({"success": False, "error": "Invalid file format. Only .csv files are supported."}), 400
        flash("Invalid file format: Only .csv files are accepted.", "error")
        return redirect(url_for("data_management_view"))

    db = get_db()
    cursor = db.cursor()

    try:
        content = file.read().decode("utf-8", errors="replace")
        df = pd.read_csv(io.StringIO(content))

        if df.empty:
            if is_api_request():
                return jsonify({"success": False, "error": "The uploaded CSV file is empty."}), 400
            flash("The uploaded CSV file is empty.", "error")
            return redirect(url_for("data_management_view"))

        # Normalize column headers
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

        if "uid" not in df.columns:
            if is_api_request():
                return jsonify({"success": False, "error": "CSV must contain a 'uid' column."}), 400
            flash("Uploaded CSV missing required 'uid' column.", "error")
            return redirect(url_for("data_management_view"))

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        active_batch = get_active_batch_code()

        # Step 1: UID Normalization
        orig_uids = df["uid"].astype(str)
        clean_uids = orig_uids.str.replace(" ", "", regex=False).str.upper()
        uid_fixes = int((orig_uids != clean_uids).sum())
        df["uid"] = clean_uids

        # Step 2: Remove Duplicates
        num_duplicates = int(df.duplicated(subset=["uid"]).sum())
        if num_duplicates > 0:
            df = df.drop_duplicates(subset=["uid"], keep="last").reset_index(drop=True)

        # Step 3 & 4: Range clamping and missing imputation
        clamped_count = 0
        imputed_count = 0

        for col, (min_val, max_val, expected_type, _) in FIELD_RULES.items():
            if col in df.columns:
                missing_mask = df[col].isna()
                num_missing = int(missing_mask.sum())
                if num_missing > 0:
                    imputed_count += num_missing
                    median_val = df[col].median()
                    if pd.isna(median_val):
                        median_val = (min_val + max_val) / 2.0
                    df[col] = df[col].fillna(median_val)

                out_mask = (df[col] < min_val) | (df[col] > max_val)
                num_out = int(out_mask.sum())
                if num_out > 0:
                    clamped_count += num_out
                    df[col] = df[col].clip(min_val, max_val)

                if expected_type is int:
                    df[col] = df[col].round().astype(int)
                else:
                    df[col] = df[col].astype(float).round(2)

        # Record fixes into data_quality_report
        if uid_fixes > 0:
            cursor.execute("""
                INSERT INTO data_quality_report (issue_type, description, count, timestamp)
                VALUES (?, ?, ?, ?);
            """, ("UID Normalization", f"Standardized casing and spacing in uploaded {file.filename}", uid_fixes, now_iso))

        if num_duplicates > 0:
            cursor.execute("""
                INSERT INTO data_quality_report (issue_type, description, count, timestamp)
                VALUES (?, ?, ?, ?);
            """, ("Duplicate Removal", f"Dropped duplicate records from uploaded {file.filename}", num_duplicates, now_iso))

        if imputed_count > 0:
            cursor.execute("""
                INSERT INTO data_quality_report (issue_type, description, count, timestamp)
                VALUES (?, ?, ?, ?);
            """, ("Missing Values", f"Imputed missing numeric values with medians in uploaded {file.filename}", imputed_count, now_iso))

        if clamped_count > 0:
            cursor.execute("""
                INSERT INTO data_quality_report (issue_type, description, count, timestamp)
                VALUES (?, ?, ?, ?);
            """, ("Out-of-Range Clamping", f"Clamped out-of-bounds metrics to boundaries in uploaded {file.filename}", clamped_count, now_iso))

        # Step 5: Upsert into students table
        rows_processed = 0
        new_students_added = 0
        students_updated = 0

        existing_uids = {r["uid"] for r in db.execute("SELECT uid FROM students").fetchall()}

        for _, row in df.iterrows():
            st_uid = str(row["uid"]).strip().upper()
            if not st_uid:
                continue

            rows_processed += 1
            st_batch = str(row.get("batch_code", row.get("batch", active_batch))).strip()
            st_name = str(row.get("name", f"Student {st_uid}")).strip()

            if st_uid in existing_uids:
                students_updated += 1
                upd_cols = []
                upd_vals = []
                for col in FIELD_RULES.keys():
                    if col in df.columns:
                        upd_cols.append(f"{col} = ?")
                        upd_vals.append(row[col])
                if "name" in df.columns:
                    upd_cols.append("name = ?")
                    upd_vals.append(st_name)

                if upd_cols:
                    upd_vals.append(st_uid)
                    cursor.execute(f"UPDATE students SET {', '.join(upd_cols)} WHERE uid = ?", upd_vals)

                if "attendance_overall" in df.columns:
                    cursor.execute("UPDATE attendance_details SET attendance_pct = ? WHERE uid = ?", (row["attendance_overall"], st_uid))
                if "exam_avg" in df.columns:
                    cursor.execute("UPDATE academic_details SET exam_marks = ? WHERE uid = ?", (row["exam_avg"], st_uid))
                if "internal_avg" in df.columns:
                    cursor.execute("UPDATE academic_details SET internal_marks = ? WHERE uid = ?", (row["internal_avg"], st_uid))
            else:
                new_students_added += 1
                cols = ["uid", "name", "batch_code"]
                vals = [st_uid, st_name, st_batch]

                for col, (min_v, max_v, exp_t, _) in FIELD_RULES.items():
                    if col in df.columns:
                        cols.append(col)
                        vals.append(row[col])
                    else:
                        cols.append(col)
                        vals.append(exp_t(round((min_v + max_v) / 2.0)) if exp_t is int else round((min_v + max_v) / 2.0, 2))

                placeholders = ["?"] * len(cols)
                cursor.execute(f"INSERT INTO students ({', '.join(cols)}) VALUES ({', '.join(placeholders)})", vals)

                for subj in ["Mathematics", "Core Subject 1", "Core Subject 2", "Core Subject 3", "Elective 1", "Elective 2"]:
                    cursor.execute("INSERT INTO academic_details (uid, subject, internal_marks, exam_marks) VALUES (?, ?, ?, ?)",
                                   (st_uid, subj, row.get("internal_avg", 25.0), row.get("exam_avg", 35.0)))
                    cursor.execute("INSERT INTO attendance_details (uid, subject, attendance_pct) VALUES (?, ?, ?)",
                                   (st_uid, subj, row.get("attendance_overall", 75.0)))

        db.commit()

        # Step 6: Recalculate scores and indicators across the database
        recalculate_cohort_scores()

        # Step 7: Log audit action
        log_audit_action(
            action="CSV_IMPORT",
            target_uid="BATCH",
            details={
                "filename": file.filename,
                "rows_processed": rows_processed,
                "new_students": new_students_added,
                "updated_students": students_updated,
                "uid_fixes": uid_fixes,
                "duplicates_dropped": num_duplicates,
                "missing_imputed": imputed_count,
                "values_clamped": clamped_count
            }
        )

        msg = f"CSV Ingestion & Cleaning Complete: Processed {rows_processed} records ({new_students_added} added, {students_updated} updated). All scores recalculated."
        if is_api_request():
            return jsonify({
                "success": True,
                "message": msg,
                "rows_processed": rows_processed,
                "new_students": new_students_added,
                "updated_students": students_updated,
                "cleaning_fixes": {
                    "uid_fixes": uid_fixes,
                    "duplicates_dropped": num_duplicates,
                    "missing_imputed": imputed_count,
                    "values_clamped": clamped_count
                }
            })

        flash(msg, "success")
        return redirect(url_for("data_management_view"))

    except Exception as e:
        db.rollback()
        err_msg = f"Failed to ingest CSV: {str(e)}"
        if is_api_request():
            return jsonify({"success": False, "error": err_msg}), 500
        flash(err_msg, "error")
        return redirect(url_for("data_management_view"))


@app.route("/api/data-management/template-csv")
@login_required
def download_template_csv():
    """Provides a sample CSV template with standard student headers."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "uid", "name", "batch_code", "cgpa", "internal_avg", "exam_avg",
        "attendance_overall", "backlogs", "lms_assignment_pct", "aptitude_score",
        "coding_score", "mock_interview"
    ])
    writer.writerow([
        "CSE2023099", "Sample Student", "CSE_2023_27", 8.25, 32.5, 48.0,
        88.5, 0, 92.0, 78.0, 82.5, 80.0
    ])
    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=student_import_template.csv",
            "Content-Type": "text/csv; charset=utf-8"
        }
    )



# ---------------------------------------------------------------------------
# RESTful JSON APIs (Phase 3 Backend Engine)
# ---------------------------------------------------------------------------

# 1. Authentication APIs
# ---------------------------------------------------------------------------
@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """
    POST /api/auth/login
    Accepts JSON: { "username": "admin", "password": "..." }
    Returns authenticated user profile and initializes session.
    """
    data = request.get_json(silent=True) or request.form
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"success": False, "error": "Username and password are required."}), 400

    db = get_db()
    user = db.execute(
        "SELECT id, username, password_hash, role, full_name FROM users WHERE username = ?",
        (username,)
    ).fetchone()

    if user and check_password_hash(user["password_hash"], password):
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]

        # Default batch selection if none active
        default_batch = get_active_batch_code()
        session["batch_code"] = default_batch
        session["last_activity"] = time.time()

        return jsonify({
            "success": True,
            "message": "Login successful.",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "full_name": user["full_name"],
                "active_batch": session["batch_code"]
            }
        })

    return jsonify({"success": False, "error": "Invalid username or password."}), 401


@app.route("/api/auth/logout", methods=["POST", "GET"])
def api_logout():
    """POST /api/auth/logout - Clears user session."""
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully."})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def api_me():
    """GET /api/auth/me - Returns current session identity and active batch."""
    return jsonify({
        "success": True,
        "authenticated": True,
        "user": {
            "user_id": session.get("user_id"),
            "username": session.get("username"),
            "role": session.get("role"),
            "full_name": session.get("full_name"),
            "active_batch": get_active_batch_code()
        }
    })


# 2. Batches APIs
# ---------------------------------------------------------------------------
@app.route("/api/batches", methods=["GET"])
@login_required
def api_batches():
    """
    GET /api/batches
    Returns list of academic cohorts with student counts, average score, and average attendance.
    """
    db = get_db()
    rows = db.execute("""
        SELECT 
            b.id,
            b.batch_code,
            b.batch_name,
            b.department,
            b.start_year,
            b.end_year,
            COUNT(s.uid) AS total_students,
            ROUND(AVG(s.success_score), 1) AS avg_success_score,
            ROUND(AVG(s.attendance_overall), 1) AS avg_attendance,
            SUM(CASE WHEN s.needs_attention = 1 THEN 1 ELSE 0 END) AS attention_count
        FROM batches b
        LEFT JOIN students s ON b.batch_code = s.batch_code
        GROUP BY b.batch_code, b.id, b.batch_name, b.department, b.start_year, b.end_year
        ORDER BY b.start_year DESC, b.batch_name ASC;
    """).fetchall()

    batches = [dict(row) for row in rows]
    return jsonify({
        "success": True,
        "count": len(batches),
        "active_batch": get_active_batch_code(),
        "batches": batches
    })


@app.route("/api/batches/select", methods=["POST"])
@login_required
def api_select_batch():
    """
    POST /api/batches/select
    Body: { "batch_code": "CSE_2023_27" }
    Stores the active batch in the user session.
    """
    data = request.get_json(silent=True) or request.form
    batch_code = str(data.get("batch_code", "")).strip()

    db = get_db()
    batch = db.execute("SELECT batch_code, batch_name FROM batches WHERE batch_code = ?", (batch_code,)).fetchone()
    if not batch:
        return jsonify({"success": False, "error": f"Invalid batch code '{batch_code}'."}), 400

    session["batch_code"] = batch_code
    return jsonify({
        "success": True,
        "message": f"Active batch switched to {batch['batch_name']}.",
        "batch_code": batch_code
    })


# 3. Batch Summary API (Designed for Overview Page)
# ---------------------------------------------------------------------------
@app.route("/api/batch/summary", methods=["GET"])
@login_required
def api_batch_summary():
    """
    GET /api/batch/summary?batch_code=...
    Returns high-level KPI cards and Students Requiring Attention list:
      - Total Students
      - Class Average (Success Score %)
      - Students at Risk / Requiring Attention count
      - Attendance Average %
      - Students Requiring Attention list formatted with:
        * Initials avatar
        * Avg Marks (exam_avg scaled / internal_avg)
        * Attendance %
        * Primary concern (e.g. 'Low attendance', 'Low marks', 'Multiple below threshold')
        * Priority badge ('High', 'Medium')
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    db = get_db()

    # Batch information
    batch_info = db.execute(
        "SELECT batch_code, batch_name, department, start_year, end_year FROM batches WHERE batch_code = ?",
        (batch_code,)
    ).fetchone()

    if not batch_info:
        return jsonify({"success": False, "error": f"Batch '{batch_code}' not found."}), 404

    # KPI Aggregates
    summary_row = db.execute("""
        SELECT 
            COUNT(uid) AS total_students,
            ROUND(AVG(success_score), 1) AS class_average,
            ROUND(AVG(attendance_overall), 1) AS attendance_avg,
            ROUND(AVG((exam_avg / 60.0) * 100.0), 1) AS marks_avg,
            SUM(CASE WHEN needs_attention = 1 THEN 1 ELSE 0 END) AS attention_count
        FROM students
        WHERE batch_code = ?;
    """, (batch_code,)).fetchone()

    # Attention Students query
    attention_rows = db.execute("""
        SELECT 
            uid,
            name,
            batch_code,
            success_score,
            cgpa,
            internal_avg,
            exam_avg,
            backlogs,
            attendance_overall,
            academic_subscore,
            placement_subscore,
            risk_level,
            needs_attention,
            segment,
            top_reasons
        FROM students
        WHERE batch_code = ? AND (needs_attention = 1 OR risk_level = 'High' OR success_score < 50.0)
        ORDER BY success_score ASC, attendance_overall ASC;
    """, (batch_code,)).fetchall()

    attention_list = []
    for s in attention_rows:
        # Construct avatar initials (e.g. Aarav Sharma -> AS)
        parts = s["name"].split()
        initials = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

        # Scaled marks percentage (average of internal % and exam %)
        marks_pct = round(((s["internal_avg"] / 40.0) * 50.0) + ((s["exam_avg"] / 60.0) * 50.0), 1)
        att_pct = round(s["attendance_overall"], 1)

        # Determine concise Primary Concern label (matching design reference)
        if att_pct < 65.0 and marks_pct < 50.0:
            concern = "Multiple below threshold"
        elif att_pct < 65.0:
            concern = "Low attendance"
        elif s["backlogs"] >= 3:
            concern = "Multiple backlogs"
        elif marks_pct < 45.0 or s["cgpa"] < 5.5:
            concern = "Low marks"
        elif s["placement_subscore"] < 40.0:
            concern = "Placement risk"
        else:
            concern = "Academic concern"

        # Priority badge: High or Medium
        priority = "High" if (s["risk_level"] == "High" or marks_pct < 45.0 or att_pct < 60.0 or s["backlogs"] >= 3) else "Medium"

        attention_list.append({
            "uid": s["uid"],
            "name": s["name"],
            "initials": initials,
            "avg_marks": f"{marks_pct}%",
            "attendance": f"{att_pct}%",
            "raw_marks_pct": marks_pct,
            "raw_attendance_pct": att_pct,
            "primary_concern": concern,
            "priority": priority,
            "success_score": s["success_score"],
            "cgpa": s["cgpa"],
            "backlogs": s["backlogs"],
            "segment": s["segment"],
            "action_text": "View Details"
        })

    return jsonify({
        "success": True,
        "batch": dict(batch_info),
        "kpis": {
            "total_students": summary_row["total_students"] or 0,
            "class_average": summary_row["class_average"] or 0.0,
            "attendance_avg": summary_row["attendance_avg"] or 0.0,
            "marks_avg": summary_row["marks_avg"] or 0.0,
            "attention_count": summary_row["attention_count"] or 0,
        },
        "attention_students": attention_list
    })


# 4. Students List API (Search & Filters)
# ---------------------------------------------------------------------------
@app.route("/api/students", methods=["GET"])
@login_required
def api_students_list():
    """
    GET /api/students
    Query parameters:
      - batch_code: filter by batch code (or 'all')
      - search: search substring in uid or name (case-insensitive)
      - risk: 'all', 'high', 'medium', 'low', 'academic', 'placement', 'both', 'attention'
      - segment: specific cohort segment name (or 'all')
      - sort_by: column name (default 'success_score')
      - sort_order: 'asc' or 'desc' (default 'desc')
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    search = request.args.get("search", "").strip()
    risk_filter = request.args.get("risk", "all").strip().lower()
    segment_filter = request.args.get("segment", "all").strip()
    sort_by = request.args.get("sort_by", "success_score").strip()
    sort_order = request.args.get("sort_order", "desc").strip().lower()

    # Allowed sorting columns to prevent SQL injection
    allowed_sort_cols = {
        "uid", "name", "cgpa", "attendance_overall", "success_score",
        "academic_subscore", "placement_subscore", "risk_level", "segment", "backlogs"
    }
    if sort_by not in allowed_sort_cols:
        sort_by = "success_score"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    query = """
        SELECT 
            s.uid,
            s.name,
            s.batch_code,
            b.batch_name,
            s.cgpa,
            s.internal_avg,
            s.exam_avg,
            s.backlogs,
            s.attendance_overall,
            s.success_score,
            s.academic_subscore,
            s.placement_subscore,
            s.risk_level,
            s.needs_attention,
            s.risk_academic,
            s.risk_placement,
            s.risk_flag,
            s.segment
        FROM students s
        LEFT JOIN batches b ON s.batch_code = b.batch_code
        WHERE 1=1
    """
    params: List[Any] = []

    if batch_code and batch_code.lower() != "all":
        query += " AND s.batch_code = ?"
        params.append(batch_code)

    if search:
        query += " AND (s.uid LIKE ? OR s.name LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term])

    # Risk filtering
    if risk_filter == "high":
        query += " AND s.risk_level = 'High'"
    elif risk_filter == "medium":
        query += " AND s.risk_level = 'Medium'"
    elif risk_filter == "low":
        query += " AND s.risk_level = 'Low'"
    elif risk_filter == "attention":
        query += " AND s.needs_attention = 1"
    elif risk_filter == "academic":
        query += " AND s.risk_academic = 1"
    elif risk_filter == "placement":
        query += " AND s.risk_placement = 1"
    elif risk_filter == "both":
        query += " AND s.risk_academic = 1 AND s.risk_placement = 1"

    # Segment filtering
    if segment_filter and segment_filter.lower() != "all":
        query += " AND s.segment = ?"
        params.append(segment_filter)

    query += f" ORDER BY s.{sort_by} {sort_order.upper()};"

    db = get_db()
    rows = db.execute(query, params).fetchall()

    students = []
    for r in rows:
        parts = r["name"].split()
        initials = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()
        item = dict(r)
        item["initials"] = initials
        students.append(item)

    return jsonify({
        "success": True,
        "count": len(students),
        "students": students
    })


# 5. Student Detail API (All 7 Sources + Explainability)
# ---------------------------------------------------------------------------
@app.route("/api/students/<uid>", methods=["GET"])
@login_required
def api_student_detail(uid: str):
    """
    GET /api/students/<uid>
    Returns comprehensive profile and all 7 data sources:
      1. Academic performance & subject breakdown
      2. Attendance & subject breakdown
      3. LMS engagement metrics
      4. Extracurricular activities
      5. Placement readiness & assessments
      6. Technical and soft skills assessment
      7. Feedback and campus experience
      + Success Score breakdown across 8 indicators vs batch averages
      + Top negative contributors & targeted actionable intervention playbook
    """
    norm_uid = uid.strip().upper()
    db = get_db()

    student_row = db.execute("""
        SELECT s.*, b.batch_name, b.department, b.start_year, b.end_year
        FROM students s
        LEFT JOIN batches b ON s.batch_code = b.batch_code
        WHERE s.uid = ?;
    """, (norm_uid,)).fetchone()

    if not student_row:
        return jsonify({"success": False, "error": f"Student with UID '{norm_uid}' not found."}), 404

    student = dict(student_row)

    # Detailed subject academic marks
    academic_subjects = db.execute("""
        SELECT subject, internal_marks, exam_marks,
               ROUND(internal_marks + exam_marks, 1) AS total_marks
        FROM academic_details
        WHERE uid = ?
        ORDER BY subject ASC;
    """, (norm_uid,)).fetchall()

    # Detailed subject attendance
    attendance_subjects = db.execute("""
        SELECT subject, attendance_pct
        FROM attendance_details
        WHERE uid = ?
        ORDER BY subject ASC;
    """, (norm_uid,)).fetchall()

    # Parse explainability reasons and actions
    try:
        top_reasons = json.loads(student.get("top_reasons") or "[]")
    except Exception:
        top_reasons = []

    try:
        top_actions = json.loads(student.get("top_actions") or "[]")
    except Exception:
        top_actions = []

    # Compute batch averages for indicator contribution comparison
    batch_averages_row = db.execute("""
        SELECT 
            ROUND(AVG(cgpa), 2) AS avg_cgpa,
            ROUND(AVG((exam_avg / 60.0) * 100.0), 1) AS avg_examinations,
            ROUND(AVG((internal_avg / 40.0) * 100.0), 1) AS avg_internal,
            ROUND(AVG(attendance_overall), 1) AS avg_attendance,
            ROUND(AVG(lms_assignment_pct), 1) AS avg_lms,
            ROUND(AVG((aptitude_score + coding_score + mock_interview) / 3.0), 1) AS avg_placement,
            ROUND(AVG((python_score + sql_score + problem_solving + skill_communication + teamwork + leadership) / 6.0), 1) AS avg_skills,
            ROUND(AVG(student_satisfaction), 1) AS avg_feedback
        FROM students
        WHERE batch_code = ?;
    """, (student["batch_code"],)).fetchone()

    # Assemble structured 7 data sources
    seven_sources = {
        "academic": {
            "title": "Academic Performance",
            "cgpa": student["cgpa"],
            "internal_avg": student["internal_avg"],
            "exam_avg": student["exam_avg"],
            "backlogs": student["backlogs"],
            "subjects": [dict(row) for row in academic_subjects],
        },
        "attendance": {
            "title": "Attendance Tracking",
            "overall_pct": student["attendance_overall"],
            "subject_avg_pct": student["attendance_avg_subject"],
            "subjects": [dict(row) for row in attendance_subjects],
        },
        "lms": {
            "title": "Learning Management System (LMS)",
            "login_frequency": student["lms_login_freq"],
            "assignment_completion_pct": student["lms_assignment_pct"],
            "resources_downloaded": student["lms_resources"],
            "forum_posts": student["lms_forum_posts"],
        },
        "engagement": {
            "title": "Extracurricular Engagement",
            "events_attended": student["events_attended"],
            "clubs_joined": student["clubs_joined"],
            "hackathons": student["hackathons"],
            "certifications": student["certifications"],
            "workshops": student["workshops"],
        },
        "placement": {
            "title": "Placement Readiness",
            "aptitude_score": student["aptitude_score"],
            "coding_score": student["coding_score"],
            "mock_interview": student["mock_interview"],
            "communication_score": student["communication_score"],
            "drives_attended": student["drives_attended"],
            "offers_received": student["offers_received"],
        },
        "skills": {
            "title": "Skills Assessment",
            "python_score": student["python_score"],
            "sql_score": student["sql_score"],
            "problem_solving": student["problem_solving"],
            "communication": student["skill_communication"],
            "teamwork": student["teamwork"],
            "leadership": student["leadership"],
        },
        "feedback": {
            "title": "Student & Faculty Feedback",
            "student_satisfaction": student["student_satisfaction"],
            "faculty_feedback": student["faculty_feedback"],
            "course_rating": student["course_rating"],
            "infrastructure_rating": student["infrastructure_rating"],
            "overall_experience": student["overall_experience"],
        }
    }

    # Radar/Breakdown Indicators
    norm_exam = round((student["exam_avg"] / 60.0) * 100.0, 1)
    norm_internal = round((student["internal_avg"] / 40.0) * 100.0, 1)
    norm_att = round(student["attendance_overall"], 1)
    norm_lms = round(student["lms_assignment_pct"], 1)
    norm_place = round((student["aptitude_score"] + student["coding_score"] + student["mock_interview"]) / 3.0, 1)
    norm_skills = round((student["python_score"] + student["sql_score"] + student["problem_solving"] +
                         student["skill_communication"] + student["teamwork"] + student["leadership"]) / 6.0, 1)
    total_acts = student["events_attended"] + student["clubs_joined"] + student["hackathons"] + student["certifications"] + student["workshops"]
    norm_extra = round(min(100.0, (total_acts / 30.0) * 100.0), 1)
    fb_avg = (student["student_satisfaction"] + student["faculty_feedback"] + student["course_rating"] + student["infrastructure_rating"] + student["overall_experience"]) / 5.0
    norm_fb = round((fb_avg / 5.0) * 100.0, 1)

    indicators_breakdown = [
        {"name": "Examinations", "weight": 15, "value": norm_exam, "batch_avg": batch_averages_row["avg_examinations"] if batch_averages_row else 50.0},
        {"name": "Internal assessments", "weight": 15, "value": norm_internal, "batch_avg": batch_averages_row["avg_internal"] if batch_averages_row else 50.0},
        {"name": "Attendance", "weight": 15, "value": norm_att, "batch_avg": batch_averages_row["avg_attendance"] if batch_averages_row else 65.0},
        {"name": "LMS activity", "weight": 10, "value": norm_lms, "batch_avg": batch_averages_row["avg_lms"] if batch_averages_row else 50.0},
        {"name": "Placement participation & tests", "weight": 20, "value": norm_place, "batch_avg": batch_averages_row["avg_placement"] if batch_averages_row else 50.0},
        {"name": "Skills", "weight": 10, "value": norm_skills, "batch_avg": batch_averages_row["avg_skills"] if batch_averages_row else 50.0},
        {"name": "Extracurricular", "weight": 8, "value": norm_extra, "batch_avg": 45.0},
        {"name": "Feedback", "weight": 7, "value": norm_fb, "batch_avg": 60.0},
    ]

    parts = student["name"].split()
    initials = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    return jsonify({
        "success": True,
        "student": {
            "uid": student["uid"],
            "name": student["name"],
            "initials": initials,
            "batch_code": student["batch_code"],
            "batch_name": student.get("batch_name"),
            "department": student.get("department"),
            "success_score": student["success_score"],
            "academic_subscore": student["academic_subscore"],
            "placement_subscore": student["placement_subscore"],
            "risk_level": student["risk_level"],
            "needs_attention": student["needs_attention"],
            "risk_flag": student["risk_flag"],
            "risk_academic": student["risk_academic"],
            "risk_placement": student["risk_placement"],
            "segment": student["segment"],
            "top_reasons": top_reasons,
            "top_actions": top_actions,
            "indicators_breakdown": indicators_breakdown,
            "sources": seven_sources
        }
    })


# 6. At-Risk & Segments API
# ---------------------------------------------------------------------------
@app.route("/api/at-risk", methods=["GET"])
@login_required
def api_at_risk():
    """
    GET /api/at-risk?batch_code=...
    Returns partitioned cohort segments and risk analysis lists:
      - Academic Risk list (CGPA < 6.0 OR backlogs > 2 OR attendance < 65% OR academic_subscore < 50)
      - Placement Risk list (placement tests < 40 OR placement_subscore < 50)
      - Dual Risk list (students facing both)
      - Segment counts across all 6 segments
      - Student rosters grouped by segment
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    db = get_db()

    # Query all students in batch
    rows = db.execute("""
        SELECT 
            uid, name, batch_code, cgpa, attendance_overall, backlogs,
            success_score, academic_subscore, placement_subscore,
            risk_level, needs_attention, risk_academic, risk_placement, risk_flag,
            segment, top_reasons, top_actions
        FROM students
        WHERE batch_code = ?
        ORDER BY success_score ASC;
    """, (batch_code,)).fetchall()

    academic_risk_list = []
    placement_risk_list = []
    both_risk_list = []
    segments_map: Dict[str, List[Dict[str, Any]]] = {
        "High Performers": [],
        "Strong Academics but Low Placement Readiness": [],
        "Placement Ready but Weak Academics": [],
        "Disengaged": [],
        "Needs Overall Support": [],
        "Steady": [],
    }

    for r in rows:
        item = dict(r)
        parts = item["name"].split()
        item["initials"] = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

        try:
            item["reasons"] = json.loads(item["top_reasons"] or "[]")
        except Exception:
            item["reasons"] = []

        try:
            item["actions"] = json.loads(item["top_actions"] or "[]")
        except Exception:
            item["actions"] = []

        # Categorize into risk lists
        if item["risk_academic"] == 1:
            academic_risk_list.append(item)
        if item["risk_placement"] == 1:
            placement_risk_list.append(item)
        if item["risk_academic"] == 1 and item["risk_placement"] == 1:
            both_risk_list.append(item)

        # Categorize into segment groups
        seg_name = item.get("segment", "Steady")
        if seg_name in segments_map:
            segments_map[seg_name].append(item)
        else:
            segments_map.setdefault(seg_name, []).append(item)

    segment_counts = {seg: len(students) for seg, students in segments_map.items()}

    return jsonify({
        "success": True,
        "batch_code": batch_code,
        "total_students": len(rows),
        "counts": {
            "academic_risk_count": len(academic_risk_list),
            "placement_risk_count": len(placement_risk_list),
            "both_risk_count": len(both_risk_list),
            "segment_counts": segment_counts,
        },
        "academic_risk": academic_risk_list,
        "placement_risk": placement_risk_list,
        "both_risk": both_risk_list,
        "segments": segments_map
    })


# 7. Trends API (Charts & Analytics)
# ---------------------------------------------------------------------------
@app.route("/api/trends", methods=["GET"])
@login_required
def api_trends():
    """
    GET /api/trends?batch_code=...
    Returns analytical distributions suitable for Chart.js:
      - Score Distribution Histogram (bins: <40, 40-49, 50-59, 60-69, 70-79, 80+)
      - Attendance Distribution (bins: <50%, 50-64%, 65-74%, 75-84%, 85-100%)
      - Subject-wise Attendance Averages (from attendance_details)
      - Subject-wise Marks Averages (from academic_details: internal vs exam)
      - Cohort Skills Radar Averages (Python, SQL, Problem Solving, Communication, Teamwork, Leadership)
    """
    batch_code = request.args.get("batch_code", get_active_batch_code()).strip()
    db = get_db()

    students = db.execute("""
        SELECT uid, success_score, attendance_overall, cgpa,
               python_score, sql_score, problem_solving,
               skill_communication, teamwork, leadership
        FROM students
        WHERE batch_code = ?;
    """, (batch_code,)).fetchall()

    if not students:
        return jsonify({"success": False, "error": f"No data found for batch '{batch_code}'."}), 404

    # 1. Score Distribution Bins
    score_bins = {
        "< 40": 0,
        "40 - 49": 0,
        "50 - 59": 0,
        "60 - 69": 0,
        "70 - 79": 0,
        "80+": 0
    }
    for s in students:
        score = s["success_score"] or 0.0
        if score < 40:
            score_bins["< 40"] += 1
        elif score < 50:
            score_bins["40 - 49"] += 1
        elif score < 60:
            score_bins["50 - 59"] += 1
        elif score < 70:
            score_bins["60 - 69"] += 1
        elif score < 80:
            score_bins["70 - 79"] += 1
        else:
            score_bins["80+"] += 1

    # 2. Attendance Distribution Bins
    attendance_bins = {
        "< 50%": 0,
        "50% - 64%": 0,
        "65% - 74%": 0,
        "75% - 84%": 0,
        "85% - 100%": 0
    }
    for s in students:
        att = s["attendance_overall"] or 0.0
        if att < 50:
            attendance_bins["< 50%"] += 1
        elif att < 65:
            attendance_bins["50% - 64%"] += 1
        elif att < 75:
            attendance_bins["65% - 74%"] += 1
        elif att < 85:
            attendance_bins["75% - 84%"] += 1
        else:
            attendance_bins["85% - 100%"] += 1

    # 3. Subject-wise Attendance Averages
    subject_attendance_rows = db.execute("""
        SELECT ad.subject, ROUND(AVG(ad.attendance_pct), 1) AS avg_attendance
        FROM attendance_details ad
        JOIN students s ON ad.uid = s.uid
        WHERE s.batch_code = ?
        GROUP BY ad.subject
        ORDER BY ad.subject ASC;
    """, (batch_code,)).fetchall()

    # 4. Subject-wise Marks Averages
    subject_marks_rows = db.execute("""
        SELECT 
            acd.subject,
            ROUND(AVG(acd.internal_marks), 1) AS avg_internal,
            ROUND(AVG(acd.exam_marks), 1) AS avg_exam,
            ROUND(AVG(acd.internal_marks + acd.exam_marks), 1) AS avg_total
        FROM academic_details acd
        JOIN students s ON acd.uid = s.uid
        WHERE s.batch_code = ?
        GROUP BY acd.subject
        ORDER BY acd.subject ASC;
    """, (batch_code,)).fetchall()

    # 5. Cohort Skills Radar Averages
    skills_avg_row = db.execute("""
        SELECT 
            ROUND(AVG(python_score), 1) AS python,
            ROUND(AVG(sql_score), 1) AS sql,
            ROUND(AVG(problem_solving), 1) AS problem_solving,
            ROUND(AVG(skill_communication), 1) AS communication,
            ROUND(AVG(teamwork), 1) AS teamwork,
            ROUND(AVG(leadership), 1) AS leadership
        FROM students
        WHERE batch_code = ?;
    """, (batch_code,)).fetchone()

    # 1. Standard Risk Score Bands (Low / Medium / High)
    low_band_count = sum(1 for s in students if (s["success_score"] or 0.0) < 50.0)
    med_band_count = sum(1 for s in students if 50.0 <= (s["success_score"] or 0.0) < 65.0)
    high_band_count = sum(1 for s in students if (s["success_score"] or 0.0) >= 65.0)

    score_bands = {
        "labels": ["Low Band (< 50)", "Medium Band (50 - 64)", "High Band (65+)"],
        "data": [low_band_count, med_band_count, high_band_count],
        "colors": ["#ef4444", "#f59e0b", "#10b981"]
    }

    # Subject attendance labels and values
    sub_att_labels = [r["subject"] for r in subject_attendance_rows]
    sub_att_values = [r["avg_attendance"] for r in subject_attendance_rows]

    return jsonify({
        "success": True,
        "batch_code": batch_code,
        "score_bands": score_bands,
        "score_distribution": {
            "labels": list(score_bins.keys()),
            "data": list(score_bins.values())
        },
        "attendance_distribution": {
            "labels": list(attendance_bins.keys()),
            "data": list(attendance_bins.values())
        },
        "attendance_trend": {
            "labels": sub_att_labels,
            "data": sub_att_values
        },
        "subject_attendance": [dict(r) for r in subject_attendance_rows],
        "subject_marks": [dict(r) for r in subject_marks_rows],
        "skills_radar": dict(skills_avg_row) if skills_avg_row else {}
    })


# 8. Data Quality Report API
# ---------------------------------------------------------------------------
@app.route("/api/data-quality", methods=["GET"])
@login_required
def api_data_quality():
    """
    GET /api/data-quality
    Returns data cleaning anomaly reports and fix statistics produced by clean_and_merge.py.
    """
    db = get_db()
    rows = db.execute("""
        SELECT id, issue_type, description, count, timestamp
        FROM data_quality_report
        ORDER BY id ASC;
    """).fetchall()

    reports = [dict(r) for r in rows]

    # Aggregate summaries
    total_fixes = sum(r["count"] for r in reports)
    type_counts = {}
    for r in reports:
        type_counts[r["issue_type"]] = type_counts.get(r["issue_type"], 0) + r["count"]

    return jsonify({
        "success": True,
        "total_fixes_applied": total_fixes,
        "fix_types": type_counts,
        "report_count": len(reports),
        "audit_entries": reports
    })


# 9. Data Management: Add Student (Admin Only)
# ---------------------------------------------------------------------------
@app.route("/api/students", methods=["POST"])
@admin_required
def api_add_student():
    """
    POST /api/students
    Admin only: Creates a new student record.
    1. Validates inputs (presence, boundaries, no duplicate UID).
    2. Inserts student master record.
    3. Populates subject breakdown tables (academic_details & attendance_details).
    4. Automatically recalculates scores via scoring engine.
    5. Records action in audit_log.
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    is_valid, err_msg, cleaned = validate_student_inputs(data, is_new=True)

    if not is_valid:
        return jsonify({"success": False, "error": err_msg}), 400

    uid = cleaned["uid"]
    batch_code = cleaned["batch_code"]
    name = cleaned["name"]

    db = get_db()

    # Check for duplicate UID
    existing = db.execute("SELECT uid FROM students WHERE uid = ?", (uid,)).fetchone()
    if existing:
        return jsonify({"success": False, "error": f"A student with UID '{uid}' already exists in the system."}), 409

    # Verify batch code exists
    batch = db.execute("SELECT batch_code FROM batches WHERE batch_code = ?", (batch_code,)).fetchone()
    if not batch:
        return jsonify({"success": False, "error": f"Specified batch code '{batch_code}' does not exist."}), 400

    # Build INSERT query dynamically for all validated fields
    columns = list(cleaned.keys())
    placeholders = ["?"] * len(columns)
    values = [cleaned[col] for col in columns]

    insert_sql = f"INSERT INTO students ({', '.join(columns)}) VALUES ({', '.join(placeholders)});"

    try:
        cursor = db.cursor()
        cursor.execute(insert_sql, values)

        # Populate standard subjects in academic_details and attendance_details
        standard_subjects = [
            "Mathematics", "Core Subject 1", "Core Subject 2",
            "Core Subject 3", "Elective 1", "Elective 2"
        ]
        internal_mark = round(cleaned.get("internal_avg", 25.0), 1)
        exam_mark = round(cleaned.get("exam_avg", 35.0), 1)
        att_pct = round(cleaned.get("attendance_overall", 75.0), 1)

        for subj in standard_subjects:
            cursor.execute("""
                INSERT INTO academic_details (uid, subject, internal_marks, exam_marks)
                VALUES (?, ?, ?, ?);
            """, (uid, subj, internal_mark, exam_mark))

            cursor.execute("""
                INSERT INTO attendance_details (uid, subject, attendance_pct)
                VALUES (?, ?, ?);
            """, (uid, subj, att_pct))

        db.commit()

        # Recalculate scores automatically across the cohort
        recalculate_cohort_scores()

        # Write audit log entry
        log_audit_action(
            action="ADD_STUDENT",
            target_uid=uid,
            details={
                "message": f"Created new student record for {name} ({uid})",
                "batch_code": batch_code,
                "initial_metrics": cleaned
            }
        )

        # Retrieve freshly recalculated student record
        new_student = db.execute("SELECT * FROM students WHERE uid = ?", (uid,)).fetchone()

        return jsonify({
            "success": True,
            "message": f"Student {name} ({uid}) added successfully.",
            "student": dict(new_student)
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": f"Failed to add student: {str(e)}"}), 500


# 10. Data Management: Edit Student (Admin Only)
# ---------------------------------------------------------------------------
@app.route("/api/students/<uid>", methods=["PUT", "POST"])
@admin_required
def api_edit_student(uid: str):
    """
    PUT /api/students/<uid> or POST /api/students/<uid>/edit
    Admin only: Modifies an existing student's data.
    1. Validates input values against allowed boundary ranges.
    2. Identifies field-level changes (before vs. after diff).
    3. Updates student row.
    4. Automatically recalculates all scores and explainability.
    5. Records change history in audit_log.
    """
    norm_uid = uid.strip().upper()
    data = request.get_json(silent=True) or request.form.to_dict()

    db = get_db()
    existing_row = db.execute("SELECT * FROM students WHERE uid = ?", (norm_uid,)).fetchone()
    if not existing_row:
        return jsonify({"success": False, "error": f"Student with UID '{norm_uid}' does not exist."}), 404

    is_valid, err_msg, cleaned = validate_student_inputs(data, is_new=False)
    if not is_valid:
        return jsonify({"success": False, "error": err_msg}), 400

    # Calculate diff between existing and new values
    existing_dict = dict(existing_row)
    changes = []
    update_fields = []
    update_values = []

    for col, new_val in cleaned.items():
        old_val = existing_dict.get(col)
        # Check if values actually differ (handling float rounding)
        is_different = False
        if isinstance(new_val, float) and isinstance(old_val, (int, float)):
            is_different = abs(new_val - float(old_val)) > 1e-4
        else:
            is_different = (new_val != old_val)

        if is_different:
            changes.append({
                "field": col,
                "old": old_val,
                "new": new_val
            })
            update_fields.append(f"{col} = ?")
            update_values.append(new_val)

    if not update_fields:
        return jsonify({
            "success": True,
            "message": "No changes detected.",
            "changes_applied": 0,
            "student": existing_dict
        })

    update_values.append(norm_uid)
    update_sql = f"UPDATE students SET {', '.join(update_fields)} WHERE uid = ?;"

    try:
        cursor = db.cursor()
        cursor.execute(update_sql, update_values)

        # If attendance_overall was updated, update subject attendance records as well
        if "attendance_overall" in cleaned:
            cursor.execute("""
                UPDATE attendance_details
                SET attendance_pct = ?
                WHERE uid = ?;
            """, (cleaned["attendance_overall"], norm_uid))

        # If exam_avg or internal_avg were updated, update academic details as well
        if "exam_avg" in cleaned:
            cursor.execute("""
                UPDATE academic_details
                SET exam_marks = ?
                WHERE uid = ?;
            """, (cleaned["exam_avg"], norm_uid))

        if "internal_avg" in cleaned:
            cursor.execute("""
                UPDATE academic_details
                SET internal_marks = ?
                WHERE uid = ?;
            """, (cleaned["internal_avg"], norm_uid))

        db.commit()

        # Recalculate scores automatically across the cohort
        recalculate_cohort_scores()

        # Log changes in audit table
        log_audit_action(
            action="EDIT_STUDENT",
            target_uid=norm_uid,
            details={
                "message": f"Updated {len(changes)} field(s) for student {existing_dict.get('name')} ({norm_uid})",
                "changes": changes
            }
        )

        # Retrieve freshly recalculated student record
        updated_student = db.execute("SELECT * FROM students WHERE uid = ?", (norm_uid,)).fetchone()

        return jsonify({
            "success": True,
            "message": f"Successfully updated student {norm_uid}.",
            "changes_applied": len(changes),
            "changes": changes,
            "student": dict(updated_student)
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": f"Failed to update student: {str(e)}"}), 500


# 11. Audit Logs History API
# ---------------------------------------------------------------------------
@app.route("/api/audit-logs", methods=["GET"])
@login_required
def api_audit_logs():
    """
    GET /api/audit-logs
    Returns complete modification history from the audit_log table.
    """
    db = get_db()
    rows = db.execute("""
        SELECT id, username, role, action, target_uid, details, timestamp
        FROM audit_log
        ORDER BY id DESC
        LIMIT 200;
    """).fetchall()

    logs = []
    for r in rows:
        item = dict(r)
        try:
            item["details_parsed"] = json.loads(item["details"])
        except Exception:
            item["details_parsed"] = item["details"]
        logs.append(item)

    return jsonify({
        "success": True,
        "count": len(logs),
        "audit_logs": logs
    })


# ---------------------------------------------------------------------------
# Database File Verification on Startup
# ---------------------------------------------------------------------------
def check_database_exists():
    """Verifies that SQLite database is present and initializes audit logging."""
    if not os.path.exists(DATABASE_PATH):
        print("\n" + "=" * 70)
        print("[WARNING] SQLite database not found at:")
        print(f"  --> {DATABASE_PATH}")
        print("Please run the data preparation scripts first:")
        print("  1. python generate_data.py")
        print("  2. python clean_and_merge.py")
        print("  3. python scoring.py")
        print("=" * 70 + "\n")
    else:
        init_audit_table()
        print(f"[INFO] Connected to campus database: {DATABASE_PATH}")
        print("[INFO] Audit log table initialized and ready.")


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    check_database_exists()
    app.run(debug=True, port=5000)
