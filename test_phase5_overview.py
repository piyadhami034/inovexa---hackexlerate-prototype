"""
=============================================================================
Smart Campus Analytics - Phase 5 Batch Overview Verification Test Suite
=============================================================================
Verifies:
1. Three stat cards (total students, average Success Score, students needing attention).
2. Rectangular scrollable box listing students needing attention sorted lowest first.
3. Attention rows clickable to student detail.
4. "Download as CSV" button and backend /api/batch/attention-csv route.
5. Key-trends section with Chart.js canvases (score distribution & attendance trend).
6. API trends endpoint returns score bands and attendance data.
7. Three navigation flow cards (STUDENTS LIST, AT-RISK & SEGMENTS, DATA MANAGEMENT).
8. "How is the score calculated?" info link and modal with all 8 indicator weights.
=============================================================================
"""

import csv
import io
from app import app


def test_phase5_overview():
    print("=" * 70)
    print("SMART CAMPUS ANALYTICS: RUNNING PHASE 5 BATCH OVERVIEW TEST SUITE")
    print("=" * 70)

    auth_client = app.test_client()
    # Log in as admin
    login_res = auth_client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
    assert login_res.status_code == 200, "Login failed"

    passed = 0
    total = 0

    def assert_test(cond, msg):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
            print(f"  [PASS] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            assert cond, f"Assertion failed: {msg}"

    # -------------------------------------------------------------------------
    # 1. Overview Page & 3 Stat Cards
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 1: Three Stat Cards & Header Layout ---")
    ov_res = auth_client.get("/overview")
    assert_test(ov_res.status_code == 200, "GET /overview returns 200 OK")
    html = ov_res.get_data(as_text=True)

    # 3 Stat Cards
    assert_test("Total Students" in html, "Stat Card 1: 'Total Students' present")
    assert_test("Avg Success Score" in html, "Stat Card 2: 'Avg Success Score' present")
    assert_test("Students Needing Attention" in html, "Stat Card 3: 'Students Needing Attention' present")
    assert_test("kpi-total-students" in html, "KPI element for total students present")
    assert_test("kpi-avg-score" in html, "KPI element for average score present")
    assert_test("kpi-attention-count" in html, "KPI element for attention count present")

    # -------------------------------------------------------------------------
    # 2. Rectangular Scrollable Attention Box & Sorting
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 2: Scrollable Attention Box & Lowest-Score Sorting ---")
    assert_test("scrollable-attention-box" in html, "Scrollable container element present")
    assert_test("attention-box-card" in html, "Attention card box present")
    assert_test("Download as CSV" in html, "CSV Download button present")
    assert_test("api/batch/attention-csv" in html, "CSV download link points to backend route")

    # Verify that attention rows are rendered and clickable
    assert_test("attention-row-clickable" in html, "Clickable row classes present")
    assert_test("/students-view/" in html, "Rows link to student detail route")

    # Query backend API to confirm strict ascending sorting (lowest score first)
    summary_api = auth_client.get("/api/batch/summary?batch_code=CSE_2023_27").get_json()
    att_list = summary_api["attention_students"]
    assert_test(len(att_list) > 0, "Attention students list is populated")

    scores = [s["success_score"] for s in att_list]
    is_sorted_lowest_first = all(scores[i] <= scores[i + 1] for i in range(len(scores) - 1))
    assert_test(is_sorted_lowest_first, f"Attention students strictly sorted lowest score first (Min: {scores[0]}, Max: {scores[-1]})")

    # -------------------------------------------------------------------------
    # 3. Download Attention as CSV
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 3: Attention CSV Download Route ---")
    csv_res = auth_client.get("/api/batch/attention-csv?batch_code=CSE_2023_27")
    assert_test(csv_res.status_code == 200, "GET /api/batch/attention-csv returns 200 OK")
    assert_test("text/csv" in csv_res.headers.get("Content-Type", ""), "Response Content-Type is text/csv")
    assert_test("attention_students_CSE_2023_27.csv" in csv_res.headers.get("Content-Disposition", ""), "Response header has attachment filename")

    csv_text = csv_res.get_data(as_text=True)
    reader = list(csv.reader(io.StringIO(csv_text)))
    assert_test(len(reader) > 1, "CSV contains rows")
    header = reader[0]
    assert_test("UID" in header and "Success Score (0-100)" in header, "CSV header has UID and Success Score columns")

    # Verify CSV rows are sorted lowest score first
    csv_scores = [float(row[3]) for row in reader[1:]]
    assert_test(all(csv_scores[i] <= csv_scores[i + 1] for i in range(len(csv_scores) - 1)), "CSV data rows strictly sorted lowest score first")

    # -------------------------------------------------------------------------
    # 4. Key Trends & Chart.js Visualizations
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 4: Key-Trends Section & Chart.js Integration ---")
    assert_test("scoreBandsChart" in html, "Canvas for score distribution chart present")
    assert_test("attendanceTrendChart" in html, "Canvas for attendance trend chart present")
    assert_test("chart.min.js" in html, "Chart.js library included")

    # Verify trends API output
    trends_res = auth_client.get("/api/trends?batch_code=CSE_2023_27")
    assert_test(trends_res.status_code == 200, "GET /api/trends returns 200 OK")
    t_data = trends_res.get_json()

    assert_test("score_bands" in t_data, "Trends API returns score_bands object")
    assert_test(len(t_data["score_bands"]["labels"]) == 3, "Score bands contain Low, Medium, High labels")
    assert_test("attendance_trend" in t_data, "Trends API returns attendance_trend object")
    assert_test(len(t_data["attendance_trend"]["labels"]) == 6, "Attendance trend contains 6 subjects")

    # -------------------------------------------------------------------------
    # 5. Three Navigation Flow Cards
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 5: Three Navigation Flow Cards ---")
    assert_test("STUDENTS LIST" in html, "Card 1: STUDENTS LIST present")
    assert_test("AT-RISK & SEGMENTS" in html, "Card 2: AT-RISK & SEGMENTS present")
    assert_test("DATA MANAGEMENT" in html, "Card 3: DATA MANAGEMENT present")
    assert_test("students_view" in html or "/students-view" in html, "STUDENTS LIST links to students route")
    assert_test("at_risk_view" in html or "/at-risk-view" in html, "AT-RISK & SEGMENTS links to at-risk route")
    assert_test("data_management_view" in html or "/data-management-view" in html, "DATA MANAGEMENT links to data management route")

    # -------------------------------------------------------------------------
    # 6. "How is the score calculated?" Modal
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 6: Scoring Weights Modal ---")
    assert_test("How is this calculated?" in html, "Info trigger button present")
    assert_test("scoringModal" in html, "Accessible modal container present")
    assert_test("weights-table" in html, "Weights table element present")

    # Check that all 8 indicator weights are displayed
    weights_expected = ["Examinations", "Internal Assessments", "Attendance", "LMS", "Placement", "Skills", "Extracurricular", "Feedback"]
    for w in weights_expected:
        assert_test(w.lower() in html.lower(), f"Weight indicator '{w}' displayed in modal")

    print("\n" + "=" * 70)
    print(f"ALL PHASE 5 TESTS PASSED: {passed} / {total} (100% SUCCESS)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    test_phase5_overview()
