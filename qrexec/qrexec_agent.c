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
#include <sys/stat.h>
#include "qrexec.h"
#include "buffer.h"
#include "glue.h"

enum fdtype {
	FDTYPE_INVALID,
	FDTYPE_STDOUT,
	FDTYPE_STDERR
};

struct _process_fd {
	int client_id;
	int type;
	int is_blocked;
};
struct _client_info {
	int stdin_fd;
	int stdout_fd;
	int stderr_fd;

	int exit_status;
	int is_exited;
	int pid;
	int is_blocked;
	int is_close_after_flush_needed;
	struct buffer buffer;
};

int max_process_fd = -1;

/* indexed by file descriptor */
struct _process_fd process_fd[MAX_FDS];

/* indexed by client id, which is descriptor number of a client in daemon */
struct _client_info client_info[MAX_FDS];

int trigger_fd;
int passfd_socket;

int meminfo_write_started = 0;

void init()
{
	peer_server_init(REXEC_PORT);
	umask(0);
	mkfifo(QREXEC_AGENT_TRIGGER_PATH, 0666);
	passfd_socket = get_server_socket(QREXEC_AGENT_FDPASS_PATH);
	umask(077);
	trigger_fd =
	    open(QREXEC_AGENT_TRIGGER_PATH, O_RDONLY | O_NONBLOCK);
}

void wake_meminfo_writer() {
	FILE *f;
	pid_t pid;

	if (meminfo_write_started)
		/* wake meminfo-writer only once */
		return;

	f = fopen(MEMINFO_WRITER_PIDFILE, "r");
	if (f == NULL) {
		/* no meminfo-writer found, ignoring */
		return;
	}
	if (fscanf(f, "%d", &pid) < 1) {
		/* no meminfo-writer found, ignoring */
		return;
	}

	fclose(f);
	kill(pid, SIGUSR1);
	meminfo_write_started = 1;
}

void no_colon_in_cmd()
{
	fprintf(stderr,
		"cmdline is supposed to be in user:command form\n");
	exit(1);
}

void do_exec(char *cmd)
{
	char buf[strlen(QUBES_RPC_MULTIPLEXER_PATH) + strlen(cmd) - strlen(QUBES_RPC_MAGIC_CMD) + 1];
	char *realcmd = index(cmd, ':');
	if (!realcmd)
		no_colon_in_cmd();
	/* mark end of username and move to command */
	*realcmd = 0;
	realcmd++;
	/* replace magic RPC cmd with RPC multiplexer path */
	if (strncmp(realcmd, QUBES_RPC_MAGIC_CMD " ", strlen(QUBES_RPC_MAGIC_CMD)+1)==0) {
		strcpy(buf, QUBES_RPC_MULTIPLEXER_PATH);
		strcpy(buf + strlen(QUBES_RPC_MULTIPLEXER_PATH), realcmd + strlen(QUBES_RPC_MAGIC_CMD));
		realcmd = buf;
	}
	signal(SIGCHLD, SIG_DFL);
	signal(SIGPIPE, SIG_DFL);

	execl("/bin/su", "su", "-", cmd, "-c", realcmd, NULL);
	perror("execl");
	exit(1);
}

void handle_just_exec(int client_id, int len)
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

void create_info_about_client(int client_id, int pid, int stdin_fd,
			      int stdout_fd, int stderr_fd)
{
	process_fd[stdout_fd].client_id = client_id;
	process_fd[stdout_fd].type = FDTYPE_STDOUT;
	process_fd[stdout_fd].is_blocked = 0;
	process_fd[stderr_fd].client_id = client_id;
	process_fd[stderr_fd].type = FDTYPE_STDERR;
	process_fd[stderr_fd].is_blocked = 0;

	if (stderr_fd > max_process_fd)
		max_process_fd = stderr_fd;
	if (stdout_fd > max_process_fd)
		max_process_fd = stdout_fd;

	set_nonblock(stdin_fd);

	client_info[client_id].stdin_fd = stdin_fd;
	client_info[client_id].stdout_fd = stdout_fd;
	client_info[client_id].stderr_fd = stderr_fd;
	client_info[client_id].exit_status = 0;
	client_info[client_id].is_exited = 0;
	client_info[client_id].pid = pid;
	client_info[client_id].is_blocked = 0;
	client_info[client_id].is_close_after_flush_needed = 0;
	buffer_init(&client_info[client_id].buffer);
}

void handle_exec(int client_id, int len)
{
	char buf[len];
	int pid, stdin_fd, stdout_fd, stderr_fd;

	read_all_vchan_ext(buf, len);

	do_fork_exec(buf, &pid, &stdin_fd, &stdout_fd, &stderr_fd);

	create_info_about_client(client_id, pid, stdin_fd, stdout_fd,
				 stderr_fd);

	fprintf(stderr, "executed %s pid %d\n", buf, pid);

}

void handle_connect_existing(int client_id, int len)
{
	int stdin_fd, stdout_fd, stderr_fd;
	char buf[len];
	read_all_vchan_ext(buf, len);
	sscanf(buf, "%d %d %d", &stdin_fd, &stdout_fd, &stderr_fd);
	create_info_about_client(client_id, -1, stdin_fd, stdout_fd,
				 stderr_fd);
	client_info[client_id].is_exited = 1;	//do not wait for SIGCHLD
}

void update_max_process_fd()
{
	int i;
	for (i = max_process_fd;
	     process_fd[i].type == FDTYPE_INVALID && i >= 0; i--);
	max_process_fd = i;
}

void send_exit_code(int client_id, int status)
{
	struct server_header s_hdr;
	s_hdr.type = MSG_AGENT_TO_SERVER_EXIT_CODE;
	s_hdr.client_id = client_id;
	s_hdr.len = sizeof status;
	write_all_vchan_ext(&s_hdr, sizeof s_hdr);
	write_all_vchan_ext(&status, sizeof(status));
	fprintf(stderr, "send exit code for client_id %d pid %d\n",
		client_id, client_info[client_id].pid);
}


// erase process data structures, possibly forced by remote
void remove_process(int client_id, int status)
{
	int i;
	if (!client_info[client_id].pid)
		return;
	fork_and_flush_stdin(client_info[client_id].stdin_fd,
			     &client_info[client_id].buffer);
#if 0
//      let's let it die by itself, possibly after it has received buffered stdin
	kill(client_info[client_id].pid, SIGKILL);
#endif
	if (status != -1)
		send_exit_code(client_id, status);


	close(client_info[client_id].stdin_fd);
	client_info[client_id].pid = 0;
	client_info[client_id].stdin_fd = -1;
	client_info[client_id].is_blocked = 0;
	buffer_free(&client_info[client_id].buffer);

	for (i = 0; i <= max_process_fd; i++)
		if (process_fd[i].type != FDTYPE_INVALID
		    && process_fd[i].client_id == client_id) {
			process_fd[i].type = FDTYPE_INVALID;
			process_fd[i].client_id = -1;
			process_fd[i].is_blocked = 0;
			close(i);
		}
	update_max_process_fd();
}

// remove process not immediately after it has exited, but after its stdout and stderr has been drained
// previous method implemented in flush_out_err was broken - it cannot work when peer signalled it is blocked
void possibly_remove_process(int client_id)
{
	if (client_info[client_id].stdout_fd == -1 &&
	    client_info[client_id].stderr_fd == -1 &&
	    client_info[client_id].is_exited)
		remove_process(client_id,
			       client_info[client_id].exit_status);
}


void handle_input(int client_id, int len)
{
	char buf[len];

	read_all_vchan_ext(buf, len);
	if (!client_info[client_id].pid)
		return;

	if (len == 0) {
		if (client_info[client_id].is_blocked)
			client_info[client_id].is_close_after_flush_needed
			    = 1;
		else {
			close(client_info[client_id].stdin_fd);
			client_info[client_id].stdin_fd = -1;
		}
		return;
	}

	switch (write_stdin
		(client_info[client_id].stdin_fd, client_id, buf, len,
		 &client_info[client_id].buffer)) {
	case WRITE_STDIN_OK:
		break;
	case WRITE_STDIN_BUFFERED:
		client_info[client_id].is_blocked = 1;
		break;
	case WRITE_STDIN_ERROR:
		remove_process(client_id, 128);
		break;
	default:
		fprintf(stderr, "unknown write_stdin?\n");
		exit(1);
	}

}

void set_blocked_outerr(int client_id, int val)
{
	process_fd[client_info[client_id].stdout_fd].is_blocked = val;
	process_fd[client_info[client_id].stderr_fd].is_blocked = val;
}

void handle_server_data()
{
	struct server_header s_hdr;
	read_all_vchan_ext(&s_hdr, sizeof s_hdr);

//      fprintf(stderr, "got %x %x %x\n", s_hdr.type, s_hdr.client_id,
//              s_hdr.len);

	switch (s_hdr.type) {
	case MSG_XON:
		set_blocked_outerr(s_hdr.client_id, 0);
		break;
	case MSG_XOFF:
		set_blocked_outerr(s_hdr.client_id, 1);
		break;
	case MSG_SERVER_TO_AGENT_CONNECT_EXISTING:
		handle_connect_existing(s_hdr.client_id, s_hdr.len);
		break;
	case MSG_SERVER_TO_AGENT_EXEC_CMDLINE:
		wake_meminfo_writer();
		handle_exec(s_hdr.client_id, s_hdr.len);
		break;
	case MSG_SERVER_TO_AGENT_JUST_EXEC:
		wake_meminfo_writer();
		handle_just_exec(s_hdr.client_id, s_hdr.len);
		break;
	case MSG_SERVER_TO_AGENT_INPUT:
		handle_input(s_hdr.client_id, s_hdr.len);
		break;
	case MSG_SERVER_TO_AGENT_CLIENT_END:
		remove_process(s_hdr.client_id, -1);
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
	s_hdr.client_id = process_fd[fd].client_id;

	if (process_fd[fd].type == FDTYPE_STDOUT)
		s_hdr.type = MSG_AGENT_TO_SERVER_STDOUT;
	else if (process_fd[fd].type == FDTYPE_STDERR)
		s_hdr.type = MSG_AGENT_TO_SERVER_STDERR;
	else {
		fprintf(stderr, "fd=%d, client_id=%d, type=%d ?\n", fd,
			process_fd[fd].client_id, process_fd[fd].type);
		exit(1);
	}
	s_hdr.len = ret;
	if (ret >= 0) {
		write_all_vchan_ext(&s_hdr, sizeof s_hdr);
		write_all_vchan_ext(buf, ret);
	}
	if (ret == 0) {
		int client_id = process_fd[fd].client_id;
		if (process_fd[fd].type == FDTYPE_STDOUT)
			client_info[client_id].stdout_fd = -1;
		else
			client_info[client_id].stderr_fd = -1;

		process_fd[fd].type = FDTYPE_INVALID;
		process_fd[fd].client_id = -1;
		process_fd[fd].is_blocked = 0;
		close(fd);
		update_max_process_fd();
		possibly_remove_process(client_id);
	}
	if (ret < 0)
		remove_process(process_fd[fd].client_id, 127);
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

void reap_children()
{
	int status;
	int pid;
	int client_id;
	while ((pid = waitpid(-1, &status, WNOHANG)) > 0) {
		client_id = find_info(pid);
		if (client_id < 0)
			continue;
		client_info[client_id].is_exited = 1;
		client_info[client_id].exit_status = status;
		possibly_remove_process(client_id);
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

	FD_SET(trigger_fd, rdset);
	if (trigger_fd > max)
		max = trigger_fd;
	FD_SET(passfd_socket, rdset);
	if (passfd_socket > max)
		max = passfd_socket;

	for (i = 0; i < MAX_FDS; i++)
		if (client_info[i].pid && client_info[i].is_blocked) {
			fd = client_info[i].stdin_fd;
			FD_SET(fd, wrset);
			if (fd > max)
				max = fd;
		}
	return max;
}

void flush_client_data_agent(int client_id)
{
	struct _client_info *info = &client_info[client_id];
	switch (flush_client_data
		(info->stdin_fd, client_id, &info->buffer)) {
	case WRITE_STDIN_OK:
		info->is_blocked = 0;
		if (info->is_close_after_flush_needed) {
			close(info->stdin_fd);
			info->stdin_fd = -1;
			info->is_close_after_flush_needed = 0;
		}
		break;
	case WRITE_STDIN_ERROR:
		remove_process(client_id, 128);
		break;
	case WRITE_STDIN_BUFFERED:
		break;
	default:
		fprintf(stderr, "unknown flush_client_data?\n");
		exit(1);
	}
}

void handle_new_passfd()
{
	int fd = do_accept(passfd_socket);
	if (fd >= MAX_FDS) {
		fprintf(stderr, "too many clients ?\n");
		exit(1);
	}
	// let client know what fd has been allocated
	write(fd, &fd, sizeof(fd));
}


void handle_trigger_io()
{
	struct server_header s_hdr;
	struct trigger_connect_params params;
	int ret;

	s_hdr.client_id = 0;
	s_hdr.len = 0;
	ret = read(trigger_fd, &params, sizeof(params));
	if (ret == sizeof(params)) {
		s_hdr.type = MSG_AGENT_TO_SERVER_TRIGGER_CONNECT_EXISTING;
		write_all_vchan_ext(&s_hdr, sizeof s_hdr);
		write_all_vchan_ext(&params, sizeof params);
	}
// trigger_fd is nonblock - so no need to reopen
// not really, need to reopen at EOF
	if (ret <= 0) {
		close(trigger_fd);
		trigger_fd =
		    open(QREXEC_AGENT_TRIGGER_PATH, O_RDONLY | O_NONBLOCK);
	}
}

int main()
{
	fd_set rdset, wrset;
	int max;
	int i;
	sigset_t chld_set;

	init();
	signal(SIGCHLD, sigchld_handler);
	signal(SIGPIPE, SIG_IGN);
	sigemptyset(&chld_set);
	sigaddset(&chld_set, SIGCHLD);


	for (;;) {
		sigprocmask(SIG_BLOCK, &chld_set, NULL);
		if (child_exited)
			reap_children();
		max = fill_fds_for_select(&rdset, &wrset);
		if (buffer_space_vchan_ext() <=
		    sizeof(struct server_header))
			FD_ZERO(&rdset);

		wait_for_vchan_or_argfd(max, &rdset, &wrset);
		sigprocmask(SIG_UNBLOCK, &chld_set, NULL);

		if (FD_ISSET(passfd_socket, &rdset))
			handle_new_passfd();

		while (read_ready_vchan_ext())
			handle_server_data();

		if (FD_ISSET(trigger_fd, &rdset))
			handle_trigger_io();

		handle_process_data_all(&rdset);
		for (i = 0; i <= MAX_FDS; i++)
			if (client_info[i].pid
			    && client_info[i].is_blocked
			    && FD_ISSET(client_info[i].stdin_fd, &wrset))
				flush_client_data_agent(i);
	}
}
