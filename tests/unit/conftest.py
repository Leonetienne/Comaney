import sys
import os

# Make the project root importable so 'buddies.debt_utils' can be found
# without Django being configured.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
