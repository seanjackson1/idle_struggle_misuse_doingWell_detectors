#!/usr/bin/env python3
import csv
from datetime import datetime, timedelta

# file paths
INPUT_CSV  = "./Full_Data_With_Marked_Help.csv"
OUTPUT_CSV = "./Full_Idle_Output.csv"

# Idle thresholds (seconds) and labels
IDLE_THRESHOLDS = [
    (0,   "0 s"),
    (120, "2 min"),
    (300, "5 min"),
]

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

def parse_time(ts_str):
    """Turn the CSV 'Time' string into a datetime."""
    return datetime.strptime(ts_str, TIME_FORMAT)

class SessionState:
    """Keeps track of the last action time for one (student, session)."""
    def __init__(self):
        self.last_action_time = None

def determine_idle_state(state, now):
    """
    Replicates the JS setTimeout logic in one shot:
      - Computes seconds since last_action_time (0 if first action)
      - Finds which threshold(s) have been crossed
      - Returns (flag, label, elapsed_seconds, detection_time)
    """
    if state.last_action_time is None:
        elapsed = 0
    else:
        elapsed = (now - state.last_action_time).total_seconds()

    # Default: not idle
    idle_flag      = 0
    idle_label     = "> 0 s"
    idle_timestamp = now

    # highest threshold ≤ elapsed
    for th, label in IDLE_THRESHOLDS:
        if elapsed >= th:
            idle_flag      = 1 if th > 0 else 0
            idle_label     = f"> {label}"
            # Emulate firing at last_action_time + th
            idle_timestamp = (state.last_action_time + timedelta(seconds=th)) \
                             if state.last_action_time else now

    return idle_flag, idle_label, int(elapsed), idle_timestamp

def main():
    # In-memory state per (Anon Student Id, Session Id)
    states = {}

    with open(INPUT_CSV, newline='') as fin, open(OUTPUT_CSV, "w", newline='') as fout:
        reader = csv.DictReader(fin)
        # four idle columns
        fieldnames = reader.fieldnames + ["IdleFlag","IdleLabel","IdleElapsedSec","IdleTimestamp"]
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            key = (row["Anon Student Id"], row["Session Id"])
            now = parse_time(row["Time"])

            # Initialize state if first time seeing student+session
            if key not in states:
                states[key] = SessionState()
            state = states[key]

            # Compute the annotation
            flag, label, elapsed, det_time = determine_idle_state(state, now)
            row["IdleFlag"]       = flag
            row["IdleLabel"]      = label
            row["IdleElapsedSec"] = elapsed
            row["IdleTimestamp"]  = det_time.strftime(TIME_FORMAT)

            writer.writerow(row)

            # Update last_action_time for next iteration
            state.last_action_time = now

if __name__ == "__main__":
    main()
