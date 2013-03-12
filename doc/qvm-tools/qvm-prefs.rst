=========
qvm-prefs
=========

NAME
====
qvm-prefs - list/set various per-VM properties

:Date:   2012-04-11

SYNOPSIS
========
| qvm-prefs -l [options] <vm-name>
| qvm-prefs -s [options] <vm-name> <property> [...]


OPTIONS
=======
-h, --help
    Show this help message and exit
-l, --list
    List properties of a specified VM
-s, --set
    Set properties of a specified VM

PROPERTIES
==========

include_in_backups
    Accepted values: ``True``, ``False``

    Control whenever this VM will be included in backups by default (for now works only in qubes-manager). You can always manually select or deselect any VM for backup.

pcidevs
    PCI devices assigned to the VM. Should be edited using qvm-pci tool.

label
    Accepted values: ``red``, ``orange``, ``yellow``, ``green``, ``gray``, ``blue``, ``purple``, ``black``

    Color of VM label (icon, appmenus, windows border). If VM is running, change will be applied at first VM restart.

netvm
    Accepted values: netvm name, ``default``, ``none``

    To which NetVM connect. Setting to ``default`` will follow system-global default NetVM (managed by qubes-prefs). Setting to ``none`` will disable networking in this VM.

    *Notice:* when setting to ``none``, firewall will be set to block all traffic - it will be used by DispVM started from this VM. Setting back to some NetVM will _NOT_ restore previous firewall settings.

maxmem
    Accepted values: memory size in MB

    Maximum memory size available for this VM. Dynamic memory management (aka qmemman) will not be able to balloon over this limit. For VMs with qmemman disabled, this will be overridden by *memory* property (at VM startup).

memory
    Accepted values: memory size in MB

    Initial memory size for VM. This should be large enough to allow VM startup - before qmemman starts managing memory for this VM. For VM with qmemman disabled, this is static memory size.

kernel
    Accepted values: kernel version, ``default``, ``none``

    Kernel version to use (only for PV VMs). Available kernel versions will be listed when no value given (there are in /var/lib/qubes/vm-kernels). Setting to ``default`` will follow system-global default kernel (managed via qubes-prefs). Setting to ``none`` will use "kernels" subdir in VM directory - this allows having VM-specific kernel; also this the only case when /lib/modules is writable from within VM.

template
    Accepted values: TemplateVM name

    TemplateVM on which VM base. It can be changed only when VM isn't running.

vcpus
    Accepted values: no of CPUs

    Number of CPU (cores) available to VM. Some VM types (eg DispVM) will not work properly with more than one CPU.

kernelopts
    Accepted values: string, ``default``

    VM kernel parameters (available only for PV VMs). This can be used to workaround some hardware specific problems (eg for NetVM). Setting to ``default`` will use some reasonable defaults (currently different for VMs with PCI devices and without). Some helpful options (for debugging purposes): ``earlyprintk=xen``, ``init=/bin/bash``

name
    Accepted values: alphanumerical name

    Name of the VM. Can be only changed when VM isn't running.

drive
    Accepted values: [hd:\|cdrom:][backend-vm:]path

    Additional drive for the VM (available only for HVMs). This can be used to attach installation image. ``path`` can be file or physical device (eg. /dev/sr0). The same syntax can be used in qvm-start --drive - to attach drive only temporarily.

mac
    Accepted values: MAC address, ``auto``

    Can be used to force specific of virtual ethernet card in the VM. Setting to ``auto`` will use automatic-generated MAC - based on VM id. Especially useful when some licencing depending on static MAC address.

default_user
    Accepted values: username

    Default user used by qvm-run. Note that it make sense only on non-standard template, as the standard one always have "user" account.

debug
    Accepted values: ``on``, ``off``

    Enables debug mode for VM. This can be used to turn on/off verbose logging in many qubes components at once (gui virtualization, VM kernel, some other services).

AUTHORS
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
