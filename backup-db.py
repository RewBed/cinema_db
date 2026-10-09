"""Stream the production PostgreSQL backup over SSH; never write it on prod.

Run backup-db.ps1 on Windows. SSH credentials are entered at launch.
The backup is a point-in-time snapshot, not continuous protection of new writes.
"""

import argparse
import base64
import hashlib
import json
import getpass
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parent


def stream_command(client, command, destination, idle_timeout=3600):
    """Drain both SSH streams to avoid deadlocks and preserve binary bytes."""
    partial = destination.with_name(destination.name + ".partial")
    digest = hashlib.sha256()
    total = 0
    started = last_data = last_report = time.monotonic()
    transport = client.get_transport()
    channel = transport.open_session(timeout=30)
    try:
        channel.exec_command(command)
        channel.shutdown_write()
        with partial.open("xb") as output:
            while True:
                received = False
                while channel.recv_ready():
                    chunk = channel.recv(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                    received = True
                while channel.recv_stderr_ready():
                    message = channel.recv_stderr(65536)
                    if message:
                        sys.stderr.write(message.decode("utf-8", errors="replace"))
                        sys.stderr.flush()
                        received = True
                now = time.monotonic()
                if received:
                    last_data = now
                if now - last_report >= 10:
                    print(f"  {destination.name}: {total / 1024**2:.1f} MiB, "
                          f"{now - started:.0f}s", flush=True)
                    last_report = now
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    status = channel.recv_exit_status()
                    if status != 0:
                        raise RuntimeError(f"Remote command failed (exit {status}); partial file retained.")
                    break
                if not transport.is_active() or channel.closed:
                    raise RuntimeError("SSH disconnected; partial file retained.")
                if now - last_data > idle_timeout:
                    raise TimeoutError("No SSH output for one hour; partial file retained.")
                if not received:
                    time.sleep(0.05)
            output.flush()
            os.fsync(output.fileno())
        if total == 0:
            raise RuntimeError("Empty backup output; partial file retained.")
        partial.rename(destination)
        print(f"  Saved {destination.name}: {total / 1024**2:.1f} MiB", flush=True)
        return digest.hexdigest()
    finally:
        channel.close()


def connect(host, user, password, port, known_hosts):
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("Paramiko is missing. Run backup-db.ps1 to prepare dependencies.") from None

    class ConfirmHostKey(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
            print(f"First SSH connection to {hostname}: {key.get_name()} SHA256:{fingerprint}")
            print("Compare this fingerprint with your server/provider console.")
            if input("Trust this host key? Type yes: ").strip().lower() != "yes":
                raise RuntimeError("SSH host key was not accepted.")
            client.get_host_keys().add(hostname, key.get_name(), key)
            client.save_host_keys(str(known_hosts))

    client = paramiko.SSHClient()
    if known_hosts.exists():
        client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(ConfirmHostKey())
    try:
        client.connect(host, port=port, username=user, password=password,
                       allow_agent=False, look_for_keys=False, timeout=30,
                       banner_timeout=30, auth_timeout=30)
        client.get_transport().set_keepalive(30)
        return client
    except BaseException:
        client.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="SSH server address (prompted if omitted)")
    parser.add_argument("--user", help="SSH login (prompted if omitted)")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--container", help="Explicit container instead of Swarm service lookup")
    parser.add_argument("--service", default="cinema_db_cinema-postgres")
    parser.add_argument("--sudo", action="store_true", help="Use sudo -n for remote Docker commands")
    parser.add_argument("--database", default="cinema")
    parser.add_argument("--db-user", default="cinema")
    parser.add_argument("--check", action="store_true", help="Validate parameters locally; do not connect")
    args = parser.parse_args()
    host = (args.host or input("SSH server: ")).strip()
    user = (args.user or input("SSH login: ")).strip()
    port = args.port
    if not host or not user or not 1 <= port <= 65535:
        parser.error("SSH host and login are required; port must be between 1 and 65535.")
    if args.check:
        print("SSH parameters are valid. No connection or backup was started.")
        return

    output = ROOT / "backups"
    output.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(output).free
    if free < 10 * 1024**3:
        raise RuntimeError("Less than 10 GiB free in the database project directory.")
    password = getpass.getpass("SSH password: ")
    if not password:
        raise ValueError("SSH password is required.")
    backup_dir = output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir.mkdir(mode=0o700)
    print(f"Backup directory: {backup_dir}")
    print("Streaming from prod; no remote backup files are created.")
    print("Writes after the dump snapshot are NOT included. Do not run prod migrations during backup.")
    docker = "sudo -n docker" if args.sudo else "docker"
    connection = " -U " + shlex.quote(args.db_user)
    checksums = []
    with connect(host, user, password, port, output / "known_hosts") as client:
        container = args.container
        if not container:
            lookup = docker + " ps -q --filter " + shlex.quote(
                "label=com.docker.swarm.service.name=" + args.service)
            stdin, stdout, stderr = client.exec_command(lookup, timeout=30)
            stdin.close()
            containers = stdout.read().decode().split()
            error = stderr.read().decode("utf-8", errors="replace").strip()
            if stdout.channel.recv_exit_status() != 0:
                raise RuntimeError("Cannot find PostgreSQL container: " + error)
            if len(containers) != 1:
                raise RuntimeError("Expected one running PostgreSQL container for " + args.service
                                   + "; connect to the node running the database.")
            container = containers[0]
        prefix = docker + " exec " + shlex.quote(container) + " "
        commands = [
            ("postgres-version.txt", prefix + "postgres --version"),
            ("globals.sql", prefix + "pg_dumpall" + connection + " --globals-only"),
            ("cinema.dump", prefix + "pg_dump" + connection + " -d " + shlex.quote(args.database)
             + " --format=custom --compress=6"),
        ]
        for filename, command in commands:
            print(f"Downloading {filename}...", flush=True)
            checksums.append((filename, stream_command(client, command, backup_dir / filename)))
    with (backup_dir / "cinema.dump").open("rb") as archive:
        if archive.read(5) != b"PGDMP":
            (backup_dir / "cinema.dump").rename(backup_dir / "cinema.dump.partial")
            raise RuntimeError("Invalid PostgreSQL archive header. Backup is incomplete.")
    (backup_dir / "SHA256SUMS").write_text(
        "".join(f"{digest}  {filename}\n" for filename, digest in checksums), encoding="utf-8")
    metadata = {
        "download_completed_utc": datetime.now(timezone.utc).isoformat(),
        "container": container,
        "database": args.database,
        "db_user": args.db_user,
        "format": "custom",
        "files": {filename: {"sha256": digest, "bytes": (backup_dir / filename).stat().st_size}
                  for filename, digest in checksums},
        "restore_verified": False,
        "note": "Snapshot only. Validate by a full restore into a separate PostgreSQL 17 instance.",
    }
    (backup_dir / "backup-complete.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Download completed: {backup_dir}")
    print("Full restore has NOT been verified. Restore into a separate local PostgreSQL 17 before experiments.")
    print("globals.sql may contain password hashes; keep this directory private.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Partial files are not valid backups.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        sys.exit(1)
