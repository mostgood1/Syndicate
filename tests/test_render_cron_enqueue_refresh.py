from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RenderCronEnqueueRefreshTests(unittest.TestCase):
    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "render_cron_enqueue_refresh.py"
        spec = importlib.util.spec_from_file_location("test_render_cron_enqueue_refresh", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_main_treats_already_queued_refresh_as_skip(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        error_payload = json.dumps({"ok": False, "error": "A refresh run is already queued for the external runner. Cancel it before starting a new run."})
        http_error = urllib_error = subprocess.CalledProcessError

        class BusyHTTPError(Exception):
            code = 400

            def read(self) -> bytes:
                return error_payload.encode("utf-8")

        with patch.dict(
            sys.modules,
            {"urllib.error": __import__("urllib.error", fromlist=["HTTPError"]), "urllib.request": __import__("urllib.request", fromlist=["Request"])},
        ):
            import urllib.error as real_urllib_error
            import urllib.request as real_urllib_request

            with TemporaryDirectory() as tmp_dir:
                base_url = "https://syndicate.test"
                request_data = {"sports": "mlb,nba", "phase": "live", "execution_mode": "source", "regions": "us"}

                with patch.dict(
                    sys.modules,
                    {},
                    clear=False,
                ), patch.dict(
                    module.os.environ,
                    {"ADMIN_TOKEN": "secret-token"},
                    clear=False,
                ), patch.object(module, "_coerce_base_url", return_value=base_url), patch.object(
                    real_urllib_request,
                    "urlopen",
                    side_effect=real_urllib_error.HTTPError(
                        url=f"{base_url}/api/ops/odds-refresh/run?admin_token=secret-token",
                        code=400,
                        msg="Bad Request",
                        hdrs=None,
                        fp=io.BytesIO(error_payload.encode("utf-8")),
                    ),
                ), patch.object(sys, "argv", ["render_cron_enqueue_refresh.py", "--sports", "mlb,nba", "--phase", "live", "--execution-mode", "source", "--regions", "us", "--include-mirror"]), patch.object(
                    module,
                    "print",
                ) as mocked_print:
                    exit_code = module.main()

        self.assertEqual(exit_code, 0)
        printed = " ".join(" ".join(str(part) for part in call.args) for call in mocked_print.call_args_list)
        self.assertIn('"status":"skipped"', printed)


if __name__ == "__main__":
    unittest.main()