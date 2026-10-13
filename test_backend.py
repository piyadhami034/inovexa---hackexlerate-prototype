"""
=============================================================================
Smart Campus Analytics - Phase 3 Backend Verification Test Suite
=============================================================================
Automated test script testing:
1. Authentication & Session Security (Reject unauthenticated -> 401)
2. Role-Based Access Control (Faculty cannot add/edit -> 403)
3. Seeded Accounts verification (admin & faculty1)
4. Batch APIs & Batch Summary API (KPI cards + attention student roster)
5. Student Search & Filtering APIs
6. Student Detail API (All 7 data sources, score breakdown, explainability)
7. At-Risk lists & Segment counts API
8. Trends & Distribution API
9. Data Quality Report API
10. Data Management: Add Student (Validation, Duplicate prevention, Auto-recalc, Audit log)
11. Data Management: Edit Student (Validation, Diff tracking, Auto-recalc, Audit log)
12. Audit Logs History API
=============================================================================
"""

import json
import sqlite3
from pathlib import Path
from app import app, init_audit_table

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "campus.db"


def run_tests():
    print("=" * 70)
    print("SMART CAMPUS ANALYTICS: RUNNING PHASE 3 BACKEND TEST SUITE")
    print("=" * 70)

    # Initialize audit table and ensure clean test database state
    init_audit_table()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM students WHERE uid = 'CSE2023999'")
        conn.execute("DELETE FROM academic_details WHERE uid = 'CSE2023999'")
        conn.execute("DELETE FROM attendance_details WHERE uid = 'CSE2023999'")
        conn.commit()
        conn.close()
        import scoring
        df_sync, _ = scoring.load_and_score(DB_PATH)
        scoring.update_database_scores(df_sync, DB_PATH)
    except Exception:
        pass

    client = app.test_client()

    passed_tests = 0
    total_tests = 0

    def assert_test(condition, test_name):
        nonlocal passed_tests, total_tests
        total_tests += 1
        if condition:
            passed_tests += 1
            print(f"  [PASS] {test_name}")
        else:
            print(f"  [FAIL] {test_name}")
            assert condition, f"Test failed: {test_name}"

    # -------------------------------------------------------------------------
    # TEST 1: Unauthenticated Requests Must Be Rejected (HTTP 401)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 1: Unauthenticated API Security (401 Rejection) ---")
    
    protected_endpoints = [
        ("GET", "/api/auth/me"),
        ("GET", "/api/batches"),
        ("GET", "/api/batch/summary"),
        ("GET", "/api/students"),
        ("GET", "/api/students/CSE2023001"),
        ("GET", "/api/at-risk"),
        ("GET", "/api/trends"),
        ("GET", "/api/data-quality"),
        ("POST", "/api/students"),
        ("PUT", "/api/students/CSE2023001"),
        ("GET", "/api/audit-logs"),
    ]

    for method, endpoint in protected_endpoints:
        if method == "GET":
            res = client.get(endpoint)
        elif method == "POST":
            res = client.post(endpoint, json={})
        elif method == "PUT":
            res = client.put(endpoint, json={})

        assert_test(res.status_code == 401, f"Unauthenticated {method} {endpoint} returns 401 Unauthorized")
        data = res.get_json()
        assert_test("error" in data, f"Unauthenticated response contains error message for {endpoint}")

    # Test HTML unauthenticated redirect
    html_res = client.get("/select-batch")
    assert_test(html_res.status_code == 302 and "/login" in html_res.headers.get("Location", ""), "Unauthenticated HTML route redirects to /login")

    # -------------------------------------------------------------------------
    # TEST 2: Seeded Authentication (admin & faculty1)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 2: Seeded Staff Authentication ---")
    
    # Invalid login test
    bad_res = client.post("/api/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert_test(bad_res.status_code == 401, "Invalid password rejected with 401")

    # Faculty login test
    faculty_client = app.test_client()
    fac_res = faculty_client.post("/api/auth/login", json={"username": "faculty1", "password": "faculty123"})
    assert_test(fac_res.status_code == 200, "Faculty1 login returns 200 OK")
    fac_data = fac_res.get_json()
    assert_test(fac_data["user"]["role"] == "Faculty", "Faculty1 has 'Faculty' role")

    # Admin login test
    admin_client = app.test_client()
    adm_res = admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert_test(adm_res.status_code == 200, "Admin login returns 200 OK")
    adm_data = adm_res.get_json()
    assert_test(adm_data["user"]["role"] == "Admin", "Admin has 'Admin' role")

    # Check /api/auth/me for admin
    me_res = admin_client.get("/api/auth/me")
    assert_test(me_res.status_code == 200 and me_res.get_json()["user"]["username"] == "admin", "/api/auth/me reflects active session")

    # -------------------------------------------------------------------------
    # TEST 3: Role-Based Access Control (Only Admin can Add/Edit)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 3: Role Authorization (Faculty Blocked from Add/Edit -> 403) ---")
    
    fac_add = faculty_client.post("/api/students", json={"uid": "HACK2023001", "name": "Hack User", "batch_code": "CSE_2023_27"})
    assert_test(fac_add.status_code == 403, "Faculty cannot POST /api/students (403 Forbidden)")

    fac_edit = faculty_client.put("/api/students/CSE2023001", json={"cgpa": 9.9})
    assert_test(fac_edit.status_code == 403, "Faculty cannot PUT /api/students/<uid> (403 Forbidden)")

    # -------------------------------------------------------------------------
    # TEST 4: Batches APIs
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 4: Batches APIs ---")
    batches_res = admin_client.get("/api/batches")
    assert_test(batches_res.status_code == 200, "GET /api/batches returns 200")
    batches_data = batches_res.get_json()
    assert_test(batches_data["count"] == 3, "Returns 3 batches")
    sample_batch = batches_data["batches"][0]
    assert_test("total_students" in sample_batch and "avg_success_score" in sample_batch, "Batch object contains KPI summary metrics")

    # Switch active batch
    sel_res = admin_client.post("/api/batches/select", json={"batch_code": "CSE_2023_27"})
    assert_test(sel_res.status_code == 200 and sel_res.get_json()["batch_code"] == "CSE_2023_27", "Switching active batch succeeds")

    # -------------------------------------------------------------------------
    # TEST 5: Batch Summary API (Overview Page)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 5: Batch Summary API (Overview KPIs & Attention Roster) ---")
    summary_res = admin_client.get("/api/batch/summary?batch_code=CSE_2023_27")
    assert_test(summary_res.status_code == 200, "GET /api/batch/summary returns 200")
    s_data = summary_res.get_json()
    kpis = s_data["kpis"]
    assert_test(kpis["total_students"] == 60, "Total students in CSE_2023_27 is 60")
    assert_test(kpis["class_average"] > 0, "Class average success score is positive")
    assert_test(kpis["attendance_avg"] > 0, "Attendance average is positive")
    assert_test(kpis["attention_count"] > 0, "Attention count identified")

    att_students = s_data["attention_students"]
    assert_test(len(att_students) > 0, "Attention students list is populated")
    first_att = att_students[0]
    assert_test("initials" in first_att and "avg_marks" in first_att and "attendance" in first_att, "Attention student formatted with initials, avg_marks, and attendance")
    assert_test("primary_concern" in first_att and "priority" in first_att, "Attention student formatted with primary concern and priority badge")
    print(f"      -> Sample Attention Student: {first_att['name']} ({first_att['uid']}) | Concern: {first_att['primary_concern']} | Priority: {first_att['priority']}")

    # -------------------------------------------------------------------------
    # TEST 6: Students List API (Search & Filtering)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 6: Students List API (Search & Filters) ---")
    # All students
    all_stud = admin_client.get("/api/students?batch_code=CSE_2023_27").get_json()
    assert_test(all_stud["count"] == 60, "Querying all students for batch returns 60")

    # Search by UID
    uid_search = admin_client.get("/api/students?batch_code=CSE_2023_27&search=CSE2023001").get_json()
    assert_test(uid_search["count"] == 1 and uid_search["students"][0]["uid"] == "CSE2023001", "Search by UID returns specific student")

    # Search by Name
    first_name = uid_search["students"][0]["name"].split()[0]
    name_search = admin_client.get(f"/api/students?batch_code=CSE_2023_27&search={first_name}").get_json()
    assert_test(name_search["count"] >= 1, f"Search by name substring '{first_name}' finds match")

    # Filter by Risk
    high_risk = admin_client.get("/api/students?batch_code=CSE_2023_27&risk=high").get_json()
    assert_test(all(s["risk_level"] == "High" for s in high_risk["students"]), "Risk filter 'high' returns only High risk students")

    # Filter by Segment
    disengaged = admin_client.get("/api/students?batch_code=CSE_2023_27&segment=Disengaged").get_json()
    assert_test(all(s["segment"] == "Disengaged" for s in disengaged["students"]), "Segment filter returns only requested segment")

    # -------------------------------------------------------------------------
    # TEST 7: Student Detail API (7 Sources & Explainability)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 7: Student Detail API (All 7 Sources + Explainability) ---")
    det_res = admin_client.get("/api/students/CSE2023001")
    assert_test(det_res.status_code == 200, "GET /api/students/CSE2023001 returns 200")
    det_data = det_res.get_json()["student"]
    
    # Verify 7 sources exist
    sources = det_data["sources"]
    expected_sources = ["academic", "attendance", "lms", "engagement", "placement", "skills", "feedback"]
    for src in expected_sources:
        assert_test(src in sources, f"Source '{src}' present in student detail payload")

    # Check academic subjects details
    assert_test(len(sources["academic"]["subjects"]) == 6, "Academic source contains 6 subject breakdown rows")
    # Check attendance subjects details
    assert_test(len(sources["attendance"]["subjects"]) == 6, "Attendance source contains 6 subject breakdown rows")
    # Check explainability
    assert_test(isinstance(det_data["top_reasons"], list) and len(det_data["top_reasons"]) > 0, "Student has top_reasons explainability list")
    assert_test(isinstance(det_data["top_actions"], list) and len(det_data["top_actions"]) > 0, "Student has top_actions intervention list")
    assert_test(len(det_data["indicators_breakdown"]) == 8, "Indicators breakdown contains all 8 normalized indicators")

    # -------------------------------------------------------------------------
    # TEST 8: At-Risk & Segments API
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 8: At-Risk & Segments API ---")
    atrisk_res = admin_client.get("/api/at-risk?batch_code=CSE_2023_27")
    assert_test(atrisk_res.status_code == 200, "GET /api/at-risk returns 200")
    atrisk_data = atrisk_res.get_json()
    assert_test("academic_risk" in atrisk_data and "placement_risk" in atrisk_data, "At-Risk response contains academic and placement risk lists")
    assert_test("segment_counts" in atrisk_data["counts"], "At-Risk response contains segment counts")
    assert_test("High Performers" in atrisk_data["counts"]["segment_counts"], "Segment counts include 'High Performers'")
    assert_test("Disengaged" in atrisk_data["counts"]["segment_counts"], "Segment counts include 'Disengaged'")

    # -------------------------------------------------------------------------
    # TEST 9: Trends API
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 9: Trends API ---")
    trends_res = admin_client.get("/api/trends?batch_code=CSE_2023_27")
    assert_test(trends_res.status_code == 200, "GET /api/trends returns 200")
    trends_data = trends_res.get_json()
    assert_test("score_distribution" in trends_data and len(trends_data["score_distribution"]["labels"]) > 0, "Trends contains score distribution histogram")
    assert_test("attendance_distribution" in trends_data, "Trends contains attendance distribution")
    assert_test(len(trends_data["subject_attendance"]) == 6, "Trends contains 6 subject attendance averages")
    assert_test(len(trends_data["subject_marks"]) == 6, "Trends contains 6 subject marks averages")
    assert_test("python" in trends_data["skills_radar"], "Trends contains cohort skills radar averages")

    # -------------------------------------------------------------------------
    # TEST 10: Data Quality Report API
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 10: Data Quality Report API ---")
    dq_res = admin_client.get("/api/data-quality")
    assert_test(dq_res.status_code == 200, "GET /api/data-quality returns 200")
    dq_data = dq_res.get_json()
    assert_test(dq_data["total_fixes_applied"] > 0, "Total fixes applied is greater than 0")
    assert_test(len(dq_data["audit_entries"]) > 0, "Audit entries table is populated")

    # -------------------------------------------------------------------------
    # TEST 11: Data Management - Add Student (Admin Only)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 11: Add Student Validation, Recalculation & Audit ---")
    new_uid = "CSE2023999"
    
    # Cleanup previous run if exists
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM students WHERE uid = ?", (new_uid,))
    conn.execute("DELETE FROM academic_details WHERE uid = ?", (new_uid,))
    conn.execute("DELETE FROM attendance_details WHERE uid = ?", (new_uid,))
    conn.commit()
    conn.close()

    # Out-of-bounds validation test (CGPA 15.0)
    invalid_add = admin_client.post("/api/students", json={
        "uid": new_uid,
        "name": "Test Student",
        "batch_code": "CSE_2023_27",
        "cgpa": 15.0  # Invalid! Max is 10.0
    })
    assert_test(invalid_add.status_code == 400, "Out-of-bounds CGPA 15.0 rejected with 400 Bad Request")

    # Valid add student test
    valid_add = admin_client.post("/api/students", json={
        "uid": new_uid,
        "name": "Rohan Deshmukh",
        "batch_code": "CSE_2023_27",
        "cgpa": 8.7,
        "internal_avg": 34.0,
        "exam_avg": 52.0,
        "backlogs": 0,
        "attendance_overall": 92.5,
        "aptitude_score": 85.0,
        "coding_score": 90.0,
        "mock_interview": 88.0,
        "python_score": 95.0,
        "sql_score": 89.0,
        "problem_solving": 92.0,
        "events_attended": 5,
        "clubs_joined": 2,
        "hackathons": 3,
        "certifications": 4,
        "workshops": 3,
        "student_satisfaction": 4.5
    })
    assert_test(valid_add.status_code == 201, "Valid student creation returns 201 Created")
    created_stud = valid_add.get_json()["student"]
    assert_test(created_stud["uid"] == new_uid, "Created student has correct UID")
    assert_test(created_stud["success_score"] > 60.0, f"Automatic score recalculated for new student (Score: {created_stud['success_score']})")

    # Duplicate UID prevention test
    duplicate_add = admin_client.post("/api/students", json={
        "uid": new_uid,
        "name": "Another Person",
        "batch_code": "CSE_2023_27"
    })
    assert_test(duplicate_add.status_code == 409, "Duplicate UID rejected with 409 Conflict")

    # -------------------------------------------------------------------------
    # TEST 12: Data Management - Edit Student & Diff Tracking
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 12: Edit Student Validation, Recalculation & Audit ---")
    
    # Out-of-bounds edit test (attendance 150%)
    invalid_edit = admin_client.put(f"/api/students/{new_uid}", json={"attendance_overall": 150.0})
    assert_test(invalid_edit.status_code == 400, "Out-of-bounds attendance 150% rejected with 400 Bad Request")

    # Valid edit test: change attendance from 92.5% to 45.0% and backlogs to 3
    valid_edit = admin_client.put(f"/api/students/{new_uid}", json={
        "attendance_overall": 45.0,
        "backlogs": 3
    })
    assert_test(valid_edit.status_code == 200, "Valid student update returns 200 OK")
    edit_data = valid_edit.get_json()
    assert_test(edit_data["changes_applied"] == 2, "Reported 2 field changes applied")
    
    # Check that score recalculation downgraded risk_level and needs_attention
    updated_stud = edit_data["student"]
    assert_test(updated_stud["needs_attention"] == 1, "Automatic recalculation flagged student for Needs Attention")
    assert_test(updated_stud["risk_level"] == "High", "Automatic recalculation elevated risk_level to 'High'")

    # -------------------------------------------------------------------------
    # TEST 13: Audit Logs History API
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 13: Audit Logs History Verification ---")
    audit_res = admin_client.get("/api/audit-logs")
    assert_test(audit_res.status_code == 200, "GET /api/audit-logs returns 200 OK")
    audit_data = audit_res.get_json()
    assert_test(audit_data["count"] >= 2, "Audit log contains entries for ADD_STUDENT and EDIT_STUDENT")
    
    latest_log = audit_data["audit_logs"][0]
    assert_test(latest_log["username"] == "admin" and latest_log["role"] == "Admin", "Audit log captured admin username and role")
    assert_test(latest_log["target_uid"] == new_uid, "Audit log captured correct target_uid")

    # Clean up test student
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM students WHERE uid = 'CSE2023999'")
        conn.execute("DELETE FROM academic_details WHERE uid = 'CSE2023999'")
        conn.execute("DELETE FROM attendance_details WHERE uid = 'CSE2023999'")
        conn.commit()
        conn.close()
        import scoring
        df_sync, _ = scoring.load_and_score(DB_PATH)
        scoring.update_database_scores(df_sync, DB_PATH)
    except Exception:
        pass

    print("\n" + "=" * 70)
    print(f"ALL TESTS COMPLETED: {passed_tests} / {total_tests} PASSED (100% SUCCESS)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_tests()
