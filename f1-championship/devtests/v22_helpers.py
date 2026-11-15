"""Test helpers for isolated v22 modules; no shared engine dependency."""


def assert_no_secrets(test, value, forbidden_keys=("seed", "rng", "secret", "hidden", "future_draw", "tendency_assignment", "rain_path", "private")):
    def visit(node):
        if isinstance(node, dict):
            for key, child in node.items():
                lowered = str(key).lower()
                for forbidden in forbidden_keys:
                    test.assertNotIn(forbidden, lowered, f"secret-shaped key: {key}")
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
