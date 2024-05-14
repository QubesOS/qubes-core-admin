#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2019 Frédéric Pierret <frederic.pierret@qubes-os.org>
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

import asyncio
import subprocess
import qubes.config
import qubes.ext


class AUDIO(qubes.ext.Extension):
    # pylint: disable=unused-argument
    @staticmethod
    def attached_vms(vm):
        for domain in vm.app.domains:
            if domain == vm:
                continue
            if getattr(domain, "audiovm", None) == vm:
                yield domain

    @staticmethod
    def set_qubesdb_audiovm(vm):
        # Ensure that qube is ready
        if not vm.is_running():
            return

        # Add AudioVM Xen ID for gui-agent
        audiovm = getattr(vm, "audiovm", None)
        if audiovm is not None:
            if audiovm != vm and audiovm.is_running():
                vm.untrusted_qdb.write(
                    "/qubes-audio-domain-xid", str(audiovm.xid)
                )
        else:
            vm.untrusted_qdb.rm("/qubes-audio-domain-xid")

    def set_tag_and_qubesdb_entry(self, subject, event, newvalue=None):
        # Clean other 'audiovm-XXX' tags.
        # pulseaudio agent (module-vchan-sink) can connect to only one domain
        tags_list = list(subject.tags)
        for tag in tags_list:
            if tag.startswith("audiovm-"):
                subject.tags.remove(tag)

        if newvalue:
            audiovm = "audiovm-" + newvalue.name
            subject.tags.add(audiovm)

        # It is needed to filter these events because
        # vm.is_running() is not yet available.
        if event not in ("domain-init", "domain-load"):
            self.set_qubesdb_audiovm(subject)

    @qubes.ext.handler("domain-pre-shutdown")
    def on_domain_pre_shutdown(self, vm, event, **kwargs):
        attached_vms = [
            domain for domain in self.attached_vms(vm) if domain.is_running()
        ]
        if attached_vms and not kwargs.get("force", False):
            raise qubes.exc.QubesVMError(
                self,
                "There are running VMs using this VM as AudioVM: "
                "{}".format(", ".join(vm.name for vm in attached_vms)),
            )

    @qubes.ext.handler("domain-init", "domain-load")
    def on_domain_init_load(self, vm, event):
        if getattr(vm, "audiovm", None):
            if "audiovm-" + vm.audiovm.name not in vm.tags:
                self.on_property_set(
                    vm, event, name="audiovm", newvalue=vm.audiovm
                )

    @qubes.ext.handler("property-reset:audiovm")
    def on_property_reset(self, subject, event, name, oldvalue=None):
        newvalue = getattr(subject, "audiovm", None)
        self.on_property_set(subject, event, name, newvalue, oldvalue)

    @staticmethod
    async def set_stubdom_audiovm_domid(qube, audiovm):
        if audiovm:
            audiovm_xid = audiovm.xid
        else:
            audiovm_xid = -1
        try:
            await qube.run_service_for_stdio(
                f"qubes.SetAudioVM+{audiovm_xid}",
                user="root",
                stubdom=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as e:
            msg = f"{qube}: failed to set stubdom AudioVM domid: {str(e)}"
            qube.log.error(msg)

    @qubes.ext.handler("property-set:audiovm")
    def on_property_set(self, subject, event, name, newvalue, oldvalue=None):
        self.set_tag_and_qubesdb_entry(
            subject=subject, event=event, newvalue=newvalue
        )
        if newvalue == oldvalue:
            return
        has_stubdom_qrexec = subject.features.check_with_template(
            'stubdom-qrexec', None)
        has_audio_model = subject.features.check_with_template(
            'audio-model', None)
        if has_audio_model and not has_stubdom_qrexec:
            subject.log.warning("Cannot change dynamically audiovm: qrexec"
                                " is not available (stubdom-qrexec feature)")
        if has_audio_model and has_stubdom_qrexec:
            asyncio.ensure_future(
                self.set_stubdom_audiovm_domid(subject, newvalue)
            )

    @qubes.ext.handler("domain-qdb-create")
    def on_domain_qdb_create(self, vm, event):
        self.set_qubesdb_audiovm(vm)

    @qubes.ext.handler("property-set:default_audiovm", system=True)
    def on_property_set_default_audiovm(
            self, app, event, name, newvalue, oldvalue=None
    ):
        for vm in app.domains:
            if hasattr(vm, "audiovm") and vm.property_is_default("audiovm"):
                vm.fire_event(
                    "property-set:audiovm",
                    name="audiovm",
                    newvalue=newvalue,
                    oldvalue=oldvalue,
                )

    @qubes.ext.handler("domain-start")
    def on_domain_start(self, vm, event, **kwargs):
        attached_vms = [
            domain for domain in self.attached_vms(vm) if domain.is_running()
        ]
        for attached_vm in attached_vms:
            attached_vm.untrusted_qdb.write(
                "/qubes-audio-domain-xid", str(vm.xid)
            )
