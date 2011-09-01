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

#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <libvchan.h>
#include <xs.h>
#include <xenctrl.h>

static struct libvchan *ctrl;
static int is_server;
int write_all_vchan_ext(void *buf, int size)
{
	int written = 0;
	int ret;

	while (written < size) {
		ret =
		    libvchan_write(ctrl, (char *) buf + written,
				   size - written);
		if (ret <= 0) {
			perror("write");
			exit(1);
		}
		written += ret;
	}
//      fprintf(stderr, "sent %d bytes\n", size);
	return size;
}


int read_all_vchan_ext(void *buf, int size)
{
	int written = 0;
	int ret;
	while (written < size) {
		ret =
		    libvchan_read(ctrl, (char *) buf + written,
				  size - written);
		if (ret == 0) {
			fprintf(stderr, "EOF\n");
			exit(1);
		}
		if (ret < 0) {
			perror("read");
			exit(1);
		}
		written += ret;
	}
//      fprintf(stderr, "read %d bytes\n", size);
	return size;
}

int read_ready_vchan_ext()
{
	return libvchan_data_ready(ctrl);
}

int buffer_space_vchan_ext()
{
	return libvchan_buffer_space(ctrl);
}

// if the remote domain is destroyed, we get no notification
// thus, we check for the status periodically

#ifdef XENCTRL_HAS_XC_INTERFACE
static xc_interface *xc_handle = NULL;
#else
static int xc_handle = -1;
#endif
void slow_check_for_libvchan_is_eof(struct libvchan *ctrl)
{
	struct evtchn_status evst;
	evst.port = ctrl->evport;
	evst.dom = DOMID_SELF;
	if (xc_evtchn_status(xc_handle, &evst)) {
		perror("xc_evtchn_status");
		exit(1);
	}
	if (evst.status != EVTCHNSTAT_interdomain) {
		fprintf(stderr, "event channel disconnected\n");
		exit(0);
	}
}


int wait_for_vchan_or_argfd_once(int max, fd_set * rdset, fd_set * wrset)
{
	int vfd, ret;
	struct timespec tv = { 1, 100000000 };
	sigset_t empty_set;

	sigemptyset(&empty_set);

	vfd = libvchan_fd_for_select(ctrl);
	FD_SET(vfd, rdset);
	if (vfd > max)
		max = vfd;
	max++;
	ret = pselect(max, rdset, wrset, NULL, &tv, &empty_set);
	if (ret < 0) {
		if (errno != EINTR) {
			perror("select");
			exit(1);
		} else {
			FD_ZERO(rdset);
			FD_ZERO(wrset);
			fprintf(stderr, "eintr\n");
			return 1;
		}

	}
	if (libvchan_is_eof(ctrl)) {
		fprintf(stderr, "libvchan_is_eof\n");
		exit(0);
	}
	if (!is_server && ret == 0)
		slow_check_for_libvchan_is_eof(ctrl);
	if (FD_ISSET(vfd, rdset))
		// the following will never block; we need to do this to
		// clear libvchan_fd pending state 
		libvchan_wait(ctrl);
	return ret;
}

void wait_for_vchan_or_argfd(int max, fd_set * rdset, fd_set * wrset)
{
	fd_set r = *rdset, w = *wrset;
	do {
		*rdset = r;
		*wrset = w;
	}
	while (wait_for_vchan_or_argfd_once(max, rdset, wrset) == 0);
}

int peer_server_init(int port)
{
	is_server = 1;
	ctrl = libvchan_server_init(port);
	if (!ctrl) {
		perror("libvchan_server_init");
		exit(1);
	}
	return 0;
}

char *peer_client_init(int dom, int port)
{
	struct xs_handle *xs;
	char buf[64];
	char *name;
	char *dummy;
	unsigned int len = 0;
	char devbuf[128];
	unsigned int count;
	char **vec;

//      double_buffered = 1; // writes to vchan are buffered, nonblocking
//      double_buffer_init();
	xs = xs_daemon_open();
	if (!xs) {
		perror("xs_daemon_open");
		exit(1);
	}
	snprintf(buf, sizeof(buf), "/local/domain/%d/name", dom);
	name = xs_read(xs, 0, buf, &len);
	if (!name) {
		perror("xs_read domainname");
		exit(1);
	}
	snprintf(devbuf, sizeof(devbuf),
		 "/local/domain/%d/device/vchan/%d/event-channel", dom,
		 port);
	xs_watch(xs, devbuf, devbuf);
	do {
		vec = xs_read_watch(xs, &count);
		if (vec)
			free(vec);
		len = 0;
		dummy = xs_read(xs, 0, devbuf, &len);
	}
	while (!dummy || !len);	// wait for the server to create xenstore entries
	free(dummy);
	xs_daemon_close(xs);

	// now client init should succeed; "while" is redundant
	while (!(ctrl = libvchan_client_init(dom, port)));

#ifdef XENCTRL_HAS_XC_INTERFACE
	xc_handle = xc_interface_open(NULL, 0, 0);
	if (!xc_handle) {
#else
	xc_handle = xc_interface_open();
	if (xc_handle < 0) {
#endif
		perror("xc_interface_open");
		exit(1);
	}
	return name;
}
