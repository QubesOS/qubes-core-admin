#include <sys/stat.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <ioall.h>
#include "dvm2.h"

char *get_filename()
{
	char buf[DVM_FILENAME_SIZE];
	static char retname[sizeof(buf) + sizeof("/tmp/")];
	if (!read_all(0, buf, sizeof(buf)))
		exit(1);
	if (index(buf, '/')) {
		fprintf(stderr, "filename contains /");
		exit(1);
	}
	snprintf(retname, sizeof(retname), "/tmp/%s", buf);
	return retname;
}

int copy_fd_all(int fdout, int fdin)
{
	int ret;
	char buf[4096];
	for (;;) {
		ret = read(fdin, buf, sizeof(buf));
		if (!ret)
			break;
		if (ret < 0) {
			perror("read");
			return 0;
		}
		if (!write_all(fdout, buf, ret)) {
			perror("write");
			return 0;
		}
	}
	return 1;
}


void copy_file(char *filename)
{
	int fd = open(filename, O_WRONLY | O_CREAT, 0600);
	if (fd < 0) {
		perror("open file");
		exit(1);
	}
	if (!copy_fd_all(fd, 0))
        exit(1);
	close(fd);
}

void send_file_back(char * filename)
{
	int fd = open(filename, O_RDONLY);
	if (fd < 0) {
		perror("open file");
		exit(1);
	}
	if (!copy_fd_all(1, fd))
	 exit(1);
	close(fd);
}

int
main()
{
	char cmdbuf[512];
	struct stat stat_pre, stat_post;
	char *filename = get_filename();

	copy_file(filename);
	if (stat(filename, &stat_pre)) {
		perror("stat pre");
		exit(1);
	}
	snprintf(cmdbuf, sizeof(cmdbuf),
		 "HOME=/home/user DISPLAY=:0 /usr/bin/mimeopen -n -M '%s' 2>&1 > /tmp/kde-open.log </dev/null",
		 filename);
	if (system(cmdbuf))
		system
		    ("HOME=/home/user DISPLAY=:0 /usr/bin/kdialog --sorry 'Unable to handle mimetype of the requested file!'");
	if (stat(filename, &stat_post)) {
		perror("stat post");
		exit(1);
	}
	if (stat_pre.st_mtime != stat_post.st_mtime)
		send_file_back(filename);
	return 0;
}
