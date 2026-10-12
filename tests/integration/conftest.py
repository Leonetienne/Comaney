"""
Opt-in live tests against a real model server. Collected only when
LOCAL_AI_TEST_BASE_URL is set, so default pytest runs never touch them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if not os.environ.get("LOCAL_AI_TEST_BASE_URL"):
    collect_ignore_glob = ["test_*.py"]
