#!/usr/bin/python2 -O

'''
Qubes OS
'''

__author__ = 'Invisible Things Lab'
__license__ = 'GPLv2 or later'
__version__ = 'R3'

import qubes._pluginloader

class QubesException(Exception):
    '''Exception that can be shown to the user'''
    pass

class QubesVMMConnection(object):
    '''Connection to Virtual Machine Manager (libvirt)'''
    def __init__(self):
        self._libvirt_conn = None
        self._xs = None
        self._xc = None
        self._offline_mode = False

    @property
    def offline_mode(self):
        '''Check or enable offline mode (do not actually connect to vmm)'''
        return self._offline_mode

    @offline_mode.setter
    def offline_mode(self, value):
        if value and self._libvirt_conn is not None:
            raise QubesException("Cannot change offline mode while already connected")

        self._offline_mode = value

    def _libvirt_error_handler(self, ctx, error):
        pass

    def init_vmm_connection(self):
        '''Initialise connection

        This method is automatically called when getting'''
        if self._libvirt_conn is not None:
            # Already initialized
            return
        if self._offline_mode:
            # Do not initialize in offline mode
            raise QubesException("VMM operations disabled in offline mode")

        if 'xen.lowlevel.xs' in sys.modules:
            self._xs = xen.lowlevel.xs.xs()
        self._libvirt_conn = libvirt.open(defaults['libvirt_uri'])
        if self._libvirt_conn == None:
            raise QubesException("Failed connect to libvirt driver")
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)
        atexit.register(self._libvirt_conn.close)

    @property
    def libvirt_conn(self):
        '''Connection to libvirt'''
        self.init_vmm_connection()
        return self._libvirt_conn

    @property
    def xs(self):
        '''Connection to Xen Store

        This property in available only when running on Xen.'''

        if 'xen.lowlevel.xs' not in sys.modules:
            return None

        self.init_vmm_connection()
        return self._xs

vmm = QubesVMMConnection()

