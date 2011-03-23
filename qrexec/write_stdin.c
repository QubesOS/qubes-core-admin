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

#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <ioall.h>
#include <stdlib.h>
#include "qrexec.h"
#include "buffer.h"
#include "glue.h"

int flush_client_data(int fd, int clid, struct buffer *buffer)
{
	int ret;
	int len;
	for (;;) {
		len = buffer_len(buffer);
		if (len > MAX_DATA_CHUNK)
			len = MAX_DATA_CHUNK;
		ret = write(fd, buffer_data(buffer), len);
		if (ret == -1) {
			if (errno != EAGAIN) {
				return WRITE_STDIN_ERROR;
			} else
				return WRITE_STDIN_BUFFERED;
		}
		buffer_remove(buffer, len);
		len = buffer_len(buffer);
		if (!len) {
			struct server_header s_hdr;
			s_hdr.type = MSG_XON;
			s_hdr.clid = clid;
			s_hdr.len = 0;
			write_all_vchan_ext(&s_hdr, sizeof s_hdr);
			return WRITE_STDIN_OK;
		}
	}

}

int write_stdin(int fd, int clid, char *data, int len,
		struct buffer *buffer)
{
	int ret;
	int written = 0;

	if (buffer_len(buffer)) {
		buffer_append(buffer, data, len);
		return WRITE_STDIN_BUFFERED;
	}
	while (written < len) {
		ret = write(fd, data + written, len - written);
		if (ret == 0) {
			perror("write_stdin: write returns 0 ???");
			exit(1);
		}
		if (ret == -1) {
			struct server_header s_hdr;

			if (errno != EAGAIN)
				return WRITE_STDIN_ERROR;

			buffer_append(buffer, data + written,
				      len - written);

			s_hdr.type = MSG_XOFF;
			s_hdr.clid = clid;
			s_hdr.len = 0;
			write_all_vchan_ext(&s_hdr, sizeof s_hdr);

			return WRITE_STDIN_BUFFERED;
		}
		written += ret;
	}
	return WRITE_STDIN_OK;

}

void set_nonblock(int fd)
{
	int fl = fcntl(fd, F_GETFL, 0);
	fcntl(fd, F_SETFL, fl | O_NONBLOCK);
}

void set_block(int fd)
{
	int fl = fcntl(fd, F_GETFL, 0);
	fcntl(fd, F_SETFL, fl & ~O_NONBLOCK);
}

int fork_and_flush_stdin(int fd, struct buffer *buffer)
{
	int i;
	if (!buffer_len(buffer))
		return 0;
	switch (fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		break;
	default:
		return 1;
	}
	for (i = 0; i < MAX_FDS; i++)
		if (i != fd && i != 2)
			close(i);
	set_block(fd);
	write_all(fd, buffer_data(buffer), buffer_len(buffer));
	exit(0);
}
