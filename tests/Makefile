PYTHON_TESTSPATH = $(PYTHON_SITEPATH)/qubes/tests

all:
	python -m compileall .
	python -O -m compileall .

install:
ifndef PYTHON_SITEPATH
	$(error PYTHON_SITEPATH not defined)
endif
	mkdir -p $(DESTDIR)$(PYTHON_TESTSPATH)
	cp __init__.py $(DESTDIR)$(PYTHON_TESTSPATH)
	cp __init__.py[co] $(DESTDIR)$(PYTHON_TESTSPATH)
	cp backup.py $(DESTDIR)$(PYTHON_TESTSPATH)
	cp backup.py[co] $(DESTDIR)$(PYTHON_TESTSPATH)
	cp backupcompatibility.py $(DESTDIR)$(PYTHON_TESTSPATH)
	cp backupcompatibility.py[co] $(DESTDIR)$(PYTHON_TESTSPATH)
	cp basic.py $(DESTDIR)$(PYTHON_TESTSPATH)
	cp basic.py[co] $(DESTDIR)$(PYTHON_TESTSPATH)
	cp vm_qrexec_gui.py $(DESTDIR)$(PYTHON_TESTSPATH)
	cp vm_qrexec_gui.py[co] $(DESTDIR)$(PYTHON_TESTSPATH)
