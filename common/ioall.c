/*
 * The Qubes OS Project, http://www.qubes-os.org
 *
 * Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
 *
 */

#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>

int write_all(int fd, void *buf, int size)
{
	int written = 0;
	int ret;
	while (written < size) {
		ret = write(fd, (char *) buf + written, size - written);
		if (ret <= 0) {
			perror("write");
			return 0;
		}
		written += ret;
	}
//      fprintf(stderr, "sent %d bytes\n", size);
	return 1;
}

int read_all(int fd, void *buf, int size)
{
	int got_read = 0;
	int ret;
	while (got_read < size) {
		ret = read(fd, (char *) buf + got_read, size - got_read);
		if (ret == 0) {
			fprintf(stderr, "EOF\n");
			return 0;
		}
		if (ret < 0) {
			perror("read");
			return 0;
		}
		got_read += ret;
	}
//      fprintf(stderr, "read %d bytes\n", size);
	return 1;
}

int copy_fd_all(int fdout, int fdin)
{
	int ret;
	char buf[4096];
	for (;;) {
		ret = read(fdin, buf, sizeof(buf));
		if (!ret)
			break;
		if (ret < 0) {
			perror("read");
			return 0;
		}
		if (!write_all(fdout, buf, ret)) {
			perror("write");
			return 0;
		}
	}
	return 1;
}

