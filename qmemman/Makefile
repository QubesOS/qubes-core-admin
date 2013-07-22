PYTHON_QUBESPATH = $(PYTHON_SITEPATH)/qubes
SYSCONFDIR ?= /etc
UNITDIR ?= /usr/lib/systemd/system
all:
	python -m compileall .
	python -O -m compileall .

clean:
	rm -f *.pyo 

install:
ifndef PYTHON_SITEPATH
	$(error PYTHON_SITEPATH not defined)
endif
	mkdir -p $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qmemman*py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qmemman*py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	mkdir -p $(DESTDIR)$(SYSCONFDIR)/qubes
	cp qmemman.conf $(DESTDIR)$(SYSCONFDIR)/qubes/
	mkdir -p $(DESTDIR)/usr/lib/qubes
	cp server.py $(DESTDIR)/usr/lib/qubes/qmemman_daemon.py
	mkdir -p $(DESTDIR)$(UNITDIR)
	cp qubes-qmemman.service $(DESTDIR)$(UNITDIR)

