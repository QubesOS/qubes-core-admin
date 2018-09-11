#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''qubes-create - Create new Qubes OS store'''

import sys
import qubes
import qubes.tools

parser = qubes.tools.QubesArgumentParser(
    description='Create new Qubes OS store.',
    want_app=True,
    want_app_no_instance=True)

def main(args=None):
    '''Main routine of :program:`qubes-create`.

    :param list args: Optional arguments to override those delivered from \
        command line.
    '''

    args = parser.parse_args(args)
    qubes.Qubes.create_empty_store(args.app,
        offline_mode=args.offline_mode).setup_pools()
    return 0


if __name__ == '__main__':
    sys.exit(main())
