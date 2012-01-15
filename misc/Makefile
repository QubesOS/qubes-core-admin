CC=gcc
CFLAGS=-Wall -g -O3
all:	meminfo-writer xenstore-watch
meminfo-writer: meminfo-writer.o
	$(CC) -g -o meminfo-writer meminfo-writer.o -lxenstore
xenstore-watch: xenstore-watch.o
	$(CC) -o xenstore-watch xenstore-watch.o -lxenstore
clean:
	rm -f meminfo-writer xenstore-watch *.o *~
