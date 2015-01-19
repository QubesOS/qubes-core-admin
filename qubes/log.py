#!/usr/bin/python2 -O
# -*- coding: utf-8 -*-

'''Qubes logging routines

See also: :py:attr:`qubes.vm.qubesvm.QubesVM.logger`
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
    handler = logging.FileHandler(os.path.join(LOGPATH, 'vm', vmname + '.log'))
    handler.setFormatter(formatter_log)
    logger.addHandler(handler)

    return logger
