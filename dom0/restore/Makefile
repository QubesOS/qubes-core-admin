CC=gcc
all: qubes_restore xenstore-watch
qubes_restore: qubes_restore.o
	$(CC) -o qubes_restore qubes_restore.o -lxenstore

xenstore-watch: xenstore-watch.o
	$(CC) -o xenstore-watch xenstore-watch.o -lxenstore
clean:
	rm -f *.o *~ qubes_restore xenstore-watch
