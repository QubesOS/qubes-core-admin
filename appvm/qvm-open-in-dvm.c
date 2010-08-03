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
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <xs.h>
#include "dvm.h"

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

int get_and_set_seq()
{
	int seq_fd, seq, n;
	mkdir(DBDIR, 0700);
	seq_fd = open(DBDIR "/seq", O_CREAT | O_RDWR, 0600);
	if (seq_fd < 0) {
		perror("open seq_fd");
		exit(1);
	}
	n = read(seq_fd, &seq, sizeof(seq));
	if (n < sizeof(seq))
		seq = 0;
	seq++;
	lseek(seq_fd, 0, SEEK_SET);
	write(seq_fd, &seq, sizeof(seq));
	close(seq_fd);
	return seq;
}
/*
Write the filename we are sending to DVM to DBDIR/transaction_seq
When DVM sends us a modified document via transaction with transaction_seq,
we will know that we are supposed to update the document with the
filename at DBDIR/transaction_seq
*/ 
void write_db(char *name, int seq)
{
	int db_fd;
	char dbname[256];
	struct stat st;
	if (!stat("/etc/this_is_dvm", &st))
		return;
	snprintf(dbname, sizeof(dbname), DBDIR "/%d", seq);
	db_fd = open(dbname, O_CREAT | O_WRONLY | O_TRUNC, 0600);
	if (db_fd < 0) {
		perror("open dbfile");
		exit(1);
	}
	if (write(db_fd, name, strlen(name) + 1) != strlen(name) + 1) {
		perror("write db");
		exit(1);
	}
	close(db_fd);
}

void copy_file(int xvdg_fd, int file_fd)
{
	int n;
	char buf[4096];

	for (;;) {
		n = read(file_fd, buf, sizeof(buf));
		if (n < 0) {
			perror("read file");
			exit(1);
		}
		if (n == 0)
			break;
		if (write(xvdg_fd, buf, n) != n) {
			perror("write file");
			exit(1);
		}
	}
}

int main(int argc, char **argv)
{
	struct dvm_header header = { 0, };
	struct stat st;
	struct xs_handle *xs;
	int seq;
	int xvdg_fd, file_fd;
	char *abs_filename;
	char buf[4096];

	if (argc != 3 && argc != 4) {
		fprintf(stderr, "usage: %s vmname file\n", argv[0]);
		exit(1);
	}
	check_name((unsigned char *) argv[1]);
	if (argv[2][0] == '/')
		abs_filename = argv[2];
	else {
		char cwd[4096];
		getcwd(cwd, sizeof(cwd));
		asprintf(&abs_filename, "%s/%s", cwd, argv[2]);
	}
	if (stat(abs_filename, &st)) {
		perror("stat file");
		exit(1);
	}
	header.file_size = st.st_size;
	strncpy(header.name, rindex(abs_filename, '/') + 1,
		sizeof(header.name) - 1);
	xs = xs_domain_open();
	if (!xs) {
		perror("xs_domain_open");
		exit(1);
	}
	// request a new block device at /dev/xvdg from qfileexchgd
	if (!xs_write(xs, 0, "device/qpen", "new", 3)) {
		perror("xs_write");
		exit(1);
	}
	while (stat("/dev/xvdg", &st))
		usleep(100000);
	xvdg_fd = open("/dev/xvdg", O_WRONLY);
	if (xvdg_fd < 0) {
		perror("open xvdg");
		exit(1);
	}
	setuid(getuid());
	if (argc == 3)
		// we are AppVM; get new seq
		seq = get_and_set_seq();
	else
		// we are DVM; use the cmdline transaction_seq
		seq = strtoul(argv[3], 0, 0);
	file_fd = open(abs_filename, O_RDONLY);
	if (file_fd < 0) {
		perror("open file");
		exit(1);
	}
	if (write(xvdg_fd, &header, sizeof(header)) != sizeof(header)) {
		perror("write filesize");
		exit(1);
	}
	copy_file(xvdg_fd, file_fd);
	close(file_fd);
	close(xvdg_fd);
	// request qfileexchgd to send our /dev/xvdg to its destination
	// either "disposable", which means "create DVM for me"
	// or vmname, meaning this is a reply to originator AppVM
	snprintf(buf, sizeof(buf), "send %s %d", argv[1], seq);
	if (!xs_write(xs, 0, "device/qpen", buf, strlen(buf))) {
		perror("xs_write");
		exit(1);
	}
	write_db(abs_filename, seq);
	xs_daemon_close(xs);
	return 0;
}
