"""
=============================================================================
Smart Campus Analytics - Scoring & Explainability Engine (Phase 2)
=============================================================================
This module computes student performance metrics, risk classifications,
rule-based cohort segments, and explainability contributions:

1. Indicator Normalization (0-100 scale):
   - Examinations (15%): End-sem exam average normalized from 60-point scale.
   - Internal assessments (15%): Internal average normalized from 40-point scale.
   - Attendance (15%): Overall attendance percentage (0-100).
   - LMS activity (10%): Composite of assignment completion, login frequency,
     resources downloaded, and forum posts.
   - Placement participation and tests (20%): Aptitude, coding, mock interview,
     and campus recruitment drive participation.
   - Skills (10%): Mean of Python, SQL, problem solving, communication,
     teamwork, and leadership scores.
   - Extracurricular (8%): Total events, clubs, hackathons, certs, workshops
     normalized against benchmarks.
   - Feedback (7%): Mean of student satisfaction, faculty feedback, course rating,
     infrastructure rating, and overall experience normalized from 5-point scale.

2. Composite & Sub-Scores:
   - Success Score (0-100): Weighted sum of all 8 normalized indicators (total 100).
   - Academic Readiness (0-100): Weighted sum of Attendance, Internal, Exams, and LMS.
   - Placement Readiness (0-100): Weighted sum of Placement, Skills, and Extracurricular.

3. Risk Rules:
   - High ("Needs attention"): Score < 50, OR Attendance < 65%, OR Backlogs >= 3.
   - Medium: Score 50-64 (without High risk triggers).
   - Low: Score >= 65 (without High risk triggers).
   - Academic risk: Academic sub-score < 50.
   - Placement risk: Placement sub-score < 50.

4. Rule-Based Cohort Segments:
   - High Performers
   - Strong Academics but Low Placement Readiness
   - Placement Ready but Weak Academics
   - Disengaged
   - Needs Overall Support
   - Steady

5. Explainability & Actionable Recommendations:
   - Contribution = Weight * (Student Value - Batch Average) / 100
   - Generates plain-English reasons for the top 3 negative contributors.
   - Provides targeted suggested interventions for each negative contributor.
=============================================================================
"""

import os
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import numpy as np
import pandas as pd

# -----------------------------------------------------------------------------
# Configuration & Weights
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "campus.db"

# Official 8-indicator weights (sum = 100)
INDICATOR_WEIGHTS: Dict[str, float] = {
    "Examinations": 15.0,
    "Internal assessments": 15.0,
    "Attendance": 15.0,
    "LMS activity": 10.0,
    "Placement participation and tests": 20.0,
    "Skills": 10.0,
    "Extracurricular": 8.0,
    "Feedback": 7.0,
}

# Sub-score indicators & respective weights within the sub-scores
ACADEMIC_SUB_INDICATORS: List[str] = [
    "Examinations",
    "Internal assessments",
    "Attendance",
    "LMS activity",
]  # Weights: 15 + 15 + 15 + 10 = 55.0

PLACEMENT_SUB_INDICATORS: List[str] = [
    "Placement participation and tests",
    "Skills",
    "Extracurricular",
]  # Weights: 20 + 10 + 8 = 38.0

# Intervention playbook: tailored suggested actions per negative indicator
SUGGESTED_ACTIONS: Dict[str, str] = {
    "Attendance": "Arrange a 1-on-1 mentor meeting to understand absence causes and issue an attendance warning notice.",
    "Examinations": "Schedule remedial tutoring sessions and review previous exam papers with course instructors.",
    "Internal assessments": "Pair with a high-performing peer study partner and schedule weekly assignment review checkpoints.",
    "LMS activity": "Trigger an LMS re-engagement prompt and verify student has reliable portal and digital device access.",
    "Placement participation and tests": "Enroll in targeted aptitude bootcamps and conduct 1-on-1 mock technical interview coaching.",
    "Skills": "Assign hands-on practical lab coding exercises in Python/SQL and recommend self-paced certification tracks.",
    "Extracurricular": "Encourage student to join a technical club or participate in upcoming hackathons and departmental workshops.",
    "Feedback": "Schedule a pastoral counselling check-in to discuss student satisfaction, campus environment, and well-being.",
}


# -----------------------------------------------------------------------------
# Step 1: Normalize Indicators to 0-100 Scale
# -----------------------------------------------------------------------------
def normalize_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalizes every raw student indicator from its native domain range
    to a standardized 0-100 percentage scale.
    """
    norm_df = pd.DataFrame(index=df.index)

    # 1. Examinations (raw exam_avg is out of 60.0)
    if "exam_avg" in df.columns:
        norm_df["norm_examinations"] = np.clip((df["exam_avg"] / 60.0) * 100.0, 0.0, 100.0)
    else:
        norm_df["norm_examinations"] = 50.0

    # 2. Internal assessments (raw internal_avg is out of 40.0)
    if "internal_avg" in df.columns:
        norm_df["norm_internal"] = np.clip((df["internal_avg"] / 40.0) * 100.0, 0.0, 100.0)
    else:
        norm_df["norm_internal"] = 50.0

    # 3. Attendance (attendance_overall is already 0.0 - 100.0%)
    if "attendance_overall" in df.columns:
        norm_df["norm_attendance"] = np.clip(df["attendance_overall"], 0.0, 100.0)
    else:
        norm_df["norm_attendance"] = 75.0

    # 4. LMS activity (composite of assignment completion, login frequency, resources, forums)
    lms_assignment = df["lms_assignment_pct"] if "lms_assignment_pct" in df.columns else pd.Series(50.0, index=df.index)
    lms_logins = np.clip((df["lms_login_freq"] / 60.0) * 100.0, 0.0, 100.0) if "lms_login_freq" in df.columns else lms_assignment
    lms_resources = np.clip((df["lms_resources"] / 50.0) * 100.0, 0.0, 100.0) if "lms_resources" in df.columns else lms_assignment
    lms_forums = np.clip((df["lms_forum_posts"] / 30.0) * 100.0, 0.0, 100.0) if "lms_forum_posts" in df.columns else lms_assignment

    norm_df["norm_lms"] = (
        0.40 * lms_assignment +
        0.30 * lms_logins +
        0.15 * lms_resources +
        0.15 * lms_forums
    )

    # 5. Placement participation and tests (aptitude, coding, mock interview + drives attended)
    tests_avg = (
        df.get("aptitude_score", 50.0) +
        df.get("coding_score", 50.0) +
        df.get("mock_interview", 50.0)
    ) / 3.0
    drives_comp = np.clip((df.get("drives_attended", 0) / 10.0) * 100.0, 0.0, 100.0)

    norm_df["norm_placement"] = 0.80 * tests_avg + 0.20 * drives_comp

    # 6. Skills (mean of 6 technical & soft skills: python, sql, problem solving, communication, teamwork, leadership)
    norm_df["norm_skills"] = (
        df.get("python_score", 50.0) +
        df.get("sql_score", 50.0) +
        df.get("problem_solving", 50.0) +
        df.get("skill_communication", 50.0) +
        df.get("teamwork", 50.0) +
        df.get("leadership", 50.0)
    ) / 6.0

    # 7. Extracurricular (sum of events, clubs, hackathons, certs, workshops out of benchmark 30 activities)
    total_activities = (
        df.get("events_attended", 0) +
        df.get("clubs_joined", 0) +
        df.get("hackathons", 0) +
        df.get("certifications", 0) +
        df.get("workshops", 0)
    )
    norm_df["norm_extracurricular"] = np.clip((total_activities / 30.0) * 100.0, 0.0, 100.0)

    # 8. Feedback (mean of 5 feedback ratings on 1.0 - 5.0 scale normalized to 0-100)
    feedback_avg = (
        df.get("student_satisfaction", 3.0) +
        df.get("faculty_feedback", 3.0) +
        df.get("course_rating", 3.0) +
        df.get("infrastructure_rating", 3.0) +
        df.get("overall_experience", 3.0)
    ) / 5.0
    norm_df["norm_feedback"] = np.clip((feedback_avg / 5.0) * 100.0, 0.0, 100.0)

    return norm_df


# -----------------------------------------------------------------------------
# Step 2: Compute Composite Success Score & Readiness Sub-Scores
# -----------------------------------------------------------------------------
def compute_scores(df: pd.DataFrame, norm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes:
      - Success Score (0-100) using 8 indicator weights
      - Academic Readiness sub-score (0-100)
      - Placement Readiness sub-score (0-100)
    """
    scores_df = pd.DataFrame(index=df.index)

    # 1. Overall Success Score (0-100)
    success_score = (
        INDICATOR_WEIGHTS["Examinations"] * norm_df["norm_examinations"] +
        INDICATOR_WEIGHTS["Internal assessments"] * norm_df["norm_internal"] +
        INDICATOR_WEIGHTS["Attendance"] * norm_df["norm_attendance"] +
        INDICATOR_WEIGHTS["LMS activity"] * norm_df["norm_lms"] +
        INDICATOR_WEIGHTS["Placement participation and tests"] * norm_df["norm_placement"] +
        INDICATOR_WEIGHTS["Skills"] * norm_df["norm_skills"] +
        INDICATOR_WEIGHTS["Extracurricular"] * norm_df["norm_extracurricular"] +
        INDICATOR_WEIGHTS["Feedback"] * norm_df["norm_feedback"]
    ) / 100.0
    scores_df["success_score"] = np.round(success_score, 2)

    # 2. Academic Readiness Sub-Score (0-100)
    # Sum of weights: 15 + 15 + 15 + 10 = 55.0
    academic_sub = (
        INDICATOR_WEIGHTS["Examinations"] * norm_df["norm_examinations"] +
        INDICATOR_WEIGHTS["Internal assessments"] * norm_df["norm_internal"] +
        INDICATOR_WEIGHTS["Attendance"] * norm_df["norm_attendance"] +
        INDICATOR_WEIGHTS["LMS activity"] * norm_df["norm_lms"]
    ) / 55.0
    scores_df["academic_subscore"] = np.round(academic_sub, 2)

    # 3. Placement Readiness Sub-Score (0-100)
    # Sum of weights: 20 + 10 + 8 = 38.0
    placement_sub = (
        INDICATOR_WEIGHTS["Placement participation and tests"] * norm_df["norm_placement"] +
        INDICATOR_WEIGHTS["Skills"] * norm_df["norm_skills"] +
        INDICATOR_WEIGHTS["Extracurricular"] * norm_df["norm_extracurricular"]
    ) / 38.0
    scores_df["placement_subscore"] = np.round(placement_sub, 2)

    return scores_df


# -----------------------------------------------------------------------------
# Step 3: Evaluate Risk Rules & Rule-Based Segments
# -----------------------------------------------------------------------------
def assign_risks_and_segments(
    df: pd.DataFrame,
    norm_df: pd.DataFrame,
    scores_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Evaluates:
      - Overall Risk: High, Medium, Low
      - "Needs Attention" flag (High = Needs Attention)
      - Academic Risk (Academic Readiness < 50)
      - Placement Risk (Placement Readiness < 50)
      - Consolidated risk flag ('both', 'academic', 'placement', 'none')
      - Rule-based segments:
        * High Performers
        * Strong Academics but Low Placement Readiness
        * Placement Ready but Weak Academics
        * Disengaged
        * Needs Overall Support
        * Steady
    """
    res_df = pd.DataFrame(index=df.index)

    # Risk rule thresholds:
    # High if score < 50, OR attendance < 65%, OR backlogs >= 3
    attendance_col = df["attendance_overall"] if "attendance_overall" in df.columns else norm_df["norm_attendance"]
    backlogs_col = df["backlogs"] if "backlogs" in df.columns else pd.Series(0, index=df.index)

    high_risk_condition = (
        (scores_df["success_score"] < 50.0) |
        (attendance_col < 65.0) |
        (backlogs_col >= 3)
    )

    # Medium if 50 <= score < 65 and not High
    medium_risk_condition = (~high_risk_condition) & (scores_df["success_score"] < 65.0)

    # Low if score >= 65 and not High
    low_risk_condition = (~high_risk_condition) & (scores_df["success_score"] >= 65.0)

    risk_levels = np.select(
        [high_risk_condition, medium_risk_condition, low_risk_condition],
        ["High", "Medium", "Low"],
        default="Medium"
    )
    res_df["risk_level"] = risk_levels
    res_df["needs_attention"] = (risk_levels == "High").astype(int)

    # Domain risk sub-scores (< 50)
    acad_risk = (scores_df["academic_subscore"] < 50.0).astype(int)
    place_risk = (scores_df["placement_subscore"] < 50.0).astype(int)
    res_df["risk_academic"] = acad_risk
    res_df["risk_placement"] = place_risk

    # Consolidated risk flag
    risk_flags = np.select(
        [
            (acad_risk == 1) & (place_risk == 1),
            (acad_risk == 1) & (place_risk == 0),
            (acad_risk == 0) & (place_risk == 1),
        ],
        ["both", "academic", "placement"],
        default="none"
    )
    res_df["risk_flag"] = risk_flags

    # -------------------------------------------------------------------------
    # Rule-Based Cohort Segments
    # -------------------------------------------------------------------------
    segments = []
    for i in range(len(df)):
        score_val = scores_df["success_score"].iloc[i]
        acad_val = scores_df["academic_subscore"].iloc[i]
        place_val = scores_df["placement_subscore"].iloc[i]
        att_val = attendance_col.iloc[i]
        lms_val = norm_df["norm_lms"].iloc[i]
        backlog_val = backlogs_col.iloc[i]
        is_high_risk = (risk_levels[i] == "High")

        # 1. High Performers: Solid high score (>= 65.0) and healthy indicators
        if score_val >= 65.0 and not is_high_risk:
            seg = "High Performers"

        # 2. Disengaged: Severe drop in attendance (< 60%) alongside low LMS or backlogs
        elif att_val < 60.0 and (lms_val < 40.0 or backlog_val >= 3):
            seg = "Disengaged"

        # 3. Placement Ready but Weak Academics:
        # Placement is viable (>= 48.0 or place > acad) while academic readiness is struggling (< 50.0)
        elif (place_val >= 48.0 or place_val > acad_val) and acad_val < 50.0:
            seg = "Placement Ready but Weak Academics"

        # 4. Strong Academics but Low Placement Readiness:
        # Academic readiness is safe (>= 50.0) but placement readiness is lagging (< 50.0)
        elif acad_val >= 50.0 and place_val < 50.0:
            seg = "Strong Academics but Low Placement Readiness"

        # 5. Needs Overall Support: Struggling in both academic and placement domains
        elif acad_val < 50.0 and place_val < 50.0:
            seg = "Needs Overall Support"

        # 6. Steady: Solid, stable cohort meeting benchmarks without acute deficits
        else:
            seg = "Steady"

        segments.append(seg)

    res_df["segment"] = segments
    return res_df


# -----------------------------------------------------------------------------
# Step 4: Explainability Engine (Batch-Relative Contribution & Actions)
# -----------------------------------------------------------------------------
INDICATOR_COL_MAPPING: Dict[str, str] = {
    "Examinations": "norm_examinations",
    "Internal assessments": "norm_internal",
    "Attendance": "norm_attendance",
    "LMS activity": "norm_lms",
    "Placement participation and tests": "norm_placement",
    "Skills": "norm_skills",
    "Extracurricular": "norm_extracurricular",
    "Feedback": "norm_feedback",
}


def compute_batch_averages(
    df: pd.DataFrame,
    norm_df: pd.DataFrame
) -> Dict[str, Dict[str, float]]:
    """
    Computes the average score for each normalized indicator across each batch.
    Returns: {batch_code: {indicator_name: batch_mean}}
    """
    batch_averages = {}
    combined_df = norm_df.copy()
    combined_df["batch_code"] = df["batch_code"].values

    for batch_code, group in combined_df.groupby("batch_code"):
        means = {}
        for indicator_name, col_name in INDICATOR_COL_MAPPING.items():
            means[indicator_name] = float(group[col_name].mean())
        batch_averages[batch_code] = means

    return batch_averages


def explain_student(
    student_row: pd.Series,
    student_norm: pd.Series,
    batch_means: Dict[str, float]
) -> Dict[str, Any]:
    """
    Calculates indicator contributions for a single student relative to their batch:
      Contribution = Weight * (Student Value - Batch Average) / 100

    Extracts:
      - All indicator contributions
      - Top 3 negative contributors (metrics pulling the student down most)
      - Plain-English reason sentences
      - Suggested actionable interventions
    """
    contributions = []

    for indicator_name, col_name in INDICATOR_COL_MAPPING.items():
        weight = INDICATOR_WEIGHTS[indicator_name]
        student_val = float(student_norm[col_name])
        batch_avg = float(batch_means.get(indicator_name, 50.0))

        diff = student_val - batch_avg
        contribution = (weight * diff) / 100.0

        contributions.append({
            "indicator": indicator_name,
            "weight": weight,
            "student_value": round(student_val, 1),
            "batch_average": round(batch_avg, 1),
            "difference": round(diff, 1),
            "contribution": round(contribution, 2),
        })

    # Filter negative contributors (where student score is below batch average)
    negative_contributors = [c for c in contributions if c["difference"] < 0]

    # Sort ascending by contribution (i.e. largest negative point loss first)
    negative_contributors.sort(key=lambda x: x["contribution"])

    top_3_negative = negative_contributors[:3]

    reasons: List[str] = []
    actions: List[str] = []

    for item in top_3_negative:
        pts_below = abs(item["difference"])
        ind_name = item["indicator"]
        loss = abs(item["contribution"])

        # Construct clear plain-English explanation sentence
        reason_text = (
            f"{ind_name} is {pts_below:.1f} points below batch average "
            f"({item['student_value']:.1f} vs batch avg {item['batch_average']:.1f}, "
            f"reducing score by {loss:.2f} pts)"
        )
        action_text = SUGGESTED_ACTIONS.get(
            ind_name,
            f"Review student performance in {ind_name} and schedule a follow-up."
        )

        reasons.append(reason_text)
        actions.append(action_text)

    # Graceful handling for students excelling across all or most indicators
    if not reasons:
        reasons.append("All performance indicators meet or exceed the batch average.")
        actions.append("Nominate student for peer mentorship, technical leadership, or honors recognition.")

    return {
        "uid": student_row.get("uid"),
        "name": student_row.get("name"),
        "batch_code": student_row.get("batch_code"),
        "all_contributions": contributions,
        "top_negative_contributors": top_3_negative,
        "reasons": reasons,
        "actions": actions,
    }


def compute_all_explainability(
    df: pd.DataFrame,
    norm_df: pd.DataFrame,
    batch_means: Dict[str, Dict[str, float]]
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """
    Computes explainability reasons and actions for all students in the cohort.
    Returns: (reasons_json_list, actions_json_list, full_explain_objects)
    """
    reasons_json_list = []
    actions_json_list = []
    full_explain_objects = []

    for idx in range(len(df)):
        student_row = df.iloc[idx]
        student_norm = norm_df.iloc[idx]
        batch_code = student_row.get("batch_code", "DEFAULT")
        b_means = batch_means.get(batch_code, {})

        explain_res = explain_student(student_row, student_norm, b_means)
        full_explain_objects.append(explain_res)
        reasons_json_list.append(json.dumps(explain_res["reasons"]))
        actions_json_list.append(json.dumps(explain_res["actions"]))

    return reasons_json_list, actions_json_list, full_explain_objects


# -----------------------------------------------------------------------------
# Step 5: Full Pipeline Execution & Database Synchronization
# -----------------------------------------------------------------------------
def run_scoring_pipeline(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Executes the complete scoring pipeline on a student DataFrame:
    1. Normalizes indicators to 0-100.
    2. Computes composite Success Score, Academic sub-score, and Placement sub-score.
    3. Evaluates risks and segments.
    4. Computes explainability contributions and suggested actions.
    
    Returns:
      - Enriched DataFrame with all computed scores and attributes
      - Summary dictionary with batch-level insights
    """
    # 1. Normalization
    norm_df = normalize_indicators(df)

    # 2. Scores
    scores_df = compute_scores(df, norm_df)

    # 3. Risks & Segments
    risks_df = assign_risks_and_segments(df, norm_df, scores_df)

    # 4. Batch Averages & Explainability
    batch_means = compute_batch_averages(df, norm_df)
    reasons_json, actions_json, explain_objs = compute_all_explainability(df, norm_df, batch_means)

    # Assemble master scored DataFrame
    scored_df = df.copy()
    scored_df["success_score"] = scores_df["success_score"]
    scored_df["academic_subscore"] = scores_df["academic_subscore"]
    scored_df["placement_subscore"] = scores_df["placement_subscore"]
    scored_df["risk_level"] = risks_df["risk_level"]
    scored_df["needs_attention"] = risks_df["needs_attention"]
    scored_df["risk_academic"] = risks_df["risk_academic"]
    scored_df["risk_placement"] = risks_df["risk_placement"]
    scored_df["risk_flag"] = risks_df["risk_flag"]
    scored_df["segment"] = risks_df["segment"]
    scored_df["top_reasons"] = reasons_json
    scored_df["top_actions"] = actions_json

    # Attach normalized columns as well for granular inspection
    for col in norm_df.columns:
        scored_df[col] = np.round(norm_df[col], 2)

    summary = {
        "total_students": len(scored_df),
        "batch_means": batch_means,
        "explain_objs": explain_objs,
    }

    return scored_df, summary


def update_database_scores(scored_df: pd.DataFrame, db_path: Optional[Path] = None):
    """
    Synchronizes newly computed scores, sub-scores, risks, segments, and explainability
    into the SQLite database at data/campus.db.
    """
    db_file = db_path or DEFAULT_DB_PATH
    if not db_file.exists():
        print(f"[WARNING] Database not found at {db_file}. Skipping DB update.")
        return

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Ensure all required columns exist in the 'students' table
    existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(students);").fetchall()]

    columns_to_add = {
        "academic_subscore": "REAL",
        "placement_subscore": "REAL",
        "risk_level": "TEXT",
        "needs_attention": "INTEGER",
        "segment": "TEXT",
        "top_reasons": "TEXT",
        "top_actions": "TEXT",
    }

    for col_name, col_type in columns_to_add.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE students ADD COLUMN {col_name} {col_type};")

    # Update student rows in batch
    update_rows = []
    for _, row in scored_df.iterrows():
        update_rows.append((
            float(row["success_score"]),
            float(row["academic_subscore"]),
            float(row["placement_subscore"]),
            str(row["risk_level"]),
            int(row["needs_attention"]),
            int(row["risk_academic"]),
            int(row["risk_placement"]),
            str(row["risk_flag"]),
            str(row["segment"]),
            str(row["top_reasons"]),
            str(row["top_actions"]),
            str(row["uid"])
        ))

    cursor.executemany("""
        UPDATE students SET
            success_score = ?,
            academic_subscore = ?,
            placement_subscore = ?,
            risk_level = ?,
            needs_attention = ?,
            risk_academic = ?,
            risk_placement = ?,
            risk_flag = ?,
            segment = ?,
            top_reasons = ?,
            top_actions = ?
        WHERE uid = ?;
    """, update_rows)

    conn.commit()
    conn.close()
    print(f"[SUCCESS] Updated {len(update_rows)} student records in {db_file}.")


def load_and_score(db_path: Optional[Path] = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Helper function to load student records from SQLite, execute scoring,
    and return the enriched DataFrame.
    """
    db_file = db_path or DEFAULT_DB_PATH
    if not db_file.exists():
        raise FileNotFoundError(f"Database not found at {db_file}. Please run data pipeline first.")

    conn = sqlite3.connect(db_file)
    df = pd.read_sql("SELECT * FROM students;", conn)
    conn.close()

    scored_df, summary = run_scoring_pipeline(df)
    return scored_df, summary


# -----------------------------------------------------------------------------
# Standalone Execution Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("SMART CAMPUS ANALYTICS: RUNNING SCORING ENGINE (PHASE 2)")
    print("=" * 70)

    try:
        scored_df, summary = load_and_score()
        update_database_scores(scored_df)

        print("\n--- Summary Statistics Across Batches ---")
        for batch_code, grp in scored_df.groupby("batch_code"):
            print(f"\nBatch: {batch_code} (N = {len(grp)})")
            print(f"  Success Score: Mean = {grp['success_score'].mean():.2f}, "
                  f"Min = {grp['success_score'].min():.2f}, Max = {grp['success_score'].max():.2f}")
            print(f"  Academic Sub-Score: Mean = {grp['academic_subscore'].mean():.2f}")
            print(f"  Placement Sub-Score: Mean = {grp['placement_subscore'].mean():.2f}")
            print(f"  Risk Breakdown: {grp['risk_level'].value_counts().to_dict()}")
            print(f"  Needs Attention: {grp['needs_attention'].sum()}")
            print(f"  Segment Breakdown: {grp['segment'].value_counts().to_dict()}")

        print("\n--- Sample Explainability Output (Student 1) ---")
        first_explain = summary["explain_objs"][0]
        print(f"Student UID: {first_explain['uid']} ({first_explain['name']}) [Batch: {first_explain['batch_code']}]")
        print("Reasons:")
        for r in first_explain["reasons"]:
            print(f"  * {r}")
        print("Suggested Actions:")
        for a in first_explain["actions"]:
            print(f"  -> {a}")

        print("\n[SUCCESS] Phase 2 scoring completed successfully.\n")

    except Exception as e:
        print(f"[ERROR] Failed during scoring execution: {e}")
        raise
