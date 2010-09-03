CC=gcc
CFLAGS=-Wall -g
all:	meminfo-writer
meminfo-writer: meminfo-writer.o
	$(CC) -g -o meminfo-writer meminfo-writer.o -lxenstore
clean:
	rm -f meminfo-writer *.o *~
