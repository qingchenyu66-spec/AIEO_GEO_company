from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402


def main() -> int:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    command = [
        str(python),
        "-m",
        "celery",
        "-A",
        "app.celery_app",
        "flower",
        f"--port={settings.flower_port}",
        "--address=0.0.0.0",
        "--loglevel=info",
    ]
    auth = settings.flower_basic_auth.strip()
    if auth:
        command.append(f"--basic_auth={auth}")
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
