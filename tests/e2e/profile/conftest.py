"""
Add the parent tests/e2e directory to sys.path so 'from helpers import ...'
works in all test files within this sub-package.
The session-scoped driver/w fixtures are provided by the parent conftest.py
and are automatically discovered by pytest.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

