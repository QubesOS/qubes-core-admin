CC=gcc
all: qubes_restore xenstore-watch xenfreepages
qubes_restore: qubes_restore.o
	$(CC) -o qubes_restore qubes_restore.o -lxenstore

xenstore-watch: xenstore-watch.o
	$(CC) -o xenstore-watch xenstore-watch.o -lxenstore

xenfreepages: xenfreepages.o
	$(CC) -o xenfreepages xenfreepages.o -lxenctrl
	
clean:
	rm -f *.o *~ qubes_restore xenstore-watch xenfreepages

