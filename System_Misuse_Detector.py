import csv
from datetime import datetime, timedelta

# === Configuration ===
INPUT_CSV   = "./Full_Data_With_Marked_Help.csv"
OUTPUT_CSV  = "./Full_System_Misuse_Output.csv"

WINDOW_SIZE           = 10
MISUSE_THRESHOLD      = 3    # if ≥3 misuse signals in window -> misuse
ERROR_THRESHOLD       = 2    # secs after an error before next action is “deliberate”
NEW_STEP_THRESHOLD    = 1    # secs between actions on a new step
FAMILIARITY_THRESHOLD = 0.4  # p_know cutoff for "familiar"
SENSE_THRESHOLD       = 0.6  # p_know cutoff for "sense" of next action

BKT_PARAMS = {
    "p_transit": 0.2,   # chance of learning between attempts
    "p_slip":    0.1,   # chance of mistake despite knowing
    "p_guess":   0.2,   # chance of guess despite not knowing
    "p_know":    0.25,  # initial mastery probability
}

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_time(ts_str):
    return datetime.strptime(ts_str, TIME_FORMAT)

def is_correct(outcome):
    return outcome.strip().lower() == "correct"

def is_deliberate(state, now):
    last = state.help_vars["last_action_time"]
    if last is None:
        return True
    dt = (now - last).total_seconds()
    last_action = state.help_vars["last_action"]
    last_hint_len = state.help_vars["last_hint_len"]
    if last_action == "error":
        return dt > ERROR_THRESHOLD
    if last_action == "hint":
        return dt > (last_hint_len / 10.0)
    return dt > NEW_STEP_THRESHOLD

def evaluate_action(state, row, row_p_known):
    """
    Label each action as hint/try-step variants or not-deliberate,
    using the freshly computed p_know for sense/familiarity.
    """
    action   = row.get("Action", "").strip().lower()
    outcome  = row.get("Outcome", "").strip().lower()
    now      = parse_time(row["Time"])
    deliberate = is_deliberate(state, now)

    # Update hint history
    hint_len = int(row.get("Help Level", 0)) if str(row.get("Help Level", "")).isdigit() else 0
    if hint_len > state.help_vars["last_hint_len"]:
        state.help_vars["seen_all_hints"].add(row.get("Step Name", ""))
    state.help_vars["last_hint_len"] = hint_len

    familiar = row_p_known > FAMILIARITY_THRESHOLD
    sense    = row_p_known > SENSE_THRESHOLD

    if action == "hint":
        if not deliberate:
            label = "not acceptable/hint abuse"
        elif not sense:
            label = "not acceptable/hint abuse"
        elif not familiar:
            label = "acceptable/ask hint"
        else:
            label = "preferred/ask hint"
        state.help_vars["last_action"] = "hint"

    else:
        # non-hint actions
        if not deliberate:
            label = "not acceptable/not deliberate"
        elif outcome == "correct":
            if sense:
                label = "preferred/try step"
            elif familiar:
                label = "acceptable/try step"
            else:
                label = "ask teacher for help/try step"
        else:
            label = "ask teacher for help/try step"
        state.help_vars["last_action"] = "correct" if outcome == "correct" else "error"

    state.help_vars["last_action_time"] = now
    return label



class SessionState:
    def __init__(self):
        self.attempt_window = [0] * WINDOW_SIZE
        self.help_vars = {
            "last_action_time": None,
            "last_action":      None,
            "last_hint_len":    0,
            "seen_all_hints":   set(),
        }
        # track BKT per skill
        self.onboard_skills = {}

# --- Main processing ---

with open(INPUT_CSV, newline='') as infile, \
     open(OUTPUT_CSV, 'w', newline='') as outfile:

    reader = csv.DictReader(infile)
    fieldnames = reader.fieldnames + ["Computed p_known", "System Misuse"]
    writer = csv.DictWriter(outfile, fieldnames=fieldnames)
    writer.writeheader()

    states = {}

    for row in reader:
        key = (row['Anon Student Id'], row['Session Id'])
        if key not in states:
            states[key] = SessionState()
        state = states[key]

        # Update BKT per skill (should be same as struggle detector)
        skills = [sk.strip()
                  for sk in str(row.get("KC_Model(MATHia)", "")).split(";")
                  if sk.strip()]
        p_knowns = []

        for sk in skills:
            if sk not in state.onboard_skills:
                state.onboard_skills[sk] = BKT_PARAMS.copy()
            bkt = state.onboard_skills[sk]
            p0, slip, guess, transit = (
                bkt["p_know"], bkt["p_slip"],
                bkt["p_guess"], bkt["p_transit"]
            )
            outcome = row.get("Outcome", "").strip().lower()
            if outcome == "correct":
                p_obs = (p0*(1-slip)) / (p0*(1-slip) + (1-p0)*guess)
            else:
                p_obs = (p0*slip)       / (p0*slip       + (1-p0)*(1-guess))

            new_p = round(p_obs + (1-p_obs)*transit, 2)
            bkt["p_know"] = new_p
            p_knowns.append(new_p)

        # choose max mastery across skills, default to initial
        row_p_known = max(p_knowns) if p_knowns else BKT_PARAMS["p_know"]
        row["Computed p_known"] = f"{row_p_known:.2f}"

        # Label & compute misuse signal
        label = evaluate_action(state, row, row_p_known)
        misuse_signal = 1 if (
            "hint abuse" in label or "not deliberate" in label
        ) else 0

        # Sliding window & compute misuse flag
        state.attempt_window.pop(0)
        state.attempt_window.append(misuse_signal)
        row["System Misuse"] = 1 if sum(state.attempt_window) >= MISUSE_THRESHOLD else 0

        # Write out
        writer.writerow(row)
