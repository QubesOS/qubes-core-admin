"""mock libvirt module

WARNING: you did not import real libvirt module

This is needed, because we don't currently ship libvirt-python for templates.
The module contains libvirtError and openReadOnly() function, which
does nothing and raises the aforementioned exception. More functions can be
added as needed.
"""

class libvirtError(Exception):
    def get_error_code(self):
        return VIR_ERR_NO_DOMAIN

class virConnect:
    pass

class virDomain:
    pass

def openReadOnly(*args, **kwargs):
    raise libvirtError('mock module, always raises')

def registerErrorHandler(f, ctx):
    pass

VIR_DOMAIN_BLOCKED = 2
VIR_DOMAIN_RUNNING = 1
VIR_DOMAIN_PAUSED = 3
VIR_DOMAIN_SHUTDOWN = 4
VIR_DOMAIN_SHUTOFF = 5
VIR_DOMAIN_CRASHED = 6
VIR_DOMAIN_PMSUSPENDED = 7

VIR_ERR_NO_DOMAIN = 0
