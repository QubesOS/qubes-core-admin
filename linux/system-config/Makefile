all:
	true

install:
	mkdir -p $(DESTDIR)/etc/xen/scripts
	cp vif-route-qubes $(DESTDIR)/etc/xen/scripts
	cp block-snapshot $(DESTDIR)/etc/xen/scripts
	ln -s block-snapshot $(DESTDIR)/etc/xen/scripts/block-origin
	install -d $(DESTDIR)/etc/xdg/autostart
	install -m 0644 qubes-guid.desktop $(DESTDIR)/etc/xdg/autostart/
	install -m 0644 -D tmpfiles-qubes.conf $(DESTDIR)/usr/lib/tmpfiles.d/qubes.conf
