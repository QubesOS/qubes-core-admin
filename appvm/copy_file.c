#include <unistd.h>
#include <ioall.h>
extern void notify_progress(int, int);

char * copy_file(int outfd, int infd, long long size)
{
	char buf[4096];
	long long written = 0;
	int ret;
	int count;
	while (written < size) {
		if (size - written > sizeof(buf))
			count = sizeof buf;
		else
			count = size - written;
		ret = read(infd, buf, count);
		if (!ret)
			return("EOF while reading file");
		if (ret < 0)
			return("error reading file");
		if (!write_all(outfd, buf, ret))
			return("error writing file content");
		notify_progress(ret, 0);
		written += ret;
	}
	return NULL;
}

