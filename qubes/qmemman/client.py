# pylint: skip-file

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

import socket
import fcntl

class QMemmanClient:
    def request_memory(self, amount):
        self.sock = socket.socket(socket.AF_UNIX)

        flags = fcntl.fcntl(self.sock.fileno(), fcntl.F_GETFD)
        flags |= fcntl.FD_CLOEXEC
        fcntl.fcntl(self.sock.fileno(), fcntl.F_SETFD, flags)

        self.sock.connect("/var/run/qubes/qmemman.sock")
        self.sock.send(str(int(amount)).encode('ascii')+b"\n")
        received = self.sock.recv(1024).strip()
        if received == b'OK':
            return True
        else:
            return False

    def close(self):
        self.sock.close()
