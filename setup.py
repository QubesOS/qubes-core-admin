#!/usr/bin/python3 -O
# vim: fileencoding=utf-8

import os

import setuptools


# don't import: import * is unreliable and there is no need, since this is
# compile time and we have source files
def get_console_scripts():
    for filename in os.listdir('./qubes/tools'):
        basename, ext = os.path.splitext(os.path.basename(filename))
        if basename == '__init__' or ext != '.py':
            continue
        yield '{} = qubes.tools.{}:main'.format(
            basename.replace('_', '-'), basename)


if __name__ == '__main__':
    setuptools.setup(
        name='qubes',
        version=open('version').read().strip(),
        author='Invisible Things Lab',
        author_email='woju@invisiblethingslab.com',
        description='Qubes core package',
        license='GPL2+',
        url='https://www.qubes-os.org/',
        packages=setuptools.find_packages(exclude=('core*', 'tests')),
        package_data = {
            'qubespolicy': ['glade/*.glade'],
        },
        entry_points={
            'console_scripts': list(get_console_scripts()) + [
                'qrexec-policy = qubespolicy.cli:main',
                'qrexec-policy-agent = qubespolicy.agent:main',
            ],
            'qubes.vm': [
                'AppVM = qubes.vm.appvm:AppVM',
                'TemplateVM = qubes.vm.templatevm:TemplateVM',
                'StandaloneVM = qubes.vm.standalonevm:StandaloneVM',
                'AdminVM = qubes.vm.adminvm:AdminVM',
                'DispVM = qubes.vm.dispvm:DispVM',
            ],
            'qubes.ext': [
                'qubes.ext.core_features = qubes.ext.core_features:CoreFeatures',
                'qubes.ext.qubesmanager = qubes.ext.qubesmanager:QubesManager',
                'qubes.ext.gui = qubes.ext.gui:GUI',
                'qubes.ext.r3compatibility = qubes.ext.r3compatibility:R3Compatibility',
                'qubes.ext.pci = qubes.ext.pci:PCIDeviceExtension',
                'qubes.ext.block = qubes.ext.block:BlockDeviceExtension',
            ],
            'qubes.devices': [
                'pci = qubes.ext.pci:PCIDevice',
                'block = qubes.ext.block:BlockDevice',
                'testclass = qubes.tests.devices:TestDevice',
            ],
            'qubes.storage': [
                'file = qubes.storage.file:FilePool',
                'linux-kernel = qubes.storage.kernels:LinuxKernel',
                'lvm_thin = qubes.storage.lvm:ThinPool',
            ],
            'qubes.tests.storage': [
                'test = qubes.tests.storage:TestPool',
                'file = qubes.storage.file:FilePool',
                'linux-kernel = qubes.storage.kernels:LinuxKernel',
                'lvm_thin = qubes.storage.lvm:ThinPool',
            ],
        })
