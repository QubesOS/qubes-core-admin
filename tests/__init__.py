class BackupTestsMixin(SystemTestsMixin):
    def setUp(self):
        super(BackupTestsMixin, self).setUp()
        self.error_detected = multiprocessing.Queue()
        self.verbose = False

        if self.verbose:
            print >>sys.stderr, "-> Creating backupvm"

        # TODO: allow non-default template
        self.backupvm = self.qc.add_new_vm("QubesAppVm",
            name=self.make_vm_name('backupvm'),
            template=self.qc.get_default_template())
        self.backupvm.create_on_disk(verbose=self.verbose)

        self.backupdir = os.path.join(os.environ["HOME"], "test-backup")
        if os.path.exists(self.backupdir):
            shutil.rmtree(self.backupdir)
        os.mkdir(self.backupdir)


    def tearDown(self):
        super(BackupTestsMixin, self).tearDown()
        shutil.rmtree(self.backupdir)


    def print_progress(self, progress):
        if self.verbose:
            print >> sys.stderr, "\r-> Backing up files: {0}%...".format(progress)


    def error_callback(self, message):
        self.error_detected.put(message)
        if self.verbose:
            print >> sys.stderr, "ERROR: {0}".format(message)


    def print_callback(self, msg):
        if self.verbose:
            print msg


    def fill_image(self, path, size=None, sparse=False):
        block_size = 4096

        if self.verbose:
            print >>sys.stderr, "-> Filling %s" % path
        f = open(path, 'w+')
        if size is None:
            f.seek(0, 2)
            size = f.tell()
        f.seek(0)

        for block_num in xrange(size/block_size):
            f.write('a' * block_size)
            if sparse:
                f.seek(block_size, 1)

        f.close()


    # NOTE: this was create_basic_vms
    def create_backup_vms(self):
        template=self.qc.get_default_template()

        vms = []
        vmname = self.make_vm_name('test1')
        if self.verbose:
            print >>sys.stderr, "-> Creating %s" % vmname
        testvm1 = self.qc.add_new_vm('QubesAppVm',
            name=vmname, template=template)
        testvm1.create_on_disk(verbose=self.verbose)
        vms.append(testvm1)
        self.fill_image(testvm1.private_img, 100*1024*1024)

        vmname = self.make_vm_name('testhvm1')
        if self.verbose:
            print >>sys.stderr, "-> Creating %s" % vmname
        testvm2 = self.qc.add_new_vm('QubesHVm', name=vmname)
        testvm2.create_on_disk(verbose=self.verbose)
        self.fill_image(testvm2.root_img, 1024*1024*1024, True)
        vms.append(testvm2)

        self.qc.save()

        return vms


    def make_backup(self, vms, prepare_kwargs=dict(), do_kwargs=dict(),
            target=None):
        # XXX: bakup_prepare and backup_do don't support host_collection
        self.qc.unlock_db()
        if target is None:
            target = self.backupdir
        try:
            files_to_backup = \
                qubes.backup.backup_prepare(vms,
                                      print_callback=self.print_callback,
                                      **prepare_kwargs)
        except qubes.qubes.QubesException as e:
            self.fail("QubesException during backup_prepare: %s" % str(e))

        try:
            qubes.backup.backup_do(target, files_to_backup, "qubes",
                             progress_callback=self.print_progress,
                             **do_kwargs)
        except qubes.qubes.QubesException as e:
            self.fail("QubesException during backup_do: %s" % str(e))

        self.qc.lock_db_for_writing()
        self.qc.load()


    def restore_backup(self, source=None, appvm=None, options=None):
        if source is None:
            backupfile = os.path.join(self.backupdir,
                                      sorted(os.listdir(self.backupdir))[-1])
        else:
            backupfile = source

        with self.assertNotRaises(qubes.qubes.QubesException):
            backup_info = qubes.backup.backup_restore_prepare(
                backupfile, "qubes",
                host_collection=self.qc,
                print_callback=self.print_callback,
                appvm=appvm,
                options=options or {})

        if self.verbose:
            qubes.backup.backup_restore_print_summary(backup_info)

        with self.assertNotRaises(qubes.qubes.QubesException):
            qubes.backup.backup_restore_do(
                backup_info,
                host_collection=self.qc,
                print_callback=self.print_callback if self.verbose else None,
                error_callback=self.error_callback)

        # maybe someone forgot to call .save()
        self.qc.load()

        errors = []
        while not self.error_detected.empty():
            errors.append(self.error_detected.get())
        self.assertTrue(len(errors) == 0,
                         "Error(s) detected during backup_restore_do: %s" %
                         '\n'.join(errors))
        if not appvm and not os.path.isdir(backupfile):
            os.unlink(backupfile)


    def create_sparse(self, path, size):
        f = open(path, "w")
        f.truncate(size)
        f.close()
