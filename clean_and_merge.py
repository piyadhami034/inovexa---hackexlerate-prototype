"""
clean_and_merge.py
==================
Smart Campus Analytics - Phase 1: Data Cleaning, ETL & Relational Merging

This script performs the complete data cleaning, normalization, transformation,
and ingestion pipeline from raw CSV files into a production SQLite database:
data/campus.db.

Cleaning Pipeline Steps:
------------------------
1. UID Normalization:
   - Removes internal and leading/trailing whitespace.
   - Converts all letters to uppercase (e.g., 'cse2023005' -> 'CSE2023005').
   - Tracks the number of fixed UIDs per file.
2. Duplicate Removal:
   - Identifies and drops exact duplicate records in each CSV.
   - Tracks removed duplicate count.
3. Missing Value Imputation:
   - Identifies NaN cells across numeric features.
   - Imputes missing numeric values using the column median.
   - Tracks total imputed values.
4. Out-of-Range Value Clamping:
   - CGPA: clamped to [0.0, 10.0]
   - Internal marks: clamped to [0.0, 40.0]
   - Exam marks: clamped to [0.0, 60.0]
   - Attendance percentages: clamped to [0.0, 100.0]
   - Skill & Placement test scores: clamped to [0.0, 100.0]
   - Feedback ratings: clamped to [1.0, 5.0]
   - Tracks clamped anomalous values.
5. Type Enforcement:
   - Casts count fields (backlogs, events, clubs, hackathons, certifications, workshops, etc.) to integers.

Engineered Metrics & Relational Schema:
---------------------------------------
- Success Score: Weighted composite index (0-100) reflecting academic, attendance,
  LMS, extracurricular, placement, and skill performance.
- Risk Flags:
  - Academic Risk: CGPA < 6.0 OR backlogs > 2 OR attendance < 65%
  - Placement Risk: Aptitude < 40 OR Coding < 40 OR Mock Interview < 40
  - Consolidated risk flag: 'academic', 'placement', 'both', or 'none'
- Normalized Tables:
  - users (seeded with Admin and Faculty accounts)
  - batches (CSE 2023-27, ECE 2023-27, CSE 2024-28)
  - students (consolidated master profile with KPI scores and risk flags)
  - academic_details (unpivoted subject-level marks)
  - attendance_details (unpivoted subject-level attendance percentages)
  - data_quality_report (audit trail of all data quality fixes applied)
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from werkzeug.security import generate_password_hash

# -----------------------------------------------------------------------------
# Configuration and Path Setup
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "campus.db"

# Batch mapping: map human-readable name to foreign key batch_code
BATCH_NAME_TO_CODE = {
    "CSE 2023-27": "CSE_2023_27",
    "ECE 2023-27": "ECE_2023_27",
    "CSE 2024-28": "CSE_2024_28",
    "CSE_2023_27": "CSE_2023_27",
    "ECE_2023_27": "ECE_2023_27",
    "CSE_2024_28": "CSE_2024_28",
}

# Standard subject mapping for unpivoting detailed academic/attendance records
SUBJECT_MAP = {
    "math": "Mathematics",
    "core1": "Core Subject 1",
    "core2": "Core Subject 2",
    "core3": "Core Subject 3",
    "elective1": "Elective 1",
    "elective2": "Elective 2",
}


class DataCleaner:
    """
    Manages data cleaning, anomaly correction, and audit tracking across datasets.
    """
    def __init__(self):
        # List of tracked issues for the data_quality_report table
        self.quality_report_log = []
        
        # Summary counters
        self.stats = {
            "uid_fixes": 0,
            "duplicates_removed": 0,
            "missing_imputed": 0,
            "out_of_range_clamped": 0,
            "types_enforced": 0,
        }

    def log_issue(self, issue_type: str, description: str, count: int):
        """Record an entry in the quality audit log."""
        if count > 0:
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            self.quality_report_log.append({
                "issue_type": issue_type,
                "description": description,
                "count": count,
                "timestamp": now_iso,
            })

    def normalize_uids(self, df: pd.DataFrame, source_name: str) -> pd.DataFrame:
        """
        Cleaning Step 1: UID Normalization.
        Strips whitespace, removes inner spaces, and converts to uppercase.
        Example: ' cse2023005 ' -> 'CSE2023005', 'CSE 2023010' -> 'CSE2023010'.
        """
        orig_series = df["uid"].astype(str)
        # Remove all whitespace and convert to uppercase
        clean_series = orig_series.str.replace(" ", "", regex=False).str.upper()
        
        # Identify how many UIDs were changed
        inconsistent_mask = (orig_series != clean_series)
        num_fixed = int(inconsistent_mask.sum())
        
        if num_fixed > 0:
            self.stats["uid_fixes"] += num_fixed
            self.log_issue(
                issue_type="UID Normalization",
                description=f"Standardized inconsistent casing/spacing in {source_name}.csv",
                count=num_fixed
            )
            print(f"  [UID Normalization] Fixed {num_fixed} inconsistent UIDs in {source_name}.csv")
            
        df["uid"] = clean_series
        return df

    def remove_duplicates(self, df: pd.DataFrame, source_name: str) -> pd.DataFrame:
        """
        Cleaning Step 2: Duplicate Removal.
        Identifies and removes exact duplicate rows.
        """
        num_duplicates = int(df.duplicated().sum())
        if num_duplicates > 0:
            self.stats["duplicates_removed"] += num_duplicates
            self.log_issue(
                issue_type="Duplicate Removal",
                description=f"Removed exact duplicate rows in {source_name}.csv",
                count=num_duplicates
            )
            print(f"  [Duplicate Removal] Dropped {num_duplicates} duplicate rows from {source_name}.csv")
            df = df.drop_duplicates().reset_index(drop=True)
            
        return df

    def impute_missing_numeric(self, df: pd.DataFrame, source_name: str) -> pd.DataFrame:
        """
        Cleaning Step 3: Missing Value Imputation.
        Fills missing values (NaN) in numeric columns using the column median.
        """
        numeric_cols = [c for c in df.columns if c not in ["uid", "name", "batch"]]
        total_imputed_file = 0
        
        for col in numeric_cols:
            nan_count = int(df[col].isna().sum())
            if nan_count > 0:
                median_val = df[col].median()
                df[col] = df[col].fillna(median_val)
                total_imputed_file += nan_count
                
        if total_imputed_file > 0:
            self.stats["missing_imputed"] += total_imputed_file
            self.log_issue(
                issue_type="Missing Values",
                description=f"Imputed missing numeric values with column medians in {source_name}.csv",
                count=total_imputed_file
            )
            print(f"  [Missing Values] Imputed {total_imputed_file} missing values in {source_name}.csv")
            
        return df

    def clamp_ranges(self, df: pd.DataFrame, source_name: str, column_ranges: dict[str, tuple[float, float]]) -> pd.DataFrame:
        """
        Cleaning Step 4: Out-of-Range Clamping.
        Clamps column values to valid mathematical/domain boundaries [min_val, max_val].
        """
        total_clamped_file = 0
        
        for col, (min_val, max_val) in column_ranges.items():
            if col in df.columns:
                out_of_bounds_mask = (df[col] < min_val) | (df[col] > max_val)
                num_violations = int(out_of_bounds_mask.sum())
                if num_violations > 0:
                    total_clamped_file += num_violations
                    df[col] = df[col].clip(min_val, max_val)
                    
        if total_clamped_file > 0:
            self.stats["out_of_range_clamped"] += total_clamped_file
            self.log_issue(
                issue_type="Out-of-Range Clamping",
                description=f"Clamped values outside boundaries in {source_name}.csv",
                count=total_clamped_file
            )
            print(f"  [Out-of-Range] Clamped {total_clamped_file} out-of-bounds values in {source_name}.csv")
            
        return df

    def enforce_types(self, df: pd.DataFrame, source_name: str, integer_cols: list[str]) -> pd.DataFrame:
        """
        Cleaning Step 5: Type Enforcement.
        Ensures discrete count metrics are typed as integers.
        """
        enforced_count = 0
        for col in integer_cols:
            if col in df.columns:
                df[col] = df[col].round().astype(int)
                enforced_count += len(df)
                
        if enforced_count > 0:
            self.stats["types_enforced"] += len(integer_cols)
            self.log_issue(
                issue_type="Type Enforcement",
                description=f"Enforced integer types on discrete columns {integer_cols} in {source_name}.csv",
                count=len(integer_cols)
            )
            
        return df


def load_and_clean_raw_data() -> tuple[dict[str, pd.DataFrame], DataCleaner]:
    """
    Loads all 7 raw CSV files from data/raw/ and applies the 5-step cleaning pipeline.
    Returns cleaned DataFrames and cleaner instance with audit log.
    """
    cleaner = DataCleaner()
    print("\n" + "=" * 70)
    print("STEP 1: READING AND CLEANING RAW CSV FILES")
    print("=" * 70)

    # 1. Academic Data
    academic_path = RAW_DATA_DIR / "academic.csv"
    academic_df = pd.read_csv(academic_path)
    academic_df = cleaner.normalize_uids(academic_df, "academic")
    academic_df = cleaner.remove_duplicates(academic_df, "academic")
    academic_df = cleaner.impute_missing_numeric(academic_df, "academic")
    
    academic_ranges = {"cgpa": (0.0, 10.0), "backlogs": (0, 5)}
    for s in ["math", "core1", "core2", "core3", "elective1", "elective2"]:
        academic_ranges[f"{s}_internal"] = (0.0, 40.0)
        academic_ranges[f"{s}_exam"] = (0.0, 60.0)
    academic_df = cleaner.clamp_ranges(academic_df, "academic", academic_ranges)
    academic_df = cleaner.enforce_types(academic_df, "academic", ["backlogs"])

    # 2. Attendance Data
    attendance_path = RAW_DATA_DIR / "attendance.csv"
    attendance_df = pd.read_csv(attendance_path)
    attendance_df = cleaner.normalize_uids(attendance_df, "attendance")
    attendance_df = cleaner.remove_duplicates(attendance_df, "attendance")
    attendance_df = cleaner.impute_missing_numeric(attendance_df, "attendance")
    
    attendance_ranges = {"overall_pct": (0.0, 100.0)}
    for s in ["math", "core1", "core2", "core3", "elective1", "elective2"]:
        attendance_ranges[f"{s}_pct"] = (0.0, 100.0)
    attendance_df = cleaner.clamp_ranges(attendance_df, "attendance", attendance_ranges)

    # 3. LMS Data
    lms_path = RAW_DATA_DIR / "lms.csv"
    lms_df = pd.read_csv(lms_path)
    lms_df = cleaner.normalize_uids(lms_df, "lms")
    lms_df = cleaner.remove_duplicates(lms_df, "lms")
    lms_df = cleaner.impute_missing_numeric(lms_df, "lms")
    lms_df = cleaner.clamp_ranges(lms_df, "lms", {
        "login_frequency": (0, 100),
        "assignment_completion_pct": (0.0, 100.0),
        "resources_downloaded": (0, 100),
        "forum_posts": (0, 100)
    })
    lms_df = cleaner.enforce_types(lms_df, "lms", ["login_frequency", "resources_downloaded", "forum_posts"])

    # 4. Engagement Data
    engagement_path = RAW_DATA_DIR / "engagement.csv"
    engagement_df = pd.read_csv(engagement_path)
    engagement_df = cleaner.normalize_uids(engagement_df, "engagement")
    engagement_df = cleaner.remove_duplicates(engagement_df, "engagement")
    engagement_df = cleaner.impute_missing_numeric(engagement_df, "engagement")
    engagement_df = cleaner.clamp_ranges(engagement_df, "engagement", {
        "events_attended": (0, 30),
        "clubs_joined": (0, 10),
        "hackathons_participated": (0, 20),
        "certifications_earned": (0, 20),
        "workshops_attended": (0, 25),
    })
    engagement_df = cleaner.enforce_types(engagement_df, "engagement", [
        "events_attended", "clubs_joined", "hackathons_participated", "certifications_earned", "workshops_attended"
    ])

    # 5. Placement Data
    placement_path = RAW_DATA_DIR / "placement.csv"
    placement_df = pd.read_csv(placement_path)
    placement_df = cleaner.normalize_uids(placement_df, "placement")
    placement_df = cleaner.remove_duplicates(placement_df, "placement")
    placement_df = cleaner.impute_missing_numeric(placement_df, "placement")
    placement_df = cleaner.clamp_ranges(placement_df, "placement", {
        "aptitude_score": (0.0, 100.0),
        "coding_score": (0.0, 100.0),
        "mock_interview_score": (0.0, 100.0),
        "communication_score": (0.0, 100.0),
        "drives_attended": (0, 20),
        "offers_received": (0, 10),
    })
    placement_df = cleaner.enforce_types(placement_df, "placement", ["drives_attended", "offers_received"])

    # 6. Skills Data
    skills_path = RAW_DATA_DIR / "skills.csv"
    skills_df = pd.read_csv(skills_path)
    skills_df = cleaner.normalize_uids(skills_df, "skills")
    skills_df = cleaner.remove_duplicates(skills_df, "skills")
    skills_df = cleaner.impute_missing_numeric(skills_df, "skills")
    skills_df = cleaner.clamp_ranges(skills_df, "skills", {
        "python_score": (0.0, 100.0),
        "sql_score": (0.0, 100.0),
        "problem_solving_score": (0.0, 100.0),
        "communication_score": (0.0, 100.0),
        "teamwork_score": (0.0, 100.0),
        "leadership_score": (0.0, 100.0),
    })

    # 7. Feedback Data
    feedback_path = RAW_DATA_DIR / "feedback.csv"
    feedback_df = pd.read_csv(feedback_path)
    feedback_df = cleaner.normalize_uids(feedback_df, "feedback")
    feedback_df = cleaner.remove_duplicates(feedback_df, "feedback")
    feedback_df = cleaner.impute_missing_numeric(feedback_df, "feedback")
    feedback_df = cleaner.clamp_ranges(feedback_df, "feedback", {
        "student_satisfaction": (1.0, 5.0),
        "faculty_feedback": (1.0, 5.0),
        "course_rating": (1.0, 5.0),
        "infrastructure_rating": (1.0, 5.0),
        "overall_experience": (1.0, 5.0),
    })

    cleaned_dfs = {
        "academic": academic_df,
        "attendance": attendance_df,
        "lms": lms_df,
        "engagement": engagement_df,
        "placement": placement_df,
        "skills": skills_df,
        "feedback": feedback_df,
    }

    return cleaned_dfs, cleaner


def transform_and_merge(cleaned_dfs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Transforms and merges cleaned datasets into:
    1. students_master: Primary student records with computed aggregates, Success Score, and Risk Flags.
    2. academic_details: Unpivoted subject-level marks table.
    3. attendance_details: Unpivoted subject-level attendance table.
    """
    print("\n" + "=" * 70)
    print("STEP 2: TRANSFORMING, AGGREGATING, AND MERGING DATASETS")
    print("=" * 70)

    acad_df = cleaned_dfs["academic"]
    att_df = cleaned_dfs["attendance"]
    lms_df = cleaned_dfs["lms"]
    eng_df = cleaned_dfs["engagement"]
    plc_df = cleaned_dfs["placement"]
    skl_df = cleaned_dfs["skills"]
    fdb_df = cleaned_dfs["feedback"]

    # Compute academic aggregates: internal_avg and exam_avg across the 6 subjects
    internal_cols = [f"{s}_internal" for s in ["math", "core1", "core2", "core3", "elective1", "elective2"]]
    exam_cols = [f"{s}_exam" for s in ["math", "core1", "core2", "core3", "elective1", "elective2"]]
    acad_df["internal_avg"] = np.round(acad_df[internal_cols].mean(axis=1), 2)
    acad_df["exam_avg"] = np.round(acad_df[exam_cols].mean(axis=1), 2)

    # Compute attendance subject average
    subject_pct_cols = [f"{s}_pct" for s in ["math", "core1", "core2", "core3", "elective1", "elective2"]]
    att_df["attendance_avg_subject"] = np.round(att_df[subject_pct_cols].mean(axis=1), 1)

    # Map batch column to foreign key batch_code
    acad_df["batch_code"] = acad_df["batch"].map(BATCH_NAME_TO_CODE).fillna("CSE_2023_27")

    # Build primary students master dataframe
    # We select and rename columns to match the target SQLite schema
    students_df = pd.DataFrame({
        "uid": acad_df["uid"],
        "name": acad_df["name"],
        "batch_code": acad_df["batch_code"],
        "cgpa": acad_df["cgpa"],
        "internal_avg": acad_df["internal_avg"],
        "exam_avg": acad_df["exam_avg"],
        "backlogs": acad_df["backlogs"],
    })

    # Merge attendance
    att_subset = att_df[["uid", "overall_pct", "attendance_avg_subject"]].rename(
        columns={"overall_pct": "attendance_overall"}
    )
    students_df = students_df.merge(att_subset, on="uid", how="inner")

    # Merge LMS
    lms_subset = lms_df[["uid", "login_frequency", "assignment_completion_pct", "resources_downloaded", "forum_posts"]].rename(
        columns={
            "login_frequency": "lms_login_freq",
            "assignment_completion_pct": "lms_assignment_pct",
            "resources_downloaded": "lms_resources",
            "forum_posts": "lms_forum_posts",
        }
    )
    students_df = students_df.merge(lms_subset, on="uid", how="inner")

    # Merge Engagement
    eng_subset = eng_df[["uid", "events_attended", "clubs_joined", "hackathons_participated", "certifications_earned", "workshops_attended"]].rename(
        columns={
            "hackathons_participated": "hackathons",
            "certifications_earned": "certifications",
            "workshops_attended": "workshops",
        }
    )
    students_df = students_df.merge(eng_subset, on="uid", how="inner")

    # Merge Placement
    plc_subset = plc_df[["uid", "aptitude_score", "coding_score", "mock_interview_score", "communication_score", "drives_attended", "offers_received"]].rename(
        columns={"mock_interview_score": "mock_interview"}
    )
    students_df = students_df.merge(plc_subset, on="uid", how="inner")

    # Merge Skills (note: communication_score in skills is renamed to skill_communication)
    skl_subset = skl_df[["uid", "python_score", "sql_score", "problem_solving_score", "communication_score", "teamwork_score", "leadership_score"]].rename(
        columns={
            "problem_solving_score": "problem_solving",
            "communication_score": "skill_communication",
            "teamwork_score": "teamwork",
            "leadership_score": "leadership",
        }
    )
    students_df = students_df.merge(skl_subset, on="uid", how="inner")

    # Merge Feedback
    fdb_subset = fdb_df[["uid", "student_satisfaction", "faculty_feedback", "course_rating", "infrastructure_rating", "overall_experience"]]
    students_df = students_df.merge(fdb_subset, on="uid", how="inner")

    # -------------------------------------------------------------------------
    # Composite Success Score Calculation (0-100)
    # -------------------------------------------------------------------------
    # 1. Academic component (CGPA scaled to 0-100, weight 25%):
    acad_comp = (students_df["cgpa"] / 10.0) * 100.0

    # 2. Attendance component (overall attendance 0-100, weight 15%):
    att_comp = students_df["attendance_overall"]

    # 3. LMS engagement component (assignment completion 0-100, weight 10%):
    lms_comp = students_df["lms_assignment_pct"]

    # 4. Extracurricular Engagement (total activities normalized to 0-100, weight 10%):
    total_activities = (
        students_df["events_attended"] +
        students_df["clubs_joined"] +
        students_df["hackathons"] +
        students_df["certifications"] +
        students_df["workshops"]
    )
    # Theoretical maximum activities ~ 50 (15 events + 5 clubs + 8 hackathons + 10 certs + 12 workshops)
    eng_comp = np.clip((total_activities / 50.0) * 100.0, 0.0, 100.0)

    # 5. Placement readiness (mean of aptitude, coding, mock_interview, weight 20%):
    place_comp = (
        students_df["aptitude_score"] +
        students_df["coding_score"] +
        students_df["mock_interview"]
    ) / 3.0

    # 6. Skills composite (mean of all 6 technical & soft skills, weight 15%):
    skills_comp = (
        students_df["python_score"] +
        students_df["sql_score"] +
        students_df["problem_solving"] +
        students_df["skill_communication"] +
        students_df["teamwork"] +
        students_df["leadership"]
    ) / 6.0

    # 7. Student Feedback (mean of 5 feedback ratings scaled to 0-100, weight 5%):
    feedback_avg = (
        students_df["student_satisfaction"] +
        students_df["faculty_feedback"] +
        students_df["course_rating"] +
        students_df["infrastructure_rating"] +
        students_df["overall_experience"]
    ) / 5.0
    feedback_comp = (feedback_avg / 5.0) * 100.0

    # Weighted calculation
    success_score = (
        0.25 * acad_comp +
        0.15 * att_comp +
        0.10 * lms_comp +
        0.10 * eng_comp +
        0.20 * place_comp +
        0.15 * skills_comp +
        0.05 * feedback_comp
    )
    students_df["success_score"] = np.round(success_score, 2)

    # -------------------------------------------------------------------------
    # Risk Flag Evaluation
    # -------------------------------------------------------------------------
    # risk_academic = 1 if CGPA < 6.0 OR backlogs > 2 OR attendance < 65%
    acad_risk_mask = (
        (students_df["cgpa"] < 6.0) |
        (students_df["backlogs"] > 2) |
        (students_df["attendance_overall"] < 65.0)
    )
    students_df["risk_academic"] = acad_risk_mask.astype(int)

    # risk_placement = 1 if aptitude < 40 OR coding < 40 OR mock_interview < 40
    place_risk_mask = (
        (students_df["aptitude_score"] < 40.0) |
        (students_df["coding_score"] < 40.0) |
        (students_df["mock_interview"] < 40.0)
    )
    students_df["risk_placement"] = place_risk_mask.astype(int)

    # Consolidated risk_flag: 'academic', 'placement', 'both', or 'none'
    conditions = [
        (students_df["risk_academic"] == 1) & (students_df["risk_placement"] == 1),
        (students_df["risk_academic"] == 1) & (students_df["risk_placement"] == 0),
        (students_df["risk_academic"] == 0) & (students_df["risk_placement"] == 1),
    ]
    choices = ["both", "academic", "placement"]
    students_df["risk_flag"] = np.select(conditions, choices, default="none")

    # -------------------------------------------------------------------------
    # Build Unpivoted Detail Tables
    # -------------------------------------------------------------------------
    # 1. academic_details: uid, subject, internal_marks, exam_marks
    acad_detail_rows = []
    for _, row in acad_df.iterrows():
        student_uid = row["uid"]
        for key, subject_name in SUBJECT_MAP.items():
            acad_detail_rows.append({
                "uid": student_uid,
                "subject": subject_name,
                "internal_marks": row[f"{key}_internal"],
                "exam_marks": row[f"{key}_exam"],
            })
    academic_details_df = pd.DataFrame(acad_detail_rows)

    # 2. attendance_details: uid, subject, attendance_pct
    att_detail_rows = []
    for _, row in att_df.iterrows():
        student_uid = row["uid"]
        for key, subject_name in SUBJECT_MAP.items():
            att_detail_rows.append({
                "uid": student_uid,
                "subject": subject_name,
                "attendance_pct": row[f"{key}_pct"],
            })
    attendance_details_df = pd.DataFrame(att_detail_rows)

    print(f"Successfully constructed Master Student records for {len(students_df)} students.")
    print(f"Constructed academic_details ({len(academic_details_df)} rows) and attendance_details ({len(attendance_details_df)} rows).")

    return students_df, academic_details_df, attendance_details_df


def initialize_and_populate_db(
    students_df: pd.DataFrame,
    academic_details_df: pd.DataFrame,
    attendance_details_df: pd.DataFrame,
    cleaner: DataCleaner
):
    """
    Creates SQLite schema at data/campus.db, seeds reference data, and populates cleaned records.
    """
    print("\n" + "=" * 70)
    print("STEP 3: INITIALIZING SQLITE DATABASE & SEEDING DEMO DATA")
    print("=" * 70)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Enable foreign key enforcement
    cursor.execute("PRAGMA foreign_keys = ON;")

    # Drop existing tables to guarantee idempotent, clean initialization
    cursor.execute("DROP TABLE IF EXISTS data_quality_report;")
    cursor.execute("DROP TABLE IF EXISTS attendance_details;")
    cursor.execute("DROP TABLE IF EXISTS academic_details;")
    cursor.execute("DROP TABLE IF EXISTS students;")
    cursor.execute("DROP TABLE IF EXISTS batches;")
    cursor.execute("DROP TABLE IF EXISTS users;")

    # Create tables
    cursor.executescript("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('Admin', 'Faculty')),
        full_name TEXT NOT NULL
    );

    CREATE TABLE batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_code TEXT UNIQUE NOT NULL,
        batch_name TEXT NOT NULL,
        department TEXT NOT NULL,
        start_year INTEGER NOT NULL,
        end_year INTEGER NOT NULL
    );

    CREATE TABLE students (
        uid TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        batch_code TEXT NOT NULL,
        cgpa REAL, internal_avg REAL, exam_avg REAL, backlogs INTEGER,
        attendance_overall REAL, attendance_avg_subject REAL,
        lms_login_freq INTEGER, lms_assignment_pct REAL, lms_resources INTEGER, lms_forum_posts INTEGER,
        events_attended INTEGER, clubs_joined INTEGER, hackathons INTEGER, certifications INTEGER, workshops INTEGER,
        aptitude_score REAL, coding_score REAL, mock_interview REAL, communication_score REAL, drives_attended INTEGER, offers_received INTEGER,
        python_score REAL, sql_score REAL, problem_solving REAL, skill_communication REAL, teamwork REAL, leadership REAL,
        student_satisfaction REAL, faculty_feedback REAL, course_rating REAL, infrastructure_rating REAL, overall_experience REAL,
        success_score REAL,
        risk_academic INTEGER DEFAULT 0,
        risk_placement INTEGER DEFAULT 0,
        risk_flag TEXT DEFAULT 'none',
        FOREIGN KEY (batch_code) REFERENCES batches(batch_code)
    );

    CREATE TABLE academic_details (
        uid TEXT, subject TEXT, internal_marks REAL, exam_marks REAL,
        FOREIGN KEY (uid) REFERENCES students(uid)
    );

    CREATE TABLE attendance_details (
        uid TEXT, subject TEXT, attendance_pct REAL,
        FOREIGN KEY (uid) REFERENCES students(uid)
    );

    CREATE TABLE data_quality_report (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_type TEXT NOT NULL,
        description TEXT NOT NULL,
        count INTEGER NOT NULL,
        timestamp TEXT NOT NULL
    );
    """)

    # Seed Demo Users
    demo_users = [
        ("admin", generate_password_hash("admin123"), "Admin", "Dr. Admin User"),
        ("faculty1", generate_password_hash("faculty123"), "Faculty", "Prof. Sharma"),
        ("faculty2", generate_password_hash("faculty123"), "Faculty", "Prof. Patel"),
    ]
    cursor.executemany(
        "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?);",
        demo_users
    )
    print(f"Seeded {len(demo_users)} demo users in 'users' table.")

    # Seed Batches
    demo_batches = [
        ("CSE_2023_27", "CSE 2023-27", "Computer Science", 2023, 2027),
        ("ECE_2023_27", "ECE 2023-27", "Electronics & Communication", 2023, 2027),
        ("CSE_2024_28", "CSE 2024-28", "Computer Science", 2024, 2028),
    ]
    cursor.executemany(
        "INSERT INTO batches (batch_code, batch_name, department, start_year, end_year) VALUES (?, ?, ?, ?, ?);",
        demo_batches
    )
    print(f"Seeded {len(demo_batches)} academic batches in 'batches' table.")

    # Insert Students Master
    students_df.to_sql("students", conn, if_exists="append", index=False)
    print(f"Inserted {len(students_df)} students into 'students' table.")

    # Insert Academic Details
    academic_details_df.to_sql("academic_details", conn, if_exists="append", index=False)
    print(f"Inserted {len(academic_details_df)} subject rows into 'academic_details' table.")

    # Insert Attendance Details
    attendance_details_df.to_sql("attendance_details", conn, if_exists="append", index=False)
    print(f"Inserted {len(attendance_details_df)} subject rows into 'attendance_details' table.")

    # Insert Data Quality Report
    report_rows = [
        (item["issue_type"], item["description"], item["count"], item["timestamp"])
        for item in cleaner.quality_report_log
    ]
    cursor.executemany(
        "INSERT INTO data_quality_report (issue_type, description, count, timestamp) VALUES (?, ?, ?, ?);",
        report_rows
    )
    conn.commit()
    conn.close()
    print(f"Recorded {len(report_rows)} quality audit entries into 'data_quality_report' table.")


def print_summary_reports(cleaner: DataCleaner):
    """
    Queries and prints formatted Data Quality Audit Report and student statistics.
    """
    print("\n" + "=" * 70)
    print("STEP 4: DATA QUALITY & ETL AUDIT REPORT")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    
    # 1. Data Quality Fixes Table
    report_df = pd.read_sql_query("SELECT id, issue_type, count, description, timestamp FROM data_quality_report;", conn)
    print("\n[DATA QUALITY FIXES APPLIED]")
    print("-" * 70)
    print(f"{'ID':<4} {'Issue Type':<22} {'Count':<7} {'Description'}")
    print("-" * 70)
    for _, row in report_df.iterrows():
        print(f"{row['id']:<4} {row['issue_type']:<22} {row['count']:<7} {row['description']}")
    print("-" * 70)
    print(f"Total UIDs Fixed:           {cleaner.stats['uid_fixes']}")
    print(f"Total Duplicates Dropped:   {cleaner.stats['duplicates_removed']}")
    print(f"Total Missing Cells Filled: {cleaner.stats['missing_imputed']}")
    print(f"Total Out-of-Range Clamped: {cleaner.stats['out_of_range_clamped']}")
    print(f"Total Column Types Checked: {cleaner.stats['types_enforced']}")

    # 2. Student Cohort Summary Statistics
    total_students = pd.read_sql_query("SELECT COUNT(*) AS total FROM students;", conn).iloc[0]["total"]
    batch_summary = pd.read_sql_query("""
        SELECT b.batch_name, b.department, COUNT(s.uid) AS student_count,
               ROUND(AVG(s.cgpa), 2) AS avg_cgpa,
               ROUND(AVG(s.attendance_overall), 1) AS avg_attendance,
               ROUND(AVG(s.success_score), 1) AS avg_success_score
        FROM batches b
        LEFT JOIN students s ON b.batch_code = s.batch_code
        GROUP BY b.batch_code;
    """, conn)

    risk_summary = pd.read_sql_query("""
        SELECT risk_flag, COUNT(*) as count,
               ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM students), 1) AS percentage
        FROM students
        GROUP BY risk_flag
        ORDER BY count DESC;
    """, conn)

    overall_metrics = pd.read_sql_query("""
        SELECT 
            ROUND(AVG(success_score), 2) AS mean_success,
            ROUND(MIN(success_score), 2) AS min_success,
            ROUND(MAX(success_score), 2) AS max_success,
            SUM(risk_academic) AS total_academic_risks,
            SUM(risk_placement) AS total_placement_risks
        FROM students;
    """, conn).iloc[0]

    print("\n" + "=" * 70)
    print("STEP 5: STUDENT COHORT SUMMARY STATISTICS")
    print("=" * 70)
    print(f"Total Cleaned Students Ingested: {total_students}")
    print(f"Overall Mean Success Score:       {overall_metrics['mean_success']} (Range: {overall_metrics['min_success']} - {overall_metrics['max_success']})")
    print(f"Students with Academic Risk:      {int(overall_metrics['total_academic_risks'])}")
    print(f"Students with Placement Risk:     {int(overall_metrics['total_placement_risks'])}")

    print("\n[STUDENT DISTRIBUTION BY BATCH]")
    print("-" * 70)
    print(f"{'Batch Name':<16} {'Department':<28} {'Count':<6} {'Avg CGPA':<10} {'Avg Att%':<10} {'Success':<8}")
    print("-" * 70)
    for _, row in batch_summary.iterrows():
        print(f"{row['batch_name']:<16} {row['department']:<28} {row['student_count']:<6} {row['avg_cgpa']:<10} {row['avg_attendance']:<10} {row['avg_success_score']:<8}")

    print("\n[STUDENT RISK CATEGORIZATION]")
    print("-" * 70)
    print(f"{'Risk Category':<18} {'Student Count':<14} {'Cohort Percentage':<16}")
    print("-" * 70)
    for _, row in risk_summary.iterrows():
        print(f"{row['risk_flag']:<18} {row['count']:<14} {row['percentage']}%")
    print("-" * 70)

    conn.close()
    print("\n[SUCCESS] Unified SQLite database campus.db generated and verified successfully at:")
    print(f"          {DB_PATH}\n")


def run_pipeline():
    """
    Orchestrates the entire ETL workflow from raw CSV ingestion to SQLite population.
    """
    cleaned_dfs, cleaner = load_and_clean_raw_data()
    students_df, academic_details_df, attendance_details_df = transform_and_merge(cleaned_dfs)
    initialize_and_populate_db(students_df, academic_details_df, attendance_details_df, cleaner)
    print_summary_reports(cleaner)


if __name__ == "__main__":
    run_pipeline()
