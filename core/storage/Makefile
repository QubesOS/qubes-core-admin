OS ?= Linux

SYSCONFDIR ?= /etc
PYTHON_QUBESPATH = $(PYTHON_SITEPATH)/qubes

all:
	python -m compileall .
	python -O -m compileall .

install:
ifndef PYTHON_SITEPATH
	$(error PYTHON_SITEPATH not defined)
endif
	mkdir -p $(DESTDIR)$(PYTHON_QUBESPATH)/storage
	cp __init__.py $(DESTDIR)$(PYTHON_QUBESPATH)/storage
	cp __init__.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)/storage
	mkdir -p $(DESTDIR)$(SYSCONFDIR)/qubes
	cp storage.conf $(DESTDIR)$(SYSCONFDIR)/qubes/
ifneq ($(BACKEND_VMM),)
	if [ -r $(BACKEND_VMM).py ]; then \
		cp $(BACKEND_VMM).py $(DESTDIR)$(PYTHON_QUBESPATH)/storage && \
		cp $(BACKEND_VMM).py[co] $(DESTDIR)$(PYTHON_QUBESPATH)/storage; \
	fi
endif
