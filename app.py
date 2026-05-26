import subprocess
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _ensure_tzdata() -> None:
    try:
        ZoneInfo("America/Chicago")
        return
    except ZoneInfoNotFoundError:
        pass

    subprocess.check_call([sys.executable, "-m", "pip", "install", "tzdata"])
    ZoneInfo("America/Chicago")


_ensure_tzdata()

from syndicate.app import app


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)