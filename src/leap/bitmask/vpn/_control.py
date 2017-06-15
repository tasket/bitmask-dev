import os
import subprocess

from twisted.internet.task import LoopingCall
from twisted.internet import reactor
from twisted.logger import Logger

from .process import VPNProcess
from .constants import IS_MAC

log = Logger()

POLL_TIME = 1


class VPNControl(object):
    """
    This is the high-level object that the service knows about.
    It exposes the start and terminate methods.

    On start, it spawns a VPNProcess instance that will use a vpnlauncher
    suited for the running platform and connect to the management interface
    opened by the openvpn process, executing commands over that interface on
    demand.

    This class also has knowledge of the reactor, since it controlls the
    pollers that write and read to the management interface.
    """
    TERMINATE_MAXTRIES = 10
    TERMINATE_WAIT = 1  # secs
    RESTART_WAIT = 2  # secs

    OPENVPN_VERB = "openvpn_verb"

    def __init__(self, remotes, vpnconfig,
                 providerconfig, socket_host, socket_port):
        self._vpnproc = None
        self._pollers = []

        self._openvpn_verb = None
        self._user_stopped = False

        self._remotes = remotes
        self._vpnconfig = vpnconfig
        self._providerconfig = providerconfig
        self._host = socket_host
        self._port = socket_port

    def start(self):
        log.debug('VPN: start')

        self._user_stopped = False
        self._stop_pollers()

        args = [self._vpnconfig, self._providerconfig, self._host,
                self._port]
        kwargs = {'openvpn_verb': 4, 'remotes': self._remotes,
                  'restartfun': self.restart}

        vpnproc = VPNProcess(*args, **kwargs)
        if vpnproc.get_openvpn_process():
            log.info('Another vpn process is running. Will try to stop it.')
            vpnproc.stop_if_already_running()

        try:
            vpnproc.preUp()
        except Exception as e:
            log.error('Error on vpn pre-up {0!r}'.format(e))
            raise
        try:
            cmd = vpnproc.getCommand()
        except Exception as e:
            log.error('Error while getting vpn command... {0!r}'.format(e))
            raise

        env = os.environ

        runningproc = reactor.spawnProcess(vpnproc, cmd[0], cmd, env)
        vpnproc.pid = runningproc.pid
        self._vpnproc = vpnproc

        # add pollers for status and state
        # this could be extended to a collection of
        # generic watchers

        poll_list = [LoopingCall(vpnproc.pollStatus),
                     LoopingCall(vpnproc.pollState),
                     LoopingCall(vpnproc.pollLog)]
        self._pollers.extend(poll_list)
        self._start_pollers()
        return True

    def restart(self):
        self.stop(shutdown=False, restart=True)
        reactor.callLater(
            self.RESTART_WAIT, self.start)

    def stop(self, shutdown=False, restart=False):
        """
        Stops the openvpn subprocess.

        Attempts to send a SIGTERM first, and after a timeout
        it sends a SIGKILL.

        :param shutdown: whether this is the final shutdown
        :type shutdown: bool
        :param restart: whether this stop is part of a hard restart.
        :type restart: bool
        """
        self._stop_pollers()
        try:
            self._vpnproc.preDown()
        except Exception as e:
            log.error('Error on vpn pre-down {0!r}'.format(e))
            raise

        if IS_LINUX:
            # TODO factor this out to a linux-only launcher mechanism.
            # First we try to be polite and send a SIGTERM...
            if self._vpnproc is not None:
                # We assume that the only valid stops are initiated
                # by an user action, not hard restarts
                self._user_stopped = not restart
                self._vpnproc.restarting = restart

                self._sentterm = True
                self._vpnproc.terminate(shutdown=shutdown)

                # ...but we also trigger a countdown to be unpolite
                # if strictly needed.
                reactor.callLater(
                    self.TERMINATE_WAIT, self._kill_if_left_alive)
                self._vpnproc.traffic_status = (0, 0)
        return True

    @property
    def status(self):
        if not self._vpnproc:
            return {'status': 'off', 'error': None}
        return self._vpnproc.status

    @property
    def traffic_status(self):
        return self._vpnproc.traffic_status

    def _killit(self):
        """
        Sends a kill signal to the process.
        """
        self._stop_pollers()
        if self._vpnproc is None:
            log.debug("There's no vpn process running to kill.")
        else:
            self._vpnproc.aborted = True
            self._vpnproc.killProcess()

    def _kill_if_left_alive(self, tries=0):
        """
        Check if the process is still alive, and send a
        SIGKILL after a timeout period.

        :param tries: counter of tries, used in recursion
        :type tries: int
        """
        while tries < self.TERMINATE_MAXTRIES:
            if self._vpnproc.transport.pid is None:
                return
            else:
                log.debug('Process did not die, waiting...')

            tries += 1
            reactor.callLater(self.TERMINATE_WAIT,
                              self._kill_if_left_alive, tries)
            return

        # after running out of patience, we try a killProcess
        log.debug('Process did not die. Sending a SIGKILL.')
        try:
            self._killit()
        except OSError:
            log.error('Could not kill process!')

    def _start_pollers(self):
        """
        Iterate through the registered observers
        and start the looping call for them.
        """
        for poller in self._pollers:
            poller.start(POLL_TIME)

    def _stop_pollers(self):
        """
        Iterate through the registered observers
        and stop the looping calls if they are running.
        """
        for poller in self._pollers:
            if poller.running:
                poller.stop()
        self._pollers = []
