CC=gcc
CFLAGS=-g -Wall -I../common -fPIC -pie
all:	vm-file-editor qopen-in-vm qfile-agent qfile-unpacker
vm-file-editor: vm-file-editor.o ../common/ioall.o
	$(CC) -pie -g -o $@ $^
qopen-in-vm: qopen-in-vm.o ../common/ioall.o ../common/gui-fatal.o
	$(CC) -pie -g -o $@ $^
qfile-agent: qfile-agent.o ../common/ioall.o ../common/gui-fatal.o ../common/copy_file.o ../common/crc32.o
	$(CC) -pie -g -o $@ $^
qfile-unpacker: qfile-unpacker.o ../common/ioall.o ../common/gui-fatal.o ../common/copy_file.o ../common/unpack.o ../common/crc32.o
	$(CC) -pie -g -o $@ $^

clean:
	rm -f qopen-in-vm qfile-agent qfile-unpacker vm-file-editor *.o *~
