#!/usr/libexec/platform-python
# -*- mode: python -*-

"""Pbench Tar Balls & Unpack

The goal is to find all tar balls that are in the backup tree and restore them
to the archive tree, unpacking as appropriate (left to the unpack process to
see if the tar ball is not too old), marking them as being already backed up.

The general algorithm is:

  1. Find all the tar balls on the backup drive

  2. Sort them by the date in the tar ball from newest to oldest

  3. For each tar ball

     a. Check if tar ball exists in archive tree, if so, skip

     b. Copy tar ball to archive tree, and .md5 and run md5sum check

        * Create controller directory if it doesn't exist

        * Create TO-RE-UNPACK and BACKED-UP directories if they don't exist

     c. Create symlink to tar ball in TO-RE-UNPACK directory

  4. After processing 10 tar balls, wait for # of TO-RE-UNPACK to drop to zero
"""

import sys
import os
import re
import subprocess
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

import pbench
from pbench import (
    PbenchConfig,
    BadConfig,
    get_pbench_logger,
)


_NAME_ = "pbench-restore-and-unpack-tarballs"

tb_pat_r = r"\S+_(\d\d\d\d)[._-](\d\d)[._-](\d\d)[T_](\d\d)[._:](\d\d)[._:](\d\d)\.tar\.xz\.md5"
tb_pat = re.compile(tb_pat_r)


def gen_list(backup):
    """gen_list - traverse the given BACKUP hierarchy looking for all tar balls
    that have a .md5 file.
    """
    with os.scandir(backup) as backup_scan:
        for c_entry in backup_scan:
            if c_entry.name.startswith(".") and c_entry.is_dir(follow_symlinks=False):
                continue
            if not c_entry.is_dir(follow_symlinks=False):
                continue
            # We have a controller directory.
            with os.scandir(c_entry.path) as controller_scan:
                for entry in controller_scan:
                    if entry.name.startswith(".") and entry.is_dir(
                        follow_symlinks=False
                    ):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        continue
                    match = tb_pat.fullmatch(entry.name)
                    if not match:
                        continue
                    # Turn the pattern components of the match into a datetime
                    # object.
                    tb_dt = datetime(
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                        int(match.group(4)),
                        int(match.group(5)),
                        int(match.group(6)),
                    )
                    tb = Path(entry.path[:-4])
                    if not tb.exists():
                        print(f"what? {entry.path}")
                        sys.exit(1)
                    yield tb_dt, c_entry.name, tb


def main(options):
    if not options.cfg_name:
        print(
            f"{_NAME_}: ERROR: No config file specified; set"
            " _PBENCH_SERVER_CONFIG env variable",
            file=sys.stderr,
        )
        return 1

    try:
        config = PbenchConfig(options.cfg_name)
    except BadConfig as e:
        print(f"{_NAME_}: {e}", file=sys.stderr)
        return 2

    logger = get_pbench_logger(_NAME_, config)

    archive = config.ARCHIVE
    archive_p = Path(archive).resolve(strict=True)

    if not archive_p.is_dir():
        logger.error(
            "The configured ARCHIVE directory, {}, is not a valid directory", archive
        )
        return 4

    backup = config.conf.get("pbench-server", "pbench-backup-dir")
    backup_p = Path(backup).resolve(strict=True)

    if not backup_p.is_dir():
        logger.error(
            "The configured pbench-backup-dir directory, {}, is not a valid directory",
            backup,
        )
        return 6

    start = pbench._time()

    _msg = f"Restoring tar balls from backup volume, {backup} (started at: {start})"
    if options.dry_run:
        print(_msg)
    else:
        logger.debug(_msg)

    gen = gen_list(backup_p)
    tbs_sorted = sorted(
        [
            (tb_dt, controller_name, tar_ball_name)
            for tb_dt, controller_name, tar_ball_name in gen
        ],
        reverse=True,
    )
    tbs_cnt = len(tbs_sorted)
    tbs_left = tbs_cnt
    tbs_existing = 0
    tbs_restored = 0
    for tb_dt, ctrl, tb in tbs_sorted:
        try:
            a_tb = archive_p / ctrl / tb.name
            tbs_left -= 1

            if a_tb.exists():
                tbs_existing += 1
                print(
                    f"Exists {tbs_existing:d} ({tbs_restored:d} restored) of (tbs_cnt:d): {a_tb}",
                    flush=True,
                )
                continue

            # Create controller directory if it doesn't exist
            ctrl_p = archive_p / ctrl
            if not options.dry_run:
                ctrl_p.mkdir(exist_ok=True)

            # Copy tar ball to archive tree, along with its .md5 ...
            cp_cmd = f"cp -a {tb} {tb}.md5 {ctrl_p}/"
            print(f"\n{cp_cmd}", flush=True)
            if not options.dry_run:
                cp = subprocess.run(cp_cmd, shell=True, stderr=subprocess.STDOUT)
                if cp.returncode != 0:
                    print(
                        f"FAILURE: cp command: '{cp_cmd}': {cp.returncode}, {cp.stdout!r}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            # ... and run md5sum check against it
            md5sum_cmd = f"md5sum --check {a_tb}.md5"
            print(md5sum_cmd, flush=True)
            if not options.dry_run:
                cp = subprocess.run(md5sum_cmd, shell=True, cwd=str(ctrl_p))
                if cp.returncode != 0:
                    print(
                        f"FAILURE: md5sum command: '{md5sum_cmd}': {cp.returncode}, {cp.stdout!r}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            # Create the symlink recording the tar ball is already backed up
            backed_up_dir = ctrl_p / "BACKED-UP"
            if not options.dry_run:
                backed_up_dir.mkdir(exist_ok=True)
            backed_up = backed_up_dir / tb.name
            print(f"ln -s {a_tb} {backed_up}", flush=True)
            if not options.dry_run:
                backed_up.symlink_to(a_tb)

            # Create the symlink requesting the tar ball be unpacked
            to_unpack_dir = ctrl_p / "TO-RE-UNPACK"
            if not options.dry_run:
                to_unpack_dir.mkdir(exist_ok=True)
            to_unpack = to_unpack_dir / tb.name
            print(f"ln -s {a_tb} {to_unpack}", flush=True)
            if not options.dry_run:
                to_unpack.symlink_to(a_tb)

            tbs_restored += 1

            print(
                f"\nRestored {tbs_restored:d} ({tbs_existing:d} existing) of ({tbs_cnt:d}): {a_tb}\n",
                flush=True,
            )
        except Exception as exc:
            print(
                f"Exception while processing ({tb_dt!r}, {ctrl!r}, {tb!r}): {exc}",
                file=sys.stderr,
            )
            raise

    end = pbench._time()
    _msg = f"Restored {tbs_restored:d} tar balls from backup volume, {backup} (ended at: {end}, elapsed ({end - start:d})"
    if options.dry_run:
        print(_msg)
    else:
        logger.debug(_msg)

    sys.exit(0)


if __name__ == "__main__":
    parser = ArgumentParser(f"Usage: {_NAME_} [--config <path-to-config-file>]")
    parser.add_argument("-C", "--config", dest="cfg_name", help="Specify config file")
    parser.add_argument(
        "-D",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Perform a dry-run only",
    )
    parser.set_defaults(cfg_name=os.environ.get("_PBENCH_SERVER_CONFIG"))
    parsed = parser.parse_args()
    status = main(parsed)
    sys.exit(status)
