import os
import signal
import time

import psutil

from leap.common.config import get_path_prefix


class NoAuthTokenError(Exception):
    pass


def get_authenticated_url():
    url = "http://localhost:7070"
    path = os.path.join(get_path_prefix(), 'leap', 'authtoken')
    waiting = 20
    while not os.path.isfile(path):
        if waiting == 0:
            # If we arrive here, something really messed up happened,
            # because touching the token file is one of the first
            # things the backend does, and this BrowserWindow
            # should be called *right after* launching the backend.
            raise NoAuthTokenError(
                'No authentication token found!')
        time.sleep(0.1)
        waiting -= 1
    token = open(path).read().strip()
    url += '#' + token
    return url


def terminate(pid):
    if os.path.isfile(pid):
        with open(pid) as f:
            pidno = int(f.read())
        print('[bitmask] terminating bitmaskd...')
        os.kill(pidno, signal.SIGTERM)


def reset_authtoken():
    prev_auth = os.path.join(get_path_prefix(), 'leap', 'authtoken')
    try:
        os.remove(prev_auth)
    except OSError:
        pass


def check_stale_pidfile():

    def is_pid_running(pidno):
        return 1 == len(filter(lambda p: p.pid == int(pidno), psutil.process_iter()))

    pidno = None
    pidfile = os.path.join(get_path_prefix(), 'leap', 'bitmaskd.pid')
    if os.path.isfile(pidfile):
        with open(pidfile, 'r') as pid_fd:
            pidno = pid_fd.readline().strip()
    if pidno and pidno.isdigit():
        if not is_pid_running(pidno):
            os.unlink(pidfile)


def cleanup():
    print('[bitmask] cleaning up files')
    base = os.path.join(get_path_prefix(), 'leap')
    token = os.path.join(base, 'authtoken')
    pid = os.path.join(base, 'bitmaskd.pid')
    for _f in [token, pid]:
        if os.path.isfile(_f):
            os.unlink(_f)
