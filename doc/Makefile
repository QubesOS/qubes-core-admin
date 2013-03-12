QVM_DIR=qvm-tools
QUBES_DIR=qubes-tools
PANDOC=pandoc -s -f rst -t man

QVM_DOCS=$(patsubst %.rst,%.1.gz,$(wildcard $(QVM_DIR)/*.rst))
QUBES_DOCS=$(patsubst %.rst,%.1.gz,$(wildcard $(QUBES_DIR)/*.rst))

help:
	@echo "make rst=example.rst preview	-- generate manpage preview from example.rst"
	@echo "make manpages			-- generate manpages"
	@echo "make install			-- generate manpages and copy them to /usr/share/man"

install: manpages
	mkdir -p $(DESTDIR)/usr/share/man/man1
	cp $(QVM_DOCS) $(DESTDIR)/usr/share/man/man1/
	cp $(QUBES_DOCS) $(DESTDIR)/usr/share/man/man1/

%.1: %.rst
	$(PANDOC) $< > $@

%.1.gz: %.1
	gzip -f $<

manpages: $(QVM_DOCS) $(QUBES_DOCS) $(VM_DOCS)
	
preview:	$(rst)
	pandoc -s -f rst -t man $(rst) | groff -mandoc -Tlatin1 | less -R

clean:
	rm -f $(QVM_DOCS) $(QUBES_DOCS) $(VM_DOCS)
