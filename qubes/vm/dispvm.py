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

"""
A disposable qube implementation
"""

import asyncio
import copy
import subprocess
from typing import Optional

import qubes.config
import qubes.vm.appvm
import qubes.vm.qubesvm

PRELOAD_OUTDATED_IGNORED_PROPERTIES = [
    "autostart",
    "backup_timestamp",
    "default_dispvm",
    "dispid",
    "gateway",
    "gateway6",
    "icon",
    "include_in_backups",
    "installed_by_rpm",
    "ip",
    "ip6",
    "klass",
    "name",
    "qid",
    "start_time",
    "stubdom_uuid",
    "stubdom_xid",
    "template",
    "template_for_dispvms",
    "updateable",
    "uuid",
    "visible_gateway",
    "visible_gateway6",
    "visible_ip",
    "visible_ip6",
    "xid",
]


def _setter_template(self, prop, value):
    if not getattr(value, "template_for_dispvms", False):
        raise qubes.exc.QubesPropertyValueError(
            self,
            prop,
            value,
            "template for disposable must have template_for_dispvms=True",
        )
    return value


# Keep in sync with linux/aux-tools/preload-dispvm
def get_preload_max(qube) -> int | None:
    """
    Get the ``preload-dispvm-max`` feature as an integer.

    :param qubes.vm.qubes.QubesVM qube: Qube to query the feature from.
    :rtype: int | None
    """
    value = qube.features.get("preload-dispvm-max", None)
    return int(value) if value else value


# Keep in sync with linux/aux-tools/preload-dispvm
def get_preload_templates(app) -> list:
    """
    Get all disposable templates that have the ``preload-dispvm-max`` feature
    greater than 0, either directly or indirectly by being the global
    default_dispvm and dom0 has the feature enabled.

    :param qubes.app.Qubes app: Qubes application.
    :rtype: list
    """
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
    """
    Disposable qube.

    Disposable behavior
    -------------------
    A :term:`disposable template` is a qube which has the :py:class:`AppVM
    <qubes.vm.appvm.AppVM>` class and the :py:attr:`template_for_dispvms
    <qubes.vm.mix.dvmtemplate.DVMTemplateMixin.template_for_dispvms>` property
    enabled, being a :py:class:`DVMTemplateMixin
    <qubes.vm.mix.dvmtemplate.DVMTemplateMixin>`.

    A :term:`disposable` is a qube with the :py:class:`DispVM
    <qubes.vm.dispvm.DispVM>` class and is based on a disposable template.
    Every disposable type has all of its volumes configured to disable
    :py:attr:`save_on_stop <qubes.storage.Volume.save_on_stop>`, therefore no
    changes are saved on shutdown. Unnamed disposables enables the property
    :py:attr:`auto_cleanup <qubes.vm.dispvm.DispVM.auto_cleanup>` by default,
    thus automatically removes the qube upon shutdown.

    Named disposables are useful for service qubes, as referencing static names
    is easier when the qube name is mentioned on Qrexec policies
    (:file:`qubes.UpdatesProxy` target) or as a property of another qube, such
    as a disposable :term:`net qube` which is referenced by downstream clients
    in the ``netvm`` property.

    Unnamed disposables have their names in the format :samp:`disp{1234}`,
    where :samp:`{1234}` is derived from the :py:attr:`dispid
    <qubes.vm.dispvm.DispVM.dispid>` property, a random integer ranging from 0
    to 9999 with a fail-safe mechanism to avoid reusing the same value in a
    short period.

    The system and every qube can have the :py:attr:`default_dispvm
    <qubes.vm.dispvm.DispVM.default_dispvm>` property. If the qube property is
    set to the default value, it will use the system's property.  This property
    can only have disposable template as value or an empty value.  Qubes which
    have this property set are allowed to request the creation of a disposable
    from this property. An exception to the rule is the property of
    disposables, which always default to their disposables templates to avoid
    data leaks such as using unintended network paths.

    There are some Qrexec services that which allows execution to disposables
    created from the :py:attr:`default_dispvm
    <qubes.vm.dispvm.DispVM.default_dispvm>` property when the destination qube
    of the Qrexec field uses the :doc:`@dispvm <core-qrexec:qrexec-policy>`
    tag, most commonly used to open files and URLs, (:file:`qubes.OpenInVM` and
    :file:`qubes.OpenURL`, respectively).

    Preload queue
    -------------
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
        doc="AppVM, on which this disposable is based.",
    )

    dispid = qubes.property(
        "dispid",
        type=int,
        write_once=True,
        clone=False,
        doc="Internal, persistent identifier of particular disposable.",
    )

    auto_cleanup = qubes.property(
        "auto_cleanup",
        type=bool,
        default=False,
        doc="automatically remove this qube upon shutdown",
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
        doc="Default disposable template to be used for service calls.",
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

    def __init__(self, app, xml, *args, **kwargs) -> None:
        assert isinstance(self, qubes.vm.BaseVM)
        self.volume_config = copy.deepcopy(self.default_volume_config)
        template = kwargs.get("template", None)
        self.preload_complete = asyncio.Event()
        self.preload_requested_event = asyncio.Event()

        if xml is None:
            assert template is not None

            if not getattr(template, "template_for_dispvms", False):
                raise qubes.exc.QubesValueError(
                    "template for disposable ({}) needs to be an AppVM with "
                    "template_for_dispvms=True".format(template.name)
                )

            if "dispid" not in kwargs:
                kwargs["dispid"] = app.domains.get_new_unused_dispid()
            if "name" not in kwargs:
                kwargs["name"] = "disp" + str(kwargs["dispid"])

        if template is not None:
            assert isinstance(self, qubes.vm.qubesvm.QubesVM)
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

        if xml is None and template is not None:
            assert isinstance(self, qubes.vm.qubesvm.QubesVM)
            # by default inherit properties from the disposable template
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
    def preload_requested(self) -> bool:
        """
        Check if preloaded disposable was requested and still is preloaded (not
        used yet).

        This property exists because the qube may still be a preloaded
        disposable and not be on the ``preload-dispvm`` feature of the
        disposable template. This offload is done to avoid race conditions:

        - Decreasing ``preload-dispvm-max`` feature will not remove the qube;
        - Another request to this function will not return the same qube.

        :rtype: bool
        """
        return getattr(self, "_preload_requested", False)

    @preload_requested.setter
    def preload_requested(self, value) -> None:
        self._preload_requested = value
        self.preload_requested_event.set()
        self.fire_event("property-reset:is_preload", name="is_preload")

    @preload_requested.deleter
    def preload_requested(self) -> None:
        del self._preload_requested
        self.preload_requested_event.clear()
        self.fire_event("property-reset:is_preload", name="is_preload")

    @qubes.stateless_property
    def is_preload(self) -> bool:
        """
        Check if qube is a preloaded disposable.

        :rtype: bool
        """
        appvm = self.template
        preload_dispvm = appvm.get_feat_preload()
        if self.name in preload_dispvm or self.preload_requested:
            return True
        return False

    def is_preload_outdated(self) -> dict:
        """
        Show properties that differ on disposable compared to its template.

        :rtype: dict
        """
        differed: dict[str, list] = {}
        if not self.is_preload:
            return differed

        appvm = self.template
        if self.volumes["private"].size != appvm.volumes["private"].size:
            differed["volumes_size"] = ["private"]
            return differed

        for vol_name, vol in self.volumes.items():
            if vol.is_outdated():
                differed["volumes_outdated"] = [vol_name]
                return differed

        appvm_props = appvm.property_dict()
        props = self.property_dict()
        differed_props = [
            k
            for k in props.keys() & appvm_props.keys()
            if k not in PRELOAD_OUTDATED_IGNORED_PROPERTIES
            and getattr(self, k, None) != getattr(appvm, k, None)
        ]
        if not differed_props:
            return differed
        # Not using any() cause it is nice to know the property for debugging.
        differed["properties"] = differed_props
        return differed

    @qubes.events.handler("domain-load")
    def on_domain_loaded(self, event) -> None:
        """
        When qube is loaded, assert that this qube has a template.
        """
        # pylint: disable=unused-argument
        assert self.template

    async def wait_operational_preload(
        self, rpc: str, service: str, timeout: int | float
    ) -> None:
        """
        Await for preloaded disposable to become fully operational.

        :param str rpc: Pretty RPC service name.
        :param str service: Full command-line.
        :param int|float timeout: Fail after timeout is reached.
        """
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
            self.log.info("Preload startup completed '%s'", rpc)
        except asyncio.TimeoutError:
            debug_msg = "systemd-analyze blame"
            raise qubes.exc.QubesException(
                "Timed out call to '%s' after '%d' seconds during preload "
                "startup. To debug, run the following on a new disposable of "
                "'%s': %s" % (rpc, timeout, self.template, debug_msg)
            )
        except (subprocess.CalledProcessError, qubes.exc.QubesException):
            debug_msg = "systemctl --failed"
            raise qubes.exc.QubesException(
                "Error on call to '%s' during preload startup. To debug, "
                "run the following on a new disposable of '%s': %s"
                % (rpc, self.template, debug_msg)
            )

    @qubes.events.handler("domain-start")
    async def on_domain_started_dispvm(
        self,
        event,
        **kwargs,
    ):
        # pylint: disable=unused-argument
        """
        When starting a qube, await for basic services to be started on
        preloaded disposables and interrupts the domain if the qube has not
        been requested yet.

        :param str event: Event which was fired.
        """
        if not self.is_preload:
            return
        if not self.preload_requested:
            timeout = self.qrexec_timeout
            # https://github.com/QubesOS/qubes-issues/issues/9964
            path = "/run/qubes-rpc:/usr/local/etc/qubes-rpc:/etc/qubes-rpc"
            rpcs = ["qubes.WaitForRunningSystem"]
            start_tasks = []
            for rpc in rpcs:
                service = '$(PATH="{}" command -v "{}")'.format(path, rpc)
                start_tasks.append(
                    asyncio.create_task(
                        self.wait_operational_preload(rpc, service, timeout)
                    )
                )
            break_task = asyncio.create_task(
                self.preload_requested_event.wait()
            )
            tasks = [break_task] + start_tasks
            try:
                # CI uses Python 3.12 and asynchronous iterator requires >=3.13
                # pylint: disable=not-an-iterable
                async for earliest_task in asyncio.as_completed(tasks):
                    await earliest_task
                    if earliest_task == break_task:
                        for incomplete_task in [
                            t for t in start_tasks if not t.done()
                        ]:
                            incomplete_task.cancel()
                    else:
                        if all(t.done() for t in start_tasks):
                            break_task.cancel()
            except asyncio.CancelledError:
                pass
            except ExceptionGroup as e:
                # Show detailed exception in desktop notification.
                wanted_ex_group, _ = e.split(qubes.exc.QubesException)
                if wanted_ex_group:
                    messages = [
                        "\n" + str(exc) for exc in wanted_ex_group.exceptions
                    ]
                    raise qubes.exc.QubesException("\n".join(messages))
                raise
        if not self.preload_requested:
            try:
                await self.pause()
            except qubes.exc.QubesVMCancelledPauseError:
                pass
        self.features["preload-dispvm-completed"] = True
        if not self.preload_requested:
            self.features["preload-dispvm-in-progress"] = False
            # If self.preload_requested, use_preload() saves the file.
            self.app.save()
        self.log.info("Preloading completed")
        self.preload_complete.set()

    @qubes.events.handler("domain-pre-paused")
    async def on_domain_pre_paused(self, event, **kwargs) -> None:
        """
        Before the qube is paused, if the qube is a preloaded disposable
        that has memory balancing enabled, attempt to set it's memory to its
        preferred memory configuration, which is just enough to get the qube
        working at that time.

        This helps preloaded disposables to be paused with just enough memory.

        :param str event: Event which was fired.
        """
        # pylint: disable=unused-argument
        if not self.is_preload or self.maxmem == 0:
            return
        if self.preload_requested:
            return
        qmemman_client = None
        break_task = asyncio.create_task(self.preload_requested_event.wait())
        qmemman_task = asyncio.get_event_loop().run_in_executor(
            None, self.set_mem
        )
        tasks = [break_task, qmemman_task]
        try:
            # CI uses Python 3.12 and asynchronous iterator requires >=3.13
            # pylint: disable=not-an-iterable
            async for earliest_task in asyncio.as_completed(tasks):
                await earliest_task
                if earliest_task == break_task:
                    qmemman_task.cancel()
                else:
                    break_task.cancel()
        except asyncio.CancelledError:
            if qmemman_client:
                qmemman_client.close()
        except Exception as exc:
            self.log.warning(
                "Preload memory request before pause failed: %s", str(exc)
            )
            if qmemman_client:
                qmemman_client.close()
            raise
        finally:
            if self.preload_requested:
                raise qubes.exc.QubesVMCancelledPauseError(
                    self,
                    "preload was requested before memory request completed",
                )

    @qubes.events.handler("domain-paused")
    def on_domain_paused(
        self, event, **kwargs
    ):  # pylint: disable=unused-argument
        """
        On pause, log if it is a preloaded disposable.

        :param str event: Event which was fired.
        """
        if self.is_preload:
            self.log.info("Paused preloaded qube")

    @qubes.events.handler("domain-unpaused")
    async def on_domain_unpaused(
        self, event, **kwargs
    ):  # pylint: disable=unused-argument
        """
        When qube is unpaused, mark preloaded disposables as used.

        :param str event: Event which was fired.
        """
        # Qube start triggers unpause via 'libvirt_domain.resume()'.
        if self.is_preload and self.is_fully_usable():
            self.log.info("Unpaused preloaded qube will be marked as used")
            await self.use_preload()

    @qubes.events.handler("domain-shutdown")
    async def on_domain_shutdown(self, _event, **_kwargs) -> None:
        """
        Do auto cleanup if enabled.
        """
        await self._auto_cleanup()

    @qubes.events.handler("domain-remove-from-disk")
    def on_domain_remove_from_disk(self, _event, **_kwargs) -> None:
        """
        On volume removal, remove preloaded disposable from ``preload-dispvm``
        feature in disposable template. If the feature is still here, it means
        the ``domain-shutdown`` cleanup was bypassed, possibly by improper
        shutdown, which can happen when a disposable is running, qubesd stops
        and system reboots.
        """
        self._preload_cleanup()

    @qubes.events.handler("property-pre-reset:template")
    def on_property_pre_reset_template(
        self, event, name, oldvalue=None
    ) -> None:
        """
        Forbid deleting template of qube.

        :param str event: Event which was fired.
        :param str name: Property name.
        :param qubes.vm.mix.dvmtemplate.DVMTemplateMixin oldvalue: Old value \
            of the property.
        """
        # pylint: disable=unused-argument
        raise qubes.exc.QubesValueError("Cannot unset template")

    @qubes.events.handler("property-pre-set:template")
    def on_property_pre_set_template(
        self, event, name, newvalue, oldvalue=None
    ):
        """
        Forbid changing template of running qube.

        :param str event: Event which was fired.
        :param str name: Property name.
        :param qubes.vm.mix.dvmtemplate.DVMTemplateMixin newvalue: New value \
            of the property.
        :param qubes.vm.mix.dvmtemplate.DVMTemplateMixin oldvalue: Old value \
            of the property.
        """
        # pylint: disable=unused-argument
        if not self.is_halted():
            raise qubes.exc.QubesVMNotHaltedError(
                self, "Cannot change template while qube is running"
            )

    @qubes.events.handler("property-set:template")
    def on_property_set_template(
        self, event, name, newvalue, oldvalue=None
    ) -> None:
        """
        Adjust root (and possibly other snap_on_start=True) volume on template
        change.

        :param str event: Event which was fired.
        :param str name: Property name.
        :param qubes.vm.mix.dvmtemplate.DVMTemplateMixin newvalue: New value \
            of the property.
        :param qubes.vm.mix.dvmtemplate.DVMTemplateMixin oldvalue: Old value \
            of the property.
        """
        # pylint: disable=unused-argument
        qubes.vm.appvm.template_changed_update_storage(self)

    @classmethod
    async def from_appvm(
        cls, appvm, preload=False, **kwargs
    ) -> Optional["qubes.vm.dispvm.DispVM"]:
        """
        Use a preloaded disposable if available, else fallback to creating a
        new disposable instance from given app qube.

        :param qubes.vm.appvm.AppVM appvm: template from which the qube \
            should be created
        :param bool preload: Whether to preload a disposable
        :returns: new disposable qube
        :rtype: qubes.vm.dispvm.DispVM

        *kwargs* are passed to the newly created disposable.

        >>> import qubes.vm.dispvm.DispVM
        >>> dispvm = qubes.vm.dispvm.DispVM.from_appvm(appvm).start()
        >>> dispvm.run_service('qubes.VMShell', input='firefox')
        >>> dispvm.cleanup()

        This method modifies :file:`qubes.xml` file.
        """
        if not cls.can_gen_disposable(appvm, preload=preload):
            return None

        if (
            not preload
            and (dispvm := appvm.request_preload())
            and await dispvm.get_preload()
        ):
            return dispvm

        dispvm = await cls.gen_disposable(appvm, preload=preload, **kwargs)
        return dispvm

    @classmethod
    def can_gen_disposable(cls, appvm, preload=False) -> bool:
        """
        Check if app qube can be used to generate a disposable.

        :rtype: bool
        """
        if not getattr(appvm, "template_for_dispvms", False):
            raise qubes.exc.QubesException(
                "Refusing to create disposable out of app qube which has "
                "template_for_dispvms=False"
            )
        if preload and not appvm.can_preload():
            # Using an exception clutters the log when 'used' event is
            # simultaneously called.
            appvm.log.warning(
                "Can't create more preloaded disposable as limit has been met"
            )
            return False
        return True

    @classmethod
    async def gen_disposable(
        cls, appvm, preload=False, **kwargs
    ) -> "qubes.vm.dispvm.DispVM":
        """
        Create a new disposable instance from a given app qube. If preload is
        truthy, the qube is started.

        :param qubes.vm.appvm.AppVM appvm: template from which the qube \
            should be created
        :param bool preload: Whether to preload a disposable
        :rtype: qubes.vm.dispvm.DispVM
        """
        app = appvm.app
        dispvm = app.add_new_vm(
            cls, template=appvm, auto_cleanup=True, **kwargs
        )
        if preload:
            dispvm.mark_preload()
        await dispvm.create_on_disk()
        if preload:
            await dispvm.start()
        else:
            # Start method saves the qubes.xml.
            app.save()
        return dispvm

    def mark_preload(self) -> None:
        """
        Mark disposable as a preload.
        """
        appvm = self.template
        self.log.info("Marking preloaded qube")
        self.features["preload-dispvm-in-progress"] = True
        preload_dispvm = appvm.get_feat_preload()
        preload_dispvm.append(self.name)
        appvm.features["preload-dispvm"] = " ".join(preload_dispvm or [])
        self.features["internal"] = True

    async def get_preload(self) -> bool:
        """
        Get preloaded disposable.

        :rtype: bool
        """
        timeout = int(self.qrexec_timeout * 1.2)
        try:
            if not self.features.get("preload-dispvm-completed", False):
                self.log.info(
                    "Waiting preload completion with '%s' seconds timeout",
                    timeout,
                )
                async with asyncio.timeout(timeout):
                    await self.preload_complete.wait()
            if self.is_paused():
                await self.unpause()
            else:
                await self.use_preload()
            return True
        except asyncio.TimeoutError:
            self.log.warning(
                "Requested preloaded qube but failed to finish "
                "preloading after '%d' seconds, falling back to normal "
                "disposable",
                int(timeout),
            )
            # Delay to not affect this run.
            asyncio.ensure_future(self.delay(delay=2, coros=[self.cleanup()]))
            return False

    def mark_preload_requested(self) -> None:
        """
        Mark preloaded disposable as requested.
        """
        appvm = self.template
        self.log.info("Requesting preloaded qube")
        self.features["preload-dispvm-in-progress"] = True
        appvm.remove_preload_from_list([self.name], reason="qube was requested")
        self.preload_requested = True

    async def use_preload(self) -> None:
        """
        Marks preloaded disposable as used (tainted), delete the ``internal``
        when appropriate, making GUI applications show the qube as any other
        disposable. Start the preload cycle to fill gaps.
        """
        if not self.is_preload:
            raise qubes.exc.QubesException("Disposable is not preloaded")
        appvm = self.template
        if self.preload_requested:
            self.log.info("Using preloaded qube")
            if not appvm.features.get("internal", None):
                del self.features["internal"]
            self.preload_requested = False
            await self.apply_deferred_netvm()
            del self.features["preload-dispvm-in-progress"]
        else:
            # Happens when unpause/resume occurs without qube being requested.
            self.log.warning("Using a preloaded qube before requesting it")
            if not appvm.features.get("internal", None):
                del self.features["internal"]
            appvm.remove_preload_from_list(
                [self.name], reason="qube was used without being requested"
            )
            await self.apply_deferred_netvm()
            self.features["preload-dispvm-in-progress"] = False
        self.app.save()
        delay = appvm.get_feat_preload_delay()
        if delay < 0 and appvm.get_feat_preload():
            return
        asyncio.ensure_future(
            appvm.fire_event_async(
                "domain-preload-dispvm-used", dispvm=self, delay=delay
            )
        )

    def _preload_cleanup(self) -> None:
        """
        Cleanup preload from list.
        """
        name = getattr(self, "name", None)
        template = getattr(self, "template", None)
        if not (name and template):
            # Objects from self may be absent.
            return
        if name in template.get_feat_preload():
            self.template.remove_preload_from_list(
                [self.name], reason="automatic cleanup was called"
            )
            self.template.remove_preload_from_list([self.name])

    async def _auto_cleanup(self, force: bool = False) -> None:
        """
        Do auto cleanup if enabled.

        :param bool force: Auto clean up even if property is disabled
        """
        if not self.auto_cleanup and not force:
            return
        self._preload_cleanup()
        if self not in self.app.domains:
            return
        del self.app.domains[self]
        await self.remove_from_disk()
        self.app.save()

    async def cleanup(self, force: bool = False) -> None:
        """
        Clean up after the disposable.

        This stops the disposable qube and removes it from the store.
        This method modifies :file:`qubes.xml` file.

        :param bool force: Auto clean up if property is enabled and domain \
                is not running, should be used in special circumstances only \
                as the sole purpose of this option is because using it may not \
                be reliable.
        """
        if self not in self.app.domains:
            return
        running = True
        try:
            await self.kill()
        except qubes.exc.QubesVMNotStartedError:
            running = False
        # Full cleanup will be done automatically if event 'domain-shutdown' is
        # triggered and "auto_cleanup=True".
        if not self.auto_cleanup or (
            force and not running and self.auto_cleanup
        ):
            await self._auto_cleanup(force=force)

    async def start(self, **kwargs):
        """
        Start disposable qube, but if it fails, make sure to clean it up.
        """
        # pylint: disable=arguments-differ
        try:
            # sanity check, if template_for_dispvm got changed in the meantime
            if not self.template.template_for_dispvms:
                raise qubes.exc.QubesException(
                    "template for disposable ({}) needs to have "
                    "template_for_dispvms=True".format(self.template.name)
                )
            await super().start(**kwargs)
        except:
            # Cleanup also on failed startup
            await self.cleanup()
            raise

    def create_qdb_entries(self) -> None:
        super().create_qdb_entries()
        self.untrusted_qdb.write("/qubes-vm-persistence", "none")
