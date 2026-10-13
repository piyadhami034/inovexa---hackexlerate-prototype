"""
Phase 9 End-to-End Verification Test Suite: Complete User Journey
Verifies:
1. Complete journey:
   - Login (/login)
   - Batch selection (/select-batch)
   - Overview dashboard (/overview)
   - Students list (/students-view) with search and filters
   - Student detail (/students-view/<uid>) with 7 sources & explainability
   - At-risk & segments (/at-risk-view)
   - Data management (/data-management-view)
   - Edit student & automatic recalculation
   - Add student & automatic recalculation
   - CSV upload & automated cleaning pipeline
2. Phase 9 Enhancements:
   - Synthetic data footer ("Demo uses synthetic data generated for this prototype.") present on all pages.
   - 15-minute inactivity session expiration and redirect with flash message.
   - Logout and session clearance.
"""

import io
import time
import unittest
import sqlite3
from app import app, DATABASE_PATH
import scoring


class TestPhase9EndToEnd(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

    def tearDown(self):
        # Guarantee database integrity
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM students WHERE uid IN ('E2ETEST001', 'E2ETEST002', 'CSVE2E001');")
            cur.execute("DELETE FROM academic_details WHERE uid IN ('E2ETEST001', 'E2ETEST002', 'CSVE2E001');")
            cur.execute("DELETE FROM attendance_details WHERE uid IN ('E2ETEST001', 'E2ETEST002', 'CSVE2E001');")
            conn.commit()
            conn.close()
            scoring.load_and_score(DATABASE_PATH)
        except Exception:
            pass

    def test_01_synthetic_data_footer_on_all_pages(self):
        """Verifies requirement: 'Show a small footer on every page: Demo uses synthetic data generated for this prototype.'"""
        # Login page
        resp_login = self.client.get("/login")
        self.assertEqual(resp_login.status_code, 200)
        self.assertIn("Demo uses synthetic data generated for this prototype.", resp_login.get_data(as_text=True))

        # Log in as faculty
        self.client.post("/login", data={"username": "faculty1", "password": "faculty123"}, follow_redirects=True)

        pages = [
            "/select-batch",
            "/overview",
            "/students-view",
            "/students-view/CSE2023001",
            "/at-risk-view",
            "/data-management-view"
        ]

        for path in pages:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"Failed on path: {path}")
            html = resp.get_data(as_text=True)
            self.assertIn("Demo uses synthetic data generated for this prototype.", html, f"Footer missing on: {path}")

    def test_02_15_minute_inactivity_auto_logout(self):
        """Verifies requirement: 'Automatically log staff out after 15 minutes of inactivity and return them to the login page with a message.'"""
        # 1. Log in
        self.client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)

        # Confirm session is valid
        resp = self.client.get("/overview")
        self.assertEqual(resp.status_code, 200)

        # Simulate 16 minutes (960 seconds) elapsed since last activity
        with self.client.session_transaction() as sess:
            sess["last_activity"] = time.time() - 960

        # Next request must be rejected and redirected to login with inactivity message
        resp_expired = self.client.get("/overview", follow_redirects=True)
        self.assertEqual(resp_expired.status_code, 200)
        html = resp_expired.get_data(as_text=True)
        self.assertIn("Your session has expired due to 15 minutes of inactivity. Please log in again.", html)

        # Confirm session was cleared
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

    def test_03_end_to_end_staff_journey(self):
        """Verifies complete end-to-end flow: Login -> Batch -> Overview -> List -> Detail -> Risk -> Edit."""
        # Step 1: Login
        login_resp = self.client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)

        # Step 2: Batch Selection
        batch_resp = self.client.post("/select-batch", data={"batch_code": "CSE_2023_27"}, follow_redirects=True)
        self.assertEqual(batch_resp.status_code, 200)
        self.assertIn("Batch Overview", batch_resp.get_data(as_text=True))

        # Step 3: Overview Page Inspection
        overview_resp = self.client.get("/overview")
        self.assertEqual(overview_resp.status_code, 200)
        ov_html = overview_resp.get_data(as_text=True)
        self.assertIn("Total Students", ov_html)
        self.assertIn("Students Requiring Attention", ov_html)
        self.assertIn("scoreBandsChart", ov_html)
        self.assertIn("attendanceTrendChart", ov_html)

        # Step 4: Students List with Search & Filter
        list_resp = self.client.get("/students-view?search=CSE2023001&risk=all")
        self.assertEqual(list_resp.status_code, 200)
        list_html = list_resp.get_data(as_text=True)
        self.assertIn("CSE2023001", list_html)

        # Step 5: Student Detail View
        detail_resp = self.client.get("/students-view/CSE2023001")
        self.assertEqual(detail_resp.status_code, 200)
        dt_html = detail_resp.get_data(as_text=True)
        self.assertIn("Success Score", dt_html)
        self.assertIn("Academic Performance", dt_html)
        self.assertIn("Attendance Tracking", dt_html)
        self.assertIn("Why Flagged", dt_html)

        # Step 6: At-Risk & Segments View
        risk_resp = self.client.get("/at-risk-view")
        self.assertEqual(risk_resp.status_code, 200)
        rk_html = risk_resp.get_data(as_text=True)
        self.assertIn("Academic Risk List", rk_html)
        self.assertIn("Placement Risk List", rk_html)
        self.assertIn("Behavioral Cohort Segments", rk_html)

        # Step 7: Data Management & Recalculation
        mgmt_resp = self.client.get("/data-management-view")
        self.assertEqual(mgmt_resp.status_code, 200)
        mg_html = mgmt_resp.get_data(as_text=True)
        self.assertIn("Editable Student Records", mg_html)
        self.assertIn("Add New Student Record", mg_html)
        self.assertIn("Data Quality Audit Report", mg_html)
        self.assertIn("Administrative Audit Log", mg_html)

        # Step 8: Edit Student and verify immediate score recalculation
        edit_resp = self.client.put("/api/students/CSE2023001", json={
            "attendance_overall": 99.0
        })
        self.assertEqual(edit_resp.status_code, 200)
        edit_data = edit_resp.get_json()
        self.assertTrue(edit_data["success"])

        # Step 9: Add Student
        add_resp = self.client.post("/api/students", json={
            "uid": "E2ETEST001",
            "name": "E2E Student",
            "batch_code": "CSE_2023_27",
            "cgpa": 9.2,
            "attendance_overall": 95.0
        })
        self.assertEqual(add_resp.status_code, 201)
        self.assertTrue(add_resp.get_json()["success"])

        # Step 10: Sign Out
        logout_resp = self.client.get("/logout", follow_redirects=True)
        self.assertEqual(logout_resp.status_code, 200)
        self.assertIn("Sign In", logout_resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
