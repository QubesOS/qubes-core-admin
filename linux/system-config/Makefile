all:
	true

install:
	mkdir -p $(DESTDIR)/etc/xen/scripts $(DESTDIR)/usr/lib/qubes
	cp vif-route-qubes $(DESTDIR)/etc/xen/scripts
	install -m 0755 create-snapshot destroy-snapshot $(DESTDIR)/usr/lib/qubes
	install -m 0644 -D tmpfiles-qubes.conf $(DESTDIR)/usr/lib/tmpfiles.d/qubes.conf
