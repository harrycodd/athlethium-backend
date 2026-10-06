"""
Athlethium Test Suite Runner.
Executes all unit tests and athlete simulations.
"""

import sys
import os
import unittest

# Ensure functions/ is on pythonpath
FUNCTIONS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, FUNCTIONS_DIR)


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.join(FUNCTIONS_DIR, "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
