RPMS_DIR=rpm/

VERSION_DOM0 := $(shell cat version_dom0)
VERSION_VM := $(shell cat version_vm)

help:
	@echo "make rpms                  -- generate binary rpm packages"
	@echo "make update-repo-current   -- copy newly generated rpms to qubes yum repo"
	@echo "make update-repo-unstable  -- same, but to -testing repo"
	@echo "make clean                 -- cleanup"

rpms:	
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-commonvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-appvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-netvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-proxyvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-dom0.spec
	rpm --addsign \
		$(RPMS_DIR)/x86_64/qubes-core-dom0-*$(VERSION_DOM0)*.rpm \
		$(RPMS_DIR)/x86_64/qubes-core-*vm-*$(VERSION_VM)*.rpm

update-repo-current:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-*$(VERSION_DOM0)*fc13*.rpm ../yum/current-release/current/dom0/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-*vm-*$(VERSION_VM)*fc13*.rpm ../yum/current-release/current/vm/f13/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-*vm-*$(VERSION_VM)*fc14*.rpm ../yum/current-release/current/vm/f14/rpm/
	cd ../yum && ./update_repo.sh

update-repo-unstable:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-*$(VERSION_DOM0)*fc13*.rpm ../yum/current-release/unstable/dom0/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-*vm-*$(VERSION_VM)*fc13*.rpm ../yum/current-release/unstable/vm/f13/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-*vm-*$(VERSION_VM)*fc14*.rpm ../yum/current-release/unstable/vm/f14/rpm/
	cd ../yum && ./update_repo.sh

clean:
	(cd appvm && make clean)
	(cd dom0/restore && make clean)
	(cd dom0/qmemman && make clean)
	(cd common && make clean)
	make -C qrexec clean
	make -C vchan clean
