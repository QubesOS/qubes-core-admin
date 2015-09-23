#!/usr/bin/python2 -O
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2014-2015  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

'''Qubes logging routines

See also: :py:attr:`qubes.vm.qubesvm.QubesVM.log`
'''

import logging
import os
import sys

FORMAT_CONSOLE = '%(message)s'
FORMAT_LOG = '%(asctime)s %(message)s'
FORMAT_DEBUG = '%(asctime)s ' \
    '[%(processName)s %(module)s.%(funcName)s:%(lineno)d] %(name)s: %(message)s'
LOGPATH = '/var/log/qubes'
LOGFILE = os.path.join(LOGPATH, 'qubes.log')

formatter_console = logging.Formatter(FORMAT_CONSOLE)
formatter_log = logging.Formatter(FORMAT_LOG)
formatter_debug = logging.Formatter(FORMAT_DEBUG)

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

    handler_log = logging.FileHandler('log', 'a', encoding='utf-8')
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
    handler = logging.FileHandler(
        os.path.join(LOGPATH, 'vm-{}.log'.format(vmname)))
    handler.setFormatter(formatter_log)
    logger.addHandler(handler)

    return logger
