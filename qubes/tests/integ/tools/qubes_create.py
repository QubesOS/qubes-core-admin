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

import qubes
import qubes.tools.qubes_create

import qubes.tests

@qubes.tests.skipUnlessDom0
class TC_00_qubes_create(qubes.tests.SystemTestCase):
    def test_000_basic(self):
        self.assertEqual(0, qubes.tools.qubes_create.main([
            '--qubesxml', qubes.tests.XMLPATH]))

    def test_001_property(self):
        self.assertEqual(0, qubes.tools.qubes_create.main([
            '--qubesxml', qubes.tests.XMLPATH,
            '--property', 'default_kernel=testkernel']))

        self.assertEqual('testkernel',
            qubes.Qubes(qubes.tests.XMLPATH).default_kernel)
