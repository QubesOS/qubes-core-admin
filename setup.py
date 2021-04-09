#!/usr/bin/python3 -O
# vim: fileencoding=utf-8

import os
import setuptools
import setuptools.command.install

from cffi import FFI
ffibuilder = FFI()
ffibuilder.cdef("""
typedef unsigned long long	__u64;
typedef unsigned int	__u32;
typedef unsigned char	__u8;
enum {
	LO_FLAGS_READ_ONLY	= 1,
	LO_FLAGS_AUTOCLEAR	= 4,
	LO_FLAGS_PARTSCAN	= 8,
	LO_FLAGS_DIRECT_IO	= 16,
};

struct loop_info64 {
	__u64		   lo_device;
	__u64		   lo_inode;
	__u64		   lo_rdevice;
	__u64		   lo_offset;
	__u64		   lo_sizelimit;
	__u32		   lo_number;
	__u32		   lo_encrypt_type;
	__u32		   lo_encrypt_key_size;
	__u32		   lo_flags;
	__u8		   lo_file_name[64];
	__u8		   lo_crypt_name[64];
	__u8		   lo_encrypt_key[32];
	__u64		   lo_init[2];
};

struct qubes_stat {
    uint64_t	st_dev;
    uint64_t	st_ino;
    uint32_t	st_mode;
};

int qubes_get_loop_dev_info(const int loop_fd, struct loop_info64 *stat);
int qubes_create_loop_dev(const int, const int, struct qubes_stat *);
""")

ffibuilder.set_source("_qubes_loop", """\
#include <stdio.h>
#include <errno.h>
#include <stddef.h>

#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>

#include <linux/loop.h>

struct qubes_stat {
    uint64_t	st_dev;
    uint64_t	st_ino;
    uint32_t	st_mode;
};

int qubes_get_loop_dev_info(const int loop_fd, struct loop_info64 *info) {
    return ioctl(loop_fd, LOOP_GET_STATUS64, info);
}

/**
 * @brief Create a block device file descriptor from the given FD
 * @param loop_control_fd An open file descriptor to `/dev/loop-control`.
 * @param file_fd An open file descriptor to a block device, character device,
 * or regular file.
 * @return An open file descriptor on success, or a negative errno value on
 * error.  Block and character device file descriptors are duplicated.  Regular
 * file descriptors are used to create a loop device.  For other types of files,
 * `-EINVAL` is returned.
 */
int qubes_create_loop_dev(const int loop_control_fd, const int file_fd,
                          struct qubes_stat *s_buf) {
    int sp, dev_fd, dev;
    char buf[40];
    struct stat stat_buf;
    if (fstat(file_fd, &stat_buf) == -1)
        return -errno;
    s_buf->st_dev = stat_buf.st_dev;
    s_buf->st_ino = stat_buf.st_ino;
    s_buf->st_mode = stat_buf.st_mode;
    switch (stat_buf.st_mode & S_IFMT) {
    case S_IFBLK:
        dev_fd = fcntl(file_fd, F_DUPFD_CLOEXEC, 3);
        return dev_fd >= 0 ? dev_fd : -errno;
    case S_IFREG:
        break;
    default:
    case S_IFCHR:
        return -EINVAL;
    }
retry:
    if ((dev = ioctl(loop_control_fd, LOOP_CTL_GET_FREE)) < 0)
        return -errno;
    if ((sp = snprintf(buf, sizeof buf, "/dev/loop%d", dev)) < 0)
        return -ENOMEM;
    if (sp >= sizeof buf)
        return -EFAULT;
    if ((dev_fd = open(buf, O_RDWR|O_CLOEXEC|O_NOCTTY, 0)) < 0)
        return -errno;
    struct loop_config config = {
        .fd = file_fd,
        .block_size = 0,
        .info = {
            .lo_number = dev,
            .lo_encrypt_type = LO_CRYPT_NONE,
            .lo_flags = LO_FLAGS_AUTOCLEAR | LO_FLAGS_DIRECT_IO,
        }
    };
    if (ioctl(dev_fd, LOOP_CONFIGURE, &config) < 0) {
        if (errno == EBUSY) {
            (void)close(dev_fd);
            goto retry;
        }
        return -errno;
    }
    return dev_fd;
}
""")

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
                'qubes.ext.backup_restore = '
                'qubes.ext.backup_restore:BackupRestoreExtension',
                'qubes.ext.core_features = qubes.ext.core_features:CoreFeatures',
                'qubes.ext.gui = qubes.ext.gui:GUI',
                'qubes.ext.audio = qubes.ext.audio:AUDIO',
                'qubes.ext.r3compatibility = qubes.ext.r3compatibility:R3Compatibility',
                'qubes.ext.pci = qubes.ext.pci:PCIDeviceExtension',
                'qubes.ext.block = qubes.ext.block:BlockDeviceExtension',
                'qubes.ext.services = qubes.ext.services:ServicesExtension',
                'qubes.ext.supported_features = qubes.ext.supported_features:SupportedFeaturesExtension',
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
                'callback = qubes.storage.callback:CallbackPool',
            ],
            'qubes.tests.storage': [
                'test = qubes.tests.storage:TestPool',
                'file = qubes.storage.file:FilePool',
                'file-reflink = qubes.storage.reflink:ReflinkPool',
                'linux-kernel = qubes.storage.kernels:LinuxKernel',
                'lvm_thin = qubes.storage.lvm:ThinPool',
                'callback = qubes.storage.callback:CallbackPool',
            ],
        },
        cffi_modules=["setup.py:ffibuilder"])
