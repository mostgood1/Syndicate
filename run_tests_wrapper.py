import sys, pathlib
sys.path.insert(0, str(pathlib.Path('.').resolve()))
import pytest
sys.exit(pytest.main(['-q', 'tests/test_live_refresh_loop.py']))
