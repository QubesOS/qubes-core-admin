CC=gcc
CFLAGS=-Wall
all:	qubes_penctl qubes_add_pendrive_script qvm-open-in-dvm
qubes_penctl: qubes_penctl.o
	$(CC) -o qubes_penctl qubes_penctl.o -lxenstore
qubes_add_pendrive_script: qubes_add_pendrive_script.o
	$(CC) -o qubes_add_pendrive_script qubes_add_pendrive_script.o -lxenstore
qvm-open-in-dvm: qvm-open-in-dvm.o
	 $(CC) -o qvm-open-in-dvm qvm-open-in-dvm.o -lxenstore

clean:
	rm -f qubes_penctl qubes_add_pendrive_script qvm-open-in-dvm xenstore-watch *.o *~
