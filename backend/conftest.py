"""pytest 根配置：保证从 backend/ 目录运行 pytest 时 app 包可导入"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
