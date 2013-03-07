CC=gcc
CFLAGS=-g -I. -Wall -fPIC -pie
qfile-dom0-unpacker: qfile-dom0-unpacker.o ioall.o copy_file.o unpack.o crc32.o
	$(CC) -pie -g -o $@ $^
