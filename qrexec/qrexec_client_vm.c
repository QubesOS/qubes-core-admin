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
#include <sys/socket.h>
#include <sys/un.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include "qrexec.h"
int connect_unix_socket()
{
	int s, len;
	struct sockaddr_un remote;

	if ((s = socket(AF_UNIX, SOCK_STREAM, 0)) == -1) {
		perror("socket");
		return -1;
	}

	remote.sun_family = AF_UNIX;
	strncpy(remote.sun_path, QREXEC_AGENT_FDPASS_PATH,
		sizeof(remote.sun_path));
	len = strlen(remote.sun_path) + sizeof(remote.sun_family);
	if (connect(s, (struct sockaddr *) &remote, len) == -1) {
		perror("connect");
		exit(1);
	}
	return s;
}

char *get_program_name(char *prog)
{
	char *basename = rindex(prog, '/');
	if (basename)
		return basename + 1;
	else
		return prog;
}

int main(int argc, char **argv)
{
	int trigger_fd;
	struct trigger_connect_params params;
	int local_fd[3], remote_fd[3];
	int i;

	if (argc < 4) {
		fprintf(stderr,
			"usage: %s local_program target_vmname program_ident [local program arguments]\n",
			argv[0]);
		exit(1);
	}

	trigger_fd = open(QREXEC_AGENT_TRIGGER_PATH, O_WRONLY);
	if (trigger_fd < 0) {
		perror("open QREXEC_AGENT_TRIGGER_PATH");
		exit(1);
	}

	for (i = 0; i < 3; i++) {
		local_fd[i] = connect_unix_socket();
		read(local_fd[i], &remote_fd[i], sizeof(remote_fd[i]));
		if (i != 2 || getenv("PASS_LOCAL_STDERR")) {
		        char * env;
		        asprintf(&env, "SAVED_FD_%d=%d", i, dup(i));
		        putenv(env);	
			dup2(local_fd[i], i);
			close(local_fd[i]);
		}
	}
	
	memset(&params, 0, sizeof(params));
	strncpy(params.exec_index, argv[3], sizeof(params.exec_index));
	strncpy(params.target_vmname, argv[2],
		sizeof(params.target_vmname));
	snprintf(params.process_fds.ident,
		 sizeof(params.process_fds.ident), "%d %d %d",
		 remote_fd[0], remote_fd[1], remote_fd[2]);

	write(trigger_fd, &params, sizeof(params));
	close(trigger_fd);

	argv[3] = get_program_name(argv[1]);
	execv(argv[1], argv + 3);
	perror("execv");
	return 1;
}
