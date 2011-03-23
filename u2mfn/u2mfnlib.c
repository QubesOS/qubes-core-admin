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
#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdlib.h>
#include "u2mfn-kernel.h"


static int u2mfn_fd = -1;

static int get_fd()
{
	if (u2mfn_fd == -1) {
		u2mfn_fd = open("/proc/u2mfn", O_RDWR);
		if (u2mfn_fd < 0)
			return -1;
	}
	return 0;
}

int u2mfn_get_mfn_for_page(long va, int *mfn)
{
	if (get_fd())
		return -1;
	*mfn = ioctl(u2mfn_fd, U2MFN_GET_MFN_FOR_PAGE, va);
	if (*mfn == -1)
		return -1;

	return 0;
}

int u2mfn_get_last_mfn(int *mfn)
{
	if (get_fd())
		return -1;

	*mfn = ioctl(u2mfn_fd, U2MFN_GET_LAST_MFN, 0);
	if (*mfn == -1)
		return -1;

	return 0;
}



char *u2mfn_alloc_kpage()
{
	char *ret;
	if (get_fd())
		return MAP_FAILED;
	ret =
	    mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, u2mfn_fd, 0);
	return ret;
}
