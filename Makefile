RPMS_DIR=rpm/
help:
	@echo "make rpms        -- generate binary rpm packages"
	@echo "make update_repo -- copy newly generated rpms to qubes yum repo"

rpms:	
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-appvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-netvm.spec
	rpmbuild --define "_rpmdir $(RPMS_DIR)" -bb rpm_spec/core-dom0.spec
	rpm --addsign $(RPMS_DIR)/x86_64/*.rpm

update_repo:
	ln -f $(RPMS_DIR)/x86_64/*.rpm ../yum/rpm/
	(if [ -d $(RPMS_DIR)/i686 ] ; then ln -f $(RPMS_DIR)/i686/*.rpm ../yum/rpm/; fi)

clean:
	(cd appvm && make clean)
