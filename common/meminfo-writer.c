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
#include <sys/types.h>
#include <pwd.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdlib.h>
#include <xs.h>
#include <syslog.h>
int main()
{
	struct xs_handle *xs;
	int fd, n;
	char buf[4096];

	openlog("meminfo-writer", LOG_CONS | LOG_PID, LOG_DAEMON);
	xs = xs_domain_open();
	if (!xs) {
		syslog(LOG_DAEMON | LOG_ERR, "xs_domain_open");
		exit(1);
	}
	for (;;) {
		fd = open("/proc/meminfo", O_RDONLY);
		if (fd < 0) {
			syslog(LOG_DAEMON | LOG_ERR,
			       "error opening /proc/meminfo ?");
			exit(1);
		}
		n = read(fd, buf, sizeof(buf));
		if (n <= 0) {
			syslog(LOG_DAEMON | LOG_ERR,
			       "error reading /proc/meminfo ?");
			exit(1);
		}
		close(fd);
		if (!xs_write(xs, XBT_NULL, "memory/meminfo", buf, n)) {
			syslog(LOG_DAEMON | LOG_ERR,
			       "error writing xenstore ?");
			exit(1);
		}
		sleep(1);
	}
}
