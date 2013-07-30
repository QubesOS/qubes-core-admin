RPMS_DIR=rpm/

VERSION := $(shell cat version)

DIST_DOM0 ?= fc18

OS ?= Linux

ifeq ($(OS),Linux)
DATADIR ?= /var/lib/qubes
STATEDIR ?= /var/run/qubes
LOGDIR ?= /var/log/qubes
else ifeq ($(OS),Windows_NT)
DATADIR ?= c:/qubes
STATEDIR ?= c:/qubes/state
LOGDIR ?= c:/qubes/log
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

clean:
	make -C dispvm clean
	make -C qmemman clean

all:
	make all -C core
	make all -C core-modules
	make all -C tests
	# Currently supported only on xen
ifeq ($(BACKEND_VMM),xen)
	make all -C qmemman
	make all -C dispvm
endif

install:
ifeq ($(OS),Linux)
	$(MAKE) install -C linux/systemd
	$(MAKE) install -C linux/aux-tools
	$(MAKE) install -C linux/system-config
endif
	$(MAKE) install -C qvm-tools
	$(MAKE) install -C core
	$(MAKE) install -C core-modules
	$(MAKE) install -C tests
ifeq ($(BACKEND_VMM),xen)
	# Currently supported only on xen
	$(MAKE) install -C qmemman
	$(MAKE) install -C dispvm
endif
	mkdir -p $(DESTDIR)/etc/qubes-rpc/policy
	mkdir -p $(DESTDIR)/usr/libexec/qubes
	cp qubes-rpc-policy/qubes.Filecopy.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.Filecopy
	cp qubes-rpc-policy/qubes.OpenInVM.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.OpenInVM
	cp qubes-rpc-policy/qubes.VMShell.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.VMShell
	cp qubes-rpc-policy/qubes.NotifyUpdates.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.NotifyUpdates
	cp qubes-rpc-policy/qubes.NotifyTools.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.NotifyTools
	cp qubes-rpc-policy/qubes.GetImageRGBA.policy $(DESTDIR)/etc/qubes-rpc/policy/qubes.GetImageRGBA
	cp qubes-rpc/qubes.NotifyUpdates $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes.NotifyTools $(DESTDIR)/etc/qubes-rpc/
	cp qubes-rpc/qubes-notify-updates $(DESTDIR)/usr/libexec/qubes/
	cp qubes-rpc/qubes-notify-tools $(DESTDIR)/usr/libexec/qubes/
	mkdir -p $(DESTDIR)/usr/share/qubes
ifeq ($(BACKEND_VMM),xen)
	cp xen-vm-config/vm-template.xml $(DESTDIR)/usr/share/qubes/xen-vm-template.xml
	cp xen-vm-config/vm-template-hvm.xml $(DESTDIR)/usr/share/qubes/
endif
	mkdir -p $(DESTDIR)$(DATADIR)
	mkdir -p $(DESTDIR)$(DATADIR)/vm-templates
	mkdir -p $(DESTDIR)$(DATADIR)/appvms
	mkdir -p $(DESTDIR)$(DATADIR)/servicevms
	mkdir -p $(DESTDIR)$(DATADIR)/vm-kernels
	mkdir -p $(DESTDIR)$(DATADIR)/backup
	mkdir -p $(DESTDIR)$(DATADIR)/dvmdata
	mkdir -p $(DESTDIR)$(STATEDIR)
	mkdir -p $(DESTDIR)$(LOGDIR)

