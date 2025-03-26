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
            self.features.update(template.features)
            self.tags.update(template.tags)

    def is_preloaded(self) -> bool:
        appvm = getattr(self, "template")
        preload_dispvm = appvm.get_feat_preload()
        if not preload_dispvm:
            return False
        if self.name not in preload_dispvm:
            return False
        return True

    async def preload(self):
        """
        Preloaded DispVM.

        :return:
        """
        appvm = getattr(self, "template")
        preload_dispvm = appvm.get_feat_preload()
        if preload_dispvm:
            preload_dispvm.append(self.name)
        else:
            preload_dispvm = [self.name]
        appvm.features["preload-dispvm"] = " ".join(preload_dispvm or [])
        self.features["internal"] = True
        await self.start()

    async def use_preloaded(self):
        """
        Mark preloaded DispVM as used (tainted).

        :return:
        """
        if not self.is_preloaded():
            raise qubes.exc.QubesException("DispVM is not preloaded")
        appvm = getattr(self, "template")
        preload_dispvm = appvm.get_feat_preload().remove(self.name)
        appvm.features["preload-dispvm"] = " ".join(preload_dispvm or [])
        self.features["internal"] = False
        await appvm.fire_event_async(
            "domain-preloaded-dispvm-used", dispvm=self
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
        if not self.is_preloaded():
            return
        # TODO:
        # Marek: Test if pause isn't too early. Some services (especially:
        #   gui-agent) may still be starting.  qubes.WaitForSession service may
        #   help (ensure to use async handler to not block qubesd while waiting
        #   on it).
        # TODO:
        # Ben:
        #   Test if pause isn't too late, what if application autostarts, will
        #   it open before the qube is paused?
        # Marek:
        #   Yes, it will. Theoretically there is an "invisible" mode for
        #   gui-daemon for situation like this (it was used for very old
        #   implementation of DispVM that also kinda preloaded it). But there
        #   is no support for flipping it in runtime, gui-daemon needs to be
        #   restarted for that, so that's a broader change to use it in this
        #   version. Maybe later, I'd say it's okay to ignore this issue for
        #   now.
        # Ben:
        #   I set xterm.dekstop to autostart, tested that it autostarted first
        #   and then tested if pause isn't too late:
        #     import qubesadmin
        #     domains = qubesadmin.Qubes().domains
        #     q = domains['q']
        #     if q.run_service_for_stdio("qubes.WaitForSession"):
        #         q.pause()
        #   XTerm did not appear, and this is on a minimal qube that has no
        #   heavy service that delays the start. As soon as I did
        #   'q.unpause()', the application window appeared.
        no_gui_sleep = 15
        gui_timeout = 30
        gui = self.features.get("gui", None)
        if not gui:
            await asyncio.sleep(no_gui_sleep)
            await self.pause()
            return
        proc = None
        try:
            proc = await asyncio.wait_for(
                self.run_service_for_stdio(
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
        except (subprocess.CalledProcessError, qubes.exc.QubesException):
            raise qubes.exc.QubesException(
                "Failed to run QUBESRPC qubes.WaitForSession"
            )
        finally:
            if proc is not None:
                proc.terminate()
            await self.pause()

    @qubes.events.handler("domain-unpaused")
    def on_domain_unpaused(
        self, event, **kwargs
    ):  # pylint: disable=unused-argument
        """Mark unpaused preloaded domains as used."""
        if self.is_preloaded() and self.is_fully_usable():
            # Event domain-unpaused is triggered on every qube start by
            # 'libvirt_domain.resume()'.
            # asyncio.get_event_loop().run_until_complete(self.use_preloaded())
            # TODO: is there a better task function?
            asyncio.ensure_future(self.use_preloaded())

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
        if self.is_preloaded():
            appvm = getattr(self, "template")
            preload_dispvm = appvm.get_feat_preload().remove(self.name)
            appvm.features["preload-dispvm"] = " ".join(preload_dispvm or [])
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

        if not preload:
            preload_dispvm = appvm.get_feat_preload()
            if preload_dispvm:
                dispvm = app.domains[preload_dispvm[0]]
                # Paused preloaded disposable signals that it is ready for use.
                while True:
                    if dispvm.is_paused():
                        await dispvm.unpause()
                        app.save()
                        return dispvm
                    await asyncio.sleep(0.25)

        dispvm = app.add_new_vm(
            cls, template=appvm, auto_cleanup=True, **kwargs
        )
        await dispvm.create_on_disk()
        if preload:
            await dispvm.preload()
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
