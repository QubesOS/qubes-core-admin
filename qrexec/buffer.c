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
#include <stdlib.h>
#include <string.h>
#include "buffer.h"

#define BUFFER_LIMIT 50000000
static int total_mem;
static char *limited_malloc(int len)
{
	char *ret;
	total_mem += len;
	if (total_mem > BUFFER_LIMIT) {
		fprintf(stderr, "attempt to allocate >BUFFER_LIMIT\n");
		exit(1);
	}
	ret = malloc(len);
	if (!ret) {
		perror("malloc");
		exit(1);
	}
	return ret;
}

static void limited_free(char *ptr, int len)
{
	free(ptr);
	total_mem -= len;
}

void buffer_init(struct buffer *b)
{
	b->buflen = 0;
	b->data = NULL;
}

void buffer_free(struct buffer *b)
{
	if (b->buflen)
		limited_free(b->data, b->buflen);
	buffer_init(b);
}

/*
The following two functions can be made much more efficient.
Yet the profiling output show they are not significant CPU hogs, so
we keep them so simple to make them obviously correct.
*/

void buffer_append(struct buffer *b, char *data, int len)
{
	int newsize = len + b->buflen;
	char *qdata = limited_malloc(len + b->buflen);
	memcpy(qdata, b->data, b->buflen);
	memcpy(qdata + b->buflen, data, len);
	buffer_free(b);
	b->buflen = newsize;
	b->data = qdata;
}

void buffer_remove(struct buffer *b, int len)
{
	int newsize = b->buflen - len;
	char *qdata = limited_malloc(newsize);
	memcpy(qdata, b->data + len, newsize);
	buffer_free(b);
	b->buflen = newsize;
	b->data = qdata;
}

int buffer_len(struct buffer *b)
{
	return b->buflen;
}

void *buffer_data(struct buffer *b)
{
	return b->data;
}
