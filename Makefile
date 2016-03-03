RPMS_DIR=rpm/

VERSION := $(shell cat version)

DIST_DOM0 ?= fc18

OS ?= Linux

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

clean:
	make -C dispvm clean

all:
	python setup.py build
#	make all -C tests
	# Currently supported only on xen
ifeq ($(BACKEND_VMM),xen)
	make all -C dispvm
endif

install:
ifeq ($(OS),Linux)
	$(MAKE) install -C linux/systemd
	$(MAKE) install -C linux/aux-tools
	$(MAKE) install -C linux/system-config
endif
	python setup.py install -O1 --skip-build --root $(DESTDIR)
#	$(MAKE) install -C tests
	$(MAKE) install -C relaxng
	mkdir -p $(DESTDIR)/etc/qubes
	cp etc/storage.conf $(DESTDIR)/etc/qubes/
ifeq ($(BACKEND_VMM),xen)
	# Currently supported only on xen
	cp etc/qmemman.conf $(DESTDIR)/etc/qubes/
endif
	$(MAKE) install -C dispvm
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

	mkdir -p "$(DESTDIR)$(FILESDIR)"
	cp vm-config/$(BACKEND_VMM)-vm-template.xml "$(DESTDIR)$(FILESDIR)/vm-template.xml"
	cp vm-config/$(BACKEND_VMM)-vm-template-hvm.xml "$(DESTDIR)$(FILESDIR)/vm-template-hvm.xml"

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

