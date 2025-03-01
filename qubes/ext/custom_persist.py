# -*- encoding: utf-8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2024 Guillaume Chinal <guiiix@invisiblethingslab.com>
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

import os
import qubes.ext
import qubes.config

FEATURE_PREFIX = "custom-persist."
QDB_PREFIX = "/persist/"
QDB_KEY_LIMIT = 63


class CustomPersist(qubes.ext.Extension):
    """This extension allows to create minimal-state APP with by configuring an
    exhaustive list of bind dirs(and files)
    """

    @staticmethod
    def _extract_key_from_feature(feature) -> str:
        return feature[len(FEATURE_PREFIX) :]

    @staticmethod
    def _is_expected_feature(feature) -> bool:
        return feature.startswith(FEATURE_PREFIX)

    @staticmethod
    def _check_key(key):
        if not key:
            raise qubes.exc.QubesValueError(
                "custom-persist key cannot be empty"
            )

        # QubesDB key length limit
        key_maxlen = QDB_KEY_LIMIT - len(QDB_PREFIX)
        if len(key) > key_maxlen:
            raise qubes.exc.QubesValueError(
                "custom-persist key is too long (max {}), ignoring: "
                "{}".format(key_maxlen, key)
            )

    @staticmethod
    def _check_value_path(value):
        if not os.path.isabs(value):
            raise qubes.exc.QubesValueError(f"invalid path '{value}'")

    def _check_value(self, value):
        if value.startswith("/"):
            self._check_value_path(value)
        else:
            options = value.split(":")
            if len(options) < 5 or not options[4].startswith("/"):
                raise qubes.exc.QubesValueError(
                    f"invalid value format: '{value}'"
                )

            resource_type = options[0]
            mode = options[3]
            if resource_type not in ("file", "dir"):
                raise qubes.exc.QubesValueError(
                    f"invalid resource type option '{resource_type}' "
                    f"in value '{value}'"
                )
            try:
                if not 0 <= int(mode, 8) <= 0o7777:
                    raise qubes.exc.QubesValueError(
                        f"invalid mode option '{mode}' in value '{value}'"
                    )
            except ValueError:
                raise qubes.exc.QubesValueError(
                    f"invalid mode option '{mode}' in value '{value}'"
                )

            self._check_value_path(":".join(options[4:]))

    def _write_db_value(self, feature, value, vm):
        vm.untrusted_qdb.write(
            "{}{}".format(QDB_PREFIX, self._extract_key_from_feature(feature)),
            str(value),
        )

    @qubes.ext.handler("domain-qdb-create")
    def on_domain_qdb_create(self, vm, event):
        """Actually export features"""
        # pylint: disable=unused-argument
        for feature, value in vm.features.items():
            if self._is_expected_feature(feature):
                self._check_key(self._extract_key_from_feature(feature))
                self._check_value(value)
                self._write_db_value(feature, value, vm)

    @qubes.ext.handler("domain-feature-set:*")
    def on_domain_feature_set(self, vm, event, feature, value, oldvalue=None):
        """Inject persist keys in QubesDB in runtime"""
        # pylint: disable=unused-argument

        if not self._is_expected_feature(feature):
            return

        self._check_key(self._extract_key_from_feature(feature))
        self._check_value(value)

        if not vm.is_running():
            return

        self._write_db_value(feature, value, vm)

    @qubes.ext.handler("domain-feature-delete:*")
    def on_domain_feature_delete(self, vm, event, feature):
        """Update /persist/ QubesDB tree in runtime"""
        # pylint: disable=unused-argument
        if not vm.is_running():
            return
        if not feature.startswith(FEATURE_PREFIX):
            return

        vm.untrusted_qdb.rm(
            "{}{}".format(QDB_PREFIX, self._extract_key_from_feature(feature))
        )
