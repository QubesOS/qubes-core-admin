CC=gcc
CFLAGS=-g -Wall -I../../qubes_rpc -fPIC -pie
qfile-dom0-unpacker: qfile-dom0-unpacker.o ../../qubes_rpc/ioall.o ../../qubes_rpc/copy_file.o ../../qubes_rpc/unpack.o ../../qubes_rpc/crc32.o
	$(CC) -pie -g -o $@ $^
