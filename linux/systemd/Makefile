UNITDIR ?= /usr/lib/systemd/system

all:
	true

install:
	mkdir -p $(DESTDIR)$(UNITDIR)
	cp qubes-core.service $(DESTDIR)$(UNITDIR)
	cp qubes-vm@.service $(DESTDIR)$(UNITDIR)
	cp qubes-qmemman.service $(DESTDIR)$(UNITDIR)
	cp qubesd.service $(DESTDIR)$(UNITDIR)
	cp qubes-preload-dispvm.service $(DESTDIR)$(UNITDIR)
	install -d $(DESTDIR)$(UNITDIR)/lvm2-pvscan@.service.d
	install -m 0644 lvm2-pvscan@.service.d_30_qubes.conf \
		$(DESTDIR)$(UNITDIR)/lvm2-pvscan@.service.d/30_qubes.conf
