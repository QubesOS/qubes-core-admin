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
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <string.h>
#include <pwd.h>
#include <grp.h>
#include "qrexec.h"
#include "buffer.h"
#include "glue.h"

enum fdtype {
	FDTYPE_INVALID,
	FDTYPE_STDOUT,
	FDTYPE_STDERR
};

struct _process_fd {
	int clid;
	int type;
	int is_blocked;
};
struct _client_info {
	int stdin_fd;
	int stdout_fd;
	int stderr_fd;

	int pid;
	int is_blocked;
	struct buffer buffer;
};

int max_process_fd = -1;

/* indexed by file descriptor */
struct _process_fd process_fd[MAX_FDS];

/* indexed by client id, which is descriptor number of a client in daemon */
struct _client_info client_info[MAX_FDS];

void init()
{
	peer_server_init(REXEC_PORT);
}

void no_colon_in_cmd()
{
	fprintf(stderr,
		"cmdline is supposed to be in user:command form\n");
	exit(1);
}

void do_exec_directly(char *cmd)
{
	struct passwd *pwd;
	char *sep = index(cmd, ':');
	if (!sep)
		no_colon_in_cmd();
	*sep = 0;
	pwd = getpwnam(cmd);
	if (!pwd) {
		perror("getpwnam");
		exit(1);
	}
	setgid(pwd->pw_gid);
	initgroups(cmd, pwd->pw_gid);
	setuid(pwd->pw_uid);
	setenv("HOME", pwd->pw_dir, 1);
	setenv("USER", cmd, 1);
	execl(sep + 1, sep + 1, NULL);
	perror("execl");
	exit(1);
}

void do_exec(char *cmd)
{
	char *sep = index(cmd, ':');
	if (!sep)
		no_colon_in_cmd();
	*sep = 0;
	signal(SIGCHLD, SIG_DFL);
	signal(SIGPIPE, SIG_DFL);

	if (!strcmp(cmd, "directly"))
		do_exec_directly(sep + 1);
	execl("/bin/su", "su", "-", cmd, "-c", sep + 1, NULL);
	perror("execl");
	exit(1);
}

void handle_just_exec(int clid, int len)
{
	char buf[len];
	int fdn, pid;

	read_all_vchan_ext(buf, len);
	switch (pid = fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		fdn = open("/dev/null", O_RDWR);
		fix_fds(fdn, fdn, fdn);
		do_exec(buf);
		perror("execl");
		exit(1);
	default:;
	}
	fprintf(stderr, "executed (nowait) %s pid %d\n", buf, pid);
}

void handle_exec(int clid, int len)
{
	char buf[len];
	int pid, stdin_fd, stdout_fd, stderr_fd;

	read_all_vchan_ext(buf, len);

	do_fork_exec(buf, &pid, &stdin_fd, &stdout_fd, &stderr_fd);

	process_fd[stdout_fd].clid = clid;
	process_fd[stdout_fd].type = FDTYPE_STDOUT;
	process_fd[stdout_fd].is_blocked = 0;
	process_fd[stderr_fd].clid = clid;
	process_fd[stderr_fd].type = FDTYPE_STDERR;
	process_fd[stderr_fd].is_blocked = 0;

	if (stderr_fd > max_process_fd)
		max_process_fd = stderr_fd;
	if (stdout_fd > max_process_fd)
		max_process_fd = stdout_fd;

	set_nonblock(stdin_fd);

	client_info[clid].stdin_fd = stdin_fd;
	client_info[clid].stdout_fd = stdout_fd;
	client_info[clid].stderr_fd = stderr_fd;
	client_info[clid].pid = pid;
	client_info[clid].is_blocked = 0;
	buffer_init(&client_info[clid].buffer);

	fprintf(stderr, "executed %s pid %d\n", buf, pid);

}


void update_max_process_fd()
{
	int i;
	for (i = max_process_fd;
	     process_fd[i].type == FDTYPE_INVALID && i >= 0; i--);
	max_process_fd = i;
}

void send_exit_code(int clid, int status)
{
	struct server_header s_hdr;
	s_hdr.type = MSG_AGENT_TO_SERVER_EXIT_CODE;
	s_hdr.clid = clid;
	s_hdr.len = sizeof status;
	write_all_vchan_ext(&s_hdr, sizeof s_hdr);
	write_all_vchan_ext(&status, sizeof(status));
	fprintf(stderr, "send exit code for clid %d pid %d\n", clid,
		client_info[clid].pid);
}


// erase process data structures, possibly forced by remote
void remove_process(int clid, int status)
{
	int i;
	if (!client_info[clid].pid)
		return;
	kill(client_info[clid].pid, SIGKILL);

	if (status != -1)
		send_exit_code(clid, status);


	close(client_info[clid].stdin_fd);
	client_info[clid].pid = 0;
	client_info[clid].stdin_fd = -1;
	client_info[clid].is_blocked = 0;
	buffer_free(&client_info[clid].buffer);

	for (i = 0; i <= max_process_fd; i++)
		if (process_fd[i].type != FDTYPE_INVALID
		    && process_fd[i].clid == clid) {
			process_fd[i].type = FDTYPE_INVALID;
			process_fd[i].clid = -1;
			process_fd[i].is_blocked = 0;
			close(i);
		}
	update_max_process_fd();
}

void handle_input(int clid, int len)
{
	char buf[len];

	read_all_vchan_ext(buf, len);
	if (!client_info[clid].pid)
		return;

	if (len == 0) {
		close(client_info[clid].stdin_fd);
		client_info[clid].stdin_fd = -1;
		return;
	}

	switch (write_stdin
		(client_info[clid].stdin_fd, clid, buf, len,
		 &client_info[clid].buffer)) {
	case WRITE_STDIN_OK:
		break;
	case WRITE_STDIN_BUFFERED:
		client_info[clid].is_blocked = 1;
		break;
	case WRITE_STDIN_ERROR:
		remove_process(clid, 128);
		break;
	default:
		fprintf(stderr, "unknown write_stdin?\n");
		exit(1);
	}

}

void set_blocked_outerr(int clid, int val)
{
	process_fd[client_info[clid].stdout_fd].is_blocked = val;
	process_fd[client_info[clid].stderr_fd].is_blocked = val;
}

void handle_server_data()
{
	struct server_header s_hdr;
	read_all_vchan_ext(&s_hdr, sizeof s_hdr);

//      fprintf(stderr, "got %x %x %x\n", s_hdr.type, s_hdr.clid,
//              s_hdr.len);

	switch (s_hdr.type) {
	case MSG_XON:
		set_blocked_outerr(s_hdr.clid, 0);
		break;
	case MSG_XOFF:
		set_blocked_outerr(s_hdr.clid, 1);
		break;
	case MSG_SERVER_TO_AGENT_EXEC_CMDLINE:
		handle_exec(s_hdr.clid, s_hdr.len);
		break;
	case MSG_SERVER_TO_AGENT_JUST_EXEC:
		handle_just_exec(s_hdr.clid, s_hdr.len);
		break;
	case MSG_SERVER_TO_AGENT_INPUT:
		handle_input(s_hdr.clid, s_hdr.len);
		break;
	case MSG_SERVER_TO_AGENT_CLIENT_END:
		remove_process(s_hdr.clid, -1);
		break;
	default:
		fprintf(stderr, "msg type from daemon is %d ?\n",
			s_hdr.type);
		exit(1);
	}
}

void handle_process_data(int fd)
{
	struct server_header s_hdr;
	char buf[MAX_DATA_CHUNK];
	int ret;
	int len;

	len = buffer_space_vchan_ext();
	if (len <= sizeof s_hdr)
		return;

	ret = read(fd, buf, len - sizeof s_hdr);
	s_hdr.clid = process_fd[fd].clid;

	if (process_fd[fd].type == FDTYPE_STDOUT)
		s_hdr.type = MSG_AGENT_TO_SERVER_STDOUT;
	else if (process_fd[fd].type == FDTYPE_STDERR)
		s_hdr.type = MSG_AGENT_TO_SERVER_STDERR;
	else {
		fprintf(stderr, "fd=%d, clid=%d, type=%d ?\n", fd,
			process_fd[fd].clid, process_fd[fd].type);
		exit(1);
	}
	s_hdr.len = ret;
	if (ret >= 0) {
		write_all_vchan_ext(&s_hdr, sizeof s_hdr);
		write_all_vchan_ext(buf, ret);
	}
	if (ret == 0) {
		process_fd[fd].type = FDTYPE_INVALID;
		process_fd[fd].clid = -1;
		process_fd[fd].is_blocked = 0;
		close(fd);
		update_max_process_fd();
	}
	if (ret < 0)
		remove_process(process_fd[fd].clid, 127);
}

volatile int child_exited;

void sigchld_handler(int x)
{
	child_exited = 1;
	signal(SIGCHLD, sigchld_handler);
}

int find_info(int pid)
{
	int i;
	for (i = 0; i < MAX_FDS; i++)
		if (client_info[i].pid == pid)
			return i;
	return -1;
}


void handle_process_data_all(fd_set * select_fds)
{
	int i;
	for (i = 0; i <= max_process_fd; i++)
		if (process_fd[i].type != FDTYPE_INVALID
		    && FD_ISSET(i, select_fds))
			handle_process_data(i);
}


void flush_out_err(int clid)
{
	fd_set select_set;
	int fd_max = -1;
	int i;
	int ret;
	struct timeval tv;
	for (;;) {
		FD_ZERO(&select_set);
		for (i = 0; i <= max_process_fd; i++) {
			if (process_fd[i].type != FDTYPE_INVALID
			    && !process_fd[i].is_blocked
			    && process_fd[i].clid == clid) {
				FD_SET(i, &select_set);
				fd_max = i;
			}
		}
		if (fd_max == -1)
			return;
		tv.tv_sec = 0;
		tv.tv_usec = 0;
		ret = select(fd_max + 1, &select_set, NULL, NULL, &tv);
		if (ret < 0 && errno != EINTR) {
			perror("select");
			exit(1);
		}
		if (!ret)
			return;
		handle_process_data_all(&select_set);
	}
}

void reap_children()
{
	int status;
	int pid;
	int clid;
	while ((pid = waitpid(-1, &status, WNOHANG)) > 0) {
		clid = find_info(pid);
		if (clid < 0)
			continue;
		flush_out_err(clid);
		remove_process(clid, status);
	}
	child_exited = 0;
}

int fill_fds_for_select(fd_set * rdset, fd_set * wrset)
{
	int max = -1;
	int fd, i;
	FD_ZERO(rdset);
	FD_ZERO(wrset);

	for (i = 0; i <= max_process_fd; i++)
		if (process_fd[i].type != FDTYPE_INVALID
		    && !process_fd[i].is_blocked) {
			FD_SET(i, rdset);
			max = i;
		}
	for (i = 0; i < MAX_FDS; i++)
		if (client_info[i].pid > 0 && client_info[i].is_blocked) {
			fd = client_info[i].stdin_fd;
			FD_SET(fd, wrset);
			if (fd > max)
				max = fd;
		}
	return max;
}

void flush_client_data_agent(int clid)
{
	struct _client_info *info = &client_info[clid];
	switch (flush_client_data(info->stdin_fd, clid, &info->buffer)) {
	case WRITE_STDIN_OK:
		info->is_blocked = 0;
		break;
	case WRITE_STDIN_ERROR:
		remove_process(clid, 128);
		break;
	case WRITE_STDIN_BUFFERED:
		break;
	default:
		fprintf(stderr, "unknown flush_client_data?\n");
		exit(1);
	}
}


int main()
{
	fd_set rdset, wrset;
	int max;
	int i;

	init();
	signal(SIGCHLD, sigchld_handler);
	signal(SIGPIPE, SIG_IGN);


	for (;;) {
		max = fill_fds_for_select(&rdset, &wrset);
		if (buffer_space_vchan_ext() <=
		    sizeof(struct server_header))
			FD_ZERO(&rdset);

		wait_for_vchan_or_argfd(max, &rdset, &wrset);

		while (read_ready_vchan_ext())
			handle_server_data();

		handle_process_data_all(&rdset);
		for (i = 0; i <= MAX_FDS; i++)
			if (client_info[i].pid > 0
			    && client_info[i].is_blocked
			    && FD_ISSET(client_info[i].stdin_fd, &wrset))
				flush_client_data_agent(i);

		if (child_exited)
			reap_children();
	}
}
