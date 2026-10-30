"""Consistent local-stack backups and restore rehearsal into a NEW project.

Backups contain private data and sign-in/encryption secrets. Store them outside
Git, restrict access, and encrypt them before copying off-machine.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deployment" / "compose.training.yaml"
ARCHIVES = {"hub.tar.gz": ("hub", "/data"),
            "opengym.tar.gz": ("opengym-api", "/data"),
            "endurain.tar.gz": ("endurain", "/app/backend/data")}


def write_private(path, content):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def compose(env, project=None):
    cmd = ["docker", "compose", "--env-file", str(env), "-f", str(COMPOSE)]
    return cmd + (["-p", project] if project else [])


def run(cmd, *, data=None):
    # Capture stderr: tools can report connection URLs, which must not be echoed.
    result = subprocess.run(cmd, input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError("Staging command failed: " + " ".join(cmd[-3:]))
    return result.stdout


def backup(destination):
    if destination.exists():
        raise ValueError("Backup destination must be new")
    env = ROOT / "deployment" / ".env"
    cmd = compose(env)
    active = run(cmd + ["ps", "--status", "running", "--services"]).decode().split()
    if "postgres" not in active:
        raise ValueError("Staging PostgreSQL must be running for a consistent backup")
    writers = [name for name in ("hub", "opengym-api", "endurain") if name in active]
    destination.mkdir(mode=0o700, parents=True)
    try:
        if writers:
            run(cmd + ["stop", *writers])
        database = run(cmd + ["exec", "-T", "postgres", "pg_dump", "-U", "endurain",
                              "-d", "endurain", "-Fc"])
        write_private(destination / "postgres.dump", database)
        for filename, (service, mount) in ARCHIVES.items():
            content = run(cmd + ["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar",
                                 service, "czf", "-", "-C", mount, "."])
            write_private(destination / filename, content)
        write_private(destination / "stack.env", env.read_bytes())
        names = ["postgres.dump", "stack.env", *ARCHIVES]
        manifest = {"format": 1, "files": {name: hashlib.sha256(
            (destination / name).read_bytes()).hexdigest() for name in names}}
        write_private(destination / "manifest.json", json.dumps(manifest, indent=2).encode())
    finally:
        if writers:
            run(cmd + ["up", "-d", "--no-deps", *writers])


def restore(source, project):
    if not re.fullmatch(r"aisaac-training-restore-[a-z0-9-]+", project or ""):
        raise ValueError("Use a new project name beginning aisaac-training-restore-")
    manifest = json.loads((source / "manifest.json").read_text())
    expected = {"postgres.dump", "stack.env", *ARCHIVES}
    if manifest.get("format") != 1 or set(manifest["files"]) != expected:
        raise ValueError("Unrecognized backup manifest")
    for name, digest in manifest["files"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Backup checksum mismatch")
    volumes = run(["docker", "volume", "ls", "-q", "--filter",
                   "label=com.docker.compose.project=" + project]).strip()
    if volumes:
        raise ValueError("Restore project already has volumes; choose a new name")
    cmd = compose(source / "stack.env", project)
    try:
        run(cmd + ["up", "-d", "--wait", "postgres"])
        run(cmd + ["exec", "-T", "postgres", "pg_restore", "-U", "endurain",
                   "-d", "endurain", "--no-owner", "--exit-on-error"],
            data=(source / "postgres.dump").read_bytes())
        for filename, (service, mount) in ARCHIVES.items():
            run(cmd + ["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar",
                       service, "xzf", "-", "-C", mount], data=(source / filename).read_bytes())
        # Database and archive checks happen on separate volumes from staging.
        run(cmd + ["exec", "-T", "postgres", "psql", "-U", "endurain", "-d", "endurain",
                   "-c", "SELECT 1"])
        for service, mount in ARCHIVES.values():
            run(cmd + ["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar",
                       service, "cf", "/dev/null", "-C", mount, "."])
    finally:
        run(cmd + ["stop", "postgres"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--project")
    args = parser.parse_args()
    try:
        if args.action == "backup":
            backup(args.directory)
        else:
            restore(args.directory, args.project)
    except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, str(error) + "\n")
    print(args.action.capitalize() + " completed; no production resources were changed.")


if __name__ == "__main__":
    main()
