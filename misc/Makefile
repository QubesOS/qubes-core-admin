CC=gcc
CFLAGS=-Wall -g -O3
all:	meminfo-writer xenstore-watch python
meminfo-writer: meminfo-writer.o
	$(CC) -g -o meminfo-writer meminfo-writer.o -lxenstore
xenstore-watch: xenstore-watch.o
	$(CC) -o xenstore-watch xenstore-watch.o -lxenstore
python:
	python -m compileall .
	python -O -m compileall .
clean:
	rm -f meminfo-writer xenstore-watch *.o *~ *.pyc *.pyo
