"""Encrypted, Render-free backup of the fleet's secrets (todo #766 D5, option E1).

    python3 scripts/fleet_secrets_backup.py backup            # nightly, inside `local_production.py backup`
    python3 scripts/fleet_secrets_backup.py verify            # decrypt the newest, compare with the live files
    python3 scripts/fleet_secrets_backup.py restore --file <x.tar.gpg> --to <empty dir>

WHY THIS EXISTS `[2026-11-16, lane render-retirement, user: "Yes, build E1"]`. Every live
secret the fleet runs on lives in two places on ONE WSL disk:

  * `<home>/render_env/<role>.json` -- each role's full env (88 / 182 / 148 keys),
    imported once from Render on 2026-10-01;
  * `<home>/local_production.env` -- the overrides (78 keys, 42 of them `ROLE__KEY`).

The nightly `backup` copies the DATA ROOT (`<home>/data`) only, so neither file was in any
backup, and the one documented recovery -- re-importing from the Render API -- was retired
on 2026-11-15 because Render must not be needed for anything. A lost disk lost every venue
and API key. This closes that.

WHAT IT DOES. It reads those files, builds a tar IN MEMORY (with a `MANIFEST.json` of names,
sizes and sha256 -- never values), pipes it to `gpg --symmetric` (AES256, SHA512 S2K), and
writes ONE `fleet-secrets-<UTC>.tar.gpg` into the off-disk directory (`<offdisk>/secrets`;
OneDrive on the fleet), `.partial` until complete. **Plaintext never touches a disk** other
than the files it came from. Then it decrypts what it just wrote and checks every file
against the manifest, so a backup that cannot be restored is a FAILED run, not a quiet one.
The newest `--keep` files are kept.

THE PASSPHRASE is a FILE on the fleet host (`~/.syndicate-secrets-passphrase`, mode 600,
>= 16 characters), created by the user, who also keeps the same passphrase in their password
manager. That copy is the only one off this machine, and without it the backups are
useless. This tool never prints it, never generates it, and refuses a file that is group- or
world-readable.

NEVER PRINTS A SECRET. Output is file names, byte counts, key COUNTS and match/differs
verdicts. Exit codes: 0 ok; 2 refused (missing inputs, bad arguments); 3 no usable passphrase
file; 4 gpg failed; 5 verification failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

EXIT_OK, EXIT_REFUSED, EXIT_NO_PASSPHRASE, EXIT_GPG, EXIT_VERIFY = 0, 2, 3, 4, 5

DEFAULT_HOME = "~/syndicate-prod"
DEFAULT_PASSPHRASE_FILE = "~/.syndicate-secrets-passphrase"
ENV_FILE_NAME = "local_production.env"
SNAPSHOT_DIR_NAME = "render_env"
MANIFEST_NAME = "MANIFEST.json"
PREFIX, SUFFIX = "fleet-secrets-", ".tar.gpg"
MIN_PASSPHRASE_CHARS = 16
DEFAULT_KEEP = 30
TOOL_VERSION = 1

# AES256 with a slow, salted SHA512 S2K. `--pinentry-mode loopback` lets `--passphrase-file`
# work under gpg 2.1+ without an agent prompt; `--batch` makes any prompt an error instead.
GPG_COMMON = ["--batch", "--yes", "--quiet", "--no-tty", "--pinentry-mode", "loopback"]
GPG_ENCRYPT = ["--symmetric", "--cipher-algo", "AES256", "--s2k-mode", "3",
               "--s2k-digest-algo", "SHA512", "--s2k-count", "65011712"]


class Refused(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def secret_files(home: Path) -> list[tuple[str, Path]]:
    """(archive name, path) for every file this backs up, in a stable order.

    `local_production.env` must exist and `render_env/` must hold at least one `.json`:
    a backup missing either is a backup of the wrong home, refused rather than written.
    """
    env_file = home / ENV_FILE_NAME
    snap_dir = home / SNAPSHOT_DIR_NAME
    if not env_file.is_file():
        raise Refused(EXIT_REFUSED, f"no {ENV_FILE_NAME} under {home} -- is --home the fleet home?")
    snaps = sorted(p for p in snap_dir.iterdir() if p.is_file()) if snap_dir.is_dir() else []
    if not any(p.suffix == ".json" for p in snaps):
        raise Refused(EXIT_REFUSED, f"no {SNAPSHOT_DIR_NAME}/*.json under {home}")
    return [(ENV_FILE_NAME, env_file)] + [(f"{SNAPSHOT_DIR_NAME}/{p.name}", p) for p in snaps]


def check_passphrase_file(path: Path) -> Path:
    """The passphrase FILE, after the checks that make it safe to rely on. Never read here."""
    if not path.is_file():
        raise Refused(EXIT_NO_PASSPHRASE, (
            f"no passphrase file at {path}. Create it ON THE FLEET HOST and keep the same "
            "passphrase in your password manager (the only copy off this machine), e.g.:\n"
            f"  ( umask 077; openssl rand -base64 33 > {path} )   # then copy it into the password manager"))
    info = path.stat()
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        raise Refused(EXIT_NO_PASSPHRASE, f"{path} is readable by group/others (mode "
                      f"{stat.S_IMODE(info.st_mode):o}); run: chmod 600 {path}")
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) < MIN_PASSPHRASE_CHARS:
        raise Refused(EXIT_NO_PASSPHRASE, f"{path} holds fewer than {MIN_PASSPHRASE_CHARS} characters")
    return path


def env_file_setting(env_file: Path, key: str) -> str:
    """One NON-secret setting from `local_production.env` (a path), by exact key."""
    try:
        lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def default_out_dir(home: Path) -> Path | None:
    """`SYNDICATE_SECRETS_BACKUP_DIR`, else `<offdisk>/secrets` where offdisk is the data
    backup's own off-disk directory (`SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR`, environment then
    `local_production.env`), else `/mnt/c/SyndicateBackup/secrets` on WSL, else None."""
    explicit = os.environ.get("SYNDICATE_SECRETS_BACKUP_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    offdisk = (os.environ.get("SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR", "").strip()
               or env_file_setting(home / ENV_FILE_NAME, "SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR"))
    if offdisk:
        return Path(offdisk).expanduser() / "secrets"
    if os.name != "nt" and Path("/mnt/c").is_dir():
        return Path("/mnt/c/SyndicateBackup/secrets")
    return None


# ---------------------------------------------------------------------------
# the archive (in memory)
# ---------------------------------------------------------------------------

def key_count(name: str, data: bytes) -> int | None:
    """How many keys a file holds -- a COUNT, never a key or a value."""
    try:
        if name.endswith(".json"):
            payload = json.loads(data.decode("utf-8"))
            values = payload.get("values") if isinstance(payload, dict) else None
            return len(values) if isinstance(values, dict) else None
        if name.endswith(".env"):
            return sum(1 for line in data.decode("utf-8", errors="replace").splitlines()
                       if line.strip() and not line.lstrip().startswith("#") and "=" in line)
    except (ValueError, UnicodeDecodeError):
        return None
    return None


def build_archive(files: list[tuple[str, Path]], *, home: Path, now: dt.datetime) -> tuple[bytes, dict]:
    """(tar bytes, manifest). Members are mode 0600; the manifest is a member too."""
    entries, blobs = [], []
    for name, path in files:
        data = path.read_bytes()
        blobs.append((name, data, path.stat().st_mtime))
        entries.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "keys": key_count(name, data)})
    manifest = {"tool_version": TOOL_VERSION, "created_at": now.isoformat(), "host": socket.gethostname(),
                "home": str(home), "files": entries}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data, mtime in [(MANIFEST_NAME, json.dumps(manifest, indent=1).encode("utf-8"), now.timestamp()),
                                  *blobs]:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o600, int(mtime)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue(), manifest


def read_archive(tar_bytes: bytes) -> tuple[dict, dict[str, bytes]]:
    """(manifest, {name: bytes}) from a decrypted archive; refuses anything but plain files."""
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        for member in tar.getmembers():
            if not member.isfile() or member.name.startswith(("/", "..")) or ".." in Path(member.name).parts:
                raise Refused(EXIT_VERIFY, f"unexpected archive member {member.name!r}")
            handle = tar.extractfile(member)
            members[member.name] = handle.read() if handle else b""
    if MANIFEST_NAME not in members:
        raise Refused(EXIT_VERIFY, "archive has no MANIFEST.json")
    manifest = json.loads(members.pop(MANIFEST_NAME).decode("utf-8"))
    return manifest, members


def integrity_problems(manifest: dict, members: dict[str, bytes]) -> list[str]:
    """Every way the archive disagrees with its own manifest (empty = intact)."""
    problems = []
    listed = {entry["path"]: entry for entry in manifest.get("files") or []}
    for name in sorted(set(listed) | set(members)):
        if name not in members:
            problems.append(f"{name}: in the manifest, not in the archive")
        elif name not in listed:
            problems.append(f"{name}: in the archive, not in the manifest")
        elif hashlib.sha256(members[name]).hexdigest() != listed[name]["sha256"]:
            problems.append(f"{name}: content does not match its manifest hash")
    if not members:
        problems.append("the archive holds no files")
    return problems


# ---------------------------------------------------------------------------
# gpg
# ---------------------------------------------------------------------------

def _gpg(args: list[str], data: bytes) -> bytes:
    gpg = os.environ.get("SYNDICATE_GPG", "gpg")
    try:
        proc = subprocess.run([gpg, *GPG_COMMON, *args], input=data, capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(EXIT_GPG, f"gpg could not run: {type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        # gpg's stderr carries no secret (the passphrase is read from a file it never echoes).
        raise Refused(EXIT_GPG, f"gpg rc={proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return proc.stdout


def encrypt(tar_bytes: bytes, passphrase_file: Path) -> bytes:
    return _gpg(["--passphrase-file", str(passphrase_file), *GPG_ENCRYPT, "--output", "-"], tar_bytes)


def decrypt(blob: bytes, passphrase_file: Path) -> bytes:
    return _gpg(["--passphrase-file", str(passphrase_file), "--decrypt"], blob)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def backups_in(out_dir: Path) -> list[Path]:
    return sorted(out_dir.glob(f"{PREFIX}*{SUFFIX}")) if out_dir.is_dir() else []


def do_backup(home: Path, out_dir: Path, passphrase_file: Path, keep: int, *, now: dt.datetime | None = None) -> dict:
    """Write, re-read, verify, rotate. Returns a report; raises Refused on any failure."""
    now = now or dt.datetime.now(dt.timezone.utc)
    files = secret_files(home)
    check_passphrase_file(passphrase_file)
    tar_bytes, manifest = build_archive(files, home=home, now=now)
    blob = encrypt(tar_bytes, passphrase_file)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(f"{PREFIX}*{SUFFIX}.partial"):
        stale.unlink(missing_ok=True)
    target = out_dir / f"{PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}{SUFFIX}"
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(blob)
    os.replace(partial, target)
    # The backup is only a backup if it comes back: decrypt what is ON DISK now. A file that
    # does not is renamed `.bad`, so it can never be taken for the newest good backup.
    try:
        back_manifest, members = read_archive(decrypt(target.read_bytes(), passphrase_file))
        problems = integrity_problems(back_manifest, members)
        if not problems and back_manifest.get("files") != manifest["files"]:
            problems = ["the manifest read back differs from the one written"]
    except Refused as exc:
        problems = [str(exc)]
    except (tarfile.TarError, ValueError) as exc:
        problems = [f"{type(exc).__name__}: {exc}"]
    if problems:
        bad = target.with_name(target.name[: -len(SUFFIX)] + ".bad")
        os.replace(target, bad)
        raise Refused(EXIT_VERIFY, f"{bad.name} did not read back intact: {problems}")
    removed = []
    for old in backups_in(out_dir)[: max(0, len(backups_in(out_dir)) - int(keep))]:
        old.unlink(missing_ok=True)
        removed.append(old.name)
    return {"path": str(target), "bytes": len(blob), "files": manifest["files"], "removed": removed,
            "kept": len(backups_in(out_dir))}


def do_verify(home: Path, backup: Path, passphrase_file: Path) -> dict:
    """Decrypt `backup`, check it against its own manifest, and compare each file with the live one."""
    check_passphrase_file(passphrase_file)
    manifest, members = read_archive(decrypt(backup.read_bytes(), passphrase_file))
    problems = integrity_problems(manifest, members)
    rows = []
    for entry in manifest.get("files") or []:
        live = home / entry["path"]
        if not live.is_file():
            verdict = "NOT LIVE"
        elif hashlib.sha256(live.read_bytes()).hexdigest() == entry["sha256"]:
            verdict = "same as live"
        else:
            verdict = "DIFFERS from live"
        rows.append({**{k: entry[k] for k in ("path", "bytes", "keys")}, "live": verdict})
    return {"path": str(backup), "created_at": manifest.get("created_at"), "integrity": problems or "ok",
            "files": rows}


def do_restore(backup: Path, to_dir: Path, passphrase_file: Path, *, live_home: Path) -> dict:
    """Decrypt into an EMPTY `to_dir` (files 0600, dirs 0700). Never over the live home:
    moving files into place is a deliberate, separate step."""
    if to_dir.resolve() == live_home.resolve():
        raise Refused(EXIT_REFUSED, "refusing to restore over the live home; restore to an empty dir, then move files")
    if to_dir.exists() and any(to_dir.iterdir()):
        raise Refused(EXIT_REFUSED, f"{to_dir} is not empty")
    check_passphrase_file(passphrase_file)
    manifest, members = read_archive(decrypt(backup.read_bytes(), passphrase_file))
    problems = integrity_problems(manifest, members)
    if problems:
        raise Refused(EXIT_VERIFY, f"{backup} is not intact: {problems}")
    for name, data in members.items():
        path = to_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(path.parent, 0o700)
        path.write_bytes(data)
        if os.name != "nt":
            os.chmod(path, 0o600)
    return {"path": str(backup), "to": str(to_dir), "created_at": manifest.get("created_at"),
            "files": [{k: e[k] for k in ("path", "bytes", "keys")} for e in manifest.get("files") or []]}


def _print_files(rows: list[dict]) -> None:
    for row in rows:
        keys = "?" if row.get("keys") is None else row["keys"]
        live = f"   {row['live']}" if "live" in row else ""
        print(f"  {row['path']:40s} {row['bytes']:>7d} B  {keys:>4} keys{live}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", default=os.environ.get("SYNDICATE_LOCAL_HOME", DEFAULT_HOME))
    parser.add_argument("--passphrase-file",
                        default=os.environ.get("SYNDICATE_SECRETS_PASSPHRASE_FILE", DEFAULT_PASSPHRASE_FILE))
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("backup", help="encrypt the secrets into the off-disk dir, read the file back, rotate")
    p.add_argument("--out", help="directory (default: <offdisk>/secrets, see default_out_dir)")
    p.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    p = sub.add_parser("verify", help="decrypt a backup (default: the newest) and compare it with the live files")
    p.add_argument("--out", help="directory to take the newest backup from")
    p.add_argument("--file", help="a specific backup file")
    p = sub.add_parser("restore", help="decrypt a backup into an EMPTY directory (never over the live home)")
    p.add_argument("--file", required=True)
    p.add_argument("--to", required=True)
    args = parser.parse_args(argv)

    home = Path(args.home).expanduser()
    passphrase_file = Path(args.passphrase_file).expanduser()
    try:
        if args.command == "backup":
            out_dir = Path(args.out).expanduser() if args.out else default_out_dir(home)
            if out_dir is None:
                raise Refused(EXIT_REFUSED, "no off-disk directory: pass --out or set SYNDICATE_SECRETS_BACKUP_DIR")
            report = do_backup(home, out_dir, passphrase_file, args.keep)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(f"secrets backup {report['path']}: {report['bytes']} B encrypted, read back intact, "
                      f"{report['kept']} kept" + (f", removed {len(report['removed'])}" if report["removed"] else ""))
                _print_files(report["files"])
            return EXIT_OK
        if args.command == "verify":
            if args.file:
                backup = Path(args.file).expanduser()
            else:
                out_dir = Path(args.out).expanduser() if args.out else default_out_dir(home)
                found = backups_in(out_dir) if out_dir else []
                if not found:
                    raise Refused(EXIT_REFUSED, f"no {PREFIX}*{SUFFIX} in {out_dir}")
                backup = found[-1]
            report = do_verify(home, backup, passphrase_file)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(f"verify {report['path']} (created {report['created_at']}): integrity {report['integrity']}")
                _print_files(report["files"])
            return EXIT_OK if report["integrity"] == "ok" else EXIT_VERIFY
        report = do_restore(Path(args.file).expanduser(), Path(args.to).expanduser(), passphrase_file, live_home=home)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"restored {report['path']} (created {report['created_at']}) into {report['to']}:")
            _print_files(report["files"])
            print("Move the files into the fleet home by hand, keep them mode 600, then a drained full down/up.")
        return EXIT_OK
    except Refused as exc:
        print(f"{'REFUSED' if exc.code in (EXIT_REFUSED, EXIT_NO_PASSPHRASE) else 'FAILED'}: {exc}", flush=True)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
