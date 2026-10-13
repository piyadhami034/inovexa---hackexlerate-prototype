"""
=============================================================================
Smart Campus Analytics - Phase 4 Frontend Shell & Page Flow Test Suite
=============================================================================
Tests:
1. Login page rendering, branding, elements, and zero data leakage before auth.
2. Wrong password error handling & flash messaging.
3. Successful authentication flow and session state.
4. Batch selection page rendering, cards, student counts, and header components.
5. Batch selection POST transition to Overview.
6. Batch Overview page rendering, 4 stat cards, 3 flow cards, and attention roster table.
7. Common header items: logged-in name, role badge, current batch pill, logout button.
8. Back button pattern functionality.
9. Unauthenticated protection across all shell pages.
=============================================================================
"""

from app import app


def test_frontend_shell():
    print("=" * 70)
    print("SMART CAMPUS ANALYTICS: RUNNING PHASE 4 FRONTEND SHELL TEST SUITE")
    print("=" * 70)

    client = app.test_client()
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
    # 1. Login Page Inspection
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 1: Login Page Shell (design/1-login.png) ---")
    res = client.get("/login")
    assert_test(res.status_code == 200, "GET /login returns 200 OK")
    html = res.get_data(as_text=True)

    assert_test("InnoVista University" in html, "Brand title 'InnoVista University' present")
    assert_test("Engineering College" in html, "Subtitle 'Engineering College' present")
    assert_test("🎓" in html, "Stylized graduation cap emblem present")
    assert_test("Welcome Back!" in html, "Welcome Back! greeting present")
    assert_test("togglePassword()" in html, "Password visibility toggle JS present")
    assert_test("Remember me" in html, "Remember me checkbox present")
    assert_test("Forgot password?" in html, "Forgot password link present")
    assert_test("Contact your institution" in html, "Footer contact link present")
    assert_test("style.css" in html, "Shared stylesheet linked")

    # Verify no student data is leaked before login
    assert_test("CSE2023001" not in html and "Alok Reddy" not in html, "Zero student data leakage on login page")

    # -------------------------------------------------------------------------
    # 2. Login Failure Feedback
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 2: Authentication Error Feedback ---")
    fail_res = client.post("/login", data={"username": "admin", "password": "wrong_password"})
    assert_test(fail_res.status_code == 200, "Failed login re-renders page")
    fail_html = fail_res.get_data(as_text=True)
    assert_test("Invalid username or password" in fail_html, "Clear error flash message displayed on bad credentials")

    # -------------------------------------------------------------------------
    # 3. Successful Login & Session Initialization
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 3: Successful Authentication ---")
    auth_client = app.test_client()
    login_res = auth_client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
    assert_test(login_res.status_code == 200, "Successful login navigates to authenticated page")
    with auth_client.session_transaction() as sess:
        assert_test(sess.get("user_id") is not None, "Session stores user_id")
        assert_test(sess.get("role") == "Admin", "Session stores Admin role")
        assert_test(sess.get("full_name") == "Dr. Admin User", "Session stores full_name")

    # -------------------------------------------------------------------------
    # 4. Batch Selection Page (design/2-batch.png)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 4: Batch Selection Shell (design/2-batch.png) ---")
    batch_res = auth_client.get("/select-batch")
    assert_test(batch_res.status_code == 200, "GET /select-batch returns 200 OK")
    batch_html = batch_res.get_data(as_text=True)

    # Check common header elements
    assert_test("Dr. Admin User" in batch_html, "Header displays logged-in staff name")
    assert_test("Admin" in batch_html, "Header displays staff role badge")
    assert_test("Sign Out" in batch_html or "Logout" in batch_html, "Header displays logout button")

    # Check page header bar pattern
    assert_test("Select Academic Batch" in batch_html, "Page title 'Select Academic Batch' present")
    assert_test("btn-back-arrow" in batch_html, "Back button / navigation element present")

    # Check batch cards
    assert_test("CSE 2023-27" in batch_html, "Batch CSE 2023-27 card displayed")
    assert_test("ECE 2023-27" in batch_html, "Batch ECE 2023-27 card displayed")
    assert_test("CSE 2024-28" in batch_html, "Batch CSE 2024-28 card displayed")
    assert_test("60" in batch_html, "Enrolled student counts displayed")
    assert_test("selectBatch(" in batch_html, "Interactive card selection function present")
    assert_test("Quick Cohort Switcher" in batch_html, "Dropdown cohort switcher present")

    # -------------------------------------------------------------------------
    # 5. Batch Selection Action & Redirect to Overview
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 5: Selecting Batch Redirects to Overview ---")
    select_res = auth_client.post("/select-batch", data={"batch_code": "CSE_2023_27"}, follow_redirects=False)
    assert_test(select_res.status_code == 302 and "/overview" in select_res.headers.get("Location", ""), "POST /select-batch redirects to /overview")
    with auth_client.session_transaction() as sess:
        assert_test(sess.get("batch_code") == "CSE_2023_27", "Session updated with selected batch_code")

    # -------------------------------------------------------------------------
    # 6. Overview Dashboard Rendering (design/3-overview.png)
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 6: Batch Overview Page & Components ---")
    ov_res = auth_client.get("/overview")
    assert_test(ov_res.status_code == 200, "GET /overview returns 200 OK")
    ov_html = ov_res.get_data(as_text=True)

    # Header and back button pattern
    assert_test("Class Analytics" in ov_html, "Page title 'Class Analytics' present")
    assert_test("btn-back-arrow" in ov_html, "Back arrow button present")
    assert_test("cohort-info-pill" in ov_html, "Top-right cohort info pill present")
    assert_test("CSE 2023-27" in ov_html, "Active cohort displayed in pill")

    # Stat Cards
    assert_test("Total Students" in ov_html, "Stat Card 1: Total Students present")
    assert_test("Success Score" in ov_html or "Class Average" in ov_html, "Stat Card 2: Success Score / Class Average present")
    assert_test("Attention" in ov_html or "Students at Risk" in ov_html, "Stat Card 3: Students Needing Attention present")

    # 3 Navigation Flow Cards
    assert_test("STUDENTS LIST" in ov_html, "Flow Card 1: STUDENTS LIST present")
    assert_test("AT-RISK & SEGMENTS" in ov_html, "Flow Card 2: AT-RISK & SEGMENTS present")
    assert_test("DATA MANAGEMENT" in ov_html, "Flow Card 3: DATA MANAGEMENT present")

    # Attention Box Section
    assert_test("Students Requiring Attention" in ov_html, "Attention table section present")
    assert_test("Download as CSV" in ov_html, "Download as CSV button present")
    assert_test("View Details" in ov_html, "Action 'View Details' buttons present")

    # -------------------------------------------------------------------------
    # 7. Unauthenticated Protection
    # -------------------------------------------------------------------------
    print("\n--- Test Suite 7: Unauthenticated Route Protection ---")
    anon_client = app.test_client()
    for route in ["/overview", "/select-batch", "/students-view"]:
        r = anon_client.get(route)
        assert_test(r.status_code == 302 and "/login" in r.headers.get("Location", ""), f"Unauthenticated {route} redirects to /login")

    print("\n" + "=" * 70)
    print(f"ALL FRONTEND SHELL TESTS PASSED: {passed} / {total} (100% SUCCESS)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    test_frontend_shell()
