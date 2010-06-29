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
void check_name(unsigned char *s)
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
		fprintf(stderr, "invalid string %s\n", s);
		exit(1);
	}
}

void usage(char *argv0)
{
	fprintf(stderr, "usage: %s [new|umount]\n"
		"%s send vmname [seq]\n", argv0, argv0);
	exit(1);
}

int main(int argc, char **argv)
{
	char buf[256];
	struct xs_handle *xs;
	xs = xs_domain_open();
	setuid(getuid());
	if (!xs) {
		perror("xs_domain_open");
		exit(1);
	}
	switch (argc) {
	case 2:
		if (!strcmp(argv[1], "umount"))
			strcpy(buf, "umount");
		else
			strcpy(buf, "new");	
		break;
	case 3:
		check_name((unsigned char *) argv[2]);
		snprintf(buf, sizeof(buf), "send %s", argv[2]);
		break;
	case 4:
		check_name((unsigned char *) argv[2]);
		check_name((unsigned char *) argv[3]);
		snprintf(buf, sizeof(buf), "send %s %s", argv[2], argv[3]);
	default:
		usage(argv[0]);
	}

	if (!xs_write(xs, 0, "device/qpen", buf, strlen(buf))) {
		perror("xs_write");
		exit(1);
	}
	xs_daemon_close(xs);
	return 0;
}
