#!/usr/bin/python2 -O

'''
Qubes OS
'''

__author__ = 'Invisible Things Lab'
__license__ = 'GPLv2 or later'
__version__ = 'R3'

import ast

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


class QubesHost(object):
    '''Basic information about host machine'''
    def __init__(self):
        (model, memory, cpus, mhz, nodes, socket, cores, threads) = vmm.libvirt_conn.getInfo()
        self._total_mem = long(memory)*1024
        self._no_cpus = cpus

#        print "QubesHost: total_mem  = {0}B".format (self.xen_total_mem)
#        print "QubesHost: free_mem   = {0}".format (self.get_free_xen_memory())
#        print "QubesHost: total_cpus = {0}".format (self.xen_no_cpus)

    @property
    def memory_total(self):
        '''Total memory, in bytes'''
        return self._total_mem

    @property
    def no_cpus(self):
        '''Noumber of CPUs'''
        return self._no_cpus

    # TODO
    def get_free_xen_memory(self):
        ret = self.physinfo['free_memory']
        return long(ret)

    # TODO
    def measure_cpu_usage(self, previous=None, previous_time = None,
            wait_time=1):
        """measure cpu usage for all domains at once"""
        if previous is None:
            previous_time = time.time()
            previous = {}
            info = vmm.xc.domain_getinfo(0, qubes_max_qid)
            for vm in info:
                previous[vm['domid']] = {}
                previous[vm['domid']]['cpu_time'] = (
                        vm['cpu_time'] / vm['online_vcpus'])
                previous[vm['domid']]['cpu_usage'] = 0
            time.sleep(wait_time)

        current_time = time.time()
        current = {}
        info = vmm.xc.domain_getinfo(0, qubes_max_qid)
        for vm in info:
            current[vm['domid']] = {}
            current[vm['domid']]['cpu_time'] = (
                    vm['cpu_time'] / max(vm['online_vcpus'], 1))
            if vm['domid'] in previous.keys():
                current[vm['domid']]['cpu_usage'] = (
                    float(current[vm['domid']]['cpu_time'] -
                        previous[vm['domid']]['cpu_time']) /
                    long(1000**3) / (current_time-previous_time) * 100)
                if current[vm['domid']]['cpu_usage'] < 0:
                    # VM has been rebooted
                    current[vm['domid']]['cpu_usage'] = 0
            else:
                current[vm['domid']]['cpu_usage'] = 0

        return (current_time, current)


class QubesVmLabel(object):
    '''Label definition for virtual machines

    Label specifies colour of the padlock displayed next to VM's name.
    When this is a :py:class:`qubes.vm.dispvm.DispVM`, padlock is overlayed
    with recycling pictogram.

    :param int index: numeric identificator of label
    :param str color: colour specification as in HTML (``#abcdef``)
    :param str name: label's name like "red" or "green"
    :param bool dispvm: :py:obj:`True` if this is :py:class:`qubes.vm.dispvm.DispVM` label

    '''
    def __init__(self, index, color, name, dispvm=False):
        #: numeric identificator of label
        self.index = index

        #: colour specification as in HTML (``#abcdef``)
        self.color = color

        #: label's name like "red" or "green"
        self.name = name

        #: :py:obj:`True` if this is :py:class:`qubes.vm.dispvm.DispVM` label
        self.dispvm = dispvm

        #: freedesktop icon name, suitable for use in :py:meth:`PyQt4.QtGui.QIcon.fromTheme`
        self.icon = '{}-{}'.format(('dispvm' if dispvm else 'appvm'), name)

    @classmethod
    def fromxml(cls, xml):
        '''Create label definition from XML node

        :param :py:class:`lxml.etree._Element` xml: XML node reference
        :rtype: :py:class:`qubes.QubesVmLabel`
        '''

        index = int(xml.get('id').split('-', 1)[1])
        color = xml.get('color')
        name = xml.text
        dispvm = ast.literal_eval(xml.get('dispvm', 'False'))

        return cls(index, color, name, dispvm)

    def __repr__(self):
        return '{}({!r}, {!r}, {!r}, dispvm={!r})'.format(
            self.__class__.__name__,
            self.index,
            self.color,
            self.name,
            self.dispvm)

    # self.icon_path is obsolete
    # use QIcon.fromTheme(label.icon) where applicable
    @property
    def icon_path(self):
        '''Icon path

        DEPRECATED --- use :py:meth:`PyQt4.QtGui.QIcon.fromTheme` and :py:attr:`QubesVmLabel.icon`'''
        return os.path.join(system_path['qubes_icon_dir'], self.icon) + ".png"

#: Globally defined labels
QubesVmLabels = {
    "red":      QubesVmLabel(1, "0xcc0000", "red"     ),
    "orange":   QubesVmLabel(2, "0xf57900", "orange"  ),
    "yellow":   QubesVmLabel(3, "0xedd400", "yellow"  ),
    "green":    QubesVmLabel(4, "0x73d216", "green"   ),
    "gray":     QubesVmLabel(5, "0x555753", "gray"    ),
    "blue":     QubesVmLabel(6, "0x3465a4", "blue"    ),
    "purple":   QubesVmLabel(7, "0x75507b", "purple"  ),
    "black":    QubesVmLabel(8, "0x000000", "black"   ),
}

#: Globally defined labels for :py:class:`qubes.vm.dispvm.DispVM` s
QubesDispVmLabels = {
    "red":      QubesVmLabel(1, "0xcc0000", "red",      dispvm=True),
    "orange":   QubesVmLabel(2, "0xf57900", "orange",   dispvm=True),
    "yellow":   QubesVmLabel(3, "0xedd400", "yellow",   dispvm=True),
    "green":    QubesVmLabel(4, "0x73d216", "green",    dispvm=True),
    "gray":     QubesVmLabel(5, "0x555753", "gray",     dispvm=True),
    "blue":     QubesVmLabel(6, "0x3465a4", "blue",     dispvm=True),
    "purple":   QubesVmLabel(7, "0x75507b", "purple",   dispvm=True),
    "black":    QubesVmLabel(8, "0x000000", "black",    dispvm=True),
}

