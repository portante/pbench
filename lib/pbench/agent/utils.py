import logging
import os
import subprocess
import sys

from datetime import datetime
from pathlib import Path

from pbench.agent.constants import (
    sysinfo_opts_available,
    sysinfo_opts_convenience,
    sysinfo_opts_default,
)


def setup_logging(debug, logfile):
    """Setup logging for client
    :param debug: Turn on debug logging
    :param logfile: Logfile to write to
    """
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(message)s"

    rootLogger = logging.getLogger()
    # cause all messages to be processed when the logger is the root logger
    # or delegation to the parent when the logger is a non-root logger
    # see https://docs.python.org/3/library/logging.html
    rootLogger.setLevel(logging.NOTSET)

    streamhandler = logging.StreamHandler()
    streamhandler.setLevel(level)
    streamhandler.setFormatter(logging.Formatter(fmt))
    rootLogger.addHandler(streamhandler)

    if logfile:
        if not os.environ.get("_PBENCH_UNIT_TESTS"):
            fmt = "[%(levelname)-1s][%(asctime)s.%(msecs)d] %(message)s"
        else:
            fmt = "[%(levelname)-1s][1900-01-01T00:00:00.000000] %(message)s"
        filehandler = logging.FileHandler(logfile)
        filehandler.setLevel(logging.NOTSET)
        filehandler.setFormatter(logging.Formatter(fmt))
        rootLogger.addHandler(filehandler)

    return rootLogger


def run_command(args, env=None, name=None, logger=None):
    """Run the command defined by args and return its output"""
    try:
        output = subprocess.check_output(args=args, stderr=subprocess.STDOUT, env=env)
        if isinstance(output, bytes):
            output = output.decode("utf-8")
        return output
    except subprocess.CalledProcessError as e:
        message = "%s failed: %s" % (name, e.output)
        logger.error(message)
        raise RuntimeError(message)


def _log_date():
    if os.environ.get("_PBENCH_UNIT_TESTS", "0") == "1":
        log_date = "1900-01-01T00:00:00.000000"
    else:
        log_date = datetime.utcnow().isoformat()
    return log_date


def _pbench_log(message):
    with open(os.environ["pbench_log"], "a+") as fp:
        print(message, file=fp)


def warn_log(msg):
    message = f"[warn][{_log_date()}] {msg}"
    print(message, file=sys.stderr)
    _pbench_log(message)


def error_log(msg):
    message = f"[error][{_log_date()}] {msg}"
    print(message, file=sys.stderr)
    _pbench_log(message)


def info_log(msg):
    message = f"[info][{_log_date()}] {msg}"
    _pbench_log(message)


def verify_sysinfo(sysinfo):
    if sysinfo == "default":
        return sorted(list(sysinfo_opts_default)), []
    elif sysinfo == "all":
        return sorted(list(sysinfo_opts_available)), []
    elif sysinfo == "none":
        return [], []

    sysinfo_list = sysinfo.split(",")
    final_list = []
    bad_list = []
    for item in sysinfo_list:
        item = item.strip()
        if len(item) == 0:
            continue
        if item in sysinfo_opts_available:
            final_list.append(item)
            continue
        if item in sysinfo_opts_convenience:
            # Ignore convenience arguments
            continue
        bad_list.append(item)

    return sorted(final_list), sorted(bad_list)


def collect_local_info(pbench_bin):
    try:
        version = (pbench_bin / "VERSION").read_text()
    except Exception:
        version = "(unknown)"
    try:
        seqno = (pbench_bin / "SEQNO").read_text()
    except Exception:
        seqno = ""
    try:
        sha1 = (pbench_bin / "SHA1").read_text()
    except Exception:
        sha1 = "(unknown)"

    hostdata = {}
    for arg in ["f", "s", "i", "I", "A"]:
        cp = subprocess.run(
            ["hostname", f"-{arg}"],
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        hostdata[arg] = cp.stdout.strip() if cp.stdout is not None else ""

    return (version, seqno, sha1, hostdata)


class BadToolGroup(Exception):
    """Exception representing a tool group that does not exist or is invalid.
    """

    pass


# Current tool group prefix in use.
TOOL_GROUP_PREFIX = "tools-v1"


def verify_tool_group(group, pbench_run=None):
    """verify_tool_group - given a tool group name, verify it exists in the
    ${pbench_run} directory as a properly prefixed tool group directory name.

    Raises a BadToolGroup exception if the directory is invalid or does not
    exist.

    Returns a Pathlib object of the tool group directory on success.
    """
    _pbench_run = os.environ["pbench_run"] if pbench_run is None else pbench_run
    tg_dir_name = Path(_pbench_run, f"{TOOL_GROUP_PREFIX}-{group}")
    try:
        tg_dir = tg_dir_name.resolve(strict=True)
    except FileNotFoundError:
        raise BadToolGroup(
            f"Bad tool group, '{group}': directory {tg_dir_name} does not exist"
        )
    else:
        if not tg_dir.is_dir():
            raise BadToolGroup(
                f"Bad tool group, '{group}': directory {tg_dir_name} not valid"
            )
        else:
            return tg_dir
