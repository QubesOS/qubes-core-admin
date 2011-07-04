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

#include <sys/socket.h>
#include <sys/un.h>
#include <stdio.h>
#include <getopt.h>
#include <stdlib.h>
#include <unistd.h>
#include <ioall.h>
#include <sys/wait.h>
#include "qrexec.h"
#include "buffer.h"
#include "glue.h"

int connect_unix_socket(char *domname)
{
	int s, len;
	struct sockaddr_un remote;

	if ((s = socket(AF_UNIX, SOCK_STREAM, 0)) == -1) {
		perror("socket");
		return -1;
	}

	remote.sun_family = AF_UNIX;
	snprintf(remote.sun_path, sizeof remote.sun_path,
		 QREXEC_DAEMON_SOCKET_DIR "/qrexec.%s", domname);
	len = strlen(remote.sun_path) + sizeof(remote.sun_family);
	if (connect(s, (struct sockaddr *) &remote, len) == -1) {
		perror("connect");
		exit(1);
	}
	return s;
}

void do_exec(char *prog)
{
	execl("/bin/bash", "bash", "-c", prog, NULL);
}

int local_stdin_fd, local_stdout_fd;

void do_exit(int code)
{
	int status;
// sever communication lines; wait for child, if any
// so that qrexec-daemon can count (recursively) spawned processes correctly          
	close(local_stdin_fd);
	close(local_stdout_fd);
	waitpid(-1, &status, 0);
	exit(code);
}


void prepare_local_fds(char *cmdline)
{
	int pid;
	if (!cmdline) {
		local_stdin_fd = 1;
		local_stdout_fd = 0;
		return;
	}
	do_fork_exec(cmdline, &pid, &local_stdin_fd, &local_stdout_fd,
		     NULL);
}


void send_cmdline(int s, int type, char *cmdline)
{
	struct client_header hdr;
	hdr.type = type;
	hdr.len = strlen(cmdline) + 1;
	if (!write_all(s, &hdr, sizeof(hdr))
	    || !write_all(s, cmdline, hdr.len)) {
		perror("write daemon");
		do_exit(1);
	}
}

void handle_input(int s)
{
	char buf[MAX_DATA_CHUNK];
	int ret;
	ret = read(local_stdout_fd, buf, sizeof(buf));
	if (ret < 0) {
		perror("read");
		do_exit(1);
	}
	if (ret == 0) {
		local_stdout_fd = -1;
		shutdown(s, SHUT_WR);
	}
	if (!write_all(s, buf, ret)) {
		perror("write daemon");
		do_exit(1);
	}
}

void handle_daemon_data(int s)
{
	int status;
	struct client_header hdr;
	char buf[MAX_DATA_CHUNK];

	if (!read_all(s, &hdr, sizeof hdr)) {
		perror("read daemon");
		do_exit(1);
	}
	if (hdr.len > MAX_DATA_CHUNK) {
		fprintf(stderr, "client_header.len=%d\n", hdr.len);
		do_exit(1);
	}
	if (!read_all(s, buf, hdr.len)) {
		perror("read daemon");
		do_exit(1);
	}

	switch (hdr.type) {
	case MSG_SERVER_TO_CLIENT_STDOUT:
		if (hdr.len == 0)
			close(local_stdin_fd);
		else if (!write_all(local_stdin_fd, buf, hdr.len)) {
			perror("write local stdout");
			do_exit(1);
		}
		break;
	case MSG_SERVER_TO_CLIENT_STDERR:
		write_all(2, buf, hdr.len);
		break;
	case MSG_SERVER_TO_CLIENT_EXIT_CODE:
		status = *(unsigned int *) buf;
		if (WIFEXITED(status))
			do_exit(WEXITSTATUS(status));
		else
			do_exit(255);
		break;
	default:
		fprintf(stderr, "unknown msg %d\n", hdr.type);
		do_exit(1);
	}
}

// perhaps we could save a syscall if we include both sides in both
// rdset and wrset; to be investigated
void handle_daemon_only_until_writable(s)
{
	fd_set rdset, wrset;

	do {
		FD_ZERO(&rdset);
		FD_ZERO(&wrset);
		FD_SET(s, &rdset);
		FD_SET(s, &wrset);

		if (select(s + 1, &rdset, &wrset, NULL, NULL) < 0) {
			perror("select");
			do_exit(1);
		}
		if (FD_ISSET(s, &rdset))
			handle_daemon_data(s);
	} while (!FD_ISSET(s, &wrset));
}

void select_loop(int s)
{
	fd_set select_set;
	int max;
	for (;;) {
		handle_daemon_only_until_writable(s);
		FD_ZERO(&select_set);
		FD_SET(s, &select_set);
		max = s;
		if (local_stdout_fd != -1) {
			FD_SET(local_stdout_fd, &select_set);
			if (s < local_stdout_fd)
				max = local_stdout_fd;
		}
		if (select(max + 1, &select_set, NULL, NULL, NULL) < 0) {
			perror("select");
			do_exit(1);
		}
		if (FD_ISSET(s, &select_set))
			handle_daemon_data(s);
		if (local_stdout_fd != -1
		    && FD_ISSET(local_stdout_fd, &select_set))
			handle_input(s);
	}
}

void usage(char *name)
{
	fprintf(stderr,
		"usage: %s -d domain_num [-l local_prog] -e -c remote_cmdline\n"
		"-e means exit after sending cmd, -c: connect to existing process\n",
		name);
	exit(1);
}

int main(int argc, char **argv)
{
	int opt;
	char *domname = NULL;
	int s;
	int just_exec = 0;
	int connect_existing = 0;
	char *local_cmdline = NULL;
	while ((opt = getopt(argc, argv, "d:l:e")) != -1) {
		switch (opt) {
		case 'd':
			domname = strdup(optarg);
			break;
		case 'l':
			local_cmdline = strdup(optarg);
			break;
		case 'e':
			just_exec = 1;
			break;
		case 'c':
			connect_existing = 1;
			break;
		default:
			usage(argv[0]);
		}
	}
	if (optind >= argc || !domname)
		usage(argv[0]);

	s = connect_unix_socket(domname);
	setenv("QREXEC_REMOTE_DOMAIN", domname, 1);
	prepare_local_fds(local_cmdline);

	if (just_exec)
		send_cmdline(s, MSG_CLIENT_TO_SERVER_JUST_EXEC,
			     argv[optind]);
	else {
		int cmd;
		if (connect_existing)
			cmd = MSG_CLIENT_TO_SERVER_CONNECT_EXISTING;
		else
			cmd = MSG_CLIENT_TO_SERVER_EXEC_CMDLINE;
		send_cmdline(s, cmd, argv[optind]);
		select_loop(s);
	}
	return 0;
}
