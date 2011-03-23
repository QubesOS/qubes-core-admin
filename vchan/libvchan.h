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

#include <stdint.h>
typedef uint32_t VCHAN_RING_IDX;

/// struct vchan_interface is placed in memory shared between domains
struct vchan_interface {
        // One buffer for each data direction
	char buf_in[1024];
	char buf_out[2048];
	// standard consumer/producer interface, one pair per buffer	
	VCHAN_RING_IDX cons_in, prod_in, cons_out, prod_out;
	uint32_t debug;
	int client_closed, server_closed;
};
/// struct libvchan is a control structure, passed to all library calls
struct libvchan {
	struct vchan_interface *ring;
	uint32_t ring_ref;
	/// descriptor to event channel interface
	int evfd;
	int evport;
	VCHAN_RING_IDX *wr_cons, *wr_prod, *rd_cons, *rd_prod;
	char *rd_ring, *wr_ring;
	int rd_ring_size, wr_ring_size;
	int is_server;
};

struct libvchan *libvchan_server_init(int devno);

struct libvchan *libvchan_client_init(int domain, int devno);

int libvchan_write(struct libvchan *ctrl, char *data, int size);
int libvchan_read(struct libvchan *ctrl, char *data, int size);
int libvchan_wait(struct libvchan *ctrl);
int libvchan_close(struct libvchan *ctrl);
void libvchan_prepare_to_select(struct libvchan *ctrl);
int libvchan_fd_for_select(struct libvchan *ctrl);
int libvchan_is_eof(struct libvchan *ctrl);
int libvchan_data_ready(struct libvchan *ctrl);
int libvchan_buffer_space(struct libvchan *ctrl);
