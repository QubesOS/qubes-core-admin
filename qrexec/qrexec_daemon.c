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

#include <sys/select.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <ioall.h>
#include "qrexec.h"
#include "buffer.h"
#include "glue.h"

enum client_flags {
	CLIENT_INVALID = 0,
	CLIENT_CMDLINE = 1,
	CLIENT_DATA = 2,
	CLIENT_DONT_READ = 4,
	CLIENT_OUTQ_FULL = 8
};

struct _client {
	int state;
	struct buffer buffer;
};

struct _client clients[MAX_FDS];

int max_client_fd = -1;
int server_fd;

void handle_usr1(int x)
{
	exit(0);
}

char domain_id[64];

void init(int xid)
{
	char dbg_log[256];
	int logfd;

	if (xid <= 0) {
		fprintf(stderr, "domain id=0?\n");
		exit(1);
	}
	snprintf(domain_id, sizeof(domain_id), "%d", xid);
	signal(SIGUSR1, handle_usr1);
	switch (fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		break;
	default:
		pause();
		exit(0);
	}
	close(0);
	snprintf(dbg_log, sizeof(dbg_log),
		 "/var/log/qubes/qrexec.%d.log", xid);
	umask(0007);
	logfd = open(dbg_log, O_WRONLY | O_CREAT | O_TRUNC, 0640);
	dup2(logfd, 1);
	dup2(logfd, 2);

	chdir("/var/run/qubes");
	if (setsid() < 0) {
		perror("setsid()");
		exit(1);
	}

	umask(0);
	server_fd = get_server_socket(xid);
	umask(0077);
	peer_client_init(xid, REXEC_PORT);
	setuid(getuid());
	signal(SIGPIPE, SIG_IGN);
	signal(SIGCHLD, SIG_IGN);
	signal(SIGUSR1, SIG_DFL);
	kill(getppid(), SIGUSR1);
}

void handle_new_client()
{
	int fd = do_accept(server_fd);
	if (fd >= MAX_FDS) {
		fprintf(stderr, "too many clients ?\n");
		exit(1);
	}
	clients[fd].state = CLIENT_CMDLINE;
	buffer_init(&clients[fd].buffer);
	if (fd > max_client_fd)
		max_client_fd = fd;
}

void flush_client(int fd)
{
	int i;
	struct server_header s_hdr;
	close(fd);
	clients[fd].state = CLIENT_INVALID;
	buffer_free(&clients[fd].buffer);
	if (max_client_fd == fd) {
		for (i = fd; clients[i].state == CLIENT_INVALID && i >= 0;
		     i--);
		max_client_fd = i;
	}
	s_hdr.type = MSG_SERVER_TO_AGENT_CLIENT_END;
	s_hdr.clid = fd;
	s_hdr.len = 0;
	write_all_vchan_ext(&s_hdr, sizeof(s_hdr));
}

void pass_to_agent(int fd, struct server_header *s_hdr)
{
	int len = s_hdr->len;
	char buf[len];
	if (!read_all(fd, buf, len)) {
		flush_client(fd);
		return;
	}
	write_all_vchan_ext(s_hdr, sizeof(*s_hdr));
	write_all_vchan_ext(buf, len);
}

void set_nonblock(int fd)
{
	int fl = fcntl(fd, F_GETFL, 0);
	fcntl(fd, F_SETFL, fl | O_NONBLOCK);
}

void handle_client_cmdline(int fd)
{
	struct client_header hdr;
	struct server_header s_hdr;
	if (!read_all(fd, &hdr, sizeof hdr)) {
		flush_client(fd);
		return;
	}
	switch (hdr.type) {
	case MSG_CLIENT_TO_SERVER_EXEC_CMDLINE:
		s_hdr.type = MSG_SERVER_TO_AGENT_EXEC_CMDLINE;
		break;
	case MSG_CLIENT_TO_SERVER_JUST_EXEC:
		s_hdr.type = MSG_SERVER_TO_AGENT_JUST_EXEC;
		break;
	default:
		flush_client(fd);
		return;
	}

	s_hdr.clid = fd;
	s_hdr.len = hdr.len;
	pass_to_agent(fd, &s_hdr);
	clients[fd].state = CLIENT_DATA;
	set_nonblock(fd);
	if (hdr.type == MSG_CLIENT_TO_SERVER_JUST_EXEC)
		flush_client(fd);

}

void handle_client_data(int fd)
{
	struct server_header s_hdr;
	char buf[MAX_DATA_CHUNK];
	int len, ret;

	if (clients[fd].state == CLIENT_CMDLINE) {
		handle_client_cmdline(fd);
		return;
	}
	len = buffer_space_vchan_ext();
	if (len <= sizeof s_hdr)
		return;
	ret = read(fd, buf, len - sizeof(s_hdr));
	if (ret < 0) {
		perror("read client");
		flush_client(fd);
		return;
	}
	s_hdr.clid = fd;
	s_hdr.len = ret;
	s_hdr.type = MSG_SERVER_TO_AGENT_INPUT;

	write_all_vchan_ext(&s_hdr, sizeof(s_hdr));
	write_all_vchan_ext(buf, ret);
	if (ret == 0)
		clients[fd].state |= CLIENT_DONT_READ;
}

void flush_client_data_daemon(int clid)
{
	switch (flush_client_data(clid, clid, &clients[clid].buffer)) {
	case WRITE_STDIN_OK:
		clients[clid].state &= ~CLIENT_OUTQ_FULL;
		break;
	case WRITE_STDIN_ERROR:
		flush_client(clid);
		break;
	case WRITE_STDIN_BUFFERED:
		break;
	default:
		fprintf(stderr, "unknown flush_client_data?\n");
		exit(1);
	}
}

void pass_to_client(int clid, struct client_header *hdr)
{
	int len = hdr->len;
	char buf[sizeof(*hdr) + len];

	*(struct client_header *) buf = *hdr;
	read_all_vchan_ext(buf + sizeof(*hdr), len);

	switch (write_stdin
		(clid, clid, buf, len + sizeof(*hdr),
		 &clients[clid].buffer)) {
	case WRITE_STDIN_OK:
		break;
	case WRITE_STDIN_BUFFERED:
		clients[clid].state |= CLIENT_OUTQ_FULL;
		break;
	case WRITE_STDIN_ERROR:
		flush_client(clid);
		break;
	default:
		fprintf(stderr, "unknown write_stdin?\n");
		exit(1);
	}
}

void handle_trigger_exec(int req)
{
	char *rcmd = NULL, *lcmd = NULL;
	int i;
	switch (req) {
	case QREXEC_EXECUTE_FILE_COPY:
		rcmd = "directly:user:/usr/lib/qubes/qfile-agent";
		lcmd = "/usr/lib/qubes/qfile-daemon";
		break;
	case QREXEC_EXECUTE_FILE_COPY_FOR_DISPVM:
		rcmd = "directly:user:/usr/lib/qubes/qfile-agent-dvm";
		lcmd = "/usr/lib/qubes/qfile-daemon-dvm";
		break;
	default:
		fprintf(stderr, "got trigger exec no %d\n", req);
		exit(1);
	}
	switch (fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		break;
	default:
		return;
	}
	for (i = 3; i < 256; i++)
		close(i);
	signal(SIGCHLD, SIG_DFL);
	signal(SIGPIPE, SIG_DFL);
	execl("/usr/lib/qubes/qrexec_client", "qrexec_client", "-d",
	      domain_id, "-l", lcmd, rcmd, NULL);
	perror("execl");
	exit(1);
}

void handle_agent_data()
{
	struct client_header hdr;
	struct server_header s_hdr;
	read_all_vchan_ext(&s_hdr, sizeof s_hdr);

//      fprintf(stderr, "got %x %x %x\n", s_hdr.type, s_hdr.clid,
//              s_hdr.len);

	if (s_hdr.type == MSG_AGENT_TO_SERVER_TRIGGER_EXEC) {
		handle_trigger_exec(s_hdr.clid);
		return;
	}

	if (s_hdr.clid >= MAX_FDS || s_hdr.clid < 0) {
		fprintf(stderr, "from agent: clid=%d\n", s_hdr.clid);
		exit(1);
	}

	if (s_hdr.type == MSG_XOFF) {
		clients[s_hdr.clid].state |= CLIENT_DONT_READ;
		return;
	}
	if (s_hdr.type == MSG_XON) {
		clients[s_hdr.clid].state &= ~CLIENT_DONT_READ;
		return;
	}

	switch (s_hdr.type) {
	case MSG_AGENT_TO_SERVER_STDOUT:
		hdr.type = MSG_SERVER_TO_CLIENT_STDOUT;
		break;
	case MSG_AGENT_TO_SERVER_STDERR:
		hdr.type = MSG_SERVER_TO_CLIENT_STDERR;
		break;
	case MSG_AGENT_TO_SERVER_EXIT_CODE:
		hdr.type = MSG_SERVER_TO_CLIENT_EXIT_CODE;
		break;
	default:
		fprintf(stderr, "from agent: type=%d\n", s_hdr.type);
		exit(1);
	}
	hdr.len = s_hdr.len;
	if (hdr.len > MAX_DATA_CHUNK) {
		fprintf(stderr, "agent feeded %d of data bytes?\n",
			hdr.len);
		exit(1);
	}
	if (clients[s_hdr.clid].state == CLIENT_INVALID) {
		// benefit of doubt - maybe client exited earlier
		char buf[MAX_DATA_CHUNK];
		read_all_vchan_ext(buf, s_hdr.len);
		return;
	}
	pass_to_client(s_hdr.clid, &hdr);
	if (s_hdr.type == MSG_AGENT_TO_SERVER_EXIT_CODE)
		flush_client(s_hdr.clid);
}

int fill_fds_for_select(fd_set * rdset, fd_set * wrset)
{
	int i;
	int max = -1;
	FD_ZERO(rdset);
	FD_ZERO(wrset);
	for (i = 0; i <= max_client_fd; i++) {
		if (clients[i].state != CLIENT_INVALID
		    && !(clients[i].state & CLIENT_DONT_READ)) {
			FD_SET(i, rdset);
			max = i;
		}
		if (clients[i].state != CLIENT_INVALID
		    && clients[i].state & CLIENT_OUTQ_FULL) {
			FD_SET(i, wrset);
			max = i;
		}
	}
	FD_SET(server_fd, rdset);
	if (server_fd > max)
		max = server_fd;
	return max;
}

int main(int argc, char **argv)
{
	fd_set rdset, wrset;
	int i;
	int max;

	if (argc != 2) {
		fprintf(stderr, "usage: %s domainid\n", argv[0]);
		exit(1);
	}
	init(atoi(argv[1]));
	for (;;) {
		max = fill_fds_for_select(&rdset, &wrset);
		if (buffer_space_vchan_ext() <=
		    sizeof(struct server_header))
			FD_ZERO(&rdset);

		wait_for_vchan_or_argfd(max, &rdset, &wrset);

		if (FD_ISSET(server_fd, &rdset))
			handle_new_client();

		while (read_ready_vchan_ext())
			handle_agent_data();

		for (i = 0; i <= max_client_fd; i++)
			if (clients[i].state != CLIENT_INVALID
			    && FD_ISSET(i, &rdset))
				handle_client_data(i);

		for (i = 0; i <= max_client_fd; i++)
			if (clients[i].state != CLIENT_INVALID
			    && FD_ISSET(i, &wrset))
				flush_client_data_daemon(i);
	}
}
