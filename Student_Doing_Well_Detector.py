#!/usr/bin/env python3
import csv
import pandas as pd

# file paths here
INPUT_CSV  = "./Full_Data_With_Marked_Help.csv"
OUTPUT_CSV = "./Full_Student_Doing_Well_Output.csv"
# ————————————————————————————————————————————

# Detector parameters (from JS logic)
WINDOW_SIZE = 10
THRESHOLD   = 8  # >=8 of last 10 first-attempts considered "doing well"

class SessionState:
    """
    Maintains the sliding window of the last WINDOW_SIZE first-attempt outcomes for one session.
    """
    def __init__(self):
        # Initialize with zeros (no prior first-attempts)
        self.attempt_window = [0] * WINDOW_SIZE


def main():
    # In-memory state keyed by (Anon Student Id, Session Id)
    states = {}

    with open(INPUT_CSV, newline='') as fin, open(OUTPUT_CSV, 'w', newline='') as fout:
        reader = csv.DictReader(fin)
        # Add new column for the detector flag
        fieldnames = reader.fieldnames + ['DoingWellFlag']
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            # Key state by student and session
            key = (row['Anon Student Id'], row['Session Id'])
            if key not in states:
                states[key] = SessionState()
            state = states[key]

            # Determine if this is the first attempt at the step
            try:
                attempt_num = int(row.get('Attempt At Step', 0))
            except ValueError:
                attempt_num = 0
            is_first = (attempt_num == 1)

            if is_first:
                outcome = row.get('Outcome', '').strip()
                correct = 1 if outcome in ('OK', 'OK_AMBIGUOUS') else 0
                # Shift out oldest and append the new result
                state.attempt_window.pop(0)
                state.attempt_window.append(correct)

            # Compute the "doing well" flag from the window
            flag = 1 if sum(state.attempt_window) >= THRESHOLD else 0
            row['DoingWellFlag'] = flag

            # Write annotated row
            writer.writerow(row)

if __name__ == '__main__':
    main()
