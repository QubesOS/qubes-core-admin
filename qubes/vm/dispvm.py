#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2014-2016  Wojtek Porczyk <woju@invisiblethingslab.com>
# Copyright (C) 2016       Marek Marczykowski <marmarek@invisiblethingslab.com>)
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

""" A disposable vm implementation """

import asyncio
import copy
import psutil
import subprocess

import qubes.vm.qubesvm
import qubes.vm.appvm
import qubes.config


def _setter_template(self, prop, value):
    if not getattr(value, "template_for_dispvms", False):
        raise qubes.exc.QubesPropertyValueError(
            self,
            prop,
            value,
            "template for DispVM must have template_for_dispvms=True",
        )
    return value


class DispVM(qubes.vm.qubesvm.QubesVM):
    """Disposable VM"""

    template = qubes.VMProperty(
        "template",
        load_stage=4,
        setter=_setter_template,
        doc="AppVM, on which this DispVM is based.",
    )

    dispid = qubes.property(
        "dispid",
        type=int,
        write_once=True,
        clone=False,
        doc="""Internal, persistent identifier of particular DispVM.""",
    )

    auto_cleanup = qubes.property(
        "auto_cleanup",
        type=bool,
        default=False,
        doc="automatically remove this VM upon shutdown",
    )

    include_in_backups = qubes.property(
        "include_in_backups",
        type=bool,
        default=(lambda self: not self.auto_cleanup),
        doc="If this domain is to be included in default backup.",
    )

    default_dispvm = qubes.VMProperty(
        "default_dispvm",
        load_stage=4,
        allow_none=True,
        default=(lambda self: self.template),
        doc="Default VM to be used as Disposable VM for service calls.",
    )

    default_volume_config = {
        "root": {
            "name": "root",
            "snap_on_start": True,
            "save_on_stop": False,
            "rw": True,
            "source": None,
        },
        "private": {
            "name": "private",
            "snap_on_start": True,
            "save_on_stop": False,
            "rw": True,
            "source": None,
        },
        "volatile": {
            "name": "volatile",
            "snap_on_start": False,
            "save_on_stop": False,
            "rw": True,
            "size": qubes.config.defaults["root_img_size"]
            + qubes.config.defaults["private_img_size"],
        },
        "kernel": {
            "name": "kernel",
            "snap_on_start": False,
            "save_on_stop": False,
            "rw": False,
        },
    }

    def __init__(self, app, xml, *args, **kwargs):
        self.volume_config = copy.deepcopy(self.default_volume_config)
        template = kwargs.get("template", None)

        if xml is None:
            assert template is not None

            if not getattr(template, "template_for_dispvms", False):
                raise qubes.exc.QubesValueError(
                    "template for DispVM ({}) needs to be an AppVM with "
                    "template_for_dispvms=True".format(template.name)
                )

            if "dispid" not in kwargs:
                kwargs["dispid"] = app.domains.get_new_unused_dispid()
            if "name" not in kwargs:
                kwargs["name"] = "disp" + str(kwargs["dispid"])

        if template is not None:
            # template is only passed if the AppVM is created, in other cases we
            # don't need to patch the volume_config because the config is
            # coming from XML, already as we need it
            for name, config in template.volume_config.items():
                # in case the template vm has more volumes add them to own
                # config
                if name not in self.volume_config:
                    self.volume_config[name] = config.copy()
                    if "vid" in self.volume_config[name]:
                        del self.volume_config[name]["vid"]
                else:
                    # if volume exists, use its live config, since some settings
                    # can be changed and volume_config isn't updated
                    config = template.volumes[name].config
                    # copy pool setting from base AppVM; root and private would
                    # be in the same pool anyway (because of snap_on_start),
                    # but not volatile, which could be surprising
                    if (
                        "pool" not in self.volume_config[name]
                        and "pool" in config
                    ):
                        self.volume_config[name]["pool"] = config["pool"]
                    # copy rw setting from the base AppVM too
                    if "rw" in config:
                        self.volume_config[name]["rw"] = config["rw"]
                    # copy ephemeral setting from the base AppVM too, but only
                    # if non-default value is used
                    if (
                        "ephemeral" not in self.volume_config[name]
                        and "ephemeral" in config
                    ):
                        self.volume_config[name]["ephemeral"] = config[
                            "ephemeral"
                        ]

        super().__init__(app, xml, *args, **kwargs)

        if xml is None:
            # by default inherit properties from the DispVM template
            proplist = [
                prop.__name__
                for prop in template.property_list()
                if prop.clone and prop.__name__ not in ["template"]
            ]
            # Do not overwrite properties that have already been set to a
            # non-default value.
            self_props = [
                prop.__name__
                for prop in self.property_list()
                if self.property_is_default(prop)
            ]
            self.clone_properties(
                template, set(proplist).intersection(self_props)
            )

            self.firewall.clone(template.firewall)
            self.features.update(template.features)
            self.tags.update(template.tags)

    def get_feat_preload(self, feature):
        if feature not in ["preload-dispvm", "preload-dispvm-max"]:
            raise qubes.exc.QubesException("Invalid feature provided")

        if feature == "preload-dispvm":
            default = ""
        elif feature == "preload-dispvm-max":
            default = 0

        value = self.features.check_with_template(feature, default)

        if feature == "preload-dispvm":
            return value.split(" ")
        if feature == "preload-dispvm-max":
            return int(value)
        return None

    def is_preloaded(self):
        preload_dispvm = self.get_feat_preload("preload-dispvm")
        if not preload_dispvm:
            return False
        if self.name not in preload_dispvm:
            return False
        return True

    async def mark_preloaded(self):
        """
        Create preloaded DispVM.

        Template from which the VM should be created.

        :return:
        """
        preload_dispvm = self.get_feat_preload("preload-dispvm")
        if preload_dispvm:
            preload_dispvm.append(self.name)
        else:
            preload_dispvm = [self.name]

        appvm = getattr(self, "template")
        appvm.features["preload-dispvm"] = " ".join(preload_dispvm)
        self.features["internal"] = True

    async def use_preloaded(self):
        """
        Mark preloaded DispVM as used.

        :return:
        """
        appvm = getattr(self, "template")

        preload_dispvm = self.get_feat_preload("preload-dispvm")
        if self.name not in preload_dispvm:
            raise qubes.exc.QubesException("DispVM is not preloaded")

        preload_dispvm = " ".join(preload_dispvm.remove(self.name))
        appvm.features["preload-dispvm"] = preload_dispvm
        self.features["internal"] = False
        await appvm.fire_event_async(
            "domain-preloaded-dispvm-used", dispvm=self
        )

    @qubes.events.handler(
        "domain-preloaded-dispvm-used", "domain-preloaded-dispvm-autostart"
    )
    async def on_domain_preloaded_dispvm_used(self, event, delay=5, **kwargs):  # pylint: disable=unused-argument
        """When preloaded DispVM is used or after boot, preload another one.

        :param event: event which was fired
        :param delay: delay between trials
        :returns:
        """
        await asyncio.sleep(delay)
        while True:
            # TODO: Is there existing Qubes code that checks available memory
            # before starting a qube?
            memory = getattr(self, "memory", 0)
            available_memory = (
                psutil.virtual_memory().available / (1024 * 1024)
            )
            threshold = 1024 * 5
            if memory >= (available_memory - threshold):
                ## TODO: how to pass arg?
                await qubes.vm.dispvm.DispVM.from_appvm(
                    self, preload=True
                ).start()
                #await qubes.api.admin.QubesAdminAPI.create_disposable(
                #    self.app, b"dom0", "admin.vm.CreateDisposable", b"dom0", b"preload"
                #)
                # TODO: what to do if the maximum is never reached on autostart
                # as there is not enough memory, and then a preloaded DispVM is
                # used, calling for the creation of another one, while the
                # autostart will also try to create one. Is this a race
                # condition?
                # TODO: fire event after start of all qubes that are set to
                # autostart.
                if event == "domain-preloaded-dispvm-autostart":
                    preload_dispvm_max = self.get_feat_preload(
                        "preload-dispvm-max"
                    )
                    preload_dispvm = self.get_feat_preload("preload-dispvm")
                    if (
                        preload_dispvm
                        and len(preload_dispvm) < preload_dispvm_max
                    ):
                        continue
                break
            await asyncio.sleep(delay)

    @qubes.events.handler("domain-load")
    def on_domain_loaded(self, event):
        """When domain is loaded assert that this vm has a template."""  # pylint: disable=unused-argument
        assert self.template

    @qubes.events.handler("domain-start")
    # W0236 (invalid-overridden-method) Method 'on_domain_started' was expected
    # to be 'non-async', found it instead as 'async'
    # TODO: Seems to conflict with qubes.vm.mix.net, which is pretty strange.
    # Larger bug? qubes.vm.qubesvm.QubesVM has NetVMMixin... which conflicts...
    async def on_domain_started(self, event, **kwargs):
        """Pause preloaded domains as soon as they start."""
        # TODO:
        # Marek: Test if pause isn't too early. Some services (especially:
        #   gui-agent) may still be starting.  qubes.WaitForSession service may
        #   help (ensure to use async handler to not block qubesd while waiting
        #   on it).
        no_gui_sleep = 15
        gui_timeout = 30
        if self.is_preloaded():
            gui = self.features.get("gui", None)
            if not gui:
                asyncio.sleep(no_gui_sleep)
                self.pause()
                return

            proc = None
            try:
                proc = await asyncio.wait_for(
                    self.run_service(
                        "qubes.WaitForSession",
                        user=self.default_user,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ),
                    timeout=gui_timeout,
                )
            except asyncio.TimeoutError:
                ## TODO: should timeout be treated as an error/qubes.exc?
                return
            except (subprocess.CalledProcessError,qubes.exc.QubesException):
                raise qubes.exc.QubesException(
                    "Failed to run QUBESRPC qubes.WaitForSession"
                )
            finally:
                if proc is not None:
                    proc.terminate()
                self.pause()

    @qubes.events.handler("domain-unpaused")
    async def on_domain_unpaused(self):
        """Mark unpaused preloaded domains as used."""
        if self.is_preloaded():
            await self.use_preloaded()

    @qubes.events.handler("property-pre-reset:template")
    def on_property_pre_reset_template(self, event, name, oldvalue=None):
        """Forbid deleting template of VM"""  # pylint: disable=unused-argument
        raise qubes.exc.QubesValueError("Cannot unset template")

    @qubes.events.handler("property-pre-set:template")
    def on_property_pre_set_template(
        self, event, name, newvalue, oldvalue=None
    ):
        """Forbid changing template of running VM"""  # pylint: disable=unused-argument
        if not self.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(
                self, "Cannot change template while qube is running"
            )

    @qubes.events.handler("property-set:template")
    def on_property_set_template(self, event, name, newvalue, oldvalue=None):
        """Adjust root (and possibly other snap_on_start=True) volume
        on template change.
        """  # pylint: disable=unused-argument
        qubes.vm.appvm.template_changed_update_storage(self)

    @qubes.events.handler("domain-shutdown")
    async def on_domain_shutdown(
        self, _event, **_kwargs
    ):  # pylint: disable=invalid-overridden-method
        await self._auto_cleanup()

    async def _auto_cleanup(self):
        """Do auto cleanup if enabled"""
        if self.auto_cleanup and self in self.app.domains:
            del self.app.domains[self]
            await self.remove_from_disk()
            self.app.save()

    @classmethod
    async def from_appvm(cls, appvm, preload=False, **kwargs):
        """Create a new instance from given AppVM

        :param qubes.vm.appvm.AppVM appvm: template from which the VM should \
            be created
        :param bool preload: Whether to preload a disposable
        :returns: new disposable vm

        *kwargs* are passed to the newly created VM

        >>> import qubes.vm.dispvm.DispVM
        >>> dispvm = qubes.vm.dispvm.DispVM.from_appvm(appvm).start()
        >>> dispvm.run_service('qubes.VMShell', input='firefox')
        >>> dispvm.cleanup()

        This method modifies :file:`qubes.xml` file.
        The qube returned is not started.
        """
        if not getattr(appvm, "template_for_dispvms", False):
            raise qubes.exc.QubesException(
                "Refusing to create DispVM out of this AppVM, because "
                "template_for_dispvms=False"
            )
        app = appvm.app

        if preload:
            preload_dispvm_max = appvm.get_feat_preload("preload-dispvm-max")
            if preload_dispvm_max == 0:
                return
            preload_dispvm = appvm.get_feat_preload("preload-dispvm")
            if preload_dispvm and len(preload_dispvm) >= preload_dispvm_max:
                raise qubes.exc.QubesException(
                    "Failed to create preloaded disposable, limit of "
                    "preloaded DispVMs reached"
                )
        else:
            preload_dispvm = appvm.get_feat_preload("preload-dispvm")
            if preload_dispvm:
                dispvm = app.domains[preload_dispvm[0]]
                await dispvm.use_preloaded()
                return dispvm

        dispvm = app.add_new_vm(
            cls, template=appvm, auto_cleanup=True, **kwargs
        )
        await dispvm.create_on_disk()

        if preload:
            await dispvm.mark_preloaded()

        app.save()
        return dispvm

    async def cleanup(self):
        """Clean up after the DispVM

        This stops the disposable qube and removes it from the store.
        This method modifies :file:`qubes.xml` file.
        """
        try:
            await self.kill()
        except qubes.exc.QubesVMNotStartedError:
            pass
        # if auto_cleanup is set, this will be done automatically
        if not self.auto_cleanup:
            del self.app.domains[self]
            await self.remove_from_disk()
            self.app.save()

    async def start(self, **kwargs):
        # pylint: disable=arguments-differ

        try:
            # sanity check, if template_for_dispvm got changed in the meantime
            if not self.template.template_for_dispvms:
                raise qubes.exc.QubesException(
                    "template for DispVM ({}) needs to have "
                    "template_for_dispvms=True".format(self.template.name)
                )

            await super().start(**kwargs)
        except:
            # Cleanup also on failed startup
            await self._auto_cleanup()
            raise

    def create_qdb_entries(self):
        super().create_qdb_entries()
        self.untrusted_qdb.write("/qubes-vm-persistence", "none")
