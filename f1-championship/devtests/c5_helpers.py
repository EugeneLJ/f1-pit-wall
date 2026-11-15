"""Shared C5 public-input fixtures for devtests."""

from track_c import c5


def field():
    return {
        "Apex A": {"team": "Apex", "driver_key": "driver_a", "base_pace_sec": 89.70},
        "Apex B": {"team": "Apex", "driver_key": "driver_b", "base_pace_sec": 89.90},
        "Orion A": {"team": "Orion", "driver_key": "driver_a", "base_pace_sec": 89.45},
        "Orion B": {"team": "Orion", "driver_key": "driver_b", "base_pace_sec": 89.55},
        "Nova A": {"team": "Nova", "driver_key": "driver_a", "base_pace_sec": 89.95},
        "Nova B": {"team": "Nova", "driver_key": "driver_b", "base_pace_sec": 90.25},
        "Vertex A": {"team": "Vertex", "driver_key": "driver_a", "base_pace_sec": 90.50},
        "Vertex B": {"team": "Vertex", "driver_key": "driver_b", "base_pace_sec": 90.85},
    }


def public_state(archetype="mixed", team="Apex"):
    return c5.initial_public_state(
        c5.load_model(archetype), weekend_id="round-test", team=team,
        car_ids={"driver_a": "Apex A" if team == "Apex" else "Other A",
                 "driver_b": "Apex B" if team == "Apex" else "Other B"},
        field=field() if team == "Apex" else other_field(),
    )


def other_field():
    value = field()
    value.pop("Apex A")
    value.pop("Apex B")
    value["Other A"] = {"team": "Other", "driver_key": "driver_a", "base_pace_sec": 91.10}
    value["Other B"] = {"team": "Other", "driver_key": "driver_b", "base_pace_sec": 91.20}
    return value


def action(program_a="SETUP_TEST", setup_a="low_drag", laps_a=4,
           program_b="SETUP_TEST", setup_b="high_downforce", laps_b=4):
    return {
        "type": "PRACTICE",
        "driver_a": {"program": program_a, "setup_id": setup_a, "laps": laps_a},
        "driver_b": {"program": program_b, "setup_id": setup_b, "laps": laps_b},
    }


def zero_action():
    return action(laps_a=0, laps_b=0)


def qualifying_state(rng_key=1):
    state = public_state()
    first = c5.simulate_practice(state, zero_action(), rng_key)["state"]
    return c5.simulate_practice(first, zero_action(), rng_key)["state"]


def assert_no_secrets(test, value, forbidden_keys=("seed", "rng", "secret", "hidden", "true_effect", "future_draw")):
    def visit(node, path=""):
        if isinstance(node, dict):
            for key, child in node.items():
                lowered = str(key).lower()
                for forbidden in forbidden_keys:
                    test.assertNotIn(forbidden, lowered, f"secret-shaped key {path}{key}")
                visit(child, f"{path}{key}.")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}{index}.")
    visit(value)
