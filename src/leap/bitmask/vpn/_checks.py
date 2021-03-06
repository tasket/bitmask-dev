import os

from datetime import datetime
from time import mktime
from twisted.logger import Logger

from leap.bitmask.vpn.privilege import is_pkexec_in_system, NoPkexecAvailable
from leap.common.certs import get_cert_time_boundaries
from leap.common.config import get_path_prefix

from .constants import IS_LINUX

log = Logger()


class ImproperlyConfigured(Exception):
    pass


def get_failure_for(provider):
    if IS_LINUX and not is_pkexec_in_system():
        raise NoPkexecAvailable()
    if not _has_valid_cert(provider):
        raise ImproperlyConfigured('Missing VPN certificate')


def is_service_ready(provider):
    if not _has_valid_cert(provider):
        return False
    if os.getuid() == 0:
        # it's your problem if you run as root, not mine.
        return True
    if IS_LINUX and not is_pkexec_in_system():
        log.warn('System has no pkexec')
        return False
    return True


def cert_expires(provider):
    path = get_vpn_cert_path(provider)
    try:
        with open(path, 'r') as f:
            cert = f.read()
    except IOError:
        return None
    _, to = get_cert_time_boundaries(cert)
    expiry_date = datetime.fromtimestamp(mktime(to))
    return expiry_date


def get_vpn_cert_path(provider):
    return os.path.join(get_path_prefix(),
                        'leap', 'providers', provider,
                        'keys', 'client', 'openvpn.pem')


def _has_valid_cert(provider):
    cert_path = get_vpn_cert_path(provider)
    has_file = os.path.isfile(cert_path)
    if not has_file:
        log.warn("VPN cert not present for %s" % (provider,))
        return False

    expiry = cert_expires(provider)
    if datetime.now() > expiry:
        log.warn("VPN cert expired for %s" % (provider,))
        return False
    return True
