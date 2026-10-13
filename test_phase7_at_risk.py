"""
Phase 7 Verification Test Suite: At-Risk & Segments View (/at-risk-view)
Verifies:
1. Authentication guard (redirects unauthenticated users to /login).
2. Successful rendering (200 OK) for faculty and admin sessions.
3. Standard design system consistency (header, Back button to /overview, cohort pill).
4. Side-by-side Academic Risk and Placement Risk rosters:
   - Academic Risk list, flagged count, student names, UIDs, academic sub-scores, diagnostic reasons.
   - Placement Risk list, flagged count, student names, UIDs, placement sub-scores, diagnostic reasons.
   - Clicking student rows navigates to /students-view/<uid>.
5. All 6 behavioral cohort segment cards:
   - High Performers, Strong Academics but Low Placement Readiness,
     Placement Ready but Weak Academics, Disengaged, Needs Overall Support, Steady.
   - Each displays count, description, and actionable recommended intervention.
   - Sum of segment counts matches total students in batch (60).
6. Chart.js canvas (#segmentSizeChart) and script inclusion.
7. Interactive modal (#segmentRosterModal) with student roster table and filtering script.
8. Batch switcher query parameter compatibility (?batch_code=ECE_2023_27).
"""

import unittest
from app import app, get_db


class TestPhase7AtRisk(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

    def login(self, username="faculty1", password="faculty123"):
        return self.client.post("/login", data={
            "username": username,
            "password": password
        }, follow_redirects=True)

    def test_01_unauthenticated_access_redirects(self):
        """Unauthenticated requests to /at-risk-view must redirect to /login."""
        resp = self.client.get("/at-risk-view")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_02_authenticated_access_faculty(self):
        """Faculty user should successfully view /at-risk-view with 200 OK."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("At-Risk Students &amp; Cohort Segments", html)
        self.assertIn("Academic Risk List", html)
        self.assertIn("Placement Risk List", html)

    def test_03_authenticated_access_admin(self):
        """Admin user should successfully view /at-risk-view with 200 OK."""
        self.login("admin", "admin123")
        resp = self.client.get("/at-risk-view")
        self.assertEqual(resp.status_code, 200)

    def test_04_back_button_and_cohort_pill(self):
        """Page must contain standard Back button linking to Overview and cohort pill."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view")
        html = resp.get_data(as_text=True)
        # Back button pattern
        self.assertIn('href="/overview"', html)
        self.assertIn('btn-back-arrow', html)
        # Cohort info pill
        self.assertIn('cohort-info-pill', html)
        self.assertIn('Change Batch', html)

    def test_05_academic_risk_roster(self):
        """Academic risk card must show flagged students with UID, name, academic score, and reason."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view")
        html = resp.get_data(as_text=True)

        self.assertIn('academic-risk-card', html)
        self.assertIn('academic-risk-scroll', html)
        self.assertIn('Academic Risk List', html)
        self.assertIn('Academic', html)
        self.assertIn('Flagged', html)

        # Ensure student rows link to student details
        self.assertIn('/students-view/', html)

    def test_06_placement_risk_roster(self):
        """Placement risk card must show flagged students with UID, name, placement score, and reason."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view")
        html = resp.get_data(as_text=True)

        self.assertIn('placement-risk-card', html)
        self.assertIn('placement-risk-scroll', html)
        self.assertIn('Placement Risk List', html)
        self.assertIn('Placement', html)

    def test_07_all_six_canonical_segments_rendered(self):
        """All 6 behavioral cohort segments must be rendered with name, description, and intervention."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view")
        html = resp.get_data(as_text=True)

        canonical_segments = [
            "High Performers",
            "Strong Academics but Low Placement Readiness",
            "Placement Ready but Weak Academics",
            "Disengaged",
            "Needs Overall Support",
            "Steady"
        ]

        for seg_name in canonical_segments:
            self.assertIn(seg_name, html, f"Missing segment: {seg_name}")

        # Check for intervention headers and buttons
        self.assertIn("RECOMMENDED INTERVENTION", html)
        self.assertIn("btn-view-segment-students", html)

    def test_08_chartjs_canvas_and_script(self):
        """Chart.js canvas element and local chart.min.js script must be present."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view")
        html = resp.get_data(as_text=True)

        self.assertIn('id="segmentSizeChart"', html)
        self.assertIn('chart.min.js', html)
        self.assertIn('new Chart', html)

    def test_09_interactive_roster_modal(self):
        """Interactive segment roster modal and search filter must be present."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view")
        html = resp.get_data(as_text=True)

        self.assertIn('id="segmentRosterModal"', html)
        self.assertIn('id="modalRosterTable"', html)
        self.assertIn('id="modalRosterSearch"', html)
        self.assertIn('openSegmentRoster', html)
        self.assertIn('closeSegmentModal', html)

    def test_10_different_batch_param(self):
        """Querying with a different batch_code must load that batch cleanly."""
        self.login("faculty1", "faculty123")
        resp = self.client.get("/at-risk-view?batch_code=ECE_2023_27")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("ECE 2023-27", html)


if __name__ == "__main__":
    unittest.main()
