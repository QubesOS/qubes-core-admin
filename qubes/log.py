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

"""Qubes logging routines

See also: :py:attr:`qubes.vm.qubesvm.QubesVM.log`
"""

import logging
import sys


class Formatter(logging.Formatter):

    def __init__(self, *args, debug=False, time=False, **kwargs):
        kwargs.pop("fmt", None)
        fmt = ""
        if time:
            fmt += "%(asctime)s "
        fmt += "%(levelname)s "
        if debug:
            fmt += "%(name)s[%(process)d %(module)s.%(funcName)s:%(lineno)d]: "
        else:
            fmt += "%(name)s[%(process)d]: "
        fmt += "%(message)s"
        super().__init__(fmt=fmt, *args, **kwargs)


def enable(log_level: int = logging.INFO, enable_debug_libvirt: bool = False):
    """Enable global logging

    Use :py:mod:`logging` module from standard library to log messages.

    >>> import qubes.log
    >>> qubes.log.enable()          # doctest: +SKIP
    >>> import logging
    >>> logging.warning('Foobar')   # doctest: +SKIP
    """

    if logging.root.handlers:
        return

    debug = bool(log_level == logging.DEBUG)

    handler_console = logging.StreamHandler(sys.stderr)
    handler_console.setFormatter(Formatter(debug=debug))
    logging.root.addHandler(handler_console)

    for handler in logging.root.handlers:
        handler.setFormatter(Formatter(debug=debug))
    if debug and not enable_debug_libvirt:
        logging.getLogger("virEventAsyncIOImpl").setLevel(logging.INFO)
    logging.root.setLevel(log_level)


def get_vm_logger(vmname):
    """Initialise logging for particular VM name

    :param str vmname: VM's name
    :rtype: :py:class:`logging.Logger`
    """

    return logging.getLogger("vm." + vmname)
