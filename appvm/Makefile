CC=gcc
CFLAGS=-Wall
all:	qubes_penctl qubes_add_pendrive_script
qubes_penctl: qubes_penctl.o
	$(CC) -o qubes_penctl qubes_penctl.o -lxenstore
qubes_add_pendrive_script: qubes_add_pendrive_script.o
	$(CC) -o qubes_add_pendrive_script qubes_add_pendrive_script.o
clean:
	rm -f qubes_penctl qubes_add_pendrive_script *.o *~
