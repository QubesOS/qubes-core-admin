"""mock libvirtaio module

WARNING: you did not import real libvirtaio module

This is needed, because we don't currently ship libvirt-python for templates.
"""

def virEventRegisterAsyncIOImpl(loop):
    pass
