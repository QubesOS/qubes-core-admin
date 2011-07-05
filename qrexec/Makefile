CC=gcc
CFLAGS+=-g -Wall -I../vchan -I../common -pie -fPIC
XENLIBS=-lvchan -lu2mfn -lxenstore -lxenctrl
COMMONIOALL=../common/ioall.o

all: qrexec_daemon qrexec_agent qrexec_client qrexec_client_vm
qrexec_daemon: qrexec_daemon.o unix_server.o $(COMMONIOALL) txrx-vchan.o buffer.o write_stdin.o
	$(CC) -pie -L../vchan -L../u2mfn -g -o qrexec_daemon qrexec_daemon.o unix_server.o $(COMMONIOALL) txrx-vchan.o write_stdin.o buffer.o $(XENLIBS) 
qrexec_agent: qrexec_agent.o unix_server.o exec.o txrx-vchan.o write_stdin.o buffer.o $(COMMONIOALL)
	$(CC) -pie -L../vchan -L../u2mfn -g -o qrexec_agent qrexec_agent.o unix_server.o exec.o txrx-vchan.o write_stdin.o buffer.o $(COMMONIOALL) $(XENLIBS)
qrexec_client: qrexec_client.o $(COMMONIOALL) exec.o
	$(CC) -pie -g -o qrexec_client qrexec_client.o $(COMMONIOALL) exec.o
qrexec_client_vm: qrexec_client_vm.o
	$(CC) -pie -g -o qrexec_client_vm qrexec_client_vm.o
clean:
	rm -f *.o *~ qrexec_daemon qrexec_agent qrexec_client qrexec_client_vm
