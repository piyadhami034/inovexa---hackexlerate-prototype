"""
generate_data.py
================
Smart Campus Analytics - Phase 1: Synthetic Dataset Generator

This script generates realistic synthetic data for college students across 3 batches:
1. CSE 2023-27 (UIDs: CSE2023001 to CSE2023060)
2. ECE 2023-27 (UIDs: ECE2023001 to ECE2023060)
3. CSE 2024-28 (UIDs: CSE2024001 to CSE2024060)

Total students: ~180 students (60 per batch).

Core Concept - Correlation Strategy:
-------------------------------------
Real students exhibit correlations across metrics: a student with higher academic ability
is also likely to have better attendance, placement aptitude, coding skills, and LMS engagement.
To model this realistically:
- Each student is assigned a latent 'base_ability' sampled from a Beta(2, 5) distribution.
  Beta(2, 5) creates a right-skewed distribution where most students are in the average range,
  and fewer students are exceptionally high-performing.
- All domain metrics (marks, attendance, placement test scores, skills, LMS activities) derive
  from this latent ability using a noisy transfer function:
      val = base + normal(0, noise_std)
      result = clip(val, 0, 1) * (high - low) + low

Deliberate Data Quality Issues ("Mess"):
----------------------------------------
To test and demonstrate data cleaning in downstream pipelines, realistic anomalies are added:
1. ~3% random missing values (NaN) across numeric columns.
2. 4-6 duplicate rows scattered across the CSV files.
3. Inconsistent UID casing and spacing (e.g., 'cse2023005', 'CSE 2023010', 'Cse2023015') in ~5% of records.
4. Out-of-range anomalies (e.g., CGPA > 10, Attendance > 100%, negative marks, feedback rating > 5.0).
UIDs are never permanently corrupted so records remain recoverable.

Generated CSV Files in data/raw/:
1. academic.csv
2. attendance.csv
3. lms.csv
4. engagement.csv
5. placement.csv
6. skills.csv
7. feedback.csv
"""

import os
import random
from pathlib import Path
import numpy as np
import pandas as pd

# Set global random seed for exact reproducibility
RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

# Resolve directories relative to this file
BASE_DIR = Path(__file__).resolve().parent
DATA_RAW_DIR = BASE_DIR / "data" / "raw"

# Realistic Indian First and Last Names for synthetic identity generation
FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
    "Shaurya", "Dhruv", "Kabir", "Rohan", "Ananya", "Diya", "Ishani", "Sanya", "Pooja", "Priya",
    "Sneha", "Neha", "Tanvi", "Shreya", "Divya", "Meera", "Rhea", "Kavya", "Aditi", "Nikhil",
    "Varun", "Kunal", "Gaurav", "Mohit", "Deepak", "Pranav", "Siddharth", "Yash", "Harsh", "Rakesh",
    "Alok", "Manish", "Rahul", "Rohit", "Amit", "Ankit", "Vikram", "Suresh", "Karan", "Ayush",
    "Pooja", "Swati", "Kavita", "Ritu", "Sunita", "Bhavna", "Anjali", "Akash", "Abhishek", "Tarun"
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Singh", "Kumar", "Rao", "Gupta", "Reddy", "Nair", "Iyer",
    "Joshi", "Mehta", "Shah", "Bhat", "Chatterjee", "Mukherjee", "Ghosh", "Das", "Sen", "Banerjee",
    "Pillai", "Menon", "Nambiar", "Kulkarni", "Deshmukh", "Patil", "Shinde", "Pawar", "Mishra", "Tiwari",
    "Pandey", "Dubey", "Shukla", "Agarwal", "Jain", "Bansal", "Goel", "Mittal", "Choudhury", "Malhotra",
    "Bose", "Kapoor", "Khanna", "Chawla", "Bhatia", "Saxena", "Srivastava", "Chauhan", "Yadav", "Tripathi"
]


def generate_names(count: int) -> list[str]:
    """
    Generate realistic student full names by combining random first and last names.
    Ensures high variety and natural representation.
    """
    names = []
    for _ in range(count):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        names.append(f"{first} {last}")
    return names


def noisy(base: np.ndarray, low: float, high: float, noise_std: float = 0.1) -> np.ndarray:
    """
    Scales latent student ability to a target range [low, high] with added Gaussian noise.
    
    Parameters:
        base (np.ndarray): Base ability array in range [0, 1].
        low (float): Lower bound of output metric.
        high (float): Upper bound of output metric.
        noise_std (float): Standard deviation of Gaussian noise added to ability.
        
    Returns:
        np.ndarray: Scaled metric array clipped to valid range [low, high].
    """
    val = base + np.random.normal(0.0, noise_std, size=len(base))
    return np.clip(val, 0.0, 1.0) * (high - low) + low


def create_student_cohort():
    """
    Constructs the base cohort of 180 students across 3 batches with assigned
    UIDs, batches, full names, and latent abilities.
    """
    batches_spec = [
        {"prefix": "CSE2023", "batch_name": "CSE 2023-27", "count": 60},
        {"prefix": "ECE2023", "batch_name": "ECE 2023-27", "count": 60},
        {"prefix": "CSE2024", "batch_name": "CSE 2024-28", "count": 60},
    ]

    uids = []
    batches = []
    
    for spec in batches_spec:
        prefix = spec["prefix"]
        batch_name = spec["batch_name"]
        for i in range(1, spec["count"] + 1):
            uids.append(f"{prefix}{i:03d}")
            batches.append(batch_name)

    total_students = len(uids)
    names = generate_names(total_students)
    
    # Latent base ability: right-skewed Beta(2, 5) distribution
    base_abilities = np.random.beta(a=2.0, b=5.0, size=total_students)

    cohort_df = pd.DataFrame({
        "uid": uids,
        "name": names,
        "batch": batches,
        "ability": base_abilities
    })
    
    return cohort_df


def inject_mess(dfs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Deliberately injects data anomalies ("mess") into clean datasets:
    1. Missing values (~3% of values randomly set to np.nan in numeric columns).
    2. Exact duplicate rows (4-6 duplicates scattered across CSVs).
    3. Inconsistent UID casing and spacing (~5% of UIDs per CSV).
    4. Out-of-range values (attendance 110%, CGPA 11.2, negative marks, satisfaction 6.0).
    5. Preserves recoverable UID values (never replaces UID with NaN).
    """
    print("\n--- Injecting Deliberate Real-World Data Quality Issues ---")
    
    # 1. Inconsistent UIDs (~5% per CSV)
    # We apply this directly to each dataframe independently so students have variations across sources
    for name, df in dfs.items():
        n_rows = len(df)
        n_inconsistent = max(3, int(round(n_rows * 0.05)))
        chosen_indices = np.random.choice(n_rows, size=n_inconsistent, replace=False)
        
        uid_series = df["uid"].copy()
        for idx in chosen_indices:
            orig_uid = uid_series.iloc[idx]
            variant_type = np.random.choice(["lower", "spaces", "mixed"])
            if variant_type == "lower":
                uid_series.iloc[idx] = orig_uid.lower()
            elif variant_type == "spaces":
                # Add internal or bounding spaces
                if len(orig_uid) > 3:
                    uid_series.iloc[idx] = orig_uid[:3] + " " + orig_uid[3:]
                else:
                    uid_series.iloc[idx] = f" {orig_uid} "
            elif variant_type == "mixed":
                # Capitalize only first letter, rest lowercase
                uid_series.iloc[idx] = orig_uid[0].upper() + orig_uid[1:].lower()
                
        df["uid"] = uid_series
        print(f"  [UID Noise] Injected {n_inconsistent} inconsistent UIDs into {name}.csv")

    # 2. Missing Values (~3% of numeric cells set to NaN)
    for name, df in dfs.items():
        numeric_cols = [c for c in df.columns if c not in ["uid", "name", "batch"]]
        if not numeric_cols:
            continue
            
        total_numeric_cells = len(df) * len(numeric_cols)
        nan_count = int(round(total_numeric_cells * 0.03))
        
        # Pick random row indices and column choices
        for _ in range(nan_count):
            r_idx = np.random.randint(0, len(df))
            c_col = np.random.choice(numeric_cols)
            # Use .iloc to set cell to NaN
            df.loc[r_idx, c_col] = np.nan
            
        print(f"  [Missing Values] Injected ~{nan_count} NaNs (~3%) into {name}.csv")

    # 3. Exact Duplicate Rows (4-6 duplicates across CSVs)
    # Target 5 CSVs and append 1 duplicate row each
    duplicate_target_csvs = ["academic", "attendance", "lms", "engagement", "placement"]
    for target in duplicate_target_csvs:
        if target in dfs:
            target_df = dfs[target]
            dup_idx = np.random.randint(0, len(target_df))
            row_to_duplicate = target_df.iloc[[dup_idx]].copy()
            dfs[target] = pd.concat([target_df, row_to_duplicate], ignore_index=True)
            print(f"  [Duplicates] Added 1 exact duplicate row in {target}.csv (UID: {row_to_duplicate['uid'].values[0]})")

    # 4. Out-of-Range Values
    # 4.1 Attendance 110% in attendance.csv
    if "attendance" in dfs:
        dfs["attendance"].loc[5, "overall_pct"] = 110.0
        print("  [Out-of-Range] Injected overall_pct = 110.0% in attendance.csv (index 5)")

    # 4.2 CGPA 11.2 in academic.csv
    if "academic" in dfs:
        dfs["academic"].loc[10, "cgpa"] = 11.2
        print("  [Out-of-Range] Injected cgpa = 11.2 in academic.csv (index 10)")

    # 4.3 Negative marks in academic.csv
    if "academic" in dfs:
        dfs["academic"].loc[20, "math_internal"] = -5.0
        print("  [Out-of-Range] Injected math_internal = -5.0 in academic.csv (index 20)")

    # 4.4 Satisfaction 6.0 in feedback.csv
    if "feedback" in dfs:
        dfs["feedback"].loc[15, "student_satisfaction"] = 6.0
        print("  [Out-of-Range] Injected student_satisfaction = 6.0 in feedback.csv (index 15)")

    return dfs


def generate_all_datasets():
    """
    Main data generation procedure:
    1. Generates cohort with base latent abilities.
    2. Builds clean domain DataFrames correlated with ability.
    3. Adds deliberate noise (NaNs, duplicates, casing issues, boundary violations).
    4. Saves all 7 CSVs in data/raw/ directory.
    """
    print("=" * 70)
    print("SMART CAMPUS ANALYTICS: SYNTHETIC DATA GENERATOR (PHASE 1)")
    print("=" * 70)
    
    # 1. Cohort Generation
    cohort = create_student_cohort()
    n_students = len(cohort)
    ability = cohort["ability"].values
    uids = cohort["uid"].values
    names = cohort["name"].values
    batches = cohort["batch"].values
    
    print(f"Generated base cohort of {n_students} students across 3 batches.")
    print(f"Seed: {RANDOM_SEED} | Latent Ability: Beta(2, 5) right-skewed")

    # 2. Build 7 Clean Datasets
    # -------------------------
    # CSV 1: academic.csv
    academic_df = pd.DataFrame({
        "uid": uids,
        "name": names,
        "batch": batches,
        "cgpa": np.round(noisy(ability, 4.0, 10.0, noise_std=0.06), 2),
        "math_internal": np.round(noisy(ability, 10.0, 40.0, noise_std=0.08), 1),
        "math_exam": np.round(noisy(ability, 15.0, 60.0, noise_std=0.08), 1),
        "core1_internal": np.round(noisy(ability, 10.0, 40.0, noise_std=0.08), 1),
        "core1_exam": np.round(noisy(ability, 15.0, 60.0, noise_std=0.08), 1),
        "core2_internal": np.round(noisy(ability, 10.0, 40.0, noise_std=0.08), 1),
        "core2_exam": np.round(noisy(ability, 15.0, 60.0, noise_std=0.08), 1),
        "core3_internal": np.round(noisy(ability, 10.0, 40.0, noise_std=0.08), 1),
        "core3_exam": np.round(noisy(ability, 15.0, 60.0, noise_std=0.08), 1),
        "elective1_internal": np.round(noisy(ability, 10.0, 40.0, noise_std=0.08), 1),
        "elective1_exam": np.round(noisy(ability, 15.0, 60.0, noise_std=0.08), 1),
        "elective2_internal": np.round(noisy(ability, 10.0, 40.0, noise_std=0.08), 1),
        "elective2_exam": np.round(noisy(ability, 15.0, 60.0, noise_std=0.08), 1),
        "backlogs": np.clip(np.round(4.0 * (1.0 - ability) + np.random.normal(0, 0.4, size=n_students)), 0, 5).astype(int)
    })

    # CSV 2: attendance.csv
    attendance_df = pd.DataFrame({
        "uid": uids,
        "overall_pct": np.round(noisy(ability, 50.0, 100.0, noise_std=0.08), 1),
        "math_pct": np.round(noisy(ability, 45.0, 100.0, noise_std=0.12), 1),
        "core1_pct": np.round(noisy(ability, 45.0, 100.0, noise_std=0.12), 1),
        "core2_pct": np.round(noisy(ability, 45.0, 100.0, noise_std=0.12), 1),
        "core3_pct": np.round(noisy(ability, 45.0, 100.0, noise_std=0.12), 1),
        "elective1_pct": np.round(noisy(ability, 45.0, 100.0, noise_std=0.12), 1),
        "elective2_pct": np.round(noisy(ability, 45.0, 100.0, noise_std=0.12), 1)
    })

    # CSV 3: lms.csv
    lms_df = pd.DataFrame({
        "uid": uids,
        "login_frequency": np.round(noisy(ability, 5.0, 60.0, noise_std=0.12)).astype(int),
        "assignment_completion_pct": np.round(noisy(ability, 20.0, 100.0, noise_std=0.10), 1),
        "resources_downloaded": np.round(noisy(ability, 0.0, 50.0, noise_std=0.15)).astype(int),
        "forum_posts": np.round(noisy(ability, 0.0, 30.0, noise_std=0.18)).astype(int)
    })

    # CSV 4: engagement.csv
    engagement_df = pd.DataFrame({
        "uid": uids,
        "events_attended": np.round(noisy(ability, 0.0, 15.0, noise_std=0.20)).astype(int),
        "clubs_joined": np.round(noisy(ability, 0.0, 5.0, noise_std=0.22)).astype(int),
        "hackathons_participated": np.round(noisy(ability, 0.0, 8.0, noise_std=0.25)).astype(int),
        "certifications_earned": np.round(noisy(ability, 0.0, 10.0, noise_std=0.22)).astype(int),
        "workshops_attended": np.round(noisy(ability, 0.0, 12.0, noise_std=0.20)).astype(int)
    })

    # CSV 5: placement.csv
    placement_df = pd.DataFrame({
        "uid": uids,
        "aptitude_score": np.round(noisy(ability, 15.0, 100.0, noise_std=0.10), 1),
        "coding_score": np.round(noisy(ability, 10.0, 100.0, noise_std=0.10), 1),
        "mock_interview_score": np.round(noisy(ability, 20.0, 100.0, noise_std=0.10), 1),
        "communication_score": np.round(noisy(ability, 25.0, 100.0, noise_std=0.15), 1),
        "drives_attended": np.round(noisy(ability, 0.0, 10.0, noise_std=0.20)).astype(int),
        "offers_received": np.clip(np.round(noisy(ability, 0.0, 3.2, noise_std=0.15)), 0, 3).astype(int)
    })

    # CSV 6: skills.csv
    skills_df = pd.DataFrame({
        "uid": uids,
        "python_score": np.round(noisy(ability, 15.0, 100.0, noise_std=0.12), 1),
        "sql_score": np.round(noisy(ability, 15.0, 100.0, noise_std=0.12), 1),
        "problem_solving_score": np.round(noisy(ability, 15.0, 100.0, noise_std=0.10), 1),
        "communication_score": np.round(noisy(ability, 20.0, 100.0, noise_std=0.18), 1),
        "teamwork_score": np.round(noisy(ability, 25.0, 100.0, noise_std=0.18), 1),
        "leadership_score": np.round(noisy(ability, 20.0, 100.0, noise_std=0.20), 1)
    })

    # CSV 7: feedback.csv
    feedback_df = pd.DataFrame({
        "uid": uids,
        "student_satisfaction": np.round(noisy(ability, 1.0, 5.0, noise_std=0.25), 1),
        "faculty_feedback": np.round(noisy(ability, 1.0, 5.0, noise_std=0.25), 1),
        "course_rating": np.round(noisy(ability, 1.0, 5.0, noise_std=0.25), 1),
        "infrastructure_rating": np.round(noisy(ability, 1.0, 5.0, noise_std=0.30), 1),
        "overall_experience": np.round(noisy(ability, 1.0, 5.0, noise_std=0.25), 1)
    })

    datasets = {
        "academic": academic_df,
        "attendance": attendance_df,
        "lms": lms_df,
        "engagement": engagement_df,
        "placement": placement_df,
        "skills": skills_df,
        "feedback": feedback_df
    }

    # 3. Deliberate Mess Injection
    datasets = inject_mess(datasets)

    # 4. Save to CSV in data/raw/
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    print("\n--- Saving Raw CSV Datasets ---")
    for name, df in datasets.items():
        file_path = DATA_RAW_DIR / f"{name}.csv"
        df.to_csv(file_path, index=False)
        print(f"Saved: {file_path} ({len(df)} rows, {len(df.columns)} columns)")

    print("\n[SUCCESS] Phase 1 synthetic data generation complete!\n")


if __name__ == "__main__":
    generate_all_datasets()
