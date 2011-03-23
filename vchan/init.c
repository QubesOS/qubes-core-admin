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

#include <sys/mman.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <malloc.h>
#include <xs.h>
#include <string.h>
#include <xenctrl.h>
#include <unistd.h>
#include <stdlib.h>
#include "libvchan.h"
#include "../u2mfn/u2mfnlib.h"

static int ring_init(struct libvchan *ctrl)
{
	int u2mfn = open("/proc/u2mfn", O_RDONLY);
	int mfn;
	struct vchan_interface *ring;
	ring = (struct vchan_interface *) u2mfn_alloc_kpage ();
        
	if (ring == MAP_FAILED)
		return -1;

	ctrl->ring = ring;
	if (u2mfn_get_last_mfn (&mfn) < 0)
		return -1;

	ctrl->ring_ref = mfn;
	close(u2mfn);
	ring->cons_in = ring->prod_in = ring->cons_out = ring->prod_out =
	    0;
	ring->server_closed = ring->client_closed = 0;
	ring->debug = 0xaabbccdd;
	return 0;
}
/**
        creates event channel;
        creates "ring-ref" and "event-channel" xenstore entries;
        waits for connection to event channel from the peer
*/
static int server_interface_init(struct libvchan *ctrl, int devno)
{
	int ret = -1;
	struct xs_handle *xs;
	char buf[64];
	char ref[16];
	int evfd;
	evtchn_port_or_error_t port;
	xs = xs_domain_open();
	if (!xs) {
		return ret;
	}
	evfd = xc_evtchn_open();
	if (evfd < 0)
		goto fail;
	ctrl->evfd = evfd;
	// the following hardcoded 0 is the peer domain id
	port = xc_evtchn_bind_unbound_port(evfd, 0);	
	if (port < 0)
		goto fail2;
	ctrl->evport = port;
	snprintf(ref, sizeof ref, "%d", ctrl->ring_ref);
	snprintf(buf, sizeof buf, "device/vchan/%d/ring-ref", devno);
	if (!xs_write(xs, 0, buf, ref, strlen(ref)))
		goto fail2;
	snprintf(ref, sizeof ref, "%d", ctrl->evport);
	snprintf(buf, sizeof buf, "device/vchan/%d/event-channel", devno);
	if (!xs_write(xs, 0, buf, ref, strlen(ref)))
		goto fail2;
        // wait for the peer to arrive
	if (xc_evtchn_pending(evfd) == -1)
		goto fail2;
        xc_evtchn_unmask(ctrl->evfd, ctrl->evport);
	snprintf(buf, sizeof buf, "device/vchan/%d", devno);
	xs_rm(xs, 0, buf);

	ret = 0;
      fail2:
	if (ret)
		close(evfd);
      fail:
	xs_daemon_close(xs);
	return ret;
}

#define dir_select(dir1, dir2) \
        ctrl->wr_cons = &ctrl->ring->cons_##dir1; \
        ctrl->wr_prod = &ctrl->ring->prod_##dir1; \
        ctrl->rd_cons = &ctrl->ring->cons_##dir2; \
        ctrl->rd_prod = &ctrl->ring->prod_##dir2; \
        ctrl->wr_ring = ctrl->ring->buf_##dir1; \
        ctrl->rd_ring = ctrl->ring->buf_##dir2; \
        ctrl->wr_ring_size = sizeof(ctrl->ring->buf_##dir1); \
        ctrl->rd_ring_size = sizeof(ctrl->ring->buf_##dir2)

/**
        Run in AppVM (any domain). 
        Sleeps until the connection is established.
        \param devno something like a well-known port.
        \returns NULL on failure, handle on success
*/
struct libvchan *libvchan_server_init(int devno)
{
	struct libvchan *ctrl =
	    (struct libvchan *) malloc(sizeof(struct libvchan));
	if (!ctrl)
		return 0;
	if (ring_init(ctrl))
		return 0;;
	if (server_interface_init(ctrl, devno))
		return 0;
/*
        We want the same code for read/write functions, regardless whether
        we are client, or server. Thus, we do not access buf_in nor buf_out
        buffers directly. Instead, in *_init functions, the dir_select
        macro assigns proper values to wr* and rd* pointers, so that they
        point to correct one out of buf_in or buf_out related fields.
*/
	dir_select(in, out);
	ctrl->is_server = 1;
	return ctrl;
}

/**
        retrieves ring-ref and event-channel numbers from xenstore (if
        they don't exist, return error, because nobody seems to listen);
        map the ring, connect the event channel
*/
static int client_interface_init(struct libvchan *ctrl, int domain, int devno)
{
	int ret = -1;
	unsigned int len;
	struct xs_handle *xs;
	int xcfd;
	char buf[64];
	char *ref;
	int evfd;
	int remote_port;
	xs = xs_daemon_open();
	if (!xs) {
		return ret;
	}
	snprintf(buf, sizeof buf,
		 "/local/domain/%d/device/vchan/%d/ring-ref", domain,
		 devno);
	ref = xs_read(xs, 0, buf, &len);
	if (!ref)
		goto fail;
	ctrl->ring_ref = atoi(ref);
	if (!ctrl->ring_ref)
		goto fail;
	free(ref);
	snprintf(buf, sizeof buf,
		 "/local/domain/%d/device/vchan/%d/event-channel", domain,
		 devno);
	ref = xs_read(xs, 0, buf, &len);
	if (!ref)
		goto fail;
	remote_port = atoi(ref);
	if (!remote_port)
		goto fail;
	free(ref);
	xcfd = xc_interface_open();
	if (xcfd < 0)
		goto fail;
	ctrl->ring = (struct vchan_interface *)
	    xc_map_foreign_range(xcfd, domain, 4096,
				 PROT_READ | PROT_WRITE, ctrl->ring_ref);
	close(xcfd);
	if (ctrl->ring == 0 || ctrl->ring == MAP_FAILED)
		goto fail;
	evfd = xc_evtchn_open();
	if (evfd < 0)
		goto fail;
	ctrl->evfd = evfd;
	ctrl->evport =
	    xc_evtchn_bind_interdomain(evfd, domain, remote_port);
	if (ctrl->evport < 0 || xc_evtchn_notify(evfd, ctrl->evport))
		close(evfd);
	else
		ret = 0;
      fail:
	xs_daemon_close(xs);
	return ret;
}

/**
        Run on the client side of connection (currently, must be dom0).
        \returns NULL on failure (e.g. noone listening), handle on success
*/        
struct libvchan *libvchan_client_init(int domain, int devno)
{
	struct libvchan *ctrl =
	    (struct libvchan *) malloc(sizeof(struct libvchan));
	if (!ctrl)
		return 0;
	if (client_interface_init(ctrl, domain, devno))
		return 0;
//      See comment in libvchan_server_init
	dir_select(out, in);
	ctrl->is_server = 0;
	return ctrl;
}
