#define _GNU_SOURCE /* For O_NOFOLLOW. */
#include <errno.h>
#include <ioall.h>
#include <fcntl.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdio.h>
#include "filecopy.h"
#include "crc32.h"

char untrusted_namebuf[MAX_PATH_LENGTH];
long long bytes_limit = 0;
long long files_limit = 0;
long long total_bytes = 0;
long long total_files = 0;

void notify_progress(int p1, int p2)
{
}

void set_size_limit(long long new_bytes_limit, long long new_files_limit)
{
	bytes_limit = new_bytes_limit;
	files_limit = new_files_limit;
}

unsigned long crc32_sum = 0;
int read_all_with_crc(int fd, void *buf, int size) {
	int ret;
	ret = read_all(fd, buf, size);
	if (ret)
		crc32_sum = Crc32_ComputeBuf(crc32_sum, buf, size);
	return ret;
}

void send_status_and_crc(int code) {
	struct result_header hdr;
	int saved_errno;

	saved_errno = errno;
	hdr.error_code = code;
	hdr.crc32 = crc32_sum;
	if (!write_all(1, &hdr, sizeof(hdr)))
		perror("write status");
	errno = saved_errno;
}

void do_exit(int code)
{
	send_status_and_crc(code);
	exit(code);
}

void fix_times_and_perms(struct file_header *untrusted_hdr,
			 char *untrusted_name)
{
	struct timeval times[2] =
	    { {untrusted_hdr->atime, untrusted_hdr->atime_nsec / 1000},
	    {untrusted_hdr->mtime,
	     untrusted_hdr->mtime_nsec / 1000}
	};
	if (chmod(untrusted_name, untrusted_hdr->mode & 07777))	/* safe because of chroot */
		do_exit(errno);
	if (utimes(untrusted_name, times))	/* as above */
		do_exit(errno);
}



void process_one_file_reg(struct file_header *untrusted_hdr,
			  char *untrusted_name)
{
	int ret;
	int fdout = open(untrusted_name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0700);	/* safe because of chroot */
	if (fdout < 0)
		do_exit(errno);
	total_bytes += untrusted_hdr->filelen;
	if (bytes_limit && total_bytes > bytes_limit)
		do_exit(EDQUOT);
	ret = copy_file(fdout, 0, untrusted_hdr->filelen, &crc32_sum);
	if (ret != COPY_FILE_OK) {
		if (ret == COPY_FILE_READ_EOF
		    || ret == COPY_FILE_READ_ERROR)
			do_exit(LEGAL_EOF);	// hopefully remote will produce error message
		else
			do_exit(errno);
	}
	close(fdout);
	fix_times_and_perms(untrusted_hdr, untrusted_name);
}


void process_one_file_dir(struct file_header *untrusted_hdr,
			  char *untrusted_name)
{
// fix perms only when the directory is sent for the second time
// it allows to transfer r.x directory contents, as we create it rwx initially
	if (!mkdir(untrusted_name, 0700))	/* safe because of chroot */
		return;
	if (errno != EEXIST)
		do_exit(errno);
	fix_times_and_perms(untrusted_hdr, untrusted_name);
}

void process_one_file_link(struct file_header *untrusted_hdr,
			   char *untrusted_name)
{
	char untrusted_content[MAX_PATH_LENGTH];
	unsigned int filelen;
	if (untrusted_hdr->filelen > MAX_PATH_LENGTH - 1)
		do_exit(ENAMETOOLONG);
	filelen = untrusted_hdr->filelen;	/* sanitized above */
	if (!read_all_with_crc(0, untrusted_content, filelen))
		do_exit(LEGAL_EOF);	// hopefully remote has produced error message
	untrusted_content[filelen] = 0;
	if (symlink(untrusted_content, untrusted_name))	/* safe because of chroot */
		do_exit(errno);

}

void process_one_file(struct file_header *untrusted_hdr)
{
	unsigned int namelen;
	if (untrusted_hdr->namelen > MAX_PATH_LENGTH - 1)
		do_exit(ENAMETOOLONG);
	namelen = untrusted_hdr->namelen;	/* sanitized above */
	if (!read_all_with_crc(0, untrusted_namebuf, namelen))
		do_exit(LEGAL_EOF);	// hopefully remote has produced error message
	untrusted_namebuf[namelen] = 0;
	if (S_ISREG(untrusted_hdr->mode))
		process_one_file_reg(untrusted_hdr, untrusted_namebuf);
	else if (S_ISLNK(untrusted_hdr->mode))
		process_one_file_link(untrusted_hdr, untrusted_namebuf);
	else if (S_ISDIR(untrusted_hdr->mode))
		process_one_file_dir(untrusted_hdr, untrusted_namebuf);
	else
		do_exit(EINVAL);
}

int do_unpack()
{
	struct file_header untrusted_hdr;
	/* initialize checksum */
	crc32_sum = 0;
	while (read_all_with_crc(0, &untrusted_hdr, sizeof untrusted_hdr)) {
		/* check for end of transfer marker */
		if (untrusted_hdr.namelen == 0) {
			errno = 0;
			break;
		}
		process_one_file(&untrusted_hdr);
		total_files++;
		if (files_limit && total_files > files_limit)
			do_exit(EDQUOT);
	}
	send_status_and_crc(errno);
	return errno;
}
