RPMS_DIR=rpm/

VERSION := $(shell cat version)
VERSION_VAIO_FIXES := $(shell cat version_vaio_fixes)

DIST_DOM0 ?= fc18

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

rpms-dom0: rpms-vaio-fixes
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-dom0.spec
	rpm --addsign \
		$(RPMS_DIR)/x86_64/qubes-core-dom0-$(VERSION)*.rpm

rpms-vaio-fixes:
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-dom0-vaio-fixes.spec
	rpm --addsign $(RPMS_DIR)/x86_64/qubes-core-dom0-vaio-fixes-$(VERSION_VAIO_FIXES)*.rpm 

update-repo-current:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-$(VERSION)*$(DIST_DOM0)*.rpm ../yum/current-release/current/dom0/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-vaio-fixes-$(VERSION_VAIO_FIXES)*$(DIST_DOM0)*.rpm ../yum/current-release/current/dom0/rpm/

update-repo-current-testing:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-$(VERSION)*$(DIST_DOM0)*.rpm ../yum/current-release/current-testing/dom0/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-vaio-fixes-$(VERSION_VAIO_FIXES)*$(DIST_DOM0)*.rpm ../yum/current-release/current-testing/dom0/rpm/

update-repo-unstable:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-$(VERSION)*$(DIST_DOM0)*.rpm ../yum/current-release/unstable/dom0/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-vaio-fixes-$(VERSION_VAIO_FIXES)*$(DIST_DOM0)*.rpm ../yum/current-release/unstable/dom0/rpm/

update-repo-installer:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-*$(VERSION)*$(DIST_DOM0)*.rpm ../installer/yum/qubes-dom0/rpm/

clean:
	make -C misc clean
