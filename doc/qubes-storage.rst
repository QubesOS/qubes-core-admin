:py:mod:`qubes.storage` -- Qubes data storage
=============================================

Qubes provide extensible API for domains data storage. Each domain have
multiple storage volumes, for different purposes. Each volume is provided by
some storage pool. Qubes support different storage pool drivers, and it's
possible to register additional 3rd-party drivers.

Domain's storage volumes:

 - `root` - this is where operating system is installed. The volume is
   available read-write to all domain classes. It could be made read-only for
   :py:class:`~qubes.vm.appvm.AppVM` and :py:class:`~qubes.vm.dispvm.DispVM` to
   implement an untrusted storage domain in the future, but doing so will cause
   such VMs to set up a device-mapper based copy-on-write layer that redirects
   writes to the `volatile` volume. Whose storage driver may already do CoW,
   leading to an inefficient CoW-on-CoW setup. For this reason, `root` is
   currently read-write in all cases.
 - `private` - this is where domain's data live. The volume is available
   read-write to all domain classes (including :py:class:`~qubes.vm.dispvm.DispVM`,
   but data written there is discarded on domain shutdown).
 - `volatile` - this is used for any data that do not to persist. This include
   swap, copy-on-write layer for a future read-only `root` volume etc.
 - `kernel` - domain boot files - operating system kernel, initial ramdisk,
   kernel modules etc. This volume is provided read-only and should be provided by
   a storage pool respecting :py:attr:`qubes.vm.qubesvm.QubesVM.kernel` property.

Storage pool concept
--------------------

Storage pool is responsible for managing its volumes. Qubes have defined
storage pool driver API, allowing to put domains storage in various places. By
default three drivers are provided: :py:class:`qubes.storage.file.FilePool`
(named `file`), :py:class:`qubes.storage.reflink.ReflinkPool` (named
`file-reflink`), and :py:class:`qubes.storage.lvm.ThinPool` (named `lvm_thin`).
But the API allow to implement variety of other drivers (like additionally
encrypted storage, external disk, drivers using special features of some
filesystems, etc).

Most of storage API focus on storage volumes. Each volume have at least those
properties:
 - :py:attr:`~qubes.storage.Volume.rw` - should the volume be available
   read-only or read-write to the domain
 - :py:attr:`~qubes.storage.Volume.snap_on_start` - should the domain start
   with its own state of the volume, or rather a snapshot of its template volume
   (pointed by a :py:attr:`~qubes.storage.Volume.source` property). This can be
   set to `True` only if a domain do have `template` property (AppVM and DispVM).
   If the domain's template is running already, the snapshot should be made out of
   the template's before its startup.
 - :py:attr:`~qubes.storage.Volume.save_on_stop` - should the volume state be
   saved or discarded on domain
   stop. In either case, while the domain is running, volume's current state
   should not be committed immediately. This is to allow creating snapshots of the
   volume's state from before domain start (see
   :py:attr:`~qubes.storage.Volume.snap_on_start`).
 - :py:attr:`~qubes.storage.Volume.revisions_to_keep` - number of volume
   revisions to keep. If greater than zero, at each domain stop (and if
   :py:attr:`~qubes.storage.Volume.save_on_stop` is `True`) new revision is saved
   and old ones exceeding :py:attr:`~qubes.storage.Volume.revisions_to_keep` limit
   are removed. This defaults to :py:attr:`~qubes.storage.Pool.revisions_to_keep`.
 - :py:attr:`~qubes.storage.Volume.source` - source volume for
   :py:attr:`~qubes.storage.Volume.snap_on_start` volumes
 - :py:attr:`~qubes.storage.Volume.vid` - pool specific volume identifier, must
   be unique inside given pool
 - :py:attr:`~qubes.storage.Volume.pool` - storage pool object owning this volume
 - :py:attr:`~qubes.storage.Volume.name` - name of the volume inside owning
   domain (like `root`, or `private`)
 - :py:attr:`~qubes.storage.Volume.size` - size of the volume, in bytes
 - :py:attr:`~qubes.storage.Volume.ephemeral` - whether volume is automatically
   encrypted with an ephemeral key. This can be set only on volumes that have
   both :py:attr:`~qubes.storage.Volume.snap_on_start` and
   :py:attr:`~qubes.storage.Volume.save_on_stop` set to `False` - namely,
   `volatile` volume. This property for DispVM's volatile volume is inherited
   from the template (but not for other types of VMs). For `volatile` volumes,
   this property defaults to :py:attr:`~qubes.storage.Pool.ephemeral_volatile`.

Storage pool driver may define additional properties.

Storage pool driver API
-----------------------

Storage pool driver need to implement two classes:
 - pool class - inheriting from :py:class:`qubes.storage.Pool`
 - volume class - inheriting from :py:class:`qubes.storage.Volume`

Pool class should be registered with `qubes.storage` entry_point, under the
name of storage pool driver. Volume class instances should be returned by
:py:meth:`qubes.storage.Pool.init_volume` method of pool class instance.

Methods required to be implemented by the pool class:
 - :py:meth:`~qubes.storage.Pool.init_volume` - return instance of appropriate
   volume class; this method should not alter any persistent disk state, it is
   used to instantiate both existing volumes and create new ones
 - :py:meth:`~qubes.storage.Pool.setup` - setup new storage pool
 - :py:meth:`~qubes.storage.Pool.destroy` - destroy storage pool

Methods and properties required to be implemented by the volume class:
 - :py:meth:`~qubes.storage.Volume.create` - create volume on disk
 - :py:meth:`~qubes.storage.Volume.remove` - remove volume from disk
 - :py:meth:`~qubes.storage.Volume.start` - prepare the volume for domain start;
   this include making a snapshot if
   :py:attr:`~qubes.storage.Volume.snap_on_start` is `True`
 - :py:meth:`~qubes.storage.Volume.stop` - cleanup after domain shutdown; this
   include committing changes to the volume if
   :py:attr:`~qubes.storage.Volume.save_on_stop` is `True`
 - :py:meth:`~qubes.storage.Volume.export` - return a path to be read to extract
   volume data; for complex formats, this can be a pipe (connected to some
   data-extracting process)
 - :py:meth:`~qubes.storage.Volume.export_end` - cleanup after exporting the
   data; this function is called when the path returned by
   :py:meth:`~qubes.storage.Volume.export` is not used anymore. This method
   optional - some storage drivers may not implement it if not needed.
 - :py:meth:`~qubes.storage.Volume.import_data` - return a path the data should
   be written to, to import volume data; for complex formats, this can be pipe
   (connected to some data-importing process)
 - :py:meth:`~qubes.storage.Volume.import_data_end` - finish data import
   operation (cleanup temporary files etc); this methods is called always after
   :py:meth:`~qubes.storage.Volume.import_data` regardless if operation was
   successful or not
 - :py:meth:`~qubes.storage.Volume.import_volume` - import data from another volume
 - :py:meth:`~qubes.storage.Volume.resize` - resize volume
 - :py:meth:`~qubes.storage.Volume.revert` - revert volume state to a given revision
 - :py:attr:`~qubes.storage.Volume.revisions` - collection of volume revisions (to use
   with :py:meth:`qubes.storage.Volume.revert`)
 - :py:meth:`~qubes.storage.Volume.is_dirty` - is volume properly committed
   after domain shutdown? Applies only to volumes with
   :py:attr:`~qubes.storage.Volume.save_on_stop` set to `True`
 - :py:meth:`~qubes.storage.Volume.is_outdated` - have the source volume started
   since domain startup? applies only to volumes with
   :py:attr:`~qubes.storage.Volume.snap_on_start` set to `True`
 - :py:attr:`~qubes.storage.Volume.config` - volume configuration, this should
   be enough to later reinstantiate the same volume object
 - :py:meth:`~qubes.storage.Volume.block_device` - return
   :py:class:`qubes.storage.BlockDevice` instance required to configure volume in
   libvirt

Some storage pool drivers can provide limited functionality only - for example
support only `volatile` volumes (those with
:py:attr:`~qubes.storage.Volume.snap_on_start` is `False`,
:py:attr:`~qubes.storage.Volume.save_on_stop` is `False`, and
:py:attr:`~qubes.storage.Volume.rw` is `True`). In that case, it should raise
:py:exc:`NotImplementedError` in :py:meth:`qubes.storage.Pool.init_volume` when
trying to instantiate unsupported volume.

Note that pool driver should be prepared to recover from power loss before
stopping a domain - so, if volume have
:py:attr:`~qubes.storage.Volume.save_on_stop` is `True`, and
:py:meth:`qubes.storage.Volume.stop` wasn't called, next
:py:meth:`~qubes.storage.Volume.start` should pick up previous (not committed)
state.

See specific methods documentation for details.

Module contents
---------------

.. automodule:: qubes.storage
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et
