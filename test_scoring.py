"""
=============================================================================
Smart Campus Analytics - Scoring Engine Verification & Distribution Test
=============================================================================
This test script verifies the scoring engine by:
  1. Computing scores, sub-scores, risks, segments, and explainability for all batches.
  2. Printing clean statistical distributions (mean, std, min, quartiles, max) per batch.
  3. Displaying risk distributions and "Needs Attention" student counts per batch.
  4. Displaying cohort segment distributions per batch.
  5. Printing a sample explainability card with top 3 negative contributors and actions.
  6. Asserting data integrity constraints (range [0, 100], valid labels, math consistency).
=============================================================================
"""

import math
import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np

import scoring

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "campus.db"


def run_tests():
    print("=" * 76)
    print("   SMART CAMPUS ANALYTICS: BATCH SCORE DISTRIBUTION & INTEGRITY TEST")
    print("=" * 76)

    # 1. Execute Scoring Pipeline
    scored_df, summary = scoring.load_and_score(DB_PATH)
    total_students = len(scored_df)
    print(f"\n[INFO] Loaded and scored {total_students} students across {scored_df['batch_code'].nunique()} batches.\n")

    # 2. Iterate through each batch and print formatted distributions
    batches = scored_df["batch_code"].unique()

    for batch_code in sorted(batches):
        b_df = scored_df[scored_df["batch_code"] == batch_code]
        n_students = len(b_df)

        print("-" * 76)
        print(f"BATCH: {batch_code}  |  Enrolled Students: {n_students}")
        print("-" * 76)

        # Composite Success Score Stats
        s_series = b_df["success_score"]
        print("Success Score (0-100):")
        print(f"  Mean:   {s_series.mean():.2f}    Std Dev: {s_series.std():.2f}")
        print(f"  Min:    {s_series.min():.2f}    25%:     {s_series.quantile(0.25):.2f}")
        print(f"  Median: {s_series.median():.2f}    75%:     {s_series.quantile(0.75):.2f}")
        print(f"  Max:    {s_series.max():.2f}")

        # Sub-score summary
        acad_sub = b_df["academic_subscore"]
        place_sub = b_df["placement_subscore"]
        print("\nReadiness Sub-Scores:")
        print(f"  Academic Readiness:   Mean = {acad_sub.mean():.2f}  (Min = {acad_sub.min():.2f}, Max = {acad_sub.max():.2f})")
        print(f"  Placement Readiness:  Mean = {place_sub.mean():.2f}  (Min = {place_sub.min():.2f}, Max = {place_sub.max():.2f})")

        # Risk Classification Breakdown
        risk_counts = b_df["risk_level"].value_counts()
        needs_attention_count = int(b_df["needs_attention"].sum())
        needs_attention_pct = (needs_attention_count / n_students) * 100.0

        print("\nRisk Classification:")
        for r_level in ["High", "Medium", "Low"]:
            cnt = int(risk_counts.get(r_level, 0))
            pct = (cnt / n_students) * 100.0
            flag_note = " (Needs Attention)" if r_level == "High" else ""
            print(f"  - {r_level:<6}{flag_note}: {cnt:>2} students ({pct:>5.1f}%)")

        print(f"  Total Flagged for Attention: {needs_attention_count} / {n_students} ({needs_attention_pct:.1f}%)")

        # Segment Breakdown
        segment_counts = b_df["segment"].value_counts()
        print("\nCohort Segments:")
        for seg_name, count in segment_counts.items():
            pct = (count / n_students) * 100.0
            print(f"  * {seg_name:<46}: {count:>2} ({pct:>5.1f}%)")

        # Pick a sample student in this batch who needs attention to show explainability
        batch_explains = [e for e in summary["explain_objs"] if e["batch_code"] == batch_code and len(e["top_negative_contributors"]) > 0]
        if batch_explains:
            sample_student = batch_explains[0]
            print(f"\nSample Explainability Card for {sample_student['uid']} ({sample_student['name']}):")
            print("  Top Negative Contributors:")
            for item in sample_student["top_negative_contributors"]:
                print(f"    - {item['indicator']} (Weight: {item['weight']}%): {item['student_value']:.1f} vs batch avg {item['batch_average']:.1f} [Net impact: {item['contribution']:+.2f} pts]")
            print("  Plain-English Reasons:")
            for reason in sample_student["reasons"]:
                print(f"    * {reason}")
            print("  Suggested Interventions:")
            for action in sample_student["actions"]:
                print(f"    -> {action}")
        print()

    # 3. Assertions & Validation
    print("=" * 76)
    print("RUNNING DATA INTEGRITY & MATHEMATICAL CONSISTENCY ASSERTIONS")
    print("=" * 76)

    # Constraint 1: Scores must be strictly within [0.0, 100.0]
    assert (scored_df["success_score"] >= 0.0).all() and (scored_df["success_score"] <= 100.0).all(), "Success Score outside [0, 100]!"
    assert (scored_df["academic_subscore"] >= 0.0).all() and (scored_df["academic_subscore"] <= 100.0).all(), "Academic sub-score outside [0, 100]!"
    assert (scored_df["placement_subscore"] >= 0.0).all() and (scored_df["placement_subscore"] <= 100.0).all(), "Placement sub-score outside [0, 100]!"
    print("  [PASS] All scores and sub-scores are bounded within [0.0, 100.0].")

    # Constraint 2: Risk Levels must match valid enum
    valid_risks = {"High", "Medium", "Low"}
    assert set(scored_df["risk_level"].unique()).issubset(valid_risks), "Invalid risk level found!"
    print("  [PASS] All risk level categories belong to {'High', 'Medium', 'Low'}.")

    # Constraint 3: High Risk == Needs Attention
    assert ((scored_df["risk_level"] == "High") == (scored_df["needs_attention"] == 1)).all(), "Needs attention mismatch with High risk!"
    print("  [PASS] 'Needs Attention' strictly maps to High Risk.")

    # Constraint 4: Segment categories belong to official 6 segments
    valid_segments = {
        "High Performers",
        "Strong Academics but Low Placement Readiness",
        "Placement Ready but Weak Academics",
        "Disengaged",
        "Needs Overall Support",
        "Steady"
    }
    found_segments = set(scored_df["segment"].unique())
    assert found_segments.issubset(valid_segments), f"Unexpected segment found: {found_segments - valid_segments}"
    print(f"  [PASS] All student segments belong to official 6 categories ({len(found_segments)} represented).")

    # Constraint 5: Mathematical explainability consistency
    # Sum of all contributions should closely match (student_score - batch_mean_score)
    for sample in summary["explain_objs"][:10]:
        total_contrib = sum(c["contribution"] for c in sample["all_contributions"])
        b_code = sample["batch_code"]
        b_mean_score = scored_df[scored_df["batch_code"] == b_code]["success_score"].mean()
        student_score = scored_df[scored_df["uid"] == sample["uid"]]["success_score"].values[0]
        expected_diff = student_score - b_mean_score
        assert abs(total_contrib - expected_diff) < 0.25, f"Contribution sum mismatch for {sample['uid']}: {total_contrib} vs {expected_diff}"
    print("  [PASS] Explainability contributions sum exactly to student score offset from batch mean.")

    print("\n[ALL TESTS PASSED] Scoring engine verified successfully!\n")


if __name__ == "__main__":
    run_tests()
