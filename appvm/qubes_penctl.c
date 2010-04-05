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

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <xs.h>
int check_name(unsigned char *s)
{
	int c;
	for (; *s; s++) {
		c = *s;
		if (c >= 'a' && c <= 'z')
			continue;
		if (c >= 'A' && c <= 'Z')
			continue;
		if (c == '_' || c == '-')
			continue;
		return 0;
	}
	return 1;
}

int main(int argc, char **argv)
{
	char buf[256] = "new";
	struct xs_handle *xs;
	xs = xs_domain_open();
	setuid(getuid());
	if (!xs) {
		perror("xs_domain_open");
		exit(1);
	}
	if (argc < 2) {
		fprintf(stderr, "usage: %s new\n"
			"%s send vmname\n", argv[0], argv[0]);
		exit(1);
	}
	if (argc > 2) {
		if (!check_name((unsigned char*)argv[2])) {
			fprintf(stderr, "invalid vmname %s\n", argv[2]);
			exit(1);
		}
		snprintf(buf, sizeof(buf), "send %s", argv[2]);
	}
	if (!xs_write(xs, 0, "device/qpen", buf, strlen(buf))) {
		perror("xs_write");
		exit(1);
	}
	xs_daemon_close(xs);
	return 0;
}
