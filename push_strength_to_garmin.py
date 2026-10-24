#!/usr/bin/env python3
"""
push_strength_to_garmin.py
==========================

Reads a strength program (program.json) and creates the sessions as
*workouts* in Garmin Connect — NOT scheduled into the calendar, just
created so they show up under Training > Workouts and can be started
manually on the watch.

Each session (Pas A, Pas B, Opvarmning, ...) becomes one Garmin strength
workout, named "<garmin_tag> · <session label>". On every run the old
workouts carrying the same tag are deleted first and recreated, so the
watch always matches the program file — that is the "update".

Exercises are taken from the shared program.json (same file the website
reads). Only exercises that carry a "garmin" block are sent; pure mobility
drills without one are skipped. category/exercise are Garmin's own
exercise enums (null => a generic, un-named step with just reps/time).

Usage:
    python push_strength_to_garmin.py loberknae/program.json
    python push_strength_to_garmin.py loberknae/program.json --dry-run
    python push_strength_to_garmin.py loberknae/program.json --session A --session B
    python push_strength_to_garmin.py loberknae/program.json --delete
    python push_strength_to_garmin.py --run-tests
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import unittest
from unittest.mock import MagicMock

# --------------------------------------------------------------------------- #
# CONFIGURATION
# --------------------------------------------------------------------------- #
TOKENSTORE = os.path.expanduser("~/.garminconnect")

# Human-readable labels for the sessions, used in the Garmin workout name.
SESSION_LABELS = {
    "W": "Opvarmning",
    "A": "Pas A",
    "B": "Pas B",
}
# Order sessions are processed in when none are selected explicitly.
SESSION_ORDER = ["W", "A", "B"]

# Seconds of rest inserted between sets inside a strength workout.
REST_SECS = 60

# --------------------------------------------------------------------------- #
# GARMIN STRENGTH SCHEMA CONSTANTS
# --------------------------------------------------------------------------- #
STRENGTH_SPORT = {"sportTypeId": 5, "sportTypeKey": "strength_training"}

STEP_INTERVAL = {"stepTypeId": 3, "stepTypeKey": "interval"}
STEP_REST     = {"stepTypeId": 5, "stepTypeKey": "rest"}
STEP_REPEAT   = {"stepTypeId": 6, "stepTypeKey": "repeat"}

END_REPS       = {"conditionTypeId": 10, "conditionTypeKey": "reps"}
END_TIME       = {"conditionTypeId": 2,  "conditionTypeKey": "time"}
END_ITERATIONS = {"conditionTypeId": 7,  "conditionTypeKey": "iterations"}

WEIGHT_UNIT_KG = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}


# --------------------------------------------------------------------------- #
# PAYLOAD BUILDERS
# --------------------------------------------------------------------------- #
def exercise_step(ex: dict) -> dict:
    """One ExecutableStepDTO for a single exercise (reps or time based)."""
    g = ex["garmin"]
    mode = g.get("mode", "reps")

    step = {
        "type": "ExecutableStepDTO",
        "stepType": STEP_INTERVAL,
    }
    if mode == "time":
        step["endCondition"] = END_TIME
        step["endConditionValue"] = float(g["value"])
    else:
        step["endCondition"] = END_REPS
        step["endConditionValue"] = float(g["value"])

    if g.get("category"):
        step["category"] = g["category"]
    if g.get("exercise"):
        step["exerciseName"] = g["exercise"]

    if g.get("weight_kg"):
        step["weightValue"] = float(g["weight_kg"])
        step["weightUnit"] = WEIGHT_UNIT_KG

    return step


def rest_step(seconds: int = REST_SECS) -> dict:
    return {
        "type": "ExecutableStepDTO",
        "stepType": STEP_REST,
        "endCondition": END_TIME,
        "endConditionValue": float(seconds),
    }


def set_group(ex: dict) -> dict:
    """A RepeatGroupDTO: <sets> × (exercise + rest), last rest skipped."""
    g = ex["garmin"]
    sets = int(g.get("sets", 1))
    children = [exercise_step(ex), rest_step()]
    return {
        "type": "RepeatGroupDTO",
        "stepType": STEP_REPEAT,
        "numberOfIterations": sets,
        "endCondition": END_ITERATIONS,
        "endConditionValue": float(sets),
        "skipLastRestStep": True,
        "workoutSteps": children,
    }


def assign_step_orders(steps: list, start: int = 1) -> int:
    order = start
    for step in steps:
        step["stepOrder"] = order
        order += 1
        if step.get("type") == "RepeatGroupDTO":
            order = assign_step_orders(step["workoutSteps"], order)
    return order


def build_session_payload(tag: str, session_key: str, exercises: list) -> dict | None:
    """Build one strength workout from the exercises that carry a garmin block."""
    steps = [set_group(ex) for ex in exercises if ex.get("garmin")]
    if not steps:
        return None

    assign_step_orders(steps)
    label = SESSION_LABELS.get(session_key, session_key)
    name = f"{tag} · {label}"

    return {
        "sportType": STRENGTH_SPORT,
        "workoutName": name,
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": STRENGTH_SPORT, "workoutSteps": steps}
        ],
    }


# --------------------------------------------------------------------------- #
# TRANSPORT / API CALLS
# --------------------------------------------------------------------------- #
def _inner(client):
    return getattr(client, "client", None) or getattr(client, "garth", None)


def _request_json(client, method: str, path: str, **kw):
    inner = _inner(client)
    last = None
    for use_api in (True, False):
        try:
            resp = inner.request(method, "connectapi", path, api=use_api, **kw) if use_api \
                else inner.request(method, "connectapi", path, **kw)
            if resp is None:
                return None
            return resp.json() if hasattr(resp, "json") else resp
        except TypeError as exc:
            last = exc
            continue
    raise RuntimeError(f"Could not call {method} {path}: {last}")


def list_tagged_workouts(client, tag: str) -> list:
    try:
        data = client.get_workouts(0, 999)
    except Exception:
        data = _request_json(client, "GET", "/workout-service/workouts",
                             params={"start": 0, "limit": 999, "myWorkoutsOnly": True})
    items = data if isinstance(data, list) else (data or {}).get("workoutList", data)
    return [w for w in (items or []) if str(w.get("workoutName", "")).startswith(tag)]


def create_workout(client, payload: dict) -> int:
    res = _request_json(client, "POST", "/workout-service/workout", json=payload)
    return res["workoutId"] if isinstance(res, dict) else res


def delete_tagged_workouts(client, tag: str) -> tuple[int, int]:
    old = list_tagged_workouts(client, tag)
    print(f"Found {len(old)} existing '{tag}' workout(s) in Garmin Connect.")
    ok = fail = 0
    for w in old:
        try:
            client.delete_workout(w["workoutId"])
            print(f"  - deleted: {w.get('workoutName')}")
            ok += 1
        except Exception as exc:
            print(f"  x could not delete {w.get('workoutName')}: {exc}")
            fail += 1
    return ok, fail


# --------------------------------------------------------------------------- #
# LOGIN
# --------------------------------------------------------------------------- #
def authenticate():
    try:
        from garminconnect import Garmin
    except ImportError:
        sys.exit("Missing garminconnect. Run: pip install --upgrade garminconnect garth curl_cffi")

    token = os.getenv("GARMIN_TOKEN")
    if token:
        # Preferred for CI: a base64 garth token stored as a GitHub secret.
        try:
            import garth
            garth.client.loads(base64.b64decode(token).decode() if _looks_b64(token) else token)
            os.makedirs(TOKENSTORE, exist_ok=True)
            garth.save(TOKENSTORE)
        except Exception as exc:
            sys.exit(f"GARMIN_TOKEN could not be loaded: {exc}")

    email    = os.getenv("GARMIN_EMAIL") or os.getenv("EMAIL")
    password = os.getenv("GARMIN_PASSWORD") or os.getenv("PASSWORD")
    have_token = os.path.isdir(TOKENSTORE) and any(os.scandir(TOKENSTORE))

    if not have_token and not (email and password):
        sys.exit("Need GARMIN_TOKEN, or an existing token store, or GARMIN_EMAIL + GARMIN_PASSWORD.")

    client = Garmin(email, password, prompt_mfa=lambda: input("MFA code: "))
    client.login(TOKENSTORE)
    return client


def _looks_b64(s: str) -> bool:
    try:
        base64.b64decode(s, validate=True)
        return not s.strip().startswith("{")
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# UNIT TESTS
# --------------------------------------------------------------------------- #
class TestStrengthPayload(unittest.TestCase):
    def _ex(self, **g):
        base = {"category": "SQUAT", "exercise": "GOBLET_SQUAT",
                "mode": "reps", "sets": 3, "value": 12, "per_side": False, "weight_kg": None}
        base.update(g)
        return {"n": "X", "garmin": base}

    def test_reps_step(self):
        step = exercise_step(self._ex())
        self.assertEqual(step["endCondition"]["conditionTypeKey"], "reps")
        self.assertEqual(step["endConditionValue"], 12.0)
        self.assertEqual(step["category"], "SQUAT")
        self.assertEqual(step["exerciseName"], "GOBLET_SQUAT")
        self.assertNotIn("weightValue", step)

    def test_time_step(self):
        step = exercise_step(self._ex(mode="time", value=40))
        self.assertEqual(step["endCondition"]["conditionTypeKey"], "time")
        self.assertEqual(step["endConditionValue"], 40.0)

    def test_generic_step_has_no_exercise_fields(self):
        step = exercise_step(self._ex(category=None, exercise=None))
        self.assertNotIn("category", step)
        self.assertNotIn("exerciseName", step)

    def test_weight_is_set(self):
        step = exercise_step(self._ex(weight_kg=8))
        self.assertEqual(step["weightValue"], 8.0)
        self.assertEqual(step["weightUnit"]["unitKey"], "kilogram")

    def test_set_group_structure(self):
        grp = set_group(self._ex(sets=3))
        self.assertEqual(grp["type"], "RepeatGroupDTO")
        self.assertEqual(grp["numberOfIterations"], 3)
        self.assertTrue(grp["skipLastRestStep"])
        self.assertEqual(grp["workoutSteps"][1]["stepType"]["stepTypeKey"], "rest")

    def test_build_session_payload_name_and_skip(self):
        exercises = [
            {"n": "Foam rolling"},  # no garmin -> skipped
            self._ex(),
        ]
        payload = build_session_payload("LØBERKNÆ", "A", exercises)
        self.assertEqual(payload["workoutName"], "LØBERKNÆ · Pas A")
        self.assertEqual(payload["sportType"]["sportTypeKey"], "strength_training")
        self.assertEqual(len(payload["workoutSegments"][0]["workoutSteps"]), 1)

    def test_empty_session_returns_none(self):
        self.assertIsNone(build_session_payload("T", "A", [{"n": "only mobility"}]))

    def test_step_orders_are_unique_and_sequential(self):
        payload = build_session_payload("T", "A", [self._ex(), self._ex()])
        orders = []
        def collect(steps):
            for s in steps:
                orders.append(s["stepOrder"])
                if s.get("workoutSteps"):
                    collect(s["workoutSteps"])
        collect(payload["workoutSegments"][0]["workoutSteps"])
        self.assertEqual(orders, list(range(1, len(orders) + 1)))


class TestDeletionLogic(unittest.TestCase):
    def test_list_and_delete_filter_by_tag(self):
        client = MagicMock()
        client.get_workouts.return_value = [
            {"workoutId": 1, "workoutName": "LØBERKNÆ · Pas A"},
            {"workoutId": 2, "workoutName": "LØBERKNÆ · Pas B"},
            {"workoutId": 9, "workoutName": "HM26 W01-Mon Easy"},
        ]
        self.assertEqual(len(list_tagged_workouts(client, "LØBERKNÆ")), 2)
        ok, fail = delete_tagged_workouts(client, "LØBERKNÆ")
        self.assertEqual((ok, fail), (2, 0))
        client.delete_workout.assert_any_call(1)
        client.delete_workout.assert_any_call(2)
        for call in client.delete_workout.call_args_list:
            self.assertNotEqual(call.args[0], 9)


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Create/update a strength program as Garmin workouts (no calendar).")
    ap.add_argument("program", nargs="?", help="Path to program.json")
    ap.add_argument("--dry-run", action="store_true", help="Build and print payloads without uploading.")
    ap.add_argument("--session", action="append", help="Only this session key (W/A/B). Repeatable.")
    ap.add_argument("--delete", action="store_true", help="Delete all tagged workouts, then exit.")
    ap.add_argument("--no-clean", action="store_true", help="Don't delete existing tagged workouts before upload.")
    ap.add_argument("--run-tests", action="store_true", help="Run internal unit tests and exit.")
    args = ap.parse_args()

    if args.run_tests:
        suite = unittest.TestSuite()
        for tc in (TestStrengthPayload, TestDeletionLogic):
            suite.addTest(unittest.TestLoader().loadTestsFromTestCase(tc))
        result = unittest.TextTestRunner().run(suite)
        return 0 if result.wasSuccessful() else 1

    if not args.program:
        ap.error("program.json path is required (unless --run-tests).")

    with open(args.program, encoding="utf-8") as fh:
        program = json.load(fh)

    tag = program["garmin_tag"]
    sessions = program["sessions"]

    if args.delete:
        client = authenticate()
        ok, fail = delete_tagged_workouts(client, tag)
        print(f"\nDeleted {ok}, failed {fail}.")
        return 0 if fail == 0 else 1

    keys = args.session or [k for k in SESSION_ORDER if k in sessions] or list(sessions)
    payloads = []
    for k in keys:
        if k not in sessions:
            print(f"  ! session '{k}' not in program, skipping.")
            continue
        p = build_session_payload(tag, k, sessions[k])
        if p is None:
            print(f"  ! session '{k}' has no Garmin-mapped exercises, skipping.")
            continue
        payloads.append(p)

    if not payloads:
        print("Nothing to upload."); return 1

    print(f"Program '{program.get('program_name', tag)}' — {len(payloads)} workout(s):")
    for p in payloads:
        n_steps = len(p["workoutSegments"][0]["workoutSteps"])
        print(f"  • {p['workoutName']:<28} ({n_steps} øvelser)")

    if args.dry_run:
        print("\n--- JSON for first workout ---")
        print(json.dumps(payloads[0], ensure_ascii=False, indent=2))
        print("\n--dry-run: nothing uploaded.")
        return 0

    client = authenticate()

    if not args.no_clean:
        print(f"\nClearing existing '{tag}' workouts before upload...")
        delete_tagged_workouts(client, tag)

    print("\nUploading workouts (not scheduled to calendar)...")
    ok = fail = 0
    for payload in payloads:
        try:
            wid = create_workout(client, payload)
            print(f"  + {payload['workoutName']}  (id={wid})")
            ok += 1
        except Exception as exc:
            print(f"  x {payload['workoutName']}  ERROR: {exc}")
            fail += 1

    print(f"\nDone. {ok} created, {fail} failed.")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
