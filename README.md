# InnoVista Smart Campus Analytics: Student Success Platform

A comprehensive, production-ready **Student Success and Early Intervention Platform** built for university leadership, department heads, and faculty advisors. The platform unifies **7 independent campus data sources** into explainable composite scores, predictive risk classifications, and actionable behavioral interventions.

---

## 🌟 Executive Summary

Higher education institutions face critical challenges with late-stage academic failures and career unreadiness. Student data is traditionally fragmented across isolated silos—academic registrar databases, biometric attendance turnstiles, learning management systems (LMS), and placement office trackers.

**Smart Campus Analytics** solves this problem by:
1. **Unifying 7 Data Streams** through an automated 5-step data cleaning and validation pipeline into a single production SQLite database.
2. **Computing an Explainable Success Score (0–100)** across 8 weighted indicators, complemented by distinct **Academic Readiness** and **Placement Readiness** subscores.
3. **Triaging Risk in Real-Time** into High Risk (*"Needs Attention"*), Medium Risk, and Low Risk tiers.
4. **Segmenting Students into 6 Behavioral Cohorts** paired with concrete institutional interventions.
5. **Providing Role-Based Access Control** (Admin vs. Faculty View-Only mode) with mandatory pre-entry security warnings, live scoring recalculation, and immutable audit logging.
6. **Optimizing for All Devices:** Fully responsive layout tested on laptop (1366x768, 1440x900) and tablet (768px, 1024px) screens, complete with a 15-minute inactivity session guard and synthetic data disclaimer.

---

## 🔑 Demo Staff Accounts

| Username | Password | Role | Permissions |
|:---|:---|:---|:---|
| **`admin`** | **`admin123`** | **Admin** | Full read/write access: Add students, inline record editing, CSV upload, data cleaning, and audit inspection. |
| **`faculty1`** | **`faculty123`** | **Faculty** | Read-only access: View cohort metrics, student profiles, risk lists, and data quality reports. Mutation actions are blocked. |

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- **Python 3.10+**
- **pip** (Python package installer)

### 2. Installation
Clone the repository and install the lightweight dependencies (no heavy frontend build tools required):
```powershell
pip install flask pandas numpy werkzeug
```

### 3. Initialize Database & Synthetic Data Pipeline
The project comes with a seeded random data generator producing 180 realistic students across 3 batches (`CSE 2023-27`, `ECE 2023-27`, `CSE 2024-28`):
```powershell
# 1. Generate 7 raw CSV files with realistic correlations and deliberate anomalies
python generate_data.py

# 2. Run the 5-step ETL cleaning pipeline and populate SQLite database
python clean_and_merge.py

# 3. Compute normalized scores, subscores, segments, and explainability contributions
python scoring.py
```

### 4. Run the Web Application
```powershell
python app.py
```
Open your browser to: **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 📱 Application Flow & Features

```
               ┌─────────────┐
               │   /login    │
               └──────┬──────┘
                      ▼
               ┌─────────────┐
               │/select-batch│
               └──────┬──────┘
                      ▼
               ┌─────────────┐
        ┌──────┤  /overview  ├──────────────┐
        │      └──────┬──────┘              │
        ▼             ▼                     ▼
┌──────────────┐┌──────────────┐ ┌──────────────────────┐
│/students-view││/at-risk-view │ │ /data-management-view│
└───────┬──────┘└──────────────┘ └──────────────────────┘
        ▼
┌──────────────────┐
│/students-view/<id│
└──────────────────┘
```

### 1. Authentication (`/login`)
- Split-screen brand hero showcasing InnoVista University emblem and login form.
- Session-based authentication with bcrypt password hashing.
- Password visibility toggle (`👁️` / `🙈`) and invalid credential flash messaging.
- Auto-redirects unauthenticated visits to `/login` across all protected routes.
- Footer disclaimer: *"Demo uses synthetic data generated for this prototype."*

### 2. Cohort Selector (`/select-batch`)
- Displays interactive cards for all academic cohorts:
  - **CSE 2023-27** (60 students • Computer Science & Engineering)
  - **ECE 2023-27** (60 students • Electronics & Communication)
  - **CSE 2024-28** (60 students • Computer Science & Engineering)
- Shows active student count, class average Success Score, and overall attendance.
- Keyboard accessible (`Enter` / `Space` selection).
- Active cohort is stored in session and switchable anytime from the header pill.

### 3. Batch Overview Dashboard (`/overview`)
- **3 Executive Stat Cards:** Total Students, Class Average Success Score, and Students Needing Attention count.
- **Accessible Weights Modal:** *"How is this calculated?"* modal breaking down the 8 indicator weights and formulas.
- **Students Requiring Attention Box:** Scrollable roster strictly sorted lowest score first, with primary concern badges (`Low attendance`, `Multiple backlogs`, `Placement risk`), and a **Download as CSV** button.
- **Key Trends Analytics (Chart.js):**
  1. *Score Distribution by Risk Bands* (Low `<50`, Medium `50-64`, High `65+`).
  2. *Average Attendance Trend by Subject* with 75% benchmark threshold line.
- **3 Module Flow Navigation Cards:** STUDENTS LIST, AT-RISK & SEGMENTS, DATA MANAGEMENT.

### 4. Students Directory (`/students-view`)
- Searchable, filterable table of all cohort students with initials avatar badges, UID, Name, CGPA, Attendance %, Backlogs, Success Score, and colored Risk Flags (🟢 Green, 🟡 Amber, 🔴 Red).
- Live search by student name or UID substring.
- Risk filter (All, High, Medium, Low, Needs Attention).
- Cohort segment dropdown filter.
- Sortable table columns (click any column header to sort ascending/descending).
- 1-click row navigation to detailed student profile.

### 5. Student 360° Detail & Explainability (`/students-view/<uid>`)
- **Profile Header:** Student initials, Name, UID, active batch, cohort segment badge, Success Score, Academic subscore, Placement subscore, and Attendance compliance badge.
- **Why Flagged Panel (Plain-English Diagnostics):** Explains exactly which metrics lag behind batch averages and provides faculty playbooks.
- **Score Breakdown Chart (Chart.js):** Horizontal bar chart comparing the student's normalized score against the cohort average across all 8 indicators.
- **7 Integrated Data Source Cards:**
  1. *Academic Performance:* CGPA, Internals (/40), Exams (/60), Backlogs, and subject-wise breakdown table.
  2. *Attendance Tracking:* Overall %, Subject Average %, Biometric compliance status, and subject attendance table.
  3. *LMS Engagement:* Login frequency, assignment completion %, resources downloaded, forum posts.
  4. *Extracurricular Activities:* Events attended, clubs joined, hackathons, certifications, workshops.
  5. *Placement Readiness:* Aptitude score, coding challenge score, mock interview rating, communication score, recruitment drives attended, offers received.
  6. *Skills Assessment:* Technical scores (Python, SQL, Problem Solving) & Soft Skills (Communication, Teamwork, Leadership).
  7. *Student & Faculty Feedback:* Satisfaction ratings (1–5 scale) across courses, faculty, infrastructure, and overall experience.

### 6. At-Risk Rosters & Behavioral Segments (`/at-risk-view`)
- **Side-by-Side Dual Risk Rosters:**
  - *Academic Risk List:* Flagged for attendance `<65%`, backlogs $\ge 3$, or low exam marks, showing Academic Sub-score and diagnostic reason.
  - *Placement Risk List:* Flagged for low aptitude, coding challenges, or mock interviews, showing Placement Sub-score and diagnostic reason.
- **Chart.js Segment Distribution:** Doughnut chart illustrating student shares across 6 behavioral profiles.
- **6 Behavioral Cohort Segment Cards:**
  1. 🌟 *High Performers:* Honors projects & research fellowships.
  2. 📘 *Strong Academics but Low Placement Readiness:* Interview bootcamps & mock coding clinics.
  3. 💻 *Placement Ready but Weak Academics:* Remedial tutoring & backlog clearing milestones.
  4. ⚠️ *Disengaged:* 1-on-1 counseling, parent-mentor conferences, attendance warnings.
  5. 🚨 *Needs Overall Support:* Individualized Student Support Plan (ISSP).
  6. ⚖️ *Steady:* Milestone check-ins & hackathon encouragement.
- **Interactive Segment Roster Modal:** Click any segment card, button, or chart slice to view its students with live search filtering.

### 7. Data Management & Quality Control (`/data-management-view`)
- **Pre-Entry Security Warning Modal:**
  - Required prompt before modifying records: *"You are about to modify student records. Changes affect scores and risk flags for the whole batch and are logged. Continue?"*
  - Admin proceeds with full access; Faculty receives view-only mode notice.
- **Editable Students Table:** In-table editing of CGPA, marks, attendance, backlogs, LMS, and placement scores.
- **Add Student Form:** Structured form with boundary validation hints.
- **CSV Upload & 5-Step Automated Cleaning Pipeline:** Ingests CSV files, strips UID spaces, drops duplicates, imputes missing numbers, clamps out-of-bounds metrics, recalculates scores, and logs fixes.
- **Data Quality Report:** Ledger of all anomalies detected, fixed, and imputed.
- **Administrative Audit Log:** Immutable audit trail capturing timestamp, staff user, action type (`ADD_STUDENT`, `EDIT_STUDENT`, `CSV_IMPORT`), target UID, and before-and-after diffs.

### 8. Phase 9 Enhancements
- **Synthetic Data Disclaimer Footer:** Small persistent footer on every page: *"Demo uses synthetic data generated for this prototype."*
- **15-Minute Inactivity Auto-Logout:** Dual client-side timer and server-side `before_request` timestamp check automatically logs out inactive staff after 15 minutes, returning them to `/login` with an informational flash alert.
- **Responsive Layout:** Tailored CSS media queries and flexbox/grid containers ensuring full usability across laptops (1366x768, 1440x900) and tablets (768px, 1024px).

---

## 📐 Scoring Formula & Framework

The platform calculates a transparent **Success Score (0–100)**:

$$\text{Success Score} = \sum_{i=1}^{8} \left( \frac{\text{Weight}_i \times \text{Normalized Score}_i}{100} \right)$$

| Indicator Domain | Weight | Native Scale | Normalized Scale |
|:---|:---:|:---|:---:|
| **Examinations** | 15% | 0 – 60 marks | 0 – 100 |
| **Internal Assessments** | 15% | 0 – 40 marks | 0 – 100 |
| **Attendance** | 15% | 0 – 100% | 0 – 100 |
| **Placement Readiness** | 20% | 0 – 100 tests + 0–10 drives | 0 – 100 |
| **LMS Engagement** | 10% | Assignments, Logins, Downloads, Posts | 0 – 100 |
| **Skills Assessment** | 10% | Python, SQL, Problem Solving, Soft Skills | 0 – 100 |
| **Extracurricular Activities** | 8% | Clubs, Hackathons, Certifications, Workshops | 0 – 100 |
| **Feedback Ratings** | 7% | Student & Faculty Feedback (1.0 – 5.0) | 0 – 100 |

*For complete mathematical proofs, normalization steps, subscore formulas, and decision rules, see [SCORING.md](SCORING.md).*

---

## 🎤 Presentation & Demo Script

*A 5-slide pitch deck outline and an exact 3-minute live demonstration script aligned with competition judging criteria are available in [PRESENTATION.md](PRESENTATION.md).*

- **Slide 1:** Problem Understanding & Institutional Value
- **Slide 2:** Multi-Source Data Integration & Cleaning Pipeline
- **Slide 3:** Explainable Success Score, Sub-Scores & Behavioral Cohorts
- **Slide 4:** Interactive Dashboard & Decision-Support UX
- **Slide 5:** Administrative Control, Auditability & Enterprise Scalability
- **3-Minute Demo Script:** Timed walkthrough covering Login, Overview, Student Drill-Down, At-Risk Segments, and Data Management.

---

## 🧪 Automated Test Suites

The project features a comprehensive suite of **7 automated unit and regression test files** containing **266+ test cases**:

```powershell
# Run the complete test suite
python test_phase9_e2e.py
python test_phase8_data_management.py
python test_phase7_at_risk.py
python test_phase6_students.py
python test_phase5_overview.py
python test_frontend_shell.py
python test_backend.py
```

### Test Coverage Highlights:
- **Authentication & Security:** Unauthenticated route rejection (401/302), role-based mutation prevention (403 for Faculty).
- **Session Lifecycle:** 15-minute inactivity session expiration and redirect verification.
- **Data Ingestion & Cleaning:** Out-of-bounds clamping, duplicate removal, median imputation, and UID normalization.
- **Explainability:** Feature attribution breakdown, why-flagged diagnostics, and playbook recommendations.
- **End-to-End User Flow:** Seamless navigation across all 8 pages with 100% pass rate.
