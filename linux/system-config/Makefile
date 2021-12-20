all:
	true

install:
	mkdir -p $(DESTDIR)/etc/xen/scripts
	cp block-snapshot $(DESTDIR)/etc/xen/scripts
	ln -s block-snapshot $(DESTDIR)/etc/xen/scripts/block-origin
	install -d $(DESTDIR)/etc/xdg/autostart
	install -m 0644 qrexec-policy-agent.desktop $(DESTDIR)/etc/xdg/autostart/
	install -m 0644 -D tmpfiles-qubes.conf $(DESTDIR)/usr/lib/tmpfiles.d/qubes.conf
	install -d $(DESTDIR)/etc/dbus-1/system.d
	install -m 0644 dbus-org.qubesos.PolicyAgent.conf  \
		$(DESTDIR)/etc/dbus-1/system.d/org.qubesos.PolicyAgent.conf
	install -d $(DESTDIR)/etc/logrotate.d
	install -m 0644 logrotate-qubes \
		$(DESTDIR)/etc/logrotate.d/qubes
