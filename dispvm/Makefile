all:
	true

clean:
	true

install:
	mkdir -p $(DESTDIR)/etc/xen/scripts
	cp block.qubes $(DESTDIR)/etc/xen/scripts
	mkdir -p $(DESTDIR)/usr/bin $(DESTDIR)/usr/lib/qubes
	cp qubes-prepare-saved-domain.sh  $(DESTDIR)/usr/lib/qubes
	cp qubes-update-dispvm-savefile-with-progress.sh  $(DESTDIR)/usr/lib/qubes
	cp qfile-daemon-dvm $(DESTDIR)/usr/lib/qubes


