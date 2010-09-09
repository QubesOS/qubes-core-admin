#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <xs.h>
#include <syslog.h>
#include <string.h>

unsigned long prev_used_mem;
int used_mem_change_threshold;
int delay;

char *parse(char *buf)
{
	char *ptr = buf;
	char name[256];
	static char outbuf[4096];
	int val;
	int len;
	int MemTotal=0, MemFree=0, Buffers=0, Cached=0, SwapTotal=0, SwapFree=0;
	unsigned long long key;
	long used_mem, used_mem_diff;
	int nitems = 0;

	while (nitems != 6) {
		sscanf(ptr, "%s %d kB\n%n", name, &val, &len);
		key = *(unsigned long long *) ptr;
		if (key == *(unsigned long long *) "MemTotal:") {
			MemTotal = val;
			nitems++;
		} else if (key == *(unsigned long long *) "MemFree:") {
			MemFree = val;
			nitems++;
		} else if (key == *(unsigned long long *) "Buffers:") {
			Buffers = val;
			nitems++;
		} else if (key == *(unsigned long long *) "Cached:  ") {
			Cached = val;
			nitems++;
		} else if (key == *(unsigned long long *) "SwapTotal:") {
			SwapTotal = val;
			nitems++;
		} else if (key == *(unsigned long long *) "SwapFree:") {
			SwapFree = val;
			nitems++;
		}

		ptr += len;
	}

	used_mem =
	    MemTotal - Buffers - Cached - MemFree + SwapTotal - SwapFree;
	if (used_mem < 0)
		return NULL;

	used_mem_diff = used_mem - prev_used_mem;
	prev_used_mem = used_mem;
	if (used_mem_diff < 0)
		used_mem_diff = -used_mem_diff;
	if (used_mem_diff > used_mem_change_threshold) {
		sprintf(outbuf,
			"MemTotal: %d kB\nMemFree: %d kB\nBuffers: %d kB\nCached: %d kB\n"
			"SwapTotal: %d kB\nSwapFree: %d kB\n", MemTotal,
			MemFree, Buffers, Cached, SwapTotal, SwapFree);
		return outbuf;
	}
	return NULL;
}

void usage()
{
	fprintf(stderr,
		"usage: meminfo_writer threshold_in_kb delay_in_us\n");
	exit(1);
}

void send_to_qmemman(struct xs_handle *xs, char *data)
{
	if (!xs_write(xs, XBT_NULL, "memory/meminfo", data, strlen(data))) {
		syslog(LOG_DAEMON | LOG_ERR, "error writing xenstore ?");
		exit(1);
	}
}

int
main(int argc, char **argv)
{
	char buf[4096];
	int n;
	char *meminfo_data;
	int fd;
	struct xs_handle *xs;

	if (argc != 3)
		usage();
	used_mem_change_threshold = atoi(argv[1]);
	delay = atoi(argv[2]);
	if (!used_mem_change_threshold || !delay)
		usage();

	fd = open("/proc/meminfo", O_RDONLY);
	if (fd < 0) {
		perror("open meminfo");
		exit(1);
	}
	xs = xs_domain_open();
	if (!xs) {
		perror("xs_domain_open");
		exit(1);
	}
	for (;;) {
		n = read(fd, buf, sizeof(buf));
		buf[n] = 0;
		meminfo_data = parse(buf);
		if (meminfo_data)
			send_to_qmemman(xs, meminfo_data);
		usleep(delay);
		lseek(fd, 0, SEEK_SET);
	}
}
