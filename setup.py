#!/usr/bin/python3 -O
# vim: fileencoding=utf-8

import os

import setuptools
import setuptools.command.install


# don't import: import * is unreliable and there is no need, since this is
# compile time and we have source files
def get_console_scripts():
    for filename in os.listdir('./qubes/tools'):
        basename, ext = os.path.splitext(os.path.basename(filename))
        if basename == '__init__' or ext != '.py':
            continue
        yield basename.replace('_', '-'), 'qubes.tools.{}'.format(basename)

# create simple scripts that run much faster than "console entry points"
class CustomInstall(setuptools.command.install.install):
    def run(self):
        bin = os.path.join(self.root, "usr/bin")
        try:
            os.makedirs(bin)
        except:
            pass
        for file, pkg in get_console_scripts():
           path = os.path.join(bin, file)
           with open(path, "w") as f:
               f.write(
"""#!/usr/bin/python3
from {} import main
import sys
if __name__ == '__main__':
	sys.exit(main())
""".format(pkg))

           os.chmod(path, 0o755)
        setuptools.command.install.install.run(self)

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
        cmdclass={
            'install': CustomInstall,
        },
        entry_points={
            'qubes.vm': [
                'AppVM = qubes.vm.appvm:AppVM',
                'TemplateVM = qubes.vm.templatevm:TemplateVM',
                'StandaloneVM = qubes.vm.standalonevm:StandaloneVM',
                'AdminVM = qubes.vm.adminvm:AdminVM',
                'DispVM = qubes.vm.dispvm:DispVM',
            ],
            'qubes.ext': [
                'qubes.ext.admin = qubes.ext.admin:AdminExtension',
                'qubes.ext.core_features = qubes.ext.core_features:CoreFeatures',
                'qubes.ext.qubesmanager = qubes.ext.qubesmanager:QubesManager',
                'qubes.ext.gui = qubes.ext.gui:GUI',
                'qubes.ext.r3compatibility = qubes.ext.r3compatibility:R3Compatibility',
                'qubes.ext.pci = qubes.ext.pci:PCIDeviceExtension',
                'qubes.ext.block = qubes.ext.block:BlockDeviceExtension',
                'qubes.ext.services = qubes.ext.services:ServicesExtension',
                'qubes.ext.windows = qubes.ext.windows:WindowsFeatures',
            ],
            'qubes.devices': [
                'pci = qubes.ext.pci:PCIDevice',
                'block = qubes.ext.block:BlockDevice',
                'testclass = qubes.tests.devices:TestDevice',
            ],
            'qubes.storage': [
                'file = qubes.storage.file:FilePool',
                'file-reflink = qubes.storage.reflink:ReflinkPool',
                'linux-kernel = qubes.storage.kernels:LinuxKernel',
                'lvm_thin = qubes.storage.lvm:ThinPool',
                'zfs_zvol = qubes.storage.zfs:ZFSQpool',
                'zfs_encrypted = qubes.storage.zfs_encrypted:ZFSQEncryptedPool',
            ],
            'qubes.tests.storage': [
                'test = qubes.tests.storage:TestPool',
                'file = qubes.storage.file:FilePool',
                'file-reflink = qubes.storage.reflink:ReflinkPool',
                'linux-kernel = qubes.storage.kernels:LinuxKernel',
                'lvm_thin = qubes.storage.lvm:ThinPool',
            ],
        })
