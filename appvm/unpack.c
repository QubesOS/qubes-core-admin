#include <errno.h>
#include <ioall.h>
#include <fcntl.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdio.h>
#include "filecopy.h"

char namebuf[MAX_PATH_LENGTH];
void notify_progress(int p1, int p2)
{
}

int global_status_fd;
void do_exit(int code)
{
	int codebuf = code;
	write(global_status_fd, &codebuf, sizeof codebuf);
	exit(0);
}


void fix_times_and_perms(struct file_header *hdr, char *name)
{
	struct timeval times[2] =
	    { {hdr->atime, hdr->atime_nsec / 1000}, {hdr->mtime,
						     hdr->mtime_nsec / 1000}
	};
	if (chmod(name, hdr->mode & 07777))
		do_exit(errno);
	if (utimes(name, times))
		do_exit(errno);
}



void process_one_file_reg(struct file_header *hdr, char *name)
{
	char *ret;
	int fdout =
	    open(name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0700);
	if (fdout < 0)
		do_exit(errno);
	ret = copy_file(fdout, 0, hdr->filelen);
	if (ret)
		do_exit(errno);
	close(fdout);
	fix_times_and_perms(hdr, name);
}


void process_one_file_dir(struct file_header *hdr, char *name)
{
	if (mkdir(name, 0700) && errno != EEXIST)
		do_exit(errno);
	fix_times_and_perms(hdr, name);
}

void process_one_file_link(struct file_header *hdr, char *name)
{
	char content[MAX_PATH_LENGTH];
	if (hdr->filelen > MAX_PATH_LENGTH - 1)
		do_exit(ENAMETOOLONG);
	if (!read_all(0, content, hdr->filelen))
		do_exit(errno);
	content[hdr->filelen] = 0;
	if (symlink(content, name))
		do_exit(errno);

}

void process_one_file(struct file_header *hdr)
{
	if (hdr->namelen > MAX_PATH_LENGTH - 1)
		do_exit(ENAMETOOLONG);
	if (!read_all(0, namebuf, hdr->namelen))
		do_exit(errno);
	namebuf[hdr->namelen] = 0;
	if (S_ISREG(hdr->mode))
		process_one_file_reg(hdr, namebuf);
	else if (S_ISLNK(hdr->mode))
		process_one_file_link(hdr, namebuf);
	else if (S_ISDIR(hdr->mode))
		process_one_file_dir(hdr, namebuf);
	else
		do_exit(EINVAL);
}

void do_unpack(int fd)
{
	global_status_fd = fd;
	struct file_header hdr;
	while (read_all(0, &hdr, sizeof hdr))
		process_one_file(&hdr);
	if (errno)
		do_exit(errno);
	else
		do_exit(LEGAL_EOF);
}
