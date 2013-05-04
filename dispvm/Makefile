CC=gcc
CFLAGS=-Wall -Wextra -Werror
all: xenstore-watch
xenstore-watch: xenstore-watch.o
	$(CC) -o xenstore-watch xenstore-watch.o -lxenstore

clean:
	rm -f *.o *~ qubes-restore xenstore-watch xenfreepages

