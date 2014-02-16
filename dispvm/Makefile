CC=gcc
CFLAGS=-Wall -Wextra -Werror
all: qubes-restore xenstore-watch
qubes-restore: qubes-restore.o
	$(CC) -o qubes-restore qubes-restore.o -lxenstore

xenstore-watch: xenstore-watch.o
	$(CC) -o xenstore-watch xenstore-watch.o -lxenstore

clean:
	rm -f *.o *~ qubes-restore xenstore-watch xenfreepages

