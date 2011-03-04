CC=gcc
CFLAGS+=-g -Wall
XENLIBS=-lvchan -lxenstore -lxenctrl

all: qrexec_daemon qrexec_agent qrexec_client
qrexec_daemon: qrexec_daemon.o unix_server.o ioall.o txrx-vchan.o buffer.o write_stdin.o
	$(CC) -g -o qrexec_daemon qrexec_daemon.o unix_server.o ioall.o txrx-vchan.o write_stdin.o buffer.o $(XENLIBS)
qrexec_agent: qrexec_agent.o ioall.o exec.o txrx-vchan.o write_stdin.o buffer.o
	$(CC) -g -o qrexec_agent qrexec_agent.o ioall.o exec.o txrx-vchan.o write_stdin.o buffer.o $(XENLIBS)
qrexec_client: qrexec_client.o ioall.o exec.o
	$(CC) -g -o qrexec_client qrexec_client.o ioall.o exec.o
clean:
	rm -f *.o *~ qrexec_daemon qrexec_agent qrexec_client
