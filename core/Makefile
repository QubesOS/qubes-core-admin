PYTHON_QUBESPATH = $(PYTHON_SITEPATH)/qubes

all:
	python -m compileall .
	python -O -m compileall .

install:
ifndef PYTHON_SITEPATH
	$(error PYTHON_SITEPATH not defined)
endif
	mkdir -p $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubes.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubes.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubesutils.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubesutils.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp guihelpers.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp guihelpers.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp notify.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp notify.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp backup.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp backup.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
