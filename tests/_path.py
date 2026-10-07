"""Make the pipeline package importable from tests without installing it."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline")
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def fixture_text(name: str) -> str:
    with open(fixture(name), "r", encoding="utf-8") as fh:
        return fh.read()


def fixture_json(name: str):
    import json
    with open(fixture(name), "r", encoding="utf-8") as fh:
        return json.load(fh)
