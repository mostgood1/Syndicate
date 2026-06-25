from __future__ import annotations

import json
import os
import threading
from typing import Callable


def _public_version_payload() -> dict[str, str] | None:
	commit = str(
		os.environ.get("RENDER_GIT_COMMIT")
		or os.environ.get("GIT_COMMIT")
		or os.environ.get("SOURCE_VERSION")
		or ""
	).strip()
	branch = str(
		os.environ.get("RENDER_GIT_BRANCH")
		or os.environ.get("GIT_BRANCH")
		or ""
	).strip()
	if not commit and not branch:
		return None
	payload: dict[str, str] = {}
	if commit:
		payload["commit"] = commit
	if branch:
		payload["branch"] = branch
	return payload


def _json_response(status: str, payload: dict[str, object]) -> tuple[str, list[tuple[str, str]], bytes]:
	body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
	headers = [
		("Content-Type", "application/json"),
		("Content-Length", str(len(body))),
	]
	return status, headers, body


class LazyApplication:
	def __init__(self) -> None:
		self._app = None
		self._lock = threading.Lock()

	def _load_app(self):
		if self._app is not None:
			return self._app
		with self._lock:
			if self._app is None:
				from syndicate.app import create_app

				self._app = create_app()
		return self._app

	def __call__(self, environ, start_response):
		path = str(environ.get("PATH_INFO") or "/")
		method = str(environ.get("REQUEST_METHOD") or "GET").upper()

		if path in {"/", "/healthz", "/api/health"}:
			payload: dict[str, object] = {"ok": True, "service": "syndicate"}
			version = _public_version_payload()
			if version:
				payload["version"] = version
			status, headers, body = _json_response("200 OK", payload)
			start_response(status, headers)
			if method == "HEAD":
				return [b""]
			return [body]

		app = self._load_app()
		return app(environ, start_response)


application = LazyApplication()