CC=gcc
CFLAGS=-g -Wall -I../../common -fPIC -pie
qfile-dom0-unpacker: qfile-dom0-unpacker.o ../../common/ioall.o ../../common/gui-fatal.o ../../common/copy_file.o ../../common/unpack.o ../../common/crc32.o
	$(CC) -pie -g -o $@ $^
