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
#include <sys/inotify.h>
#include <fcntl.h>
#include <stdlib.h>
#include <xs.h>
#include <syslog.h>
#include <sys/stat.h>
#include <string.h>
#include "dvm.h"

int parse_events(char *buf, int len)
{
	int i = 0;
	while (i < len) {
		struct inotify_event *ev =
		    (struct inotify_event *) (buf + i);
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
	case 0:
		break;
	default:
		exit(0);
	}
}

int check_legal_filename(char *name)
{
	if (index(name, '/')) {
		syslog(LOG_DAEMON | LOG_ERR,
		       "the received filename contains /");
		return 0;
	}
	return 1;
}

void drop_to_user()
{
	struct passwd *pw = getpwnam("user");
	if (pw)
		setuid(pw->pw_uid);
}

int copy_from_xvdh(int destfd, int srcfd, unsigned long long count)
{
	int n, size;
	char buf[4096];
	unsigned long long total = 0;
	while (total < count) {
		if (count - total > sizeof(buf))
			size = sizeof(buf);
		else
			size = count - total;
		n = read(srcfd, buf, size);
		if (n != size) {
			syslog(LOG_DAEMON | LOG_ERR, "reading xvdh");
			return 0;
		}
		if (write(destfd, buf, size) != size) {
			syslog(LOG_DAEMON | LOG_ERR, "writing file");
			return 0;
		}
		total += size;
	}
	return 1;
}

void redirect_stderr()
{
	int fd =
	    open("/var/log/dvm.log", O_CREAT | O_TRUNC | O_WRONLY, 0600);
	if (fd < 0) {
		syslog(LOG_DAEMON | LOG_ERR, "open dvm.log");
		exit(1);
	}
	dup2(fd, 2);
}

void suicide(struct xs_handle *xs)
{
	xs_write(xs, XBT_NULL, "device/qpen", "killme", 6);
	xs_daemon_close(xs);
	exit(1);
}

void dvm_transaction_request(char *seq, struct xs_handle *xs)
{
	char filename[1024], cmdbuf[1024];
	struct dvm_header header;
	int xvdh_fd, file_fd;
	char *src_vm;
	unsigned int len;
	xvdh_fd = open("/dev/xvdh", O_RDONLY);
	if (read(xvdh_fd, &header, sizeof(header)) != sizeof(header)) {
		syslog(LOG_DAEMON | LOG_ERR, "read dvm_header");
		suicide(xs);
	}

	header.name[sizeof(header.name) - 1] = 0;
	if (!check_legal_filename(header.name))
		suicide(xs);
	snprintf(filename, sizeof(filename), "/tmp/%s", header.name);
	drop_to_user();

	file_fd = open(filename, O_CREAT | O_TRUNC | O_WRONLY, 0600);
	if (file_fd < 0) {
		syslog(LOG_DAEMON | LOG_ERR, "open file");
		suicide(xs);
	}
	if (!copy_from_xvdh(file_fd, xvdh_fd, header.file_size))
		suicide(xs);
	close(xvdh_fd);
	close(file_fd);
	snprintf(cmdbuf, sizeof(cmdbuf),
		 "DISPLAY=:0 mimeopen -n '/tmp/%s'", header.name);
	if (system(cmdbuf))
		system("DISPLAY=:0 /usr/bin/kdialog --sorry 'Unable to handle mimetype of the requested file'");
	src_vm = xs_read(xs, XBT_NULL, "qubes_blocksrc", &len);
	xs_write(xs, XBT_NULL, "device/qpen", "umount", 6);
	xs_daemon_close(xs);
	execl("/usr/bin/qvm-dvm-transfer", "qvm-dvm-transfer", src_vm,
	      filename, seq, NULL);
	syslog(LOG_DAEMON | LOG_ERR, "execl qvm-dvm-transfer");
	suicide(xs);
}

void dvm_transaction_return(char *seq_string, struct xs_handle *xs)
{
	int seq = strtoul(seq_string, 0, 10);
	char db_name[1024];
	char file_name[1024];
	int db_fd, file_fd, xvdh_fd;

	struct dvm_header header;
	xvdh_fd = open("/dev/xvdh", O_RDONLY);
	if (xvdh_fd < 0) {
		syslog(LOG_DAEMON | LOG_ERR, "open xvdh");
		goto out_err;
	}
	if (read(xvdh_fd, &header, sizeof(header)) != sizeof(header)) {
		syslog(LOG_DAEMON | LOG_ERR, "read dvm_header");
		goto out_err;
	}
	drop_to_user();
	snprintf(db_name, sizeof(db_name), DBDIR "/%d", seq);
	db_fd = open(db_name, O_RDONLY);
	if (!db_fd) {
		syslog(LOG_DAEMON | LOG_ERR, "open db");
		goto out_err;
	}
	if (read(db_fd, file_name, sizeof(file_name)) < 0) {
		syslog(LOG_DAEMON | LOG_ERR, "read db");
		goto out_err;
	}
	close(db_fd);
	file_fd = open(file_name, O_WRONLY | O_TRUNC);
	if (file_fd < 0) {
		syslog(LOG_DAEMON | LOG_ERR, "open filename");
		goto out_err;
	}
	copy_from_xvdh(file_fd, xvdh_fd, header.file_size);
	close(xvdh_fd);
	close(file_fd);
out_err:
	xs_write(xs, XBT_NULL, "device/qpen", "umount", 6);
	xs_daemon_close(xs);
}




void dvm_transaction(char *seq, struct xs_handle *xs)
{
	struct stat st;
	redirect_stderr();
	if (stat("/etc/this_is_dvm", &st))
		dvm_transaction_return(seq, xs);
	else
		dvm_transaction_request(seq, xs);
}

#define MOUNTDIR "/mnt/incoming"
int main()
{
	struct xs_handle *xs;
	char *seq;
	unsigned int len;
	background();
	openlog("qubes_add_pendrive_script", LOG_CONS | LOG_PID,
		LOG_DAEMON);
	xs = xs_domain_open();
	if (!xs) {
		syslog(LOG_DAEMON | LOG_ERR, "xs_domain_open");
		exit(1);
	}
	seq = xs_read(xs, XBT_NULL, "qubes_transaction_seq", &len);
	if (seq && len > 0 && strcmp(seq, "0")) {
		dvm_transaction(seq, xs);
		exit(0);
	}
	if (!system("su - user -c 'mount " MOUNTDIR "'"))
		wait_for_umount(MOUNTDIR "/.");
	xs_write(xs, XBT_NULL, "device/qpen", "umount", 6);
	xs_daemon_close(xs);
	return 0;
}
