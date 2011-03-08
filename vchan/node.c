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
#include <time.h>
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
	fprintf(stderr, "usage:\n\tnode server [read|write] nodeid\n"
		"or\n" "\tnode client [read|write] domainid nodeid\n");
	exit(1);
}

#define BUFSIZE 5000
char buf[BUFSIZE];
void reader(struct libvchan *ctrl)
{
	int size;
	for (;;) {
		size = rand() % (BUFSIZE - 1) + 1;
		size = libvchan_read(ctrl, buf, size);
		fprintf(stderr, "#");
		if (size < 0) {
			perror("read vchan");
			libvchan_close(ctrl);
			exit(1);
		}
		if (size == 0)
			break;
		size = write_all(1, buf, size);
		if (size < 0) {
			perror("stdout write");
			exit(1);
		}
		if (size == 0) {
			perror("write size=0?\n");
			exit(1);
		}
	}
}

void writer(struct libvchan *ctrl)
{
	int size;
	for (;;) {
		size = rand() % (BUFSIZE - 1) + 1;
		size = read(0, buf, size);
		if (size < 0) {
			perror("read stdin");
			libvchan_close(ctrl);
			exit(1);
		}
		if (size == 0)
			break;
		size = libvchan_write_all(ctrl, buf, size);
		fprintf(stderr, "#");
		if (size < 0) {
			perror("vchan write");
			exit(1);
		}
		if (size == 0) {
			perror("write size=0?\n");
			exit(1);
		}
	}
}


/**
	Simple libvchan application, both client and server.
	One side does writing, the other side does reading; both from
	standard input/output fds.
*/
int main(int argc, char **argv)
{
	int seed = time(0);
	struct libvchan *ctrl = 0;
	int wr;
	if (argc < 4)
		usage();
	if (!strcmp(argv[2], "read"))
		wr = 0;
	else if (!strcmp(argv[2], "write"))
		wr = 1;
	else
		usage();
	if (!strcmp(argv[1], "server"))
		ctrl = libvchan_server_init(atoi(argv[3]));
	else if (!strcmp(argv[1], "client"))
		ctrl = libvchan_client_init(atoi(argv[3]), atoi(argv[4]));
	else
		usage();
	if (!ctrl) {
		perror("libvchan_*_init");
		exit(1);
	}

	srand(seed);
	fprintf(stderr, "seed=%d\n", seed);
	if (wr)
		writer(ctrl);
	else
		reader(ctrl);
	libvchan_close(ctrl);
	return 0;
}
