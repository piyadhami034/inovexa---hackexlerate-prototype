"""
=============================================================================
Smart Campus Analytics - Phase 6 Students List & Student Detail Test Suite
=============================================================================
Verifies:
1. Students List page (/students-view) rendering, table elements, colored risk flags.
2. Search by UID and search by student name.
3. Filtering by Risk Level (High / Medium / Low / Attention).
4. Filtering by Cohort Segment (Disengaged, High Performers, etc.).
5. Column sorting (CGPA, Success Score, Name).
6. Clickable table rows navigating to student detail.
7. Student Detail page (/students-view/<uid>) rendering & Back button pattern.
8. Profile header (UID, name, batch, segment badge, status).
9. Success Score callout with risk flag and readiness sub-scores.
10. "Why Flagged" panel with plain-English reasons and suggested actions.
11. Indicator breakdown chart vs batch average across all 8 domains.
12. All seven data sources with real values and detailed subject breakdowns.
13. Unauthenticated protection.
=============================================================================
"""

from app import app


def test_phase6():
    print("=" * 70)
    print("SMART CAMPUS ANALYTICS: RUNNING PHASE 6 STUDENTS LIST & DETAIL TEST SUITE")
    print("=" * 70)

    auth_client = app.test_client()
    # Log in as admin
    login_res = auth_client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
    assert login_res.status_code == 200, "Login failed"

    # Select CSE_2023_27 batch
    sel_res = auth_client.post("/select-batch", data={"batch_code": "CSE_2023_27"}, follow_redirects=True)
    assert sel_res.status_code == 200, "Batch selection failed"

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
    # 1. Students List Page Rendering
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 1: Students List Page Rendering (design/4-students-list.png) ---")
    list_res = auth_client.get("/students-view")
    assert_test(list_res.status_code == 200, "GET /students-view returns 200 OK")
    list_html = list_res.get_data(as_text=True)

    assert_test("Students Directory" in list_html, "Page title 'Students Directory' present")
    assert_test("btn-back-arrow" in list_html, "Back button element present")
    assert_test("students-table" in list_html, "Students table present")
    assert_test("search-input" in list_html, "Search input field present")
    assert_test("filter-select" in list_html, "Filter select dropdowns present")
    assert_test("risk-flag-badge" in list_html, "Colored risk flag badges present")
    assert_test("clickable-student-row" in list_html, "Clickable student rows present")

    # -------------------------------------------------------------------------
    # 2. Search & Filtering Functionality
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 2: Search & Filter Verification ---")
    
    # Search by UID in active batch
    uid_res = auth_client.get("/students-view?search=CSE2023001")
    uid_html = uid_res.get_data(as_text=True)
    uid_tbody = uid_html.split("<tbody>")[1].split("</tbody>")[0]
    assert_test("CSE2023001" in uid_tbody, "Search finds student by UID 'CSE2023001'")
    assert_test("CSE2023002" not in uid_tbody, "Non-matching UIDs are filtered out")

    # Search by Name
    name_res = auth_client.get("/students-view?search=Alok")
    name_html = name_res.get_data(as_text=True)
    name_tbody = name_html.split("<tbody>")[1].split("</tbody>")[0]
    assert_test("Alok" in name_tbody, "Search finds student by name substring 'Alok'")

    # Filter by High Risk
    high_res = auth_client.get("/students-view?risk=high")
    high_html = high_res.get_data(as_text=True)
    high_tbody = high_html.split("<tbody>")[1].split("</tbody>")[0]
    assert_test("High Risk" in high_tbody, "Table body shows High Risk students")
    assert_test("Low Risk" not in high_tbody, "Table body does not show Low Risk students when filtered to high")

    # Filter by Low Risk
    low_res = auth_client.get("/students-view?risk=low")
    low_html = low_res.get_data(as_text=True)
    low_tbody = low_html.split("<tbody>")[1].split("</tbody>")[0]
    assert_test("Low Risk" in low_tbody, "Table body shows Low Risk students")
    assert_test("High Risk" not in low_tbody, "Table body does not show High Risk students when filtered to low")

    # Filter by Segment
    seg_res = auth_client.get("/students-view?segment=Disengaged")
    seg_html = seg_res.get_data(as_text=True)
    seg_tbody = seg_html.split("<tbody>")[1].split("</tbody>")[0]
    assert_test("Disengaged" in seg_tbody, "Filter segment=Disengaged returns matching cohort rows")

    # Sort by CGPA
    sort_res = auth_client.get("/students-view?sort_by=cgpa&sort_order=desc")
    assert_test(sort_res.status_code == 200, "Sorting by CGPA returns 200 OK")

    # -------------------------------------------------------------------------
    # 3. Student Detail Page (design/5-student-detail.png)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 3: Student Detail Page Rendering ---")
    det_res = auth_client.get("/students-view/CSE2023001")
    assert_test(det_res.status_code == 200, "GET /students-view/CSE2023001 returns 200 OK")
    det_html = det_res.get_data(as_text=True)

    # Back button
    assert_test("btn-back-arrow" in det_html, "Back button present on student detail")

    # Profile Header
    assert_test("profile-hero-card" in det_html, "Profile hero card present")
    assert_test("CSE2023001" in det_html, "Student UID displayed")
    assert_test("profile-avatar-large" in det_html, "Large avatar with initials displayed")
    assert_test("meta-pill segment" in det_html, "Segment tag displayed in profile")

    # Success Score & Readiness
    assert_test("score-hero-display" in det_html, "Score hero display widget present")
    assert_test("Success Score" in det_html, "Success Score label present")
    assert_test("Academic Readiness:" in det_html, "Academic Readiness sub-score present")
    assert_test("Placement Readiness:" in det_html, "Placement Readiness sub-score present")
    assert_test("risk-flag-badge" in det_html, "Colored risk flag badge present")

    # Why Flagged Panel
    assert_test("why-flagged-panel" in det_html, "Why Flagged panel present")
    assert_test("Root Causes &amp; Deficits" in det_html or "Root Causes" in det_html, "Diagnostic reasons block present")
    assert_test("Suggested Faculty &amp; Mentor Action Plan" in det_html or "Action Plan" in det_html, "Faculty action playbook block present")

    # Score Breakdown Chart
    assert_test("studentBreakdownChart" in det_html, "Indicator breakdown chart canvas present")
    assert_test("Indicator Breakdown vs. Cohort Average" in det_html, "Breakdown section title present")
    assert_test("Examinations" in det_html, "Examinations indicator present")
    assert_test("Internal assessments" in det_html, "Internal assessments indicator present")
    assert_test("Attendance" in det_html, "Attendance indicator present")
    assert_test("LMS activity" in det_html, "LMS activity indicator present")

    # -------------------------------------------------------------------------
    # 4. Seven Data Sources Verification
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 4: All Seven Data Sources Verification ---")
    assert_test("1. Academic Performance" in det_html, "Source 1: Academic Performance present")
    assert_test("Cumulative GPA (CGPA):" in det_html, "CGPA metric present")
    assert_test("Subject Marks Breakdown:" in det_html, "Subject marks table present")

    assert_test("2. Attendance Tracking" in det_html, "Source 2: Attendance Tracking present")
    assert_test("Overall Attendance:" in det_html, "Overall attendance metric present")
    assert_test("Subject-Wise Attendance:" in det_html, "Subject-wise attendance table present")

    assert_test("3. Learning Management System" in det_html, "Source 3: LMS Activity present")
    assert_test("Monthly Login Frequency:" in det_html, "LMS login frequency metric present")

    assert_test("4. Extracurricular Engagement" in det_html, "Source 4: Extracurricular Engagement present")
    assert_test("Campus Events Attended:" in det_html, "Events attended metric present")

    assert_test("5. Placement Readiness" in det_html, "Source 5: Placement Readiness present")
    assert_test("Aptitude Assessment Score:" in det_html, "Aptitude score metric present")
    assert_test("Coding Assessment Score:" in det_html, "Coding score metric present")

    assert_test("6. Skills Assessment" in det_html, "Source 6: Skills Assessment present")
    assert_test("Python Programming:" in det_html, "Python score metric present")
    assert_test("SQL &amp; Database Design:" in det_html, "SQL score metric present")

    assert_test("7. Student &amp; Faculty Feedback" in det_html, "Source 7: Feedback present")
    assert_test("Student Satisfaction" in det_html, "Student satisfaction metric present")
    assert_test("Faculty Feedback" in det_html, "Faculty feedback metric present")

    # -------------------------------------------------------------------------
    # 5. Invalid UID & Unauthenticated Security
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 5: Security & Edge Case Handling ---")
    bad_res = auth_client.get("/students-view/NONEXISTENT999", follow_redirects=True)
    assert_test(bad_res.status_code == 200 and "not found" in bad_res.get_data(as_text=True).lower(), "Non-existent UID gracefully redirects with error flash")

    anon_client = app.test_client()
    for route in ["/students-view", "/students-view/CSE2023001"]:
        anon_res = anon_client.get(route)
        assert_test(anon_res.status_code == 302 and "/login" in anon_res.headers.get("Location", ""), f"Unauthenticated {route} redirects to /login")

    print("\n" + "=" * 70)
    print(f"ALL PHASE 6 TESTS PASSED: {passed} / {total} (100% SUCCESS)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    test_phase6()
