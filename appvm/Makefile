CC=gcc
CFLAGS=-g -Wall -I../common -fPIC -pie
all:	dvm_file_editor qfile-agent-dvm qfile-agent qfile-unpacker
dvm_file_editor: dvm_file_editor.o ../common/ioall.o
	$(CC) -pie -g -o $@ $^
qfile-agent-dvm: qfile-agent-dvm.o ../common/ioall.o ../common/gui-fatal.o
	$(CC) -pie -g -o $@ $^
qfile-agent: qfile-agent.o ../common/ioall.o ../common/gui-fatal.o ../common/copy_file.o ../common/crc32.o
	$(CC) -pie -g -o $@ $^
qfile-unpacker: qfile-unpacker.o ../common/ioall.o ../common/gui-fatal.o ../common/copy_file.o ../common/unpack.o ../common/crc32.o
	$(CC) -pie -g -o $@ $^

clean:
	rm -f qfile-agent-dvm qfile-agent qfile-unpacker dvm_file_editor *.o *~
