CC=gcc
CFLAGS+=-g -Wall -I../vchan -I../common
XENLIBS=-lvchan -lu2mfn -lxenstore -lxenctrl
COMMONIOALL=../common/ioall.o

all: qrexec_daemon qrexec_agent qrexec_client
qrexec_daemon: qrexec_daemon.o unix_server.o $(COMMONIOALL) txrx-vchan.o buffer.o write_stdin.o
	$(CC) -L../vchan -L../u2mfn -g -o qrexec_daemon qrexec_daemon.o unix_server.o $(COMMONIOALL) txrx-vchan.o write_stdin.o buffer.o $(XENLIBS) 
qrexec_agent: qrexec_agent.o exec.o txrx-vchan.o write_stdin.o buffer.o $(COMMONIOALL)
	$(CC) -L../vchan -L../u2mfn -g -o qrexec_agent qrexec_agent.o exec.o txrx-vchan.o write_stdin.o buffer.o $(COMMONIOALL) $(XENLIBS)
qrexec_client: qrexec_client.o $(COMMONIOALL) exec.o
	$(CC) -g -o qrexec_client qrexec_client.o $(COMMONIOALL) exec.o
clean:
	rm -f *.o *~ qrexec_daemon qrexec_agent qrexec_client
