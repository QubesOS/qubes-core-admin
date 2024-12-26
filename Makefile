RPMS_DIR=rpm/

VERSION := $(file <version)

DIST_DOM0 ?= fc32

OS ?= Linux
PYTHON ?= python3

ADMIN_API_METHODS_SIMPLE = \
	admin.deviceclass.List \
	admin.vmclass.List \
	admin.Events \
	admin.backup.Execute \
	admin.backup.Info \
	admin.backup.Cancel \
	admin.label.Create \
	admin.label.Get \
	admin.label.List \
	admin.label.Index \
	admin.label.Remove \
	admin.pool.Add \
	admin.pool.Info \
	admin.pool.UsageDetails \
	admin.pool.List \
	admin.pool.ListDrivers \
	admin.pool.Remove \
	admin.pool.Set.ephemeral_volatile \
	admin.pool.Set.revisions_to_keep \
	admin.pool.volume.Info \
	admin.pool.volume.List \
	admin.pool.volume.ListSnapshots \
	admin.pool.volume.Resize \
	admin.pool.volume.Revert \
	admin.pool.volume.Set.ephemeral \
	admin.pool.volume.Set.revisions_to_keep \
	admin.pool.volume.Set.rw \
	admin.pool.volume.Snapshot \
	admin.property.Get \
	admin.property.GetAll \
	admin.property.GetDefault \
	admin.property.Help \
	admin.property.HelpRst \
	admin.property.List \
	admin.property.Reset \
	admin.property.Set \
	admin.vm.Create.AppVM \
	admin.vm.Create.DispVM \
	admin.vm.Create.StandaloneVM \
	admin.vm.Create.TemplateVM \
	admin.vm.CreateInPool.AppVM \
	admin.vm.CreateInPool.DispVM \
	admin.vm.CreateInPool.StandaloneVM \
	admin.vm.CreateInPool.TemplateVM \
	admin.vm.CreateDisposable \
	admin.vm.Kill \
	admin.vm.List \
	admin.vm.Pause \
	admin.vm.Remove \
	admin.vm.Shutdown \
	admin.vm.Start \
	admin.vm.Unpause \
	admin.vm.device.pci.Assign \
	admin.vm.device.pci.Assigned \
	admin.vm.device.pci.Attach \
	admin.vm.device.pci.Attached \
	admin.vm.device.pci.Available \
	admin.vm.device.pci.Detach \
	admin.vm.device.pci.Set.assignment \
	admin.vm.device.pci.Unassign \
	admin.vm.device.block.Assign \
	admin.vm.device.block.Assigned \
	admin.vm.device.block.Attach \
	admin.vm.device.block.Attached \
	admin.vm.device.block.Available \
	admin.vm.device.block.Detach \
	admin.vm.device.block.Set.assignment \
	admin.vm.device.block.Unassign \
	admin.vm.device.usb.Assign \
	admin.vm.device.usb.Assigned \
	admin.vm.device.usb.Attach \
	admin.vm.device.usb.Attached \
	admin.vm.device.usb.Available \
	admin.vm.device.usb.Detach \
	admin.vm.device.usb.Set.assignment \
	admin.vm.device.usb.Unassign \
	admin.vm.device.mic.Assign \
	admin.vm.device.mic.Assigned \
	admin.vm.device.mic.Attach \
	admin.vm.device.mic.Attached \
	admin.vm.device.mic.Available \
	admin.vm.device.mic.Detach \
	admin.vm.device.mic.Set.assignment \
	admin.vm.device.mic.Unassign \
	admin.vm.feature.CheckWithNetvm \
	admin.vm.feature.CheckWithTemplate \
	admin.vm.feature.CheckWithAdminVM \
	admin.vm.feature.CheckWithTemplateAndAdminVM \
	admin.vm.feature.Get \
	admin.vm.feature.List \
	admin.vm.feature.Remove \
	admin.vm.feature.Set \
	admin.vm.firewall.Flush \
	admin.vm.firewall.Get \
	admin.vm.firewall.Set \
	admin.vm.firewall.GetPolicy \
	admin.vm.firewall.SetPolicy \
	admin.vm.firewall.Reload \
	admin.vm.property.Get \
	admin.vm.property.GetAll \
	admin.vm.property.GetDefault \
	admin.vm.property.Help \
	admin.vm.property.HelpRst \
	admin.vm.property.List \
	admin.vm.property.Reset \
	admin.vm.property.Set \
	admin.vm.tag.Get \
	admin.vm.tag.List \
	admin.vm.tag.Remove \
	admin.vm.tag.Set \
	admin.vm.volume.Clear \
	admin.vm.volume.CloneFrom \
	admin.vm.volume.CloneTo \
	admin.vm.volume.Info \
	admin.vm.volume.List \
	admin.vm.volume.ListSnapshots \
	admin.vm.volume.Resize \
	admin.vm.volume.Revert \
	admin.vm.volume.Set.ephemeral \
	admin.vm.volume.Set.revisions_to_keep \
	admin.vm.volume.Set.rw \
	admin.vm.Stats \
	admin.vm.CurrentState \
	$(null)

ifeq ($(OS),Linux)
DATADIR ?= /var/lib/qubes
STATEDIR ?= /var/run/qubes
LOGDIR ?= /var/log/qubes
FILESDIR ?= /usr/share/qubes
DOCDIR ?= /usr/share/doc/qubes
else ifeq ($(OS),Windows_NT)
DATADIR ?= c:/qubes
STATEDIR ?= c:/qubes/state
LOGDIR ?= c:/qubes/log
FILESDIR ?= c:/program files/Invisible Things Lab/Qubes
DOCDIR ?= c:/qubes/doc
endif

help:
	@echo "make rpms                  -- generate binary rpm packages"
	@echo "make rpms-dom0             -- generate binary rpm packages for Dom0"
	@echo "make update-repo-current   -- copy newly generated rpms to qubes yum repo"
	@echo "make update-repo-current-testing  -- same, but to -current-testing repo"
	@echo "make update-repo-unstable  -- same, but to -testing repo"
	@echo "make update-repo-installer -- copy dom0 rpms to installer repo"
	@echo "make clean                 -- cleanup"

rpms: rpms-dom0

rpms-vm:
	@true

rpms-dom0:
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-dom0.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-dom0-doc.spec
	rpm --addsign \
		$(RPMS_DIR)/x86_64/qubes-core-dom0-$(VERSION)*.rpm \
		$(RPMS_DIR)/noarch/qubes-core-dom0-doc-$(VERSION)*rpm

all:
	$(PYTHON) setup.py build
	# Currently supported only on xen

install:
ifeq ($(OS),Linux)
	$(MAKE) install -C linux/systemd
	$(MAKE) install -C linux/aux-tools
	$(MAKE) install -C linux/system-config
endif
	$(PYTHON) setup.py install -O1 --skip-build --root $(DESTDIR)
	$(MAKE) install -C relaxng
	mkdir -p $(DESTDIR)/etc/qubes
ifeq ($(BACKEND_VMM),xen)
	# Currently supported only on xen
	cp etc/qmemman.conf $(DESTDIR)/etc/qubes/
endif
	mkdir -p $(DESTDIR)/etc/qubes-rpc
	mkdir -p $(DESTDIR)/etc/qubes/policy.d
	mkdir -p $(DESTDIR)/usr/libexec/qubes
	install -m 0644 qubes-rpc-policy/90-default.policy \
		$(DESTDIR)/etc/qubes/policy.d/90-default.policy
	install -m 0644 qubes-rpc-policy/85-admin-backup-restore.policy \
		$(DESTDIR)/etc/qubes/policy.d/85-admin-backup-restore.policy
	cp qubes-rpc/qubes.FeaturesRequest $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.GetDate $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.GetRandomizedTime $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.NotifyTools $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.NotifyUpdates $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.ConnectTCP $(DESTDIR)/etc/qubes-rpc/
	install -m 0755 qvm-tools/qubes-bug-report $(DESTDIR)/usr/bin/qubes-bug-report
	install -m 0755 qvm-tools/qubes-hcl-report $(DESTDIR)/usr/bin/qubes-hcl-report
	install -m 0755 qvm-tools/qvm-sync-clock $(DESTDIR)/usr/bin/qvm-sync-clock
	install -m 0755 qvm-tools/qvm-console-dispvm $(DESTDIR)/usr/bin/qvm-console-dispvm
	for method in $(ADMIN_API_METHODS_SIMPLE); do \
		ln -sf ../../var/run/qubesd.sock \
			$(DESTDIR)/etc/qubes-rpc/$$method || exit 1; \
	done
	install qubes-rpc/admin.vm.volume.Import $(DESTDIR)/etc/qubes-rpc/
	ln -sf admin.vm.volume.Import $(DESTDIR)/etc/qubes-rpc/admin.vm.volume.ImportWithSize
	install qubes-rpc/admin.vm.Console $(DESTDIR)/etc/qubes-rpc/
	PYTHONPATH=.:test-packages qubes-rpc-policy/generate-admin-policy \
		--dest=$(DESTDIR)/etc/qubes/policy.d/90-admin-default.policy \
		--header=qubes-rpc-policy/90-admin-default.policy.header \
		--exclude admin.vm.Create.AdminVM \
				  admin.vm.CreateInPool.AdminVM \
		          admin.vm.device.testclass.Attach \
				  admin.vm.device.testclass.Detach \
				  admin.vm.device.testclass.Assign \
				  admin.vm.device.testclass.Unassign \
				  admin.vm.device.testclass.Attached \
				  admin.vm.device.testclass.Assigned \
				  admin.vm.device.testclass.Set.assignment \
				  admin.vm.device.testclass.Available
	install -d $(DESTDIR)/etc/qubes/policy.d/include
	install -m 0644 qubes-rpc-policy/admin-local-ro \
		qubes-rpc-policy/admin-local-rwx \
		qubes-rpc-policy/admin-global-ro \
		qubes-rpc-policy/admin-global-rwx \
		$(DESTDIR)/etc/qubes/policy.d/include/

	mkdir -p "$(DESTDIR)$(FILESDIR)"
	cp -r templates "$(DESTDIR)$(FILESDIR)/templates"
	cp -r tests-data "$(DESTDIR)$(FILESDIR)/tests-data"
	rm -f "$(DESTDIR)$(FILESDIR)/templates/README"

	mkdir -p "$(DESTDIR)$(DOCDIR)"
	cp qubes/storage/callback.json.example "$(DESTDIR)$(DOCDIR)/qubes_callback.json.example"

	mkdir -p $(DESTDIR)$(DATADIR)
	mkdir -p $(DESTDIR)$(DATADIR)/vm-templates
	mkdir -p $(DESTDIR)$(DATADIR)/appvms
	mkdir -p $(DESTDIR)$(DATADIR)/vm-kernels
	mkdir -p $(DESTDIR)$(DATADIR)/backup
	mkdir -p $(DESTDIR)$(STATEDIR)
	mkdir -p $(DESTDIR)$(LOGDIR)

msi:
	rm -rf destinstdir
	mkdir -p destinstdir
	$(MAKE) install \
		DESTDIR=$(PWD)/destinstdir \
		PYTHON_SITEPATH=/site-packages \
		FILESDIR=/pfiles \
		BINDIR=/bin \
		DATADIR=/qubes \
		STATEDIR=/qubes/state \
		LOGDIR=/qubes/log
	# icons placeholder
	mkdir -p destinstdir/icons
	for i in blue gray green yellow orange black purple red; do touch destinstdir/icons/$$i.png; done
	candle -arch x64 -dversion=$(VERSION) installer.wxs
	light -b destinstdir -o core-admin.msm installer.wixobj
	rm -rf destinstdir
