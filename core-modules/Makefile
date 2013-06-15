PYTHON_QUBESMODPATH = $(PYTHON_SITEPATH)/qubes/modules

all:
	python -m compileall .
	python -O -m compileall .

install:
ifndef PYTHON_SITEPATH
	$(error PYTHON_SITEPATH not defined)
endif
	mkdir -p $(DESTDIR)$(PYTHON_QUBESMODPATH)
	cp 0*.py $(DESTDIR)$(PYTHON_QUBESMODPATH)
	cp 0*.py[co] $(DESTDIR)$(PYTHON_QUBESMODPATH)
	cp __init__.py $(DESTDIR)$(PYTHON_QUBESMODPATH)
	cp __init__.py[co] $(DESTDIR)$(PYTHON_QUBESMODPATH)
