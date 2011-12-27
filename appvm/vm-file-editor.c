#include <sys/stat.h>
#include <sys/wait.h>
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
	struct stat stat_pre, stat_post;
	char *filename = get_filename();
	int child, status, log_fd;

	copy_file(filename);
	if (stat(filename, &stat_pre)) {
		perror("stat pre");
		exit(1);
	}
	switch (child = fork()) {
		case -1:
			perror("fork");
			exit(1);
		case 0:
			close(0);
			log_fd = open("/tmp/mimeopen.log", O_CREAT | O_APPEND, 0666);
			if (log_fd == -1) {
				perror("open /tmp/mimeopen.log");
				exit(1);
			}
			dup2(log_fd, 1);
			dup2(log_fd, 2);
			close(log_fd);

			setenv("HOME", "/home/user", 1);
			setenv("DISPLAY", ":0", 1);
			execl("/usr/bin/mimeopen", "mimeopen", "-n", "-M", filename, (char*)NULL);
			perror("execl");
			exit(1);
		default:
			waitpid(child, &status, 0);
			if (status != 0) {
#ifdef USE_KDIALOG
				system
					("HOME=/home/user DISPLAY=:0 /usr/bin/kdialog --sorry 'Unable to handle mimetype of the requested file!' > /tmp/kdialog.log 2>&1 </dev/null");
#else
				system
					("HOME=/home/user DISPLAY=:0 /usr/bin/zenity --error --text 'Unable to handle mimetype of the requested file!' > /tmp/kdialog.log 2>&1 </dev/null");
#endif
			}
	}

	if (stat(filename, &stat_post)) {
		perror("stat post");
		exit(1);
	}
	if (stat_pre.st_mtime != stat_post.st_mtime)
		send_file_back(filename);
	return 0;
}
