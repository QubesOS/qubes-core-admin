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
    def _is_valid_key(key, vm) -> bool:
        if not key:
            vm.log.warning("Got empty custom-persist key, ignoring")
            return False

        # QubesDB key length limit
        key_maxlen = QDB_KEY_LIMIT - len(QDB_PREFIX)
        if len(key) > key_maxlen:
            vm.log.warning(
                "custom-persist key is too long (max {}), ignoring: "
                "{}".format(key_maxlen, key)
            )
            return False
        return True

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
            if self._is_expected_feature(feature) and self._is_valid_key(
                self._extract_key_from_feature(feature), vm
            ):
                self._write_db_value(feature, value, vm)

    @qubes.ext.handler("domain-feature-set:*")
    def on_domain_feature_set(self, vm, event, feature, value, oldvalue=None):
        """Inject persist keys in QubesDB in runtime"""
        # pylint: disable=unused-argument

        if not self._is_expected_feature(feature):
            return

        if not self._is_valid_key(self._extract_key_from_feature(feature), vm):
            return

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
