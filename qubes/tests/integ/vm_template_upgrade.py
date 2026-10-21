#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2026 Nihal Kumar <nihalxkumar@tutamail.com>
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
"""Integration tests for qvm-template-upgrade."""

import asyncio
import os
import subprocess
import sys

import qubes.tests
import qubes.vm.appvm
import qubes.vm.standalonevm

EXIT_OK = 0
EXIT_ERR = 1
EXIT_USAGE = 64

# Nonexistent release version used to test failure paths without repository access.
BOGUS_VERSION = "998"


# noinspection PyAttributeOutsideInit,PyPep8Naming
class TemplateUpgradeMixin(object):
    """Tests for qvm-template-upgrade"""

    # filled by load_tests
    template = None

    def setUp(self):
        """
        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        if not self.template.count("debian") and not self.template.count(
            "fedora"
        ):
            self.skipTest(
                "Template {} not supported by "
                "qvm-template-upgrade".format(self.template)
            )
        super(TemplateUpgradeMixin, self).setUp()
        self.init_default_template(self.template)
        self.new_name = self.make_vm_name("upgraded")

    def run_template_upgrade(
        self, *options, expected_ret_codes=(EXIT_OK,), timeout=600
    ):
        """
        Run qvm-template-upgrade in dom0 and assert its return code.

        Returns the tool's combined stdout+stderr.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        proc = self.loop.run_until_complete(
            asyncio.create_subprocess_exec(
                "qvm-template-upgrade",
                *options,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        )
        try:
            stdout, _ = self.loop.run_until_complete(
                asyncio.wait_for(proc.communicate(), timeout)
            )
        except asyncio.TimeoutError:
            proc.terminate()
            self.loop.run_until_complete(proc.wait())
            self.fail(
                "qvm-template-upgrade {} timed out after {}s".format(
                    " ".join(options), timeout
                )
            )
        output = stdout.decode(errors="replace")
        if proc.returncode not in expected_ret_codes:
            self.fail(
                "qvm-template-upgrade returned unexpected code: "
                "{} not in {}\n{}".format(
                    proc.returncode, expected_ret_codes, output
                )
            )
        return output

    def create_source_vm(self, os_version, *, with_disk=False, name_suffix=""):
        """Create a StandaloneVM as an upgrade source.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.app.add_new_vm(
            qubes.vm.standalonevm.StandaloneVM,
            name=self.make_vm_name("source" + name_suffix),
            label="red",
        )
        tpl = self.app.domains[self.template]
        if with_disk:
            source.clone_properties(tpl)
            source.features.update(tpl.features)
            self.loop.run_until_complete(source.clone_disk_files(tpl))
        else:
            self.loop.run_until_complete(source.create_on_disk())
            source.features["os-distribution"] = tpl.features.get(
                "os-distribution", ""
            )
        source.features["os-version"] = os_version
        self.app.save()
        return source

    def test_000_dry_run(self):
        """
        Dry run against the real template: plan printed, nothing created.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        self.app.save()
        output = self.run_template_upgrade(
            "--template",
            self.template,
            "--new-name",
            self.new_name,
            "--dry-run",
        )
        self.assertIn("[dry-run]", output)
        self.assertIn(self.new_name, output)
        self.assertNotIn(self.new_name, self.app.domains)

    def test_001_dry_run_derived_name(self):
        """
        Without --new-name the final version in the name is replaced.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.create_source_vm("7", name_suffix="-7")
        # the trailing version in the name is replaced, not appended to
        derived = source.name[: -len("7")] + "8"
        output = self.run_template_upgrade(
            "--template", source.name, "--dry-run"
        )
        self.assertIn("[dry-run]", output)
        self.assertIn(derived, output)
        self.assertNotIn(derived, self.app.domains)

    def test_010_reject_missing_features(self):
        """
        A source that never reported os-* features is rejected.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.create_source_vm("1")
        del source.features["os-version"]
        self.app.save()
        self.run_template_upgrade(
            "--template",
            source.name,
            "--dry-run",
            expected_ret_codes=(EXIT_USAGE,),
        )

    def test_011_reject_unsupported_distro(self):
        """
        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.create_source_vm("1")
        source.features["os-distribution"] = "templeos"
        source.features["os-distribution-like"] = ""
        self.app.save()
        self.run_template_upgrade(
            "--template",
            source.name,
            "--dry-run",
            expected_ret_codes=(EXIT_USAGE,),
        )

    def test_012_reject_non_numeric_version(self):
        """
        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.create_source_vm("sid")
        self.run_template_upgrade(
            "--template",
            source.name,
            "--dry-run",
            expected_ret_codes=(EXIT_USAGE,),
        )

    def test_013_reject_nonexistent_qube(self):
        """
        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        self.app.save()
        self.run_template_upgrade(
            "--template",
            self.make_vm_name("no-such-qube"),
            "--dry-run",
            expected_ret_codes=(EXIT_USAGE,),
        )

    def test_014_reject_existing_target(self):
        """
        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.create_source_vm("1")
        self.run_template_upgrade(
            "--template",
            source.name,
            "--new-name",
            self.template,
            "--dry-run",
            expected_ret_codes=(EXIT_USAGE,),
        )

    def test_015_reject_appvm(self):
        """
        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        appvm = self.app.add_new_vm(
            qubes.vm.appvm.AppVM,
            name=self.make_vm_name("appvm"),
            label="red",
        )
        self.loop.run_until_complete(appvm.create_on_disk())
        self.app.save()
        self.run_template_upgrade(
            "--template",
            appvm.name,
            "--dry-run",
            expected_ret_codes=(EXIT_USAGE,),
        )

    def test_020_failed_upgrade_rolls_back_clone(self):
        """
        When the in-qube agent fails, the clone is removed and the
        source is untouched.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.create_source_vm(BOGUS_VERSION, with_disk=True)
        self.run_template_upgrade(
            "--template",
            source.name,
            "--new-name",
            self.new_name,
            expected_ret_codes=(EXIT_ERR,),
            timeout=1800,
        )
        self.assertNotIn(self.new_name, self.app.domains)
        self.assertIn(source.name, self.app.domains)
        self.assertEqual(source.features.get("os-version"), BOGUS_VERSION)

    def test_021_keep_new_on_failure(self):
        """
        With --keep-new-on-failure the half-upgraded clone survives for
        inspection.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        source = self.create_source_vm(BOGUS_VERSION, with_disk=True)
        self.run_template_upgrade(
            "--template",
            source.name,
            "--new-name",
            self.new_name,
            "--keep-new-on-failure",
            expected_ret_codes=(EXIT_ERR,),
            timeout=1800,
        )
        self.assertIn(self.new_name, self.app.domains)

    def test_100_full_release_upgrade(self):
        """
        Full upgrade of the real template to the next release.

        Needs the next release's repositories to exist and takes tens of
        minutes, so it only runs when QUBES_TEST_RELEASE_UPGRADE is set.

        :type self: qubes.tests.SystemTestCase | TemplateUpgradeMixin
        """
        if not os.environ.get("QUBES_TEST_RELEASE_UPGRADE"):
            self.skipTest("QUBES_TEST_RELEASE_UPGRADE not set")
        tpl = self.app.domains[self.template]
        old_version = tpl.features.get("os-version")
        self.app.save()
        self.run_template_upgrade(
            "--template",
            self.template,
            "--new-name",
            self.new_name,
            "--log",
            "DEBUG",
            timeout=7200,
        )
        self.assertIn(self.new_name, self.app.domains)
        clone = self.app.domains[self.new_name]
        self.loop.run_until_complete(clone.shutdown(wait=True))
        # metadata rewritten by finalize()
        self.assertEqual(clone.features.get("template-name"), self.new_name)
        self.assertEqual(
            clone.features.get("template-reponame"), "@qvm-template-upgrade"
        )
        # the in-qube agent verified and reported the new release
        self.assertEqual(
            clone.features.get("os-version"), str(int(old_version) + 1)
        )
        # the source is untouched
        self.assertEqual(tpl.features.get("os-version"), old_version)


def create_testcases_for_templates():
    yield from qubes.tests.create_testcases_for_templates(
        "TemplateUpgrade",
        TemplateUpgradeMixin,
        qubes.tests.SystemTestCase,
        module=sys.modules[__name__],
    )


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromNames(create_testcases_for_templates()))
    return tests


qubes.tests.maybe_create_testcases_on_import(create_testcases_for_templates)
