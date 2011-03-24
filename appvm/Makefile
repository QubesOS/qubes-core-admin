CC=gcc
CFLAGS=-g -Wall -I../common
all:	dvm_file_editor qfile-agent-dvm qfile-agent qfile-unpacker
dvm_file_editor: dvm_file_editor.o ../common/ioall.o
	$(CC) -g -o dvm_file_editor dvm_file_editor.o ../common/ioall.o
qfile-agent-dvm: qfile-agent-dvm.o ../common/ioall.o ../common/gui-fatal.o
	$(CC) -g -o qfile-agent-dvm qfile-agent-dvm.o ../common/ioall.o ../common/gui-fatal.o 
qfile-agent: qfile-agent.o ../common/ioall.o ../common/gui-fatal.o copy_file.o
	$(CC) -g -o qfile-agent qfile-agent.o ../common/ioall.o ../common/gui-fatal.o copy_file.o
qfile-unpacker: qfile-unpacker.o ../common/ioall.o ../common/gui-fatal.o copy_file.o unpack.o
	$(CC) -g -o qfile-unpacker qfile-unpacker.o ../common/ioall.o ../common/gui-fatal.o copy_file.o unpack.o

clean:
	rm -f qfile-agent-dvm qfile-agent qfile-unpacker dvm_file_editor *.o *~
