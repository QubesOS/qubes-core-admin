BINDIR ?= /usr/bin
ifeq ($(OS),Windows_NT)
PYTHONEXEEXT = .py
endif

all:
	true

install:
	mkdir -p $(DESTDIR)$(BINDIR)
	for f in qvm-* qubes-*; do \
		cp $$f $(DESTDIR)$(BINDIR)/$$f$(PYTHONEXEEXT); \
	done

