#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

CC=gcc
CFLAGS=-g -Wall -I../u2mfn
all: libvchan.so

libvchan.so : init.o io.o
	gcc -shared -o libvchan.so init.o io.o -L ../u2mfn -lu2mfn
init.o: init.c
	gcc -fPIC -Wall -g -c init.c
io.o: io.c
	gcc -fPIC -Wall -g -c io.c
node:	node.o libvchan.so
	gcc -g -o node node.o -L. -lvchan -lxenctrl -lxenstore
node-select:	node-select.o libvchan.so
	gcc -g -o node-select node-select.o -L. -lvchan -lxenctrl -lxenstore
clean:
	rm -f *.o *so *~ client server node node-select
	
		
