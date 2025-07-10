#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010  Rafal Wojtczuk  <rafal@invisiblethingslab.com>
# Copyright (C) 2022  Marek Marczykowski-Górecki
#                           <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.

from typing import Optional


class DomainState:  # pylint: disable=too-few-public-methods
    def __init__(self, domid) -> None:
        # Current memory size.
        self.mem_current: int = 0
        # Current memory allocation (what VM is using or can use at any time).
        self.mem_actual: Optional[int] = None
        # Maximum memory size.
        self.mem_max: Optional[int] = None
        # Used memory, computed based on meminfo.
        self.mem_used: Optional[int] = None
        # Domain ID.
        self.domid: str = domid
        # Last memset target.
        self.last_target: int = 0
        # Use memory hotplug for mem-set.
        self.use_hotplug: bool = False
        # No reaction to memset.
        self.no_progress: bool = False
        # Slow react to memset (after few tries still above target).
        self.slow_memset_react: bool = False

    def __repr__(self) -> str:
        return self.__dict__.__repr__()
