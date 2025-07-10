#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

import socket
import fcntl
from typing import Optional


class QMemmanClient:
    def __init__(self) -> None:
        self.sock: Optional[socket.socket] = None

    def request_mem(self, amount) -> bool:
        self.sock = socket.socket(socket.AF_UNIX)
        flags = fcntl.fcntl(self.sock.fileno(), fcntl.F_GETFD)
        flags |= fcntl.FD_CLOEXEC
        fcntl.fcntl(self.sock.fileno(), fcntl.F_SETFD, flags)
        self.sock.connect("/var/run/qubes/qmemman.sock")
        self.sock.send(str(int(amount)).encode("ascii") + b"\n")
        received = self.sock.recv(1024).strip()
        return bool(received == b"OK")

    def close(self) -> None:
        assert isinstance(self.sock, socket.socket)
        self.sock.close()
