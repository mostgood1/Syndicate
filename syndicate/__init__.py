from __future__ import annotations

# `render-egress-transport`, 2026-09-05: ask every upstream for gzip.
#
# THIS IS AN IMPORT-TIME SIDE EFFECT AND THAT IS THE POINT. It installs a
# global `urllib` opener that adds `Accept-Encoding: gzip` and gunzips the
# reply. `http.client` sends `Accept-Encoding: identity` when the caller sets
# nothing -- an EXPLICIT refusal, not a missing header -- and this repo has 122
# `urllib.request.Request` call sites, none of which set it, against upstreams
# that all serve gzip already (ESPN CFB scoreboard 1,441,192 -> 107,229 bytes,
# 13.4x; measured end to end through this opener). Outbound fetches from a
# worker are BILLED egress: the "Service-Initiated" 5.06 GB of 24.4 GB.
#
# Here rather than in the three entrypoints because this is the only module
# all three import -- web enters through `wsgi:application` -> `syndicate.app`,
# and both workers' start scripts import `syndicate.features.shared.*`. Two of
# those entrypoints are also claimed by other OPEN lanes. A choke point that
# only covers callers who opted in is not a choke point.
#
# Kill switch `SYNDICATE_HTTP_GZIP=off`; absent means ON. Never raises, and
# `http_compression.py` carries the ESPN-403 fallback and the measurements.
try:  # pragma: no cover - exercised by every import of this package
    from syndicate.features.shared.http_compression import install_http_compression

    install_http_compression()
except Exception:
    # A transport optimisation must never be the reason the platform fails to
    # import. Losing compression costs money; losing the import costs the app.
    pass


def create_app():
	from syndicate.app import create_app as _create_app

	return _create_app()


__all__ = ["create_app"]