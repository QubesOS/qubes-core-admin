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


class DomainState:  # pylint: disable=too-few-public-methods
    def __init__(self, domid):
        self.mem_current = 0  # the current memory size
        self.mem_actual = None  # the current memory allocation (what VM
        # is using or can use at any time)
        self.mem_max = None  # the maximum memory size
        self.mem_used = None  # used memory, computed based on meminfo
        self.domid = domid  # domain id
        self.last_target = 0  # the last memset target
        self.use_hotplug = False  # use memory hotplug for mem-set
        self.no_progress = False  # no react to memset
        self.slow_memset_react = False  # slow react to memset (after few
        # tries still above target)

    def __repr__(self):
        return self.__dict__.__repr__()
