#!/usr/bin/env python3
import csv
from datetime import datetime

# file paths
INPUT_CSV  = "./Full_Data_With_Marked_Help.csv"
OUTPUT_CSV = "./Full_Struggle_Output.csv"
# ——————————————————————————————————————————————————

# Detector parameters
WINDOW_SIZE               = 10
STRUGGLE_THRESHOLD        = 3  # max #corrects in window to flag struggle
BKT_PARAMS                = {
    "p_transit": 0.2,
    "p_slip":    0.1,
    "p_guess":   0.2,
    "p_know":    0.25
}
ERROR_THRESHOLD           = 2    # seconds
NEW_STEP_THRESHOLD        = 1    # second
FAMILIARITY_THRESHOLD     = 0.4  # p_know
SENSE_THRESHOLD           = 0.6  # p_know


def parse_time(s):
    # adjust format if needed
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

def seconds_between(t1, t2):
    return (t2 - t1).total_seconds()


class StepState:
    def __init__(self):
        self.attempt_window   = [1] * WINDOW_SIZE
        self.onboard_skills   = {}  # skill_name -> BKT state
        self.step_counter     = {}
        self.help_vars        = {
            "last_action_time": None,
            "last_action":      None,
            "last_hint_len":    0,
            "seen_all_hints":   set(),
            "last_sense":       False
        }

    def init_skill(self, skill):
        if skill not in self.onboard_skills:
            self.onboard_skills[skill] = BKT_PARAMS.copy()


def last_action_is_hint(state):
    return state.help_vars["last_action"] == "hint"

def last_action_is_error(state):
    return state.help_vars["last_action"] == "error"

def seen_all_hints(state, step_id):
    return step_id in state.help_vars["seen_all_hints"]

def is_correct(outcome):
    return outcome.strip().lower() == "correct"

def is_deliberate(state, curr_time):
    last_t = state.help_vars["last_action_time"]
    if last_t is None:
        return True
    dt = seconds_between(last_t, curr_time)
    if last_action_is_error(state):
        return dt > ERROR_THRESHOLD
    if last_action_is_hint(state):
        hint_len = state.help_vars["last_hint_len"]
        return dt > (hint_len / 10.0)
    return dt > NEW_STEP_THRESHOLD


def is_familiar(state, skill):
    return state.onboard_skills[skill]["p_know"] > FAMILIARITY_THRESHOLD


def sense_of_what_to_do(state, skill):
    return state.onboard_skills[skill]["p_know"] > SENSE_THRESHOLD


def hint_is_helpful(state, *_):
    return False

def last_action_unclear_fix(state):
    return not state.help_vars["last_sense"]


def evaluate_action(state, row):
    action = row.get("Action", "").strip().lower()
    outcome = row.get("Outcome", "").strip().lower()
    step_id = row.get("Step Name", "")

    skills = [sk.strip() for sk in row.get("KC_Model(MATHia)", "").split(";") if sk.strip()]
    deliberate = is_deliberate(state, parse_time(row.get("Time", "1970-01-01 00:00:00")))
    familiar_all = all(is_familiar(state, sk) for sk in skills) if skills else False
    sense_all    = all(sense_of_what_to_do(state, sk) for sk in skills) if skills else False
    seen_all     = seen_all_hints(state, step_id)

    if action == "hint":
        if deliberate and not seen_all and (
            (not familiar_all)
            or (last_action_is_error(state) and last_action_unclear_fix(state))
            or (last_action_is_hint(state) and not hint_is_helpful(state))
        ):
            return "preferred/ask hint"
        if deliberate and ((familiar_all and not sense_all) or last_action_is_hint(state)):
            return "acceptable/ask hint"
        return "not acceptable/hint abuse"

    if deliberate:
        if not familiar_all or (last_action_is_error(state) and last_action_unclear_fix(state)):
            return "preferred/try step"
        if familiar_all and not sense_all:
            return "acceptable/try step"
        return "ask teacher for help/try step"
    return "not acceptable/not deliberate"


def update_history(state, row, eval_label):
    t = parse_time(row.get("Time", "1970-01-01 00:00:00"))
    step_id = row.get("Step Name", "")
    hint_len = 0
    if row.get("Help Level", "").isdigit():
        hint_len = int(row.get("Help Level", "0"))

    if hint_len > state.help_vars["last_hint_len"]:
        state.help_vars["seen_all_hints"].add(step_id)
    state.help_vars["last_hint_len"] = hint_len

    state.help_vars["last_sense"] = eval_label.startswith("preferred") or eval_label.startswith("acceptable")

    action = row.get("Action", "").strip().lower()
    st = "hint" if action == "hint" else ("correct" if is_correct(row.get("Outcome", "")) else "error")
    state.help_vars["last_action"] = st
    state.help_vars["last_action_time"] = t


def receive_transaction(state, row):
    skills = [sk.strip() for sk in row.get("KC_Model(MATHia)", "").split(";") if sk.strip()]
    for sk in skills:
        state.init_skill(sk)
        bkt = state.onboard_skills[sk]
        p0, slip, guess, transit = bkt["p_know"], bkt["p_slip"], bkt["p_guess"], bkt["p_transit"]
        outcome = row.get("Outcome", "").strip().lower()
        if outcome == "correct":
            p_obs = (p0*(1-slip)) / (p0*(1-slip) + (1-p0)*guess)
        else:
            p_obs = (p0*slip) / (p0*slip + (1-p0)*(1-guess))
        bkt["p_know"] = round(p_obs + (1-p_obs)*transit, 2)

    label = evaluate_action(state, row)
    if label.startswith("ask teacher for help"):
        # Penalize BKT low master (struggle) by adding more zeros in window
        for _ in range(WINDOW_SIZE - STRUGGLE_THRESHOLD):
            state.attempt_window.pop(0)
            state.attempt_window.append(0)

    correct = 1 if is_correct(row.get("Outcome", "")) else 0
    state.attempt_window.pop(0)
    state.attempt_window.append(correct)

    update_history(state, row, label)


def main():
    states = {}
    with open(INPUT_CSV, newline='') as fin, open(OUTPUT_CSV, "w", newline='') as fout:
        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames + ["Struggle"]
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            key = (
                row.get("Anon Student Id"),
                row.get("Session Id"),
                row.get("Step Name")
            )
            if key not in states:
                states[key] = StepState()
            st = states[key]
            receive_transaction(st, row)
            row["Struggle"] = 1 if sum(st.attempt_window) <= STRUGGLE_THRESHOLD else 0
            writer.writerow(row)

if __name__ == "__main__":
    main()
