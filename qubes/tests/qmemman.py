#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2022 Marek Marczykowski-Górecki
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
import unittest.mock

import qubes.qmemman.domainstate
import qubes.qmemman.algo

import qubes.tests


def in_megabyte(val):
    return int(val * 1024 * 1024)


def construct_dominfo(
    domid,
    mem_used=None,
    mem_max=None,
    mem_actual=None,
    mem_current=0,
    last_target=0,
    use_hotplug=False,
):
    dom = qubes.qmemman.domainstate.DomainState(domid)
    dom.mem_used = mem_used
    dom.mem_max = mem_max
    dom.mem_actual = mem_actual
    dom.mem_current = mem_current
    dom.last_target = last_target
    dom.use_hotplug = use_hotplug
    return dom


class TC_00_Qmemman_algo(qubes.tests.QubesTestCase):
    def test_000_meminfo(self):
        self.assertEqual(
            qubes.qmemman.algo.sanitize_and_parse_meminfo(b"4096"), 4096 * 1024
        )
        self.assertIsNone(qubes.qmemman.algo.sanitize_and_parse_meminfo(b""))
        self.assertIsNone(
            qubes.qmemman.algo.sanitize_and_parse_meminfo(b"a4096")
        )
        self.assertIsNone(
            qubes.qmemman.algo.sanitize_and_parse_meminfo(b"4096a")
        )
        self.assertIsNone(
            qubes.qmemman.algo.sanitize_and_parse_meminfo(b"4096 1024")
        )
        self.assertIsNone(
            qubes.qmemman.algo.sanitize_and_parse_meminfo(b"4096\n1024")
        )

    def test_010_pref_mem_dom0(self):
        dom = qubes.qmemman.domainstate.DomainState("0")
        dom.mem_used = in_megabyte(1024)
        dom.mem_max = in_megabyte(4096)
        self.assertEqual(qubes.qmemman.algo.pref_mem(dom), in_megabyte(1681.2))
        dom.mem_used = in_megabyte(5000)
        self.assertEqual(qubes.qmemman.algo.pref_mem(dom), in_megabyte(4096))

    def test_011_pref_mem_domU(self):  # pylint: disable=invalid-name
        dom = qubes.qmemman.domainstate.DomainState("10")
        dom.mem_used = in_megabyte(1024)
        dom.mem_max = in_megabyte(4096)
        self.assertEqual(qubes.qmemman.algo.pref_mem(dom), in_megabyte(1331.2))
        dom.mem_used = in_megabyte(5000)
        self.assertEqual(qubes.qmemman.algo.pref_mem(dom), in_megabyte(4096))

    def test_020_needed_mem(self):
        dom = qubes.qmemman.domainstate.DomainState("10")
        dom.mem_used = in_megabyte(1024)
        dom.mem_max = in_megabyte(4096)
        dom.mem_actual = in_megabyte(1024)
        self.assertEqual(qubes.qmemman.algo.needed_mem(dom), in_megabyte(307.2))

        dom.mem_actual = in_megabyte(2024)
        self.assertEqual(
            qubes.qmemman.algo.needed_mem(dom), in_megabyte(-692.800001)
        )

    def test_100_balloon(self):
        domains = {
            "0": construct_dominfo(
                "0",
                mem_used=in_megabyte(1024),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(1736),
                mem_current=in_megabyte(1736),
            ),
            "1": construct_dominfo(
                "1",
                mem_used=in_megabyte(1024),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(1536),
                mem_current=in_megabyte(1536),
            ),
            # at pref_mem
            "2": construct_dominfo(
                "2",
                mem_used=in_megabyte(4096),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(4096),
                mem_current=in_megabyte(4096),
            ),
            # no meminfo at all
            "3": construct_dominfo(
                "3",
                mem_used=None,
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(4096),
                mem_current=in_megabyte(4096),
            ),
        }
        result = qubes.qmemman.algo.balloon(in_megabyte(400), domains)
        expected = []
        self.assertEqual(result, expected)
        domains["1"].mem_used = in_megabyte(512)

        result = qubes.qmemman.algo.balloon(in_megabyte(400), domains)
        released = sum(domains[l[0]].mem_current - l[1] for l in result)
        expected = [("0", 1794242737), ("1", 1196296014)]
        self.assertGreater(released, in_megabyte(400))
        # should be within about 5% margin
        self.assertLess(released - in_megabyte(400), in_megabyte(21))
        self.assertEqual(result, expected)

    def test_200_balance_when_enough_mem(self):
        domains = {
            "0": construct_dominfo(
                "0",
                mem_used=in_megabyte(1024),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(1736),
                mem_current=in_megabyte(1736),
            ),
            "1": construct_dominfo(
                "1",
                mem_used=in_megabyte(1024),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(1536),
                mem_current=in_megabyte(1536),
            ),
            # at maxmem
            "2": construct_dominfo(
                "2",
                mem_used=in_megabyte(4096),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(4096),
                mem_current=in_megabyte(4096),
            ),
            # no meminfo at all
            "3": construct_dominfo(
                "3",
                mem_used=None,
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(4096),
                mem_current=in_megabyte(4096),
            ),
            # at pref_mem, but can get more
            "4": construct_dominfo(
                "4",
                mem_used=in_megabyte(1536),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(1536),
                mem_current=in_megabyte(1536),
            ),
            # low maxmem
            "5": construct_dominfo(
                "5",
                mem_used=in_megabyte(512),
                mem_max=in_megabyte(1024),
                mem_actual=in_megabyte(768),
                mem_current=in_megabyte(768),
            ),
        }
        total_pref_mem = sum(
            qubes.qmemman.algo.pref_mem(dom)
            for dom in domains.values()
            if dom.mem_used is not None
        )
        # xen_free_mem is ignored, use dummy 0 there
        result = qubes.qmemman.algo.balance_when_enough_mem(
            domains, 0, total_pref_mem, in_megabyte(4096)
        )
        total_allocated = sum(l[1] - domains[l[0]].mem_actual for l in result)
        # FIXME: the current algo is broken here, thus +5%
        self.assertLess(total_allocated, in_megabyte(4096) * 1.05)
        # should be no repeats
        self.assertEqual(
            len(result),
            len(set(x[0] for x in result)),
            "repeated requests in {!r}".format(result),
        )
        # no meminfo -> no adjustment
        self.assertNotIn(("3", unittest.mock.ANY), result)
        # pref_mem==maxmem==current, shouldn't adjust
        request = [x for x in result if x[0] == "2"][0]
        self.assertEqual(request[1], domains["2"].mem_actual)

        # bigger pref_mem -> bigger target
        request1 = [x for x in result if x[0] == "1"][0]  # mem_used 1GB
        request2 = [x for x in result if x[0] == "4"][0]  # mem_used 1.5GB
        self.assertGreater(request2[1], request1[1])

        # verify all requests exactly, when changing the algorithm this needs
        # to be re-validated manually
        self.assertEqual(
            result,
            [
                ("0", 3068708976),
                ("1", 2548378128),
                ("2", 4294967296),
                ("4", 3537898734),
                ("5", 1073741824),
            ],
        )

    def test_250_balance_when_low_on_mem(self):
        domains = {
            # below pref_mem
            "0": construct_dominfo(
                "0",
                mem_used=in_megabyte(1024),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(768),
                mem_current=in_megabyte(768),
            ),
            "1": construct_dominfo(
                "1",
                mem_used=in_megabyte(1024),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(1536),
                mem_current=in_megabyte(1536),
            ),
            # at maxmem
            "2": construct_dominfo(
                "2",
                mem_used=in_megabyte(4096),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(4096),
                mem_current=in_megabyte(4096),
            ),
            # no meminfo at all
            "3": construct_dominfo(
                "3",
                mem_used=None,
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(4096),
                mem_current=in_megabyte(4096),
            ),
            # at pref_mem, but can get more
            "4": construct_dominfo(
                "4",
                mem_used=in_megabyte(1536),
                mem_max=in_megabyte(4096),
                mem_actual=in_megabyte(1536),
                mem_current=in_megabyte(1536),
            ),
            # low maxmem
            "5": construct_dominfo(
                "5",
                mem_used=in_megabyte(512),
                mem_max=in_megabyte(1024),
                mem_actual=in_megabyte(768),
                mem_current=in_megabyte(768),
            ),
        }
        # call "balance" instead of "balance_low_on_memory" directly,
        # to collect donors/acceptors list
        result = qubes.qmemman.algo.balance(in_megabyte(50), domains)
        # should be no repeats
        self.assertEqual(
            len(result),
            len(set(x[0] for x in result)),
            "repeated requests in {!r}".format(result),
        )
        # no meminfo -> no adjustment
        self.assertNotIn(("3", unittest.mock.ANY), result)
        for domid, target in result:
            if domains[domid].mem_used > domains[domid].mem_actual:
                # no domain should get less, if already below pref_mem
                self.assertGreaterEqual(
                    target,
                    domains[domid].mem_actual,
                    "Request for {} reduces in {!r}".format(domid, result),
                )
            else:
                # otherwise it _should_ get reduced
                self.assertLess(
                    target,
                    domains[domid].mem_actual,
                    "Request for {} increases in {!r}".format(domid, result),
                )

        # verify all requests exactly, when changing the algorithm this needs
        # to be re-validated manually
        self.assertEqual(
            result,
            [
                ("1", 1395864371),
                ("5", 697932185),
            ],
        )
