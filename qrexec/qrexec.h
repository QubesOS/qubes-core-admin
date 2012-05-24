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

/* See also http://wiki.qubes-os.org/trac/wiki/Qrexec */

#define QREXEC_DAEMON_SOCKET_DIR "/var/run/qubes"
#define MAX_FDS 256
#define MAX_DATA_CHUNK 4096

#define REXEC_PORT 512

#define QREXEC_AGENT_TRIGGER_PATH "/var/run/qubes/qrexec_agent"
#define QREXEC_AGENT_FDPASS_PATH "/var/run/qubes/qrexec_agent_fdpass"
#define MEMINFO_WRITER_PIDFILE "/var/run/meminfo-writer.pid"

enum {
	/* messages from qrexec_client to qrexec_daemon (both in dom0) */
	/* start process in VM and pass its stdin/out/err to dom0 */
	MSG_CLIENT_TO_SERVER_EXEC_CMDLINE = 0x100,
	/* start process in VM discarding its stdin/out/err (connect to /dev/null) */
	MSG_CLIENT_TO_SERVER_JUST_EXEC,
	/* connect to existing process in VM to receive its stdin/out/err 
	 * struct connect_existing_params passed as data */
	MSG_CLIENT_TO_SERVER_CONNECT_EXISTING,

	/* messages qrexec_daemon(dom0)->qrexec_agent(VM) */
	/* same as MSG_CLIENT_TO_SERVER_CONNECT_EXISTING */
	MSG_SERVER_TO_AGENT_CONNECT_EXISTING,
	/* same as MSG_CLIENT_TO_SERVER_EXEC_CMDLINE */
	MSG_SERVER_TO_AGENT_EXEC_CMDLINE,
	/* same as MSG_CLIENT_TO_SERVER_JUST_EXEC */
	MSG_SERVER_TO_AGENT_JUST_EXEC,
	/* pass data to process stdin */
	MSG_SERVER_TO_AGENT_INPUT,
	/* detach from process; qrexec_agent should close pipes to process
	 * stdin/out/err; it's up to the VM child process if it cause its termination */
	MSG_SERVER_TO_AGENT_CLIENT_END,

	/* flow control, qrexec_daemon->qrexec_agent */
	/* suspend reading of named fd from child process */
	MSG_XOFF,
	/* resume reading of named fd from child process */
	MSG_XON,

	/* messages qrexec_agent(VM)->qrexec_daemon(dom0) */
	/* pass data from process stdout */
	MSG_AGENT_TO_SERVER_STDOUT,
	/* pass data from process stderr */
	MSG_AGENT_TO_SERVER_STDERR,
	/* inform that process terminated and pass its exit code; this should be
	 * send after all data from stdout/err are send */
	MSG_AGENT_TO_SERVER_EXIT_CODE,
	/* call Qubes RPC service
	 * struct trigger_connect_params passed as data */
	MSG_AGENT_TO_SERVER_TRIGGER_CONNECT_EXISTING,

	/* messages qrexec_daemon->qrexec_client (both in dom0) */
	/* same as MSG_AGENT_TO_SERVER_STDOUT */
	MSG_SERVER_TO_CLIENT_STDOUT,
	/* same as MSG_AGENT_TO_SERVER_STDERR */
	MSG_SERVER_TO_CLIENT_STDERR,
	/* same as MSG_AGENT_TO_SERVER_EXIT_CODE */
	MSG_SERVER_TO_CLIENT_EXIT_CODE
};

struct server_header {
	unsigned int type;
	unsigned int client_id;
	unsigned int len;
};

struct client_header {
	unsigned int type;
	unsigned int len;
};

struct connect_existing_params {
	char ident[32];
};

struct trigger_connect_params {
	char exec_index[64];
	char target_vmname[32];
	struct connect_existing_params process_fds;
};
