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

#define QREXEC_DAEMON_SOCKET_DIR "/var/run/qubes"
#define MAX_FDS 256
#define MAX_DATA_CHUNK 4096

#define REXEC_PORT 512

#define QREXEC_AGENT_TRIGGER_PATH "/var/run/qubes/qrexec_agent"
#define QREXEC_AGENT_FDPASS_PATH "/var/run/qubes/qrexec_agent_fdpass"
#define MEMINFO_WRITER_PIDFILE "/var/run/meminfo-writer.pid"

enum {
	MSG_CLIENT_TO_SERVER_EXEC_CMDLINE = 0x100,
	MSG_CLIENT_TO_SERVER_JUST_EXEC,
	MSG_CLIENT_TO_SERVER_CONNECT_EXISTING,

	MSG_SERVER_TO_AGENT_CONNECT_EXISTING,
	MSG_SERVER_TO_AGENT_EXEC_CMDLINE,
	MSG_SERVER_TO_AGENT_JUST_EXEC,
	MSG_SERVER_TO_AGENT_INPUT,
	MSG_SERVER_TO_AGENT_CLIENT_END,

	MSG_XOFF,
	MSG_XON,

	MSG_AGENT_TO_SERVER_STDOUT,
	MSG_AGENT_TO_SERVER_STDERR,
	MSG_AGENT_TO_SERVER_EXIT_CODE,
	MSG_AGENT_TO_SERVER_TRIGGER_CONNECT_EXISTING,

	MSG_SERVER_TO_CLIENT_STDOUT,
	MSG_SERVER_TO_CLIENT_STDERR,
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
