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

#include "libvchan.h"
#include <xenctrl.h>
#include <string.h>
#include <errno.h>
#include <sys/select.h>
/**
        \return How much data is immediately available for reading
*/
int libvchan_data_ready(struct libvchan *ctrl)
{
	return *ctrl->rd_prod - *ctrl->rd_cons;
}

/**
        \return How much space is available for writing, without blocking
*/
int libvchan_buffer_space(struct libvchan *ctrl)
{
	return ctrl->wr_ring_size - (*ctrl->wr_prod - *ctrl->wr_cons);
}

static int do_notify(struct libvchan *ctrl)
{
	return xc_evtchn_notify(ctrl->evfd, ctrl->evport);
}

/// returns nonzero if the peer has closed connection 
int libvchan_is_eof(struct libvchan *ctrl)
{
	if (ctrl->is_server) {
		if (ctrl->ring->client_closed)
			return -1;
	} else {
		if (ctrl->ring->server_closed) {
			ctrl->ring->client_closed = 1;
			do_notify(ctrl);
			return -1;
		}

	}
	return 0;
}

/// waits for the peer to do any action
/**
        \return -1 return value means peer has closed
*/
int libvchan_wait(struct libvchan *ctrl)
{
	int ret;
#ifndef CONFIG_STUBDOM
	ret = xc_evtchn_pending(ctrl->evfd);
#else
	int vchan_fd = libvchan_fd_for_select(ctrl);
	fd_set rfds;

	libvchan_prepare_to_select(ctrl);
	while ((ret = xc_evtchn_pending(ctrl->evfd)) < 0) {
        FD_ZERO(&rfds);
        FD_SET(0, &rfds);
        FD_SET(vchan_fd, &rfds);
        ret = select(vchan_fd + 1, &rfds, NULL, NULL, NULL);
        if (ret < 0 && errno != EINTR) {
            perror("select");
			return ret;
        }
	}
#endif
	if (ret!=-1 && xc_evtchn_unmask(ctrl->evfd, ctrl->evport))
		return -1;
	if (ret!=-1 && libvchan_is_eof(ctrl))
		return -1;
	return ret;
}

/**
        may sleep (only if no buffer space available);
        may write less data than requested;
        returns the amount of data processed, -1 on error or peer close
*/        
int libvchan_write(struct libvchan *ctrl, char *data, int size)
{
	int avail, avail_contig;
	int real_idx;
	while ((avail = libvchan_buffer_space(ctrl)) == 0)
		if (libvchan_wait(ctrl) < 0)
			return -1;
	if (avail > size)
		avail = size;
	real_idx = (*ctrl->wr_prod) & (ctrl->wr_ring_size - 1);
	avail_contig = ctrl->wr_ring_size - real_idx;
	if (avail_contig < avail)
		avail = avail_contig;
	memcpy(ctrl->wr_ring + real_idx, data, avail);
	*ctrl->wr_prod += avail;
	if (do_notify(ctrl) < 0)
		return -1;
	return avail;
}

/**
        may sleep (only if no data is available for reading);
        may return less data than requested;
        returns the amount of data processed, -1 on error or peer close
*/        
int libvchan_read(struct libvchan *ctrl, char *data, int size)
{
	int avail, avail_contig;
	int real_idx;
	while ((avail = libvchan_data_ready(ctrl)) == 0)
		if (libvchan_wait(ctrl) < 0)
			return -1;
	if (avail > size)
		avail = size;
	real_idx = (*ctrl->rd_cons) & (ctrl->rd_ring_size - 1);
	avail_contig = ctrl->rd_ring_size - real_idx;
	if (avail_contig < avail)
		avail = avail_contig;
	memcpy(data, ctrl->rd_ring + real_idx, avail);
	*ctrl->rd_cons += avail;
	if (do_notify(ctrl) < 0)
		return -1;
	return avail;
}

/**
        Wait fot the writes to finish, then notify the peer of closing
        On server side, it waits for the peer to acknowledge
*/
int libvchan_close(struct libvchan *ctrl)
{
	while (*ctrl->wr_prod != *ctrl->wr_cons)
		if (libvchan_wait(ctrl) < 0)
			return -1;
	if (ctrl->is_server) {
		ctrl->ring->server_closed = 1;
		do_notify(ctrl);
		while (!ctrl->ring->client_closed
		       && libvchan_wait(ctrl) == 0);
	} else {
		ctrl->ring->client_closed = 1;
		do_notify(ctrl);
	}
	return 0;
}

/// The fd to use for select() set
int libvchan_fd_for_select(struct libvchan *ctrl)
{
	return xc_evtchn_fd(ctrl->evfd);
}

/// Unmasks event channel; must be called before calling select(), and only then
void libvchan_prepare_to_select(struct libvchan *ctrl)
{
	xc_evtchn_unmask(ctrl->evfd, ctrl->evport);
}
