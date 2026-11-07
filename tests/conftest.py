import sys
from pathlib import Path

# Ensure the parent of tests/ is on sys.path so logic_manager, ai_manager, etc. import
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
