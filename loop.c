#include <stdio.h>
#include <errno.h>
#include <stddef.h>

#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>

#include <linux/loop.h>

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
                          struct stat *stat) {
    int sp, dev_fd, dev;
    char buf[40];
    if (fstat(file_fd, stat) == -1)
        return -errno;
    switch (stat->st_mode & S_IFMT) {
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
    if (sp >= (int)sizeof buf)
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
