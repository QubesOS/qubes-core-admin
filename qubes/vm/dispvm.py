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
import subprocess
from typing import Optional

import qubes.config
import qubes.vm.appvm
import qubes.vm.qubesvm


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
            self.features.update(
                [
                    (key, value)
                    for key, value in template.features.items()
                    if not key.startswith("preload-dispvm")
                ]
            )
            self.tags.update(template.tags)

    # TODO: ben: @qubes.stateless_property
    #
    # Marek: I wonder if this shouldn't be a public property (like
    # @qubes.stateless_property) - this way GUI will be able to better
    # distinguish this case, instead of relying on just internal feature. But
    # for this to work reliably, you'd need to manually fire
    # property-reset:is_preload event when the value might change. With
    # internal feature you get that for free.
    #
    # Ben: checking for internal feature is not enough in case the appvm
    # (default-mgmt-dvm) has it also. Checking for paused state is also not
    # enough because it is late (when preloading has finished) and may also not
    # occur in case the qube is requested prior to being paused.
    @qubes.stateless_property
    def is_preload(self) -> bool:
        appvm = self.template
        preload_dispvm = appvm.get_feat_preload()
        if self.name in preload_dispvm:
            return True
        if self.features.get("preload-dispvm-request", None):
            return True
        return False

    def use_preload(self):
        """
        Mark preloaded DispVM as used (tainted).

        :return:
        """
        if not self.is_preload:
            raise qubes.exc.QubesException("DispVM is not preloaded")
        appvm = self.template
        self.log.info("Using preloaded qube")
        if self.features.get("preload-dispvm-request", None):
            del self.features["preload-dispvm-request"]
            if not appvm.features.get("internal", None):
                del self.features["internal"]
        else:
            # Happens if qube is unpaused before being requested.
            self.log.warning(
                "Using a preloaded qube before requesting it, marking as used"
            )
            appvm.remove_preload_from_list(self.name)
        asyncio.ensure_future(
            appvm.fire_event_async("domain-preload-dispvm-used", dispvm=self)
        )

    @qubes.events.handler("domain-load")
    def on_domain_loaded(self, event):
        """When domain is loaded assert that this vm has a template."""  # pylint: disable=unused-argument
        assert self.template

    @qubes.events.handler("domain-start")
    async def on_domain_started_dispvm(
        self,
        event,
        **kwargs,
    ):  # pylint: disable=unused-argument
        """Pause preloaded domains as soon as basic services have started."""
        if not self.is_preload:
            return
        # TODO: pause is late for autostarted GUI applications
        #   https://github.com/QubesOS/qubes-issues/issues/9907
        timeout = self.qrexec_timeout
        gui = self.guivm and self.features.get("gui", True)
        service = "qubes.WaitForSession"
        if not gui:
            service = "qubes.WaitForRunningSystem"
        try:
            self.log.info(
                "Waiting '%s' with timeout of '%d' seconds", service, timeout
            )
            await asyncio.wait_for(
                self.run_service_for_stdio(
                    service,
                    user=self.default_user,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # TODO: if pause occurs before the GUI session starts (on boot
            # before login manager), results in an unusable GUI for the qube:
            # https://github.com/QubesOS/qubes-issues/issues/9940
            self.log.error(
                "Timed out Qrexec call to '%s' after '%d' seconds during "
                "preload startup",
                service,
                timeout,
            )
        except (subprocess.CalledProcessError, qubes.exc.QubesException):
            raise qubes.exc.QubesException(
                "Error on Qrexec call to '%s' during preload startup" % service
            )

        appvm = self.template
        # Qube may have been destroyed during the await above.
        appvm.remove_preload_excess()
        if self.is_preload:
            if self.features.get("preload-dispvm-request", None):
                self.features["preload-dispvm-skip-interrupt"] = True
                self.use_preload()
            else:
                await self.pause()

    @qubes.events.handler("domain-paused")
    def on_domain_paused(
        self, event, **kwargs
    ):  # pylint: disable=unused-argument
        """Log preloaded domains when paused."""
        if self.is_preload:
            self.log.info("Paused preloaded qube")

    @qubes.events.handler("domain-unpaused")
    def on_domain_unpaused(
        self, event, **kwargs
    ):  # pylint: disable=unused-argument
        """Mark unpaused preloaded domains as used."""
        # Qube start triggers unpause via 'libvirt_domain.resume()'.
        if self.is_preload and self.is_fully_usable():
            self.log.info("Unpaused preloaded qube will be marked as used")
            self.use_preload()

    @qubes.events.handler("domain-feature-set:preload-dispvm-request")
    def on_feature_set_preload_dispvm_request(
        self, event, feature, value, oldvalue=None
    ):  # pylint: disable=unused-argument
        # TODO: ben: review and cleanup
        self.fire_event("property-reset:is_preload", name="is_preload")

    @qubes.events.handler("domain-feature-delete:preload-dispvm-request")
    def on_feature_delete_preload_dispvm_request(
        self, event, feature
    ):  # pylint: disable=unused-argument
        # TODO: ben: review and cleanup
        self.fire_event("property-reset:is_preload", name="is_preload")

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
        if self.is_preload:
            appvm = self.template
            preload_dispvm = appvm.get_feat_preload()
            if self.name in preload_dispvm:
                self.log.info("Shutdown removes qube from preload list")
                appvm.remove_preload_from_list(self.name)
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

        if preload and not appvm.can_preload():
            raise qubes.exc.QubesException(
                "Failed to create preloaded disposable, limit of "
                "preloaded DispVMs reached"
            )

        if not preload and (preload_dispvm := appvm.get_feat_preload()):
            dispvm = app.domains[preload_dispvm[0]]
            dispvm.log.info("Requesting preloaded qube")
            # The feature "preload-dispvm-request" offloads "preload-dispvm"
            # and thus avoids various race condition:
            # - Decreasing maximum feature will not remove the qube;
            # - Another request to this function will not return the same qube.
            appvm.remove_preload_from_list(dispvm.name)
            dispvm.features["preload-dispvm-request"] = True
            tries, sleep = 1200, 0.1
            for _ in range(tries):
                if dispvm.features.get(
                    "preload-dispvm-skip-interrupt", None
                ) or (paused := dispvm.is_paused()):
                    if paused:
                        await dispvm.unpause()
                    app.save()
                    return dispvm
                await asyncio.sleep(sleep)
            dispvm.log.warning(
                "Requested preloaded qube but failed to finish preloading after"
                " '%d' seconds, falling back to normal disposable",
                int(tries * sleep),
            )
            if dispvm in app.domains:
                asyncio.ensure_future(dispvm.cleanup())

        dispvm = app.add_new_vm(
            cls, template=appvm, auto_cleanup=True, **kwargs
        )

        if preload:
            dispvm.log.info("Marking preloaded qube")
            preload_dispvm = appvm.get_feat_preload()
            preload_dispvm.append(dispvm.name)
            appvm.features["preload-dispvm"] = " ".join(preload_dispvm or [])
            dispvm.features["internal"] = True
        await dispvm.create_on_disk()
        if preload:
            await dispvm.start()
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
