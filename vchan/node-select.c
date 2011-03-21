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

#include "libvchan.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
int libvchan_write_all(struct libvchan *ctrl, char *buf, int size)
{
	int written = 0;
	int ret;
	while (written < size) {
		ret = libvchan_write(ctrl, buf + written, size - written);
		if (ret <= 0) {
			perror("write");
			exit(1);
		}
		written += ret;
	}
	return size;
}

int write_all(int fd, char *buf, int size)
{
	int written = 0;
	int ret;
	while (written < size) {
		ret = write(fd, buf + written, size - written);
		if (ret <= 0) {
			perror("write");
			exit(1);
		}
		written += ret;
	}
	return size;
}


void usage()
{
	fprintf(stderr, "usage:\n\tnode-select server nodeid\n"
		"or\n" "\tnode-select client domainid nodeid\n");
	exit(1);
}

#define BUFSIZE 5000
char buf[BUFSIZE];

/**
        Simple libvchan application, both client and server.
	Both sides may write and read, both from the libvchan and from 
	stdin/stdout (just like netcat). More code is required to avoid
	deadlock when both sides write, and noone reads.
*/

int main(int argc, char **argv)
{
	int ret;
	int libvchan_fd;
	struct libvchan *ctrl = 0;
	if (argc < 3)
		usage();
	if (!strcmp(argv[1], "server"))
		ctrl = libvchan_server_init(atoi(argv[2]));
	else if (!strcmp(argv[1], "client"))
		ctrl = libvchan_client_init(atoi(argv[2]), atoi(argv[3]));
	else
		usage();
	if (!ctrl) {
		perror("libvchan_*_init");
		exit(1);
	}

	libvchan_fd = libvchan_fd_for_select(ctrl);
	for (;;) {
		fd_set rfds;
		FD_ZERO(&rfds);
		FD_SET(0, &rfds);
		FD_SET(libvchan_fd, &rfds);
//		libvchan_prepare_to_select(ctrl);
		ret = select(libvchan_fd + 1, &rfds, NULL, NULL, NULL);
		if (ret < 0) {
			perror("select");
			exit(1);
		}
		if (libvchan_is_eof(ctrl))
			exit(0);
		if (FD_ISSET(libvchan_fd, &rfds))
// we don't care about the result, but we need to do the read to
// clear libvchan_fd pendind state 
			libvchan_wait(ctrl);
		while (libvchan_data_ready(ctrl) > 0) {
			ret = libvchan_read(ctrl, buf, BUFSIZE);
			if (ret < 0)
				exit(0);
			write_all(1, buf, ret);
		}
		if (FD_ISSET(0, &rfds)) {
			ret = read(0, buf, BUFSIZE);
			if (ret == 0) {
				libvchan_close(ctrl);
				exit(0);
			}
			if (ret < 0) {
				perror("read 0");
				exit(1);
			}
// libvchan_write_all can block; so if both sides write a lot,
// we can deadlock. Need higher level solution; would libvchan_write be ok ?                    
			libvchan_write_all(ctrl, buf, ret);
		}

	}
}
