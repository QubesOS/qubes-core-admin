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
import sys


class Formatter(logging.Formatter):
    def __init__(self, *args, debug=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = debug

    def formatMessage(self, record):
        fmt = ''
        if self.debug:
            fmt += '[%(processName)s %(module)s.%(funcName)s:%(lineno)d] '
        if self.debug or record.name.startswith('vm.'):
            fmt += '%(name)s: '
        fmt += '%(message)s'

        return fmt % record.__dict__


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
    handler_console.setFormatter(Formatter())
    logging.root.addHandler(handler_console)

    logging.root.setLevel(logging.INFO)

def enable_debug():
    '''Enable debug logging

    Enable more messages and additional info to message format.
    '''

    enable()

    for handler in logging.root.handlers:
        handler.setFormatter(Formatter(debug=True))

    logging.root.setLevel(logging.DEBUG)

def get_vm_logger(vmname):
    '''Initialise logging for particular VM name

    :param str vmname: VM's name
    :rtype: :py:class:`logging.Logger`
    '''

    return logging.getLogger('vm.' + vmname)
