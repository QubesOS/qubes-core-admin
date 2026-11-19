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

"""Qubes' command line tools"""

import argparse
import importlib
import logging

import qubes.log


class QubesArgumentParser(argparse.ArgumentParser):
    """Parser preconfigured for use in most of the Qubes command-line tools.

    :param bool want_app: instantiate :py:class:`qubes.Qubes` object
    :param bool want_app_no_instance: don't actually instantiate \
        :py:class:`qubes.Qubes` object, just add argument for custom xml file

    *kwargs* are passed to :py:class:`argparser.ArgumentParser`.

    Currenty supported options:
        ``--qubesxml`` location of :file:`qubes.xml` (help is suppressed)
        ``--offline-mode`` do not talk to hypervisor (help is suppressed)
        ``--verbose`` and ``--quiet``
    """

    def __init__(self, want_app=True, want_app_no_instance=False, **kwargs):

        super().__init__(**kwargs)

        self._want_app = want_app
        self._want_app_no_instance = want_app_no_instance
        if self._want_app:
            self.add_argument(
                "--qubesxml",
                metavar="FILE",
                action="store",
                dest="app",
                help=argparse.SUPPRESS,
            )
            self.add_argument(
                "--offline-mode",
                action="store_true",
                default=None,
                dest="offline_mode",
                help=argparse.SUPPRESS,
            )

        self.add_argument(
            "--verbose", "-v", action="count", help="increase verbosity"
        )

        self.add_argument(
            "--quiet", "-q", action="count", help="decrease verbosity"
        )

        self.set_defaults(verbose=1, quiet=0)

    def parse_args(self, args=None, namespace=None):
        namespace = super().parse_args(args, namespace)

        if self._want_app and not self._want_app_no_instance:
            self.set_qubes_verbosity(namespace)
            namespace.app = qubes.Qubes(
                namespace.app, offline_mode=namespace.offline_mode
            )

        return namespace

    @staticmethod
    def set_qubes_verbosity(namespace):
        """Apply a verbosity setting.

        This is done by configuring global logging.
        :param argparse.Namespace args: args as parsed by parser
        """
        if namespace.debug:
            qubes.log.enable(
                log_level=logging.DEBUG,
                enable_debug_libvirt=getattr(
                    namespace, "enable_debug_libvirt", False
                ),
            )
            return

        verbose = namespace.verbose - namespace.quiet
        levels = [logging.NOTSET, logging.INFO, logging.DEBUG]
        log_level = levels[min(verbose, 2)]
        qubes.log.enable(log_level=log_level)


def get_parser_for_command(command):
    """Get parser for given qvm-tool.

    :param str command: command name
    :rtype: argparse.ArgumentParser
    :raises ImportError: when command's module is not found
    :raises AttributeError: when parser was not found
    """

    module = importlib.import_module(
        "." + command.replace("-", "_"), "qubes.tools"
    )

    try:
        parser = module.parser
    except AttributeError:
        try:
            parser = module.get_parser()
        except AttributeError:
            raise AttributeError("cannot find parser in module")

    return parser
