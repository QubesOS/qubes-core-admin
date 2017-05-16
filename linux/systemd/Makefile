UNITDIR ?= /usr/lib/systemd/system

all:
	true

install:
	mkdir -p $(DESTDIR)$(UNITDIR)
	cp qubes-core.service $(DESTDIR)$(UNITDIR)
	cp qubes-netvm.service $(DESTDIR)$(UNITDIR)
	cp qubes-vm@.service $(DESTDIR)$(UNITDIR)
	cp qubes-reload-firewall@.service $(DESTDIR)$(UNITDIR)
	cp qubes-reload-firewall@.timer $(DESTDIR)$(UNITDIR)
	cp qubes-qmemman.service $(DESTDIR)$(UNITDIR)
	cp qubesd.service $(DESTDIR)$(UNITDIR)
