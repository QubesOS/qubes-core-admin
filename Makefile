RPMS_DIR=rpm/

VERSION := $(shell cat version)

DIST_DOM0 ?= fc18

OS ?= Linux
PYTHON ?= python3

ADMIN_API_METHODS_SIMPLE = \
	admin.vm.List \
	admin.vmclass.List \
	admin.Events \
	admin.backup.Execute \
	admin.backup.Info \
	admin.backup.Restore \
	admin.label.Create \
	admin.label.Get \
	admin.label.List \
	admin.label.Remove \
	admin.pool.Add \
	admin.pool.Info \
	admin.pool.List \
	admin.pool.ListDrivers \
	admin.pool.Remove \
	admin.pool.volume.Info \
	admin.pool.volume.List \
	admin.pool.volume.ListSnapshots \
	admin.pool.volume.Resize \
	admin.pool.volume.Revert \
	admin.pool.volume.Snapshot \
	admin.property.Get \
	admin.property.Help \
	admin.property.HelpRst \
	admin.property.List \
	admin.property.Reset \
	admin.property.Set \
	admin.vm.Clone \
	admin.vm.Create.AppVM \
	admin.vm.Create.DispVM \
	admin.vm.Create.StandaloneVM \
	admin.vm.Create.TemplateVM \
	admin.vm.CreateInPool.AppVM \
	admin.vm.CreateInPool.DispVM \
	admin.vm.CreateInPool.StandaloneVM \
	admin.vm.CreateInPool.TemplateVM \
	admin.vm.Kill \
	admin.vm.List \
	admin.vm.Pause \
	admin.vm.Remove \
	admin.vm.Shutdown \
	admin.vm.Start \
	admin.vm.Unpause \
	admin.vm.device.pci.Attach \
	admin.vm.device.pci.Available \
	admin.vm.device.pci.Detach \
	admin.vm.device.pci.List \
	admin.vm.device.block.Attach \
	admin.vm.device.block.Available \
	admin.vm.device.block.Detach \
	admin.vm.device.block.List \
	admin.vm.device.mic.Attach \
	admin.vm.device.mic.Available \
	admin.vm.device.mic.Detach \
	admin.vm.device.mic.List \
	admin.vm.feature.CheckWithTemplate \
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
	admin.vm.property.Help \
	admin.vm.property.HelpRst \
	admin.vm.property.List \
	admin.vm.property.Reset \
	admin.vm.property.Set \
	admin.vm.tag.Get \
	admin.vm.tag.List \
	admin.vm.tag.Remove \
	admin.vm.tag.Set \
	admin.vm.volume.Info \
	admin.vm.volume.List \
	admin.vm.volume.ListSnapshots \
	admin.vm.volume.Resize \
	admin.vm.volume.Revert \
	$(null)

ADMIN_API_METHODS := $(ADMIN_API_METHODS_SIMPLE) \
	 admin.vm.volume.Import \
	 $(null)

ifeq ($(OS),Linux)
DATADIR ?= /var/lib/qubes
STATEDIR ?= /var/run/qubes
LOGDIR ?= /var/log/qubes
FILESDIR ?= /usr/share/qubes
else ifeq ($(OS),Windows_NT)
DATADIR ?= c:/qubes
STATEDIR ?= c:/qubes/state
LOGDIR ?= c:/qubes/log
FILESDIR ?= c:/program files/Invisible Things Lab/Qubes
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
	$(MAKE) -C qubes-rpc all
#	make all -C tests
	# Currently supported only on xen

install:
ifeq ($(OS),Linux)
	$(MAKE) install -C linux/systemd
	$(MAKE) install -C linux/aux-tools
	$(MAKE) install -C linux/system-config
endif
	$(PYTHON) setup.py install -O1 --skip-build --root $(DESTDIR)
	ln -s qvm-device $(DESTDIR)/usr/bin/qvm-pci
	ln -s qvm-device $(DESTDIR)/usr/bin/qvm-usb
#	$(MAKE) install -C tests
	$(MAKE) install -C relaxng
	mkdir -p $(DESTDIR)/etc/qubes
ifeq ($(BACKEND_VMM),xen)
	# Currently supported only on xen
	cp etc/qmemman.conf $(DESTDIR)/etc/qubes/
endif
	mkdir -p $(DESTDIR)/etc/qubes-rpc/policy
	mkdir -p $(DESTDIR)/usr/libexec/qubes
	cp qubes-rpc-policy/qubes.FeaturesRequest.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.FeaturesRequest
	cp qubes-rpc-policy/qubes.Filecopy.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.Filecopy
	cp qubes-rpc-policy/qubes.OpenInVM.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.OpenInVM
	cp qubes-rpc-policy/qubes.OpenURL.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.OpenURL
	cp qubes-rpc-policy/qubes.VMShell.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.VMShell
	cp qubes-rpc-policy/qubes.NotifyUpdates.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.NotifyUpdates
	cp qubes-rpc-policy/qubes.NotifyTools.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.NotifyTools
	cp qubes-rpc-policy/qubes.GetImageRGBA.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.GetImageRGBA
	cp qubes-rpc-policy/qubes.GetRandomizedTime.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.GetRandomizedTime
	cp qubes-rpc-policy/qubes.NotifyTools.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.NotifyTools
	cp qubes-rpc-policy/qubes.NotifyUpdates.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.NotifyUpdates
	cp qubes-rpc-policy/qubes.OpenInVM.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.OpenInVM
	cp qubes-rpc-policy/qubes.VMShell.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.VMShell
	cp qubes-rpc/qubes.FeaturesRequest $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.GetRandomizedTime $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.NotifyTools $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.NotifyUpdates $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes-notify-updates $(DESTDIR)/usr/libexec/qubes/
	cp qubes-rpc/qubes-notify-tools $(DESTDIR)/usr/libexec/qubes/
	install qubes-rpc/qubesd-query-fast $(DESTDIR)/usr/libexec/qubes/
	for method in $(ADMIN_API_METHODS_SIMPLE); do \
		ln -s ../../usr/libexec/qubes/qubesd-query-fast \
			$(DESTDIR)/etc/qubes-rpc/$$method; \
	done
	install qubes-rpc/admin.vm.volume.Import $(DESTDIR)/etc/qubes-rpc/
	for method in $(ADMIN_API_METHODS); do \
		install -m 0644 qubes-rpc-policy/admin-default \
			$(DESTDIR)/etc/qubes-rpc/policy/$$method; \
	done
	install -d $(DESTDIR)/etc/qubes-rpc/policy/include
	install -m 0644 qubes-rpc-policy/admin-all \
		$(DESTDIR)/etc/qubes-rpc/policy/include/

	mkdir -p "$(DESTDIR)$(FILESDIR)"
	cp -r templates "$(DESTDIR)$(FILESDIR)/templates"
	rm -f "$(DESTDIR)$(FILESDIR)/templates/README"

	mkdir -p $(DESTDIR)$(DATADIR)
	mkdir -p $(DESTDIR)$(DATADIR)/vm-templates
	mkdir -p $(DESTDIR)$(DATADIR)/appvms
	mkdir -p $(DESTDIR)$(DATADIR)/servicevms
	mkdir -p $(DESTDIR)$(DATADIR)/vm-kernels
	mkdir -p $(DESTDIR)$(DATADIR)/backup
	mkdir -p $(DESTDIR)$(DATADIR)/dvmdata
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

