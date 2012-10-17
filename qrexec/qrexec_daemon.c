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
#include <sys/wait.h>
#include <ioall.h>
#include <string.h>
#include "qrexec.h"
#include "buffer.h"
#include "glue.h"

enum client_flags {
	CLIENT_INVALID = 0,	// table slot not used
	CLIENT_CMDLINE = 1,	// waiting for cmdline from client
	CLIENT_DATA = 2,	// waiting for data from client
	CLIENT_DONT_READ = 4,	// don't read from the client, the other side pipe is full, or EOF (additionally marked with CLIENT_EOF)
	CLIENT_OUTQ_FULL = 8,	// don't write to client, its stdin pipe is full
	CLIENT_EOF = 16,	// got EOF
	CLIENT_EXITED = 32	// only send remaining data from client and remove from list
};

struct _client {
	int state;		// combination of above enum client_flags
	struct buffer buffer;	// buffered data to client, if any
};

/*
The "clients" array is indexed by client's fd.
Thus its size must be equal MAX_FDS; defining MAX_CLIENTS for clarity.
*/

#define MAX_CLIENTS MAX_FDS
struct _client clients[MAX_CLIENTS];	// data on all qrexec_client connections

int max_client_fd = -1;		// current max fd of all clients; so that we need not to scan all the "clients" table
int qrexec_daemon_unix_socket_fd;	// /var/run/qubes/qrexec.xid descriptor
char *default_user = "user";
char default_user_keyword[] = "DEFAULT:";
#define default_user_keyword_len_without_colon (sizeof(default_user_keyword)-2)

void sigusr1_handler(int x)
{
	fprintf(stderr, "connected\n");
	exit(0);
}

void sigchld_handler(int x);

char *remote_domain_name;	// guess what

int create_qrexec_socket(int domid, char *domname)
{
	char socket_address[40];
	char link_to_socket_name[strlen(domname) + sizeof(socket_address)];

	snprintf(socket_address, sizeof(socket_address),
		 QREXEC_DAEMON_SOCKET_DIR "/qrexec.%d", domid);
	snprintf(link_to_socket_name, sizeof link_to_socket_name,
		 QREXEC_DAEMON_SOCKET_DIR "/qrexec.%s", domname);
	unlink(link_to_socket_name);
	symlink(socket_address, link_to_socket_name);
	return get_server_socket(socket_address);
}

#define MAX_STARTUP_TIME_DEFAULT 60

/* ask on qrexec connect timeout */
int ask_on_connect_timeout(int xid, int timeout)
{
	char text[1024];
	int ret;
	snprintf(text, sizeof(text),
			"kdialog --title 'Qrexec daemon' --warningyesno "
			"'Timeout while trying connecting to qrexec agent (Xen domain ID: %d). Do you want to wait next %d seconds?'",
			xid, timeout);
	ret = system(text);
	ret = WEXITSTATUS(ret);
	//              fprintf(stderr, "ret=%d\n", ret);
	switch (ret) {
		case 1: /* NO */
			return 0;
		case 0: /*YES */
			return 1;
		default:
			// this can be the case at system startup (netvm), when Xorg isn't running yet
			// so just don't give possibility to extend the timeout
			return 0;
	}
}

/* do the preparatory tasks, needed before entering the main event loop */
void init(int xid)
{
	char qrexec_error_log_name[256];
	int logfd;
	int i;
	pid_t pid;
	int startup_timeout = MAX_STARTUP_TIME_DEFAULT;
	char *startup_timeout_str = NULL;

	if (xid <= 0) {
		fprintf(stderr, "domain id=0?\n");
		exit(1);
	}
	startup_timeout_str = getenv("QREXEC_STARTUP_TIMEOUT");
	if (startup_timeout_str) {
		startup_timeout = atoi(startup_timeout_str);
		if (startup_timeout == 0)
			// invalid number
			startup_timeout = MAX_STARTUP_TIME_DEFAULT;
	}
	signal(SIGUSR1, sigusr1_handler);
	switch (pid=fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		break;
	default:
		fprintf(stderr, "Waiting for VM's qrexec agent.");
		for (i=0;i<startup_timeout;i++) {
			sleep(1);
			fprintf(stderr, ".");
			if (i==startup_timeout-1) {
				if (ask_on_connect_timeout(xid, startup_timeout))
					i=0;
			}
		}
		fprintf(stderr, "Cannot connect to qrexec agent for %d seconds, giving up\n", startup_timeout);
		kill(pid, SIGTERM);
		exit(1);
	}
	close(0);
	snprintf(qrexec_error_log_name, sizeof(qrexec_error_log_name),
		 "/var/log/qubes/qrexec.%d.log", xid);
	umask(0007);		// make the log readable by the "qubes" group
	logfd =
	    open(qrexec_error_log_name, O_WRONLY | O_CREAT | O_TRUNC,
		 0640);

	if (logfd < 0) {
		perror("open");
		exit(1);
	}

	dup2(logfd, 1);
	dup2(logfd, 2);

	chdir("/var/run/qubes");
	if (setsid() < 0) {
		perror("setsid()");
		exit(1);
	}

	remote_domain_name = peer_client_init(xid, REXEC_PORT);
	setuid(getuid());
	/* When running as root, make the socket accessible; perms on /var/run/qubes still apply */
	umask(0);
	qrexec_daemon_unix_socket_fd =
	    create_qrexec_socket(xid, remote_domain_name);
	umask(0077);
	signal(SIGPIPE, SIG_IGN);
	signal(SIGCHLD, sigchld_handler);
	signal(SIGUSR1, SIG_DFL);
	kill(getppid(), SIGUSR1);	// let the parent know we are ready
}

void handle_new_client()
{
	int fd = do_accept(qrexec_daemon_unix_socket_fd);
	if (fd >= MAX_CLIENTS) {
		fprintf(stderr, "too many clients ?\n");
		exit(1);
	}
	clients[fd].state = CLIENT_CMDLINE;
	buffer_init(&clients[fd].buffer);
	if (fd > max_client_fd)
		max_client_fd = fd;
}

/* 
we need to track the number of children, so that excessive QREXEC_EXECUTE_*
commands do not fork-bomb dom0
*/
int children_count;

void terminate_client_and_flush_data(int fd)
{
	int i;
	struct server_header s_hdr;

	if (!(clients[fd].state & CLIENT_EXITED) && fork_and_flush_stdin(fd, &clients[fd].buffer))
		children_count++;
	close(fd);
	clients[fd].state = CLIENT_INVALID;
	buffer_free(&clients[fd].buffer);
	if (max_client_fd == fd) {
		for (i = fd; clients[i].state == CLIENT_INVALID && i >= 0;
		     i--);
		max_client_fd = i;
	}
	s_hdr.type = MSG_SERVER_TO_AGENT_CLIENT_END;
	s_hdr.client_id = fd;
	s_hdr.len = 0;
	write_all_vchan_ext(&s_hdr, sizeof(s_hdr));
}

int get_cmdline_body_from_client_and_pass_to_agent(int fd, struct server_header
						    *s_hdr)
{
	int len = s_hdr->len;
	char buf[len];
	int use_default_user = 0;
	if (!read_all(fd, buf, len)) {
		terminate_client_and_flush_data(fd);
		return 0;
	}
	if (!strncmp(buf, default_user_keyword, default_user_keyword_len_without_colon+1)) {
		use_default_user = 1;
		s_hdr->len -= default_user_keyword_len_without_colon; // -1 because of colon
		s_hdr->len += strlen(default_user);
	}
	write_all_vchan_ext(s_hdr, sizeof(*s_hdr));
	if (use_default_user) {
		write_all_vchan_ext(default_user, strlen(default_user));
		write_all_vchan_ext(buf+default_user_keyword_len_without_colon, len-default_user_keyword_len_without_colon);
	} else
		write_all_vchan_ext(buf, len);
	return 1;
}

void handle_cmdline_message_from_client(int fd)
{
	struct client_header hdr;
	struct server_header s_hdr;
	if (!read_all(fd, &hdr, sizeof hdr)) {
		terminate_client_and_flush_data(fd);
		return;
	}
	switch (hdr.type) {
	case MSG_CLIENT_TO_SERVER_EXEC_CMDLINE:
		s_hdr.type = MSG_SERVER_TO_AGENT_EXEC_CMDLINE;
		break;
	case MSG_CLIENT_TO_SERVER_JUST_EXEC:
		s_hdr.type = MSG_SERVER_TO_AGENT_JUST_EXEC;
		break;
	case MSG_CLIENT_TO_SERVER_CONNECT_EXISTING:
		s_hdr.type = MSG_SERVER_TO_AGENT_CONNECT_EXISTING;
		break;
	default:
		terminate_client_and_flush_data(fd);
		return;
	}

	s_hdr.client_id = fd;
	s_hdr.len = hdr.len;
	if (!get_cmdline_body_from_client_and_pass_to_agent(fd, &s_hdr))
		// client disconnected while sending cmdline, above call already
		// cleaned up client info
		return;
	clients[fd].state = CLIENT_DATA;
	set_nonblock(fd);	// so that we can detect full queue without blocking
	if (hdr.type == MSG_CLIENT_TO_SERVER_JUST_EXEC)
		terminate_client_and_flush_data(fd);

}

/* handle data received from one of qrexec_client processes */
void handle_message_from_client(int fd)
{
	struct server_header s_hdr;
	char buf[MAX_DATA_CHUNK];
	int len, ret;

	if (clients[fd].state == CLIENT_CMDLINE) {
		handle_cmdline_message_from_client(fd);
		return;
	}
	// We have already passed cmdline from client. 
	// Now the client passes us raw data from its stdin.
	len = buffer_space_vchan_ext();
	if (len <= sizeof s_hdr)
		return;
	/* Read at most the amount of data that we have room for in vchan */
	ret = read(fd, buf, len - sizeof(s_hdr));
	if (ret < 0) {
		perror("read client");
		terminate_client_and_flush_data(fd);
		return;
	}
	s_hdr.client_id = fd;
	s_hdr.len = ret;
	s_hdr.type = MSG_SERVER_TO_AGENT_INPUT;

	write_all_vchan_ext(&s_hdr, sizeof(s_hdr));
	write_all_vchan_ext(buf, ret);
	if (ret == 0)		// EOF - so don't select() on this client
		clients[fd].state |= CLIENT_DONT_READ | CLIENT_EOF;
	if (clients[fd].state & CLIENT_EXITED)
		//client already exited and all data sent - cleanup now
		terminate_client_and_flush_data(fd);
}

/* 
Called when there is buffered data for this client, and select() reports
that client's pipe is writable; so we should be able to flush some
buffered data.
*/
void write_buffered_data_to_client(int client_id)
{
	switch (flush_client_data
		(client_id, client_id, &clients[client_id].buffer)) {
	case WRITE_STDIN_OK:	// no more buffered data
		clients[client_id].state &= ~CLIENT_OUTQ_FULL;
		break;
	case WRITE_STDIN_ERROR:
		// do not write to this fd anymore
		clients[client_id].state |= CLIENT_EXITED;
		if (clients[client_id].state & CLIENT_EOF)
			terminate_client_and_flush_data(client_id);
		else
			// client will be removed when read returns 0 (EOF)
			// clear CLIENT_OUTQ_FULL flag to no select on this fd anymore
			clients[client_id].state &= ~CLIENT_OUTQ_FULL;
		break;
	case WRITE_STDIN_BUFFERED:	// no room for all data, don't clear CLIENT_OUTQ_FULL flag
		break;
	default:
		fprintf(stderr, "unknown flush_client_data?\n");
		exit(1);
	}
}

/* 
The header (hdr argument) is already built. Just read the raw data from
the packet, and pass it along with the header to the client.
*/
void get_packet_data_from_agent_and_pass_to_client(int client_id, struct client_header
						   *hdr)
{
	int len = hdr->len;
	char buf[sizeof(*hdr) + len];

	/* make both the header and data be consecutive in the buffer */
	*(struct client_header *) buf = *hdr;
	read_all_vchan_ext(buf + sizeof(*hdr), len);
	if (clients[client_id].state & CLIENT_EXITED)
		// ignore data for no longer running client
		return;

	switch (write_stdin
		(client_id, client_id, buf, len + sizeof(*hdr),
		 &clients[client_id].buffer)) {
	case WRITE_STDIN_OK:
		break;
	case WRITE_STDIN_BUFFERED:	// some data have been buffered
		clients[client_id].state |= CLIENT_OUTQ_FULL;
		break;
	case WRITE_STDIN_ERROR:
		// do not write to this fd anymore
		clients[client_id].state |= CLIENT_EXITED;
		// if already got EOF, remove client
		if (clients[client_id].state & CLIENT_EOF)
			terminate_client_and_flush_data(client_id);
		break;
	default:
		fprintf(stderr, "unknown write_stdin?\n");
		exit(1);
	}
}

/* 
The signal handler executes asynchronously; therefore all it should do is
to set a flag "signal has arrived", and let the main even loop react to this
flag in appropriate moment.
*/

int child_exited;

void sigchld_handler(int x)
{
	child_exited = 1;
	signal(SIGCHLD, sigchld_handler);
}

/* clean zombies, update children_count */
void reap_children()
{
	int status;
	while (waitpid(-1, &status, WNOHANG) > 0)
		children_count--;
	child_exited = 0;
}

/* too many children - wait for one of them to terminate */
void wait_for_child()
{
	int status;
	waitpid(-1, &status, 0);
	children_count--;
}

#define MAX_CHILDREN 10
void check_children_count_and_wait_if_too_many()
{
	if (children_count > MAX_CHILDREN) {
		fprintf(stderr,
			"max number of children reached, waiting for child exit...\n");
		wait_for_child();
		fprintf(stderr, "now children_count=%d, continuing.\n",
			children_count);
	}
}

void sanitize_name(char * untrusted_s_signed)
{
        unsigned char * untrusted_s;
        for (untrusted_s=(unsigned char*)untrusted_s_signed; *untrusted_s; untrusted_s++) {
                if (*untrusted_s >= 'a' && *untrusted_s <= 'z')
                        continue;
                if (*untrusted_s >= 'A' && *untrusted_s <= 'Z')
                        continue;
                if (*untrusted_s >= '0' && *untrusted_s <= '9')
                        continue;
                if (*untrusted_s == '$' || *untrusted_s == '_' || *untrusted_s == '-' || *untrusted_s == '.' || *untrusted_s == ' ')
                        continue;
                *untrusted_s = '_';
        }
}
                        


#define ENSURE_NULL_TERMINATED(x) x[sizeof(x)-1] = 0

/* 
Called when agent sends a message asking to execute a predefined command.
*/

void handle_execute_predefined_command()
{
	int i;
	struct trigger_connect_params untrusted_params, params;

	check_children_count_and_wait_if_too_many();
	read_all_vchan_ext(&untrusted_params, sizeof(params));

	/* sanitize start */
	ENSURE_NULL_TERMINATED(untrusted_params.exec_index);
	ENSURE_NULL_TERMINATED(untrusted_params.target_vmname);
	ENSURE_NULL_TERMINATED(untrusted_params.process_fds.ident);
	sanitize_name(untrusted_params.exec_index);
	sanitize_name(untrusted_params.target_vmname);
	sanitize_name(untrusted_params.process_fds.ident);
	params = untrusted_params;
	/* sanitize end */

	switch (fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		break;
	default:
		children_count++;
		return;
	}
	for (i = 3; i < MAX_FDS; i++)
		close(i);
	signal(SIGCHLD, SIG_DFL);
	signal(SIGPIPE, SIG_DFL);
	execl("/usr/lib/qubes/qrexec_policy", "qrexec_policy",
	      remote_domain_name, params.target_vmname,
	      params.exec_index, params.process_fds.ident, NULL);
	perror("execl");
	exit(1);
}

void check_client_id_in_range(unsigned int untrusted_client_id)
{
	if (untrusted_client_id >= MAX_CLIENTS || untrusted_client_id < 0) {
		fprintf(stderr, "from agent: client_id=%d\n",
			untrusted_client_id);
		exit(1);
	}
}


void sanitize_message_from_agent(struct server_header *untrusted_header)
{
	switch (untrusted_header->type) {
	case MSG_AGENT_TO_SERVER_TRIGGER_CONNECT_EXISTING:
		break;
	case MSG_AGENT_TO_SERVER_STDOUT:
	case MSG_AGENT_TO_SERVER_STDERR:
	case MSG_AGENT_TO_SERVER_EXIT_CODE:
		check_client_id_in_range(untrusted_header->client_id);
		if (untrusted_header->len > MAX_DATA_CHUNK
		    || untrusted_header->len < 0) {
			fprintf(stderr, "agent feeded %d of data bytes?\n",
				untrusted_header->len);
			exit(1);
		}
		break;

	case MSG_XOFF:
	case MSG_XON:
		check_client_id_in_range(untrusted_header->client_id);
		break;
	default:
		fprintf(stderr, "unknown mesage type %d from agent\n",
			untrusted_header->type);
		exit(1);
	}
}

void handle_message_from_agent()
{
	struct client_header hdr;
	struct server_header s_hdr, untrusted_s_hdr;

	read_all_vchan_ext(&untrusted_s_hdr, sizeof untrusted_s_hdr);
	/* sanitize start */
	sanitize_message_from_agent(&untrusted_s_hdr);
	s_hdr = untrusted_s_hdr;
	/* sanitize end */

//      fprintf(stderr, "got %x %x %x\n", s_hdr.type, s_hdr.client_id,
//              s_hdr.len);

	if (s_hdr.type == MSG_AGENT_TO_SERVER_TRIGGER_CONNECT_EXISTING) {
		handle_execute_predefined_command();
		return;
	}

	if (s_hdr.type == MSG_XOFF) {
		clients[s_hdr.client_id].state |= CLIENT_DONT_READ;
		return;
	}

	if (s_hdr.type == MSG_XON) {
		clients[s_hdr.client_id].state &= ~CLIENT_DONT_READ;
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
	default:		/* cannot happen, already sanitized */
		fprintf(stderr, "from agent: type=%d\n", s_hdr.type);
		exit(1);
	}
	hdr.len = s_hdr.len;
	if (clients[s_hdr.client_id].state == CLIENT_INVALID) {
		// benefit of doubt - maybe client exited earlier
		// just eat the packet data and continue
		char buf[MAX_DATA_CHUNK];
		read_all_vchan_ext(buf, s_hdr.len);
		return;
	}
	get_packet_data_from_agent_and_pass_to_client(s_hdr.client_id,
						      &hdr);
	if (s_hdr.type == MSG_AGENT_TO_SERVER_EXIT_CODE)
		terminate_client_and_flush_data(s_hdr.client_id);
}

/* 
Scan the "clients" table, add ones we want to read from (because the other 
end has not send MSG_XOFF on them) to read_fdset, add ones we want to write
to (because its pipe is full) to write_fdset. Return the highest used file 
descriptor number, needed for the first select() parameter.
*/
int fill_fdsets_for_select(fd_set * read_fdset, fd_set * write_fdset)
{
	int i;
	int max = -1;
	FD_ZERO(read_fdset);
	FD_ZERO(write_fdset);
	for (i = 0; i <= max_client_fd; i++) {
		if (clients[i].state != CLIENT_INVALID
		    && !(clients[i].state & CLIENT_DONT_READ)) {
			FD_SET(i, read_fdset);
			max = i;
		}
		if (clients[i].state != CLIENT_INVALID
		    && clients[i].state & CLIENT_OUTQ_FULL) {
			FD_SET(i, write_fdset);
			max = i;
		}
	}
	FD_SET(qrexec_daemon_unix_socket_fd, read_fdset);
	if (qrexec_daemon_unix_socket_fd > max)
		max = qrexec_daemon_unix_socket_fd;
	return max;
}

int main(int argc, char **argv)
{
	fd_set read_fdset, write_fdset;
	int i;
	int max;
	sigset_t chld_set;

	if (argc != 2 && argc != 3) {
		fprintf(stderr, "usage: %s domainid [default user]\n", argv[0]);
		exit(1);
	}
	if (argc == 3)
		default_user = argv[2];
	init(atoi(argv[1]));
	sigemptyset(&chld_set);
	sigaddset(&chld_set, SIGCHLD);
	/*
	   The main event loop. Waits for one of the following events:
	   - message from client
	   - message from agent
	   - new client
	   - child exited
	 */
	for (;;) {
		max = fill_fdsets_for_select(&read_fdset, &write_fdset);
		if (buffer_space_vchan_ext() <=
		    sizeof(struct server_header))
			FD_ZERO(&read_fdset);	// vchan full - don't read from clients

		sigprocmask(SIG_BLOCK, &chld_set, NULL);
		if (child_exited)
			reap_children();
		wait_for_vchan_or_argfd(max, &read_fdset, &write_fdset);
		sigprocmask(SIG_UNBLOCK, &chld_set, NULL);

		if (FD_ISSET(qrexec_daemon_unix_socket_fd, &read_fdset))
			handle_new_client();

		while (read_ready_vchan_ext())
			handle_message_from_agent();

		for (i = 0; i <= max_client_fd; i++)
			if (clients[i].state != CLIENT_INVALID
			    && FD_ISSET(i, &read_fdset))
				handle_message_from_client(i);

		for (i = 0; i <= max_client_fd; i++)
			if (clients[i].state != CLIENT_INVALID
			    && FD_ISSET(i, &write_fdset))
				write_buffered_data_to_client(i);

	}
}
