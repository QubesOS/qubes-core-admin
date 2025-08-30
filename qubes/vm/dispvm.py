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

"""A disposable vm implementation"""

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


# Keep in sync with linux/aux-tools/preload-dispvm
def get_preload_max(qube) -> int | None:
    value = qube.features.get("preload-dispvm-max", None)
    return int(value) if value else value


# Keep in sync with linux/aux-tools/preload-dispvm
def get_preload_templates(app) -> list:
    domains = app.domains
    default_dispvm = getattr(app, "default_dispvm", None)
    global_max = get_preload_max(domains["dom0"])
    appvms = [
        qube
        for qube in domains
        if (
            qube.klass == "AppVM"
            and getattr(qube, "template_for_dispvms", False)
            and (
                (qube != default_dispvm and get_preload_max(qube))
                or (
                    (qube == default_dispvm and global_max)
                    or (global_max is None and get_preload_max(qube))
                )
            )
        )
    ]
    return appvms


class DispVM(qubes.vm.qubesvm.QubesVM):
    """Disposable VM

    Preloading
    ----------
    Preloaded disposables are started in the background and kept hidden from the
    user when not in use. They are interrupted (paused or suspended, as
    appropriate) and resumed (transparently) when a disposable qube is requested
    by the user.

    **Goals**:

    - **Fast**: Usage must be always instantaneous from user perspective when
      requesting the use of disposables. Pause/suspend must be skipped if qube
      is requested before the interrupt can be performed.

    - **Easy-to-use**: Preloading requires a single qube feature
      (*preload-dispvm-max*), and its use must be transparent, indistinguishable
      from working with normal (non-preloaded) unnamed disposable qubes.

    - **Reliable**:

      - Avoid race conditions: Marking a qube as preloaded or marking the
        preloaded as used must be synchronous.

      - Recovery from failed or incomplete preload: The system must attempt to
        preload qubes even if previous preloading attempts failed due to errors,
        qubesd restart or lack of available memory, regardless of whether
        preloaded disposable qubes have been requested on this instance. If
        current qube list is invalid, it must be cleaned up before being used.

      - Avoid copy of invalid attributes: Qube operation (in particular cloning,
        renaming or creating a standalone based on a template) must not result
        in properties that are invalid on the target.

      - Full start: Preloaded disposable must only be interrupted
        (paused/suspended) or used after all basic services in it have been
        started. Failure to complete this step must remove the qube from the
        preload list.

    - **Prevents accidental tampering**:

      - Preloaded qubes have the *internal* feature set when they are created.
        This feature hides the qube from GUI tools and discourages user
        tampering. It is unset when the qube is marked as used. Remember to
        validate if all GUI applications correctly react to setting and removing
        the *internal* feature (optionally, the *is_preload* property can be
        helpful). GUI applications may react to *domain-add* before the
        *internal* feature is set and the qube entry may briefly appear on some
        GUI applications, that is a bug because features cannot be set before
        that event.

      - Preloaded qubes must be marked as used after being unpaused/resumed,
        even if it was not requested. The goal of pause/suspend in case of
        preloaded disposables is mostly detecting whether a qube was used or
        not, not managing resource consumption; thus, even with abundant system
        resources, they should not be unpaused/resumed without being requested.

    **Features and properties relationship on stages**:

    - Properties indicate the runtime stage of preloaded qubes and intentionally
      lost on qubesd restart.
    - Features indicate that a preloaded qube has reached certain stage at any
      qubesd cycle.
    - Comparing the value of certain features and properties can indicate that
      there were qubes being preloaded or requested but qubesd restarted between
      the stages, interrupting the process. The only stage that should conserve
      the preloaded qubes is a qubes that has completed preloading but has not
      been requested.

    **Stages**:

    - **Preload**: The qube is created and marked as preloaded. Qube is not
      visible in GUI applications.

      - **Startup**: Begins qube startup, start basic services in it and attempt
        to interrupt (suspend/pause).

      - **Request**: The qube is removed from the preload list. If *startup* has
        not yet reached interrupt, the latter is skipped.

    - **Used**: The qube is marked as used and may be unpaused/resumed (if
      applicable). Only in this phase, GUI applications treat the qube as any
      other unnamed disposable and the qube object is returned to the caller if
      requested.
    """

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
        self.preload_complete = asyncio.Event()

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

    @property
    def preload_requested(self):
        if not hasattr(self, "_preload_requested"):
            return None
        return self._preload_requested

    @preload_requested.setter
    def preload_requested(self, value):
        self._preload_requested = value
        self.fire_event("property-reset:is_preload", name="is_preload")

    @preload_requested.deleter
    def preload_requested(self):
        del self._preload_requested
        self.fire_event("property-reset:is_preload", name="is_preload")

    @qubes.stateless_property
    def is_preload(self) -> bool:
        """Returns True if qube is a preloaded disposable."""
        appvm = self.template
        preload_dispvm = appvm.get_feat_preload()
        if self.name in preload_dispvm or self.preload_requested:
            return True
        return False

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
        """
        Awaits for basic services to be started on preloaded domains and
        interrupts the domain if the qube has not been requested yet.
        """
        if not self.is_preload:
            return
        timeout = self.qrexec_timeout
        # https://github.com/QubesOS/qubes-issues/issues/9964
        rpc = "qubes.WaitForRunningSystem"
        path = "/run/qubes-rpc:/usr/local/etc/qubes-rpc:/etc/qubes-rpc"
        service = '$(PATH="' + path + '" command -v ' + rpc + ")"
        try:
            self.log.info(
                "Preload startup waiting '%s' with '%d' seconds timeout",
                rpc,
                timeout,
            )
            await asyncio.wait_for(
                self.run_for_stdio(
                    service,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise qubes.exc.QubesException(
                "Timed out call to '%s' after '%d' seconds during preload "
                "startup" % (service, timeout)
            )
        except (subprocess.CalledProcessError, qubes.exc.QubesException):
            raise qubes.exc.QubesException(
                "Error on call to '%s' during preload startup" % service
            )

        if not self.preload_requested:
            await self.pause()
        self.log.info("Preloading finished")
        self.features["preload-dispvm-completed"] = True
        if not self.preload_requested:
            self.features["preload-dispvm-in-progress"] = False
        self.app.save()
        self.preload_complete.set()

    @qubes.events.handler("domain-pre-paused")
    async def on_domain_pre_paused(
        self, event, **kwargs
    ):  # pylint: disable=unused-argument
        if not self.is_preload or self.maxmem == 0:
            return
        qmemman_client = None
        try:
            qmemman_client = await asyncio.get_event_loop().run_in_executor(
                None, self.set_mem
            )
        except Exception as exc:
            self.log.warning(
                "Preload memory request before pause failed: %s", str(exc)
            )
            if qmemman_client:
                qmemman_client.close()
            raise

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
        """Mark preloaded disposables as used."""
        # Qube start triggers unpause via 'libvirt_domain.resume()'.
        if self.is_preload and self.is_fully_usable():
            self.log.info("Unpaused preloaded qube will be marked as used")
            self.use_preload()

    @qubes.events.handler("domain-shutdown")
    async def on_domain_shutdown(self, _event, **_kwargs):
        """Do auto cleanup if enabled"""
        await self._auto_cleanup()

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
        The qube returned is not started unless the ``preload`` argument is
        ``True``.
        """
        if not getattr(appvm, "template_for_dispvms", False):
            raise qubes.exc.QubesException(
                "Refusing to create DispVM out of this AppVM, because "
                "template_for_dispvms=False"
            )
        app = appvm.app

        if preload and not appvm.can_preload():
            # Using an exception clutters the log when 'used' event is
            # simultaneously called.
            appvm.log.warning(
                "Failed to create preloaded disposable, limit reached"
            )
            return

        if not preload and appvm.can_preload():
            # Not necessary to await for this event as its intent is to fill
            # gaps and not relevant for this run. Delay to not affect this run.
            asyncio.ensure_future(
                appvm.fire_event_async(
                    "domain-preload-dispvm-start",
                    reason="there is a gap",
                    delay=5,
                )
            )

        if not preload and (preload_dispvm := appvm.get_feat_preload()):
            dispvm = None
            for item in preload_dispvm:
                qube = app.domains[item]
                if any(vol.is_outdated() for vol in qube.volumes.values()):
                    qube.log.warning(
                        "Requested preloaded qube but it is outdated, trying "
                        "another one if available"
                    )
                    # The gap is filled after the delay set by the
                    # 'domain-shutdown' of its ancestors. Not refilling now to
                    # deliver a disposable faster.
                    appvm.remove_preload_from_list([qube.name])
                    # Delay to not  affect this run.
                    asyncio.ensure_future(
                        qube.delay(delay=2, coros=[qube.cleanup()])
                    )
                    continue
                dispvm = qube
                break
            if dispvm:
                dispvm.log.info("Requesting preloaded qube")
                # The property "preload_requested" offloads "preload-dispvm"
                # and thus avoids various race condition:
                # - Decreasing maximum feature will not remove the qube;
                # - Another request to this function will not return the same
                #   qube.
                dispvm.features["preload-dispvm-in-progress"] = True
                appvm.remove_preload_from_list([dispvm.name])
                dispvm.preload_requested = True
                app.save()
                timeout = int(dispvm.qrexec_timeout * 1.2)
                try:
                    if not dispvm.features.get(
                        "preload-dispvm-completed", False
                    ):
                        dispvm.log.info(
                            "Waiting preload completion with '%s' seconds "
                            "timeout",
                            timeout,
                        )
                        async with asyncio.timeout(timeout):
                            await dispvm.preload_complete.wait()
                    if dispvm.is_paused():
                        await dispvm.unpause()
                    else:
                        dispvm.use_preload()
                    app.save()
                    return dispvm
                except asyncio.TimeoutError:
                    dispvm.log.warning(
                        "Requested preloaded qube but failed to finish "
                        "preloading after '%d' seconds, falling back to normal "
                        "disposable",
                        int(timeout),
                    )
                    # Delay to not affect this run.
                    asyncio.ensure_future(
                        dispvm.delay(delay=2, coros=[dispvm.cleanup()])
                    )
            else:
                appvm.log.warning(
                    "Found only outdated preloaded qube(s), falling back to "
                    "normal disposable"
                )

        dispvm = app.add_new_vm(
            cls, template=appvm, auto_cleanup=True, **kwargs
        )

        if preload:
            dispvm.log.info("Marking preloaded qube")
            dispvm.features["preload-dispvm-in-progress"] = True
            preload_dispvm = appvm.get_feat_preload()
            preload_dispvm.append(dispvm.name)
            appvm.features["preload-dispvm"] = " ".join(preload_dispvm or [])
            dispvm.features["internal"] = True
            app.save()
        await dispvm.create_on_disk()
        if preload:
            await dispvm.start()
        app.save()
        return dispvm

    def use_preload(self):
        """
        Marks preloaded DispVM as used (tainted).

        :return:
        """
        if not self.is_preload:
            raise qubes.exc.QubesException("DispVM is not preloaded")
        appvm = self.template
        if self.preload_requested:
            self.log.info("Using preloaded qube")
            if not appvm.features.get("internal", None):
                del self.features["internal"]
            self.preload_requested = None
            del self.features["preload-dispvm-in-progress"]
        else:
            # Happens when unpause/resume occurs without qube being requested.
            self.log.warning("Using a preloaded qube before requesting it")
            if not appvm.features.get("internal", None):
                del self.features["internal"]
            appvm.remove_preload_from_list([self.name])
            self.features["preload-dispvm-in-progress"] = False
        self.app.save()
        asyncio.ensure_future(
            appvm.fire_event_async("domain-preload-dispvm-used", dispvm=self)
        )

    async def _bare_cleanup(self):
        """Cleanup bare DispVM objects."""
        if self in self.app.domains:
            del self.app.domains[self]
            await self.remove_from_disk()
            self.app.save()

    def _preload_cleanup(self):
        """Cleanup preload from list"""
        if self.name in self.template.get_feat_preload():
            self.log.info("Automatic cleanup removes qube from preload list")
            self.template.remove_preload_from_list([self.name])

    async def cleanup(self):
        """Clean up after the DispVM

        This stops the disposable qube and removes it from the store.
        This method modifies :file:`qubes.xml` file.
        """
        if self not in self.app.domains:
            return
        try:
            await self.kill()
        except qubes.exc.QubesVMNotStartedError:
            pass
        # This will be done automatically if event 'domain-shutdown' is
        # triggered and 'auto_cleanup' evaluates to 'True'.
        if not self.auto_cleanup:
            self._preload_cleanup()
            if self in self.app.domains:
                await self._bare_cleanup()

    async def _auto_cleanup(self):
        """Do auto cleanup if enabled"""
        if self.auto_cleanup:
            self._preload_cleanup()
            if self in self.app.domains:
                await self._bare_cleanup()

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
            try:
                await self.kill()
            except qubes.exc.QubesVMNotStartedError:
                pass
            await self._auto_cleanup()
            raise

    def create_qdb_entries(self):
        super().create_qdb_entries()
        self.untrusted_qdb.write("/qubes-vm-persistence", "none")
