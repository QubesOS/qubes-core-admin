RPMS_DIR=rpm/
help:
	@echo "make rpms        -- generate binary rpm packages"
	@echo "make update-repo -- copy newly generated rpms to qubes yum repo"
	@echo "make update-repo-testing -- same, but to -testing repo"

rpms:	
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-commonvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-appvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-netvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-proxyvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-dom0.spec
	rpm --addsign $(RPMS_DIR)/x86_64/*.rpm

update-repo:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-*.rpm ../yum/r1/dom0/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-appvm-*.rpm ../yum/r1/appvm/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-commonvm-*.rpm ../yum/r1/netvm/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-netvm-*.rpm ../yum/r1/netvm/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-proxyvm-*.rpm ../yum/r1/netvm/rpm/

update-repo-testing:
	ln -f $(RPMS_DIR)/x86_64/qubes-core-dom0-*.rpm ../yum/r1-testing/dom0/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-appvm-*.rpm ../yum/r1-testing/appvm/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-commonvm-*.rpm ../yum/r1-testing/netvm/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-netvm-*.rpm ../yum/r1-testing/netvm/rpm/
	ln -f $(RPMS_DIR)/x86_64/qubes-core-proxyvm-*.rpm ../yum/r1-testing/netvm/rpm/



clean:
	(cd appvm && make clean)
	(cd dom0/restore && make clean)
	(cd dom0/qmemman && make clean)
	(cd common && make clean)
	make -C qrexec clean
	make -C vchan clean
