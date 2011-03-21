CC=gcc
CFLAGS=-g -Wall -I../common
all:	qubes_penctl qubes_add_pendrive_script qvm-open-in-dvm dvm_file_editor qfile-agent-dvm qfile-agent qfile-unpacker
dvm_file_editor: dvm_file_editor.o ../common/ioall.o
	$(CC) -g -o dvm_file_editor dvm_file_editor.o ../common/ioall.o
qfile-agent-dvm: qfile-agent-dvm.o ../common/ioall.o ../common/gui-fatal.o
	$(CC) -g -o qfile-agent-dvm qfile-agent-dvm.o ../common/ioall.o ../common/gui-fatal.o 
qfile-agent: qfile-agent.o ../common/ioall.o ../common/gui-fatal.o copy_file.o
	$(CC) -g -o qfile-agent qfile-agent.o ../common/ioall.o ../common/gui-fatal.o copy_file.o
qfile-unpacker: qfile-unpacker.o ../common/ioall.o ../common/gui-fatal.o copy_file.o unpack.o
	$(CC) -g -o qfile-unpacker qfile-unpacker.o ../common/ioall.o ../common/gui-fatal.o copy_file.o unpack.o
qubes_penctl: qubes_penctl.o
	$(CC) -o qubes_penctl qubes_penctl.o -lxenstore
qubes_add_pendrive_script: qubes_add_pendrive_script.o
	$(CC) -o qubes_add_pendrive_script qubes_add_pendrive_script.o -lxenstore
qvm-open-in-dvm: qvm-open-in-dvm.o
	 $(CC) -o qvm-open-in-dvm qvm-open-in-dvm.o -lxenstore

clean:
	rm -f qfile-agent-dvm qfile-agent qfile-unpacker dvm_file_editor qubes_penctl qubes_add_pendrive_script qvm-open-in-dvm *.o *~
	rm -f xenstore-watch
