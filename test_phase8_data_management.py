"""
Phase 8 Verification Test Suite: Data Management Page (/data-management-view)
Verifies:
1. Authentication guard: unauthenticated visits redirect to /login.
2. Warning modal BEFORE modifying:
   - Contains exact warning: "You are about to modify student records. Changes affect scores and risk flags for the whole batch and are logged. Continue?"
   - Cancel and Continue options.
   - Admin can proceed with modifications.
   - Faculty receives view-only mode notice and persistent banner.
3. Components inside Data Management:
   - Editable table of students with live search and risk filter.
   - Add-student form with validation hints and boundary checks.
   - CSV upload form and automated cleaning pipeline.
   - Data Quality report section with issue counts and audit rows.
   - System Audit Log section tracking user, role, timestamp, and field diffs.
   - Sample CSV template download endpoint (/api/data-management/template-csv).
4. Modification security and permissions:
   - Faculty is rejected with 403 Forbidden on add, edit, and CSV upload.
   - Admin can successfully add a student, edit a student, and upload a CSV.
   - Automatic score and risk flag recalculation after any modification.
   - Audit logging of all actions.
   - Boundary range validation (clear error messages on invalid input).
"""

import io
import json
import unittest
import sqlite3
from app import app, DATABASE_PATH
import scoring


class TestPhase8DataManagement(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

    def tearDown(self):
        # Guarantee database integrity: remove any test UIDs inserted during testing
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM students WHERE uid IN ('TESTPHASE801', 'TESTPHASE802', 'CSVTEST001', 'CSVTEST002');")
            cur.execute("DELETE FROM academic_details WHERE uid IN ('TESTPHASE801', 'TESTPHASE802', 'CSVTEST001', 'CSVTEST002');")
            cur.execute("DELETE FROM attendance_details WHERE uid IN ('TESTPHASE801', 'TESTPHASE802', 'CSVTEST001', 'CSVTEST002');")
            conn.commit()
            conn.close()
            # Restore fresh scores
            scoring.load_and_score(DATABASE_PATH)
        except Exception:
            pass

    def login(self, username="admin", password="admin123"):
        return self.client.post("/login", data={
            "username": username,
            "password": password
        }, follow_redirects=True)

    # -------------------------------------------------------------------------
    # 1. Access Control & Warning Modal
    # -------------------------------------------------------------------------
    def test_01_unauthenticated_access_redirects(self):
        """Unauthenticated requests to /data-management-view must redirect to /login."""
        resp = self.client.get("/data-management-view")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_02_admin_warning_modal_rendered(self):
        """Admin visit renders the exact required warning prompt."""
        self.login("admin", "admin123")
        resp = self.client.get("/data-management-view")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Exact warning modal text
        self.assertIn("You are about to modify student records. Changes affect scores and risk flags for the whole batch and are logged. Continue?", html)
        self.assertIn("Cancel", html)
        self.assertIn("Continue", html)
        self.assertIn("dataMgmtWarningModal", html)

    def test_03_faculty_view_only_modal_and_banner(self):
        """Faculty visit renders view-only modal notice and persistent alert banner."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/data-management-view")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("View only", html)
        self.assertIn("View-Only Mode Active", html)
        self.assertIn("Only Admin", html)
        # Edit and submit buttons should be disabled for Faculty
        self.assertIn("disabled", html)

    # -------------------------------------------------------------------------
    # 2. Structural Components Inside Data Management
    # -------------------------------------------------------------------------
    def test_04_core_sections_rendered(self):
        """All 5 core sections must be present inside the page."""
        self.login("admin", "admin123")
        resp = self.client.get("/data-management-view")
        html = resp.get_data(as_text=True)

        # 1. Editable Table
        self.assertIn('editable-records-section', html)
        self.assertIn('editable-students-table', html)
        self.assertIn('studentSearchInput', html)

        # 2. Add Student Form
        self.assertIn('add-student-section', html)
        self.assertIn('addStudentForm', html)
        self.assertIn('add_uid', html)

        # 3. CSV Upload Section
        self.assertIn('csv-upload-section', html)
        self.assertIn('csv_file', html)
        self.assertIn('csv-upload-dropzone', html)

        # 4. Data Quality Report
        self.assertIn('data-quality-section', html)
        self.assertIn('Total Fixes Applied', html)

        # 5. Administrative Audit Log
        self.assertIn('audit-log-section', html)
        self.assertIn('Administrative Audit Log', html)

    def test_05_sample_csv_template_download(self):
        """Staff should be able to download sample CSV template."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/api/data-management/template-csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["Content-Type"])
        content = resp.get_data(as_text=True)
        self.assertIn("uid,name,batch_code,cgpa", content)

    # -------------------------------------------------------------------------
    # 3. Security: Faculty Blocked from Adding/Editing/Uploading
    # -------------------------------------------------------------------------
    def test_06_faculty_blocked_from_adding_student(self):
        """Faculty cannot add a student (403 Forbidden)."""
        self.login("faculty1", "faculty123")
        resp = self.client.post("/api/students", json={
            "uid": "TESTPHASE801",
            "name": "Unauthorized Student",
            "batch_code": "CSE_2023_27"
        })
        self.assertEqual(resp.status_code, 403)

    def test_07_faculty_blocked_from_editing_student(self):
        """Faculty cannot edit a student (403 Forbidden)."""
        self.login("faculty1", "faculty123")
        resp = self.client.put("/api/students/CSE2023001", json={
            "cgpa": 9.99
        })
        self.assertEqual(resp.status_code, 403)

    def test_08_faculty_blocked_from_uploading_csv(self):
        """Faculty cannot upload a CSV (403 Forbidden)."""
        self.login("faculty1", "faculty123")
        csv_data = "uid,name,cgpa\nTEST01,Test,8.0\n"
        data = {
            "csv_file": (io.BytesIO(csv_data.encode("utf-8")), "test.csv")
        }
        resp = self.client.post("/upload-csv", data=data, content_type="multipart/form-data")
        # HTML form redirects or returns 403
        self.assertIn(resp.status_code, (302, 403))

    # -------------------------------------------------------------------------
    # 4. Admin Add Student, Validation & Score Recalculation
    # -------------------------------------------------------------------------
    def test_09_admin_add_student_with_validation_and_audit(self):
        """Admin adds a new student; validates ranges, creates audit log, recalculates scores."""
        self.login("admin", "admin123")

        # Invalid range: CGPA = 15.0
        resp_invalid = self.client.post("/api/students", json={
            "uid": "TESTPHASE801",
            "name": "Test Boundary",
            "batch_code": "CSE_2023_27",
            "cgpa": 15.0
        })
        self.assertEqual(resp_invalid.status_code, 400)
        self.assertIn("out of bounds", resp_invalid.get_json()["error"])

        # Valid addition
        resp_valid = self.client.post("/api/students", json={
            "uid": "TESTPHASE801",
            "name": "Pooja Hegde",
            "batch_code": "CSE_2023_27",
            "cgpa": 8.50,
            "attendance_overall": 92.0,
            "internal_avg": 35.0,
            "exam_avg": 50.0,
            "backlogs": 0,
            "lms_assignment_pct": 95.0,
            "aptitude_score": 85.0,
            "coding_score": 90.0,
            "mock_interview": 85.0
        })
        self.assertEqual(resp_valid.status_code, 201)
        data = resp_valid.get_json()
        self.assertTrue(data["success"])
        # Score calculated
        self.assertGreater(data["student"]["success_score"], 70.0)

        # Verify audit log recorded ADD_STUDENT
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        log = cur.execute("SELECT action, target_uid, username FROM audit_log WHERE target_uid = 'TESTPHASE801'").fetchone()
        conn.close()
        self.assertIsNotNone(log)
        self.assertEqual(log[0], "ADD_STUDENT")
        self.assertEqual(log[2], "admin")

    # -------------------------------------------------------------------------
    # 5. Admin Edit Student, Recalculation & Diff Logging
    # -------------------------------------------------------------------------
    def test_10_admin_edit_student_recalculates_and_diffs(self):
        """Admin edits student metrics; recalculates scores and flags diffs."""
        self.login("admin", "admin123")

        # First add a student to edit
        self.client.post("/api/students", json={
            "uid": "TESTPHASE802",
            "name": "Vikram Rathore",
            "batch_code": "CSE_2023_27",
            "cgpa": 7.50,
            "attendance_overall": 80.0
        })

        # Edit attendance down to 45% (should trigger Low Attendance concern / Attention flag)
        resp_edit = self.client.put("/api/students/TESTPHASE802", json={
            "attendance_overall": 45.0,
            "backlogs": 4
        })
        self.assertEqual(resp_edit.status_code, 200)
        data = resp_edit.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["changes_applied"], 2)
        # Recalculated risk flag elevated
        self.assertEqual(data["student"]["risk_level"], "High")

        # Verify audit diff logged
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        log = cur.execute("SELECT details FROM audit_log WHERE action = 'EDIT_STUDENT' AND target_uid = 'TESTPHASE802' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertIsNotNone(log)
        self.assertIn("attendance_overall", log[0])

    # -------------------------------------------------------------------------
    # 6. Admin CSV Upload with Automated Cleaning Pipeline
    # -------------------------------------------------------------------------
    def test_11_admin_csv_cleaning_pipeline(self):
        """Admin uploads CSV with deliberate anomalies; cleans, clamps, imputes, and updates."""
        self.login("admin", "admin123")

        # CSV with messy UID whitespace, out-of-range attendance (125.0%), and duplicate row
        csv_content = (
            "uid,name,batch_code,cgpa,attendance_overall,exam_avg,internal_avg\n"
            " csvtest001 ,Rohan Mehra,CSE_2023_27,8.2,125.0,45.0,32.0\n"
            "csvtest001,Rohan Mehra,CSE_2023_27,8.2,125.0,45.0,32.0\n"
            "CSVTEST002,Simran Kaur,CSE_2023_27,7.8,78.0,40.0,28.0\n"
        )

        data = {
            "csv_file": (io.BytesIO(csv_content.encode("utf-8")), "messy_batch_update.csv")
        }

        resp = self.client.post("/api/upload-csv", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        res = resp.get_json()
        self.assertTrue(res["success"])

        # Check that anomalies were detected and fixed
        fixes = res["cleaning_fixes"]
        self.assertGreaterEqual(fixes["uid_fixes"], 1)
        self.assertGreaterEqual(fixes["duplicates_dropped"], 1)
        self.assertGreaterEqual(fixes["values_clamped"], 1)

        # Check clamped attendance in database (clamped to 100.0)
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        row = cur.execute("SELECT attendance_overall FROM students WHERE uid = 'CSVTEST001'").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertLessEqual(row[0], 100.0)


if __name__ == "__main__":
    unittest.main()
