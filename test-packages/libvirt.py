"""mock libvirt module

WARNING: you did not import real libvirt module

This is needed, because we don't currently ship libvirt-python for templates.
The module contains libvirtError and openReadOnly() function, which
does nothing and raises the aforementioned exception. More functions can be
added as needed.
"""

class libvirtError(Exception):
    pass

def openReadOnly(*args, **kwargs):
    raise libvirtError('mock module, always raises')
