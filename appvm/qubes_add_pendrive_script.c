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
#include <sys/inotify.h>
#include <fcntl.h>
#include <stdlib.h>
int parse_events(char *buf, int len)
{
	int i = 0;
	while (i < len) {
		struct inotify_event *ev = (struct inotify_event *)(buf + i);
		if ((ev->mask & IN_UNMOUNT) || (ev->mask & IN_IGNORED))
			return 1;
		i += sizeof(struct inotify_event) + ev->len;
	}
	return 0;
}

#define BUFLEN 1024
void wait_for_umount(char *name)
{
	char buf[BUFLEN];
	int fd = inotify_init();
	int len;
	int ret = inotify_add_watch(fd, name, IN_ATTRIB);
	if (ret < 0) {
		perror("inotify_add_watch");
		return;
	}
	for (;;) {
		len = read(fd, buf, BUFLEN - 1);
		if (len <= 0) {
			perror("read inotify");
			return;
		}
		if (parse_events(buf, len))
			return;
	}
}

void background()
{
	int i, fd;
	for (i = 0; i < 256; i++)
		close(i);
	fd = open("/dev/null", O_RDWR);
	for (i = 0; i <= 2; i++)
		dup2(fd, i);
	switch (fork()) {
	case -1:
		exit(1);
	case 0: break;
	default:
		exit(0);
	}
}


#define MOUNTDIR "/mnt/incoming"
int main()
{
	background();
	if (!system("su - user -c 'mount " MOUNTDIR "'"))
		wait_for_umount(MOUNTDIR "/.");
	system("xenstore-write device/qpen umount");
	return 0;
}
