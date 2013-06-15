CC=gcc
CFLAGS=-Wall -Wextra -Werror
all: xenstore-watch
xenstore-watch: xenstore-watch.o
	$(CC) -o xenstore-watch xenstore-watch.o -lxenstore

clean:
	rm -f *.o *~ qubes-restore xenstore-watch xenfreepages

install:
	mkdir -p $(DESTDIR)/etc/xen/scripts
	cp block.qubes $(DESTDIR)/etc/xen/scripts
	mkdir -p $(DESTDIR)/usr/bin $(DESTDIR)/usr/lib/qubes
	cp xenstore-watch $(DESTDIR)/usr/bin/xenstore-watch-qubes
	cp qubes-prepare-saved-domain.sh  $(DESTDIR)/usr/lib/qubes
	cp qubes-update-dispvm-savefile-with-progress.sh  $(DESTDIR)/usr/lib/qubes
	cp qfile-daemon-dvm $(DESTDIR)/usr/lib/qubes


