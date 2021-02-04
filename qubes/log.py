#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

'''Qubes logging routines

See also: :py:attr:`qubes.vm.qubesvm.QubesVM.log`
'''

import logging
import os
import sys
import fcntl

import dbus

FORMAT_CONSOLE = '%(message)s'
FORMAT_LOG = '%(asctime)s %(message)s'
FORMAT_DEBUG = '%(asctime)s ' \
    '[%(processName)s %(module)s.%(funcName)s:%(lineno)d] %(name)s: %(message)s'
LOGPATH = '/var/log/qubes'

formatter_console = logging.Formatter(FORMAT_CONSOLE)
formatter_log = logging.Formatter(FORMAT_LOG)
formatter_debug = logging.Formatter(FORMAT_DEBUG)

class DBusHandler(logging.Handler):
    '''Handler which displays records as DBus notifications'''

    #: mapping of loglevels to icons
    app_icons = {
        logging.ERROR:      'dialog-error',
        logging.WARNING:    'dialog-warning',
        logging.NOTSET:     'dialog-information',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._notify_object = dbus.SessionBus().get_object(
            'org.freedesktop.Notifications', '/org/freedesktop/Notifications')


    def emit(self, record):
        app_icon = self.app_icons[
            max(level for level in self.app_icons if level <= record.levelno)]

        try:
            # https://developer.gnome.org/notification-spec/#command-notify
            self._notify_object.Notify(
                'Qubes',    # STRING app_name
                0,          # UINT32 replaces_id
                app_icon,   # STRING app_icon
                record.msg, # STRING summary
                '',         # STRING body
                (),         # ARRAY actions
                {},         # DICT hints
                0,          # INT32 timeout
                dbus_interface='org.freedesktop.Notifications')
        except dbus.DBusException:
            pass


def enable():
    '''Enable global logging

    Use :py:mod:`logging` module from standard library to log messages.

    >>> import qubes.log
    >>> qubes.log.enable()          # doctest: +SKIP
    >>> import logging
    >>> logging.warning('Foobar')   # doctest: +SKIP
    '''

    if logging.root.handlers:
        return

    handler_console = logging.StreamHandler(sys.stderr)
    handler_console.setFormatter(formatter_console)
    logging.root.addHandler(handler_console)

    if os.path.exists('/var/log/qubes'):
        log_path = '/var/log/qubes/qubes.log'
    else:
        # for tests, travis etc
        log_path = '/tmp/qubes.log'
    old_umask = os.umask(0o007)
    try:
        handler_log = logging.FileHandler(log_path, 'a', encoding='utf-8')
        fcntl.fcntl(handler_log.stream.fileno(),
            fcntl.F_SETFD, fcntl.FD_CLOEXEC)
    finally:
        os.umask(old_umask)
    handler_log.setFormatter(formatter_log)
    logging.root.addHandler(handler_log)

    logging.root.setLevel(logging.INFO)

def enable_debug():
    '''Enable debug logging

    Enable more messages and additional info to message format.
    '''

    enable()
    logging.root.setLevel(logging.DEBUG)

    for handler in logging.root.handlers:
        handler.setFormatter(formatter_debug)

def get_vm_logger(vmname):
    '''Initialise logging for particular VM name

    :param str vmname: VM's name
    :rtype: :py:class:`logging.Logger`
    '''

    logger = logging.getLogger('vm.' + vmname)
    if logger.handlers:
        return logger
    old_umask = os.umask(0o007)
    try:
        handler = logging.FileHandler(
            os.path.join(LOGPATH, 'vm-{}.log'.format(vmname)))
        fcntl.fcntl(handler.stream.fileno(),
            fcntl.F_SETFD, fcntl.FD_CLOEXEC)
    finally:
        os.umask(old_umask)
    handler.setFormatter(formatter_log)
    logger.addHandler(handler)

    return logger
