# Smart Campus Analytics: Student Scoring & Explainability Framework

Welcome to the **Student Success Scoring Framework** for Innovista University. This document explains in clear, everyday language how student performance is evaluated, how risk levels are flagged, how student cohorts are segmented, and how teachers and counselors can see the exact reasons and recommended interventions for students who need assistance.

---

## 1. Executive Overview

The Smart Campus Analytics system combines 8 student performance indicators into a single, transparent **Success Score (0 to 100)**. 

Rather than judging a student solely on exam marks, the Success Score provides a 360-degree view of student growth, covering class attendance, continuous internal work, laboratory coding and soft skills, career placement readiness, campus involvement, and learning management system (LMS) engagement.

In addition to the overall score, the platform calculates:
1. **Academic Readiness Sub-Score (0–100)**: Measures classroom and curriculum mastery.
2. **Placement Readiness Sub-Score (0–100)**: Measures job-readiness, coding ability, and extracurricular drive.
3. **Risk Classifications**: Identifies students needing immediate intervention ("Needs Attention").
4. **Cohort Segments**: Classifies students into six actionable categories for targeted support.
5. **Point-by-Point Explainability**: Tells advisors *exactly* how many points a student is behind their batch average and gives one concrete intervention step for each issue.

---

## 2. The 8 Indicators & Normalization

All student data is first converted (normalized) to a uniform **0 to 100 scale** before weighting. This ensures that a 40-point internal test, a 60-point semester exam, and an 80% attendance rate are compared fairly.

| # | Indicator Name | Weight | Native Scale | How It Is Normalized to 0–100 | What It Measures |
|---|---|:---:|---|---|---|
| **1** | **Examinations** | **15%** | 0 – 60 marks | `(Exam Avg / 60) × 100` | Major semester examination mastery across all enrolled courses. |
| **2** | **Internal Assessments** | **15%** | 0 – 40 marks | `(Internal Avg / 40) × 100` | Continuous evaluation, mid-term tests, lab practicals, and quizzes. |
| **3** | **Attendance** | **15%** | 0 – 100% | Directly `Attendance %` | Physical lecture and laboratory session presence. |
| **4** | **LMS Activity** | **10%** | Diverse metrics | `40% Assignments + 30% Logins + 15% Downloads + 15% Forum Posts` | Digital engagement on the college learning portal (submitting assignments, downloading lecture slides, asking questions). |
| **5** | **Placement Participation & Tests** | **20%** | 0 – 100 tests + 0–10 drives | `80% Test Avg (Aptitude, Coding, Mock Interview) + 20% Drive Participation` | Readiness for campus recruitment drives, competitive problem-solving aptitude, and mock interviews. |
| **6** | **Skills** | **10%** | 0 – 100 scores | Mean of Python, SQL, Problem Solving, Communication, Teamwork, and Leadership | Technical competence and essential soft skills assessed during laboratories and bootcamps. |
| **7** | **Extracurricular** | **8%** | Total counts (0–30) | `(Total Activities / 30) × 100` | Active involvement in campus clubs, hackathons, seminars, certifications, and technical workshops. |
| **8** | **Feedback** | **7%** | 1.0 – 5.0 rating | `(Average Rating / 5.0) × 100` | Student course satisfaction, faculty feedback ratings, infrastructure satisfaction, and campus experience. |
| **Total** | | **100%** | | | **Comprehensive composite weighting** |

---

## 3. Score Calculations

### 3.1 Composite Success Score (0 – 100)
$$\text{Success Score} = \sum_{i=1}^{8} \left( \frac{\text{Weight}_i \times \text{Normalized Score}_i}{100} \right)$$

Every student receives a single score from **0.0 to 100.0**. Higher numbers represent stronger overall balance between curricular discipline and career preparation.

### 3.2 Academic Readiness Sub-Score (0 – 100)
Combines the four core classroom metrics (Attendance, Internal Assessments, Examinations, and LMS Activity) which have a combined weight of 55 points:
$$\text{Academic Readiness} = \frac{(15 \times \text{Exams}) + (15 \times \text{Internal}) + (15 \times \text{Attendance}) + (10 \times \text{LMS})}{55}$$

### 3.3 Placement Readiness Sub-Score (0 – 100)
Combines the three career-launching metrics (Placement Tests & Drives, Skills, and Extracurricular Activities) which have a combined weight of 38 points:
$$\text{Placement Readiness} = \frac{(20 \times \text{Placement}) + (10 \times \text{Skills}) + (8 \times \text{Extracurricular})}{38}$$

---

## 4. Risk Classification Rules

The platform classifies students into three clear risk tiers to help faculty prioritize time and counseling resources:

```
                          ┌─────────────────────────────┐
                          │     Student Performance     │
                          └──────────────┬──────────────┘
                                         │
                   Score < 50 OR Attendance < 65% OR Backlogs >= 3 ?
                                  /            \
                             YES /              \ NO
                                ▼                ▼
                      ┌───────────────┐     Score >= 65 ?
                      │   HIGH RISK   │       /       \
                      │Needs Attention│  YES /         \ NO
                      └───────────────┘     ▼           ▼
                                    ┌───────────┐  ┌────────────┐
                                    │ LOW RISK  │  │MEDIUM RISK │
                                    └───────────┘  └────────────┘
```

### Risk Level Rules:
1. **High Risk ("Needs Attention")**:
   A student is placed in **High Risk** if **any one** of the following warning conditions is triggered:
   - Success Score is less than **50.0**, **OR**
   - Overall Attendance is less than **65.0%**, **OR**
   - Active Backlogs are **3 or more**.
   *Note: In administrative dashboards, all High Risk students are labeled as **"Needs Attention"**.*

2. **Medium Risk**:
   - The student does not meet any High Risk condition, and their Success Score is between **50.0 and 64.9**.
   - These students are passing comfortably but benefit from light check-ins and encouragement.

3. **Low Risk**:
   - The student does not meet any High Risk condition, and their Success Score is **65.0 or above**.
   - These students demonstrate consistent, healthy academic habits and active participation.

### Domain-Specific Risk Flags:
- **Academic Risk**: Triggered if the **Academic Readiness Sub-Score < 50.0**.
- **Placement Risk**: Triggered if the **Placement Readiness Sub-Score < 50.0**.
- **Consolidated Flag**: Labeled as `'academic'`, `'placement'`, `'both'`, or `'none'`.

---

## 5. Rule-Based Cohort Segments

To avoid a "one-size-fits-all" advisory approach, students are sorted into six rule-based segments based on their strengths and deficits:

| Segment Name | Definition & Rule Criteria | Recommended Advisory Focus |
|---|---|---|
| **High Performers** | Success Score $\ge 65.0$ with no active high-risk flags. | Nominate for academic honors, undergraduate research, and student peer mentoring roles. |
| **Strong Academics but Low Placement Readiness** | Academic Readiness $\ge 50.0$, but Placement Readiness $< 50.0$. | Provide resume clinics, coding interview bootcamps, and soft skill communication workshops. |
| **Placement Ready but Weak Academics** | Placement Readiness $\ge 48.0$ (or higher than academic), but Academic Readiness $< 50.0$. | Assign remedial tutoring in weak theory subjects and enforce strict attendance monitoring. |
| **Disengaged** | Attendance $< 60.0\%$ combined with low LMS activity ($< 40.0$) or $\ge 3$ backlogs. | Immediate pastoral counseling, parental notification, and investigation of personal or health issues. |
| **Needs Overall Support** | Both Academic Readiness $< 50.0$ and Placement Readiness $< 50.0$. | Intensive academic support plan, weekly mentor checkpoints, and gradual remedial milestones. |
| **Steady** | Both sub-scores $\ge 50.0$, steady progress without acute deficits ($50.0 \le \text{Score} < 65.0$). | Keep on track, encourage technical certifications, and prepare for placement tests early. |

---

## 6. Explainability: The "Why" Behind Every Score

Administrators and faculty should never have to guess why a score is low. The platform uses a transparent **Batch-Relative Contribution Formula**:

$$\text{Contribution} = \frac{\text{Weight} \times (\text{Student Value} - \text{Batch Average})}{100}$$

### How It Works:
1. **Student Value**: The student's normalized score on that metric (0–100).
2. **Batch Average**: The average normalized score achieved by their direct peer cohort (0–100).
3. **Difference**: Shows whether the student is ahead ($+$) or behind ($-$) their classmates.
4. **Point Contribution**: Shows the exact number of overall points gained or lost on the Success Score.

### Top 3 Negative Contributors:
For each student, the system automatically extracts the **top 3 metrics pulling their score down the most**, translates them into a plain-English explanation, and provides one tailored suggested action.

#### Example Student Profile:
> **Student**: *Ananya Nair (CSE 2023-27)*  
> **Success Score**: 38.4 | **Risk**: High (Needs Attention)
> 
> **Top 3 Reasons:**
> 1. **Placement participation and tests** is 12.9 points below batch average *(22.7 vs batch avg 35.6, reducing score by 2.57 pts)*.
> 2. **Extracurricular** is 19.0 points below batch average *(23.3 vs batch avg 42.3, reducing score by 1.52 pts)*.
> 3. **Internal assessments** is 9.0 points below batch average *(35.8 vs batch avg 44.8, reducing score by 1.35 pts)*.
> 
> **Suggested Actions:**
> 1. *Enroll in targeted aptitude bootcamps and conduct 1-on-1 mock technical interview coaching.*
> 2. *Encourage student to join a technical club or participate in upcoming hackathons and departmental workshops.*
> 3. *Pair with a high-performing peer study partner and schedule weekly assignment review checkpoints.*

---

## 7. Faculty Intervention Playbook

When an advisor opens a student's card, each negative indicator is paired with an actionable recommendation from our standard intervention playbook:

- **Attendance Deficit**:  
  *Action:* Arrange a 1-on-1 mentor meeting to understand absence causes and issue an attendance advisory notice.
- **Examination Deficit**:  
  *Action:* Schedule remedial tutoring sessions and review previous exam papers with course instructors.
- **Internal Assessment Deficit**:  
  *Action:* Pair with a high-performing peer study partner and schedule weekly assignment review checkpoints.
- **LMS Engagement Deficit**:  
  *Action:* Trigger an LMS re-engagement prompt and verify the student has reliable portal and digital device access.
- **Placement & Aptitude Deficit**:  
  *Action:* Enroll in targeted aptitude bootcamps and conduct 1-on-1 mock technical interview coaching.
- **Skill Competency Deficit**:  
  *Action:* Assign hands-on practical lab coding exercises in Python/SQL and recommend self-paced certification tracks.
- **Extracurricular Deficit**:  
  *Action:* Encourage student to join a technical club or participate in upcoming hackathons and departmental workshops.
- **Feedback & Experience Deficit**:  
  *Action:* Schedule a pastoral counselling check-in to discuss student satisfaction, campus environment, and well-being.

---

## 8. Verifying the System

To view the score distribution across all active batches and verify that data integrity constraints are met, run the built-in test suite:

```bash
python test_scoring.py
```

This script:
- Scores all students across CSE 2023-27, CSE 2024-28, and ECE 2023-27.
- Outputs distribution statistics (Mean, Median, Quartiles, Min, Max).
- Displays the exact count and percentage of students in each Risk and Segment tier.
- Prints a sample explainability card for each batch.
- Automatically asserts that all scores remain bounded within `[0.0, 100.0]` and all contributions mathematically reconcile.
